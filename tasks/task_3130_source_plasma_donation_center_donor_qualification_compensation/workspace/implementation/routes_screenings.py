"""Routes: ScreeningVisit and ScreeningSubRecord lifecycle."""
from flask import Blueprint, request

import db
import errors
import middleware
import response
import services as svc

bp = Blueprint("screenings", __name__)


@bp.post("/donors/<donor_id>/screening-visits")
def schedule_screening(donor_id):
    middleware.require_roles("Recorder")
    donor = svc.get_donor_or_404(donor_id)
    body = middleware.get_body()
    center_id = body.get("center_id")
    if not isinstance(center_id, str) or center_id == "":
        raise errors.err_invalid_request("center_id must be a non-empty string")
    scheduled_for_raw = body.get("scheduled_for")
    sf = db.parse_dt(scheduled_for_raw)
    if sf is None:
        raise errors.err_invalid_request("scheduled_for must be an ISO 8601 datetime")
    with db.lock():
        center = svc.get_center(center_id)
        if center is None:
            raise errors.err_not_found("center_id does not resolve")
        if donor["donor_status"] not in ("APPLICANT", "QUALIFIED"):
            raise errors.err_donor_not_eligible()
        svc.assert_center_operational(center)
        visit = {
            "id": db.next_id(),
            "donor_id": donor["id"],
            "center_id": center_id,
            "scheduled_for": db.ts(sf),
            "_scheduled_for_dt": sf,
            "screening_lane_index": None,
            "identity_verified": False,
            "health_history_recorded": False,
            "physical_exam_recorded": False,
            "viral_marker_recorded": False,
            "visit_status": "SCHEDULED",
        }
        db.stamp_new(visit)
        db.DB["screening_visits"][visit["id"]] = visit
    return response.success_object(svc.screening_visit_view(visit), status=201)


@bp.get("/donors/<donor_id>/screening-visits")
def list_screenings(donor_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Recorder"
    )
    svc.get_donor_or_404(donor_id)
    limit, offset = response.parse_pagination(request.args)
    visit_status = request.args.get("visit_status")
    items = [
        v for v in db.DB["screening_visits"].values() if v["donor_id"] == donor_id
    ]
    if visit_status is not None:
        items = [v for v in items if v["visit_status"] == visit_status]
    items.sort(key=lambda v: v["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list(
        [svc.screening_visit_view(v) for v in page], limit, offset, total
    )


@bp.get("/screening-visits/<visit_id>")
def get_screening(visit_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Recorder"
    )
    visit = svc.get_screening_visit_or_404(visit_id)
    return response.success_object(svc.screening_visit_view(visit))


@bp.post("/screening-visits/<visit_id>/sub-records")
def create_sub_record(visit_id):
    ctx = middleware.require_roles("Recorder")
    visit = svc.get_screening_visit_or_404(visit_id)
    body = middleware.get_body()
    record_type = body.get("record_type")
    if record_type not in svc.RECORD_TYPES:
        raise errors.err_invalid_request(
            "record_type must be one of IDENTITY, HEALTH_HISTORY, PHYSICAL_EXAM, VIRAL_MARKER"
        )
    payload = body.get("payload")
    with db.lock():
        if visit["visit_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise errors.err_invalid_state(
                "screening visit must be SCHEDULED or IN_PROGRESS to accept sub-records"
            )
        if svc.sub_record_of_type(visit["id"], record_type) is not None:
            raise errors.err_duplicate_sub_record()
        # Payload validation + outcome computation.
        outcome = svc.validate_sub_record_payload(record_type, payload)

        now = db.now()
        donor = svc.get_donor(visit["donor_id"])
        first_write = visit["visit_status"] == "SCHEDULED"
        if first_write:
            sf = visit["_scheduled_for_dt"]
            if now >= sf + svc.SCREENING_EXPIRY:
                visit["visit_status"] = "EXPIRED"
                db.touch(visit)
                svc.write_snapshot(visit["center_id"], "screening.expired")
                raise errors.err_invalid_state("screening visit has expired")
            visit["visit_status"] = "IN_PROGRESS"
            center = svc.get_center(visit["center_id"])
            if center is not None:
                svc.assign_lane(center, visit)
            db.touch(visit)
            svc.write_snapshot(visit["center_id"], "screening.started")

        flag_field = {
            "IDENTITY": "identity_verified",
            "HEALTH_HISTORY": "health_history_recorded",
            "PHYSICAL_EXAM": "physical_exam_recorded",
            "VIRAL_MARKER": "viral_marker_recorded",
        }[record_type]
        visit[flag_field] = True
        db.touch(visit)

        record = {
            "id": db.next_id(),
            "screening_visit_id": visit["id"],
            "record_type": record_type,
            "payload": payload,
            "recorded_by_user_id": ctx.user_id,
            "outcome": outcome,
        }
        db.stamp_new(record)
        db.DB["screening_sub_records"][record["id"]] = record

        if record_type == "PHYSICAL_EXAM" and donor is not None:
            donor["weight_kg"] = payload["weight_kg"]
            db.touch(donor)

        if outcome == "FAIL" and visit["visit_status"] == "IN_PROGRESS":
            visit["visit_status"] = "FAILED"
            db.touch(visit)
            if record_type == "VIRAL_MARKER" and donor is not None:
                svc.open_lookback_case(donor, record, now)
            svc.write_snapshot(visit["center_id"], "screening.failed")

    return response.success_object(svc.sub_record_view(record), status=201)


@bp.get("/screening-visits/<visit_id>/sub-records")
def list_sub_records(visit_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Recorder"
    )
    svc.get_screening_visit_or_404(visit_id)
    limit, offset = response.parse_pagination(request.args)
    record_type = request.args.get("record_type")
    items = svc.sub_records_of(visit_id)
    if record_type is not None:
        items = [r for r in items if r["record_type"] == record_type]
    items.sort(key=lambda r: r["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list(
        [svc.sub_record_view(r) for r in page], limit, offset, total
    )


@bp.post("/screening-visits/<visit_id>/clear")
def clear_screening(visit_id):
    ctx = middleware.require_roles("MedicalScreener")
    visit = svc.get_screening_visit_or_404(visit_id)
    middleware.get_body()
    with db.lock():
        if visit["visit_status"] != "IN_PROGRESS":
            raise errors.err_visit_not_in_progress()
        center = svc.get_center(visit["center_id"])
        if center is not None:
            svc.assert_center_operational(center)
        donor = svc.get_donor(visit["donor_id"])
        if donor is None or donor["donor_status"] not in ("APPLICANT", "QUALIFIED"):
            raise errors.err_donor_not_eligible()
        records = svc.sub_records_of(visit["id"])
        if not (
            visit["identity_verified"]
            and visit["health_history_recorded"]
            and visit["physical_exam_recorded"]
            and visit["viral_marker_recorded"]
        ):
            raise errors.err_incomplete_screening()
        if any(r["outcome"] != "PASS" for r in records):
            raise errors.err_screening_not_passable()
        if ctx.user_id in {r["recorded_by_user_id"] for r in records}:
            raise errors.err_segregation_of_duties()
        visit["visit_status"] = "CLEARED"
        db.touch(visit)
        svc.write_snapshot(visit["center_id"], "screening.cleared")
    return response.success_object(svc.screening_visit_view(visit))
