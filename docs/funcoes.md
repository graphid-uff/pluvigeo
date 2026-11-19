# Funções da pluvigeo: entradas e saídas

Uma seção por função, **na ordem em que o processamento é feito**, com o que cada uma recebe,
os parâmetros e o que devolve. Os valores padrão dos limiares e as suas justificativas estão em
[`regras.md`](regras.md).

```python
from pluvigeo import leitura, chuva, umidade, exclusao, resolucao, figuras
```

## Os objetos que encadeiam as funções

A saída de uma função é a entrada de outra. Os nomes abaixo são os usados no notebook de exemplo
e nesta documentação (as funções aceitam qualquer nome de variável). A regra dos nomes:

- o prefixo diz a variável: `pluv` (chuva) ou `umid` (umidade);
- o sufixo diz a etapa: `raw` (como foi lido), `reg` (chuva em grade regular, com as falhas
  marcadas), `clean` (umidade limpa), `rs` (*resample*: reamostrado para outra resolução);
- cada objeto é um **dicionário** `{codestacao: dado da estação}`; `pluv_reg[cod]` é o dado de
  uma estação.

| Objeto | O que é | Criado por | Usado por |
|---|---|---|---|
| `dados` | tabela padronizada: uma linha por estação, instante e sensor | `leitura.ler_dados` | `inventario_dados`, `chuva_por_estacao`, `umidade_por_estacao`, `limpar_umidade` |
| `estacoes` | tabela de estações | `leitura.ler_dados` | `inventario_dados` |
| `pluv_raw` | `{cod: série de chuva bruta}` | `leitura.chuva_por_estacao` | `chuva.regularizar_chuva` |
| `umid_raw` | `{cod: umidade bruta n1..n6}` | `leitura.umidade_por_estacao` | `figuras.serie_umidade_interativo` (escolher a acomodação) |
| `pluv_reg` | `{cod: tabela regular de chuva}`; a série a usar é `pluv_reg[cod]['chuva_mm']` | `chuva.regularizar_chuva` | `relatorio_falhas`, `retornos_pos_falha`, `acumulados`, `resumo_estacao`, `excluir_periodos`, `reamostrar_chuva`, `serie_chuva`, `status_pluv` |
| `umid_clean` | `{cod: resultado da limpeza}`; a série a usar é `umid_clean[cod].operacional` | `umidade.limpar_umidade` (uma estação por vez) | `tabela_periodos`, `excluir_periodos`, `reamostrar_umidade`, `serie_umidade`, `status_umid` |
| `pluv_rs` | `{cod: chuva em outra resolução}` | `resolucao.reamostrar_chuva` | figuras |
| `umid_rs` | `{cod: umidade em outra resolução}` | `resolucao.reamostrar_umidade` | figuras |

Saídas finais, que não alimentam outra função: o inventário, o relatório de falhas, os retornos,
os acumulados e o resumo da estação.

Datas podem ser passadas como texto (`'2022-02-15'`, `'2022-02-15 18:00'`) ou `Timestamp`, sempre no
mesmo fuso dos dados lidos. Períodos (`freq`, janelas) são textos do pandas: `'10min'`, `'1h'`,
`'24h'`, `'1D'`, `'7D'`, `'MS'` (mês), `'YS'` (ano).

## Janela móvel x bloco fixo

São duas formas de somar a chuva, para usos diferentes:

| | `chuva.acumulados` | `resolucao.reamostrar_chuva` |
|---|---|---|
| Tipo | **janela móvel** | **bloco fixo** do calendário |
| Uma linha por | instante de 10 min | hora, dia, mês... |
| `24h` / `1D` às 15:00 de 15/02 | chuva de 15:00 de 14/02 a 15:00 de 15/02 | (o dia 15/02 é uma linha só) chuva de 00:00 a 24:00 de 15/02 |
| Serve para | máximos e limiares ("a maior chuva em 24 h") | totais horários, diários e mensais |

