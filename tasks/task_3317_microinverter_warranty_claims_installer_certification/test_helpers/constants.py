"""Domain thresholds — numeric constants stated in the PRD."""

# Logical clock default before any client sets it (PRD §2.7).
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Installer certification term, in months (PRD §3.1).
CERT_TERM_MONTHS = 36

# Decided claims required before a level promotion (PRD §3.1).
CLAIMS_FOR_LEVEL_UP = 100

# DC/AC ratio approval gate (PRD §3.2): a ratio greater than 1.5 is refused;
# ratios at or below 1.5 pass.
MAX_DC_AC_RATIO = 1.50

# AC nameplate watts per microinverter (PRD §3.2).
MICRO_AC_WATTS = 350

# Coverage arithmetic (PRD §3.3).
BASE_TERM_MONTHS = 300
MAX_REPLACEMENT_RATIO = 0.50
REPLACEMENT_EXT_THRESHOLD = 0.30
FULL_EXTENSION_MONTHS = 120
PARTIAL_EXTENSION_MONTHS = 60

# Replacement budget seeded on every system (PRD §3.3).
REPLACEMENT_LIMIT_PER_SYSTEM = 5

# Monitoring thresholds (PRD §3.4).
UNDERPERFORMANCE_RATIO = 0.95
FAILURE_STREAK_HOURS = 24

# Metering (PRD §3.4).
METERING_BASE_RATE_CENTS = 250
METERING_FREE_MONTHS = 60

# Lot defect thresholds (PRD §3.5).
DEFAULT_DEFECT_THRESHOLD_PCT = 5.0
AUTOMATED_CAMPAIGN_MIN_UNITS = 10

# Labor rate tables (PRD §3.8).
LEVEL_BASE_RATE_CENTS = {"PLATINUM": 9500, "GOLD": 8500, "CERTIFIED": 7500}
LEVEL_FACTOR = {"PLATINUM": 1.25, "GOLD": 1.10, "CERTIFIED": 1.00}
LEVEL_CAP_HOURS = {"PLATINUM": 6.0, "GOLD": 4.0, "CERTIFIED": 2.0}
DIAGNOSTIC_FEE_CENTS_BY_LEVEL = {"PLATINUM": 12500, "GOLD": 8500, "CERTIFIED": 6500}

# Age bands shared by labor and metering (PRD §3.4 / §3.8).
AGE_BAND_1_MONTHS = 60
AGE_BAND_2_MONTHS = 120
AGE_BAND_3_MONTHS = 144

# Whole months -> age factor (PRD §3.8).
def age_factor_for_months(age_months: int) -> float:
    if age_months <= AGE_BAND_1_MONTHS:
        return 1.000
    if age_months <= AGE_BAND_2_MONTHS:
        return 0.750
    if age_months <= AGE_BAND_3_MONTHS:
        return 0.375
    return 0.000


# Billing correction tolerance (PRD §3.4).
RECONCILIATION_TOLERANCE_BPS = 500

# Entitlement window length, in months (PRD §3.7).
ENTITLEMENT_MONTHS = 3

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Well-formed but nonexistent UUID used for not-found tests.
NONEXISTENT_ID = "00000000-0000-0000-0000-000000000001"


def months_between(start_iso: str, end_iso: str) -> int:
    """Whole calendar months from start_iso to end_iso (PRD §2.7 month arithmetic)."""
    from datetime import datetime

    def _parse(value: str):
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")

    a, b = _parse(start_iso), _parse(end_iso)
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)