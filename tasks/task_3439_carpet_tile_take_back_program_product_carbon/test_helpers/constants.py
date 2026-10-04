"""Domain thresholds and program constants — only values the PRD pins verbatim.

NOTE: the take-back sort cascade (PRD §2.9, cascade C) names two program
constants — TAKEBACK_LOT_CARBON_FACTOR and TAKEBACK_SUPPLIER_NAME — but the
PRD deliberately never assigns them values. They are NOT defined here, and no
helper may assert them; a test needing a carbon factor or supplier name as an
*input* passes it explicitly to the factory.
"""

# PRD §2.5 — the logical clock reads exactly this before any client call.
LOGICAL_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# PRD §2.3 — pagination envelope defaults and bounds.
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# PRD §2.6 — canonical tile mass: every square meter masses exactly 4.0 kg.
TILE_MASS_KG_PER_M2 = 4.0

# PRD §3.3 — contractor install-window conflict buffer: one full day added at
# both ends of each closed install window.
CONTRACTOR_BUFFER_SECONDS = 86400

# PRD §3.4 — replacement quote pricing: base rate and dye-lot factors.
BASE_PRICE_CENTS_PER_M2 = 1200
EXACT_LOT_FACTOR = 1.00
OTHER_LOT_FACTOR = 1.15

# PRD §3.5 — take-back credit schedule: per-grade area rates, per-pathway
# bonus rates, and the forty-percent bonus cap.
GRADE_RATE_CENTS_PER_M2 = {"A": 250, "B": 150, "C": 40}
PATHWAY_BONUS_CENTS_PER_KG = {
    "REUSE": 30,
    "DEPOLYMERIZE": 18,
    "DOWNCYCLE": 6,
    "LANDFILL": 0,
}
BONUS_CAP_FRACTION = 0.40

# PRD §3.6 — lifecycle footprint adjustments: transport adder and the maximum
# end-of-life credit scaled by recovery share.
TRANSPORT_KGCO2E_PER_M2 = 0.35
EOL_MAX_CREDIT_KGCO2E_PER_M2 = 2.10

# PRD §3.7 — fixed buffer added to the offset requirement of CARBON_NEGATIVE
# claims only.
CARBON_NEGATIVE_BUFFER_KGCO2E = 500.0

# PRD §3.7 — offset vintage floor.
VINTAGE_YEAR_MIN = 2020
