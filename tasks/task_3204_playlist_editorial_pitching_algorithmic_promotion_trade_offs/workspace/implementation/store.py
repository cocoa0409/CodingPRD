"""In-memory data store. Starts completely empty on every boot; the logical
clock starts pinned at 2026-09-01T00:00:00Z."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.artists = {}
        self.releases = {}
        self.tracks = {}
        self.pitches = {}
        self.playlists = {}
        self.placements = {}
        self.promotions = {}
        self.streams = {}
        self.fraud_cases = {}
        self.periods = {}
        self.statements = {}
        self.modules = {}
        self.presaves = {}
        self.seq = 0
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-09-01T00:00:00Z"

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
