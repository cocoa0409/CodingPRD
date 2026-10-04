"""Route registration: one blueprint per resource group."""

from routes import (
    agreements,
    clock,
    cohorts,
    invoices,
    interviews,
    outcomes,
    partners,
    placement_actions,
    placements,
    satisfaction,
    stipend_actions,
    stipends,
    students,
)

MODULES = (
    partners,
    students,
    cohorts,
    agreements,
    placements,
    placement_actions,
    interviews,
    stipends,
    stipend_actions,
    satisfaction,
    invoices,
    outcomes,
    clock,
)


def register_routes(app):
    for module in MODULES:
        app.register_blueprint(module.bp)
