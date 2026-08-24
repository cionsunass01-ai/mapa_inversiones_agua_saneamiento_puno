import pandas as pd
import requests
import time
from pathlib import Path
import json
import re

CSV_V2 = Path("outputs/proyectos_agua_saneamiento_puno_v2.csv")
CSV_REV_MANUAL = Path("outputs/revision_manual.csv")
CSV_LOC = Path("outputs/coordenadas_aproximadas_localidad.csv")
CACHE_FILE = Path("data/processed/cache_coordenadas.csv")
CSV_V3 = Path("outputs/proyectos_agua_saneamiento_puno_v3.csv")
EXCEL_V3 = Path("outputs/proyectos_agua_saneamiento_puno_v3.xlsx")
AUDITORIA_OUT = Path("outputs/auditoria_coordenadas.csv")
DICCIONARIO_CSV = Path("data/raw/Detalle_Inversiones_Diccionario.csv")

dtypes = {
    'CODIGO_UNICO': str,
    'CODIGO_SNIP': str,
    'UBIGEO': str,
    'SEC_EJEC': str
}

def geocode_nominatim(query):
    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': query, 'format': 'json', 'limit': 1}
    headers = {'User-Agent': 'PunoAguaSaneamientoBot/4.0'}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
    except:
        pass
    return None, None

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

def generar_descripcion(row):
    tipo = str(row['TIPO_INVERSION']).upper()
    nombre = str(row['NOMBRE_INVERSION']).upper()
    dist = str(row['DISTRITO']).title()
    prov = str(row['PROVINCIA']).title()
    subp = str(row['SUBPROGRAMA']).lower()
    
    if subp == 'nan' or not subp.strip():
        subp = 'saneamiento'
        
    kw = []
    if "MEJORAMIENTO" in nombre: kw.append("mejoramiento")
    if "AMPLIACION" in nombre or "AMPLIACIÓN" in nombre: kw.append("ampliación")
    if "CREACION" in nombre or "CREACIÓN" in nombre: kw.append("creación")
    if "INSTALACION" in nombre or "INSTALACIÓN" in nombre: kw.append("instalación")
    if "RECUPERACION" in nombre or "RECUPERACIÓN" in nombre: kw.append("recuperación")
    
    if "ADQUISICION" in nombre or "ADQUISICIÓN" in nombre: kw.append("adquisición")
    if "RENOVACION" in nombre or "RENOVACIÓN" in nombre: kw.append("renovación")
    if "REPARACION" in nombre or "REPARACIÓN" in nombre: kw.append("reparación")
    if "CONSTRUCCION" in nombre or "CONSTRUCCIÓN" in nombre: kw.append("construcción")
    if "OPTIMIZACION" in nombre or "OPTIMIZACIÓN" in nombre: kw.append("optimización")

    action = " y ".join(kw[:2]) if kw else "intervención"
    
    if action.startswith(('adquis', 'renov', 'repar', 'constru', 'crea', 'instala', 'amplia', 'optimiz', 'intervenci')):
        prep = "a la "
    else:
        prep = "al "

    if tipo == 'INVERSIONES IOARR':
        desc = f"IOARR destinada {prep}{action} relacionada con los servicios de {subp} en el distrito de {dist}, provincia de {prov}, Puno."
    else:
        desc = f"Proyecto de inversión orientado {prep}{action} de los servicios de {subp} en el distrito de {dist}, provincia de {prov}, Puno."
        
    # Replace - TODOS - for CUI 2183864
    if dist == '- Todos -': desc = desc.replace("distrito de - Todos -", "distrito correspondiente")
    if prov == '- Todos -': desc = desc.replace("provincia de - Todos -", "provincia correspondiente")
        
    return desc[0].upper() + desc[1:]

