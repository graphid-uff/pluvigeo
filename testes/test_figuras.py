"""
Fumaça das figuras: cada função roda com dados sintéticos e devolve uma figura.
Confere o que dá para conferir sem olhar (número de painéis, de séries, de colunas);
a aparência não é testada.

    python -m pytest testes -q
"""
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use('Agg')
import matplotlib.pyplot as plt                       # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pluvigeo import chuva as cr                      # noqa: E402
from pluvigeo import exclusao as ex                   # noqa: E402
from pluvigeo import figuras as fg                    # noqa: E402
from pluvigeo import resolucao as rs                  # noqa: E402
from pluvigeo import umidade as um                    # noqa: E402
from pluvigeo.constantes import NIV                   # noqa: E402
from test_umidade import tabela_longa                 # noqa: E402

RNG = np.random.default_rng(1)


def _umidade(dias=120):
    idx = pd.date_range('2023-01-01', periods=dias * 24, freq='h')
    v = np.array([20, 25, 30, 35, 40, 45.0]) + RNG.normal(0, .1, (len(idx), 6))
    u = pd.DataFrame(v, index=idx, columns=NIV)
    u.iloc[500, :] -= 12
    u.iloc[900, 2] = 0
    u.iloc[1500:, 5] += 3
    return u


def _chuva_regular():
    idx = pd.date_range('2024-01-01', '2024-03-31 23:50', freq='10min')
    v = pd.Series(0.0, index=idx)
    v['2024-02-10 12:00':'2024-02-10 12:50'] = 10.0
    # começa às 00:10: o registro de 01/03 00:00 é chuva de fevereiro (ver resolucao)
    return ex.excluir_periodos(cr.regularizar_chuva(v), [('2024-03-01 00:10', '2024-03-10')])


def test_figuras_umidade():
    u = _umidade()
    ch = pd.Series(0.0, index=pd.date_range(u.index[0], u.index[-1], freq='h'))
    ch.iloc[::200] = 15
    r = um.limpar_umidade(tabela_longa(u, ch), '3399999901G', acomodacao=('2023-01-01', '2023-01-05'))
    fig = fg.status_umid({'3399999901G': r, '3399999902G': r}, '2023-01-01', '2023-05-01')
    assert len(fig.axes[0].get_yticklabels()) == 2
    umid_rs = rs.reamostrar_umidade(r.operacional, '1D')
    fig = fg.serie_umidade(umid_rs, r.pluv_h, freq='1D', acomodacao=r.acomodacao)
    assert len(fig.axes) == 2 and len(fig.axes[0].lines) == 6          # 6 níveis + painel de chuva
    assert len(fig.axes[0].lines[0].get_xdata()) == len(umid_rs)       # diária não é "desagregada" em horas
    fig = fg.serie_umidade(u, niveis=['n1', 'n2'], inicio='2023-02-01', fim='2023-02-10')
    assert len(fig.axes) == 1 and len(fig.axes[0].lines) == 2
    plt.close('all')


def test_figuras_chuva():
    reg = _chuva_regular()
    D = fg.disponibilidade(reg, 'MS')
    assert D.index[0] == pd.Timestamp('2024-01-01')                    # sem o "dezembro" do 1º registro
    assert D.iloc[1] == 1 and 0.6 < D.iloc[2] < 0.75
    fig = fg.status_pluv({'A': reg, 'B': reg})
    assert fig.axes[0].images[0].get_array().shape == (2, 3)           # 2 estações x 3 meses
    dia = fg.status_pluv({'A': reg}, freq='D')
    assert dia.axes[0].images[0].get_array().shape[1] == 91            # jan a mar de 2024, por dia
    fig = fg.serie_chuva(reg, '2024-02-01', '2024-03-15')              # tabela regular: falha em cinza
    assert len(fig.axes) == 1 and len(fig.axes[0].patches) > 100
    assert fg.serie_chuva(rs.reamostrar_chuva(reg, '1D')['chuva_mm']) is not None    # ou uma série
    plt.close('all')


def test_salvar(tmp_path):
    fg.salvar(fg.status_pluv({'A': _chuva_regular()}), tmp_path / 'sub' / 'fig.png')
    assert (tmp_path / 'sub' / 'fig.png').stat().st_size > 1000


def test_figuras_interativas():
    pytest.importorskip('plotly')
    reg = _chuva_regular()
    assert len(fg.serie_chuva_interativo(reg, '2024-02-01', '2024-03-15').data) == 1
    u = _umidade()
    ch = pd.Series(1.0, index=pd.date_range(u.index[0], u.index[-1], freq='h'))
    fig = fg.serie_umidade_interativo(u, ch, niveis=['n1', 'n6'], acomodacao=('2023-01-01', '2023-01-20'))
    assert len(fig.data) == 3                                     # 2 níveis + chuva
    assert len(fg.serie_umidade_interativo(u, freq=None).data) == 6
    assert len(fg.serie_umidade_interativo(u, freq='1D').data[0].x) == 120    # 120 dias
