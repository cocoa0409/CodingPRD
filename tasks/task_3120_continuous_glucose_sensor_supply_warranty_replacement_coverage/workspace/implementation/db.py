"""In-memory data store. Store starts empty on every boot — no seeding."""


class DB:
    def __init__(self):
        self.patients = {}
        self.prescribers = {}
        self.payers = {}
        self.sensor_products = {}
        self.sensor_lots = {}
        self.prescriptions = {}
        self.coverage_verifications = {}
        self.sensor_units = {}
        self.sensor_orders = {}
        self.device_bindings = {}
        self.warranty_claims = {}
        self.replacement_shipments = {}
        self.support_enrollments = {}
        self.adverse_event_reports = {}
        # Logical clock: default before any call is exactly 2026-09-01T00:00:00Z
        self.logical_now_iso = "2026-09-01T00:00:00Z"
        # Per-patient plan-year deductible accumulator (starts at 0; single-order scope)
        self.deductible_used = {}


db = DB()
