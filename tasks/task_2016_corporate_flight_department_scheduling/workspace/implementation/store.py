"""In-memory data store and logical clock.

The store starts empty on every boot. No entity seeding happens here or
anywhere else at startup -- every entity is created via the declared API.
"""

import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables keyed by id. Values are plain dicts.
        self.aircraft = {}              # Aircraft
        self.documents = {}             # DocumentPermit (child of Aircraft)
        self.crew_members = {}          # CrewMember
        self.business_units = {}        # BusinessUnit
        self.passengers = {}            # PassengerProfile
        self.trips = {}                 # TripRequest
        self.flight_legs = {}           # FlightLeg (child of TripRequest)
        self.maintenance_windows = {}   # MaintenanceWindow (child of Aircraft)
        self.catering_orders = {}       # CateringOrder (child of FlightLeg)
        self.ground_transports = {}     # GroundTransport (child of FlightLeg)
        self.charter_supplements = {}   # CharterSupplement
        self.sifl_rate_periods = {}     # SiflRatePeriod

        # Monotonic insertion sequence for stable created_at tie-breaking.
        self.seq = itertools.count(1)

        # Logical clock (PRD 2.4): reads exactly 2026-08-01T00:00:00Z before
        # any clock-setting call; never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def next_seq(self):
        return next(self.seq)


# Module-level singleton. A fresh process gets a fresh, empty store.
db = Store()
