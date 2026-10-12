"""The Overruled Register bundle (exported from recourse-sci-pool; see REGISTER.md there)."""
from . import register, register_guard, overlay


def load(path=None):
    import os
    return register.Register.load(path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "register_slim.json"))


def load_overlay(path=None):
    import os
    return overlay.Overlay.load(path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay_slim.json"))
