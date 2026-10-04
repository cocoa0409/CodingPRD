"""Named constants.

Values pinned by PRD.md / SCAFFOLD.yaml are used verbatim.  A handful of
symbols are named by the specification but never given a literal value in
either document; the reading chosen for each of those is recorded here.

Unpinned symbols and the reading chosen:
  INITIAL_FUEL_INVENTORY_THERMS   operator-funded opening fuel pool, 1,000,000 therms
  KW_PER_SQM                      installation density, 10 kW of capacity per m2
  MIN_RESUME_DRAW_THERMS          resume floor, 1,000 therms
  MAX_ACTIVE_DEMANDS_PER_SITE     simultaneous commitment ceiling, 5
  MAINTENANCE_GAP_DAYS            pairwise window separation, 7 days
  MODULE_DISPATCH_HOLD_DAYS       monitoring-degradation tolerance, 7 days
  MODULE_REPLACEMENT_REVERT_HOURS deferred hardware revert, 24 hours
  SETTLEMENT_REVERSAL_WINDOW_DAYS reversal window, 15 days
  ACCRUAL_RECONCILE_SLA_DAYS      stale-accrual age, 1 day
  TRANSFER_TOKEN_GRANT            tokens granted on transfer, 1
  DAILY_KW_CHARGE_CENTS_PER_KW    daily fixed leg of an allowance, 1 cent/kW/day
  CANDIDATE_PPA_DISTANCE_KM       transfer distance recorded for a candidate, 0.0
"""

# --- fuel pool and site physicals -------------------------------------------
INITIAL_FUEL_INVENTORY_THERMS = 1000000.0
KW_PER_SQM = 10.0
MIN_RESUME_DRAW_THERMS = 1000.0
MAX_ACTIVE_DEMANDS_PER_SITE = 5

# --- service / hardware ------------------------------------------------------
MAINTENANCE_GAP_DAYS = 7
MODULE_DISPATCH_HOLD_DAYS = 7
MODULE_REPLACEMENT_REVERT_HOURS = 24

# --- settlement windows ------------------------------------------------------
SETTLEMENT_REVERSAL_WINDOW_DAYS = 15
ACCRUAL_RECONCILE_SLA_DAYS = 1
FORECAST_WINDOW_DAYS = 15
FORECAST_DISCOUNT_PCT = 0.85

# --- tokens ------------------------------------------------------------------
TRANSFER_TOKEN_GRANT = 1
EARNED_TOKEN_PER_REVERSAL = 1
SPENT_TOKEN_PER_REVERSAL = 2
TOKEN_FLOOR = 0

# --- contract terms and escalation ------------------------------------------
COMMITTED_TERMS = (10, 12, 15, 20)
ESCALATOR_MAX_PCT = 0.06
CONTRACT_DAYS_PER_YEAR = 365
HOURS_PER_DAY = 24
EXTENSION_DAYS_MAX = 30

# --- fuel pricing ------------------------------------------------------------
HARD_CAP_CENTS_PER_THERM = 14.0
INDEX_CEILING_MULTIPLE = 1.5
SOURCED_INDEX_CEILING_MULTIPLE = 1.25

# --- reserves, stop-loss and credit caps ------------------------------------
AVAILABILITY_PENALTY_MULTIPLE = 1.20
AVAILABILITY_CREDIT_MONTHLY_DRAW_PCT = 0.60
SETTLEMENT_CREDIT_CAP_CENTS = 50000000
CAPACITY_RESERVE_PRE_DEFAULT_CENTS = 1000000
LOSS_ALLOCATION_PCT = 0.04

# --- settlement line assembly ------------------------------------------------
TAX_DELTA_PCT = 0.06
PERIOD_ALLOCATION_CENT_CAP = 75000
ALLOCATION_DISCOUNT_CEILING_PCT = 0.35
TRUEUP_EXCESS_PCT = 0.15
POOL_OPENING_CENTS = 500000

# --- guarantee remedy --------------------------------------------------------
ENERGY_REMEDY_PCT = 0.92
OUTPUT_REMEDY_REFERENCE_CENTS = 380000
OUTPUT_REMEDY_TIER0_CENTS = 100000
OUTPUT_REMEDY_TIER1_CENTS = 90000
TIER0_PAYOUT_PCT = 1.35
TIER1_PAYOUT_PCT = 0.80
HIGH_LOAD_TIER_1_MULTIPLE = 1.75
HIGH_LOAD_TIER_2_MULTIPLE = 1.55

