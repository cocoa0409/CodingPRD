"""The 14 calculation rules of SCAFFOLD S1.3 / PRD S3.

Every function here is pure integer arithmetic.  No float, no Decimal, no
round(): PRD S2.6 fixes the whole system on integer floor division, and the
allocation primitive pins floor-then-cycle order instead of round-half-up.
"""

# ---------------------------------------------------------------- constants

ACH_STANDARD_BASE_CENTS = 25
ACH_SAME_DAY_BASE_CENTS = 500
RTP_BASE_CENTS = 75
RTP_TRANCHE_CENTS = 1000000
RTP_TRANCHE_FEE_CENTS = 100
WIRE_BASE_CENTS = 500
WIRE_TRANCHE_CENTS = 1000000
WIRE_TRANCHE_FEE_CENTS = 250
CHECK_DEBIT_BASE_CENTS = 350
CHECK_CREDIT_BASE_CENTS = 150
CREDIT_ADJUSTMENT_CENTS = 25
ACH_CAP_CENTS = 400
WIRE_CAP_CENTS = 2500
RTP_CAP_CENTS = 250
FEE_FLOOR_CENTS = 10
RETURN_LEG_FEE_CENTS = 25

DUP_WINDOW_SECONDS = 600

# ---------------------------------------------------------------- 2. ledger_balance_projection
# pending / posted partitions are derived in serializer.py (pending_balance /
# posted_balance) and recomputed by services.recompute_ledger_balances for every
# mutation.  Nothing to compute here beyond the two partition predicates.

PENDING_PARTITION = ("UNSETTLED", "IN_SETTLEMENT")


def round_half_up_to_cent(value):
    """Only used for operator-facing presentation of a fractional total (S3.x)."""
    if value is None:
        return None
    return (value * 2 + 1) // 2


# ---------------------------------------------------------------- 3. rail_fee_schedule

RAILS = ("ACH", "WIRE", "RTP", "CHECK")


