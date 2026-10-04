"""In-memory data store.

Storage is Python dicts keyed by id, and nothing else: there is no SQLite file,
no JSON dump, no /tmp cache and no external persistence of any kind.  The store
starts EMPTY on every boot — no entity is seeded, preloaded, registered or
hardcoded at startup.  Every record any caller sees was constructed through the
declared API surface.  Because start.sh re-execs a fresh process on every
per-test reboot, the store is wiped by construction.
"""

import uuid

from clock import Clock, fmt_dt

# Entity collections (dict keyed by id).  Created empty at import time.
ZONES = {}
AGENCIES = {}
PROPERTIES = {}
APPRAISALS = {}
SCHEDULED_ITEMS = {}
APPRAISAL_DOCUMENTS = {}
MITIGATION_REQUIREMENTS = {}
RISK_CONSULTATIONS = {}
DISPATCHES = {}
ENROLLMENTS = {}
MANAGED_RISK_EVENTS = {}
CLAIMS = {}
NON_RENEWAL_NOTICES = {}
ENDORSEMENTS = {}

CLOCK = Clock()


def new_id():
    return str(uuid.uuid4())


def reset():
    """Drop every record.  Called only by tests/tools, never at boot."""
    for collection in (
        ZONES, AGENCIES, PROPERTIES, APPRAISALS, SCHEDULED_ITEMS,
        APPRAISAL_DOCUMENTS, MITIGATION_REQUIREMENTS, RISK_CONSULTATIONS,
        DISPATCHES, ENROLLMENTS, MANAGED_RISK_EVENTS, CLAIMS,
        NON_RENEWAL_NOTICES, ENDORSEMENTS,
    ):
        collection.clear()
    CLOCK.set(Clock().now)


def now():
    return CLOCK.now


def stamp():
    return fmt_dt(CLOCK.now)