"""Interactive PySide6 parameter editor with real-time 3D and 2D sketching for waveguides."""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .parameters import (
    FIELDS,
    compute_baffle_azimuths_and_perimeter,
    compute_synchronized_profiles,
    validate,
)


class Realtime3DSketch(QWidget):
    """Real-time interactive 3D and 2D sketch canvas for waveguides.

    Supports interactive mouse orbiting, zooming, lighting, and switching
    between 3D Orbit View and 2D Cross-Section View at 60 FPS.
    """

    def __init__(self):
        super().__init__()
        self.source: dict[str, Any] | None = None
        self.view_mode: str = "3d"  # "3d" or "2d"

        # 3D Camera Angles
        self.yaw_deg: float = 40.0
        self.pitch_deg: float = -22.0
        self.zoom: float = 1.0

        self.last_mouse_pos: QPoint | None = None
        self.setMinimumHeight(240)
        self.setMaximumHeight(340)
        self.setMouseTracking(True)
        self.setAccessibleName("Waveguide Realtime 3D and 2D Sketch Viewer")

    def reset_view(self):
        self.yaw_deg = 40.0
        self.pitch_deg = -22.0
        self.zoom = 1.0
        self.update()

    def set_view_mode(self, mode: str):
        self.view_mode = mode
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_mouse_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.view_mode == "3d" and event.buttons() & Qt.MouseButton.LeftButton and self.last_mouse_pos is not None:
            pos = event.position().toPoint()
            delta = pos - self.last_mouse_pos
            self.yaw_deg = (self.yaw_deg + delta.x() * 0.7) % 360.0
            self.pitch_deg = max(-85.0, min(85.0, self.pitch_deg + delta.y() * 0.7))
            self.last_mouse_pos = pos
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_mouse_pos = None

    def wheelEvent(self, event):
        if self.view_mode == "3d":
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom = min(3.0, self.zoom * 1.1)
            elif delta < 0:
                self.zoom = max(0.4, self.zoom * 0.9)
            self.update()

    def paintEvent(self, event):
        if self.source is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background container styling
        bg = self.palette().window().color()
        painter.fillRect(self.rect(), bg)

        if self.view_mode == "2d":
            self._paint_2d_section(painter)
        else:
            self._paint_3d_orbit(painter)

    def _paint_2d_section(self, painter: QPainter):
        p = self.source
        pen_h = QPen(self.palette().text().color(), 1.6)
        pen_v = QPen(self.palette().highlight().color(), 1.4, Qt.DashLine)

        pts_h, pts_v = compute_synchronized_profiles(p, num_horn_points=32, num_rolloff_points=10)
        if not pts_h or not pts_v:
            return

        total_length = pts_h[-1][0]
        max_r_h = max(r for _, r in pts_h)
        max_r_v = max(r for _, r in pts_v)
        baffle_rh = p["baffle_width_m"] / 2.0
        baffle_rv = p["baffle_height_m"] / 2.0
        max_extent = max(max_r_h, max_r_v, baffle_rh, baffle_rv)

        margin = 25
        w_avail = self.width() - 2 * margin
        h_avail = self.height() - 2 * margin

        scale = min(w_avail / max(total_length, 0.05), (h_avail / 2.0) / max(max_extent, 0.05))

        x_start = margin + 15
        y_center = self.height() / 2.0

        # Draw centerline axis
        pen_axis = QPen(self.palette().mid().color(), 1.0, Qt.DashLine)
        painter.setPen(pen_axis)
        painter.drawLine(int(x_start - 10), int(y_center), int(x_start + total_length * scale + 15), int(y_center))

        # Draw Vertical (V) and Horizontal (H) 2D profile curves + baffle extensions
        for pts_axis, baffle_r, pen_curve in ((pts_v, baffle_rv, pen_v), (pts_h, baffle_rh, pen_h)):
            painter.setPen(pen_curve)
            for sign in (-1, 1):
                path = QPainterPath()
                first = True
                for z, r in pts_axis:
                    px = x_start + z * scale
                    py = y_center + sign * r * scale
                    if first:
                        path.moveTo(px, py)
                        first = False
                    else:
                        path.lineTo(px, py)

                baffle_px = x_start + pts_axis[-1][0] * scale
                baffle_py = y_center + sign * max(baffle_r, pts_axis[-1][1]) * scale
                path.lineTo(baffle_px, baffle_py)
                painter.drawPath(path)

        # Throat disc
        r_throat = p["throat_diameter_m"] / 2.0
        pen_driver = QPen(self.palette().highlight().color(), 2.5)
        painter.setPen(pen_driver)
        painter.drawLine(
            int(x_start),
            int(y_center - r_throat * scale),
            int(x_start),
            int(y_center + r_throat * scale),
        )

        painter.setPen(pen_h)
        painter.drawText(x_start, 16, "─── Horizontal (H)   - - - Vertical (V)")
        painter.drawText(x_start, int(self.height() - 8), "Throat (Z=0)")
        painter.drawText(int(x_start + total_length * scale - 50), int(self.height() - 8), "Baffle (+Z)")

    def _paint_3d_orbit(self, painter: QPainter):
        p = self.source
        rolloff_pts = 6 if p["rolloff_radius_m"] > 1e-4 else 0
        pts_h, pts_v = compute_synchronized_profiles(p, num_horn_points=14, num_rolloff_points=rolloff_pts)
        if not pts_h or not pts_v:
            return

        total_length = pts_h[-1][0]
        r_x_lip = pts_h[-1][1]
        r_y_lip = pts_v[-1][1]
        baffle_w = max(p["baffle_width_m"], 2.0 * r_x_lip + 0.006)
        baffle_h = max(p["baffle_height_m"], 2.0 * r_y_lip + 0.006)
        max_dim = max(total_length, baffle_w, baffle_h)

        # Center of viewport
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        base_scale = min(self.width(), self.height()) * 0.75 / max(max_dim, 0.05)
        scale = base_scale * self.zoom

        # Camera rotation matrix
        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        cos_p, sin_p = math.cos(pitch), math.sin(pitch)

        z_center = total_length * 0.5

        def project(x: float, y: float, z: float) -> tuple[float, float, float]:
            zc = z - z_center
            # Y-rotation
            x1 = x * cos_y + zc * sin_y
            z1 = -x * sin_y + zc * cos_y
            y1 = y
            # X-rotation
            x2 = x1
            y2 = y1 * cos_p - z1 * sin_p
            z2 = y1 * sin_p + z1 * cos_p

            # Weak perspective projection (larger z2 is closer to viewer)
            cam_d = max_dim * 3.5
            persp = cam_d / max(cam_d - z2, max_dim * 0.5)
            sx = cx + x2 * scale * persp
            sy = cy - y2 * scale * persp
            return sx, sy, z2

        angles, rect_pts = compute_baffle_azimuths_and_perimeter(baffle_w, baffle_h, n_quadrant=6)
        num_sectors = len(angles)

        # 1. Horn + roll-off rings (group "horn")
        rings_3d: list[list[tuple[float, float, float]]] = []
        ring_groups: list[str] = []

        for k in range(len(pts_h)):
            z = pts_h[k][0]
            rx = pts_h[k][1]
            ry = pts_v[k][1]
            ring: list[tuple[float, float, float]] = []
            for s, angle in enumerate(angles):
                x = rx * math.cos(angle)
                y = ry * math.sin(angle)
                ring.append(project(x, y, z))
            rings_3d.append(ring)
            if k > 0:
                ring_groups.append("horn")

        # 2. Front rectangular baffle rings (group "baffle")
        z_baffle = pts_h[-1][0]
        for u in (0.5, 1.0):
            ring = []
            for s, angle in enumerate(angles):
                lx = r_x_lip * math.cos(angle)
                ly = r_y_lip * math.sin(angle)
                rx_rect, ry_rect = rect_pts[s]
                x = (1.0 - u) * lx + u * rx_rect
                y = (1.0 - u) * ly + u * ry_rect
                ring.append(project(x, y, z_baffle))
            rings_3d.append(ring)
            ring_groups.append("baffle")

        # 3. Rectangular baffle rim (group "baffle")
        t_flange = max(0.004, min(0.012, 0.15 * p["length_m"]))
        rim_ring = [project(rx_rect, ry_rect, z_baffle - t_flange) for rx_rect, ry_rect in rect_pts]
        rings_3d.append(rim_ring)
        ring_groups.append("baffle")

        base_color = self.palette().window().color()
        is_dark = base_color.lightness() < 128
        wire_color = QColor(220, 220, 220, 145) if is_dark else QColor(40, 40, 40, 145)
        horn_base = QColor(60, 130, 185) if is_dark else QColor(125, 175, 215)
        baffle_base = QColor(95, 105, 118) if is_dark else QColor(165, 172, 182)

        # Build depth-sorted quads across horn and baffle
        quads: list[tuple[float, QPolygonF, QColor]] = []

        for i in range(len(rings_3d) - 1):
            r1 = rings_3d[i]
            r2 = rings_3d[i + 1]
            grp = ring_groups[i]
            f_base = horn_base if grp == "horn" else baffle_base
            alpha = 215 if grp == "horn" else 190

            for s in range(num_sectors):
                s_next = (s + 1) % num_sectors
                p0 = r1[s]
                p1 = r1[s_next]
                p2 = r2[s_next]
                p3 = r2[s]

                z_avg = (p0[2] + p1[2] + p2[2] + p3[2]) / 4.0
                poly = QPolygonF(
                    [QPointF(p0[0], p0[1]), QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]), QPointF(p3[0], p3[1])]
                )

                dx1, dy1 = p1[0] - p0[0], p1[1] - p0[1]
                dx2, dy2 = p3[0] - p0[0], p3[1] - p0[1]
                nz = dx1 * dy2 - dy1 * dx2
                shade = 0.58 + 0.38 * max(0.0, min(1.0, abs(nz) / 280.0))
                color = QColor(
                    min(255, int(f_base.red() * shade)),
                    min(255, int(f_base.green() * shade)),
                    min(255, int(f_base.blue() * shade)),
                    alpha,
                )
                quads.append((z_avg, poly, color))

        # Throat driver cap quad/polygon included in depth sort
        throat_ring = rings_3d[0]
        throat_z = sum(pt[2] for pt in throat_ring) / len(throat_ring)
        throat_poly = QPolygonF([QPointF(pt[0], pt[1]) for pt in throat_ring])
        driver_color = QColor(self.palette().highlight().color())
        driver_color.setAlpha(235)
        quads.append((throat_z, throat_poly, driver_color))

        # Sort quads by depth (back to front: smallest z2 to largest z2)
        quads.sort(key=lambda item: item[0])

        pen_edge = QPen(wire_color, 0.9)
        painter.setPen(pen_edge)

        for _, poly, color in quads:
            painter.setBrush(color)
            painter.drawPolygon(poly)

        # Orientation helper axes indicator (bottom-left)
        ax_origin = (45.0, self.height() - 45.0)
        axis_len = 24.0
        # X (red)
        ax_x = (ax_origin[0] + axis_len * cos_y, ax_origin[1] - axis_len * sin_y * sin_p)
        # Y (green)
        ax_y = (ax_origin[0], ax_origin[1] - axis_len * cos_p)
        # Z (blue/yellow on-axis)
        ax_z = (ax_origin[0] + axis_len * sin_y, ax_origin[1] + axis_len * cos_y * sin_p)

        painter.setPen(QPen(QColor(230, 80, 80), 2.0))
        painter.drawLine(int(ax_origin[0]), int(ax_origin[1]), int(ax_x[0]), int(ax_x[1]))
        painter.drawText(int(ax_x[0] + 3), int(ax_x[1] + 3), "X")

        painter.setPen(QPen(QColor(80, 200, 80), 2.0))
        painter.drawLine(int(ax_origin[0]), int(ax_origin[1]), int(ax_y[0]), int(ax_y[1]))
        painter.drawText(int(ax_y[0] + 3), int(ax_y[1] + 3), "Y")

        painter.setPen(QPen(QColor(230, 200, 60), 2.0))
        painter.drawLine(int(ax_origin[0]), int(ax_origin[1]), int(ax_z[0]), int(ax_z[1]))
        painter.drawText(int(ax_z[0] + 3), int(ax_z[1] + 3), "Z")

        # Instruction text
        painter.setPen(QPen(self.palette().text().color(), 1.0))
        painter.drawText(85, int(self.height() - 10), "Drag to Orbit · Scroll to Zoom")


