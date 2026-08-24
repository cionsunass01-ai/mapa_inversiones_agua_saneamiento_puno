import pandas as pd
from pathlib import Path

# Analyze data/raw/DETALLE_INVERSIONES.csv against outputs/proyectos_agua_saneamiento_puno_v3.csv
CSV_V3 = Path("outputs/proyectos_agua_saneamiento_puno_v3.csv")
RAW_CSV = Path("data/raw/DETALLE_INVERSIONES.csv")

def is_valid_numeric(val):
    if pd.isna(val) or val == '' or str(val).strip().lower() in ['nan', 'none', 'null']:
        return False
    return True

def parse_num(val):
    if not is_valid_numeric(val): return None
    try:
        return float(val)
    except:
        return None

def main():
    # Load the subset of 761 CUIs
    v3_cuis = set(pd.read_csv(CSV_V3, dtype=str)['CODIGO_UNICO'])
    
    # Load raw file
    raw = pd.read_csv(RAW_CSV, dtype=str, keep_default_na=False)
    df = raw[raw['CODIGO_UNICO'].isin(v3_cuis)].copy()
    
    cols = ['DEVEN_ACUMUL_ANIO_ANT', 'DEV_ANIO_ACTUAL', 'AVANCE_FISICO', 'AVANCE_EJECUCION', 'ULT_FEC_DECLA_ESTIM']
    stats = {}
    
    for c in cols:
        valid_count = 0
        zero_count = 0
        missing_count = 0
        
        for val in df[c]:
            if not is_valid_numeric(val):
                missing_count += 1
            else:
                num = parse_num(val)
                if num is not None:
                    if num == 0.0:
                        zero_count += 1
                    valid_count += 1
                else:
                    if c == 'ULT_FEC_DECLA_ESTIM':
                        valid_count += 1 # it's a date
                    else:
                        missing_count += 1
                        
        stats[c] = {'valid': valid_count, 'zero': zero_count, 'missing': missing_count}
        
    # Both Devengados
    both = 0
    for idx, r in df.iterrows():
        ant = parse_num(r['DEVEN_ACUMUL_ANIO_ANT'])
        act = parse_num(r['DEV_ANIO_ACTUAL'])
        if ant is not None and act is not None:
            both += 1
            
    print("=== ANÁLISIS DE DATOS EXISTENTES (761 proyectos) ===")
    for k, v in stats.items():
        print(f"- {k}:")
        if k != 'ULT_FEC_DECLA_ESTIM':
            print(f"  Válidos (incluyendo ceros): {v['valid']} | Ceros explícitos: {v['zero']} | Vacíos/Nulos: {v['missing']}")
        else:
            print(f"  Fechas Válidas: {v['valid']} | Vacíos/Nulos: {v['missing']}")
            
    print(f"- Registros con AMBOS devengados (DEVEN_ACUMUL_ANIO_ANT y DEV_ANIO_ACTUAL): {both}")

if __name__ == "__main__":
    main()
