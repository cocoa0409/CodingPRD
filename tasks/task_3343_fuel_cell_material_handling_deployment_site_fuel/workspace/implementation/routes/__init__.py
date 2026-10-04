"""Route registration: one blueprint per resource group."""

from . import (
    agreements_r, assessments_r, availability_r, claims_r, clock_r,
    contracts_r, downtime_r, events_r, fueling_r, invoices_r, permits_r,
    plans_r, sites_r, stations_r, technicians_r, training_r,
)

_MODULES = (
    clock_r, sites_r, assessments_r, contracts_r, stations_r, permits_r,
    technicians_r, plans_r, events_r, agreements_r, downtime_r, fueling_r,
    invoices_r, availability_r, claims_r, training_r,
)


def register_routes(app):
    for mod in _MODULES:
        app.register_blueprint(mod.bp)
