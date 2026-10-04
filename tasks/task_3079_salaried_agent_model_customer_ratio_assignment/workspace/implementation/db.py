"""In-memory store. Starts empty on every boot; nothing is ever seeded.

Storage is plain Python dicts keyed by id. There is no file, no dump and no
external persistence of any kind, so re-invoking start.sh wipes every byte of
state and the next boot is guaranteed fresh.
"""

from errors import ApiError
from utils import iso_z


class Store(object):
    def __init__(self):
        self.regions = {}
        self.agents = {}
        self.open_client_counts = {}   # agent_id -> row
        self.lead_capacities = {}      # agent_id -> row
        self.clients = {}
        self.transactions = {}
        self.listings = {}
        self.tours = {}
        self.surveys = {}
        self.referrals = {}
        self.audits = {}               # event_seq -> row (ActivityAudit is append-only)
        self.ops_run_index = {}        # region_id -> int
        self.region_order = []
        self.agent_order = []
        self.agent_registry_orders = {}  # region_id -> [agent_id, ...] in registry order


db = Store()


# ---------------------------------------------------------------------------
# Timestamp helpers shared by every collection (uses the logical clock, never
# wall-clock time).
# ---------------------------------------------------------------------------
def stamp(row):
    row["updated_at"] = iso_z(_now())
    row["version"] = row.get("version", 0) + 1


def _now():
    from utils import clock_now
    return clock_now()


def _region_of(agent):
    return db.regions.get(agent.get("region_id"))


def get_region_or_404(region_id):
    region = db.regions.get(region_id)
    if region is None:
        raise ApiError("ERR_REGION_NOT_FOUND", http_status=404)
    return region


def get_agent_or_404(agent_id):
    agent = db.agents.get(agent_id)
    if agent is None:
        raise ApiError("ERR_AGENT_NOT_FOUND", http_status=404)
    return agent


def get_client_or_404(client_id):
    client = db.clients.get(client_id)
    if client is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND", http_status=404)
    return client


def get_transaction_or_404(tx_id):
    tx = db.transactions.get(tx_id)
    if tx is None:
        raise ApiError("ERR_TRANSACTION_NOT_FOUND", http_status=404)
    return tx


def get_listing_or_404(listing_id):
    listing = db.listings.get(listing_id)
    if listing is None:
        raise ApiError("ERR_LISTING_NOT_FOUND", http_status=404)
    return listing


def get_tour_or_404(tour_id):
    tour = db.tours.get(tour_id)
    if tour is None:
        raise ApiError("ERR_TOUR_NOT_FOUND", http_status=404)
    return tour


def get_survey_or_404(survey_id):
    survey = db.surveys.get(survey_id)
    if survey is None:
        raise ApiError("ERR_SURVEY_NOT_FOUND", http_status=404)
    return survey


def get_referral_or_404(referral_id):
    referral = db.referrals.get(referral_id)
    if referral is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND", http_status=404)
    return referral


def audit(region_id, entity_type, entity_ref_id, kind, detail):
    """Append-only ActivityAudit row: id + created_at only, no updated_at/version."""
    from utils import new_id, next_seq
    row = {
        "id": new_id(),
        "_seq": next_seq(),
        "region_id": region_id,
        "entity_type": entity_type,
        "entity_ref_id": entity_ref_id,
        "kind": kind,
        "detail": detail,
        "created_at": iso_z(_now()),
    }
    db.audits[row["_seq"]] = row
    return row