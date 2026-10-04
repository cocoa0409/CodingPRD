"""Route package."""

from . import (agencies, agents, call_sessions, carriers, complaints,
               enrollments, ledger, members, plans, platform, scopes)

MODULES = (
    platform,
    agencies,
    carriers,
    agents,
    members,
    scopes,
    call_sessions,
    plans,
    enrollments,
    ledger,
    complaints,
)


def register_all(app):
    for module in MODULES:
        module.register(app)