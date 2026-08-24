import pandas as pd
from pathlib import Path
from openpyxl.styles import Font
import os

csv_principal = Path("outputs/proyectos_agua_saneamiento_puno.csv")
csv_revision = Path("outputs/revision_manual.csv")
excel_out = Path("outputs/proyectos_agua_saneamiento_puno.xlsx")

# Tipos forzados para evitar alteraciones en texto
dtypes = {
    'CODIGO_UNICO': str,
    'CODIGO_SNIP': str,
    'UBIGEO': str,
    'SEC_EJEC': str,
    'UBIGEO_SNIP': str
}

print("Leyendo CSVs...")
df_proyectos = pd.read_csv(csv_principal, dtype=dtypes, keep_default_na=False)
df_rev = pd.read_csv(csv_revision, dtype=dtypes, keep_default_na=False)

print(f"Creando {excel_out.name}...")
with pd.ExcelWriter(excel_out, engine='openpyxl') as writer:
    # --- HOJA 1: PROYECTOS ---
    df_proyectos.to_excel(writer, sheet_name='PROYECTOS', index=False)
    ws_proyectos = writer.sheets['PROYECTOS']
    ws_proyectos.auto_filter.ref = ws_proyectos.dimensions
    ws_proyectos.freeze_panes = "A2"
    
    for cell in ws_proyectos[1]:
        cell.font = Font(bold=True)
        
    for col in ws_proyectos.columns:
        max_length = 0
        column_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                length = len(str(cell.value))
                if length > max_length:
                    max_length = length
        adjusted_width = min((max_length + 2), 50)
        ws_proyectos.column_dimensions[column_letter].width = adjusted_width

    # --- HOJA 2: RESUMEN ---
    resumen_data = []
    resumen_data.append(['Métrica', 'Valor'])
    resumen_data.append(['Total de proyectos', len(df_proyectos)])
    resumen_data.append(['Total de CUIs únicos', df_proyectos['CODIGO_UNICO'].nunique()])
    
    def add_grouping(df, column):
        resumen_data.append(['', ''])
        resumen_data.append([f'Proyectos por {column}', 'Cantidad'])
        counts = df[column].value_counts()
        for k, v in counts.items():
            resumen_data.append([k, v])
            
    add_grouping(df_proyectos, 'ORIGEN_CLASIFICACION')
    add_grouping(df_proyectos, 'PROVINCIA')
    add_grouping(df_proyectos, 'SUBPROGRAMA')
    add_grouping(df_proyectos, 'ESTADO')
    add_grouping(df_proyectos, 'SITUACION')
    add_grouping(df_proyectos, 'ETAPA_F8')
    
    df_resumen = pd.DataFrame(resumen_data[1:], columns=resumen_data[0])
    df_resumen.to_excel(writer, sheet_name='RESUMEN', index=False, header=False)
    
    ws_resumen = writer.sheets['RESUMEN']
    for cell in ws_resumen['A']:
        if cell.value and str(cell.value).startswith('Proyectos por'):
            cell.font = Font(bold=True)
    ws_resumen.column_dimensions['A'].width = 40
    ws_resumen.column_dimensions['B'].width = 15

    # --- HOJA 3: REVISION_MANUAL ---
    df_rev.to_excel(writer, sheet_name='REVISION_MANUAL', index=False)
    ws_rev = writer.sheets['REVISION_MANUAL']
    ws_rev.auto_filter.ref = ws_rev.dimensions
    ws_rev.freeze_panes = "A2"
    for cell in ws_rev[1]:
        cell.font = Font(bold=True)

    # --- HOJA 4: DICCIONARIO ---
    diccionario_data = []
    dicc_csv = Path("data/raw/Detalle_Inversiones_Diccionario.csv")
    if dicc_csv.exists():
        try:
            df_dic = pd.read_csv(dicc_csv, keep_default_na=False)
            diccionario_data = df_dic.values.tolist()
        except:
            pass
    
    nuevos_campos = [
        ["ORIGEN_CLASIFICACION", "Origen utilizado para determinar por qué el proyecto forma parte del universo consolidado."],
        ["CRITERIO_INCLUSION", "Justificación breve de la inclusión del proyecto en la base consolidada."]
    ]
    
    if not diccionario_data:
        diccionario_data = nuevos_campos
    else:
        diccionario_data = nuevos_campos + diccionario_data
        
    df_dic_out = pd.DataFrame(diccionario_data, columns=['COLUMNA', 'DESCRIPCION'])
    df_dic_out.to_excel(writer, sheet_name='DICCIONARIO', index=False)
    ws_dic = writer.sheets['DICCIONARIO']
    ws_dic.column_dimensions['A'].width = 30
    ws_dic.column_dimensions['B'].width = 100
    for cell in ws_dic[1]:
        cell.font = Font(bold=True)

print("Excel guardado exitosamente.\n")

# --- VALIDACIONES FINALES ---
print("=== VALIDACIONES ===")
cuis_unicos = df_proyectos['CODIGO_UNICO'].nunique()
filas = len(df_proyectos)
duplicados = filas - cuis_unicos
todo_puno = all(str(x).upper().strip() == 'PUNO' for x in df_proyectos['DEPARTAMENTO'])
rev_filas = len(df_rev)
overlap = set(df_proyectos['CODIGO_UNICO']).intersection(set(df_rev['CODIGO_UNICO']))

print(f"Ruta Excel: {excel_out.as_posix()}")
print(f"Tamaño del archivo: {excel_out.stat().st_size / (1024 * 1024):.2f} MB")
print(f"Número de hojas: 4 (PROYECTOS, RESUMEN, REVISION_MANUAL, DICCIONARIO)")
print(f"Registros en PROYECTOS: {filas} (Esperado: 761)")
print(f"CUIs únicos en PROYECTOS: {cuis_unicos} (Esperado: 761)")
print(f"Duplicados CUI: {duplicados} (Esperado: 0)")
print(f"Todos los proyectos pertenecen a PUNO: {todo_puno} (Esperado: True)")
print(f"Registros en REVISION_MANUAL: {rev_filas} (Esperado: 15)")
print(f"Proyectos de REVISION_MANUAL no presentes en PROYECTOS: {len(overlap) == 0} (Superposición: {len(overlap)})")

if filas == 761 and cuis_unicos == 761 and duplicados == 0 and todo_puno and rev_filas == 15 and len(overlap) == 0:
    print("\n¡Todas las validaciones fueron exitosas!")
else:
    print("\nADVERTENCIA: Alguna validación falló.")
