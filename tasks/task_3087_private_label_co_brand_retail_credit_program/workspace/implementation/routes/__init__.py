"""Route registration barrel."""
from . import (
    accounts,
    benefits,
    clock_routes,
    disputes,
    partners,
    programs,
    settlement,
    transfers,
)


def register_routes(app):
    partners.register(app)
    programs.register(app)
    accounts.register(app)
    settlement.register(app)
    disputes.register(app)
    benefits.register(app)
    transfers.register(app)
    clock_routes.register(app)