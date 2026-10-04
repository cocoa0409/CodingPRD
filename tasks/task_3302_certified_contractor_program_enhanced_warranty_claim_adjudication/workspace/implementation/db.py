"""In-memory data store. Starts empty on every boot."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.contractors = {}
        self.training_courses = {}
        self.training_enrollments = {}
        self.certifications = {}
        self.catalog_items = {}          # id -> item
        self.catalog_by_sku = {}         # sku -> item
        self.registrations = {}
        self.components = {}
        self.claims = {}
        self.inspection_orders = {}
        self.remedies = {}
        self.complaints = {}
        self.distributors = {}
        self.lead_assignments = {}
        # logical clock: startup default exactly 2026-09-01T00:00:00Z
        self.clock = "2026-09-01T00:00:00Z"


db = Store()
