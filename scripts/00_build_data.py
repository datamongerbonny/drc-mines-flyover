"""
Build drc_mines_flyover.gpkg from data/drc_mines.csv (runs OUTSIDE QGIS, plain Python).

Layers written (all EPSG:3857 except mines_wgs84):
  mines_wgs84   - mine points, lon/lat
  mines         - mine points, Web Mercator (same CRS as satellite XYZ tiles)
  route         - one LineString through the mines in tour_order
  dem_clip      - 20 km buffers around mines: download/clip DEM only here

Re-run after editing the CSV (re-order tour_order, add mines, fix coords):
    pip install geopandas shapely pyproj pyogrio
    python scripts/00_build_data.py
"""
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
csv = ROOT / "data" / "drc_mines.csv"
out = ROOT / "data" / "drc_mines_flyover.gpkg"

df = pd.read_csv(csv).sort_values("tour_order")
mines = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326)
m3857 = mines.to_crs(3857)

route = LineString(list(m3857.geometry.apply(lambda p: (p.x, p.y))))
route_gdf = gpd.GeoDataFrame({"name": ["DRC mines tour"], "length_km": [route.length / 1000]},
                             geometry=[route], crs=3857)

clip = m3857[["tour_order", "name"]].copy()
clip["geometry"] = m3857.geometry.buffer(20_000)
clip = gpd.GeoDataFrame(clip, geometry="geometry", crs=3857)

if out.exists():
    out.unlink()
mines.to_file(out, layer="mines_wgs84", driver="GPKG")
m3857.to_file(out, layer="mines", driver="GPKG")
route_gdf.to_file(out, layer="route", driver="GPKG")
clip.to_file(out, layer="dem_clip", driver="GPKG")
print(f"Wrote {out}  route length = {route.length/1000:,.0f} km (Web Mercator)")
