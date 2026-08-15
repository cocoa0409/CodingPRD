"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD §2.4): startup default, never wall-clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Staffing arithmetic (PRD §3.4): two-adult minimum per enrolled classroom.
TWO_ADULT_MINIMUM = 2

# Kit recommendation (PRD §3.6): enrolled total * 1.10, rounded up.
KIT_BUFFER_MULT = 1.10

# Craft pack allocation (PRD §3.6): 3 units per child, packs of 10,
# rounded up per classroom first, then summed.
CRAFT_UNITS_PER_CHILD = 3
CRAFT_PACK_SIZE = 10

# Retention tiers (PRD §3.8): inclusive comparisons against the 4dp rate.
TIER_A_RATE = 0.80
TIER_A_BONUS_RATE = 0.60
TIER_B_RATE = 0.50

# Program defaults (PRD §3.1).
DEFAULT_CHILD_STAFF_RATIO = 4
DEFAULT_WAITLIST_TTL_HOURS = 48
DEFAULT_PICKUP_CUTOFF = "12:00"
DEFAULT_SUPPLY_BUDGET_CENTS = 100000

# Standard program shape used across fixtures: a one-week program whose
# registration window comfortably contains the default logical clock.
DEFAULT_PROGRAM = {
    "name": "VBS Alpha",
    "program_year": 2026,
    "start_date": "2026-08-17",
    "end_date": "2026-08-21",
    "registration_opens_at": "2026-07-15T00:00:00Z",
    "registration_closes_at": "2026-08-15T23:59:59Z",
    "supply_budget_cents": DEFAULT_SUPPLY_BUDGET_CENTS,
    "child_staff_ratio": DEFAULT_CHILD_STAFF_RATIO,
    "waitlist_offer_ttl_hours": DEFAULT_WAITLIST_TTL_HOURS,
    "pickup_cutoff_time": DEFAULT_PICKUP_CUTOFF,
}

# A six-year-old on the program's start_date (2026-08-17): fits band 4-6.
DEFAULT_CHILD_BIRTH_DATE = "2020-03-15"
DEFAULT_CHILD_GRADE = "KINDERGARTEN"

# Adult volunteer birth dates (well over 18 at the 2026 program start).
ADULT_BIRTH_DATE_1 = "1990-05-20"
ADULT_BIRTH_DATE_2 = "1988-02-11"

# Opaque staff caller ids (PRD §2.1: opaque, never compared to an entity id).
SAFETY_OFFICER_ID = "so-1"
CHECKIN_DESK_ID = "desk-1"
DIRECTOR_ID = "director-1"
REGISTRATION_COORDINATOR_ID = "regcoord-1"
VOLUNTEER_COORDINATOR_ID = "volcoord-1"
