from pathlib import Path
import duckdb

CSV_PATH = Path("data/raw/DETALLE_INVERSIONES.csv")

if not CSV_PATH.exists():
    raise FileNotFoundError(f"No se encontró el archivo: {CSV_PATH.resolve()}")

con = duckdb.connect()

print("Cargando datos (esto puede tardar unos segundos)...")
# Create base view for Puno
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

# Create view for Saneamiento
con.execute("""
    CREATE OR REPLACE TEMP VIEW puno_saneamiento AS
    SELECT *
    FROM inversiones_puno
    WHERE UPPER(TRIM(FUNCION)) = 'SANEAMIENTO';
""")

# --- 1. Cantidad real de proyectos ---
print("\n" + "="*50)
print("1. CANTIDAD REAL DE PROYECTOS (FUNCION = SANEAMIENTO)")
print("="*50)

total_filas = con.execute("SELECT COUNT(*) FROM puno_saneamiento").fetchone()[0]
total_cuis = con.execute("SELECT COUNT(DISTINCT CODIGO_UNICO) FROM puno_saneamiento").fetchone()[0]
sin_cui = con.execute("SELECT COUNT(*) FROM puno_saneamiento WHERE CODIGO_UNICO IS NULL OR TRIM(CODIGO_UNICO) = ''").fetchone()[0]

cui_stats = con.execute("""
    WITH cui_counts AS (
        SELECT CODIGO_UNICO, COUNT(*) as n FROM puno_saneamiento GROUP BY CODIGO_UNICO
    )
    SELECT 
        SUM(CASE WHEN n = 1 THEN 1 ELSE 0 END) as una_vez,
        SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) as mas_de_una,
        MAX(n) as max_filas
    FROM cui_counts
""").fetchone()

print(f"Total de filas: {total_filas:,}")
print(f"Total de CODIGO_UNICO distintos: {total_cuis:,}")
print(f"Registros sin CODIGO_UNICO: {sin_cui:,}")
print(f"CUIs que aparecen una sola vez: {cui_stats[0]:,}")
print(f"CUIs que aparecen más de una vez: {cui_stats[1]:,}")
print(f"Máximo número de filas asociado a un mismo CUI: {cui_stats[2]:,}")

print("\nTop 20 CUIs con más registros:")
top_cuis = con.execute("""
    SELECT 
        CODIGO_UNICO,
        MAX(NOMBRE_INVERSION) as NOMBRE_INVERSION,
        COUNT(*) as filas,
        COUNT(DISTINCT PROVINCIA) as dist_prov,
        COUNT(DISTINCT DISTRITO) as dist_dist,
        COUNT(DISTINCT UBIGEO) as dist_ubi
    FROM puno_saneamiento
    GROUP BY CODIGO_UNICO
    ORDER BY filas DESC
    LIMIT 20
""").fetchall()

print(f"{'CUI':<10} | {'FILAS':<6} | {'PROV':<4} | {'DIST':<4} | {'UBIG':<4} | {'NOMBRE'}")
print("-" * 100)
for fila in top_cuis:
    nombre_corto = (fila[1][:50] + '...') if fila[1] and len(fila[1]) > 50 else fila[1]
    print(f"{fila[0]:<10} | {fila[2]:<6} | {fila[3]:<4} | {fila[4]:<4} | {fila[5]:<4} | {nombre_corto}")

# --- 2. Revisar clasificación oficial de saneamiento ---
print("\n" + "="*50)
print("2. CLASIFICACIÓN OFICIAL (FUNCION = SANEAMIENTO)")
print("="*50)

campos_clasificacion = [
    "PROGRAMA", "SUBPROGRAMA", "DES_TIPOLOGIA", "TIPO_INVERSION", 
    "NIVEL", "ESTADO", "SITUACION", "EXPEDIENTE_TECNICO", "ETAPA_F8",
    "TIENE_F8", "TIENE_F12B", "TIENE_AVAN_FISICO", "REGISTRADO_PMI"
]

