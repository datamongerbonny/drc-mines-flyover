"""
DRC MINES FLY-OVER - FULL TOUR IN 3D PERSPECTIVE (terrain + Google Satellite)
==============================================================================
The whole route flown over 3D terrain with the satellite imagery draped on it.
The camera follows the Chainage points like a chase camera, looking forward and down,
drops low over each mine and climbs between them. Animated points are drawn on
every frame: the flight trail grows behind you, the current mine pulses, visited
mines turn green, and upcoming mines are labelled.

Run from the QGIS Python Console (Show Editor > Open Script > Run).

ONE-TIME 3D VIEW SETUP
  View > 3D Map Views > New 3D Map View, then the gear icon (Configure):
    * Terrain: Type "Online" (global terrain tiles, nothing to download).
      Vertical scale 2.  [Or "DEM (Raster layer)" with your own DEM.]
    * Layers: tick "Google Satellite" so it is draped over the terrain.
  QGIS 3.36 or newer: leave the 3D view open.
  QGIS 3.34 or older: SAVE the project after configuring the 3D view.

OPTIONAL: a DEM layer named "dem" (e.g. Copernicus 30 m around the mines from the
OpenTopography plugin). It is only used to aim the camera at the right ground
height; without it the script assumes 1,200 m (the DRC plateau average).

Frames are written to OUT_DIR and the MP4 (drc_mines_3d_tour.mp4) is made there
automatically when ffmpeg is installed; Finder then opens with the video selected.
Re-running with the same settings resumes where it stopped; changing settings
clears the old frames automatically.
"""
import math
import os
import sys
import time

# --------------------------------------------------------------- settings
KIT_DIR = os.path.expanduser("~/drc_mines_flyover")   # where you unzipped the kit
OUT_DIR = os.path.expanduser("~/drc_3d_tour_frames")
SIZE = (1920, 1080)
FPS = 25
PITCH_DEG = 62              # 0 = straight down, 90 = horizon. 55-70 = aerial oblique
HOVER_PITCH_DEG = 55        # a little steeper over the mines, to look into the pits
DEM_LAYER = "dem"
FALLBACK_GROUND_M = 1200
START_MINE, END_MINE = 1, None  # whole tour (all 18 mines). e.g. 1, 6 for one leg
PREVIEW = True              # True: half size, every 5th frame (fast). False: full HD, smooth
ANIMATE_POINTS = True
RESUME = True               # skip frames already rendered with these same settings
TRAIL_COLOR = (255, 196, 64)
VISITED_COLOR = (80, 220, 120)
UPCOMING_COLOR = (255, 255, 255)
ATTRIBUTION = "Imagery © Google"


def _scripts_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.path.join(KIT_DIR, "scripts")


