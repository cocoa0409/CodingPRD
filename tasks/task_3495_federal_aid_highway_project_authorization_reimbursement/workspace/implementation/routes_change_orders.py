"""ChangeOrder endpoints: cost overruns with the federal participation cap
(PRD §3.8)."""
from flask import Blueprint

from calculations import change_order_participation
from db import STORE, new_id, now_bookkeeping, touch
from errors import err
from helpers import as_enum, as_int, as_str, get_body, paginate, req_field, resolve_body_fk
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes_authorizations import _resolve_authorization, recompute_cell
from serializers import serialize_change_order

bp = Blueprint("change_orders", __name__)


@bp.route("/federal-aid/change-orders", methods=["POST"])
@require_roles("StateDOTEngineer")
def create_change_order(user_id, user_role):
    body = get_body()
    # Body FK resolution precedes body well-formedness on plain creates.
    if "authorization_id" in body and body["authorization_id"] is not None:
        resolve_body_fk("authorizations", body["authorization_id"], "authorization_id")
    authorization_id = req_field(body, "authorization_id")
    auth = STORE["authorizations"][authorization_id]
    description = as_str(req_field(body, "description"), "description")
    delta = as_int(req_field(body, "delta_cost_cents"), "delta_cost_cents")
    if delta <= 0:
        raise err("ERR_INVALID_REQUEST", "delta_cost_cents must be greater than 0")
    project = STORE["projects"][auth["project_id"]]
    if project["status"] != "UNDER_CONSTRUCTION":
        raise err("ERR_INVALID_STATE", "The project is not UNDER_CONSTRUCTION")
    # Change-order intake accepts OBLIGATED or FULLY_DRAWN (unlike vouchers).
    if auth["status"] not in ("OBLIGATED", "FULLY_DRAWN"):
        raise err(
            "ERR_AUTHORIZATION_NOT_OBLIGATED",
            "The authorization is CLOSED",
        )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "authorization_id": authorization_id,
        "description": description,
        "delta_cost_cents": delta,
        "requested_by_user_id": user_id,
        "state_concurred_by_user_id": None,
        "federal_participation_cents": None,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["change_orders"][rec["id"]] = rec
    return success_object(serialize_change_order(rec), status=201)


@bp.route("/federal-aid/change-orders/<cid>/state-concur", methods=["POST"])
@require_roles("StateDOTEngineer")
def state_concur_change_order(cid, user_id, user_role):
    co = STORE["change_orders"].get(cid)
    if co is None:
        raise err("ERR_NOT_FOUND", "ChangeOrder not found")
    get_body()
    if co["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "ChangeOrder is not in REQUESTED")
    # Segregation of duties: the concurring operator must differ from the
    # requester.
    if user_id == co["requested_by_user_id"]:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The concurring operator must differ from the change order requester",
        )
    co["state_concurred_by_user_id"] = user_id
    co["status"] = "STATE_CONCURRED"
    touch(co)
    return success_object(serialize_change_order(co))


@bp.route("/federal-aid/change-orders/<cid>/federal-decide", methods=["POST"])
@require_roles("FHWAReviewer")
def federal_decide_change_order(cid, user_id, user_role):
    co = STORE["change_orders"].get(cid)
    if co is None:
        raise err("ERR_NOT_FOUND", "ChangeOrder not found")
    body = get_body()
    decision = as_enum(req_field(body, "decision"), "decision", ("APPROVE", "REJECT"))
    if co["status"] != "STATE_CONCURRED":
        raise err("ERR_INVALID_STATE", "ChangeOrder is not in STATE_CONCURRED")
    if decision == "REJECT":
        co["status"] = "FEDERAL_REJECTED"
        touch(co)
        return success_object(serialize_change_order(co))
    auth = STORE["authorizations"][co["authorization_id"]]
    participation = change_order_participation(
        co["delta_cost_cents"],
        auth["_share_dec"],
        auth["initial_obligated_cents"],
        auth["cumulative_change_order_federal_cents"],
    )
    cell = STORE["apportionments"][auth["apportionment_id"]]
    available = cell["apportioned_cents"] - cell["obligated_cents"]
    if participation > available:
        raise err(
            "ERR_APPORTIONMENT_EXCEEDED",
            "Change-order draw exceeds the cell's available_cents",
        )
    co["federal_participation_cents"] = participation
    co["status"] = "FEDERAL_APPROVED"
    touch(co)
    auth["obligated_cents"] += participation
    auth["cumulative_change_order_federal_cents"] += participation
    # New headroom returns a FULLY_DRAWN authorization to OBLIGATED.
    if (
        auth["status"] == "FULLY_DRAWN"
        and auth["obligated_cents"] > auth["reimbursed_cents"]
    ):
        auth["status"] = "OBLIGATED"
    touch(auth)
    cell["obligated_cents"] += participation
    recompute_cell(cell)
    touch(cell)
    project = STORE["projects"][auth["project_id"]]
    project["total_estimated_cost_cents"] += co["delta_cost_cents"]
    touch(project)
    return success_object(serialize_change_order(co))


@bp.route("/federal-aid/authorizations/<aid>/change-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_authorization_change_orders(aid, user_id, user_role):
    _resolve_authorization(aid)
    items = [
        c for c in STORE["change_orders"].values() if c["authorization_id"] == aid
    ]
    items.sort(key=lambda c: c["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list([serialize_change_order(c) for c in page], total, limit, offset)
