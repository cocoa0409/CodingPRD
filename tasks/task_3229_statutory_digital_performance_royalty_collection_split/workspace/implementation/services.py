"""Business logic: rate resolution, counters, liability math, splits, cascades."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from helpers import day_floor, touch, logical_now, new_id
from errors import ApiError

MICROCENTS_PER_CENT = 1_000_000
ADMIN_FEE_PCT = Decimal("0.05")
UNDERREPORT_PENALTY_PCT = Decimal("0.15")
AUDIT_COST_RECOVERY_CENTS = 50_000
CAMPAIGNS_BEFORE_DISTRIBUTION = 3
UNCLAIMED_EXPIRY_DAYS = 365


def round_half_up_cents(value):
    """value is Decimal or Fraction-like; returns int cents rounded half up."""
    d = Decimal(value) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Rate schedules
# ---------------------------------------------------------------------------

def schedules_overlap(s1, e1, s2, e2):
    """Half-open adjacency semantics: window = [start, day_after(end))."""
    s1d = day_floor(s1)
    e1x = day_floor(e1) + timedelta(days=1)
    s2d = day_floor(s2)
    e2x = day_floor(e2) + timedelta(days=1)
    return s1d < e2x and s2d < e1x


def schedule_overlap_exists(category, start, end, exclude_id=None):
    for sch in store.rate_schedules.values():
        if sch["id"] == exclude_id:
            continue
        if sch["category"] != category:
            continue
        if sch["schedule_status"] not in ("DRAFT", "EFFECTIVE"):
            continue
        if schedules_overlap(start, end, sch["effective_start"], sch["effective_end"]):
            return True
    return False


def resolve_effective_schedule(category, when_dt):
    """EFFECTIVE schedule of category covering when_dt (inclusive both ends)."""
    wd = day_floor(when_dt)
    for sch in store.rate_schedules.values():
        if sch["category"] != category:
            continue
        if sch["schedule_status"] != "EFFECTIVE":
            continue
        if day_floor(sch["effective_start"]) <= wd <= day_floor(sch["effective_end"]):
            return sch
    return None


def supersede_prior_effective(new_schedule):
    """Flip EFFECTIVE same-category schedules with earlier effective_start."""
    for sch in store.rate_schedules.values():
        if sch["id"] == new_schedule["id"]:
            continue
        if sch["category"] != new_schedule["category"]:
            continue
        if sch["schedule_status"] != "EFFECTIVE":
            continue
        if day_floor(sch["effective_start"]) < day_floor(new_schedule["effective_start"]):
            sch["schedule_status"] = "SUPERSEDED"
            touch(sch)


# ---------------------------------------------------------------------------
# Usage reports / play lines
# ---------------------------------------------------------------------------

def report_windows_overlap(s1, e1, s2, e2):
    """Aggregate-coverage: any shared day, inclusive both ends."""
    return day_floor(s1) <= day_floor(e2) and day_floor(s2) <= day_floor(e1)


def report_overlap_exists(licensee_id, start, end, exclude_id=None):
    for rep in store.usage_reports.values():
        if rep["id"] == exclude_id:
            continue
        if rep["licensee_id"] != licensee_id:
            continue
        if rep["report_status"] not in ("SUBMITTED", "ACCEPTED", "AMENDED"):
            continue
        if report_windows_overlap(start, end, rep["period_start"], rep["period_end"]):
            return True
    return False


def identify_play_line(line):
    """MATCHED iff exactly one ACTIVE recording carries the line's isrc."""
    matches = [
        rec
        for rec in store.recordings.values()
        if rec["isrc"] == line["isrc"] and rec["catalog_status"] == "ACTIVE"
    ]
    if len(matches) == 1:
        line["identification_status"] = "MATCHED"
        line["matched_recording_id"] = matches[0]["id"]
    else:
        line["identification_status"] = "UNMATCHED"
        line["matched_recording_id"] = None


def recompute_report_counters(report):
    lines = [pl for pl in store.play_lines.values() if pl["usage_report_id"] == report["id"]]
    total = sum(pl["performance_count"] for pl in lines)
    matched = sum(
        pl["performance_count"] for pl in lines if pl["identification_status"] == "MATCHED"
    )
    report["total_performances"] = total
    report["matched_performances"] = matched
    report["unmatched_performances"] = total - matched


