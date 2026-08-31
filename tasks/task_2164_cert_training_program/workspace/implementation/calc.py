"""Domain constants, derived-state recomputation and the eight calculations."""
from __future__ import annotations

from decimal import Decimal

from store import store, touch, sorted_rows
from util import (D, add_days, add_minutes, fmt_iso, parse_iso, round_half_up,
                  whole_days_between)

# ---- constants (SCAFFOLD table 3) ----------------------------------------
MIN_ATTENDANCE_RATIO = D("0.80")
DEMO_PASS_SCORE = D("70")
MAX_DEMO_ATTEMPTS = 3
FACILITY_TURNOVER_BUFFER_MINUTES = 30

READINESS_CORE_WEIGHT = D("60.0")
READINESS_DEMO_WEIGHT = D("40.0")
RECENCY_TIER_1_DAYS = 90
RECENCY_TIER_2_DAYS = 180
RECENCY_TIER_3_DAYS = 365
RECENCY_FACTOR_TIER_1 = D("1.00")
RECENCY_FACTOR_TIER_2 = D("0.90")
RECENCY_FACTOR_TIER_3 = D("0.75")
RECENCY_FACTOR_STALE = D("0.50")
EXERCISE_BONUS_PER_CREDITED = D("2.5")
EXERCISE_BONUS_CAP = D("10.0")
IMPUTED_PENDING_DEMO_SCORE = D("70")

CREDENTIAL_BASE_TERM_DAYS = 365
GRACE_PERIOD_DAYS = 60
RENEWAL_TIER_HOURS = {
    "STANDARD": D("8.0"),
    "WATCH": D("12.0"),
    "PROBATION": D("16.0"),
}
EXTENSION_DAYS_PER_SURPLUS_HOUR = 5
EXTENSION_DAYS_CAP = 90

DEPRECIATION_PCT_PER_MONTH = D("0.015")
RESIDUAL_FLOOR_PCT = D("0.40")
DAYS_PER_DEPRECIATION_MONTH = 30

ROLE_MULTIPLIERS = {
    "TEAM_LEADER": D("1.50"),
    "SEARCH_RESCUE": D("1.25"),
    "MEDICAL": D("1.25"),
    "LOGISTICS": D("1.00"),
    "OBSERVER": D("0.50"),
}

RESPONSE_WINDOW_MINUTES = {"ROUTINE": 240, "URGENT": 120, "CRITICAL": 60}

AAR_MIN_SUMMARY_CHARS = 40

KIT_TYPES = ("BACKPACK_STANDARD", "BACKPACK_ADVANCED", "RADIO_KIT")
EXERCISE_TYPES = ("TABLETOP", "FUNCTIONAL", "FULL_SCALE")
SEVERITIES = ("ROUTINE", "URGENT", "CRITICAL")
ROLE_PLAYED = tuple(ROLE_MULTIPLIERS.keys())


def hnum(value, places=1):
    if value is None:
        return None
    return float(round_half_up(value, places))


# ---- small lookups --------------------------------------------------------
def core_active_modules():
    return [m for m in store.curriculum_modules.values()
            if m["is_core"] and m["status"] == "ACTIVE"]


def core_active_count():
    return len(core_active_modules())


def core_hours_total():
    total = D(0)
    for m in core_active_modules():
        total += D(m["contact_hours"])
    return total


def trainee_rows(collection, trainee_id):
    return [r for r in collection.values() if r.get("trainee_id") == trainee_id]


def module_of(row):
    return store.curriculum_modules.get(row.get("module_id"))


def credential_of(trainee_id):
    for c in sorted_rows(list(store.credentials.values())):
        if c["trainee_id"] == trainee_id:
            return c
    return None


def cohort_trainees(cohort_id):
    return [t for t in store.trainees.values() if t.get("cohort_id") == cohort_id]


def cohort_sessions(cohort_id):
    return [s for s in store.class_sessions.values() if s.get("cohort_id") == cohort_id]


# ---- conserved counters ---------------------------------------------------
def recompute_session_counter(session):
    session["recorded_completion_count"] = sum(
        1 for c in store.module_completions.values()
        if c["class_session_id"] == session["id"] and c["status"] != "VOIDED")


def recompute_cohort_seats(cohort):
    trainees = cohort_trainees(cohort["id"])
    cohort["seats_confirmed"] = sum(
        1 for t in trainees if t["enrollment_status"] in ("ENROLLED", "GRADUATED"))
    cohort["seats_waitlisted"] = sum(
        1 for t in trainees if t["enrollment_status"] == "WAITLISTED")


def recompute_cohort_delivered_hours(cohort):
    total = D(0)
    for s in cohort_sessions(cohort["id"]):
        if s["status"] == "DELIVERED":
            mod = store.curriculum_modules.get(s["module_id"])
            if mod:
                total += D(mod["contact_hours"])
    cohort["delivered_contact_hours"] = hnum(total)


