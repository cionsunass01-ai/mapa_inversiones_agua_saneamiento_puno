import csv
import re
from pathlib import Path
import duckdb

con = duckdb.connect()
CSV_PATH = Path("data/raw/DETALLE_INVERSIONES.csv")

# Setup base view
con.execute(f"""
    CREATE OR REPLACE TEMP VIEW inversiones_puno AS
    SELECT *
    FROM read_csv_auto(
        '{CSV_PATH.as_posix()}',
        HEADER = TRUE,
        IGNORE_ERRORS = TRUE,
        ALL_VARCHAR = TRUE
    )
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO';
""")

print("=== 1. REVISAR TODOS LOS PROYECTOS DE SALUD Y SANEAMIENTO ===")
salud_saneamiento = con.execute("""
    SELECT 
        CODIGO_UNICO, NOMBRE_INVERSION, FUNCION, PROGRAMA, SUBPROGRAMA, 
        DES_TIPOLOGIA, TIPO_INVERSION, PROVINCIA, DISTRITO, ESTADO, SITUACION
    FROM inversiones_puno
    WHERE UPPER(TRIM(FUNCION)) = 'SALUD Y SANEAMIENTO'
""").fetchall()

columnas_salud = [d[0] for d in con.description]

salud_incluir_cuis = set()
salud_revisar_cuis = set()
salud_excluir_cuis = set()

# Terms
agua_terms = ['AGUA', 'SANEAMIENTO', 'ALCANTARILLADO', 'EXCRETAS', 'PTAR', 'PTAP', 'DRENAJE', 'LETRINAS', 'DESAGUE']
salud_terms = ['SALUD', 'HOSPITAL', 'PUESTO DE SALUD', 'CENTRO DE SALUD', 'MEDICO', 'CLINICA']

for fila in salud_saneamiento:
    row_dict = dict(zip(columnas_salud, fila))
    nombre = (row_dict['NOMBRE_INVERSION'] or '').upper()
    
    # Classify
    clase = 'REVISAR'
    if any(t in nombre for t in salud_terms) and not any(t in nombre for t in agua_terms):
        clase = 'EXCLUIR_SALUD'
    elif any(t in nombre for t in agua_terms) and not any(t in nombre for t in salud_terms):
        clase = 'INCLUIR_AGUA_SANEAMIENTO'
    elif 'AGUA' in nombre or 'SANEAMIENTO' in nombre:
        clase = 'INCLUIR_AGUA_SANEAMIENTO' # if mixed, usually water systems for a town
    else:
        clase = 'REVISAR'
        
    if 'HOSPITAL' in nombre or 'PUESTO DE SALUD' in nombre:
        clase = 'EXCLUIR_SALUD'
        
    print(f"CUI: {row_dict['CODIGO_UNICO']} | {row_dict['PROGRAMA']} - {row_dict['SUBPROGRAMA']}")
    print(f"Nombre: {row_dict['NOMBRE_INVERSION']}")
    print(f"Clasificación: {clase}\n")
    
    if clase == 'INCLUIR_AGUA_SANEAMIENTO':
        salud_incluir_cuis.add(row_dict['CODIGO_UNICO'])
    elif clase == 'REVISAR':
        salud_revisar_cuis.add(row_dict['CODIGO_UNICO'])
    else:
        salud_excluir_cuis.add(row_dict['CODIGO_UNICO'])

print("\n=== 2. REVISAR LOS 19 CANDIDATOS PENDIENTES ===")
audit_path = Path("outputs/auditoria_29_candidatos_clasificados.csv")

candidatos_incluir = set()
candidatos_excluir = set()
candidatos_revisar = set()

