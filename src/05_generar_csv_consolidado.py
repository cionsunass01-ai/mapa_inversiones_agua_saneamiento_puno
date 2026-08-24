import duckdb
from pathlib import Path
import os

CSV_PATH = Path("data/raw/DETALLE_INVERSIONES.csv")
OUT_PATH = Path("outputs/proyectos_agua_saneamiento_puno.csv")

con = duckdb.connect()

# 1. Cargar archivo original
con.execute(f"""
    CREATE OR REPLACE TEMP VIEW fuente AS
    SELECT *
    FROM read_csv_auto(
        '{CSV_PATH.as_posix()}',
        HEADER = TRUE,
        IGNORE_ERRORS = TRUE,
        ALL_VARCHAR = TRUE
    );
""")

# 2. Cargar listas de control
con.execute("""
    CREATE OR REPLACE TEMP VIEW seguro AS
    SELECT TRIM(CODIGO_UNICO) as CODIGO_UNICO FROM read_csv_auto('outputs/universo_seguro.csv', HEADER=TRUE, ALL_VARCHAR=TRUE)
""")
con.execute("""
    CREATE OR REPLACE TEMP VIEW complementario AS
    SELECT TRIM(CODIGO_UNICO) as CODIGO_UNICO FROM read_csv_auto('outputs/universo_complementario.csv', HEADER=TRUE, ALL_VARCHAR=TRUE)
""")
con.execute("""
    CREATE OR REPLACE TEMP VIEW revision AS
    SELECT TRIM(CODIGO_UNICO) as CODIGO_UNICO FROM read_csv_auto('outputs/revision_manual.csv', HEADER=TRUE, ALL_VARCHAR=TRUE)
""")

# Obtener todas las columnas originales
columnas_originales = [c[0] for c in con.execute("DESCRIBE fuente").fetchall()]

# Columnas obligatorias solicitadas por el usuario en orden
columnas_obligatorias = [
    "CODIGO_UNICO", "CODIGO_SNIP", "NOMBRE_INVERSION", "TIPO_INVERSION",
    "NIVEL", "SECTOR", "ENTIDAD", "NOMBRE_OPMI", "NOMBRE_UF", "NOMBRE_UEI", "SEC_EJEC", "NOMBRE_UEP",
    "FUNCION", "PROGRAMA", "SUBPROGRAMA", "DES_TIPOLOGIA",
    "ESTADO", "SITUACION", "FECHA_REGISTRO", "FECHA_VIABILIDAD", "MARCO",
    "MONTO_VIABLE", "COSTO_ACTUALIZADO", "CTRL_CONCURR", "MONTO_LAUDO", "MONTO_FIANZA", "SALDO_EJECUTAR",
    "REGISTRADO_PMI", "PMI_ANIO_1", "PMI_ANIO_2", "PMI_ANIO_3", "PMI_ANIO_4",
    "PRIMER_DEVENGADO", "ULTIMO_DEVENGADO", "DEVEN_ACUMUL_ANIO_ANT", "DEV_ANIO_ACTUAL", 
    "PIA_ANIO_ACTUAL", "PIM_ANIO_ACTUAL", "CERTIF_ANIO_ACTUAL", "COMPROM_ANUAL_ANIO_ACTUAL",
    "EXPEDIENTE_TECNICO", "MONTO_ET_F8", "TIENE_F8", "ETAPA_F8", "TIENE_F12B",
    "TIENE_AVAN_FISICO", "AVANCE_FISICO", "AVANCE_EJECUCION", "ULT_FEC_DECLA_ESTIM",
    "FEC_INI_EJECUCION", "FEC_FIN_EJECUCION", "FEC_INI_EJEC_FISICA", "FEC_FIN_EJEC_FISICA",
    "INFORME_CIERRE", "TIENE_F9", "FEC_REG_F9", "ETAPA_F9",
    "DEPARTAMENTO", "PROVINCIA", "DISTRITO", "UBIGEO", "LATITUD", "LONGITUD",
    "ALTERNATIVA", "DES_MODALIDAD", "IND_IOARR_EMERG", "NUM_HABITANTES_BENEF", "ANIO_PROCESO"
]

# Columnas adicionales (presentes en original pero no en la lista obligatoria)
columnas_adicionales = [c for c in columnas_originales if c not in columnas_obligatorias]

# Construir la lista de selección con TRIM para TODAS las columnas
select_fields = ["TRIM(CODIGO_UNICO) AS CODIGO_UNICO"]

