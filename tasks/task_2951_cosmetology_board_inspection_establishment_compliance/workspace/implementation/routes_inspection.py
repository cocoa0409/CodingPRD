"""Inspection scheduling, conduct, scoring, finalization and hazard authority."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import derive
import envelope
import store
from errors import fail
from helpers import find, scope_establishment
from validate import (body_of, d2, fk, opt_str, req_bool, req_enum, req_instant, req_int, req_str)

inspection_bp = Blueprint("inspection", __name__)


# -------------------------------------------------------------- scheduling
@inspection_bp.post("/inspections")
def create_inspection():
    auth.authenticate(("BoardAdmin", "Inspector"))
    body = body_of(request)

    est_id = fk(body, "establishment_id")
    est = find("Establishment", est_id) if est_id is not None else None
    parent_id = fk(body, "reinspection_of_id")
    parent = find("Inspection", parent_id) if parent_id is not None else None

    if est is None:
        fail("ERR_INVALID_REQUEST", "Field 'establishment_id' is required.")
    insp_type = req_enum(body, "inspection_type", derive.INSPECTION_TYPES)
    window_start_at = req_instant(body, "window_start_at")
    window_end_at = req_instant(body, "window_end_at")
    inspector_user_id = req_str(body, "inspector_user_id")
    complaint_reference = opt_str(body, "complaint_reference")

    if window_end_at <= window_start_at:
        fail("ERR_INVALID_REQUEST", "Field 'window_end_at' must be strictly after 'window_start_at'.")
    if insp_type == "COMPLAINT_DRIVEN":
        if complaint_reference is None:
            fail("ERR_INVALID_REQUEST", "Field 'complaint_reference' is required for a complaint-driven visit.")
    elif complaint_reference is not None:
        fail("ERR_INVALID_REQUEST", "Field 'complaint_reference' is forbidden for this inspection type.")
    if insp_type == "REINSPECTION":
        if parent_id is None:
            fail("ERR_INVALID_REQUEST", "Field 'reinspection_of_id' is required for a reinspection.")
    elif parent_id is not None:
        fail("ERR_INVALID_REQUEST", "Field 'reinspection_of_id' is forbidden for this inspection type.")

    if insp_type == "ROUTINE" and est["license_status"] not in derive.OPERABLE_STATUSES:
        fail("ERR_ESTABLISHMENT_NOT_OPERABLE",
             "A routine inspection may not be scheduled against a %s establishment."
             % est["license_status"])

    others = [i for i in derive.inspections_of(est["id"])
              if i["status"] in derive.NON_TERMINAL_INSPECTION]
    for other in others:
        if window_start_at <= other["window_end_at"] and other["window_start_at"] <= window_end_at:
            fail("ERR_INSPECTION_WINDOW_OVERLAP",
                 "The requested window collides with an existing inspection window.")
    if insp_type in ("ROUTINE", "COMPLAINT_DRIVEN"):
        buffer = timedelta(hours=derive.INSPECTION_COOLDOWN_HOURS)
        for other in others:
            after = window_start_at >= other["window_end_at"] + buffer
            before = window_end_at <= other["window_start_at"] - buffer
            if not (after or before):
                fail("ERR_INSPECTION_WINDOW_COOLDOWN",
                     "The requested window is inside the 24-hour cooldown buffer.")

    if insp_type == "REINSPECTION":
        if (parent is None
                or parent["establishment_id"] != est["id"]
                or parent["status"] != "FINALIZED"
                or parent["final_outcome"] not in ("CONDITIONAL_PASS", "FAIL", "IMMEDIATE_CLOSURE")):
            fail("ERR_REINSPECTION_PARENT_REQUIRED",
                 "The nominated parent inspection cannot be reinspected.")

    row = store.make_row()
    row.update({
        "establishment_id": est["id"],
        "inspection_type": insp_type,
        "reinspection_of_id": parent_id,
        "inspector_user_id": inspector_user_id,
        "complaint_reference": complaint_reference,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "status": "SCHEDULED",
        "hazard_state": "NONE",
        "started_at": None,
        "submitted_at": None,
        "finalized_at": None,
        "finding_count": 0,
        "provisional_adjusted_score": None,
        "final_adjusted_score": None,
        "provisional_outcome": None,
        "final_outcome": None,
        "demerit_balance_before_finalize": None,
        "citation_count": 0,
    })
    store.inspections[row["id"]] = row
    return envelope.ok(derive.ser_inspection(row), 201)


@inspection_bp.post("/inspections/<iid>/start")
def start_inspection(iid):
    auth.authenticate(("BoardAdmin", "Inspector"))
    insp = find("Inspection", iid)
    if insp["status"] != "SCHEDULED":
        fail("ERR_INSPECTION_NOT_SCHEDULED",
             "Inspection status is %s, not SCHEDULED." % insp["status"])
    insp["status"] = "IN_PROGRESS"
    insp["started_at"] = store.now_utc()
    store.bump(insp)
    return envelope.ok(derive.ser_inspection(insp))


# ---------------------------------------------------------------- findings
@inspection_bp.post("/inspections/<iid>/findings")
def create_finding(iid):
    auth.authenticate(("BoardAdmin", "Inspector"))
    insp = find("Inspection", iid)
    body = body_of(request)

    code_id = fk(body, "violation_code_id")
    code = find("ViolationCode", code_id) if code_id is not None else None
    prac_id = fk(body, "attributed_practitioner_id")
    prac = find("Practitioner", prac_id) if prac_id is not None else None
    ws_id = fk(body, "workstation_id")
    ws = find("Workstation", ws_id) if ws_id is not None else None

    if code is None:
        fail("ERR_INVALID_REQUEST", "Field 'violation_code_id' is required.")
    observed_count = req_int(body, "observed_count", minimum=1)
    corrected_on_site = req_bool(body, "corrected_on_site", default=False)
    note = opt_str(body, "note")

    if insp["status"] != "IN_PROGRESS":
        fail("ERR_INSPECTION_NOT_IN_PROGRESS",
             "Inspection status is %s, not IN_PROGRESS." % insp["status"])

    if prac is not None and not auth.practitioner_linked_to_establishment(
            prac["id"], insp["establishment_id"]):
        fail("ERR_PRACTITIONER_NOT_LINKED_TO_ESTABLISHMENT",
             "The attributed practitioner holds no PROPOSED or ACTIVE rental at this establishment.")
    if ws is not None and ws["establishment_id"] != insp["establishment_id"]:
        fail("ERR_WORKSTATION_NOT_IN_ESTABLISHMENT",
             "The workstation does not belong to the inspection's establishment.")

    row = store.make_row()
    row.update({
        "inspection_id": insp["id"],
        "violation_code_id": code["id"],
        "attributed_practitioner_id": prac_id,
        "workstation_id": ws_id,
        "observed_count": observed_count,
        "corrected_on_site": corrected_on_site,
        "severity": code["severity"],
        "repeat_factor_provisional": None,
        "repeat_factor_final": None,
        "provisional_points": None,
        "final_points": None,
        "declared_hazard": False,
        "note": note,
    })
    store.violation_findings[row["id"]] = row
    insp["finding_count"] = len(derive.findings_of(insp["id"]))
    store.bump(insp)
    return envelope.ok(derive.ser_finding(row), 201)


# ------------------------------------------------------ submit and finalize
@inspection_bp.post("/inspections/<iid>/submit")
def submit_inspection(iid):
    auth.authenticate(("BoardAdmin", "Inspector"))
    insp = find("Inspection", iid)
    if insp["status"] != "IN_PROGRESS":
        fail("ERR_INSPECTION_NOT_IN_PROGRESS",
             "Inspection status is %s, not IN_PROGRESS." % insp["status"])
    insp["status"] = "PENDING_REVIEW"
    insp["submitted_at"] = store.now_utc()
    derive.score_inspection(insp, "provisional")
    store.bump(insp)
    return envelope.ok(derive.ser_inspection(insp))


@inspection_bp.post("/inspections/<iid>/finalize")
def finalize_inspection(iid):
    auth.authenticate(("BoardAdmin",))
    insp = find("Inspection", iid)
    if insp["status"] != "PENDING_REVIEW":
        fail("ERR_INSPECTION_NOT_PENDING_REVIEW",
             "Inspection status is %s, not PENDING_REVIEW." % insp["status"])
    est = store.establishments[insp["establishment_id"]]

    # Hop one: finalize and run the final scoring variant.
    insp["status"] = "FINALIZED"
    insp["finalized_at"] = store.now_utc()
    score = derive.score_inspection(insp, "final")

    # Hop two: snapshot the pre-cascade balance, then post the assessment.
    insp["demerit_balance_before_finalize"] = derive.establishment_demerit_balance(est["id"])
    derive.post_ledger("DEMERIT_POINTS", "INSPECTION_DEMERIT_ASSESSMENT",
                       delta_points=score, establishment_id=est["id"], inspection_id=insp["id"])

    # Hop three: recompute the live balance from the ledger.
    balance = derive.establishment_demerit_balance(est["id"])
    est["demerit_balance"] = balance

    # Hop four: re-derive the licence status, promotion before demotions.
    mode = None
    if est["license_status"] == "PENDING_INSPECTION" and insp["final_outcome"] in ("PASS", "CONDITIONAL_PASS"):
        est["license_status"] = "ACTIVE"
    if balance >= derive.REVOCATION_DEMERIT_THRESHOLD and est["license_status"] in ("ACTIVE", "PROBATION"):
        est["license_status"] = "REVOKED"
        mode = "REVOKED"
    elif (derive.PROBATION_DEMERIT_THRESHOLD <= balance < derive.REVOCATION_DEMERIT_THRESHOLD
          and est["license_status"] == "ACTIVE"):
        est["license_status"] = "PROBATION"
        mode = "PROBATION"

    # Hop five: propagate into personnel, then refresh the derived summary.
    if mode is not None:
        derive.establishment_personnel_cascade(est["id"], mode, store.now_utc())
    derive.refresh_establishment(est, force=True)
    store.bump(insp)
    return envelope.ok(derive.ser_inspection(insp))


# --------------------------------------------------------- hazard authority
@inspection_bp.post("/inspections/<iid>/hazard-declaration")
def declare_hazard(iid):
    auth.authenticate(("BoardAdmin", "Inspector"))
    insp = find("Inspection", iid)
    body = body_of(request)
    finding_id = fk(body, "hazard_violation_finding_id")
    finding = find("ViolationFinding", finding_id) if finding_id is not None else None
    if finding is None:
        fail("ERR_INVALID_REQUEST", "Field 'hazard_violation_finding_id' is required.")
    narrative = req_str(body, "narrative")

    if insp["status"] != "IN_PROGRESS":
        fail("ERR_INSPECTION_NOT_IN_PROGRESS",
             "Inspection status is %s, not IN_PROGRESS." % insp["status"])
    if insp["hazard_state"] != "NONE":
        fail("ERR_HAZARD_ALREADY_DECLARED",
             "Hazard state is already %s." % insp["hazard_state"])

    if finding["inspection_id"] != insp["id"] or finding["severity"] != "IMMINENT_HAZARD":
        fail("ERR_HAZARD_FINDING_NOT_ELIGIBLE",
             "Only an IMMINENT_HAZARD finding of this inspection can support immediate closure.")

    finding["declared_hazard"] = True
    store.bump(finding)
    insp["hazard_state"] = "HAZARD_DECLARED"
    store.bump(insp)

    est = store.establishments[insp["establishment_id"]]
    if est["license_status"] != "REVOKED":
        est["license_status"] = "CLOSED_IMMINENT_HAZARD"
    derive.refresh_establishment(est, force=True)
    return envelope.ok(derive.ser_inspection(insp))


@inspection_bp.post("/inspections/<iid>/hazard-clearance")
def clear_hazard(iid):
    auth.authenticate(("BoardAdmin",))
    insp = find("Inspection", iid)
    body = body_of(request)
    clearing_id = fk(body, "clearing_reinspection_id")
    clearing = find("Inspection", clearing_id) if clearing_id is not None else None
    if clearing is None:
        fail("ERR_INVALID_REQUEST", "Field 'clearing_reinspection_id' is required.")

    if clearing["status"] != "FINALIZED":
        fail("ERR_INSPECTION_NOT_FINALIZED",
             "The nominated reinspection is %s, not FINALIZED." % clearing["status"])
    if insp["hazard_state"] != "HAZARD_DECLARED":
        fail("ERR_HAZARD_NOT_DECLARED",
             "Hazard state is %s, not HAZARD_DECLARED." % insp["hazard_state"])
    est = store.establishments[insp["establishment_id"]]
    if est["license_status"] != "CLOSED_IMMINENT_HAZARD":
        fail("ERR_HAZARD_NOT_DECLARED",
             "The establishment is not under an immediate closure.")

    derive.compute_establishment(est)
    if (clearing["inspection_type"] != "REINSPECTION"
            or clearing["reinspection_of_id"] != insp["id"]
            or clearing["establishment_id"] != insp["establishment_id"]
            or clearing["hazard_state"] != "NONE"
            or clearing["final_adjusted_score"] is None
            or clearing["final_adjusted_score"] > derive.HAZARD_CLEARANCE_MAX_SCORE
            or not est["foot_spa_biofilm_current"]):
        fail("ERR_HAZARD_CLEARANCE_REINSPECTION_REQUIRED",
             "The nominated reinspection does not qualify to lift the closure.")

    insp["hazard_state"] = "HAZARD_CLEARED"
    store.bump(insp)
    est["license_status"] = "ACTIVE"
    derive.refresh_establishment(est, force=True)
    return envelope.ok(derive.ser_inspection(insp))
