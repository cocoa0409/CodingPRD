"""Placement endpoints: confirmation, removal, completion and the money
dimension (PRD 3.6 and 3.9)."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import flows
import matcher
import shapes
import store
import views
from auth import endpoint
from errors import ApiError
from routes.candidates import set_state_report_deadline

bp = Blueprint("placements", __name__)

READERS = ["PlacementCoordinator", "ProgramAdmin", "UniversitySupervisorUser",
           "CandidateUser"]


def _placement_state_invalid(message):
    return ApiError("ERR_PLACEMENT_STATE_INVALID", message)


def _stipend_state_invalid(message):
    return ApiError("ERR_STIPEND_STATE_INVALID", message)


def _has_district_fingerprint(candidate):
    derive.sweep_candidate_items(candidate)
    for item in store.items_of(candidate["id"]):
        if item["item_type"] != "BACKGROUND_CLEARANCE":
            continue
        if item["status"] != "VERIFIED":
            continue
        if item["clearance_scope"] != "DISTRICT_FINGERPRINT":
            continue
        return True
    return False


@bp.get("/epp/placements/<placement_id>")
@endpoint(READERS)
def read_placement(placement_id):
    row = store.get_placement(placement_id)
    derive.derive_placement_observations(row)
    return envelope.ok(views.dump(row, views.PLACEMENT))


@bp.get("/epp/placements")
@endpoint(["PlacementCoordinator", "ProgramAdmin", "SupervisionLead"])
def list_placements():
    page, page_size = shapes.pagination(request.args)
    filters = [
        ("request_id", "request_id"),
        ("candidate_id", "candidate_id"),
        ("cooperating_teacher_id", "cooperating_teacher_id"),
        ("agreement_id", "agreement_id"),
        ("supervisor_id", "supervisor_id"),
        ("replaces_placement_id", "replaces_placement_id"),
    ]
    status = shapes.query_enum(request.args, "placement_status",
                               shapes.PLACEMENT_STATUSES)
    rows = []
    for row in store.all_of(store.PLACEMENTS):
        keep = True
        for arg, field in filters:
            wanted = request.args.get(arg) or None
            if wanted is not None and row[field] != wanted:
                keep = False
                break
        if not keep:
            continue
        if status is not None and row["placement_status"] != status:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.PLACEMENT),
                            page, page_size, total)


@bp.post("/epp/placements/<placement_id>/confirm")
@endpoint(["PlacementCoordinator"])
def confirm_placement(placement_id):
    row = store.get_placement(placement_id)
    agreement = store.AGREEMENTS.get(row["agreement_id"])
    teacher = store.TEACHERS.get(row["cooperating_teacher_id"])
    candidate = store.CANDIDATES.get(row["candidate_id"])
    supervisor = store.SUPERVISORS.get(row["supervisor_id"])

    # Rung 14 -- lazy agreement expiry.
    if agreement is not None:
        derive.expire_agreement(agreement)
        if agreement["status"] == "EXPIRED":
            raise ApiError("ERR_AGREEMENT_EXPIRED",
                           "The backing partnership agreement has expired.")
        # Rung 15 -- the agreement must be ACTIVE.
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                           "The backing partnership agreement is not ACTIVE.")

    # Rung 17 -- clinical state.
    if row["placement_status"] != "PROPOSED":
        raise _placement_state_invalid(
            "Only a PROPOSED placement may be confirmed.")

    # Rung 22 -- lazy training expiry.
    if teacher is not None:
        derive.expire_teacher_training(teacher)
        if teacher["qualification_status"] == "TRAINING_EXPIRED":
            raise ApiError("ERR_TEACHER_TRAINING_EXPIRED",
                           "The cooperating teacher's training has lapsed.")

    # Rung 24 -- the district fingerprint sub-gate precedes the score gate.
    district = flows.district_of_placement(row)
    if (district is not None and district.get("requires_district_fingerprint")
            and candidate is not None):
        if not _has_district_fingerprint(candidate):
            raise ApiError(
                "ERR_FINGERPRINT_CLEARANCE_REQUIRED",
                "The district requires a VERIFIED, unexpired "
                "DISTRICT_FINGERPRINT background clearance.")

    # Rung 25 -- aggregate readiness.
    if candidate is not None:
        if derive.evaluate_readiness(candidate, "STRICT") != "READY":
            raise ApiError("ERR_CANDIDATE_NOT_READY",
                           "The candidate is not READY under the STRICT "
                           "readiness evaluation.")

    # Rung 26 -- teacher qualification.
    if teacher is not None and teacher["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_TEACHER_NOT_QUALIFIED",
                       "The cooperating teacher is not QUALIFIED.")

    # Rung 31 -- the padded turnaround window.
    if teacher is not None and matcher.teacher_turnaround_conflict(
            teacher, row["start_date"], row["end_date"],
            ignore_placement_id=row["id"]):
        raise ApiError("ERR_TEACHER_TURNAROUND_CONFLICT",
                       "The cooperating teacher's turnaround window is not "
                       "clear of this term.")

    # Rung 44 -- supervisor caseload re-scored at the ACTIVE base.
    if supervisor is not None:
        derive.derive_supervisor(supervisor)
        travel = derive.supervisor_travel_miles(row)
        projected = (int(supervisor["caseload_points"])
                     - int(row["supervisor_points"] or 0)
                     + calc.stage_points("ACTIVE", travel))
        if projected > int(supervisor["max_caseload_points"]):
            raise ApiError("ERR_SUPERVISOR_CASELOAD_EXCEEDED",
                           "The supervisor's caseload would exceed its "
                           "ceiling.")

    # Rung 45 -- the hard placement cap.
    if agreement is not None:
        derive.derive_agreement_ledger(agreement)
        if agreement["seats_committed"] >= agreement["placement_cap"]:
            raise ApiError("ERR_PLACEMENT_CAP_EXCEEDED",
                           "The agreement has no committed seat left.")

    row["placement_status"] = "ACTIVE"
    store.touch(row)
    derive.derive_placement_points(row)
    flows.accrue_provisional(row)
    flows.refresh_teacher(row)
    flows.refresh_supervisor(row)
    flows.refresh_agreement(row)

    request_row = store.REQUESTS.get(row["request_id"])
    if request_row is not None:
        request_row["status"] = "MATCHED"
        request_row["current_placement_id"] = row["id"]
        store.touch(request_row)
    return envelope.ok(views.dump(row, views.PLACEMENT))


@bp.post("/epp/placements/<placement_id>/removal-request")
@endpoint(["PlacementCoordinator", "SupervisionLead"])
def removal_request(placement_id):
    row = store.get_placement(placement_id)
    body = shapes.body_of(request)
    reason = shapes.req_enum(body, "removal_reason", shapes.REMOVAL_REASONS)
    narrative = shapes.req_str(body, "removal_narrative", 1, None)

    # Rung 17 -- only an ACTIVE placement admits a removal case.
    if row["placement_status"] != "ACTIVE":
        raise _placement_state_invalid(
            "Only an ACTIVE placement may be removal-pended.")

    flows.enter_removal_pending(row, reason, auth.role(), auth.user_id(),
                               narrative)
    return envelope.ok(views.dump(row, views.PLACEMENT))


@bp.post("/epp/placements/<placement_id>/removal-decision")
@endpoint(["ProgramAdmin"])
def removal_decision(placement_id):
    row = store.get_placement(placement_id)
    body = shapes.body_of(request)
    decision = shapes.req_enum(body, "decision", ("UPHELD", "DISMISSED"))
    shapes.opt_str(body, "decision_note", 1, None)

    # Rung 17 -- only an open case may be decided.
    if row["placement_status"] != "REMOVAL_PENDING":
        raise _placement_state_invalid(
            "Only a REMOVAL_PENDING placement may be decided.")

    # Rung 23 -- segregation of duties.
    requester = row.get("removal_requested_by_user_id")
    if requester is not None and requester == auth.user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The deciding principal filed this removal request.")

    if decision == "UPHELD":
        flows.uphold_removal(row, auth.user_id())
    else:
        row["placement_status"] = "ACTIVE"
        row["removal_decided_by_user_id"] = auth.user_id()
        store.touch(row)
        derive.derive_placement_points(row)
        flows.refresh_teacher(row)
        flows.refresh_supervisor(row)
        flows.refresh_agreement(row)
    return envelope.ok(views.dump(row, views.PLACEMENT))


@bp.post("/epp/placements/<placement_id>/complete")
@endpoint(["PlacementCoordinator"])
def complete_placement(placement_id):
    row = store.get_placement(placement_id)

    # Rung 17 -- clinical state.
    if row["placement_status"] != "ACTIVE":
        raise _placement_state_invalid(
            "Only an ACTIVE placement may be completed.")

    # Rung 40 -- the term must have ended.
    if clock.today() < row["end_date"]:
        raise ApiError("ERR_TERM_NOT_ENDED",
                       "The placement's term has not ended yet.")

    # Rung 41 -- the observation gate.
    derive.derive_placement_observations(row)
    if (not derive.ratio_is_one(row)
            or int(row["summative_completed_count"]) < 1):
        raise ApiError("ERR_COMPLETION_GATE_UNMET",
                       "The placement needs a compliance ratio of exactly 1.0 "
                       "and at least one completed summative cycle.")

    # Rung 42 -- the performance assessment must have passed.
    assessment = store.assessment_of_placement(row["id"])
    if assessment is None or assessment["status"] != "PASSED":
        raise ApiError("ERR_ASSESSMENT_NOT_PASSED",
                       "The placement's performance assessment has not "
                       "passed.")

    row["placement_status"] = "COMPLETED"
    row["completed_at"] = clock.now()
    row["settlement_date"] = clock.today()
    store.touch(row)
    flows.settle_final(row, calc.COMPLETION_PREMIUM_CENTS)
    derive.derive_placement_points(row)
    flows.refresh_teacher(row)
    flows.refresh_supervisor(row)
    flows.refresh_agreement(row)

    candidate = store.CANDIDATES.get(row["candidate_id"])
    if candidate is not None:
        derive.evaluate_readiness(candidate, "ROLLING", force_touch=True)

    request_row = store.REQUESTS.get(row["request_id"])
    if request_row is not None:
        request_row["status"] = "CLOSED"
        request_row["current_placement_id"] = row["id"]
        store.touch(request_row)
        if candidate is not None:
            set_state_report_deadline(candidate, request_row["term_end_date"])
            store.touch(candidate)
    return envelope.ok(views.dump(row, views.PLACEMENT))


STIPEND_MOVES = {
    ("ACCRUED", "APPROVED"),
    ("APPROVED", "PAID"),
    ("ACCRUED", "VOIDED"),
    ("APPROVED", "VOIDED"),
    ("PAID", "CLAWED_BACK"),
}
APPROVABLE_STAGES = ("ACTIVE", "REMOVAL_PENDING", "REMOVED", "COMPLETED")


@bp.post("/epp/placements/<placement_id>/stipend-transition")
@endpoint(["ProgramAdmin"])
def stipend_transition(placement_id):
    row = store.get_placement(placement_id)
    body = shapes.body_of(request)
    target = shapes.req_enum(body, "target_status", shapes.STIPEND_STATUSES)
    shapes.opt_str(body, "note", 1, None)

    current = row["stipend_status"]
    teacher = store.TEACHERS.get(row["cooperating_teacher_id"])
    disqualified = (teacher is not None
                    and teacher["qualification_status"] == "DISQUALIFIED")

    # Rung 18 -- the money dimension's declared moves.
    if (current, target) not in STIPEND_MOVES:
        raise _stipend_state_invalid(
            "The money dimension does not move from %s to %s." %
            (current, target))
    if target == "CLAWED_BACK" and not disqualified:
        raise _stipend_state_invalid(
            "A clawback requires a DISQUALIFIED cooperating teacher.")
    if (target == "APPROVED"
            and row["placement_status"] not in APPROVABLE_STAGES):
        raise _stipend_state_invalid(
            "The placement's clinical stage does not admit an approval.")

    # Rung 27 -- a disqualified teacher's stipend is neither approved nor paid.
    if target in ("APPROVED", "PAID") and disqualified:
        raise ApiError("ERR_TEACHER_DISQUALIFIED",
                       "The cooperating teacher is disqualified.")

    # Rung 46 -- only a FINAL settlement may be paid.
    if target == "PAID" and row["stipend_variant"] != "FINAL":
        raise ApiError("ERR_PROVISIONAL_STIPEND_NOT_PAYABLE",
                       "A provisional accrual must be settled before payment.")

    row["stipend_status"] = target
    if target == "VOIDED":
        row["stipend_gross_cents"] = 0
    elif target == "CLAWED_BACK":
        row["stipend_gross_cents"] = 0
        row["weeks_credited"] = 0
    store.touch(row)
    flows.refresh_agreement(row)
    return envelope.ok(views.dump(row, views.PLACEMENT))
