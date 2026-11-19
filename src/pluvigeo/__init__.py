"""
pluvigeo
========
Biblioteca do GRAPHID (Projeto SALAD) para dados de chuva e umidade do solo do Cemaden.
É um trabalho independente, sem vínculo com o Cemaden.

Faz três coisas: diagnóstico de integridade, ajuste da resolução temporal e plotagem.

Módulos, na ordem do processamento
----------------------------------
leitura     PED e mapa interativo -> mesma tabela padronizada (dados); fuso; inventário
chuva       chuva em grade de 10 min (pluv_reg): falhas, acumulados móveis, resumos
umidade     regras de leituras espúrias da umidade e limpeza (umid_clean)
exclusao    exclusão manual de períodos, para a chuva e para a umidade
resolucao   blocos de hora, dia, mês: soma da chuva (pluv_rs) e média da umidade (umid_rs)
figuras     figuras (matplotlib; as de sufixo _interativo usam plotly)
constantes  dicionário de sensores do Cemaden

Regras, padrões e referências: docs/regras.md. Entradas e saídas: docs/funcoes.md.
Exemplo de uso: exemplos/exemplo_uso_pluvigeo.ipynb.
"""
__version__ = '0.1.0'
