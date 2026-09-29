"""Every calculation rule in PRD section 3, in the order the PRD states them."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

import constants as C
from store import (
    add_days,
    db,
    dec,
    elapsed_whole_days,
    elapsed_whole_weeks,
    sort_rows,
)


# ------------------------------------------------------------------ rounding

def round_half_up(value, places):
    """PRD 2.7: rounded half up -- a value ending in exactly half rounds up."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Whole cents, half up (PRD 2.7)."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------- visit slot and capacity

def visit_end_datetime(visit_datetime, visit_type):
    """PRD 3.2: the slot length is a property of the visit type."""
    from datetime import timedelta

    return visit_datetime + timedelta(minutes=C.VISIT_DURATION_MINUTES[visit_type])


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def clinician_overlapping_visit_count(clinician_id, start, end):
    """PRD 3.2: every persisted visit of that clinician counts, no buffer."""
    count = 0
    for visit in db.visits.values():
        if visit["clinician_id"] != clinician_id:
            continue
        if _overlaps(start, end, visit["visit_datetime"], visit["visit_end_datetime"]):
            count += 1
    return count


# ------------------------------------------------------- disease activity

def cdai_score(tender, swollen, patient_global, physician_global):
    """PRD 3.2: the plain sum of four components, rounded once to 2 places."""
    raw = dec(tender) + dec(swollen) + dec(patient_global) + dec(physician_global)
    return round_half_up(raw, 2)


def das28_crp_score(tender, swollen, crp_mg_dl, patient_global):
    """PRD 3.2: five terms at full precision, rounded once at the end."""
    with localcontext() as ctx:
        ctx.prec = 50
        raw = (
            C.DAS28_TJC_COEFFICIENT * dec(tender).sqrt()
            + C.DAS28_SJC_COEFFICIENT * dec(swollen).sqrt()
            + C.DAS28_CRP_COEFFICIENT * (dec(crp_mg_dl) * Decimal(10) + Decimal(1)).ln()
            + C.DAS28_PGA_COEFFICIENT * (dec(patient_global) * Decimal(10))
            + C.DAS28_INTERCEPT
        )
    return round_half_up(raw, 2)


def cdai_category(score):
    """PRD 3.2: REMISSION bound INCLUSIVE at 2.80."""
    if score <= C.CDAI_REMISSION_MAX:
        return "REMISSION"
    if score <= C.CDAI_LOW_MAX:
        return "LOW"
    if score <= C.CDAI_MODERATE_MAX:
        return "MODERATE"
    return "HIGH"


def das28_category(score):
    """PRD 3.2: REMISSION bound STRICTLY less than 2.60."""
    if score < C.DAS28_REMISSION_MAX_EXCLUSIVE:
        return "REMISSION"
    if score <= C.DAS28_LOW_MAX:
        return "LOW"
    if score <= C.DAS28_MODERATE_MAX:
        return "MODERATE"
    return "HIGH"


def escalation_recommendation(patient_id, activity_category, visit_datetime):
    """PRD 3.2 treat-to-target advice."""
    if activity_category == "HIGH":
        return "ESCALATE"
    if activity_category == "MODERATE":
        for episode in db.episodes.values():
            if episode["patient_id"] != patient_id:
                continue
            if episode["therapy_state"] != "ACTIVE":
                continue
            # The dwell comparison is inclusive: exactly 90 days qualifies.
            elapsed = elapsed_whole_days(visit_datetime, episode["therapy_start_at"])
            if elapsed >= C.ESCALATION_DWELL_DAYS:
                return "ESCALATE"
        return "OPTIMIZE_CURRENT"
    return "CONTINUE"


def project_patient_activity(patient):
    """PRD 3.2: copy the newest SCORED visit's figures verbatim onto the patient."""
    scored = [
        v
        for v in db.visits.values()
        if v["patient_id"] == patient["id"] and v["status"] == "SCORED"
    ]
    if not scored:
        patient["latest_activity_score"] = None
        patient["latest_activity_category"] = None
        patient["target_status"] = "UNASSESSED"
        return
    winner = max(scored, key=lambda v: (v["visit_datetime"], v["created_at"], v["_seq"]))
    patient["latest_activity_score"] = winner["activity_score"]
    patient["latest_activity_category"] = winner["activity_category"]
    if winner["activity_category"] in C.AT_TARGET_CATEGORIES:
        patient["target_status"] = "AT_TARGET"
    else:
        patient["target_status"] = "NOT_AT_TARGET"


