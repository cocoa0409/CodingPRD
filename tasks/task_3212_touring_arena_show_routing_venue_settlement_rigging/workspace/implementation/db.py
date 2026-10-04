"""In-memory data store. Empty at boot; populated only via API calls."""
import uuid

from clock import now_iso


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.tours = {}
        self.venues = {}
        self.rigging_points = {}
        self.date_avails = {}
        self.engagements = {}
        self.rigging_plans = {}
        self.rigging_allocations = {}
        self.labor_calls = {}
        self.truck_moves = {}
        self.ticket_scales = {}
        self.ticket_sales = {}
        self.settlements = {}          # keyed by settlement id
        self.settlements_by_eng = {}   # engagement_id -> settlement id
        self.license_agreements = {}
        self.safety_inspections = {}


db = Store()


def base_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1
