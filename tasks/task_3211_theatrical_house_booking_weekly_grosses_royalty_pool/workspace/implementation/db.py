"""In-memory data store. Fresh and empty on every process boot."""


class Store:
    def __init__(self):
        self.companies = {}
        self.theatres = {}
        self.productions = {}
        self.bookings = {}
        self.license_agreements = {}
        self.royalty_participants = {}
        self.discount_codes = {}
        self.ticket_orders = {}
        self.weekly_reports = {}
        self.settlements = {}
        self.stop_notices = {}
        self.capital_projects = {}
        self.crew_assignments = {}
        # Logical clock; startup default is exactly 2026-09-01T00:00:00Z,
        # never wall-clock time.
        self.clock = "2026-09-01T00:00:00Z"


STORE = Store()
