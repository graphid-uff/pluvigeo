"""
umidade.py
==========
Diagnóstico e limpeza das séries de umidade do solo (sonda Sentek FDR, 6 profundidades)
das PCDs Geo do Cemaden. Regras e referências: docs/regras.md.

Objetos que circulam (nomes usados no notebook e na documentação)
------------------------------------------------------------------
  umid_raw    {codestacao: umidade bruta n1..n6}        <- leitura.umidade_por_estacao
              (só para olhar a série e escolher a acomodação)
  umid_clean  {codestacao: ResultadoUmidade}            <- limpar_umidade, uma estação por vez
  umid_clean[cod].operacional é a umidade limpa, a série a usar.

Ordem de uso
------------
  1. limpar_umidade(dados, cod, acomodacao=...)  aplica as regras e devolve umid_clean[cod]
  2. tabela_periodos(umid_clean[cod])            os períodos marcados, para você avaliar
  3. exclusao.excluir_periodos(umid_clean[cod], [...])   exclui à mão o que julgou espúrio
  4. resolucao.reamostrar_umidade(umid_clean[cod].operacional, '1h')   hora, dia, mês

Regras (cada uma devolve uma máscara True = leitura marcada)
------------------------------------------------------------
Falhas do equipamento (no padrão, excluir='falhas', viram NaN):
  zero exato                       (código de falha)          -> flag_zero
  acima de 60 %                    (fora da faixa física)     -> flag_faixa
  valor congelado por 24 h ou mais (datalogger repetindo)     -> flag_congelado
  queda simultânea                 (falha elétrica)           -> flag_quedas_iter
Suspeitas (no padrão só sinalizadas; excluir='todas' apaga também):
  queda isolada                                               -> flag_quedas_iter
  pico sem chuva                                              -> flag_picos
Sempre aplicada: o período de acomodação pós-instalação informado pelo usuário.
Nunca apagados, só listados: degraus e descontinuidades       -> acha_degraus, descontinuidades

Base: as regras de faixa, congelado, queda isolada, pico e degrau são ADAPTAÇÕES SIMPLIFICADAS
das categorias do controle de qualidade da ISMN (Dorigo et al., 2013, Vadose Zone J. 12(3),
doi:10.2136/vzj2012.0097): as categorias vêm do artigo, os algoritmos são mais simples e os
limiares são empíricos. Queda simultânea e acomodação são critérios só empíricos.

A chuva da própria estação (sensor 10, no mesmo arquivo do PED) é lida, regularizada e
somada por hora DENTRO de `limpar_umidade`: as regras do pico e do degrau precisam saber se
choveu. Quem já tem a chuva horária tratada pode passá-la em `pluv_h`.

Convenções
----------
* `u` é sempre um DataFrame largo: índice = datahora, colunas n1..n6, valores em %.
  Leituras irregulares no tempo são aceitas.
* `pluv_h` é a chuva horária (mm) numa grade horária regular, rotulada pelo início da hora
  (a hora 01:00 é a chuva de 01:00 a 02:00), com NaN nas horas em falha: a saída de
  resolucao.reamostrar_chuva(pluv_reg[cod], '1h')['chuva_mm'].
* Toda função `flag_*` devolve uma MÁSCARA booleana do formato de `u` (True = marcada).
  Nenhuma função altera a entrada.
* Nada é interpolado.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .chuva import regularizar_chuva
from .constantes import ID_CHUVA, NIV
from .leitura import chuva_por_estacao, umidade_por_estacao
from .resolucao import reamostrar_chuva


# ------------------------------------------------------------------------------
# Regras de detecção (cada uma devolve uma máscara True = marcada)
# ------------------------------------------------------------------------------
def flag_zero(u: pd.DataFrame) -> pd.DataFrame:
    """Zero exato. Solo nunca tem umidade 0: é o código que o equipamento envia
    quando falha (aparece em n2-n6 juntos, com n1 ausente)."""
    return u == 0


def flag_faixa(u: pd.DataFrame, maximo: float = 60.0) -> pd.DataFrame:
    """Acima do máximo físico plausível (`maximo`, em %). Nas 7 PCDs de Petrópolis,
    nenhum sensor limpo e fora da instalação passa de ~52 %; 60 % deixa margem."""
    return u > maximo


def flag_congelado(u: pd.DataFrame, duracao_min: str = '24h') -> pd.DataFrame:
    """Valor congelado: o MESMO número exato repetido por `duracao_min` ou mais.

    O Sentek informa 5 casas decimais e sempre oscila na 3a-5a casa. Repetir o
    mesmo valor por um dia inteiro indica que o datalogger está reenviando a
    última leitura (estação parada). Marca a sequência inteira.
    """
    out = pd.DataFrame(False, index=u.index, columns=u.columns)
    for n in u.columns:
        s = u[n].dropna()
        s = s[s != 0]                                   # zeros já têm regra própria
        if s.empty:
            continue
        seq = (s.diff() != 0).cumsum()                  # id de cada sequência de valores iguais
        t = s.index.to_series()
        dur = t.groupby(seq).transform('max') - t.groupby(seq).transform('min')
        out.loc[s.index[dur >= pd.Timedelta(duracao_min)], n] = True
    return out


def mediana_antes_depois(u: pd.DataFrame, k: int = 12) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mediana das k leituras ANTERIORES e das k POSTERIORES a cada ponto (sem o ponto).
    Devolve (antes, depois), duas tabelas no formato de `u`; usadas por flag_quedas e
    flag_picos.

    A janela é contada em número de leituras, e não em horas, porque a frequência
    de envio varia de 10 min (chuva) a várias horas (seca). Uma janela de 12 h na
    seca pode ter só 2-3 leituras, e a própria anomalia contaminaria a mediana.
    """
    antes = u.rolling(k, min_periods=3, closed='left').median()
    depois = u.iloc[::-1].rolling(k, min_periods=3, closed='left').median().iloc[::-1]
    return antes, depois


