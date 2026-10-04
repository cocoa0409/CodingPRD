from datetime import datetime, timezone
from util import now_iso

class Store:
    def __init__(self):
        self.studios = {}
        self.properties = {}
        self.agreements = {}
        self.lines = {}
        self.skus = {}
        self.factories = {}
        self.tooling_orders = {}
        self.retailers = {}
        self.reviews = {}
        self.commitments = {}
        self.shipments = {}
        self.safety_tests = {}
        self.clock = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.clock_str = now_iso(self.clock)

db = Store()

def stamp_new(rec):
    ts = now_iso(db.clock)
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1

def touch(rec):
    rec["updated_at"] = now_iso(db.clock)
    rec["version"] += 1

def property_lifecycle(p):
    rev = p["_reveal_dt"]; rel = p["_release_dt"]; c = db.clock
    if c < rev: return "CONFIDENTIAL"
    if c < rel: return "REVEALED"
    return "RELEASED"

def review_lifecycle(r):
    if r["status"] != "CONFIRMED":
        return "PENDING_APPROVAL"
    c = db.clock
    if c < r["_ws_dt"]: return "SCHEDULED"
    if c < r["_cd_dt"]: return "OPEN"
    return "LOCKED"

def recompute_shelf(review_id):
    r = db.reviews[review_id]
    used = sum(c["shelf_slots"] for c in db.commitments.values()
               if c["line_review_id"] == review_id and c["status"] in ("COMMITTED", "AT_RISK"))
    r["shelf_slots_used"] = used
