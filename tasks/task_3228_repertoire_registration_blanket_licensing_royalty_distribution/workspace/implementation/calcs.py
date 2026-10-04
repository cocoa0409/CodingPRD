"""Calculation rules: fee_engine, sampled_projection, performance_weight,
royalty_pool, royalty_allocation, admin_fee."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from store import DB, new_resource, touch, err

# --- fee_engine constants ---
BCAST_T1_CAP = 500_000_000_000
BCAST_T1_RATE = Decimal("0.0160")
BCAST_T2_CAP = 2_000_000_000_000
BCAST_T2_RATE = Decimal("0.0140")
BCAST_T3_RATE = Decimal("0.0110")
BCAST_MIN_FEE = 25_000_000

DIG_T1_CAP = 100_000_000_000
DIG_T1_RATE = Decimal("0.0175")
DIG_T2_RATE = Decimal("0.0150")
PER_STREAM_MICRO_CENTS = 20
DIG_MIN_FEE = 10_000_000

VENUE_RATE = Decimal("0.0080")
VENUE_PER_EVENT_CENTS = 15_000
VENUE_MIN_FEE = 5_000_000

# --- performance weighting ---
MEDIUM_FACTORS = {
    "TERRESTRIAL_RADIO": Decimal("1.0"),
    "NETWORK_TV": Decimal("2.5"),
    "CABLE_TV": Decimal("1.5"),
    "DIGITAL_STREAMING": Decimal("0.6"),
    "LIVE_VENUE": Decimal("1.2"),
}
DAYPART_FACTORS = {
    "PRIME": Decimal("2.0"),
    "DAY": Decimal("1.0"),
    "LATE_NIGHT": Decimal("0.7"),
    "OVERNIGHT": Decimal("0.4"),
}
FEATURE_BONUS_MULT = Decimal("1.1")
SAMPLING_FRAME_UNITS = 52

# --- pool / admin ---
ADMIN_RATE = Decimal("0.15")
ADMIN_WITHHOLD_RATE = Decimal("0.05")
DAYS_IN_YEAR = 365
CLAIMS_WINDOW_DAYS = 90
ESCHEAT_GRACE_DAYS = 30
LICENSEE_DELINQUENCY_THRESHOLD_CENTS = 1_000_000
AUDIT_LOOKBACK_DAYS = 1095


def round_half_up_cents(d):
    """Round a Decimal to whole cents, half-up, returning int."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_engine(category, revenue_cents, usage_units):
    """Compute blanket_fee_cents. Marginal tiers + per-usage charge; final
    max(fee, min_fee) rounded half-up once to whole cents."""
    revenue = Decimal(revenue_cents)
    usage = Decimal(usage_units)
    if category == "BROADCASTER":
        fee = Decimal(0)
        t1 = min(revenue, Decimal(BCAST_T1_CAP))
        fee += t1 * BCAST_T1_RATE
        if revenue > BCAST_T1_CAP:
            t2 = min(revenue, Decimal(BCAST_T2_CAP)) - Decimal(BCAST_T1_CAP)
            fee += t2 * BCAST_T2_RATE
        if revenue > BCAST_T2_CAP:
            t3 = revenue - Decimal(BCAST_T2_CAP)
            fee += t3 * BCAST_T3_RATE
        min_fee = Decimal(BCAST_MIN_FEE)
    elif category == "DIGITAL_SERVICE":
        fee = Decimal(0)
        t1 = min(revenue, Decimal(DIG_T1_CAP))
        fee += t1 * DIG_T1_RATE
        if revenue > DIG_T1_CAP:
            t2 = revenue - Decimal(DIG_T1_CAP)
            fee += t2 * DIG_T2_RATE
        fee += usage * Decimal(PER_STREAM_MICRO_CENTS) / Decimal(10000)
        min_fee = Decimal(DIG_MIN_FEE)
    else:  # VENUE
        fee = revenue * VENUE_RATE + usage * Decimal(VENUE_PER_EVENT_CENTS)
        min_fee = Decimal(VENUE_MIN_FEE)
    return round_half_up_cents(max(fee, min_fee))


