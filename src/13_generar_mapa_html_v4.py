import pandas as pd
import geopandas as gpd
import folium
import branca.colormap as cm
from shapely.geometry import Point
import os
import json
from pathlib import Path

# Archivos
CSV_FILE = Path("outputs/proyectos_agua_saneamiento_puno_v4.csv")
GPKG_FILE = Path("data/geografia/DISTRITO.gpkg")
HTML_OUT = Path("outputs/mapa_inversiones_agua_saneamiento_puno.html")
AUDITORIA_AVANCES = Path("outputs/auditoria_avances.csv")

def format_money(val):
    if pd.isna(val) or val == '' or str(val).lower() == 'nan': return "Sin información"
    val = float(val)
    if val >= 1_000_000_000:
        return f"S/ {val/1_000_000_000:.2f} mil M"
    elif val >= 1_000_000:
        return f"S/ {val/1_000_000:.1f} M"
    else:
        return f"S/ {val:,.0f}"

def format_pct(val):
    if pd.isna(val) or val == '' or str(val).lower() == 'nan': return "Sin información registrada"
    return f"{float(val):.1f}%"

def parse_num(val):
    if pd.isna(val) or str(val).strip().lower() in ['', 'nan', 'none', 'null']:
        return None
    try:
        return float(val)
    except:
        return None

