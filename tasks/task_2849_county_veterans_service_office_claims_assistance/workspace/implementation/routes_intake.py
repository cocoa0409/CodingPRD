"""Intake, the discharge-document file, screening and the case lifecycle
(PRD 3.2, 3.3)."""

from flask import Blueprint, g

import calc
from errors import ApiError
from envelope import list_response, object_response
from guard import (
    authorize, check_shape, filter_rows, invalid_transition, need_document,
    need_representative, need_veteran, page_of, run_checks,
)
from store import bump, db, new_row, now_date, now_instant, ordered, parse_date
from views import view, view_all

bp = Blueprint("intake", __name__, url_prefix="/cvso")

FRONT_DESK = ("IntakeClerk", "CountyOfficer")
READ_VETERANS = ("IntakeClerk", "CountyOfficer", "StateAuditor", "SystemAdmin")
READ_VETERAN_ONE = ("IntakeClerk", "CountyOfficer", "StateAuditor",
                    "SystemAdmin", "VeteranClient")

VETERAN_INPUTS = ("full_name", "date_of_birth", "service_start_date",
                  "service_end_date", "household_income_cents",
                  "net_worth_cents", "dependent_count", "homeless_status",
                  "referral_source")


# --------------------------------------------------------------------------
# eligibility screens (shared by screening and by the death record)
# --------------------------------------------------------------------------

