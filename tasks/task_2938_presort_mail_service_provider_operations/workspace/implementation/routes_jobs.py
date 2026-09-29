"""Mail jobs: tender, hygiene passes, cancellation and computed reads."""

from flask import Blueprint

import calc
import domain
import enums
import serialize
import shape
from envelope import enum_filter, listed, single, str_filter
from errors import ApiError
from routes_clients import scope_client
from store import db, touch
from util import num

bp = Blueprint("jobs", __name__)


def _scope_job(role, user_id, job):
    if role == "ClientContact" and user_id != job["client_id"]:
        raise ApiError("ERR_CLIENT_SCOPE_VIOLATION")


def _require_fee_current(permit):
    """Rung 22 — the annual fee must not have lapsed against the logical clock."""
    if permit["annual_fee_paid_through_utc"] < db.now():
        raise ApiError("ERR_PERMIT_ANNUAL_FEE_LAPSED")


@bp.post("/mail-jobs")
def create_mail_job():
    user, role = shape.authenticate(("PresortOperator", "ClientContact"))
    body = shape.validate_body(
        {
            "client_id": {"type": "string"},
            "permit_account_id": {"type": "string"},
            "mail_class": {"type": "enum", "values": enums.MAIL_CLASSES},
            "processing_category": {
                "type": "enum",
                "values": enums.PROCESSING_CATEGORIES,
            },
            "declared_piece_count": {"type": "integer"},
            "declared_weight_oz_per_piece": {
                "type": "number",
                "check": shape.weight_check,
            },
        }
    )
    # rung 5 — body foreign keys, client_id before permit_account_id
    client = domain.get_client(body["client_id"])
    permit = domain.get_permit(body["permit_account_id"])
    # rung 7
    scope_client(role, user, body["client_id"])
    # rung 8
    if permit["client_id"] != client["id"]:
        raise ApiError("ERR_PERMIT_CLIENT_MISMATCH")
    # rung 18
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_SUSPENDED")
    # rung 19
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    # rung 22
    _require_fee_current(permit)
    # rung 31
    if body["declared_piece_count"] < 1:
        raise ApiError("ERR_INVALID_PIECE_COUNT")

    record = db.insert(
        "mail_jobs",
        {
            "client_id": client["id"],
            "permit_account_id": permit["id"],
            "commingle_batch_id": None,
            "mail_class": body["mail_class"],
            "processing_category": body["processing_category"],
            "declared_piece_count": body["declared_piece_count"],
            "declared_weight_oz_per_piece": body["declared_weight_oz_per_piece"],
            "status": "RECEIVED",
            "accepted_piece_count": body["declared_piece_count"],
            "hygiene_run_count": 0,
            "rework_count": 0,
            "address_quality_pct": 0,
            "move_update_compliant": False,
            "postage_due_cents": 0,
            "mailed_at_utc": None,
            "cancel_reason": None,
        },
    )
    return single(serialize.mail_job(record), 201)


@bp.get("/mail-jobs/<job_id>")
def read_mail_job(job_id):
    user, role = shape.authenticate(enums.ROLE_ALL)
    record = domain.get_job(job_id)
    _scope_job(role, user, record)
    return single(serialize.mail_job(record))


@bp.get("/mail-jobs")
def list_mail_jobs():
    shape.authenticate(("BureauAdmin", "PostageManager", "PresortOperator"))
    client_id = str_filter("client_id")
    permit_id = str_filter("permit_account_id")
    batch_id = str_filter("commingle_batch_id")
    status = enum_filter("status", enums.JOB_STATUSES)
    records = []
    for job in db.ordered("mail_jobs"):
        if client_id is not None and job["client_id"] != client_id:
            continue
        if permit_id is not None and job["permit_account_id"] != permit_id:
            continue
        if batch_id is not None and job["commingle_batch_id"] != batch_id:
            continue
        if status is not None and job["status"] != status:
            continue
        records.append(job)
    return listed(records, serialize.mail_job)


