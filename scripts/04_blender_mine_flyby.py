"""
Blender + BlenderGIS: cinematic descent and orbit over one mine
================================================================
Requirements: Blender 3.6+/4.x with the BlenderGIS add-on
(https://github.com/domlysz/BlenderGIS).

Per mine:
  1. New file. GIS > Georeferencing: set scene CRS to EPSG:3857 (Web Mercator).
  2. GIS > Web geodata > Basemap: source Google > Satellite, zoom
     around the mine (use the coords in data/drc_mines.csv; 'G' key to go to
     a location), press E to export the area to a textured plane.
  3. With the plane selected: GIS > Web geodata > Get elevation (SRTM or
     OpenTopography Copernicus 30 m) -> the plane becomes 3D terrain.
     Optional: Displace modifier strength 1.5-2 for vertical exaggeration.
  4. Scripting tab > open this file > set MINE > Run Script.
  5. Render > Render Animation (Eevee is fast; Cycles for final quality).

The script creates an empty on the mine (snapped to the terrain), a camera that
descends from high altitude and then orbits once while tracking the mine,
a sun, and sets frame range + output path.
"""
import bpy, csv, math
from mathutils import Vector

CSV_PATH = bpy.path.abspath("//../data/drc_mines.csv")   # or an absolute path
MINE = "Kamoa-Kakula"
FPS = 25
DESCENT_S, ORBIT_S = 5, 14
START_ALT_M, ORBIT_ALT_M = 25_000, 3_500   # height above the mine
START_DIST_M, ORBIT_RADIUS_M = 20_000, 5_000
OUTPUT = "//renders/{mine}/frame_"


def to_3857(lon, lat):
    R = 6378137.0
    return (math.radians(lon) * R,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R)


def main():
    scn = bpy.context.scene
    if "crs x" not in scn:
        raise RuntimeError("Scene is not georeferenced - import a basemap with BlenderGIS first")
    if scn.get("crs") not in ("EPSG:3857", "3857"):
        print("WARNING: scene CRS is", scn.get("crs"), "- this script assumes EPSG:3857")

    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        row = next(r for r in csv.DictReader(fh) if r["name"] == MINE)
    x, y = to_3857(float(row["lon"]), float(row["lat"]))
    lx, ly = x - scn["crs x"], y - scn["crs y"]

    # ground height under the mine
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, *_ = scn.ray_cast(dg, Vector((lx, ly, 20_000)), Vector((0, 0, -1)))
    gz = loc.z if hit else 0.0

    for name in ("MineTarget", "FlyCam", "FlySun"):
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

    target = bpy.data.objects.new("MineTarget", None)
    target.location = (lx, ly, gz)
    scn.collection.objects.link(target)

    cam_data = bpy.data.cameras.new("FlyCam")
    cam_data.lens = 24
    cam_data.clip_start, cam_data.clip_end = 10, 200_000
    cam = bpy.data.objects.new("FlyCam", cam_data)
    scn.collection.objects.link(cam)
    scn.camera = cam
    c = cam.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"

    sun = bpy.data.objects.new("FlySun", bpy.data.lights.new("FlySun", "SUN"))
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(50), 0, math.radians(135))
    scn.collection.objects.link(sun)

    # keyframes: descent from the north, then one orbit
    f_desc, f_orb = int(DESCENT_S * FPS), int(ORBIT_S * FPS)
    def place(frame, ang, radius, alt):
        cam.location = (lx + radius * math.sin(ang), ly + radius * math.cos(ang), gz + alt)
        cam.keyframe_insert("location", frame=frame)
    place(1, 0, START_DIST_M, START_ALT_M)
    place(f_desc, 0, ORBIT_RADIUS_M, ORBIT_ALT_M)
    steps = 24
    for i in range(1, steps + 1):
        place(f_desc + round(f_orb * i / steps), 2 * math.pi * i / steps,
              ORBIT_RADIUS_M, ORBIT_ALT_M)
    for fc in cam.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"

    scn.render.fps = FPS
    scn.frame_start, scn.frame_end = 1, f_desc + f_orb
    scn.render.resolution_x, scn.render.resolution_y = 1920, 1080
    scn.render.filepath = OUTPUT.format(mine=MINE.replace(" ", "_").replace("/", "-"))
    print(f"Ready: {MINE} at local ({lx:.0f}, {ly:.0f}, {gz:.0f}); "
          f"{scn.frame_end} frames. Render > Render Animation.")


main()
