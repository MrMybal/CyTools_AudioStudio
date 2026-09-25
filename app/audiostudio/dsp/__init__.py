"""Native DSP: the effect registry plus the processor families that register into it."""
from . import effects  # noqa: F401  (registry first)
from . import dynamics, filters, modulation, space, distortion, vocoder, stereo_tools, creative, mastering  # noqa: F401,E402
from . import spectral, rhythm, guitar, pitch, reverbs  # noqa: F401,E402