---

## 1. Leitura (`leitura`)

### `ler_dados(caminho, fuso=-3, sensores=None, padrao='*.csv')`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `caminho` | `str`, `Path` ou lista deles | obrigatório | arquivo, pasta ou lista de arquivos e pastas; PED e mapa interativo podem vir misturados |
| `fuso` | número | `-3` | horas somadas ao horário do arquivo (UTC); `0` mantém UTC |
| `sensores` | lista de `int` ou `None` | `None` | ids de sensor a manter já na leitura, por exemplo `[10]` para só chuva; `None` mantém todos. Para `limpar_umidade`, leia sem filtrar |
| `padrao` | `str` | `'*.csv'` | quais arquivos ler de uma pasta |

**Saída:** três coisas, que se desempacotam em `dados, estacoes, n_dup = ler_dados(...)`:

- `dados`, a tabela padronizada, com as colunas `codestacao` (str), `nome` (str), `datahora` (datetime), `id_sensor` (int; 10 = chuva), `valor` (float; mm ou %) e `qualificacao` (float; não usada);
- `estacoes`, a tabela de estações, com `codestacao`, `nome`, `municipio`, `uf`, `latitude` e `longitude`;
- `n_dup`, o número (`int`) de linhas repetidas removidas.

### `inventario_dados(dados, estacoes=None)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `dados` | tabela padronizada | obrigatório | de `ler_dados` |
| `estacoes` | tabela de estações ou `None` | `None` | se dada, acrescenta município, UF e coordenadas |

**Saída:** tabela, uma linha por estação: `codestacao`, `tipo` ('PCD Geo' ou 'pluviômetro'),
`inicio`, `fim` (datetime), `linhas` (int), `tem_umidade` (bool), `sensores` (lista de ids) e
`ids_desconhecidos` (lista dos ids fora de `constantes.IDS_CONHECIDOS`; um id novo pode indicar
mudança no formato do Cemaden).

### `chuva_por_estacao(dados, id_chuva=10)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `dados` | tabela padronizada | obrigatório | de `ler_dados`, com o sensor 10 |
| `id_chuva` | `int` | `10` | sensor de chuva |

**Saída:** `pluv_raw`, um `dict` `{codestacao: série}`. Cada série tem mm por registro e índice
`datahora` irregular (como a estação transmitiu).

### `umidade_por_estacao(dados)`

| Entrada | Tipo | Padrão | Descrição |
|---|---|---|---|
| `dados` | tabela padronizada | obrigatório | de `ler_dados`, com os sensores de umidade |

**Saída:** `umid_raw`, um `dict` `{codestacao: tabela}` só das estações com umidade (PCDs Geo).
Cada tabela tem índice `datahora` e colunas `n1`…`n6` (%, de 0,5 a 3,0 m), sem limpeza. Serve para
olhar a série bruta e escolher a acomodação; `limpar_umidade` não usa esta saída.

---

## 2. Chuva: diagnóstico (`chuva`)

### `regularizar_chuva(pluv_raw, freq='10min', max_intervalos_vazios=5, limiar_leitura_alta=25.0, limiar_retorno=25.0, excluir_retorno_alto=True, filtrar_repetidos=True, min_repetidos=12, valor_repetido_mm=0.2)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_raw` | `dict` ou série | obrigatório | o dicionário inteiro (devolve um dicionário) ou a série de uma estação, `pluv_raw[cod]` (devolve uma tabela) |
| `freq` | período | `'10min'` | passo da grade regular |
| `max_intervalos_vazios` | `int` | `5` | nº de intervalos vazios seguidos ainda tratados como "não choveu" |
| `limiar_leitura_alta` | `float` (mm) | `25.0` | leitura a partir da qual `leitura_alta` é marcada (só marca) |
| `limiar_retorno` | `float` (mm) | `25.0` | a primeira leitura após uma falha longa é marcada em `retorno_alto` a partir deste valor |
| `excluir_retorno_alto` | `bool` | `True` | `True` descarta o retorno alto (NaN); `False` só o marca |
| `filtrar_repetidos` | `bool` | `True` | descarta sequências longas de leituras com o mesmo valor (ruído de 0,2 mm); `False` desliga |
| `min_repetidos` | `int` | `12` | nº de leituras transmitidas seguidas, com o mesmo valor, para a sequência ser descartada (empírico: teste outros valores) |
| `valor_repetido_mm` | `float` ou `None` | `0.2` | valor (mm) do ruído procurado; `None` aceita qualquer valor não nulo |

