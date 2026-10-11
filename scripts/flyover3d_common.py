"""
Shared 3D renderer for 03_qgis3d_mine_orbit.py and 05_qgis3d_full_tour.py.

Why a layout item and not the 3D window: QGIS does not expose its 3D animation
exporter (Qgs3DAnimationSettings / Qgs3DUtils) to Python in any version. A print
layout's 3D Map item IS exposed: we copy your 3D view's settings into it, set the
camera for each frame, and export the layout as a PNG. On export the item waits
until terrain and imagery have finished loading, and it keeps its scene between
frames so tiles are reused.

Requires a 3D Map View configured in the project (terrain, layers, sky...).
QGIS 3.36+: the open 3D view is used directly.
Older QGIS: SAVE the project after configuring the 3D view; its settings are
read from the project file.
"""
import math
import os
import zipfile

MM_PER_INCH = 25.4


def _settings_from_xml_element(elem, prj):
    from qgis.core import QgsReadWriteContext
    from qgis._3d import Qgs3DMapSettings
    ctx = QgsReadWriteContext()
    ctx.setPathResolver(prj.pathResolver())
    s = Qgs3DMapSettings()
    s.setTransformContext(prj.transformContext())
    s.readXml(elem, ctx)
    s.resolveReferences(prj)
    try:
        s.setOutputDpi(96)
    except Exception:
        pass
    return s


def scene_settings(prj=None):
    """Return a fresh Qgs3DMapSettings copied from the user's 3D Map View."""
    from qgis.core import QgsProject, QgsReadWriteContext
    from qgis.PyQt.QtXml import QDomDocument
    prj = prj or QgsProject.instance()
    # 1) open 3D view (QGIS >= 3.36)
    try:
        from qgis.utils import iface
        canvases = iface.mapCanvases3D() if iface else []
        if canvases:
            src = canvases[0].mapSettings()
            doc = QDomDocument()
            elem = src.writeXml(doc, QgsReadWriteContext())
            doc.appendChild(elem)
            return _settings_from_xml_element(doc.documentElement(), prj)
    except Exception as e:  # older QGIS: Qgs3DMapCanvas not exposed
        print("3D view not reachable from Python here (", e, ") - reading the project file")
    # 2) 3D view saved in the project file
    fn = prj.fileName()
    if not fn or not os.path.exists(fn):
        raise RuntimeError("Configure a 3D Map View, then SAVE the project and run again")
    if fn.lower().endswith(".qgz"):
        with zipfile.ZipFile(fn) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".qgs"))
            xml = z.read(name).decode("utf-8")
    else:
        with open(fn, encoding="utf-8") as fh:
            xml = fh.read()
    doc = QDomDocument()
    doc.setContent(xml)
    elems = doc.elementsByTagName("qgis3d")
    if elems.isEmpty():
        raise RuntimeError("No 3D Map View found in the saved project. Open View > 3D Map Views "
                           "> New 3D Map View, configure it, save the project, run again")
    return _settings_from_xml_element(elems.at(0).toElement(), prj)


