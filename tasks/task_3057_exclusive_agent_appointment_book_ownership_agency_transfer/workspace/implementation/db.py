"""In-memory data store.

Storage is dicts keyed by id and nothing else — no SQLite file, no JSON dump on
disk, no /tmp cache, no external service.  Re-invoking start.sh therefore wipes
every byte of state and guarantees a fresh boot.

The store starts EMPTY on every boot: nothing here is seeded, preloaded,
registered or hardcoded.  Every entity a client needs is created by that client
through the declared API surface.
"""

import uuid


def new_id():
    return str(uuid.uuid4())


def empty_store():
    return {
        "agencies": {},            # id -> Agency
        "agents": {},              # id -> Agent
        "policies": {},            # id -> Policy
        "agreements": {},          # id -> Agreement
        "staff": {},               # id -> StaffMember
        "campaigns": {},           # id -> MarketingCampaign
        "claims": {},              # id -> Claim
        "book_transfers": {},      # id -> BookTransfer
        "license_records": {},     # id -> LicenseRecord
        "applications": {},        # id -> AppointmentApplication
    }


STORE = empty_store()


def reset():
    """Wipe every collection.  Called once at module install; never seeds."""
    global STORE
    STORE = empty_store()
    return STORE


def get(collection):
    return STORE[collection]


def agency_rows():
    return STORE["agencies"]


def agent_rows():
    return STORE["agents"]


def policy_rows():
    return STORE["policies"]


def agreement_rows():
    return STORE["agreements"]


def staff_rows():
    return STORE["staff"]


def campaign_rows():
    return STORE["campaigns"]


def claim_rows():
    return STORE["claims"]


def transfer_rows():
    return STORE["book_transfers"]


def license_rows():
    return STORE["license_records"]


def application_rows():
    return STORE["applications"]