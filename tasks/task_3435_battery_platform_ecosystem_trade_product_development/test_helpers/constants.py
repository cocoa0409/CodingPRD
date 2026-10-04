"""Domain thresholds — numeric constants stated in PRD prose.

Sources:
- Clock default:            PRD §2.5 "defaults to exactly 2026-09-01T00:00:00Z"
- Runtime derate:           PRD §3.3 (0.05 per generation step, cap 4, floor 0.8)
- Warranty month length:    PRD §3.5 ("warranty_days divided by 30")
- Legacy charger derate:    PRD §3.2 ("a legacy derate of 0.5 applies")
- Account asset limits:     PRD §3.4 (STANDARD 10 / PROFESSIONAL 100 / FLEET 1000)
- Channel allocation caps:  PRD §3.6 (HOME_CENTER 500 / INDUSTRIAL_DISTRIBUTOR 10000)
- Pro-pack capacity gate:   PRD §3.6 (216 watt-hours)
- Counterfeit threshold:    PRD §3.7 ("evidence_score of at least 70")
"""

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Runtime estimate (PRD §3.3)
GEN_GAP_EFFICIENCY_STEP = 0.05
GEN_GAP_EFFICIENCY_CAP = 4
MIN_EFFICIENCY = 0.8

# Warranty credit (PRD §3.5)
DAYS_PER_MONTH = 30

# Charge-time estimate (PRD §3.2)
LEGACY_CHARGE_DERATE = 0.5

# Account asset limits by tier (PRD §3.4)
ASSET_LIMIT_STANDARD = 10
ASSET_LIMIT_PROFESSIONAL = 100
ASSET_LIMIT_FLEET = 1000

# Channel allocation caps (PRD §3.6)
HOME_CENTER_ALLOCATION_CAP = 500
INDUSTRIAL_ALLOCATION_CAP = 10000
PRO_PACK_CAPACITY_THRESHOLD_WH = 216

# Counterfeit evidence threshold, inclusive (PRD §3.7)
COUNTERFEIT_CONFIRM_THRESHOLD = 70

# Pagination defaults (PRD §2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MAX = 100
