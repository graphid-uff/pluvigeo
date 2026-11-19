"""
leitura.py
==========
Leitura dos dois formatos de dados do Cemaden, com a mesma saída para ambos.

Formatos de entrada
-------------------
PED (Plataforma de Entrega de Dados): um CSV por estação, formato longo, separador
vírgula e decimal ponto, com as colunas

    cidade, codestacao, datahora, id_sensor, latitude, longitude, nome, offset,
    qualificacao, uf, valor

Mapa interativo: um CSV por mês com todas as estações do município, só chuva,
separador ponto e vírgula e decimal vírgula, com as colunas

    municipio, codEstacao, uf, nomeEstacao, latitude, longitude, datahora, valorMedida

Tabela padronizada (saída de ler_dados)
---------------------------------------
    codestacao    código completo da estação, ex.: '330390612A'
    nome          nome da estação
    datahora      instante da transmissão, já no fuso escolhido (ver FUSO_PADRAO)
    id_sensor     10 = chuva (mm por registro); demais em constantes.DICIONARIO_SENSORES
    valor         mm para chuva, % para umidade
    qualificacao  como veio no PED (significado desconhecido; não é usada); NaN no mapa

Junto vem a tabela de estações (uma linha por estação): codestacao, nome, municipio,
uf, latitude, longitude.

Funções (na ordem de uso)
------------------------
  ler_dados            -> arquivo, pasta ou lista, de qualquer formato -> dados, estacoes, n_duplicadas
  inventario_dados     -> resumo por estação de uma tabela padronizada
  chuva_por_estacao    -> dados -> pluv_raw = {codestacao: série de chuva}  (vai para chuva.regularizar_chuva)
  umidade_por_estacao  -> dados -> umid_raw = {codestacao: umidade n1..n6}  (vai para as figuras,
                          para escolher a acomodação; umidade.limpar_umidade lê direto de `dados`)

As estações são identificadas sempre pelo código completo (ex.: '330390612A'), que não se
repete entre municípios e estados.

Fuso horário
------------
Os arquivos do Cemaden vêm em UTC (conferido: o total diário do sensor 600 fecha com a
soma das 24 h que terminam à 00:00 do arquivo, e a chuva de 15/02/2022 em Petrópolis
aparece entre 19 h e 22 h). `ler_dados` recebe `fuso`, o número de horas a somar ao
horário do arquivo. O padrão é -3 (horário de Brasília, fixo, sem horário de verão,
para a série não ter horas repetidas nem faltando). Use fuso=0 para manter o UTC.

A transmissão é irregular: 10 min durante chuva, horária ou mais esparsa sem chuva.
"""
from __future__ import annotations

import gzip
import re
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from .constantes import ID_CHUVA, IDS_CONHECIDOS, MAPA_UMIDADE, NIV

# Horas somadas ao horário dos arquivos (que vêm em UTC). -3 = horário de Brasília.
FUSO_PADRAO = -3

COLUNAS_PADRAO = ['codestacao', 'nome', 'datahora', 'id_sensor', 'valor', 'qualificacao']
COLUNAS_ESTACOES = ['codestacao', 'nome', 'municipio', 'uf', 'latitude', 'longitude']


class Leitura(NamedTuple):
    """Resultado de ler_dados. Pode ser desempacotado:
    dados, estacoes, n_duplicadas = ler_dados(caminho)"""
    dados: pd.DataFrame        # tabela padronizada (COLUNAS_PADRAO)
    estacoes: pd.DataFrame     # uma linha por estação (COLUNAS_ESTACOES)
    n_duplicadas: int          # linhas repetidas removidas


# ==============================================================================
# Um arquivo de cada formato -> as mesmas colunas, ainda em UTC e com duplicatas
# ==============================================================================
def _detectar_formato(caminho: str | Path) -> str:
    """Olha só o cabeçalho do arquivo e devolve 'ped' ou 'mapa_interativo'."""
    # arquivos .gz (compactados) são lidos direto; utf-8-sig descarta o BOM do mapa
    abrir = gzip.open if str(caminho).endswith('.gz') else open
    with abrir(caminho, 'rt', encoding='utf-8-sig') as f:
        cabecalho = f.readline()
    if 'valorMedida' in cabecalho and 'codEstacao' in cabecalho:
        return 'mapa_interativo'
    if 'id_sensor' in cabecalho and 'codestacao' in cabecalho:
        return 'ped'
    raise ValueError(f'formato não reconhecido em {caminho}; cabeçalho: {cabecalho.strip()!r}')


def _ler_ped(caminho: str | Path) -> pd.DataFrame:
    """Um arquivo do PED -> colunas padronizadas mais as da tabela de estações."""
    df = pd.read_csv(caminho, parse_dates=['datahora'], dtype={'codestacao': str})
    df = df.rename(columns={'cidade': 'municipio'})
    return df[COLUNAS_PADRAO + ['municipio', 'uf', 'latitude', 'longitude']]


