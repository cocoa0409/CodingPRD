"""Pinned calculations (PRD 3.6, 3.8, 3.9). Every ordering here is normative."""
from decimal import Decimal
from fractions import Fraction

import db as store
from db import db, touch
from services import cascade, derive, lookup
from services.nums import HUNDRED, ONE, ZERO, rhu, rhu_frac

SAP_BANDS = ("GOOD", "WARN", "PROB", "FAIL")


# --------------------------------------------------- weighted rubric score

def weighted_rubric_score(blueprint, raw_by_code):
    """PRD 3.6: ratios at full precision, accumulate in declared order, then
    multiply by one hundred and round half up to two decimals exactly once."""
    total = Fraction(0)
    for dimension in blueprint["dimensions"]:
        ratio = (Fraction(Decimal(str(raw_by_code[dimension["code"]])))
                 / Fraction(dimension["max_score"]))
        total += ratio * Fraction(Decimal(str(dimension["weight"])))
    return rhu_frac(total * 100, 2)


def critical_fail_flag(blueprint, program, raw_by_code):
    """Decided from the raw ratios, never from the rounded total (PRD 3.6)."""
    floor_ratio = Fraction(Decimal(str(program["critical_dimension_min_ratio"])))
    for dimension in blueprint["dimensions"]:
        if not dimension["critical"]:
            continue
        ratio = (Fraction(Decimal(str(raw_by_code[dimension["code"]])))
                 / Fraction(dimension["max_score"]))
        if ratio < floor_ratio:
            return True
    return False


# ------------------------------------------------------ attempt resolution

def _submitted_scores(attempt_row):
    rows = [s for s in lookup.scores_of(attempt_row["id"])
            if s["status"] == "SUBMITTED"]
    rows.sort(key=lambda s: (s["reader_ordinal"], s["created_at"], s["_seq"]))
    return rows


def _finalize(attempt_row, blueprint, program, counted):
    competency = db.competencies.get(attempt_row["competency_id"])
    threshold = derive.effective_mastery_threshold(competency)
    critical = any(bool(s["critical_fail"]) for s in counted)
    attempt_row["critical_fail"] = critical
    mastered = attempt_row["final_score_pct"] >= threshold
    if blueprint["passing_rule"] == "WEIGHTED_PLUS_ALL_CRITICAL" and critical:
        mastered = False
    now = db.now()
    attempt_row["scored_at_utc"] = now
    if mastered:
        attempt_row["status"] = "SCORED_MASTERED"
        attempt_row["mastered_at_utc"] = now
    else:
        attempt_row["status"] = "SCORED_NOT_MASTERED"
        attempt_row["mastered_at_utc"] = None
    return mastered


def resolve_after_score(attempt_row, blueprint, program):
    """Writes final_score_pct / score_variant / status. Returns True when the
    resolution mastered the competency (the caller then runs the cascade)."""
    submitted = _submitted_scores(attempt_row)
    required = blueprint["required_evaluator_count"]
    if required == 1:
        first = submitted[0]
        attempt_row["final_score_pct"] = first["weighted_score_pct"]
        attempt_row["is_provisional_score"] = False
        attempt_row["score_variant"] = "SINGLE_READER_FINAL"
        return _finalize(attempt_row, blueprint, program, [first])
    if len(submitted) <= 1:
        first = submitted[0]
        attempt_row["final_score_pct"] = first["weighted_score_pct"]
        attempt_row["is_provisional_score"] = True
        attempt_row["score_variant"] = "PROVISIONAL_SINGLE_READER"
        return False
    if len(submitted) == 2:
        one, two = submitted[0], submitted[1]
        gap = abs(one["weighted_score_pct"] - two["weighted_score_pct"])
        if gap <= program["irr_tolerance_pct"]:
            attempt_row["final_score_pct"] = rhu(
                (one["weighted_score_pct"] + two["weighted_score_pct"])
                / Decimal(2), 2)
            attempt_row["is_provisional_score"] = False
            attempt_row["score_variant"] = "TWO_READER_MEAN"
            return _finalize(attempt_row, blueprint, program, [one, two])
        attempt_row["status"] = "ADJUDICATION"
        attempt_row["final_score_pct"] = None
        attempt_row["is_provisional_score"] = False
        attempt_row["score_variant"] = None
        return False
    third = submitted[2]
    attempt_row["final_score_pct"] = third["weighted_score_pct"]
    attempt_row["is_provisional_score"] = False
    attempt_row["score_variant"] = "ADJUDICATED"
    return _finalize(attempt_row, blueprint, program, [third])


# ----------------------------------------------- evaluator standing (IRR)

def check_demotion(evaluator_row, program):
    """Both conditions are required (PRD 3.6); volume is the forgotten one."""
    if evaluator_row is None or program is None:
        return
    if evaluator_row["status"] != "CERTIFIED":
        return
    paired, _agreeing, rate = derive.evaluator_reliability(evaluator_row)
    if paired < program["irr_min_paired_reviews"]:
        return
    if rate >= program["irr_suspend_rate_pct"]:
        return
    evaluator_row["status"] = "PROVISIONAL"
    evaluator_row["demoted_at_utc"] = db.now()
    touch(evaluator_row)