class WaveguideEditor:
    """Waveguide dock editor housing parameters, live 3D/2D sketch, and host binding."""

    def __init__(self, parent, host):
        self.host = host
        self.source: dict[str, Any] = {}
        self.revision = ""
        self.widget = QWidget(parent)
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # View Mode Control Bar
        mode_bar = QHBoxLayout()
        self.btn_3d = QPushButton("3D Orbit View")
        self.btn_2d = QPushButton("2D Profile View")
        self.btn_reset = QPushButton("Reset Camera")

        self.btn_3d.setCheckable(True)
        self.btn_2d.setCheckable(True)
        self.btn_3d.setChecked(True)

        self.mode_group = QButtonGroup(self.widget)
        self.mode_group.addButton(self.btn_3d)
        self.mode_group.addButton(self.btn_2d)

        mode_bar.addWidget(self.btn_3d)
        mode_bar.addWidget(self.btn_2d)
        mode_bar.addWidget(self.btn_reset)
        mode_bar.addStretch()
        layout.addLayout(mode_bar)

        # Real-time 3D and 2D Sketch Canvas
        self.sketch = Realtime3DSketch()
        layout.addWidget(self.sketch)

        self.btn_3d.clicked.connect(lambda: self.sketch.set_view_mode("3d"))
        self.btn_2d.clicked.connect(lambda: self.sketch.set_view_mode("2d"))
        self.btn_reset.clicked.connect(self.sketch.reset_view)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.spins: dict[str, QDoubleSpinBox] = {}
        self.sliders: dict[str, QSlider] = {}
        self.connections: dict[str, Any] = {}

        for title, fields in FIELDS.items():
            page = QWidget()
            form = QVBoxLayout(page)
            for key, label, unit, factor, low, high, default, decimals in fields:
                text = QLabel(label)
                form.addWidget(text)
                row = QHBoxLayout()
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 1000)
                slider.setAccessibleName(label)

                spin = QDoubleSpinBox()
                spin.setDecimals(decimals)
                spin.setRange(low, high)
                spin.setSuffix(" " + unit if unit else "")
                spin.setSingleStep(10**-decimals if not unit else 1)
                spin.setValue(default)
                spin.setKeyboardTracking(False)
                spin.setAccessibleName(label)
                text.setBuddy(spin)

                slider.valueChanged.connect(
                    lambda value, s=spin, lo=low, hi=high: s.setValue(lo + (hi - lo) * value / 1000)
                )

                def slot(value, k=key, scale=factor):
                    self.edited(k, value / scale)

                self.connections[key] = slot
                spin.valueChanged.connect(slot)
                row.addWidget(slider, 1)
                row.addWidget(spin)
                form.addLayout(row)
                self.spins[key], self.sliders[key] = spin, slider

            form.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)

        self.status = QLabel("Use Generate to mesh the waveguide.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.host.services.subscribe(self.event)

    def apply_source(self, source, revision):
        self.source, self.revision = dict(source), revision
        for fields in FIELDS.values():
            for key, _, _, factor, low, high, _, _ in fields:
                spin, slider = self.spins[key], self.sliders[key]
                spin.blockSignals(True)
                slider.blockSignals(True)
                spin.setValue(float(source[key]) * factor)
                slider.setValue(round(1000 * (spin.value() - low) / (high - low)))
                spin.blockSignals(False)
                slider.blockSignals(False)
        self.refresh()

    def edited(self, key, value):
        source = self.source | {key: value}
        try:
            snapshot = self.host.update_source(source, expected_revision=self.revision)
        except (ValueError, RuntimeError) as exc:
            self.status.setText(str(exc))
            return
        self.apply_source(snapshot.source, snapshot.revision)
        self.status.setText("Geometry changed. Use Generate to update the mesh.")

    def refresh(self):
        try:
            p = validate(self.source)
        except ValueError as exc:
            self.summary.setText(str(exc))
            self.sketch.source = None
        else:
            throat_dia = p["throat_diameter_m"] * 1000.0
            cov_h = p["coverage_h_deg"]
            cov_v = p["coverage_v_deg"]
            len_mm = p["length_m"] * 1000.0
            self.summary.setText(
                f"OS-WG Waveguide · Throat Ø{throat_dia:.1f} mm · {cov_h:.0f}°H × {cov_v:.0f}°V · Depth {len_mm:.0f} mm"
            )
            self.sketch.source = p
        self.sketch.update()

    def event(self, event):
        if event.kind == "geometry_accepted":
            self.status.setText("Waveguide mesh accepted and ready to solve.")
        elif event.job is not None:
            self.status.setText(event.job.message)

    def set_operation_state(self, state):
        self.tabs.setEnabled(not state.active)

    def dispose(self):
        for key, spin in self.spins.items():
            spin.valueChanged.disconnect(self.connections[key])


def create_editor(parent, document_host):
    return WaveguideEditor(parent, document_host)