# ----------------------------------------------------- screening postures

def _patient_screens(patient_id):
    return [r for r in db.screening_records.values() if r["patient_id"] == patient_id]


def _is_current(record, clock):
    """PRD 3.3: current when elapsed whole days from resulted_at is at most 365."""
    return elapsed_whole_days(clock, record["resulted_at"]) <= C.SCREEN_VALIDITY_DAYS


def tb_screen_status(patient_id):
    """PRD 3.3: six cases walked in order, first match wins."""
    clock = db.now()
    records = _patient_screens(patient_id)
    tb_records = [r for r in records if r["screen_type"] in C.TB_TEST_TYPES]
    treatment_records = [
        r
        for r in records
        if r["screen_type"] == "TB_LTBI_TREATMENT_COMPLETE" and r["result"] == "COMPLETED"
    ]
    current_tb = [r for r in tb_records if _is_current(r, clock)]

    positives = [r for r in current_tb if r["result"] == "POSITIVE"]
    if positives:
        followed = False
        for positive in positives:
            if any(t["resulted_at"] >= positive["resulted_at"] for t in treatment_records):
                followed = True
                break
        # POSITIVE_UNTREATED wins when no completed-treatment record follows.
        untreated = any(
            not any(t["resulted_at"] >= p["resulted_at"] for t in treatment_records)
            for p in positives
        )
        if untreated:
            return "POSITIVE_UNTREATED"
        if followed:
            return "CLEARED_AFTER_TREATMENT"

    if any(r["result"] == "INDETERMINATE" for r in current_tb) and not any(
        r["result"] == "NEGATIVE" for r in current_tb
    ):
        return "INDETERMINATE"
    if any(r["result"] == "NEGATIVE" for r in current_tb):
        return "CLEARED"
    # EXPIRED when tuberculosis records exist but none of them is current;
    # MISSING when the patient has no tuberculosis record at all.
    if tb_records:
        return "EXPIRED"
    return "MISSING"


def hbv_screen_status(patient_id):
    """PRD 3.3: four cases walked in order, first match wins."""
    clock = db.now()
    records = _patient_screens(patient_id)
    surface = [r for r in records if r["screen_type"] == "HBV_SURFACE_AG" and _is_current(r, clock)]
    core = [r for r in records if r["screen_type"] == "HBV_CORE_AB" and _is_current(r, clock)]

    surface_positive = any(r["result"] == "POSITIVE" for r in surface)
    if surface_positive:
        return "ACTIVE_INFECTION"
    if any(r["result"] == "POSITIVE" for r in core) and not surface_positive:
        return "OCCULT_RISK"
    if any(r["result"] == "NEGATIVE" for r in surface) and any(
        r["result"] == "NEGATIVE" for r in core
    ):
        return "CLEARED"
    return "INCOMPLETE"


def tb_cleared(status):
    """PRD 3.3: only CLEARED and CLEARED_AFTER_TREATMENT count as cleared."""
    return status in ("CLEARED", "CLEARED_AFTER_TREATMENT")


# ------------------------------------------------------- episode routing

def line_of_therapy(prior_episode):
    """PRD 3.4: the chain is walked exactly one hop."""
    if prior_episode is None:
        return 1
    return prior_episode["line_of_therapy"] + 1


def benefit_routing(drug, plan):
    """PRD 3.4: benefit channel first, then site of care.

    Returns ``(benefit_channel, site_of_care)`` or ``None`` when the plan funds
    neither channel the drug's route can use.
    """
    if drug["route"] == "SC":
        if plan["pharmacy_benefit_enabled"]:
            channel = "PHARMACY"
        elif plan["medical_benefit_enabled"]:
            channel = "MEDICAL"
        else:
            return None
    else:  # IV -- the pharmacy benefit is never an option.
        if plan["medical_benefit_enabled"]:
            channel = "MEDICAL"
        else:
            return None

    if drug["route"] == "SC" and channel == "PHARMACY":
        site = "SELF_ADMIN"
    elif drug["route"] == "SC" and channel == "MEDICAL":
        site = "AMBULATORY_INFUSION_CENTER"
    else:
        policy = plan["site_of_care_policy"]
        if policy == "HOME_REQUIRED":
            site = "HOME_INFUSION"
        elif policy == "PREFER_AMBULATORY":
            site = "AMBULATORY_INFUSION_CENTER"
        else:  # SITE_NEUTRAL -- the 180-minute comparison is inclusive.
            if drug["admin_time_minutes"] <= C.SITE_NEUTRAL_AMBULATORY_MAX_MINUTES:
                site = "AMBULATORY_INFUSION_CENTER"
            else:
                site = "HOSPITAL_OUTPATIENT"
    return channel, site


