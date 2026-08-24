import pandas as pd
import geopandas as gpd
from pathlib import Path
import unicodedata

def normalize_text(text):
    if pd.isna(text) or not isinstance(text, str): return ""
    text = text.replace('Á','A').replace('É','E').replace('Í','I').replace('Ó','O').replace('Ú','U').replace('Ü','U')
    s = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    return s.upper().strip()

def main():
    print("Iniciando actualización de base Arequipa...")
    # 1. Cargar nuevos archivos
    f1 = '/Users/pierotarazona/Downloads/cuis_gn_arequipa_puno.xlsx'
    f2 = '/Users/pierotarazona/Downloads/cuis_arequipa_puno_3_niveles_solo_cuis_saneamiento.csv'
    df1 = pd.read_excel(f1)
    df2 = pd.read_csv(f2)
    df_nuevos = pd.concat([df1, df2], ignore_index=True)
    df_nuevos = df_nuevos[df_nuevos['departamento_consulta'].str.upper() == 'AREQUIPA']

    # Limpiar CUI
    df_nuevos['CODIGO_UNICO'] = df_nuevos['CUI'].fillna(0).astype(int).astype(str)

    # 2. Cargar GPKG para Ubigeos
    gdf = gpd.read_file('data/geografia/DISTRITO.gpkg')
    gdf['nombdist_norm'] = gdf['nombdist'].apply(normalize_text)
    gdf['nombprov_norm'] = gdf['nombprov'].apply(normalize_text)

    # Construir diccionario de provincia+distrito -> ubigeo
    ubigeo_map = {}
    for _, row in gdf.iterrows():
        k = (row['nombprov_norm'], row['nombdist_norm'])
        ubigeo_map[k] = str(row['ubigeo']).zfill(6)

    def get_ubigeo(row):
        p = normalize_text(row['NOMBRE_PROVINCIA'])
        d = normalize_text(row['NOMBRE_DISTRITO'])
        return ubigeo_map.get((p, d), '')

    df_nuevos['UBIGEO'] = df_nuevos.apply(get_ubigeo, axis=1)

    # 3. Cargar v1 anterior para cruzar información enriquecida (avance físico, coordenadas, eps)
    df_v6 = pd.read_csv('outputs/proyectos_agua_saneamiento_arequipa_v1.csv', dtype=str)
    cols_v6 = ['CODIGO_UNICO', 'AVANCE_FISICO', 'AVANCE_EJECUCION', 'ESTADO_ACTUALIZACION_FISICA', 
               'ULT_FEC_DECLA_ESTIM', 'ADVERTENCIA_AVANCE_FISICO', 'TIENE_EPS_PRESTACION', 
               'EPS_PRESTACION', 'TIPO_COORDENADA', 'TIPO_INVERSION', 'LATITUD', 'LONGITUD']
    
    # En caso no exista la columna TIPO_INVERSION
    if 'TIPO_INVERSION' not in df_v6.columns:
        df_v6['TIPO_INVERSION'] = ''
        
    df_v6_sub = df_v6[cols_v6].drop_duplicates('CODIGO_UNICO')

    # 4. Construir dataframe final
    df_final = df_nuevos[['CODIGO_UNICO', 'NOMBRE_INVERSION', 'COSTO', 'MONTO_VIABLE', 'DEVENGADO_ACUMULADO', 'ESTADO', 
                          'PROGRAMACION_INVERSION_ANIO0', 'PROGRAMACION_INVERSION_ANIO1', 'PROGRAMACION_INVERSION_ANIO2', 'PROGRAMACION_INVERSION_ANIO3', 
                          'INICIO_EJECUCION_STR', 'FIN_EJECUCION_STR', 'UBIGEO']].copy()
    df_final.rename(columns={
        'COSTO': 'COSTO_ACTUALIZADO',
        'DEVENGADO_ACUMULADO': 'PRESUPUESTO_EJECUTADO',
        'PROGRAMACION_INVERSION_ANIO0': 'PROGRAMACION_EJECUCION_0',
        'PROGRAMACION_INVERSION_ANIO1': 'PROGRAMACION_EJECUCION_1',
        'PROGRAMACION_INVERSION_ANIO2': 'PROGRAMACION_EJECUCION_2',
        'PROGRAMACION_INVERSION_ANIO3': 'PROGRAMACION_EJECUCION_3'
    }, inplace=True)

    # Merge con la info de v6
    df_final = pd.merge(df_final, df_v6_sub, on='CODIGO_UNICO', how='left')

    # Valores por defecto para nuevos sin v6
    df_final['ESTADO_ACTUALIZACION_FISICA'] = df_final['ESTADO_ACTUALIZACION_FISICA'].fillna('SIN_AVANCE_FISICO')
    df_final['TIENE_EPS_PRESTACION'] = df_final['TIENE_EPS_PRESTACION'].fillna('NO')
    df_final['UBIGEO_NORMALIZADO'] = df_final['UBIGEO']

    # Guardar
    out_path = 'outputs/proyectos_agua_saneamiento_arequipa_v2.csv'
    df_final.to_csv(out_path, index=False)
    print(f"Base actualizada guardada en {out_path} con {len(df_final)} registros.")

if __name__ == "__main__":
    main()