**Saída:** `pluv_reg` (ou `pluv_reg[cod]`, se a entrada foi uma série): tabela com índice
`datahora` em grade regular e as colunas

| Coluna | Tipo | Conteúdo |
|---|---|---|
| `valor_original` | float (mm) | leitura como veio; NaN onde não houve transmissão |
| `ausente` | bool | não houve transmissão no intervalo |
| `grupo_falha`, `tamanho_bloco` | int | número do bloco contínuo de presença ou ausência e o seu tamanho em intervalos |
| `falha_longa` | bool | ausente, em bloco maior que `max_intervalos_vazios` |
| `retorno_pos_falha_longa` | bool | primeira leitura depois de uma falha longa |
| `retorno_alto` | bool | retorno com valor a partir de `limiar_retorno` |
| `valor_repetido` | bool | dentro de uma sequência longa de leituras iguais; toda `False` com o filtro desligado |
| `leitura_alta` | bool | leitura a partir de `limiar_leitura_alta` |
| `exclusao_manual` | bool | excluída por `exclusao.excluir_periodos` |
| `valido` | bool | `False` em falha longa, valor repetido, retorno alto (se `excluir_retorno_alto`) e exclusão manual |
| `chuva_mm` | float (mm) | **a série a usar**: a leitura; 0 nos vazios curtos; NaN onde não é válido |

Cada registro traz a chuva dos 10 min que **terminam** no seu horário: o valor das 01:00 é a chuva
de 00:50 a 01:00.

### `relatorio_falhas(pluv_reg)`

| Entrada | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_reg` | `dict` ou tabela | obrigatório | o dicionário inteiro (devolve uma tabela, uma linha por estação) ou `pluv_reg[cod]` (devolve um `dict`) |

**Saída (campos):** `inicio`, `fim` (datetime), `total_dias`, `dias_com_falha_longa`,
`dias_com_falha_%`, `n_falhas_longas`, `horas_em_falha`, `maior_falha_h` (h), `funcionamento_%`
(% dos intervalos com chuva válida), `n_retornos_pos_falha`, `n_retornos_descartados`,
`n_leituras_repetidas`, `mm_repetidos_descartados` (mm), `maior_retorno_mm`, `n_leituras_altas`,
`maximo_valido_mm` (mm), `data_maximo_valido` (datetime). Os nomes com `%` só se acessam entre
colchetes: `tabela['funcionamento_%']`.

### `retornos_pos_falha(pluv_reg)`

| Entrada | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_reg` | tabela | obrigatório | `pluv_reg[cod]`, de uma estação |

**Saída:** tabela com índice `datahora`, da maior leitura para a menor: `valor_original` (mm),
`duracao_falha_h` (h, a falha anterior) e `descartado` (bool).

### `acumulados(pluv_reg, janelas=('1h', …, '30D'), fracao_falha_max=0.0)`

