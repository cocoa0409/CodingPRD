"""Derived calculations: tube plans, necessity, fasting gate, wait estimate,
patient responsibility estimates, courier selection, rejection counting."""

import hashlib
from datetime import date, datetime, timedelta, timezone

from core import (
    db, cents, parse_iso, get_clock, local_minute_of_day, local_calendar_day,
    TUBE_PANEL_PROVIDER, ATTENDED_COLLECTED_RATE, PEDIATRIC_FEE_MULTIPLIER,
    EXPIRED_PLAN_DISCOUNT_PCT, STABILITY_FACTOR, COURIER_CHECKIN_LEAD_MINUTES,
    COURIER_WINDOW_MINUTES, COURIER_COMMIT_LEAD_MINUTES, BAND_IMMEDIATE_MAX,
    BAND_WITHIN_WINDOW_MAX,
)


# ---------------------------------------------------------------------------
# Patients / orders
# ---------------------------------------------------------------------------
def is_pediatric(patient, clock=None):
    """True when clock is strictly before birth_date + a bare 18-year offset."""
    clock = clock or get_clock()
    birth = patient.get("birth_date")
    if not birth:
        return False
    try:
        y, m, d = (int(x) for x in str(birth)[:10].split("-"))
        bdt = date(y, m, d)
    except Exception:
        return False
    try:
        shifted = bdt.replace(year=bdt.year + 18)
    except ValueError:
        shifted = bdt.replace(year=bdt.year + 18, day=28)
    # Pediatric through and including the 18th birthday; non-pediatric the
    # next calendar day. A 2008-09-01 birth is PEDIATRIC on 2026-09-01 and
    # non-pediatric on 2026-09-02.
    return clock.date() <= shifted


def recompute_order_pediatric(order):
    patient = db.patients.get(order["patient_id"])
    if patient is None:
        return
    order["patient_is_pediatric"] = is_pediatric(patient)


def order_for_appointment(appt):
    return db.test_orders.get(appt["test_order_id"])


def appointment_for_order(order_id, active_only=False):
    appts = [a for a in db.appointments.values() if a["test_order_id"] == order_id]
    appts.sort(key=lambda a: a["created_at"])  # id is never consulted
    if active_only:
        for a in appts:
            if a["draw_state"] not in ("DRAWN", "RESCHEDULED", "NO_SHOW"):
                return a
        return None
    return appts[-1] if appts else None


# ---------------------------------------------------------------------------
# Tube resolution (collection_tube_plan)
# ---------------------------------------------------------------------------
def panel_chain(panel):
    """Walk the panel ancestry graph from the ordered panel up to the root."""
    chain = []
    seen = set()
    cur = panel
    while cur is not None and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = TUBE_PANEL_PROVIDER.get(cur)
    return chain


def gtt_rows():
    """GTT resolves through a sodium-fluoride-gray provider."""
    out = []
    for r in db.tube_requirements.values():
        if r["tube_code"] == "SODIUM_FLUORIDE_GRAY":
            out.append(r)
    return out


def rows_for_chain(panel):
    chain = panel_chain(panel)
    rows = []
    if panel == "GTT":
        return gtt_rows()
    for label in chain:
        rows.extend(r for r in db.tube_requirements.values()
                    if r["test_panel"] == label)
    return rows


def resolve_tubes(order):
    """Topological walk collecting TubeRequirement rows, deduplicated by tube_code."""
    rows = rows_for_chain(order["test_panel"])
    best = {}
    for r in rows:
        tc = r["tube_code"]
        cur = best.get(tc)
        if cur is None:
            best[tc] = r
            continue
        new_key = (r["order_of_draw"], r["created_at"])
        cur_key = (cur["order_of_draw"], cur["created_at"])
        if new_key < cur_key:
            best[tc] = r
    return sorted(best.values(),
                  key=lambda r: (r["order_of_draw"], r["created_at"]))


def handling_for(order):
    handling = set()
    for r in resolve_tubes(order):
        for c in (r.get("special_handling_codes") or []):
            handling.add(c)
    return sorted(handling)


def recompute_order_plan(order):
    resolved = resolve_tubes(order)
    order["resolved_tubes"] = [r["tube_code"] for r in resolved]
    order["draw_order_spec"] = [
        {"tube_code": r["tube_code"], "order_of_draw": r["order_of_draw"]}
        for r in resolved
    ]
    order["concurrence_hash"] = compute_concurrence_hash(
        order["test_panel"], sorted(order["resolved_tubes"]), handling_for(order))


