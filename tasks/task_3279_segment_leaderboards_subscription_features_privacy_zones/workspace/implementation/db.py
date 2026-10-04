"""In-memory data store. Store starts empty on every boot; tests build all state
via the declared API surface. Never seed here."""
import itertools
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)
        self.athletes = {}            # id -> dict
        self.subscriptions = {}       # id -> dict
        self.privacy_zones = {}       # id -> dict
        self.activities = {}          # id -> dict
        self.segments = {}            # id -> dict
        self.efforts = {}             # id -> dict
        self.flags = {}               # id -> dict
        self.clubs = {}               # id -> dict
        self.memberships = {}         # id -> dict
        self.challenges = {}          # id -> dict
        self.participations = {}      # id -> dict
        self.events = {}              # id -> dict
        self.rsvps = {}               # id -> dict
        self.safety_contacts = {}     # id -> dict
        self.beacon_sessions = {}     # id -> dict
        self.route_plans = {}         # id -> dict
        # Logical clock, per PRD 2.6: fixed default, no wall-clock fallback.
        self.current_utc_iso = "2026-09-01T00:00:00Z"


db = Store()