def flag_quedas(u: pd.DataFrame, limiar: float = 1.5, k: int = 12,
                min_niveis: int = 3) -> tuple[pd.DataFrame, pd.Series]:
    """Quedas instantâneas que voltam: leitura mais de `limiar` p.p. abaixo da mediana de
    ANTES **e** da de DEPOIS.

    Exigir as duas condições preserva a recessão normal depois de uma chuva (o solo
    desce e não volta). Fora da chuva, 99,9 % das variações entre leituras de 10 min
    ficam abaixo de ~1,4 p.p.; por isso 1,5 p.p.

    Devolve:
      por_nivel  -> máscara (datahora x nível) das quedas em cada nível
      simultanea -> Série booleana: `min_niveis` níveis ou mais caindo no mesmo instante.
                    É a assinatura elétrica (a 3 m o solo não perde água em minutos).
    """
    v = u.mask(u == 0)
    antes, depois = mediana_antes_depois(v, k)
    por_nivel = (v < antes - limiar) & (v < depois - limiar)
    simultanea = por_nivel.sum(axis=1) >= min_niveis
    return por_nivel, simultanea


def flag_quedas_iter(u: pd.DataFrame, limiar: float = 1.5, ks=(12, 24, 48),
                     min_niveis: int = 3) -> tuple[pd.DataFrame, pd.Series]:
    """`flag_quedas` em passadas sucessivas com janelas maiores (`ks`), removendo a cada
    passada o que já foi marcado. Pega rajadas longas de leituras baixas (comuns na
    04G), que numa única passada contaminam a mediana. Devolve o mesmo que flag_quedas."""
    v = u.mask(u == 0)
    por_nivel = pd.DataFrame(False, index=u.index, columns=u.columns)
    simultanea = pd.Series(False, index=u.index)
    for k in ks:
        f, s = flag_quedas(v, limiar, k, min_niveis)
        por_nivel |= f
        simultanea |= s
        v = v.mask(f).mask(s, axis=0)          # tira o que já achou antes da próxima passada
    return por_nivel, simultanea


