"""Derived fields, aggregate recomputation, cascades and JSON serialisers."""

from datetime import timedelta

import calc
from core import (
    COVERAGE_TYPES,
    D,
    RESERVING_STATUSES,
    clock,
    db,
    num,
    ordered,
    rhu,
    tons,
    to_date,
    touch,
)


# ---------------------------------------------------------------------------
# Simple lookup helpers
# ---------------------------------------------------------------------------
def loads_of_contract(contract_id):
    return [l for l in db.loads.values() if l["mill_contract_id"] == contract_id]


def loads_of_truck(truck_id):
    return [l for l in db.loads.values() if l["truck_id"] == truck_id]


def loads_of_tract(tract_id):
    return [l for l in db.loads.values() if l["tract_id"] == tract_id]


def certified_ticket_for_load(load_id):
    for t in db.delivery_tickets.values():
        if t["load_id"] == load_id and t["ticket_status"] == "CERTIFIED":
            return t
    return None


def live_ticket_for_load(load_id):
    for t in db.delivery_tickets.values():
        if t["load_id"] == load_id and t["ticket_status"] in ("DRAFT", "CERTIFIED"):
            return t
    return None


def assignments_of_tract(tract_id):
    return ordered([a for a in db.crew_assignments.values() if a["tract_id"] == tract_id])


def plans_of_tract(tract_id):
    return ordered([p for p in db.production_plans.values() if p["tract_id"] == tract_id])


def certs_of_contractor(contractor_id):
    return ordered(
        [c for c in db.insurance_certificates.values() if c["haul_contractor_id"] == contractor_id]
    )


def trucks_of_contractor(contractor_id):
    return ordered([t for t in db.trucks.values() if t["haul_contractor_id"] == contractor_id])


# ---------------------------------------------------------------------------
# MillContract quota position (calculations.mill_contract_quota_position)
# ---------------------------------------------------------------------------
def contract_reserved_tons(contract):
    total = D(0)
    for load in loads_of_contract(contract["id"]):
        if load["dispatch_status"] in RESERVING_STATUSES:
            total += D(load["estimated_net_tons"])
    return tons(total)


def contract_delivered_tons(contract):
    total = D(0)
    for ticket in db.delivery_tickets.values():
        if ticket["ticket_status"] != "CERTIFIED":
            continue
        load = db.loads.get(ticket["load_id"])
        if not load:
            continue
        if load["mill_contract_id"] != contract["id"]:
            continue
        if load["dispatch_status"] != "DELIVERED":
            continue
        total += D(ticket["net_tons"])
    return tons(total)


def contract_available_tons(contract):
    return tons(
        D(contract["quota_tons"]) - contract_reserved_tons(contract) - contract_delivered_tons(contract)
    )


def sync_contract_status(contract):
    """Derived FILLED <-> OPEN auto-transition; never settable by a client."""
    available = contract_available_tons(contract)
    if contract["status"] == "OPEN" and available <= 0:
        contract["status"] = "FILLED"
    elif contract["status"] == "FILLED" and available > 0:
        contract["status"] = "OPEN"


def recompute_contract(contract, bump=True):
    """Recompute the quota position after a load moved in or out of reserving."""
    if contract is None:
        return
    if bump:
        touch(contract)
    sync_contract_status(contract)


# ---------------------------------------------------------------------------
# Tract aggregates
# ---------------------------------------------------------------------------
def tract_move_in_cost_cents(tract):
    total = 0
    for a in db.crew_assignments.values():
        if a["tract_id"] == tract["id"]:
            total += a["move_in_cost_cents"]
    return total


def tract_produced_tons(tract):
    total = D(0)
    for ticket in db.delivery_tickets.values():
        if ticket["ticket_status"] != "CERTIFIED":
            continue
        load = db.loads.get(ticket["load_id"])
        if not load or load["tract_id"] != tract["id"]:
            continue
        if load["dispatch_status"] != "DELIVERED":
            continue
        total += D(ticket["net_tons"])
    return tons(total)


# ---------------------------------------------------------------------------
# InsuranceCertificate derived status (PRD 3.2 precedence order)
# ---------------------------------------------------------------------------
def certificate_status(cert):
    if cert.get("revoked_at") is not None:
        return "REVOKED"
    today = clock.date()
    if today < to_date(cert["effective_on"]):
        return "PENDING"
    if today > to_date(cert["expires_on"]):
        return "EXPIRED"
    return "ACTIVE"


