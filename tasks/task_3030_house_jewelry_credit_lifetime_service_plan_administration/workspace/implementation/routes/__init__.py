"""Route registration: one module per resource group."""

from routes import (appraisals, clock, config, credit, customers, designs, diamonds,
                    ledger, lists, plans, purchases, refdata, registrations, repairs,
                    statements, stores, visits)

MODULES = (
    clock,
    stores,
    refdata,
    config,
    customers,
    diamonds,
    credit,
    plans,
    ledger,
    registrations,
    visits,
    repairs,
    appraisals,
    purchases,
    designs,
    statements,
    lists,
)


def register_all(app):
    for module in MODULES:
        module.register(app)