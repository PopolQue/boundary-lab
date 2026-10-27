"""Watertight 3D BEM meshing engine for parametric acoustic waveguides."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import meshio
import numpy as np

if __package__:
    from .parameters import (
        compute_baffle_azimuths_and_perimeter,
        compute_synchronized_profiles,
        validate,
    )
else:
    import runpy

    _params = runpy.run_path(str(Path(__file__).with_name("parameters.py")))
    compute_baffle_azimuths_and_perimeter = _params["compute_baffle_azimuths_and_perimeter"]
    compute_synchronized_profiles = _params["compute_synchronized_profiles"]
    validate = _params["validate"]


def orient_closed(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Orient a single connected watertight BEM shell towards exterior air."""
    triangles = triangles.copy()
    edges: dict[tuple[int, int], list[tuple[int, bool]]] = {}
    for i, tri in enumerate(triangles):
        for a, b in zip(tri, np.roll(tri, -1), strict=True):
            edges.setdefault((min(int(a), int(b)), max(int(a), int(b))), []).append((i, int(a) < int(b)))
    if any(len(adjacent) != 2 for adjacent in edges.values()):
        raise ValueError("Generated exterior waveguide shell is not watertight.")
    neighbors: list[list[tuple[int, bool]]] = [[] for _ in triangles]
    for (a, sign_a), (b, sign_b) in edges.values():
        neighbors[a].append((b, sign_a == sign_b))
        neighbors[b].append((a, sign_a == sign_b))
    flips = {0: False}
    stack = [0]
    while stack:
        a = stack.pop()
        for b, opposite in neighbors[a]:
            flip = flips[a] ^ opposite
            if b in flips:
                if flips[b] != flip:
                    raise ValueError("Generated exterior waveguide shell is not orientable.")
            else:
                flips[b] = flip
                stack.append(b)
    if len(flips) != len(triangles):
        raise ValueError("Generated exterior waveguide shell is disconnected.")
    ids = [i for i, flip in flips.items() if flip]
    triangles[ids] = triangles[ids][:, [0, 2, 1]]
    a, b, c = points[triangles].transpose(1, 0, 2)
    if np.einsum("ij,ij->i", a, np.cross(b, c)).sum() < 0:
        triangles = triangles[:, [0, 2, 1]]
    return triangles