class Renderer3D:
    """Owns a hidden print layout with one full-page 3D map item."""

    def __init__(self, settings, size=(1920, 1080), dpi=96, prj=None):
        from qgis.core import (QgsProject, QgsPrintLayout, QgsLayoutSize, QgsLayoutPoint)
        from qgis._3d import QgsLayoutItem3DMap
        self.prj = prj or QgsProject.instance()
        self.settings = settings
        self.size, self.dpi = size, dpi
        w_mm, h_mm = size[0] / dpi * MM_PER_INCH, size[1] / dpi * MM_PER_INCH
        self.layout = QgsPrintLayout(self.prj)
        self.layout.initializeDefaults()
        self.layout.pageCollection().page(0).setPageSize(QgsLayoutSize(w_mm, h_mm))
        self.item = QgsLayoutItem3DMap.create(self.layout)
        self.layout.addLayoutItem(self.item)
        self.item.attemptMove(QgsLayoutPoint(0, 0))
        self.item.attemptResize(QgsLayoutSize(w_mm, h_mm))
        try:
            self.item.setFrameEnabled(False)
        except Exception:
            pass
        self.item.setMapSettings(settings)   # the item takes ownership

    def world(self, x, y, z):
        from qgis.core import QgsVector3D
        return self.settings.mapToWorldCoordinates(QgsVector3D(x, y, z))

    def render(self, path, look_x, look_y, look_z, dist, pitch, yaw):
        from qgis.core import QgsLayoutExporter
        from qgis._3d import QgsCameraPose
        pose = QgsCameraPose()
        pose.setCenterPoint(self.world(look_x, look_y, look_z))
        pose.setDistanceFromCenterPoint(dist)
        pose.setPitchAngle(pitch)
        pose.setHeadingAngle(yaw)
        self.item.setCameraPose(pose)
        exp = QgsLayoutExporter(self.layout)
        st = QgsLayoutExporter.ImageExportSettings()
        st.dpi = self.dpi
        st.cropToContents = False
        res = exp.exportToImage(path, st)
        if res != QgsLayoutExporter.ExportResult.Success:
            raise RuntimeError(f"Export failed for {path}: {exp.errorMessage()}")
        return path


def ground_sampler(settings, prj, dem_name="dem", fallback=1200.0):
    """Ground height (map units, before vertical exaggeration) from a DEM layer if present,
    else a constant. Only used to aim the camera; the terrain itself comes from the 3D view."""
    from qgis.core import QgsCoordinateTransform, QgsPointXY
    dem = (prj.mapLayersByName(dem_name) or [None])[0]
    try:
        vscale = settings.terrainVerticalScale()
    except AttributeError:
        vscale = 1.0
    tr = QgsCoordinateTransform(settings.crs(), dem.crs(), prj) if dem else None

    def ground(x, y):
        if dem is not None:
            v, ok = dem.dataProvider().sample(tr.transform(QgsPointXY(x, y)), 1)
            if ok and not math.isnan(v):
                return v * vscale
        return fallback * vscale
    return ground, (dem is not None)