def flag_picos(u: pd.DataFrame, pluv_h: pd.Series, limiar: float = 3.0,
               k: int = 12, horas_chuva: int = 6) -> pd.DataFrame:
    """Picos para CIMA que voltam (mais de `limiar` p.p. acima da mediana de antes e de
    depois) sem chuva nas `horas_chuva` horas anteriores: não há água para entrar no solo.

    pluv_h : chuva horária (mm) da estação, numa grade horária regular (ver o cabeçalho).
    O pico só é marcado quando a chuva das `horas_chuva` horas é CONHECIDA e igual a
    zero. Se alguma dessas horas está em falha (NaN), não dá para saber se choveu, e o
    pico fica como está.
    """
    v = u.mask(u == 0)
    antes, depois = mediana_antes_depois(v, k)
    f = (v > antes + limiar) & (v > depois + limiar)
    # min_periods = janela inteira: uma hora em falha deixa a soma NaN, e NaN == 0 é False
    soma = pluv_h.rolling(horas_chuva, min_periods=horas_chuva).sum().reindex(v.index.floor('h'))
    sem_chuva = (soma == 0).values
    return f & sem_chuva[:, None]


def acha_degraus(u: pd.DataFrame, pluv_h: pd.Series, limiar: float = 1.0,
                 k: int = 6) -> pd.DataFrame:
    """Degraus: mudança de nível de `limiar` p.p. ou mais entre duas leituras consecutivas
    (até 2 h) que PERSISTE (mediana das k leituras depois difere da das k antes, no mesmo
    sentido).

    Só entra na lista se for suspeito:
      'sem chuva'        -> chuva CONHECIDA abaixo de 1 mm nas 12 h anteriores
                            (com falha na chuva, este motivo não é atribuído);
      'profundo isolado' -> subida em n4-n6 sem que nenhuma camada acima tenha
                            subido 0,5 p.p. ou mais nas 24 h anteriores (a água precisa
                            passar pelas camadas de cima).
    Degraus NÃO são apagados: devolve uma tabela (datahora, nivel, salto, chuva12h, motivo)
    para revisão.
    """
    v = u.mask(u == 0)
    antes, depois = mediana_antes_depois(v, k)
    chuva12 = pluv_h.rolling(12, min_periods=12).sum()      # NaN se alguma hora está em falha
    vh = v.resample('h').median()
    subida24 = vh - vh.rolling('24h').min()            # quanto cada camada subiu nas últimas 24 h
    linhas = []
    for n in v.columns:
        s = v[n].dropna()
        if len(s) < 3:
            continue
        dif = s.diff()
        dt = s.index.to_series().diff()
        persiste = (depois[n] - antes[n]).reindex(s.index)
        cand = ((dif.abs() >= limiar) & (dt <= pd.Timedelta('2h'))
                & (persiste.abs() >= limiar) & (np.sign(persiste) == np.sign(dif)))
        acima = NIV[:NIV.index(n)] if n in NIV else []
        for t in s.index[cand]:
            w = float(chuva12.get(t.floor('h'), np.nan))
            motivo = None
            if w < 1.0:                                   # NaN < 1 é False: chuva desconhecida
                motivo = 'sem chuva'
            elif dif[t] > 0 and n in ('n4', 'n5', 'n6') and acima:
                r = subida24.loc[:t.floor('h'), acima].tail(1).max(axis=1)
                if len(r) and (pd.isna(r.iloc[0]) or r.iloc[0] < 0.5):
                    motivo = 'profundo isolado'
            if motivo:
                linhas.append(dict(datahora=t, nivel=n, salto=round(float(dif[t]), 2),
                                   chuva12h=round(w, 1), motivo=motivo))
    return pd.DataFrame(linhas, columns=['datahora', 'nivel', 'salto', 'chuva12h', 'motivo'])


def descontinuidades(u: pd.DataFrame, lacuna_min: str = '3D', limiar: float = 3.0,
                     min_niveis: int = 2) -> pd.DataFrame:
    """Lacunas de transmissão de `lacuna_min` ou mais depois das quais `min_niveis` níveis
    ou mais voltam mais de `limiar` p.p. diferentes (mediana das 24 h antes x 24 h depois).

    Não é erro em si: pode ter chovido ou secado na lacuna, ou a sonda pode ter sido
    reinstalada. Medida: tratar cada trecho como um segmento com normalização própria.
    Devolve uma tabela (inicio_lacuna, fim_lacuna, dias, delta_n1..delta_n6); nada é apagado.
    """
    v = u.mask(u == 0).dropna(how='all')
    t = v.index.to_series()
    lac = t.diff()
    linhas = []
    for fim in lac[lac >= pd.Timedelta(lacuna_min)].index:
        ini = t[t < fim].iloc[-1]
        dif = v[fim:fim + pd.Timedelta('24h')].median() - v[ini - pd.Timedelta('24h'):ini].median()
        if (dif.abs() > limiar).sum() >= min_niveis:
            linhas.append(dict(inicio_lacuna=ini, fim_lacuna=fim,
                               dias=round((fim - ini) / pd.Timedelta('1D'), 1),
                               **{f'delta_{n}': round(dif[n], 1) for n in v.columns}))
    return pd.DataFrame(linhas)


