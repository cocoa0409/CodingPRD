"""Domain thresholds and canonical test values.

Every number below is stated in the PRD prose and cross-checked against it:

- Issuance criteria per hazard at the WARNING and ADVISORY floors (PRD §3.5:
  "wind of at least 58 mph or hail of at least 1.00 inch", "rainfall rate of at
  least 2.0 inches per hour", "at least 74 mph", "at least 35 mph"; advisory
  floors "at least 40 mph or ... 0.75 inches", "at least 1.0 inch per hour",
  "at least 39 mph", "at least 25 mph"). Comparisons are inclusive (§2.5).
- Duration ranges in whole minutes, inclusive (PRD §3.5: "15 to 120 minutes for
  severe thunderstorm, 15 to 90 for tornado, 30 to 180 for flash flood, 60 to
  720 for hurricane, and 60 to 720 for winter storm").
- Impact tiers (PRD §3.4: catastrophic "at least 80 mph ... at least 2.75
  inches ... debris_signature"; considerable "at least 70 mph or ... 1.75").
- Zone overlap inclusion (PRD §3.4: "at least 0.10").
- Geometry conversion (PRD §3.4: "111.0 kilometers per degree") and the vertex
  envelope (PRD §2.8: "between 3 and 12 vertices").
- WEA budget (PRD §3.2: "no more than 360 characters"; §3.6: "the smaller of
  360 and the channel's max_message_chars").
- Retry maximum (PRD §3.6: "at exactly three failed attempts the record
  terminates as DEAD").
- Performance bands (PRD §3.8: "strictly greater than 0.70", "strictly less
  than 0.50").
- Evacuation re-entry buffer (PRD §3.9: "sixty minutes after that prior
  action's end ... a gap of exactly sixty minutes allowed").
- Coordination timeout default (PRD §3.1: "defaulting to 15").
- Logical-clock startup instant (PRD §2.4: "At startup the logical clock reads
  exactly 2026-09-01T00:00:00Z").
"""

# --- Logical clock (PRD §2.4) -------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
DEFAULT_ISSUE_CLOCK_ISO = "2026-09-01T10:00:00Z"

# --- Polygon geometry (PRD §3.4, §2.8) ----------------------------------------
KM_PER_DEG = 111.0
POLYGON_MIN_VERTICES = 3
POLYGON_MAX_VERTICES = 12
ZONE_INCLUSION_MIN_PCT = 0.10

# --- Issuance criteria (PRD §3.5); every comparison is inclusive (>=) ---------
SEVERE_WARNING_WIND_MPH = 58
SEVERE_WARNING_HAIL_IN = 1.00
SEVERE_ADVISORY_WIND_MPH = 40
SEVERE_ADVISORY_HAIL_IN = 0.75
FLOOD_WARNING_RAIN_IN_HR = 2.0
FLOOD_ADVISORY_RAIN_IN_HR = 1.0
HURRICANE_WARNING_WIND_MPH = 74
HURRICANE_ADVISORY_WIND_MPH = 39
WINTER_WARNING_WIND_MPH = 35
WINTER_ADVISORY_WIND_MPH = 25

# --- Duration ranges in whole minutes, inclusive bounds (PRD §3.5) ------------
# Only WARNING and ADVISORY products face this gate; WATCH and OUTLOOK are exempt.
DURATION_RANGES_MINUTES = {
    "SEVERE_THUNDERSTORM": (15, 120),
    "TORNADO": (15, 90),
    "FLASH_FLOOD": (30, 180),
    "HURRICANE": (60, 720),
    "WINTER_STORM": (60, 720),
}

# --- Impact tag tiers (PRD §3.4); inclusive comparisons ------------------------
CATASTROPHIC_WIND_MPH = 80
CATASTROPHIC_HAIL_INCHES = 2.75
CONSIDERABLE_WIND_MPH = 70
CONSIDERABLE_HAIL_INCHES = 1.75

# --- WEA rendering (PRD §3.2, §3.6) -------------------------------------------
WEA_ABSOLUTE_MAX_CHARS = 360

# --- Dissemination retries (PRD §3.6) ------------------------------------------
MAX_RETRIES = 3

# --- Performance bands (PRD §3.8); STRICT inequalities -------------------------
FAR_REVIEW_THRESHOLD = 0.70  # band flips only when far > 0.70
POD_REVIEW_THRESHOLD = 0.50  # band flips only when pod < 0.50

# --- Coordination (PRD §3.1) ----------------------------------------------------
COORDINATION_TIMEOUT_DEFAULT_MINUTES = 15

# --- Evacuation re-entry buffer (PRD §3.9); >= comparison, equality passes ------
EVAC_REENTRY_BUFFER_MINUTES = 60

# --- Pagination envelope defaults (PRD §2.3) ------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Canonical fixture geometry --------------------------------------------------
# A 0.1 x 0.1 degree cell converted at 111.0 km/deg measures 11.1 km x 11.1 km =
# 123.21 sq km under the PLANAR area method. Using that exact figure as the
# surveyed area keeps overlap percentages clean: the same cell as a polygon
# overlaps the zone at exactly 1.000, half of it at 0.500.
STANDARD_ZONE_LAT_MIN = 0.0
STANDARD_ZONE_LAT_MAX = 0.1
STANDARD_ZONE_LON_MIN = 0.0
STANDARD_ZONE_LON_MAX = 0.1
STANDARD_SURVEYED_AREA_SQ_KM = 123.21

__all__ = [
    "CLOCK_START_ISO",
    "DEFAULT_ISSUE_CLOCK_ISO",
    "KM_PER_DEG",
    "POLYGON_MIN_VERTICES",
    "POLYGON_MAX_VERTICES",
    "ZONE_INCLUSION_MIN_PCT",
    "SEVERE_WARNING_WIND_MPH",
    "SEVERE_WARNING_HAIL_IN",
    "SEVERE_ADVISORY_WIND_MPH",
    "SEVERE_ADVISORY_HAIL_IN",
    "FLOOD_WARNING_RAIN_IN_HR",
    "FLOOD_ADVISORY_RAIN_IN_HR",
    "HURRICANE_WARNING_WIND_MPH",
    "HURRICANE_ADVISORY_WIND_MPH",
    "WINTER_WARNING_WIND_MPH",
    "WINTER_ADVISORY_WIND_MPH",
    "DURATION_RANGES_MINUTES",
    "CATASTROPHIC_WIND_MPH",
    "CATASTROPHIC_HAIL_INCHES",
    "CONSIDERABLE_WIND_MPH",
    "CONSIDERABLE_HAIL_INCHES",
    "WEA_ABSOLUTE_MAX_CHARS",
    "MAX_RETRIES",
    "FAR_REVIEW_THRESHOLD",
    "POD_REVIEW_THRESHOLD",
    "COORDINATION_TIMEOUT_DEFAULT_MINUTES",
    "EVAC_REENTRY_BUFFER_MINUTES",
    "PAGE_LIMIT_DEFAULT",
    "PAGE_LIMIT_MIN",
    "PAGE_LIMIT_MAX",
    "PAGE_OFFSET_DEFAULT",
    "STANDARD_ZONE_LAT_MIN",
    "STANDARD_ZONE_LAT_MAX",
    "STANDARD_ZONE_LON_MIN",
    "STANDARD_ZONE_LON_MAX",
    "STANDARD_SURVEYED_AREA_SQ_KM",
]
