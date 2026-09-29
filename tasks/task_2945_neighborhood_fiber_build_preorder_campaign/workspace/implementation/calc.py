"""Domain enumerations, derived aggregates and the eight pinned calculations."""

from decimal import Decimal, ROUND_HALF_UP

from store import db, insert, new_row, now, rows

# --------------------------------------------------------------------------
# enumerations
# --------------------------------------------------------------------------

ACCOUNT_TYPES = ("RESIDENT", "PROPERTY_OWNER", "BUSINESS")
DWELLING_TYPES = ("SINGLE_FAMILY", "MDU")
SERVICEABILITIES = ("UNDETERMINED", "SERVICEABLE", "CONDITIONAL_MDU", "NOT_SERVICEABLE")
DETERMINATIONS = ("SERVICEABLE", "CONDITIONAL_MDU", "NOT_SERVICEABLE")
NOT_SERVICEABLE_REASONS = (
    "NO_ROW_ACCESS",
    "EXCESSIVE_DISTANCE",
    "MDU_AGREEMENT_UNAVAILABLE",
    "BUILD_NOT_QUALIFIED",
)
EXCEPTION_STATUSES = ("NONE", "REQUESTED", "GRANTED", "DENIED")
EXCEPTION_ACTIONS = ("REQUEST", "GRANT", "DENY")
CAMPAIGN_STATUSES = ("PREREG_OPEN", "PREREG_EXTENDED", "QUALIFIED", "NOT_QUALIFIED")
CONSTRUCTION_STATUSES = (
    "NOT_STARTED",
    "SEQUENCED",
    "IN_CONSTRUCTION",
    "SUSPENDED",
    "SERVICE_READY",
)
SUSPENSION_REASONS = ("MANUAL", "POLE_DENIED", "PERMIT_EXPIRED")
POSTURES = ("BLOCKED", "PERMIT_PENDING", "POLE_PENDING", "SUSPENDED", "READY")
PERMIT_TYPES = ("ROW", "TRAFFIC_CONTROL", "ENVIRONMENTAL")
PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")
POLE_STATUSES = ("REQUESTED", "SURVEYED", "ACCEPTED", "DENIED", "ATTACHED")
POLE_DENIAL_REASONS = ("INSUFFICIENT_CLEARANCE", "SAFETY_VIOLATION", "CAPACITY_FULL")
MDU_STATUSES = ("DRAFT", "SENT", "COUNTERED", "SIGNED", "DECLINED", "EXPIRED")
OWNER_RESPONSES = ("SIGN", "DECLINE", "COUNTER")
PLAN_TIERS = ("BASIC_300", "GIGABIT_1000", "MULTIGIG_2000")
PREORDER_STATUSES = ("PENDING", "QUALIFIED", "CONVERTED", "CANCELLED", "LAPSED")
DEPOSIT_STATUSES = ("HELD", "REFUNDED", "APPLIED", "FORFEITED")
LAPSE_REASONS = ("ZONE_NOT_QUALIFIED", "ADDRESS_NOT_COUNTED")
DROP_METHODS = ("BURY", "AERIAL")
CREW_TYPES = ("BURY", "AERIAL", "RESTORATION")
APPOINTMENT_TYPES = ("DROP_BURY", "AERIAL_DROP", "RESTORATION_FOLLOWUP")
APPOINTMENT_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
OUTCOMES = ("COMPLETED", "NO_SHOW", "CANCELLED")
CANCELLATION_REASONS = ("SUBSCRIBER_REQUEST", "CREW_UNAVAILABLE", "ZONE_SUSPENDED")
DAMAGE_TYPES = ("LAWN", "IRRIGATION", "DRIVEWAY", "UTILITY_LINE")
CLAIM_STATUSES = ("FILED", "UNDER_ASSESSMENT", "PAID", "DENIED")
ASSESSMENT_VARIANTS = ("STANDARD_SCHEDULE", "LATE_FILING_SCHEDULE")
CLAIM_DECISIONS = ("APPROVE", "DENY")
PERMIT_DECISIONS = ("APPROVE", "REJECT")
POLE_DECISIONS = ("ACCEPT", "DENY")
ENTRY_TYPES = (
    "DEPOSIT_HELD",
    "DEPOSIT_REFUNDED",
    "DEPOSIT_APPLIED",
    "DEPOSIT_FORFEITED",
    "CLAIM_PAYOUT",
)
TECHNOLOGIES = ("FIXED_WIRELESS", "DSL_PARTNER", "SATELLITE_PARTNER")
OPTION_STATUSES = ("ENABLED", "DISABLED")
OFFER_STATUSES = ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED")
OFFER_RESPONSES = ("ACCEPT", "DECLINE")
SUSPEND_ACTIONS = ("SUSPEND", "RESUME")

# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------

TWO = Decimal("0.01")
ONE = Decimal("1")


def pct(value):
    """Round half up to exactly two decimal places."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole number of cents."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def as_number(value):
    """Render a two-place Decimal for JSON."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# graph helpers
# --------------------------------------------------------------------------


def zone_addresses(zone_id):
    return [a for a in rows("service_addresses") if a["build_zone_id"] == zone_id]


def zone_preorders(zone_id):
    return [p for p in rows("preorders") if p["build_zone_id"] == zone_id]


def zone_permits(zone_id):
    return [p for p in rows("permit_applications") if p["build_zone_id"] == zone_id]


def zone_poles(zone_id):
    return [p for p in rows("pole_requests") if p["build_zone_id"] == zone_id]


def address_agreements(address_id):
    return [m for m in rows("mdu_agreements") if m["service_address_id"] == address_id]


def has_signed_agreement(address_id):
    return any(m["status"] == "SIGNED" for m in address_agreements(address_id))


def zone_appointments(zone_id):
    preorder_ids = set(p["id"] for p in zone_preorders(zone_id))
    return [a for a in rows("install_appointments") if a["preorder_id"] in preorder_ids]


def crew_appointments(crew_id):
    return [a for a in rows("install_appointments") if a["crew_id"] == crew_id]


# --------------------------------------------------------------------------
# counts_toward_threshold predicates (PRD 3.2)
# --------------------------------------------------------------------------


def address_counts(address):
    serviceability = address["serviceability"]
    if serviceability in ("UNDETERMINED", "SERVICEABLE"):
        return True
    if serviceability == "CONDITIONAL_MDU":
        return has_signed_agreement(address["id"])
    return False


def preorder_counts(preorder):
    if preorder["preorder_status"] not in ("PENDING", "QUALIFIED"):
        return False
    if preorder["deposit_status"] != "HELD":
        return False
    address = db.service_addresses.get(preorder["service_address_id"])
    if address is None:
        return False
    return address_counts(address)


# --------------------------------------------------------------------------
# zone_prereg_rate (PRD 3.3 / 3.4)
# --------------------------------------------------------------------------


def _admits(address, variant):
    serviceability = address["serviceability"]
    if variant == "PROVISIONAL":
        return serviceability in ("UNDETERMINED", "SERVICEABLE", "CONDITIONAL_MDU")
    if serviceability == "SERVICEABLE":
        return True
    if serviceability == "CONDITIONAL_MDU":
        return has_signed_agreement(address["id"])
    return False


def prereg_rate(zone, variant="PROVISIONAL"):
    """Returns (qualifying_count, rate rounded half up to two places)."""
    count = 0
    for preorder in zone_preorders(zone["id"]):
        if preorder["preorder_status"] not in ("PENDING", "QUALIFIED"):
            continue
        if preorder["deposit_status"] != "HELD":
            continue
        address = db.service_addresses.get(preorder["service_address_id"])
        if address is None or not _admits(address, variant):
            continue
        count += 1
    rate = pct(Decimal(count) * Decimal(100) / Decimal(zone["household_count"]))
    return count, rate