def intervalos(mascara: pd.Series, tolerancia: str = '2D', min_pontos: int = 1) -> pd.DataFrame:
    """Converte uma série booleana (índice datahora) em intervalos, juntando os pontos
    marcados separados por menos de `tolerancia`. Devolve uma tabela (inicio, fim,
    leituras) com os intervalos de `min_pontos` leituras ou mais. Usada por tabela_periodos."""
    t = mascara[mascara].index
    if len(t) == 0:
        return pd.DataFrame(columns=['inicio', 'fim', 'leituras'])
    grupo = (t.to_series().diff() > pd.Timedelta(tolerancia)).cumsum()
    iv = t.to_series().groupby(grupo.values).agg(['min', 'max', 'size'])
    iv.columns = ['inicio', 'fim', 'leituras']
    return iv[iv.leituras >= min_pontos].reset_index(drop=True)


# ------------------------------------------------------------------------------
# Função principal
# ------------------------------------------------------------------------------
@dataclass
class ResultadoUmidade:
    """Tudo o que `limpar_umidade` produz para UMA estação (umid_clean[cod])."""
    codestacao: str                         # código completo da estação
    bruto: pd.DataFrame                     # umidade como entrou (n1..n6, %)
    limpo: pd.DataFrame                     # NaN nas regras excluídas pelo modo e nas exclusões manuais
    operacional: pd.DataFrame               # limpo e sem a acomodação: A SÉRIE A USAR
    pluv_h: pd.Series                       # chuva horária usada nas regras (mm; NaN = falha)
    mascaras: dict = field(default_factory=dict)   # regra -> máscara (datahora x nível)
    degraus: pd.DataFrame | None = None     # para revisão (não apagados)
    descontinuidades: pd.DataFrame | None = None   # para segmentação (não apagadas)
    acomodacao: tuple | None = None         # (inicio, fim) informado
    resumo: dict = field(default_factory=dict)     # contagens (ver limpar_umidade)
    excluir: str = 'falhas'                 # modo usado: 'falhas', 'todas' ou 'nenhuma'
    excluidas: tuple = ()                   # regras que viraram NaN; as demais só sinalizam


# Regras de FALHA: falha inequívoca do equipamento. Zero, fora da faixa e congelado são
# impossíveis num sensor funcionando; a queda simultânea (3 ou mais profundidades caindo no
# mesmo instante) é empírica, mas é uma assinatura elétrica identificada pelo autor em anos de
# trabalho com estes dados: a 3 m o solo não perde água em minutos.
# Regras SUSPEITAS: o comportamento é estranho, mas pode ser real; o usuário decide
# (exclusao.excluir_periodos).
REGRAS_FALHA = ('zero', 'faixa', 'congelado', 'queda_simultanea')
REGRAS_SUSPEITA = ('queda_isolada', 'pico')
MODOS_EXCLUSAO = {'falhas': REGRAS_FALHA, 'todas': REGRAS_FALHA + REGRAS_SUSPEITA, 'nenhuma': ()}


def _chuva_horaria(dados: pd.DataFrame, codestacao: str) -> pd.Series:
    """Chuva horária (mm) de uma estação, tirada da tabela de `leitura.ler_dados`:
    regularizar_chuva (padrões) e soma por hora (resolucao.reamostrar_chuva).
    Horas com falha ficam NaN. Erro se a estação não tem o sensor de chuva."""
    pluv_raw = chuva_por_estacao(dados[dados.codestacao == codestacao])
    if codestacao not in pluv_raw:
        raise ValueError(f'{codestacao}: sensor de chuva (id {ID_CHUVA}) não encontrado nos dados. '
                         'A limpeza da umidade usa a chuva da própria estação: leia o arquivo do PED '
                         'com todos os sensores (sem filtrar `sensores` em ler_dados), ou passe a '
                         'chuva horária em `pluv_h`.')
    return reamostrar_chuva(regularizar_chuva(pluv_raw[codestacao]), '1h')['chuva_mm']


