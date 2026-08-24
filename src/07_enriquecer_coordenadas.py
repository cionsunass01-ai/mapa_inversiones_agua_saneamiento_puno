import pandas as pd
import requests
import time
from pathlib import Path
import json
import re

CSV_IN = Path("outputs/proyectos_agua_saneamiento_puno.csv")
CSV_REV = Path("outputs/revision_manual.csv")
CACHE_FILE = Path("data/processed/cache_coordenadas.csv")
CSV_OUT = Path("outputs/proyectos_agua_saneamiento_puno_v2.csv")
EXCEL_OUT = Path("outputs/proyectos_agua_saneamiento_puno_v2.xlsx")
AUDITORIA_OUT = Path("outputs/auditoria_coordenadas.csv")
DICCIONARIO_CSV = Path("data/raw/Detalle_Inversiones_Diccionario.csv")

dtypes = {
    'CODIGO_UNICO': str,
    'CODIGO_SNIP': str,
    'UBIGEO': str,
    'SEC_EJEC': str
}

def cargar_cache():
    if CACHE_FILE.exists():
        df = pd.read_csv(CACHE_FILE, dtype=str)
        # Drop duplicates by CUI to prevent reindexing issues
        df = df.drop_duplicates(subset=['CODIGO_UNICO'])
        return df.set_index('CODIGO_UNICO').to_dict('index')
    return {}


