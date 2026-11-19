"""
figuras.py
==========
Figuras da chuva e da umidade. Todas recebem dados já processados e DEVOLVEM a figura;
nenhuma lê arquivo nem grava nada. Para gravar: salvar(fig, caminho).

Séries no tempo (cada uma tem a versão interativa, de mesmo nome com o sufixo _interativo)
  serie_chuva / serie_chuva_interativo      -> chuva por tempo (falhas em cinza)
  serie_umidade / serie_umidade_interativo  -> umidade por tempo, uma linha por profundidade.
                                               A interativa é a ferramenta para identificar o
                                               período de acomodação dos sensores.

Situação das estações (várias de uma vez)
  status_pluv  -> chuva: fração de cada mês (ou dia) com dado válido, por estação
  status_umid  -> umidade: situação de cada PCD Geo, dia a dia

As versões interativas usam o plotly; as demais, matplotlib.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.dates as md
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .constantes import NIV, PROFUNDIDADE_M
from .resolucao import reamostrar_chuva, reamostrar_umidade

# ======================================================================== estilo comum
RC = {'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
      'axes.edgecolor': '#9a9a96', 'axes.labelcolor': '#3b3b38', 'xtick.color': '#52514e',
      'ytick.color': '#52514e', 'axes.grid': True, 'grid.color': '#e6e5e0', 'grid.linewidth': .6,
      'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.bbox': 'tight',
      'legend.frameon': False}

# profundidade: do raso (claro) ao fundo (escuro)
COR_NIVEL = dict(zip(NIV, plt.get_cmap('YlGnBu')(np.linspace(.38, 1, 6))))
ROTULO_NIVEL = {n: f'{n} ({PROFUNDIDADE_M[n]:.1f} m)'.replace('.', ',') for n in NIV}

COR_CHUVA = '#2a78d6'
COR_ACOMODACAO = '#f3d27a'


def aplicar():
    """Aplica o estilo (rcParams) globalmente. Chamada ao importar o módulo."""
    plt.rcParams.update(RC)


def salvar(fig, caminho: str | Path, dpi: int = 110):
    """Grava uma figura do matplotlib e a fecha.

    fig     : a figura devolvida por qualquer função deste módulo (menos as _interativo,
              que se gravam com fig.write_html(caminho)).
    caminho : arquivo de saída (.png, .pdf...); a pasta é criada se não existir.
    dpi     : resolução. Padrão 110.
    """
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, dpi=dpi)
    plt.close(fig)


def eixo(ax=None, figsize=(12, 4)):
    """Devolve (fig, ax): usa o `ax` dado ou cria uma figura nova."""
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
        return fig, ax
    return ax.figure, ax


aplicar()


# ======================================================================== chuva
def disponibilidade(pluv_reg: pd.DataFrame, freq: str = 'MS') -> pd.Series:
    """Fração (0 a 1) de cada período (padrão: mês) com chuva válida, contando o período
    INTEIRO: um mês em que a estação só existiu na segunda quinzena aparece com ~0,5.
    pluv_reg é a tabela de UMA estação. Usa os mesmos períodos de resolucao.reamostrar_chuva."""
    r = reamostrar_chuva(pluv_reg, freq, fracao_falha_max=1.0)
    # o 1º registro da série (ex.: 01/01 00:00) é chuva do período anterior; um período que
    # só tem ele fica de fora, para não aparecer como um mês (dia) quase vazio
    fim_periodo = r.index + pd.tseries.frequencies.to_offset(freq)
    r = r[fim_periodo > pluv_reg.index[0]]
    return r['n_validos'] / r['n_esperados']


def _blocos_de_falha(reg: pd.DataFrame) -> list:
    """Lista de (início, fim) dos trechos sem dado válido (falha longa, retorno, exclusão manual)."""
    ruim = reg['chuva_mm'].isna()
    if not ruim.any():
        return []
    grupo = (ruim != ruim.shift()).cumsum()[ruim]
    passo = reg.index[1] - reg.index[0]
    return [(g.index[0] - passo, g.index[-1]) for _, g in ruim[ruim].groupby(grupo)]


def status_pluv(pluv_reg: dict, freq: str = 'MS', ax=None):
    """Situação da chuva de várias estações: uma linha por estação, uma coluna por período.

    Entrada : pluv_reg, o dicionário {codestacao: tabela de chuva.regularizar_chuva}.
    Parâmetros
      freq : tamanho de cada coluna. 'MS' (padrão) = mês; 'D' = dia (bom para períodos
             curtos: em anos de dados as colunas ficam finas demais).
      ax   : eixo do matplotlib, para desenhar dentro de uma figura sua (opcional).
    Saída   : figura. Cores do vermelho (0, nenhum dado válido no período) ao verde (1,
              período completo); cinza = fora do período da estação.
    """
    D = pd.DataFrame({c: disponibilidade(r, freq) for c, r in pluv_reg.items()}).sort_index(axis=1)
    cores = plt.get_cmap('RdYlGn').with_extremes(bad='#d9d9d9')     # sem dado nenhum: cinza
    fig, ax = eixo(ax, figsize=(12, .26 * D.shape[1] + 1.4))
    im = ax.imshow(np.ma.masked_invalid(D.T.values.astype(float)), aspect='auto', cmap=cores, vmin=0, vmax=1,
                   interpolation='nearest')
    ax.set_yticks(range(D.shape[1]), D.columns, fontsize=8)
    anos = D.index.year
    xt = [i for i in range(len(D.index)) if i == 0 or anos[i] != anos[i - 1]]     # 1ª coluna de cada ano
    ax.set_xticks(xt, [str(anos[i]) for i in xt])
    ax.grid(False)
    fig.colorbar(im, ax=ax, fraction=.02, pad=.01, label='fração do período com dado válido')
    unidade = 'dia' if pd.tseries.frequencies.to_offset(freq).name in ('D',) else 'mês'
    ax.set_title(f'Chuva com dado válido, por {unidade} (cinza: fora do período da estação)', loc='left')
    return fig


def _chuva_e_falhas(pluv, inicio, fim):
    """Aceita a tabela regular ou uma série de chuva. Devolve (série no período, lista de
    (início, fim) dos trechos em falha), a lista vazia quando veio só a série."""
    if isinstance(pluv, pd.DataFrame):
        reg = pluv.loc[inicio:fim]
        return reg['chuva_mm'], _blocos_de_falha(reg)
    return pluv.loc[inicio:fim], []


def serie_chuva(pluv, inicio=None, fim=None, titulo: str = ''):
    """Chuva por tempo, em barras.

    Entrada : pluv, uma destas:
              - pluv_reg[cod], a tabela de 10 min de UMA estação (as falhas aparecem em cinza);
              - uma série de chuva (mm) em qualquer resolução, ex.: pluv_rs[cod]['chuva_mm']
                (de resolucao.reamostrar_chuva).
    Parâmetros: inicio, fim (recorte do período; None = tudo) e titulo.
    Saída   : figura do matplotlib.
    """
    serie, falhas = _chuva_e_falhas(pluv, inicio, fim)
    fig, ax = eixo(figsize=(12, 3.6))
    _barras_chuva(ax, serie, rotulo='chuva (mm)')
    for k, (a, b) in enumerate(falhas):
        ax.axvspan(a, b, color='#bdbdbd', alpha=.5, lw=0, label='sem dado válido' if k == 0 else None)
    if falhas:
        ax.legend(loc='upper right', fontsize=8.5)
    ax.xaxis.set_major_formatter(md.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    ax.set_title(titulo or 'Chuva', loc='left')
    fig.tight_layout()
    return fig


def serie_chuva_interativo(pluv, inicio=None, fim=None, titulo: str = ''):
    """Versão interativa (plotly) de serie_chuva: mesmas entradas, com zoom e valores ao
    passar o mouse. Saída: plotly.graph_objects.Figure (grave com fig.write_html)."""
    try:
        import plotly.graph_objects as go
    except ImportError as e:
        raise ImportError('serie_chuva_interativo precisa do plotly: pip install plotly') from e
    serie, falhas = _chuva_e_falhas(pluv, inicio, fim)
    fig = go.Figure(go.Bar(x=serie.index, y=serie.round(2), name='chuva', marker_color=COR_CHUVA))
    for a, b in falhas:
        fig.add_vrect(x0=a, x1=b, fillcolor='#bdbdbd', opacity=.5, line_width=0)
    fig.update_yaxes(title_text='chuva (mm)')
    fig.update_layout(title=(titulo or 'Chuva') + (' (faixas cinza: sem dado válido)' if falhas else ''),
                      height=380, bargap=0, margin=dict(t=50, r=20))
    return fig


# ======================================================================== umidade
def _barras_chuva(ax, chuva: pd.Series, largura=None, rotulo='chuva (mm)'):
    if chuva is None or not len(chuva):
        return
    if largura is None:
        passo = (chuva.index[1] - chuva.index[0]) if len(chuva) > 1 else pd.Timedelta('1D')
        largura = passo / pd.Timedelta('1D') * .9
    ax.bar(chuva.index, chuva.values, width=largura, color=COR_CHUVA, lw=0)
    ax.set_ylabel(rotulo)


def _mais_grossa(indice: pd.DatetimeIndex, freq) -> bool:
    """True se `freq` é mais grossa que o passo típico da série (só então vale agregar:
    agregar uma série diária em horas criaria buracos)."""
    if freq is None or len(indice) < 2:
        return False
    passo = pd.Series(indice).diff().median()
    try:
        return pd.Timedelta(freq) > passo
    except ValueError:                         # 'MS', 'YS'...: sempre mais grossas que um dia
        return True


def _preparar_umidade(umid, pluv, inicio, fim, niveis, freq):
    """Recorta e, se for o caso, agrega a umidade (média, reamostrar_umidade) e a chuva (soma)."""
    niveis = [n for n in (niveis or NIV) if n in umid.columns]
    d = umid.loc[inicio:fim, niveis]
    if _mais_grossa(d.index, freq):
        d = reamostrar_umidade(d, freq)[niveis]
    c = None
    if pluv is not None:
        c = pluv.loc[inicio:fim]
        if _mais_grossa(c.index, freq):
            c = c.resample(freq).sum(min_count=1)
    return d, c, niveis


def serie_umidade(umid: pd.DataFrame, pluv: pd.Series | None = None, inicio=None, fim=None,
                  niveis=None, freq: str | None = '1h', acomodacao: tuple | None = None,
                  titulo: str = ''):
    """Umidade por tempo, uma linha por profundidade; com a chuva embaixo, se for dada.

    Entrada
      umid : umidade larga de UMA estação (n1..n6, %) em qualquer resolução, ex.:
             umid_clean[cod].operacional ou umid_rs[cod].
      pluv : série de chuva (mm) para o painel de baixo (opcional), ex.: umid_clean[cod].pluv_h
             ou pluv_rs[cod]['chuva_mm'].
    Parâmetros
      inicio, fim : recorte do período (None = tudo).
      niveis      : lista de níveis a mostrar (None = todos).
      freq        : resolução do desenho: média da umidade e soma da chuva por `freq`. Padrão
                    '1h'. Só agrega quando a série é mais fina que `freq`; None desenha como veio.
      acomodacao  : (inicio, fim) a sombrear em amarelo (opcional).
      titulo      : título da figura.
    Saída: figura do matplotlib.
    """
    d, c, niveis = _preparar_umidade(umid, pluv, inicio, fim, niveis, freq)
    if c is None:
        fig, a0 = plt.subplots(figsize=(12, 4))
        ax = [a0]
    else:
        fig, ax = plt.subplots(2, 1, figsize=(12, 5.4), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        _barras_chuva(ax[1], c, rotulo='chuva (mm)')
    for n in niveis:
        ax[0].plot(d.index, d[n], color=COR_NIVEL[n], lw=1.3, label=ROTULO_NIVEL[n])
    if acomodacao:
        ax[0].axvspan(pd.Timestamp(acomodacao[0]), pd.Timestamp(acomodacao[1]), color=COR_ACOMODACAO,
                      alpha=.35, lw=0, label='acomodação')
    ax[0].set_ylabel('umidade (%)')
    ax[0].legend(ncol=7, fontsize=8, loc='lower left')
    ax[0].set_title(titulo or 'Umidade do solo', loc='left')
    ax[-1].xaxis.set_major_formatter(md.ConciseDateFormatter(ax[-1].xaxis.get_major_locator()))
    fig.tight_layout()
    return fig


def serie_umidade_interativo(umid: pd.DataFrame, pluv: pd.Series | None = None, inicio=None, fim=None,
                             niveis=None, freq: str | None = '1h', acomodacao: tuple | None = None,
                             titulo: str = ''):
    """Ferramenta para identificar o período de acomodação dos sensores: as profundidades
    da umidade (e a chuva, se dada) numa figura interativa (plotly), com zoom e datas ao
    passar o mouse.

    Como usar: desenhe a série BRUTA (umid_raw[cod], de leitura.umidade_por_estacao), dê zoom
    no começo, passe o mouse sobre o ponto em que as camadas fundas param de descer sem
    relação com a chuva e leia a data. Confira a escolha sombreando o período candidato em
    `acomodacao` e depois informe-o em limpar_umidade(dados, cod, acomodacao=(inicio, fim)).
    Também serve para avaliar as suspeitas de tabela_periodos na série limpa.

    Entradas e parâmetros: os mesmos de serie_umidade.
    Saída: plotly.graph_objects.Figure (grave com fig.write_html). Precisa do plotly.
    """
    try:
        import plotly.graph_objects as go
        from matplotlib.colors import to_hex
        from plotly.subplots import make_subplots
    except ImportError as e:
        raise ImportError('serie_umidade_interativo precisa do plotly: pip install plotly') from e
    d, c, niveis = _preparar_umidade(umid, pluv, inicio, fim, niveis, freq)
    tem_chuva = c is not None
    fig = make_subplots(rows=2 if tem_chuva else 1, cols=1, shared_xaxes=True, vertical_spacing=.04,
                        row_heights=[.74, .26] if tem_chuva else [1])
    for n in niveis:
        fig.add_trace(go.Scattergl(x=d.index, y=d[n].round(2), mode='lines', name=ROTULO_NIVEL[n],
                                   line=dict(color=to_hex(COR_NIVEL[n]), width=1.3), connectgaps=False),
                      row=1, col=1)
    if tem_chuva:
        fig.add_trace(go.Bar(x=c.index, y=c, name='chuva', marker_color=COR_CHUVA), row=2, col=1)
        fig.update_yaxes(title_text='chuva (mm)', row=2, col=1)
    if acomodacao:
        fig.add_vrect(x0=pd.Timestamp(acomodacao[0]), x1=pd.Timestamp(acomodacao[1]), fillcolor=COR_ACOMODACAO,
                      opacity=.3, line_width=0, annotation_text='acomodação', annotation_position='top left')
    fig.update_yaxes(title_text='umidade (%)', row=1, col=1)
    fig.update_layout(title=(titulo or 'Umidade do solo') + ' (dê zoom e passe o mouse para ler as datas)',
                      height=560, hovermode='x unified', bargap=0, legend=dict(orientation='h', y=-.1),
                      margin=dict(t=50, r=20))
    return fig


def status_umid(umid_clean: dict, inicio, fim, ax=None):
    """Situação diária da umidade de várias PCDs Geo: uma faixa por estação.

    Entrada : umid_clean, o dicionário {codestacao: resultado de umidade.limpar_umidade}.
    Parâmetros: inicio, fim (período da figura) e ax (eixo do matplotlib, opcional).
    Saída   : figura. Cada dia aparece como operando, dia com quedas simultâneas,
              acomodação, falha (zeros ou congelado em boa parte do dia) ou sem dados.
    """
    dias = pd.date_range(inicio, fim, freq='D')
    cores = ['#ffffff', '#e34948', '#b9b6ae', '#9085e9', '#2a78d6']
    rot = ['sem dados', 'falha (zeros / congelado)', 'acomodação', 'dia com quedas simultâneas', 'operando']
    cods = sorted(umid_clean)
    fig, ax = eixo(ax, figsize=(12, .45 * len(cods) + 1.4))
    for i, c in enumerate(cods):
        r = umid_clean[c]
        tem = r.bruto.notna().any(axis=1).resample('D').sum().reindex(dias, fill_value=0) > 0
        falha = ((r.mascaras['zero'].any(axis=1)) | (r.mascaras['congelado'].sum(axis=1) >= 3)).resample('D').mean().reindex(dias, fill_value=0)
        qs = r.mascaras['queda_simultanea'].any(axis=1).resample('D').sum().reindex(dias, fill_value=0)
        s = pd.Series(4, index=dias)
        s[qs > 0] = 3
        s[falha > .5] = 1
        if r.acomodacao:
            s[(dias >= pd.Timestamp(r.acomodacao[0])) & (dias <= pd.Timestamp(r.acomodacao[1])) & tem.values] = 2
        s[~tem.values] = 0
        for k in (1, 2, 3, 4):
            d = dias[s.values == k]
            if len(d):
                ax.broken_barh([(md.date2num(x), 1) for x in d], (i - .38, .76), color=cores[k], lw=0)
    ax.set_yticks(range(len(cods)), cods)
    ax.invert_yaxis()
    ax.grid(False)
    ax.xaxis_date()
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=cores[k]) for k in (4, 3, 2, 1)],
              labels=[rot[k] for k in (4, 3, 2, 1)], ncol=4, loc='upper center', bbox_to_anchor=(.5, -.12), fontsize=8.5)
    ax.set_title('Situação diária da umidade', loc='left')
    return fig
