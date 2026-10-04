"""Domain thresholds and constants — every value copied verbatim from PRD.md.

Source lines:
- PRICE_LADDER_CENTS:      PRD §3.1 "whose five rungs are exactly 39900, 59900, 89900, 129900, and 189900 cents"
- CLEARANCE_MARKDOWN_KEEP: PRD §3.1 "the clearance keep CLEARANCE_MARKDOWN_KEEP of 0.75"
- LICENSEE_DISCOUNT_RATE:  PRD §3.5 "the licensee discount LICENSEE_DISCOUNT_RATE is 0.30"
- TIER qtys/rates:         PRD §3.5 "0.14 when ... TIER3_QTY threshold of 50 ... 0.09 when ... TIER2_QTY ... 25 ... 0.05 when ... TIER1_QTY ... 10"
- Licensee defaults:       PRD §3.2 "defaults to 0.04 ... defaults to \"MS-2026.1\" ... defaults to 80"
- MAX_TERRITORIES:         PRD §3.2 "the MAX_TERRITORIES_PER_LICENSEE cap of 3"
- Waterfall:               PRD §3.4 "WHOLESALE_FLOOR_PCT, fixed at 0.25, and LICENSEE_GUARANTEE_PCT, fixed at 0.60"
- CONSTRAINED halving:     PRD §3.4 "half of that figure rounded down to a whole unit while the factory is CONSTRAINED"
- Delivery fees:           PRD §3.6 "CALL_OUT_CENTS of 14900 ... 0 ... LOCAL, 5000 ... REGIONAL, 12000 ... EXTENDED ...
                           2500 cents per crew unit ... OVERAGE_BLOCK_MINUTES (30 minutes) ... OVERAGE_CENTS, 4000 ...
                           STAIRS_FREE_FLIGHTS is 1 ... STAIRS_CENTS, 1500"
- DC crew default:         PRD §3.6 "daily_crew_units ... defaults to 6 and must lie between 1 and 20 inclusive"
- Temporal:                PRD §2.5 "MISSED_GRACE_MINUTES of 120 minutes"; PRD §3.6 "DELIVERY_MIN_LEAD_HOURS — 48 hours";
                           PRD §3.6 "WINDOW_MIN_MINUTES (120 minutes) and WINDOW_MAX_MINUTES (360 minutes)"
- Warranty windows:        PRD §3.7 "within 365 days ... DAMAGE_IN_TRANSIT claims within 30 days"
- Chargeback:              PRD §3.7 "the CHARGEBACK_RATE of 0.15"
- Info budget:             PRD §3.7 "at most INFO_REQUEST_MAX (2) times"
- Performance:             PRD §3.8 "PERF_PROBATION_THRESHOLD of 60.00 ... PERF_RECOVERY_THRESHOLD of 75.00 ...
                           PERF_SUSPENSION_THRESHOLD of 40.00"; "SEASONED_WEIGHTS of 0.4, 0.3, 0.2, and 0.1"
- Clock:                   PRD §2.5 "At startup the logical clock is exactly 2026-09-01T00:00:00Z"
"""

# --- catalog / pricing -------------------------------------------------------
PRICE_LADDER_CENTS = [39900, 59900, 89900, 129900, 189900]
CLEARANCE_MARKDOWN_KEEP = 0.75
LICENSEE_DISCOUNT_RATE = 0.30
TIER1_QTY = 10
TIER2_QTY = 25
TIER3_QTY = 50
TIER1_RATE = 0.05
TIER2_RATE = 0.09
TIER3_RATE = 0.14

# --- licensee program ----------------------------------------------------------
DEFAULT_ROYALTY_RATE = 0.04
DEFAULT_MERCHANDISING_STANDARD_VERSION = "MS-2026.1"
DEFAULT_AUDIT_SCORE = 80
MAX_TERRITORIES_PER_LICENSEE = 3

# --- capacity waterfall --------------------------------------------------------
WHOLESALE_FLOOR_PCT = 0.25
LICENSEE_GUARANTEE_PCT = 0.60
CONSTRAINED_CAPACITY_FRACTION = 0.5

# --- home delivery fees --------------------------------------------------------
CALL_OUT_CENTS = 14900
ZONE_CENTS = {"LOCAL": 0, "REGIONAL": 5000, "EXTENDED": 12000}
CREW_CENTS = 2500
OVERAGE_BLOCK_MINUTES = 30
OVERAGE_CENTS = 4000
STAIRS_FREE_FLIGHTS = 1
STAIRS_CENTS = 1500
DEFAULT_DAILY_CREW_UNITS = 6

# --- temporal rules ------------------------------------------------------------
MISSED_GRACE_MINUTES = 120
DELIVERY_MIN_LEAD_HOURS = 48
WINDOW_MIN_MINUTES = 120
WINDOW_MAX_MINUTES = 360
WARRANTY_WINDOW_DEFECT_DAYS = 365
WARRANTY_WINDOW_DIT_DAYS = 30

# --- warranty / royalty ledger ---------------------------------------------------
CHARGEBACK_RATE = 0.15
INFO_REQUEST_MAX = 2

# --- performance standards -------------------------------------------------------
PERF_PROBATION_THRESHOLD = 60.00
PERF_SUSPENSION_THRESHOLD = 40.00
PERF_RECOVERY_THRESHOLD = 75.00
SEASONED_WEIGHTS = [0.4, 0.3, 0.2, 0.1]

# --- logical clock -----------------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- test convenience: canonical week starts (Monday-aligned, midnight-aligned) -----
WEEK_1_START = "2026-09-07T00:00:00Z"
WEEK_2_START = "2026-09-14T00:00:00Z"
WEEK_3_START = "2026-09-21T00:00:00Z"