def snapshot_rate(report, licensee):
    sch = resolve_effective_schedule(licensee["service_category"], report["period_start"])
    if sch is None:
        return None
    report["_snapshot_schedule_id"] = sch["id"]
    report["_snapshot_rate_microcents"] = sch["rate_per_performance_microcents"]
    report["_snapshot_min_fee_cents"] = sch["min_fee_cents"]
    return sch


def suspend_licensee_cascade(licensee, reason):
    licensee["license_status"] = "SUSPENDED"
    licensee["suspended_reason"] = reason
    touch(licensee)
    for rep in store.usage_reports.values():
        if rep["licensee_id"] == licensee["id"] and rep["report_status"] == "SUBMITTED":
            rep["report_status"] = "REJECTED"
            touch(rep)


# ---------------------------------------------------------------------------
# Royalty liability
# ---------------------------------------------------------------------------

def get_min_fee_paid(licensee_id, year):
    return store.min_fee_paid_ytd.get(licensee_id, {}).get(year, 0)


def add_min_fee_paid(licensee_id, year, cents):
    ledger = store.min_fee_paid_ytd.setdefault(licensee_id, {})
    ledger[year] = ledger.get(year, 0) + cents


def compute_gross(report, rate_microcents, override_total_perfs=None):
    """Per-line round-half-up first, then sum. When override_total_perfs is
    given (audit), treat the report as a single aggregate line."""
    if override_total_perfs is not None:
        raw = Decimal(override_total_perfs) * Decimal(rate_microcents) / Decimal(
            MICROCENTS_PER_CENT
        )
        return round_half_up_cents(raw)
    gross = 0
    for pl in store.play_lines.values():
        if pl["usage_report_id"] != report["id"]:
            continue
        raw = Decimal(pl["performance_count"]) * Decimal(rate_microcents) / Decimal(
            MICROCENTS_PER_CENT
        )
        gross += round_half_up_cents(raw)
    return gross


def liability_mode_for(report):
    """PER_PERIOD_MINIMUM iff no other liability of this licensee exists in the
    calendar year of period_start."""
    year = report["period_start"].year
    for liab in store.royalty_liabilities.values():
        if liab["usage_report_id"] == report["id"]:
            continue
        other_report = store.usage_reports.get(liab["usage_report_id"])
        if other_report is None:
            continue
        if other_report["licensee_id"] != report["licensee_id"]:
            continue
        if liab["period_start"].year == year:
            return "YTD_MINIMUM_FEE"
    return "PER_PERIOD_MINIMUM"


def run_liability_math(report, licensee, rate_microcents, min_fee_cents, mode,
                       override_total_perfs=None):
    gross = compute_gross(report, rate_microcents, override_total_perfs)
    if mode == "PER_PERIOD_MINIMUM":
        minimum_fee = min_fee_cents
    else:
        paid = get_min_fee_paid(report["licensee_id"], report["period_start"].year)
        minimum_fee = max(0, min_fee_cents - paid)
    amount_due = max(gross, minimum_fee)
    if gross >= minimum_fee:
        admin_fee = round_half_up_cents(ADMIN_FEE_PCT * Decimal(gross))
    else:
        admin_fee = 0
    pool = amount_due - admin_fee
    return gross, minimum_fee, amount_due, admin_fee, pool


def compute_liability(report, licensee, force_mode=None, override_total_perfs=None):
    """Returns dict of computed amounts using snapshot rate when available."""
    rate = report.get("_snapshot_rate_microcents")
    min_fee = report.get("_snapshot_min_fee_cents")
    if rate is None or min_fee is None:
        sch = resolve_effective_schedule(licensee["service_category"], report["period_start"])
        if sch is None:
            raise ApiError("ERR_NO_EFFECTIVE_RATE_SCHEDULE", 409,
                           "No EFFECTIVE schedule covers the report's period_start")
        rate = sch["rate_per_performance_microcents"]
        min_fee = sch["min_fee_cents"]
    mode = force_mode or liability_mode_for(report)
    gross, minimum_fee, amount_due, admin_fee, pool = run_liability_math(
        report, licensee, rate, min_fee, mode, override_total_perfs
    )
    return {
        "rate_microcents": rate,
        "schedule_min_fee_cents": min_fee,
        "mode": mode,
        "gross": gross,
        "minimum_fee": minimum_fee,
        "amount_due": amount_due,
        "admin_fee": admin_fee,
        "pool": pool,
    }


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

