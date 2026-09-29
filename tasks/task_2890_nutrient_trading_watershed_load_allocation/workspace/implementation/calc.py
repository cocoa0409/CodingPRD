"""Domain calculations: allocation waterfall, permit limits, compliance
reconciliation, credit serialization, delivery arithmetic, geographic
eligibility and watershed response evaluation."""
from decimal import Decimal

from errors import ApiError
from store import (
    D0,
    ONE4,
    ZERO2,
    dec,
    db,
    day_end,
    day_start,
    iso,
    new_row,
    now,
    now_iso,
    parse_date,
    parse_datetime,
    plus_years,
    public,
    q2,
    q4,
    sorted_rows,
    today,
    touch,
)

LB_PER_DAY_FACTOR = Decimal("5.393")
DAYS_PER_YEAR = Decimal("365")
RESERVE_FRACTION = Decimal("0.0500")
POINT_POOL_SHARE = Decimal("0.6000")
TIER_A_MAX_PCT = Decimal("20.00")
TIER_B_MAX_PCT = Decimal("50.00")
TIER_RELIEF = {"TIER_A": Decimal("0.00"), "TIER_B": Decimal("0.25"), "TIER_C": Decimal("0.50")}
TIER_YEARS = {"TIER_A": 0, "TIER_B": 3, "TIER_C": 5}
MAX_PATH_DEPTH = 10


# --------------------------------------------------------------------------
# lookup helpers
# --------------------------------------------------------------------------
def rows_where(collection, **filters):
    out = []
    for row in collection.values():
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return sorted_rows(out)


def watershed_of_reach(reach):
    return db.watersheds.get(reach["watershed_id"])


def watershed_of_project(project):
    reach = db.reaches.get(project["reach_id"])
    return watershed_of_reach(reach) if reach else None


def assessment_of_source(source):
    return db.tmdl_assessments.get(source["tmdl_assessment_id"])


def set_program_status(watershed, status, touched):
    watershed["program_status"] = status
    watershed["trading_enabled"] = status == "ACTIVE"
    touch(watershed, touched)


# --------------------------------------------------------------------------
# monitoring sample load
# --------------------------------------------------------------------------
def monitoring_sample_load(conc, flow):
    return q2(dec(conc) * dec(flow) * LB_PER_DAY_FACTOR * DAYS_PER_YEAR)


def samples_in_window(watershed_id, reach_class, start_date, end_date):
    lo = day_start(start_date)
    hi = day_end(end_date)
    out = []
    for sample in db.monitoring_samples.values():
        if sample.get("qa_status") != "ACCEPTED":
            continue
        reach = db.reaches.get(sample["reach_id"])
        if reach is None or reach["watershed_id"] != watershed_id:
            continue
        if reach["reach_class"] != reach_class:
            continue
        moment = sample.get("_sample_dt")
        if moment is None or moment < lo or moment > hi:
            continue
        out.append(sample)
    return sorted_rows(out)


# --------------------------------------------------------------------------
# the allocation waterfall
# --------------------------------------------------------------------------
def effective_background(assessment):
    """Step one: the variant-dependent background load."""
    if assessment["status"] == "APPROVED":
        variant = "FINAL"
        start = parse_date(assessment["period_start_date"])
        end = parse_date(assessment["period_end_date"])
        samples = samples_in_window(assessment["watershed_id"], "BACKGROUND", start, end)
        if samples:
            total = sum((dec(s["computed_load_lbs_yr"]) for s in samples), D0)
            return variant, q2(total / Decimal(len(samples)))
        return variant, q2(assessment["background_load_lbs_yr"])
    return "PROVISIONAL", q2(assessment["background_load_lbs_yr"])


def included_sources(assessment_id):
    out = []
    for source in db.source_assessments.values():
        if source["tmdl_assessment_id"] != assessment_id:
            continue
        if source["status"] in ("INVENTORIED", "ADJUSTED"):
            out.append(source)
    return out


def _group_order(rows):
    return sorted(rows, key=lambda r: (-dec(r["existing_load_lbs_yr"]), r["created_at"], r["_seq"]))