def main():
    print("Iniciando generación de la Versión 3...")
    df = pd.read_csv(CSV_V2, dtype=dtypes, keep_default_na=False)
    df_loc = pd.read_csv(CSV_LOC, dtype=dtypes, keep_default_na=False)
    cache = cargar_cache()
    
    # 1. Identificar CUIs a degradar a distrito
    cuis_revisar = df_loc[df_loc['ESTADO_VALIDACION'] == 'REVISAR']['CODIGO_UNICO'].tolist()
    print(f"Degradando {len(cuis_revisar)} localidades fallidas a distrito...")
    
    # 2. Correcciones Geográficas
    for idx, row in df.iterrows():
        cui = row['CODIGO_UNICO']
        
        # Caso especial 2183864
        if cui == '2183864':
            query = "Acora, Puno, Puno, Peru"
            lat, lon = geocode_nominatim(query)
            if lat and lon:
                df.at[idx, 'LATITUD'] = str(lat)
                df.at[idx, 'LONGITUD'] = str(lon)
                df.at[idx, 'FUENTE_COORDENADA'] = "OPENSTREETMAP_NOMINATIM"
                df.at[idx, 'TIPO_COORDENADA'] = "APROXIMADA_DISTRITO"
                df.at[idx, 'URL_FUENTE_COORDENADA'] = "https://nominatim.openstreetmap.org"
                df.at[idx, 'OBSERVACION_COORDENADA'] = "El distrito ACORA se extrajo del nombre de la inversión, ya que MEF reporta '- TODOS -'. Coordenada referencial del distrito."
                df.at[idx, 'ESTADO_ENRIQUECIMIENTO'] = "COMPLETADO_APROXIMADO"
                cache[cui] = df.loc[idx, ['LATITUD_NUEVA' if 'NUEVA' in x else x for x in ['LATITUD', 'LONGITUD', 'FUENTE_COORDENADA', 'TIPO_COORDENADA', 'URL_FUENTE_COORDENADA', 'OBSERVACION_COORDENADA', 'ESTADO_ENRIQUECIMIENTO']]].to_dict()
                time.sleep(1.2)
        
        # Casos REVISAR
        elif cui in cuis_revisar:
            distrito = row['DISTRITO']
            provincia = row['PROVINCIA']
            query = f"{distrito}, {provincia}, Puno, Peru"
            lat, lon = geocode_nominatim(query)
            if lat and lon:
                df.at[idx, 'LATITUD'] = str(lat)
                df.at[idx, 'LONGITUD'] = str(lon)
                df.at[idx, 'FUENTE_COORDENADA'] = "OPENSTREETMAP_NOMINATIM"
                df.at[idx, 'TIPO_COORDENADA'] = "APROXIMADA_DISTRITO"
                df.at[idx, 'URL_FUENTE_COORDENADA'] = "https://nominatim.openstreetmap.org"
                df.at[idx, 'OBSERVACION_COORDENADA'] = "La geocodificación automática de la localidad no superó la validación administrativa; se utiliza una coordenada referencial del distrito."
                df.at[idx, 'ESTADO_ENRIQUECIMIENTO'] = "COMPLETADO_APROXIMADO"
                # Actualizar cache para no perder
                cache[cui] = {
                    'LATITUD_NUEVA': str(lat),
                    'LONGITUD_NUEVA': str(lon),
                    'FUENTE_COORDENADA': "OPENSTREETMAP_NOMINATIM",
                    'TIPO_COORDENADA': "APROXIMADA_DISTRITO",
                    'URL_FUENTE_COORDENADA': "https://nominatim.openstreetmap.org",
                    'OBSERVACION_COORDENADA': df.at[idx, 'OBSERVACION_COORDENADA'],
                    'ESTADO_ENRIQUECIMIENTO': "COMPLETADO_APROXIMADO"
                }
            time.sleep(1.2)
            
    guardar_cache(cache)
    
    # 3. Generar DESCRIPCION
    # Encontrar la posicion de ALTERNATIVA para insertar DESCRIPCION justo despues
    cols = list(df.columns)
    if 'DESCRIPCION' not in cols:
        alt_idx = cols.index('ALTERNATIVA')
        cols.insert(alt_idx + 1, 'DESCRIPCION')
        df = df.reindex(columns=cols)
        
    df['DESCRIPCION'] = df.apply(generar_descripcion, axis=1)
    df['FUENTE_DESCRIPCION'] = 'GENERADA_DESDE_DATOS_MEF'
    
    # Asegurar regla de alternativa por si acaso
    for idx, row in df.iterrows():
        if str(row['TIPO_INVERSION']).upper() == 'INVERSIONES IOARR' and not str(row['ALTERNATIVA_MEF']).strip():
            df.at[idx, 'ALTERNATIVA'] = 'NO APLICA - INVERSIÓN IOARR'

    # Validaciones Finales
    assert len(df) == 761, "El total de filas debe ser 761"
    assert df['CODIGO_UNICO'].nunique() == 761, "Los CUIs deben ser únicos"
    assert len(df[df['DESCRIPCION'].str.strip() == '']) == 0, "No deben haber descripciones vacías"
    assert len(df[df['ALTERNATIVA'].str.strip() == '']) == 0, "No deben haber alternativas vacías"
    assert len(df[(df['LATITUD'] == '0.0') | (df['LATITUD'] == '')]) == 0, "No deben quedar coordenadas 0,0"

    # Generar Auditoria Actualizada
    cols_auditoria = ['CODIGO_UNICO', 'NOMBRE_INVERSION', 'PROVINCIA', 'DISTRITO', 
                      'LATITUD_MEF', 'LONGITUD_MEF', 'LATITUD', 'LONGITUD', 
                      'FUENTE_COORDENADA', 'TIPO_COORDENADA', 'URL_FUENTE_COORDENADA', 
                      'OBSERVACION_COORDENADA', 'ESTADO_ENRIQUECIMIENTO']
    df_auditoria = df[cols_auditoria].copy()
    df_auditoria = df_auditoria.rename(columns={'LATITUD': 'LATITUD_NUEVA', 'LONGITUD': 'LONGITUD_NUEVA'})
    df_auditoria.to_csv(AUDITORIA_OUT, index=False)
    
    # Guardar CSV V3
    df.to_csv(CSV_V3, index=False)
    
    # Guardar Excel V3
    from openpyxl.styles import Font
    print(f"Generando Excel {EXCEL_V3.name}...")
    with pd.ExcelWriter(EXCEL_V3, engine='openpyxl') as writer:
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
        add_grouping(df, 'TIPO_COORDENADA')
        
        df_res = pd.DataFrame(resumen_data[1:], columns=resumen_data[0])
        df_res.to_excel(writer, sheet_name='RESUMEN', index=False, header=False)
        
        # Revision Manual
        df_rev = pd.read_csv(CSV_REV_MANUAL, dtype=dtypes, keep_default_na=False)
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
            ["ALTERNATIVA_MEF", "Alternativa original reportada por el MEF."],
            ["DESCRIPCION", "Descripción normalizada de la inversión construida a partir de los campos oficiales disponibles en el registro del Banco de Inversiones del MEF."],
            ["FUENTE_DESCRIPCION", "Indica el origen metodológico utilizado para construir la descripción de la inversión."]
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

    # Reportes Finales
    print("\n=== REPORTE GEOGRÁFICO FINAL ===")
    print(df['TIPO_COORDENADA'].value_counts())
    print(f"PENDIENTE: {len(df[df['ESTADO_ENRIQUECIMIENTO'] == 'PENDIENTE'])}")
    print(f"Coordenadas Únicas: {df.groupby(['LATITUD', 'LONGITUD']).ngroups}")
    
    print("\n=== REPORTE DE DESCRIPCION ===")
    print(f"DESCRIPCION completadas: {len(df[df['DESCRIPCION'] != ''])}")
    print(f"DESCRIPCION vacías o null: {len(df[df['DESCRIPCION'].isin(['', 'nan', 'None', 'null'])])}")
    
    print("\nEjemplos Representativos:")
    # IOARR
    print("- IOARR:")
    for _, r in df[df['TIPO_INVERSION'] == 'INVERSIONES IOARR'].head(2).iterrows():
        print(f"  * {r['DESCRIPCION']}")
        
    # RURAL
    print("- RURAL:")
    for _, r in df[df['SUBPROGRAMA'] == 'SANEAMIENTO RURAL'].head(2).iterrows():
        print(f"  * {r['DESCRIPCION']}")
        
    # URBANO
    print("- URBANO:")
    for _, r in df[df['SUBPROGRAMA'] == 'SANEAMIENTO URBANO'].head(2).iterrows():
        print(f"  * {r['DESCRIPCION']}")
        
    # PROYECTOS INVERSION (general)
    print("- PROYECTOS DE INVERSIÓN (SNIP):")
    for _, r in df[df['TIPO_INVERSION'].isin(['PIP MAYOR (SNIP)', 'PIP MENOR (SNIP)'])].head(2).iterrows():
        print(f"  * {r['DESCRIPCION']}")
        
if __name__ == "__main__":
    main()
