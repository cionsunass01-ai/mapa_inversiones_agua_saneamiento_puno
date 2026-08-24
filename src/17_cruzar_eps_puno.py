import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from pathlib import Path
import numpy as np

CSV_V5 = Path("outputs/proyectos_agua_saneamiento_puno_v5.csv")
EPS_SHP = Path("/Users/pierotarazona/Downloads/Rodrigo_Puno y Arequipa/EPS_Puno.shp")
CSV_V6 = Path("outputs/proyectos_agua_saneamiento_puno_v6.csv")
EXCEL_V6 = Path("outputs/proyectos_agua_saneamiento_puno_v6.xlsx")
AUDIT_EPS = Path("outputs/auditoria_eps_prestacion.csv")
DICCIONARIO_CSV = Path("data/raw/Detalle_Inversiones_Diccionario.csv")

def main():
    print("Cargando V5...")
    df = pd.read_csv(CSV_V5, dtype=str, keep_default_na=False)
    
    print("Cargando capa EPS...")
    gdf_eps = gpd.read_file(EPS_SHP)
    
    # Asegurar EPSG:4326
    if gdf_eps.crs is None or gdf_eps.crs.to_epsg() != 4326:
        gdf_eps = gdf_eps.to_crs(epsg=4326)
        
    print(f"Total EPS features: {len(gdf_eps)}")
    
    # Crear geometrías a partir de LATITUD y LONGITUD en df
    geometries = []
    for idx, row in df.iterrows():
        lat_str = row['LATITUD']
        lon_str = row['LONGITUD']
        try:
            lat = float(lat_str)
            lon = float(lon_str)
            if pd.notna(lat) and pd.notna(lon):
                geometries.append(Point(lon, lat))
            else:
                geometries.append(None)
        except:
            geometries.append(None)
            
    gdf_proy = gpd.GeoDataFrame(df, geometry=geometries, crs="EPSG:4326")
    
    print("Realizando cruce espacial (Spatial Join)...")
    # Spatial join: left join, points within polygons
    # gdf_eps has 'EPS' column
    # Usamos keep_geom_type por si acaso, pero sjoin mantiene geometría izquierda
    gdf_joined = gpd.sjoin(gdf_proy, gdf_eps[['EPS', 'geometry']], how='left', predicate='within')
    
    # Puede que un punto caiga en superposición, droppeamos duplicados por index
    if gdf_joined.index.duplicated().any():
        gdf_joined = gdf_joined[~gdf_joined.index.duplicated(keep='first')]
        
    df['EPS_PRESTACION'] = gdf_joined['EPS'].fillna('SIN_EPS_IDENTIFICADA')
    df['TIENE_EPS_PRESTACION'] = df['EPS_PRESTACION'].apply(lambda x: 'NO' if x == 'SIN_EPS_IDENTIFICADA' else 'SI')
    
    # Export V6 CSV
    df.to_csv(CSV_V6, index=False)
    
    # Auditoria Espacial
    cols_audit = [
        'CODIGO_UNICO', 'NOMBRE_INVERSION', 'PROVINCIA', 'DISTRITO',
        'LATITUD', 'LONGITUD', 'TIPO_COORDENADA',
        'EPS_PRESTACION', 'TIENE_EPS_PRESTACION'
    ]
    df_audit = df[cols_audit].copy()
    
    # Add custom indicators requested
    df_audit['DENTRO_EPS'] = df_audit['TIENE_EPS_PRESTACION']
    
    def clasificar_coord(row):
        tc = str(row['TIPO_COORDENADA']).upper()
        if 'OFICIAL' in tc: return 'OFICIAL'
        elif 'APROX' in tc: return 'APROXIMADA'
        return 'SIN_COORDENADA'
        
    df_audit['CATEGORIA_COORD'] = df_audit.apply(clasificar_coord, axis=1)
    
    df_audit.to_csv(AUDIT_EPS, index=False)
    
    # Excel V6
    print(f"Generando Excel {EXCEL_V6.name}...")
    from openpyxl.styles import Font
    with pd.ExcelWriter(EXCEL_V6, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='PROYECTOS', index=False)
        
        # Resumen
        res_data = [['Métrica', 'Valor'], ['Total de proyectos', len(df)]]
        
        counts_eps = df['EPS_PRESTACION'].value_counts()
        res_data.append(['', ''])
        res_data.append(['Proyectos por EPS', 'Cantidad'])
        for k, v in counts_eps.items():
            res_data.append([k, v])
            
        df_res = pd.DataFrame(res_data[1:], columns=res_data[0])
        df_res.to_excel(writer, sheet_name='RESUMEN', index=False, header=False)
        
        df_audit.to_excel(writer, sheet_name='AUDITORIA_EPS', index=False)
        
        dicc_data = []
        if DICCIONARIO_CSV.exists():
            try:
                df_dic = pd.read_csv(DICCIONARIO_CSV, keep_default_na=False)
                dicc_data = df_dic.values.tolist()
            except: pass
            
        nuevos_campos = [
            ["EPS_PRESTACION", "Nombre de la Empresa Prestadora de Servicios cuyo polígono intersecta con la ubicación del proyecto."],
            ["TIENE_EPS_PRESTACION", "Indicador si el proyecto se encuentra dentro del ámbito de prestación de alguna EPS (SI/NO)."]
        ]
        
        existing = [x[0] for x in dicc_data]
        dicc_final = [x for x in nuevos_campos if x[0] not in existing] + dicc_data
        df_dic_out = pd.DataFrame(dicc_final, columns=['COLUMNA', 'DESCRIPCION'])
        df_dic_out.to_excel(writer, sheet_name='DICCIONARIO', index=False)
        
        for ws_name in writer.sheets:
            ws = writer.sheets[ws_name]
            if ws_name in ['PROYECTOS', 'AUDITORIA_EPS']:
                ws.auto_filter.ref = ws.dimensions
                ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
                
            if ws_name == 'DICCIONARIO':
                ws.column_dimensions['A'].width = 30
                ws.column_dimensions['B'].width = 100
                
    print("V6 finalizado con éxito.")
    
    # Stats to print
    eps_list = gdf_eps['EPS'].unique().tolist()
    total_proy = len(df)
    dentro = (df['TIENE_EPS_PRESTACION'] == 'SI').sum()
    fuera = total_proy - dentro
    
    top_eps_count = df[df['TIENE_EPS_PRESTACION'] == 'SI']['EPS_PRESTACION'].value_counts().head(3)
    
    df['MONTO_REFERENCIA'] = pd.to_numeric(df['COSTO_ACTUALIZADO'], errors='coerce')
    df.loc[df['MONTO_REFERENCIA'].isna(), 'MONTO_REFERENCIA'] = pd.to_numeric(df['MONTO_VIABLE'], errors='coerce')
    
    monto_eps = df[df['TIENE_EPS_PRESTACION'] == 'SI'].groupby('EPS_PRESTACION')['MONTO_REFERENCIA'].sum().sort_values(ascending=False).head(3)
    
    print("\n=== REPORTE ESPACIAL EPS ===")
    print(f"- EPS únicas en shapefile: {len(eps_list)}")
    print(f"- Nombres EPS: {', '.join(eps_list)}")
    print(f"- Polígonos en shapefile: {len(gdf_eps)}")
    print(f"- Proyectos dentro de EPS: {dentro}")
    print(f"- Proyectos fuera de EPS (SIN_EPS): {fuera}")
    print("\n- Top EPS por cantidad de proyectos:")
    for k, v in top_eps_count.items():
        print(f"  * {k}: {v} proyectos")
    print("\n- Top EPS por monto total:")
    for k, v in monto_eps.items():
        print(f"  * {k}: S/ {v:,.2f}")
        
if __name__ == "__main__":
    main()
