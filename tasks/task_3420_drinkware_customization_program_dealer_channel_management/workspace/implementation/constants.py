"""All pinned constants from SCAFFOLD.yaml §1.3 calculations and RBAC roles."""
from datetime import datetime, timezone
from decimal import Decimal

# The nine declared roles (PRD §2.1).
ROLES = [
    "PlatformAdmin", "ChannelManager", "FieldInspector", "Dealer", "Buyer",
    "PrepressTech", "ProductionLead", "WarrantyAgent", "CustomerCare",
]

# customization_quote_cents
COLOR_SURCHARGE_CENTS = 150
PLACEMENT_SURCHARGE_CENTS = 200
SETUP_FEE_CENTS = 8000
SETUP_WAIVER_QTY = 144
PEAK_MULTIPLIER = Decimal("1.25")
# Quantity-tier discount for CORPORATE buyers only, evaluated high to low.
CORPORATE_TIERS = (
    (500, Decimal("0.22")),
    (144, Decimal("0.15")),
    (48, Decimal("0.08")),
)

# The corporate-gifting peak window (half-open), shared by quote peak probe,
# dealer allocation scoring, and slot peak_overlap (PRD §2.9).
PEAK_WINDOW_START = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
PEAK_WINDOW_END = datetime(2026, 12, 21, 0, 0, 0, tzinfo=timezone.utc)

# dealer_infraction_points
INFRACTION_POINTS = {
    "MAP_VIOLATION": 4,
    "UNAUTHORIZED_MARKETPLACE": 6,
    "BRAND_STANDARD": 3,
    "CHANNEL_DIVERSION": 5,
}
INFRACTION_EXPIRY_DAYS = 365
PROBATION_THRESHOLD = 8
SUSPEND_THRESHOLD = 12

# slot_capacity_ledger
PER_UNIT_MINUTES = {"LASER": 4, "PAD": 2}

# return_refund_cents
CANCEL_FEE_RATE = Decimal("0.10")
RETURN_WINDOW_DAYS = 45

# warranty_window_and_fraud
FRAUD_PRIOR_THRESHOLD = 3
FRAUD_WINDOW_DAYS = 365

# print_slot_overlap / inspection_schedule_conflict
CHANGEOVER_BUFFER_MINUTES = 20
TRAVEL_BUFFER_MINUTES = 60

# dealer authorization brand-standard gate
BRAND_SCORE_THRESHOLD = 70

# dealer defaults
DEFAULT_CREDIT_LIMIT_CENTS = 500000