Somas em **janela móvel** (ver "Janela móvel x bloco fixo").

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_reg` | tabela | obrigatório | `pluv_reg[cod]`, de uma estação |
| `janelas` | tupla de períodos | `('1h','3h','6h','12h','24h','36h','48h','72h','7D','30D')` | durações das janelas |
| `fracao_falha_max` | `float` de 0 a 1 | `0.0` | fração da janela, em intervalos de 10 min, que pode estar em falha |

**Saída:** tabela com o mesmo índice e uma coluna `acum_<janela>` (mm) por janela. A janela termina
no instante da linha. NaN onde a janela tem falha além da tolerância.

### `resumo_estacao(pluv_reg, janelas=('1h', …, '7D'), fracao_falha_max=0.0, fracao_min_periodo=0.9, q=(50, 90, 95, 99), limiar_chuvoso=1.0, inicio_dia=0)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_reg` | `dict` ou tabela | obrigatório | o dicionário inteiro (devolve uma tabela) ou `pluv_reg[cod]` (devolve um `dict`) |
| `janelas` | tupla de períodos | `('1h','3h','6h','12h','24h','36h','48h','72h','7D')` | janelas móveis dos máximos acumulados |
| `fracao_falha_max` | `float` de 0 a 1 | `0.0` | tolerância a falhas nas janelas e nos dias |
| `fracao_min_periodo` | `float` de 0 a 1 | `0.9` | fração mínima de dados válidos para um mês ou ano entrar nas médias |
| `q` | tupla de `int` | `(50, 90, 95, 99)` | percentis da chuva diária |
| `limiar_chuvoso` | `float` (mm) | `1.0` | total a partir do qual o dia conta como "com chuva" nos percentis |
| `inicio_dia` | número (h) | `0` | hora em que o dia começa, para os totais diários |

**Saída (campos):** funcionamento (`inicio`, `fim`, `total_dias`, `funcionamento_%`,
`horas_em_falha`, `n_falhas_longas`, `maior_falha_h`, `n_retornos_pos_falha`, `n_leituras_altas`);
`leitura_max_mm` e `data_leitura_max`; `max_<janela>` (mm) e `data_max_<janela>` para cada janela;
`p<q>_dia` e `p<q>_dia_chuvoso` (mm) para cada percentil; `media_mensal`, `maximo_mensal`,
`data_maximo_mensal`, `n_meses_completos`; `media_anual`, `maximo_anual`, `data_maximo_anual`,
`n_anos_completos`. Os totais diários, mensais e anuais são blocos do calendário, como em
`reamostrar_chuva`.

---

## 3. Umidade: diagnóstico e limpeza (`umidade`)

### `limpar_umidade(dados, codestacao, acomodacao=None, maximo=60.0, congelado_min='24h', limiar_queda=1.5, limiar_pico=3.0, excluir='falhas', pluv_h=None)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `dados` | tabela padronizada | obrigatório | precisa ter a umidade (n1 a n6) **e** a chuva (sensor 10) da estação; nas PCDs Geo as duas vêm no mesmo arquivo do PED |
| `codestacao` | `str` | obrigatório | código completo da estação, ex.: `'330390605G'` |
| `acomodacao` | tupla `(inicio, fim)` ou `None` | `None` | período de acomodação pós-instalação, sempre excluído |
| `maximo` | `float` (%) | `60.0` | acima disso a leitura é falha |
| `congelado_min` | período | `'24h'` | duração mínima do mesmo valor exato para ser "congelado" |
| `limiar_queda` | `float` (p.p.) | `1.5` | queda instantânea que volta |
| `limiar_pico` | `float` (p.p.) | `3.0` | pico sem chuva |
| `excluir` | `'falhas'`, `'todas'` ou `'nenhuma'` | `'falhas'` | o que as regras apagam sozinhas: só as falhas do equipamento (zero, acima do máximo, congelado, queda simultânea), todas (inclui pico e queda isolada) ou nenhuma (tudo só sinalizado) |
| `pluv_h` | `Series` (mm por hora) ou `None` | `None` | chuva horária já tratada, rotulada pelo início da hora, com NaN nas horas em falha (a saída de `reamostrar_chuva(pluv_reg[cod], '1h')['chuva_mm']`). `None`: a função usa o sensor 10 da estação |

