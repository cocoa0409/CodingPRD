"""Client onboarding, trading status, reverse lookups, billing and indices."""

from flask import Blueprint

import calc
import domain
import enums
import serialize
import shape
from envelope import listed, single
from errors import ApiError
from store import db, order_by_created, touch
from util import num, parse_instant

bp = Blueprint("clients", __name__)

READ_ROLES = enums.ROLE_ALL
CLIENT_SUB_READ = ("BureauAdmin", "PostageManager", "ClientContact")


def scope_client(role, user_id, client_id):
    """Ladder rung 7 for endpoints addressed by a client identifier."""
    if role == "ClientContact" and user_id != client_id:
        raise ApiError("ERR_CLIENT_SCOPE_VIOLATION")


@bp.post("/clients")
def create_client():
    shape.authenticate(("BureauAdmin",))
    body = shape.validate_body(
        {
            "name": {"type": "string", "check": shape.non_blank_len(1, 120)},
            "client_code": {"type": "string", "check": shape.client_code_check},
            "service_fee_rate_per_thousand_cents": {
                "type": "integer",
                "check": shape.int_min(1),
            },
            "billing_terms": {
                "type": "enum",
                "values": enums.BILLING_TERMS,
                "required": False,
                "default": "NET_30",
            },
            "commingle_opt_in": {
                "type": "boolean",
                "required": False,
                "default": True,
            },
        }
    )
    for existing in db.clients.values():
        if existing["client_code"] == body["client_code"]:
            raise ApiError("ERR_DUPLICATE_CLIENT_CODE")
    record = db.insert(
        "clients",
        {
            "name": body["name"],
            "client_code": body["client_code"],
            "service_fee_rate_per_thousand_cents": body[
                "service_fee_rate_per_thousand_cents"
            ],
            "billing_terms": body["billing_terms"],
            "commingle_opt_in": body["commingle_opt_in"],
            "status": "ACTIVE",
            "suspension_reason": None,
            "unbilled_postage_cents": 0,
            "lifetime_pieces_mailed": 0,
        },
    )
    return single(serialize.client(record), 201)


@bp.get("/clients/<client_id>")
def read_client(client_id):
    _user, role = shape.authenticate(READ_ROLES)
    record = domain.get_client(client_id)
    scope_client(role, _user, client_id)
    return single(serialize.client(record))


@bp.post("/clients/<client_id>/status")
def set_client_status(client_id):
    shape.authenticate(("BureauAdmin",))
    body = shape.validate_body(
        {
            "status": {"type": "enum", "values": enums.CLIENT_STATUSES},
            "reason": {"type": "string", "required": False, "nullable": True},
        }
    )
    record = domain.get_client(client_id)
    target = body["status"]
    if target == "SUSPENDED":
        if record["status"] != "ACTIVE":
            raise ApiError("ERR_CLIENT_SUSPENDED")
        record["status"] = "SUSPENDED"
        record["suspension_reason"] = body.get("reason")
    else:
        if record["status"] != "SUSPENDED":
            raise ApiError("ERR_CLIENT_SUSPENDED")
        record["status"] = "ACTIVE"
        record["suspension_reason"] = None
    touch(record)
    return single(serialize.client(record))


@bp.get("/clients/<client_id>/permit-accounts")
def list_client_permits(client_id):
    user, role = shape.authenticate(CLIENT_SUB_READ)
    domain.get_client(client_id)
    scope_client(role, user, client_id)
    records = order_by_created(
        [p for p in db.permit_accounts.values() if p["client_id"] == client_id]
    )
    return listed(records, serialize.permit_account)


@bp.get("/clients/<client_id>/mail-jobs")
def list_client_jobs(client_id):
    user, role = shape.authenticate(
        ("BureauAdmin", "PostageManager", "PresortOperator", "ClientContact")
    )
    domain.get_client(client_id)
    scope_client(role, user, client_id)
    records = order_by_created(
        [j for j in db.mail_jobs.values() if j["client_id"] == client_id]
    )
    return listed(records, serialize.mail_job)


@bp.get("/clients/<client_id>/invoices")
def list_client_invoices(client_id):
    user, role = shape.authenticate(CLIENT_SUB_READ)
    domain.get_client(client_id)
    scope_client(role, user, client_id)
    return listed(domain.client_invoices(client_id), serialize.client_invoice)


@bp.get("/clients/<client_id>/service-level")
def client_service_level(client_id):
    user, role = shape.authenticate(CLIENT_SUB_READ)
    domain.get_client(client_id)
    scope_client(role, user, client_id)

    batch_ids = set()
    for member in db.batch_members.values():
        job = db.mail_jobs.get(member["mail_job_id"])
        if job is not None and job["client_id"] == client_id:
            batch_ids.add(member["commingle_batch_id"])

    population = []
    for record in db.ordered("service_level_records"):
        if record["actual_delivery_days"] is None:
            continue
        container = db.sort_containers.get(record["sort_container_id"])
        if container is None or container["commingle_batch_id"] not in batch_ids:
            continue
        population.append(record)

    zone_index, piece_index, count, on_time = calc.service_level_indexes(population)
    return single(
        {
            "client_id": client_id,
            "zone_weighted_index": num(zone_index),
            "piece_weighted_index": num(piece_index),
            "record_count": count,
            "on_time_count": on_time,
        }
    )


@bp.post("/clients/<client_id>/invoices")
def issue_invoice(client_id):
    shape.authenticate(("PostageManager",))
    body = shape.validate_body(
        {
            "period_start_utc": {"type": "datetime"},
            "period_end_utc": {"type": "datetime"},
        }
    )
    client = domain.get_client(client_id)

    # rung 18
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_SUSPENDED")

    start = parse_instant(body["period_start_utc"])
    end = parse_instant(body["period_end_utc"])
    # rung 37
    if not end > start:
        raise ApiError("ERR_INTERVAL_INVALID")
    # rung 41
    if domain.overlapping_invoice(client_id, start, end) is not None:
        raise ApiError("ERR_BILLING_PERIOD_OVERLAP")

    jobs = [
        job
        for job in db.ordered("mail_jobs")
        if job["client_id"] == client_id
        and job["status"] == "MAILED"
        and job["mailed_at_utc"] is not None
        and start <= job["mailed_at_utc"] <= end
    ]
    # rung 43
    if not jobs:
        raise ApiError("ERR_NO_BILLABLE_JOBS")

    postage = 0
    adjustment = 0
    billed_pieces = 0
    for job in jobs:
        member = domain.member_for_job(job["id"])
        if member is not None:
            postage += member["allocated_postage_cents"]
            adjustment += member["allocated_adjustment_cents"]
        billed_pieces += job["accepted_piece_count"]

    service_fee = calc.service_fee_cents(
        billed_pieces, client["service_fee_rate_per_thousand_cents"]
    )
    invoice = db.insert(
        "client_invoices",
        {
            "client_id": client_id,
            "period_start_utc": start,
            "period_end_utc": end,
            "postage_cents": postage,
            "adjustment_cents": adjustment,
            "service_fee_cents": service_fee,
            "total_cents": postage + adjustment + service_fee,
            "included_job_count": len(jobs),
            "billed_piece_count": billed_pieces,
            "status": "ISSUED",
            "paid_amount_cents": 0,
        },
    )
    for job in jobs:
        job["status"] = "BILLED"
        touch(job)
    client["unbilled_postage_cents"] -= postage + adjustment
    touch(client)
    return single(serialize.client_invoice(invoice), 201)