def main():
    print("Cargando datos V4...")
    df = pd.read_csv(CSV_FILE, dtype={'UBIGEO': str, 'CODIGO_UNICO': str})
    df['UBIGEO'] = df['UBIGEO'].str.zfill(6)
    
    df['UBIGEO_NORMALIZADO'] = df['UBIGEO'].apply(lambda x: x if len(x) == 6 and not x.endswith('00') else 'GENERICO')
    
    gdf_distritos = gpd.read_file(GPKG_FILE)
    gdf_puno = gdf_distritos[gdf_distritos['ccdd'] == '21'].copy()
    gdf_puno['ubigeo'] = gdf_puno['ubigeo'].astype(str).str.zfill(6)
    
    # Manejo seguro de numéricos
    df['COSTO_ACTUALIZADO'] = pd.to_numeric(df['COSTO_ACTUALIZADO'], errors='coerce')
    df['MONTO_VIABLE'] = pd.to_numeric(df['MONTO_VIABLE'], errors='coerce')
    df['MONTO_REFERENCIA'] = df['COSTO_ACTUALIZADO']
    df.loc[df['MONTO_REFERENCIA'].isna(), 'MONTO_REFERENCIA'] = df['MONTO_VIABLE']
    df['MONTO_REFERENCIA'] = df['MONTO_REFERENCIA'].fillna(0.0)
    
    df['PRESUPUESTO_EJECUTADO'] = pd.to_numeric(df['PRESUPUESTO_EJECUTADO'], errors='coerce')
    df['AVANCE_FISICO'] = pd.to_numeric(df['AVANCE_FISICO'], errors='coerce')
    df['AVANCE_EJECUCION'] = pd.to_numeric(df['AVANCE_EJECUCION'], errors='coerce')
    df['COSTO_ACTUALIZADO'] = pd.to_numeric(df['COSTO_ACTUALIZADO'], errors='coerce').fillna(0.0)
    
    df_valid = df[df['UBIGEO_NORMALIZADO'] != 'GENERICO'].copy()
    
    # Agrupaciones Distritales
    agg = df_valid.groupby('UBIGEO_NORMALIZADO').agg(
        TOTAL_PROYECTOS=('CODIGO_UNICO', 'nunique'),
        MONTO_TOTAL_INVERSION=('MONTO_REFERENCIA', 'sum'),
        PRESUPUESTO_EJECUTADO_TOTAL=('PRESUPUESTO_EJECUTADO', lambda x: x.dropna().sum())
    ).reset_index()
    
    # Promedios físicos y generales considerando SÓLO los válidos
    def calc_mean_and_count(s):
        s_valid = s.dropna()
        if len(s_valid) == 0: return pd.Series([None, 0])
        return pd.Series([s_valid.mean(), len(s_valid)])

    fis_agg = df_valid.groupby('UBIGEO_NORMALIZADO')['AVANCE_FISICO'].apply(calc_mean_and_count).unstack()
    ejec_agg = df_valid.groupby('UBIGEO_NORMALIZADO')['AVANCE_EJECUCION'].apply(calc_mean_and_count).unstack()
    
    agg['AVANCE_FISICO_PROM'] = fis_agg[0]
    agg['AVANCE_FISICO_COUNT'] = fis_agg[1].fillna(0)
    agg['AVANCE_EJECUCION_PROM'] = ejec_agg[0]
    agg['AVANCE_EJECUCION_COUNT'] = ejec_agg[1].fillna(0)
    
    TOTAL_PUNO_PROY = df['CODIGO_UNICO'].nunique()
    TOTAL_PUNO_MONTO = df['MONTO_REFERENCIA'].sum()
    TOTAL_PUNO_EJECUTADO = df['PRESUPUESTO_EJECUTADO'].sum()
    TOTAL_PUNO_COSTO = df['COSTO_ACTUALIZADO'].sum()
    TOTAL_PUNO_AVANCE_FINAN = (TOTAL_PUNO_EJECUTADO / TOTAL_PUNO_COSTO * 100) if TOTAL_PUNO_COSTO > 0 else 0
    
    COUNT_PUNO_FISICO = df['AVANCE_FISICO'].notna().sum()
    COUNT_PUNO_EJECUCION = df['AVANCE_EJECUCION'].notna().sum()
    
    COUNT_EJEC_NULO = df['PRESUPUESTO_EJECUTADO'].isna().sum()
    COUNT_EJEC_VALID = df['PRESUPUESTO_EJECUTADO'].notna().sum()
    COUNT_FISICO_NULO = df['AVANCE_FISICO'].isna().sum()
    COUNT_EJECUCION_NULO = df['AVANCE_EJECUCION'].isna().sum()
    TOTAL_DEV_ACTUAL = pd.to_numeric(df['PRESUPUESTO_EJECUTADO_ANIO_ACTUAL'], errors='coerce').sum()
    
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
    gdf_mapa['PRESUPUESTO_EJECUTADO_TOTAL'] = gdf_mapa['PRESUPUESTO_EJECUTADO_TOTAL'].fillna(0)
    gdf_mapa['INDICE_INVERSION'] = gdf_mapa['INDICE_INVERSION'].fillna(0)
    gdf_mapa['MONTO_FORMAT'] = gdf_mapa['MONTO_TOTAL_INVERSION'].apply(format_money)
    
    print("Creando mapa HTML...")
    
    # JSON para JS
    proyectos_dict = {}
    for u in df_valid['UBIGEO_NORMALIZADO'].unique():
        proys_u = df_valid[df_valid['UBIGEO_NORMALIZADO'] == u]
        lista = []
        for _, p in proys_u.iterrows():
            estado = str(p['ESTADO'])
            if estado.lower() in ['nan', 'none', 'null', '']: estado = "NO REGISTRADO"
            
            fec = str(p['ULT_FEC_DECLA_ESTIM'])
            if fec.lower() in ['nan', 'none', 'null', '']: fec = ""
            
            lista.append({
                'cui': str(p['CODIGO_UNICO']),
                'nombre': str(p['NOMBRE_INVERSION']),
                'estado': estado,
                'monto': format_money(p['MONTO_REFERENCIA']),
                'ejecutado': format_money(p['PRESUPUESTO_EJECUTADO']),
                'fisico': p['AVANCE_FISICO'] if pd.notna(p['AVANCE_FISICO']) else None,
                'general': p['AVANCE_EJECUCION'] if pd.notna(p['AVANCE_EJECUCION']) else None,
                'fecha_fisico': fec
            })
        proyectos_dict[u] = lista
        
    # Variables agregadas para inyectar al geojson JS
    distritos_data = {}
    for _, r in gdf_mapa.iterrows():
        u = r['ubigeo']
        distritos_data[u] = {
            'TOTAL_PROYECTOS': int(r['TOTAL_PROYECTOS']),
            'MONTO_FORMAT': r['MONTO_FORMAT'],
            'PCT_PROYECTOS': r['PCT_PROYECTOS'],
            'PCT_MONTO': r['PCT_MONTO'],
            'EJECUTADO_FORMAT': format_money(r['PRESUPUESTO_EJECUTADO_TOTAL']),
            'FISICO_PROM': f"{r['AVANCE_FISICO_PROM']:.1f}% ({int(r['AVANCE_FISICO_COUNT'])} proy.)" if pd.notna(r['AVANCE_FISICO_PROM']) else "Sin información",
            'EJECUCION_PROM': f"{r['AVANCE_EJECUCION_PROM']:.1f}% ({int(r['AVANCE_EJECUCION_COUNT'])} proy.)" if pd.notna(r['AVANCE_EJECUCION_PROM']) else "Sin información",
        }

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

    # Capa de Puntos Individuales
    points_layer = folium.FeatureGroup(name='Proyectos individuales', show=False)
    for idx, row in df.iterrows():
        lat = pd.to_numeric(row['LATITUD'], errors='coerce')
        lon = pd.to_numeric(row['LONGITUD'], errors='coerce')
        if pd.notna(lat) and pd.notna(lon) and lat != 0.0:
            ctype = row['TIPO_COORDENADA']
            color = 'green' if ctype == 'OFICIAL_ORIGINAL' else ('orange' if 'LOCALIDAD' in ctype else 'red')
            monto = row['MONTO_REFERENCIA']
            
            fec = str(row['ULT_FEC_DECLA_ESTIM'])
            if fec.lower() in ['nan', 'none', 'null', '']: fec = "Sin información"
            
            html_pt = f"""
            <div style="font-family: Arial; font-size:12px; width:320px; max-height:280px; overflow-y:auto;">
            <b>CUI:</b> {row['CODIGO_UNICO']}<br>
            <b>Inversión:</b> {row['NOMBRE_INVERSION']}<br><br>
            <b>Ubicación:</b> {row['DISTRITO']}, {row['PROVINCIA']}<br>
            <b>Monto Referencia:</b> {format_money(monto)}<br>
            <hr style="margin:5px 0;">
            <b>Presupuesto Ejecutado:</b> {format_money(row['PRESUPUESTO_EJECUTADO'])}<br>
            <b>Devengado Año Actual:</b> {format_money(row['PRESUPUESTO_EJECUTADO_ANIO_ACTUAL'])}<br>
            <b>Avance Físico:</b> {format_pct(row['AVANCE_FISICO'])}<br>
            <b>Avance General:</b> {format_pct(row['AVANCE_EJECUCION'])}<br>
            <b>Avance Financiero Calculado:</b> {format_pct(row['AVANCE_FINANCIERO_CALCULADO'])}<br>
            <b>Último reporte físico:</b> {fec}<br>
            <hr style="margin:5px 0;">
            <b>TIPO_COORDENADA:</b> <span style="color:{color};">{ctype}</span>
            </div>
            """
            folium.CircleMarker(
                location=[lat, lon], radius=4, color=color, fill=True, fillOpacity=0.8,
                popup=folium.Popup(html_pt, max_width=340)
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
    
    # Panel General superpuesto
    panel_html = f'''
    <div style="position: fixed; 
         top: 10px; left: 60px; width: 320px; 
         background-color: rgba(255, 255, 255, 0.95); border:2px solid grey; z-index:9999; font-size:12px; padding: 10px; font-family: Arial; max-height: 90vh; overflow-y: auto;">
         <h4 style="margin-top:0; font-size:14px; text-align:center;">Agua y Saneamiento (Puno)</h4>
         <hr style="margin:5px 0;">
         <b>Total de proyectos:</b> {TOTAL_PUNO_PROY}<br>
         <b>Inversión total referencial:</b> {format_money(TOTAL_PUNO_MONTO)}<br>
         <b>Presupuesto ejecutado acumulado:</b> {format_money(TOTAL_PUNO_EJECUTADO)}<br>
         <b>Avance financiero departamental:</b> {TOTAL_PUNO_AVANCE_FINAN:.1f}%<br>
         <b>Proy. con avance físico informado:</b> {COUNT_PUNO_FISICO}<br>
         <b>Proy. con avance general informado:</b> {COUNT_PUNO_EJECUCION}<br>
         <hr style="margin:5px 0;">
         <b>Top 5 por cantidad de proyectos:</b>
         <ol style="margin-top:5px; margin-bottom:5px; padding-left:25px;">{top_proy_html}</ol>
         <b>Top 5 por monto de inversión:</b>
         <ol style="margin-top:5px; margin-bottom:5px; padding-left:25px;">{top_monto_html}</ol>
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
        
        html += "<div style='display:flex; flex-wrap:wrap; gap:8px; margin-bottom: 10px;'>";
        html += "<div style='flex:1; min-width:45%; background:#fff; padding:8px; border-radius:5px; border:1px solid #eee;'><b>Total Proy.</b><br><span style='font-size:16px; color:#2980b9; font-weight:bold;'>" + (ddata.TOTAL_PROYECTOS || 0) + "</span></div>";
        html += "<div style='flex:1; min-width:45%; background:#fff; padding:8px; border-radius:5px; border:1px solid #eee;'><b>Inversión</b><br><span style='font-size:14px; color:#27ae60; font-weight:bold;'>" + (ddata.MONTO_FORMAT || 'S/ 0') + "</span></div>";
        html += "<div style='flex:1; min-width:100%; background:#fff; padding:8px; border-radius:5px; border:1px solid #eee;'><b>Ejecutado Acum.</b><br><span style='font-size:14px; color:#8e44ad; font-weight:bold;'>" + (ddata.EJECUTADO_FORMAT || 'S/ 0') + "</span></div>";
        html += "<div style='flex:1; min-width:45%; background:#fff; padding:8px; border-radius:5px; border:1px solid #eee;'><b>Físico Prom.</b><br><span style='font-size:12px; color:#d35400;'>" + (ddata.FISICO_PROM || '') + "</span></div>";
        html += "<div style='flex:1; min-width:45%; background:#fff; padding:8px; border-radius:5px; border:1px solid #eee;'><b>General Prom.</b><br><span style='font-size:12px; color:#d35400;'>" + (ddata.EJECUCION_PROM || '') + "</span></div>";
        html += "</div>";
        
        html += "<h3 style='margin-bottom:8px; color:#34495e; font-size: 14px;'>Lista de Proyectos (" + proys.length + ")</h3>";
        html += "<div style='display:flex; flex-direction:column; gap:10px;'>";
        
        for(var i=0; i<proys.length; i++) {
            var p = proys[i];
            html += "<div style='background: white; border: 1px solid #ddd; border-radius: 5px; padding: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>";
            html += "<div style='font-size: 10px; color: #7f8c8d; margin-bottom: 3px;'>CUI: " + p.cui + "</div>";
            html += "<div style='font-size: 12px; font-weight: bold; margin-bottom: 5px; color: #2c3e50; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;' title='" + p.nombre + "'>" + p.nombre + "</div>";
            html += "<div style='font-size: 11px; margin-bottom: 3px;'>Estado: <span style='color: blue; font-weight: bold;'>" + p.estado + "</span></div>";
            html += "<div style='font-size: 11px; margin-bottom: 3px;'>Monto: <b>" + p.monto + "</b></div>";
            html += "<div style='font-size: 11px; margin-bottom: 6px;'>Ejecutado: <span style='color:#8e44ad; font-weight:bold;'>" + p.ejecutado + "</span></div>";
            
            html += "<div style='font-size: 10px; color:#555;'>Avance Físico " + (p.fecha_fisico ? "(Rep: "+p.fecha_fisico+")" : "") + "</div>";
            html += createProgressBar(p.fisico);
            
            html += "<div style='font-size: 10px; color:#555; margin-top:5px;'>Avance General</div>";
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
    
    anomalias = pd.read_csv(AUDITORIA_AVANCES) if AUDITORIA_AVANCES.exists() else pd.DataFrame()
    
    print("\n=== REPORTE FINAL V4 ===")
    print(f"1. Total de proyectos: {len(df)}")
    print(f"2. Proyectos con presupuesto ejecutado disponible: {COUNT_EJEC_VALID}")
    print(f"3. Proyectos sin presupuesto ejecutado: {COUNT_EJEC_NULO}")
    print(f"4. Presupuesto ejecutado acumulado total: {format_money(TOTAL_PUNO_EJECUTADO)}")
    print(f"5. Devengado correspondiente al año actual: {format_money(TOTAL_DEV_ACTUAL)}")
    print(f"6. Proyectos con AVANCE_FISICO: {COUNT_PUNO_FISICO}")
    print(f"7. Proyectos sin AVANCE_FISICO: {COUNT_FISICO_NULO}")
    print(f"8. Proyectos con AVANCE_EJECUCION: {COUNT_PUNO_EJECUCION}")
    print(f"9. Proyectos sin AVANCE_EJECUCION: {COUNT_EJECUCION_NULO}")
    print(f"10. Promedio de AVANCE_FISICO (de los {COUNT_PUNO_FISICO} informados): {df['AVANCE_FISICO'].dropna().mean():.1f}%")
    print(f"11. Promedio de AVANCE_EJECUCION (de los {COUNT_PUNO_EJECUCION} informados): {df['AVANCE_EJECUCION'].dropna().mean():.1f}%")
    print(f"12. Casos anómalos detectados: {len(anomalias)}")
    print(f"13. ¿Uso Consulta Amigable? No (El dataset contenía info. en el 100% de proyectos).")
    print(f"14. ¿Endpoint oficial reutilizable encontrado? No fue necesario aplicarlo.")
    print(f"15. Ruta del CSV v4: {CSV_FILE.as_posix()}")
    print(f"16. Ruta del Excel v4: {str(CSV_FILE.with_suffix('.xlsx').as_posix())}")
    print(f"17. Ruta del HTML actualizado: {HTML_OUT.as_posix()}")

if __name__ == "__main__":
    main()
