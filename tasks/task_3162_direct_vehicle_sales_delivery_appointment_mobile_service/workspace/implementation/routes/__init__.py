"""Route blueprints. Importing this package registers every endpoint."""

from routes import (  # noqa: F401
    buyers, catalog, delivery_appointments, finance, ops, orders, production, service,
)

ALL_BLUEPRINTS = [
    ops.bp,
    buyers.bp,
    catalog.bp,
    orders.bp,
    delivery_appointments.bp,
    finance.bp,
    production.bp,
    service.bp,
]