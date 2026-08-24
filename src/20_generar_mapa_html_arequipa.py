import pandas as pd
import geopandas as gpd
import folium
import branca.colormap as cm
from shapely.geometry import Point
import os
import json
from pathlib import Path

CSV_FILE = Path("outputs/proyectos_agua_saneamiento_arequipa_v1.csv")
GPKG_FILE = Path("data/geografia/DISTRITO.gpkg")
EPS_SHP = Path("/Users/pierotarazona/Downloads/Rodrigo_Puno y Arequipa/EPS_Arequipa.shp")
HTML_OUT = Path("outputs/mapa_inversiones_agua_saneamiento_arequipa.html")
EXCEL_HORARIO = Path("/Users/pierotarazona/Downloads/Horario Arequipa.xlsx")

def format_money(val):
    if pd.isna(val) or val == '' or str(val).lower() == 'nan': return "Sin información"
    val = float(val)
    if val >= 1_000_000_000: return f"S/ {val/1_000_000_000:.2f} mil M"
    elif val >= 1_000_000: return f"S/ {val/1_000_000:.1f} M"
    else: return f"S/ {val:,.0f}"

def get_badge_color(estado_actualizacion):
    if estado_actualizacion == 'ACTUALIZADO': return '#2ecc71'
    elif estado_actualizacion == 'VIGENTE_CON_RETRASO': return '#f1c40f'
    elif estado_actualizacion == 'DESACTUALIZADO': return '#e67e22'
    elif estado_actualizacion == 'SIN_FECHA_REPORTE': return '#95a5a6'
    elif estado_actualizacion == 'SIN_AVANCE_FISICO': return '#bdc3c7'
    return '#bdc3c7'