def active_coverage_types(contractor_id):
    active = set()
    for cert in db.insurance_certificates.values():
        if cert["haul_contractor_id"] != contractor_id:
            continue
        if certificate_status(cert) == "ACTIVE":
            active.add(cert["coverage_type"])
    return active


def missing_coverage_count(contractor_id):
    active = active_coverage_types(contractor_id)
    return len([c for c in COVERAGE_TYPES if c not in active])


# ---------------------------------------------------------------------------
# Truck derived status (PRD 3.1)
# ---------------------------------------------------------------------------
def truck_status(truck):
    contractor = db.haul_contractors.get(truck["haul_contractor_id"])
    if contractor and contractor["compliance_status"] == "SUSPENDED":
        return "OUT_OF_SERVICE"
    for load in loads_of_truck(truck["id"]):
        if load["dispatch_status"] in RESERVING_STATUSES:
            return "DISPATCHED"
    return "AVAILABLE"


# ---------------------------------------------------------------------------
# contractor_compliance_score (PRD 3.2) -- two window variants
# ---------------------------------------------------------------------------
def compliance_score(contractor_id, window_start, window_end):
    finding_points = 0
    for f in db.safety_findings.values():
        if f["haul_contractor_id"] != contractor_id:
            continue
        occurred = to_date(f["occurred_on"])
        if window_start <= occurred <= window_end:
            finding_points += f["points"]
    missing = missing_coverage_count(contractor_id)
    reject_count = 0
    for load in db.loads.values():
        if load.get("haul_contractor_id") != contractor_id:
            continue
        if load["dispatch_status"] != "REJECTED":
            continue
        if load.get("rejected_on") is None:
            continue
        rejected = to_date(load["rejected_on"])
        if window_start <= rejected <= window_end:
            reject_count += 1
    raw = (
        calc.BASE_SCORE
        - finding_points
        - calc.INSURANCE_PENALTY_POINTS * missing
        - calc.REJECT_PENALTY_POINTS * reject_count
    )
    return max(calc.SCORE_FLOOR, min(calc.BASE_SCORE, raw))


def rolling_compliance_score(contractor_id):
    end = clock.date()
    start = end - timedelta(days=calc.SAFETY_LOOKBACK_DAYS)
    return compliance_score(contractor_id, start, end)


def period_to_date_compliance_score(contractor_id, period_start, period_end):
    return compliance_score(contractor_id, to_date(period_start), to_date(period_end))


def contractor_lifetime_settled_cents(contractor):
    total = 0
    for s in db.settlement_statements.values():
        if s["haul_contractor_id"] == contractor["id"] and s["status"] == "PAID":
            total += s["net_pay_cents"]
    return total


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def release_load_reservation(load):
    """A load left a reserving status: its contract recomputes and may reopen."""
    contract = db.mill_contracts.get(load["mill_contract_id"])
    recompute_contract(contract)


def cancel_load(load):
    load["dispatch_status"] = "CANCELLED"
    touch(load)
    release_load_reservation(load)


def suspend_contractor(contractor):
    """The four-hop suspension cascade (PRD 3.2)."""
    contractor["compliance_status"] = "SUSPENDED"
    touch(contractor)
    for truck in trucks_of_contractor(contractor["id"]):
        touch(truck)
        for load in ordered(loads_of_truck(truck["id"])):
            if load["dispatch_status"] in RESERVING_STATUSES:
                cancel_load(load)


def crew_of_assignment(assignment):
    return db.crews.get(assignment["crew_id"])


def set_crew_status(assignment, status):
    crew = crew_of_assignment(assignment)
    if crew is not None:
        crew["status"] = status
        touch(crew)


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------
def common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def mill_json(rec):
    out = common(rec)
    out.update(
        {
            "name": rec["name"],
            "state_code": rec["state_code"],
            "receiving_status": rec["receiving_status"],
        }
    )
    return out


