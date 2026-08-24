import pandas as pd
import geopandas as gpd
import re
import time
import requests
import urllib3
import unicodedata
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EXCEL_FILES = [
    Path("/Users/pierotarazona/Downloads/Cartera_260824-123814.xlsx"),
    Path("/Users/pierotarazona/Downloads/Cartera_260824-124021.xlsx"),
    Path("/Users/pierotarazona/Downloads/Cartera_260824-124127.xlsx")
]
GPKG_FILE = Path("data/geografia/DISTRITO.gpkg")
CSV_OUT = Path("outputs/cartera_funcion_saneamiento_con_ubigeo.csv")
EXCEL_OUT = Path("outputs/cartera_funcion_saneamiento_con_ubigeo.xlsx")
AUDIT_OUT = Path("outputs/auditoria_ubigeo_cartera_saneamiento.csv")

def normalize_text(text):
    if pd.isna(text) or not isinstance(text, str): return ""
    text = text.replace('Á','A').replace('É','E').replace('Í','I').replace('Ó','O').replace('Ú','U').replace('Ü','U')
    s = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    return s.upper().strip()

def get_pmi_data(cui):
    url = "https://ofi5.mef.gob.pe/invierte/Pmi/traeListaCarteraSector"
    data = f"ddlSector=&txtCodigoUnico={cui}&ddlGobiernoRegional=&ddlDepartamento=&ddlMunProvincial=&ddlMunDistrital="
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post(url, data=data, headers=headers, verify=False, timeout=15)
        if r.status_code == 200:
            res = r.json()
            if isinstance(res, list) and len(res) > 0:
                item = res[0]
                return {
                    'NOMBRE_DISTRITO': item.get('NOMBRE_DISTRITO', ''),
                    'NOMBRE_PROVINCIA': item.get('NOMBRE_PROVINCIA', ''),
                    'NOMBRE_DEPARTAMENTO': item.get('NOMBRE_DEPARTAMENTO', '')
                }
            return []
    except Exception as e:
        print(f"Error PMI CUI {cui}: {e}")
    return None

def extract_ubigeo_from_name(nombre, dict_gpkg, dist_to_ubigeo, prov_to_ubigeo):
    nom = normalize_text(nombre)
    
    # 1. Detectar si es multidistrital
    if 'DISTRITOS DE' in nom or 'PROVINCIAS DE' in nom or 'DEPARTAMENTOS DE' in nom:
        return None, 'REVISAR_MULTIDISTRITAL', 'Múltiples distritos detectados en el nombre', []
        
    # Extraer el fragmento del distrito y provincia
    # Usualmente "DISTRITO DE X - PROVINCIA DE Y - DEPARTAMENTO DE Z"
    # O "DISTRITO DE X, PROVINCIA DE Y"
    match_dist = re.search(r'DISTRITO\s+DE\s+([A-Z0-9\s\.\-]+?)(?:,|\s-|\sY\s|$|PROVINCIA|DEPARTAMENTO)', nom)
    match_prov = re.search(r'PROVINCIA\s+DE\s+([A-Z0-9\s\.\-]+?)(?:,|\s-|\sY\s|$|DEPARTAMENTO)', nom)
    
    dist_name = match_dist.group(1).strip() if match_dist else ""
    prov_name = match_prov.group(1).strip() if match_prov else ""
    
    if not dist_name:
        return None, 'NO_IDENTIFICADO', 'No se detectó patrón "DISTRITO DE" en el nombre', []
        
    # Limpiar trailing words like "LA", "EN", etc (simple cleaning)
    dist_clean = re.sub(r'\s+(?:EN|LA|EL|LOS|LAS)\s*$', '', dist_name).strip()
    prov_clean = re.sub(r'\s+(?:EN|LA|EL|LOS|LAS)\s*$', '', prov_name).strip()
    
    candidatos = dist_to_ubigeo.get(dist_clean, [])
    
    if not candidatos:
        # Try direct matching inside the whole string as fallback? 
        # Risky, better to stay strict.
        return None, 'NO_IDENTIFICADO', f'Distrito {dist_clean} no encontrado en GPKG', []
        
    if len(candidatos) == 1:
        # Unambiguous
        return candidatos[0], 'RESUELTO', 'Coincidencia exacta y única por nombre', candidatos
        
    # Ambiguous, needs province resolution
    if prov_clean:
        candidatos_prov = prov_to_ubigeo.get(prov_clean, [])
        # Intersection
        inter = list(set(candidatos) & set(candidatos_prov))
        if len(inter) == 1:
            return inter[0], 'RESUELTO', f'Coincidencia resuelta usando provincia {prov_clean}', inter
        elif len(inter) > 1:
            return None, 'REVISAR_AMBIGUO', f'Distrito {dist_clean} ambiguo incluso con provincia {prov_clean}', inter
        else:
            return None, 'REVISAR_CONFLICTO', f'Distrito {dist_clean} no coincide con provincia {prov_clean}', candidatos
            
    return None, 'REVISAR_AMBIGUO', f'Distrito {dist_clean} es ambiguo y no se extrajo provincia', candidatos

