"""Client accounts, their lifecycle, and the client-facing views."""

from flask import Blueprint

from db import STORE
from middleware import body, query, require
from response import array_response, object_response, page
from services import billing, intake
from utils import week_of

bp = Blueprint("clients", __name__)

CLIENT_ROLES = ["ClinicalOps", "BillingOps", "EnrollmentOps"]
STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")


@bp.route("/msk/clients", methods=["POST"])
def create_client():
    require(["ClinicalOps"], "POST /msk/clients")
    payload = body()
    row = intake.create_client(payload)
    # Creating the contract also instantiates the care-track configurations the
    # client will use, when they are supplied with it.
    for spec in payload.get("program_tracks") or []:
        intake.create_track(spec, owner=row["id"])
    row["program_track_ids"] = [
        t["id"] for t in STORE.all("ProgramTrack") if t.get("client_account_id") == row["id"]
    ]
    return object_response(dict(row), 201)


@bp.route("/msk/clients", methods=["GET"])
def list_clients():
    require(CLIENT_ROLES, "GET /msk/clients")
    rows = STORE.all("ClientAccount")
    entitlement = query("entitlement_filter")
    if entitlement is not None and entitlement in STATUSES:
        rows = [r for r in rows if r["account_status"] == entitlement]
    status = query("client_status")
    if status is not None:
        rows = [r for r in rows if r["account_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    items, limit, offset, total = page(rows, query("limit"), query("offset"))
    return array_response([dict(r) for r in items], limit, offset, total)


@bp.route("/msk/clients/<client_id>", methods=["GET"])
def read_client(client_id):
    require(["ClinicalOps", "BillingOps"], "GET /msk/clients/{id}")
    row = STORE.need("ClientAccount", client_id, "ClientAccount")
    return object_response(dict(row))


@bp.route("/msk/clients/<client_id>/engagement-report", methods=["GET"])
def engagement_report(client_id):
    require(
        ["BillingOps", "ClinicalOps"], "GET /msk/clients/{id}/engagement-report"
    )
    return object_response(billing.engagement_report(client_id))


@bp.route("/msk/clients/<client_id>/suspend", methods=["POST"])
def suspend_client(client_id):
    require(["BillingOps"], "POST /msk/clients/{id}/suspend")
    row = intake.suspend_client(client_id, body().get("reason"))
    return object_response(dict(row))


@bp.route("/msk/clients/<client_id>/reinstate", methods=["POST"])
def reinstate_client(client_id):
    require(["BillingOps"], "POST /msk/clients/{id}/reinstate")
    return object_response(dict(intake.reinstate_client(client_id)))


@bp.route("/msk/clients/<client_id>/close", methods=["POST"])
def close_client(client_id):
    require(["BillingOps"], "POST /msk/clients/{id}/close")
    return object_response(dict(intake.close_client(client_id)))


@bp.route("/msk/clients/<client_id>/recompute_engagement-tier", methods=["POST"])
def recompute_tier(client_id):
    require(
        ["BillingOps"], "POST /msk/clients/{id}/recompute_engagement-tier"
    )
    return object_response(dict(intake.recompute_engagement_tier(client_id)))


@bp.route("/msk/clients/<client_id>/retention-credit", methods=["POST"])
def retention_credit(client_id):
    require(["BillingOps"], "POST /msk/clients/{id}/retention-credit")
    return object_response(billing.retention_credit(client_id))


@bp.route("/msk/clients/<client_id>/membership-roll", methods=["POST"])
def membership_roll(client_id):
    require(["BillingOps"], "POST /msk/clients/{id}/membership-roll")
    as_of = body().get("as_of_week_index")
    if as_of is None:
        as_of = week_of(STORE.clock)
    return object_response(billing.membership_roll(client_id, int(as_of)))


@bp.route(
    "/msk/clients/<client_id>/run-weekly-reconciliation", methods=["POST"]
)
def run_weekly(client_id):
    require(
        ["ClinicalOps"], "POST /msk/clients/{id}/run-weekly-reconciliation"
    )
    from services import operations

    return object_response(operations.weekly_reconciliation(client_id))