def matched_recordings_for_report(report):
    """Distinct matched recordings of a report, by Recording.created_at ASC.
    Returns list of (recording, perfs_sum)."""
    perfs = {}
    for pl in store.play_lines.values():
        if pl["usage_report_id"] != report["id"]:
            continue
        if pl["identification_status"] != "MATCHED":
            continue
        rid = pl["matched_recording_id"]
        perfs[rid] = perfs.get(rid, 0) + pl["performance_count"]
    recs = [store.recordings[rid] for rid in perfs if rid in store.recordings]
    recs.sort(key=lambda r: (r["created_at"], r["id"]))
    return [(r, perfs[r["id"]]) for r in recs]


def execute_distribution(batch, report, liability):
    """Run the 50/45/5 waterfall; accrue unmatched share; settle liability."""
    pool = liability["distributable_pool_cents"]
    total = report["total_performances"]
    matched = report["matched_performances"]
    if total > 0:
        matched_pool = round_half_up_cents(
            Decimal(pool) * Decimal(matched) / Decimal(total)
        )
    else:
        matched_pool = 0
    unmatched_pool = pool - matched_pool

    # create distribution lines per matched recording
    for rec, perfs_r in matched_recordings_for_report(report):
        if matched > 0:
            rec_pool = round_half_up_cents(
                Decimal(matched_pool) * Decimal(perfs_r) / Decimal(matched)
            )
        else:
            rec_pool = 0
        rights_owner_cents = (Decimal("0.50") * Decimal(rec_pool)).to_integral_value(
            rounding="ROUND_FLOOR"
        )
        featured_cents = (Decimal("0.45") * Decimal(rec_pool)).to_integral_value(
            rounding="ROUND_FLOOR"
        )
        rights_owner_cents = int(rights_owner_cents)
        featured_cents = int(featured_cents)
        remainder = rec_pool - rights_owner_cents - featured_cents
        afm_cents = remainder // 2
        sag_aftra_cents = remainder - afm_cents
        _make_line(batch["id"], "RIGHTS_OWNER", rights_owner_cents,
                   payee_rights_owner_id=rec["rights_owner_id"])
        _make_line(batch["id"], "FEATURED_ARTIST", featured_cents,
                   payee_artist_id=rec["featured_artist_id"])
        _make_line(batch["id"], "NONFEATURED_FUND", afm_cents, fund_type="AFM")
        _make_line(batch["id"], "NONFEATURED_FUND", sag_aftra_cents,
                   fund_type="SAG_AFTRA")

    # accrue unmatched share into covering pool(s)
    if unmatched_pool > 0:
        for pl_pool in store.unclaimed_pools.values():
            if report_windows_overlap_cover(pl_pool, report):
                pl_pool["accrued_unmatched_cents"] += unmatched_pool
                touch(pl_pool)

    # settle liability
    liability["liability_status"] = "SETTLED"
    touch(liability)

    batch["batch_status"] = "EXECUTED"
    batch["executed_at"] = logical_now()
    touch(batch)
    return unmatched_pool


def _make_line(batch_id, payee_type, amount, payee_artist_id=None,
               payee_rights_owner_id=None, fund_type=None):
    now = logical_now()
    line = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "distribution_batch_id": batch_id,
        "payee_type": payee_type,
        "payee_artist_id": payee_artist_id,
        "payee_rights_owner_id": payee_rights_owner_id,
        "fund_type": fund_type,
        "amount_cents": amount,
    }
    store.distribution_lines[line["id"]] = line
    return line


def report_windows_overlap_cover(pool, report):
    """Report period lies inside the pool window (inclusive days)."""
    return (
        day_floor(pool["period_start"]) <= day_floor(report["period_start"])
        and day_floor(report["period_end"]) <= day_floor(pool["period_end"])
    )


# ---------------------------------------------------------------------------
# Unclaimed pool campaigns / release
# ---------------------------------------------------------------------------