def recompute_program_counters(program):
    pid = program["id"]
    program["active_member_count"] = sum(
        1 for t in store.trainees.values()
        if t["program_id"] == pid and t["enrollment_status"] in ("ENROLLED", "GRADUATED"))
    program["pending_graduation_count"] = sum(
        1 for c in store.cohorts.values()
        if c["program_id"] == pid and c["status"] == "GRADUATION_REVIEW")
    committed = 0
    for iss in store.equipment_issuances.values():
        if iss["status"] != "ISSUED":
            continue
        asset = store.equipment_assets.get(iss["asset_id"])
        if asset and asset["program_id"] == pid:
            committed += int(asset["unit_value_cents"])
    program["equipment_committed_cents"] = committed


def recompute_activation_counts(activation):
    rows = [r for r in store.roster_assignments.values()
            if r["activation_id"] == activation["id"]]
    rostered = sum(1 for r in rows if r["status"] in
                   ("NOTIFIED", "ACCEPTED", "DEPLOYED", "RELEASED"))
    accepted = sum(1 for r in rows if r["status"] in ("ACCEPTED", "DEPLOYED", "RELEASED"))
    deployed = sum(1 for r in rows if r["status"] in ("DEPLOYED", "RELEASED"))
    activation["rostered_count"] = rostered
    activation["accepted_count"] = accepted
    activation["deployed_count"] = deployed
    if rostered == 0:
        activation["fill_status"] = "UNFILLED"
    elif rostered < int(activation["requested_responders"]):
        activation["fill_status"] = "PARTIAL"
    else:
        activation["fill_status"] = "FILLED"


def recompute_exercise_counter(exercise):
    exercise["accepted_participant_count"] = sum(
        1 for p in store.exercise_participations.values()
        if p["exercise_id"] == exercise["id"] and p["status"] == "CREDITED")


# ---- trainee derived tallies ---------------------------------------------
def compute_last_qualifying(trainee):
    stamps = []
    for c in store.module_completions.values():
        if c["trainee_id"] == trainee["id"] and c["status"] == "PASSED":
            stamps.append(c["updated_at"])
    for p in store.exercise_participations.values():
        if p["trainee_id"] == trainee["id"] and p["status"] == "CREDITED":
            stamps.append(p["updated_at"])
    for r in store.roster_assignments.values():
        if r["trainee_id"] == trainee["id"] and r["status"] == "RELEASED":
            stamps.append(r["updated_at"])
    if not stamps:
        return None
    return max(stamps, key=lambda s: parse_iso(s))


def recompute_trainee_tallies(trainee):
    """earned_contact_hours, passed_core_count, equipment_liability_cents and
    last_qualifying_activity_at — all aggregates over primary rows."""
    earned = D(0)
    passed_core = 0
    for c in store.module_completions.values():
        if c["trainee_id"] != trainee["id"] or c["status"] != "PASSED":
            continue
        earned += D(c.get("credited_contact_hours") or 0)
        mod = module_of(c)
        if mod and mod["is_core"]:
            passed_core += 1
    trainee["earned_contact_hours"] = hnum(earned)
    trainee["passed_core_count"] = passed_core
    liability = 0
    for iss in sorted_rows(trainee_rows(store.equipment_issuances, trainee["id"])):
        if iss["status"] == "LOST_WRITTEN_OFF":
            liability += int(iss.get("settlement_cents") or 0)
    trainee["equipment_liability_cents"] = liability
    trainee["last_qualifying_activity_at"] = compute_last_qualifying(trainee)


