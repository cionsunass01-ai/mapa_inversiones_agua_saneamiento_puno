import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, MultiPoint
from shapely.ops import voronoi_diagram
from pathlib import Path

EXCEL_HORARIO = Path("/Users/pierotarazona/Downloads/Puno_P_C/Horario Puno.xlsx")
EPS_SHP = Path("/Users/pierotarazona/Downloads/Rodrigo_Puno y Arequipa/EPS_Puno.shp")

df_horario = pd.read_excel(EXCEL_HORARIO)
agg_horario = df_horario.groupby(['nombre', 'latitud', 'longitud'], dropna=False).agg(
    HorasPrometidasSemana=('ServicioPrometido', 'sum')
).reset_index()

points = [Point(xy) for xy in zip(agg_horario['longitud'], agg_horario['latitud']) if not pd.isna(xy[0])]
mp = MultiPoint(points)

# eps polygon
gdf_eps = gpd.read_file(EPS_SHP)
if gdf_eps.crs.to_epsg() != 4326:
    gdf_eps = gdf_eps.to_crs(epsg=4326)
eps_union = gdf_eps.unary_union

# voronoi
regions = voronoi_diagram(mp, envelope=eps_union)
for p in regions.geoms:
    clipped = p.intersection(eps_union)
    if not clipped.is_empty:
        print("Clipped region area:", clipped.area)
