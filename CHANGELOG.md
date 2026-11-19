# Histórico de versões

Todas as mudanças relevantes da pluvigeo ficam registradas aqui. As versões seguem o
[versionamento semântico](https://semver.org/lang/pt-BR/): enquanto o número começar com 0, a
biblioteca está em desenvolvimento e os nomes de funções e parâmetros ainda podem mudar.

## [0.1.0] - ainda não publicada

Primeira versão pública. Antes dela houve versões internas, usadas só no Projeto SALAD.

### O que a biblioteca faz

- **Leitura** dos dois formatos do Cemaden (PED e mapa interativo), em CSV ou CSV compactado
  (`.csv.gz`), numa tabela padronizada, com conversão de UTC para o horário de Brasília e remoção
  de linhas repetidas (`leitura`).
- **Diagnóstico da chuva** em grade regular de 10 min: falha longa, retorno alto depois de falha,
  ruído de valor repetido e leitura alta; relatório de falhas, acumulados em janela móvel e resumo
  da estação (`chuva`).
- **Diagnóstico e limpeza da umidade do solo** das PCDs Geo, com regras de falha do equipamento
  (zero, fora da faixa, valor congelado, queda simultânea) e suspeitas (pico sem chuva, queda
  isolada), período de acomodação e tabela de períodos marcados (`umidade`).
- **Exclusão manual** de instantes e períodos, a mesma para chuva e umidade, com escolha de
  níveis na umidade (`exclusao`).
- **Ajuste da resolução temporal** em blocos fixos do calendário (hora, dia civil, mês), sem
  esconder as falhas (`resolucao`).
- **Figuras** de chuva e umidade no tempo, com versões interativas, e da situação das estações
  (`figuras`).
