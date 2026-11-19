# Regras de integridade da pluvigeo

Este documento lista cada regra que a biblioteca aplica, o valor padrão, de onde ele vem e a
função que o implementa. Todo limiar é um parâmetro: o padrão pode ser trocado na chamada.

## Aviso sobre a origem das regras

As regras têm três origens diferentes, marcadas em cada linha:

- **Referência**: a regra, e às vezes o próprio número, existe em uma referência publicada.
- **Formato**: a regra decorre de como o Cemaden transmite e grava os dados, conforme observado
  nos próprios arquivos.
- **Empírico**: o valor foi obtido por experimentação com os dados das 7 PCDs Geo e dos
  pluviômetros automáticos de Petrópolis/RJ (2015–2026). Não há referência que sustente o número.
  Ele pode não servir para outro município, outro solo ou outro equipamento, e deve ser
  reavaliado antes de ser usado fora desse contexto.

Em vários casos a **ideia** da regra tem referência, mas o **número** é empírico. As tabelas
separam as duas coisas.

A limpeza nunca corrige valores: ela mascara com NaN e guarda o motivo. Nada é interpolado.
A coluna `qualificacao` do PED é lida e preservada, mas não é usada, porque o significado dos
seus códigos é desconhecido.

## Chuva (`chuva.py`)

O diagnóstico é feito uma estação por vez e só enxerga falhas de transmissão. Um pluviômetro
entupido, que transmite normalmente e registra menos do que choveu, **não é detectado**: isso
exige comparar estações vizinhas (consistência espacial), o que está fora desta biblioteca.

| Regra | Padrão (parâmetro) | Origem da ideia | Origem do número |
|---|---|---|---|
| Grade regular: horários fora da grade são arredondados e somados | 10 min (`freq`) | Formato: com chuva, a estação transmite a cada 10 min | Formato |
| Vazio curto vale 0 mm | até 5 intervalos seguidos (`max_intervalos_vazios`) | Formato: sem chuva, a estação transmite de hora em hora, o que deixa 5 intervalos vazios entre dois registros | Formato |
| Falha longa vira NaN | mais de 5 intervalos seguidos | Formato: acima disso faltou ao menos um registro horário | Formato |
| Retorno alto: a primeira leitura depois de uma falha longa é marcada em `retorno_pos_falha_longa`; se for alta, é marcada em `retorno_alto` e vira NaN. Com `excluir_retorno_alto=False`, só fica marcada | 25 mm (`limiar_retorno`) | Empírico: em algumas estações essa leitura traz a chuva acumulada do período fora do ar | Empírico. Em Petrópolis, de 23.224 retornos, 17.973 são zero, a média é 0,11 mm e 6 chegam a 25 mm (entre eles 228, 179 e 99 mm após 45, 37 e 79 dias fora do ar) |
| Valor repetido: sequência de leituras transmitidas seguidas com o valor do ruído vira NaN, do primeiro ao último registro. Pode ser desligado (`filtrar_repetidos=False`) | 12 leituras ou mais (`min_repetidos`) de 0,2 mm (`valor_repetido_mm`; `None` aceita qualquer valor não nulo) | A ideia vem dos valores constantes da umidade no ISMN [1]; aplicá-la à chuva é escolha nossa. Empírico: nas estações de Petrópolis o valor repetido é quase sempre 0,2 mm (uma basculada, valor exato em todas as 28 estações), às vezes por dias seguidos, inclusive logo depois de uma chuva forte (funil escoando aos poucos). Hipótese, não confirmada com o fabricante | **Empírico, sem referência publicada; teste outros valores.** O ruído é muito intermitente e não há quebra natural na distribuição. Nas 28 estações de Petrópolis (278 mil mm no total), as sequências de 0,2 mm somam: 6 ou mais leituras, 6,8 % da chuva; 12 ou mais, 3,5 % (2.228 sequências, mediana de 16 leituras); 24 ou mais, 1,6 %; 48 ou mais, 0,6 %. A maior tem 559 leituras em 26 dias (112 mm, 330390612A). Com qualquer valor, 12 ou mais somam 3,8 %: a diferença são repetições de 0,39 e 0,59 mm (duas e três basculadas). Garoa real pode repetir 0,2 mm por algumas leituras, por isso sequências curtas não são tocadas. O padrão de 12 foi escolhido pelo autor na inspeção dos dados (antes era 24) |
| Leitura alta: só marcada, não invalidada | 25 mm em 10 min, isto é, 150 mm/h (`limiar_leitura_alta`) | Referência: o ISMN marca precipitação acima de 100 mm/h [1b] | Empírico. Há leituras reais acima disso (04G em 15/02/2022: 25,2 mm em 10 min no meio de chuva contínua), por isso a regra só marca |
| Período só vale completo: os acumulados móveis e os totais por hora, dia ou mês ficam NaN se houver falha | tolerância 0 (`fracao_falha_max`, fração de 0 a 1 do período) | Soma com falha subestima a chuva sem aviso | Escolha conservadora; a tolerância é parâmetro. Nos totais, a coluna `incompleto` avisa quando a falha coube na tolerância |
| Dia com chuva, nos percentis de `resumo_estacao` | 1 mm (`limiar_chuvoso`) | Referência: dia úmido definido como RR ≥ 1 mm nos índices do ETCCDI [2] | Referência |
| Mês ou ano completo, nas médias de `resumo_estacao` | 90 % de dados válidos (`fracao_min_periodo`) | Evitar que períodos com falha puxem a média para baixo | Escolha de trabalho |

