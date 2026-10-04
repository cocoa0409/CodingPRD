"""Authorization endpoints: obligating federal funds against the
current-FFY apportionment cell (PRD §3.5)."""
from flask import Blueprint, request

from db import STORE, clock, new_id, now_bookkeeping, touch
from errors import err
from helpers import as_int, as_str, ffy_of, get_body, paginate, req_field, resolve_body_fk
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from serializers import serialize_authorization

bp = Blueprint("authorizations", __name__)


def _resolve_authorization(aid):
    auth = STORE["authorizations"].get(aid)
    if auth is None:
        raise err("ERR_NOT_FOUND", "Authorization not found")
    return auth


def recompute_cell(cell):
    """Invariant I-APPORTION: available == apportioned - obligated."""
    cell["available_cents"] = cell["apportioned_cents"] - cell["obligated_cents"]


def project_authorization(project_id):
    """The authorization belonging to a project (at most one ever exists,
    enforced structurally by the ELIGIBLE gate)."""
    for a in STORE["authorizations"].values():
        if a["project_id"] == project_id:
            return a
    return None


@bp.route("/federal-aid/authorizations", methods=["POST"])
@require_roles("FHWADivisionAdmin")
def create_authorization(user_id, user_role):
    body = get_body()
    # Body FK resolution precedes body well-formedness on plain creates.
    if "project_id" in body and body["project_id"] is not None:
        resolve_body_fk("projects", body["project_id"], "project_id")
    project_id = req_field(body, "project_id")
    project = STORE["projects"][project_id]
    agreement_number = as_str(req_field(body, "agreement_number"), "agreement_number")
    initial = as_int(
        req_field(body, "initial_obligated_cents"), "initial_obligated_cents"
    )
    if initial <= 0:
        raise err(
            "ERR_INVALID_REQUEST", "initial_obligated_cents must be greater than 0"
        )
    # Gate chain per PRD §2.7: 7 STIP, 8 eligibility, 10 environmental,
    # 11 right-of-way, 29 cell existence, 30 availability.
    stip = STORE["stips"][project["stip_id"]]
    if stip["status"] != "APPROVED":
        raise err("ERR_STIP_NOT_APPROVED", "The owning STIP is not APPROVED")
    if project["status"] != "ELIGIBLE":
        raise err("ERR_PROJECT_NOT_ELIGIBLE", "Project is not ELIGIBLE")
    env_cleared = any(
        c["project_id"] == project_id
        and c["kind"] == "ENVIRONMENTAL"
        and c["status"] == "CLEARED"
        for c in STORE["clearances"].values()
    )
    if not env_cleared:
        raise err(
            "ERR_ENVIRONMENTAL_NOT_CLEARED",
            "Project lacks a CLEARED environmental clearance",
        )
    row_cleared = any(
        c["project_id"] == project_id
        and c["kind"] == "RIGHT_OF_WAY"
        and c["status"] == "CLEARED"
        for c in STORE["clearances"].values()
    )
    if not row_cleared:
        raise err(
            "ERR_ROW_NOT_CERTIFIED",
            "Project lacks a CLEARED right-of-way certification",
        )
    cell = None
    current_ffy = ffy_of(clock.dt)
    for a in STORE["apportionments"].values():
        if (
            a["funding_program_id"] == project["funding_program_id"]
            and a["state_code"] == stip["state_code"]
            and a["federal_fiscal_year"] == current_ffy
        ):
            cell = a
            break
    if cell is None:
        raise err(
            "ERR_NO_APPORTIONMENT_FOR_FFY",
            "No apportionment row exists for (program, state, FFY of the clock)",
        )
    available = cell["apportioned_cents"] - cell["obligated_cents"]
    if initial > available:
        raise err(
            "ERR_APPORTIONMENT_EXCEEDED",
            "Obligation exceeds the cell's available_cents",
        )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "project_id": project_id,
        "agreement_number": agreement_number,
        "initial_obligated_cents": initial,
        "apportionment_id": cell["id"],
        "_share_dec": project["_determined_share_dec"],
        "obligated_cents": initial,
        "reimbursed_cents": 0,
        "repaid_cents": 0,
        "cumulative_change_order_federal_cents": 0,
        "status": "OBLIGATED",
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["authorizations"][rec["id"]] = rec
    cell["obligated_cents"] += initial
    recompute_cell(cell)
    touch(cell)
    project["status"] = "AUTHORIZED"
    touch(project)
    return success_object(serialize_authorization(rec), status=201)


@bp.route("/federal-aid/authorizations/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_authorization(aid, user_id, user_role):
    return success_object(serialize_authorization(_resolve_authorization(aid)))


@bp.route("/federal-aid/authorizations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_authorizations(user_id, user_role):
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    apportionment_id = request.args.get("apportionment_id")
    items = list(STORE["authorizations"].values())
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if apportionment_id is not None:
        items = [a for a in items if a["apportionment_id"] == apportionment_id]
    items.sort(key=lambda a: a["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(
        [serialize_authorization(a) for a in page], total, limit, offset
    )