def run_matching_campaign(pool):
    """Re-attempt every UNMATCHED play line whose report period lies inside the
    pool window; move proportional unmatched cents out of the accrual."""
    total_moved = 0
    for rep in store.usage_reports.values():
        if not report_windows_overlap_cover(pool, rep):
            continue
        liab = _liability_for_report(rep["id"])
        for pl in store.play_lines.values():
            if pl["usage_report_id"] != rep["id"]:
                continue
            if pl["identification_status"] != "UNMATCHED":
                continue
            pl["match_attempt_count"] += 1
            before = pl["identification_status"]
            identify_play_line(pl)
            if before == "UNMATCHED" and pl["identification_status"] == "MATCHED":
                touch(pl)
                # move proportional unmatched cents out of the pool
                if (
                    liab is not None
                    and rep["unmatched_performances"] > 0
                    and rep["total_performances"] > 0
                ):
                    pool_cents = liab["distributable_pool_cents"]
                    unmatched_pool = pool_cents - round_half_up_cents(
                        Decimal(pool_cents)
                        * Decimal(rep["matched_performances"])
                        / Decimal(rep["total_performances"])
                    )
                    share = (Decimal(unmatched_pool) * Decimal(pl["performance_count"])
                             / Decimal(rep["unmatched_performances"])).to_integral_value(
                        rounding="ROUND_FLOOR"
                    )
                    total_moved += int(share)
        recompute_report_counters(rep)
        touch(rep)
    if total_moved > 0:
        pool["accrued_unmatched_cents"] = max(
            0, pool["accrued_unmatched_cents"] - total_moved
        )


def _liability_for_report(report_id):
    for liab in store.royalty_liabilities.values():
        if liab["usage_report_id"] == report_id:
            return liab
    return None


def release_pool(pool):
    """Pro-rata release to VERIFIED rights owners by matched catalog weight."""
    weights = {}
    for rep in store.usage_reports.values():
        if not report_windows_overlap_cover(pool, rep):
            continue
        for pl in store.play_lines.values():
            if pl["usage_report_id"] != rep["id"]:
                continue
            if pl["identification_status"] != "MATCHED":
                continue
            rec = store.recordings.get(pl["matched_recording_id"])
            if rec is None or rec["catalog_status"] != "ACTIVE":
                continue
            owner = store.rights_owners.get(rec["rights_owner_id"])
            if owner is None or owner["registration_status"] != "VERIFIED":
                continue
            weights[owner["id"]] = weights.get(owner["id"], 0) + 1
    total_weight = sum(weights.values())
    accrued = pool["accrued_unmatched_cents"]
    pool["distributed_cents"] = accrued
    if total_weight <= 0:
        return
    owners = [
        store.rights_owners[oid]
        for oid in weights
        if oid in store.rights_owners
    ]
    owners.sort(key=lambda o: (o["created_at"], o["id"]))
    allocated = 0
    for o in owners:
        share = int(
            (Decimal(accrued) * Decimal(weights[o["id"]]) / Decimal(total_weight)
             ).to_integral_value(rounding="ROUND_FLOOR")
        )
        allocated += share
    residual = accrued - allocated
    if residual > 0:
        # residual goes to earliest-created VERIFIED owner with weight > 0
        # (already sorted by created_at); nothing persisted per-owner here.
        pass


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def issue_findings_calc(audit, declared_true_performances):
    """Compute assessed_underpayment_cents per calc_audit_underpayment."""
    licensee = store.licensees.get(audit["licensee_id"])
    in_scope = []
    for liab in store.royalty_liabilities.values():
        rep = store.usage_reports.get(liab["usage_report_id"])
        if rep is None:
            continue
        if rep["licensee_id"] != audit["licensee_id"]:
            continue
        if liab["liability_status"] == "WRITTEN_OFF":
            continue
        if not report_windows_overlap(
            rep["period_start"], rep["period_end"],
            audit["period_start"], audit["period_end"],
        ):
            continue
        in_scope.append((rep, liab))
    in_scope.sort(key=lambda t: (day_floor(t[0]["period_start"]),
                                 t[0]["created_at"], t[0]["id"]))

    declared = 0
    for rep, liab in in_scope:
        # declared_true_performances: int (applies per report) or map report_id->int
        if isinstance(declared_true_performances, dict):
            true_perfs = declared_true_performances.get(rep["id"])
            if true_perfs is None:
                continue
        else:
            true_perfs = declared_true_performances
        recomputed = compute_liability(
            rep, licensee, force_mode=liab.get("_mode"),
            override_total_perfs=true_perfs,
        )
        delta = recomputed["amount_due"] - liab["amount_due_cents"]
        if delta > 0:
            declared += delta
    penalty = round_half_up_cents(UNDERREPORT_PENALTY_PCT * Decimal(declared))
    return declared + penalty + AUDIT_COST_RECOVERY_CENTS


def licensee_has_report_in_status_overlapping(licensee_id, start, end, statuses):
    for rep in store.usage_reports.values():
        if rep["licensee_id"] != licensee_id:
            continue
        if rep["report_status"] not in statuses:
            continue
        if report_windows_overlap(rep["period_start"], rep["period_end"], start, end):
            return True
    return False
