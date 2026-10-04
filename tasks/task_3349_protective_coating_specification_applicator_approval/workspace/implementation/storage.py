"""In-memory storage and the logical clock. No disk persistence of any kind."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.coating_systems = {}
        self.voc_regulations = {}
        self.applicators = {}
        self.qualification_programs = {}
        self.qualifications = {}
        self.projects = {}
        self.specifications = {}
        self.substitution_requests = {}
        self.work_orders = {}
        self.prep_inspections = {}
        self.applications = {}
        self.inspection_reports = {}
        self.warranties = {}
        self.investigations = {}
        # qualification_id -> count of ACCEPTED reports since entering PROBATION
        self.probation_progress = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK

    def now(self):
        return self.clock

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