def _weight(source, method):
    load = dec(source["existing_load_lbs_yr"])
    if method == "CONTROLLABILITY_WEIGHTED":
        return load * dec(source["controllability_index"])
    return load


def run_allocation(assessment, run_label, method, touched):
    """Executes the allocation run, writing every row it touches."""
    watershed = db.watersheds.get(assessment["watershed_id"])
    variant, background = effective_background(assessment)

    capacity = dec(assessment["loading_capacity_lbs_yr"])
    mos = q2(capacity * dec(assessment["margin_of_safety_pct"]))
    allocable = q2(capacity - mos - background)
    if allocable < ZERO2:
        raise ApiError("ERR_ALLOCABLE_LOAD_NEGATIVE")

    reserve_setaside = q2(allocable * RESERVE_FRACTION)
    distributable = q2(allocable - reserve_setaside)
    point_pool = q2(distributable * POINT_POOL_SHARE)
    nonpoint_pool = q2(distributable - point_pool)

    included = included_sources(assessment["id"])
    point_group = _group_order([s for s in included if s["source_type"] == "POINT"])
    nonpoint_group = _group_order([s for s in included if s["source_type"] == "NONPOINT"])

    run = new_row(
        "AllocationRun",
        tmdl_assessment_id=assessment["id"],
        run_label=run_label,
        method=method,
        variant=variant,
        status="ACTIVE",
        effective_background_lbs_yr=q2(background),
        margin_of_safety_lbs_yr=mos,
        allocable_load_lbs_yr=allocable,
        point_pool_lbs_yr=point_pool,
        nonpoint_pool_lbs_yr=nonpoint_pool,
        reserve_allocation_lbs_yr=ZERO2,
        wla_total_lbs_yr=ZERO2,
        la_total_lbs_yr=ZERO2,
        included_source_count=len(included),
        allocations=[],
        rescinded_at=None,
    )

    allocations = []
    totals = {}
    for group, pool, key in (
        (point_group, point_pool, "point"),
        (nonpoint_group, nonpoint_pool, "nonpoint"),
    ):
        denominator = sum((_weight(s, method) for s in group), D0)
        group_total = ZERO2
        for source in group:
            weight = _weight(source, method)
            if denominator > 0:
                allocated = q2(pool * weight / denominator)
            else:
                allocated = ZERO2
            group_total = group_total + allocated
            source["allocated_load_lbs_yr"] = allocated
            source["allocation_run_id"] = run["id"]
            touch(source, touched)
            allocations.append(
                {
                    "source_assessment_id": source["id"],
                    "source_type": source["source_type"],
                    "existing_load_lbs_yr": dec(source["existing_load_lbs_yr"]),
                    "weight": q4(weight),
                    "allocated_load_lbs_yr": allocated,
                }
            )
        totals[key] = q2(group_total)

    run["allocations"] = allocations
    run["wla_total_lbs_yr"] = totals["point"]
    run["la_total_lbs_yr"] = totals["nonpoint"]
    run["reserve_allocation_lbs_yr"] = q2(allocable - totals["point"] - totals["nonpoint"])

    # --- step seven: supersede the prior ACTIVE run and re-base the program
    for prior in rows_where(db.allocation_runs, tmdl_assessment_id=assessment["id"], status="ACTIVE"):
        prior["status"] = "SUPERSEDED"
        touch(prior, touched)
        if watershed is not None:
            watershed["reserve_pool_lbs"] = q2(
                dec(watershed["reserve_pool_lbs"]) - dec(prior["reserve_allocation_lbs_yr"])
            )

    db.allocation_runs[run["id"]] = run

    if watershed is not None:
        watershed["reserve_pool_lbs"] = q2(
            dec(watershed["reserve_pool_lbs"]) + run["reserve_allocation_lbs_yr"]
        )
        watershed["allocated_wla_total_lbs_yr"] = run["wla_total_lbs_yr"]
        watershed["allocated_la_total_lbs_yr"] = run["la_total_lbs_yr"]
        touch(watershed, touched)

    copy_run_totals(assessment, run)
    touch(assessment, touched)
    return run