# ---------------------------------------------------- monitoring currency

def episode_matching_labs(episode, drug):
    return [
        lab
        for lab in db.monitoring_labs.values()
        if lab["episode_id"] == episode["id"]
        and lab["panel_type"] == drug["monitoring_panel_type"]
    ]


def monitoring_status(episode, drug):
    """PRD 3.6: only the newest matching panel is consulted."""
    matching = episode_matching_labs(episode, drug)
    if not matching:
        return "OVERDUE"
    newest = max(matching, key=lambda l: (l["collected_at"], l["created_at"], l["_seq"]))
    elapsed = elapsed_whole_days(db.now(), newest["collected_at"])
    if elapsed <= drug["monitoring_panel_interval_days"]:
        return "CURRENT"
    return "OVERDUE"


def lab_grades(alt_u_l, neutrophil_k_ul):
    """PRD 3.6: ALT on inclusive upper bounds, ANC on inclusive lower bounds."""
    if alt_u_l is None:
        alt_grade = 0
    else:
        value = dec(alt_u_l)
        if value <= C.ALT_GRADE_BOUNDS[0]:
            alt_grade = 0
        elif value <= C.ALT_GRADE_BOUNDS[1]:
            alt_grade = 1
        elif value <= C.ALT_GRADE_BOUNDS[2]:
            alt_grade = 2
        elif value <= C.ALT_GRADE_BOUNDS[3]:
            alt_grade = 3
        else:
            alt_grade = 4

    if neutrophil_k_ul is None:
        anc_grade = 0
    else:
        value = dec(neutrophil_k_ul)
        if value >= C.ANC_GRADE_BOUNDS[0]:
            anc_grade = 0
        elif value >= C.ANC_GRADE_BOUNDS[1]:
            anc_grade = 1
        elif value >= C.ANC_GRADE_BOUNDS[2]:
            anc_grade = 2
        elif value >= C.ANC_GRADE_BOUNDS[3]:
            anc_grade = 3
        else:
            anc_grade = 4

    abnormal_grade = max(alt_grade, anc_grade)
    return alt_grade, anc_grade, abnormal_grade, abnormal_grade >= C.LAB_HOLD_GRADE_THRESHOLD


# ------------------------------------------------------------ resumption

def resume_not_before(held_at, hold_reason, molecule_class):
    """PRD 3.9: a reason-by-class washout matrix in whole days."""
    days = C.WASHOUT_DAYS[hold_reason][molecule_class]
    return add_days(held_at, days)


# ---------------------------------------------------------- step therapy

def step_therapy_evaluation(episode, drug, plan):
    """PRD 3.5: required minus satisfied, sorted ascending alphabetically."""
    required = set(drug["step_therapy_required_classes"]) | set(
        plan["step_therapy_classes_required"]
    )
    required.discard(drug["molecule_class"])

    satisfied = set()
    for other in db.episodes.values():
        if other["id"] == episode["id"]:
            continue
        if other["patient_id"] != episode["patient_id"]:
            continue
        if other["therapy_state"] != "DISCONTINUED":
            continue
        if other["discontinuation_reason"] not in C.QUALIFYING_DISCONTINUATION_REASONS:
            continue
        other_drug = db.drugs.get(other["drug_id"])
        if other_drug is None:
            continue
        if other["discontinuation_reason"] == "INTOLERANCE":
            satisfied.add(other_drug["molecule_class"])
        else:
            exposure = other["therapy_exposure_weeks"] or 0
            if exposure >= C.STEP_MIN_EXPOSURE_WEEKS:
                satisfied.add(other_drug["molecule_class"])

    return sorted(required - satisfied)


