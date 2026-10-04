"""Domain thresholds and constants — every value traces to a PRD sentence.

Sources (PRD.md):
- Section 2.3: pagination defaults (limit 10, range 1..100, offset 0).
- Section 2.4: logical clock starts at exactly 2026-09-01T00:00:00Z; renewal
  window opens at end_date minus ninety days.
- Section 2.6: escalation multiplier kept at four decimal places, rounded
  half up once per elapsed year.
- Section 3.1: mode recommendation thresholds 4000 / 1500 / 200 Nm3/h,
  inclusive (a demand exactly equal to a threshold takes the higher mode).
- Section 3.2: activation minimum-volume floors per mode; makeup_credit_cap_pct
  defaults to 0.10 (ten percent).
- Section 3.5: WMA weights 1/2, 1/4, 1/8, 1/8 over up to the 4 most recent
  intervals, latest first, unused weights discarded.
- Section 3.6: route_code is "RT-" prefixed onto the route_date.
- Section 3.7: turnaround window duration within [24h, 720h].
- Section 3.8: makeup credit grant is sixty percent of the shortfall value.
"""

# --- Logical clock (PRD section 2.4) ---
CLOCK_START_UTC = "2026-09-01T00:00:00Z"

# --- Supply-mode recommendation thresholds, Nm3/h (PRD section 3.1) ---
MODE_THRESHOLDS_NM3H = {
    "ONSITE_MIN_AVG_NM3H": 4000,
    "PIPELINE_MIN_AVG_NM3H": 1500,
    "BULK_MIN_AVG_NM3H": 200,
}

# --- Activation minimum monthly volume floors per mode, Nm3 (PRD section 3.2) ---
MODE_MIN_MONTHLY_VOLUME_NM3 = {
    "ONSITE_PLANT": 2000000,
    "PIPELINE": 800000,
    "BULK_LIQUID": 150000,
    "CYLINDER": 0,
}

# --- Makeup-credit bank (PRD sections 3.2, 3.8) ---
MAKEUP_CREDIT_RATE = 0.6
DEFAULT_MAKEUP_CREDIT_CAP_PCT = 0.10

# --- Turnaround window bounds, hours (PRD section 3.7) ---
TURNAROUND_MIN_DURATION_HOURS = 24
TURNAROUND_MAX_DURATION_HOURS = 720

# --- Renewal window opens this many days before end_date (PRD section 2.4) ---
RENEWAL_WINDOW_DAYS = 90

# --- Tank burn analytics (PRD section 3.5) ---
WMA_WEIGHTS = [0.5, 0.25, 0.125, 0.125]

# --- Facility-fee escalation precision (PRD section 2.6) ---
ESCALATION_MULTIPLIER_DECIMAL_PLACES = 4

# --- Delivery routing (PRD section 3.6) ---
ROUTE_CODE_PREFIX = "RT-"

# --- Pagination (PRD section 2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

__all__ = [
    "CLOCK_START_UTC",
    "MODE_THRESHOLDS_NM3H",
    "MODE_MIN_MONTHLY_VOLUME_NM3",
    "MAKEUP_CREDIT_RATE",
    "DEFAULT_MAKEUP_CREDIT_CAP_PCT",
    "TURNAROUND_MIN_DURATION_HOURS",
    "TURNAROUND_MAX_DURATION_HOURS",
    "RENEWAL_WINDOW_DAYS",
    "WMA_WEIGHTS",
    "ESCALATION_MULTIPLIER_DECIMAL_PLACES",
    "ROUTE_CODE_PREFIX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
]
