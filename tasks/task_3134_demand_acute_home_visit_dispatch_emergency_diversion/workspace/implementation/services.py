"""Business logic services: acuity scoring, selector policy, claim totals, cascades, system sweeps."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import helpers as H
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_VR_INVALID_STATE, ERR_TRIAGE_ALREADY_EXISTS,
    ERR_RED_FLAG_REQUIRES_EMS, ERR_ACUITY_TOO_HIGH_FOR_DECLINE,
    ERR_ACUITY_TOO_LOW_FOR_DIVERSION, ERR_MARKET_INACTIVE, ERR_OUT_OF_COVERAGE,
    ERR_NO_AVAILABLE_CARE_TEAM, ERR_NOT_ASSIGNED_TEAM_MEMBER, ERR_SHIFT_NOT_OPERATIONAL,
    ERR_CLAIM_INVALID_STATE, ERR_CLAIM_CAP_EXCEEDED, ERR_CONTRACT_NOT_IN_FORCE,
    ERR_STALE_VERSION, ERR_APPEAL_LIMIT_REACHED, ERR_PCP_MISMATCH,
)

NON_TERMINAL_VISIT_STATUSES = {
    "INTAKE", "TRIAGE_PENDING", "TRIAGED", "DISPATCH_PENDING", "EN_ROUTE",
    "ON_SCENE", "DISPOSITIONED", "ESCALATED_TRANSPORT",
    "CLAIM_DRAFT", "CLAIM_SUBMITTED", "CLAIM_ADJUDICATED_PAID",
    "CLAIM_ADJUDICATED_DENIED", "CLAIM_APPEALED",
}
# Per scaffold open_visit_count: INTAKE..DISPOSITIONED, CLAIM_DRAFT, CLAIM_SUBMITTED, CLAIM_APPEALED
OPEN_VISIT_STATUSES = {
    "INTAKE", "TRIAGE_PENDING", "TRIAGED", "DISPATCH_PENDING", "EN_ROUTE",
    "ON_SCENE", "DISPOSITIONED", "ESCALATED_TRANSPORT",
    "CLAIM_DRAFT", "CLAIM_SUBMITTED", "CLAIM_APPEALED",
}

RED_FLAG_FIELDS = ("is_chest_pain", "is_stroke_signs", "is_severe_trauma", "is_altered_mental_status")

SKILL_TAGS = {"POCT", "IMAGING", "IV_INFUSION", "PEDIATRIC"}

# ---------------------------------------------------------------------------
# Acuity scoring (calculations.acuity_score)
# ---------------------------------------------------------------------------

def _clamp(lo, hi, v):
    return max(lo, min(hi, v))


def compute_acuity(assessment, patient, now):
    """Return (acuity_score, band)."""
    hr = assessment["heart_rate"]
    sbp = assessment["systolic_bp"]
    spo2 = assessment["spo2_pct"]
    hr_score = _clamp(0, 25, abs(hr - 80) // 4)
    if sbp < 90 or sbp > 180:
        bp_score = 25
    else:
        bp_score = _clamp(0, 15, abs(sbp - 120) // 5)
    spo2_score = _clamp(0, 25, (95 - spo2) * 2) if spo2 < 95 else 0
    red_flag_pts = 20 * sum(1 for f in RED_FLAG_FIELDS if assessment.get(f))
    age = H.age_years(patient["date_of_birth"], now)
    if age >= 75:
        age_pts = 10
    elif age >= 65:
        age_pts = 5
    else:
        age_pts = 0
    comorb_pts = min(15, int(patient.get("comorbidity_count", 0)) * 3)
    raw = hr_score + bp_score + spo2_score + red_flag_pts + age_pts + comorb_pts
    score = _clamp(0, 100, raw)
    any_red = any(assessment.get(f) for f in RED_FLAG_FIELDS)
    # Band mapping: red-flag check FIRST, then score thresholds.
    if any_red:
        band = "EMERGENT"
    elif score >= 80:
        band = "EMERGENT"
    elif score >= 50:
        band = "URGENT"
    elif score >= 30:
        band = "STANDARD"
    else:
        band = "NON_ACUTE"
    return score, band


def red_flag_count(assessment):
    return sum(1 for f in RED_FLAG_FIELDS if assessment.get(f))


# ---------------------------------------------------------------------------
# Market / visit helpers
# ---------------------------------------------------------------------------

def decr_open_visit_count(market_id):
    market = db.STORES["markets"].get(market_id)
    if market is not None:
        market["open_visit_count"] = market.get("open_visit_count", 0) - 1
        H.touch(market)


def triage_for_visit(vr_id):
    for t in db.STORES["triage_assessments"].values():
        if t["visit_request_id"] == vr_id:
            return t
    return None


def orders_for_encounter(enc_id):
    return [o for o in db.STORES["diagnostic_orders"].values() if o["encounter_id"] == enc_id]


def encounter_for_visit(vr_id):
    for e in db.STORES["encounters"].values():
        if e["visit_request_id"] == vr_id:
            return e
    return None


def claim_for_visit(vr_id):
    for c in db.STORES["claims"].values():
        if c["visit_request_id"] == vr_id:
            return c
    return None


def assignments_for_visit(vr_id):
    return [a for a in db.STORES["dispatch_assignments"].values()
            if a["visit_request_id"] == vr_id]


def checkins_for_visit(vr_id):
    return [c for c in db.STORES["monitoring_checkins"].values()
            if c["visit_request_id"] == vr_id]


def notices_for_visit(vr_id):
    return [n for n in db.STORES["follow_up_notices"].values()
            if n["visit_request_id"] == vr_id]


def clear_assigned_team_if_all_dead(vr):
    assigns = assignments_for_visit(vr["id"])
    if assigns and all(a["status"] in ("CANCELLED", "REJECTED") for a in assigns):
        if vr.get("assigned_care_team_id") is not None:
            vr["assigned_care_team_id"] = None
            H.touch(vr)


def decr_team_dispatch(team_id):
    team = db.STORES["care_teams"].get(team_id)
    if team is None:
        return
    team["active_dispatch_count"] = max(0, team.get("active_dispatch_count", 0) - 1)
    if team["active_dispatch_count"] == 0 and team.get("status") == "ON_DISPATCH":
        team["status"] = "AVAILABLE"
    H.touch(team)


def complete_dispatch(da_id):
    da = db.STORES["dispatch_assignments"].get(da_id)
    if da is not None and da["status"] != "COMPLETED":
        da["status"] = "COMPLETED"
        H.touch(da)
        decr_team_dispatch(da["care_team_id"])


def required_skills(vr):
    complaint = (vr.get("chief_complaint") or "").lower()
    skills = {"POCT"}
    if "injury" in complaint or "fall" in complaint:
        skills.add("IMAGING")
    if "dehydrat" in complaint:
        skills.add("IV_INFUSION")
    return skills


def shift_operational(shift, now):
    if shift["status"] not in ("SCHEDULED", "ACTIVE"):
        return False
    start = H.parse_dt(shift["window_start"])
    end = H.parse_dt(shift["window_end"])
    return start <= now < end


def find_operational_shift(team_id, market_id, now):
    best = None
    for s in db.STORES["vehicle_shifts"].values():
        if (s["care_team_id"] == team_id and s["market_id"] == market_id
                and shift_operational(s, now)):
            if best is None or s["created_at"] < best["created_at"]:
                best = s
    return best


# ---------------------------------------------------------------------------
# Claim totals (calculations.site_of_service_claim_total)
# ---------------------------------------------------------------------------

def estimate_unit_price(vr, encounter, order):
    """Unit price estimate for an order: formulary for IV_INFUSION, list price otherwise."""
    if order["order_kind"] == "IV_INFUSION":
        entry = formulary_entry_for_order(vr, encounter, order["code"])
        if entry is not None:
            return entry["unit_price_cents"]
        return 0
    return list_price_for_code(order["code"])


def list_price_for_code(code):
    """Fixed price list for non-IV codes: derive a deterministic integer price."""
    h = 0
    for ch in str(code):
        h = (h * 131 + ord(ch)) % 100003
    return 200 + h


def round_half_up_cents(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _base_rate_cents(vr, contract):
    if vr.get("acuity_band") == "URGENT":
        return contract["urgent_base_rate_cents"]
    return contract["standard_base_rate_cents"]


def base_line_cents(vr, contract):
    return round_half_up_cents(Decimal(str(_base_rate_cents(vr, contract)))
                               * Decimal(str(contract["place_of_service_modifier_pct"])))


def line_amount(order):
    return round_half_up_cents(Decimal(order["units"]) * Decimal(order.get("unit_price_cents") or 0))


def compute_claim_totals(vr, contract, encounter):
    """Return (provisional_total_cents, final_total_cents, lines) where lines is a list
    of (line_kind, ref_order_id, description, amount_cents)."""
    base = base_line_cents(vr, contract)
    orders = orders_for_encounter(encounter["id"]) if encounter else []
    provisional_included = {"ORDERED", "COLLECTED", "RESULTED", "AMENDED"}
    final_included = {"RESULTED", "VERIFIED", "AMENDED"}
    prov_total = base
    fin_total = base
    lines = [("BASE_VISIT", None, "Base home visit", base)]
    for order in sorted(orders, key=lambda o: (o["created_at"], o["id"])):
        price = order.get("unit_price_cents")
        if price is None:
            price = estimate_unit_price(vr, encounter, order)
        amount = round_half_up_cents(Decimal(order["units"]) * Decimal(price))
        kind = "IV_DRUG" if order["order_kind"] == "IV_INFUSION" else "DIAGNOSTIC"
        desc = f"{order['order_kind']} {order['code']} x{order['units']}"
        if order["status"] in provisional_included or order["status"] in final_included:
            lines.append((kind, order["id"], desc, amount))
        if order["status"] in provisional_included:
            prov_total += amount
        if order["status"] in final_included:
            fin_total += amount
    return prov_total, fin_total, lines


def sync_claim_lines(claim, vr, contract, encounter):
    """Regenerate the claim's lines to match current totals."""
    prov, fin, lines = compute_claim_totals(vr, contract, encounter)
    claim["provisional_total_cents"] = prov
    claim["final_total_cents"] = fin
    # Drop existing lines and recreate
    for lid in [lid for lid, l in db.STORES["claim_lines"].items() if l["claim_id"] == claim["id"]]:
        del db.STORES["claim_lines"][lid]
    for kind, ref, desc, amount in lines:
        line = H.new_entity()
        line.update({
            "claim_id": claim["id"],
            "line_kind": kind,
            "ref_diagnostic_order_id": ref,
            "description": desc,
            "amount_cents": amount,
        })
        db.STORES["claim_lines"][line["id"]] = line
    H.touch(claim)