def copy_run_totals(assessment, run):
    assessment["margin_of_safety_lbs_yr"] = run["margin_of_safety_lbs_yr"]
    assessment["allocable_load_lbs_yr"] = run["allocable_load_lbs_yr"]
    assessment["wla_total_lbs_yr"] = run["wla_total_lbs_yr"]
    assessment["la_total_lbs_yr"] = run["la_total_lbs_yr"]
    assessment["reserve_allocation_lbs_yr"] = run["reserve_allocation_lbs_yr"]
    assessment["effective_background_lbs_yr"] = run["effective_background_lbs_yr"]
    assessment["allocation_variant"] = run["variant"]


def rescind_run(run, touched):
    assessment = db.tmdl_assessments.get(run["tmdl_assessment_id"])
    watershed = db.watersheds.get(assessment["watershed_id"]) if assessment else None

    run["status"] = "RESCINDED"
    run["rescinded_at"] = now_iso()
    touch(run, touched)

    for source in rows_where(db.source_assessments, allocation_run_id=run["id"]):
        source["allocated_load_lbs_yr"] = None
        source["allocation_run_id"] = None
        touch(source, touched)

    if assessment is not None:
        remaining = [
            r
            for r in rows_where(db.allocation_runs, tmdl_assessment_id=assessment["id"], status="ACTIVE")
            if r["id"] != run["id"]
        ]
        if not remaining:
            assessment["margin_of_safety_lbs_yr"] = ZERO2
            assessment["allocable_load_lbs_yr"] = ZERO2
            assessment["wla_total_lbs_yr"] = ZERO2
            assessment["la_total_lbs_yr"] = ZERO2
            assessment["reserve_allocation_lbs_yr"] = ZERO2
            assessment["effective_background_lbs_yr"] = None
            assessment["allocation_variant"] = None
            touch(assessment, touched)

    if watershed is not None:
        watershed["reserve_pool_lbs"] = q2(
            dec(watershed["reserve_pool_lbs"]) - dec(run["reserve_allocation_lbs_yr"])
        )
        watershed["allocated_wla_total_lbs_yr"] = ZERO2
        watershed["allocated_la_total_lbs_yr"] = ZERO2
        touch(watershed, touched)


# --------------------------------------------------------------------------
# permit limit derivation (five pinned steps)
# --------------------------------------------------------------------------
def derive_limits(permit, source, watershed, touched):
    wla = dec(source["allocated_load_lbs_yr"])
    final_limit = q2(wla * dec(watershed["equivalence_ratio"]))

    current = dec(permit["current_annual_load_lbs"])
    if current <= 0:
        required_pct = ZERO2
    else:
        quotient = (current - final_limit) / current
        if quotient < 0:
            quotient = D0
        required_pct = q2(quotient * Decimal("100"))

    if required_pct <= TIER_A_MAX_PCT:
        tier = "TIER_A"
    elif required_pct <= TIER_B_MAX_PCT:
        tier = "TIER_B"
    else:
        tier = "TIER_C"

    relief = TIER_RELIEF[tier]
    years = TIER_YEARS[tier]
    interim_limit = q2(final_limit + relief * (current - final_limit))
    effective = parse_date(permit["effective_date"])
    schedule_end = plus_years(effective, years)

    permit["wla_lbs_yr"] = q2(wla)
    permit["final_limit_lbs_yr"] = final_limit
    permit["required_reduction_pct"] = required_pct
    permit["schedule_tier"] = tier
    permit["interim_limit_lbs_yr"] = interim_limit
    permit["compliance_schedule_end_date"] = schedule_end.isoformat()
    permit["limit_status"] = "INTERIM"
    refresh_applicable_limit(permit)
    touch(permit, touched)
    return permit


def refresh_applicable_limit(permit):
    """Pure re-derivation of applicable_limit_lbs_yr; never bumps version."""
    status = permit["limit_status"]
    if status == "DRAFT_LIMITS":
        permit["applicable_limit_lbs_yr"] = None
        return None
    if status == "FINAL":
        permit["applicable_limit_lbs_yr"] = permit["final_limit_lbs_yr"]
        return permit["applicable_limit_lbs_yr"]
    end = parse_date(permit.get("compliance_schedule_end_date") or "")
    if end is not None and today() > end:
        permit["applicable_limit_lbs_yr"] = permit["final_limit_lbs_yr"]
    else:
        permit["applicable_limit_lbs_yr"] = permit["interim_limit_lbs_yr"]
    return permit["applicable_limit_lbs_yr"]


