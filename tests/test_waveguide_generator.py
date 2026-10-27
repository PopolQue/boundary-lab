"""Integration tests for the native waveguide generator plugin and Gmsh meshing pipeline."""

from pathlib import Path

import meshio
from geometry_providers.waveguide.waveguide.backend import WaveguideBackend, configuration_patch
from geometry_providers.waveguide.waveguide.parameters import DEFAULTS
from geometry_providers.waveguide.waveguide.worker import build

from blab.generators.base import GenerationRequest
from blab.generators.catalog import bundled_provider_ids, provider_catalog


def test_bundled_provider_ids_includes_waveguide():
    """Verify blab.waveguide is present in first-party bundled allowlist."""
    assert "blab.waveguide" in bundled_provider_ids()


def test_catalog_discovers_waveguide_plugin():
    """Verify ProviderCatalog finds and registers blab.waveguide."""
    catalog = provider_catalog()
    catalog.scan()
    pkg = catalog.package("blab.waveguide") if "blab.waveguide" in catalog.enabled else next(
        p for p in catalog.packages if p.manifest and p.manifest.id == "blab.waveguide"
    )
    assert pkg.manifest.name == "Parametric Waveguide"
    assert pkg.manifest.version == "0.1.0"


def test_waveguide_worker_builds_watertight_bem_mesh(tmp_path: Path):
    """Verify worker produces a closed, watertight 3D BEM mesh with driver, horn, and baffle physical groups."""
    import numpy as np

    from blab.config import MeshConfig
    from blab.mesh_topology import analyze_exterior_mesh_topology

    info = build(DEFAULTS, tmp_path)
    assert info["triangles"] > 50
    assert info["nodes"] > 50
    assert info["mirror_axes"] == []

    mesh_file = tmp_path / "exterior.msh"
    assert mesh_file.is_file()

    m = meshio.read(str(mesh_file))
    assert "driver" in m.field_data
    assert "horn" in m.field_data
    assert "baffle" in m.field_data

    # Ensure cell types are triangles
    assert any(c.type == "triangle" and len(c.data) > 0 for c in m.cells)

    # Verify 100% watertight manifold topology (zero open edges, zero non-manifold edges)
    topology = analyze_exterior_mesh_topology((MeshConfig("waveguide", str(mesh_file), scale_factor=1.0),))
    assert topology.has_warnings is False
    assert topology.open_edge_count == 0
    assert topology.nonmanifold_edge_count == 0

    # Verify full 360-degree rectangular baffle bounds match baffle_width_m x baffle_height_m
    pts = np.asarray(m.points, dtype=float)
    assert np.isclose(np.min(pts[:, 0]), -DEFAULTS["baffle_width_m"] / 2.0, atol=1e-4)
    assert np.isclose(np.max(pts[:, 0]), DEFAULTS["baffle_width_m"] / 2.0, atol=1e-4)
    assert np.isclose(np.min(pts[:, 1]), -DEFAULTS["baffle_height_m"] / 2.0, atol=1e-4)
    assert np.isclose(np.max(pts[:, 1]), DEFAULTS["baffle_height_m"] / 2.0, atol=1e-4)


def test_waveguide_worker_asymmetric_coverage_and_baffle(tmp_path: Path):
    """Verify asymmetric 90x40 degree waveguide with 1.2x1.0m baffle matches design dimensions and is watertight."""
    import numpy as np

    from blab.config import MeshConfig
    from blab.mesh_topology import analyze_exterior_mesh_topology

    user_source = {
        "throat_diameter_m": 0.0305,
        "throat_angle_deg": 0.0,
        "length_m": 0.2854,
        "coverage_h_deg": 90.0,
        "coverage_v_deg": 40.0,
        "rolloff_radius_m": 0.0148,
        "baffle_width_m": 1.2,
        "baffle_height_m": 1.0,
        "mesh_size_throat_m": 0.03,
        "mesh_size_mouth_m": 0.06,
    }
    info = build(user_source, tmp_path)
    assert info["mouth_width_m"] > info["mouth_height_m"]

    mesh_file = tmp_path / "exterior.msh"
    topology = analyze_exterior_mesh_topology((MeshConfig("waveguide_asym", str(mesh_file), scale_factor=1.0),))
    assert topology.has_warnings is False
    assert topology.open_edge_count == 0
    assert topology.nonmanifold_edge_count == 0

    m = meshio.read(str(mesh_file))
    pts = np.asarray(m.points, dtype=float)
    assert np.isclose(np.min(pts[:, 0]), -0.6, atol=1e-4)
    assert np.isclose(np.max(pts[:, 0]), 0.6, atol=1e-4)
    assert np.isclose(np.min(pts[:, 1]), -0.5, atol=1e-4)
    assert np.isclose(np.max(pts[:, 1]), 0.5, atol=1e-4)

    from blab.mesh_clean import triangle_quality_warning
    from blab.mesh_quality import inspect_resource_vertices
    from blab.physical_model import MeshPurpose, MeshResource

    quality = triangle_quality_warning(m)
    assert not quality.has_warnings
    resource = MeshResource(id="wg", name="wg", file=str(mesh_file), purpose=MeshPurpose.BEM_SURFACE)
    assert inspect_resource_vertices(resource, m) is None