def overlay(path, label="", sublabel="", fade=0.0, info="", attribution="Imagery © Google"):
    """Draw the name card / readout / credit on an exported frame (same look as the 2D tour)."""
    from qgis.PyQt.QtGui import QImage, QPainter, QColor, QFont
    from qgis.PyQt.QtCore import QRectF, Qt
    img = QImage(path)
    w, h = img.width(), img.height()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("Arial", max(8, int(h / 40)))
    if info:
        p.setFont(f)
        for dx, col in ((2, QColor(0, 0, 0, 170)), (0, QColor(255, 255, 255, 230))):  # shadow, text
            p.setPen(col)
            p.drawText(QRectF(dx, dx, w - 30, h * 0.08),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, info)
    if label and fade > 0:
        a = int(255 * fade)
        p.fillRect(QRectF(0, h * 0.80, w, h * 0.14), QColor(0, 0, 0, int(a * 0.55)))
        tf = QFont("Arial", max(10, int(h / 22))); tf.setBold(True)
        p.setFont(tf); p.setPen(QColor(255, 255, 255, a))
        p.drawText(QRectF(40, h * 0.80, w - 80, h * 0.085), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        p.setFont(f); p.setPen(QColor(255, 200, 90, a))
        p.drawText(QRectF(40, h * 0.875, w - 80, h * 0.06), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sublabel)
    if attribution:
        p.setFont(QFont("Arial", max(7, int(h / 70))))
        for dx, col in ((1, QColor(0, 0, 0, 160)), (0, QColor(255, 255, 255, 190))):
            p.setPen(col)
            p.drawText(QRectF(dx, h * 0.96 + dx, w - 20, h * 0.04),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, attribution)
    p.end()
    img.save(path)


class Projector:
    """Reproduces the QGIS 3D camera (QgsCameraPose) so map points can be drawn
    on exported 3D frames: pitch from vertical, yaw = -compass heading, vertical FOV."""

    def __init__(self, look_x, look_y, look_z, dist, pitch, heading, fov_deg, w, h):
        p, hd = math.radians(pitch), math.radians(heading)
        self.f = (math.sin(hd) * math.sin(p), math.cos(hd) * math.sin(p), -math.cos(p))
        self.r = (math.cos(hd), -math.sin(hd), 0.0)
        fx, fy, fz = self.f; rx, ry, rz = self.r
        self.u = (ry * fz - rz * fy, rz * fx - rx * fz, rx * fy - ry * fx)
        self.c = (look_x - dist * fx, look_y - dist * fy, look_z - dist * fz)
        self.t = math.tan(math.radians(fov_deg) / 2)
        self.w, self.h = w, h

    def __call__(self, x, y, z):
        d = (x - self.c[0], y - self.c[1], z - self.c[2])
        zc = sum(a * b for a, b in zip(d, self.f))
        if zc <= 1.0:
            return None                      # behind the camera
        xc = sum(a * b for a, b in zip(d, self.r))
        yc = sum(a * b for a, b in zip(d, self.u))
        aspect = self.w / self.h
        return ((xc / (zc * self.t * aspect) + 1) / 2 * self.w,
                (1 - yc / (zc * self.t)) / 2 * self.h)


def draw_points(path, proj, frame, trail, stop_pts, stops, start_mine,
                trail_color=(255, 196, 64), visited_color=(80, 220, 120),
                upcoming_color=(255, 255, 255)):
    """Animated points on a saved frame: trail up to the current position, pulsing
    ring on the current mine, visited mines green, upcoming mines labelled.
    proj(x, y, z) -> (px, py) or None (behind the camera)."""
    from qgis.PyQt.QtGui import QImage, QPainter, QColor, QFont, QPen
    from qgis.PyQt.QtCore import QPointF, QRectF, Qt
    img = QImage(path)
    w, h = img.width(), img.height()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(*trail_color, 235)); pen.setWidthF(max(2.0, h / 220))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    prev = None
    for dd, x, y, z in trail:
        if dd > frame["d"]:
            break
        q = proj(x, y, z)
        if q is not None and prev is not None:
            p.drawLine(QPointF(*prev), QPointF(*q))
        prev = q
    r = h / 90
    font = QFont("Arial", max(8, int(h / 50))); font.setBold(True)
    placed = []
    for j, ((x, y, z), (_, nm, _)) in enumerate(zip(stop_pts, stops)):
        q = proj(x, y, z)
        if q is None or not (-50 < q[0] < w + 50 and -50 < q[1] < h + 50):
            continue
        q = QPointF(*q)
        current = j == frame["stop"] and frame["hover"] is not None
        visited = j < frame["stop"] or (j == frame["stop"] and frame["hover"] is None)
        col = QColor(*(visited_color if (visited or current) else upcoming_color))
        if current:
            for ph in (0.0, 0.5):
                t = (frame["hover"] * 3 + ph) % 1.0
                ring = QColor(col); ring.setAlpha(int(255 * (1 - t)))
                rp = QPen(ring); rp.setWidthF(max(2.0, h / 300)); p.setPen(rp)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(q, r * (1.5 + 5 * t), r * (1.5 + 5 * t))
        p.setPen(QPen(QColor(0, 0, 0, 180), max(1.0, h / 540))); p.setBrush(col)
        p.drawEllipse(q, r, r)
        if not current:
            text = f"{j + start_mine}. {nm}"
            p.setFont(font)
            box = p.fontMetrics().boundingRect(text)
            rect = QRectF(q.x() + r * 1.6, q.y() - r * 0.6 - box.height(), box.width(), box.height())
            if any(rect.intersects(o) for o in placed):
                continue                      # skip labels that would overlap (distant clusters)
            placed.append(rect.adjusted(-4, -2, 4, 2))
            p.setPen(QColor(0, 0, 0, 170))                       # shadow for light skies
            p.drawText(QPointF(q.x() + r * 1.6 + 1.5, q.y() - r * 0.6 + 1.5), text)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(QPointF(q.x() + r * 1.6, q.y() - r * 0.6), text)
    p.end()
    img.save(path)
