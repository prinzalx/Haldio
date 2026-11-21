"""Haldio — PDF to audiobook converter."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("haldio")
except PackageNotFoundError:  # source checkout without installed metadata
    __version__ = "0.0.0"
