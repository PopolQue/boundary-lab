"""Parametric acoustic waveguide geometry generator for Boundary Lab."""

from .backend import WaveguideBackend, create_backend
from .editor import WaveguideEditor, create_editor
from .parameters import DEFAULTS, FIELDS, validate

__all__ = [
    "DEFAULTS",
    "FIELDS",
    "WaveguideBackend",
    "WaveguideEditor",
    "create_backend",
    "create_editor",
    "validate",
]
