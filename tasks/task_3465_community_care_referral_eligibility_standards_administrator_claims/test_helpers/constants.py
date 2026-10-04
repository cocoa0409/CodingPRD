"""Domain thresholds and shared fixture anchors — every value is stated in
PRD prose. Comments cite the rule each constant carries.
"""

# --- Logical clock -----------------------------------------------------------
# "At startup the logical clock reads exactly 2026-09-01T00:00:00Z."
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Eligibility access standards (strictly-greater; exactly equal passes) ---
# "30 minutes for PRIMARY_CARE, 60 minutes for SPECIALTY_CARE"
DRIVE_TIME_STANDARD_PRIMARY_MIN = 30
DRIVE_TIME_STANDARD_SPECIALTY_MIN = 60
# "20 days for PRIMARY_CARE, 28 days for SPECIALTY_CARE"
WAIT_TIME_STANDARD_PRIMARY_DAYS = 20
WAIT_TIME_STANDARD_SPECIALTY_DAYS = 28
# "choice_granted is true exactly when choice_requested is true and the
#  veteran's priority_group is at most 4"
CHOICE_PRIORITY_MAX = 4

# --- Drive-time geodesic variants --------------------------------------------
# "haversine formula using an earth radius of 3958.8 miles"
EARTH_RADIUS_MI = 3958.8
# urban: "circuity factor of 1.4 and assumes 40 miles per hour"
URBAN_CIRCUITY = 1.4
URBAN_SPEED_MPH = 40
# rural: "circuity factor of 1.2 and assumes 55 miles per hour"
RURAL_CIRCUITY = 1.2
RURAL_SPEED_MPH = 55

# --- Episode scope caps -------------------------------------------------------
# "an integer from 1 to the initial cap of 12"
INITIAL_VISIT_MAX = 12
# "from 1 to at most 365 days"
DURATION_MAX_DAYS = 365
# "at most 12 additional visits and at most 180 additional days"
EXTENSION_VISIT_MAX = 12
EXTENSION_DAYS_MAX = 180

# --- Medical documentation windows -------------------------------------------
# "born AWAITED with ... its deadline_at set to the completion timestamp plus 30 days"
DOC_RETURN_DEADLINE_DAYS = 30
# "deadline_at resets to the current logical clock plus a 15-day resubmission grace"
DOC_RESUBMIT_GRACE_DAYS = 15

# --- Scheduling ---------------------------------------------------------------
# "each appointment occupies the half-open slot from its scheduled_start
#  through the following 60 minutes"
APPT_SLOT_MINUTES = 60
# "at most 5 days — the comparison is inclusive"
SCHEDULE_TIMELINESS_DAYS = 5

# --- Claims --------------------------------------------------------------------
# "the number of days from service_date to the submission date must be at most
#  180 — the window is inclusive"
TIMELY_FILING_DAYS = 180
# "at most twice per claim"
RESUBMISSION_MAX = 2
# "the Medicare fallback ... 10000 cents per unit for PRIMARY_CARE,
#  18000 cents per unit for SPECIALTY_CARE"
MEDICARE_BASE_RATE_PRIMARY_CENTS = 10000
MEDICARE_BASE_RATE_SPECIALTY_CENTS = 18000
# "multiplied by 2.5 percent, rounded half up to a whole cent" (per line)
TPA_ADMIN_FEE_RATE = 0.025

# --- TPA denial-rate surveillance ----------------------------------------------
# "an adjudicated_events of at least 5 and a denial_rate strictly greater than
#  0.20" (a rate of exactly 0.20 does not suspend)
MIN_ADJUDICATED_EVENTS = 5
DENIAL_RATE_THRESHOLD = 0.20
DENIAL_RATE_DECIMALS = 4  # "rounded half up to 4 decimal places"

# --- Urgent care copay tiers -----------------------------------------------------
# "LOW for groups 1 through 3, MID for groups 4 through 6, HIGH for groups 7 and 8"
PRIORITY_GROUP_MIN = 1
PRIORITY_GROUP_MAX = 8
BAND_LOW_MAX_GROUP = 3
BAND_MID_MAX_GROUP = 6
# "MID pays 1500 cents for a visit_index_in_fy of 3 or less and 3000 cents from
#  the fourth visit ... HIGH pays 3000 ... and 4500 from the fourth onward"
URGENT_VISIT_LOWER_TIER_MAX = 3
COPAY_LOW_CENTS = 0
COPAY_MID_FIRST_CENTS = 1500
COPAY_MID_REPEAT_CENTS = 3000
COPAY_HIGH_FIRST_CENTS = 3000
COPAY_HIGH_REPEAT_CENTS = 4500
# "when the visit month is October or later the fiscal year is the calendar
#  year plus one, otherwise it is the calendar year"
FY_START_MONTH = 10

# --- Prescription supply caps ------------------------------------------------------
# "at most 14 days of supply when urgent-care-linked and at most 90 days when
#  appointment-linked"
RX_URGENT_MAX_DAYS = 14
RX_REFERRAL_MAX_DAYS = 90

# --- Shared fixture geography -------------------------------------------------------
# Station at (40.0, -75.0), veteran home at (40.2609, -75.0) => ~18.0266
# crow-fly miles; URBAN drive time 37.9 min (fails the 30-min primary
# standard), RURAL 23.6 min (passes). These anchors keep every default
# PRIMARY_CARE/URBAN assessment eligible via the drive-time leg.
DEFAULT_STATION_LATITUDE = 40.0
DEFAULT_STATION_LONGITUDE = -75.0
DEFAULT_HOME_LATITUDE = 40.2609
DEFAULT_HOME_LONGITUDE = -75.0
DEFAULT_URBAN_DRIVE_MINUTES = 37.9
DEFAULT_RURAL_DRIVE_MINUTES = 23.6

# --- Shared fixture values -----------------------------------------------------------
DEFAULT_SERVICE_CODE = "PT_EVAL"
DEFAULT_PRIMARY_WAIT_DAYS = 10    # passes the 20-day primary standard
DEFAULT_SPECIALTY_WAIT_DAYS = 10  # passes the 28-day specialty standard
DEFAULT_PRIORITY_GROUP = 5        # MID band; choice NOT granted (5 > 4)
DEFAULT_START_DATE = "2026-09-05"     # episode opens after the clock start
DEFAULT_REQUESTED_DATE = "2026-09-02"  # VAMC timeliness anchor
DEFAULT_APPOINTMENT_DATE = "2026-09-06"  # in-window, lag 5 days from authorize
