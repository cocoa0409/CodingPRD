"""The fifteen calculation rules (SCAFFOLD.yaml section 1.3, PRD section 3).

Each function mirrors one scaffold rule block; the constants below are the
scaffold's own `constants:` maps verbatim.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import clock
import db
from errors import api_error

# ---------------------------------------------------------------------------
# order_totals
# ---------------------------------------------------------------------------
FINANCE_RATE_BPS_LOW = 500
FINANCE_RATE_BPS_HIGH = 1000
BASIS_TIER_CENTS = 300000
SHIPPED_STAIR_CARRY_FEE_CENTS = 0
SHIPPED_ASSEMBLY_FEE_CENTS = 0

# ---------------------------------------------------------------------------
# delivery_charge
# ---------------------------------------------------------------------------
ZONE_BASE = {"METRO": 4500, "SUBURBAN": 3600, "RURAL": 3000}
ZONE_LEGS = {"METRO": 1, "SUBURBAN": 2, "RURAL": 3}
TIER_RATE = {1: 1500, 2: 1200, 3: 900}
WEIGHT_UNITS = {
    "BIKE": 1, "REFURB_BIKE": 1, "TREAD": 2, "REFURB_TREAD": 2, "ROWER": 2,
}

# ---------------------------------------------------------------------------
# stair_carry_surcharge
# ---------------------------------------------------------------------------
FIRST_FLIGHT_FLAT_CENTS = 500
FINE_RATE_CENTS = 250
TAX_BASIS = Decimal("1.0825")
CARRY_FEE_CAP_CENTS = 2500

# ---------------------------------------------------------------------------
# installment_amounts
# ---------------------------------------------------------------------------
TERMS_ALLOWED = (6, 12, 24)
DEFAULT_APR_BPS = 0

# ---------------------------------------------------------------------------
# pause_proration
# ---------------------------------------------------------------------------
CYCLE_DAYS = 30
MAX_PAUSE_DAYS = 60

# ---------------------------------------------------------------------------
# financing_delinquency_state
# ---------------------------------------------------------------------------
DELINQUENT_RETRY_THRESHOLD = 3
DEFAULT_GRACE_DAYS = 30

# ---------------------------------------------------------------------------
# concurrent_stream_limit
# ---------------------------------------------------------------------------
DEFAULT_PLUS_STREAMS = 4
DEFAULT_BUSINESS_STREAMS = 10

# ---------------------------------------------------------------------------
# leaderboard_integrity_cap
# ---------------------------------------------------------------------------
POINTS_MULTIPLIER = 2
BENCHMARK_TOLERANCE_SECONDS = 600
POINTS_PER_PCT = {"CYCLING": 10, "RUNNING": 7, "STRENGTH": 5, "YOGA": 5}

# ---------------------------------------------------------------------------
# parts_stock_position
# ---------------------------------------------------------------------------
DEFAULT_SAFETY_STOCK_QTY = 2

# ---------------------------------------------------------------------------
# refurb_certification_chain
# ---------------------------------------------------------------------------
MAX_CHAIN_DEPTH = 3

# ---------------------------------------------------------------------------
# warranty_window
# ---------------------------------------------------------------------------
NEW_WARRANTY_DAYS = 365
RESALE_WARRANTY_DAYS = 90

# ---------------------------------------------------------------------------
# class_enrollment_count
# ---------------------------------------------------------------------------
COUNTED_STATES = ("ENROLLED", "WAITLISTED")

# ---------------------------------------------------------------------------
# run_ops_sweep
# ---------------------------------------------------------------------------
TERMINATION_GRACE_DAYS = 180


def round_half_up(value):
    """Round half up to zero decimal places, returning an int.

    PRD section 2.8: an exact half is rounded away from zero and any remainder
    below a half is discarded.  Decimal is used throughout so no monetary value
    ever passes through binary floating point.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# order_totals (dual variant: FORWARD_LOOKING / CHRONOLOGICAL)