# --- allowances --------------------------------------------------------------
DAILY_ENERGY_CAP_CENTS = 250000
DAILY_KWH_DIVISOR = 30
DAILY_KW_CHARGE_CENTS_PER_KW = 1

# --- commitment allocation ---------------------------------------------------
SCOPE_RATIO_CEILING = 3
ALLOCATION_CEILING_PCT = 0.55
FALLBACK_BINDING_PCT = 0.55
EXCESS_ALLOCATION_TOLERANCE_PCT = 0.10
CANDIDATE_PPA_DISTANCE_KM = 0.0

# --- transfer valuation ------------------------------------------------------
DOWN_PAYMENT_1_PCT = 0.055
DOWN_PAYMENT_2_PCT = 0.035
DOWN_PAYMENT_3_PCT = 0.02
TERM_DISCOUNT_CENTS_PER_YEAR = 100
SUMMER_HEAT_DELTA = 0.10
SUMMER_HEAT_MAX = 0.35
SUMMER_HEAT_MULTIPLIER = 0.018
WINTER_HEAT_DELTA = 0.25
WINTER_HEAT_MAX = 0.40
WINTER_HEAT_DIVISOR = 2.0
SUMMER_GRID_FEE_CENTS = 1000
HEATING_BASE_CENTS = 100
BASELINE_DEGRADE_PCT = 0.25
DEFAULT_EXCISE_RATE = 0.0385
FIXED_LINE_CENTS = 1000
OTHER_CENTS = 1000
OUTAGE_FIXED_LINE_THRESHOLD = 3
CONTRIBUTION_TERM_YEARS = 15
REBATE_CENTS = 0
HAS_HEATING = 1
SUMMER_MONTHS = (6, 7, 8, 9)

# --- exit / interconnection --------------------------------------------------
DEFAULT_STANDBY_MONTHS = 12
DAILY_KW_HOURS = 24

# --- home availability -------------------------------------------------------
AVAILABILITY_HEADROOM_CEILING_PCT = 0.2
AVAILABILITY_FALLBACK_PCT = 1.0
PR_YEAR_LOAD_FALLBACK_PCT = 1.0
SPECIAL_AGE_FALLBACK_PCT = 0.35

# --- two-offtaker savings ----------------------------------------------------
RATE_CAP_REFERENCE_CENTS = 300000
BASE_SAVINGS_REFERENCE_CENTS = 2
DEFAULT_RATE_DIFFERENCE_CENTS_PER_KWH = 2.2
MAX_SAVINGS_CAP_CENTS = 1500000

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- pagination --------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- roles -------------------------------------------------------------------
ROLES = (
    "SiteOperator",
    "Customer",
    "CustomerService",
    "FuelCoordinator",
    "ServiceEngineer",
    "SettlementAnalyst",
    "SettlementApprover",
)
ENTITY_BACKED_ROLES = {"Customer": "Customer"}