def recompute_claim_for_visit(vr_id):
    vr = db.STORES["visit_requests"].get(vr_id)
    if vr is None or not vr.get("claim_id"):
        return
    claim = db.STORES["claims"].get(vr["claim_id"])
    if claim is None or claim["status"] != "DRAFT":
        return
    contract = db.STORES["payer_contracts"].get(claim["payer_contract_id"])
    encounter = encounter_for_visit(vr_id)
    if contract is None:
        return
    sync_claim_lines(claim, vr, contract, encounter)


def resolve_payer_contract(patient, vr):
    """Contract for patient's payer_code + visit's market; latest created wins."""
    best = None
    for c in db.STORES["payer_contracts"].values():
        if c["payer_code"] == patient["payer_code"] and c["market_id"] == vr["market_id"]:
            if best is None or c["created_at"] > best["created_at"]:
                best = c
    return best


def formulary_entry_for_order(vr, encounter, drug_code):
    """Formulary entry for the drug code under the contract applicable to this visit."""
    patient = db.STORES["patients"].get(vr["patient_id"])
    if patient is None:
        return None
    contract = resolve_payer_contract(patient, vr)
    if contract is None:
        return None
    for e in db.STORES["formulary_entries"].values():
        if e["payer_contract_id"] == contract["id"] and e["drug_code"] == drug_code:
            return e
    return None