def _ler_mapa_interativo(caminho: str | Path) -> pd.DataFrame:
    """Um arquivo mensal do mapa interativo -> colunas padronizadas mais as da tabela de estações.

    Particularidades tratadas (todas encontradas nos arquivos de Petrópolis, 2014-2024):
      - separador ';' e decimal ','; BOM no início; fim de linha do Windows;
      - um ';' sobrando no fim de cada linha (por isso index_col=False, como no script
        agregador original: sem ele o pandas usaria a primeira coluna como índice);
      - ordem das colunas diferente em alguns arquivos de 2015 (as colunas são lidas pelo nome);
      - data como dd/mm/aaaa nos arquivos mais antigos e aaaa-mm-dd depois (decidido pelo
        conteúdo do arquivo, não por uma lista de meses);
      - meses só com o cabeçalho (devolve tabela vazia).
    """
    df = pd.read_csv(caminho, sep=';', decimal=',', index_col=False, encoding='utf-8-sig',
                     dtype={'codEstacao': str, 'datahora': str})
    df = df.rename(columns={'codEstacao': 'codestacao', 'nomeEstacao': 'nome', 'valorMedida': 'valor'})
    texto = df['datahora'].str.strip()
    if len(texto) and re.match(r'\d{2}/\d{2}/\d{4}', texto.iloc[0]):
        df['datahora'] = pd.to_datetime(texto, format='%d/%m/%Y %H:%M:%S')
    else:
        df['datahora'] = pd.to_datetime(texto, format='ISO8601')
    for col in ['valor', 'latitude', 'longitude']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['id_sensor'] = 10                  # o mapa interativo só traz chuva
    df['qualificacao'] = float('nan')     # coluna que só existe no PED
    return df[COLUNAS_PADRAO + ['municipio', 'uf', 'latitude', 'longitude']]


def _lista_arquivos(caminho, padrao: str = '*.csv*') -> list[Path]:
    """Arquivo, pasta ou lista (de arquivos e pastas) -> lista ordenada de arquivos."""
    if isinstance(caminho, (list, tuple)):
        achados = [a for c in caminho for a in _lista_arquivos(c, padrao)]
    elif Path(caminho).is_dir():
        achados = sorted(Path(caminho).glob(padrao))
    else:
        achados = [Path(caminho)]
    if not achados:
        raise FileNotFoundError(f'nenhum arquivo {padrao} em {caminho}')
    return achados


