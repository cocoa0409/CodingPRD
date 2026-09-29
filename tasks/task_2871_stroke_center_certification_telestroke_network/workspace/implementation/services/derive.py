"""Derived aggregates, the EMS routing advisory and the cascade helpers."""
import db
from constants import (
    CASE_TERMINAL,
    CONSULT_LIVE,
    OPEN_CASE_DIVERT_THRESHOLD,
)


# --- facility postures (PRD 2.9) -------------------------------------------

def recompute_equipment_posture(center):
    ready = (center["ct_scanner_ready"], center["video_cart_ready"])
    count = sum(1 for flag in ready if flag)
    if count == 2:
        posture = "READY"
    elif count == 1:
        posture = "DEGRADED"
    else:
        posture = "OFFLINE"
    db.setf(center, "equipment_readiness_posture", posture)
    return posture


def open_case_count(center_id):
    live_cases = sum(
        1 for case in db.DB["cases"].values()
        if case["center_id"] == center_id and case["status"] not in CASE_TERMINAL
    )
    inbound = sum(
        1 for transfer in db.DB["transfers"].values()
        if transfer["destination_center_id"] == center_id
        and transfer["status"] == "ACCEPTED"
    )
    return live_cases + inbound


def recompute_open_case_count(center):
    db.setf(center, "open_case_count", open_case_count(center["id"]))
    return center["open_case_count"]


def recompute_ems_posture(center):
    if (center["certification_status"] in ("SUSPENDED", "WITHDRAWN")
            or center["equipment_readiness_posture"] == "OFFLINE"):
        posture = "BYPASS"
    elif (center["equipment_readiness_posture"] == "DEGRADED"
          or center["open_case_count"] >= OPEN_CASE_DIVERT_THRESHOLD
          or center["certification_status"] == "CONDITIONAL"):
        posture = "DIVERT_ADVISORY"
    else:
        posture = "ROUTINE"
    db.setf(center, "ems_routing_posture", posture)
    return posture


def settle_center(center):
    """Recompute the facility's open-case count, then its routing advisory."""
    recompute_open_case_count(center)
    recompute_ems_posture(center)


# --- live-load aggregates (PRD 2.8) ----------------------------------------

def recompute_agreement_active_count(agreement):
    count = sum(
        1 for consult in db.DB["consults"].values()
        if consult["agreement_id"] == agreement["id"]
        and consult["status"] in CONSULT_LIVE
    )
    db.setf(agreement, "active_consult_count", count)
    return count


def recompute_neurologist_active_count(neurologist):
    count = sum(
        1 for consult in db.DB["consults"].values()
        if consult["assigned_neurologist_id"] == neurologist["id"]
        and consult["status"] in ("ASSIGNED", "IN_SESSION")
    )
    db.setf(neurologist, "active_consult_count", count)
    return count


def recompute_case_deviation_count(case):
    count = sum(
        1 for deviation in db.DB["deviations"].values()
        if deviation["case_id"] == case["id"] and deviation["status"] != "DISMISSED"
    )
    db.setf(case, "deviation_count", count)
    return count


# --- system-detected deviations (PRD 3.8) ----------------------------------

def open_system_deviation(case, deviation_type, severity, narrative):
    record = {
        "case_id": case["id"],
        "deviation_type": deviation_type,
        "severity": severity,
        "narrative": narrative,
        "source": "SYSTEM_DETECTED",
        "status": "OPEN",
        "opened_by_user_id": "system",
        "reviewed_by_user_id": None,
        "review_round": 0,
        "info_request": None,
        "additional_info": None,
        "debrief_completed": False,
        "debrief_summary": None,
    }
    db.insert("deviations", record)
    recompute_case_deviation_count(case)
    return record


# --- consult cancellation (PRD 3.4 / 3.1 / 3.8) ---------------------------

def cancel_consult(consult, reason, raise_deviation, narrative=None):
    """Cancel a live consult; the assignee is retained for audit."""
    consult["status"] = "CANCELLED"
    consult["cancellation_reason"] = reason
    db.touch(consult)
    neurologist_id = consult.get("assigned_neurologist_id")
    if neurologist_id:
        neurologist = db.get("neurologists", neurologist_id)
        if neurologist is not None:
            if neurologist["on_call_state"] == "IN_CONSULT":
                db.setf(neurologist, "on_call_state", "ON_CALL")
            recompute_neurologist_active_count(neurologist)
    if raise_deviation:
        case = db.get("cases", consult["case_id"])
        if case is not None:
            open_system_deviation(
                case, "CONSULT_UNFILLED", "MAJOR",
                narrative or "Live telestroke consult cancelled by cascade.")
    agreement = db.get("agreements", consult["agreement_id"])
    if agreement is not None:
        recompute_agreement_active_count(agreement)


def suspend_agreement_cascade(agreement, suspension_reason, cancellation_reason):
    """PRD 3.1: suspension cancels every live consult on the agreement."""
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = suspension_reason
    db.touch(agreement)
    live = [c for c in db.all_of("consults")
            if c["agreement_id"] == agreement["id"] and c["status"] in CONSULT_LIVE]
    for consult in live:
        cancel_consult(consult, cancellation_reason, True,
                       "Telestroke consult cancelled: coverage agreement suspended.")
    recompute_agreement_active_count(agreement)


def suspend_center_cascade(center, suspension_reason):
    """PRD 3.9: the four-hop facility suspension cascade."""
    center["certification_status"] = "SUSPENDED"
    center["suspension_reason"] = suspension_reason
    db.touch(center)
    recompute_ems_posture(center)
    for agreement in db.all_of("agreements"):
        if agreement["hub_center_id"] == center["id"] and agreement["status"] == "ACTIVE":
            suspend_agreement_cascade(
                agreement, "hub certification suspended", "agreement suspended")


def terminate_hub_agreements(center):
    """PRD 3.9: withdrawal drives every hubbed agreement to TERMINATED."""
    for agreement in db.all_of("agreements"):
        if (agreement["hub_center_id"] == center["id"]
                and agreement["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")):
            agreement["status"] = "TERMINATED"
            db.touch(agreement)
            recompute_agreement_active_count(agreement)