def schedule_expired(permit):
    end = parse_date(permit.get("compliance_schedule_end_date") or "")
    if end is None:
        return False
    return today() > end


# --------------------------------------------------------------------------
# compliance reconciliation
# --------------------------------------------------------------------------
def credit_applied_total(permit_id):
    total = D0
    for txn in db.credit_transactions.values():
        if txn["permit_id"] != permit_id or txn["status"] != "APPROVED":
            continue
        if txn.get("applied_lbs") is None:
            continue
        total = total + dec(txn["applied_lbs"])
    return q2(total)


def permit_need(permit):
    """Outstanding need: reported - applicable - credits, floored at zero."""
    refresh_applicable_limit(permit)
    reported = permit.get("reported_annual_load_lbs")
    if reported is None:
        return ZERO2
    applicable = permit.get("applicable_limit_lbs_yr")
    applicable = D0 if applicable is None else dec(applicable)
    gap = dec(reported) - applicable - dec(permit["credit_applied_lbs"])
    if gap < 0:
        gap = D0
    return q2(gap)


def reconcile(permit, trigger, touched=None):
    """Recompute compliance_gap_lbs and move compliance_status.

    trigger is one of: report, finalize, credit_approve, void_release,
    void_invalidated.
    """
    permit["credit_applied_lbs"] = credit_applied_total(permit["id"])
    refresh_applicable_limit(permit)
    previous = permit["compliance_status"]
    reported = permit.get("reported_annual_load_lbs")

    if reported is None:
        permit["compliance_gap_lbs"] = ZERO2
        permit["compliance_status"] = "NOT_REPORTED"
        if touched is not None:
            touch(permit, touched)
        return permit

    gap = permit_need(permit)
    permit["compliance_gap_lbs"] = gap

    if gap == ZERO2:
        if trigger == "report":
            permit["compliance_status"] = "IN_COMPLIANCE"
        elif trigger == "credit_approve":
            permit["compliance_status"] = "RESOLVED"
        elif trigger == "void_invalidated":
            if previous == "SHORTFALL":
                permit["compliance_status"] = "VIOLATION"
    else:
        if trigger == "void_invalidated":
            permit["compliance_status"] = "VIOLATION"
        elif trigger == "report":
            if schedule_expired(permit):
                permit["compliance_status"] = "VIOLATION"
            else:
                permit["compliance_status"] = "SHORTFALL"
        elif trigger == "credit_approve":
            permit["compliance_status"] = "SHORTFALL"
        else:  # void_release / finalize
            if previous in ("RESOLVED", "IN_COMPLIANCE", "SHORTFALL"):
                permit["compliance_status"] = "SHORTFALL"

    if permit["compliance_status"] == "VIOLATION":
        permit["enforcement_flag"] = True
    if touched is not None:
        touch(permit, touched)
    return permit


# --------------------------------------------------------------------------
# geographic eligibility path
# --------------------------------------------------------------------------
def delivery_path(generating_reach, buyer_reach):
    """Walk downstream from the generating reach to the buyer reach.

    Returns (delivery_ratio, path_reach_count).  Raises ERR_ZONE_NOT_ELIGIBLE
    when the buyer is not reachable within the depth limit.
    """
    if generating_reach["id"] == buyer_reach["id"]:
        return ONE4, 1
    path = [generating_reach]
    product = Decimal("1")
    current = generating_reach
    while True:
        nxt_id = current.get("downstream_reach_id")
        if nxt_id is None:
            raise ApiError("ERR_ZONE_NOT_ELIGIBLE")
        nxt = db.reaches.get(nxt_id)
        if nxt is None:
            raise ApiError("ERR_ZONE_NOT_ELIGIBLE")
        path.append(nxt)
        product = product * dec(nxt["delivery_factor"])
        if nxt["id"] == buyer_reach["id"]:
            return q4(product), len(path)
        if len(path) > MAX_PATH_DEPTH:
            raise ApiError("ERR_ZONE_NOT_ELIGIBLE")
        current = nxt


