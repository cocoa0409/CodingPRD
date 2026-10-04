"""Pure arithmetic from SCAFFOLD Table 3 (Calculation Rules Table).

All quantity arithmetic returns integers.  Division always uses a ceiling,
never round-half-up, except the redemption substitution ratio multiply which
is floored (PRD 2.9).  No `float` is used for money or for the projection.
"""

import datetime
import math
from decimal import Decimal, ROUND_FLOOR

from constants import (
    BRAND_DIRECTIVE_BASE,
    CLAIM_BACKDATE_WINDOW_DAYS,
    MARKET_DEMAND_UNITS_PER_CASE,
    PROJECTION_CEILING,
    PROJECTION_FLOOR,
    PROJECTION_MULTIPLE_OF,
    REORDER_HIT_RATE,
    SALES_HISTORY_MIN_RECORDS,
    SALES_HISTORY_UNITS_PER_CLAIM,
    SEVERITY_WEIGHT,
    SUBSTITUTION_DEADLINE_DAYS_HIGH,
    SUBSTITUTION_DEADLINE_DAYS_LOW,
    SUBSTITUTION_DIVERGENCE_CENTS,
    SUBSTITUTION_RATIO_HIGH,
    SUBSTITUTION_RATIO_LOW,
)
from errors import ApiError, ERR_INSUFFICIENT_SALES_HISTORY, ERR_MARKET_SIGNAL_UNAVAILABLE


def ceil_div_to(value, quantum):
    """Ceiling division onto a quantum.  Never round-half-up."""
    q = Decimal(quantum)
    v = Decimal(value)
    return int((v / q).to_integral_value(rounding="ROUND_CEILING") * q)


def _dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# print_run_projection (SCAFFOLD calc #1) + print_run_quality_floor (calc #2)
# ---------------------------------------------------------------------------

def sales_history_count(store, card_set_id, now):
    """Count CollectorComplaint rows in APPROVED or SETTLED whose filed_on lies
    in the half-open window (now - 30d, now].  FILED, UNDER_REVIEW and DENIED
    rows are excluded."""
    lower = now - datetime.timedelta(days=CLAIM_BACKDATE_WINDOW_DAYS)
    total = 0
    for c in store.all("collector_complaints"):
        if c["card_set_id"] != card_set_id:
            continue
        if c["status"] not in ("APPROVED", "SETTLED"):
            continue
        filed = c["filed_on"]
        if filed > lower and filed <= now:
            total += 1
    return total


def market_demand_signals(allocations, product_line_id):
    """DistributionAllocation rows for the line on HOBBY or MASS only.
    Direct-channel reservations are excluded."""
    out = []
    for a in allocations.all("distribution_allocations"):
        if a["product_line_id"] != product_line_id:
            continue
        if a["channel"] in ("HOBBY", "MASS"):
            out.append(a)
    return out


def verifiable_defect_quantity(claims, card_set_id):
    """Only QualityClaim rows in status APPROVED enter verifiable_quantity.
    FILED, UNDER_REVIEW, DENIED and CREDITED rows are excluded."""
    total = 0
    for q in claims.all("quality_claims"):
        if q["card_set_id"] != card_set_id:
            continue
        if q["status"] == "APPROVED":
            total += q["affected_quantity"]
    return total


def print_run_projection(store, decision, card_set, now):
    """The four ordered stages plus the interposed safety floor.

      1. base quantity from the authority
      2. demand multiplier
      3. tier floor, then tier ceiling
      3b. quality-claim safety floor (interposed between 3 and 4)
      4. snap upward to the tier quantum
    """
    tier = card_set["set_tier"]
    authority = decision["authority"]
    quantum = PROJECTION_MULTIPLE_OF[tier]

    # ---- Step 1: base quantity from the authority ----
    if authority == "SALES_HISTORY":
        history_count = sales_history_count(store, card_set["id"], now)
        if history_count < SALES_HISTORY_MIN_RECORDS:
            raise ApiError(
                ERR_INSUFFICIENT_SALES_HISTORY,
                "Fewer than %d qualifying complaints in the back-date window"
                % SALES_HISTORY_MIN_RECORDS,
            )
        base = Decimal(history_count * SALES_HISTORY_UNITS_PER_CLAIM)
    elif authority == "MARKET_DEMAND":
        signals = market_demand_signals(store, card_set["product_line_id"])
        if not signals:
            raise ApiError(
                ERR_MARKET_SIGNAL_UNAVAILABLE,
                "No HOBBY or MASS distribution allocation exists for the line",
            )
        allocated = sum(s["quantity_allocated"] for s in signals)
        base = Decimal(allocated * MARKET_DEMAND_UNITS_PER_CASE)
    else:  # BRAND_DIRECTIVE — reads no observed activity at all
        base = Decimal(BRAND_DIRECTIVE_BASE[tier])

    # ---- Step 2: demand multiplier ----
    scaled = base * _dec(decision["demand_multiplier"])

    # ---- Step 3: floor applied first, then ceiling ----
    floored = max(scaled, Decimal(PROJECTION_FLOOR[tier]))
    capped = min(floored, Decimal(PROJECTION_CEILING[tier]))

    # ---- Step 3b: quality-claim safety floor ----
    verifiable = verifiable_defect_quantity(store, card_set["id"])
    threshold = _dec(REORDER_HIT_RATE) * Decimal(verifiable)
    safety_floor = Decimal(ceil_div_to(threshold, quantum))
    carried = max(capped, threshold, safety_floor)

    # ---- Step 4: snap to the tier quantum ----
    return ceil_div_to(carried, quantum)


