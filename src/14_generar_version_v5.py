import pandas as pd
import numpy as np
from pathlib import Path

CSV_V4 = Path("outputs/proyectos_agua_saneamiento_puno_v4.csv")
CSV_V5 = Path("outputs/proyectos_agua_saneamiento_puno_v5.csv")
EXCEL_V5 = Path("outputs/proyectos_agua_saneamiento_puno_v5.xlsx")
AUDIT_VIGENCIA = Path("outputs/auditoria_vigencia_avance_fisico.csv")
DICCIONARIO_CSV = Path("data/raw/Detalle_Inversiones_Diccionario.csv")

FECHA_REFERENCIA = pd.to_datetime("2026-08-24")

dtypes = {
    'CODIGO_UNICO': str,
    'UBIGEO': str
}

def parse_num(val):
    if pd.isna(val) or str(val).strip().lower() in ['', 'nan', 'none', 'null']:
        return None
    try:
        return float(val)
    except:
        return None

def main():
    print("Iniciando generación de V5 (Auditoría Temporal)...")
    df = pd.read_csv(CSV_V4, dtype=dtypes, keep_default_na=False)
    
    # Pre-parse dates
    # ULT_FEC_DECLA_ESTIM could be empty or invalid string
    # We will convert it safely
    df['ULT_FEC_DECLA_ESTIM_DT'] = pd.to_datetime(df['ULT_FEC_DECLA_ESTIM'], errors='coerce')
    
    # 1. & 2. & 3. Columnas de Antigüedad
    df['ANTIGUEDAD_REPORTE_FISICO_DIAS'] = (FECHA_REFERENCIA - df['ULT_FEC_DECLA_ESTIM_DT']).dt.days
    df['ANTIGUEDAD_REPORTE_FISICO_ANIOS'] = (df['ANTIGUEDAD_REPORTE_FISICO_DIAS'] / 365.25).round(1)
    
    for idx, row in df.iterrows():
        # Clean nulls for output
        if pd.isna(row['ANTIGUEDAD_REPORTE_FISICO_DIAS']):
            df.at[idx, 'ANTIGUEDAD_REPORTE_FISICO_DIAS'] = ''
            df.at[idx, 'ANTIGUEDAD_REPORTE_FISICO_ANIOS'] = ''
            
        av_fis = row['AVANCE_FISICO']
        tiene_avance = pd.notna(av_fis) and str(av_fis).strip().lower() not in ['', 'nan', 'none', 'null']
        tiene_fecha = pd.notna(row['ULT_FEC_DECLA_ESTIM_DT'])
        
        # 5. ESTADO_ACTUALIZACION_FISICA
        if tiene_avance:
            if tiene_fecha:
                dias = row['ANTIGUEDAD_REPORTE_FISICO_DIAS']
                if dias <= 180:
                    estado = 'ACTUALIZADO'
                    adv = ''
                elif dias <= 365:
                    estado = 'VIGENTE_CON_RETRASO'
                    adv = 'Reporte físico con más de 6 meses de antigüedad'
                else:
                    estado = 'DESACTUALIZADO'
                    adv = 'Reporte físico desactualizado'
            else:
                estado = 'SIN_FECHA_REPORTE'
                adv = 'Avance físico sin fecha de reporte disponible'
        else:
            estado = 'SIN_AVANCE_FISICO'
            adv = 'Sin avance físico registrado'
            
        df.at[idx, 'ESTADO_ACTUALIZACION_FISICA'] = estado
        df.at[idx, 'ADVERTENCIA_AVANCE_FISICO'] = adv
        
    df = df.drop(columns=['ULT_FEC_DECLA_ESTIM_DT'])
    
    assert len(df) == 761, "El total de filas debe ser 761"
    assert df['CODIGO_UNICO'].nunique() == 761, "Los CUIs deben ser únicos"
    
    df.to_csv(CSV_V5, index=False)
    
    # 8. Auditoría proyectos ACTIVO con avance antiguo
    df_activos_desact = df[(df['ESTADO'] == 'ACTIVO') & (df['ESTADO_ACTUALIZACION_FISICA'] == 'DESACTUALIZADO')].copy()
    
    cols_audit = [
        'CODIGO_UNICO', 'NOMBRE_INVERSION', 'PROVINCIA', 'DISTRITO', 'ESTADO', 'SITUACION',
        'AVANCE_FISICO', 'AVANCE_EJECUCION', 'ULT_FEC_DECLA_ESTIM', 
        'ANTIGUEDAD_REPORTE_FISICO_DIAS', 'ANTIGUEDAD_REPORTE_FISICO_ANIOS',
        'TIENE_F12B', 'TIENE_AVAN_FISICO', 'PRESUPUESTO_EJECUTADO', 'COSTO_ACTUALIZADO',
        'ADVERTENCIA_AVANCE_FISICO'
    ]
    # To sort from oldest to newest report, sort by DIAS descending (oldest is higher days)
    df_activos_desact['DIAS_NUM'] = pd.to_numeric(df_activos_desact['ANTIGUEDAD_REPORTE_FISICO_DIAS'], errors='coerce')
    df_activos_desact = df_activos_desact.sort_values(by='DIAS_NUM', ascending=False)
    df_activos_desact[cols_audit].to_csv(AUDIT_VIGENCIA, index=False)
    
    # Generar Excel V5
    from openpyxl.styles import Font
    print(f"Generando Excel {EXCEL_V5.name}...")
    with pd.ExcelWriter(EXCEL_V5, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='PROYECTOS', index=False)
        
        # Resumen
        resumen_data = [['Métrica', 'Valor'], ['Total de proyectos', len(df)], ['Total de CUIs únicos', df['CODIGO_UNICO'].nunique()]]
        def add_grouping(d, column):
            resumen_data.append(['', ''])
            resumen_data.append([f'Proyectos por {column}', 'Cantidad'])
            counts = d[column].value_counts()
            for k, v in counts.items():
                resumen_data.append([k, v])
                
        add_grouping(df, 'ESTADO_ACTUALIZACION_FISICA')
        add_grouping(df, 'ESTADO')
        add_grouping(df, 'SITUACION')
        
        df_res = pd.DataFrame(resumen_data[1:], columns=resumen_data[0])
        df_res.to_excel(writer, sheet_name='RESUMEN', index=False, header=False)
        
        df_activos_desact[cols_audit].to_excel(writer, sheet_name='AUDIT_VIG_FISICO_ACTIVOS', index=False)
        
        # Diccionario
        dicc_data = []
        if DICCIONARIO_CSV.exists():
            try:
                df_dic = pd.read_csv(DICCIONARIO_CSV, keep_default_na=False)
                dicc_data = df_dic.values.tolist()
            except: pass
            
        nuevos_campos = [
            ["PRESUPUESTO_EJECUTADO", "Devengado acumulado de la inversión hasta la fecha (suma de DEVEN_ACUMUL_ANIO_ANT + DEV_ANIO_ACTUAL)."],
            ["PRESUPUESTO_EJECUTADO_ANIO_ACTUAL", "Ejecución financiera correspondiente únicamente al año actual (DEV_ANIO_ACTUAL)."],
            ["FUENTE_PRESUPUESTO_EJECUTADO", "Origen de la información financiera utilizada."],
            ["FECHA_REFERENCIA_EJECUCION", "Fecha o año de referencia para la ejecución financiera del registro."],
            ["AVANCE_FINANCIERO_CALCULADO", "Indicador derivado (PRESUPUESTO_EJECUTADO / COSTO_ACTUALIZADO * 100). No reemplaza el AVANCE_EJECUCION oficial."],
            ["AVANCE_FISICO", "Avance Físico (%) reportado oficialmente."],
            ["AVANCE_EJECUCION", "Avance General de Ejecución (%) reportado oficialmente."],
            ["ULT_FEC_DECLA_ESTIM", "Fecha del último reporte de avance físico, si existe."],
            ["ANTIGUEDAD_REPORTE_FISICO_DIAS", "Días transcurridos entre ULT_FEC_DECLA_ESTIM y 2026-08-24."],
            ["ANTIGUEDAD_REPORTE_FISICO_ANIOS", "Años transcurridos entre ULT_FEC_DECLA_ESTIM y 2026-08-24."],
            ["ESTADO_ACTUALIZACION_FISICA", "Categoría de vigencia del reporte de avance físico."],
            ["ADVERTENCIA_AVANCE_FISICO", "Etiqueta visual de alerta si el reporte físico tiene retraso o está desactualizado."]
        ]
        
        existing_cols = [x[0] for x in dicc_data]
        final_campos = []
        for x in nuevos_campos:
            if x[0] not in existing_cols:
                final_campos.append(x)
                
        dicc_final = final_campos + dicc_data
        df_dic_out = pd.DataFrame(dicc_final, columns=['COLUMNA', 'DESCRIPCION'])
        df_dic_out.to_excel(writer, sheet_name='DICCIONARIO', index=False)
        
        for ws_name in writer.sheets:
            ws = writer.sheets[ws_name]
            if ws_name in ['PROYECTOS', 'AUDIT_VIG_FISICO_ACTIVOS']:
                ws.auto_filter.ref = ws.dimensions
                ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
                
            if ws_name == 'DICCIONARIO':
                ws.column_dimensions['A'].width = 30
                ws.column_dimensions['B'].width = 100

    print("Generación de V5 completada.")
    
    # 7. & 17. Reporte estadístico
    tiene_fis = df[df['ESTADO_ACTUALIZACION_FISICA'] != 'SIN_AVANCE_FISICO']
    sin_fis = df[df['ESTADO_ACTUALIZACION_FISICA'] == 'SIN_AVANCE_FISICO']
    
    tiene_fec = df[pd.to_numeric(df['ANTIGUEDAD_REPORTE_FISICO_DIAS'], errors='coerce').notna()]
    sin_fec = tiene_fis[pd.to_numeric(tiene_fis['ANTIGUEDAD_REPORTE_FISICO_DIAS'], errors='coerce').isna()]
    
    c_act = (df['ESTADO_ACTUALIZACION_FISICA'] == 'ACTUALIZADO').sum()
    c_vig = (df['ESTADO_ACTUALIZACION_FISICA'] == 'VIGENTE_CON_RETRASO').sum()
    c_des = (df['ESTADO_ACTUALIZACION_FISICA'] == 'DESACTUALIZADO').sum()
    c_sfr = (df['ESTADO_ACTUALIZACION_FISICA'] == 'SIN_FECHA_REPORTE').sum()
    c_saf = (df['ESTADO_ACTUALIZACION_FISICA'] == 'SIN_AVANCE_FISICO').sum()
    
    df['DIAS_NUM'] = pd.to_numeric(df['ANTIGUEDAD_REPORTE_FISICO_DIAS'], errors='coerce')
    fechas_validas = pd.to_datetime(df['ULT_FEC_DECLA_ESTIM'], errors='coerce').dropna()
    f_rec = fechas_validas.max().strftime('%Y-%m-%d') if not fechas_validas.empty else "N/A"
    f_ant = fechas_validas.min().strftime('%Y-%m-%d') if not fechas_validas.empty else "N/A"
    
    mediana = df['DIAS_NUM'].median()
    promedio = df['DIAS_NUM'].mean()
    
    m_1 = (df['DIAS_NUM'] > 365).sum()
    m_2 = (df['DIAS_NUM'] > 730).sum()
    m_3 = (df['DIAS_NUM'] > 1095).sum()
    m_4 = (df['DIAS_NUM'] > 1460).sum()
    
    print(f"\n--- REPORTE DE VIGENCIA TEMPORAL (21 puntos) ---")
    print(f"1. Total de proyectos: {len(df)}")
    print(f"2. Proyectos con AVANCE_FISICO: {len(tiene_fis)}")
    print(f"3. Proyectos sin AVANCE_FISICO: {len(sin_fis)}")
    print(f"4. Proyectos con fecha válida de último reporte: {len(tiene_fec)}")
    print(f"5. ACTUALIZADO: {c_act}")
    print(f"6. VIGENTE_CON_RETRASO: {c_vig}")
    print(f"7. DESACTUALIZADO: {c_des}")
    print(f"8. SIN_FECHA_REPORTE: {c_sfr}")
    print(f"9. SIN_AVANCE_FISICO: {c_saf}")
    print(f"10. Fecha más reciente de reporte: {f_rec}")
    print(f"11. Fecha más antigua: {f_ant}")
    print(f"12. Mediana de antigüedad en días: {mediana:.0f} (Promedio: {promedio:.1f})")
    print(f"13. Proyectos con más de 1 año sin actualizar: {m_1}")
    print(f"14. Más de 2 años: {m_2}")
    print(f"15. Más de 3 años: {m_3}")
    print(f"16. Más de 4 años: {m_4}")
    
    # Validar CUI 2309673
    cui_val = df[df['CODIGO_UNICO'] == '2309673'].iloc[0]
    print(f"\n17. Resultado específico del CUI 2309673:")
    print(f"   - AVANCE_FISICO: {cui_val['AVANCE_FISICO']}")
    print(f"   - AVANCE_EJECUCION: {cui_val['AVANCE_EJECUCION']}")
    print(f"   - ULT_FEC_DECLA_ESTIM: {cui_val['ULT_FEC_DECLA_ESTIM']}")
    print(f"   - ANTIGUEDAD_REPORTE_FISICO_DIAS: {cui_val['ANTIGUEDAD_REPORTE_FISICO_DIAS']}")
    print(f"   - ANTIGUEDAD_REPORTE_FISICO_ANIOS: {cui_val['ANTIGUEDAD_REPORTE_FISICO_ANIOS']}")
    print(f"   - ESTADO_ACTUALIZACION_FISICA: {cui_val['ESTADO_ACTUALIZACION_FISICA']}")
    print(f"   - ADVERTENCIA_AVANCE_FISICO: {cui_val['ADVERTENCIA_AVANCE_FISICO']}")
    
    print(f"\n18. Ruta auditoria_vigencia: {AUDIT_VIGENCIA.as_posix()}")
    print(f"19. Ruta CSV v5: {CSV_V5.as_posix()}")
    print(f"20. Ruta Excel v5: {EXCEL_V5.as_posix()}")

if __name__ == "__main__":
    main()
