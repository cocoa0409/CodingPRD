"""Blueprint registration for every resource group."""
from routes import (
    agreements,
    disputes,
    eligibility,
    employers,
    ledger,
    memberships,
    merchants,
    offers,
    ops,
    redemptions,
    reports,
    slots,
    statements,
)

BLUEPRINTS = (
    ops.bp,
    merchants.bp,
    agreements.bp,
    employers.bp,
    eligibility.bp,
    memberships.bp,
    offers.bp,
    slots.bp,
    redemptions.bp,
    disputes.bp,
    statements.bp,
    ledger.bp,
    reports.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
