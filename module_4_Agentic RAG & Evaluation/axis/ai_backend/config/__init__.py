"""Configuration and secrets, read once from the environment.

`Settings` is imported by the AI Backend and the Backend. The Frontend gets
`FrontendSettings`, which structurally cannot hold a secret — see the module
docstring in `settings.py`.
"""

from ai_backend.config.settings import (
    FrontendSettings,
    Settings,
    for_frontend,
    get_settings,
)

__all__ = ["FrontendSettings", "Settings", "for_frontend", "get_settings"]
