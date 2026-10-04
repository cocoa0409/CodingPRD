"""ClinicalImageSubmission endpoints (PRD §3.3, §4)."""

import flask

import db
import response
from errors import fail
from middleware import require
from services import calculations, common


def _guards_for_filing(unit, facility):
    """Priority-4 state gates, in the order PRD §2.12 declares them.

    `ERR_UNIT_DEFERRED` is evaluated before `ERR_ACCREDITATION_LAPSED`; the
    stale-version rejection is the last rung of the same band.
    """
    if unit["unit_status"] != "ENROLLED":
        fail("ERR_UNIT_DEFERRED", "the owning modality unit is not ENROLLED")
    if facility is not None and facility["accreditation_currency"] in ("LAPSED", "SUSPENDED"):
        fail("ERR_ACCREDITATION_LAPSED", "the facility's accreditation has lapsed")


def _enforce_window(unit):
    deadline = unit.get("clinical_deadline_at")
    if deadline is not None and db.parse_ts(deadline) < db.now():
        fail("ERR_SUBMISSION_WINDOW_CLOSED", "the clinical submission window has closed")


def _ensure_plan(facility, submission, deficiency_code, stamp=None):
    plan = common.make_record(
        id=db.new_id(),
        facility_id=facility["id"],
        source_submission_id=submission["id"],
        deficiency_code=deficiency_code,
        plan_status="OPEN",
        deadline_status=None,
        due_at=submission["deficiency_deadline_at"],
        resubmission_deadline_at=submission["deficiency_deadline_at"],
        resubmission_attempts=0,
    )
    common.recompute_deadline_status(plan)
    db.PLANS[plan["id"]] = plan
    return plan