# --------------------------------------------------------------------------
# zone-level aggregates
# --------------------------------------------------------------------------


def make_ready_cost(zone):
    total = 0
    for pole in zone_poles(zone["id"]):
        if pole["status"] in ("ACCEPTED", "ATTACHED"):
            total += pole["make_ready_cost_cents"]
    return total


def outstanding_restoration_count(zone):
    total = 0
    for appointment in zone_appointments(zone["id"]):
        if (
            appointment["status"] == "COMPLETED"
            and appointment["restoration_required"]
            and appointment["restoration_satisfied_at"] is None
        ):
            total += 1
    return total


def approved_required_types(zone):
    required = zone["required_permit_types"]
    approved = set()
    for permit in zone_permits(zone["id"]):
        if permit["status"] == "APPROVED" and permit["permit_type"] in required:
            approved.add(permit["permit_type"])
    return approved


def readiness_posture(zone):
    """PRD 2.6. SUSPENDED dominates; then BLOCKED, PERMIT_PENDING, POLE_PENDING, READY."""
    if zone["construction_status"] == "SUSPENDED":
        return "SUSPENDED"
    required = zone["required_permit_types"]
    approved = approved_required_types(zone)
    if zone["construction_status"] == "NOT_STARTED" and len(approved) == 0:
        return "BLOCKED"
    if any(permit_type not in approved for permit_type in required):
        return "PERMIT_PENDING"
    if not any(pole["status"] == "ATTACHED" for pole in zone_poles(zone["id"])):
        return "POLE_PENDING"
    return "READY"


def crew_booked(crew):
    minutes = 0
    count = 0
    for appointment in crew_appointments(crew["id"]):
        if appointment["status"] == "SCHEDULED":
            minutes += appointment["occupied_minutes"]
            count += 1
    return minutes, count


# --------------------------------------------------------------------------
# ledger (PRD 2.8)
# --------------------------------------------------------------------------

DEPOSIT_ENTRY_TYPES = (
    "DEPOSIT_HELD",
    "DEPOSIT_REFUNDED",
    "DEPOSIT_APPLIED",
    "DEPOSIT_FORFEITED",
)


def append_entry(account_id, entry_type, amount_cents, memo, preorder_id=None,
                 damage_claim_id=None):
    entry = new_row(
        {
            "account_id": account_id,
            "preorder_id": preorder_id,
            "damage_claim_id": damage_claim_id,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "memo": memo,
            "occurred_at": now(),
        },
        versioned=False,
    )
    return insert("ledger_entries", entry)


def balances(account):
    held = 0
    credit = 0
    for entry in rows("ledger_entries"):
        if entry["account_id"] != account["id"]:
            continue
        if entry["entry_type"] in DEPOSIT_ENTRY_TYPES:
            held += entry["amount_cents"]
        elif entry["entry_type"] == "CLAIM_PAYOUT":
            credit += entry["amount_cents"]
    return held, credit


# --------------------------------------------------------------------------
# zone_readiness_score (PRD 3.5)
# --------------------------------------------------------------------------

POLE_FACTORS = {
    "ATTACHED": Decimal("1.00"),
    "ACCEPTED": Decimal("0.50"),
    "SURVEYED": Decimal("0.25"),
    "REQUESTED": Decimal("0.10"),
    "DENIED": Decimal("0.00"),
}
MAKE_READY_SATURATION = Decimal(1000000)
DEMAND_WEIGHT = Decimal(50)
PERMIT_WEIGHT = Decimal(25)
POLE_WEIGHT = Decimal(20)
PENALTY_WEIGHT = Decimal(15)


