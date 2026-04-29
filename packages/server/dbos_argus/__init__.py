"""dbos-argus — FastAPI backend for the Argus management console."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dbos-argus")
except PackageNotFoundError:
    # Source checkout that hasn't been installed (or installed without metadata).
    __version__ = "0.0.0.dev0"
