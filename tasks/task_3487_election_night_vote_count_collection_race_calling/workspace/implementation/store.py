"""In-memory store (PRD: storage is in-memory dicts keyed by id; the store
starts empty on every boot — no seeding of any entity)."""
import itertools

_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion counter; used as the final tie-break wherever the
    spec orders by created_at (ties are possible on a shared logical clock)."""
    return next(_seq)


TABLES = [
    "events",
    "counties",
    "contests",
    "links",       # ContestCounty
    "candidates",
    "feeds",       # FeedSource
    "stringers",
    "assignments",
    "reports",     # VoteReport
    "calls",       # RaceCall
    "recounts",    # RecountCase
    "coverages",   # CoverageDecision
    "customers",   # MediaCustomer
    "deliveries",  # ResultDelivery
    "invoices",    # MediaInvoice
]

db = {name: {} for name in TABLES}