def build(source: dict[str, Any], output_dir: Path | str) -> dict[str, Any]:
    """Generate a closed, watertight 3D BEM surface mesh for the parametric waveguide."""
    p = validate(source)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mesh_file = output_dir / "exterior.msh"
    info_file = output_dir / "mesh_info.json"

    r_throat = p["throat_diameter_m"] / 2.0
    length = p["length_m"]
    rolloff_r = p["rolloff_radius_m"]
    baffle_w = p["baffle_width_m"]
    baffle_h = p["baffle_height_m"]
    h_throat = p["mesh_size_throat_m"]
    h_mouth = p["mesh_size_mouth_m"]
    h_avg = 0.5 * (h_throat + h_mouth)

    # Estimate mouth extent to choose adaptive axial and azimuthal counts
    pts_h_est, pts_v_est = compute_synchronized_profiles(p, num_horn_points=16, num_rolloff_points=6)
    r_x_lip_est = pts_h_est[-1][1]
    r_y_lip_est = pts_v_est[-1][1]

    horn_arc_est = math.hypot(length, max(r_x_lip_est, r_y_lip_est) - r_throat)
    num_horn_points = max(14, min(42, round(horn_arc_est / max(h_avg, 0.002))))
    num_rolloff_points = (
        max(5, min(14, round((0.5 * math.pi * rolloff_r) / max(h_avg, 0.002))))
        if rolloff_r > 1e-4
        else 0
    )

    pts_h, pts_v = compute_synchronized_profiles(
        p,
        num_horn_points=num_horn_points,
        num_rolloff_points=num_rolloff_points,
    )

    z_baffle, r_x_lip = pts_h[-1]
    _, r_y_lip = pts_v[-1]

    # Ensure at least a 3 mm flange margin around the lip so baffle triangles are never degenerate
    baffle_w_eff = max(baffle_w, 2.0 * r_x_lip + 0.006)
    baffle_h_eff = max(baffle_h, 2.0 * r_y_lip + 0.006)

    quarter_mouth_arc = 0.25 * math.pi * (r_x_lip + r_y_lip)
    quarter_throat_arc = 0.5 * math.pi * r_throat
    n_quadrant = max(
        8,
        min(
            24,
            max(
                round(quarter_mouth_arc / max(h_mouth, 0.002)),
                round(quarter_throat_arc / max(h_throat, 0.001)),
            ),
        ),
    )

    angles, rect_pts = compute_baffle_azimuths_and_perimeter(baffle_w_eff, baffle_h_eff, n_quadrant=n_quadrant)
    n_theta = len(angles)
    cos_a = np.array([math.cos(a) for a in angles], dtype=np.float64)
    sin_a = np.array([math.sin(a) for a in angles], dtype=np.float64)
    rect_x = np.array([pt[0] for pt in rect_pts], dtype=np.float64)
    rect_y = np.array([pt[1] for pt in rect_pts], dtype=np.float64)

    rings: list[np.ndarray] = []
    strip_tags: list[int] = []  # physical group tag for each strip between consecutive rings

    def make_ellipse_ring(rx: float, ry: float, z: float) -> np.ndarray:
        ring = np.empty((n_theta, 3), dtype=np.float64)
        ring[:, 0] = rx * cos_a
        ring[:, 1] = ry * sin_a
        ring[:, 2] = z
        return ring

    # 1. Throat diaphragm rings (tag 1: "driver") at z = 0
    n_driver_rings = max(1, min(6, round(r_throat / max(h_throat, 0.001))))
    for j in range(1, n_driver_rings + 1):
        r_j = r_throat * (j / n_driver_rings)
        rings.append(make_ellipse_ring(r_j, r_j, 0.0))
        if j > 1:
            strip_tags.append(1)

    # 2. Inner horn flare + mouth roll-off rings (tag 2: "horn")
    for k in range(1, len(pts_h)):
        z_k, rx_k = pts_h[k]
        _, ry_k = pts_v[k]
        rings.append(make_ellipse_ring(rx_k, ry_k, z_k))
        strip_tags.append(2)

    # 3. Front rectangular baffle face rings (tag 3: "baffle") at z = z_baffle
    lip_x = r_x_lip * cos_a
    lip_y = r_y_lip * sin_a
    baffle_span = max(0.5 * baffle_w_eff - r_x_lip, 0.5 * baffle_h_eff - r_y_lip)
    n_baffle_rings = max(2, min(12, round(baffle_span / max(h_mouth, 0.002))))
    for j in range(1, n_baffle_rings + 1):
        u = j / n_baffle_rings
        ring = np.empty((n_theta, 3), dtype=np.float64)
        ring[:, 0] = (1.0 - u) * lip_x + u * rect_x
        ring[:, 1] = (1.0 - u) * lip_y + u * rect_y
        ring[:, 2] = z_baffle
        rings.append(ring)
        strip_tags.append(3)

    # 4. Rectangular baffle outer rim & contoured rear horn shell (tag 3: "baffle")
    t_flange = max(0.004, min(0.012, 0.15 * length))
    t_wall = 0.002  # 2 mm radial shell thickness (< 3 mm minimum flange margin)
    z_flange_back = z_baffle - t_flange

    # Outer rim back edge at z = z_flange_back
    rim_back = np.empty((n_theta, 3), dtype=np.float64)
    rim_back[:, 0] = rect_x
    rim_back[:, 1] = rect_y
    rim_back[:, 2] = z_flange_back
    rings.append(rim_back)
    strip_tags.append(3)

    # Rear of baffle flange stepping inward to outer horn wall at z = z_flange_back
    outer_lip_x = (r_x_lip + t_wall) * cos_a
    outer_lip_y = (r_y_lip + t_wall) * sin_a
    n_back_flange = max(2, n_baffle_rings // 2)
    for j in range(1, n_back_flange + 1):
        u = j / n_back_flange
        ring = np.empty((n_theta, 3), dtype=np.float64)
        ring[:, 0] = (1.0 - u) * rect_x + u * outer_lip_x
        ring[:, 1] = (1.0 - u) * rect_y + u * outer_lip_y
        ring[:, 2] = z_flange_back
        rings.append(ring)
        strip_tags.append(3)

    # Contoured outer horn wall stepping from mouth back to throat (z = -t_flange)
    rear_indices = list(range(len(pts_h) - 2, 0, -2))
    if not rear_indices or rear_indices[-1] != 0:
        rear_indices.append(0)
    for k in rear_indices:
        z_k, rx_k = pts_h[k]
        _, ry_k = pts_v[k]
        rings.append(make_ellipse_ring(rx_k + t_wall, ry_k + t_wall, z_k - t_flange))
        strip_tags.append(3)

    # Rear throat cap rings at z = -t_flange
    r_rear_throat = r_throat + t_wall
    if n_driver_rings > 1:
        for j in range(n_driver_rings - 1, 0, -1):
            r_j = r_rear_throat * (j / n_driver_rings)
            rings.append(make_ellipse_ring(r_j, r_j, -t_flange))
            strip_tags.append(3)

    # Assemble vertices: [north_pole, *rings, south_pole]
    num_rings = len(rings)
    north_pole = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
    south_pole = np.array([[0.0, 0.0, -t_flange]], dtype=np.float64)
    points = np.vstack([north_pole, *rings, south_pole])
    south_pole_idx = 1 + num_rings * n_theta

    tri_list: list[tuple[int, int, int]] = []
    tag_list: list[int] = []

    def v_idx(ring_idx: int, sector_idx: int) -> int:
        return 1 + ring_idx * n_theta + (sector_idx % n_theta)

    # North Pole cap (tag 1: "driver")
    for s in range(n_theta):
        tri_list.append((0, v_idx(0, s), v_idx(0, s + 1)))
        tag_list.append(1)

    # Quad strips between consecutive rings
    for m in range(num_rings - 1):
        tag = strip_tags[m]
        for s in range(n_theta):
            p00 = v_idx(m, s)
            p01 = v_idx(m, s + 1)
            p10 = v_idx(m + 1, s)
            p11 = v_idx(m + 1, s + 1)

            # Split quad along the shorter diagonal for best triangle quality
            d1 = float(np.sum((points[p00] - points[p11]) ** 2))
            d2 = float(np.sum((points[p10] - points[p01]) ** 2))
            if d1 <= d2:
                tri_list.append((p00, p10, p11))
                tri_list.append((p00, p11, p01))
            else:
                tri_list.append((p00, p10, p01))
                tri_list.append((p10, p11, p01))
            tag_list.append(tag)
            tag_list.append(tag)

    # South Pole cap (tag 3: "baffle")
    last_ring = num_rings - 1
    for s in range(n_theta):
        tri_list.append((v_idx(last_ring, s), south_pole_idx, v_idx(last_ring, s + 1)))
        tag_list.append(3)

    triangles = np.asarray(tri_list, dtype=np.int64)
    tags = np.asarray(tag_list, dtype=np.int32)

    # Verify watertightness and orient all normals outward into exterior air
    triangles = orient_closed(points, triangles)

    mesh = meshio.Mesh(
        points=points,
        cells=[("triangle", triangles)],
        cell_data={"gmsh:physical": [tags], "gmsh:geometrical": [tags]},
        field_data={
            "driver": np.array([1, 2], dtype=np.int32),
            "horn": np.array([2, 2], dtype=np.int32),
            "baffle": np.array([3, 2], dtype=np.int32),
        },
    )
    meshio.write(mesh_file, mesh, file_format="gmsh22", binary=False)

    info = {
        "generator": "blab.waveguide",
        "version": "0.1.0",
        "nodes": int(len(points)),
        "triangles": int(len(triangles)),
        "throat_diameter_m": p["throat_diameter_m"],
        "length_m": length,
        "mouth_width_m": 2.0 * r_x_lip,
        "mouth_height_m": 2.0 * r_y_lip,
        "baffle_width_m": p["baffle_width_m"],
        "baffle_height_m": p["baffle_height_m"],
        "mirror_axes": [],
    }
    info_file.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <source.json>")
    src_file = Path(sys.argv[1])
    build(json.loads(src_file.read_text(encoding="utf-8")), src_file.parent)