def therapy_exposure_weeks(episode, discontinued_at):
    """PRD 3.9: whole weeks from therapy_start_at, remainder discarded."""
    if not episode.get("_ever_activated"):
        return 0
    weeks = elapsed_whole_weeks(discontinued_at, episode["therapy_start_at"])
    return max(0, weeks)


# --------------------------------------------------- member cost waterfall

def cost_share_variant(episode, drug, plan):
    """PRD 3.7: the two amounts that feed the waterfall, per benefit channel."""
    if episode["benefit_channel"] == "PHARMACY":
        return int(drug["acquisition_cost_cents"]), 0
    multiplier = (
        dec(plan["hospital_outpatient_multiplier"])
        if episode["site_of_care"] == "HOSPITAL_OUTPATIENT"
        else Decimal("1.00")
    )
    allowed = round_cents(dec(drug["acquisition_cost_cents"]) * multiplier)
    return allowed, int(plan["medical_facility_fee_cents"])


def cost_share_waterfall(episode, drug, plan, dose_count):
    """PRD 3.7: the deductible is consumed dose by dose, coinsurance rounded per dose."""
    allowed, facility = cost_share_variant(episode, drug, plan)
    coinsurance_pct = dec(plan["coinsurance_pct"])
    pool = int(plan["deductible_remaining_cents"])

    per_dose = []
    deductible_total = 0
    coinsurance_total = 0
    for _ in range(dose_count):
        deductible_applied = min(pool, allowed)
        pool -= deductible_applied
        coinsurance = round_cents(dec(allowed - deductible_applied) * coinsurance_pct)
        per_dose.append(deductible_applied + coinsurance + facility)
        deductible_total += deductible_applied
        coinsurance_total += coinsurance

    return {
        "benefit_channel": episode["benefit_channel"],
        "site_of_care": episode["site_of_care"],
        "allowed_per_dose_cents": allowed,
        "facility_per_dose_cents": facility,
        "deductible_applied_cents": deductible_total,
        "coinsurance_cents": coinsurance_total,
        "facility_cents": facility * dose_count,
        "per_dose_share_cents": per_dose,
        "total_member_share_cents": sum(per_dose),
    }


# ------------------------------------------------- authorization selector

def select_authorization(episode, scheduled_start):
    """PRD 3.7: three steps, in this order.

    Returns ``(winner, error_id)``: on success the winning authorization row and
    ``None``; on failure ``None`` and the single error_id this calculation would
    report.  The selector never raises and never mutates, because PRD 2.10
    governs how its outcome is ranked against the chair-calendar check that
    follows it.  The three steps below settle which of
    ``ERR_AUTHORIZATION_UNITS_EXHAUSTED`` and
    ``ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW`` is that outcome -- that pair, and
    only that pair, is what PRD 2.10's second clarification lifts out of the
    general ladder.
    """
    pool = [
        a
        for a in db.authorizations.values()
        if a["episode_id"] == episode["id"] and a["status"] == "APPROVED"
    ]
    if not pool or all((a["units_remaining"] or 0) == 0 for a in pool):
        return None, "ERR_AUTHORIZATION_UNITS_EXHAUSTED"

    in_window = [
        a
        for a in pool
        if a["valid_from"] is not None
        and a["valid_through"] is not None
        and a["valid_from"] <= scheduled_start <= a["valid_through"]
    ]
    if not in_window:
        return None, "ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW"

    usable = [a for a in in_window if (a["units_remaining"] or 0) >= 1]
    if not usable:
        return None, "ERR_AUTHORIZATION_UNITS_EXHAUSTED"

    return min(usable, key=lambda a: (a["valid_from"], a["created_at"], a["_seq"])), None


# ------------------------------------------------------------- assistance

def assistance_coverage_pct(gross_share_cents):
    """PRD 3.7: the tier is keyed on the GROSS dose cost share."""
    if gross_share_cents < C.ASSISTANCE_TIER_1_MAX_EXCLUSIVE:
        return C.ASSISTANCE_TIER_1_PCT
    if gross_share_cents < C.ASSISTANCE_TIER_2_MAX_EXCLUSIVE:
        return C.ASSISTANCE_TIER_2_PCT
    return C.ASSISTANCE_TIER_3_PCT