# ---------------------------------------------------------------------------
# tier_snap_aggregate (SCAFFOLD calc #8)
# ---------------------------------------------------------------------------

def tier_snap_aggregate(store, product_line_id):
    """Per-set-then-sum: snap EACH CardSet to THAT set's own tier multiple
    first, and only then sum the snapped quantities into the line total.
    Snapping the summed total once is explicitly wrong."""
    total = 0
    for s in store.all("card_sets"):
        if s["product_line_id"] != product_line_id:
            continue
        quantum = PROJECTION_MULTIPLE_OF[s["set_tier"]]
        total += ceil_div_to(s["print_run_quantity"], quantum)
    return total


# ---------------------------------------------------------------------------
# quality_claim_weight (SCAFFOLD calc #3)
# ---------------------------------------------------------------------------

def quality_claim_weight(severity):
    return SEVERITY_WEIGHT[severity]


# ---------------------------------------------------------------------------
# autograph_royalty_charge (SCAFFOLD calc #4)
# ---------------------------------------------------------------------------

def autograph_royalty_cents(allocation_lines, royalty_per_card):
    """Per-line charge summed.  Lines are processed in ascending
    (card_set_id, player_id) tuple order so the per-line ledger entries are
    reproducible; the sum itself is commutative."""
    ordered = sorted(
        allocation_lines, key=lambda l: (l["card_set_id"], l["player_id"])
    )
    return sum(royalty_per_card * l["quantity_delivered"] for l in ordered)


# ---------------------------------------------------------------------------
# redemption substitution / deadline (SCAFFOLD calc #5 and #8)
# ---------------------------------------------------------------------------

def redemption_deadline_days(estimated_value_cents):
    """730 when >= SUBSTITUTION_DIVERGENCE_CENTS, else 365.  Inclusive on the
    high side: 250000 already takes the high window."""
    if estimated_value_cents >= SUBSTITUTION_DIVERGENCE_CENTS:
        return SUBSTITUTION_DEADLINE_DAYS_HIGH
    return SUBSTITUTION_DEADLINE_DAYS_LOW


def redemption_compensation_cents(scratch_cents):
    """floor(ratio * scratch).  The single place in the platform where the
    rounding direction is downward (PRD 2.9)."""
    ratio = (
        SUBSTITUTION_RATIO_HIGH
        if scratch_cents >= SUBSTITUTION_DIVERGENCE_CENTS
        else SUBSTITUTION_RATIO_LOW
    )
    product = _dec(ratio) * Decimal(scratch_cents)
    return int(product.to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# distribution_share_projection (SCAFFOLD calc #6)
# ---------------------------------------------------------------------------

def projected_cases(store, product_line_id, incoming_quantity, exclude_id=None):
    """other_cases + the request's own quantity.  Every allocation for the line
    is counted regardless of status."""
    other = 0
    for a in store.all("distribution_allocations"):
        if a["product_line_id"] != product_line_id:
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        other += a["quantity_allocated"]
    return other + incoming_quantity


def allocation_within_capacity(store, product_line, incoming_quantity, exclude_id=None):
    """Strict greater-than: an allocation landing exactly on capacity is
    accepted."""
    cases = projected_cases(store, product_line["id"], incoming_quantity, exclude_id)
    sets_per_case = product_line["sets_per_case"]
    capacity = product_line["cases_printed"] * sets_per_case
    return cases * sets_per_case <= capacity


# ---------------------------------------------------------------------------
# license_set_counts (SCAFFOLD calc #9)
# ---------------------------------------------------------------------------

def license_set_counts(store, license_id):
    """Full traversal, never incremental, so a rollback of a set out of
    APPROVED immediately lowers approved_set_count."""
    set_count = 0
    approved = 0
    line_ids = {
        p["id"] for p in store.all("product_lines") if p["license_id"] == license_id
    }
    for s in store.all("card_sets"):
        if s["product_line_id"] in line_ids:
            set_count += 1
            if s["status"] == "APPROVED":
                approved += 1
    return set_count, approved


def reverse_foreclosure(severity):
    """Kept for symmetry with quality_claim_weight; unused arithmetic helper."""
    return math.ceil(SEVERITY_WEIGHT[severity])