A ordem dentro de `regularizar_chuva` é: grade regular, falha longa, retorno pós-falha, valor
repetido, leitura alta. Tudo o que é descartado continua visível em `valor_original`.

Funções: `regularizar_chuva`, `relatorio_falhas`, `retornos_pos_falha`, `acumulados`,
`resumo_estacao`.

A exclusão manual (`exclusao.excluir_periodos`) não é uma regra: é uma ferramenta para invalidar
leituras claramente erradas que nenhuma regra pegou. Ela vale para a chuva e para a umidade, e o
que exclui fica registrado (coluna `exclusao_manual` na chuva).

## Umidade do solo (`umidade.py`)

As regras seguem as categorias do controle de qualidade automático da International Soil
Moisture Network (ISMN) [1]: valor fora da faixa, pico sem chuva, saltos e valores constantes.
São **adaptações simplificadas** de Dorigo et al. (2013) [1], não uma implementação do método
do artigo: dele vêm as categorias; os algoritmos são mais simples (medianas antes e depois, em vez
de derivadas da série) e os números, em geral, são empíricos, ajustados aos dados de Petrópolis.

Cada regra é de **falha** (falha inequívoca do equipamento) ou **suspeita** (comportamento
estranho que pode ser real). O parâmetro `excluir` de `limpar_umidade` escolhe o que vira NaN
sozinho: `'falhas'` (padrão) apaga só as falhas; `'todas'` apaga também as suspeitas; `'nenhuma'`
não apaga nada. O que não é apagado continua marcado em `umid_clean[cod].mascaras` e em
`tabela_periodos` (coluna `excluida`), para o usuário avaliar e excluir com
`exclusao.excluir_periodos`, que aceita a lista de níveis a excluir. A divisão segue a ideia do
ISMN [1b], que separa as flags de plausibilidade (C, valores impossíveis) das de comportamento da
série (D, picos, quebras, valores constantes), com uma diferença: aqui o congelado e a queda
simultânea entram nas falhas. A classificação da queda simultânea como falha é empírica: é um
padrão identificado pelo autor em anos de trabalho com estes dados (3 ou mais profundidades
caindo no mesmo instante; a 3 m o solo não perde água em minutos). Não há referência publicada
para ela.

