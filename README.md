# DRC Mines Fly-over (QGIS + QChainage + Google Satellite, 3D terrain)

An aerial tour across 18 DRC mines, from Kibali (gold, Haut-Uélé) to Kipushi (Haut-Katanga).
The camera follows the Chainage points along the route. It drops to about 4 km over each
mine and climbs to 10–90 km between them.

| Script | What it makes |
|---|---|
| `05_qgis3d_full_tour.py` | **Main video.** The whole tour in 3D perspective over terrain, with Google Satellite draped on it. Animated points: a growing trail, the current mine pulsing, visited mines turning green, upcoming mines labelled. |
| `02_flyover_2d_frames.py` | The same flight seen straight down, with the same animated points. Fast to render. Also contains the flight-path logic the 3D script reuses. |
| `03_qgis3d_mine_orbit.py` | Close-up: approach and one 360° orbit of a single mine (or every mine). |
| `04_blender_mine_flyby.py` | Optional: cinematic orbit in Blender with BlenderGIS. |
| `00_build_data.py` | Rebuilds the GeoPackage after you edit `data/drc_mines.csv` (run in Terminal, not QGIS). |

**Tested:** I ran the scripts in real QGIS 3.34 (headless), together with the actual QChainage
plugin code. Google imagery and online terrain couldn't be downloaded there, so I used a test
checkerboard image and synthetic hills in their place. The camera direction and the overlay
positions were measured against the rendered frames.

## Release checks (run on every version of these scripts)
- Every Qt name is checked against **Qt 6** (QGIS 4 / Qt 6 builds) and still works on Qt 5 (QGIS 3.x).
- Every QGIS function used is checked against the latest QGIS Qt 6 Python bindings.
- `pyflakes`: no undefined names or leftover imports.
- The drawing code is run under real PyQt6 (Qt 6.11).
- All tours are run end to end in QGIS 3.34 with the real QChainage plugin code, with
  layer names as QGIS gives them ("drc_mines_flyover — route").

## Run everything inside QGIS, not VS Code
Quickest way: paste this into the QGIS Python Console and press Enter:

    import runpy, os; runpy.run_path(os.path.expanduser("~/drc_mines_flyover/scripts/05_qgis3d_full_tour.py"), run_name="__main__")

The scripts control QGIS itself. Open them in **Plugins › Python Console › Show Editor ›
Open Script**, then click **Run**. QGIS looks frozen while it renders; progress appears in the
console. You can use VS Code to edit settings in the scripts.

## 1. Setup (once)
1. Unzip this folder to your home folder, so you have `~/drc_mines_flyover`.
2. Install QGIS (3.40 LTR or newer recommended) and run `brew install ffmpeg` in Terminal.
3. Install the **QChainage** plugin (Plugins › Manage and Install).

## 2. Project
1. Start a new project with CRS **EPSG:3857**.
2. Add the `mines` and `route` layers from `data/drc_mines_flyover.gpkg`.
3. In the Browser, go to XYZ Tiles › New Connection.
   - Name: **Google Satellite**
   - URL: `https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}`

   Then add it to the map.
4. Select the `route` layer › QChainage › distance **1000** › OK. It creates `chain_route`,
   which the scripts find automatically.
5. Check the six mines marked `approx` (Rubaya, Twangiza, Namoya, Manono, MIBA, Kisanfu) on
   the imagery.

## 3. 3D view
1. View › 3D Map Views › New 3D Map View, then the gear icon (Configure).
2. Terrain: **Online**, vertical scale **2**.
3. Layers: tick **Google Satellite**.
4. QGIS 3.36+: leave the 3D view open. QGIS 3.34 or older: **save the project** (the script
   reads the 3D view settings from the saved file).
5. Optional: add a DEM layer named `dem` (e.g. Copernicus 30 m around the mines, from the
   OpenTopography plugin). It's only used to aim the camera at the exact ground height;
   without it the script assumes 1,200 m.

## 4. Render
1. Open `05_qgis3d_full_tour.py` and run it as it is. The defaults are `PREVIEW = True`
   (half size, every 5th frame) and mines 1–3.
2. Frames go to `~/drc_3d_tour_frames`. Paste the printed `ffmpeg` command into Terminal to
   make the MP4.
3. When the preview looks right, set `PREVIEW = False` and choose `START_MINE` / `END_MINE`.
   Render the tour one leg at a time.
   - `RESUME = True` skips frames that already exist, so you can stop and continue later.
   - The console shows seconds per frame and the time remaining.
4. The top-down version (`02`) and the mine orbits (`03`) work the same way.

Main settings: `PITCH_DEG` (camera tilt), and in `02`: `ALT_LOW_M`, `ALT_CRUISE_MAX_M`,
`HOVER_S`, `TRANSIT_S_*`.

## Google imagery terms
Google's tiles are fine for personal and research use. For a published video, keep the
"Imagery © Google" credit (it's added to every frame) and check Google's attribution
guidelines.

## Coordinate sources
"verified" = mindat.org locality pages. "approx" = placed by hand; check against the imagery.
