"""Route registration: one blueprint per resource domain."""
from . import (
    aid,
    application_actions,
    applications,
    clock_routes,
    colleges,
    cycles,
    matches,
    outcomes,
    people,
    prep,
    referrals,
    verifications,
)

_MODULES = (
    clock_routes,
    cycles,
    colleges,
    people,
    referrals,
    prep,
    applications,
    application_actions,
    matches,
    aid,
    verifications,
    outcomes,
)


def register_blueprints(app):
    for module in _MODULES:
        app.register_blueprint(module.bp)
