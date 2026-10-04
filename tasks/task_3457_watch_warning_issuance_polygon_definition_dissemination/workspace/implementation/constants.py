"""Every named constant in the system, defined exactly once (PRD §2/§3, SCAFFOLD §1.3)."""
from decimal import Decimal

# --- mounting -----------------------------------------------------------------
API_PREFIX = "/alerts"

# --- logical clock --------------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- enumerations (PRD §2.7) ----------------------------------------------------
HAZARD_TYPES = ["TORNADO", "SEVERE_THUNDERSTORM", "FLASH_FLOOD", "HURRICANE", "WINTER_STORM"]
PRODUCT_LEVELS = ["OUTLOOK", "WATCH", "ADVISORY", "WARNING"]
DAMAGE_THREATS = ["NONE", "CONSIDERABLE", "CATASTROPHIC"]
AREA_METHODS = ["PLANAR", "GEODETIC"]
PERFORMANCE_BANDS = ["SATISFACTORY", "REVIEW_REQUIRED"]
POPULATION_TIERS = ["LOW", "MEDIUM", "HIGH", "URBAN"]
CHANNEL_TYPES = ["EAS", "WEA", "NOAA_WEATHER_RADIO", "DATA_FEED"]
CHANNEL_STATUSES = ["ACTIVE", "SUSPENDED"]
FORECASTER_LEVELS = ["JOURNEYMAN", "SENIOR", "MIC"]
SUPERSEDE_REASONS = ["UPGRADE", "CONTINUATION", "CORRECTION"]
VERIFICATION_STATUSES = ["UNVERIFIED", "VERIFIED"]
MATCHING_VARIANTS = ["POLYGON_STRICT", "COUNTY_FALLBACK"]
ACTION_TYPES = ["EVACUATION", "SHELTER_IN_PLACE", "SHELTER_OPEN"]
COORDINATION_OUTCOMES = ["ACKNOWLEDGED", "DECLINED"]
ADJUDICATION_OUTCOMES = ["CONFIRMED", "REJECTED"]
SETTLE_OUTCOMES = ["CONFIRMED", "FAILED"]

ROLES = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]
ENTITY_BACKED_ROLES = ["Forecaster", "MeteorologistInCharge"]

PRODUCT_STATUSES = ["DRAFT", "PENDING_COORDINATION", "ISSUED", "EXPIRED", "CANCELLED", "SUPERSEDED"]
COORDINATION_STATUSES = ["REQUESTED", "ACKNOWLEDGED", "DECLINED", "EXPIRED", "CANCELLED", "OVERRIDDEN"]
RECORD_STATUSES = ["QUEUED", "SENT", "CONFIRMED", "FAILED", "DEAD", "WITHDRAWN"]
STORM_STATUSES = ["DETECTED", "TRACKING", "DISSIPATED"]
EVENT_STATUSES = ["REPORTED", "CONFIRMED", "REJECTED"]
EM_ACTION_STATUSES = ["RECOMMENDED", "ORDERED", "LIFTED", "WITHDRAWN"]

# --- geometry (calculations.polygon_area_sq_km / zone_overlap_resolution) --------
KM_PER_DEG = 111.0
ZONE_INCLUSION_MIN_PCT = Decimal("0.10")
POLYGON_MIN_VERTICES = 3
POLYGON_MAX_VERTICES = 12

# --- impact tier scoring (calculations.impact_tier_scoring) ----------------------
CATASTROPHIC_WIND_MPH = Decimal("80")
CATASTROPHIC_HAIL_INCHES = Decimal("2.75")
CONSIDERABLE_WIND_MPH = Decimal("70")
CONSIDERABLE_HAIL_INCHES = Decimal("1.75")

# --- issuance criteria (calculations.issuance_criteria_evaluation) ---------------
SEVERE_WARNING_WIND_MPH = Decimal("58")
SEVERE_WARNING_HAIL_IN = Decimal("1.00")
SEVERE_ADVISORY_WIND_MPH = Decimal("40")
SEVERE_ADVISORY_HAIL_IN = Decimal("0.75")
FLOOD_WARNING_RAIN_IN_HR = Decimal("2.0")
FLOOD_ADVISORY_RAIN_IN_HR = Decimal("1.0")
HURRICANE_WARNING_WIND_MPH = Decimal("74")
HURRICANE_ADVISORY_WIND_MPH = Decimal("39")
WINTER_WARNING_WIND_MPH = Decimal("35")
WINTER_ADVISORY_WIND_MPH = Decimal("25")

# hazard -> (min_duration_minutes, max_duration_minutes), inclusive
DURATION_RANGES = {
    "SEVERE_THUNDERSTORM": (15, 120),
    "TORNADO": (15, 90),
    "FLASH_FLOOD": (30, 180),
    "HURRICANE": (60, 720),
    "WINTER_STORM": (60, 720),
}

# --- WEA rendering (calculations.wea_message_rendering) ---------------------------
WEA_ABSOLUTE_MAX_CHARS = 360

# --- dissemination retries (DisseminationRecord state machine) --------------------
MAX_RETRIES = 3

# --- performance band (calculations.performance_band_derivation) ------------------
FAR_REVIEW_THRESHOLD = Decimal("0.70")
POD_REVIEW_THRESHOLD = Decimal("0.50")

# --- evacuation re-entry buffer (calculations.evacuation_reentry_buffer) ----------
EVAC_REENTRY_BUFFER_MINUTES = 60

# --- neighbor agreement default ---------------------------------------------------
DEFAULT_COORDINATION_TIMEOUT_MINUTES = 15

# --- pagination (response_envelope.pagination_defaults) ---------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
