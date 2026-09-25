"""Operation handlers, registered on the Core runtime by tool.create_runtime."""
from .common import Services


def register_all(runtime):
    services = Services(runtime)
    from . import processing, generation, voices, maintenance
    processing.register(runtime, services)
    generation.register(runtime, services)
    voices.register(runtime, services)
    maintenance.register(runtime, services)
    return services
