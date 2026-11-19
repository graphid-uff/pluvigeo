"""
chuva.py
========
Diagnóstico de integridade da chuva: põe a chuva de cada estação numa grade regular de
10 min, marca as falhas e resume o funcionamento da estação.

Objetos que circulam (nomes usados no notebook e na documentação)
------------------------------------------------------------------
  pluv_raw  {codestacao: série de chuva bruta}         <- leitura.chuva_por_estacao
  pluv_reg  {codestacao: tabela regular de chuva}      <- regularizar_chuva(pluv_raw)
  pluv_reg[cod] é a tabela de UMA estação; a coluna pluv_reg[cod]['chuva_mm'] é a série a usar.

Funções
-------
  regularizar_chuva   -> grade regular + marcação de falhas + chuva higienizada (chuva_mm)
  relatorio_falhas    -> números de falha de uma estação (ou de várias, numa tabela)
  retornos_pos_falha  -> as primeiras leituras depois de cada falha longa
  acumulados          -> somas em JANELA MÓVEL (1 h ... 30 dias) que terminam em cada instante
  resumo_estacao      -> funcionamento, máximos por janela, percentis, médias mensais e anuais

Para excluir à mão leituras que nenhuma regra pegou: exclusao.excluir_periodos.
Para somar a chuva em BLOCOS FIXOS (hora redonda, dia civil, mês): resolucao.reamostrar_chuva.

Janela móvel (acumulados) x bloco fixo (reamostrar_chuva)
--------------------------------------------------------
  acumulados : a cada 10 min, a soma das últimas N horas. `acum_24h` às 15:00 de 15/02 é a
               chuva de 15:00 de 14/02 a 15:00 de 15/02. Serve para máximos e limiares
               ("a maior chuva em 24 h"), que podem atravessar a meia-noite.
  reamostrar : uma soma por período do calendário. O dia 15/02 é a chuva que caiu de 00:00
               a 24:00 de 15/02. Serve para totais horários, diários e mensais.

Por que a grade regular precisa de uma regra
--------------------------------------------
O pluviômetro do Cemaden transmite a cada 10 min quando chove e de hora em hora quando
não chove. Então um intervalo de 10 min sem registro pode ser "não choveu" (normal) ou
"a estação não transmitiu" (falha). A regra, vinda do notebook original:

  - até `max_intervalos_vazios` intervalos vazios seguidos (padrão 5, isto é, 50 min: o
    espaço normal entre duas transmissões horárias) -> não choveu, vale 0 mm;
  - mais do que isso -> falha longa, fica NaN;
  - a primeira leitura depois de uma falha longa é MARCADA (`retorno_pos_falha_longa`):
    em algumas estações ela traz, de uma vez, toda a chuva acumulada enquanto a estação
    esteve fora do ar, e não dá para saber quando essa chuva caiu. Quando chega a
    `limiar_retorno` (padrão 25 mm) ela é marcada em `retorno_alto` e descartada (NaN);
    com `excluir_retorno_alto=False` fica só marcada. Nos dados de Petrópolis, dos
    23.224 retornos, 17.973 são zero, a média é 0,11 mm e só 6 chegam a 25 mm (entre eles
    228, 179 e 99 mm depois de 45, 37 e 79 dias fora do ar).

Valor repetido: uma sequência longa de leituras TRANSMITIDAS seguidas com exatamente
0,2 mm (uma basculada do pluviômetro) provavelmente não é chuva (hipótese: ruído do
equipamento, ou água escoando aos poucos de um funil parcialmente entupido). Por padrão,
sequências de 12 leituras de 0,2 mm ou mais são descartadas (NaN), do primeiro ao último
registro da sequência. Em Petrópolis há sequências de até 559 leituras de 0,2 mm (26 dias,
112 mm de chuva que não existiu, na 330390612A). A regra e os padrões (`min_repetidos`,
`valor_repetido_mm`) são EMPÍRICOS e o ruído é muito intermitente: teste outros valores
nos seus dados. `filtrar_repetidos=False` desliga o filtro.

Leituras altas (padrão >= 25 mm em 10 min, ou 150 mm/h) são só MARCADAS em
`leitura_alta`: podem ser chuva real de evento extremo, e a decisão de usar ou não é sua.

Limite deste módulo: ele olha UMA estação por vez e só enxerga falhas de transmissão.
Um pluviômetro entupido, que transmite normalmente e registra menos do que choveu, não é
detectado; isso exige comparar estações vizinhas, o que está fora desta biblioteca.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .resolucao import reamostrar_chuva

# Janelas dos acumulados móveis. As nove primeiras são as do script 3; 30 dias foi pedido depois.
JANELAS_PADRAO = ('1h', '3h', '6h', '12h', '24h', '36h', '48h', '72h', '7D', '30D')


def _n_intervalos(janela: str, freq) -> int:
    """Quantos intervalos de `freq` cabem em `janela` (ex.: '3h' em '10min' -> 18)."""
    n = pd.Timedelta(janela) / pd.Timedelta(freq)
    if n < 1 or n != int(n):
        raise ValueError(f'a janela {janela} não é múltipla da frequência {freq}')
    return int(n)


def _passo(df_ou_serie) -> pd.Timedelta:
    """Passo da grade regular (diferença entre os dois primeiros instantes)."""
    idx = df_ou_serie.index
    return pd.Timedelta(idx.freq) if idx.freq is not None else idx[1] - idx[0]


def _valor_repetido(valor_original: pd.Series, min_repetidos: int, valor_repetido_mm=0.2) -> pd.Series:
    """Marca as sequências de `min_repetidos` ou mais leituras transmitidas seguidas com o
    mesmo valor `valor_repetido_mm` (None = qualquer valor não nulo). A contagem é pelas
    transmissões, não pelos intervalos da grade: sem chuva de verdade a estação transmite de
    hora em hora, e uma sequência dessas pode ser 0,2 mm a cada hora durante dias. Marca do
    primeiro ao último registro da sequência, incluindo os intervalos sem transmissão entre eles."""
    lidos = valor_original.dropna().round(3)           # 3 casas: compara sem ruído de ponto flutuante
    positivo = lidos > 0
    if valor_repetido_mm is not None:                  # só o valor do ruído conta; os outros quebram a sequência
        positivo &= lidos == round(valor_repetido_mm, 3)
    bloco = ((lidos != lidos.shift()) | ~positivo).cumsum()
    tamanho = lidos.groupby(bloco).transform('size')
    longos = bloco[positivo & (tamanho >= min_repetidos)]
    marca = pd.Series(False, index=valor_original.index)
    for _, instantes in longos.groupby(longos):
        marca.loc[instantes.index[0]:instantes.index[-1]] = True
    return marca


def regularizar_chuva(pluv_raw, freq: str = '10min', max_intervalos_vazios: int = 5,
                      limiar_leitura_alta: float = 25.0, limiar_retorno: float = 25.0,
                      excluir_retorno_alto: bool = True, filtrar_repetidos: bool = True,
                      min_repetidos: int = 12, valor_repetido_mm: float | None = 0.2):
    """Coloca a chuva em grade regular e marca as falhas.

    Entrada
    -------
    pluv_raw : a chuva bruta de leitura.chuva_por_estacao. Pode ser
               - o dicionário inteiro {codestacao: série}  -> devolve {codestacao: tabela};
               - a série de UMA estação (pluv_raw[cod])    -> devolve a tabela dessa estação.
               A série tem mm por registro e índice datahora (irregular).

    Parâmetros
    ----------
    freq                  : passo da grade. Padrão '10min', a resolução do Cemaden com chuva.
    max_intervalos_vazios : nº máximo de intervalos vazios seguidos ainda tratados como
                            "não choveu" (vale 0 mm). Padrão 5: com 10 min, é o vazio normal
                            entre duas transmissões horárias. Mais do que isso é falha longa.
    limiar_leitura_alta   : mm num único intervalo a partir do qual a leitura é marcada em
                            `leitura_alta`. Padrão 25 mm. Só marca, nunca descarta.
    limiar_retorno        : mm a partir dos quais a primeira leitura depois de uma falha longa
                            é marcada em `retorno_alto`. Padrão 25 mm.
    excluir_retorno_alto  : True (padrão) descarta (NaN) o retorno alto; False só o marca.
    filtrar_repetidos     : True (padrão) descarta as sequências longas de leituras com o
                            mesmo valor; False processa sem esse filtro.
    min_repetidos         : nº mínimo de leituras transmitidas seguidas, com o mesmo valor,
                            para a sequência ser descartada. Padrão 12 (empírico; teste
                            outros valores, ver docs/regras.md).
    valor_repetido_mm     : valor (mm) do ruído procurado. Padrão 0,2 mm, uma basculada do
                            pluviômetro, que é o ruído observado em Petrópolis. None aceita
                            qualquer valor não nulo.

    Saída (para cada estação): tabela com índice regular `datahora` e as colunas
    -----
      valor_original           leitura como veio (NaN onde não houve transmissão)
      ausente                  True onde não houve transmissão
      grupo_falha              número do bloco contínuo de presença/ausência
      tamanho_bloco            nº de intervalos do bloco a que a linha pertence
      falha_longa              ausente, em bloco maior que max_intervalos_vazios
      retorno_pos_falha_longa  primeira leitura depois de uma falha longa (só marca)
      retorno_alto             retorno pós-falha com valor >= limiar_retorno
      valor_repetido           dentro de uma sequência longa de leituras iguais (toda False
                               com filtrar_repetidos=False)
      leitura_alta             valor_original >= limiar_leitura_alta (só marca)
      exclusao_manual          False (ver exclusao.excluir_periodos)
      valido                   False em falha longa, valor repetido, retorno alto (se
                               excluir_retorno_alto) e exclusão manual
      chuva_mm                 A SÉRIE A USAR: a leitura; 0 nos vazios curtos; NaN onde não
                               é válido

    Cada registro do Cemaden traz a chuva dos 10 min que TERMINAM no seu horário: o valor das
    01:00 é a chuva de 00:50 a 01:00. Os horários fora da grade (comuns no mapa interativo
    até 2015, ex.: 00:30:24) são arredondados para o intervalo mais próximo e somados.
    """
    if isinstance(pluv_raw, dict):
        return {cod: regularizar_chuva(s, freq, max_intervalos_vazios, limiar_leitura_alta, limiar_retorno,
                                       excluir_retorno_alto, filtrar_repetidos, min_repetidos,
                                       valor_repetido_mm)
                for cod, s in pluv_raw.items()}
    serie = pluv_raw.dropna().sort_index()
    # arredonda para a grade e soma o que cair no mesmo intervalo (script 3)
    serie = serie.groupby(serie.index.round(freq)).sum()
    grade = pd.date_range(serie.index.min(), serie.index.max(), freq=freq, name='datahora')
    reg = pd.DataFrame({'valor_original': serie.reindex(grade)})

    reg['ausente'] = reg['valor_original'].isna()
    # cada troca entre presente/ausente abre um bloco novo
    reg['grupo_falha'] = reg['ausente'].ne(reg['ausente'].shift()).cumsum()
    reg['tamanho_bloco'] = reg.groupby('grupo_falha')['ausente'].transform('size')
    reg['falha_longa'] = reg['ausente'] & (reg['tamanho_bloco'] > max_intervalos_vazios)
    reg['retorno_pos_falha_longa'] = reg['falha_longa'].shift(1, fill_value=False) & ~reg['ausente']
    reg['retorno_alto'] = reg['retorno_pos_falha_longa'] & (reg['valor_original'] >= limiar_retorno)
    reg['valor_repetido'] = _valor_repetido(reg['valor_original'], min_repetidos, valor_repetido_mm) if filtrar_repetidos else False
    reg['leitura_alta'] = reg['valor_original'] >= limiar_leitura_alta
    reg['exclusao_manual'] = False

    invalido = reg['falha_longa'] | reg['valor_repetido']
    if excluir_retorno_alto:
        invalido |= reg['retorno_alto']
    reg['valido'] = ~invalido

    reg['chuva_mm'] = reg['valor_original']
    reg.loc[reg['ausente'] & reg['valido'], 'chuva_mm'] = 0.0     # vazio curto = não choveu
    reg.loc[~reg['valido'], 'chuva_mm'] = np.nan                  # falha longa, repetido, retorno alto
    return reg


def acumulados(pluv_reg: pd.DataFrame, janelas=JANELAS_PADRAO, fracao_falha_max: float = 0.0) -> pd.DataFrame:
    """Acumulados em JANELA MÓVEL: a cada instante, a chuva das últimas N horas.

    Entrada
    -------
    pluv_reg : a tabela regular de UMA estação (pluv_reg[cod], de regularizar_chuva).

    Parâmetros
    ----------
    janelas          : durações das janelas ('3h', '24h', '7D'...). Padrão JANELAS_PADRAO.
    fracao_falha_max : fração da janela, de 0 a 1, que pode estar em falha (NaN), contada em
                       intervalos de 10 min. Padrão 0: qualquer falha dentro da janela
                       invalida o acumulado. Com 0.02 numa janela de 30 dias, até 14 h de
                       falha são toleradas; o valor então é a soma do que foi medido (um
                       limite inferior da chuva real).

    Saída: tabela com o mesmo índice e uma coluna `acum_<janela>` (mm) por janela. A janela
    TERMINA no instante da linha: `acum_24h` às 15:00 é a chuva das 15:00 da véspera até as
    15:00. NaN onde a janela tem falha além da tolerância e no começo da série, antes de
    completar a primeira janela.

    Para totais por hora redonda, dia civil ou mês (blocos fixos, não móveis), use
    resolucao.reamostrar_chuva.
    """
    chuva_mm = pluv_reg['chuva_mm']
    passo = _passo(chuva_mm)
    saida = pd.DataFrame(index=chuva_mm.index)
    for janela in janelas:
        n = _n_intervalos(janela, passo)
        soma = chuva_mm.rolling(n, min_periods=1).sum()
        n_validos = chuva_mm.rolling(n, min_periods=1).count()
        completa = (n - n_validos) <= fracao_falha_max * n
        saida[f'acum_{janela}'] = soma.where(completa)
    return saida


def retornos_pos_falha(pluv_reg: pd.DataFrame) -> pd.DataFrame:
    """As primeiras leituras depois de cada falha longa, da maior para a menor.

    Entrada: a tabela regular de UMA estação (pluv_reg[cod]).
    Saída: tabela com índice `datahora` e as colunas `valor_original` (mm), `duracao_falha_h`
    (h, a duração da falha anterior) e `descartado` (True se o retorno virou NaN).
    Serve para ver se os retornos parecem acumulados do período fora do ar."""
    passo_h = _passo(pluv_reg) / pd.Timedelta('1h')
    ret = pluv_reg.loc[pluv_reg['retorno_pos_falha_longa'], ['valor_original']].copy()
    ret['duracao_falha_h'] = (pluv_reg['tamanho_bloco'].shift(1)[ret.index] * passo_h).round(2)
    ret['descartado'] = ~pluv_reg.loc[ret.index, 'valido']
    return ret.sort_values('valor_original', ascending=False)


def relatorio_falhas(pluv_reg):
    """Números de falha de uma estação.

    Entrada
    -------
    pluv_reg : o dicionário inteiro {codestacao: tabela}  -> devolve uma tabela, uma linha
               por estação; ou a tabela de UMA estação (pluv_reg[cod]) -> devolve um dicionário.

    Saída (campos): inicio, fim, total_dias, dias_com_falha_longa, dias_com_falha_%,
    n_falhas_longas, horas_em_falha, maior_falha_h, funcionamento_% (% dos intervalos com
    chuva válida), n_retornos_pos_falha, n_retornos_descartados, n_leituras_repetidas,
    mm_repetidos_descartados, maior_retorno_mm, n_leituras_altas, maximo_valido_mm,
    data_maximo_valido.
    """
    if isinstance(pluv_reg, dict):
        return pd.DataFrame({cod: relatorio_falhas(r) for cod, r in pluv_reg.items()}).T
    reg = pluv_reg
    passo_h = _passo(reg) / pd.Timedelta('1h')
    total_dias = (reg.index.max().normalize() - reg.index.min().normalize()).days + 1
    dias_falha = reg.index[reg['falha_longa']].normalize().nunique()
    blocos = reg.loc[reg['falha_longa']].groupby('grupo_falha')['tamanho_bloco'].first()
    ret = retornos_pos_falha(reg)
    validos = reg.loc[reg['valido'], 'valor_original']
    return {'inicio': reg.index.min(), 'fim': reg.index.max(), 'total_dias': total_dias,
            'dias_com_falha_longa': int(dias_falha),
            'dias_com_falha_%': round(100 * dias_falha / total_dias, 2),
            'n_falhas_longas': int(len(blocos)),
            'horas_em_falha': round(float(reg['falha_longa'].sum() * passo_h), 1),
            'maior_falha_h': round(float(blocos.max() * passo_h), 1) if len(blocos) else 0.0,
            'funcionamento_%': round(100 * reg['chuva_mm'].notna().mean(), 2),
            'n_retornos_pos_falha': int(len(ret)),
            'n_retornos_descartados': int(ret['descartado'].sum()),
            'n_leituras_repetidas': int((reg['valor_repetido'] & ~reg['ausente']).sum()),
            'mm_repetidos_descartados': round(float(reg.loc[reg['valor_repetido'], 'valor_original'].sum()), 1),
            'maior_retorno_mm': float(ret['valor_original'].max()) if len(ret) else np.nan,
            'n_leituras_altas': int(reg['leitura_alta'].sum()),
            'maximo_valido_mm': float(validos.max()) if validos.notna().any() else np.nan,
            'data_maximo_valido': validos.idxmax() if validos.notna().any() else pd.NaT}


def _percentis(chuva_diaria: pd.Series, q=(50, 90, 95, 99), limiar_chuvoso: float = 1.0) -> dict:
    """Percentis da chuva diária (mm) sobre todos os dias com dado e só sobre os dias com
    chuva (>= `limiar_chuvoso`, o limiar usual de dia chuvoso em climatologia).
    Uso interno de resumo_estacao. Devolve {'p50_dia': ..., 'p50_dia_chuvoso': ...}."""
    dias = chuva_diaria.dropna()
    chuvosos = dias[dias >= limiar_chuvoso]
    saida = {}
    for p in q:
        saida[f'p{p}_dia'] = round(float(dias.quantile(p / 100)), 1) if len(dias) else np.nan
        saida[f'p{p}_dia_chuvoso'] = round(float(chuvosos.quantile(p / 100)), 1) if len(chuvosos) else np.nan
    return saida


def resumo_estacao(pluv_reg, janelas=('1h', '3h', '6h', '12h', '24h', '36h', '48h', '72h', '7D'),
                   fracao_falha_max: float = 0.0, fracao_min_periodo: float = 0.9,
                   q=(50, 90, 95, 99), limiar_chuvoso: float = 1.0, inicio_dia: float = 0):
    """Resumo da chuva de uma estação: funcionamento, máximos, percentis e médias.

    Entrada
    -------
    pluv_reg : o dicionário inteiro {codestacao: tabela}  -> devolve uma tabela, uma linha
               por estação; ou a tabela de UMA estação (pluv_reg[cod]) -> devolve um dicionário.

    Parâmetros
    ----------
    janelas            : janelas MÓVEIS dos máximos acumulados (ver acumulados).
    fracao_falha_max   : fração, de 0 a 1, de cada janela e de cada dia que pode estar em
                         falha. Padrão 0 (qualquer falha invalida).
    fracao_min_periodo : fração mínima, de 0 a 1, de dados válidos para um mês (ou ano)
                         entrar nas médias e nos máximos mensais (anuais). Padrão 0.9.
    q                  : percentis da chuva diária. Padrão (50, 90, 95, 99).
    limiar_chuvoso     : mm a partir dos quais o dia conta como "com chuva" nos percentis
                         p<q>_dia_chuvoso. Padrão 1 mm (índices do ETCCDI).
    inicio_dia        : hora em que o dia começa, para os totais diários (ver
                         resolucao.reamostrar_chuva). Padrão 0 (dia civil).

    Saída (campos)
    -----
      funcionamento: inicio, fim, total_dias, funcionamento_%, horas_em_falha,
                     n_falhas_longas, maior_falha_h, n_retornos_pos_falha, n_leituras_altas
      leitura_max_mm, data_leitura_max   maior leitura de 10 min
      max_<janela>, data_max_<janela>    maior acumulado em cada janela móvel e quando terminou
      p<q>_dia, p<q>_dia_chuvoso         percentis da chuva diária (todos os dias válidos / só
                                         os dias com 1 mm ou mais)
      media_mensal, maximo_mensal, data_maximo_mensal, n_meses_completos
      media_anual, maximo_anual, data_maximo_anual, n_anos_completos
    Os totais diários, mensais e anuais são blocos do calendário (reamostrar_chuva).
    """
    if isinstance(pluv_reg, dict):
        return pd.DataFrame({cod: resumo_estacao(r, janelas, fracao_falha_max, fracao_min_periodo, q,
                                                 limiar_chuvoso, inicio_dia)
                             for cod, r in pluv_reg.items()}).T
    chuva = pluv_reg['chuva_mm']
    r = relatorio_falhas(pluv_reg)
    saida = {'inicio': r['inicio'], 'fim': r['fim'], 'total_dias': r['total_dias'],
             'funcionamento_%': r['funcionamento_%'], 'horas_em_falha': r['horas_em_falha'],
             'n_falhas_longas': r['n_falhas_longas'], 'maior_falha_h': r['maior_falha_h'],
             'n_retornos_pos_falha': r['n_retornos_pos_falha'], 'n_leituras_altas': r['n_leituras_altas'],
             'leitura_max_mm': float(chuva.max()) if chuva.notna().any() else np.nan,
             'data_leitura_max': chuva.idxmax() if chuva.notna().any() else pd.NaT}
    ac = acumulados(pluv_reg, janelas, fracao_falha_max)
    for janela in janelas:
        col = ac[f'acum_{janela}']
        saida[f'max_{janela}'] = round(float(col.max()), 2) if col.notna().any() else np.nan
        saida[f'data_max_{janela}'] = col.idxmax() if col.notna().any() else pd.NaT
    diaria = reamostrar_chuva(pluv_reg, '1D', fracao_falha_max, inicio_dia)['chuva_mm']
    saida.update(_percentis(diaria, q, limiar_chuvoso))
    # mês (ano) completo = no máximo (1 - fracao_min_periodo) do período em falha; o primeiro e
    # o último período da série costumam estar cortados e por isso saem da conta
    for nome, regra, formato in [('mensal', 'MS', '%Y-%m'), ('anual', 'YS', '%Y')]:
        total = reamostrar_chuva(pluv_reg, regra, 1 - fracao_min_periodo, inicio_dia)['chuva_mm'].dropna()
        saida[f'media_{nome}'] = round(float(total.mean()), 1) if len(total) else np.nan
        saida[f'maximo_{nome}'] = round(float(total.max()), 1) if len(total) else np.nan
        saida[f'data_maximo_{nome}'] = total.idxmax().strftime(formato) if len(total) else None
        saida[f'n_{"meses" if nome == "mensal" else "anos"}_completos'] = int(len(total))
    return saida