# --- state vocabularies ------------------------------------------------------
SITE_STATUSES = ("SITE_ACTIVE", "SITE_SUSPENDED")
SITE_LIFECYCLES = ("RESOURCE_AVAILABLE", "RESOURCE_DRAWING", "RESOURCE_CLOSED")
CREDIT_TIERS = ("CREDIT_PRIME", "CREDIT_STANDARD", "CREDIT_SUBSTANDARD")
RENEWAL_STAGES = ("RENEWAL_NONE", "RENEWAL_OFFERED", "RENEWAL_ACCEPTED", "RENEWAL_DECLINED")
CUSTOMER_STATUSES = ("CUSTOMER_ACTIVE", "CUSTOMER_CREDIT_HOLD", "CUSTOMER_SUSPENDED")
PPA_STATES = ("PPA_DRAFT", "PPA_ACTIVE", "PPA_SUSPENDED", "PPA_EXIT_PENDING", "PPA_TERMINATED")
PPA_BASES = ("PPA_BASIS_AS_BUILT", "PPA_BASIS_TRANSFERRED")
TRANSFER_STAGES = ("TRANSFER_NONE", "TRANSFER_BLOCKED")
SERVICE_STATES = (
    "SERVICE_PLAN_DRAFT",
    "SERVICE_ACTIVE",
    "SERVICE_MAINTENANCE_WINDOW_OPEN",
    "SERVICE_SUSPENDED",
    "SERVICE_ARCHIVED",
)
REPLACEMENT_STAGES = (
    "REPLACEMENT_NONE",
    "REPLACEMENT_SCHEDULED",
    "REPLACEMENT_DISPATCHED",
    "REPLACEMENT_BLOCKED",
)
MONITORING_STATUSES = ("MONITORING_LINKED", "MONITORING_DEGRADED")
DELIVERY_STATES = (
    "DELIVERY_SCHEDULED",
    "DELIVERY_IN_TRANSIT",
    "DELIVERY_CONFIRMED",
    "DELIVERY_CANCELLED",
    "DELIVERY_SETTLED",
)
SOURCING_MODES = ("FIXED_PRICE_BLEND", "INDEXED_BLEND")
SETTLEMENT_STATES = (
    "SETTLEMENT_DRAFT",
    "SETTLEMENT_VALIDATED",
    "SETTLEMENT_APPROVED",
    "SETTLEMENT_APPLIED",
    "SETTLEMENT_REVERSED",
)
ALLOCATION_BASES = ("UNIT_INDEX", "ALLOCATION_ORDER")
ACCRUAL_TYPES = ("CHARGE_ACCRUAL", "OUTPUT_GUARANTEE_ACCRUAL", "TRUEUP_ACCRUAL", "CAPACITY_ACCRUAL")
ACCRUAL_STATES = ("ACCRUAL_OPEN", "ACCRUAL_RECONCILED")
ALLOWANCE_KINDS = ("AVOIDED_COST_ALLOWANCE", "CAPACITY_ALLOWANCE")
ALLOWANCE_STATES = ("ALLOWANCE_ISSUED", "ALLOWANCE_APPLIED")
ALLOWANCE_DIRECTIONS = ("ALLOWANCE_APPLIED_AS_TIME", "ALLOWANCE_APPLIED_AS_REVERSAL")
FUEL_RESPONSIBILITIES = ("PPA_FUEL_INCLUDED", "CUSTOMER_SOURCED_GAS")
FREEZE_REASONS = ("FUEL_SHORTAGE", "GRID_INTERCONNECT_FAILURE", "NONPAYMENT", "CUSTOMER_REQUEST")