# ---------------------------------------------------------------------------
# Readmission risk score (calculation; computed, stored on visit)
# ---------------------------------------------------------------------------

def compute_readmission_risk(vr, encounter, disposition):
    patient = db.STORES["patients"].get(vr["patient_id"])
    now = H.logical_now()
    score = 0
    if vr.get("acuity_band") == "URGENT":
        score += 30
    if patient is not None and int(patient.get("comorbidity_count", 0)) >= 3:
        score += 25
    orders = orders_for_encounter(encounter["id"]) if encounter else []
    if any(o["order_kind"] == "IV_INFUSION" and o["status"] in ("RESULTED", "VERIFIED")
           for o in orders):
        score += 20
    if disposition == "ESCALATE_TO_FACILITY":
        score += 25
    if patient is not None:
        age = H.age_years(patient["date_of_birth"], now)
        if age >= 75:
            score += 15
    if any(c["status"] == "MISSED" for c in checkins_for_visit(vr["id"])):
        score += 10
    score = _clamp(0, 100, score)
    if score >= 60:
        tier = "HIGH"
    elif score >= 30:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return score, tier


# ---------------------------------------------------------------------------
# Disposition cascade (ON_SCENE -> DISPOSITIONED / ESCALATED_TRANSPORT)
# ---------------------------------------------------------------------------

def auto_advance_dispositioned(vr):
    """DISPOSITIONED -> CLAIM_DRAFT once a DRAFT claim exists and a QUEUED notice exists."""
    if vr["status"] != "DISPOSITIONED":
        return
    claim = claim_for_visit(vr["id"])
    if claim is None or claim["status"] != "DRAFT":
        return
    if not any(n["status"] == "QUEUED" for n in notices_for_visit(vr["id"])):
        return
    vr["status"] = "CLAIM_DRAFT"
    H.touch(vr)


