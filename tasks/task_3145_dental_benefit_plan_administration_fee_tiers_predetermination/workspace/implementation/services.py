"""Shared helpers for entity creation, mutation, calendar math, and
fee schedule resolution."""

from datetime import timedelta

from db import store
from errors import ApiError, ERR_NO_FEE_SCHEDULE
from response import new_id, iso_now, format_iso


def add_months(dt, months):
    """Add `months` calendar months to a tz-aware datetime."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    # Clamp day-of-month to last valid day.
    last_day = _days_in_month(year, month)
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        return 31
    next_month_first = (year, month + 1, 1)
    if month == 12:
        next_month_first = (year + 1, 1, 1)
    from datetime import date
    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - first).days


def months_between(start, end):
    """Whole calendar months elapsed from start to end (may be negative)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # Adjust for partial month
    candidate = add_months(start, months)
    if candidate > end:
        months -= 1
    return months


def whole_years_between(dob, when):
    """Age in whole years at `when`. A person is 17 until their 18th birthday."""
    years = when.year - dob.year
    # Subtract one if the birthday hasn't occurred yet this year.
    if (when.month, when.day) < (dob.month, dob.day):
        years -= 1
    return years


def create_record(collection, fields, has_updated=True):
    """Mint id/created_at/updated_at/version per PRD §2.4."""
    record = dict(fields)
    record["id"] = new_id()
    record["created_at"] = iso_now()
    if has_updated:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    collection[record["id"]] = record
    return record