def test_waveguide_configuration_patch():
    """Verify physical model compiler patch produces exterior region and velocity source."""
    request = GenerationRequest(
        provider_id="blab.waveguide",
        document_id="doc_test",
        mesh_name="Horn1",
        source=DEFAULTS,
        run_root=Path("/tmp"),
        case_name="test_case",
    )
    patch = configuration_patch(request)

    assert "regions" in patch
    regions = patch["regions"]["upsert"]
    assert any(r["kind"] == "unbounded_air" for r in regions)

    assert "surface_assignments" in patch
    boundaries = patch["surface_assignments"]["upsert"]
    boundary_names = [b["name"] for b in boundaries]
    assert any("throat diaphragm" in name for name in boundary_names)
    assert any("horn wall" in name for name in boundary_names)

    assert "component_assignments" in patch
    components = patch["component_assignments"]["upsert"]
    assert components[0]["kind"] == "ideal_velocity_source"
    assert components[0]["boundary_ids"] == [request.document_id + "/outside/driver"]


def test_waveguide_backend_session_generate(tmp_path: Path):
    """Verify WaveguideBackend session executes and returns a complete GenerationResponse."""
    backend = WaveguideBackend()
    request = GenerationRequest(
        provider_id="blab.waveguide",
        document_id="doc_waveguide",
        mesh_name="WaveguideTest",
        source=DEFAULTS,
        run_root=tmp_path,
        case_name="horn_case",
    )
    session = backend.create_session(request)
    response = session.generate()

    assert response.request_id == request.request_id
    assert response.geometry is not None
    assert len(response.geometry.meshes) == 1
    assert response.geometry.meshes[0].purpose == "bem_surface"
    assert response.geometry.meshes[0].mesh_path.is_file()


def test_waveguide_compiles_cleanly_with_physical_system_compiler(tmp_path: Path):
    """Verify that stage_generation and PhysicalSystemCompiler compile without duplicate ID errors."""
    from dataclasses import replace

    from blab.generators.application import stage_generation
    from blab.generators.base import complete_generation
    from blab.physical_compiler import PhysicalSystemCompiler
    from blab.project.model import ProjectDocument, new_generator_document

    document = replace(new_generator_document("horn", provider_id="blab.waveguide"), id="doc_waveguide", source=DEFAULTS)
    project = ProjectDocument((document,), document.id)

    backend = WaveguideBackend()
    request = GenerationRequest(
        provider_id="blab.waveguide",
        document_id=document.id,
        mesh_name="Horn1",
        source=DEFAULTS,
        run_root=tmp_path,
        case_name="horn_case",
    )
    session = backend.create_session(request)
    response = session.generate()

    from blab.exterior_preparation import prepare_exterior_system

    completed = complete_generation(request, response)
    candidate = stage_generation(project, {}, completed)
    compiled = PhysicalSystemCompiler().compile(candidate.physical_system)
    assert len(compiled.regions) == 1
    assert len(compiled.components) == 1
    assert compiled.components[0].id == f"{document.id}/driver"

    prepared = prepare_exterior_system(
        compiled,
        stitch_tolerance_mm=0.25,
        symmetry_mode="off",
        output_root=tmp_path / "prepared",
    )
    assert len(prepared.regions) == 1



def test_waveguide_editor_instantiation():
    """Verify WaveguideEditor widget creates cleanly with host mock."""
    from geometry_providers.waveguide.waveguide.editor import WaveguideEditor
    from PySide6.QtWidgets import QApplication, QWidget

    _app = QApplication.instance() or QApplication([])

    class DummyServices:
        def subscribe(self, callback):
            pass

    class DummyHost:
        def __init__(self):
            self.services = DummyServices()

        def update_source(self, source, expected_revision=""):
            from blab.generators.host import SourceSnapshot

            return SourceSnapshot(source, "rev1", DEFAULTS)

    parent = QWidget()
    host = DummyHost()
    editor = WaveguideEditor(parent, host)
    editor.apply_source(DEFAULTS, "rev0")

    assert "OS-WG Waveguide" in editor.summary.text()
    assert editor.sketch.source is not None


def test_waveguide_editor_3d_sketch_interaction():
    """Verify Realtime3DSketch handles mouse orbit, zoom, and view switching."""
    from geometry_providers.waveguide.waveguide.editor import WaveguideEditor
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication, QWidget

    _app = QApplication.instance() or QApplication([])

    class DummyHost:
        class DummyServices:
            def subscribe(self, callback):
                pass

        def __init__(self):
            self.services = self.DummyServices()

        def update_source(self, source, expected_revision=""):
            from blab.generators.host import SourceSnapshot

            return SourceSnapshot(source, "rev1", DEFAULTS)

    parent = QWidget()
    editor = WaveguideEditor(parent, DummyHost())
    editor.apply_source(DEFAULTS, "rev0")
    sketch = editor.sketch

    assert sketch.view_mode == "3d"
    initial_yaw = sketch.yaw_deg
    initial_pitch = sketch.pitch_deg

    # Simulate mouse drag to orbit
    sketch.last_mouse_pos = QPoint(100, 100)
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(120.0, 110.0),
        QPointF(120.0, 110.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    sketch.mouseMoveEvent(move_event)
    assert sketch.yaw_deg != initial_yaw
    assert sketch.pitch_deg != initial_pitch

    # Simulate mouse wheel to zoom
    initial_zoom = sketch.zoom
    wheel_event = QWheelEvent(
        QPoint(100, 100),
        QPoint(100, 100),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    sketch.wheelEvent(wheel_event)
    assert sketch.zoom > initial_zoom

    # Toggle to 2D and back
    editor.btn_2d.click()
    assert sketch.view_mode == "2d"
    editor.btn_3d.click()
    assert sketch.view_mode == "3d"
    editor.btn_reset.click()
    assert sketch.zoom == 1.0