| Regra | Classe | Padrão (parâmetro) | Origem da ideia | Origem do número |
|---|---|---|---|---|
| Zero exato | falha | 0 | Formato: é o valor que o equipamento envia quando falha (aparece em vários níveis ao mesmo tempo) | Formato |
| Acima do máximo | falha | 60 % (`maximo`) | Referência: faixa de 0,0 a 0,6 m³/m³ para a umidade [1] (flag C02 do ISMN [1b]) | Referência, e coincide com os dados: nenhum sensor limpo das 7 PCDs passa de cerca de 52 % |
| Valor congelado | falha | mesmo valor exato por 24 h ou mais (`congelado_min`) | Referência: valores constantes por ao menos 12 h [1] (flags D09 e D10 do ISMN [1b]) | Empírico. A sonda informa 5 casas decimais e sempre oscila nas últimas; 24 h é mais conservador que as 12 h do ISMN |
| Queda simultânea: 3 ou mais níveis caem no mesmo instante; todos os níveis viram NaN | falha | 3 níveis | Empírico: o solo a 3 m não perde água em minutos; é assinatura de falha elétrica, identificada pelo autor nos dados | Empírico |
| Queda isolada: queda instantânea que volta | suspeita | 1,5 p.p. abaixo da mediana das 12 leituras anteriores e das 12 seguintes (`limiar_queda`) | Referência: picos, isto é, subidas ou quedas de um só passo de tempo, causados por falha temporária do sensor ou alimentação elétrica reduzida [1] (flag D06 do ISMN [1b]) | Empírico. Fora da chuva, 99,9 % das variações entre leituras de 10 min ficam abaixo de cerca de 1,4 p.p. |
| Pico sem chuva | suspeita | 3,0 p.p. acima das duas medianas, sem chuva nas 6 h anteriores (`limiar_pico`); se a chuva dessas 6 h tem falha, o pico não é marcado | Referência: subida de umidade sem chuva significativa nas 24 h anteriores [1] (flag D04 do ISMN [1b]) | Empírico. A janela de 6 h é mais restrita que as 24 h do ISMN |
| Acomodação pós-instalação vira NaN | sempre aplicada | período informado pelo usuário (`acomodacao`) | Empírico: depois de instalada, as camadas fundas descem por meses sem relação com a chuva | Não há padrão. Escolha olhando a série bruta com `figuras.serie_umidade_interativo` |
| Degraus e descontinuidades: só listados | nunca apagados | 1,0 p.p. que persiste | Referência: quebras, isto é, saltos e quedas que deixam um deslocamento em relação ao período anterior; o artigo observa que é difícil saber qual dos dois períodos está certo [1] (flags D07 e D08 do ISMN [1b]) | Empírico. Não são apagados porque podem ser mudança real |

Funções: `limpar_umidade` aplica tudo; cada regra é uma função (`flag_zero`, `flag_faixa`,
`flag_congelado`, `flag_quedas`, `flag_quedas_iter`, `flag_picos`, `acha_degraus`,
`descontinuidades`) que pode ser usada sozinha; `tabela_periodos` transforma o resultado em uma
tabela de períodos. As distâncias que `tabela_periodos` usa para juntar pontos próximos num
período (3, 15 e 30 dias, na constante `AGRUPAMENTO`) só organizam a tabela: não mudam o que é
marcado nem o que é excluído.

A regra do pico e a lista de degraus precisam saber se choveu. `limpar_umidade` usa a chuva da
própria estação, que nas PCDs Geo vem no mesmo arquivo do PED: lê o sensor 10, aplica
`regularizar_chuva` com os padrões e soma por hora (`reamostrar_chuva`). Se a estação não tem o
sensor de chuva nos dados, a função dá erro; quem já tem a chuva horária tratada pode passá-la em
`pluv_h`. A chuva usada fica em `umid_clean[cod].pluv_h`.

Quando a chuva da janela tem falha (hora NaN), não dá para saber se choveu: o pico **não** é
marcado e o degrau não recebe o motivo "sem chuva". A regra só marca o que tem certeza de ser
suspeito. Isso pesa nos períodos descartados pelo filtro de valor repetido da chuva, que podem
durar dias.

## Resolução temporal (`resolucao.py`)

