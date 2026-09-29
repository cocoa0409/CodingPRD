"""Blueprint registry. Every endpoint of PRD §4 lives in one of these modules."""

from routes import billing, blocks, catalog, contracts, leads, quotes, reservations

BLUEPRINTS = (
    catalog.bp,
    leads.bp,
    quotes.bp,
    contracts.bp,
    blocks.bp,
    reservations.bp,
    billing.bp,
)
