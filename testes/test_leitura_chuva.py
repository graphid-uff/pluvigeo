"""
Testes da leitura padronizada, da chuva em grade regular e da resolução temporal, com
séries pequenas feitas à mão, de resposta conhecida. Não dependem dos seus arquivos.

    python -m pytest testes -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pluvigeo import chuva as cr               # noqa: E402
from pluvigeo import exclusao as ex            # noqa: E402
from pluvigeo import leitura as lei            # noqa: E402
from pluvigeo import resolucao as rs           # noqa: E402

AMOSTRAS = Path(__file__).parent / 'amostras'
PED = AMOSTRAS / 'PED_Cemaden_339999901A.csv'
MAPA = AMOSTRAS / 'mapa_interativo'


# ------------------------------------------------------------------------------ leitura
def test_ped_e_mapa_dao_a_mesma_tabela():
    """As amostras trazem os mesmos registros de chuva nos dois formatos."""
    ped = lei.ler_dados(PED)
    mapa = lei.ler_dados(MAPA / 'cidade_01_2024.csv')
    assert list(ped.dados.columns) == lei.COLUNAS_PADRAO == list(mapa.dados.columns)
    a = lei.chuva_por_estacao(ped.dados)['339999901A']
    b = lei.chuva_por_estacao(mapa.dados)['339999901A']
    assert a.index.equals(b.index) and np.allclose(a.values, b.values)
    assert ped.n_duplicadas == 1                        # a amostra tem 1 linha repetida
    assert set(ped.dados.id_sensor) == {10, 330}        # o PED traz também a umidade
    assert lei.ler_dados(PED, sensores=[10]).dados.id_sensor.eq(10).all()


def test_csv_compactado(tmp_path):
    """Um .csv.gz é lido direto e dá a mesma tabela do .csv; a pasta acha os dois."""
    import gzip
    import shutil
    for origem in (PED, MAPA / 'cidade_03_2014.csv'):
        with open(origem, 'rb') as f, gzip.open(tmp_path / (origem.name + '.gz'), 'wb') as g:
            shutil.copyfileobj(f, g)
    gz = lei.ler_dados(tmp_path / (PED.name + '.gz'))
    assert gz.dados.equals(lei.ler_dados(PED).dados)
    pasta = lei.ler_dados(tmp_path).dados
    assert set(pasta.codestacao) == {'339999901A', '339999902A'}       # PED e mapa, ambos .gz


def test_fuso():
    utc = lei.ler_dados(PED, fuso=0).dados
    local = lei.ler_dados(PED).dados                    # padrão: -3 h
    assert (utc.datahora - local.datahora == pd.Timedelta(hours=3)).all()
    assert utc.datahora.min() == pd.Timestamp('2024-01-10 00:00')


def test_mapa_formatos_antigos():
    """Data dd/mm/aaaa, latitude e longitude trocadas, ';' sobrando, ordem diferente de
    colunas e mês vazio (só cabeçalho)."""
    r = lei.ler_dados(MAPA, fuso=0)
    d = r.dados[r.dados.codestacao == '339999902A']
    assert d.datahora.min() == pd.Timestamp('2014-03-01 00:30:24')      # 01/03, não 03/01
    assert d.datahora.max() == pd.Timestamp('2015-06-02 01:00:00')
    est = r.estacoes.set_index('codestacao').loc['339999902A']
    assert est.latitude == pytest.approx(-22.53) and est.longitude == pytest.approx(-43.171)
    assert d.valor.sum() == pytest.approx(1.2 + 0.4 + 2.5)


def test_formatos_misturados_sem_repetir():
    r = lei.ler_dados([AMOSTRAS, MAPA], sensores=[10])
    n = r.dados.groupby('codestacao').size()
    assert n['339999901A'] == 6            # mesmos registros nos dois formatos: uma vez só
    assert set(r.estacoes.codestacao) == {'339999901A', '339999902A'}


def test_umidade_por_estacao_e_inventario():
    r = lei.ler_dados(PED)
    umid_raw = lei.umidade_por_estacao(r.dados)
    assert list(umid_raw) == ['339999901A'] and list(umid_raw['339999901A'].columns) == ['n1', 'n2', 'n3', 'n4', 'n5', 'n6']
    assert umid_raw['339999901A'].n1.tolist() == [31.5, 31.6, 33.0] and umid_raw['339999901A'].n2.isna().all()
    inv = lei.inventario_dados(r.dados, r.estacoes)
    assert 'codigo' not in inv.columns and inv.codestacao.tolist() == ['339999901A']
    linha = inv.iloc[0]
    assert linha.tem_umidade and linha.sensores == [10, 330] and linha.ids_desconhecidos == []
    assert {'municipio', 'uf', 'latitude', 'longitude'} <= set(inv.columns)        # veio de `estacoes`
    assert 'municipio' not in lei.inventario_dados(r.dados).columns                 # sem `estacoes`


# ------------------------------------------------------------------------------ grade regular
def serie(pares, dia='2024-01-01'):
    """{'00:10': 1.0, ...} -> série de chuva."""
    return pd.Series({pd.Timestamp(f'{dia} {h}'): v for h, v in pares.items()}, dtype=float)


def test_vazio_curto_vira_zero_e_falha_longa_vira_nan():
    # 00:00 -> 01:00: 5 intervalos vazios (transmissão horária normal) = não choveu
    # 01:00 -> 02:10: 6 intervalos vazios = falha longa; 02:10 é o retorno, de 30 mm: alto
    reg = cr.regularizar_chuva(serie({'00:00': 0.0, '01:00': 0.2, '02:10': 30.0, '02:20': 0.4}))
    assert len(reg) == 15
    assert (reg.loc['2024-01-01 00:10':'2024-01-01 00:50', 'chuva_mm'] == 0).all()
    falha = reg.loc['2024-01-01 01:10':'2024-01-01 02:00']
    assert falha.falha_longa.all() and falha.chuva_mm.isna().all()
    r = reg.loc['2024-01-01 02:10']
    assert r.retorno_pos_falha_longa and r.retorno_alto and r.leitura_alta
    assert not r.valido and np.isnan(r.chuva_mm)
    assert reg.loc['2024-01-01 02:20', 'chuva_mm'] == 0.4
    assert reg.valor_original.sum() == pytest.approx(30.6)      # o original fica preservado
    assert not reg.exclusao_manual.any()


def test_retorno_alto_pode_ser_so_marcado():
    s = serie({'00:00': 0.0, '01:10': 30.0, '01:20': 0.2})          # falha longa e retorno de 30 mm
    padrao = cr.regularizar_chuva(s).loc['2024-01-01 01:10']
    assert padrao.retorno_alto and not padrao.valido and np.isnan(padrao.chuva_mm)
    so_marca = cr.regularizar_chuva(s, excluir_retorno_alto=False)
    r = so_marca.loc['2024-01-01 01:10']
    assert r.retorno_alto and r.valido and r.chuva_mm == 30.0     # marcado, mas continua valendo
    assert cr.relatorio_falhas(so_marca)['n_retornos_descartados'] == 0
    assert cr.relatorio_falhas(cr.regularizar_chuva(s))['n_retornos_descartados'] == 1


def test_retorno_pequeno_e_so_marcado():
    s = serie({'00:00': 0.0, '01:10': 1.0, '01:20': 0.2})          # falha longa e retorno de 1 mm
    reg = cr.regularizar_chuva(s)
    r = reg.loc['2024-01-01 01:10']
    assert r.retorno_pos_falha_longa and not r.retorno_alto and r.valido and r.chuva_mm == 1.0
    todos = cr.regularizar_chuva(s, limiar_retorno=0)                # todo retorno é "alto"
    assert todos.loc['2024-01-01 01:10', 'retorno_alto'] and np.isnan(todos.loc['2024-01-01 01:10', 'chuva_mm'])
    assert cr.relatorio_falhas(reg)['n_retornos_descartados'] == 0


def test_regularizar_aceita_o_dicionario_inteiro():
    pluv_raw = {'3399999901A': serie({'00:00': 1.0, '00:20': 2.0}), '3399999902A': serie({'00:00': 0.0})}
    pluv_reg = cr.regularizar_chuva(pluv_raw)
    assert list(pluv_reg) == ['3399999901A', '3399999902A']
    assert pluv_reg['3399999901A'].chuva_mm.tolist() == [1.0, 0.0, 2.0]
    assert pluv_reg['3399999901A'].equals(cr.regularizar_chuva(pluv_raw['3399999901A']))


def test_valor_repetido():
    # 30 leituras horárias seguidas de 0,2 mm (ruído), depois chuva de verdade com valores variados
    idx = pd.date_range('2024-01-01', periods=30, freq='1h')
    s = pd.concat([pd.Series(0.2, index=idx),
                   pd.Series([0.4, 0.2, 0.2, 0.6, 0.0], index=pd.date_range('2024-01-02 07:00', periods=5, freq='10min'))])
    reg = cr.regularizar_chuva(s)
    ruido = reg.loc[:'2024-01-02 05:00']
    assert ruido.valor_repetido.all() and ruido.chuva_mm.isna().all() and not ruido.valido.any()
    depois = reg.loc['2024-01-02 07:00':]
    assert not depois.valor_repetido.any() and depois.chuva_mm.sum() == pytest.approx(1.4)
    r = cr.relatorio_falhas(reg)
    assert r['n_leituras_repetidas'] == 30 and r['mm_repetidos_descartados'] == 6.0
    # desligado: tudo como veio
    sem = cr.regularizar_chuva(s, filtrar_repetidos=False)
    assert not sem.valor_repetido.any() and sem.chuva_mm.sum() == pytest.approx(7.4)
    # o tamanho da sequência é parâmetro; sequência curta de garoa não é tocada
    assert not cr.regularizar_chuva(s, min_repetidos=31).valor_repetido.any()
    garoa = cr.regularizar_chuva(pd.Series(0.2, index=pd.date_range('2024-01-01', periods=11, freq='10min')))
    assert not garoa.valor_repetido.any() and garoa.chuva_mm.sum() == pytest.approx(2.2)


def test_valor_repetido_so_o_valor_escolhido():
    # 15 leituras seguidas de 0,4 mm: no padrão (0,2 mm) não são ruído; com None (qualquer valor), são
    s = pd.Series(0.4, index=pd.date_range('2024-01-01', periods=15, freq='1h'))
    assert not cr.regularizar_chuva(s).valor_repetido.any()
    assert cr.regularizar_chuva(s, valor_repetido_mm=None).valor_repetido.all()
    assert cr.regularizar_chuva(s, valor_repetido_mm=0.4).valor_repetido.all()
    # 0,2 mm intercalado com outro valor: a sequência é quebrada e nada é marcado
    alternado = pd.Series([0.2] * 8 + [0.4] + [0.2] * 8, index=pd.date_range('2024-01-01', periods=17, freq='1h'))
    assert not cr.regularizar_chuva(alternado).valor_repetido.any()


def test_limiares_sao_parametros():
    s = serie({'00:00': 0.0, '01:10': 1.0})                     # 6 vazios seguidos
    assert cr.regularizar_chuva(s).falha_longa.sum() == 6                            # padrão 5
    assert cr.regularizar_chuva(s, max_intervalos_vazios=6).falha_longa.sum() == 0
    alta = cr.regularizar_chuva(serie({'00:00': 26.0, '00:10': 12.0}), limiar_leitura_alta=10)
    assert alta.leitura_alta.all() and alta.valido.all()        # leitura alta só marca


def test_horario_fora_da_grade_e_arredondado_e_somado():
    reg = cr.regularizar_chuva(serie({'00:00:24': 1.0, '00:02:10': 0.5, '00:30:24': 2.0}))
    assert reg.chuva_mm.tolist() == [1.5, 0.0, 0.0, 2.0]


def test_acumulado_movel_so_com_janela_completa():
    idx = pd.date_range('2024-01-01', periods=24, freq='10min')
    chuva = pd.Series(1.0, index=idx)
    chuva.iloc[10] = np.nan
    pluv_reg = pd.DataFrame({'chuva_mm': chuva})
    ac = cr.acumulados(pluv_reg, janelas=('1h',))['acum_1h']
    assert ac.iloc[:5].isna().all()             # antes de completar a 1ª hora
    assert ac.iloc[5:10].eq(6).all()            # janela móvel: a cada 10 min, as últimas 6 leituras
    assert ac.iloc[10:16].isna().all()          # janelas que contêm a falha
    assert ac.iloc[16:].eq(6).all()
    tol = cr.acumulados(pluv_reg, janelas=('1h',), fracao_falha_max=0.2)['acum_1h']
    assert tol.iloc[10:16].eq(5).all()          # 1 falha em 6 tolerada: soma do que foi medido
    with pytest.raises(ValueError):
        cr.acumulados(pluv_reg, janelas=('25min',))


def test_relatorio_e_retornos():
    reg = cr.regularizar_chuva(serie({'00:00': 0.0, '01:00': 0.2, '03:00': 30.0, '03:10': 0.4}))
    ret = cr.retornos_pos_falha(reg)
    assert len(ret) == 1 and ret.valor_original.iloc[0] == 30 and ret.descartado.iloc[0]
    assert ret.duracao_falha_h.iloc[0] == pytest.approx(1.83)
    r = cr.relatorio_falhas(reg)
    assert r['n_falhas_longas'] == 1 and r['n_retornos_descartados'] == 1 and r['maximo_valido_mm'] == 0.4
    assert 'funcionamento_%' in r and 'dias_com_falha_%' in r and not any('pct' in k for k in r)


def test_percentis_internos():
    dias = pd.Series([0.0] * 90 + [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0] + [np.nan] * 5)
    p = cr._percentis(dias)
    assert set(p) == {f'p{q}_dia{s}' for q in (50, 90, 95, 99) for s in ('', '_chuvoso')}
    assert p['p50_dia'] == 0 and p['p50_dia_chuvoso'] == 5.5      # NaN fica de fora
    assert cr._percentis(dias, q=(75,), limiar_chuvoso=6)['p75_dia_chuvoso'] == 9


def test_resumo_estacao():
    idx = pd.date_range('2024-01-01', '2024-03-31 23:50', freq='10min')
    v = pd.Series(0.0, index=idx)
    v['2024-01-15 12:00'] = 20.0
    v['2024-02-10 12:00':'2024-02-10 12:50'] = 10.0       # 60 mm em 1 h
    reg = ex.excluir_periodos(cr.regularizar_chuva(v), [('2024-03-01', '2024-03-10')])   # março com ~30 % de falha
    r = cr.resumo_estacao(reg)
    assert r['max_1h'] == 60 and r['data_max_1h'] == pd.Timestamp('2024-02-10 12:50')
    assert r['leitura_max_mm'] == 20
    assert r['n_meses_completos'] == 2 and r['maximo_mensal'] == 60 and r['data_maximo_mensal'] == '2024-02'
    assert r['media_mensal'] == 40
    assert r['p99_dia_chuvoso'] == pytest.approx(59.6) and r['p50_dia'] == 0
    assert cr.resumo_estacao(reg, limiar_chuvoso=30)['p50_dia_chuvoso'] == 60    # só 10/02 conta
    # várias estações de uma vez: o dicionário inteiro dá uma tabela, uma linha por estação
    T = cr.resumo_estacao({'3399999901A': reg, '3399999902A': reg})
    assert list(T.index) == ['3399999901A', '3399999902A'] and T.loc['3399999902A', 'max_1h'] == 60
    F = cr.relatorio_falhas({'3399999901A': reg})
    assert F.loc['3399999901A', 'funcionamento_%'] == r['funcionamento_%']


# ------------------------------------------------------------------------------ resolução temporal
def _pluv_reg_dois_dias():
    """Grade de 10 min de 01/01 00:00 a 03/01 00:00, com chuva em pontos conhecidos."""
    idx = pd.date_range('2024-01-01 00:00', '2024-01-03 00:00', freq='10min')
    c = pd.Series(0.0, index=idx)
    c['2024-01-01 01:00'] = 3.0          # chuva de 00:50 a 01:00 -> hora 00, dia 01/01
    c['2024-01-01 01:30'] = 2.0          # chuva de 01:20 a 01:30 -> hora 01, dia 01/01
    c['2024-01-02 00:00'] = 7.0          # chuva de 23:50 a 00:00 -> hora 23 e dia 01/01 (não 02/01)
    c['2024-01-02 05:00':'2024-01-02 05:10'] = np.nan     # 2 intervalos em falha no dia 02/01
    return pd.DataFrame({'chuva_mm': c})


def test_reamostrar_chuva_dia_civil():
    pluv = _pluv_reg_dois_dias()
    h = rs.reamostrar_chuva(pluv, '1h')
    assert h.loc['2024-01-01 00:00', 'chuva_mm'] == 3 and h.loc['2024-01-01 01:00', 'chuva_mm'] == 2
    assert h.loc['2024-01-01 23:00', 'chuva_mm'] == 7
    assert h.n_esperados.eq(6).all()
    assert np.isnan(h.loc['2024-01-02 04:00', 'chuva_mm']) and np.isnan(h.loc['2024-01-02 05:00', 'chuva_mm'])
    # o 1º registro (01/01 00:00) é chuva de 31/12: o período anterior sai incompleto e inválido
    assert h.iloc[0].incompleto and not h.iloc[0].valido and h.index[0] == pd.Timestamp('2023-12-31 23:00')

    d = rs.reamostrar_chuva(pluv, '1D')
    assert d.loc['2024-01-01', 'chuva_mm'] == 12 and not d.loc['2024-01-01', 'incompleto']
    assert np.isnan(d.loc['2024-01-02', 'chuva_mm']) and d.loc['2024-01-02', 'incompleto']
    tol = rs.reamostrar_chuva(pluv, '1D', fracao_falha_max=0.05)          # 2 de 144 = 1,4 %
    assert tol.loc['2024-01-02', 'chuva_mm'] == 0
    assert tol.loc['2024-01-02', 'valido'] and tol.loc['2024-01-02', 'incompleto']   # vale, mas avisa
    assert rs.reamostrar_chuva(pluv, 'MS').loc['2024-01-01', 'n_esperados'] == 31 * 144


def test_reamostrar_chuva_inicio_dia():
    pluv = _pluv_reg_dois_dias()
    d9 = rs.reamostrar_chuva(pluv, '1D', fracao_falha_max=0.05, inicio_dia=9)
    # o "dia" 01/01 vai de 01/01 09:00 a 02/01 09:00 e tem só os 7 mm da meia-noite
    assert d9.loc['2024-01-01 09:00', 'chuva_mm'] == 7
    assert d9.loc['2023-12-31 09:00', 'incompleto'] and np.isnan(d9.loc['2023-12-31 09:00', 'chuva_mm'])
    assert rs.reamostrar_chuva(pluv, '1D', fracao_falha_max=1, inicio_dia=9).loc['2023-12-31 09:00', 'chuva_mm'] == 5


def test_reamostrar_umidade():
    idx = pd.date_range('2024-01-01', periods=12, freq='10min')          # 2 horas
    u = pd.DataFrame({'n1': np.r_[np.full(6, 20.0), [30, 30, 30, 30, 30, 90]], 'n2': 40.0}, index=idx)
    u.iloc[1:6, 1] = np.nan                                               # n2: 1 leitura na 1ª hora
    h = rs.reamostrar_umidade(u, '1h')
    assert h.n1.tolist() == [20, 40] and h.n2.tolist() == [40, 40] and not h.incompleto.any()
    assert rs.reamostrar_umidade(u, '1h', agregacao='mediana').n1.tolist() == [20, 30]
    assert np.isnan(rs.reamostrar_umidade(u, '1h', min_leituras=3).n2.iloc[0])
    with pytest.raises(ValueError):
        rs.reamostrar_umidade(u, '1h', agregacao='moda')


def test_reamostrar_umidade_incompleto_e_inicio_dia():
    idx = pd.date_range('2024-01-01 00:00', '2024-01-02 23:00', freq='1h')
    u = pd.DataFrame({'n1': np.where(idx < pd.Timestamp('2024-01-01 09:00'), 10.0, 20.0)}, index=idx)
    u = u.drop(pd.Timestamp('2024-01-02 05:00'))                         # uma hora sem leitura no dia 02
    d = rs.reamostrar_umidade(u, '1D')
    assert d.incompleto.tolist() == [False, True]
    assert d.n1.iloc[1] == 20                                            # média do que há
    d9 = rs.reamostrar_umidade(u, '1D', inicio_dia=9)
    assert d9.loc['2024-01-01 09:00', 'n1'] == 20                       # 09:00 de 01/01 a 09:00 de 02/01
    assert d9.loc['2023-12-31 09:00', 'n1'] == 10 and d9.loc['2023-12-31 09:00', 'incompleto']
    # a saída pode voltar a entrar (horária -> diária): a coluna incompleto é ignorada
    assert rs.reamostrar_umidade(rs.reamostrar_umidade(u, '1h'), '1D').n1.tolist() == d.n1.tolist()