def apply_assistance(episode, dose_cost_share_cents):
    """PRD 3.7 six-step assistance application.

    Mutates the chosen enrollment's ledger and returns
    ``(reserved_enrollment_id, assistance_applied_cents, patient_out_of_pocket_cents)``.
    """
    from store import bump, touch

    # 1. Select the enrollment -- only ACTIVE enrollments are visible.
    candidates = [
        e
        for e in db.enrollments.values()
        if e["episode_id"] == episode["id"] and e["status"] == "ACTIVE"
    ]
    if not candidates:
        return None, 0, dose_cost_share_cents
    enrollment = min(candidates, key=lambda e: (e["created_at"], e["_seq"]))

    # 2. Coverage tier from the gross share.
    share = dose_cost_share_cents
    coverage_pct = assistance_coverage_pct(share)

    # 3. Gross assistance.
    gross_assistance = round_cents(dec(share) * coverage_pct)

    # 4. Coverage window gate.
    clock = db.now()
    if clock < enrollment["coverage_start"] or clock > enrollment["coverage_end"]:
        return None, 0, share

    # 5. Cap at the remaining benefit.
    applied = min(gross_assistance, enrollment["benefit_remaining_cents"])

    # 6. Settle the books.
    out_of_pocket = share - applied
    enrollment["benefit_reserved_cents"] += applied
    enrollment["benefit_remaining_cents"] -= applied
    if enrollment["benefit_remaining_cents"] == 0 and enrollment["status"] == "ACTIVE":
        enrollment["status"] = "EXHAUSTED"
        bump(enrollment)
    else:
        touch(enrollment)
    return enrollment["id"], applied, out_of_pocket


# ---------------------------------------------------------- quality report

def quality_report(patient, period_start, period_end):
    """PRD 3.9: six counts and four percentages over a half-open window."""
    from errors import fail

    qualifying = [
        v
        for v in db.visits.values()
        if v["patient_id"] == patient["id"]
        and v["visit_type"] in C.QUALIFYING_VISIT_TYPES
        and period_start <= v["visit_datetime"] < period_end
    ]
    if not qualifying:
        fail("ERR_QUALITY_PERIOD_NO_VISITS")

    scored = [v for v in qualifying if v["status"] == "SCORED"]
    at_target = [v for v in scored if v["activity_category"] in C.AT_TARGET_CATEGORIES]
    indicated = [v for v in scored if v["escalation_recommendation"] == "ESCALATE"]

    patient_episodes = [e for e in db.episodes.values() if e["patient_id"] == patient["id"]]
    acted = []
    for visit in indicated:
        deadline = add_days(visit["scored_at"], C.ESCALATION_ACTION_WINDOW_DAYS)
        if any(visit["scored_at"] < e["created_at"] <= deadline for e in patient_episodes):
            acted.append(visit)

    episode_ids = {e["id"]: e for e in patient_episodes}
    doses = [
        a
        for a in db.appointments.values()
        if a["episode_id"] in episode_ids
        and a["status"] == "ADMINISTERED"
        and a["administered_at"] is not None
        and period_start <= a["administered_at"] < period_end
    ]
    biosimilar_doses = []
    for appointment in doses:
        episode = episode_ids[appointment["episode_id"]]
        drug = db.drugs.get(episode["drug_id"])
        if drug is not None and drug["is_biosimilar"]:
            biosimilar_doses.append(appointment)

    def pct(numerator, denominator):
        if denominator == 0:
            return Decimal("0.0")
        return round_half_up(Decimal(100) * Decimal(numerator) / Decimal(denominator), 1)

    return {
        "qualifying_visit_count": len(qualifying),
        "scored_visit_count": len(scored),
        "at_target_visit_count": len(at_target),
        "escalation_indicated_count": len(indicated),
        "escalation_acted_count": len(acted),
        "administered_dose_count": len(doses),
        "completeness_pct": pct(len(scored), len(qualifying)),
        "treat_to_target_attainment_pct": pct(len(at_target), len(scored)),
        "escalation_action_pct": pct(len(acted), len(indicated)),
        "biosimilar_uptake_pct": pct(len(biosimilar_doses), len(doses)),
    }


__all__ = [name for name in dir() if not name.startswith("_")]
