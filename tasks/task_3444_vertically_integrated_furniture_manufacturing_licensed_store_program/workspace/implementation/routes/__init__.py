"""Blueprint registry."""
from routes import (
    appointments, claims, clock, cycles, dcs, factories, licensees, orders,
    parts, product_lines, retail_accounts, territories,
)

ALL_BLUEPRINTS = [
    clock.bp,
    factories.bp,
    product_lines.bp,
    licensees.bp,
    territories.bp,
    retail_accounts.bp,
    dcs.bp,
    cycles.bp,
    orders.bp,
    appointments.bp,
    claims.bp,
    parts.bp,
]
