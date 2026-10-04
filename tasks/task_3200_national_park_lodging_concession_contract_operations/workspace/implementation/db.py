"""In-memory data store. Wiped on every process start."""
from datetime import datetime, timezone


def _initial_clock():
    return datetime(2026, 9, 1, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.contracts = {}
        self.seasons = {}
        self.service_lines = {}
        self.room_classes = {}
        self.studies = {}
        self.filings = {}
        self.reservations = {}
        self.receipts_reports = {}
        self.fee_statements = {}
        self.capital_projects = {}
        self.housing_units = {}
        self.hires = {}
        self.vouchers = {}
        self.incidents = {}
        self.clock = _initial_clock()
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