**Erro** (`ValueError`) se a estação não tem umidade, se não tem o sensor de chuva (e `pluv_h` não
foi dado), ou se o modo de exclusão não existe.

**Saída:** `umid_clean[cod]`, um objeto com os campos

| Campo | Tipo | Conteúdo |
|---|---|---|
| `codestacao` | `str` | o código da estação |
| `bruto` | tabela n1..n6 | como entrou |
| `limpo` | tabela n1..n6 | NaN nas leituras das regras excluídas pelo modo e nas exclusões manuais |
| `operacional` | tabela n1..n6 | `limpo` sem a acomodação: **a série a usar** |
| `pluv_h` | `Series` (mm por hora) | chuva horária usada nas regras; NaN nas horas com falha |
| `mascaras` | `dict` `{regra: tabela bool}` | onde cada regra marcou: `zero`, `faixa`, `congelado`, `queda_simultanea`, `queda_isolada`, `pico`, `exclusao_manual` |
| `degraus`, `descontinuidades` | tabela | mudanças de patamar, só listadas |
| `acomodacao` | tupla ou `None` | o período informado |
| `resumo` | `dict` | `leituras`, `espurias` (marcadas por alguma regra), `espurias_%`, `excluidas` (viraram NaN), `excluidas_%`, `so_sinalizadas`, `em_acomodacao`, `n_<regra>`, `n_degraus`, `n_descontinuidades` |
| `excluir`, `excluidas` | `str`, tupla | o modo usado e as regras que viraram NaN |

*Nota:* o resultado não traz séries horárias nem diárias. Para mudar a resolução, use
`resolucao.reamostrar_umidade(umid_clean[cod].operacional, '1h')`.

### `tabela_periodos(umid_clean)`

Resume as marcações, que são feitas leitura por leitura, em episódios legíveis: junta as leituras
marcadas próximas no tempo num período só e acrescenta a acomodação, os degraus (por mês) e as
descontinuidades. Serve para decidir o que excluir com `exclusao.excluir_periodos`.

| Entrada | Tipo | Padrão | Descrição |
|---|---|---|---|
| `umid_clean` | resultado da limpeza | obrigatório | `umid_clean[cod]`, de uma estação |

**Saída:** tabela, uma linha por período: `estacao`, `tipo`, `inicio`, `fim`, `niveis` (afetados),
`leituras`, `excluida` (bool: virou NaN ou só foi sinalizado), `medida` (o que fazer) e, se houver
acomodação, `dentro_da_acomodacao`.

### Regras isoladas, usadas por `limpar_umidade`

| Função | Entrada | Parâmetros (padrão) | Saída |
|---|---|---|---|
| `flag_zero(u)` | `u`: tabela n1..n6 | | máscara bool no formato de `u` |
| `flag_faixa(u, maximo=60.0)` | `u` | `maximo` (%) | máscara bool |
| `flag_congelado(u, duracao_min='24h')` | `u` | `duracao_min` | máscara bool |
| `mediana_antes_depois(u, k=12)` | `u` | `k` (leituras) | tupla `(antes, depois)`, duas tabelas no formato de `u` |
| `flag_quedas(u, limiar=1.5, k=12, min_niveis=3)` | `u` | `limiar` (p.p.), `k`, `min_niveis` | tupla (máscara por nível, `Series` bool dos instantes de queda simultânea) |
| `flag_quedas_iter(u, limiar=1.5, ks=(12, 24, 48), min_niveis=3)` | `u` | idem, com janelas `ks` | a mesma tupla |
| `flag_picos(u, pluv_h, limiar=3.0, k=12, horas_chuva=6)` | `u`; `pluv_h`: chuva horária (mm) | `limiar` (p.p.), `k`, `horas_chuva` | máscara bool; o pico só é marcado se a chuva das 6 h anteriores é conhecida e zero |
| `acha_degraus(u, pluv_h, limiar=1.0, k=6)` | `u`; `pluv_h` | `limiar` (p.p.), `k` | tabela (`datahora`, `nivel`, `salto`, `chuva12h`, `motivo`); nada é apagado |
| `descontinuidades(u, lacuna_min='3D', limiar=3.0, min_niveis=2)` | `u` | `lacuna_min`, `limiar` (p.p.), `min_niveis` | tabela (`inicio_lacuna`, `fim_lacuna`, `dias`, `delta_n1`…); nada é apagado |
| `intervalos(mascara, tolerancia='2D', min_pontos=1)` | `mascara`: `Series` bool | `tolerancia`, `min_pontos` | tabela (`inicio`, `fim`, `leituras`); usada por `tabela_periodos` |

