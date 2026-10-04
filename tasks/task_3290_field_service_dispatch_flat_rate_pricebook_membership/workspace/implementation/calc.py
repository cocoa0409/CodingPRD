"""The calculations of PRD section 3, implemented literally.

Money is integer cents and every division is rounded once, half up, at the point
the money value is materialised (PRD 2.8).
"""

import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_DOWN

import store
from constants import (clock, WINDOW_DAYS, BOUNDARY_MEETS_CENTS,
                       BOUNDARY_EXCEEDS_CENTS, BOUNDARY_OUTSTANDING_CENTS,
                       INCENTIVE_TIER1_UPPER_CENTS, INCENTIVE_TIER2_UPPER_CENTS,
                       INCENTIVE_RATE_T1, INCENTIVE_RATE_T2, INCENTIVE_RATE_T3,
                       GROSS_CAP_CENTS, STRIKE_CHARGE_CENTS,
                       PAY_TIER1_UPPER_CENTS, PAY_TIER2_UPPER_CENTS,
                       PAY_RATE_T1, PAY_RATE_T2, PAY_RATE_T3,
                       AUTHORIZATION_CEILING_MULTIPLE, OVERRIDE_MARKUP,
                       OVERRIDE_HEADROOM, DISCOUNT_FLOOR_PCT,
                       MIN_DESCRIPTION_WORDS, WORDS_PER_MINUTE_FRACTION,
                       CONVERSION_SCALE, LOAD_BUCKET1_MAX_EXCLUSIVE,
                       LOAD_BUCKET2_MAX_EXCLUSIVE, LOAD_INCREMENT_BUCKET1,
                       LOAD_INCREMENT_BUCKET2, LOAD_INCREMENT_BUCKET3,
                       APPLIANCE_NUMERATOR, DEFAULT_NUMERATOR,
                       DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)


