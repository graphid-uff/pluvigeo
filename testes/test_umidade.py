"""
Testes de unidade: cada regra de limpeza aplicada a dados SINTÉTICOS com o defeito
plantado. Não dependem dos seus arquivos, então valem sempre (o ruído usa semente fixa).
Se um destes falhar depois de você mexer no código, a regra mudou de comportamento.

    python -m pytest testes -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pluvigeo import umidade as lu                    # noqa: E402
from pluvigeo.constantes import MAPA_UMIDADE          # noqa: E402

RNG = np.random.default_rng(42)
COD = '3399999901G'


def umidade_base(dias=20, freq='10min'):
    """6 níveis com ruído pequeno (±0,1 p.p.) em torno de 20, 25, ..., 45 %."""
    idx = pd.date_range('2024-01-01', periods=int(dias * 24 * 6), freq=freq)
    base = np.array([20, 25, 30, 35, 40, 45], dtype=float)
    v = base + RNG.normal(0, .1, (len(idx), 6))
    return pd.DataFrame(v, index=idx, columns=lu.NIV)


def chuva_zero(u):
    """Chuva horária zero em todo o período de `u` (grade horária, mm)."""
    return pd.Series(0.0, index=pd.date_range(u.index[0].floor('h'), u.index[-1].ceil('h'), freq='h'))


def tabela_longa(u, chuva=None, cod=COD):
    """Monta a tabela padronizada de ler_dados (formato longo) a partir de u e da chuva."""
    ids = {n: i for i, n in MAPA_UMIDADE.items()}
    longa = u.rename(columns=ids).rename_axis('datahora').reset_index().melt('datahora', var_name='id_sensor',
                                                                           value_name='valor')
    if chuva is not None:
        longa = pd.concat([longa, pd.DataFrame({'datahora': chuva.index, 'id_sensor': 10, 'valor': chuva.values})])
    return longa.assign(codestacao=cod).dropna(subset=['valor'])


# ------------------------------------------------------------------------------ regras isoladas
def test_zero_e_faixa():
    u = umidade_base()
    u.iloc[100, 1:] = 0
    u.iloc[200, 0] = 75
    assert lu.flag_zero(u).iloc[100, 1:].all()
    assert lu.flag_faixa(u).iloc[200, 0]
    assert lu.flag_zero(u).values.sum() == 5 and lu.flag_faixa(u).values.sum() == 1


def test_congelado():
    u = umidade_base()
    u.iloc[1000:1000 + 6 * 30, 2] = 31.12345           # 30 h com o mesmo valor
    u.iloc[3000:3000 + 6 * 10, 3] = 35.5               # 10 h: curto demais, não marca
    f = lu.flag_congelado(u)
    assert f.iloc[1000:1180, 2].all()
    assert not f.iloc[3000:3060, 3].any()


def test_queda_simultanea_e_preserva_recessao():
    u = umidade_base()
    u.iloc[500, :] -= np.array([8, 10, 12, 14, 16, 18])   # queda elétrica em todos os níveis
    # recessão real: n1 sobe 5 p.p. e desce devagar (não pode ser marcada)
    t = np.arange(400)
    u.iloc[1500:1900, 0] += 5 * np.exp(-t / 100)
    q, s = lu.flag_quedas_iter(u)
    assert s.iloc[500]
    assert not q.iloc[1500:1900, 0].any()


def test_pico_so_sem_chuva():
    u = umidade_base()
    u.iloc[800, 0] += 6
    u.iloc[1600, 0] += 6
    pluv_h = chuva_zero(u)
    pluv_h[u.index[1600].floor('h') - pd.Timedelta('2h')] = 10       # choveu antes do 2º pico
    f = lu.flag_picos(u, pluv_h)
    assert f.iloc[800, 0] and not f.iloc[1600, 0]


def test_pico_com_falha_na_chuva_nao_e_marcado():
    # sem saber se choveu (chuva NaN), o pico não é marcado
    u = umidade_base()
    u.iloc[800, 0] += 6
    pluv_h = chuva_zero(u)
    pluv_h[u.index[800].floor('h') - pd.Timedelta('3h')] = np.nan
    assert not lu.flag_picos(u, pluv_h).iloc[800, 0]


def test_degrau_profundo_isolado():
    u = umidade_base()
    u.iloc[1200:, 5] += 4                                # n6 sobe 4 p.p. de uma vez e fica
    d = lu.acha_degraus(u, chuva_zero(u))
    assert ((d.nivel == 'n6') & (d.motivo == 'sem chuva')).any()


# ------------------------------------------------------------------------------ limpar_umidade
def _com_defeitos():
    u = umidade_base()
    u.iloc[100, 1:] = 0                                   # falha: zero
    u.iloc[500, :] -= 15                                  # falha: queda simultânea
    u.iloc[800, 0] += 6                                   # suspeita: pico sem chuva
    chuva = pd.Series(0.0, index=pd.date_range(u.index[0], u.index[-1], freq='1h'))   # pluviômetro sem chuva
    return u, tabela_longa(u, chuva)


def test_limpar_umidade_integra():
    u, dados = _com_defeitos()
    r = lu.limpar_umidade(dados, COD, acomodacao=('2024-01-01', '2024-01-02'))
    assert r.codestacao == COD
    assert r.limpo.iloc[100, 1:].isna().all() and r.limpo.iloc[500].isna().all()
    assert r.operacional['2024-01-01':'2024-01-02'].isna().all().all()
    assert r.resumo['n_zero'] == 5
    assert r.mascaras['pico'].iloc[800, 0]                # a chuva da própria estação foi usada
    assert (r.pluv_h.dropna() == 0).all() and r.pluv_h.index.freq == 'h'
    assert not hasattr(r, 'horario') and not hasattr(r, 'diario')     # hora e dia: reamostrar_umidade
    assert {'espurias_%', 'excluidas_%'} <= set(r.resumo) and not any('pct' in k for k in r.resumo)


def test_modos_de_exclusao():
    u, dados = _com_defeitos()
    padrao = lu.limpar_umidade(dados, COD)                # excluir='falhas'
    assert padrao.excluir == 'falhas'
    assert padrao.limpo.iloc[100, 1:].isna().all() and padrao.limpo.iloc[500].isna().all()
    assert padrao.limpo.iloc[800, 0] == u.iloc[800, 0]    # o pico fica, só sinalizado
    assert padrao.mascaras['pico'].iloc[800, 0] and padrao.resumo['so_sinalizadas'] >= 1
    assert 'zero' in padrao.excluidas and 'pico' not in padrao.excluidas
    assert np.isnan(lu.limpar_umidade(dados, COD, excluir='todas').limpo.iloc[800, 0])
    nada = lu.limpar_umidade(dados, COD, excluir='nenhuma')
    assert nada.limpo.equals(nada.bruto) and nada.resumo['excluidas'] == 0
    with pytest.raises(ValueError, match='excluir'):
        lu.limpar_umidade(dados, COD, excluir='certain')


def test_chuva_horaria_tratada_pode_ser_passada():
    u, _ = _com_defeitos()
    dados_sem_chuva = tabela_longa(u)                      # sem o sensor 10
    with pytest.raises(ValueError, match='sensor de chuva'):
        lu.limpar_umidade(dados_sem_chuva, COD)
    pluv_h = chuva_zero(u)
    r = lu.limpar_umidade(dados_sem_chuva, COD, pluv_h=pluv_h)
    assert r.pluv_h is pluv_h and r.mascaras['pico'].iloc[800, 0]
    choveu = pluv_h.copy()
    choveu[u.index[800].floor('h') - pd.Timedelta('2h')] = 5           # chuva antes do pico
    assert not lu.limpar_umidade(dados_sem_chuva, COD, pluv_h=choveu).mascaras['pico'].iloc[800, 0]


def test_limpar_umidade_sem_umidade_da_erro():
    dados = tabela_longa(umidade_base(dias=2))
    with pytest.raises(ValueError, match='umidade'):
        lu.limpar_umidade(dados, 'outra')
