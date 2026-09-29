"""Verification bodies and third-party verification (section 3.6)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, serialize

bp = Blueprint("verifications", __name__)

PRACTICE_CODES = ("COVER_CROP", "REDUCED_TILLAGE", "NUTRIENT_MANAGEMENT")
OPINIONS = ("POSITIVE", "QUALIFIED", "ADVERSE")

BODY_FILTERS = {
    "status": ("status", "str"),
    "practice_code": ("accredited_practices", "list"),
    "accredited_practice": ("accredited_practices", "list"),
}

VERIFICATION_FILTERS = {
    "quantification_run_id": ("quantification_run_id", "str"),
    "verification_body_id": ("verification_body_id", "str"),
    "opinion": ("opinion", "str"),
    "status": ("opinion", "str"),
}

BODY_READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_VERIFIER, mw.ROLE_REGISTRY_OFFICER)
VERIFICATION_READ_ROLES = (
    mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER, mw.ROLE_REGISTRY_OFFICER,
)


def _require_accredited(body_row):
    """Rung 8 -- the body involved in the write must be ACCREDITED."""
    if body_row["status"] != "ACCREDITED":
        common.fail("ERR_VERIFICATION_BODY_SUSPENDED")


def _window(row):
    return (
        v.parse_date_prefix(row["site_visit_start"]),
        v.parse_date_prefix(row["site_visit_end"]),
    )


def _check_capacity(body_row, start, end, exclude_id=None):
    """Rung 19 -- overlapping PENDING visit windows of the same body."""
    overlapping = 0
    for other in db.sorted_rows(db.verifications):
        if other["verification_body_id"] != body_row["id"]:
            continue
        if other["opinion"] != "PENDING":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        other_start, other_end = _window(other)
        if other_start is None or other_end is None:
            continue
        if other_start <= end and start <= other_end:
            overlapping += 1
    if overlapping >= body_row["max_concurrent_visits"]:
        common.fail("ERR_VERIFIER_CAPACITY_EXCEEDED")


def _visit_window(body, required=True):
    start_raw = v.v_date(body, "site_visit_start", required=required)
    end_raw = v.v_date(body, "site_visit_end", required=required)
    if start_raw is None or end_raw is None:
        return None, None, None, None
    start = v.parse_date_prefix(start_raw)
    end = v.parse_date_prefix(end_raw)
    if end < start:
        v.bad("Field 'site_visit_end' may not be earlier than 'site_visit_start'.")
    return start_raw, end_raw, start, end


# ---------------------------------------------------------------------------
# verification bodies
# ---------------------------------------------------------------------------
@bp.route("/verification-bodies", methods=["POST"])
def create_body():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    body = v.json_body()
    name = v.v_str(body, "name")
    accreditation_id = v.v_str(body, "accreditation_id")
    practices = v.v_str_list(body, "accredited_practices", allowed=PRACTICE_CODES)
    if not practices:
        v.bad("Field 'accredited_practices' must name at least one practice code.")
    max_concurrent_visits = v.v_int(body, "max_concurrent_visits", minimum=1)

    row = db.common_fields()
    row.update({
        "name": name,
        "accreditation_id": accreditation_id,
        "accredited_practices": practices,
        "max_concurrent_visits": max_concurrent_visits,
        "status": "ACCREDITED",
    })
    db.verification_bodies[row["id"]] = row
    return resp.object_response(serialize.verification_body(row), 201)


@bp.route("/verification-bodies", methods=["GET"])
def list_bodies():
    mw.authorize(*BODY_READ_ROLES)
    rows = common.apply_filters(db.verification_bodies.values(), BODY_FILTERS)
    return resp.paginate(rows, serialize.verification_body)


@bp.route("/verification-bodies/<verification_body_id>", methods=["GET"])
def read_body(verification_body_id):
    mw.authorize(*BODY_READ_ROLES)
    row = common.get_verification_body(verification_body_id)
    return resp.object_response(serialize.verification_body(row))


@bp.route("/verification-bodies/<verification_body_id>/suspend", methods=["POST"])
def suspend_body(verification_body_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    row = common.get_verification_body(verification_body_id)
    if row["status"] != "ACCREDITED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only an ACCREDITED body may be suspended."
        )
    row["status"] = "SUSPENDED"
    db.touch(row)
    return resp.object_response(serialize.verification_body(row))


@bp.route("/verification-bodies/<verification_body_id>/reinstate", methods=["POST"])
def reinstate_body(verification_body_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    row = common.get_verification_body(verification_body_id)
    if row["status"] != "SUSPENDED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a SUSPENDED body may be reinstated."
        )
    row["status"] = "ACCREDITED"
    db.touch(row)
    return resp.object_response(serialize.verification_body(row))


# ---------------------------------------------------------------------------
# verifications
# ---------------------------------------------------------------------------
@bp.route("/verifications", methods=["POST"])
def create_verification():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    body = v.json_body()
    quantification_run_id = v.v_str(body, "quantification_run_id")
    verification_body_id = v.v_str(body, "verification_body_id")
    sample_pct = v.v_dec(body, "sample_pct", 2, minimum=0, maximum=100, exclusive_min=True)
    start_raw, end_raw, start, end = _visit_window(body)

    run = common.get_quantification_run(quantification_run_id)
    body_row = common.get_verification_body(verification_body_id)

    _require_accredited(body_row)

    if run["status"] != "SUBMITTED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED run may be assigned for verification."
        )

    _check_capacity(body_row, start, end)

    enrollment = db.enrollments[run["enrollment_id"]]
    if enrollment["practice_code"] not in body_row["accredited_practices"]:
        common.fail("ERR_PRACTICE_NOT_ACCREDITED")

    if sample_pct < calc.SAMPLE_MIN_PCT:
        common.fail("ERR_SAMPLE_TOO_SMALL")

    for other in db.verifications.values():
        if other["quantification_run_id"] == run["id"] and other["opinion"] == "PENDING":
            common.fail("ERR_DUPLICATE_VERIFICATION")

    row = db.common_fields()
    row.update({
        "quantification_run_id": run["id"],
        "verification_body_id": body_row["id"],
        "sample_pct": sample_pct,
        "site_visit_start": start_raw,
        "site_visit_end": end_raw,
        "opinion": "PENDING",
        "restated_removals_t": None,
        "material_discrepancy_pct": Decimal("0.00"),
        "findings_note": None,
        "resample_count": 0,
    })
    db.verifications[row["id"]] = row
    return resp.object_response(serialize.verification(row), 201)


@bp.route("/verifications", methods=["GET"])
def list_verifications():
    mw.authorize(*VERIFICATION_READ_ROLES)
    rows = common.apply_filters(db.verifications.values(), VERIFICATION_FILTERS)
    return resp.paginate(rows, serialize.verification)


@bp.route("/verifications/<verification_id>", methods=["GET"])
def read_verification(verification_id):
    mw.authorize(*VERIFICATION_READ_ROLES)
    row = common.get_verification(verification_id)
    mw.require_verifier_owner(row["verification_body_id"])
    mw.require_grower_owner(common.verification_grower_id(row))
    return resp.object_response(serialize.verification(row))


@bp.route("/verifications/<verification_id>/start-visit", methods=["POST"])
def start_visit(verification_id):
    mw.authorize(mw.ROLE_VERIFIER)
    row = common.get_verification(verification_id)
    mw.require_verifier_owner(row["verification_body_id"])
    body_row = db.verification_bodies[row["verification_body_id"]]
    _require_accredited(body_row)
    if row["opinion"] != "PENDING":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A site visit may only be recorded while the opinion is PENDING.",
        )
    row["site_visit_start"] = db.now_raw()
    db.touch(row)
    return resp.object_response(serialize.verification(row))


@bp.route("/verifications/<verification_id>/opine", methods=["POST"])
def opine(verification_id):
    mw.authorize(mw.ROLE_VERIFIER)
    row = common.get_verification(verification_id)
    mw.require_verifier_owner(row["verification_body_id"])
    body = v.json_body()
    opinion = v.v_enum(body, "opinion", OPINIONS)
    restated = v.v_dec(body, "restated_removals_t", 3, required=False, minimum=0)
    findings_note = v.v_str(body, "findings_note", required=False)

    body_row = db.verification_bodies[row["verification_body_id"]]
    _require_accredited(body_row)

    if row["opinion"] != "PENDING":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a PENDING verification may be opined upon."
        )

    run = db.quantification_runs[row["quantification_run_id"]]
    discrepancy = calc.material_discrepancy_pct(restated, run["net_removals_t"])
    if opinion == "POSITIVE" and discrepancy > calc.MATERIAL_DISCREPANCY_MAX_PCT:
        common.fail("ERR_MATERIAL_DISCREPANCY_EXCEEDED")

    if restated is not None:
        row["restated_removals_t"] = restated
    row["material_discrepancy_pct"] = discrepancy
    row["findings_note"] = findings_note
    row["opinion"] = opinion
    db.touch(row)

    if opinion == "POSITIVE":
        run["status"] = "VERIFIED"
        db.touch(run)
    elif opinion == "ADVERSE":
        run["status"] = "REJECTED"
        db.touch(run)

    return resp.object_response(serialize.verification(row))


@bp.route("/verifications/<verification_id>/resample", methods=["POST"])
def resample(verification_id):
    mw.authorize(mw.ROLE_VERIFIER)
    row = common.get_verification(verification_id)
    mw.require_verifier_owner(row["verification_body_id"])
    body = v.json_body()
    sample_pct = v.v_dec(body, "sample_pct", 2, minimum=0, maximum=100, exclusive_min=True)
    start_raw, end_raw, start, end = _visit_window(body)

    body_row = db.verification_bodies[row["verification_body_id"]]
    _require_accredited(body_row)

    if row["opinion"] != "QUALIFIED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a QUALIFIED verification may be resampled."
        )

    _check_capacity(body_row, start, end, exclude_id=row["id"])

    if sample_pct < calc.SAMPLE_MIN_PCT:
        common.fail("ERR_SAMPLE_TOO_SMALL")

    row["sample_pct"] = sample_pct
    row["site_visit_start"] = start_raw
    row["site_visit_end"] = end_raw
    row["restated_removals_t"] = None
    row["findings_note"] = None
    row["material_discrepancy_pct"] = Decimal("0.00")
    row["resample_count"] = row["resample_count"] + 1
    row["opinion"] = "PENDING"
    db.touch(row)
    return resp.object_response(serialize.verification(row))