def validate_against_pmi(cui, nombre_inversion, dict_gpkg, dist_to_ubigeo, prov_to_ubigeo, estado_previo):
    # If the user said "si el nombre menciona múltiples distritos... salvo que PMI permita identificar"
    res = get_pmi_data(cui)
    if res == []:
        return None, 'NO', 'NO_IDENTIFICADO' if estado_previo != 'REVISAR_MULTIDISTRITAL' else 'REVISAR_MULTIDISTRITAL', 'Búsqueda PMI devolvió lista vacía', 'BAJA'
    elif res is None:
        return None, 'NO', 'NO_IDENTIFICADO', 'Error de conexión PMI', 'BAJA'
        
    d_pmi = normalize_text(res['NOMBRE_DISTRITO'])
    p_pmi = normalize_text(res['NOMBRE_PROVINCIA'])
    
    cand_dist = dist_to_ubigeo.get(d_pmi, [])
    cand_prov = prov_to_ubigeo.get(p_pmi, [])
    inter = list(set(cand_dist) & set(cand_prov))
    
    ubigeo_pmi = None
    if len(inter) == 1: ubigeo_pmi = inter[0]
    elif len(cand_dist) == 1: ubigeo_pmi = cand_dist[0]
    
    if not ubigeo_pmi:
        return None, 'NO', 'REVISAR_CONFLICTO', f'Datos PMI no cruzaron con GPKG ({d_pmi} - {p_pmi})', 'BAJA'
        
    # Coincide nombre PMI?
    coincide = 'NO'
    nom = normalize_text(nombre_inversion)
    if d_pmi and d_pmi in nom:
        coincide = 'SI'
        
    estado = 'RESUELTO'
    confianza = 'ALTA'
    obs = f'Validado por PMI: {d_pmi}'
    
    if coincide == 'NO':
        estado = 'REVISAR_CONFLICTO'
        confianza = 'BAJA'
        obs = f'Distrito PMI ({d_pmi}) no encontrado en nombre de inversión'
        
    return ubigeo_pmi, coincide, estado, obs, confianza

