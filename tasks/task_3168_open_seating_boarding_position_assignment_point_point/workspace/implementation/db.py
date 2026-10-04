"""In-memory data store for the Open Seat P2P Ops API."""
from __future__ import annotations

import threading


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.stations = {}
        self.fare_classes = {}
        self.passengers = {}
        self.aircraft = {}
        self.crew_members = {}
        self.flight_legs = {}
        self.aircraft_routings = {}
        self.crew_pairings = {}
        self.bookings = {}
        self.journeys = {}
        self.boarding_assignments = {}
        self.boarding_upgrades = {}
        self.bags = {}
        self.travel_credits = {}
        self.credit_redemptions = {}
        self.disruption_events = {}
        # logical clock: startup default exactly 2026-09-01T00:00:00Z
        self.clock_iso = "2026-09-01T00:00:00Z"


db = DB()