for campo in campos_clasificacion:
    print(f"\nDistribución por {campo}:")
    try:
        resultados = con.execute(f"""
            SELECT {campo}, COUNT(*) as n 
            FROM puno_saneamiento 
            GROUP BY {campo} 
            ORDER BY n DESC
        """).fetchall()
        for fila in resultados:
            print(f"  {fila[0]} -> {fila[1]}")
    except duckdb.BinderException:
        print(f"  Columna {campo} no encontrada.")

# --- 3. Buscar posibles falsos negativos ---
print("\n" + "="*50)
print("3. POSIBLES PROYECTOS DE AGUA/SANEAMIENTO (FUERA DE FUNCION = SANEAMIENTO)")
print("="*50)

patron = 'AGUA POTABLE|SANEAMIENTO|ALCANTARILLADO|AGUAS RESIDUALES|\\bPTAR\\b|\\bPTAP\\b|DISPOSICION SANITARIA|EXCRETAS|DESAGUE|DRENAJE PLUVIAL'

con.execute(f"""
    CREATE OR REPLACE TEMP VIEW posibles_saneamiento AS
    SELECT 
        CODIGO_UNICO, 
        NOMBRE_INVERSION, 
        FUNCION, 
        PROGRAMA, 
        SUBPROGRAMA, 
        DES_TIPOLOGIA, 
        PROVINCIA, 
        DISTRITO
    FROM inversiones_puno
    WHERE UPPER(TRIM(FUNCION)) <> 'SANEAMIENTO'
      AND (
          REGEXP_MATCHES(UPPER(COALESCE(NOMBRE_INVERSION, '')), '{patron}')
          OR REGEXP_MATCHES(UPPER(COALESCE(PROGRAMA, '')), '{patron}')
          OR REGEXP_MATCHES(UPPER(COALESCE(SUBPROGRAMA, '')), '{patron}')
          OR REGEXP_MATCHES(UPPER(COALESCE(DES_TIPOLOGIA, '')), '{patron}')
      );
""")

cantidad_falsos_negativos = con.execute("SELECT COUNT(*) FROM posibles_saneamiento").fetchone()[0]
print(f"Cantidad de registros encontrados fuera de FUNCION=SANEAMIENTO: {cantidad_falsos_negativos:,}")

if cantidad_falsos_negativos > 0:
    out_path = Path("outputs/auditoria_saneamiento_fuera_funcion.csv")
    out_path.parent.mkdir(exist_ok=True)
    con.execute(f"""
        COPY (SELECT * FROM posibles_saneamiento) 
        TO '{out_path.as_posix()}' (HEADER, DELIMITER ',');
    """)
    print(f"Archivo de auditoría generado: {out_path}")

# --- 4. Distribución territorial ---
print("\n" + "="*50)
print("4. DISTRIBUCIÓN TERRITORIAL (FUNCION = SANEAMIENTO)")
print("="*50)

print("Por Provincia:")
provincias = con.execute("""
    SELECT PROVINCIA, COUNT(*) as filas, COUNT(DISTINCT CODIGO_UNICO) as cuis 
    FROM puno_saneamiento 
    GROUP BY PROVINCIA 
    ORDER BY cuis DESC
""").fetchall()

for fila in provincias:
    print(f"  {fila[0]}: {fila[2]} CUIs ({fila[1]} filas)")

print("\nTop 20 Distritos con más CUIs:")
distritos = con.execute("""
    SELECT DISTRITO, COUNT(*) as filas, COUNT(DISTINCT CODIGO_UNICO) as cuis 
    FROM puno_saneamiento 
    GROUP BY DISTRITO 
    ORDER BY cuis DESC
    LIMIT 20
""").fetchall()

for fila in distritos:
    print(f"  {fila[0]}: {fila[2]} CUIs ({fila[1]} filas)")
