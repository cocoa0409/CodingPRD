"""In-memory data store. Store starts empty on every boot."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.productions = {}
        self.assets = {}
        self.render_batches = {}
        self.shows = {}
        self.bookings = {}
        self.venue_systems = {}
        self.maintenance_windows = {}
        self.sponsors = {}
        self.campaigns = {}
        self.settlements = {}
        # logical clock
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


DB = Store()
