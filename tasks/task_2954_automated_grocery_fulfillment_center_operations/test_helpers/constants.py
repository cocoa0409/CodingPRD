"""Named constants taken from the PRD.

Nothing here is invented: every value below is stated in the requirements
document, and tests reference these names instead of repeating literals.
"""

# ─── Money and basket rules ──────────────────────────────────────────────────

#: Minimum merchandise subtotal (ten dollars) required to book a delivery slot.
MINIMUM_ORDER_CENTS = 1000

#: A merchandise subtotal at or above this figure earns free delivery.
FREE_DELIVERY_THRESHOLD_CENTS = 10000

#: PREMIER shoppers take the larger discount rate at or above this subtotal.
LOYALTY_TIER_THRESHOLD_CENTS = 5000

#: Discount rate applied to a PLUS shopper's merchandise subtotal.
PLUS_DISCOUNT_PCT = 0.05

#: Discount rate applied to a PREMIER shopper at or above the tier threshold.
PREMIER_DISCOUNT_PCT_HIGH = 0.10

#: Discount rate applied to a PREMIER shopper below the tier threshold.
PREMIER_DISCOUNT_PCT_LOW = 0.05


# ─── Surge multiplier ────────────────────────────────────────────────────────

#: Lower clamp on the surge multiplier.
SURGE_FLOOR = 1.0

#: Upper clamp on the surge multiplier.
SURGE_CEILING = 1.8

#: Utilisation at or above which the high utilisation premium applies.
UTIL_TIER_HIGH = 0.85
UTIL_HIGH_ADD = 0.35

#: Utilisation at or above which the middle utilisation premium applies.
UTIL_TIER_MID = 0.60
UTIL_MID_ADD = 0.15

#: Lead time strictly below this many hours earns the short-lead premium.
LEAD_SHORT_HOURS = 12
LEAD_SHORT_ADD = 0.20

#: Lead time strictly below this many hours earns the middle-lead premium.
LEAD_MID_HOURS = 36
LEAD_MID_ADD = 0.10

#: Congestion premium added per wave already formed on the slot.
CONGESTION_ADD_PER_WAVE = 0.05

#: Number of waves at which the congestion premium stops growing.
CONGESTION_WAVE_CAP = 3


# ─── Grid, cold chain and audits ─────────────────────────────────────────────

#: Turnaround buffer applied to both sides of a maintenance window.
MAINTENANCE_BUFFER_MINUTES = 15

#: Unit-weighted accuracy strictly below this figure puts a zone on hold.
ACCURACY_HOLD_THRESHOLD = 0.98

#: Deterministic ordering across temperature classes: frozen first.
ZONE_RANK = {"FROZEN": 0, "CHILLED": 1, "AMBIENT": 2}

#: Grams in a kilogram, for catchweight pricing.
GRAMS_PER_KG = 1000


# ─── Substitutions and waitlist ──────────────────────────────────────────────

#: Approval clock granted to a proposal when it is sent to the customer.
PROPOSAL_TTL_MINUTES = 120

#: At most one waitlisted booking is promoted per capacity-freeing request.
MAX_PROMOTIONS_PER_REQUEST = 1


# ─── Logical clock ───────────────────────────────────────────────────────────

#: The instant the logical clock holds when the service boots.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"
