"""Domain constants — canonical values from the PRD.

Every temporal rule reads the logical clock (POST /_clock/set_current_utc);
the startup default is CLOCK_DEFAULT_UTC and it never falls back to
wall-clock time.
"""

# --- Logical clock -----------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# --- Screening / volunteer standing ------------------------------------------
SCREENING_VALIDITY_MONTHS = 24
STRIKE_LIMIT = 3

# --- Site agreements ----------------------------------------------------------
RENEWAL_WINDOW_DAYS = 60

# --- Staffing coverage / posture ----------------------------------------------
COVERAGE_OPEN_THRESHOLD = 0.75
COVERAGE_ASSIGNED_WEIGHT = 0.5

# --- Service booking capacities and durations --------------------------------
ROOM_BUFFER_MINUTES = 45
SLEEPING_AREA_CAPACITY = 8
SHOWER_CAPACITY = 4
CONNECTIVITY_CAPACITY = 20
FAMILY_ROOM_CAPACITY = 1
SLEEPING_AREA_MAX_MINUTES = 480
SHOWER_MAX_MINUTES = 30
CONNECTIVITY_MAX_MINUTES = 120
FAMILY_ROOM_MAX_MINUTES = 240
DAILY_SERVICE_MINUTES_CAP = 360
DEPENDENT_DAILY_MINUTES_CAP = 240

# --- Partner match ------------------------------------------------------------
MATCH_PCT = 0.25

# --- Convenience lookups derived from the constants above ---------------------
# Service-type duration ceilings (whole minutes).
SERVICE_TYPE_MAX_MINUTES = {
    "SLEEPING_AREA": SLEEPING_AREA_MAX_MINUTES,
    "SHOWER": SHOWER_MAX_MINUTES,
    "CONNECTIVITY": CONNECTIVITY_MAX_MINUTES,
    "FAMILY_ROOM": FAMILY_ROOM_MAX_MINUTES,
}

# Service-type overlap pool capacities.
SERVICE_TYPE_CAPACITY = {
    "SLEEPING_AREA": SLEEPING_AREA_CAPACITY,
    "SHOWER": SHOWER_CAPACITY,
    "CONNECTIVITY": CONNECTIVITY_CAPACITY,
    "FAMILY_ROOM": FAMILY_ROOM_CAPACITY,
}

# Services bookable while a center posture is RESTRICTED.
RESTRICTED_ALLOWED_SERVICE_TYPES = ("SHOWER", "CONNECTIVITY")