# ---- calculation 1: trainee_readiness_score ------------------------------
def readiness_components(trainee):
    total = core_hours_total()
    earned_cert = D(0)
    earned_prov = D(0)
    demos_cert = []
    demos_prov = []
    for c in store.module_completions.values():
        if c["trainee_id"] != trainee["id"]:
            continue
        mod = module_of(c)
        if mod is None:
            continue
        if c["status"] == "PASSED":
            if mod["is_core"]:
                earned_cert += D(mod["contact_hours"])
                earned_prov += D(mod["contact_hours"])
            if mod["requires_skills_demo"] and c.get("demo_score") is not None:
                demos_cert.append(D(c["demo_score"]))
                demos_prov.append(D(c["demo_score"]))
        elif c["status"] == "SKILLS_PENDING":
            if mod["is_core"]:
                earned_prov += D(mod["contact_hours"]) / D(2)
                demos_prov.append(IMPUTED_PENDING_DEMO_SCORE)

    def ratio(earned):
        if total == 0:
            return D("0.0")
        r = earned / total
        return r if r < D(1) else D(1)

    def avg(values):
        if not values:
            return D("0.0")
        return sum(values, D(0)) / D(len(values))

    lqa = trainee.get("last_qualifying_activity_at")
    if not lqa:
        recency = RECENCY_FACTOR_STALE
        days_since = None
    else:
        days_since = whole_days_between(parse_iso(lqa), store.now())
        if days_since <= RECENCY_TIER_1_DAYS:
            recency = RECENCY_FACTOR_TIER_1
        elif days_since <= RECENCY_TIER_2_DAYS:
            recency = RECENCY_FACTOR_TIER_2
        elif days_since <= RECENCY_TIER_3_DAYS:
            recency = RECENCY_FACTOR_TIER_3
        else:
            recency = RECENCY_FACTOR_STALE

    credited = sum(1 for p in store.exercise_participations.values()
                   if p["trainee_id"] == trainee["id"] and p["status"] == "CREDITED")
    bonus = EXERCISE_BONUS_PER_CREDITED * D(credited)
    if bonus > EXERCISE_BONUS_CAP:
        bonus = EXERCISE_BONUS_CAP

    def score(core_ratio, demo_avg):
        base = READINESS_CORE_WEIGHT * core_ratio + READINESS_DEMO_WEIGHT * (demo_avg / D("100.0"))
        raw = base * recency + bonus
        if raw < D(0):
            raw = D(0)
        if raw > D(100):
            raw = D(100)
        return round_half_up(raw, 2)

    ratio_cert = ratio(earned_cert)
    ratio_prov = ratio(earned_prov)
    avg_cert = avg(demos_cert)
    avg_prov = avg(demos_prov)
    return {
        "core_hours_total": total,
        "core_hours_earned_certified": earned_cert,
        "core_hours_earned_provisional": earned_prov,
        "core_ratio_certified": ratio_cert,
        "core_ratio_provisional": ratio_prov,
        "demo_avg_certified": avg_cert,
        "demo_avg_provisional": avg_prov,
        "recency_factor": recency,
        "days_since": days_since,
        "exercise_bonus": bonus,
        "certified_readiness_score": score(ratio_cert, avg_cert),
        "provisional_readiness_score": score(ratio_prov, avg_prov),
    }


def recompute_readiness(trainee):
    trainee["readiness_score"] = float(readiness_components(trainee)["certified_readiness_score"])


# ---- calculation: refresher_currency_hours -------------------------------
def refresher_hours_in_window(credential):
    """Half-open window [term_start_on, logical_now)."""
    start = parse_iso(credential["term_start_on"])
    now = store.now()
    trainee_id = credential["trainee_id"]
    total = D(0)
    for p in store.exercise_participations.values():
        if p["trainee_id"] != trainee_id or p["status"] != "CREDITED":
            continue
        stamp = parse_iso(p["updated_at"])
        if start <= stamp < now:
            total += D(p.get("hours_credited") or 0)
    for c in store.module_completions.values():
        if c["trainee_id"] != trainee_id or c["status"] != "PASSED":
            continue
        mod = module_of(c)
        if not mod or not mod["refresher_eligible"]:
            continue
        stamp = parse_iso(c["updated_at"])
        if start <= stamp < now:
            total += D(c.get("credited_contact_hours") or 0)
    return round_half_up(total, 1)


def refresh_refresher_hours(credential):
    credential["refresher_hours_in_term"] = float(refresher_hours_in_window(credential))


def add_refresher_hours(credential, hours):
    current = D(credential.get("refresher_hours_in_term") or 0)
    credential["refresher_hours_in_term"] = hnum(current + D(hours))


# ---- calculation: credential_renewal_terms -------------------------------
def resolve_tier(reinstatement_count):
    if reinstatement_count == 0:
        return "STANDARD"
    if 1 <= reinstatement_count <= 2:
        return "WATCH"
    return "PROBATION"


def apply_issuance_terms(credential):
    """Steps 1, 2, 3 and 8 with r == 0 (PRD 3.5)."""
    tier = resolve_tier(0)
    credential["renewal_tier"] = tier
    credential["required_refresher_hours"] = float(RENEWAL_TIER_HOURS[tier])
    start = store.now()
    credential["term_start_on"] = fmt_iso(start)
    expires = add_days(start, CREDENTIAL_BASE_TERM_DAYS)
    credential["expires_on"] = fmt_iso(expires)
    credential["grace_ends_on"] = fmt_iso(add_days(expires, GRACE_PERIOD_DAYS))


def renewal_tier_and_requirement(credential):
    """Steps 2 and 3, read from the PRE-increment reinstatement_count."""
    tier = resolve_tier(int(credential["reinstatement_count"]))
    return tier, RENEWAL_TIER_HOURS[tier]


