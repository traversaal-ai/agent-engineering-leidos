"""Axis composition root.

The only package that imports all three layers. Everything else in the tree obeys
the dependency direction:

    frontend  ──HTTP──▶  backend  ──in-process──▶  ai_backend

`asgi.py` mounts the Frontend and Backend apps into one process; `__main__.py` is
the `python -m axis` entry point.
"""

__version__ = "0.1.0"
