"""Quantification runs and credit issuance (sections 3.6 and 3.7)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, payments, serialize

bp = Blueprint("runs", __name__)

METHODS = ("MODEL", "MEASUREMENT")

FILTERS = {
    "enrollment_id": ("enrollment_id", "str"),
    "baseline_id": ("baseline_id", "str"),
    "crop_year": ("crop_year", "int"),
    "status": ("status", "str"),
    "method": ("method", "str"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER, mw.ROLE_REGISTRY_OFFICER)


def passed_packets(enrollment_id, crop_year):
    return [
        p for p in db.sorted_rows(db.data_packets)
        if p["enrollment_id"] == enrollment_id
        and p["crop_year"] == crop_year
        and p["qc_status"] == "PASSED"
    ]


def check_standard_version(enrollment):
    standard = db.practice_standards[enrollment["practice_standard_id"]]
    if enrollment["pinned_standard_version"] != standard["standard_version"]:
        common.fail("ERR_STANDARD_VERSION_MISMATCH")
    return standard


def compute(run, enrollment, baseline, standard):
    figures = calc.quantify(
        run["method"], passed_packets(enrollment["id"], run["crop_year"]),
        enrollment, baseline, standard, common.fail,
    )
    run.update(figures)
    return run


@bp.route("/quantification-runs", methods=["POST"])
def create_run():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    body = v.json_body()
    enrollment_id = v.v_str(body, "enrollment_id")
    baseline_id = v.v_str(body, "baseline_id")
    crop_year = v.v_crop_year(body, "crop_year")
    method = v.v_enum(body, "method", METHODS)
    expected_version = v.v_int(body, "expected_enrollment_version")

    enrollment = common.get_enrollment(enrollment_id)
    baseline = common.get_baseline(baseline_id)

    window_low = enrollment["start_crop_year"]
    window_high = enrollment["start_crop_year"] + enrollment["commitment_years"] - 1
    if crop_year < window_low or crop_year > window_high:
        v.bad("Field 'crop_year' must lie inside the enrollment's commitment window.")
    if crop_year > db.current_crop_year():
        v.bad("Field 'crop_year' may not be later than the current crop year.")

    if enrollment["status"] != "ACTIVE":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Quantification requires an ACTIVE enrollment."
        )

    if expected_version != enrollment["version"]:
        common.fail("ERR_STALE_ENROLLMENT_VERSION")

    standard = check_standard_version(enrollment)

    if baseline["enrollment_id"] != enrollment["id"]:
        common.fail("ERR_BASELINE_ENROLLMENT_MISMATCH")
    if baseline["status"] != "APPROVED":
        common.fail("ERR_BASELINE_NOT_APPROVED")

    row = {
        "enrollment_id": enrollment["id"],
        "baseline_id": baseline["id"],
        "crop_year": crop_year,
        "method": method,
    }
    figures = calc.quantify(
        method, passed_packets(enrollment["id"], crop_year),
        enrollment, baseline, standard, common.fail,
    )

    for other in db.sorted_rows(db.quantification_runs):
        if (
            other["enrollment_id"] == enrollment["id"]
            and other["crop_year"] == crop_year
            and other["status"] != "REJECTED"
        ):
            common.fail("ERR_DUPLICATE_QUANTIFICATION_RUN")

    stored = db.common_fields()
    stored.update(row)
    stored.update(figures)
    stored.update({"status": "DRAFT", "revision_count": 0})
    db.quantification_runs[stored["id"]] = stored
    db.touch(enrollment)
    return resp.object_response(serialize.quantification_run(stored), 201)


@bp.route("/quantification-runs", methods=["GET"])
def list_runs():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.quantification_runs.values(), FILTERS)
    return resp.paginate(rows, serialize.quantification_run)


@bp.route("/quantification-runs/<quantification_run_id>", methods=["GET"])
def read_run(quantification_run_id):
    mw.authorize(*READ_ROLES)
    row = common.get_quantification_run(quantification_run_id)
    mw.require_grower_owner(common.run_grower_id(row))
    return resp.object_response(serialize.quantification_run(row))


@bp.route("/quantification-runs/<quantification_run_id>/submit", methods=["POST"])
def submit_run(quantification_run_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    run = common.get_quantification_run(quantification_run_id)
    v.json_body()
    if run["status"] != "DRAFT":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT run may be submitted.")
    run["status"] = "SUBMITTED"
    db.touch(run)
    return resp.object_response(serialize.quantification_run(run))


@bp.route("/quantification-runs/<quantification_run_id>/revise", methods=["POST"])
def revise_run(quantification_run_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    run = common.get_quantification_run(quantification_run_id)
    body = v.json_body()
    method = v.v_enum(body, "method", METHODS, required=False)
    if run["status"] != "REJECTED":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only a REJECTED run may be revised.")
    enrollment = db.enrollments[run["enrollment_id"]]
    baseline = db.baselines[run["baseline_id"]]
    standard = db.practice_standards[enrollment["practice_standard_id"]]
    if method is not None:
        run["method"] = method
    compute(run, enrollment, baseline, standard)
    run["status"] = "DRAFT"
    run["revision_count"] = run["revision_count"] + 1
    db.touch(run)
    return resp.object_response(serialize.quantification_run(run))


@bp.route("/quantification-runs/<quantification_run_id>/issue", methods=["POST"])
def issue_run(quantification_run_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    run = common.get_quantification_run(quantification_run_id)
    body = v.json_body()
    vintage_year = v.v_crop_year(body, "vintage_year")
    supersedes_batch_id = v.v_str(body, "supersedes_batch_id", required=False)
    registry_account_ref = v.v_str(body, "registry_account_ref", required=False)
    if vintage_year != run["crop_year"]:
        v.bad("Field 'vintage_year' must equal the run's crop_year.")

    enrollment = db.enrollments[run["enrollment_id"]]
    if run["status"] != "VERIFIED":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only a VERIFIED run may be issued.")
    for verification in db.verifications.values():
        if verification["quantification_run_id"] == run["id"] and verification["opinion"] == "ADVERSE":
            common.fail(
                "ERR_INVALID_STATE_TRANSITION",
                "A run carrying an ADVERSE verification opinion may not be issued.",
            )
    if enrollment["status"] != "ACTIVE":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Issuance requires an ACTIVE enrollment.")

    standard = check_standard_version(enrollment)

    superseded = None
    if supersedes_batch_id is not None:
        superseded = common.get_credit_batch(supersedes_batch_id)
        if superseded["enrollment_id"] != enrollment["id"]:
            common.fail("ERR_SUPERSEDED_BATCH_MISMATCH")

    grower = db.growers[enrollment["grower_id"]]
    pool = db.buffer_pool()
    split = calc.issuance_split(run["net_removals_t"], standard, grower)

    if pool["pool_status"] != "HEALTHY":
        common.fail("ERR_BUFFER_POOL_DEFICIT", "The programme buffer pool is in DEFICIT.")
    prospective_balance = pool["balance_credits"] + split["buffer_credits"]
    prospective_outstanding = pool["outstanding_issued_credits"] + split["issued_credits"]
    prospective_required = calc.required_reserve(
        pool["min_reserve_ratio"], prospective_outstanding
    )
    if prospective_balance < prospective_required:
        common.fail(
            "ERR_BUFFER_POOL_DEFICIT",
            "The buffer contribution would leave the pool below its required reserve.",
        )

    serial_start = pool["next_serial_number"]
    serial_end = serial_start + split["issued_credits"] - 1

    batch = db.common_fields()
    batch.update({
        "enrollment_id": enrollment["id"],
        "quantification_run_id": run["id"],
        "supersedes_batch_id": superseded["id"] if superseded is not None else None,
        "vintage_year": vintage_year,
        "gross_credits": split["gross_credits"],
        "buffer_pct": split["buffer_pct"],
        "buffer_credits": split["buffer_credits"],
        "issued_credits": split["issued_credits"],
        "risk_tier": split["risk_tier"],
        "serial_start": serial_start,
        "serial_end": serial_end,
        "issuance_status": "ISSUED",
        "registry_status": "UNLISTED",
        "registry_account_ref": registry_account_ref,
        "retirement_beneficiary": None,
        "cancellation_reason": None,
    })
    db.credit_batches[batch["id"]] = batch

    run["status"] = "ISSUED"
    db.touch(run)

    pool["contributed_total"] = pool["contributed_total"] + split["buffer_credits"]
    pool["balance_credits"] = pool["balance_credits"] + split["buffer_credits"]
    pool["outstanding_issued_credits"] = (
        pool["outstanding_issued_credits"] + split["issued_credits"]
    )
    pool["next_serial_number"] = pool["next_serial_number"] + split["issued_credits"]
    common.recompute_pool(pool)
    db.touch(pool)

    grower["lifetime_credits_issued"] = (
        grower["lifetime_credits_issued"] + split["issued_credits"]
    )
    db.touch(grower)

    enrollment["credits_issued_total"] = (
        enrollment["credits_issued_total"] + split["issued_credits"]
    )
    db.touch(enrollment)

    if enrollment["payment_model"] == "PER_CREDIT":
        payments.accrue_per_credit(enrollment, batch)

    return resp.object_response(serialize.quantification_run(run))
