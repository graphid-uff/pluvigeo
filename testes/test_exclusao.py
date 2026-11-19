"""
Testes da exclusão manual (exclusao.excluir_periodos), a mesma função para a chuva e para a
umidade. Dados sintéticos, de resposta conhecida.

    python -m pytest testes -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pluvigeo import chuva as cr                      # noqa: E402
from pluvigeo import exclusao as ex                   # noqa: E402
from pluvigeo import umidade as lu                    # noqa: E402
from test_umidade import COD, chuva_zero, tabela_longa, umidade_base   # noqa: E402


# ------------------------------------------------------------------------------ chuva
def _pluv_reg():
    idx = pd.date_range('2024-01-01 00:00', periods=6, freq='10min')
    return cr.regularizar_chuva(pd.Series([1.0, 99.0, 1.0, 2.0, 3.0, 4.0], index=idx))


def test_chuva_instante_e_intervalo():
    reg = _pluv_reg()
    novo = ex.excluir_periodos(reg, ['2024-01-01 00:10', ('2024-01-01 00:30', '2024-01-01 00:40')])
    assert reg.chuva_mm.notna().all() and not reg.exclusao_manual.any()       # entrada intacta
    excluidos = novo.exclusao_manual
    assert excluidos.tolist() == [False, True, False, True, True, False]       # limites inclusos
    assert novo.chuva_mm[excluidos].isna().all() and not novo.valido[excluidos].any()
    assert novo.chuva_mm.sum() == 1 + 1 + 4


def test_chuva_nao_tem_niveis():
    with pytest.raises(ValueError, match='níveis'):
        ex.excluir_periodos(_pluv_reg(), [('2024-01-01 00:10', '2024-01-01 00:20', ['n1'])])


# ------------------------------------------------------------------------------ umidade
def _umid_clean():
    u = umidade_base(dias=3)
    u.iloc[200, 0] += 6                                   # pico sem chuva (só sinalizado no padrão)
    pluv_h = chuva_zero(u)
    return u, lu.limpar_umidade(tabela_longa(u), COD, pluv_h=pluv_h)


def test_umidade_so_nos_niveis_pedidos():
    u, r = _umid_clean()
    t = u.index[200]
    assert r.mascaras['pico'].iloc[200, 0] and r.limpo.iloc[200, 0] == u.iloc[200, 0]
    novo = ex.excluir_periodos(r, [(t, t, ['n1'])])
    assert np.isnan(novo.limpo.iloc[200, 0]) and np.isnan(novo.operacional.iloc[200, 0])
    assert novo.limpo.iloc[200, 1:].notna().all()                     # os outros níveis ficam
    assert novo.resumo['n_exclusao_manual'] == 1
    assert novo.resumo['excluidas'] == r.resumo['excluidas'] + 1
    assert r.limpo.iloc[200, 0] == u.iloc[200, 0]                      # entrada intacta
    T = lu.tabela_periodos(novo)
    manual = T[T.tipo == 'exclusão manual']
    assert len(manual) == 1 and manual.niveis.iloc[0] == 'n1' and manual.excluida.iloc[0]


def test_umidade_sem_niveis_exclui_todas_as_profundidades():
    u, r = _umid_clean()
    a, b = u.index[200], u.index[205]
    novo = ex.excluir_periodos(r, [(a, b)])
    assert novo.limpo.iloc[200:206].isna().all().all()
    assert novo.resumo['n_exclusao_manual'] == 6 * 6
    assert ex.excluir_periodos(r, [(a, a, 'n2')]).resumo['n_exclusao_manual'] == 1   # um nível como texto


def test_niveis_desconhecidos_e_entrada_errada():
    u, r = _umid_clean()
    with pytest.raises(ValueError, match='níveis desconhecidos'):
        ex.excluir_periodos(r, [(u.index[0], u.index[1], ['n7'])])
    with pytest.raises(TypeError):
        ex.excluir_periodos(u, [(u.index[0], u.index[1])])          # umidade bruta não serve
    with pytest.raises(ValueError):
        ex.excluir_periodos(r, [(u.index[0],)])                      # item malformado
