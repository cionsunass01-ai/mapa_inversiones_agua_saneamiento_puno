import csv
from pathlib import Path
import duckdb

con = duckdb.connect()
CSV_PATH = Path("data/raw/DETALLE_INVERSIONES.csv")

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW inversiones AS
    SELECT *
    FROM read_csv_auto(
        '{CSV_PATH.as_posix()}',
        HEADER = TRUE,
        IGNORE_ERRORS = TRUE,
        ALL_VARCHAR = TRUE
    );
""")

print("=== FUNCION, COUNT(*) EN PUNO ===")
res_funciones = con.execute("""
    SELECT FUNCION, COUNT(*) as cantidad
    FROM inversiones
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
    GROUP BY FUNCION
    ORDER BY cantidad DESC
""").fetchall()
for fila in res_funciones:
    print(f"{fila[0]} -> {fila[1]}")

print("\n=== COUNT FUNCION = SANEAMIENTO ===")
count_saneamiento = con.execute("""
    SELECT COUNT(*)
    FROM inversiones
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
    AND UPPER(TRIM(FUNCION)) = 'SANEAMIENTO'
""").fetchone()[0]
print(count_saneamiento)

print("\n=== FUNCIONES QUE CONTIENEN 'SANEAMIENTO' ===")
res_saneamiento_like = con.execute("""
    SELECT FUNCION, COUNT(*) as cantidad
    FROM inversiones
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
    AND UPPER(TRIM(FUNCION)) LIKE '%SANEAMIENTO%'
    GROUP BY FUNCION
    ORDER BY cantidad DESC
""").fetchall()
for fila in res_saneamiento_like:
    print(f"{fila[0]} -> {fila[1]}")

print("\n=== DISTRIBUCION DE PROGRAMA (FUNCION = SANEAMIENTO) ===")
res_prog = con.execute("""
    SELECT PROGRAMA, COUNT(*) as cantidad
    FROM inversiones
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
    AND UPPER(TRIM(FUNCION)) = 'SANEAMIENTO'
    GROUP BY PROGRAMA
    ORDER BY cantidad DESC
""").fetchall()
for fila in res_prog:
    print(f"{fila[0]} -> {fila[1]}")

print("\n=== DISTRIBUCION DE SUBPROGRAMA (FUNCION = SANEAMIENTO) ===")
res_subprog = con.execute("""
    SELECT SUBPROGRAMA, COUNT(*) as cantidad
    FROM inversiones
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
    AND UPPER(TRIM(FUNCION)) = 'SANEAMIENTO'
    GROUP BY SUBPROGRAMA
    ORDER BY cantidad DESC
""").fetchall()
for fila in res_subprog:
    print(f"{fila[0]} -> {fila[1]}")


# Ahora, clasificar los 29 registros de auditoria
audit_path = Path("outputs/auditoria_saneamiento_fuera_funcion.csv")
clasificados = []

if audit_path.exists():
    with open(audit_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            func = row['FUNCION'].strip().upper()
            nombre = row['NOMBRE_INVERSION'].strip().upper()
            prog = row['PROGRAMA'].strip().upper()
            
            clase = ""
            motivo = ""
            
            # Clasificacion propuesta
            if func == 'SALUD Y SANEAMIENTO':
                clase = 'INCLUIR_HISTORICO'
                motivo = 'Clasificación antigua de agua y saneamiento'
            elif 'MERCADO' in nombre or func == 'COMERCIO':
                clase = 'EXCLUIR'
                motivo = 'Reparación de baños/agua en mercado'
            elif 'HIDROELECTRICA' in nombre or func == 'ENERGÍA':
                clase = 'EXCLUIR'
                motivo = 'Agua vinculada a hidroeléctrica/energía'
            elif 'CISTERNA' in nombre or 'HIDROJET' in nombre or 'EXCAVADORA' in nombre or 'AMBULANCIA' in nombre:
                clase = 'REVISAR'
                motivo = 'Adquisición de maquinaria para EPS/Saneamiento, la finalidad es agua, pero es equipamiento'
            elif 'AGUA' in nombre or 'SANEAMIENTO' in nombre:
                clase = 'REVISAR'
                motivo = 'Contiene palabras clave pero función oficial es diferente, requiere validación manual'
            else:
                clase = 'REVISAR'
                motivo = 'Otros casos a revisar'
                
            row['CLASIFICACION_PROPUESTA'] = clase
            row['MOTIVO'] = motivo
            clasificados.append(row)

    out_path = Path("outputs/auditoria_29_candidatos_clasificados.csv")
    with open(out_path, mode='w', encoding='utf-8', newline='') as f:
        if len(clasificados) > 0:
            writer = csv.DictWriter(f, fieldnames=list(clasificados[0].keys()))
            writer.writeheader()
            writer.writerows(clasificados)

    print("\nClasificación generada en:", out_path)
    
    # Resumen clasificacion
    incluir = sum(1 for c in clasificados if c['CLASIFICACION_PROPUESTA'] == 'INCLUIR_HISTORICO')
    revisar = sum(1 for c in clasificados if c['CLASIFICACION_PROPUESTA'] == 'REVISAR')
    excluir = sum(1 for c in clasificados if c['CLASIFICACION_PROPUESTA'] == 'EXCLUIR')
    
    print(f"INCLUIR_HISTORICO: {incluir}")
    print(f"REVISAR: {revisar}")
    print(f"EXCLUIR: {excluir}")