def apply_renewal_terms(credential, tier, required):
    """Steps 5-10 of credential_renewal_terms; the gate (step 4) is enforced
    by the caller before this runs."""
    hours = D(credential.get("refresher_hours_in_term") or 0)
    surplus = hours - required
    if surplus < D(0):
        surplus = D(0)
    extension = int(surplus) * EXTENSION_DAYS_PER_SURPLUS_HOUR
    if extension > EXTENSION_DAYS_CAP:
        extension = EXTENSION_DAYS_CAP
    new_term_days = CREDENTIAL_BASE_TERM_DAYS + extension
    start = store.now()
    credential["renewal_tier"] = tier
    credential["required_refresher_hours"] = float(required)
    credential["term_start_on"] = fmt_iso(start)
    expires = add_days(start, new_term_days)
    credential["expires_on"] = fmt_iso(expires)
    credential["grace_ends_on"] = fmt_iso(add_days(expires, GRACE_PERIOD_DAYS))
    credential["reinstatement_count"] = int(credential["reinstatement_count"]) + 1
    credential["refresher_hours_in_term"] = 0.0


# ---- calculation: equipment_loss_settlement ------------------------------
def compute_settlement(issuance, asset, credential):
    issued = parse_iso(issuance["issued_on"])
    lost = parse_iso(issuance["lost_reported_on"])
    days = whole_days_between(issued, lost)
    months = days // DAYS_PER_DEPRECIATION_MONTH
    residual = D("1.00") - DEPRECIATION_PCT_PER_MONTH * D(months)
    if residual < RESIDUAL_FLOOR_PCT:
        residual = RESIDUAL_FLOOR_PCT
    residual = round_half_up(residual, 4)
    unit = int(asset["unit_value_cents"])
    if credential is None or credential["status"] in ("SUSPENDED", "REVOKED"):
        variant = "FULL_REPLACEMENT"
        cents = unit
    else:
        variant = "DEPRECIATED_WRITEOFF"
        cents = int(round_half_up(D(unit) * residual, 0))
    issuance["months_held"] = months
    issuance["residual_pct"] = float(residual)
    issuance["settlement_variant"] = variant
    issuance["settlement_cents"] = cents


# ---- calculation: equipment_issuance_selection ---------------------------
def select_asset(program_id, kit_type):
    pool = [a for a in store.equipment_assets.values()
            if a["program_id"] == program_id
            and a["kit_type"] == kit_type
            and a["status"] == "IN_STOCK"
            and a["condition"] in ("NEW", "SERVICEABLE")]
    if not pool:
        return None
    pool.sort(key=lambda a: (int(a["issue_count"]), int(a["unit_value_cents"]),
                             a["created_at"], a["_seq"]))
    return pool[0]


# ---- calculation: activation_roster_selection ----------------------------
def trainee_is_eligible(trainee, activation):
    if trainee["program_id"] != activation["program_id"]:
        return False, None
    if trainee["enrollment_status"] != "GRADUATED":
        return False, None
    if trainee.get("deployment_hold"):
        return False, None
    cred = credential_of(trainee["id"])
    if cred is None or cred["status"] not in ("ACTIVE", "GRACE"):
        return False, None
    for r in store.roster_assignments.values():
        if r["trainee_id"] != trainee["id"]:
            continue
        if r["status"] not in ("NOTIFIED", "ACCEPTED", "DEPLOYED"):
            continue
        act = store.activations.get(r["activation_id"])
        if act and act["status"] in ("REQUESTED", "ROSTERED", "ACTIVATED"):
            return False, None
    if activation["severity"] == "CRITICAL" and cred["status"] != "ACTIVE":
        return False, None
    return True, cred


def rank_candidates(activation):
    buckets = {"ACTIVE": [], "GRACE": []}
    for t in store.trainees.values():
        eligible, cred = trainee_is_eligible(t, activation)
        if eligible:
            buckets[cred["status"]].append(t)

    def sort_key(t):
        score = round_half_up(D(t.get("readiness_score") or 0), 2)
        last = t.get("last_deployed_at")
        never = 0 if last is None else 1
        stamp = last or ""
        return (-score, never, stamp, t["created_at"], t["_seq"])

    ordered = sorted(buckets["ACTIVE"], key=sort_key) + sorted(buckets["GRACE"], key=sort_key)
    return ordered


# ---- calculation: exercise_hours_credit ----------------------------------
def exercise_hours(exercise, participation):
    base = D(exercise["base_credit_hours"])
    mult = D(participation["role_multiplier"])
    return hnum(base * mult)


# ---- calculation: instructor_daily_contact_load --------------------------
def instructor_day_load(instructor_id, day, exclude_session_id=None):
    total = D(0)
    for s in store.class_sessions.values():
        if s["instructor_id"] != instructor_id:
            continue
        if s["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        if parse_iso(s["starts_at"]).date() != day:
            continue
        mod = store.curriculum_modules.get(s["module_id"])
        if mod:
            total += D(mod["contact_hours"])
    return total
