# Dados do notebook de exemplo

**Fonte:** Centro Nacional de Monitoramento e Alertas de Desastres Naturais (Cemaden).
A pluvigeo não tem vínculo com o Cemaden; os dados pertencem a ele e são reproduzidos aqui só para
o notebook de exemplo rodar.

Estes arquivos são um **recorte** de arquivos baixados do Cemaden, para estações do município de
Petrópolis (RJ). As linhas foram copiadas dos arquivos originais **sem nenhuma alteração** de valor;
só foram mantidos os períodos usados no notebook, e os arquivos foram compactados (`.csv.gz`), que a
pluvigeo lê direto. Os horários estão em UTC, como nos originais.

| Arquivo | Origem | Estação | Período (UTC) | Usado para mostrar |
|---|---|---|---|---|
| `PED_Cemaden_330390605G.csv.gz` | PED | PCD Geo, chuva e umidade | 01/11/2021 a 31/12/2022 | identificação da acomodação, limpeza da umidade, evento de 15/02/2022 |
| `PED_Cemaden_330390602G.csv.gz` | PED | PCD Geo, chuva e umidade | 01/11/2021 a 31/12/2022 | situação diária de várias PCDs Geo (`status_umid`) |
| `PED_Cemaden_330390609A.csv.gz` | PED | pluviômetro | 01/10/2020 a 31/12/2020 | ruído de 0,2 mm (valor repetido) |
| `PED_Cemaden_330390612A.csv.gz` | PED | pluviômetro | 01/10/2020 a 31/12/2020 | falhas de transmissão |
| `PED_Cemaden_330390618A.csv.gz` | PED | pluviômetro | 01/01/2017 a 30/04/2017 | retorno alto depois de uma falha longa |
| `mapa_interativo/petropolis_02_2022.csv.gz` | mapa interativo | todas as estações do município | fevereiro de 2022 (arquivo inteiro) | leitura do formato do mapa interativo |

Onde baixar os dados completos:

- **PED** (Plataforma de Entrega de Dados): https://ped.cemaden.gov.br (exige cadastro);
- **Mapa interativo**: https://mapainterativo.cemaden.gov.br

Se usar estes dados, cite o Cemaden como fonte. Não encontramos uma licença explícita para os dados
das estações; para usos além do exemplo, consulte os termos do Cemaden.