def main():
    print("Leyendo y consolidando 3 excels de Cartera...")
    dfs = []
    total_leido = 0
    for f in EXCEL_FILES:
        try:
            d = pd.read_excel(f, header=5)
            d['ARCHIVO_ORIGEN'] = f.name
            total_leido += len(d)
            dfs.append(d)
        except Exception as e:
            print(f"Error leyendo {f.name}: {e}")
            
    df_all = pd.concat(dfs, ignore_index=True)
    
    # Clean column names (strip spaces)
    df_all.columns = [str(c).strip() for c in df_all.columns]
    col_cui = 'Código Único'
    col_funcion = 'Función'
    col_nombre = 'Nombre de inversión'
    
    # 1. Detect and report duplicates
    dup_counts = df_all[col_cui].value_counts()
    dups = dup_counts[dup_counts > 1].index
    
    consolidated_rows = []
    
    for cui in df_all[col_cui].unique():
        rows = df_all[df_all[col_cui] == cui]
        if len(rows) == 1:
            consolidated_rows.append(rows.iloc[0])
        else:
            # Duplicate handling
            # check if identical except ARCHIVO_ORIGEN
            cols_to_check = [c for c in df_all.columns if c != 'ARCHIVO_ORIGEN']
            unique_rows = rows.drop_duplicates(subset=cols_to_check)
            if len(unique_rows) == 1:
                # identical
                row = rows.iloc[0].copy()
                row['ARCHIVO_ORIGEN'] = ", ".join(rows['ARCHIVO_ORIGEN'].unique())
                consolidated_rows.append(row)
            else:
                # distinct! keep them and audit
                for _, r in rows.iterrows():
                    r_copy = r.copy()
                    r_copy['OBSERVACION_DUPLICADO'] = 'Diferencias encontradas entre archivos'
                    consolidated_rows.append(r_copy)
                    
    df_cons = pd.DataFrame(consolidated_rows)
    
    # Filter SANEAMIENTO
    df_san = df_cons[df_cons[col_funcion].astype(str).str.upper().str.strip() == 'SANEAMIENTO'].copy()
    
    print("Cargando DISTRITO.gpkg para validación nacional...")
    gdf = gpd.read_file(GPKG_FILE)
    dict_gpkg = {}
    dist_to_ubigeo = {}
    prov_to_ubigeo = {}
    
    for _, row in gdf.iterrows():
        u = str(row['ubigeo']).zfill(6)
        d = normalize_text(row['nombdist'])
        p = normalize_text(row['nombprov'])
        dict_gpkg[u] = {'dist': d, 'prov': p}
        
        if d not in dist_to_ubigeo: dist_to_ubigeo[d] = []
        dist_to_ubigeo[d].append(u)
        
        if p not in prov_to_ubigeo: prov_to_ubigeo[p] = []
        prov_to_ubigeo[p].append(u)
        
    df_san['UBIGEO_DESDE_NOMBRE'] = ''
    df_san['UBIGEO_VALIDADO_PMI'] = ''
    df_san['UBIGEO_FINAL_VALIDADO'] = ''
    df_san['PMI_ENCONTRADO'] = ''
    df_san['COINCIDE_NOMBRE_PMI'] = ''
    df_san['METODO_EXTRACCION_UBIGEO'] = ''
    df_san['CONFIANZA_UBIGEO'] = ''
    df_san['ESTADO_UBIGEO'] = ''
    df_san['UBIGEOS_CANDIDATOS'] = ''
    df_san['OBSERVACION_UBIGEO'] = ''
    
    count_nombre = 0
    count_pmi = 0
    count_vacio = 0
    count_conflict = 0
    count_multi = 0
    count_pend = 0
    
    print(f"Procesando {len(df_san)} proyectos de Saneamiento...")
    for idx, row in df_san.iterrows():
        raw_cui = str(row[col_cui]).strip()
        try:
            cui = str(int(float(raw_cui)))
        except:
            cui = raw_cui
        nom = str(row[col_nombre])
        
        # 1. Nombre
        ubigeo_nom, estado, obs, cands = extract_ubigeo_from_name(nom, dict_gpkg, dist_to_ubigeo, prov_to_ubigeo)
        
        df_san.at[idx, 'UBIGEO_DESDE_NOMBRE'] = ubigeo_nom if ubigeo_nom else ''
        df_san.at[idx, 'ESTADO_UBIGEO'] = estado
        df_san.at[idx, 'OBSERVACION_UBIGEO'] = obs
        df_san.at[idx, 'UBIGEOS_CANDIDATOS'] = ", ".join(cands)
        
        if estado == 'RESUELTO':
            df_san.at[idx, 'UBIGEO_FINAL_VALIDADO'] = ubigeo_nom
            df_san.at[idx, 'METODO_EXTRACCION_UBIGEO'] = 'EXTRAIDO_DESDE_NOMBRE'
            df_san.at[idx, 'CONFIANZA_UBIGEO'] = 'ALTA'
            count_nombre += 1
        else:
            # 2. Fallback PMI
            print(f"Fallback PMI para CUI {cui}...")
            time.sleep(1.2)
            u_pmi, coincide, estado_pmi, obs_pmi, conf = validate_against_pmi(cui, nom, dict_gpkg, dist_to_ubigeo, prov_to_ubigeo, estado)
            
            df_san.at[idx, 'UBIGEO_VALIDADO_PMI'] = u_pmi if u_pmi else ''
            df_san.at[idx, 'COINCIDE_NOMBRE_PMI'] = coincide
            
            if u_pmi and coincide == 'NO':
                count_conflict += 1
                df_san.at[idx, 'PMI_ENCONTRADO'] = 'SI'
            elif u_pmi and coincide == 'SI':
                count_pmi += 1
                df_san.at[idx, 'PMI_ENCONTRADO'] = 'SI'
                df_san.at[idx, 'UBIGEO_FINAL_VALIDADO'] = u_pmi
            elif not u_pmi and estado_pmi != 'REVISAR_MULTIDISTRITAL':
                if obs_pmi == 'Búsqueda PMI devolvió lista vacía':
                    count_vacio += 1
                df_san.at[idx, 'PMI_ENCONTRADO'] = 'NO'
                
            if estado_pmi == 'REVISAR_MULTIDISTRITAL':
                count_multi += 1
                
            df_san.at[idx, 'ESTADO_UBIGEO'] = estado_pmi
            df_san.at[idx, 'OBSERVACION_UBIGEO'] = df_san.at[idx, 'OBSERVACION_UBIGEO'] + " | " + obs_pmi
            df_san.at[idx, 'METODO_EXTRACCION_UBIGEO'] = 'VALIDADO_PMI_POR_CUI' if u_pmi else 'FALLIDO'
            df_san.at[idx, 'CONFIANZA_UBIGEO'] = conf
            
            if estado_pmi not in ['RESUELTO', 'REVISAR_MULTIDISTRITAL']:
                count_pend += 1

    df_san.to_csv(CSV_OUT, index=False)
    
    # Auditoria
    cols_aud = [col_cui, col_nombre, 'ARCHIVO_ORIGEN', 'UBIGEO_DESDE_NOMBRE', 'UBIGEO_VALIDADO_PMI', 'UBIGEO_FINAL_VALIDADO', 'PMI_ENCONTRADO', 'COINCIDE_NOMBRE_PMI', 'METODO_EXTRACCION_UBIGEO', 'CONFIANZA_UBIGEO', 'ESTADO_UBIGEO', 'UBIGEOS_CANDIDATOS', 'OBSERVACION_UBIGEO']
    df_san[cols_aud].to_csv(AUDIT_OUT, index=False)
    
    print(f"Generando Excel {EXCEL_OUT.name}...")
    with pd.ExcelWriter(EXCEL_OUT, engine='openpyxl') as writer:
        df_san.to_excel(writer, sheet_name='SANEAMIENTO_UBIGEO', index=False)
        df_san[cols_aud].to_excel(writer, sheet_name='AUDITORIA', index=False)
        
    pct_res = ((count_nombre + count_pmi) / len(df_san)) * 100
    
    print("\n=== REPORTE FINAL V6 (CARTERA SANEAMIENTO) ===")
    print(f"1. Total leído en los 3 Excel: {total_leido}")
    print(f"2. Total Función = SANEAMIENTO: {len(df_san)}")
    print(f"3. CUIs únicos: {df_san[col_cui].nunique()}")
    print(f"4. Duplicados detectados: {len(dups)}")
    print(f"5. Resueltos solo por nombre: {count_nombre}")
    print(f"6. Resueltos mediante PMI: {count_pmi}")
    print(f"7. PMI con respuesta []: {count_vacio}")
    print(f"8. Conflictos (Nombre vs PMI): {count_conflict}")
    print(f"9. Multidistritales (sin resolver): {count_multi}")
    print(f"10. Pendientes/No identificados: {count_pend}")
    print(f"11. Porcentaje final resuelto: {pct_res:.1f}%")
    
    resueltos = df_san[df_san['ESTADO_UBIGEO'] == 'RESUELTO']
    pendientes = df_san[df_san['ESTADO_UBIGEO'] != 'RESUELTO']
    
    def clean_cui(c):
        try: return str(int(float(c)))
        except: return str(c)
        
    print(f"\n12. Ejemplos resueltos (hasta 10):")
    for _, r in resueltos.head(10).iterrows():
        print(f"  - CUI {clean_cui(r[col_cui])}: UBIGEO {r['UBIGEO_FINAL_VALIDADO']} ({r['METODO_EXTRACCION_UBIGEO']})")
        
    print(f"\n13. Ejemplos pendientes para revisión (hasta 10):")
    for _, r in pendientes.head(10).iterrows():
        print(f"  - CUI {clean_cui(r[col_cui])}: ESTADO {r['ESTADO_UBIGEO']} | OBS: {r['OBSERVACION_UBIGEO']}")
        
    print(f"\n14. Rutas generadas:")
    print(f"  - CSV: {CSV_OUT.as_posix()}")
    print(f"  - Excel: {EXCEL_OUT.as_posix()}")
    print(f"  - Auditoría: {AUDIT_OUT.as_posix()}")

if __name__ == "__main__":
    main()
