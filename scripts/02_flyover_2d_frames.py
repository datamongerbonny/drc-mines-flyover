"""
DRC MINES FLY-OVER  -  aerial "helicopter" tour rendered from QGIS
====================================================================
Run from the QGIS Python Console (Plugins > Python Console > Show Editor > open > Run).

What it does
  * Uses the CHAINAGE points you created on the `route` line (Chainage plugin)
    as the flight track.
  * Builds a camera timeline: hover low over each mine (slow descent + turn),
    then climb / cruise / descend to the next mine with eased speed.
  * Renders one PNG per frame (heading-up, satellite basemap, labels),
    then prints the ffmpeg command that turns the frames into an MP4.

Before running
  1. Load data/drc_mines_flyover.gpkg layers: `mines`, `route`.
  2. Add the Google Satellite basemap (Browser > XYZ Tiles > New Connection):
       https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}     name it "Google Satellite"
     (the script adds it automatically if no layer named BASEMAP_NAME exists).
  3. Chainage plugin: select layer `route` > Chainage > distance 1000 (m)
     -> QChainage names its output `chain_route` by default; the script finds it
        automatically (any name in CHAINAGE_LAYERS works).
     If no chainage layer is found the script falls back to QGIS's built-in
     "Points along geometry", which produces the same thing.
  4. Set OUT_DIR, then Run. Try PREVIEW = True first (small, every 5th frame).

Altitude note: "altitude" here is the camera height for a 60 deg field of view;
the visible ground width is about 1.15 x altitude (4 km altitude -> ~4.6 km wide).
"""
import math
import os

# ----------------------------------------------------------------- settings
OUT_DIR = os.path.expanduser("~/drc_flyover_frames")
ROUTE_LAYER = "route"
MINES_LAYER = "mines"
CHAINAGE_LAYERS = ["chain_route", "chainage"]   # QChainage output (first one found is used)
CHAINAGE_SPACING_M = 1000            # only used for the built-in fallback
BASEMAP_NAME = "Google Satellite"
# lyrs=s satellite only | lyrs=y satellite + labels/roads (hybrid)
BASEMAP_URL = ("type=xyz&zmin=0&zmax=20&"
               "url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D{x}%26y%3D{y}%26z%3D{z}")
ATTRIBUTION = "Imagery \u00a9 Google"   # keep a credit on screen
EXTRA_LAYERS = []                    # e.g. ["hillshade", "rivers"] drawn above basemap

WIDTH, HEIGHT, FPS = 1920, 1080, 25
FOV_DEG = 60.0
ALT_LOW_M = 4_000                    # over the mines - pits, waste dumps, tailings visible
ALT_HOVER_START_M = 6_000            # hover begins a bit higher and sinks to ALT_LOW_M
ALT_CRUISE_MIN_M = 10_000            # short hops still climb at least this high
ALT_CRUISE_MAX_M = 90_000            # long hops (e.g. Bisie -> Manono) cap here
CRUISE_ALT_FRACTION = 0.30           # cruise altitude = 30% of hop length (then clamped)
HOVER_S = 6.0                        # seconds over each mine
HOVER_TURN_DEG = 50.0                # slow yaw while hovering
TRANSIT_S_MIN, TRANSIT_S_MAX = 4.0, 14.0
TRANSIT_S_PER_100KM = 2.0
LOOKAHEAD_M = 8_000                  # heading looks this far ahead along the route
START_MINE, END_MINE = 1, None       # tour_order range to render (None = to the end)
PREVIEW = False                      # True: 960x540 and every 5th frame
ANIMATE_POINTS = True                # growing flight trail, pulsing current mine,
                                     # visited mines turn green, upcoming mines labelled
TRAIL_COLOR = (255, 196, 64)
VISITED_COLOR = (80, 220, 120)
UPCOMING_COLOR = (255, 255, 255)


# ----------------------------------------------------------- pure geometry
def smoothstep(u):
    return u * u * (3 - 2 * u)


def lerp(a, b, t):
    return a + (b - a) * t


def angle_lerp(a, b, t):
    d = (b - a + 540.0) % 360.0 - 180.0
    return (a + d * t) % 360.0