# --- endpoints (method, path) -> admitted roles ------------------------------
ENDPOINT_ROLES = {
    ("POST", "/power/sites"): ("SiteOperator",),
    ("GET", "/power/sites"): ("SiteOperator", "CustomerService", "SettlementAnalyst",
                              "SettlementApprover", "FuelCoordinator"),
    ("GET", "/power/sites/{id}"): ("SiteOperator", "CustomerService", "SettlementAnalyst",
                                   "SettlementApprover", "FuelCoordinator"),
    ("GET", "/power/sites/{id}/ppas"): ("SiteOperator", "CustomerService",
                                        "SettlementAnalyst", "SettlementApprover"),
    ("POST", "/power/sites/{id}/evaluate"): ("SiteOperator",),
    ("POST", "/power/sites/{id}/freeze"): ("SiteOperator",),
    ("POST", "/power/sites/{id}/unfreeze"): ("SiteOperator",),
    ("POST", "/power/sites/{id}/transfer-ppa"): ("SiteOperator",),
    ("POST", "/power/customers"): ("CustomerService",),
    ("GET", "/power/customers"): ("CustomerService", "SiteOperator", "SettlementAnalyst"),
    ("GET", "/power/customers/{id}"): ("CustomerService", "SiteOperator", "SettlementAnalyst"),
    ("GET", "/power/customers/{id}/ppas"): ("CustomerService", "SettlementAnalyst",
                                            "SettlementApprover", "Customer"),
    ("GET", "/power/customers/{id}/fuel-deliveries"): ("CustomerService", "FuelCoordinator"),
    ("POST", "/power/customers/{id}/apply-exposure-hold"): ("CustomerService",),
    ("POST", "/power/customers/{id}/release-exposure-hold"): ("CustomerService",),
    ("POST", "/power/customers/{id}/offer-renewal"): ("CustomerService",),
    ("POST", "/power/customers/{id}/accept-renewal"): ("CustomerService",),
    ("POST", "/power/customers/{id}/decline-renewal"): ("CustomerService",),
    ("POST", "/power/ppas"): ("SiteOperator",),
    ("GET", "/power/ppas"): ("SiteOperator", "CustomerService", "SettlementAnalyst",
                             "SettlementApprover"),
    ("GET", "/power/ppas/{id}"): ("SiteOperator", "CustomerService", "SettlementAnalyst",
                                  "SettlementApprover", "Customer"),
    ("GET", "/power/ppas/{id}/transfers"): ("SiteOperator", "CustomerService"),
    ("POST", "/power/ppas/{id}/activate"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/request-exit"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/cure"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/terminate"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/renew"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/adjust-contract"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/service-plans"): ("ServiceEngineer",),
    ("GET", "/power/ppas/{id}/service-plans"): ("ServiceEngineer", "SiteOperator",
                                                "SettlementAnalyst"),
    ("GET", "/power/ppas/{id}/service-plans/{id}"): ("ServiceEngineer", "SiteOperator"),
    ("POST", "/power/ppas/{id}/service-plans/{id}/schedule-replacement"): ("ServiceEngineer",),
    ("POST", "/power/ppas/{id}/service-plans/{id}/dispatch-module-replacement"): ("ServiceEngineer",),
    ("POST", "/power/sites/{id}/fuel-deliveries"): ("FuelCoordinator",),
    ("GET", "/power/sites/{id}/fuel-deliveries"): ("FuelCoordinator", "SiteOperator",
                                                   "SettlementAnalyst"),
    ("GET", "/power/sites/{id}/fuel-deliveries/{id}"): ("FuelCoordinator", "SiteOperator"),
    ("POST", "/power/sites/{id}/fuel-deliveries/{id}/dispatch"): ("FuelCoordinator",),
    ("POST", "/power/sites/{id}/fuel-deliveries/{id}/confirm"): ("FuelCoordinator",),
    ("POST", "/power/sites/{id}/fuel-deliveries/{id}/cancel"): ("FuelCoordinator",),
    ("POST", "/power/sites/{id}/resource-holds"): ("SiteOperator",),
    ("POST", "/power/sites/{id}/release-resource-hold"): ("SiteOperator",),
    ("POST", "/power/ppas/{id}/settlement-lines"): ("SettlementAnalyst",),
    ("GET", "/power/ppas/{id}/settlement-lines"): ("SettlementAnalyst", "SettlementApprover",
                                                   "SiteOperator"),
    ("GET", "/power/ppas/{id}/settlement-lines/{id}"): ("SettlementAnalyst", "SettlementApprover"),
    ("POST", "/power/ppas/{id}/settlement-lines/{id}/validate"): ("SettlementAnalyst",),
    ("POST", "/power/ppas/{id}/settlement-lines/{id}/approve"): ("SettlementApprover",),
    ("POST", "/power/ppas/{id}/settlement-lines/{id}/settle"): ("SettlementApprover",),
    ("POST", "/power/ppas/{id}/settlement-lines/{id}/reverse"): ("SettlementApprover",),
    ("POST", "/power/ppa-accruals"): ("SettlementAnalyst",),
    ("GET", "/power/ppa-accruals"): ("SettlementAnalyst", "SettlementApprover", "SiteOperator"),
    ("GET", "/power/ppa-accruals/{id}"): ("SettlementAnalyst", "SettlementApprover"),
    ("GET", "/power/ppa-accruals/{id}/applied-allowances"): ("SettlementAnalyst",
                                                             "SettlementApprover"),
    ("POST", "/power/ppas/{id}/reconcile-accruals"): ("SettlementAnalyst",),
    ("GET", "/power/ppas/{id}/fuel-deliveries"): ("FuelCoordinator", "SettlementAnalyst"),
    ("POST", "/power/ppas/{id}/allowances"): ("SettlementAnalyst",),
    ("GET", "/power/ppas/{id}/allowances"): ("SettlementAnalyst", "SettlementApprover"),
    ("GET", "/power/ppas/{id}/allowances/{id}"): ("SettlementAnalyst", "SettlementApprover"),
    ("POST", "/power/ppas/{id}/allowances/{id}/apply"): ("SettlementAnalyst",),
    ("GET", "/power/ppa-transitions"): ("SiteOperator", "CustomerService", "SettlementAnalyst"),
    ("GET", "/power/ppa-transitions/{id}"): ("SiteOperator", "SettlementAnalyst"),
    ("GET", "/power/ppas/{id}/transitions"): ("SiteOperator", "SettlementAnalyst"),
    ("POST", "/power/_ops/recompute-index-bases"): ("SiteOperator",),
    ("POST", "/power/_ops/rollover-period"): ("SiteOperator",),
    ("POST", "/power/_clock/set_current_utc"): ("SiteOperator",),
}
