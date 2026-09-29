"""Flask blueprints, one module per resource group."""

from routes import (
    accounts,
    addresses,
    appointments,
    campaigns,
    claims,
    clock,
    crews,
    fallback,
    ledger,
    mdu,
    permits,
    poles,
    preorders,
    zones,
)

BLUEPRINTS = (
    clock.bp,
    campaigns.bp,
    zones.bp,
    addresses.bp,
    accounts.bp,
    mdu.bp,
    permits.bp,
    poles.bp,
    preorders.bp,
    crews.bp,
    appointments.bp,
    claims.bp,
    fallback.bp,
    ledger.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