@bp.post("/mail-jobs/<job_id>/hygiene-runs")
def create_hygiene_run(job_id):
    shape.authenticate(("PresortOperator",))
    body = shape.validate_body(
        {
            "submitted_piece_count": {"type": "integer"},
            "cass_matched_count": {"type": "integer"},
            "ncoa_move_updated_count": {"type": "integer"},
            "undeliverable_removed_count": {"type": "integer"},
            "move_update_age_days": {"type": "integer"},
        }
    )
    job = domain.get_job(job_id)
    # rung 10
    if job["status"] not in ("RECEIVED", "HYGIENE_CLEARED"):
        raise ApiError("ERR_INVALID_JOB_STATE")
    client = domain.get_client(job["client_id"])
    permit = domain.get_permit(job["permit_account_id"])
    # rung 18
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_SUSPENDED")
    # rung 19
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_ACCOUNT_NOT_ACTIVE")
    # rung 22
    _require_fee_current(permit)
    # rung 31
    submitted = body["submitted_piece_count"]
    if submitted < 1:
        raise ApiError("ERR_INVALID_PIECE_COUNT")
    if body["cass_matched_count"] < 0 or body["cass_matched_count"] > submitted:
        raise ApiError("ERR_INVALID_PIECE_COUNT")
    if (
        body["ncoa_move_updated_count"] < 0
        or body["ncoa_move_updated_count"] > submitted
    ):
        raise ApiError("ERR_INVALID_PIECE_COUNT")
    if (
        body["undeliverable_removed_count"] < 0
        or body["undeliverable_removed_count"] >= submitted
    ):
        raise ApiError("ERR_INVALID_PIECE_COUNT")
    if body["move_update_age_days"] < 0:
        raise ApiError("ERR_INVALID_PIECE_COUNT")

    quality = calc.address_quality_pct(body["cass_matched_count"], submitted)
    compliant = calc.move_update_compliant(body["move_update_age_days"])
    run = db.insert(
        "hygiene_runs",
        {
            "mail_job_id": job["id"],
            "submitted_piece_count": submitted,
            "cass_matched_count": body["cass_matched_count"],
            "ncoa_move_updated_count": body["ncoa_move_updated_count"],
            "undeliverable_removed_count": body["undeliverable_removed_count"],
            "move_update_age_days": body["move_update_age_days"],
            "run_index": job["hygiene_run_count"],
            "net_piece_count": submitted - body["undeliverable_removed_count"],
            "address_quality_pct": quality,
            "move_update_compliant": compliant,
        },
        versioned=False,
    )
    job["hygiene_run_count"] += 1
    job["accepted_piece_count"] = run["net_piece_count"]
    job["address_quality_pct"] = quality
    job["move_update_compliant"] = compliant
    job["status"] = "HYGIENE_CLEARED"
    touch(job)
    return single(serialize.hygiene_run(run), 201)


@bp.get("/mail-jobs/<job_id>/hygiene-runs")
def list_hygiene_runs(job_id):
    user, role = shape.authenticate(
        ("BureauAdmin", "PresortOperator", "AcceptanceClerk", "ClientContact")
    )
    job = domain.get_job(job_id)
    _scope_job(role, user, job)
    return listed(domain.job_hygiene_runs(job_id), serialize.hygiene_run)


@bp.get("/mail-jobs/<job_id>/batch-memberships")
def list_job_memberships(job_id):
    shape.authenticate(
        ("BureauAdmin", "PostageManager", "PresortOperator", "ClientContact")
    )
    domain.get_job(job_id)
    records = [
        m
        for m in db.ordered("batch_members")
        if m["mail_job_id"] == job_id
    ]
    return listed(records, serialize.batch_member)


@bp.post("/mail-jobs/<job_id>/cancel")
def cancel_mail_job(job_id):
    shape.authenticate(("PresortOperator", "BureauAdmin"))
    body = shape.validate_body({"reason": {"type": "string"}})
    job = domain.get_job(job_id)
    # rung 10
    if job["status"] not in ("RECEIVED", "HYGIENE_CLEARED"):
        raise ApiError("ERR_INVALID_JOB_STATE")
    job["status"] = "CANCELLED"
    job["cancel_reason"] = body["reason"]
    touch(job)
    return single(serialize.mail_job(job))


@bp.get("/mail-jobs/<job_id>/postage-estimate")
def job_postage_estimate(job_id):
    user, role = shape.authenticate(
        ("BureauAdmin", "PostageManager", "PresortOperator", "ClientContact")
    )
    job = domain.get_job(job_id)
    _scope_job(role, user, job)
    pieces = job["accepted_piece_count"]
    tier, rate, postage = calc.assess_postage(job["mail_class"], pieces, 0)
    return single(
        {
            "mail_job_id": job["id"],
            "piece_count": pieces,
            "standalone_tier": tier,
            "standalone_rate_mills_per_piece": rate,
            "standalone_postage_cents": num(postage),
        }
    )
