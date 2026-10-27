"""SI geometry, parameter bounds, validation, and field schema for the waveguide generator."""

from __future__ import annotations

import math
from typing import Any

if __package__:
    from .math_profiles import evaluate_horn_profile, generate_waveguide_cross_section_points
else:
    import runpy
    from pathlib import Path

    _math = runpy.run_path(str(Path(__file__).with_name("math_profiles.py")))
    evaluate_horn_profile = _math["evaluate_horn_profile"]
    generate_waveguide_cross_section_points = _math["generate_waveguide_cross_section_points"]

# key, label, unit, display multiplier, minimum, maximum, default, decimals
FIELDS = {
    "Throat": (
        ("throat_diameter_m", "Throat diameter", "mm", 1000, 10, 80, 25.4, 1),
        ("throat_angle_deg", "Throat entrance angle", "°", 1, 0, 30, 7.0, 1),
    ),
    "Horn Flare": (
        ("length_m", "Horn length", "mm", 1000, 20, 500, 120.0, 1),
        ("coverage_h_deg", "Horizontal coverage angle", "°", 1, 20, 140, 90.0, 1),
        ("coverage_v_deg", "Vertical coverage angle", "°", 1, 20, 140, 60.0, 1),
    ),
    "Termination & Baffle": (
        ("rolloff_radius_m", "Mouth roll-off radius", "mm", 1000, 0, 100, 30.0, 1),
        ("baffle_width_m", "Front baffle width", "mm", 1000, 50, 1200, 320.0, 1),
        ("baffle_height_m", "Front baffle height", "mm", 1000, 50, 1000, 260.0, 1),
    ),
    "Mesh Resolution": (
        ("mesh_size_throat_m", "Throat element size", "mm", 1000, 1, 30, 5.0, 1),
        ("mesh_size_mouth_m", "Mouth element size", "mm", 1000, 2, 60, 15.0, 1),
    ),
}

DEFAULTS: dict[str, float] = {f[0]: f[6] / f[3] for fields in FIELDS.values() for f in fields}


