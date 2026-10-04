"""Route registry — imports every resource group module and registers it."""

from routes import (  # noqa: F401
    platform, terminals, state_authorities, carriers, corridors,
    workforce, safety, readiness, run_plans, containers, commitments,
    service_windows, remote_support, incidents, maintenance, engagements,
    holds, fleet_units, security, clause_variants, agreement_codes, testing,
)

MODULES = (
    platform, terminals, state_authorities, carriers, corridors,
    workforce, safety, readiness, run_plans, containers, commitments,
    service_windows, remote_support, incidents, maintenance, engagements,
    holds, fleet_units, security, clause_variants, agreement_codes, testing,
)


def register_all(app):
    for module in MODULES:
        module.register(app)