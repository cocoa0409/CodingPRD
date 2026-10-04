"""In-memory data store. Module-level singleton; fresh per process boot."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.zones = {}
        self.drive_units = {}
        self.chargers = {}
        self.pods = {}
        self.skus = {}
        self.inventory_slots = {}
        self.pick_stations = {}
        self.orders = {}
        self.order_lines = {}
        self.pick_tasks = {}
        self.stow_tasks = {}
        self.charging_sessions = {}
        self.maintenance_windows = {}
        self.floor_exceptions = {}
        self.human_entry_permits = {}
        self.shift_plans = {}
        self.software_releases = {}
        # Logical clock: fixed default per PRD 2.4.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()