---

## 4. Exclusão manual (`exclusao`)

### `excluir_periodos(dado, exclusoes)`

A mesma função para a chuva e para a umidade. Retira o que você identificou como espúrio e que as
regras não pegaram (ou só sinalizaram).

| Entrada | Tipo | Padrão | Descrição |
|---|---|---|---|
| `dado` | tabela de chuva ou resultado da limpeza | obrigatório | `pluv_reg[cod]` ou `umid_clean[cod]` |
| `exclusoes` | lista | obrigatório | cada item: um instante (`'2023-09-18 17:00'`); um intervalo (`(inicio, fim)`); ou, só na umidade, um intervalo e os níveis (`(inicio, fim, ['n1', 'n2'])`). Sem níveis, vale para todas as profundidades. Os limites entram na exclusão |

**Saída:** um novo objeto do mesmo tipo da entrada (a entrada não é alterada):

- chuva: `chuva_mm` = NaN, `valido` = `False` e `exclusao_manual` = `True` nos instantes;
- umidade: a máscara `exclusao_manual` ganha as leituras, `limpo`, `operacional` e `resumo` são
  refeitos, e `tabela_periodos` passa a mostrar a exclusão.

---

## 5. Resolução temporal (`resolucao`)

Blocos fixos do calendário (ver "Janela móvel x bloco fixo"). Cada período é rotulado pelo seu
**início** e reúne o que aconteceu dentro dele: o dia 15/02 é a chuva de 15/02 00:00 a 24:00, isto é,
os registros de 15/02 00:10 a 16/02 00:00 (cada registro traz a chuva dos 10 min que terminam no
seu horário). `rs` nos nomes `pluv_rs` e `umid_rs` quer dizer *resample*.

### `reamostrar_chuva(pluv_reg, freq='1h', fracao_falha_max=0.0, inicio_dia=0)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_reg` | tabela | obrigatório | `pluv_reg[cod]`, de uma estação |
| `freq` | período | `'1h'` | resolução de saída |
| `fracao_falha_max` | `float` de 0 a 1 | `0.0` | fração do período, em intervalos de 10 min, que pode estar em falha |
| `inicio_dia` | número (h) | `0` | hora em que o dia começa (ex.: 9 → o dia vai de 09:00 a 09:00 e é rotulado 09:00) |

**Saída:** `pluv_rs[cod]`, tabela na nova resolução: `chuva_mm` (mm; NaN se inválido),
`n_validos`, `n_esperados` (int), `incompleto` (bool: faltou algum intervalo, mesmo dentro da
tolerância), `valido` (bool: a falha cabe na tolerância).

### `reamostrar_umidade(umid, freq='1h', agregacao='media', min_leituras=1, inicio_dia=0)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `umid` | tabela n1..n6 | obrigatório | de preferência `umid_clean[cod].operacional`; aceita a própria saída (horária → diária) |
| `freq` | período | `'1h'` | resolução de saída |
| `agregacao` | `'media'` ou `'mediana'` | `'media'` | como agregar as leituras do período |
| `min_leituras` | `int` | `1` | mínimo de leituras para o período valer |
| `inicio_dia` | número (h) | `0` | hora em que o dia começa |

