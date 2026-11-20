"""
exclusao.py
===========
Exclusão manual: retira leituras ou períodos que você identificou como espúrios e que
nenhuma regra automática pegou (ou que as regras só sinalizaram como suspeitos). Uma função
só, para a chuva e para a umidade:

  excluir_periodos(pluv_reg[cod], exclusoes)    -> nova tabela regular de chuva
  excluir_periodos(umid_clean[cod], exclusoes)  -> novo resultado da limpeza da umidade

A entrada nunca é alterada: a função devolve uma cópia. A exclusão fica registrada (coluna
`exclusao_manual` na chuva; máscara `exclusao_manual` e `resumo` na umidade), e a lista `exclusoes` fica no seu notebook, como registro da decisão.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .constantes import NIV
from .umidade import ResultadoUmidade, _montar


def _itens(exclusoes) -> list[tuple]:
    """Padroniza cada item da lista em (inicio, fim, niveis ou None)."""
    itens = []
    for item in exclusoes:
        if isinstance(item, (tuple, list)):
            if len(item) == 2:
                itens.append((pd.Timestamp(item[0]), pd.Timestamp(item[1]), None))
            elif len(item) == 3:
                niveis = [item[2]] if isinstance(item[2], str) else list(item[2])
                itens.append((pd.Timestamp(item[0]), pd.Timestamp(item[1]), niveis))
            else:
                raise ValueError(f'item de exclusão inválido: {item!r}; use instante, (inicio, fim) '
                                 'ou (inicio, fim, niveis)')
        else:                                       # um instante só
            t = pd.Timestamp(item)
            itens.append((t, t, None))
    return itens


def excluir_periodos(dado, exclusoes: list):
    """Exclui (transforma em NaN) as leituras dos períodos indicados e registra a exclusão.

    Entrada
    -------
    dado      : a chuva ou a umidade de UMA estação:
                - pluv_reg[cod]   (tabela de chuva.regularizar_chuva), ou
                - umid_clean[cod] (resultado de umidade.limpar_umidade).
    exclusoes : lista de itens, cada um em uma destas formas:
                - um instante:            '2023-09-18 17:00'
                - um intervalo:           ('2023-09-18 16:00', '2023-09-18 18:00')
                - um intervalo e níveis:  ('2023-09-18 16:00', '2023-09-18 18:00', ['n1', 'n2'])
                  (só para a umidade). Sem a lista de níveis, a exclusão vale para TODAS as
                  profundidades.
                Os limites entram na exclusão. As datas estão no mesmo fuso dos dados lidos.

    Saída: um novo objeto do mesmo tipo da entrada, com a exclusão aplicada
    -----
      chuva   : chuva_mm = NaN, valido = False e exclusao_manual = True nos instantes.
      umidade : a máscara `exclusao_manual` ganha as leituras; `limpo`, `operacional` e `resumo`
                são refeitos.
    """
    itens = _itens(exclusoes)
    if isinstance(dado, ResultadoUmidade):
        u = dado.bruto
        mascaras = dict(dado.mascaras)
        exc = mascaras['exclusao_manual'].copy()
        for a, b, niveis in itens:
            colunas = niveis or list(u.columns)
            desconhecidos = set(colunas) - set(NIV)
            if desconhecidos:
                raise ValueError(f'níveis desconhecidos: {sorted(desconhecidos)}; use {NIV}')
            exc.loc[a:b, colunas] = exc.loc[a:b, colunas] | u.loc[a:b, colunas].notna()
        mascaras['exclusao_manual'] = exc
        limpo, operacional, resumo = _montar(u, mascaras, dado.excluidas, dado.acomodacao)
        resumo.update(n_degraus=dado.resumo.get('n_degraus', 0),
                      n_descontinuidades=dado.resumo.get('n_descontinuidades', 0))
        return replace(dado, mascaras=mascaras, limpo=limpo, operacional=operacional, resumo=resumo)

    if isinstance(dado, pd.DataFrame) and 'chuva_mm' in dado.columns:
        reg = dado.copy()
        for a, b, niveis in itens:
            if niveis:
                raise ValueError('a chuva não tem níveis: use só (inicio, fim)')
            alvo = reg.loc[a:b].index
            reg.loc[alvo, 'chuva_mm'] = np.nan
            reg.loc[alvo, 'valido'] = False
            reg.loc[alvo, 'exclusao_manual'] = True
        return reg

    raise TypeError('excluir_periodos recebe pluv_reg[cod] (chuva.regularizar_chuva) '
                    'ou umid_clean[cod] (umidade.limpar_umidade)')
