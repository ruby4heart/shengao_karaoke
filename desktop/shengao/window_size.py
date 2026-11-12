"""Window size on start: the usual size, made smaller only when the screen is smaller.

Shared by the real start (``app.main``) and the window checks, so the checks
try exactly the sizes a given screen would get.
"""
DEFAULT = (1460, 940)
MINIMUM = (900, 620)
MARGIN = 24          # room left around the window on a small screen
TASKBAR = 48         # Windows taskbar height in logical pixels (any scale)


def startup_geometry(width, height):
    """``(minimum, size)`` for a screen's available area in logical pixels."""
    minimum = (min(MINIMUM[0], width - MARGIN), min(MINIMUM[1], height - MARGIN))
    return minimum, (min(DEFAULT[0], width - MARGIN), min(DEFAULT[1], height - MARGIN))


def available(width, height, scale):
    """Logical area Windows leaves for windows on a screen of ``width`` × ``height``
    physical pixels at display scale ``scale`` (1.5 = 150 %), taskbar at the bottom."""
    return int(width / scale), int(height / scale) - TASKBAR