def sampled_universe(source, play_count, frame_units_reported):
    """universe_estimated_plays: census sources -> play_count; SAMPLE rows expand."""
    if source == "SAMPLE":
        projected = Decimal(play_count) * Decimal(SAMPLING_FRAME_UNITS) / Decimal(
            frame_units_reported
        )
        rounded = int(projected.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return max(play_count, rounded)
    return play_count


def compute_credit_units(work_id, medium, daypart, universe):
    """credit_units = medium_factor * daypart_factor [*1.1 if >2 ACCEPTED writer claims] * universe, 4dp half-up."""
    base = MEDIUM_FACTORS[medium] * DAYPART_FACTORS[daypart]
    writer_count = 0
    for claim in DB["share_claims"].values():
        if (
            claim["work_id"] == work_id
            and claim["status"] == "ACCEPTED"
            and claim["role"] == "WRITER"
        ):
            writer_count += 1
    if writer_count > 2:
        base = base * FEATURE_BONUS_MULT
    cu = base * Decimal(universe)
    cu = cu.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(cu)


def license_intersects_period(lic, period_start, period_end):
    eff = date.fromisoformat(lic["effective_date"])
    exp = date.fromisoformat(lic["expiry_date"])
    return eff <= period_end and exp >= period_start


def covered_days(lic, period_start, period_end):
    eff = date.fromisoformat(lic["effective_date"])
    exp = date.fromisoformat(lic["expiry_date"])
    lo = max(eff, period_start)
    hi = min(exp, period_end)
    if hi < lo:
        return 0
    return (hi - lo).days + 1  # inclusive both ends


def compute_pool_amount(period_start, period_end):
    """Sum of prorated pinned fee bases (truncated per license) * (1 - ADMIN_RATE), rounded once."""
    gross = 0
    for lic in DB["licenses"].values():
        if lic["status"] == "TERMINATED":
            continue
        if not license_intersects_period(lic, period_start, period_end):
            continue
        days = covered_days(lic, period_start, period_end)
        per_license = (lic["fee_basis_cents"] * days) // DAYS_IN_YEAR
        gross += per_license
    pool = Decimal(gross) * (Decimal(1) - ADMIN_RATE)
    return round_half_up_cents(pool)


def compute_admin_fee(payable):
    if payable <= 0:
        return 0
    fee = round_half_up_cents(Decimal(payable) * ADMIN_WITHHOLD_RATE)
    return min(fee, payable)


def run_allocation(cycle):
    """Run royalty_allocation for the cycle: create DRAFT statements for the new
    epoch and route unclaimed cents to the pool. Assumes pool_amount_cents is set
    and version_epoch already incremented."""
    cycle_id = cycle["id"]
    epoch = cycle["version_epoch"]
    pool_amount = cycle["pool_amount_cents"]

    events = [
        e
        for e in DB["performances"].values()
        if e["cycle_id"] == cycle_id and e["status"] == "ACCEPTED"
    ]
    total_credit_units = Decimal(0)
    for e in events:
        total_credit_units += Decimal(str(e["credit_units"]))

    # group events by work
    by_work = {}
    for e in events:
        by_work.setdefault(e["work_id"], Decimal(0))
        by_work[e["work_id"]] += Decimal(str(e["credit_units"]))

    pool_row = None
    for p in DB["pools"].values():
        if p["cycle_id"] == cycle_id:
            pool_row = p
            break

    # per (affiliate, work) rounded amounts
    # stmt_rows: list of dicts with affiliate_id, rounded gross
    per_affiliate = {}  # affiliate_id -> total rounded gross
    pool_credit = 0

    if total_credit_units > 0:
        unit_value = Decimal(pool_amount) / total_credit_units
        for work_id, work_credits in by_work.items():
            work_value_exact = work_credits * unit_value
            claims = [
                c
                for c in DB["share_claims"].values()
                if c["work_id"] == work_id and c["status"] == "ACCEPTED"
            ]
            if not claims:
                # whole work value routed to pool, no statement
                amt = round_half_up_cents(work_value_exact)
                pool_credit += amt
                continue
            for c in claims:
                affiliate_exact = (
                    work_value_exact * Decimal(c["collection_share_bps"]) / Decimal(10000)
                )
                amt = round_half_up_cents(affiliate_exact)
                per_affiliate[c["affiliate_id"]] = per_affiliate.get(
                    c["affiliate_id"], 0
                ) + amt

    # Build statement records sorted by (rounded amount DESC, affiliate created_at ASC)
    affiliates = DB["affiliates"]
    stmt_specs = []
    for affiliate_id, gross in per_affiliate.items():
        aff = affiliates.get(affiliate_id)
        created = aff["created_at"] if aff else ""
        stmt_specs.append(
            {"affiliate_id": affiliate_id, "gross": gross, "created_at": created}
        )
    stmt_specs.sort(key=lambda s: (-s["gross"], s["created_at"], s["affiliate_id"]))

    # residue reconciliation
    total_rounded = sum(s["gross"] for s in stmt_specs) + pool_credit
    residue = pool_amount - total_rounded
    i = 0
    n = len(stmt_specs)
    while residue > 0 and n > 0:
        stmt_specs[i % n]["gross"] += 1
        residue -= 1
        i += 1
    while residue < 0 and n > 0:
        stmt_specs[i % n]["gross"] -= 1
        residue += 1
        i += 1

    # create statements
    new_statements = []
    for spec in stmt_specs:
        aff = affiliates.get(spec["affiliate_id"])
        gross = spec["gross"]
        unclaimed = 0
        if aff is None or aff.get("status") != "ACTIVE":
            unclaimed = gross
        payable = gross - unclaimed
        admin_fee = compute_admin_fee(payable)
        net = gross - admin_fee
        st = new_resource(
            {
                "cycle_id": cycle_id,
                "affiliate_id": spec["affiliate_id"],
                "epoch": epoch,
                "gross_amount_cents": gross,
                "admin_fee_cents": admin_fee,
                "net_amount_cents": net,
                "unclaimed_amount_cents": unclaimed,
                "status": "DRAFT",
            }
        )
        DB["statements"][st["id"]] = st
        new_statements.append(st)
        if unclaimed > 0:
            pool_credit += unclaimed

    if pool_row is not None and pool_credit:
        pool_row["balance_cents"] = pool_row.get("balance_cents", 0) + pool_credit
        touch(pool_row)

    return new_statements