def append_screen(veteran):
    basic, results = calc.category_results(veteran)
    veteran["priority_group"] = calc.priority_group(veteran)
    sequence = 1 + sum(1 for s in db.eligibility_screens.values()
                       if s["veteran_id"] == veteran["id"])
    row = new_row(with_audit=False)
    row["_kind"] = "eligibility_screen"
    row["veteran_id"] = veteran["id"]
    row["screen_sequence"] = sequence
    row["basic_eligibility"] = basic
    row["income_limit_applied_cents"] = calc.income_limit_cents(
        veteran["dependent_count"])
    row["wartime_service_days_at_screen"] = veteran["wartime_service_days"]
    row["priority_group_assigned"] = veteran["priority_group"]
    row["category_results"] = results
    row["eligible_category_count"] = sum(
        1 for value in results.values() if value["eligible"])
    db.eligibility_screens[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# veterans
# --------------------------------------------------------------------------

def _mint_case_number():
    rank = len(db.veterans) + 1
    return "CVSO-%04d-%06d" % (now_date().year, rank)


@bp.post("/veterans")
def create_veteran():
    authorize(FRONT_DESK)
    body = check_shape({
        "required": ["full_name", "date_of_birth", "service_start_date",
                     "service_end_date", "household_income_cents",
                     "net_worth_cents"],
        "optional": ["dependent_count", "homeless_status", "referral_source"],
        "service_dates": ("service_start_date", "service_end_date"),
    })
    run_checks()
    row = new_row()
    row["_kind"] = "veteran"
    row["county_case_number"] = _mint_case_number()
    row["full_name"] = body["full_name"]
    row["date_of_birth"] = body["date_of_birth"]
    row["service_start_date"] = body["service_start_date"]
    row["service_end_date"] = body["service_end_date"]
    row["character_of_service"] = "UNCHARACTERIZED"
    row["discharge_doc_status"] = "NOT_SUBMITTED"
    row["intake_status"] = "INTAKE_STARTED"
    row["household_income_cents"] = body["household_income_cents"]
    row["net_worth_cents"] = body["net_worth_cents"]
    row["dependent_count"] = body.get("dependent_count", 0)
    row["homeless_status"] = body.get("homeless_status", "NOT_HOMELESS")
    row["referral_source"] = body.get("referral_source", "WALK_IN")
    row["wartime_service_days"] = 0
    row["combined_rating_pct"] = 0
    row["priority_group"] = "P4"
    row["assigned_representative_id"] = None
    row["date_of_death"] = None
    db.veterans[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/veterans")
def list_veterans():
    authorize(READ_VETERANS)
    run_checks()
    rows = filter_rows(ordered(db.veterans.values()), {
        "intake_status": "intake_status",
        "priority_group": "priority_group",
        "homeless_status": "homeless_status",
        "assigned_representative_id": "assigned_representative_id",
        "discharge_doc_status": "discharge_doc_status",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/veterans/<row_id>")
def read_veteran(row_id):
    authorize(READ_VETERAN_ONE)
    row = need_veteran(row_id)
    run_checks()
    return object_response(view(row))


@bp.patch("/veterans/<row_id>")
def patch_veteran(row_id):
    authorize(FRONT_DESK)
    body = check_shape({
        "optional": list(VETERAN_INPUTS),
        "service_dates": ("service_start_date", "service_end_date"),
    })
    row = need_veteran(row_id)
    start = body.get("service_start_date", row["service_start_date"])
    end = body.get("service_end_date", row["service_end_date"])
    if parse_date(end) < parse_date(start):
        raise ApiError("ERR_INVALID_SERVICE_DATES",
                       "service_end_date is earlier than service_start_date")
    run_checks()
    for field in VETERAN_INPUTS:
        if field in body:
            row[field] = body[field]
    row["priority_group"] = calc.priority_group(row)
    bump(row)
    return object_response(view(row))


@bp.get("/veterans/<row_id>/eligibility-screens")
def read_screens(row_id):
    authorize(READ_VETERANS)
    need_veteran(row_id)
    run_checks()
    rows = [s for s in ordered(db.eligibility_screens.values())
            if s["veteran_id"] == row_id]
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.post("/veterans/<row_id>/screen")
def screen_veteran(row_id):
    authorize(("CountyOfficer",))
    check_shape({})
    veteran = need_veteran(row_id)

    def from_state():
        if veteran["intake_status"] not in ("INTAKE_STARTED", "SCREENED",
                                            "ACTIVE"):
            invalid_transition("a screen is not available from %s"
                               % (veteran["intake_status"],))

    def verified():
        if veteran["discharge_doc_status"] != "VERIFIED":
            raise ApiError("ERR_DISCHARGE_NOT_VERIFIED",
                           "the veteran has no verified discharge document")

    run_checks([(40, from_state), (43, verified)])
    row = append_screen(veteran)
    if veteran["intake_status"] == "INTAKE_STARTED":
        veteran["intake_status"] = "SCREENED"
    bump(veteran)
    return object_response(view(row), 201)


@bp.post("/veterans/<row_id>/assign-representative")
def assign_representative(row_id):
    authorize(("IntakeClerk",))
    body = check_shape({"optional": ["representative_id"]})
    veteran = need_veteran(row_id)
    nominated = None
    if body.get("representative_id") is not None:
        nominated = need_representative(body["representative_id"])

    def from_state():
        # PRD 3.3: assigning against a deceased veteran is ERR_VETERAN_DECEASED.
        if veteran["intake_status"] == "DECEASED":
            raise ApiError("ERR_VETERAN_DECEASED",
                           "the veteran's case is closed")
        if veteran["intake_status"] != "SCREENED":
            invalid_transition("assignment is not available from %s"
                               % (veteran["intake_status"],))

    def screened():
        for screen in db.eligibility_screens.values():
            if screen["veteran_id"] == row_id and screen["basic_eligibility"]:
                return
        raise ApiError("ERR_NOT_SCREENED",
                       "the veteran has no screen passing basic eligibility")

    chosen = {}

    def selector():
        if nominated is not None:
            chosen["rep"] = nominated
            return
        candidates = calc.assignment_candidates()
        if not candidates:
            raise ApiError("ERR_NO_ELIGIBLE_REPRESENTATIVE",
                           "no representative satisfies the selector filters")
        chosen["rep"] = candidates[0]

    def ceiling():
        rep = chosen["rep"]
        if rep["active_poa_count"] >= calc.MAX_POA_PER_REPRESENTATIVE:
            raise ApiError("ERR_REPRESENTATIVE_CASELOAD_FULL",
                           "the representative holds the maximum designations")

    run_checks([(40, from_state), (47, screened), (68, selector), (69, ceiling)])
    veteran["assigned_representative_id"] = chosen["rep"]["id"]
    veteran["intake_status"] = "ACTIVE"
    bump(veteran)
    return object_response(view(veteran))


VETERAN_STATUS_FROM = {
    "DEACTIVATE": ("ACTIVE",),
    "REACTIVATE": ("INACTIVE",),
    "RECORD_DEATH": ("ACTIVE", "INACTIVE"),
}

DEATH_WITHDRAWABLE = ("DRAFT", "EVIDENCE_DEVELOPMENT", "PEER_REVIEW",
                      "READY_TO_FILE")


@bp.post("/veterans/<row_id>/status")
def drive_veteran_status(row_id):
    authorize(FRONT_DESK)

    def extra(body):
        if body.get("action") == "RECORD_DEATH":
            if parse_date(body["date_of_death"]) > now_date():
                raise ApiError("ERR_VALIDATION",
                               "date_of_death may not be later than the"
                               " logical-clock date")

    body = check_shape({
        "actions": ("DEACTIVATE", "REACTIVATE", "RECORD_DEATH"),
        "optional": ["date_of_death", "reason"],
        "action_required": {"RECORD_DEATH": ("date_of_death",)},
        "extra": extra,
    })
    veteran = need_veteran(row_id)
    action = body["action"]

    def from_state():
        if veteran["intake_status"] not in VETERAN_STATUS_FROM[action]:
            invalid_transition("%s is not available from %s"
                               % (action, veteran["intake_status"]))

    def housing():
        if action == "DEACTIVATE" and veteran["homeless_status"] in (
                "SHELTERED", "UNSHELTERED"):
            raise ApiError("ERR_HOMELESS_VETERAN_PROTECTED",
                           "an unhoused veteran's case may not be deactivated")

    run_checks([(40, from_state), (53, housing)])

    if action == "DEACTIVATE":
        veteran["intake_status"] = "INACTIVE"
        bump(veteran)
    elif action == "REACTIVATE":
        veteran["intake_status"] = "ACTIVE"
        bump(veteran)
    else:
        veteran["intake_status"] = "DECEASED"
        veteran["date_of_death"] = body["date_of_death"]
        preparers = set()
        for claim in ordered(db.claims.values()):
            if claim["veteran_id"] != row_id:
                continue
            if claim["status"] in DEATH_WITHDRAWABLE:
                claim["status"] = "WITHDRAWN"
                claim["withdrawal_reason"] = "CLAIMANT_DECEASED"
                bump(claim)
                preparers.add(claim.get("prepared_by_representative_id"))
        append_screen(veteran)
        bump(veteran)
        for rep_id in preparers:
            calc.refresh_caseload(db.representatives.get(rep_id))
    return object_response(view(veteran))


# --------------------------------------------------------------------------
# discharge documents
# --------------------------------------------------------------------------

@bp.post("/veterans/<row_id>/discharge-documents")
def create_document(row_id):
    authorize(FRONT_DESK)
    body = check_shape({
        "required": ["document_type", "source", "claimed_service_start",
                     "claimed_service_end", "claimed_character_of_service"],
        "service_dates": ("claimed_service_start", "claimed_service_end"),
    })
    veteran = need_veteran(row_id)

    def alive():
        if veteran["intake_status"] == "DECEASED":
            raise ApiError("ERR_VETERAN_DECEASED",
                           "the veteran's case is closed to new work")

    run_checks([(41, alive)])
    row = new_row()
    row["_kind"] = "discharge_document"
    row["veteran_id"] = row_id
    row["document_type"] = body["document_type"]
    row["source"] = body["source"]
    row["verification_status"] = "PENDING_VERIFICATION"
    row["claimed_service_start"] = body["claimed_service_start"]
    row["claimed_service_end"] = body["claimed_service_end"]
    row["claimed_character_of_service"] = body["claimed_character_of_service"]
    row["discrepancy_reason"] = None
    row["resubmission_count"] = 0
    row["verified_at"] = None
    row["verified_by_representative_id"] = None
    db.discharge_documents[row["id"]] = row
    calc.refresh_discharge_mirror(veteran)
    bump(veteran)
    return object_response(view(row), 201)


@bp.get("/discharge-documents")
def list_documents():
    authorize(READ_VETERANS)
    run_checks()
    rows = filter_rows(ordered(db.discharge_documents.values()), {
        "veteran_id": "veteran_id",
        "verified_by_representative_id": "verified_by_representative_id",
        "verification_status": "verification_status",
        "document_type": "document_type",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/discharge-documents/<row_id>")
def read_document(row_id):
    authorize(READ_VETERANS)
    row = need_document(row_id)
    run_checks()
    return object_response(view(row))


DOCUMENT_REVIEW_FROM = {
    "VERIFY": ("PENDING_VERIFICATION",),
    "HOLD_DISCREPANCY": ("PENDING_VERIFICATION",),
    "REJECT": ("PENDING_VERIFICATION", "DISCREPANCY_HELD"),
}


@bp.post("/discharge-documents/<row_id>/review")
def review_document(row_id):
    authorize(("CountyOfficer",))
    body = check_shape({
        "actions": ("VERIFY", "HOLD_DISCREPANCY", "REJECT"),
        "optional": ["reason"],
        "action_required": {
            "HOLD_DISCREPANCY": ("reason",),
            "REJECT": ("reason",),
        },
    })
    document = need_document(row_id)
    action = body["action"]

    def from_state():
        if document["verification_status"] not in DOCUMENT_REVIEW_FROM[action]:
            invalid_transition("%s is not available from %s"
                               % (action, document["verification_status"]))

    run_checks([(40, from_state)])
    veteran = db.veterans.get(document["veteran_id"])

    if action == "VERIFY":
        document["verification_status"] = "VERIFIED"
        document["verified_at"] = now_instant()
        document["verified_by_representative_id"] = g.user_id
        bump(document)
        if veteran is not None:
            veteran["character_of_service"] = \
                document["claimed_character_of_service"]
            veteran["wartime_service_days"] = \
                calc.wartime_service_days(veteran["id"])
            calc.refresh_discharge_mirror(veteran)
            veteran["priority_group"] = calc.priority_group(veteran)
            bump(veteran)
    elif action == "HOLD_DISCREPANCY":
        document["verification_status"] = "DISCREPANCY_HELD"
        document["discrepancy_reason"] = body["reason"]
        bump(document)
        if veteran is not None:
            calc.refresh_discharge_mirror(veteran)
            bump(veteran)
    else:
        document["verification_status"] = "REJECTED"
        document["discrepancy_reason"] = body["reason"]
        bump(document)
        if veteran is not None:
            calc.refresh_discharge_mirror(veteran)
            bump(veteran)
    return object_response(view(document))


@bp.post("/discharge-documents/<row_id>/resubmit")
def resubmit_document(row_id):
    authorize(FRONT_DESK)
    body = check_shape({
        "optional": ["claimed_service_start", "claimed_service_end",
                     "claimed_character_of_service"],
        "service_dates": ("claimed_service_start", "claimed_service_end"),
    })
    document = need_document(row_id)
    start = body.get("claimed_service_start", document["claimed_service_start"])
    end = body.get("claimed_service_end", document["claimed_service_end"])
    if parse_date(end) < parse_date(start):
        raise ApiError("ERR_INVALID_SERVICE_DATES",
                       "claimed_service_end is earlier than claimed_service_start")

    def from_state():
        if document["verification_status"] != "DISCREPANCY_HELD":
            invalid_transition("resubmission is not available from %s"
                               % (document["verification_status"],))

    run_checks([(40, from_state)])
    for field in ("claimed_service_start", "claimed_service_end",
                  "claimed_character_of_service"):
        if field in body:
            document[field] = body[field]
    document["discrepancy_reason"] = None
    document["resubmission_count"] = document["resubmission_count"] + 1
    document["verification_status"] = "PENDING_VERIFICATION"
    bump(document)
    veteran = db.veterans.get(document["veteran_id"])
    if veteran is not None:
        calc.refresh_discharge_mirror(veteran)
        bump(veteran)
    return object_response(view(document))