def readiness_score(zone):
    final_rate = zone["final_rate_pct"]
    threshold = zone["threshold_pct"]
    if final_rate is None:
        demand = Decimal(0)
    else:
        demand = Decimal(final_rate) / Decimal(threshold)
    if demand > ONE:
        demand = ONE

    required = zone["required_permit_types"]
    approved = approved_required_types(zone)
    permit_factor = Decimal(len(approved)) / Decimal(len(required))

    poles = zone_poles(zone["id"])
    if poles:
        pole_factor = max(POLE_FACTORS[pole["status"]] for pole in poles)
    else:
        pole_factor = Decimal("0.00")

    penalty_ratio = Decimal(make_ready_cost(zone)) / MAKE_READY_SATURATION
    if penalty_ratio > ONE:
        penalty_ratio = ONE
    penalty = penalty_ratio * PENALTY_WEIGHT

    raw = demand * DEMAND_WEIGHT + permit_factor * PERMIT_WEIGHT
    raw = raw + pole_factor * POLE_WEIGHT - penalty
    return pct(raw)


# --------------------------------------------------------------------------
# make_ready_share_allocation (PRD 3.6)
# --------------------------------------------------------------------------


def allocate(total, count):
    """Floor-then-distribute: the first `residue` recipients get one extra cent."""
    if count <= 0:
        return []
    quotient = total // count
    residue = total - quotient * count
    return [quotient + 1 if index < residue else quotient for index in range(count)]


# --------------------------------------------------------------------------
# conversion_settlement (PRD 3.7)
# --------------------------------------------------------------------------

INSTALL_BASE = {"BASIC_300": 9900, "GIGABIT_1000": 14900, "MULTIGIG_2000": 24900}
DROP_SURCHARGE = {"BURY": 15000, "AERIAL": 5000}


def settlement(preorder, drop_method):
    base = INSTALL_BASE[preorder["plan_tier"]]
    surcharge = DROP_SURCHARGE[drop_method]
    share = preorder["make_ready_share_cents"] or 0
    pre_discount = base + surcharge + share
    if pre_discount >= 50000:
        rate = Decimal("0.10")
    elif pre_discount >= 30000:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.00")
    discount = cents(Decimal(pre_discount) * rate)
    net = pre_discount - discount
    due = net - preorder["deposit_amount_cents"]
    return pre_discount, discount, due


# --------------------------------------------------------------------------
# damage_claim_assessment (PRD 3.9)
# --------------------------------------------------------------------------

DAMAGE_CAPS = {
    "LAWN": 120000,
    "IRRIGATION": 250000,
    "DRIVEWAY": 400000,
    "UTILITY_LINE": 750000,
}


def assess_claim(claim, appointment, campaign):
    cap = DAMAGE_CAPS[claim["damage_type"]]
    base = min(claim["claimed_amount_cents"], cap)
    due_by = appointment["restoration_due_by"]
    if due_by is not None and claim["filed_at"] > due_by:
        factor = Decimal(campaign["late_filing_factor"])
        variant = "LATE_FILING_SCHEDULE"
    else:
        factor = Decimal("1.00")
        variant = "STANDARD_SCHEDULE"
    return cents(Decimal(base) * factor), variant


# --------------------------------------------------------------------------
# fallback_option_selection (PRD 3.2)
# --------------------------------------------------------------------------


def select_fallback_option(address, campaign_id):
    declined = set()
    for offer in rows("fallback_offers"):
        if offer["service_address_id"] == address["id"] and offer["status"] == "DECLINED":
            declined.add(offer["fallback_option_id"])
    pool = []
    for option in rows("fallback_options"):
        if option["campaign_id"] != campaign_id:
            continue
        if option["option_status"] != "ENABLED":
            continue
        if option["max_serviceable_distance_m"] < address["distance_to_node_m"]:
            continue
        if address["dwelling_type"] == "MDU" and not option["supports_mdu"]:
            continue
        if option["id"] in declined:
            continue
        pool.append(option)
    if not pool:
        return None
    pool.sort(
        key=lambda o: (
            -o["min_downstream_mbps"],
            o["monthly_price_cents"],
            o["priority_rank"],
            o["created_at"],
            o["_seq"],
        )
    )
    return pool[0]
