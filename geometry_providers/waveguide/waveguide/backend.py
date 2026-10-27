"""Cancellable backend and scoped physical-system assignments for the waveguide generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from threading import Event
from uuid import uuid4

from blab.generators import GeneratedGeometry, GeneratedMesh, GenerationResponse, generated_mesh_id
from blab.generators.base import GenerationCancelledError

from .parameters import validate


def configuration_patch(request):
    """Compile physical-system exterior region, boundaries, and velocity excitation for the waveguide."""
    prefix = request.document_id + "/"
    bem = generated_mesh_id(request.document_id, "exterior")
    system = request.configuration.get("physical_system") or {}
    existing_regions = system.get("regions", [])

    exterior = next((r["id"] for r in existing_regions if r["kind"] == "unbounded_air"), prefix + "exterior")
    regions = []
    if not any(r["id"] == exterior for r in existing_regions):
        regions.append(
            dict(
                id=exterior,
                name=f"{request.mesh_name} exterior air",
                kind="unbounded_air",
                mesh_ids=[bem],
            )
        )

    boundaries = [
        dict(
            id=prefix + "outside/driver",
            name=f"{request.mesh_name} throat diaphragm",
            region_id=exterior,
            group=dict(mesh_id=bem, dimension=2, name="driver"),
            kind="moving",
        ),
        dict(
            id=prefix + "outside/horn",
            name=f"{request.mesh_name} horn wall",
            region_id=exterior,
            group=dict(mesh_id=bem, dimension=2, name="horn"),
            kind="rigid",
        ),
        dict(
            id=prefix + "outside/baffle",
            name=f"{request.mesh_name} baffle",
            region_id=exterior,
            group=dict(mesh_id=bem, dimension=2, name="baffle"),
            kind="rigid",
        ),
    ]

    component_id = prefix + "driver"
    component = dict(
        id=component_id,
        name=f"{request.mesh_name} driver",
        kind="ideal_velocity_source",
        boundary_ids=[prefix + "outside/driver"],
        parameters={"motion_profile": "uniform"},
    )

    patch = {
        "regions": {"upsert": regions},
        "surface_assignments": {"upsert": boundaries},
        "component_assignments": {"upsert": [component]},
        "excitation_ports": {
            "upsert": [
                dict(
                    id=prefix + "velocity",
                    name=f"{request.mesh_name} velocity",
                    component_id=component_id,
                    kind="normal_velocity",
                )
            ]
        },
    }
    if component_id not in request.configuration.get("component_channels", {}):
        patch["component_channels"] = {"upsert": [{"id": component_id, "channel": "main"}]}
    return patch


class WaveguideSession:
    def __init__(self, request):
        self.request = request
        self.cancelled = Event()
        self.process = None

    def stop(self):
        self.cancelled.set()
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def generate(self, *, status_callback=None, stop_requested=None):
        def check_cancelled():
            if self.cancelled.is_set() or (stop_requested and stop_requested()):
                self.stop()
                raise GenerationCancelledError("Waveguide generation cancelled.")

        check_cancelled()
        p = validate(self.request.source)

        output = self.request.run_root.resolve() / ("waveguide_" + uuid4().hex)
        output.mkdir(parents=True)
        source = output / "source.json"
        source.write_text(json.dumps(p, indent=2), encoding="utf-8")

        if status_callback:
            status_callback("Generating waveguide geometry and meshing with Gmsh")

        log_path = output / "meshing.log"
        with log_path.open("w", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).with_name("worker.py")), str(source)],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                while True:
                    check_cancelled()
                    try:
                        code = self.process.wait(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                check_cancelled()
            finally:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait()
                self.process = None

        if code:
            details = log_path.read_text(encoding="utf-8")[-2000:]
            raise ValueError(f"Waveguide meshing failed. Details: {log_path}\n{details}")

        metadata = json.loads((output / "mesh_info.json").read_text(encoding="utf-8"))
        metadata.update(
            generator_version="0.1.0",
            units="m",
            source=p,
            model="Geddes Oblate Spheroidal Waveguide (OS-WG) with roll-off termination",
        )

        geometry = GeneratedGeometry(
            self.request.provider_id,
            output,
            None,
            (),
            source_path=source,
            meshes=(
                GeneratedMesh("exterior", "bem_surface", mesh_path=output / "exterior.msh"),
            ),
            provider_metadata=metadata,
        )
        return GenerationResponse(self.request.request_id, geometry, configuration_patch(self.request))


class WaveguideBackend:
    def create_session(self, request):
        return WaveguideSession(request)

    def restore(self, document):
        return None


def create_backend(**options):
    return WaveguideBackend()