# Agregar las columnas de clasificación
select_fields.append("""
    CASE 
        WHEN UPPER(TRIM(FUNCION)) = 'SANEAMIENTO' THEN 'OFICIAL_SANEAMIENTO'
        WHEN UPPER(TRIM(FUNCION)) = 'SALUD Y SANEAMIENTO' THEN 'HISTORICO_SALUD_Y_SANEAMIENTO'
        ELSE 'COMPLEMENTARIO_VALIDADO'
    END AS ORIGEN_CLASIFICACION
""")
select_fields.append("""
    CASE 
        WHEN UPPER(TRIM(FUNCION)) = 'SANEAMIENTO' THEN 'Clasificado oficialmente por el MEF en la función SANEAMIENTO'
        WHEN UPPER(TRIM(FUNCION)) = 'SALUD Y SANEAMIENTO' THEN 'Proyecto histórico de agua/saneamiento registrado bajo la antigua función SALUD Y SANEAMIENTO'
        ELSE 'Inversión de otra función cuya finalidad directa corresponde al servicio de agua y saneamiento'
    END AS CRITERIO_INCLUSION
""")

# Agregar el resto de obligatorias y adicionales con TRIM
for col in columnas_obligatorias[1:]: # saltar CODIGO_UNICO
    # Por si la columna no existe en el CSV, usar NULL
    if col in columnas_originales:
        select_fields.append(f"TRIM({col}) AS {col}")
    else:
        select_fields.append(f"NULL AS {col}")

for col in columnas_adicionales:
    select_fields.append(f"TRIM({col}) AS {col}")

select_clause = ",\n".join(select_fields)

# 3. Construir la vista final
sql_final = f"""
    CREATE OR REPLACE TEMP VIEW dataset_final AS
    SELECT {select_clause}
    FROM fuente
    WHERE (TRIM(CODIGO_UNICO) IN (SELECT CODIGO_UNICO FROM seguro)
       OR TRIM(CODIGO_UNICO) IN (SELECT CODIGO_UNICO FROM complementario))
      AND TRIM(CODIGO_UNICO) NOT IN (SELECT CODIGO_UNICO FROM revision)
"""

con.execute(sql_final)

# 4. Generar el CSV
print(f"Exportando a {OUT_PATH}...")
con.execute(f"COPY (SELECT * FROM dataset_final) TO '{OUT_PATH.as_posix()}' (HEADER, DELIMITER ',')")

# 5. Integridad y Validaciones
print("\n=== VERIFICACIÓN DE INTEGRIDAD ===")
filas = con.execute("SELECT COUNT(*) FROM dataset_final").fetchone()[0]
cuis = con.execute("SELECT COUNT(DISTINCT CODIGO_UNICO) FROM dataset_final").fetchone()[0]
duplicados = filas - cuis
nulos = con.execute("SELECT COUNT(*) FROM dataset_final WHERE CODIGO_UNICO IS NULL").fetchone()[0]
distintos_dept = con.execute("SELECT DISTINCT DEPARTAMENTO FROM dataset_final").fetchall()
dept_puno = all(d[0].strip().upper() == 'PUNO' for d in distintos_dept)

en_revision = con.execute("SELECT COUNT(*) FROM dataset_final WHERE CODIGO_UNICO IN (SELECT CODIGO_UNICO FROM revision)").fetchone()[0]

print(f"Filas totales: {filas} (Esperado: 761)")
print(f"CUIs únicos: {cuis} (Esperado: 761)")
print(f"CUIs duplicados: {duplicados} (Esperado: 0)")
print(f"CUIs nulos: {nulos} (Esperado: 0)")
print(f"Departamento es PUNO en todos: {dept_puno}")
print(f"CUIs de revisión presentes: {en_revision} (Esperado: 0)")

print("\n=== RESUMEN DE DATOS ===")
def print_agrupacion(campo):
    print(f"\nCantidad por {campo}:")
    try:
        res = con.execute(f"SELECT {campo}, COUNT(*) FROM dataset_final GROUP BY {campo} ORDER BY COUNT(*) DESC").fetchall()
        for r in res:
            print(f"  {r[0]} -> {r[1]}")
    except Exception as e:
         print("  No disponible o error")

print_agrupacion("ORIGEN_CLASIFICACION")
print_agrupacion("PROVINCIA")
print_agrupacion("PROGRAMA")
print_agrupacion("SUBPROGRAMA")
print_agrupacion("ESTADO")
print_agrupacion("SITUACION")
print_agrupacion("ETAPA_F8")

file_size_mb = OUT_PATH.stat().st_size / (1024 * 1024)
print(f"\nTamaño del archivo final: {file_size_mb:.2f} MB")
