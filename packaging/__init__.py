"""ClipMaker packaging and local-server helpers."""

# Keep the installed PyPA packaging modules accessible beside our build helpers.
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
