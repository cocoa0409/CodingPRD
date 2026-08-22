"""Route blueprints, one module per resource group."""

from routes import (
    allocations,
    blends,
    bottling,
    clients,
    clock,
    contracts,
    dry_goods,
    intakes,
    lots,
    release_orders,
    ttb,
    vessels,
    work_orders,
)

BLUEPRINTS = (
    clock.bp,
    clients.bp,
    contracts.bp,
    vessels.bp,
    allocations.bp,
    intakes.bp,
    lots.bp,
    blends.bp,
    work_orders.bp,
    bottling.bp,
    dry_goods.bp,
    ttb.bp,
    release_orders.bp,
)