**Saída:** `umid_rs[cod]`, tabela n1..n6 na nova resolução (NaN onde há menos leituras que o
mínimo) e a coluna `incompleto` (bool: alguma hora do período ficou sem nenhuma leitura).

---

## 6. Figuras (`figuras`)

Todas devolvem a figura e não gravam nada. As de matplotlib devolvem `matplotlib.figure.Figure`;
as de sufixo `_interativo` devolvem `plotly.graph_objects.Figure`.

### `serie_chuva(pluv, inicio=None, fim=None, titulo='')` e `serie_chuva_interativo(...)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv` | tabela ou `Series` (mm) | obrigatório | `pluv_reg[cod]` (as falhas aparecem em cinza) ou uma série em qualquer resolução, ex.: `pluv_rs[cod]['chuva_mm']` |
| `inicio`, `fim` | data ou `None` | `None` | recorte do período |
| `titulo` | `str` | `''` | título da figura |

**Saída:** figura com a chuva em barras ao longo do tempo.

### `status_pluv(pluv_reg, freq='MS', ax=None)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `pluv_reg` | `dict` | obrigatório | o dicionário inteiro, as estações a comparar |
| `freq` | período | `'MS'` | tamanho de cada coluna: `'MS'` = mês, `'D'` = dia |
| `ax` | eixo do matplotlib ou `None` | `None` | para desenhar dentro de uma figura sua |

**Saída:** figura com uma linha por estação e uma coluna por período; do vermelho (nenhum dado
válido) ao verde (período completo); cinza = fora do período da estação.

### `serie_umidade(umid, pluv=None, inicio=None, fim=None, niveis=None, freq='1h', acomodacao=None, titulo='')` e `serie_umidade_interativo(...)`

A interativa é a ferramenta para **identificar o período de acomodação dos sensores**: desenhe a
série bruta (`umid_raw[cod]`), dê zoom e leia a data em que as camadas fundas estabilizam.

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `umid` | tabela n1..n6 | obrigatório | em qualquer resolução: `umid_raw[cod]`, `umid_clean[cod].operacional`, `umid_rs[cod]` |
| `pluv` | `Series` (mm) ou `None` | `None` | se dada, vira um painel de barras embaixo, ex.: `umid_clean[cod].pluv_h` |
| `inicio`, `fim` | data ou `None` | `None` | recorte do período |
| `niveis` | lista de `str` ou `None` | `None` | níveis a mostrar, por exemplo `['n1', 'n2']`; `None` = todos |
| `freq` | período ou `None` | `'1h'` | resolução do desenho (média da umidade, soma da chuva); só agrega se a série for mais fina; `None` desenha como veio |
| `acomodacao` | tupla `(inicio, fim)` ou `None` | `None` | período sombreado em amarelo, para conferir a escolha |
| `titulo` | `str` | `''` | título da figura |

**Saída:** figura com uma linha por profundidade.

### `status_umid(umid_clean, inicio, fim, ax=None)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `umid_clean` | `dict` | obrigatório | o dicionário inteiro, as estações a comparar |
| `inicio`, `fim` | data | obrigatório | período da figura |
| `ax` | eixo do matplotlib ou `None` | `None` | para desenhar dentro de uma figura sua |

**Saída:** figura com uma faixa por estação: operando, dia com quedas simultâneas, acomodação,
falha ou sem dados.

### `salvar(fig, caminho, dpi=110)`

| Entrada / parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `fig` | figura do matplotlib | obrigatório | a figura a gravar |
| `caminho` | `str` ou `Path` | obrigatório | arquivo de saída (`.png`, `.pdf`…); a pasta é criada se não existir |
| `dpi` | `int` | `110` | resolução |

**Saída:** nada; grava o arquivo e fecha a figura. Para as interativas, use `fig.write_html(caminho)`.

Auxiliares internas do módulo: `aplicar` (estilo), `eixo` (cria o eixo) e `disponibilidade` (a
fração de cada período com chuva válida, usada por `status_pluv`).