def _montar(u: pd.DataFrame, mascaras: dict, excluidas: tuple, acomodacao) -> tuple:
    """A partir das máscaras, monta (limpo, operacional, resumo). Usada por limpar_umidade
    e, depois de uma exclusão manual, por exclusao.excluir_periodos."""
    marcada = pd.DataFrame(False, index=u.index, columns=u.columns)
    apagar = marcada.copy()
    for k, f in mascaras.items():
        f = f.reindex_like(marcada).fillna(False).astype(bool)
        marcada |= f
        if k in excluidas:
            apagar |= f
    limpo = u.mask(apagar)
    operacional = limpo.copy()
    if acomodacao is not None:
        operacional.loc[acomodacao[0]:acomodacao[1]] = np.nan

    tem = u.notna()
    tot = int(tem.values.sum())
    resumo = {'leituras': tot,
              'espurias': int((marcada & tem).values.sum()),
              'espurias_%': round(100 * (marcada & tem).values.sum() / max(tot, 1), 1),
              'excluidas': int((apagar & tem).values.sum()),
              'excluidas_%': round(100 * (apagar & tem).values.sum() / max(tot, 1), 1),
              'so_sinalizadas': int((marcada & ~apagar & tem).values.sum()),
              'em_acomodacao': int(u.loc[acomodacao[0]:acomodacao[1]].notna().values.sum()) if acomodacao else 0,
              **{f'n_{k}': int((v & tem).values.sum()) for k, v in mascaras.items()}}
    return limpo, operacional, resumo


