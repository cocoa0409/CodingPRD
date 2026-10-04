"""TransferRequests and CancellationRequests routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_reference_not_found,
    err_invalid_state,
    err_stale_version,
    err_segregation,
    err_transfer_expired,
    err_user_not_active,
    err_cross_org,
    err_duplicate_plan_seat,
    err_monthly_no_etf,
)
from helpers import (
    make_record,
    touch,
    require_fields,
    compute_etf,
    refresh_org,
    revoke_entitlement,
    entitlements_of_seat,
    months_elapsed_between,
)
from middleware import get_identity, require_role, resolve_identity, require_org_scope
from response import (
    success_object,
    success_list,
    paginate,
    now_dt,
    now_iso,
    add_hours,
    add_days,
    iso_no_frac,
    parse_iso,
)

bp = Blueprint("transfers", __name__)


# ---------------- transfer requests ----------------

@bp.post("/licensing/transfer-requests")
def create_transfer_request():
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["org_id", "seat_id", "to_user_id", "requested_by_admin_id", "expected_seat_version"])
    org = db["organizations"].get(payload["org_id"])
    if org is None:
        raise err_reference_not_found("org_id does not exist")
    require_org_scope(identity, org["id"])
    seat = db["seats"].get(payload["seat_id"])
    if seat is None:
        raise err_reference_not_found("seat_id does not exist")
    to_user = db["end_users"].get(payload["to_user_id"])
    if to_user is None:
        raise err_reference_not_found("to_user_id does not exist")
    if payload["requested_by_admin_id"] not in db["admins"]:
        raise err_reference_not_found("requested_by_admin_id does not exist")
    sub = db["subscriptions"].get(seat["subscription_id"])
    if seat["status"] != "ASSIGNED":
        raise err_invalid_state("Seat is not ASSIGNED")
    expected = payload["expected_seat_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_seat_version must be an integer")
    if expected != seat["version"]:
        raise err_stale_version()
    if sub is None or sub["status"] != "ACTIVE":
        raise err_invalid_state("Subscription is not ACTIVE")
    open_tr = any(
        t for t in db["transfer_requests"].values()
        if t["seat_id"] == seat["id"] and t["status"] in ("PENDING_APPROVAL", "APPROVED")
    )
    if open_tr:
        raise err_invalid_state("Another transfer request is open for this seat")
    if to_user["org_id"] != org["id"]:
        raise err_cross_org()
    rec = make_record({
        "org_id": org["id"],
        "seat_id": seat["id"],
        "from_user_id": seat["end_user_id"],
        "to_user_id": to_user["id"],
        "requested_by_admin_id": payload["requested_by_admin_id"],
        "approver_admin_id": None,
        "status": "PENDING_APPROVAL",
        "expires_at": iso_no_frac(add_hours(now_dt(), 72)),
    })
    db["transfer_requests"][rec["id"]] = rec
    seat["status"] = "TRANSFERRING"
    touch(seat)
    return success_object(rec, 201)


@bp.get("/licensing/transfer-requests")
def list_transfer_requests():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["transfer_requests"].values())
    if identity.role == "OrgAdmin" and identity.admin:
        items = [t for t in items if t["org_id"] == identity.admin["org_id"]]
    for key in ("org_id", "seat_id", "from_user_id", "to_user_id", "requested_by_admin_id", "approver_admin_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [t for t in items if str(t.get(key)) == v]
    items.sort(key=lambda t: t["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/transfer-requests/<tid>")
def get_transfer_request(tid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    tr = db["transfer_requests"].get(tid)
    if tr is None:
        raise err_not_found("TransferRequest not found")
    require_org_scope(identity, tr["org_id"])
    return success_object(tr)


@bp.post("/licensing/transfer-requests/<tid>/approve")
def approve_transfer_request(tid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    tr = db["transfer_requests"].get(tid)
    if tr is None:
        raise err_not_found("TransferRequest not found")
    require_org_scope(identity, tr["org_id"])
    if tr["status"] != "PENDING_APPROVAL":
        if identity.admin["id"] == tr["requested_by_admin_id"]:
            raise err_segregation()
        if now_dt() >= parse_iso(tr["expires_at"]):
            raise err_transfer_expired()
        raise err_invalid_state("TransferRequest is not PENDING_APPROVAL")
    if identity.admin["id"] == tr["requested_by_admin_id"]:
        raise err_segregation()
    if now_dt() >= parse_iso(tr["expires_at"]):
        raise err_transfer_expired()
    tr["status"] = "APPROVED"
    tr["approver_admin_id"] = identity.admin["id"]
    touch(tr)
    return success_object(tr)


@bp.post("/licensing/transfer-requests/<tid>/reject")
def reject_transfer_request(tid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    tr = db["transfer_requests"].get(tid)
    if tr is None:
        raise err_not_found("TransferRequest not found")
    require_org_scope(identity, tr["org_id"])
    if tr["status"] != "PENDING_APPROVAL":
        if identity.admin["id"] == tr["requested_by_admin_id"]:
            raise err_segregation()
        raise err_invalid_state("TransferRequest is not PENDING_APPROVAL")
    if identity.admin["id"] == tr["requested_by_admin_id"]:
        raise err_segregation()
    tr["status"] = "REJECTED"
    tr["approver_admin_id"] = identity.admin["id"]
    touch(tr)
    seat = db["seats"].get(tr["seat_id"])
    if seat and seat["status"] == "TRANSFERRING":
        seat["status"] = "ASSIGNED"
        touch(seat)
    return success_object(tr)


@bp.post("/licensing/transfer-requests/<tid>/execute")
def execute_transfer_request(tid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    tr = db["transfer_requests"].get(tid)
    if tr is None:
        raise err_not_found("TransferRequest not found")
    if tr["status"] != "APPROVED":
        raise err_invalid_state("TransferRequest is not APPROVED")
    seat = db["seats"].get(tr["seat_id"])
    sub = db["subscriptions"].get(seat["subscription_id"]) if seat else None
    to_user = db["end_users"].get(tr["to_user_id"])
    if to_user is None or to_user["status"] != "ACTIVE":
        raise err_user_not_active()
    if sub is None or to_user["org_id"] != sub["org_id"]:
        raise err_cross_org()
    # one-seat-per-user-per-plan re-check for recipient
    for s in db["subscriptions"].values():
        if s["org_id"] != sub["org_id"] or s["plan_id"] != sub["plan_id"]:
            continue
        for other in db["seats"].values():
            if other["subscription_id"] != s["id"] or other["id"] == seat["id"]:
                continue
            if other["status"] in ("ASSIGNED", "TRANSFERRING") and other["end_user_id"] == to_user["id"]:
                raise err_duplicate_plan_seat()
    seat["end_user_id"] = to_user["id"]
    seat["assigned_at"] = now_iso()
    seat["status"] = "ASSIGNED"
    touch(seat)
    for ent in entitlements_of_seat(seat["id"]):
        if ent["status"] in ("ACTIVE", "SUSPENDED"):
            ent["device_id"] = None
            ent["status"] = "PENDING_ACTIVATION"
            touch(ent)
    tr["status"] = "EXECUTED"
    touch(tr)
    return success_object(tr)


# ---------------- cancellation requests ----------------

@bp.post("/licensing/cancellation-requests")
def create_cancellation_request():
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["subscription_id", "requested_by_admin_id"])
    sub = db["subscriptions"].get(payload["subscription_id"])
    if sub is None:
        raise err_reference_not_found("subscription_id does not exist")
    require_org_scope(identity, sub["org_id"])
    if payload["requested_by_admin_id"] not in db["admins"]:
        raise err_reference_not_found("requested_by_admin_id does not exist")
    rec = make_record({
        "subscription_id": sub["id"],
        "requested_by_admin_id": payload["requested_by_admin_id"],
        "requested_at": now_iso(),
        "status": "PENDING",
        "etf_amount_cents": 0,
    })
    db["cancellation_requests"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/cancellation-requests")
def list_cancellation_requests():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["cancellation_requests"].values())
    if identity.role == "OrgAdmin" and identity.admin:
        org_id = identity.admin["org_id"]
        sub_org = {s["id"]: s["org_id"] for s in db["subscriptions"].values()}
        items = [c for c in items if sub_org.get(c["subscription_id"]) == org_id]
    for key in ("subscription_id", "requested_by_admin_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if str(c.get(key)) == v]
    items.sort(key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/cancellation-requests/<cid>")
def get_cancellation_request(cid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    cr = db["cancellation_requests"].get(cid)
    if cr is None:
        raise err_not_found("CancellationRequest not found")
    sub = db["subscriptions"].get(cr["subscription_id"])
    require_org_scope(identity, sub["org_id"] if sub else None)
    return success_object(cr)


def _cancel_cascade(sub, target_status):
    sub["status"] = target_status
    touch(sub)
    for seat in db["seats"].values():
        if seat["subscription_id"] != sub["id"]:
            continue
        if seat["status"] == "ASSIGNED":
            seat["status"] = "RECLAIMED"
            seat["end_user_id"] = None
            seat["assigned_at"] = None
            seat["pending_reclaim_not_before"] = None
            seat.pop("_deactivation_initiated", None)
            touch(seat)
    sub["seats_assigned"] = 0
    touch(sub)
    for seat in db["seats"].values():
        if seat["subscription_id"] != sub["id"]:
            continue
        for ent in entitlements_of_seat(seat["id"]):
            revoke_entitlement(ent)
    refresh_org(sub["org_id"])


@bp.post("/licensing/cancellation-requests/<cid>/finalize")
def finalize_cancellation_request(cid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    cr = db["cancellation_requests"].get(cid)
    if cr is None:
        raise err_not_found("CancellationRequest not found")
    if cr["status"] != "PENDING":
        raise err_invalid_state("CancellationRequest is not PENDING")
    sub = db["subscriptions"].get(cr["subscription_id"])
    plan = db["plans"].get(sub["plan_id"]) if sub else None

    def _deny():
        cr["status"] = "DENIED"
        touch(cr)
        return success_object(cr)

    if sub is None or sub["status"] != "ACTIVE":
        return _deny()
    # any seat mid-transfer or pending reclaim blocks cancellation
    for seat in db["seats"].values():
        if seat["subscription_id"] == sub["id"] and seat["status"] in ("PENDING_RECLAIM", "TRANSFERRING"):
            return _deny()
    window_end = add_days(parse_iso(sub["commitment_start"]), plan["cancellation_window_days"])
    now = now_dt()
    if now <= window_end:
        # in-window: full refund
        cr["etf_amount_cents"] = 0
        cr["status"] = "REFUNDED"
        touch(cr)
        _cancel_cascade(sub, "CANCELLED_IN_WINDOW")
        return success_object(cr)
    # out of window
    if plan["billing_model"] == "MONTHLY":
        cr["status"] = "DENIED"
        touch(cr)
        raise err_monthly_no_etf()
    fee = compute_etf(sub)
    cr["etf_amount_cents"] = fee
    cr["status"] = "ETF_CHARGED"
    touch(cr)
    _cancel_cascade(sub, "CANCELLED_ETF")
    return success_object(cr)
