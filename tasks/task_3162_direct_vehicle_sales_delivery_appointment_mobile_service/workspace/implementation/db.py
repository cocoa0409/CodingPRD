"""In-memory-only data store. Empty on every boot; nothing is ever seeded."""

import copy
import uuid
from datetime import datetime, timezone

# Startup logical clock value; never drifts toward wall-clock time.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

CREATE_FEE = 25000
DOC_FEE_CENTS = 7500
DELIVERY_FEE_CENTS = 2500
CANCELLATION_REFUND_CENTS = 20000

BASELINE_SOFTWARE_VERSION = "2026.8.1"

MILEAGE_DEDUCTION_THRESHOLD_MILES = 50000
MILEAGE_DEDUCTION_CAP_CENTS = 200000
PER_MILE_DEDUCTION_CENTS = 12
TRADE_IN_FLOOR_CENTS = 25000

MOBILE_BASE_TRAVEL_CENTS = 0
INCLUDED_MILES = 30
PER_MILE_TRAVEL_CENTS = 95
LABOR_RATE_CENTS_PER_HOUR = 19500
WARRANTY_MILEAGE_CEILING = 60000

MAX_BUNDLE_DISCOUNT_CENTS = 200000
TIER_2_DISCOUNT_BPS = 500
TIER_3_DISCOUNT_BPS = 1000

FINANCEABLE_MAX_CENTS = {
    "PRIME": 8000000,
    "NEAR_PRIME": 6000000,
    "SUBPRIME": 4000000,
}


def new_id():
    return str(uuid.uuid4())


class Store(object):
    """Every entity is a plain dict held in memory."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.now = DEFAULT_CLOCK
        self.buyers = {}
        self.jurisdictions = {}
        self.configurations = {}
        self.options = {}
        self.centers = {}
        self.orders = {}
        self.order_options = {}
        self.order_fee_cents_override = {}
        self.ledger = {}
        self.appraisals = {}
        self.applications = {}
        self.batches = {}
        self.units = {}
        self.estimates = {}
        self.appointments = {}
        self.vehicles = {}
        self.reports = {}
        self.service_appointments = {}
        self.visits = {}
        self.entitlements = {}
        self.notes = {}

    def snapshot(self):
        state = {}
        for name, value in self.__dict__.items():
            if name == "now":
                state[name] = value
            else:
                state[name] = copy.deepcopy(value)
        return state

    def restore(self, state):
        for name, value in state.items():
            setattr(self, name, value)


DB = Store()