def limpar_umidade(dados: pd.DataFrame,
                   codestacao: str,
                   acomodacao: tuple[str, str] | None = None,
                   maximo: float = 60.0,
                   congelado_min: str = '24h',
                   limiar_queda: float = 1.5,
                   limiar_pico: float = 3.0,
                   excluir: str = 'falhas',
                   pluv_h: pd.Series | None = None) -> ResultadoUmidade:
    """Diagnostica e limpa a umidade de UMA estação, direto da tabela de `leitura.ler_dados`.

    Entrada
    -------
    dados      : tabela padronizada de leitura.ler_dados com a umidade (n1..n6) e a chuva
                 (sensor 10) da estação; nas PCDs Geo as duas vêm no mesmo arquivo do PED.
                 Leia o arquivo sem filtrar `sensores`.
    codestacao : código completo da estação (ex.: '330390605G').

    Parâmetros
    ----------
    acomodacao    : (inicio, fim) do período de acomodação pós-instalação, a excluir sempre.
                    Escolha olhando a série bruta em figuras.serie_umidade_interativo.
    maximo        : % acima do qual a leitura é falha (fora da faixa). Padrão 60.
    congelado_min : duração mínima do mesmo valor exato para ser "congelado". Padrão '24h'.
    limiar_queda  : p.p. da queda que volta (isolada ou simultânea). Padrão 1,5.
    limiar_pico   : p.p. do pico sem chuva. Padrão 3,0.
    excluir       : o que as regras apagam (viram NaN) sozinhas:
                    'falhas'  (padrão) -> só as falhas do equipamento (REGRAS_FALHA): zero,
                                          acima do máximo, congelado, queda simultânea;
                    'todas'            -> também as suspeitas (pico, queda isolada);
                    'nenhuma'          -> nada; todas as regras só sinalizam.
                    O que não é apagado continua marcado em `mascaras` e em tabela_periodos,
                    para você avaliar e excluir com exclusao.excluir_periodos.
    pluv_h        : chuva horária já tratada (opcional), no formato descrito no cabeçalho do
                    módulo. Padrão None: a função busca o sensor 10 da estação em `dados`,
                    regulariza com os padrões de chuva.regularizar_chuva e soma por hora.

    Saída: ResultadoUmidade (umid_clean[cod]), com os campos
    -----
      codestacao        o código da estação
      bruto             a umidade como entrou (n1..n6, %)
      limpo             NaN nas leituras das regras excluídas e nas exclusões manuais
      operacional       `limpo` sem a acomodação: A SÉRIE A USAR
      pluv_h            a chuva horária usada nas regras (mm; NaN nas horas em falha)
      mascaras          {regra: máscara}: zero, faixa, congelado, queda_simultanea,
                        queda_isolada, pico, exclusao_manual (onde cada regra marcou)
      degraus, descontinuidades   mudanças de patamar, só listadas
      acomodacao        o período informado
      resumo            leituras, espurias (marcadas por alguma regra), espurias_%, excluidas
                        (viraram NaN), excluidas_%,
                        so_sinalizadas, em_acomodacao, n_<regra>, n_degraus, n_descontinuidades
      excluir, excluidas   o modo usado e as regras que viraram NaN

    Nota: o resultado não traz séries horárias nem diárias. Para mudar a resolução, use
    resolucao.reamostrar_umidade(umid_clean[cod].operacional, '1h').

    Erro (ValueError) se a estação não tem umidade, se não tem o sensor de chuva (e
    `pluv_h` não foi dado), ou se o modo de exclusão não existe.
    """
    if excluir not in MODOS_EXCLUSAO:
        raise ValueError(f"excluir deve ser 'falhas', 'todas' ou 'nenhuma' (veio {excluir!r})")
    umid_raw = umidade_por_estacao(dados[dados.codestacao == codestacao])
    if codestacao not in umid_raw:
        raise ValueError(f'{codestacao}: nenhum sensor de umidade (n1..n6) nos dados.')
    if pluv_h is None:
        pluv_h = _chuva_horaria(dados, codestacao)
    u = umid_raw[codestacao].reindex(columns=NIV)

    m = {}
    m['zero'] = flag_zero(u)
    m['faixa'] = flag_faixa(u, maximo)
    m['congelado'] = flag_congelado(u, congelado_min)
    q, simult = flag_quedas_iter(u, limiar_queda)
    # a queda simultânea apaga o instante inteiro (todos os níveis com leitura)
    m['queda_simultanea'] = pd.DataFrame(np.repeat(simult.values[:, None], u.shape[1], axis=1),
                                         index=u.index, columns=u.columns) & u.notna()
    m['queda_isolada'] = q & ~m['queda_simultanea']
    m['pico'] = flag_picos(u, pluv_h, limiar_pico)
    m['exclusao_manual'] = pd.DataFrame(False, index=u.index, columns=u.columns)   # ver excluir_periodos

    excluidas = MODOS_EXCLUSAO[excluir] + ('exclusao_manual',)
    limpo, operacional, resumo = _montar(u, m, excluidas, acomodacao)

    # degraus e descontinuidades: calculados sobre o dado já sem congelados/quedas
    deg = acha_degraus(u.mask(m['congelado'] | m['queda_simultanea'] | q), pluv_h)
    desc = descontinuidades(u.mask(m['congelado']))
    resumo.update(n_degraus=len(deg), n_descontinuidades=len(desc))
    return ResultadoUmidade(codestacao=codestacao, bruto=u, limpo=limpo, operacional=operacional, pluv_h=pluv_h,
                            mascaras=m, degraus=deg, descontinuidades=desc, acomodacao=acomodacao,
                            resumo=resumo, excluir=excluir, excluidas=excluidas)


# ------------------------------------------------------------------------------
# Tabela de períodos
# ------------------------------------------------------------------------------
MEDIDAS = {
    'acomodação': 'excluída: sensor ainda se acomodando',
    'congelado (longo)': 'falha: estação parada repetindo a última leitura',
    'congelado (curto)': 'falha: valor repetido',
    'zero (falha)': 'falha: não interpolar',
    'queda simultânea': 'falha elétrica',
    'queda isolada': 'suspeita: avaliar; se for espúria, excluir com exclusao.excluir_periodos',
    'fora de faixa': 'falha: acima do máximo físico',
    'pico sem chuva': 'suspeita: avaliar; se for espúrio, excluir com exclusao.excluir_periodos',
    'exclusão manual': 'excluída pelo usuário',
    'degrau sem chuva': 'avaliar; se o nível não volta, tratar como novo segmento',
    'descontinuidade após lacuna': 'novo segmento (normalizar separado)',
}