def refresh_pair_standing(attempt_row, program):
    for score_row in lookup.scores_of(attempt_row["id"]):
        if score_row["reader_ordinal"] not in (1, 2):
            continue
        check_demotion(db.evaluators.get(score_row["evaluator_id"]), program)


# ------------------------------------------------------- mentor selection

def eligible_mentors():
    pool = []
    for mentor_row in db.mentors.values():
        if mentor_row["status"] != "ACTIVE":
            continue
        if derive.mentor_caseload(mentor_row) >= mentor_row["max_caseload"]:
            continue
        pool.append(mentor_row)
    return pool


def auto_select_mentor():
    """Ranked by caseload asc, headroom desc, cadence asc, created_at asc."""
    pool = eligible_mentors()
    if not pool:
        return None
    pool.sort(key=lambda m: (derive.mentor_caseload(m),
                             -m["max_caseload"],
                             m["cadence_days"],
                             m["created_at"],
                             m["_seq"]))
    return pool[0]


# --------------------------------------------------- progress checkpoints

def pace_band(pace_pct):
    if pace_pct >= Decimal("100.00"):
        return "GOOD"
    if pace_pct >= Decimal("75.00"):
        return "WARN"
    if pace_pct >= Decimal("50.00"):
        return "PROB"
    return "FAIL"


def next_sap_status(band, previous):
    if band == "GOOD":
        return "GOOD_STANDING"
    if band == "FAIL":
        return "DISMISSED"
    if band == "WARN":
        if previous == "GOOD_STANDING":
            return "WARNING"
        if previous == "WARNING":
            return "PROBATION"
        return "DISMISSED"
    if previous in ("GOOD_STANDING", "WARNING"):
        return "PROBATION"
    return "DISMISSED"


def sap_review_figures(student_row, term_row, program):
    """The five ordered steps of PRD 3.8."""
    counted = 0
    for candidate in lookup.terms_of(student_row["id"]):
        if candidate["status"] not in ("ACTIVE", "COMPLETED", "LAPSED"):
            continue
        if candidate["term_start_utc"] <= term_row["term_start_utc"]:
            counted += 1
    expected = program["sap_min_units_per_term"] * counted
    cumulative = derive.mastered_unit_total(student_row["id"])
    if expected == 0:
        pace = rhu(HUNDRED, 2)
    else:
        pace = rhu((Decimal(cumulative) / Decimal(expected)) * HUNDRED, 2)
    band = pace_band(pace)
    previous = student_row["sap_status"]
    return {
        "terms_counted": counted,
        "expected_units": rhu(Decimal(expected), 2),
        "cumulative_mastered_units": rhu(cumulative, 2),
        "pace_pct": pace,
        "pace_band": band,
        "previous_sap_status": previous,
        "new_sap_status": next_sap_status(band, previous),
    }


# ---------------------------------------------------- transcript snapshot

def transcript_figures(student_row, program):
    per_credit = program["units_per_credit_hour"]
    lines = []
    ordered = sorted(
        derive.mastered_competency_map(student_row["id"]).items(),
        key=lambda pair: (pair[1]["mastered_at_utc"] or pair[1]["created_at"],
                          pair[1]["created_at"], pair[1]["_seq"]),
    )
    total_units = ZERO
    line_sum = ZERO
    for competency_id, attempt_row in ordered:
        competency = db.competencies.get(competency_id)
        if competency is None:
            continue
        unit_value = competency["unit_value"]
        line_hours = rhu(unit_value / per_credit, 2)
        total_units = total_units + unit_value
        line_sum = line_sum + line_hours
        lines.append({
            "competency_code": competency["code"],
            "unit_value": rhu(unit_value, 2),
            "line_credit_hours": line_hours,
            "mastered_at_utc": attempt_row["mastered_at_utc"],
        })
    translated = rhu(total_units / per_credit, 1)
    return {
        "lines": lines,
        "competency_line_count": len(lines),
        "total_mastered_units": rhu(total_units, 2),
        "line_credit_hour_sum": rhu(line_sum, 2),
        "translated_credit_hours": translated,
        "rounding_residual_credit_hours": rhu(line_sum - translated, 2),
    }


# ------------------------------------------------------------- aid return

def return_figures(award, term_row):
    """Steps six and eight of the pinned close-out arithmetic (PRD 3.9)."""
    earned = term_row["earned_pct"]
    disbursed = Decimal(award["disbursed_amount_cents"])
    unearned = int(rhu(disbursed * (ONE - earned), 0))
    net = Decimal(term_row["net_institutional_charge_cents"])
    school_cap = int(rhu(net * (ONE - earned), 0))
    school = unearned if unearned < school_cap else school_cap
    return unearned, school, unearned - school