# ------------------------------------------------------------- primitives
def visible(mapping):
    return [r for r in mapping.values() if not r.get("__deleted")]


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def half_up_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_of(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def as_float(value):
    return float(dec(value))


# ------------------------------------------------------- computed rollups
def branch_capacity_consumed(branch_id):
    total = Decimal("0")
    for appt in visible(store.appointments):
        if appt["branch_id"] != branch_id:
            continue
        if appt["status"] in ("SCHEDULED", "DISPATCHED"):
            total += hours_of(appointment_estimated_hours(appt["id"]))
    return as_float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def branch_membership_count(branch_id):
    return sum(1 for a in visible(store.membership_agreements)
               if a["branch_id"] == branch_id and a["status"] == "ACTIVE")


def technician_scheduled_hours(technician_id):
    total = Decimal("0")
    for appt in visible(store.appointments):
        if appt.get("technician_id") != technician_id:
            continue
        if appt["status"] == "SCHEDULED":
            total += hours_of(appointment_estimated_hours(appt["id"]))
    return as_float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def technician_dispatched_hours(technician_id):
    total = Decimal("0")
    for appt in visible(store.appointments):
        if appt.get("technician_id") != technician_id:
            continue
        if appt["dispatch_status"] == "DISPATCHED":
            total += hours_of(appointment_estimated_hours(appt["id"]))
    return as_float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ledger_entries(technician_id):
    return sorted((e for e in visible(store.revenue_ledger_entries)
                   if e["technician_id"] == technician_id),
                  key=lambda e: (e["recorded_at_utc"], e["created_at"], e["id"]))


def ledger_total(technician_id):
    return sum(e["amount_cents"] for e in ledger_entries(technician_id))


def ledger_window_sum(technician_id, window_start, window_end):
    total = 0
    for entry in ledger_entries(technician_id):
        if entry["recorded_at_utc"] > window_start and entry["recorded_at_utc"] <= window_end:
            total += entry["amount_cents"]
    return total


def technician_performance_review(technician_id):
    from datetime import timedelta
    window_end = clock.now()
    window_start = window_end - timedelta(days=WINDOW_DAYS)
    window_sum = ledger_window_sum(technician_id, window_start, window_end)
    if window_sum < BOUNDARY_MEETS_CENTS:
        grade = "DOES_NOT_MEET"
    elif window_sum < BOUNDARY_EXCEEDS_CENTS:
        grade = "MEETS"
    elif window_sum <= BOUNDARY_OUTSTANDING_CENTS:
        grade = "EXCEEDS"
    else:
        grade = "OUTSTANDING"
    return {
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "window_revenue_cents": window_sum,
        "grade": grade,
    }


# -------------------------------------------------------- appointment maths
def appointment_lines(appointment_id):
    return [ln for ln in visible(store.appointment_lines)
            if ln["appointment_id"] == appointment_id]


def published_lines(appointment_id):
    out = []
    for line in appointment_lines(appointment_id):
        task = store.pricebook_tasks.get(line["pricebook_task_id"])
        if task is not None and not task.get("__deleted") and task["status"] == "PUBLISHED":
            out.append((line, task))
    return out


def appointment_estimated_hours(appointment_id):
    total = Decimal("0")
    for _line, task in published_lines(appointment_id):
        total += hours_of(task["estimated_hours"])
    return as_float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def appointment_labor_base(appointment_id):
    return sum(ln["flat_rate_cents"] for ln in appointment_lines(appointment_id)
               if ln["status"] == "SOLD")


def appointment_sold_price(appointment_id):
    return sum(line_sold_price(ln) for ln in appointment_lines(appointment_id)
               if ln["status"] == "SOLD")


def line_sold_price(line):
    task = store.pricebook_tasks.get(line["pricebook_task_id"])
    tier = line.get("option_tier")
    if tier and task is not None:
        for opt in (task.get("options") or []):
            if opt.get("tier") == tier:
                return int(opt.get("price_cents") or 0)
    return line["flat_rate_cents"]


def current_pricebook_version_id(appointment_id):
    best = None
    for line in appointment_lines(appointment_id):
        task = store.pricebook_tasks.get(line["pricebook_task_id"])
        if task is None:
            continue
        if best is None or int(task["revision"]) > int(best["revision"]):
            best = task
    return best["id"] if best else None


def selected_revision(code):
    """pricebook_revision_selection (PRD 3.2)."""
    pool = [t for t in visible(store.pricebook_tasks)
            if t["code"] == code and t["status"] == "PUBLISHED"]
    if not pool:
        return None
    pool.sort(key=lambda t: (-int(t["revision"]),
                             t["published_at_utc"] or t["created_at"],
                             t["created_at"]))
    return pool[0]


def has_newer_published_revision(appointment_id):
    """The reprice precondition: the pricebook has genuinely moved."""
    for line in appointment_lines(appointment_id):
        task = store.pricebook_tasks.get(line["pricebook_task_id"])
        if task is None:
            continue
        newer = [t for t in visible(store.pricebook_tasks)
                 if t["code"] == task["code"]
                 and t["status"] == "PUBLISHED"
                 and int(t["revision"]) > int(task["revision"])]
        if newer:
            return True
    return False


def household_load_trace(appointment_id):
    """household_load_propagation (PRD 3.4) — the bucket is read pre-increment."""
    pairs = published_lines(appointment_id)
    ordered = []
    for line, task in pairs:
        seq = store.LINE_ADD_SEQ.get(line["id"], 0)
        ordered.append((seq, task["code"], task["category"]))
    ordered.sort(key=lambda item: (item[0], item[1]))
    trace = []
    running = 0
    for _seq, _code, category in ordered:
        if running < LOAD_BUCKET1_MAX_EXCLUSIVE:
            increment = LOAD_INCREMENT_BUCKET1
        elif running < LOAD_BUCKET2_MAX_EXCLUSIVE:
            increment = LOAD_INCREMENT_BUCKET2
        else:
            increment = LOAD_INCREMENT_BUCKET3
        numerator = APPLIANCE_NUMERATOR if category == "APPLIANCE" else DEFAULT_NUMERATOR
        running = running + (increment * numerator) // 100
        trace.append(running)
    return trace


def invoice_discount_pct(appointment):
    """Half the linked plan's labour discount when the agreement is ACTIVE."""
    agreement_id = appointment.get("membership_agreement_id")
    if not agreement_id:
        return Decimal("0")
    agreement = store.membership_agreements.get(agreement_id)
    if agreement is None or agreement.get("__deleted") or agreement["status"] != "ACTIVE":
        return Decimal("0")
    plan = store.membership_plans.get(agreement["membership_plan_id"])
    if plan is None:
        return Decimal("0")
    return dec(plan["included_labor_discount_pct"]) / Decimal("2")


def cubic_quote(labor_base_cents, discount_pct):
    amount = dec(labor_base_cents) * (Decimal("1") - dec(discount_pct))
    return half_up_int(amount)


def authorization_required_for(quoted_price_cents, labor_base_cents):
    return dec(quoted_price_cents) > dec(AUTHORIZATION_CEILING_MULTIPLE) * dec(labor_base_cents)


def max_approved_price(labor_base_cents):
    """Truncated, not rounded (PRD 3.6)."""
    ceiling = dec(labor_base_cents) * dec(OVERRIDE_MARKUP) * dec(OVERRIDE_HEADROOM)
    return int(ceiling.to_integral_value(rounding="ROUND_FLOOR"))


def effective_discount_pct(appointment_id, quoted_price_cents):
    denominator = appointment_labor_base(appointment_id)
    if denominator == 0:
        return Decimal("0")
    return (dec(denominator) - dec(quoted_price_cents)) / dec(denominator)


def discount_floor_breached(appointment_id, quoted_price_cents):
    return effective_discount_pct(appointment_id, quoted_price_cents) > dec(DISCOUNT_FLOOR_PCT)


def required_description_words(estimated_hours):
    minutes = dec(estimated_hours) * Decimal("60")
    words = int(math.ceil(minutes * dec(WORDS_PER_MINUTE_FRACTION)))
    return max(MIN_DESCRIPTION_WORDS, words)


def supplied_description_words(payload):
    text = payload.get("completion_description")
    if text is None or not isinstance(text, str) or text.strip() == "":
        return 0
    return len(text.split())


# --------------------------------------------------------- membership maths
def agreement_visits(agreement_id):
    return sorted((v for v in visible(store.membership_visits)
                   if v["membership_agreement_id"] == agreement_id),
                  key=lambda v: (int(v["sequence_number"]), v["created_at"], v["id"]))


def visits_fulfilled_count(agreement_id):
    return sum(1 for v in visible(store.membership_visits)
               if v["membership_agreement_id"] == agreement_id
               and v["status"] == "COMPLETED")


def visit_bucket_total(agreement):
    plan = store.membership_plans.get(agreement["membership_plan_id"])
    if plan is None:
        return 0
    return int(plan["included_service_visit_count"]) * int(agreement["term_months"]) // 12


def deferred_revenue_waterfall(agreement_id):
    """deferred_revenue_recognition_waterfall (PRD 3.8)."""
    agreement = store.membership_agreements.get(agreement_id)
    if agreement is None:
        return
    total_buckets = visit_bucket_total(agreement)
    visits = agreement_visits(agreement_id)
    if not visits:
        return
    if total_buckets <= 0:
        base, remainder = 0, 0
    else:
        base = int(agreement["annual_price_cents"]) // total_buckets
        remainder = int(agreement["annual_price_cents"]) - base * total_buckets
    for index, visit in enumerate(visits):
        visit["deferred_revenue_cents"] = base + 1 if index < remainder else base


def membership_revenue_recognition(agreement_id, variant=None):
    """Two denominators; the base counts MISSED visits (PRD 3.8)."""
    agreement = store.membership_agreements.get(agreement_id)
    if agreement is None:
        return 0
    rows = [v for v in visible(store.membership_visits)
            if v["membership_agreement_id"] == agreement_id
            and v["status"] in ("SCHEDULED", "MISSED", "COMPLETED")]
    completed = sum(1 for v in rows if v["status"] == "COMPLETED")
    if variant is None:
        denominator = len(rows)
    elif variant in ("BASE", "base", "owed_including_missed"):
        denominator = len(rows)
    else:
        denominator = sum(1 for v in rows if v["status"] in ("SCHEDULED", "COMPLETED"))
    if denominator == 0:
        return 0
    return half_up_int(dec(agreement["annual_price_cents"]) * completed / denominator)


def apply_revenue_recognition(agreement_id, variant=None):
    agreement = store.membership_agreements.get(agreement_id)
    if agreement is None:
        return
    recognized = membership_revenue_recognition(agreement_id, variant)
    agreement["revenue_recognized_cents"] = recognized
    agreement["unearned_revenue_balance_cents"] = int(agreement["annual_price_cents"]) - recognized


def refund_amount_cents(x):
    """Evaluated against the real membership_revenue_recognition formula."""
    return membership_revenue_recognition(x)


# ------------------------------------------------------------ marketing
def attribution_variant_slug(variant):
    if variant is None:
        return "chronological_created_at"
    text = str(variant).strip().lower().replace("-", "_")
    if "waterfall" in text:
        return "visit_completion_waterfall"
    return "chronological_created_at"


def _visit_completed_for(appointment):
    agreement_id = appointment.get("membership_agreement_id")
    if not agreement_id:
        return None
    sequence = appointment.get("membership_visit_sequence_number")
    if sequence is None:
        return False
    for visit in visible(store.membership_visits):
        if (visit["membership_agreement_id"] == agreement_id
                and int(visit["sequence_number"]) == int(sequence)):
            return visit["status"] == "COMPLETED"
    return False


def campaign_attribution(campaign_id, slug="chronological_created_at"):
    campaign = store.campaigns.get(campaign_id)
    spend = int(campaign["spend_cents"]) if campaign else 0
    booked = [a for a in visible(store.appointments) if a.get("campaign_id") == campaign_id]
    booked.sort(key=lambda a: (a["created_at"], a["window_start_utc"]))
    if slug == "visit_completion_waterfall":
        booked = list(reversed(booked))
        kept = []
        for appointment in booked:
            covered = _visit_completed_for(appointment)
            if covered is None or covered:
                kept.append(appointment)
        booked = kept
    count = len(booked)
    revenue = 0
    for appointment in booked:
        if appointment["status"] == "COMPLETED":
            revenue += appointment_sold_price(appointment["id"])
    cac = half_up_int(dec(spend) / count) if count > 0 else 0
    return {
        "attributed_job_count": count,
        "attributed_revenue_cents": revenue,
        "cac_cents": cac,
    }


def marketing_attribution_denominator(numerator):
    """Denominator spans the whole tenant population (PRD 3.12)."""
    population = set()
    for appointment in visible(store.appointments):
        if appointment.get("campaign_id"):
            population.add(appointment["campaign_id"])
    for call in visible(store.call_records):
        if call.get("campaign_id"):
            population.add(call["campaign_id"])
    denominator = len(population)
    if numerator == 0:
        return 0.0
    if denominator == 0:
        return 0.0
    if numerator == denominator:
        return 1.0
    ratio = (dec(numerator) / dec(denominator)).quantize(
        Decimal("1." + "0" * CONVERSION_SCALE), rounding=ROUND_HALF_DOWN)
    return float(ratio)


# ------------------------------------------------------------ incentive pay
def incentive_statement(technician):
    gross = 0
    for appointment in visible(store.appointments):
        if appointment.get("technician_id") != technician["id"]:
            continue
        if appointment["status"] != "COMPLETED":
            continue
        base = appointment_sold_price(appointment["id"])
        if base < INCENTIVE_TIER1_UPPER_CENTS:
            rate = dec(INCENTIVE_RATE_T1)
        elif base < INCENTIVE_TIER2_UPPER_CENTS:
            rate = dec(INCENTIVE_RATE_T2)
        else:
            rate = dec(INCENTIVE_RATE_T3)
        gross += half_up_int(dec(base) * rate)
    clamped = min(gross, GROSS_CAP_CENTS)
    charge = STRIKE_CHARGE_CENTS * int(technician["sales_coaching_strike_count"])
    figure = clamped - charge
    if figure < 0:
        rate = Decimal("0")
    elif figure <= PAY_TIER1_UPPER_CENTS:
        rate = dec(PAY_RATE_T1)
    elif figure <= PAY_TIER2_UPPER_CENTS:
        rate = dec(PAY_RATE_T2)
    else:
        rate = dec(PAY_RATE_T3)
    incentive = half_up_int(dec(figure) * rate)
    return {
        "gross_component_cents": gross,
        "clamped_component_cents": clamped,
        "charge_cents": charge,
        "incentive_cents": incentive,
    }


# ------------------------------------------------------- settlement balance
def appointment_settlement(appointment, variant=None):
    sold = appointment_sold_price(appointment["id"])
    collected = 0
    discount = Decimal("0")
    agreement_id = appointment.get("membership_agreement_id")
    if agreement_id:
        agreement = store.membership_agreements.get(agreement_id)
        if agreement is not None and not agreement.get("__deleted"):
            collected = int(agreement["collected_amount_cents"])
            plan = store.membership_plans.get(agreement["membership_plan_id"])
            if plan is not None:
                discount = dec(plan["included_labor_discount_pct"])
    outstanding = sold - half_up_int(dec(sold) * discount / Decimal("2")) - collected
    covered = _visit_completed_for(appointment)
    agreement_covered = 0 if covered else sold
    return {
        "sold_price_cents": sold,
        "collected_amount_cents": collected,
        "appointment_outstanding_cents": outstanding,
        "agreement_covered_cents": agreement_covered,
    }