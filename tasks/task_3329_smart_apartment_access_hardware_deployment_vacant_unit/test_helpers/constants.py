"""Domain thresholds and pinned values used across the SmartRent access API.

Values are the numeric constants stated in the product requirements:
wireless thresholds, notice lead times, budget/accrual arithmetic, labor-hour
pricing, setpoint policy and the logical clock's pinned start instant.
"""

# --- Logical clock ---------------------------------------------------------
CLOCK_START = "2026-09-01T00:00:00Z"

# --- Wireless coverage -----------------------------------------------------
NET_RSSI_THRESHOLD_DBM = {
    "POINT_TO_POINT": -67,
    "FIELD_MESH": -75,
    "HUB_RELAY": -80,
}
AGE_PENALTY_DB_PER_DAY = 0.1

# --- Scheduling / notice ---------------------------------------------------
IDENTITY_VERIFICATION_TTL_MINUTES = 60
MAX_VERIFY_ATTEMPTS = 3
REQUIRED_NOTICE_HOURS_STANDARD = 48
REQUIRED_NOTICE_HOURS_EMERGENCY = 24
NOTICE_WINDOW_OPEN_HOUR = 8
NOTICE_WINDOW_CLOSE_HOUR = 20
ESTIMATED_INSTALL_MINUTES = 120
INSTALL_BUFFER_MINUTES = 30
DEFAULT_TOUR_DURATION_MINUTES = 60

# --- Credits / battery -----------------------------------------------------
BATTERY_DRAIN_PER_SCAN = 1
LOW_BATTERY_ALERT_PCT = 20
DEFAULT_BATTERY_PCT = 100

# --- Vacant-unit setpoint policy ------------------------------------------
DEFAULT_VACANT_SETPOINT_C = 26.0
HOT_VACANT_SETPOINT_C = 27.0
HOT_FORECAST_THRESHOLD_C = 30
DEHUMIDIFICATION_SETPOINT_C = 24.0
SETPOINT_MIN_C = 15
SETPOINT_MAX_C = 27
OCCUPIED_SETPOINT_C = 22.0
HUMIDITY_STRESS_THRESHOLD_PCT = 60

# --- Money -----------------------------------------------------------------
BASE_VISIT_CENTS = 2000
EMERGENCY_SURCHARGE_CENTS = 1500
HOURLY_CENTS = 700
ESTIMATED_JOB_RESERVE_CENTS = 2000
DEFAULT_TEMP_BUDGET_CENTS_PER_DAY = 500
DEFAULT_PROPERTY_UNIT_CAPACITY = 0

# --- Labor pricing ---------------------------------------------------------
LABOR_BASE_HOURS = {
    "SMART_LOCK": 0.5,
    "THERMOSTAT": 0.4,
    "LEAK_SENSOR": 0.25,
    "COMMUNITY_ACCESS": 0.75,
    "HUB": 1.0,
}
TIER_THRESHOLD_HOURS = 1.0
REWORK_RATE = 0.25

# --- Roles -----------------------------------------------------------------
ROLES = [
    "PlatformAdmin",
    "PropertyManager",
    "HardwareTechnician",
    "MaintenanceTechnician",
    "LeasingAgent",
    "Resident",
]

# --- Handy test defaults ---------------------------------------------------
TEST_DEFAULTS = {
    "TEMP_BUDGET_CENTS_PER_DAY": 500_000,
    "UNIT_CAPACITY": 1,
    "BUILDING_RSSI_DBM": -60,
    "NETWORK_DESIGN": "FIELD_MESH",
}