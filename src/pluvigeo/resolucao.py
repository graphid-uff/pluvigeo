"""
resolucao.py
============
Ajuste da resolução temporal: leva a chuva e a umidade para uma resolução mais grossa
(10 min -> 1 h -> 1 dia -> mês), sem esconder as falhas. "rs" nos nomes dos objetos
(pluv_rs, umid_rs) quer dizer "resample", reamostrado.

  reamostrar_chuva    -> soma da chuva por período; NaN quando o período tem falha demais
  reamostrar_umidade  -> média (ou mediana) da umidade por período

Bloco fixo, não janela móvel
----------------------------
As duas funções somam (ou fazem a média) em BLOCOS do calendário: horas redondas, dias,
meses. O dia 15/02 é a chuva que caiu de 00:00 a 24:00 de 15/02. Para somas em janela
MÓVEL (a chuva das últimas 24 h a cada 10 min, para máximos e limiares), use
chuva.acumulados.

Rótulo e limites de cada período
--------------------------------
Cada período é rotulado pelo seu INÍCIO: a hora 01:00 é a chuva de 01:00 a 02:00; o dia
15/02 é a chuva de 15/02 00:00 a 16/02 00:00.

Na chuva, cada registro do Cemaden traz a chuva dos 10 min que TERMINAM no seu horário
(o registro das 01:00 é a chuva de 00:50 a 01:00). Por isso o dia 15/02 reúne os registros
de 15/02 00:10 a 16/02 00:00, e a hora 01:00 os de 01:10 a 02:00. É a chuva que caiu de fato
dentro do dia civil; o total diário do próprio Cemaden (sensor 600) é fechado do mesmo jeito.

`inicio_dia` muda a hora em que o dia começa (ex.: 9 -> o dia 15/02 vai de 15/02 09:00 a
16/02 09:00 e aparece rotulado como 15/02 09:00). Vale também para meses e anos.

Falhas
------
* Chuva é SOMADA. Um período só vale se a fração em falha não passar de
  `fracao_falha_max` (padrão 0: qualquer falha invalida). Somar um período com falha
  daria um total menor que o real, sem aviso. A coluna `incompleto` diz se faltou algum
  intervalo, mesmo quando a falha coube na tolerância.
* Umidade é uma grandeza de estado: usa-se a MÉDIA (ou a mediana) das leituras do
  período. A transmissão é irregular (10 min com chuva, 1 h sem), então a exigência é
  um nº mínimo de leituras no período, e não uma fração. A coluna `incompleto` diz se
  alguma hora do período ficou sem nenhuma leitura.
* Nada é interpolado nem preenchido.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .constantes import NIV


def _tamanho_periodos(inicios: pd.DatetimeIndex, freq: str) -> pd.Series:
    """Duração de cada período (meses e anos têm tamanhos diferentes)."""
    desloc = pd.tseries.frequencies.to_offset(freq)
    return pd.Series((inicios + desloc) - inicios, index=inicios)


def reamostrar_chuva(pluv_reg: pd.DataFrame, freq: str = '1h', fracao_falha_max: float = 0.0,
                     inicio_dia: float = 0) -> pd.DataFrame:
    """Soma a chuva em blocos fixos do calendário (hora, dia, mês...).

    Entrada
    -------
    pluv_reg : a tabela regular de UMA estação (pluv_reg[cod], de chuva.regularizar_chuva).

    Parâmetros
    ----------
    freq             : resolução de saída: '30min', '1h', '3h', '1D', 'MS' (mês), 'YS' (ano)...
    fracao_falha_max : fração do período, de 0 a 1, que pode estar em falha, contada em
                       intervalos de 10 min. Padrão 0: qualquer falha invalida o período.
                       Com tolerância maior que zero, o total é a soma do que foi medido (um
                       limite inferior da chuva real) e a linha fica com `incompleto=True`.
    inicio_dia       : hora em que o dia começa. Padrão 0 (dia civil, 00:00 a 24:00).

    Saída (pluv_rs[cod]): tabela com índice = início de cada período e as colunas
    -----
      chuva_mm      soma do período (mm); NaN se inválido
      n_validos     nº de intervalos de 10 min com dado no período
      n_esperados   nº de intervalos que o período deveria ter
      incompleto    True se faltou algum intervalo (n_validos < n_esperados)
      valido        True se a falha cabe na tolerância (fracao_falha_max)

    Cada período é rotulado pelo início e reúne a chuva que caiu dentro dele: o dia 15/02 soma
    os registros de 15/02 00:10 a 16/02 00:00 (ver o cabeçalho do módulo). O primeiro e o último
    período da série costumam sair incompletos por estarem cortados.
    """
    chuva_mm = pluv_reg['chuva_mm']
    passo = chuva_mm.index[1] - chuva_mm.index[0]
    desloc_dia = pd.Timedelta(hours=inicio_dia)
    # cada registro passa a ser datado pelo INÍCIO do seu intervalo (00:10 -> 00:00), e o
    # relógio é atrasado em `inicio_dia`; assim o agrupamento comum (fechado à esquerda) junta
    # exatamente a chuva que caiu dentro de cada período
    serie = chuva_mm.copy()
    serie.index = serie.index - passo - desloc_dia
    grupos = serie.resample(freq)
    saida = pd.DataFrame({'chuva_mm': grupos.sum(min_count=1), 'n_validos': grupos.count()})
    saida['n_esperados'] = np.round(_tamanho_periodos(saida.index, freq) / passo).astype(int).values
    faltam = saida['n_esperados'] - saida['n_validos']
    saida['incompleto'] = faltam > 0
    saida['valido'] = faltam <= fracao_falha_max * saida['n_esperados']
    saida['chuva_mm'] = saida['chuva_mm'].where(saida['valido'])
    saida.index = saida.index + desloc_dia
    saida.index.name = 'datahora'
    return saida


def reamostrar_umidade(umid: pd.DataFrame, freq: str = '1h', agregacao: str = 'media',
                       min_leituras: int = 1, inicio_dia: float = 0) -> pd.DataFrame:
    """Agrega a umidade (n1..n6, em %) em blocos fixos do calendário (hora, dia, mês...).

    Entrada
    -------
    umid : a umidade larga de UMA estação, de preferência já limpa: umid_clean[cod].operacional
           (de umidade.limpar_umidade). Leituras irregulares no tempo são aceitas. Também
           aceita a própria saída desta função (ex.: horária -> diária).

    Parâmetros
    ----------
    freq         : resolução de saída ('1h', '1D', 'MS'...).
    agregacao    : 'media' (padrão) ou 'mediana'. A mediana resiste melhor a uma leitura
                   espúria que tenha escapado da limpeza.
    min_leituras : nº mínimo de leituras no período para ele valer; abaixo disso, NaN.
                   Padrão 1. Para o dia a partir de dados horários, algo como 18 (75 % das
                   horas) evita um "dia" representado só pela madrugada.
    inicio_dia   : hora em que o dia começa. Padrão 0 (dia civil).

    Saída (umid_rs[cod]): tabela com índice = início de cada período, as colunas n1..n6 e
    -----
      incompleto   True se alguma hora do período ficou sem nenhuma leitura. Com a estação
                   funcionando há pelo menos uma leitura por hora, então uma hora vazia é
                   falha. Em períodos menores que 1 h, a conta é por período.

    Nada é interpolado. Média horária e depois mediana diária das horas é o caminho do kit de
    origem para chegar ao dia.
    """
    niveis = [n for n in umid.columns if n in NIV]
    desloc_dia = pd.Timedelta(hours=inicio_dia)
    u = umid[niveis].copy()
    u.index = u.index - desloc_dia
    grupos = u.resample(freq)
    if agregacao == 'media':
        saida = grupos.mean()
    elif agregacao == 'mediana':
        saida = grupos.median()
    else:
        raise ValueError("agregacao deve ser 'media' ou 'mediana'")
    saida = saida.where(grupos.count() >= min_leituras)

    # incompleto: horas (ou períodos, se menores que 1 h) sem nenhuma leitura
    tamanho = _tamanho_periodos(saida.index, freq)
    unidade = min(pd.Timedelta('1h'), tamanho.min()) if len(tamanho) else pd.Timedelta('1h')
    # a hora de cada leitura (NaT onde nenhum nível tem dado), no mesmo índice de `u`, para o
    # agrupamento cair exatamente nos mesmos períodos da média
    horas = pd.Series(u.index.floor(unidade), index=u.index).where(u.notna().any(axis=1))
    n_com_dado = horas.resample(freq).nunique().reindex(saida.index, fill_value=0)
    saida['incompleto'] = n_com_dado.values < np.round(tamanho / unidade).values
    saida.index = saida.index + desloc_dia
    saida.index.name = 'datahora'
    return saida
