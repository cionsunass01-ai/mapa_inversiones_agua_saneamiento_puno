import pandas as pd
import geopandas as gpd
import folium
import branca.colormap as cm
from shapely.geometry import Point
import os
import json
from pathlib import Path

# Archivos
CSV_FILE = Path("outputs/proyectos_agua_saneamiento_puno_v3.csv")
GPKG_FILE = Path("data/geografia/DISTRITO.gpkg")
HTML_OUT = Path("outputs/mapa_inversiones_agua_saneamiento_puno.html")
AUDIT_OUT = Path("outputs/auditoria_ubigeo_espacial.csv")

def format_money(val):
    if pd.isna(val): return "S/ 0.00"
    if val >= 1_000_000:
        return f"S/ {val/1_000_000:.1f} M"
    else:
        return f"S/ {val:,.2f}"

def main():
    print("Cargando datos...")
    df = pd.read_csv(CSV_FILE, dtype={'UBIGEO': str, 'CODIGO_UNICO': str})
    df['UBIGEO'] = df['UBIGEO'].str.zfill(6)
    
    df['UBIGEO_NORMALIZADO'] = df['UBIGEO'].apply(lambda x: x if len(x) == 6 and not x.endswith('00') else 'GENERICO')
    
    gdf_distritos = gpd.read_file(GPKG_FILE)
    gdf_puno = gdf_distritos[gdf_distritos['ccdd'] == '21'].copy()
    gdf_puno['ubigeo'] = gdf_puno['ubigeo'].astype(str).str.zfill(6)
    
    df['COSTO_ACTUALIZADO'] = pd.to_numeric(df['COSTO_ACTUALIZADO'], errors='coerce')
    df['MONTO_VIABLE'] = pd.to_numeric(df['MONTO_VIABLE'], errors='coerce')
    
    df['MONTO_REFERENCIA'] = df['COSTO_ACTUALIZADO']
    mask_na = df['MONTO_REFERENCIA'].isna()
    df.loc[mask_na, 'MONTO_REFERENCIA'] = df.loc[mask_na, 'MONTO_VIABLE']
    df['MONTO_REFERENCIA'] = df['MONTO_REFERENCIA'].fillna(0.0)
    fallbacks_monto = mask_na.sum()
    
    df_valid = df[df['UBIGEO_NORMALIZADO'] != 'GENERICO'].copy()
    
    agg = df_valid.groupby('UBIGEO_NORMALIZADO').agg(
        TOTAL_PROYECTOS=('CODIGO_UNICO', 'nunique'),
        MONTO_TOTAL_INVERSION=('MONTO_REFERENCIA', 'sum')
    ).reset_index()
    
    TOTAL_PUNO_PROY = df['CODIGO_UNICO'].nunique()
    TOTAL_PUNO_MONTO = df['MONTO_REFERENCIA'].sum()
    
    agg['PCT_PROYECTOS'] = (agg['TOTAL_PROYECTOS'] / TOTAL_PUNO_PROY * 100).round(2)
    agg['PCT_MONTO'] = (agg['MONTO_TOTAL_INVERSION'] / TOTAL_PUNO_MONTO * 100).round(2)
    
    max_proy = agg['TOTAL_PROYECTOS'].max()
    max_monto = agg['MONTO_TOTAL_INVERSION'].max()
    agg['INDICE_PROYECTOS'] = agg['TOTAL_PROYECTOS'] / max_proy if max_proy > 0 else 0
    agg['INDICE_MONTO'] = agg['MONTO_TOTAL_INVERSION'] / max_monto if max_monto > 0 else 0
    agg['INDICE_INVERSION'] = (0.5 * agg['INDICE_PROYECTOS']) + (0.5 * agg['INDICE_MONTO'])
    
    gdf_mapa = gdf_puno.merge(agg, left_on='ubigeo', right_on='UBIGEO_NORMALIZADO', how='left')
    gdf_mapa['TOTAL_PROYECTOS'] = gdf_mapa['TOTAL_PROYECTOS'].fillna(0)
    gdf_mapa['MONTO_TOTAL_INVERSION'] = gdf_mapa['MONTO_TOTAL_INVERSION'].fillna(0)
    gdf_mapa['INDICE_INVERSION'] = gdf_mapa['INDICE_INVERSION'].fillna(0)
            
    gdf_mapa['MONTO_FORMAT'] = gdf_mapa['MONTO_TOTAL_INVERSION'].apply(format_money)
    
    # Validacion espacial
    df_pts = df.dropna(subset=['LATITUD', 'LONGITUD']).copy()
    df_pts = df_pts[(df_pts['LATITUD'] != '0.0') & (df_pts['LATITUD'] != '')].copy()
    geometry = [Point(xy) for xy in zip(pd.to_numeric(df_pts['LONGITUD']), pd.to_numeric(df_pts['LATITUD']))]
    gdf_pts = gpd.GeoDataFrame(df_pts, geometry=geometry, crs="EPSG:4326")
    
    if gdf_puno.crs is None or gdf_puno.crs.to_string() != "EPSG:4326":
        gdf_puno = gdf_puno.to_crs("EPSG:4326")
        
    joined = gpd.sjoin(gdf_pts, gdf_puno, how="left", predicate="intersects")
    audit_cols = ['CODIGO_UNICO', 'NOMBRE_INVERSION', 'UBIGEO', 'ubigeo', 'DISTRITO', 'nombdist', 'PROVINCIA', 'nombprov', 'TIPO_COORDENADA']
    audit_df = joined[audit_cols].copy()
    audit_df.columns = ['CODIGO_UNICO', 'NOMBRE_INVERSION', 'UBIGEO_MEF', 'UBIGEO_ESPACIAL', 'DISTRITO_MEF', 'DISTRITO_ESPACIAL', 'PROVINCIA_MEF', 'PROVINCIA_ESPACIAL', 'TIPO_COORDENADA']
    audit_df['COINCIDE_UBIGEO'] = audit_df['UBIGEO_MEF'] == audit_df['UBIGEO_ESPACIAL']
    audit_df['ES_GENERICO'] = audit_df['UBIGEO_MEF'].apply(lambda x: len(str(x)) != 6 or str(x).endswith('00'))
    audit_df.to_csv(AUDIT_OUT, index=False)
    
    coinciden = len(audit_df[(audit_df['COINCIDE_UBIGEO'] == True) & (audit_df['ES_GENERICO'] == False)])
    no_coinciden = len(audit_df[(audit_df['COINCIDE_UBIGEO'] == False) & (audit_df['ES_GENERICO'] == False) & audit_df['UBIGEO_ESPACIAL'].notna()])
    genericos = len(audit_df[audit_df['ES_GENERICO'] == True])
    
    print("Creando mapa...")
    
    # JSON para JS
    proyectos_dict = {}
    for u in df_valid['UBIGEO_NORMALIZADO'].unique():
        proys_u = df_valid[df_valid['UBIGEO_NORMALIZADO'] == u]
        lista = []
        for _, p in proys_u.iterrows():
            estado = str(p['ESTADO'])
            if estado.lower() in ['nan', 'none', 'null', '']: estado = "NO REGISTRADO"
            lista.append({
                'cui': str(p['CODIGO_UNICO']),
                'nombre': str(p['NOMBRE_INVERSION']),
                'estado': estado,
                'monto': format_money(p['MONTO_REFERENCIA'])
            })
        proyectos_dict[u] = lista

    m = folium.Map(location=[-15.1, -70.0], zoom_start=7.5, tiles='CartoDB Positron', width='70%', height='100%')
    
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
        return {
            'fillColor': colormap(idx),
            'color': '#808080',
            'weight': 1,
            'fillOpacity': 0.75
        }

    folium.GeoJson(
        gdf_mapa,
        name='Concentración por distrito',
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=['nombdist', 'nombprov', 'ubigeo', 'TOTAL_PROYECTOS', 'MONTO_FORMAT', 'PCT_PROYECTOS', 'PCT_MONTO'],
            aliases=['Distrito:', 'Provincia:', 'UBIGEO:', 'Proyectos:', 'Monto Total:', '% Proy Puno:', '% Monto Puno:'],
            localize=True
        )
    ).add_to(m)

    points_layer = folium.FeatureGroup(name='Proyectos individuales', show=False)
    type_colors = {
        'OFICIAL_ORIGINAL': 'green',
        'APROXIMADA_LOCALIDAD': 'orange',
        'APROXIMADA_DISTRITO': 'red'
    }
    type_desc = {
        'OFICIAL_ORIGINAL': 'Coordenada proveniente del Banco de Inversiones del MEF.',
        'APROXIMADA_LOCALIDAD': 'Ubicación referencial de la localidad identificada en el proyecto.',
        'APROXIMADA_DISTRITO': 'Ubicación referencial del distrito; no representa la posición exacta de la infraestructura.'
    }
    
    for idx, row in df.iterrows():
        lat = pd.to_numeric(row['LATITUD'], errors='coerce')
        lon = pd.to_numeric(row['LONGITUD'], errors='coerce')
        if pd.notna(lat) and pd.notna(lon) and lat != 0.0:
            ctype = row['TIPO_COORDENADA']
            color = type_colors.get(ctype, 'gray')
            monto = row['MONTO_REFERENCIA']
            
            html_pt = f"""
            <div style="font-family: Arial; font-size:12px; width:300px; max-height:250px; overflow-y:auto;">
            <b>CUI:</b> {row['CODIGO_UNICO']}<br>
            <b>Inversión:</b> {row['NOMBRE_INVERSION']}<br><br>
            <b>Descripción:</b> {row['DESCRIPCION']}<br>
            <b>Alternativa:</b> {row['ALTERNATIVA']}<br>
            <b>Tipo:</b> {row['TIPO_INVERSION']}<br>
            <b>Ubicación:</b> {row['DISTRITO']}, {row['PROVINCIA']}<br>
            <b>Monto Referencia:</b> {format_money(monto)}<br>
            <hr style="margin:5px 0;">
            <b>TIPO_COORDENADA:</b> <span style="color:{color}; font-weight:bold;">{ctype}</span><br>
            <i>{type_desc.get(ctype, '')}</i>
            </div>
            """
            folium.CircleMarker(
                location=[lat, lon],
                radius=4,
                color=color,
                fill=True,
                fillOpacity=0.8,
                popup=folium.Popup(html_pt, max_width=320)
            ).add_to(points_layer)
            
    points_layer.add_to(m)

    legend_html = '''
    <div style="position: fixed; 
         bottom: 50px; left: 50px; width: 280px; height: 120px; 
         background-color: rgba(255, 255, 255, 0.9); border:2px solid grey; z-index:9999; font-size:12px; padding: 10px; font-family: Arial;">
         <b>Concentración de inversión</b><br><br>
         <div style="background: linear-gradient(to right, #FFFFCC, #A1DAB4, #41B6C4, #2C7FB8, #253494); height: 15px; width: 100%;"></div>
         <div style="display: flex; justify-content: space-between; font-size:11px; margin-top:2px;">
             <span>Menos proyectos<br>y menor inversión</span>
             <span style="text-align: right;">Más proyectos<br>y mayor inversión</span>
         </div>
         <div style="font-size:10px; margin-top: 5px; color: gray;">
            El color combina en partes iguales la cantidad de proyectos y el monto acumulado de inversión por distrito. Comparativo dentro de Puno.
         </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    top_proy = agg.nlargest(5, 'TOTAL_PROYECTOS')[['UBIGEO_NORMALIZADO', 'TOTAL_PROYECTOS']]
    top_monto = agg.nlargest(5, 'MONTO_TOTAL_INVERSION')[['UBIGEO_NORMALIZADO', 'MONTO_TOTAL_INVERSION']]
    
    def get_dist_name(u):
        n = gdf_puno[gdf_puno['ubigeo'] == u]['nombdist'].values
        return n[0] if len(n)>0 else u
        
    top_proy_html = "".join([f"<li>{get_dist_name(u)} — {int(p)} proy.</li>" for u, p in zip(top_proy['UBIGEO_NORMALIZADO'], top_proy['TOTAL_PROYECTOS'])])
    top_monto_html = "".join([f"<li>{get_dist_name(u)} — {format_money(m)}</li>" for u, m in zip(top_monto['UBIGEO_NORMALIZADO'], top_monto['MONTO_TOTAL_INVERSION'])])

    dist_con_proy = len(agg[agg['TOTAL_PROYECTOS'] > 0])
    prov_con_proy = df_valid['PROVINCIA'].nunique()
    
    # Panel General superpuesto sobre el mapa a la izquierda
    panel_html = f'''
    <div style="position: fixed; 
         top: 10px; left: 60px; width: 300px; 
         background-color: rgba(255, 255, 255, 0.95); border:2px solid grey; z-index:9999; font-size:12px; padding: 10px; font-family: Arial; max-height: 90vh; overflow-y: auto;">
         <h4 style="margin-top:0; font-size:14px; text-align:center;">Proyectos de Agua y Saneamiento en Puno</h4>
         <div style="text-align:center; font-size:10px; color:gray; margin-bottom:10px;">Distribución territorial de proyectos y montos de inversión</div>
         <b>Total de proyectos:</b> {TOTAL_PUNO_PROY}<br>
         <b>Monto total:</b> {format_money(TOTAL_PUNO_MONTO)}<br>
         <b>Distritos con proyectos:</b> {dist_con_proy}<br>
         <b>Provincias con proyectos:</b> {prov_con_proy}<br>
         <hr style="margin:5px 0;">
         <b>Top 5 por cantidad de proyectos:</b>
         <ol style="margin-top:5px; margin-bottom:5px; padding-left:25px;">{top_proy_html}</ol>
         <b>Top 5 por monto de inversión:</b>
         <ol style="margin-top:5px; margin-bottom:5px; padding-left:25px;">{top_monto_html}</ol>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(panel_html))
    
    # INYECCION DEL PANEL LATERAL E INTERACCION
    side_panel_html = """
    <div id="side-panel" style="position: absolute; right: 0; top: 0; width: 30%; height: 100vh; background-color: #f8f9fa; z-index: 1000; border-left: 2px solid #ddd; padding: 20px; font-family: Arial; overflow-y: auto; box-sizing: border-box;">
        <div id="side-panel-content">
            <h3 style="color: #333; margin-top:10px;">Inversiones de Agua y Saneamiento</h3>
            <p style="color: #666; font-size: 14px;">Selecciona un distrito en el mapa para ver sus proyectos.</p>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(side_panel_html))
    
    js_data = f"<script>var proyectosPorUbigeo = {json.dumps(proyectos_dict)};</script>"
    m.get_root().html.add_child(folium.Element(js_data))
    
    js_interaction = """
    <script>
    function updatePanel(props) {
        var ubigeo = props.ubigeo;
        var proys = proyectosPorUbigeo[ubigeo] || [];
        
        var html = "<h2 style='margin-top:0; color:#2c3e50; font-size: 18px;'>" + props.nombdist + "</h2>";
        html += "<p style='margin: 0; color: #555; font-size: 12px;'><b>Provincia:</b> " + props.nombprov + " | <b>UBIGEO:</b> " + ubigeo + "</p>";
        html += "<hr style='margin: 15px 0; border: 0; border-top: 1px solid #ccc;'>";
        
        html += "<div style='display:flex; flex-wrap:wrap; gap:10px; margin-bottom: 15px;'>";
        html += "<div style='flex:1; min-width:45%; background:#fff; padding:10px; border-radius:5px; border:1px solid #eee;'><b>Total Proyectos</b><br><span style='font-size:18px; color:#2980b9; font-weight:bold;'>" + props.TOTAL_PROYECTOS + "</span><br><span style='font-size:10px; color:#7f8c8d;'>" + props.PCT_PROYECTOS + "% de Puno</span></div>";
        html += "<div style='flex:1; min-width:45%; background:#fff; padding:10px; border-radius:5px; border:1px solid #eee;'><b>Monto Total</b><br><span style='font-size:16px; color:#27ae60; font-weight:bold;'>" + props.MONTO_FORMAT + "</span><br><span style='font-size:10px; color:#7f8c8d;'>" + props.PCT_MONTO + "% de Puno</span></div>";
        html += "</div>";
        
        html += "<h3 style='margin-bottom:10px; color:#34495e; font-size: 15px;'>Lista de Proyectos (" + proys.length + ")</h3>";
        html += "<div style='display:flex; flex-direction:column; gap:10px;'>";
        
        for(var i=0; i<proys.length; i++) {
            var p = proys[i];
            html += "<div style='background: white; border: 1px solid #ddd; border-radius: 5px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);'>";
            html += "<div style='font-size: 11px; color: #7f8c8d; margin-bottom: 4px;'>CUI: " + p.cui + "</div>";
            html += "<div style='font-size: 12px; font-weight: bold; margin-bottom: 6px; color: #2c3e50; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;' title='" + p.nombre + "'>" + p.nombre + "</div>";
            html += "<div style='font-size: 11px; margin-bottom: 4px;'>Estado: <span style='color: blue; font-weight: bold;'>" + p.estado + "</span></div>";
            html += "<div style='font-size: 12px;'>Monto: <b>" + p.monto + "</b></div>";
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
    
    print("\n=== REPORTE MAPA ===")
    print(f"1. Ruta HTML: {HTML_OUT.as_posix()}")
    print(f"2. Tamaño HTML: {HTML_OUT.stat().st_size / (1024*1024):.2f} MB")
    print(f"3. Distritos Puno cargados: {len(gdf_puno)}")
    print(f"4. Distritos con proyectos: {dist_con_proy}")
    print(f"5. Total de proyectos representados (universo): {TOTAL_PUNO_PROY}")
    print(f"6. Monto total representado: {format_money(TOTAL_PUNO_MONTO)}")
    
    juliaca_proys = len(proyectos_dict.get('211101', []))
    ilave_proys = len(proyectos_dict.get('210501', []))
    acora_proys = len(proyectos_dict.get('210102', []))
    print(f"\nVerificación específica:")
    print(f"- JULIACA (UBIGEO 211101): {juliaca_proys} proyectos")
    print(f"- ILAVE (UBIGEO 210501): {ilave_proys} proyectos")
    print(f"- ACORA (UBIGEO 210102): {acora_proys} proyectos")
    
if __name__ == "__main__":
    main()