# Para a tabela ficar legível, pontos marcados próximos no tempo viram um período só.
# (regra, tipo na tabela, distância máxima entre pontos do mesmo período, mínimo de leituras)
# Estes valores só agrupam a tabela; não mudam o que é marcado nem o que é excluído.
AGRUPAMENTO = [('zero', 'zero (falha)', '3D', 3), ('queda_simultanea', 'queda simultânea', '15D', 3),
               ('faixa', 'fora de faixa', '3D', 1), ('pico', 'pico sem chuva', '3D', 1),
               ('queda_isolada', 'queda isolada', '30D', 5), ('exclusao_manual', 'exclusão manual', '1D', 1)]


def tabela_periodos(umid_clean: ResultadoUmidade) -> pd.DataFrame:
    """Resume as marcações de `limpar_umidade` em episódios legíveis.

    As regras marcam leitura por leitura (milhares de marcas em `mascaras`). Esta função
    junta as leituras marcadas próximas no tempo num período só (as distâncias estão em
    AGRUPAMENTO, ex.: zeros a menos de 3 dias um do outro) e acrescenta a acomodação, os
    degraus (agrupados por mês) e as descontinuidades. Serve para você ler algumas dezenas
    de linhas e decidir o que excluir com exclusao.excluir_periodos.

    Entrada: umid_clean[cod], o resultado de limpar_umidade de UMA estação.

    Saída: tabela, uma linha por período, ordenada pelo início, com as colunas
      estacao, tipo, inicio, fim, niveis (níveis afetados), leituras (quantas),
      excluida (True = virou NaN; False = só sinalizada), medida (o que fazer) e,
      se houver acomodação, dentro_da_acomodacao.
    """
    res = umid_clean
    linhas = []
    u = res.bruto

    def add(tipo, a, b, niveis, n, excluida):
        linhas.append(dict(estacao=res.codestacao, tipo=tipo, inicio=pd.Timestamp(a), fim=pd.Timestamp(b),
                           niveis=niveis, leituras=int(n), excluida=excluida, medida=MEDIDAS.get(tipo, '')))

    if res.acomodacao:
        a, b = res.acomodacao
        add('acomodação', max(pd.Timestamp(a), u.index.min()), b, 'todos', u.loc[a:b].notna().values.sum(), True)
    for chave, tipo, tol, mp in AGRUPAMENTO:
        f = res.mascaras[chave]
        for _, x in intervalos(f.any(axis=1), tol, mp).iterrows():
            lv = f.loc[x.inicio:x.fim].sum()
            lv = lv[lv > 0]
            add(tipo, x.inicio, x.fim, ','.join(lv.index), lv.sum(), chave in res.excluidas)
    f = res.mascaras['congelado']
    for _, x in intervalos(f.any(axis=1), '3D').iterrows():
        lv = f.loc[x.inicio:x.fim].sum()
        lv = lv[lv > 0]
        longo = (x.fim - x.inicio) > pd.Timedelta('7D') and len(lv) >= 3   # estação parada
        add('congelado (longo)' if longo else 'congelado (curto)', x.inicio, x.fim, ','.join(lv.index), lv.sum(),
            'congelado' in res.excluidas)
    for _, g in (res.descontinuidades if res.descontinuidades is not None else pd.DataFrame()).iterrows():
        saltos = ' '.join(f'{n}:{g["delta_" + n]:+.0f}' for n in NIV if pd.notna(g.get('delta_' + n)))
        add('descontinuidade após lacuna', g.inicio_lacuna, g.fim_lacuna, saltos, 0, False)
    deg = res.degraus
    if deg is not None and len(deg):
        for _, g in deg.groupby(deg.datahora.dt.to_period('M')):
            add('degrau sem chuva', g.datahora.min(), g.datahora.max(), ','.join(sorted(g.nivel.unique())), len(g), False)
    T = pd.DataFrame(linhas)
    if len(T) and res.acomodacao:
        fim_acom = pd.Timestamp(res.acomodacao[1])
        T['dentro_da_acomodacao'] = (T.tipo != 'acomodação') & (T.fim <= fim_acom)
    return T.sort_values('inicio').reset_index(drop=True) if len(T) else T