# ---------------------------------------------------------------------------
def order_totals(order, variant):
    """Pinned evaluation order, one pass.

    basis_cents = subtotal + delivery + stair + assembly
    tier_rate_bps = basis_cents >= BASIS_TIER_CENTS ? HIGH : LOW
    finance_charge_cents = FINANCE_SCHEDULED ? round_half_up(basis * rate / 10000) : 0
    total_cents = basis_cents + finance_charge_cents

    The tier is keyed on the PRE-FINANCE basis, never on the post-finance
    total, so the circular-looking dependency terminates after one pass.
    """
    if variant == "FORWARD_LOOKING":
        delivery_fee_cents = 0
    else:
        delivery_fee_cents = order["delivery_fee_cents"]

    basis_cents = (
        order["subtotal_cents"]
        + delivery_fee_cents
        + SHIPPED_STAIR_CARRY_FEE_CENTS
        + SHIPPED_ASSEMBLY_FEE_CENTS
    )
    tier_rate_bps = (
        FINANCE_RATE_BPS_HIGH if basis_cents >= BASIS_TIER_CENTS else FINANCE_RATE_BPS_LOW
    )
    if order["financing_method"] == "FINANCE_SCHEDULED":
        finance_charge_cents = round_half_up(
            _dec(basis_cents) * _dec(tier_rate_bps) / _dec(10000)
        )
    else:
        finance_charge_cents = 0
    return {
        "basis_cents": basis_cents,
        "finance_charge_cents": finance_charge_cents,
        "total_cents": basis_cents + finance_charge_cents,
    }


def order_capture_charge(order):
    """The finance charge written at capture time.

    PRD section 3.2: the order's finance_charge_cents is the captured total
    minus the subtotal minus the delivery fee, floored at zero.
    """
    captured = order["captured_total_cents"] or 0
    value = captured - order["subtotal_cents"] - order["delivery_fee_cents"]
    return max(0, value)


# ---------------------------------------------------------------------------
# delivery_charge
# ---------------------------------------------------------------------------
def delivery_charge(hardware_sku, zone):
    """min(legs * zone_base, zone_base + weight_units * tier_rate), exact."""
    zone_base_cents = ZONE_BASE[zone]
    delivery_legs = ZONE_LEGS[zone]
    weight_units = WEIGHT_UNITS[hardware_sku]
    tier_rate_cents = TIER_RATE[delivery_legs]
    return min(
        delivery_legs * zone_base_cents,
        zone_base_cents + weight_units * tier_rate_cents,
    )


# ---------------------------------------------------------------------------
# stair_carry_surcharge
# ---------------------------------------------------------------------------
def stair_carry_surcharge(stair_flights, has_elevator):
    """Round each additive component separately, then sum, then cap."""
    eligible_flights = max(0, stair_flights - (1 if has_elevator else 0))
    billable_flights = max(0, eligible_flights - 1)
    flat_component = round_half_up(_dec(FIRST_FLIGHT_FLAT_CENTS) * TAX_BASIS)
    billable_component = round_half_up(
        _dec(billable_flights) * _dec(FINE_RATE_CENTS) * TAX_BASIS
    )
    return min(flat_component + billable_component, CARRY_FEE_CAP_CENTS)


# ---------------------------------------------------------------------------
# installment_amounts
# ---------------------------------------------------------------------------
def installment_amounts(principal_cents, apr_bps, term_months, installments_paid):
    """Ceil-first / floor-rest construction with the remainder in installment 1."""
    total_due_cents = round_half_up(
        _dec(principal_cents) * _dec(10000 + apr_bps) / _dec(10000)
    )
    base = total_due_cents // term_months
    remainder = total_due_cents - base * term_months
    first_installment = base + remainder
    if installments_paid == 0:
        monthly_installment_cents = first_installment
    elif installments_paid < term_months:
        monthly_installment_cents = base
    else:
        monthly_installment_cents = total_due_cents
    return {
        "total_due_cents": total_due_cents,
        "base": base,
        "remainder": remainder,
        "first_installment": first_installment,
        "monthly_installment_cents": monthly_installment_cents,
    }


# ---------------------------------------------------------------------------
# pause_proration
# ---------------------------------------------------------------------------
def pause_proration(membership, variant):
    """UNUSED_DAYS rounds the leftover days up; REMAINING_DAYS rounds down."""
    current = clock.now()
    paid_through = membership["paid_through_at"]
    leftover_seconds = (paid_through - current).total_seconds()
    days_left_exact = max(Decimal("0"), _dec(leftover_seconds) / _dec(86400))

    if variant == "UNUSED_DAYS":
        whole = int(days_left_exact)
        if days_left_exact > whole:
            whole += 1
        leftover_days = whole
    else:
        leftover_days = int(days_left_exact)

    capped = min(leftover_days, CYCLE_DAYS)
    return round_half_up(
        _dec(membership["monthly_fee_cents"]) * _dec(capped) / _dec(CYCLE_DAYS)
    )


