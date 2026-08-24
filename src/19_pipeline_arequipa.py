import duckdb
import pandas as pd
import geopandas as gpd
import requests
import time
import re
from pathlib import Path

RAW_CSV = Path("data/raw/DETALLE_INVERSIONES.csv")
CACHE_FILE = Path("data/processed/cache_coordenadas_arequipa.csv")
EPS_SHP = Path("/Users/pierotarazona/Downloads/Rodrigo_Puno y Arequipa/EPS_Arequipa.shp")
CSV_OUT = Path("outputs/proyectos_agua_saneamiento_arequipa_v1.csv")
EXCEL_OUT = Path("outputs/proyectos_agua_saneamiento_arequipa_v1.xlsx")
FECHA_REFERENCIA = pd.to_datetime("2026-08-24")

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

def cargar_cache():
    if CACHE_FILE.exists():
        df = pd.read_csv(CACHE_FILE, dtype=str).drop_duplicates(subset=['CODIGO_UNICO'])
        return df.set_index('CODIGO_UNICO').to_dict('index')
    return {}

def guardar_cache(cache_dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame.from_dict(cache_dict, orient='index')
    df.index.name = 'CODIGO_UNICO'
    df.reset_index().to_csv(CACHE_FILE, index=False)

def validar_coordenadas(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
        if lat == 0.0 or lon == 0.0: return False, lat, lon
        if (lat < -68 and lat > -76) and (lon < -13 and lon > -18):
            lat, lon = lon, lat 
        if lat > 0: lat = -lat
        if lon > 0: lon = -lon
        # Arequipa bounds approx: Lat -17.5 to -14.5, Lon -75.0 to -70.5
        if -17.5 <= lat <= -14.5 and -75.0 <= lon <= -70.5:
            return True, lat, lon
        return False, lat, lon
    except:
        return False, 0.0, 0.0

def geocode_nominatim(query):
    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': query, 'format': 'json', 'limit': 1}
    headers = {'User-Agent': 'ArequipaAguaSaneamientoBot/1.0'}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            if d: return float(d[0]['lat']), float(d[0]['lon'])
    except Exception as e:
        print(f"Error geocoding {query}: {e}")
    return None, None

def extraer_localidad(nombre):
    patrones = [
        r"(?:LOCALIDAD|COMUNIDAD|CENTRO POBLADO|SECTOR|BARRIO|PARCIALIDAD) (?:DE |CAMPESINA DE )?([A-Z\s]+?)(?:, | DEL | EN | - )",
        r"(?:EN |A |LAS )?(?:LOCALIDADES|COMUNIDADES) (?:DE )?([A-Z\s]+?)(?:, | Y | DEL | EN | - )"
    ]
    for p in patrones:
        m = re.search(p, str(nombre), re.IGNORECASE)
        if m:
            loc = m.group(1).strip()
            if len(loc) > 3 and loc.upper() not in ["LOS", "LAS", "EL", "LA"]:
                return loc
    return None

def parse_num(val):
    if pd.isna(val) or str(val).strip().lower() in ['', 'nan', 'none', 'null']: return None
    try: return float(val)
    except: return None

def main():
    print("1. Extracción con DuckDB (Arequipa)...")
    con = duckdb.connect()
    
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW fuente AS
        SELECT * FROM read_csv_auto('{RAW_CSV.as_posix()}', HEADER=TRUE, IGNORE_ERRORS=TRUE, ALL_VARCHAR=TRUE)
        WHERE UPPER(TRIM(DEPARTAMENTO)) = 'AREQUIPA'
          AND (UPPER(TRIM(FUNCION)) = 'SANEAMIENTO' OR UPPER(TRIM(FUNCION)) = 'SALUD Y SANEAMIENTO')
    """)
    
    # Check what columns exist in the source
    existing_cols = [c[0] for c in con.execute("DESCRIBE fuente").fetchall()]
    
    select_fields = ["TRIM(CODIGO_UNICO) AS CODIGO_UNICO"]
    select_fields.append("""
        CASE 
            WHEN UPPER(TRIM(FUNCION)) = 'SANEAMIENTO' THEN 'OFICIAL_SANEAMIENTO'
            ELSE 'HISTORICO_SALUD_Y_SANEAMIENTO'
        END AS ORIGEN_CLASIFICACION
    """)
    for col in columnas_obligatorias[1:]:
        if col in existing_cols:
            select_fields.append(f"TRIM({col}) AS {col}")
        else:
            select_fields.append(f"NULL AS {col}")
            
    sql_final = "SELECT " + ",\n".join(select_fields) + " FROM fuente"
    df = con.execute(sql_final).df()
    
    print(f"Proyectos extraídos: {len(df)}")
    
    print("2. Procesamiento de Coordenadas, Métricas y Antigüedad...")
    cache = cargar_cache()
    df['LATITUD_MEF'] = df['LATITUD']
    df['LONGITUD_MEF'] = df['LONGITUD']
    
    # Initialize columns
    for col in ['LATITUD', 'LONGITUD', 'FUENTE_COORDENADA', 'TIPO_COORDENADA', 'ESTADO_ENRIQUECIMIENTO',
                'PRESUPUESTO_EJECUTADO', 'AVANCE_FINANCIERO_CALCULADO', 'FECHA_REFERENCIA_EJECUCION',
                'ESTADO_ACTUALIZACION_FISICA', 'ADVERTENCIA_AVANCE_FISICO', 'ANTIGUEDAD_REPORTE_FISICO_DIAS']:
        df[col] = ''
        
    for idx, row in df.iterrows():
        cui = str(row['CODIGO_UNICO']).strip()
        
        # --- Coordenadas ---
        valido, lat_val, lon_val = validar_coordenadas(row['LATITUD_MEF'], row['LONGITUD_MEF'])
        if valido:
            lat_nueva, lon_nueva, fuente, tipo, estado = lat_val, lon_val, "MEF_BANCO_INVERSIONES", "OFICIAL_ORIGINAL", "ORIGINAL_OK"
        else:
            if cui in cache:
                cached = cache[cui]
                lat_nueva, lon_nueva, fuente, tipo, estado = cached['LATITUD_NUEVA'], cached['LONGITUD_NUEVA'], cached['FUENTE_COORDENADA'], cached['TIPO_COORDENADA'], cached['ESTADO_ENRIQUECIMIENTO']
            else:
                lat_nueva, lon_nueva, fuente, tipo, estado = "", "", "", "", "PENDIENTE"
                loc = extraer_localidad(row['NOMBRE_INVERSION'])
                dist, prov = str(row['DISTRITO']), str(row['PROVINCIA'])
                
                if loc:
                    lat_loc, lon_loc = geocode_nominatim(f"{loc}, {dist}, {prov}, Arequipa, Peru")
                    if lat_loc:
                        v, vl, vn = validar_coordenadas(lat_loc, lon_loc)
                        if v: lat_nueva, lon_nueva, fuente, tipo, estado = vl, vn, "OSM_NOMINATIM", "APROXIMADA_LOCALIDAD", "COMPLETADO_APROXIMADO"
                        time.sleep(1)
                
                if estado == "PENDIENTE":
                    lat_dist, lon_dist = geocode_nominatim(f"{dist}, {prov}, Arequipa, Peru")
                    if lat_dist:
                        v, vl, vn = validar_coordenadas(lat_dist, lon_dist)
                        if v: lat_nueva, lon_nueva, fuente, tipo, estado = vl, vn, "OSM_NOMINATIM", "APROXIMADA_DISTRITO", "COMPLETADO_APROXIMADO"
                        time.sleep(1)
                        
                cache[cui] = {'LATITUD_NUEVA': str(lat_nueva), 'LONGITUD_NUEVA': str(lon_nueva), 'FUENTE_COORDENADA': fuente, 'TIPO_COORDENADA': tipo, 'ESTADO_ENRIQUECIMIENTO': estado}
        
        df.at[idx, 'LATITUD'] = lat_nueva
        df.at[idx, 'LONGITUD'] = lon_nueva
        df.at[idx, 'FUENTE_COORDENADA'] = fuente
        df.at[idx, 'TIPO_COORDENADA'] = tipo
        df.at[idx, 'ESTADO_ENRIQUECIMIENTO'] = estado
        
        # --- Financiero ---
        dev_ant = parse_num(row['DEVEN_ACUMUL_ANIO_ANT'])
        dev_act = parse_num(row['DEV_ANIO_ACTUAL'])
        costo = parse_num(row['COSTO_ACTUALIZADO'])
        if costo is None: costo = parse_num(row['MONTO_VIABLE'])
        df.at[idx, 'MONTO_REFERENCIA'] = costo if costo is not None else 0.0
        
        if dev_ant is not None and dev_act is not None:
            ejec = dev_ant + dev_act
            df.at[idx, 'PRESUPUESTO_EJECUTADO'] = ejec
            if costo and costo > 0:
                df.at[idx, 'AVANCE_FINANCIERO_CALCULADO'] = (ejec / costo) * 100
        
        ap = str(row['ANIO_PROCESO']).strip()
        df.at[idx, 'FECHA_REFERENCIA_EJECUCION'] = ap if ap and ap != 'nan' else 'NO DISPONIBLE'
        
        # --- Antigüedad Físico ---
        av_fis = parse_num(row['AVANCE_FISICO'])
        df.at[idx, 'AVANCE_FISICO'] = av_fis if av_fis is not None else ''
        
        ult_fec = str(row['ULT_FEC_DECLA_ESTIM']).strip()
        df.at[idx, 'ULT_FEC_DECLA_ESTIM'] = ult_fec if ult_fec and ult_fec != 'nan' else ''
        
        tiene_avance = av_fis is not None
        try: 
            fec_dt = pd.to_datetime(ult_fec)
            tiene_fecha = True
        except: 
            fec_dt = None
            tiene_fecha = False
            
        if tiene_avance:
            if tiene_fecha:
                dias = (FECHA_REFERENCIA - fec_dt).days
                df.at[idx, 'ANTIGUEDAD_REPORTE_FISICO_DIAS'] = dias
                if dias <= 180: df.at[idx, 'ESTADO_ACTUALIZACION_FISICA'], df.at[idx, 'ADVERTENCIA_AVANCE_FISICO'] = 'ACTUALIZADO', ''
                elif dias <= 365: df.at[idx, 'ESTADO_ACTUALIZACION_FISICA'], df.at[idx, 'ADVERTENCIA_AVANCE_FISICO'] = 'VIGENTE_CON_RETRASO', 'Reporte físico con > 6 meses'
                else: df.at[idx, 'ESTADO_ACTUALIZACION_FISICA'], df.at[idx, 'ADVERTENCIA_AVANCE_FISICO'] = 'DESACTUALIZADO', 'Reporte físico desactualizado'
            else:
                df.at[idx, 'ESTADO_ACTUALIZACION_FISICA'], df.at[idx, 'ADVERTENCIA_AVANCE_FISICO'] = 'SIN_FECHA_REPORTE', 'Sin fecha de reporte disponible'
        else:
            df.at[idx, 'ESTADO_ACTUALIZACION_FISICA'], df.at[idx, 'ADVERTENCIA_AVANCE_FISICO'] = 'SIN_AVANCE_FISICO', 'Sin avance físico registrado'

    guardar_cache(cache)
    
    print("3. Cruce Espacial con EPS...")
    gdf_eps = gpd.read_file(EPS_SHP)
    if gdf_eps.crs is None or gdf_eps.crs.to_epsg() != 4326:
        gdf_eps = gdf_eps.to_crs(epsg=4326)
        
    gdf_eps = gdf_eps[['Pres_Sigla', 'geometry']]
    gdf_eps = gdf_eps.rename(columns={'Pres_Sigla': 'EPS'})
    
    df_coords = df[df['LATITUD'] != ''].copy()
    df_coords['LATITUD'] = df_coords['LATITUD'].astype(float)
    df_coords['LONGITUD'] = df_coords['LONGITUD'].astype(float)
    
    gdf_proy = gpd.GeoDataFrame(df_coords, geometry=gpd.points_from_xy(df_coords.LONGITUD, df_coords.LATITUD), crs=4326)
    cruce = gpd.sjoin(gdf_proy, gdf_eps, how='left', predicate='within')
    
    df['EPS_PRESTACION'] = ''
    df['TIENE_EPS_PRESTACION'] = 'NO'
    
    for idx, row in cruce.iterrows():
        eps_val = row['EPS']
        if pd.notna(eps_val):
            cui = row['CODIGO_UNICO']
            df.loc[df['CODIGO_UNICO'] == cui, 'EPS_PRESTACION'] = eps_val
            df.loc[df['CODIGO_UNICO'] == cui, 'TIENE_EPS_PRESTACION'] = 'SI'
            
    # Resumen cruce EPS
    conteo_eps = df[df['TIENE_EPS_PRESTACION'] == 'SI']['EPS_PRESTACION'].value_counts()
    print("Proyectos dentro de EPS Arequipa:")
    print(conteo_eps)
            
    print("4. Guardando salidas...")
    df.to_csv(CSV_OUT, index=False)
    
    from openpyxl.styles import Font
    with pd.ExcelWriter(EXCEL_OUT, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='PROYECTOS', index=False)
        
        # Resumen
        res_data = [['Métrica', 'Valor'], ['Total Proyectos', len(df)], ['CUIs únicos', df['CODIGO_UNICO'].nunique()]]
        for col in ['PROVINCIA', 'ESTADO', 'SITUACION', 'ESTADO_ACTUALIZACION_FISICA', 'TIENE_EPS_PRESTACION', 'EPS_PRESTACION']:
            res_data.append(['', ''])
            res_data.append([f'Por {col}', 'Cantidad'])
            for k, v in df[col].value_counts().items(): res_data.append([k, v])
                
        pd.DataFrame(res_data[1:], columns=res_data[0]).to_excel(writer, sheet_name='RESUMEN', index=False, header=False)
        
        for ws in writer.sheets:
            sheet = writer.sheets[ws]
            if ws == 'PROYECTOS':
                sheet.auto_filter.ref = sheet.dimensions
                sheet.freeze_panes = "A2"
            for cell in sheet[1]: cell.font = Font(bold=True)

    print("Pipeline completado exitosamente.")

if __name__ == "__main__":
    main()