def register_routes(app):

    @app.route("/accreditation/clinical-image-submissions", methods=["POST"])
    @require(["FacilityAdmin"])
    def create_submission(principal):
        payload = common.body()
        common.require_fields(
            payload,
            ["unit_id", "image_type", "submitted_at", "reviewer_note_code",
             "required_view_count", "accepted_view_count", "expected_unit_version"],
        )
        common.check_required_enum(payload, "image_type", "image_type")
        unit = common.get_unit(payload["unit_id"])
        facility = common.facility_of_unit(unit)

        required = common.as_int(payload, "required_view_count")
        accepted = common.as_int(payload, "accepted_view_count")
        if accepted < 0 or accepted > required:
            fail("ERR_INVALID_VIEW_COUNT", "accepted_view_count is outside 0..required_view_count")

        parent_id = payload.get("resubmission_of_submission_id")
        parent = None
        if parent_id is not None:
            parent = common.get_submission(parent_id)

        _guards_for_filing(unit, facility)
        common.enforce_version(unit, payload, "expected_unit_version")
        _enforce_window(unit)

        if parent is not None:
            if parent["unit_id"] != unit["id"]:
                fail("ERR_RESUBMISSION_CHAIN", "the answered submission belongs to another unit")
            if parent["resubmission_round"] + 1 > 2:
                fail("ERR_RESUBMISSION_LIMIT_EXCEEDED", "the resubmission chain is exhausted")

        round_number = 0 if parent is None else parent["resubmission_round"] + 1
        if round_number > 2:
            fail("ERR_RESUBMISSION_LIMIT_EXCEEDED", "the resubmission chain is exhausted")

        # Causes precede consequences: the parent is only mutated once the new
        # submission is known to be admissible.
        stamp = db.now()
        record = common.make_record(
            id=db.new_id(),
            unit_id=unit["id"],
            image_type=payload["image_type"],
            submitted_at=db.as_ts(payload["submitted_at"]),
            reviewer_note_code=payload["reviewer_note_code"],
            required_view_count=required,
            accepted_view_count=accepted,
            resubmission_of_submission_id=parent_id,
            review_status="PENDING_REVIEW",
            deficiency_code="NONE",
            review_outcome_score=None,
            deficiency_issued_at=None,
            deficiency_deadline_at=None,
            resubmission_round=round_number,
            corrective_action_plan_id=None,
        )
        db.SUBMISSIONS[record["id"]] = record

        if parent is not None:
            common.set_field(parent, "review_status", "RESUBMITTED", stamp)
            common.recompute_deficiency_open_count(unit)

        common.touch(unit, stamp)
        return response.ok(common.serialize(record), 201)

    @app.route("/accreditation/clinical-image-submissions", methods=["GET"])
    @require(["Any"])
    def list_submissions(principal):
        rows = list(db.SUBMISSIONS.values())
        for field in ("unit_id", "review_status", "resubmission_of_submission_id"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/clinical-image-submissions/<submission_id>", methods=["GET"])
    @require(["Any"])
    def read_submission(principal, submission_id):
        return response.ok(common.serialize(common.get_submission(submission_id)))

    @app.route("/accreditation/clinical-image-submissions/<submission_id>/review", methods=["POST"])
    @require(["AccreditationBody"])
    def review_submission(principal, submission_id):
        record = common.get_submission(submission_id)
        payload = common.body()
        review_outcome_input = payload.get("review_outcome")
        if review_outcome_input is not None and review_outcome_input not in (
            "ACCEPT", "ACCEPT_WITH_DEFICIENCY", "FAIL"
        ):
            fail("ERR_INVALID_REQUEST", "invalid value for review_outcome")
        reviewer_category = payload.get("reviewer_deficiency_category")
        if reviewer_category is not None and reviewer_category not in (
            "IMAGE_QUALITY", "POSITIONING", "ARTIFACT", "DOSE"
        ):
            fail("ERR_INVALID_REQUEST", "invalid value for reviewer_deficiency_category")

        if record["review_status"] in ("ACCEPTED", "FAILED", "RESUBMITTED"):
            fail("ERR_ALREADY_TERMINAL", "the submission has already reached a terminal state")
        if record["review_status"] != "PENDING_REVIEW":
            fail("ERR_INVALID_STATE", "the submission is not PENDING_REVIEW")

        unit = common.get_unit(record["unit_id"])
        facility = common.facility_of_unit(unit)

        # A requested acceptance the evidence does not support is refused outright.
        if review_outcome_input == "ACCEPT" and record["accepted_view_count"] < record["required_view_count"]:
            fail("ERR_INVALID_VIEW_COUNT", "accepted_view_count is below required_view_count")

        outcome, deficiency_code, score = calculations.clinical_review_outcome(
            record, review_outcome_input, reviewer_category
        )

        if facility is not None:
            common.recompute_all_deadline_statuses(facility["id"])
        if outcome == "ACCEPT":
            _accept_submission(record, unit, facility, score)
            return response.ok(common.serialize(record))

        if outcome == "ACCEPT_WITH_DEFICIENCY":
            _deficiency_submission(record, unit, facility, deficiency_code, score)
            return response.ok(common.serialize(record))

        _failure_submission(record, unit, facility, score)
        return response.ok(common.serialize(record))

    @app.route("/accreditation/clinical-image-submissions/<submission_id>/resubmit", methods=["POST"])
    @require(["FacilityAdmin"])
    def resubmit_submission(principal, submission_id):
        record = common.get_submission(submission_id)
        payload = common.body()
        common.require_fields(payload, ["submitted_at", "reviewer_note_code", "accepted_view_count",
                                        "expected_unit_version"])
        unit = common.get_unit(record["unit_id"])
        common.enforce_version(unit, payload, "expected_unit_version")
        facility = common.facility_of_unit(unit)

        if record["review_status"] == "RESUBMITTED":
            fail("ERR_ALREADY_TERMINAL", "the submission has already been resubmitted")
        if record["review_status"] not in ("DEFICIENCY", "FAILED"):
            fail("ERR_INVALID_STATE", "the submission is not DEFICIENCY or FAILED")

        plan = _plan_for_senior(record)
        if plan is None:
            fail("ERR_INVALID_STATE", "no actionable corrective action plan answers this submission")
        common.recompute_deadline_status(plan)
        if plan["deadline_status"] not in ("ON_TRACK", "DUE_SOON"):
            fail("ERR_INVALID_STATE", "the answering plan's deadline has run out")

        new_round = record["resubmission_round"] + 1
        if new_round > 2:
            fail("ERR_RESUBMISSION_LIMIT_EXCEEDED", "the resubmission chain is exhausted")

        if facility is not None:
            common.recompute_all_deadline_statuses(facility["id"])
            if common.has_overdue_plan(facility["id"]):
                fail("ERR_DEADLINE_OVERDUE", "the facility holds an overdue corrective action plan")

        accepted = common.as_int(payload, "accepted_view_count")
        if accepted < 0 or accepted > record["required_view_count"]:
            fail("ERR_INVALID_VIEW_COUNT", "accepted_view_count is outside 0..required_view_count")

        stamp = db.now()
        new_record = common.make_record(
            id=db.new_id(),
            unit_id=unit["id"],
            image_type="CLINICAL",
            submitted_at=db.as_ts(payload["submitted_at"]),
            reviewer_note_code=payload["reviewer_note_code"],
            required_view_count=record["required_view_count"],
            accepted_view_count=accepted,
            resubmission_of_submission_id=record["id"],
            review_status="PENDING_REVIEW",
            deficiency_code="NONE",
            review_outcome_score=None,
            deficiency_issued_at=None,
            deficiency_deadline_at=None,
            resubmission_round=new_round,
            corrective_action_plan_id=None,
        )
        db.SUBMISSIONS[new_record["id"]] = new_record
        common.set_field(record, "review_status", "RESUBMITTED", stamp)
        common.recompute_deficiency_open_count(unit)
        common.touch(unit, stamp)
        return response.ok(common.serialize(new_record), 201)


def _plan_for_senior(submission):
    for plan in db.PLANS.values():
        if plan["source_submission_id"] != submission["id"]:
            continue
        if plan["plan_status"] in ("OPEN", "SUBMITTED"):
            return plan
    return None


def _accept_submission(record, unit, facility, score):
    if facility is not None:
        if common.clinical_role_qualifications_unverified(facility["id"]):
            fail("ERR_QUALIFICATION_UNVERIFIED", "a clinical-role qualification is not VERIFIED")
        common.recompute_all_deadline_statuses(facility["id"])
        if common.has_overdue_plan(facility["id"]):
            fail("ERR_DEADLINE_OVERDUE", "the facility holds an overdue corrective action plan")

    stamp = db.now()
    common.set_field(record, "review_status", "ACCEPTED", stamp)
    record["review_outcome_score"] = score
    record["deficiency_code"] = "NONE"
    record["deficiency_issued_at"] = None
    record["deficiency_deadline_at"] = None

    unit["clinical_deadline_at"] = db.shift_days(record["submitted_at"], 547)
    common.touch(unit, stamp)

    for plan in db.PLANS.values():
        if plan["plan_status"] != "SUBMITTED":
            continue
        source = db.SUBMISSIONS.get(plan["source_submission_id"])
        if source is None:
            continue
        answered = common.plan_resubmission_round_has_status(plan, ("ACCEPTED",))
        if answered or source["unit_id"] == unit["id"]:
            common.set_field(plan, "plan_status", "ACCEPTED", stamp)

    common.recompute_deficiency_open_count(unit)
    if facility is not None and unit["deficiency_open_count"] == 0:
        if all(u["deficiency_open_count"] == 0 for u in common.facility_units(facility["id"])):
            facility["payer_participation_status"] = "ACTIVE"


def _deficiency_submission(record, unit, facility, deficiency_code, score):
    stamp = db.now()
    if not any(
        q["personnel_role"] == "MEDICAL_PHYSICIST" and q["credential_status"] == "VERIFIED"
        for q in common.facility_qualifications(facility["id"])
    ):
        fail("ERR_INVALID_STATE", "no verified medical physicist is on the roster")

    common.set_field(record, "review_status", "DEFICIENCY", stamp)
    record["deficiency_code"] = deficiency_code
    record["review_outcome_score"] = score
    record["deficiency_issued_at"] = record["submitted_at"]
    record["deficiency_deadline_at"] = db.extend_deadline(record["submitted_at"], 45)

    plan = _ensure_plan(facility, record, deficiency_code, stamp)
    record["corrective_action_plan_id"] = plan["id"]

    for other in db.PLANS.values():
        if other["id"] == plan["id"]:
            continue
        if other["facility_id"] != facility["id"]:
            continue
        if other["plan_status"] == "SUBMITTED" and other.get("resubmission_deadline_at") is None:
            other["resubmission_deadline_at"] = db.extend_deadline(record["submitted_at"], 45)
            common.touch(other, stamp)

    common.recompute_deficiency_open_count(unit)
    current = unit.get("clinical_deadline_at")
    if current is None or db.parse_ts(current) < db.parse_ts(record["deficiency_deadline_at"]):
        unit["clinical_deadline_at"] = record["deficiency_deadline_at"]
    common.touch(unit, stamp)

    common.recompute_all_deadline_statuses(facility["id"])
    facility["payer_participation_status"] = "AT_RISK"


def _failure_submission(record, unit, facility, score):
    stamp = db.now()
    common.set_field(record, "review_status", "FAILED", stamp)
    record["deficiency_code"] = "IMAGE_QUALITY"
    record["review_outcome_score"] = score
    record["deficiency_issued_at"] = record["submitted_at"]
    record["deficiency_deadline_at"] = db.extend_deadline(record["submitted_at"], 45)

    plan = _ensure_plan(facility, record, "IMAGE_QUALITY", stamp)
    record["corrective_action_plan_id"] = plan["id"]

    common.recompute_deficiency_open_count(unit)
    common.touch(unit, stamp)
    facility["payer_participation_status"] = "AT_RISK"