class Track:
    """Chainage points sorted by distance along the route: [(d, x, y), ...]."""

    def __init__(self, pts):
        self.p = sorted(pts)
        self.d = [q[0] for q in self.p]

    def at(self, dist):
        import bisect
        dist = max(self.d[0], min(self.d[-1], dist))
        i = bisect.bisect_right(self.d, dist)
        if i >= len(self.p):
            return self.p[-1][1], self.p[-1][2]
        a, b = self.p[i - 1], self.p[i]
        t = 0 if b[0] == a[0] else (dist - a[0]) / (b[0] - a[0])
        return lerp(a[1], b[1], t), lerp(a[2], b[2], t)

    def heading(self, dist, ahead=LOOKAHEAD_M):
        """Compass bearing (deg, 0 = north) of travel at `dist`."""
        if dist + ahead > self.d[-1]:
            x0, y0 = self.at(dist - ahead)
            x1, y1 = self.at(dist)
        else:
            x0, y0 = self.at(dist)
            x1, y1 = self.at(dist + ahead)
        return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360.0


def build_timeline(track, mine_stops, fps=FPS):
    """mine_stops: [(dist_along_route, name, commodity), ...] in tour order.
    Returns a list of frames: dict(x, y, alt, heading, label, sublabel)."""
    frames = []
    for i, (dm, name, commodity) in enumerate(mine_stops):
        nxt = mine_stops[i + 1][0] if i + 1 < len(mine_stops) else None
        def leg_bearing(a, b):
            (x0, y0), (x1, y1) = track.at(a), track.at(b)
            return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360.0
        # legs are straight between mines: hold the leg bearing in transit,
        # do all turning during the hover so the camera never whips round
        h_out = leg_bearing(dm, nxt) if nxt is not None else (
            frames[-1]["heading"] if frames else 0.0)
        h_in = frames[-1]["heading"] if frames else h_out
        # --- hover over the mine
        n = int(HOVER_S * fps)
        x, y = track.at(dm)
        for k in range(n):
            u = k / max(1, n - 1)
            frames.append(dict(
                x=x, y=y,
                alt=lerp(ALT_HOVER_START_M, ALT_LOW_M, smoothstep(u)),
                heading=angle_lerp(h_in, h_out, smoothstep(u)) if i else
                (h_out - HOVER_TURN_DEG * (1 - u)) % 360,
                label=name, sublabel=commodity, fade=min(1.0, u * 4, (1 - u) * 4),
                d=dm, stop=i, hover=u))
        if nxt is None:
            break
        # --- transit to next mine
        hop = nxt - dm
        dur = max(TRANSIT_S_MIN, min(TRANSIT_S_MAX, hop / 100_000 * TRANSIT_S_PER_100KM + 3))
        cruise = max(ALT_CRUISE_MIN_M, min(ALT_CRUISE_MAX_M, hop * CRUISE_ALT_FRACTION))
        n = int(dur * fps)
        for k in range(1, n + 1):
            u = k / n
            d = dm + hop * smoothstep(u)
            x, y = track.at(d)
            alt = ALT_LOW_M + (cruise - ALT_LOW_M) * math.sin(math.pi * u) ** 0.8
            frames.append(dict(x=x, y=y, alt=alt, heading=h_out,
                               label="", sublabel="", fade=0.0, d=d, stop=i, hover=None))
    # smooth headings (removes jitter at route vertices)
    sm = [f["heading"] for f in frames]
    for f_i in range(len(frames)):
        lo, hi = max(0, f_i - fps // 2), min(len(frames), f_i + fps // 2 + 1)
        sx = sum(math.sin(math.radians(sm[j])) for j in range(lo, hi))
        cx = sum(math.cos(math.radians(sm[j])) for j in range(lo, hi))
        frames[f_i]["heading"] = math.degrees(math.atan2(sx, cx)) % 360
    return frames


def ground_width(alt):
    return 2 * alt * math.tan(math.radians(FOV_DEG / 2))


# ------------------------------------------------------------- QGIS part
def _load_common():
    import importlib.util
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        d = os.path.expanduser("~/drc_mines_flyover/scripts")
    spec = importlib.util.spec_from_file_location("flyover3d_common",
                                                  os.path.join(d, "flyover3d_common.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def find_layer(prj, name):
    """Find a layer by name, tolerating the names QGIS gives GeoPackage layers
    (e.g. 'drc_mines_flyover — route') and matching the GeoPackage table name."""
    import re
    ls = prj.mapLayersByName(name)
    if ls:
        return ls[0]
    layers = list(prj.mapLayers().values())
    for l in layers:
        if re.search(r"layername=" + re.escape(name) + r"(\||$)", l.source()):
            return l
    for l in layers:
        if re.search(r"(^|[\s—–:-])" + re.escape(name) + r"$", l.name().strip()):
            return l
    return None


def find_chainage(prj):
    for nm in CHAINAGE_LAYERS:
        found = prj.mapLayersByName(nm) or [l for l in prj.mapLayers().values()
                                            if l.name().strip().endswith(nm)]
        if found:
            print(f"Using chainage layer '{found[0].name()}' ({found[0].featureCount()} points)")
            return found[0]
    return None


def tour_from_project(prj, start_mine=1, end_mine=None):
    """Read route + chainage points + mines from the project (EPSG:3857).
    Returns (Track, stops) where stops = [(dist_along_route, name, commodity), ...]."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsPointXY, QgsGeometry)
    from qgis import processing
    crs = QgsCoordinateReferenceSystem("EPSG:3857")

    def layer(name):
        lyr = find_layer(prj, name)
        if lyr is None:
            raise RuntimeError(f"Layer '{name}' not found in the project. Add it from "
                               f"data/drc_mines_flyover.gpkg. Layers in the project: "
                               f"{[l.name() for l in prj.mapLayers().values()]}")
        return lyr

    route_lyr, mines_lyr = layer(ROUTE_LAYER), layer(MINES_LAYER)
    to3857 = lambda lyr: QgsCoordinateTransform(lyr.crs(), crs, prj)
    for lyr in (route_lyr, mines_lyr):
        if not lyr.isValid() or lyr.featureCount() == 0:
            raise RuntimeError(
                f"Layer '{lyr.name()}' is empty or its file can't be found "
                f"(source: {lyr.source()}). This happens when the folder is moved after "
                "the layers were added. Remove the 'route' and 'mines' layers and add them "
                "again from data/drc_mines_flyover.gpkg, then re-run QChainage.")
    rg = QgsGeometry(next(route_lyr.getFeatures()).geometry())
    rg.transform(to3857(route_lyr))

    ch = find_chainage(prj)
    if ch is None:
        print("No chainage layer found -> using native:pointsalonglines "
              f"every {CHAINAGE_SPACING_M} m")
        ch = processing.run("native:pointsalonglines", {
            "INPUT": route_lyr, "DISTANCE": CHAINAGE_SPACING_M,
            "START_OFFSET": 0, "END_OFFSET": 0, "OUTPUT": "memory:chainage"})["OUTPUT"]
        prj.addMapLayer(ch)
    tr = to3857(ch)
    pts = []
    for f in ch.getFeatures():
        g = QgsGeometry(f.geometry()); g.transform(tr)
        p = g.asPoint()
        pts.append((rg.lineLocatePoint(QgsGeometry.fromPointXY(p)), p.x(), p.y()))
    # add the route vertices (= the mines) so hovers sit exactly on each mine
    for v in rg.asPolyline():
        pts.append((rg.lineLocatePoint(QgsGeometry.fromPointXY(QgsPointXY(v.x(), v.y()))),
                    v.x(), v.y()))
    track = Track(pts)
    print(f"Track: {len(pts)} chainage points, {track.d[-1]/1000:,.0f} km")

    trm = to3857(mines_lyr)
    stops = []
    for f in sorted(mines_lyr.getFeatures(), key=lambda f: f["tour_order"]):
        o = f["tour_order"]
        if o < start_mine or (end_mine and o > end_mine):
            continue
        g = QgsGeometry(f.geometry()); g.transform(trm)
        stops.append((rg.lineLocatePoint(g), f["name"], f["commodity"]))
    if not stops:
        raise RuntimeError("No mines in the START_MINE..END_MINE range")
    return track, stops


def run():
    from qgis.core import (QgsProject, QgsRasterLayer, QgsMapSettings, QgsRectangle,
                           QgsCoordinateReferenceSystem, QgsMapRendererCustomPainterJob,
                           QgsPointXY)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QImage, QPainter, QColor

    prj = QgsProject.instance()
    crs = QgsCoordinateReferenceSystem("EPSG:3857")

    def layer(name, required=True):
        lyr = find_layer(prj, name)
        if lyr is None and required:
            raise RuntimeError(f"Layer '{name}' not found in the project")
        return lyr

    mines_lyr = layer(MINES_LAYER)
    track, stops = tour_from_project(prj, START_MINE, END_MINE)

    fps = FPS
    frames = build_timeline(track, stops, fps)
    w, h, step = (WIDTH, HEIGHT, 1) if not PREVIEW else (WIDTH // 2, HEIGHT // 2, 5)
    print(f"{len(frames)} frames = {len(frames)/fps:.0f} s of video "
          f"(rendering {len(frames)//step})")

    # basemap
    base = layer(BASEMAP_NAME, required=False)
    if base is None:
        base = QgsRasterLayer(BASEMAP_URL, BASEMAP_NAME, "wms")
        prj.addMapLayer(base)
    draw_layers = [layer(n) for n in EXTRA_LAYERS] + ([] if ANIMATE_POINTS else [mines_lyr]) + [base]

    ms = QgsMapSettings()
    ms.setDestinationCrs(crs)
    ms.setLayers(draw_layers)
    ms.setOutputSize(QSize(w, h))
    ms.setBackgroundColor(QColor(10, 14, 20))
    ms.setOutputDpi(96)

    os.makedirs(OUT_DIR, exist_ok=True)
    from qgis.PyQt.QtWidgets import QApplication
    c3 = _load_common()
    stop_pts = [(*track.at(sd), 0.0) for sd, _, _ in stops]
    trail = [(dd, x, y, 0.0) for dd, x, y in track.p]
    colors = dict(trail_color=TRAIL_COLOR, visited_color=VISITED_COLOR,
                  upcoming_color=UPCOMING_COLOR)

    for n, fr in enumerate(frames[::step]):
        path = os.path.join(OUT_DIR, f"frame_{n:05d}.png")
        gw = ground_width(fr["alt"]); gh = gw * h / w
        ms.setExtent(QgsRectangle(fr["x"] - gw / 2, fr["y"] - gh / 2,
                                  fr["x"] + gw / 2, fr["y"] + gh / 2))
        ms.setRotation(-fr["heading"])           # direction of travel at the top
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(10, 14, 20))
        p = QPainter(img)
        job = QgsMapRendererCustomPainterJob(ms, p)
        job.renderSynchronously()
        p.end()
        img.save(path)
        # overlay (shared with the 3D tour): animated points, readout, name card
        if ANIMATE_POINTS:
            m2p = ms.mapToPixel()

            def proj(x, y, z, m2p=m2p):
                q = m2p.transform(QgsPointXY(x, y))
                return (q.x(), q.y())
            c3.draw_points(path, proj, fr, trail, stop_pts, stops, START_MINE, **colors)
        c3.overlay(path, fr["label"], fr["sublabel"], fr["fade"],
                   f"alt {fr['alt']/1000:4.1f} km   hdg {fr['heading']:03.0f}\u00b0", ATTRIBUTION)
        if n % 25 == 0:
            print(f"  frame {n}/{len(frames)//step}")
            QApplication.processEvents()

    out_fps = fps // step
    print("\nDone. Make the video with:\n"
          f'  ffmpeg -framerate {out_fps} -i "{OUT_DIR}/frame_%05d.png" '
          f'-c:v libx264 -pix_fmt yuv420p -crf 18 "{OUT_DIR}/drc_mines_flyover.mp4"')


if __name__ in ("__main__", "__console__"):
    run()
