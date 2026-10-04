"""Route blueprints."""
from . import admin, agents, capacity, loads, settlements  # noqa: F401

BLUEPRINTS = (
    admin.bp,
    agents.bp,
    capacity.bp,
    loads.bp,
    settlements.bp,
)
