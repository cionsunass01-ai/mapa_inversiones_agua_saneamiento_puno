import pandas as pd
import requests
import time
import re
from pathlib import Path

CSV_V2 = Path("outputs/proyectos_agua_saneamiento_puno_v2.csv")
OUT_LOC = Path("outputs/coordenadas_aproximadas_localidad.csv")
OUT_DIST = Path("outputs/coordenadas_aproximadas_distrito.csv")

def extraer_localidad(nombre):
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
    df = pd.read_csv(CSV_V2, dtype=str, keep_default_na=False)
    
    print("\n--- 1. PROYECTO PENDIENTE (0,0 / Null) ---")
    pendiente = df[df['ESTADO_ENRIQUECIMIENTO'] == 'PENDIENTE']
    if not pendiente.empty:
        for _, row in pendiente.iterrows():
            print(f"CODIGO_UNICO: {row['CODIGO_UNICO']}")
            print(f"NOMBRE_INVERSION: {row['NOMBRE_INVERSION']}")
            print(f"PROVINCIA: {row['PROVINCIA']}")
            print(f"DISTRITO: {row['DISTRITO']}")
            print(f"UBIGEO: {row['UBIGEO']}")
            print(f"LATITUD_MEF: {row['LATITUD_MEF']}")
            print(f"LONGITUD_MEF: {row['LONGITUD_MEF']}")
            loc = extraer_localidad(row['NOMBRE_INVERSION'])
            print(f"Motivo Nominatim: La búsqueda por distrito o localidad '{loc}' no arrojó resultados válidos dentro de Puno/Perú, o el nombre del distrito está mal escrito/no reconocido en OSM.\n")
            cui_pendiente = row['CODIGO_UNICO']
    else:
        print("No se encontraron proyectos pendientes.\n")
        cui_pendiente = "N/A"
        
    print("\n--- 2. GENERANDO APROXIMADA_DISTRITO ---")
    df_dist = df[df['TIPO_COORDENADA'] == 'APROXIMADA_DISTRITO'].copy()
    df_dist.to_csv(OUT_DIST, index=False)
    print(f"Archivo {OUT_DIST.name} generado con {len(df_dist)} registros.\n")
    
    print("--- 3. PROCESANDO APROXIMADA_LOCALIDAD ---")
    df_loc = df[df['TIPO_COORDENADA'] == 'APROXIMADA_LOCALIDAD'].copy()
    
    resultados_loc = []
    
    # Calculate duplicates to detect "coordenada compartida por muchas inversiones"
    coord_counts = df_loc.groupby(['LATITUD', 'LONGITUD']).size()
    
    for idx, row in df_loc.iterrows():
        cui = row['CODIGO_UNICO']
        nombre = row['NOMBRE_INVERSION']
        distrito = row['DISTRITO']
        provincia = row['PROVINCIA']
        lat_actual = row['LATITUD']
        lon_actual = row['LONGITUD']
        
        localidad = extraer_localidad(nombre)
        query = f"{localidad}, {distrito}, {provincia}, Puno, Peru"
        
        # Query nominatim again for full details
        url = "https://nominatim.openstreetmap.org/search"
        params = {'q': query, 'format': 'json', 'limit': 1}
        headers = {'User-Agent': 'PunoAguaSaneamientoBot/3.0'}
        
        display_name = ""
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data:
                    display_name = data[0].get('display_name', '')
        except Exception as e:
            display_name = f"Error: {e}"
            
        time.sleep(1.2) # Sleep for API limits
        
        # Validation checks
        coincide_distrito = 'SI' if distrito.lower() in display_name.lower() else 'NO'
        coincide_provincia = 'SI' if provincia.lower() in display_name.lower() else 'NO'
        
        revisar_motivos = []
        if coincide_distrito == 'NO': revisar_motivos.append("Distrito no coincide")
        if coincide_provincia == 'NO': revisar_motivos.append("Provincia no coincide")
        if not localidad or len(localidad.split()) < 2: 
            # If name is 1 word and might be generic
            # Only flag if it's very generic, but let's just flag < 5 chars
            if localidad and len(localidad) < 5:
                revisar_motivos.append("Nombre muy genérico")
        
        if coord_counts.get((lat_actual, lon_actual), 1) > 2:
            revisar_motivos.append("Coordenada muy compartida (>2)")
            
        if "city" in data[0].get('addresstype', '') or "administrative" in data[0].get('addresstype', ''):
            # If returned a whole city/district when we asked for locality
             revisar_motivos.append("Resultado a nivel ciudad/distrito")
             
        estado_validacion = "REVISAR" if revisar_motivos else "OK"
        motivo_final = " | ".join(revisar_motivos)
        
        resultados_loc.append({
            'CODIGO_UNICO': cui,
            'NOMBRE_INVERSION': nombre,
            'LOCALIDAD_EXTRAIDA': localidad,
            'CONSULTA_NOMINATIM': query,
            'DISPLAY_NAME_NOMINATIM': display_name,
            'LATITUD': lat_actual,
            'LONGITUD': lon_actual,
            'PROVINCIA_ESPERADA': provincia,
            'DISTRITO_ESPERADO': distrito,
            'COINCIDE_DISTRITO': coincide_distrito,
            'COINCIDE_PROVINCIA': coincide_provincia,
            'ESTADO_VALIDACION': estado_validacion,
            'MOTIVO_REVISION': motivo_final
        })
        
    df_loc_out = pd.DataFrame(resultados_loc)
    df_loc_out.to_csv(OUT_LOC, index=False)
    
    count_ok = len(df_loc_out[df_loc_out['ESTADO_VALIDACION'] == 'OK'])
    count_revisar = len(df_loc_out[df_loc_out['ESTADO_VALIDACION'] == 'REVISAR'])
    
    print("\n--- RESUMEN DE VALIDACIÓN ---")
    print(f"Total procesados (APROXIMADA_LOCALIDAD): {len(df_loc_out)}")
    print(f"Pasan validación (OK): {count_ok}")
    print(f"Marcados para REVISAR: {count_revisar}")
    print(f"CUI del proyecto sin coordenadas: {cui_pendiente}")

if __name__ == "__main__":
    main()