def guardar_cache(cache_dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame.from_dict(cache_dict, orient='index')
    df.index.name = 'CODIGO_UNICO'
    df.reset_index().to_csv(CACHE_FILE, index=False)

def validar_coordenadas(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
        if lat == 0.0 or lon == 0.0:
            return False, lat, lon
        
        # Puno rough bounds: Lat: -13.0 to -17.5, Lon: -71.5 to -68.5
        # Peru bounds: Lat: 0 to -19, Lon: -82 to -68
        
        # Check if inverted
        if (lat < -68 and lat > -72) and (lon < -13 and lon > -18):
            lat, lon = lon, lat # Swap
            
        if lat > 0: # Should be negative (South)
            lat = -lat
        if lon > 0: # Should be negative (West)
            lon = -lon
            
        if -18 <= lat <= -13 and -72 <= lon <= -68:
            return True, lat, lon
        else:
            return False, lat, lon
    except:
        return False, 0.0, 0.0

def geocode_nominatim(query):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': query,
        'format': 'json',
        'limit': 1
    }
    headers = {'User-Agent': 'PunoAguaSaneamientoBot/2.0'}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        print(f"Error geocoding {query}: {e}")
    return None, None

def extraer_localidad(nombre):
    # Regex to extract localities
    patrones = [
        r"(?:LOCALIDAD|COMUNIDAD|CENTRO POBLADO|SECTOR|BARRIO|PARCIALIDAD) (?:DE |CAMPESINA DE )?([A-Z\s]+?)(?:, | DEL | EN | - )",
        r"(?:EN |A |LAS )?(?:LOCALIDADES|COMUNIDADES) (?:DE )?([A-Z\s]+?)(?:, | Y | DEL | EN | - )"
    ]
    for p in patrones:
        match = re.search(p, nombre, re.IGNORECASE)
        if match:
            loc = match.group(1).strip()
            if len(loc) > 3 and loc.upper() not in ["LOS", "LAS", "EL", "LA"]:
                return loc
    return None

def main():
    print("Iniciando enriquecimiento de coordenadas (Parte A) y alternativas (Parte B)...")
    
    # 1. Investigate GeoInvierte
    print("Etapa 1: GeoInvierte - Sin un token de sesión válido o endpoint REST abierto (MapServer/FeatureServer están restringidos por CORS y tokens), no se puede automatizar masivamente vía script simple. Usaremos OSM Nominatim para localidades.")
    
    df = pd.read_csv(CSV_IN, dtype=dtypes, keep_default_na=False)
    cache = cargar_cache()
    
    # Preserve originals
    df['LATITUD_MEF'] = df['LATITUD']
    df['LONGITUD_MEF'] = df['LONGITUD']
    df['ALTERNATIVA_MEF'] = df['ALTERNATIVA']
    
    nuevas_filas = []
    
    count_oficial = 0
    count_aprox_loc = 0
    count_aprox_dist = 0
    count_pendientes = 0
    
    print(f"Procesando {len(df)} proyectos...")
    
    for idx, row in df.iterrows():
        cui = row['CODIGO_UNICO']
        nombre = row['NOMBRE_INVERSION']
        distrito = row['DISTRITO']
        provincia = row['PROVINCIA']
        lat_mef = str(row['LATITUD'])
        lon_mef = str(row['LONGITUD'])
        
        valido, lat_val, lon_val = validar_coordenadas(lat_mef, lon_mef)
        
        if valido:
            lat_nueva, lon_nueva = lat_val, lon_val
            fuente = "MEF_BANCO_INVERSIONES"
            tipo = "OFICIAL_ORIGINAL"
            url = ""
            obs = "Coordenada original validada"
            estado = "ORIGINAL_OK"
            count_oficial += 1
        else:
            # Buscar en caché
            if cui in cache:
                cached = cache[cui]
                lat_nueva = cached['LATITUD_NUEVA']
                lon_nueva = cached['LONGITUD_NUEVA']
                fuente = cached['FUENTE_COORDENADA']
                tipo = cached['TIPO_COORDENADA']
                url = cached['URL_FUENTE_COORDENADA']
                obs = cached['OBSERVACION_COORDENADA']
                estado = cached['ESTADO_ENRIQUECIMIENTO']
                if tipo == 'APROXIMADA_LOCALIDAD': count_aprox_loc += 1
                elif tipo == 'APROXIMADA_DISTRITO': count_aprox_dist += 1
                else: count_pendientes += 1
            else:
                lat_nueva, lon_nueva, fuente, tipo, url, obs, estado = "", "", "", "", "", "", "PENDIENTE"
                
                # Etapa 2: APROXIMADA_LOCALIDAD
                localidad = extraer_localidad(nombre)
                if localidad:
                    query_loc = f"{localidad}, {distrito}, {provincia}, Puno, Peru"
                    lat_loc, lon_loc = geocode_nominatim(query_loc)
                    if lat_loc and lon_loc:
                        val_loc, v_lat, v_lon = validar_coordenadas(lat_loc, lon_loc)
                        if val_loc:
                            lat_nueva, lon_nueva = v_lat, v_lon
                            fuente = "OPENSTREETMAP_NOMINATIM"
                            tipo = "APROXIMADA_LOCALIDAD"
                            url = "https://nominatim.openstreetmap.org"
                            obs = f"Coordenada aproximada de la localidad '{localidad}' mencionada en el nombre de la inversión; no representa necesariamente la ubicación exacta de la infraestructura."
                            estado = "COMPLETADO_APROXIMADO"
                            count_aprox_loc += 1
                            time.sleep(1.2)
                
                # Etapa 3: APROXIMADA_DISTRITO
                if estado == "PENDIENTE":
                    query_dist = f"{distrito}, {provincia}, Puno, Peru"
                    lat_dist, lon_dist = geocode_nominatim(query_dist)
                    if lat_dist and lon_dist:
                        val_dist, v_lat, v_lon = validar_coordenadas(lat_dist, lon_dist)
                        if val_dist:
                            lat_nueva, lon_nueva = v_lat, v_lon
                            fuente = "OPENSTREETMAP_NOMINATIM"
                            tipo = "APROXIMADA_DISTRITO"
                            url = "https://nominatim.openstreetmap.org"
                            obs = f"Coordenada referencial del distrito {distrito}. No representa la ubicación exacta de la infraestructura."
                            estado = "COMPLETADO_APROXIMADO"
                            count_aprox_dist += 1
                            time.sleep(1.2)
                
                if estado == "PENDIENTE":
                    obs = "No se encontró información automática, requiere búsqueda manual"
                    count_pendientes += 1
                    time.sleep(1.2)
                
                # Guardar en cache
                cache[cui] = {
                    'LATITUD_NUEVA': str(lat_nueva),
                    'LONGITUD_NUEVA': str(lon_nueva),
                    'FUENTE_COORDENADA': fuente,
                    'TIPO_COORDENADA': tipo,
                    'URL_FUENTE_COORDENADA': url,
                    'OBSERVACION_COORDENADA': obs,
                    'ESTADO_ENRIQUECIMIENTO': estado
                }
                if len(cache) % 20 == 0:
                    guardar_cache(cache)
        
        # Update row
        df.at[idx, 'LATITUD'] = lat_nueva
        df.at[idx, 'LONGITUD'] = lon_nueva
        df.at[idx, 'FUENTE_COORDENADA'] = fuente
        df.at[idx, 'TIPO_COORDENADA'] = tipo
        df.at[idx, 'URL_FUENTE_COORDENADA'] = url
        df.at[idx, 'OBSERVACION_COORDENADA'] = obs
        df.at[idx, 'ESTADO_ENRIQUECIMIENTO'] = estado
        
        # Alternativa Logic
        alt_mef = str(row['ALTERNATIVA_MEF']).strip()
        if str(row['TIPO_INVERSION']).upper() == 'INVERSIONES IOARR':
            if not alt_mef or alt_mef.lower() == 'nan':
                df.at[idx, 'ALTERNATIVA'] = 'NO APLICA - INVERSIÓN IOARR'
                
    guardar_cache(cache)
    
    # Generar auditoria
    cols_auditoria = ['CODIGO_UNICO', 'NOMBRE_INVERSION', 'PROVINCIA', 'DISTRITO', 
                      'LATITUD_MEF', 'LONGITUD_MEF', 'LATITUD', 'LONGITUD', 
                      'FUENTE_COORDENADA', 'TIPO_COORDENADA', 'URL_FUENTE_COORDENADA', 
                      'OBSERVACION_COORDENADA', 'ESTADO_ENRIQUECIMIENTO']
    df_auditoria = df[cols_auditoria].copy()
    df_auditoria = df_auditoria.rename(columns={'LATITUD': 'LATITUD_NUEVA', 'LONGITUD': 'LONGITUD_NUEVA'})
    df_auditoria.to_csv(AUDITORIA_OUT, index=False)
    
    # Save CSV V2
    df.to_csv(CSV_OUT, index=False)
    
    # Save Excel V2
    from openpyxl.styles import Font
    print(f"Generando Excel {EXCEL_OUT.name}...")
    with pd.ExcelWriter(EXCEL_OUT, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='PROYECTOS', index=False)
        
        # Resumen
        resumen_data = []
        resumen_data.append(['Métrica', 'Valor'])
        resumen_data.append(['Total de proyectos', len(df)])
        resumen_data.append(['Total de CUIs únicos', df['CODIGO_UNICO'].nunique()])
        
        def add_grouping(df, column):
            resumen_data.append(['', ''])
            resumen_data.append([f'Proyectos por {column}', 'Cantidad'])
            counts = df[column].value_counts()
            for k, v in counts.items():
                resumen_data.append([k, v])
                
        add_grouping(df, 'ORIGEN_CLASIFICACION')
        add_grouping(df, 'PROVINCIA')
        add_grouping(df, 'SUBPROGRAMA')
        add_grouping(df, 'ESTADO')
        add_grouping(df, 'SITUACION')
        add_grouping(df, 'ETAPA_F8')
        
        df_res = pd.DataFrame(resumen_data[1:], columns=resumen_data[0])
        df_res.to_excel(writer, sheet_name='RESUMEN', index=False, header=False)
        
        # Revision Manual
        df_rev = pd.read_csv(CSV_REV, dtype=dtypes, keep_default_na=False)
        df_rev.to_excel(writer, sheet_name='REVISION_MANUAL', index=False)
        
        # Auditoria
        df_auditoria.to_excel(writer, sheet_name='AUDITORIA_COORDENADAS', index=False)
        
        # Diccionario
        dicc_data = []
        if DICCIONARIO_CSV.exists():
            try:
                df_dic = pd.read_csv(DICCIONARIO_CSV, keep_default_na=False)
                dicc_data = df_dic.values.tolist()
            except: pass
            
        nuevos_campos = [
            ["ORIGEN_CLASIFICACION", "Origen utilizado para determinar por qué el proyecto forma parte del universo consolidado."],
            ["CRITERIO_INCLUSION", "Justificación breve de la inclusión del proyecto en la base consolidada."],
            ["LATITUD_MEF", "Latitud original reportada por el MEF."],
            ["LONGITUD_MEF", "Longitud original reportada por el MEF."],
            ["FUENTE_COORDENADA", "Fuente desde la cual se obtuvo la coordenada."],
            ["TIPO_COORDENADA", "Nivel de precisión de la coordenada obtenida (OFICIAL_ORIGINAL, APROXIMADA_LOCALIDAD, APROXIMADA_DISTRITO)."],
            ["URL_FUENTE_COORDENADA", "URL de la fuente geográfica."],
            ["OBSERVACION_COORDENADA", "Detalle sobre la validez o aproximación de la coordenada."],
            ["ALTERNATIVA_MEF", "Alternativa original reportada por el MEF."]
        ]
        
        dicc_final = nuevos_campos + dicc_data
        df_dic_out = pd.DataFrame(dicc_final, columns=['COLUMNA', 'DESCRIPCION'])
        df_dic_out.to_excel(writer, sheet_name='DICCIONARIO', index=False)
        
        # Styling
        for ws_name in writer.sheets:
            ws = writer.sheets[ws_name]
            if ws_name in ['PROYECTOS', 'REVISION_MANUAL', 'AUDITORIA_COORDENADAS']:
                ws.auto_filter.ref = ws.dimensions
                ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
                
            if ws_name == 'DICCIONARIO':
                ws.column_dimensions['A'].width = 30
                ws.column_dimensions['B'].width = 100
            elif ws_name == 'RESUMEN':
                ws.column_dimensions['A'].width = 40
                ws.column_dimensions['B'].width = 15

    # Reporte
    print("\n=== REPORTE FINAL ===")
    print(f"1. Proyectos totales: {len(df)}")
    print(f"2. Coordenadas MEF originales válidas: {count_oficial}")
    print(f"3. Coordenadas inicialmente pendientes: {len(df) - count_oficial}")
    print(f"4. OFICIAL_CUI recuperadas: 0 (Servicio bloqueado)")
    print(f"5. OFICIAL_PROYECTO recuperadas: 0 (Servicio bloqueado)")
    print(f"6. APROXIMADA_LOCALIDAD: {count_aprox_loc}")
    print(f"7. APROXIMADA_DISTRITO: {count_aprox_dist}")
    print(f"8. REVISAR: 0")
    print(f"9. Proyectos con 0,0 o null: {count_pendientes}")
    
    coords_validas = df[df['LATITUD'] != '']
    num_coords_unicas = coords_validas.groupby(['LATITUD', 'LONGITUD']).ngroups
    print(f"10. Cantidad de coordenadas únicas: {num_coords_unicas}")
    
    ioarr = df[df['TIPO_INVERSION'].str.upper() == 'INVERSIONES IOARR']
    ioarr_no_aplica = ioarr[ioarr['ALTERNATIVA'] == 'NO APLICA - INVERSIÓN IOARR']
    ioarr_vacia = ioarr[ioarr['ALTERNATIVA'].str.strip() == '']
    print(f"11. IOARR con 'NO APLICA - INVERSIÓN IOARR': {len(ioarr_no_aplica)}")
    print(f"12. Cantidad restante de ALTERNATIVA vacía: {len(df[df['ALTERNATIVA'].str.strip() == ''])}")
    print(f"13. Ruta CSV V2: {CSV_OUT.as_posix()}")
    print(f"14. Ruta Excel V2: {EXCEL_OUT.as_posix()}")

if __name__ == "__main__":
    main()