def pause_credit_to_days(credit_cents, monthly_fee_cents):
    """floor(credit_cents / monthly_fee_cents * 30) whole days."""
    if monthly_fee_cents <= 0:
        return 0
    return int(
        (_dec(credit_cents) / _dec(monthly_fee_cents) * _dec(CYCLE_DAYS))
        .quantize(Decimal("1"), rounding=ROUND_FLOOR)
    )


# ---------------------------------------------------------------------------
# financing_delinquency_state
# ---------------------------------------------------------------------------
def unpaid_financing_count(membership):
    return sum(
        1
        for plan in db.STORE["financing_plans"].values()
        if plan["membership_id"] == membership["id"]
        and plan["status"] in ("DELINQUENT", "DEFAULTED")
    )


def has_defaulted_plan(membership):
    return any(
        plan["membership_id"] == membership["id"] and plan["status"] == "DEFAULTED"
        for plan in db.STORE["financing_plans"].values()
    )


def apply_delinquency_derivatives(membership):
    """Recompute the deterministic membership derivatives.

    membership.safety_gate_open is set true and plan.safety_disable_latched is
    left false: no financing state ever disables hardware safety functions.
    """
    membership["unpaid_financing_count"] = unpaid_financing_count(membership)
    membership["safety_gate_open"] = True
    if has_defaulted_plan(membership):
        membership["attr_frozen_reason"] = "FINANCING_DEFAULT"
    elif membership["attr_frozen_reason"] in ("FINANCING_DEFAULT", "OWNERSHIP_DISPUTE"):
        # No endpoint raises an ownership dispute and a discharged default
        # clears its marker; any other freeze reason is left untouched.
        if membership["attr_frozen_reason"] == "FINANCING_DEFAULT":
            membership["attr_frozen_reason"] = None
    return membership["unpaid_financing_count"]


# ---------------------------------------------------------------------------
# posture_resolution
# ---------------------------------------------------------------------------
def resolve_posture(membership):
    """OPEN | RESTRICTED | FROZEN, recomputed on every membership mutation."""
    status = membership["status"]
    has_default = any(
        plan["membership_id"] == membership["id"] and plan["status"] == "DEFAULTED"
        for plan in db.STORE["financing_plans"].values()
    )
    reason = membership["attr_frozen_reason"]

    if (
        status in ("CANCELLED", "TERMINATED")
        or has_default
        or reason in ("FINANCING_DEFAULT", "OWNERSHIP_DISPUTE")
    ):
        return "FROZEN"
    if status in ("PAUSED", "DELINQUENT") or membership["unpaid_financing_count"] >= 1:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(membership):
    membership["posture"] = resolve_posture(membership)
    return membership["posture"]


def recompute_membership(membership, bump=False):
    """Derivative sweep plus posture, optionally bumping the version."""
    apply_delinquency_derivatives(membership)
    recompute_posture(membership)
    if bump:
        db.touch(membership)
    return membership


# ---------------------------------------------------------------------------
# concurrent_stream_limit
# ---------------------------------------------------------------------------
def effective_stream_limit(membership):
    override = membership["concurrent_limit_override"]
    if override is not None:
        return override
    if membership["plan_tier"] == "BUSINESS":
        return DEFAULT_BUSINESS_STREAMS
    return DEFAULT_PLUS_STREAMS


def active_user_count(membership):
    return sum(
        1
        for user in db.STORE["household_users"].values()
        if user["membership_id"] == membership["id"]
        and user["status"] in ("ACTIVE", "PENDING_VERIFICATION")
    )


def total_streams_observed(membership):
    return sum(
        device["total_workouts"]
        for device in db.STORE["devices"].values()
        if device["membership_id"] == membership["id"]
        and device["activation_status"] in ("ACTIVE", "LOCKED")
    )


def recompute_stream_counters(membership):
    membership["concurrent_limit_effective"] = effective_stream_limit(membership)
    membership["active_user_count"] = active_user_count(membership)
    membership["total_streams_observed"] = total_streams_observed(membership)
    return membership