def _load(name, filename):
    import importlib.util
    d = _scripts_dir()
    if not os.path.exists(os.path.join(d, filename)):
        d = os.path.join(KIT_DIR, "scripts")
    spec = importlib.util.spec_from_file_location(name, os.path.join(d, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def camera_for(frame, ground):
    """Chase camera: QGIS orbits its camera around a look-at point, so the point on the
    flight track (or the mine, while hovering) is the look-at point and the camera sits
    behind it at the flight altitude, looking forward and down. The mine is therefore
    centred during each hover and the hover's slow turn becomes a partial orbit.
    QGIS yaw = -compass heading (verified by rendering in 3.34, and from the 3.36+
    camera code)."""
    pitch = HOVER_PITCH_DEG if frame["hover"] is not None else PITCH_DEG
    h_above = max(500.0, frame["alt"])
    lx, ly = frame["x"], frame["y"]
    return dict(x=lx, y=ly, z=ground(lx, ly), dist=h_above / math.cos(math.radians(pitch)),
                pitch=pitch, heading=frame["heading"], yaw=-frame["heading"])


def run():
    from qgis.core import QgsProject
    from qgis.PyQt.QtWidgets import QApplication
    sys.path.insert(0, _scripts_dir())
    fly = _load("flyover2d", "02_flyover_2d_frames.py")
    c3 = _load("flyover3d_common", "flyover3d_common.py")

    prj = QgsProject.instance()
    if prj.crs().authid() != "EPSG:3857":
        raise RuntimeError("Set the project CRS to EPSG:3857 first")
    track, stops = fly.tour_from_project(prj, START_MINE, END_MINE)
    frames = fly.build_timeline(track, stops, FPS)

    settings = c3.scene_settings(prj)
    w, h = SIZE if not PREVIEW else (SIZE[0] // 2, SIZE[1] // 2)
    step = 5 if PREVIEW else 1
    renderer = c3.Renderer3D(settings, (w, h), prj=prj)
    ground, has_dem = c3.ground_sampler(settings, prj, DEM_LAYER, FALLBACK_GROUND_M)
    if not has_dem:
        print(f"No '{DEM_LAYER}' layer: aiming the camera at {FALLBACK_GROUND_M} m ground height")
    try:
        fov = settings.fieldOfView()
    except AttributeError:
        fov = 45.0

    # ground heights for the trail and mines (computed once)
    trail = [(dd, x, y, ground(x, y)) for dd, x, y in track.p[::2]]
    stop_pts = [track.at(sd) for sd, _, _ in stops]
    stop_pts = [(x, y, ground(x, y)) for x, y in stop_pts]

    os.makedirs(OUT_DIR, exist_ok=True)
    # frames from a run with different settings are cleared automatically
    import glob, json
    stamp_file = os.path.join(OUT_DIR, "render_settings.json")
    stamp = dict(start=START_MINE, end=END_MINE, preview=PREVIEW, size=[w, h], fps=FPS,
                 pitch=PITCH_DEG, hover_pitch=HOVER_PITCH_DEG)
    old = None
    if os.path.exists(stamp_file):
        try:
            old = json.load(open(stamp_file))
        except Exception:
            old = None
    if old != stamp:
        stale = glob.glob(os.path.join(OUT_DIR, "frame_*.png"))
        if stale:
            print(f"Settings changed: clearing {len(stale)} old frames")
            for f in stale:
                os.remove(f)
        json.dump(stamp, open(stamp_file, "w"))
    todo = frames[::step]
    print(f"{len(frames)} frames = {len(frames)/FPS:.0f} s of video; rendering {len(todo)} "
          f"at {w}x{h} -> {OUT_DIR}")
    t0, done = time.time(), 0
    for n, fr in enumerate(todo):
        path = os.path.join(OUT_DIR, f"frame_{n:05d}.png")
        if RESUME and os.path.exists(path):
            continue
        cam = camera_for(fr, ground)
        renderer.render(path, cam["x"], cam["y"], cam["z"], cam["dist"], cam["pitch"], cam["yaw"])
        if ANIMATE_POINTS:
            proj = c3.Projector(cam["x"], cam["y"], cam["z"], cam["dist"], cam["pitch"],
                                cam["heading"], fov, w, h)
            c3.draw_points(path, proj, fr, trail, stop_pts, stops, START_MINE,
                           trail_color=TRAIL_COLOR, visited_color=VISITED_COLOR,
                           upcoming_color=UPCOMING_COLOR)
        c3.overlay(path, fr["label"], fr["sublabel"], fr["fade"],
                   f"alt {fr['alt']/1000:4.1f} km   hdg {fr['heading']:03.0f}°", ATTRIBUTION)
        done += 1
        if done % 10 == 0 or n == len(todo) - 1:
            el = time.time() - t0
            print(f"  frame {n+1}/{len(todo)}  {el/done:.1f} s/frame  "
                  f"~{(len(todo)-n-1)*el/done/60:.0f} min left")
            QApplication.processEvents()

    out_fps = FPS // step
    mp4 = os.path.join(OUT_DIR, "drc_mines_3d_tour.mp4")
    make_video(OUT_DIR, out_fps, mp4)


def make_video(folder, fps, mp4):
    """Join the frames into an MP4 with ffmpeg (Homebrew or system install)."""
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg",
                                                      "/usr/local/bin/ffmpeg",
                                                      "/usr/bin/ffmpeg")
                                         if os.path.exists(p)), None)
    cmd_text = (f'ffmpeg -y -framerate {fps} -i "{folder}/frame_%05d.png" -c:v libx264 '
                f'-pix_fmt yuv420p -crf 18 "{mp4}"')
    if ff is None:
        print("\nFrames done. ffmpeg not found - make the video in Terminal with:\n  " + cmd_text)
        return
    print("Making the video...")
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps),
                        "-i", os.path.join(folder, "frame_%05d.png"), "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-crf", "18", mp4],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"\nDone. Video: {mp4}")
        subprocess.run(["open", "-R", mp4]) if sys.platform == "darwin" else None
    else:
        print("ffmpeg failed:", r.stderr[-800:], "\nTry in Terminal:\n  " + cmd_text)


if __name__ in ("__main__", "__console__"):
    run()
