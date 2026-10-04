"""Blueprint registry."""
from . import (
    agents,
    cases,
    change_orders,
    clock,
    closing,
    disbursements,
    disputes,
    engagements,
    listing_events,
    projects,
    vendors,
)

ALL_BPS = [
    clock.bp,
    agents.bp,
    vendors.bp,
    cases.bp,
    projects.bp,
    engagements.bp,
    disbursements.bp,
    change_orders.bp,
    disputes.bp,
    listing_events.bp,
    closing.bp,
]
