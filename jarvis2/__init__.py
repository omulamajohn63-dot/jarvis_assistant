"""Jarvis.

The assistant's own package: the skills, the safety layer, the AI layer, and the
core that ties them together. The dashboard lives beside it in `web/`.

Entry points:

    python -m jarvis2            the terminal assistant
    python -m jarvis2 --browser  the dashboard
"""

from jarvis2.config.settings import Settings, load_settings

__all__ = ["Settings", "load_settings", "__version__"]

__version__ = "2.0.0"