# --------------------------------------------------------------------------
# credit delivery arithmetic
# --------------------------------------------------------------------------
def delivery_amounts(gross, watershed, delivery_ratio):
    """Returns (retired_to_reserve_lbs, tradable_lbs, delivered_lbs)."""
    gross = dec(gross)
    retired_to_reserve = q2(gross * dec(watershed["retirement_ratio"]))
    tradable = q2(gross - retired_to_reserve)
    delivered = q2(
        tradable
        * dec(delivery_ratio)
        * dec(watershed["equivalence_ratio"])
        / dec(watershed["uncertainty_ratio"])
    )
    return retired_to_reserve, tradable, delivered


# --------------------------------------------------------------------------
# credit batch serialization
# --------------------------------------------------------------------------
def mint_batch(project, watershed, touched):
    pre = dec(project["pre_load_lbs_yr"])
    post = dec(project["post_load_lbs_yr"])
    verified = dec(project["verified_acres"])
    enrolled = dec(project["enrolled_acres"])
    gross = q2((pre - post) * verified / enrolled)
    issued = int(gross.to_integral_value(rounding="ROUND_FLOOR"))
    residual = q2(gross - Decimal(issued))

    counter = int(watershed["serial_counter"])
    serial_start = counter + 1
    serial_end = counter + issued

    batch = new_row(
        "CreditBatch",
        practice_project_id=project["id"],
        vintage_year=project["vintage_year"],
        status="ISSUED",
        gross_reduction_lbs_yr=gross,
        issued_lbs=issued,
        residual_lbs=residual,
        serial_prefix="%s-%s-%s" % (watershed["state_code"], watershed["watershed_code"], project["vintage_year"]),
        serial_start=serial_start,
        serial_end=serial_end,
        verified_ratio=ONE4,
        available_lbs=q2(issued),
        reserved_lbs=ZERO2,
        retired_lbs=ZERO2,
        invalidated_lbs=ZERO2,
    )
    db.credit_batches[batch["id"]] = batch

    watershed["serial_counter"] = serial_end
    watershed["reserve_pool_lbs"] = q2(dec(watershed["reserve_pool_lbs"]) + residual)
    touch(watershed, touched)
    return batch


def batches_of_project(project_id, statuses=None):
    rows = [b for b in db.credit_batches.values() if b["practice_project_id"] == project_id]
    if statuses is not None:
        rows = [b for b in rows if b["status"] in statuses]
    return sorted_rows(rows)


# --------------------------------------------------------------------------
# watershed response evaluation (adaptive review)
# --------------------------------------------------------------------------
def approved_assessment(watershed_id):
    for assessment in sorted_rows(list(db.tmdl_assessments.values())):
        if assessment["watershed_id"] == watershed_id and assessment["status"] == "APPROVED":
            return assessment
    return None


def evaluate_response(review, watershed):
    """Returns (sample_count, observed_load, achieved_pct, verdict)."""
    start = parse_date(review["period_start_date"])
    end = parse_date(review["period_end_date"])
    samples = samples_in_window(watershed["id"], "COMPLIANCE_POINT", start, end)
    count = len(samples)
    if count == 0:
        return 0, None, None, "INDETERMINATE"
    total = sum((dec(s["computed_load_lbs_yr"]) for s in samples), D0)
    observed = q2(total / Decimal(count))

    baseline = dec(watershed["baseline_load_lbs_yr"])
    assessment = approved_assessment(watershed["id"])
    capacity = dec(assessment["loading_capacity_lbs_yr"]) if assessment else D0
    denominator = baseline - capacity
    if denominator == 0:
        return count, observed, None, "INDETERMINATE"
    achieved = q2((baseline - observed) / denominator * Decimal("100"))
    verdict = "ON_TRACK" if achieved >= dec(watershed["interim_target_pct"]) else "OFF_TRACK"
    return count, observed, achieved, verdict