def schedule_monitoring_checkins(vr, ended_at):
    for hours in (24, 72):
        sched = ended_at + timedelta(hours=hours)
        row = H.new_entity()
        row.update({
            "visit_request_id": vr["id"],
            "scheduled_at": H.fmt_dt(sched),
            "completed_at": None,
            "outcome": None,
            "status": "SCHEDULED",
        })
        db.STORES["monitoring_checkins"][row["id"]] = row


def disposition_cascade(encounter, decision):
    """Run the full disposition side-effect chain. decision is the new DispositionDecision row."""
    vr = db.STORES["visit_requests"][decision["visit_request_id"]]
    now = H.logical_now()
    now_str = H.fmt_dt(now)
    encounter["ended_at"] = now_str
    if decision["disposition"] == "DISCHARGE_HOME":
        encounter["status"] = "DISCHARGED_HOME"
    else:
        encounter["status"] = "ESCALATED_TRANSPORT"
    H.touch(encounter)

    # Complete the dispatch and reconcile the team counters.
    da = db.STORES["dispatch_assignments"].get(encounter["dispatch_assignment_id"])
    if da is not None:
        complete_dispatch(da["id"])

    # Auto-create the Claim in DRAFT (partial services are billable on escalation too).
    patient = db.STORES["patients"].get(vr["patient_id"])
    contract = resolve_payer_contract(patient, vr) if patient else None
    claim = H.new_entity()
    claim.update({
        "visit_request_id": vr["id"],
        "payer_contract_id": contract["id"] if contract else None,
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "submitted_at": None,
        "adjudicated_at": None,
        "status": "DRAFT",
        "appeal_count": 0,
    })
    db.STORES["claims"][claim["id"]] = claim
    if contract is not None:
        sync_claim_lines(claim, vr, contract, encounter)

    vr["claim_id"] = claim["id"]

    if decision["disposition"] == "DISCHARGE_HOME":
        vr["status"] = "DISPOSITIONED"
        schedule_monitoring_checkins(vr, now)
    else:
        vr["status"] = "ESCALATED_TRANSPORT"
        # No monitoring schedule on escalation.

    score, tier = compute_readmission_risk(vr, encounter, decision["disposition"])
    vr["readmission_risk_score"] = score
    vr["readmission_risk_tier"] = tier
    H.touch(vr)

    if decision["disposition"] == "ESCALATE_TO_FACILITY":
        transport = H.new_entity()
        transport.update({
            "disposition_decision_id": decision["id"],
            "visit_request_id": vr["id"],
            "transport_mode": decision.get("transport_mode"),
            "dispatched_at": now_str,
            "arrived_at_facility_at": None,
            "status": "DISPATCHED",
        })
        db.STORES["facility_transports"][transport["id"]] = transport

    auto_advance_dispositioned(vr)
    return claim


# ---------------------------------------------------------------------------
# System sweeps (lazy, evaluated against the logical clock on each request)
# ---------------------------------------------------------------------------

def spawn_provider_visit(patient_id, market_id):
    vr = H.new_entity()
    vr.update({
        "patient_id": patient_id,
        "market_id": market_id,
        "requestor_role": "PROVIDER",
        "chief_complaint": "Post-visit monitoring escalation",
        "requested_at": H.logical_now_str(),
        "status": "INTAKE",
        "acuity_band": None,
        "assigned_care_team_id": None,
        "sla_deadline_at": None,
        "sla_breached": False,
        "claim_id": None,
    })
    db.STORES["visit_requests"][vr["id"]] = vr
    market = db.STORES["markets"].get(market_id)
    if market is not None:
        market["open_visit_count"] = market.get("open_visit_count", 0) + 1
        H.touch(market)
    return vr


def maybe_close_paid_visit(vr_id):
    vr = db.STORES["visit_requests"].get(vr_id)
    if vr is None or vr["status"] != "CLAIM_ADJUDICATED_PAID":
        return
    checkins = checkins_for_visit(vr_id)
    if all(c["status"] in ("COMPLETED", "ESCALATED") for c in checkins):
        vr["status"] = "CLOSED"
        H.touch(vr)
        decr_open_visit_count(vr["market_id"])


def run_system_sweeps():
    """Lazy evaluation of clock-driven transitions: contract expiry and missed check-ins."""
    now = H.logical_now()
    with db.lock():
        for contract in db.STORES["payer_contracts"].values():
            if contract["status"] == "ACTIVE":
                if now >= H.parse_dt(contract["effective_to"]):
                    contract["status"] = "EXPIRED"
                    H.touch(contract)
        for ci in db.STORES["monitoring_checkins"].values():
            if ci["status"] == "SCHEDULED":
                if now > H.parse_dt(ci["scheduled_at"]) + timedelta(hours=6):
                    ci["status"] = "MISSED"
                    H.touch(ci)
