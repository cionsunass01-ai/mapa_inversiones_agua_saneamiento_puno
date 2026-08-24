import pandas as pd
import numpy as np
from pathlib import Path

CSV_V3 = Path("outputs/proyectos_agua_saneamiento_puno_v3.csv")
RAW_CSV = Path("data/raw/DETALLE_INVERSIONES.csv")
CSV_V4 = Path("outputs/proyectos_agua_saneamiento_puno_v4.csv")
EXCEL_V4 = Path("outputs/proyectos_agua_saneamiento_puno_v4.xlsx")
AUDITORIA_AVANCES = Path("outputs/auditoria_avances.csv")
CSV_REV_MANUAL = Path("outputs/revision_manual.csv")
DICCIONARIO_CSV = Path("data/raw/Detalle_Inversiones_Diccionario.csv")

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
    print("Iniciando generación de V4...")
    df = pd.read_csv(CSV_V3, dtype=dtypes, keep_default_na=False)
    
    anomalias = []
    
    for idx, row in df.iterrows():
        cui = row['CODIGO_UNICO']
        
        dev_ant = parse_num(row['DEVEN_ACUMUL_ANIO_ANT'])
        dev_act = parse_num(row['DEV_ANIO_ACTUAL'])
        
        # 1. PRESUPUESTO_EJECUTADO
        if dev_ant is not None and dev_act is not None:
            ejec = round(dev_ant + dev_act, 2)
            df.at[idx, 'PRESUPUESTO_EJECUTADO'] = ejec
            df.at[idx, 'PRESUPUESTO_EJECUTADO_ANIO_ACTUAL'] = round(dev_act, 2)
            df.at[idx, 'FUENTE_PRESUPUESTO_EJECUTADO'] = 'MEF_BANCO_INVERSIONES_DEVENGADO'
            
            costo = parse_num(row['COSTO_ACTUALIZADO'])
            finan = round((ejec / costo) * 100, 2) if costo is not None and costo > 0 else None
            if finan is not None:
                df.at[idx, 'AVANCE_FINANCIERO_CALCULADO'] = finan
                
            def add_anomaly(tipo, val, obs=""):
                anomalias.append({
                    'CODIGO_UNICO': cui, 
                    'NOMBRE_INVERSION': row['NOMBRE_INVERSION'], 
                    'TIPO_ANOMALIA': tipo, 
                    'VALOR': val,
                    'COSTO_ACTUALIZADO': costo,
                    'PRESUPUESTO_EJECUTADO': ejec,
                    'AVANCE_FINANCIERO_CALCULADO': finan,
                    'AVANCE_FISICO': row['AVANCE_FISICO'],
                    'AVANCE_EJECUCION': row['AVANCE_EJECUCION'],
                    'OBSERVACION': obs
                })
                
            if ejec < 0:
                add_anomaly('Presupuesto ejecutado negativo', ejec)
                
            if finan is not None:
                if finan > 100.0:
                    add_anomaly('Avance financiero > 100%', finan)
                if ejec > costo:
                    add_anomaly('Ejecutado mayor al costo actualizado', ejec, "Diferencia: {:.2f}".format(ejec - costo))
        else:
            df.at[idx, 'PRESUPUESTO_EJECUTADO'] = ''
            df.at[idx, 'PRESUPUESTO_EJECUTADO_ANIO_ACTUAL'] = ''
            df.at[idx, 'FUENTE_PRESUPUESTO_EJECUTADO'] = ''
            df.at[idx, 'AVANCE_FINANCIERO_CALCULADO'] = ''
            anomalias.append({
                'CODIGO_UNICO': cui, 'NOMBRE_INVERSION': row['NOMBRE_INVERSION'], 
                'TIPO_ANOMALIA': 'Texto inválido o faltante en devengados', 'VALOR': f"{row['DEVEN_ACUMUL_ANIO_ANT']} | {row['DEV_ANIO_ACTUAL']}",
                'COSTO_ACTUALIZADO': parse_num(row['COSTO_ACTUALIZADO']), 'PRESUPUESTO_EJECUTADO': None, 'AVANCE_FINANCIERO_CALCULADO': None,
                'AVANCE_FISICO': row['AVANCE_FISICO'], 'AVANCE_EJECUCION': row['AVANCE_EJECUCION'], 'OBSERVACION': ""
            })
        
        # 2. FECHA_REFERENCIA_EJECUCION
        anio_proc = str(row['ANIO_PROCESO']).strip()
        if anio_proc and anio_proc.lower() not in ['nan', 'none', 'null', '']:
            df.at[idx, 'FECHA_REFERENCIA_EJECUCION'] = anio_proc
        else:
            df.at[idx, 'FECHA_REFERENCIA_EJECUCION'] = 'NO DISPONIBLE A NIVEL DE REGISTRO'
            
        # 3. AVANCE_FISICO y AVANCE_EJECUCION
        av_fis = parse_num(row['AVANCE_FISICO'])
        av_ejec = parse_num(row['AVANCE_EJECUCION'])
        
        if av_fis is not None:
            if av_fis < 0 or av_fis > 100:
                anomalias.append({'CODIGO_UNICO': cui, 'NOMBRE_INVERSION': row['NOMBRE_INVERSION'], 'TIPO_ANOMALIA': 'Avance físico fuera de rango', 'VALOR': av_fis, 'COSTO_ACTUALIZADO': parse_num(row['COSTO_ACTUALIZADO']), 'PRESUPUESTO_EJECUTADO': df.at[idx, 'PRESUPUESTO_EJECUTADO'], 'AVANCE_FINANCIERO_CALCULADO': df.at[idx, 'AVANCE_FINANCIERO_CALCULADO'], 'AVANCE_FISICO': av_fis, 'AVANCE_EJECUCION': av_ejec, 'OBSERVACION': ""})
            df.at[idx, 'AVANCE_FISICO'] = av_fis
        else:
            df.at[idx, 'AVANCE_FISICO'] = ''
            
        if av_ejec is not None:
            if av_ejec < 0 or av_ejec > 100:
                anomalias.append({'CODIGO_UNICO': cui, 'NOMBRE_INVERSION': row['NOMBRE_INVERSION'], 'TIPO_ANOMALIA': 'Avance ejecución fuera de rango', 'VALOR': av_ejec, 'COSTO_ACTUALIZADO': parse_num(row['COSTO_ACTUALIZADO']), 'PRESUPUESTO_EJECUTADO': df.at[idx, 'PRESUPUESTO_EJECUTADO'], 'AVANCE_FINANCIERO_CALCULADO': df.at[idx, 'AVANCE_FINANCIERO_CALCULADO'], 'AVANCE_FISICO': av_fis, 'AVANCE_EJECUCION': av_ejec, 'OBSERVACION': ""})
            df.at[idx, 'AVANCE_EJECUCION'] = av_ejec
        else:
            df.at[idx, 'AVANCE_EJECUCION'] = ''
            
        ult_fec = str(row['ULT_FEC_DECLA_ESTIM']).strip()
        if ult_fec and ult_fec.lower() not in ['nan', 'none', 'null', '']:
            df.at[idx, 'ULT_FEC_DECLA_ESTIM'] = ult_fec
        else:
            df.at[idx, 'ULT_FEC_DECLA_ESTIM'] = ''

    # Limpiar columnas temporales de cruce (solo mantenemos AVANCE_FISICO, AVANCE_EJECUCION, ULT_FEC_DECLA_ESTIM)
    # DEVEN_ACUMUL_ANIO_ANT, DEV_ANIO_ACTUAL, ANIO_PROCESO se pueden quedar como referencia.
    
    # Validaciones Finales
    assert len(df) == 761, "El total de filas debe ser 761"
    assert df['CODIGO_UNICO'].nunique() == 761, "Los CUIs deben ser únicos"
    
    # Exportar Anomalías
    df_anomalias = pd.DataFrame(anomalias)
    df_anomalias.to_csv(AUDITORIA_AVANCES, index=False)
    
    # Guardar CSV V4
    df.to_csv(CSV_V4, index=False)
    
    # Guardar Excel V4
    from openpyxl.styles import Font
    print(f"Generando Excel {EXCEL_V4.name}...")
    with pd.ExcelWriter(EXCEL_V4, engine='openpyxl') as writer:
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
        if CSV_REV_MANUAL.exists():
            df_rev = pd.read_csv(CSV_REV_MANUAL, dtype=dtypes, keep_default_na=False)
            df_rev.to_excel(writer, sheet_name='REVISION_MANUAL', index=False)
        
        # Auditoria Coordenadas
        AUD_COORD = Path("outputs/auditoria_coordenadas.csv")
        if AUD_COORD.exists():
            df_aud_coord = pd.read_csv(AUD_COORD, keep_default_na=False)
            df_aud_coord.to_excel(writer, sheet_name='AUDITORIA_COORDENADAS', index=False)
            
        # Auditoria Avances
        df_anomalias.to_excel(writer, sheet_name='AUDITORIA_AVANCES', index=False)
        
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
            ["ULT_FEC_DECLA_ESTIM", "Fecha del último reporte de avance físico, si existe."]
        ]
        
        # append only if not already in dicc
        existing_cols = [x[0] for x in dicc_data]
        final_campos = []
        for x in nuevos_campos:
            if x[0] not in existing_cols:
                final_campos.append(x)
                
        dicc_final = final_campos + dicc_data
        df_dic_out = pd.DataFrame(dicc_final, columns=['COLUMNA', 'DESCRIPCION'])
        df_dic_out.to_excel(writer, sheet_name='DICCIONARIO', index=False)
        
        # Styling
        for ws_name in writer.sheets:
            ws = writer.sheets[ws_name]
            if ws_name in ['PROYECTOS', 'REVISION_MANUAL', 'AUDITORIA_COORDENADAS', 'AUDITORIA_AVANCES']:
                ws.auto_filter.ref = ws.dimensions
                ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
                
            if ws_name == 'DICCIONARIO':
                ws.column_dimensions['A'].width = 30
                ws.column_dimensions['B'].width = 100

    print("Generación de V4 completada.")
    
if __name__ == "__main__":
    main()
