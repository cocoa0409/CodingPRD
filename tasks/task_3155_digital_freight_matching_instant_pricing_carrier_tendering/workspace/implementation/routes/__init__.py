"""Route registration. One module per resource group, all mounted here."""

from routes import (
    cmd, facilities, carriers, equipment, shippers, contracts, loads, quotes,
    bookings, appointments, detention, tracking, events, claims, settlements,
)


def register_routes(app):
    cmd.register(app)
    shippers.register(app)
    carriers.register(app)
    equipment.register(app)
    facilities.register(app)
    contracts.register(app)
    loads.register(app)
    quotes.register(app)
    bookings.register(app)
    appointments.register(app)
    detention.register(app)
    tracking.register(app)
    events.register(app)
    claims.register(app)
    settlements.register(app)
    return app