def mill_contract_json(rec):
    out = common(rec)
    reserved = contract_reserved_tons(rec)
    delivered = contract_delivered_tons(rec)
    available = tons(D(rec["quota_tons"]) - reserved - delivered)
    out.update(
        {
            "mill_id": rec["mill_id"],
            "species": rec["species"],
            "grade": rec["grade"],
            "quota_tons": num(rec["quota_tons"]),
            "overrun_tolerance_pct": num(rec["overrun_tolerance_pct"]),
            "base_rate_cents_per_ton": rec["base_rate_cents_per_ton"],
            "period_start": rec["period_start"],
            "period_end": rec["period_end"],
            "reserved_tons": num(reserved),
            "delivered_tons": num(delivered),
            "available_tons": num(available),
            "status": rec["status"],
        }
    )
    return out


def haul_contractor_json(rec):
    out = common(rec)
    out.update(
        {
            "name": rec["name"],
            "dot_number": rec["dot_number"],
            "base_state_code": rec["base_state_code"],
            "compliance_status": rec["compliance_status"],
            "compliance_score": rolling_compliance_score(rec["id"]),
            "lifetime_settled_cents": contractor_lifetime_settled_cents(rec),
        }
    )
    return out


def insurance_certificate_json(rec):
    out = common(rec)
    out.update(
        {
            "haul_contractor_id": rec["haul_contractor_id"],
            "coverage_type": rec["coverage_type"],
            "effective_on": rec["effective_on"],
            "expires_on": rec["expires_on"],
            "limit_cents": rec["limit_cents"],
            "revoked_at": rec["revoked_at"],
            "status": certificate_status(rec),
        }
    )
    return out


def truck_json(rec):
    out = common(rec)
    out.update(
        {
            "haul_contractor_id": rec["haul_contractor_id"],
            "unit_number": rec["unit_number"],
            "axle_config": rec["axle_config"],
            "tare_weight_lbs": rec["tare_weight_lbs"],
            "permit_class": rec["permit_class"],
            "status": truck_status(rec),
        }
    )
    return out


def safety_finding_json(rec):
    # A SafetyFinding is an immutable audit record: id and created_at only.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "haul_contractor_id": rec["haul_contractor_id"],
        "severity": rec["severity"],
        "points": rec["points"],
        "occurred_on": rec["occurred_on"],
        "note": rec["note"],
    }


def tract_json(rec):
    out = common(rec)
    out.update(
        {
            "name": rec["name"],
            "legal_description": rec["legal_description"],
            "gross_acres": num(rec["gross_acres"]),
            "planned_volume_tons": num(rec["planned_volume_tons"]),
            "access_class": rec["access_class"],
            "status": rec["status"],
            "suspension_count": rec["suspension_count"],
            "move_in_cost_cents": tract_move_in_cost_cents(rec),
            "produced_tons": num(tract_produced_tons(rec)),
        }
    )
    return out


def production_plan_json(rec):
    out = common(rec)
    out.update(
        {
            "tract_id": rec["tract_id"],
            "target_tons_per_week": num(rec["target_tons_per_week"]),
            "plan_horizon_weeks": rec["plan_horizon_weeks"],
            "planned_volume_tons": num(rec["planned_volume_tons"]),
            "status": rec["status"],
        }
    )
    return out


def crew_json(rec):
    out = common(rec)
    out.update(
        {
            "name": rec["name"],
            "crew_type": rec["crew_type"],
            "equipment_pieces": rec["equipment_pieces"],
            "daily_rate_cents": rec["daily_rate_cents"],
            "status": rec["status"],
        }
    )
    return out


def crew_assignment_json(rec):
    out = common(rec)
    out.update(
        {
            "tract_id": rec["tract_id"],
            "crew_id": rec["crew_id"],
            "move_in_miles": rec["move_in_miles"],
            "window_start": rec["window_start"],
            "window_end": rec["window_end"],
            "lowboy_trips": rec["lowboy_trips"],
            "move_in_cost_cents": rec["move_in_cost_cents"],
            "status": rec["status"],
        }
    )
    return out


def haul_route_json(rec):
    out = common(rec)
    out.update(
        {
            "tract_id": rec["tract_id"],
            "mill_id": rec["mill_id"],
            "distance_miles": rec["distance_miles"],
            "legal_gross_weight_lbs": rec["legal_gross_weight_lbs"],
            "permit_class_required": rec["permit_class_required"],
            "frost_law_start_on": rec["frost_law_start_on"],
            "frost_law_end_on": rec["frost_law_end_on"],
            "status": rec["status"],
        }
    )
    return out


