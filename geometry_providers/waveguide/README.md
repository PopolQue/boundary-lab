# Parametric Acoustic Waveguide Generator

Clean-room, native Python and Gmsh OpenCASCADE parametric acoustic waveguide geometry generator for Boundary Lab.

## Overview

This plugin generates axisymmetric and elliptical constant-directivity loudspeaker waveguides and horns directly within Boundary Lab without requiring external tools or Wine.

All profiles are derived from published academic literature:
- **Dr. Earl Geddes' Oblate Spheroidal Waveguide (OS-WG)**: Constant-directivity expansion matching compression driver wavefront curvature.
- **Continuous Mouth Roll-Off**: Smooth curvature-continuous lip transition eliminating edge diffraction.
- **Integrated Baffle Flange**: Planar baffle integration for mounting in loudspeaker enclosures.

## Boundary Groups

The generated BEM mesh provides standard Boundary Lab surface groups:
- `driver`: Throat entrance diaphragm (moving ideal velocity source).
- `horn`: Inner waveguide flare wall (rigid boundary).
- `baffle`: Outer mouth roll-off and baffle surface (rigid boundary).

## Compatibility

- **Platforms**: macOS (Apple Silicon & Intel), Linux, Windows.
- **Symmetry**: Pre-configured for Quarter (XY) symmetry solving in BEAT Engine.
- **Dependencies**: Native Python and `gmsh` package bundled with Boundary Lab. Zero Wine or external binaries required.