def compute_concurrence_hash(panel, tube_codes, handling):
    payload = "|".join([panel, ",".join(tube_codes), ",".join(handling)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def requirement_by_pair(panel, tube_code):
    for r in db.tube_requirements.values():
        if r["test_panel"] == panel and r["tube_code"] == tube_code:
            return r
    return None


def requirement_for(specimen):
    """Resolve the TubeRequirement row for a specimen via the order's tube plan."""
    order = db.test_orders.get(specimen.get("test_order_id"))
    if order is None:
        return None
    for r in resolve_tubes(order):
        if r["tube_code"] == specimen["tube_code"]:
            return r
    return requirement_by_pair(order["test_panel"], specimen["tube_code"])


# ---------------------------------------------------------------------------
# Necessity
# ---------------------------------------------------------------------------
def recompute_necessity(order):
    codes = order.get("icd10_codes") or []
    if not codes:
        order["necessity_status"] = "PASS"
        return order["necessity_status"]
    panel = order["test_panel"]
    matched = [r for r in db.necessity_rules.values()
               if r["test_panel"] == panel and r["icd10_code"] in codes]
    if not matched:
        order["necessity_status"] = "PENDING"
    elif any(r["is_covered"] for r in matched):
        order["necessity_status"] = "PASS"
    else:
        order["necessity_status"] = "FAIL"
    return order["necessity_status"]


# ---------------------------------------------------------------------------
# Fasting
# ---------------------------------------------------------------------------
def fasting_deadline_for(order):
    # The deadline is fixed at intake and only a rejection recomputes it
    # (PRD §3.8); `_fasting_pinned_bl` carries the pinned instant.
    if "_fasting_pinned_bl" in order:
        pin = order.get("_fasting_pinned_bl")
        return parse_iso(pin) if pin else None
    if not order.get("is_fasting_required"):
        return None
    last = order.get("patient_last_food_utc")
    if last is None:
        return None
    return parse_iso(last) + timedelta(hours=int(order.get("fasting_hours_required") or 0))


def fasting_overdue_order(order):
    dl = fasting_deadline_for(order)
    if dl is None:
        return False
    return get_clock() > dl


def appointment_fasting_deadline(appt, order):
    pinned = appt.get("_pinned_fasting_deadline")
    if pinned:
        return parse_iso(pinned)
    return fasting_deadline_for(order)


def appointment_fasting_overdue(appt, order):
    dl = appointment_fasting_deadline(appt, order)
    if dl is None:
        return False
    return get_clock() > dl


def fasting_gate(order, served_at):
    if not order.get("is_fasting_required"):
        return "PASS"
    dl = fasting_deadline_for(order)
    if dl is None:
        return "PASS"
    return "PASS" if served_at <= dl else "FAIL"


# ---------------------------------------------------------------------------
# Complexity / wait estimate
# ---------------------------------------------------------------------------
def base_score(mode):
    return 15 if mode in ("PEDIATRIC", "DIFFICULT_DRAW") else 10


def heap_flag(created_at_iso, center):
    dt = parse_iso(created_at_iso)
    return 1 if (local_minute_of_day(dt, center) // 30) % 3 == 0 else 0


def compute_complexity_score(appt, order, center):
    return base_score(order["collection_mode"]) + \
        (5 if heap_flag(appt["created_at"], center) else 0)


def credentialed_for(mode):
    if mode in ("SELF_SERVICE", "STANDARD"):
        return None  # every credential qualifies
    if mode == "PEDIATRIC":
        return {"PBT_PEDIATRIC", "RN"}
    if mode == "DIFFICULT_DRAW":
        return {"RN"}
    return None


def staff_covers(phleb, mode):
    allowed = credentialed_for(mode)
    return True if allowed is None else phleb["credential"] in allowed


def resolving_staff(center_id, mode):
    return [p for p in db.phlebotomists.values()
            if p["service_center_id"] == center_id
            and p["status"] == "ON_DUTY" and staff_covers(p, mode)]


def expected_wait(appt):
    order = order_for_appointment(appt)
    center = db.service_centers[appt["service_center_id"]]
    mode = order["collection_mode"] if order else "STANDARD"
    instantaneous = appt["queue_state"] == "WAITING"

    if instantaneous:
        read_score = 0
    else:
        read_score = compute_complexity_score(appt, order, center)

    ahead = 0
    for other in db.appointments.values():
        if other["service_center_id"] != appt["service_center_id"]:
            continue
        if other["id"] == appt["id"] or other["queue_state"] != "WAITING":
            continue
        if other["created_at"] >= appt["created_at"]:
            continue
        oorder = order_for_appointment(other)
        if oorder is None:
            continue
        oscore = 0 if instantaneous else compute_complexity_score(other, oorder, center)
        if instantaneous:
            # PRD §3.3: every row's score collapses to zero, so every earlier
            # waiting row compares equal and contributes a weight of 2.
            ahead += 2
        elif oscore > read_score:
            # PRD §3.3 blend-rate paragraph: "scores are live again, so an
            # earlier row whose score is strictly greater contributes only 1 and
            # a tie contributes 2, and the resulting figure is strictly smaller."
            # The PRD's own worked example — six earlier rows and one resolving
            # nurse giving 12 instantaneous and 9 blended — fixes this reversed
            # mapping against the general 3/2/1 ladder.
            ahead += 1
        elif oscore == read_score:
            # PRD §3.3: 2 when the two scores are equal.
            ahead += 2
        else:
            # A row ranked below the reading row is the complement of the blend
            # mapping, keeping the blend reading strictly below the instantaneous.
            ahead += 3

    staff = resolving_staff(appt["service_center_id"], mode)
    a = (-(-ahead // len(staff))) if staff else 999

    # PRD §3.3: the second quantity is "simply the number of phlebotomists on
    # duty at the center — equivalently, the center's `staffed_minutes_available`
    # divided by 15 — and it is the roster capacity term, maintained by the
    # operations checkpoint of §3.9 rather than derived from any single roster
    # edit." The persisted scalar therefore wins wherever a checkpoint has run,
    # so a just-retired phlebotomist moves term (a) immediately and term (b)
    # only after the next operations pass. Before the first pass the scalar is
    # still its 0 default, so the live on-duty count stands in for it.
    if center.get("ops_run_index", 0) > 0:
        b = center.get("staffed_minutes_available", 0) // 15
    else:
        b = len([p for p in db.phlebotomists.values()
                 if p["service_center_id"] == appt["service_center_id"]
                 and p["status"] == "ON_DUTY"])

    wait = max(a, b)
    if wait <= BAND_IMMEDIATE_MAX:
        band = "IMMEDIATE"
    elif wait <= BAND_WITHIN_WINDOW_MAX:
        band = "WITHIN_WINDOW"
    else:
        band = "EXTENDED"
    return wait, band


# ---------------------------------------------------------------------------
# Responsibility estimates
# ---------------------------------------------------------------------------
def self_pay_rate(order):
    rate = float(int(order.get("list_price_cents", 5000)))
    if order["collection_mode"] in ("PEDIATRIC", "DIFFICULT_DRAW"):
        rate = float(cents(rate * PEDIATRIC_FEE_MULTIPLIER))
    plan = db.insurance_plans.get(order.get("insurance_plan_id"))
    if plan is None:
        return rate
    if order.get("insurance_status") == "ELIGIBLE" and plan["status"] == "ACTIVE":
        rate = min(rate, float(int(plan["allowed_amount_cents"])))
    if plan["status"] == "TERMINATED":
        rate = max(rate, float(int(plan["allowed_amount_cents"])))
    return rate


def compute_estimate(order, variant):
    if variant == "PROVISIONAL_ELIGIBLE":
        return {"copay_component_cents": 0, "coinsurance_component_cents": 0,
                "deductible_component_cents": 0, "gross_cents": 0,
                "discount_cents": 0, "net_patient_cents": 0}

    plan = db.insurance_plans.get(order.get("insurance_plan_id"))
    rate = self_pay_rate(order)
    pct = EXPIRED_PLAN_DISCOUNT_PCT if order.get("insurance_status") == "EXPIRED" else 0.0
    per_visit_fee = cents(rate * pct)

    copay_c = coins_c = deduct_c = 0
    if variant == "ATTENDED_COLLECTED":
        if plan is not None:
            allowed = float(int(plan["allowed_amount_cents"]))
            copay = float(int(plan["copay_cents"]))
            coins_pct = float(plan.get("coinsurance_pct") or 0.0)
            prior = float(plan.get("prior_paid_pct") or 0.0)
            ded_rem = float(int(plan.get("deductible_remaining_cents") or 0))
            copay_c = cents(copay * 1.0)
            coins_c = cents(allowed * coins_pct * (1 - prior))
            deduct_c = cents(min(ded_rem, max(0.0, allowed - copay) * (1 - prior)))
        gross = copay_c + coins_c + deduct_c
        discount = cents(gross * ATTENDED_COLLECTED_RATE + per_visit_fee)
        net = gross - discount - per_visit_fee
    else:  # SELF_PAY_LIST
        gross = cents(rate)
        discount = per_visit_fee
        net = gross - discount

    return {"copay_component_cents": copay_c, "coinsurance_component_cents": coins_c,
            "deductible_component_cents": deduct_c, "gross_cents": gross,
            "discount_cents": discount, "net_patient_cents": net}


def weighted_blend_cents(order):
    plan = db.insurance_plans.get(order.get("insurance_plan_id"))
    self_pay_part = float(int(order.get("list_price_cents", 5000)))
    if plan is None:
        return self_pay_part
    copay = float(int(plan["copay_cents"]))
    allowed = float(int(plan["allowed_amount_cents"]))
    coins_pct = float(plan.get("coinsurance_pct") or 0.0)
    prior = float(plan.get("prior_paid_pct") or 0.0)
    ded_rem = float(int(plan.get("deductible_remaining_cents") or 0))
    copay_part = copay * 1.0
    coins_part = allowed * coins_pct * (1 - prior)
    ded_part = min(ded_rem, (allowed - copay) * (1 - prior)) * 1.0
    return copay_part + coins_part + ded_part + self_pay_part


def apply_estimate_to_order(order, result):
    order["patient_responsibility_cents"] = result["net_patient_cents"]
    order["self_pay_discount_cents"] = result["gross_cents"] - result["net_patient_cents"]
    order["balance_remaining_cents"] = max(
        0, order["patient_responsibility_cents"] - order.get("prepay_collected_cents", 0))


# ---------------------------------------------------------------------------
# Courier selection and specimen stability
# ---------------------------------------------------------------------------
def specimen_stability_deadline(specimen):
    row = requirement_for(specimen)
    if row is None:
        return None
    mins = STABILITY_FACTOR * float(row["stability_minutes"])
    return parse_iso(specimen["collected_utc"]) + timedelta(minutes=mins)


def select_courier_run(order):
    appt = appointment_for_order(order["id"], active_only=True)
    if appt is None or not appt.get("checkin_utc"):
        return None
    checkin = parse_iso(appt["checkin_utc"])
    start = parse_iso(appt["scheduled_start_utc"])
    if start < checkin + timedelta(minutes=COURIER_CHECKIN_LEAD_MINUTES):
        return None
    if start >= checkin + timedelta(
            minutes=COURIER_CHECKIN_LEAD_MINUTES + COURIER_WINDOW_MINUTES):
        return None
    lo = checkin + timedelta(minutes=COURIER_COMMIT_LEAD_MINUTES)
    hi = lo + timedelta(minutes=60)
    for run in db.courier_runs.values():
        if run["service_center_id"] != order["service_center_id"]:
            continue
        if run["direction"] != "OUTBOUND" or run["status"] != "PLANNED":
            continue
        if lo <= parse_iso(run["dispatch_utc"]) < hi:
            return run
    return None


# ---------------------------------------------------------------------------
# Rejection counting
# ---------------------------------------------------------------------------
def collection_local_day(specimen, center):
    return local_calendar_day(parse_iso(specimen["collected_utc"]), center)


def rejection_day_index(order, center):
    """Count REJECTED specimens of this order on the current local day."""
    clock_day = local_calendar_day(get_clock(), center)
    count = 0
    for s in db.specimens.values():
        if s["test_order_id"] != order["id"] or s["status"] != "REJECTED":
            continue
        if collection_local_day(s, center) == clock_day:
            count += 1
    return count


def recount_rejections(order, center, newly_rejected):
    """Append-only per-(order, collection local day) counter, recomputed in full."""
    newly_rejected["day_rejection_index"] = order.get("day_rejection_index", 0) + 1


def is_rejection_waived(order, center):
    clock_day = local_calendar_day(get_clock(), center)
    count = 0
    for s in db.specimens.values():
        if s["test_order_id"] != order["id"] or s["status"] != "REJECTED":
            continue
        if collection_local_day(s, center) == clock_day:
            count += 1
    return count >= order.get("day_rejection_cap", 3)