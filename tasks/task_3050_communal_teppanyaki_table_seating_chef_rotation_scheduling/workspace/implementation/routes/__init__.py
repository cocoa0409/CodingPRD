"""Route registration for the service-floor API."""

ALL_BLUEPRINTS = []


def register(app):
    from . import (venues, parties, tiers, tables, reservations, seatings,
                   chefs, shows, maintenance, sushi, ledger, protein, clock)

    for module in (clock, venues, parties, tiers, tables, reservations, seatings,
                   chefs, shows, maintenance, sushi, ledger, protein):
        app.register_blueprint(module.bp)
    return app