def shutdown_order_json(rec):
    out = common(rec)
    out.update(
        {
            "tract_id": rec["tract_id"],
            "reason": rec["reason"],
            "soil_moisture_index": rec["soil_moisture_index"],
            "lift_soil_moisture_index": rec["lift_soil_moisture_index"],
            "declared_at": rec["declared_at"],
            "lifted_at": rec["lifted_at"],
            "status": rec["status"],
        }
    )
    return out


def load_json(rec):
    out = common(rec)
    out.update(
        {
            "tract_id": rec["tract_id"],
            "mill_contract_id": rec["mill_contract_id"],
            "haul_route_id": rec["haul_route_id"],
            "truck_id": rec["truck_id"],
            "haul_contractor_id": rec["haul_contractor_id"],
            "rehaul_of_load_id": rec["rehaul_of_load_id"],
            "declared_species": rec["declared_species"],
            "declared_grade": rec["declared_grade"],
            "estimated_net_tons": num(rec["estimated_net_tons"]),
            "scheduled_depart_at": rec["scheduled_depart_at"],
            "scheduled_arrive_at": rec["scheduled_arrive_at"],
            "dispatch_status": rec["dispatch_status"],
            "settlement_status": rec["settlement_status"],
            "rehaul_status": rec["rehaul_status"],
            "departed_at": rec["departed_at"],
            "arrived_at": rec["arrived_at"],
            "rejected_on": rec["rejected_on"],
            "settlement_event_on": rec["settlement_event_on"],
            "wait_minutes": rec["wait_minutes"],
            "rate_cents_per_ton_mile": rec["rate_cents_per_ton_mile"],
            "provisional_haul_pay_cents": rec["provisional_haul_pay_cents"],
            "line_haul_cents": rec["line_haul_cents"],
            "fuel_surcharge_cents": rec["fuel_surcharge_cents"],
            "demurrage_cents": rec["demurrage_cents"],
            "incentive_cents": rec["incentive_cents"],
            "regrade_adjustment_cents": rec["regrade_adjustment_cents"],
            "final_haul_pay_cents": rec["final_haul_pay_cents"],
        }
    )
    return out


def delivery_ticket_json(rec):
    out = common(rec)
    out.update(
        {
            "load_id": rec["load_id"],
            "mill_id": rec["mill_id"],
            "gross_weight_lbs": rec["gross_weight_lbs"],
            "tare_weight_lbs": rec["tare_weight_lbs"],
            "net_weight_lbs": rec["net_weight_lbs"],
            "defect_deduction_pct": num(rec["defect_deduction_pct"]),
            "defect_deducted_lbs": rec["defect_deducted_lbs"],
            "payable_lbs": rec["payable_lbs"],
            "net_tons": num(rec["net_tons"]),
            "max_allowed_gross_lbs": rec["max_allowed_gross_lbs"],
            "scaled_species": rec["scaled_species"],
            "scaled_grade": rec["scaled_grade"],
            "ticket_status": rec["ticket_status"],
            "certified_at": rec["certified_at"],
            "certified_by_user_id": rec["certified_by_user_id"],
            "reject_reason": rec["reject_reason"],
        }
    )
    return out


def settlement_line_json(line):
    return {
        "line_type": line["line_type"],
        "load_id": line["load_id"],
        "tons": num(line["tons"]) if line["tons"] is not None else None,
        "distance_miles": line["distance_miles"],
        "amount_cents": line["amount_cents"],
    }


def settlement_statement_json(rec):
    out = common(rec)
    out.update(
        {
            "haul_contractor_id": rec["haul_contractor_id"],
            "period_start": rec["period_start"],
            "period_end": rec["period_end"],
            "status": rec["status"],
            "compiled_by_user_id": rec["compiled_by_user_id"],
            "approved_by_user_id": rec["approved_by_user_id"],
            "compliance_score_at_compile": rec["compliance_score_at_compile"],
            "holdback_pct": num(rec["holdback_pct"]) if rec["holdback_pct"] is not None else None,
            "lines": [settlement_line_json(l) for l in rec["lines"]],
            "gross_pay_cents": rec["gross_pay_cents"],
            "reject_deduction_cents": rec["reject_deduction_cents"],
            "holdback_cents": rec["holdback_cents"],
            "deduction_cents": rec["deduction_cents"],
            "net_pay_cents": rec["net_pay_cents"],
            "dispute_reason": rec["dispute_reason"],
            "payment_reference": rec["payment_reference"],
        }
    )
    return out
