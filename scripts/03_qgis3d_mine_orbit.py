"""
QGIS 3D: descend onto ONE mine and orbit it (terrain + Google Satellite)
========================================================================
Uses the same 3D view setup as 05_qgis3d_full_tour.py (see its header):
3D Map View with Online terrain (or a DEM) and Google Satellite draped on it;
QGIS < 3.36: save the project after configuring the 3D view.

Set MINE (name or tour_order; None = every mine) and Run in the Python Console.
Each mine gets its own folder of frames + the ffmpeg command for its MP4.
"""
import os

KIT_DIR = os.path.expanduser("~/drc_mines_flyover")
OUT_DIR = os.path.expanduser("~/drc_3d_orbits")
MINE = "Kamoa-Kakula"      # name or tour_order number; None = all mines
SIZE = (1920, 1080)
FPS = 25
APPROACH_S, ORBIT_S = 4.0, 12.0
APPROACH_DIST_M, ORBIT_DIST_M = 30_000, 8_000
APPROACH_PITCH, ORBIT_PITCH = 35, 58      # 0 = straight down, 90 = horizon
DEM_LAYER, FALLBACK_GROUND_M = "dem", 1200
PREVIEW = True             # half size, every 5th frame


def _load(name, filename):
    import importlib.util
    try:
        d = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        d = os.path.join(KIT_DIR, "scripts")
    if not os.path.exists(os.path.join(d, filename)):
        d = os.path.join(KIT_DIR, "scripts")
    spec = importlib.util.spec_from_file_location(name, os.path.join(d, filename))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def smooth(u):
    return u * u * (3 - 2 * u)


def run():
    from qgis.core import (QgsProject, QgsCoordinateTransform, QgsCoordinateReferenceSystem,
                           QgsGeometry)
    from qgis.PyQt.QtWidgets import QApplication
    c3 = _load("flyover3d_common", "flyover3d_common.py")
    prj = QgsProject.instance()
    crs = QgsCoordinateReferenceSystem("EPSG:3857")
    settings = c3.scene_settings(prj)
    w, h = SIZE if not PREVIEW else (SIZE[0] // 2, SIZE[1] // 2)
    step = 5 if PREVIEW else 1
    r = c3.Renderer3D(settings, (w, h), prj=prj)
    ground, _ = c3.ground_sampler(settings, prj, DEM_LAYER, FALLBACK_GROUND_M)

    fly = _load("flyover2d", "02_flyover_2d_frames.py")
    mines = fly.find_layer(prj, "mines")
    tr = QgsCoordinateTransform(mines.crs(), crs, prj)
    feats = sorted(mines.getFeatures(), key=lambda f: f["tour_order"])
    if MINE is not None:
        feats = [f for f in feats if f["name"] == MINE or f["tour_order"] == MINE]
        if not feats:
            raise RuntimeError(f"Mine '{MINE}' not found in layer 'mines'")

    n_app, n_orb = int(APPROACH_S * FPS), int(ORBIT_S * FPS)
    for f in feats:
        g = QgsGeometry(f.geometry()); g.transform(tr); p = g.asPoint()
        z = ground(p.x(), p.y())
        folder = os.path.join(OUT_DIR, f"{f['tour_order']:02d}_{f['name']}".replace("/", "-"))
        os.makedirs(folder, exist_ok=True)
        print(f"{f['name']}: {(n_app + n_orb)//step} frames -> {folder}")
        k = 0
        for i in range(0, n_app + n_orb, step):
            if i < n_app:                       # approach: from far/low-angle to orbit pose
                u = smooth(i / n_app)
                dist = APPROACH_DIST_M + (ORBIT_DIST_M - APPROACH_DIST_M) * u
                pitch = APPROACH_PITCH + (ORBIT_PITCH - APPROACH_PITCH) * u
                heading = 0.0
            else:                               # one full orbit
                u = (i - n_app) / n_orb
                dist, pitch, heading = ORBIT_DIST_M, ORBIT_PITCH, 360.0 * u
            path = os.path.join(folder, f"frame_{k:05d}.png")
            r.render(path, p.x(), p.y(), z, dist, pitch, -heading)
            fade = min(1.0, (i / (n_app + n_orb)) * 6, (1 - i / (n_app + n_orb)) * 6)
            c3.overlay(path, f["name"], f["commodity"], fade, "")
            k += 1
            if k % 25 == 0:
                print(f"  {k} frames"); QApplication.processEvents()
        print(f'  ffmpeg -framerate {FPS // step} -i "{folder}/frame_%05d.png" -c:v libx264 '
              f'-pix_fmt yuv420p -crf 18 "{folder}.mp4"')


if __name__ in ("__main__", "__console__"):
    run()