def eviction_candidate(membership, requesting_user_id):
    """Earliest ACTIVE non-owner member by created_at ASC, ties eviction_count DESC."""
    candidates = [
        user
        for user in db.STORE["household_users"].values()
        if user["membership_id"] == membership["id"]
        and user["role"] == "MEMBER"
        and user["status"] == "ACTIVE"
        and user["id"] != requesting_user_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda user: (user.created_at, -user["eviction_count"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# leaderboard_integrity_cap
# ---------------------------------------------------------------------------
def scheduled_seconds(session):
    """The session's own length in whole seconds, floored.

    PRD section 3.9 measures this as the scheduled length the duration ceiling
    scales: `scheduled_seconds = session.ends_at - session.starts_at`, taken in
    whole seconds.  A datetime difference yields exactly whole seconds here, so
    the floor is an identity in practice; the clamp only guards a projection.
    """
    delta = session["ends_at"] - session["starts_at"]
    value = delta.days * 86400 + delta.seconds
    return value if value > 0 else 0


def discipline_cap(session):
    """min(capacity * POINTS_MULTIPLIER, duration_cap), duration floored.

    duration_cap = capacity * (scheduled_seconds / 600), truncated to a whole
    number of points.  Integer arithmetic is used throughout so a fractional
    projection can never land a hair below its true floor.
    """
    length = scheduled_seconds(session)
    duration_cap = (session["capacity"] * length) // 600
    return min(session["capacity"] * POINTS_MULTIPLIER, duration_cap)


def integrity_points(session, output_points, benchmark_variant):
    """Returns (integrity_points, integrity_flagged, benchmark_seconds).

    The benchmark is the session's scheduled end measured in whole seconds and
    floored — that is, the scheduled length of the session.  STRICT_BENCHMARK
    uses that bar directly, so an output reaching even one second past the
    scheduled end is flagged and earns nothing; INDULGENT_BENCHMARK adds the
    600-second tolerance, so the very output STRICT flags is left unflagged and
    earns its capped points.  A low-output completion beneath both bars scores
    identically under either variant.
    """
    benchmark_seconds = scheduled_seconds(session)
    if benchmark_variant == "INDULGENT_BENCHMARK":
        benchmark_seconds += BENCHMARK_TOLERANCE_SECONDS
    flagged = output_points > benchmark_seconds
    cap = discipline_cap(session)
    points = 0 if flagged else min(output_points, cap)
    return points, flagged, benchmark_seconds


def points_per_pct(session):
    return POINTS_PER_PCT.get(session["discipline"], 0)


# ---------------------------------------------------------------------------
# parts_stock_position
# ---------------------------------------------------------------------------
def recompute_stock(part):
    part["on_hand_qty"] = part["stock_received_qty"] - part["reserved_qty"] - part["consumed_qty"]
    return part["on_hand_qty"]


def reservable_qty(part):
    return part["on_hand_qty"] - part["safety_stock_qty"]


# ---------------------------------------------------------------------------
# refurb_certification_chain
# ---------------------------------------------------------------------------
def certification_chain(batch):
    """depth(source_device), with the cycle guard.

    The recursion visits the enumerated set only through the edge
    device.certifying_device_id -> device.id, so a self-loop is detected rather
    than followed indefinitely.
    """
    depth, cyclic = db.device_certification_depth(batch["source_device_id"])
    if cyclic:
        raise api_error(
            "ERR_CERTIFICATION_CYCLE",
            "The certification lineage self-loops on the source device.",
        )
    if depth > MAX_CHAIN_DEPTH:
        raise api_error(
            "ERR_CERTIFICATION_CHAIN_EXCEEDED",
            "The certification lineage depth %d exceeds the maximum of %d."
            % (depth, MAX_CHAIN_DEPTH),
        )
    return depth


# ---------------------------------------------------------------------------
# device_entitlement
# ---------------------------------------------------------------------------
def content_access_allowed(device):
    membership = db.STORE["memberships"].get(device["membership_id"])
    posture = membership["posture"] if membership is not None else None
    return posture in ("OPEN", "RESTRICTED") and device["entitlement_lock"] is False


def recompute_device_entitlement(device):
    device["content_access_allowed"] = content_access_allowed(device)
    return device["content_access_allowed"]


# ---------------------------------------------------------------------------
# warranty_window
# ---------------------------------------------------------------------------
def delivered_warranty(delivered_at):
    return delivered_at + clock.days(NEW_WARRANTY_DAYS)


def resale_warranty(sale_at):
    return sale_at + clock.days(RESALE_WARRANTY_DAYS)


# ---------------------------------------------------------------------------
# class_enrollment_count
# ---------------------------------------------------------------------------
def recompute_enrollment_count(session):
    session["live_enrollment_count"] = sum(
        1
        for enrollment in db.STORE["class_enrollments"].values()
        if enrollment["class_session_id"] == session["id"]
        and enrollment["status"] in COUNTED_STATES
    )
    return session["live_enrollment_count"]