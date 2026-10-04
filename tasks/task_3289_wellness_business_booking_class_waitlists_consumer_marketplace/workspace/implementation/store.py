"""In-memory entity store.

The store starts EMPTY on every process boot.  Nothing here seeds, preloads or
hardcodes entity data: every record any test needs is constructed by that test
through the declared API surface.  There is no persistence of any kind — no
SQLite file, no JSON dump, no external backend.
"""

from core import LOGICAL_START

# Logical clock cell (shared with core.now()).
CLOCK = {"now": LOGICAL_START}

# One dict per entity type, keyed by id.  All start empty.
STUDIOS = {}
TIERS = {}              # keyed by tier name
TIER_BY_ID = {}         # id -> tier name
SUBSCRIPTIONS = {}
STAFF_MEMBERS = {}
CLIENTS = {}
CLASS_TEMPLATES = {}
CLASS_SESSIONS = {}
BOOKINGS = {}
WAITLIST_ENTRIES = {}
MEMBERSHIPS = {}
CLASS_PACKS = {}
BENEFIT_NETWORKS = {}   # keyed by network_code
COMMISSION_ENTRIES = {}
PAYROLL_PERIODS = {}
PORTABILITY_REQUESTS = {}

# Per-studio monotonic creation counter for bookings (creation_seq).
BOOKING_SEQ = {}

# Test-driving injectors: discounts applied to the next pack-funded bookings on
# a pack, populated only by the operator entitlement injector.  Empty at boot.
PACK_ZERO_DISCOUNTS = {}

# Records of the clock effects that fired, used when several transitions
# become due at once so they fire in the declared lifecycle order.
FIRED = []

COLLECTIONS = {
    "studios": STUDIOS,
    "subscriptions": SUBSCRIPTIONS,
    "staff_members": STAFF_MEMBERS,
    "clients": CLIENTS,
    "class_templates": CLASS_TEMPLATES,
    "class_sessions": CLASS_SESSIONS,
    "bookings": BOOKINGS,
    "waitlist_entries": WAITLIST_ENTRIES,
    "memberships": MEMBERSHIPS,
    "class_packs": CLASS_PACKS,
    "benefit_networks": BENEFIT_NETWORKS,
    "commission_entries": COMMISSION_ENTRIES,
    "payroll_periods": PAYROLL_PERIODS,
    "portability_requests": PORTABILITY_REQUESTS,
    "subscription_tiers": TIERS,
}


def reset():
    """Clear every collection.  Present for completeness only: boot code never
    calls this, because the module-level dicts are already empty at import."""
    for mapping in COLLECTIONS.values():
        mapping.clear()
    BOOKING_SEQ.clear()
    PACK_ZERO_DISCOUNTS.clear()


def next_creation_seq(studio_id):
    current = BOOKING_SEQ.get(studio_id, 0) + 1
    BOOKING_SEQ[studio_id] = current
    return current