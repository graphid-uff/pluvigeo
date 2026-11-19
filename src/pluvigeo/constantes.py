"""
constantes.py
=============
Dicionário de sensores do Cemaden (PCD Geo e pluviômetro automático).

ATENÇÃO ao dicionário: na documentação recebida, 580 e 630 estavam trocados.
Pelos dados, 580 é a MÁXIMA diária de n4 e 630 a de n5 (conferido nas 7 PCDs Geo).
"""


# ------------------------------------------------------------------------------
# Umidade (sonda Sentek FDR, 6 profundidades)
# ------------------------------------------------------------------------------
NIV = ['n1', 'n2', 'n3', 'n4', 'n5', 'n6']


PROFUNDIDADE_M = dict(zip(NIV, [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]))


MAPA_UMIDADE = {330: 'n1', 340: 'n2', 350: 'n3', 360: 'n4', 610: 'n5', 620: 'n6'}


MAPA_MAX_DIARIA = {520: 'n1_max', 540: 'n2_max', 560: 'n3_max', 580: 'n4_max', 630: 'n5_max', 650: 'n6_max'}


MAPA_MIN_DIARIA = {530: 'n1_min', 550: 'n2_min', 570: 'n3_min', 590: 'n4_min', 640: 'n5_min', 660: 'n6_min'}



# ------------------------------------------------------------------------------
# Chuva
# ------------------------------------------------------------------------------
ID_CHUVA = 10          # mm acumulados desde a transmissão anterior


ID_CHUVA_DIA = 600     # total do dia ANTERIOR, registrado às 00:00
ID_INTENSIDADE = 240   # intensidade (mm/h) informada pela estação; não usada nas análises
ID_RARO = 250          # aparece raramente nos arquivos; não usado

# Todos os id_sensor conhecidos. leitura.inventario_dados compara os ids de cada arquivo com
# esta lista e mostra os que faltam nela em `ids_desconhecidos`: um id novo pode indicar que o
# Cemaden criou um sensor ou mudou o formato dos arquivos.
IDS_CONHECIDOS = {10, 240, 250, 330, 340, 350, 360, 520, 530, 540, 550, 560, 570, 580, 590,
                  600, 610, 620, 630, 640, 650, 660}

DICIONARIO_SENSORES = {
    10: 'chuva acumulada desde a transmissão anterior (mm por registro)',
    240: 'intensidade de chuva (mm/h)',
    250: 'raro; sem uso',
    600: 'chuva total do dia ANTERIOR, registrada às 00:00 (mm)',
    330: 'umidade n1 (0,5 m) %', 340: 'umidade n2 (1,0 m) %', 350: 'umidade n3 (1,5 m) %',
    360: 'umidade n4 (2,0 m) %', 610: 'umidade n5 (2,5 m) %', 620: 'umidade n6 (3,0 m) %',
    520: 'máx. diária n1', 540: 'máx. diária n2', 560: 'máx. diária n3', 580: 'máx. diária n4',
    630: 'máx. diária n5', 650: 'máx. diária n6',
    530: 'mín. diária n1', 550: 'mín. diária n2', 570: 'mín. diária n3', 590: 'mín. diária n4',
    640: 'mín. diária n5', 660: 'mín. diária n6',
}