def mutate_record(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.11)."""
    record["updated_at"] = iso_now()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Fee schedule resolution
# ---------------------------------------------------------------------------

def resolve_active_schedule(tier, anchor_dt):
    """The ACTIVE FeeSchedule for `tier` whose window contains `anchor_dt`.

    Window semantics: effective_from <= anchor < effective_to (effective_to
    may be None). If multiple overlap (should not happen after truncation),
    pick the one with the latest effective_from.
    """
    candidates = []
    for sched in store.fee_schedules.values():
        if sched["tier"] != tier:
            continue
        if sched["status"] != "ACTIVE":
            continue
        if sched["effective_from_dt"] > anchor_dt:
            continue
        if sched["effective_to_dt"] is not None and anchor_dt >= sched["effective_to_dt"]:
            continue
        candidates.append(sched)
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["effective_from_dt"])
    return candidates[-1]


def resolve_schedule_for_claim(claim, provider, anchor_dt):
    """Pick the schedule for claim pricing — pinned via predetermination
    when applicable, else by service_date."""
    predet_id = claim.get("predetermination_id")
    if predet_id:
        predet = store.predeterminations.get(predet_id)
        if predet is not None:
            # Lazy EXPIRED check at claim time.
            _maybe_expire_predetermination(predet)
            if predet["status"] == "APPROVED" and predet.get("version_pin_fee_schedule_id"):
                sched = store.fee_schedules.get(predet["version_pin_fee_schedule_id"])
                if sched is not None:
                    return sched
    return resolve_active_schedule(provider["tier"], anchor_dt)


def find_entry(schedule_id, cdt_code):
    for entry in store.fee_schedule_entries.values():
        if entry["fee_schedule_id"] == schedule_id and entry["cdt_code"] == cdt_code:
            return entry
    return None


def require_entry(schedule_id, cdt_code):
    entry = find_entry(schedule_id, cdt_code)
    if entry is None:
        raise ApiError(
            ERR_NO_FEE_SCHEDULE,
            "Schedule does not contain an entry for cdt_code %s" % cdt_code,
            422,
        )
    return entry


# ---------------------------------------------------------------------------
# Plan year bucketing
# ---------------------------------------------------------------------------

def plan_year_key(plan, service_dt):
    anchor_month = plan["plan_year_start_month"]
    if service_dt.month >= anchor_month:
        year_a = service_dt.year
    else:
        year_a = service_dt.year - 1
    year_b = year_a + 1
    return "%04d-%04d" % (year_a, year_b)


def get_or_create_accumulator(subscriber_id, dependent_id, key):
    """Lazily materialize the BenefitAccumulator per (subscriber, dependent, plan_year)."""
    for acc in store.accumulators.values():
        if (
            acc["subscriber_id"] == subscriber_id
            and acc.get("dependent_id") == dependent_id
            and acc["plan_year_key"] == key
        ):
            return acc
    acc = create_record(
        store.accumulators,
        {
            "subscriber_id": subscriber_id,
            "dependent_id": dependent_id,
            "plan_year_key": key,
            "deductible_met_cents": 0,
            "annual_max_used_cents": 0,
        },
    )
    return acc


# ---------------------------------------------------------------------------
# Predetermination lazy expiry
# ---------------------------------------------------------------------------

def _maybe_expire_predetermination(predet):
    if predet["status"] == "APPROVED" and predet.get("expires_on_dt") is not None:
        if store.clock > predet["expires_on_dt"]:
            predet["status"] = "EXPIRED"
            mutate_record(predet)


def maybe_expire(predet):
    _maybe_expire_predetermination(predet)


# ---------------------------------------------------------------------------
# Pricing + cost share
# ---------------------------------------------------------------------------

def price_line_against_schedule(schedule, plan, cdt_code, submitted_cents):
    """Compute allowed/ABP fields for a single line.

    Returns (entry, allowed_cents, abp_applied, abp_patient_difference_cents).
    Raises ERR_NO_FEE_SCHEDULE when the code has no entry.
    """
    entry = require_entry(schedule["id"], cdt_code)
    base_allowed = min(submitted_cents, entry["allowed_cents"])
    abp_applied = False
    abp_patient_diff = 0
    allowed = base_allowed
    alt_cdt = entry.get("abp_alternative_cdt") or ""
    if plan["abp_enabled"] and alt_cdt:
        alt_entry = find_entry(schedule["id"], alt_cdt)
        if alt_entry is not None:
            abp_allowed = min(submitted_cents, alt_entry["allowed_cents"])
            if abp_allowed < base_allowed:
                abp_applied = True
                abp_patient_diff = base_allowed - abp_allowed
                allowed = abp_allowed
    return entry, allowed, abp_applied, abp_patient_diff


def plan_year_key_for(plan, dt):
    return plan_year_key(plan, dt)


def floor_pct(amount, pct):
    """floor(amount * pct / 100) — integer arithmetic."""
    return (amount * pct) // 100


def category_pct(plan, category):
    if category == "PREVENTIVE":
        return plan["preventive_coinsurance_pct"]
    if category == "BASIC":
        return plan["basic_coinsurance_pct"]
    return plan["major_coinsurance_pct"]


def waiting_gate_denies(plan, subscriber, category, service_dt):
    """True when the line is inside the waiting period (boundary inclusive)."""
    if category == "PREVENTIVE":
        wait_months = 0
    elif category == "BASIC":
        wait_months = plan["basic_waiting_months"]
    else:
        wait_months = plan["major_waiting_months"]
    earliest = add_months(subscriber["effective_date_dt"], wait_months)
    return service_dt < earliest


def cdt_matches(rule_code, line_code):
    """Exact match, or wildcard like 'D1*'."""
    if not rule_code:
        return False
    if rule_code.endswith("*"):
        return line_code.startswith(rule_code[:-1])
    return rule_code == line_code


def paid_lines_for_patient(subscriber_id, dependent_id):
    """All PAYABLE lines on PAID claims belonging to this patient."""
    out = []
    for claim in store.claims.values():
        if claim["subscriber_id"] != subscriber_id:
            continue
        if claim.get("dependent_id") != dependent_id:
            continue
        if claim["status"] != "PAID":
            continue
        for line in store.claim_lines.values():
            if line["claim_id"] == claim["id"] and line["status"] == "PAYABLE":
                out.append((claim, line))
    return out


def evaluate_limitations(plan, subscriber, claim, line, patient_dob_dt, service_dt):
    """Run plan LimitationRules in created_at ASC; return first denial_code or None.

    The MISSING_TOOTH clause is plan-level per PRD §3.7: it fires when
    `missing_tooth_clause_active` is true and the line names a `tooth_number`
    that the claim's `tooth_missing_prior_to_coverage` map attests — no
    LimitationRule row is needed. The plan-level clause is evaluated FIRST
    (it is part of the plan configuration, not a declared rule), before any
    declared LimitationRule.
    """
    # Plan-level missing-tooth clause (PRD §3.7).
    if plan["missing_tooth_clause_active"]:
        tooth = line.get("tooth_number") or ""
        if tooth:
            attest = claim.get("tooth_missing_prior_to_coverage") or {}
            if attest.get(tooth) is True:
                return "MISSING_TOOTH"
    rules = [
        r for r in store.limitation_rules.values()
        if r["plan_id"] == plan["id"] and r["status"] == "ACTIVE"
    ]
    rules.sort(key=lambda r: r["created_at"])
    for rule in rules:
        if not cdt_matches(rule["cdt_code"], line["cdt_code"]):
            continue
        kind = rule["rule_kind"]
        if kind == "FREQUENCY":
            window_start = add_months(service_dt, -rule["window_months"])
            count = 0
            for prior_claim, prior_line in paid_lines_for_patient(
                claim["subscriber_id"], claim.get("dependent_id")
            ):
                if prior_line["cdt_code"] != line["cdt_code"]:
                    continue
                sd = prior_claim["service_date_dt"]
                if window_start <= sd <= service_dt:
                    count += 1
            if count + 1 > rule["max_occurrences"]:
                return "FREQUENCY"
        elif kind == "AGE_MAX":
            age = whole_years_between(patient_dob_dt, service_dt)
            if rule["age_years_max"] and age > rule["age_years_max"]:
                return "AGE_LIMIT"
        elif kind == "AGE_MIN":
            age = whole_years_between(patient_dob_dt, service_dt)
            if rule["age_years_min"] and age < rule["age_years_min"]:
                return "AGE_LIMIT"
        elif kind == "REPLACEMENT_INTERVAL":
            # Most recent PAID line for same tooth_number in same MAJOR category.
            tooth = line.get("tooth_number") or ""
            if not tooth:
                continue
            candidates = []
            for prior_claim, prior_line in paid_lines_for_patient(
                claim["subscriber_id"], claim.get("dependent_id")
            ):
                if (prior_line.get("tooth_number") or "") != tooth:
                    continue
                if prior_line.get("category") != "MAJOR":
                    continue
                candidates.append((prior_claim, prior_line))
            if candidates:
                # Order by service_date DESC, tie-break created_at ASC.
                candidates.sort(
                    key=lambda cl: (cl[0]["service_date_dt"],),
                    reverse=True,
                )
                # Stable sort by created_at among ties on service_date.
                best_sd = candidates[0][0]["service_date_dt"]
                tied = [c for c in candidates if c[0]["service_date_dt"] == best_sd]
                tied.sort(key=lambda c: c[1]["created_at"])
                prior_claim = tied[0][0]
                if months_between(prior_claim["service_date_dt"], service_dt) < rule["window_months"]:
                    return "FREQUENCY"
        elif kind == "MISSING_TOOTH":
            if not plan["missing_tooth_clause_active"]:
                continue
            tooth = line.get("tooth_number") or ""
            if not tooth:
                continue
            attest = claim.get("tooth_missing_prior_to_coverage") or {}
            if attest.get(tooth) is True:
                return "MISSING_TOOTH"
    return None


def estimate_cost_share(plan, subscriber, accumulator, category, allowed, abp_diff, cob_other_paid):
    """Estimate what the plan would pay without mutating the accumulator.

    The estimate does NOT apply the annual-maximum cap: the cap is enforced
    as a separate guard at approve time so a clinician can never promise
    payment the plan cannot deliver. The estimate is the uncapped
    coinsurance share that would be paid absent the cap.

    Returns (line_deductible, coinsurance_plan_cents, plan_pay_cents,
             patient_pay_cents, cob_secondary_payment_cents).
    """
    if category == "PREVENTIVE" and not plan["deductible_applies_preventive"]:
        line_deductible = 0
    else:
        deductible_remaining = plan["deductible_cents"] - accumulator["deductible_met_cents"]
        line_deductible = min(allowed, max(0, deductible_remaining))
    coinsurance_base = allowed - line_deductible
    pct = category_pct(plan, category)
    coinsurance_plan = floor_pct(coinsurance_base, pct)
    # Estimate does not cap at the annual maximum — the approve-step guard
    # refuses the approval when the estimate exceeds the remaining cap.
    plan_pay_before_cob = coinsurance_plan
    if subscriber["cob_priority"] == "SECONDARY":
        primary_paid = cob_other_paid or 0
        secondary_cap = allowed - primary_paid - line_deductible
        plan_pay = max(0, min(plan_pay_before_cob, secondary_cap))
        cob_secondary = plan_pay
    else:
        plan_pay = plan_pay_before_cob
        cob_secondary = 0
    patient_pay = allowed - plan_pay + abp_diff
    return line_deductible, coinsurance_plan, plan_pay, patient_pay, cob_secondary


def recompute_predet_estimate(predet):
    """Run the forward-looking estimate against the schedule governing the
    planned_service_date. Raises ERR_NO_FEE_SCHEDULE when no schedule
    covers. The accumulator is READ-ONLY here.

    Returns the schedule used (so callers can pin at approve).
    """
    plan = store.plans[predet["plan_id"]]
    subscriber = store.subscribers[predet["subscriber_id"]]
    provider = store.providers[predet["provider_id"]]
    anchor = predet["planned_service_date_dt"]

    schedule = resolve_active_schedule(provider["tier"], anchor)
    if schedule is None:
        raise ApiError(
            ERR_NO_FEE_SCHEDULE,
            "No ACTIVE FeeSchedule covers the provider's tier at the planned_service_date",
            422,
        )
    entry, allowed, abp_applied, abp_diff = price_line_against_schedule(
        schedule, plan, predet["cdt_code"], predet["submitted_amount_cents"]
    )
    # Resolve patient
    dependent_id = predet.get("dependent_id")
    if dependent_id:
        patient = store.dependents[dependent_id]
    else:
        patient = subscriber
    key = plan_year_key(plan, anchor)
    # Read-only accumulator: materialize-or-zero
    accumulator = None
    for acc in store.accumulators.values():
        if (
            acc["subscriber_id"] == subscriber["id"]
            and acc.get("dependent_id") == dependent_id
            and acc["plan_year_key"] == key
        ):
            accumulator = acc
            break
    if accumulator is None:
        accumulator = {"deductible_met_cents": 0, "annual_max_used_cents": 0}

    category = entry["category"]

    # Apply waiting gate and limitations — if they'd deny, plan pays 0.
    would_deny = False
    if waiting_gate_denies(plan, subscriber, category, anchor):
        would_deny = True
    else:
        pseudo_claim = {
            "subscriber_id": subscriber["id"],
            "dependent_id": dependent_id,
            "tooth_missing_prior_to_coverage": {},
        }
        pseudo_line = {
            "cdt_code": predet["cdt_code"],
            "tooth_number": "",
        }
        denial = evaluate_limitations(plan, subscriber, pseudo_claim, pseudo_line,
                                      patient["date_of_birth_dt"], anchor)
        if denial is not None:
            would_deny = True

    if would_deny:
        est_plan_pay = 0
        est_patient = predet["submitted_amount_cents"]
        est_allowed = allowed
        predet["estimated_allowed_cents"] = est_allowed
        predet["estimated_plan_pay_cents"] = 0
        predet["estimated_patient_pay_cents"] = predet["submitted_amount_cents"]
        predet["abp_applied"] = abp_applied
        return schedule

    line_ded, coins, plan_pay, patient_pay, _cob = estimate_cost_share(
        plan, subscriber, accumulator, category, allowed, abp_diff, 0
    )
    predet["estimated_allowed_cents"] = allowed
    predet["estimated_plan_pay_cents"] = plan_pay
    predet["estimated_patient_pay_cents"] = patient_pay
    predet["abp_applied"] = abp_applied
    return schedule


def compute_line_cost_share_mutating(plan, subscriber, claim, accumulator, line,
                                     entry, allowed, abp_applied, abp_diff):
    """Adjudication variant — mutates the accumulator in line order."""
    category = entry["category"]
    if category == "PREVENTIVE" and not plan["deductible_applies_preventive"]:
        line_deductible = 0
    else:
        deductible_remaining = plan["deductible_cents"] - accumulator["deductible_met_cents"]
        line_deductible = min(allowed, max(0, deductible_remaining))
    coinsurance_base = allowed - line_deductible
    pct = category_pct(plan, category)
    coinsurance_plan = floor_pct(coinsurance_base, pct)
    max_remaining = plan["annual_maximum_cents"] - accumulator["annual_max_used_cents"]
    plan_pay_before_cob = min(coinsurance_plan, max(0, max_remaining))
    if subscriber["cob_priority"] == "SECONDARY":
        primary_paid = claim.get("cob_other_plan_paid_cents") or 0
        secondary_cap = allowed - primary_paid - line_deductible
        plan_pay = max(0, min(plan_pay_before_cob, secondary_cap))
        cob_secondary = plan_pay
    else:
        plan_pay = plan_pay_before_cob
        cob_secondary = 0
    patient_pay = allowed - plan_pay + abp_diff

    line["category"] = category
    line["allowed_cents"] = allowed
    line["abp_applied"] = abp_applied
    line["abp_patient_difference_cents"] = abp_diff
    line["deductible_applied_cents"] = line_deductible
    line["coinsurance_plan_cents"] = coinsurance_plan
    line["plan_pay_cents"] = plan_pay
    line["patient_pay_cents"] = patient_pay
    line["cob_secondary_payment_cents"] = cob_secondary

    # Accumulator mutations
    accumulator["deductible_met_cents"] += line_deductible
    accumulator["annual_max_used_cents"] += plan_pay


def adjudicate_claim(claim):
    """Run the per-line pipeline per PRD §3.7. Mutates lines and the accumulator."""
    plan = store.plans[claim["plan_id"]]
    subscriber = store.subscribers[claim["subscriber_id"]]
    provider = store.providers[claim["provider_id"]]

    schedule = resolve_schedule_for_claim(claim, provider, claim["service_date_dt"])
    if schedule is None:
        raise ApiError(
            ERR_NO_FEE_SCHEDULE,
            "No ACTIVE FeeSchedule covers the provider's tier at the service_date",
            422,
        )

    # Resolve patient
    dependent_id = claim.get("dependent_id")
    if dependent_id:
        patient = store.dependents[dependent_id]
    else:
        patient = subscriber

    key = plan_year_key(plan, claim["service_date_dt"])
    accumulator = get_or_create_accumulator(subscriber["id"], dependent_id, key)

    lines = [l for l in store.claim_lines.values() if l["claim_id"] == claim["id"]]
    lines.sort(key=lambda l: l["line_number"])

    # Step 1+2: price each line (PENDING -> PRICED, transient)
    priced = []
    for line in lines:
        entry, allowed, abp_applied, abp_diff = price_line_against_schedule(
            schedule, plan, line["cdt_code"], line["submitted_amount_cents"]
        )
        line["category"] = entry["category"]
        line["allowed_cents"] = allowed
        line["abp_applied"] = abp_applied
        line["abp_patient_difference_cents"] = abp_diff
        line["status"] = "PRICED"
        priced.append((line, entry, allowed, abp_applied, abp_diff))

    # Steps 3-7: per line, gates then cost-share (mutates accumulator)
    for line, entry, allowed, abp_applied, abp_diff in priced:
        service_dt = claim["service_date_dt"]
        denial = None
        if waiting_gate_denies(plan, subscriber, entry["category"], service_dt):
            denial = "WAITING_PERIOD"
        else:
            denial = evaluate_limitations(
                plan, subscriber, claim, line, patient["date_of_birth_dt"], service_dt
            )
        if denial is not None:
            line["status"] = "DENIED"
            line["denial_code"] = denial
            line["plan_pay_cents"] = 0
            line["patient_pay_cents"] = line["submitted_amount_cents"]
            line["deductible_applied_cents"] = 0
            line["coinsurance_plan_cents"] = 0
            line["cob_secondary_payment_cents"] = 0
            mutate_record(line)
        else:
            compute_line_cost_share_mutating(
                plan, subscriber, claim, accumulator, line, entry, allowed, abp_applied, abp_diff
            )
            line["denial_code"] = None
            line["status"] = "PAYABLE"
            mutate_record(line)

    # Finalize totals
    total_submitted = sum(l["submitted_amount_cents"] for l in lines)
    total_allowed = sum(l["allowed_cents"] for l in lines)
    total_plan = sum(l["plan_pay_cents"] for l in lines)
    total_patient = sum(l["patient_pay_cents"] for l in lines)
    claim["total_submitted_cents"] = total_submitted
    claim["total_allowed_cents"] = total_allowed
    claim["total_plan_pay_cents"] = total_plan
    claim["total_patient_pay_cents"] = total_patient
    if subscriber["cob_priority"] == "SECONDARY":
        claim["cob_secondary_payment_cents"] = sum(
            l.get("cob_secondary_payment_cents", 0) for l in lines
        )
    else:
        claim["cob_secondary_payment_cents"] = 0

    # All denied -> DENIED, else ADJUDICATED
    if all(l["status"] == "DENIED" for l in lines):
        claim["status"] = "DENIED"
    else:
        claim["status"] = "ADJUDICATED"
        mutate_record(accumulator)
    mutate_record(claim)