def _tabela_estacoes(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por estação. Quando nome ou coordenadas mudam ao longo do tempo, fica o
    registro MAIS RECENTE (os arquivos novos trazem as coordenadas com mais casas decimais).

    Também destroca latitude e longitude: em parte dos arquivos do mapa interativo as duas
    colunas vêm invertidas (ex.: latitude -43,171 e longitude -22,53 em Petrópolis). No
    Brasil continental toda longitude é menor que -34,7 e nenhuma latitude é menor que
    -33,8; então uma "latitude" abaixo de -34,7 com "longitude" acima disso só pode ser troca."""
    est = (df.sort_values('datahora').drop_duplicates('codestacao', keep='last')
             [COLUNAS_ESTACOES].sort_values('codestacao').reset_index(drop=True))
    trocado = (est.latitude < -34.7) & (est.longitude > -34.7)
    est.loc[trocado, ['latitude', 'longitude']] = est.loc[trocado, ['longitude', 'latitude']].values
    return est


# ==============================================================================
# Leitura padronizada
# ==============================================================================
def ler_dados(caminho: str | Path | list, fuso: float = FUSO_PADRAO, sensores: list | None = None,
              padrao: str = '*.csv*') -> Leitura:
    """Lê arquivos do Cemaden, do PED ou do mapa interativo, e junta tudo numa tabela padronizada.

    Entrada
    -------
    caminho  : um arquivo, uma pasta ou uma lista de arquivos e pastas, em CSV ou em CSV
               compactado (.csv.gz). Os dois formatos podem vir misturados: cada arquivo é
               reconhecido pelo cabeçalho.

    Parâmetros
    ----------
    fuso     : horas a somar ao horário do arquivo, que vem em UTC. Padrão -3 (Brasília, fixo,
               sem horário de verão); 0 mantém o UTC.
    sensores : lista de id_sensor a manter; os outros são descartados já na leitura, arquivo
               por arquivo. Ex.: [10] lê só a chuva, o que economiza memória em pastas grandes
               do PED, onde a umidade ocupa a maior parte das linhas. Padrão None: todos.
               Atenção: umidade.limpar_umidade precisa da umidade E da chuva (sensor 10) da
               estação; para ela, leia sem filtrar.
    padrao   : quais arquivos ler de uma pasta. Padrão '*.csv*': os CSV e os CSV compactados
               (.csv.gz), que são lidos direto, sem descompactar antes.

    Saída: Leitura, que se desempacota em três
    -----
      dados        tabela padronizada (ver o cabeçalho do módulo) -> vai para inventario_dados,
                   chuva_por_estacao, umidade_por_estacao e umidade.limpar_umidade
      estacoes     uma linha por estação: codestacao, nome, municipio, uf, latitude, longitude
      n_duplicadas nº de linhas repetidas removidas (mesma estação, instante e sensor, inclusive
                   quando a mesma medida aparece nos dois formatos)
    """
    partes = []
    for arq in _lista_arquivos(caminho, padrao):
        df = _ler_ped(arq) if _detectar_formato(arq) == 'ped' else _ler_mapa_interativo(arq)
        if sensores is not None:
            df = df[df.id_sensor.isin(sensores)]
        if len(df):
            partes.append(df)
    if not partes:
        return Leitura(pd.DataFrame(columns=COLUNAS_PADRAO), pd.DataFrame(columns=COLUNAS_ESTACOES), 0)
    df = pd.concat(partes, ignore_index=True)
    repetidas = df.duplicated(['codestacao', 'datahora', 'id_sensor'])
    df = df[~repetidas]
    if fuso:
        df['datahora'] = df['datahora'] + pd.Timedelta(hours=fuso)
    dados = df[COLUNAS_PADRAO].sort_values(['codestacao', 'id_sensor', 'datahora']).reset_index(drop=True)
    return Leitura(dados, _tabela_estacoes(df), int(repetidas.sum()))


def chuva_por_estacao(dados: pd.DataFrame, id_chuva: int = ID_CHUVA) -> dict[str, pd.Series]:
    """Separa a chuva de cada estação.

    Entrada : dados (tabela padronizada de ler_dados), com o sensor de chuva.
    Parâmetro: id_chuva, o id do sensor de chuva. Padrão 10.
    Saída   : pluv_raw = {codestacao: série de chuva bruta}, em mm por registro, com índice
              datahora irregular (como a estação transmitiu). Vai para chuva.regularizar_chuva.
    """
    ch = dados[dados.id_sensor == id_chuva]
    return {cod: g.set_index('datahora')['valor'].sort_index().rename(cod)
            for cod, g in ch.groupby('codestacao')}


def umidade_por_estacao(dados: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Separa a umidade bruta de cada PCD Geo, em formato largo.

    Entrada : dados (tabela padronizada de ler_dados), com os sensores de umidade.
    Saída   : umid_raw = {codestacao: tabela}, só das estações que têm umidade. Cada tabela tem
              índice datahora e colunas n1..n6 (%, de 0,5 m a 3,0 m de profundidade), como
              vieram, sem limpeza.

    Serve para olhar a série bruta (figuras.serie_umidade_interativo) e escolher o período de
    acomodação dos sensores. A limpeza (umidade.limpar_umidade) NÃO usa esta saída: ela lê a
    umidade e a chuva direto de `dados`.
    """
    um = dados[dados.id_sensor.isin(MAPA_UMIDADE)]
    saida = {}
    for cod, g in um.groupby('codestacao'):
        saida[cod] = (g.pivot(index='datahora', columns='id_sensor', values='valor')
                       .rename(columns=MAPA_UMIDADE).reindex(columns=NIV).sort_index())
        saida[cod].columns.name = None
    return saida


def inventario_dados(dados: pd.DataFrame, estacoes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Resumo por estação de uma tabela padronizada (vale para os dois formatos).

    Entrada  : dados (tabela padronizada de ler_dados).
    Parâmetro: estacoes, a tabela de estações de ler_dados (opcional). Se for dada, o
               inventário ganha as colunas municipio, uf, latitude e longitude.
    Saída    : tabela, uma linha por estação, com codestacao, tipo ('PCD Geo' ou
               'pluviômetro'), inicio, fim, linhas, tem_umidade, sensores (ids presentes) e
               ids_desconhecidos. Esta última lista os ids que não estão em
               constantes.IDS_CONHECIDOS: um id novo pode indicar mudança no formato do Cemaden.
    """
    linhas = []
    for cod, g in dados.groupby('codestacao'):
        ids = sorted(int(i) for i in g.id_sensor.unique())
        linhas.append(dict(codestacao=cod,
                           tipo='PCD Geo' if str(cod).upper().endswith('G') else 'pluviômetro',
                           inicio=g.datahora.min(), fim=g.datahora.max(), linhas=len(g),
                           tem_umidade=any(i in MAPA_UMIDADE for i in ids), sensores=ids,
                           ids_desconhecidos=sorted(set(ids) - IDS_CONHECIDOS)))
    inv = pd.DataFrame(linhas)
    if estacoes is not None and len(inv):
        inv = inv.merge(estacoes.drop(columns='nome', errors='ignore'), on='codestacao', how='left')
    return inv
