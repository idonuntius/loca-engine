"""loca-engine: Location Engine for Loca."""

# Single source of truth for the engine version: pyproject reads it (hatch dynamic
# version), `/health` reports it, and the build script names the release tarball with it.
__version__ = "0.1.3"
