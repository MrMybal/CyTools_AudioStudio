"""CyUI for Python: the Dear ImGui interface library of the Cy* applications (CyDAW 2, Shaderixel,
CyEngineHub), ported from D:/_Project/CyImgui_Interface for imgui-bundle.

    from gui import cyui
    cyui.apply('mid-grey', 'compact', dpi)       # theme, density, DPI (after the context exists)
    cyui.load_fonts()                            # in the font-loading callback
    if cyui.primary_button('Export'): ...
    cyui.icon_button(cyui.icon.play, 'Play (Space)', playing)
    cyui.render_notifications()                  # at the end of the frame

Rules (docs/AI_GUIDE.md of CyUI): colours by palette role only, sizes through dp() or the style,
one primary button per view, icon buttons with tooltips naming the action and its shortcut,
property tables in settings and inspectors, empty panels that say why, visible feedback.
"""
from .theme import *          # noqa: F401,F403
from .theme import THEMES, DEFAULT_THEME, DENSITIES, PALETTE_FIELDS, Palette, Theme, Metrics
from .widgets import *        # noqa: F401,F403
from .layout import *         # noqa: F401,F403
from . import icons as icon   # noqa: F401
