"""Cascading side effects (SCAFFOLD 1.2): report verification, directive
issuance, workscope supersede/reopen compensation, and agreement expiry."""
from calc import (
    directive_due,
    forecast_visit,
    recompute_engine_removal,
    recompute_workscope_derived,
)
from storage import DB, now, touch


def expire_agreements(new_clock):
    """Clock side effect: ACTIVE agreements whose end_date has been reached
    (at or before the new reading) become EXPIRED (PRD 2.4)."""
    for agreement in DB["agreements"].values():
        if agreement["status"] == "ACTIVE" and agreement["end_date"] <= new_clock:
            agreement["status"] = "EXPIRED"
            touch(agreement)


def apply_report_verification(report, engine):
    """FlightHourReport SUBMITTED -> VERIFIED cascade (PRD 3.3)."""
    report["status"] = "VERIFIED"
    report["verified_at"] = now()
    touch(report)

    engine["cumulative_flight_hours"] += report["flight_hours"]
    engine["cumulative_cycles"] += report["cycles"]
    engine["llp_remaining_cycles"] = max(0, engine["llp_remaining_cycles"] - report["cycles"])
    recompute_engine_removal(engine)
    touch(engine)

    # Every SCHEDULED visit of the engine: recompute the forecast; when it
    # falls earlier than planned, auto-advance and cancel out-of-window
    # RESERVED leases of that visit.
    for visit in DB["visits"].values():
        if visit["engine_id"] != engine["id"] or visit["status"] != "SCHEDULED":
            continue
        new_forecast, method = forecast_visit(engine)
        changed = False
        if new_forecast != visit["forecast_induction_date"]:
            visit["forecast_induction_date"] = new_forecast
            visit["forecast_method"] = method
            changed = True
        if new_forecast < visit["planned_induction_date"]:
            visit["planned_induction_date"] = new_forecast
            changed = True
            for lease in DB["leases"].values():
                if lease["shop_visit_id"] != visit["id"] or lease["status"] != "RESERVED":
                    continue
                if not (lease["start_date"] <= new_forecast < lease["end_date"]):
                    lease["status"] = "CANCELLED"
                    touch(lease)
        if changed:
            touch(visit)


def cancel_requisitions(workscope, statuses):
    """Set matching requisitions of the workscope to CANCELLED."""
    for r in DB["requisitions"].values():
        if r["workscope_id"] == workscope["id"] and r["status"] in statuses:
            r["status"] = "CANCELLED"
            touch(r)


def supersede_workscope(workscope):
    """Previous version -> SUPERSEDED; its REQUESTED/ESCALATED/SOURCED
    requisitions are cancelled (committed cost released, PRD 3.6)."""
    workscope["status"] = "SUPERSEDED"
    touch(workscope)
    cancel_requisitions(workscope, {"REQUESTED", "ESCALATED", "SOURCED"})


def directive_issuance_cascade(directive):
    """POST /api/directives side effects (PRD 3.6): for INDUCTED visits of
    matching engine models where the directive is due at issuance —
    SUBMITTED workscopes absorb the item; APPROVED workscopes REOPEN and
    cancel their REQUESTED/ESCALATED requisitions."""
    if not directive["mandatory"]:
        return
    for visit in DB["visits"].values():
        if visit["status"] != "INDUCTED":
            continue
        engine = DB["engines"].get(visit["engine_id"])
        if engine is None or engine["engine_model"] != directive["applicability_model"]:
            continue
        if not directive_due(directive, engine):
            continue
        for w in DB["workscopes"].values():
            if w["shop_visit_id"] != visit["id"]:
                continue
            if w["status"] == "SUBMITTED":
                if not any(it.get("directive_ref") == directive["directive_ref"] for it in w["items"]):
                    w["items"].append({
                        "item_code": directive["directive_ref"],
                        "item_type": "MANDATORY_DIRECTIVE",
                        "estimated_cost_usd": directive["estimated_cost_usd"],
                        "restores_cycles": 0,
                        "directive_ref": directive["directive_ref"],
                    })
                    recompute_workscope_derived(w)
                    touch(w)
            elif w["status"] == "APPROVED":
                w["status"] = "REOPENED"
                touch(w)
                cancel_requisitions(w, {"REQUESTED", "ESCALATED"})