| Regra | Padrão (parâmetro) | Justificativa |
|---|---|---|
| Blocos fixos do calendário, não janelas móveis | horas redondas, dias, meses (`freq`) | Para totais por período. Somas em janela móvel (a chuva das últimas 24 h a cada 10 min) ficam em `chuva.acumulados` |
| Cada período é rotulado pelo início e reúne a chuva que caiu dentro dele | o dia 15/02 soma os registros de 15/02 00:10 a 16/02 00:00 | Formato: cada registro do Cemaden traz a chuva dos 10 min que terminam no seu horário, então o registro de 00:00 é chuva do dia anterior. O total diário do próprio Cemaden (sensor 600) fecha do mesmo jeito |
| Hora em que o dia começa | 0, dia civil (`inicio_dia`) | Parâmetro para quem precisa do dia começando em outra hora |
| Chuva é somada; período com falha fica NaN | tolerância 0 (`fracao_falha_max`) | A chuva é um total: somar um período com falha daria um valor menor que o real. A coluna `incompleto` diz se faltou algum intervalo, mesmo dentro da tolerância |
| Umidade é agregada pela média ou mediana | média, com ao menos 1 leitura (`agregacao`, `min_leituras`) | A umidade é uma grandeza de estado. A transmissão é irregular, então a exigência é um número mínimo de leituras, e não uma fração. A coluna `incompleto` diz se alguma hora do período ficou sem leitura |

## Fuso horário

Os arquivos do Cemaden estão em UTC. Isso foi conferido nos dados de Petrópolis de duas formas:
o total diário do sensor 600 fecha com a soma das 24 h que terminam à 00:00 do arquivo, e a
chuva de 15/02/2022 aparece entre 19 h e 22 h nos arquivos. A leitura soma `fuso` horas (padrão
−3, horário de Brasília fixo, sem horário de verão). É uma verificação empírica em um
município: confira com um evento de horário conhecido ao usar dados de outro lugar.

## Referências

[1] Dorigo, W. A., Xaver, A., Vreugdenhil, M., Gruber, A., Hegyiová, A., Sanchis-Dufau, A. D.,
Zamojski, D., Cordes, C., Wagner, W., e Drusch, M. (2013). Global automated quality control of
in situ soil moisture data from the International Soil Moisture Network. *Vadose Zone Journal*,
12(3). https://doi.org/10.2136/vzj2012.0097

[1b] International Soil Moisture Network. Quality flags: tabela de códigos e limiares.
https://ismn.earth/en/data/flag-overview/ (consultada em 16/11/2026)

[2] Expert Team on Climate Change Detection and Indices (ETCCDI). Climate change indices:
definições dos 27 índices. https://etccdi.pacificclimate.org/list_27_indices.shtml
(consultada em 16/11/2026)

### O que foi conferido na fonte

- **[1b] e [2]**: páginas abertas e lidas; os limiares citados (0,6 m³/m³, 12 h, 24 h sem
  precipitação, 100 mm/h, RR ≥ 1 mm) estão nelas.
- **[1]**: artigo conferido no PDF em 16/11/2026 (resumo e os trechos de cada
  método lidos; o restante verificado por busca no texto). Confirmado no texto:
  a faixa de 0,0 a 0,6 m³/m³ para a umidade, adotada de Dorigo et al. (2011, *Hydrol. Earth Syst.
  Sci.* 15:1675–1698); a subida de umidade sem chuva significativa nas 24 h anteriores; os picos
  (*spikes*, subidas ou quedas que duram um só passo de tempo); as quebras (*breaks*: saltos e
  quedas que deixam um deslocamento); e os valores constantes por ao menos 12 h. O artigo atribui
  picos e quebras a falha temporária do sensor ou a alimentação elétrica reduzida, o que apoia a
  leitura das quedas instantâneas como falha elétrica. Ele **não** trata de acomodação
  pós-instalação nem de queda simultânea em várias profundidades: essas duas regras são só
  empíricas. Os métodos do artigo para picos e quebras usam derivadas da série, diferentes das
  medianas antes e depois usadas aqui; a categoria é a mesma, o algoritmo e os números não.
- As diretrizes da OMM para estações automáticas (Zahumenský, 2004) e o trabalho do SBRH sobre a
  rede do Cemaden foram retirados desta lista em 18/11/2026, por não terem sido lidos. As regras
  que se apoiavam neles passaram a citar o que foi observado nos dados (formato) ou o ISMN.