def fee_base_cents(rail, direction, amount_cents, settlement_speed):
    """Base fee by rail and settlement speed, before the direction adjustment."""
    if rail == "ACH":
        return ACH_SAME_DAY_BASE_CENTS if settlement_speed == "SAME_DAY" else ACH_STANDARD_BASE_CENTS
    if rail == "RTP":
        return RTP_BASE_CENTS + (amount_cents // RTP_TRANCHE_CENTS) * RTP_TRANCHE_FEE_CENTS
    if rail == "WIRE":
        return WIRE_BASE_CENTS + (amount_cents // WIRE_TRANCHE_CENTS) * WIRE_TRANCHE_FEE_CENTS
    if rail == "CHECK":
        return CHECK_DEBIT_BASE_CENTS if direction == "DEBIT" else CHECK_CREDIT_BASE_CENTS
    raise ValueError("unknown rail %r" % (rail,))


def fee_total_cents(rail, direction, amount_cents, settlement_speed="STANDARD"):
    """Base -> direction adjustment -> rail cap -> floor.  Order is load-bearing."""
    total = fee_base_cents(rail, direction, amount_cents, settlement_speed)
    if direction == "CREDIT" and rail in ("ACH", "RTP"):
        total -= CREDIT_ADJUSTMENT_CENTS
    if rail == "ACH":
        total = min(total, ACH_CAP_CENTS)
    elif rail == "WIRE":
        total = min(total, WIRE_CAP_CENTS)
    elif rail == "RTP":
        total = min(total, RTP_CAP_CENTS)
    # CHECK carries no cap
    total = max(total, FEE_FLOOR_CENTS)
    return total


def wire_tranche_components_cents(amount_cents):
    """variant tranche_series: 500 plus 250 for every complete tranche, as a list."""
    n = amount_cents // WIRE_TRANCHE_CENTS
    out = [WIRE_BASE_CENTS]
    out.extend([WIRE_TRANCHE_FEE_CENTS] * n)
    return out


# ---------------------------------------------------------------- 4. return_recredit_allocation

def allocate_shares(total, weights):
    """Waterfall allocation: floor each share, then hand the remainder out one
    cent at a time cycling through buckets in order (PRD S3.9)."""
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0] * len(weights)
    shares = [(total * w) // weight_sum for w in weights]
    remainder = total - sum(shares)
    i = 0
    n = len(weights)
    while remainder > 0:
        shares[i % n] += 1
        remainder -= 1
        i += 1
    return shares


# ---------------------------------------------------------------- 6. rail_cutoff_resolution

LOOKAHEAD_CALENDAR_DAYS = 4


# ---------------------------------------------------------------- 7. deposit_attribution

FEE_FREE_BELOW_CENTS = 100000
MID_TIER_NUMERATOR = 10
MID_TIER_DENOMINATOR = 1000
MID_TIER_MIN_CENTS = 100
HIGH_TIER_NUMERATOR = 5
HIGH_TIER_DENOMINATOR = 1000
HIGH_TIER_MIN_CENTS = 500
HIGH_TIER_MAX_CENTS = 5000


def attributed_fee_cents(gross):
    """Fee keyed on the tier of the gross, not of the attributed amount."""
    if gross < FEE_FREE_BELOW_CENTS:
        fee = 0
    elif gross < 1000000:
        fee = max(MID_TIER_MIN_CENTS, (gross * MID_TIER_NUMERATOR) // MID_TIER_DENOMINATOR)
    else:
        fee = min(HIGH_TIER_MAX_CENTS,
                  max(HIGH_TIER_MIN_CENTS, (gross * HIGH_TIER_NUMERATOR) // HIGH_TIER_DENOMINATOR))
    return min(fee, gross)


def deposit_split(gross):
    """Returns (attributed_fee_cents, attributable_amount_cents) summing to gross."""
    fee = attributed_fee_cents(gross)
    return fee, gross - fee


# ---------------------------------------------------------------- 9/10. exception aging

CURRENT_MAX_DAYS = 1
AGING_MAX_DAYS = 3
ESCALATED_MAX_DAYS = 7


def aging_bucket(age_business_days):
    if age_business_days <= CURRENT_MAX_DAYS:
        return "CURRENT"
    if age_business_days <= AGING_MAX_DAYS:
        return "AGING"
    if age_business_days <= ESCALATED_MAX_DAYS:
        return "ESCALATED"
    return "CRITICAL"


# ---------------------------------------------------------------- 12. reverse_rail_fee_transfer

def reverse_fee_split(cover_cents, allocated_share_cents):
    """(delivered, undeliverable) for one leg.  The pair always sums to the
    allocated share, which is what keeps the conserved quantity intact."""
    if cover_cents >= allocated_share_cents:
        return allocated_share_cents, 0
    return cover_cents, allocated_share_cents - cover_cents


# ---------------------------------------------------------------- 13. settlement_pool_recompute

FORCED_FAILURE_BELOW_CENTS = 1000000
DEGRADED_AT_OR_BELOW_CENTS = 5000000


def settlement_pool_status(eligible_funds_cents):
    """Strict below 1000000 -> FAILED; inclusive at or below 5000000 -> DEGRADED."""
    if eligible_funds_cents < FORCED_FAILURE_BELOW_CENTS:
        return "FAILED"
    if eligible_funds_cents <= DEGRADED_AT_OR_BELOW_CENTS:
        return "DEGRADED"
    return "READY"


# ---------------------------------------------------------------- 14. counterparty_velocity_limit

PLATFORM_DEFAULT_LIMIT_CENTS = 5000000


def velocity_limit_effective(counterparty_limit, entity_default):
    if counterparty_limit is not None:
        return counterparty_limit
    if entity_default is not None:
        return entity_default
    return PLATFORM_DEFAULT_LIMIT_CENTS


def velocity_admits(amount_cents, limit_cents):
    """STRICT upper bound: an amount exactly at the limit is refused."""
    return amount_cents < limit_cents


# ---------------------------------------------------------------- 16. payment_dup_window

def duplicate_signature(legal_entity_id, counterparty_id, rail, direction, amount_cents):
    from utils import sha256_hex

    return sha256_hex("|".join([
        str(legal_entity_id), str(counterparty_id), str(rail),
        str(direction), str(amount_cents),
    ]))


def dup_window_blocks(now_ms, last_seen_ms):
    """INCLUSIVE at 600 seconds."""
    return (now_ms - last_seen_ms) <= DUP_WINDOW_SECONDS * 1000


# ---------------------------------------------------------------- 1. reconciliation_variance

POSTED_NET = "POSTED_NET"
SETTLED_SINGLE = "SETTLED_SINGLE"
MATCHING_ALGORITHMS = (POSTED_NET, SETTLED_SINGLE)

EXACT_AMOUNT_MATCH = True


# ---------------------------------------------------------------- 5. ledger_double_entry_identity

IDENTITY_TOLERANCE_CENTS = 0


def double_entry_identity(debits_cents, credits_cents, posted_cents, pending_cents):
    return credits_cents - debits_cents == posted_cents + pending_cents