with open(audit_path, mode='r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['CLASIFICACION_PROPUESTA'] == 'REVISAR':
            nombre = row['NOMBRE_INVERSION'].upper()
            cui = row['CODIGO_UNICO']
            
            clase = 'REVISION_MANUAL'
            motivo = ''
            
            if 'CISTERNA' in nombre or 'HIDROJET' in nombre or 'EPS' in nombre or 'SEDA' in nombre or 'EMSA' in nombre:
                clase = 'INCLUIR_COMPLEMENTARIO'
                motivo = 'Equipamiento directamente destinado a EPS / Saneamiento'
            elif 'MERCADO' in nombre or 'HIDROELECTRICA' in nombre or 'AGRICOLA' in nombre or 'RIEGO' in nombre or 'COLEGIO' in nombre:
                clase = 'EXCLUIR'
                motivo = 'Relación indirecta (infraestructura de otra entidad o agrícola)'
            elif 'EXCAVADORA' in nombre or 'AMBULANCIA' in nombre or 'VOLQUETE' in nombre:
                clase = 'EXCLUIR'
                motivo = 'Maquinaria multipropósito o vehículos no exclusivos de saneamiento'
            else:
                clase = 'REVISION_MANUAL'
                motivo = 'Información ambigua, requiere evaluación humana'
            
            print(f"CUI: {cui} | {row['FUNCION']}")
            print(f"Nombre: {nombre}")
            print(f"Clasificación: {clase} -> {motivo}\n")
            
            if clase == 'INCLUIR_COMPLEMENTARIO':
                candidatos_incluir.add(cui)
            elif clase == 'EXCLUIR':
                candidatos_excluir.add(cui)
            else:
                candidatos_revisar.add(cui)

# === 3. GENERAR TRES CONJUNTOS DE CONTROL ===
# We'll use duckdb to copy views directly to CSV.

# UNIVERSO SEGURO
# 750 FUNCION=SANEAMIENTO + INCLUIR_AGUA_SANEAMIENTO
incluir_salud_sql = "','".join(salud_incluir_cuis) if salud_incluir_cuis else "''"

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW universo_seguro AS
    SELECT * FROM inversiones_puno
    WHERE UPPER(TRIM(FUNCION)) = 'SANEAMIENTO'
       OR CODIGO_UNICO IN ('{incluir_salud_sql}')
""")
con.execute("COPY (SELECT * FROM universo_seguro) TO 'outputs/universo_seguro.csv' (HEADER, DELIMITER ',')")

# UNIVERSO COMPLEMENTARIO
# INCLUIR_COMPLEMENTARIO
incluir_comp_sql = "','".join(candidatos_incluir) if candidatos_incluir else "''"

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW universo_complementario AS
    SELECT * FROM inversiones_puno
    WHERE CODIGO_UNICO IN ('{incluir_comp_sql}')
""")
con.execute("COPY (SELECT * FROM universo_complementario) TO 'outputs/universo_complementario.csv' (HEADER, DELIMITER ',')")

# REVISION MANUAL
# salud_revisar + candidatos_revisar
rev_manual_cuis = salud_revisar_cuis.union(candidatos_revisar)
rev_manual_sql = "','".join(rev_manual_cuis) if rev_manual_cuis else "''"

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW revision_manual AS
    SELECT * FROM inversiones_puno
    WHERE CODIGO_UNICO IN ('{rev_manual_sql}')
""")
con.execute("COPY (SELECT * FROM revision_manual) TO 'outputs/revision_manual.csv' (HEADER, DELIMITER ',')")


print("\n=== 4. VERIFICACIÓN DE CUI ===")
def check_view(view_name):
    filas = con.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
    cuis = con.execute(f"SELECT COUNT(DISTINCT CODIGO_UNICO) FROM {view_name}").fetchone()[0]
    nulos = con.execute(f"SELECT COUNT(*) FROM {view_name} WHERE CODIGO_UNICO IS NULL").fetchone()[0]
    duplicados = filas - cuis
    print(f"Conjunto: {view_name}")
    print(f"  Filas: {filas}")
    print(f"  CUIs únicos: {cuis}")
    print(f"  CUIs duplicados: {duplicados}")
    print(f"  Registros sin CUI: {nulos}")
    return cuis

cuis_seguro = check_view('universo_seguro')
cuis_comp = check_view('universo_complementario')
cuis_rev = check_view('revision_manual')

# Intersection check
intersect_1 = con.execute("""
    SELECT COUNT(*) FROM universo_seguro a 
    JOIN universo_complementario b ON a.CODIGO_UNICO = b.CODIGO_UNICO
""").fetchone()[0]
intersect_2 = con.execute("""
    SELECT COUNT(*) FROM universo_seguro a 
    JOIN revision_manual c ON a.CODIGO_UNICO = c.CODIGO_UNICO
""").fetchone()[0]
intersect_3 = con.execute("""
    SELECT COUNT(*) FROM universo_complementario b 
    JOIN revision_manual c ON b.CODIGO_UNICO = c.CODIGO_UNICO
""").fetchone()[0]

print(f"\nSuperposiciones (CUI simultáneos en más de un conjunto):")
print(f"  Seguro vs Complementario: {intersect_1}")
print(f"  Seguro vs Revisión Manual: {intersect_2}")
print(f"  Complementario vs Revisión Manual: {intersect_3}")

print("\n=== 5. RESULTADO FINAL DE ESTA ETAPA ===")
print(f"1. Proyectos seguros de FUNCION = SANEAMIENTO: 750")
print(f"2. De los 14 de SALUD Y SANEAMIENTO:")
print(f"   - Incluir: {len(salud_incluir_cuis)}")
print(f"   - Excluir: {len(salud_excluir_cuis)}")
print(f"   - Revisar: {len(salud_revisar_cuis)}")
print(f"3. De los 19 candidatos de otras funciones:")
print(f"   - Incluir complementarios: {len(candidatos_incluir)}")
print(f"   - Excluir: {len(candidatos_excluir)}")
print(f"   - Revisión manual: {len(candidatos_revisar)}")
print(f"4. Total del universo_seguro: {cuis_seguro}")
print(f"5. Total potencial incluyendo universo_complementario: {cuis_seguro + cuis_comp}")