def compute_synchronized_profiles(
    p: dict[str, Any],
    num_horn_points: int = 36,
    num_rolloff_points: int = 12,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Compute synchronized (z, r) profiles for horizontal ('h') and vertical ('v') axes.

    Guarantees that both horizontal and vertical cross-sections share identical axial
    Z-coordinates at every ring index from the throat (z=0) through the horn flare (z=L)
    and around the C1 tangent-continuous mouth roll-off to the flat front baffle plane
    (z=z_baffle).
    """
    r_throat = p["throat_diameter_m"] / 2.0
    theta_in = math.radians(p["throat_angle_deg"])
    theta_cov_h = math.radians(p["coverage_h_deg"] / 2.0)
    theta_cov_v = math.radians(p["coverage_v_deg"] / 2.0)
    length = p["length_m"]
    rolloff_r = p["rolloff_radius_m"]

    h_throat = p.get("mesh_size_throat_m", 0.005)
    h_mouth = p.get("mesh_size_mouth_m", 0.015)
    gamma = min(1.5, max(1.0, math.sqrt(h_mouth / max(h_throat, 1e-4))))

    pts_h: list[tuple[float, float]] = []
    pts_v: list[tuple[float, float]] = []

    num_horn = max(4, int(num_horn_points))
    for i in range(num_horn):
        t = i / (num_horn - 1)
        z = length * (t**gamma)
        r_h, _ = evaluate_horn_profile("os_wg", z, length, r_throat, theta_in, theta_cov_h)
        r_v, _ = evaluate_horn_profile("os_wg", z, length, r_throat, theta_in, theta_cov_v)
        pts_h.append((z, r_h))
        pts_v.append((z, r_v))

    if rolloff_r > 1e-4 and num_rolloff_points > 0:
        r_mouth_h, slope_h = evaluate_horn_profile("os_wg", length, length, r_throat, theta_in, theta_cov_h)
        r_mouth_v, slope_v = evaluate_horn_profile("os_wg", length, length, r_throat, theta_in, theta_cov_v)
        beta_h = math.atan(max(1e-4, slope_h))
        beta_v = math.atan(max(1e-4, slope_v))
        beta_ref = max(beta_h, beta_v)

        dz_rolloff = rolloff_r * max(0.05, 1.0 - math.sin(beta_ref))
        z_baffle = length + dz_rolloff

        r_eff_h = dz_rolloff / max(1e-4, 1.0 - math.sin(beta_h))
        r_eff_v = dz_rolloff / max(1e-4, 1.0 - math.sin(beta_v))

        z_c_h = z_baffle - r_eff_h
        r_c_h = r_mouth_h + r_eff_h * math.cos(beta_h)

        z_c_v = z_baffle - r_eff_v
        r_c_v = r_mouth_v + r_eff_v * math.cos(beta_v)

        num_roll = max(2, int(num_rolloff_points))
        for j in range(1, num_roll + 1):
            tau = j / num_roll
            z_j = length + dz_rolloff * math.sin(0.5 * math.pi * tau)
            r_j_h = r_c_h - math.sqrt(max(0.0, r_eff_h**2 - (z_j - z_c_h) ** 2))
            r_j_v = r_c_v - math.sqrt(max(0.0, r_eff_v**2 - (z_j - z_c_v) ** 2))
            pts_h.append((z_j, r_j_h))
            pts_v.append((z_j, r_j_v))

    return pts_h, pts_v


def compute_baffle_azimuths_and_perimeter(
    baffle_w: float,
    baffle_h: float,
    n_quadrant: int = 10,
) -> tuple[list[float], list[tuple[float, float]]]:
    """Compute sorted azimuthal angles [0, 2*pi) that hit all 4 rectangle corners exactly."""
    wb2 = baffle_w / 2.0
    hb2 = baffle_h / 2.0
    alpha_c = math.atan2(hb2, wb2)

    n_quad = max(4, int(n_quadrant))
    n1 = max(2, round(n_quad * (alpha_c / (0.5 * math.pi))))
    n2 = max(2, n_quad - n1)

    q1 = [alpha_c * (i / n1) for i in range(n1)] + [
        alpha_c + (0.5 * math.pi - alpha_c) * (i / n2) for i in range(n2 + 1)
    ]
    # Mirror Q1 angles into all 4 quadrants
    angles: list[float] = []
    # Q1: [0, pi/2)
    angles.extend(q1[:-1])
    # Q2: [pi/2, pi)
    angles.extend([math.pi - a for a in reversed(q1[1:])])
    # Q3: [pi, 3*pi/2)
    angles.extend([math.pi + a for a in q1[:-1]])
    # Q4: [3*pi/2, 2*pi)
    angles.extend([2.0 * math.pi - a for a in reversed(q1[1:])])

    rect_pts: list[tuple[float, float]] = []
    for a in angles:
        ca = math.cos(a)
        sa = math.sin(a)
        rho = min(wb2 / max(abs(ca), 1e-12), hb2 / max(abs(sa), 1e-12))
        rect_pts.append((rho * ca, rho * sa))

    return angles, rect_pts


def get_profile_points(p: dict[str, Any], axis: str = "h") -> list[tuple[float, float]]:
    """Compute (z, r) profile points for horizontal ('h') or vertical ('v') cross section."""
    if "coverage_h_deg" in p and "coverage_v_deg" in p:
        pts_h, pts_v = compute_synchronized_profiles(p, num_horn_points=50, num_rolloff_points=15)
        return pts_h if axis == "h" else pts_v
    cov_deg = p["coverage_h_deg"] if axis == "h" else p["coverage_v_deg"]
    r_throat = p["throat_diameter_m"] / 2.0
    theta_in = math.radians(p["throat_angle_deg"])
    theta_cov = math.radians(cov_deg / 2.0)
    return generate_waveguide_cross_section_points(
        profile_kind="os_wg",
        length=p["length_m"],
        r_throat=r_throat,
        theta_in_rad=theta_in,
        theta_cov_rad=theta_cov,
        rolloff_radius=p["rolloff_radius_m"],
    )


def validate(source: dict[str, Any]) -> dict[str, float]:
    """Validate and sanitize source parameters against field boundaries."""
    if set(source) != set(DEFAULTS):
        missing = set(DEFAULTS) - set(source)
        extra = set(source) - set(DEFAULTS)
        raise ValueError(
            f"Waveguide settings mismatch. Missing: {missing}, Extra: {extra}. Restore supported source fields."
        )

    p: dict[str, float] = {}
    for fields in FIELDS.values():
        for key, label, unit, factor, low, high, _, _ in fields:
            value = source[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not low <= value * factor <= high:
                raise ValueError(f"{label} must be between {low} and {high} {unit}.")
            p[key] = float(value)

    # Cross-parameter sanity checks
    pts_h = get_profile_points(p, "h")
    pts_v = get_profile_points(p, "v")

    max_r_h = max(r for _, r in pts_h)
    max_r_v = max(r for _, r in pts_v)

    if p["baffle_width_m"] < 2.0 * max_r_h:
        min_w_mm = round(2000.0 * max_r_h, 1)
        raise ValueError(
            f"Front baffle width ({p['baffle_width_m']*1000:.1f} mm) must be at least the horn mouth width ({min_w_mm} mm)."
        )

    if p["baffle_height_m"] < 2.0 * max_r_v:
        min_h_mm = round(2000.0 * max_r_v, 1)
        raise ValueError(
            f"Front baffle height ({p['baffle_height_m']*1000:.1f} mm) must be at least the horn mouth height ({min_h_mm} mm)."
        )

    if p["mesh_size_mouth_m"] < p["mesh_size_throat_m"]:
        raise ValueError("Mouth mesh element size should be greater than or equal to throat element size.")

    return p
