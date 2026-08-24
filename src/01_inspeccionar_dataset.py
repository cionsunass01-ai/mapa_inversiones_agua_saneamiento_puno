from pathlib import Path
import duckdb

CSV_PATH = Path("data/raw/DETALLE_INVERSIONES.csv")

if not CSV_PATH.exists():
    raise FileNotFoundError(
        f"No se encontró el archivo: {CSV_PATH.resolve()}"
    )

print(f"Archivo encontrado: {CSV_PATH}")
print(f"Tamaño: {CSV_PATH.stat().st_size / 1024 / 1024:.2f} MB")

# Connect to DuckDB
con = duckdb.connect()

# Create a view, handling potential encoding issues or bad lines if necessary
try:
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
except Exception as e:
    print(f"Error reading CSV with default settings: {e}")
    print("Attempting with latin1 encoding...")
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW inversiones AS
        SELECT *
        FROM read_csv(
            '{CSV_PATH.as_posix()}',
            HEADER = TRUE,
            AUTO_DETECT = TRUE,
            IGNORE_ERRORS = TRUE,
            ALL_VARCHAR = TRUE,
            ENCODING = 'latin1'
        );
    """)

# 1. Total records
total = con.execute("""
    SELECT COUNT(*)
    FROM inversiones
""").fetchone()[0]

print(f"\nTotal de registros: {total:,}")

# 2. Columns available
print("\n=== COLUMNAS ===")

columnas = con.execute("""
    DESCRIBE inversiones
""").fetchall()

for columna in columnas:
    print(f"{columna[0]} -> {columna[1]}")

# 3. Total in Puno
total_puno = con.execute("""
    SELECT COUNT(*)
    FROM inversiones
    WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
""").fetchone()[0]

print(f"\nTotal de registros ubicados en Puno: {total_puno:,}")

# Groups to calculate
grupos = [
    "FUNCION",
    "PROGRAMA",
    "SUBPROGRAMA",
    "DES_TIPOLOGIA",
    "SECTOR",
    "NIVEL",
    "ESTADO",
    "SITUACION",
    "TIPO_INVERSION",
    "ETAPA_F8"
]

for grupo in grupos:
    print(f"\n=== {grupo} EN PUNO ===")
    try:
        resultados = con.execute(f"""
            SELECT
                {grupo},
                COUNT(*) AS cantidad
            FROM inversiones
            WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
            GROUP BY {grupo}
            ORDER BY cantidad DESC
        """).fetchall()
        
        for fila in resultados:
            print(f"{fila[0]} -> {fila[1]}")
    except duckdb.BinderException:
         print(f"Columna {grupo} no encontrada en el dataset.")

# Additional flags
flags = [
    "EXPEDIENTE_TECNICO",
    "TIENE_F8",
    "TIENE_F12B",
    "TIENE_AVAN_FISICO",
    "REGISTRADO_PMI"
]

print("\n=== REGISTROS CON INDICADORES EN PUNO ===")
for flag in flags:
    try:
        cantidad = con.execute(f"""
            SELECT COUNT(*)
            FROM inversiones
            WHERE UPPER(TRIM(DEPARTAMENTO)) = 'PUNO'
              AND {flag} IS NOT NULL
              AND UPPER(TRIM(CAST({flag} AS VARCHAR))) NOT IN ('', '0', 'NO', 'FALSE', 'N')
        """).fetchone()[0]
        print(f"{flag}: {cantidad:,}")
    except duckdb.BinderException:
         print(f"{flag}: Columna no encontrada")

print("\nAnálisis inicial terminado.")