def main():
    print("Cargando datos V1 Arequipa...")
    df = pd.read_csv(CSV_FILE, dtype={'UBIGEO': str, 'CODIGO_UNICO': str}, keep_default_na=False)
    df['UBIGEO'] = df['UBIGEO'].str.zfill(6)
    df['UBIGEO_NORMALIZADO'] = df['UBIGEO'].apply(lambda x: x if len(x) == 6 and not x.endswith('00') else 'GENERICO')
    
    gdf_distritos = gpd.read_file(GPKG_FILE)
    # Arequipa is '04'
    gdf_arequipa = gdf_distritos[gdf_distritos['ccdd'] == '04'].copy()
    gdf_arequipa['ubigeo'] = gdf_arequipa['ubigeo'].astype(str).str.zfill(6)
    
    gdf_eps = gpd.read_file(EPS_SHP)
    if gdf_eps.crs is None or gdf_eps.crs.to_epsg() != 4326:
        gdf_eps = gdf_eps.to_crs(epsg=4326)
    gdf_eps = gdf_eps[['Pres_Sigla', 'geometry']].rename(columns={'Pres_Sigla': 'EPS'})
    
    df['COSTO_ACTUALIZADO'] = pd.to_numeric(df['COSTO_ACTUALIZADO'], errors='coerce')
    df['MONTO_VIABLE'] = pd.to_numeric(df['MONTO_VIABLE'], errors='coerce')
    df['MONTO_REFERENCIA'] = df['COSTO_ACTUALIZADO']
    df.loc[df['MONTO_REFERENCIA'].isna(), 'MONTO_REFERENCIA'] = df['MONTO_VIABLE']
    df['MONTO_REFERENCIA'] = df['MONTO_REFERENCIA'].fillna(0.0)
    
    df['PRESUPUESTO_EJECUTADO'] = pd.to_numeric(df['PRESUPUESTO_EJECUTADO'], errors='coerce')
    df['AVANCE_FISICO_NUM'] = pd.to_numeric(df['AVANCE_FISICO'], errors='coerce')
    df['AVANCE_EJECUCION_NUM'] = pd.to_numeric(df['AVANCE_EJECUCION'], errors='coerce')
    
    df_valid = df[df['UBIGEO_NORMALIZADO'] != 'GENERICO'].copy()
    
    def count_act(x): return (x == 'ACTUALIZADO').sum()
    def count_des(x): return (x == 'DESACTUALIZADO').sum()
    def count_saf(x): return (x == 'SIN_AVANCE_FISICO').sum()
    def count_sfr(x): return (x == 'SIN_FECHA_REPORTE').sum()
    
    agg = df_valid.groupby('UBIGEO_NORMALIZADO').agg(
        TOTAL_PROYECTOS=('CODIGO_UNICO', 'nunique'),
        MONTO_TOTAL_INVERSION=('MONTO_REFERENCIA', 'sum'),
        PRESUPUESTO_EJECUTADO_TOTAL=('PRESUPUESTO_EJECUTADO', lambda x: x.dropna().sum()),
        ACTUALIZADOS=('ESTADO_ACTUALIZACION_FISICA', count_act),
        DESACTUALIZADOS=('ESTADO_ACTUALIZACION_FISICA', count_des),
        SIN_AVANCE=('ESTADO_ACTUALIZACION_FISICA', count_saf),
        SIN_FECHA=('ESTADO_ACTUALIZACION_FISICA', count_sfr)
    ).reset_index()
    
    def calc_mean_and_count(s):
        s_valid = s.dropna()
        if len(s_valid) == 0: return pd.Series([None, 0])
        return pd.Series([s_valid.mean(), len(s_valid)])

    fis_agg = df_valid.groupby('UBIGEO_NORMALIZADO')['AVANCE_FISICO_NUM'].apply(calc_mean_and_count).unstack()
    ejec_agg = df_valid.groupby('UBIGEO_NORMALIZADO')['AVANCE_EJECUCION_NUM'].apply(calc_mean_and_count).unstack()
    
    agg['AVANCE_FISICO_PROM'] = fis_agg[0]
    agg['AVANCE_FISICO_COUNT'] = fis_agg[1].fillna(0)
    agg['AVANCE_EJECUCION_PROM'] = ejec_agg[0]
    agg['AVANCE_EJECUCION_COUNT'] = ejec_agg[1].fillna(0)
    
    TOTAL_PROY = df['CODIGO_UNICO'].nunique()
    TOTAL_MONTO = df['MONTO_REFERENCIA'].sum()
    TOTAL_EJECUTADO = df['PRESUPUESTO_EJECUTADO'].sum()
    
    # EPS Stats para Panel
    DENTRO_EPS = (df['TIENE_EPS_PRESTACION'] == 'SI').sum()
    FUERA_EPS = TOTAL_PROY - DENTRO_EPS
    CANT_EPS = gdf_eps['EPS'].nunique()
    
    fechas_validas = pd.to_datetime(df['ULT_FEC_DECLA_ESTIM'], errors='coerce').dropna()
    f_rec = fechas_validas.max().strftime('%d/%m/%Y') if not fechas_validas.empty else "N/A"
    
    G_ACT = (df['ESTADO_ACTUALIZACION_FISICA'] == 'ACTUALIZADO').sum()
    G_DES = (df['ESTADO_ACTUALIZACION_FISICA'] == 'DESACTUALIZADO').sum()
    G_SAF = (df['ESTADO_ACTUALIZACION_FISICA'] == 'SIN_AVANCE_FISICO').sum()
    G_SFR = (df['ESTADO_ACTUALIZACION_FISICA'] == 'SIN_FECHA_REPORTE').sum()
    
    agg['PCT_PROYECTOS'] = (agg['TOTAL_PROYECTOS'] / TOTAL_PROY * 100).round(2)
    agg['PCT_MONTO'] = (agg['MONTO_TOTAL_INVERSION'] / TOTAL_MONTO * 100).round(2)
    
    max_proy = agg['TOTAL_PROYECTOS'].max()
    max_monto = agg['MONTO_TOTAL_INVERSION'].max()
    agg['INDICE_PROYECTOS'] = agg['TOTAL_PROYECTOS'] / max_proy if max_proy > 0 else 0
    agg['INDICE_MONTO'] = agg['MONTO_TOTAL_INVERSION'] / max_monto if max_monto > 0 else 0
    agg['INDICE_INVERSION'] = (0.5 * agg['INDICE_PROYECTOS']) + (0.5 * agg['INDICE_MONTO'])
    
    gdf_mapa = gdf_arequipa.merge(agg, left_on='ubigeo', right_on='UBIGEO_NORMALIZADO', how='left')
    gdf_mapa['TOTAL_PROYECTOS'] = gdf_mapa['TOTAL_PROYECTOS'].fillna(0)
    gdf_mapa['MONTO_TOTAL_INVERSION'] = gdf_mapa['MONTO_TOTAL_INVERSION'].fillna(0)
    gdf_mapa['PRESUPUESTO_EJECUTADO_TOTAL'] = gdf_mapa['PRESUPUESTO_EJECUTADO_TOTAL'].fillna(0)
    gdf_mapa['INDICE_INVERSION'] = gdf_mapa['INDICE_INVERSION'].fillna(0)
    gdf_mapa['MONTO_FORMAT'] = gdf_mapa['MONTO_TOTAL_INVERSION'].apply(format_money)
    
    print("Creando mapa HTML Arequipa...")
    
    proyectos_dict = {}
    for u in df_valid['UBIGEO_NORMALIZADO'].unique():
        proys_u = df_valid[df_valid['UBIGEO_NORMALIZADO'] == u]
        lista = []
        for _, p in proys_u.iterrows():
            estado = str(p['ESTADO']) if str(p['ESTADO']) not in ['nan', 'none', 'null', ''] else "NO REGISTRADO"
            fec = str(p['ULT_FEC_DECLA_ESTIM'])
            if fec.lower() in ['nan', 'none', 'null', '']: fec = ""
            elif len(fec) > 10: fec = fec[:10]
            if fec:
                parts = fec.split('-')
                if len(parts) == 3: fec = f"{parts[2]}/{parts[1]}/{parts[0]}"
                
            lista.append({
                'cui': str(p['CODIGO_UNICO']),
                'nombre': str(p['NOMBRE_INVERSION']),
                'estado': estado,
                'monto': format_money(p['MONTO_REFERENCIA']),
                'ejecutado': format_money(p['PRESUPUESTO_EJECUTADO']),
                'fisico': p['AVANCE_FISICO_NUM'] if pd.notna(p['AVANCE_FISICO_NUM']) else None,
                'general': p['AVANCE_EJECUCION_NUM'] if pd.notna(p['AVANCE_EJECUCION_NUM']) else None,
                'fecha_fisico': fec,
                'estado_act_fisica': p['ESTADO_ACTUALIZACION_FISICA'],
                'color_act': get_badge_color(p['ESTADO_ACTUALIZACION_FISICA']),
                'adv_fisica': p['ADVERTENCIA_AVANCE_FISICO']
            })
        proyectos_dict[u] = lista
        
    distritos_data = {}
    for _, r in gdf_mapa.iterrows():
        u = r['ubigeo']
        distritos_data[u] = {
            'TOTAL_PROYECTOS': int(r['TOTAL_PROYECTOS']),
            'MONTO_FORMAT': r['MONTO_FORMAT'],
            'PCT_PROYECTOS': r['PCT_PROYECTOS'],
            'PCT_MONTO': r['PCT_MONTO'],
            'EJECUTADO_FORMAT': format_money(r['PRESUPUESTO_EJECUTADO_TOTAL']),
            'FISICO_PROM': f"{r['AVANCE_FISICO_PROM']:.1f}% ({int(r['AVANCE_FISICO_COUNT'])})" if pd.notna(r['AVANCE_FISICO_PROM']) else "S/I",
            'EJECUCION_PROM': f"{r['AVANCE_EJECUCION_PROM']:.1f}% ({int(r['AVANCE_EJECUCION_COUNT'])})" if pd.notna(r['AVANCE_EJECUCION_PROM']) else "S/I",
            'ACTUALIZADOS': int(r.get('ACTUALIZADOS', 0)) if pd.notna(r.get('ACTUALIZADOS')) else 0,
            'DESACTUALIZADOS': int(r.get('DESACTUALIZADOS', 0)) if pd.notna(r.get('DESACTUALIZADOS')) else 0,
            'SIN_AVANCE': int(r.get('SIN_AVANCE', 0)) if pd.notna(r.get('SIN_AVANCE')) else 0,
            'SIN_FECHA': int(r.get('SIN_FECHA', 0)) if pd.notna(r.get('SIN_FECHA')) else 0
        }

    # Centered in Arequipa
    m = folium.Map(location=[-16.0, -72.0], zoom_start=8, tiles='CartoDB Positron', width='70%', height='100%')
    
    colormap = cm.LinearColormap(
        colors=['#FFFFCC', '#A1DAB4', '#41B6C4', '#2C7FB8', '#253494'],
        vmin=0.0,
        vmax=gdf_mapa['INDICE_INVERSION'].max() if gdf_mapa['INDICE_INVERSION'].max() > 0 else 1.0,
    )
    
    def style_function(feature):
        idx = feature['properties'].get('INDICE_INVERSION', 0)
        proy = feature['properties'].get('TOTAL_PROYECTOS', 0)
        if proy == 0:
            return {'fillColor': '#e0e0e0', 'color': '#808080', 'weight': 1, 'fillOpacity': 0.2}
        return {'fillColor': colormap(idx), 'color': '#808080', 'weight': 1, 'fillOpacity': 0.75}

    folium.GeoJson(
        gdf_mapa,
        name='Concentración por distrito',
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['nombdist', 'nombprov', 'ubigeo', 'TOTAL_PROYECTOS', 'MONTO_FORMAT', 'PCT_PROYECTOS'],
            aliases=['Distrito:', 'Provincia:', 'UBIGEO:', 'Proyectos:', 'Monto Total:', '% Proy Arequipa:'],
            localize=True
        )
    ).add_to(m)
    
    # Preparar Capa EPS
    gdf_eps['TOTAL_POLIGONOS'] = gdf_eps.groupby('EPS')['EPS'].transform('count')
    df_eps = df[df['TIENE_EPS_PRESTACION'] == 'SI']
    
    eps_agg = df_eps.groupby('EPS_PRESTACION').agg(
        PROYECTOS=('CODIGO_UNICO', 'nunique'),
        MONTO_TOTAL=('MONTO_REFERENCIA', 'sum'),
        COORD_OFICIAL=('TIPO_COORDENADA', lambda x: x.str.upper().str.contains('OFICIAL').sum()),
        COORD_APROX=('TIPO_COORDENADA', lambda x: x.str.upper().str.contains('APROX').sum()),
        PROY_INVERSION=('TIPO_INVERSION', lambda x: (x.str.upper() == 'PROYECTO DE INVERSIÓN').sum()),
        IOARR=('TIPO_INVERSION', lambda x: (x.str.upper() == 'IOARR').sum())
    ).reset_index()
    
    gdf_eps_mapa = gdf_eps.merge(eps_agg, left_on='EPS', right_on='EPS_PRESTACION', how='left')
    gdf_eps_mapa['PROYECTOS'] = gdf_eps_mapa['PROYECTOS'].fillna(0).astype(int)
    gdf_eps_mapa['PROY_INVERSION'] = gdf_eps_mapa['PROY_INVERSION'].fillna(0).astype(int)
    gdf_eps_mapa['IOARR'] = gdf_eps_mapa['IOARR'].fillna(0).astype(int)
    gdf_eps_mapa['COORD_OFICIAL'] = gdf_eps_mapa['COORD_OFICIAL'].fillna(0).astype(int)
    gdf_eps_mapa['COORD_APROX'] = gdf_eps_mapa['COORD_APROX'].fillna(0).astype(int)
    gdf_eps_mapa['MONTO_TOTAL'] = gdf_eps_mapa['MONTO_TOTAL'].fillna(0).apply(format_money)
    
    # Dynamically assign colors to EPS (using seaborn qualitative palette equivalent)
    eps_unique = gdf_eps_mapa['EPS'].dropna().unique()
    colors = ['#8e44ad', '#e74c3c', '#16a085', '#2980b9', '#f39c12', '#d35400', '#27ae60', '#c0392b', '#1abc9c', '#34495e']
    eps_colors = {eps: colors[i % len(colors)] for i, eps in enumerate(eps_unique)}
    
    def eps_style(feature):
        eps_name = feature['properties'].get('EPS', '')
        col = eps_colors.get(eps_name, '#34495e')
        return {
            'fillColor': col,
            'color': col,
            'weight': 2,
            'fillOpacity': 0.35,
            'dashArray': '4'
        }
        
    folium.GeoJson(
        gdf_eps_mapa,
        name='Ámbito de prestación EPS',
        style_function=eps_style,
        tooltip=folium.GeoJsonTooltip(
            fields=['EPS', 'TOTAL_POLIGONOS', 'PROYECTOS', 'MONTO_TOTAL', 'PROY_INVERSION', 'IOARR', 'COORD_OFICIAL', 'COORD_APROX'],
            aliases=['EPS:', 'Polígonos asociados:', 'Proyectos totales:', 'Inversión Total:', 'Proy. Inversión:', 'IOARR:', 'Coord. Oficiales:', 'Coord. Aproximadas:'],
            localize=True
        ),
        show=False
    ).add_to(m)

    # --- INICIO LÓGICA CONTINUIDAD Y VORONOI ---
    print("Cargando datos de continuidad...")
    if EXCEL_HORARIO.exists():
        df_horario = pd.read_excel(EXCEL_HORARIO)
        agg_horario = df_horario.groupby(['nombre', 'grupo', 'latitud', 'longitud', 'SECTOR', 'LOCALIDAD'], dropna=False).agg(
            HorasPrometidasSemana=('ServicioPrometido', 'sum')
        ).reset_index()
        
        agg_horario['HorasPromedioDia'] = (agg_horario['HorasPrometidasSemana'] / 7).round(1)
        
        fg_continuidad = folium.FeatureGroup(name='Puntos de Continuidad (Horario)', show=True)
        
        for _, row in agg_horario.iterrows():
            lat = row['latitud']
            lon = row['longitud']
            
            if pd.isna(lat) or pd.isna(lon):
                continue
                
            popup_html = f"""
            <div style="font-family: Arial; font-size: 12px; width: 220px;">
                <h4 style="margin: 0 0 5px 0; color: #2980b9;">{row['nombre']}</h4>
                <b>Grupo:</b> {row['grupo']}<br>
                <b>Sector:</b> {row['SECTOR']}<br>
                <b>Localidad:</b> {row['LOCALIDAD']}<br>
                <hr style="margin: 5px 0;">
                <b style="color: #27ae60;">Horas promedio/día:</b> {row['HorasPromedioDia']} h
            </div>
            """
            
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"{row['nombre']} - {row['HorasPromedioDia']} hrs/día",
                icon=folium.Icon(color='blue', icon='tint', prefix='fa')
            ).add_to(fg_continuidad)
            
        fg_continuidad.add_to(m)

        # Generar capa de Voronoi (Polígonos de Continuidad) relativos a todo Arequipa
        from shapely.geometry import Point, MultiPoint
        from shapely.ops import voronoi_diagram
        
        arequipa_geom = gdf_arequipa.unary_union
        
        points_list = []
        data_list = []
        for _, row in agg_horario.iterrows():
            if not pd.isna(row['latitud']) and not pd.isna(row['longitud']):
                points_list.append(Point(row['longitud'], row['latitud']))
                data_list.append(row)
                
        voronoi_features = []
        
        if len(points_list) > 1:
            horas = [r['HorasPromedioDia'] for r in data_list]
            min_h, max_h = min(horas), max(horas)
            
            mp = MultiPoint(points_list)
            regions = voronoi_diagram(mp, envelope=arequipa_geom)
            
            for poly in regions.geoms:
                clipped = poly.intersection(arequipa_geom)
                if clipped.is_empty:
                    continue
                    
                matched_row = None
                for pt, data in zip(points_list, data_list):
                    if poly.contains(pt) or poly.distance(pt) < 1e-6:
                        matched_row = data
                        break
                        
                if matched_row is not None:
                    val = matched_row['HorasPromedioDia']
                    rel_val = 1.0 if min_h == max_h else (val - min_h) / (max_h - min_h)
                    
                    geoms_to_add = [clipped] if clipped.geom_type == 'Polygon' else (list(clipped.geoms) if clipped.geom_type == 'MultiPolygon' else [])
                    for g in geoms_to_add:
                        voronoi_features.append({
                            'type': 'Feature',
                            'geometry': g.__geo_interface__,
                            'properties': {
                                'HorasPromedioDia': float(val),
                                'Relativo': float(rel_val)
                            }
                        })
                            
        if voronoi_features:
            voronoi_geojson = {'type': 'FeatureCollection', 'features': voronoi_features}
            
            voronoi_cmap = cm.LinearColormap(
                colors=['red', 'yellow', 'green'],
                vmin=0.0,
                vmax=1.0
            )
            voronoi_cmap.caption = 'Continuidad Relativa por EPS (0=Mínimo, 1=Máximo)'
            
            def voronoi_style(feature):
                rel_val = feature['properties']['Relativo']
                col = voronoi_cmap(rel_val)
                return {
                    'fillColor': col,
                    'color': 'black',
                    'weight': 1,
                    'fillOpacity': 0.4
                }
                
            folium.GeoJson(
                voronoi_geojson,
                name='Áreas de Continuidad (Voronoi Relativo)',
                style_function=voronoi_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=['HorasPromedioDia'],
                    aliases=['Horas Promedio/Día:'],
                    localize=True
                ),
                show=False
            ).add_to(m)
            voronoi_cmap.add_to(m)
    # --- FIN LÓGICA CONTINUIDAD Y VORONOI ---

    legend_html = '''
    <div style="position: fixed; bottom: 50px; left: 50px; width: 280px; height: 120px; 
         background-color: rgba(255, 255, 255, 0.9); border:2px solid grey; z-index:9999; font-size:12px; padding: 10px; font-family: Arial;">
         <b>Concentración de inversión</b><br><br>
         <div style="background: linear-gradient(to right, #FFFFCC, #A1DAB4, #41B6C4, #2C7FB8, #253494); height: 15px; width: 100%;"></div>
         <div style="display: flex; justify-content: space-between; font-size:11px; margin-top:2px;">
             <span>Menos<br>inversión</span><span style="text-align: right;">Más<br>inversión</span>
         </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    top_proy = agg.nlargest(5, 'TOTAL_PROYECTOS')[['UBIGEO_NORMALIZADO', 'TOTAL_PROYECTOS']]
    def get_dist_name(u):
        n = gdf_arequipa[gdf_arequipa['ubigeo'] == u]['nombdist'].values
        return n[0] if len(n)>0 else u
        
    top_proy_html = "".join([f"<li>{get_dist_name(u)} — {int(p)} proy.</li>" for u, p in zip(top_proy['UBIGEO_NORMALIZADO'], top_proy['TOTAL_PROYECTOS'])])

    # Panel General superpuesto
    panel_html = f'''
    <div style="position: fixed; bottom: 190px; left: 50px; width: 280px; 
         background-color: rgba(255, 255, 255, 0.95); border:2px solid grey; z-index:9999; font-size:12px; padding: 10px; font-family: Arial; box-sizing: border-box;">
         <h4 style="margin-top:0; font-size:14px; text-align:center; color: #2c3e50;">Agua y Saneamiento (Arequipa)</h4>
         <hr style="margin:5px 0;">
         <b>Total de proyectos:</b> {TOTAL_PROY}<br>
         <b>Inversión total referencial:</b> {format_money(TOTAL_MONTO)}<br>
         <b>Presupuesto ejecutado acumulado:</b> {format_money(TOTAL_EJECUTADO)}
    </div>
    '''
    m.get_root().html.add_child(folium.Element(panel_html))
    
    # PANEL LATERAL
    side_panel_html = """
    <div id="side-panel" style="position: absolute; right: 0; top: 0; width: 30%; height: 100vh; background-color: #f8f9fa; z-index: 1000; border-left: 2px solid #ddd; padding: 15px; font-family: Arial; overflow-y: auto; box-sizing: border-box;">
        <div id="side-panel-content">
            <h3 style="color: #333; margin-top:10px;">Inversiones de Agua y Saneamiento</h3>
            <p style="color: #666; font-size: 14px;">Selecciona un distrito en el mapa para ver sus proyectos.</p>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(side_panel_html))
    
    js_data = f"<script>var proyectosPorUbigeo = {json.dumps(proyectos_dict)};\nvar distritosData = {json.dumps(distritos_data)};</script>"
    m.get_root().html.add_child(folium.Element(js_data))
    
    js_interaction = """
    <script>
    function createProgressBar(val) {
        if (val === null || val === undefined) return "<span style='color:#7f8c8d;'>Sin información registrada</span>";
        var w = Math.min(100, Math.max(0, val));
        var c = (w < 50) ? '#e67e22' : ((w < 80) ? '#f1c40f' : '#2ecc71');
        var warn = (val > 100) ? " <span title='Valor superior al 100%' style='color:red;'>⚠</span>" : "";
        var html = "<div style='display:flex; align-items:center; gap:5px; width:100%;'>";
        html += "<div style='flex:1; background:#eee; height:8px; border-radius:4px; overflow:hidden;'>";
        html += "<div style='background:" + c + "; width:" + w + "%; height:100%;'></div>";
        html += "</div>";
        html += "<span style='font-size:11px; font-weight:bold; min-width:40px; text-align:right;'>" + val.toFixed(1) + "%" + warn + "</span>";
        html += "</div>";
        return html;
    }

    function updatePanel(props) {
        var ubigeo = props.ubigeo;
        var proys = proyectosPorUbigeo[ubigeo] || [];
        var ddata = distritosData[ubigeo] || {};
        
        var html = "<h2 style='margin-top:0; margin-bottom:5px; color:#2c3e50; font-size: 18px;'>" + props.nombdist + "</h2>";
        html += "<p style='margin: 0; color: #555; font-size: 11px;'><b>Provincia:</b> " + props.nombprov + " | <b>UBIGEO:</b> " + ubigeo + "</p>";
        html += "<hr style='margin: 10px 0; border: 0; border-top: 1px solid #ccc;'>";
        
        html += "<div style='display:flex; flex-wrap:wrap; gap:5px; margin-bottom: 10px;'>";
        html += "<div style='flex:1; min-width:30%; background:#fff; padding:6px; border-radius:5px; border:1px solid #eee;'><b>Total Proy.</b><br><span style='font-size:15px; color:#2980b9; font-weight:bold;'>" + (ddata.TOTAL_PROYECTOS || 0) + "</span></div>";
        html += "<div style='flex:1; min-width:60%; background:#fff; padding:6px; border-radius:5px; border:1px solid #eee;'><b>Inversión</b><br><span style='font-size:15px; color:#27ae60; font-weight:bold;'>" + (ddata.MONTO_FORMAT || 'S/ 0') + "</span></div>";
        html += "</div>";
        
        html += "<div style='display:flex; flex-wrap:wrap; gap:5px; margin-bottom: 10px;'>";
        html += "<div style='flex:1; min-width:48%; background:#fff; padding:6px; border-radius:5px; border:1px solid #eee; font-size:10px;'><span style='color:#27ae60; font-weight:bold;'>Actulizados:</span> " + ddata.ACTUALIZADOS + "</div>";
        html += "<div style='flex:1; min-width:48%; background:#fff; padding:6px; border-radius:5px; border:1px solid #eee; font-size:10px;'><span style='color:#e67e22; font-weight:bold;'>Desactualizados:</span> " + ddata.DESACTUALIZADOS + "</div>";
        html += "<div style='flex:1; min-width:48%; background:#fff; padding:6px; border-radius:5px; border:1px solid #eee; font-size:10px;'><span style='color:#7f8c8d;'>Sin Fecha:</span> " + ddata.SIN_FECHA + "</div>";
        html += "<div style='flex:1; min-width:48%; background:#fff; padding:6px; border-radius:5px; border:1px solid #eee; font-size:10px;'><span style='color:#bdc3c7;'>Sin Avance:</span> " + ddata.SIN_AVANCE + "</div>";
        html += "</div>";
        
        html += "<h3 style='margin-bottom:8px; color:#34495e; font-size: 14px;'>Lista de Proyectos (" + proys.length + ")</h3>";
        html += "<div style='display:flex; flex-direction:column; gap:10px;'>";
        
        for(var i=0; i<proys.length; i++) {
            var p = proys[i];
            html += "<div style='background: white; border: 1px solid #ddd; border-radius: 5px; padding: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); border-left: 4px solid " + p.color_act + ";'>";
            html += "<div style='font-size: 10px; color: #7f8c8d; margin-bottom: 3px;'>CUI: " + p.cui + "</div>";
            html += "<div style='font-size: 12px; font-weight: bold; margin-bottom: 5px; color: #2c3e50; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;' title='" + p.nombre + "'>" + p.nombre + "</div>";
            html += "<div style='font-size: 11px; margin-bottom: 3px;'>Estado: <span style='color: blue; font-weight: bold;'>" + p.estado + "</span></div>";
            html += "<div style='font-size: 11px; margin-bottom: 3px;'>Monto: <b>" + p.monto + "</b></div>";
            html += "<div style='font-size: 11px; margin-bottom: 6px;'>Ejecutado: <span style='color:#8e44ad; font-weight:bold;'>" + p.ejecutado + "</span></div>";
            
            var warning_html = (p.adv_fisica && p.estado_act_fisica === 'DESACTUALIZADO') ? "<div style='font-size:10px; color:#e67e22; margin-top:2px; font-weight:bold;'>⚠ " + p.adv_fisica + "</div>" : "";
            var fecha_text = p.fecha_fisico ? "Fecha de reporte: " + p.fecha_fisico : "Sin fecha de reporte";
            if(p.estado_act_fisica === 'SIN_AVANCE_FISICO') fecha_text = "";
            
            html += "<div style='font-size: 10px; color:#555;'><b>Último avance físico reportado</b></div>";
            html += createProgressBar(p.fisico);
            if(fecha_text) html += "<div style='font-size: 10px; color:#7f8c8d; margin-bottom:2px;'>" + fecha_text + "</div>";
            html += warning_html;
            
            html += "<div style='font-size: 10px; color:#555; margin-top:6px;'>Avance General</div>";
            html += createProgressBar(p.general);
            
            html += "</div>";
        }
        
        html += "</div>";
        document.getElementById('side-panel-content').innerHTML = html;
    }
    
    window.onload = function() {
        setTimeout(function() {
            for (var key in window) {
                if (key.startsWith("map_")) {
                    var map = window[key];
                    var selectedLayer = null;
                    
                    map.eachLayer(function(layer) {
                        if (layer.eachLayer) {
                            layer.eachLayer(function(sublayer) {
                                if (sublayer.feature && sublayer.feature.properties && sublayer.feature.properties.ubigeo) {
                                    sublayer.on('click', function(e) {
                                        if(sublayer.feature.properties.TOTAL_PROYECTOS > 0) {
                                            if (selectedLayer) {
                                                selectedLayer.setStyle({color: '#808080', weight: 1});
                                            }
                                            sublayer.setStyle({color: '#e74c3c', weight: 3});
                                            if(sublayer.bringToFront) sublayer.bringToFront();
                                            selectedLayer = sublayer;
                                            updatePanel(sublayer.feature.properties);
                                        }
                                    });
                                }
                            });
                        }
                    });
                }
            }
        }, 1000);
    };
    </script>
    """
    m.get_root().html.add_child(folium.Element(js_interaction))
    
    folium.LayerControl(position='topleft').add_to(m)
    m.save(str(HTML_OUT))
    print(f"Mapa guardado en {HTML_OUT.as_posix()}")

if __name__ == "__main__":
    main()
