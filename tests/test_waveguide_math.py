"""Unit tests for clean-room parametric waveguide mathematical profile curves."""

import math

import pytest
from geometry_providers.waveguide.waveguide.math_profiles import (
    oswg_profile_parameters,
    oswg_radius_and_slope,
    rolloff_termination,
)
from geometry_providers.waveguide.waveguide.parameters import DEFAULTS, get_profile_points, validate


def test_oswg_throat_matching():
    """Verify that OS-WG matches the throat radius and exit angle exactly at z=0."""
    r_throat = 0.0254 / 2.0  # 12.7 mm
    theta_in = math.radians(7.0)
    theta_cov = math.radians(45.0)  # 90 deg coverage

    b, c, z_t = oswg_profile_parameters(r_throat, theta_in, theta_cov)
    r_0, slope_0 = oswg_radius_and_slope(0.0, b, c, z_t)

    assert math.isclose(r_0, r_throat, rel_tol=1e-7)
    assert math.isclose(slope_0, math.tan(theta_in), rel_tol=1e-5)


def test_oswg_asymptotic_coverage_angle():
    """Verify that at large z, OS-WG slope approaches tan(theta_cov)."""
    r_throat = 0.0127
    theta_in = math.radians(7.0)
    theta_cov = math.radians(40.0)

    b, c, z_t = oswg_profile_parameters(r_throat, theta_in, theta_cov)
    _, slope_large_z = oswg_radius_and_slope(100.0, b, c, z_t)

    assert math.isclose(slope_large_z, math.tan(theta_cov), rel_tol=1e-3)


def test_rolloff_termination_continuity():
    """Verify that the mouth roll-off is tangent to the horn mouth at the join."""
    z_mouth = 0.12
    r_mouth = 0.08
    slope_mouth = math.tan(math.radians(35.0))
    rolloff_radius = 0.03

    points = rolloff_termination(z_mouth, r_mouth, slope_mouth, rolloff_radius, num_points=20)
    assert len(points) == 20

    # First point should be adjacent to (z_mouth, r_mouth)
    z1, r1 = points[0]
    dz = z1 - z_mouth
    dr = r1 - r_mouth
    initial_slope = dr / dz
    assert math.isclose(initial_slope, slope_mouth, rel_tol=0.08)

    # Last point should be perpendicular to Z (dz/dr -> 0)
    z_last, r_last = points[-1]
    assert z_last > z_mouth
    assert r_last > r_mouth


def test_parameter_validation_success():
    """Valid parameters pass validation without error."""
    valid = validate(DEFAULTS)
    assert valid["throat_diameter_m"] == 0.0254
    assert valid["length_m"] == 0.12


def test_parameter_validation_out_of_bounds():
    """Values outside physical limits raise ValueError."""
    bad_source = DEFAULTS.copy()
    bad_source["throat_diameter_m"] = 0.5  # 500 mm (too large)
    with pytest.raises(ValueError, match="Throat diameter"):
        validate(bad_source)


def test_parameter_baffle_must_fit_mouth():
    """Baffle width smaller than mouth width raises ValueError."""
    bad_source = DEFAULTS.copy()
    bad_source["baffle_width_m"] = 0.05  # 50 mm (smaller than mouth)
    with pytest.raises(ValueError, match="Front baffle width"):
        validate(bad_source)


def test_get_profile_points_generates_points():
    pts_h = get_profile_points(DEFAULTS, "h")
    pts_v = get_profile_points(DEFAULTS, "v")

    assert len(pts_h) > 20
    assert len(pts_v) > 20
    assert pts_h[0][0] == 0.0  # Starts at throat z=0
    assert math.isclose(pts_h[0][1], DEFAULTS["throat_diameter_m"] / 2.0, rel_tol=1e-5)
