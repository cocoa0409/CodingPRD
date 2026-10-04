"""Voucher endpoints: progress billing, review, and reimbursement (PRD §3.7)."""
from flask import Blueprint

from calculations import voucher_reimbursement
from db import STORE, new_id, now_bookkeeping, touch
from errors import err
from helpers import (
    as_bool,
    as_datetime,
    as_enum,
    as_int,
    as_str,
    get_body,
    paginate,
    req_field,
    resolve_body_fk,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes_authorizations import _resolve_authorization
from serializers import serialize_voucher

bp = Blueprint("vouchers", __name__)


def _validate_line_items(value):
    if not isinstance(value, list) or len(value) == 0:
        raise err("ERR_INVALID_REQUEST", "line_items must be a non-empty array")
    for entry in value:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "each line item must be an object")
        as_str(req_field(entry, "description"), "description")
        amount = as_int(
            req_field(entry, "eligible_amount_cents"), "eligible_amount_cents"
        )
        if amount <= 0:
            raise err(
                "ERR_INVALID_REQUEST",
                "line item eligible_amount_cents must be greater than 0",
            )
    return value


def _half_open_overlap(s1, e1, s2, e2):
    """Half-open [start, end) intersection; adjacency (end == start) allowed."""
    return s1 < e2 and s2 < e1


@bp.route("/federal-aid/vouchers", methods=["POST"])
@require_roles("StateDOTEngineer")
def create_voucher(user_id, user_role):
    body = get_body()
    # Body FK resolution precedes body well-formedness on plain creates.
    if "authorization_id" in body and body["authorization_id"] is not None:
        resolve_body_fk("authorizations", body["authorization_id"], "authorization_id")
    authorization_id = req_field(body, "authorization_id")
    auth = STORE["authorizations"][authorization_id]
    period_start = req_field(body, "period_start_date")
    period_end = req_field(body, "period_end_date")
    start_dt = as_datetime(period_start, "period_start_date")
    end_dt = as_datetime(period_end, "period_end_date")
    if not end_dt > start_dt:
        raise err(
            "ERR_INVALID_REQUEST",
            "period_end_date must be strictly after period_start_date",
        )
    line_items = _validate_line_items(req_field(body, "line_items"))
    documentation_complete = as_bool(
        req_field(body, "documentation_complete"), "documentation_complete"
    )
    is_final = as_bool(req_field(body, "is_final"), "is_final")
    project = STORE["projects"][auth["project_id"]]
    if project["status"] != "UNDER_CONSTRUCTION":
        raise err(
            "ERR_INVALID_STATE", "The project is not UNDER_CONSTRUCTION"
        )
    if auth["status"] != "OBLIGATED":
        raise err(
            "ERR_AUTHORIZATION_NOT_OBLIGATED",
            "The authorization is not OBLIGATED",
        )
    if is_final:
        for v in STORE["vouchers"].values():
            if (
                v["authorization_id"] == authorization_id
                and v["is_final"]
                and v["status"] != "REJECTED"
            ):
                raise err(
                    "ERR_FINAL_VOUCHER_EXISTS",
                    "A non-REJECTED final voucher already exists for this authorization",
                )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "authorization_id": authorization_id,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "line_items": [dict(li) for li in line_items],
        "documentation_complete": documentation_complete,
        "is_final": is_final,
        "status": "DRAFT",
        "claimed_amount_cents": sum(li["eligible_amount_cents"] for li in line_items),
        "eligible_amount_cents": None,
        "federal_reimbursable_cents": None,
        "ineligible_line_indexes": None,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "resubmission_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["vouchers"][rec["id"]] = rec
    return success_object(serialize_voucher(rec), status=201)


@bp.route("/federal-aid/vouchers/<vid>/submit", methods=["POST"])
@require_roles("StateDOTEngineer")
def submit_voucher(vid, user_id, user_role):
    voucher = STORE["vouchers"].get(vid)
    if voucher is None:
        raise err("ERR_NOT_FOUND", "Voucher not found")
    body = get_body()
    # Optional revised values (resubmission); validate shape where present.
    new_start = voucher["period_start_date"]
    new_start_dt = voucher["_start_dt"]
    new_end = voucher["period_end_date"]
    new_end_dt = voucher["_end_dt"]
    if "period_start_date" in body and body["period_start_date"] is not None:
        new_start = body["period_start_date"]
        new_start_dt = as_datetime(new_start, "period_start_date")
    if "period_end_date" in body and body["period_end_date"] is not None:
        new_end = body["period_end_date"]
        new_end_dt = as_datetime(new_end, "period_end_date")
    new_lines = voucher["line_items"]
    if "line_items" in body and body["line_items"] is not None:
        new_lines = _validate_line_items(body["line_items"])
    new_doc = voucher["documentation_complete"]
    if "documentation_complete" in body and body["documentation_complete"] is not None:
        new_doc = as_bool(body["documentation_complete"], "documentation_complete")
    if not new_end_dt > new_start_dt:
        raise err(
            "ERR_INVALID_REQUEST",
            "period_end_date must be strictly after period_start_date",
        )
    auth = STORE["authorizations"][voucher["authorization_id"]]
    project = STORE["projects"][auth["project_id"]]
    # State gate (priority 6): submittable voucher state + project state.
    if voucher["status"] not in ("DRAFT", "REJECTED"):
        raise err(
            "ERR_INVALID_STATE", "Voucher is not in a submittable state"
        )
    if project["status"] != "UNDER_CONSTRUCTION":
        raise err(
            "ERR_INVALID_STATE", "The project is not UNDER_CONSTRUCTION"
        )
    if auth["status"] != "OBLIGATED":
        raise err(
            "ERR_AUTHORIZATION_NOT_OBLIGATED",
            "The authorization is not OBLIGATED",
        )
    if new_doc is not True:
        raise err(
            "ERR_DOCUMENTATION_INCOMPLETE",
            "documentation_complete must be true at submit",
        )
    for sib in STORE["vouchers"].values():
        if (
            sib["authorization_id"] == voucher["authorization_id"]
            and sib["id"] != voucher["id"]
            and sib["status"] != "REJECTED"
            and _half_open_overlap(
                new_start_dt, new_end_dt, sib["_start_dt"], sib["_end_dt"]
            )
        ):
            raise err(
                "ERR_BILLING_PERIOD_OVERLAP",
                "Billing period intersects a non-REJECTED sibling voucher's period",
            )
    was_rejected = voucher["status"] == "REJECTED"
    voucher["period_start_date"] = new_start
    voucher["_start_dt"] = new_start_dt
    voucher["period_end_date"] = new_end
    voucher["_end_dt"] = new_end_dt
    voucher["line_items"] = [dict(li) for li in new_lines]
    voucher["documentation_complete"] = new_doc
    voucher["claimed_amount_cents"] = sum(
        li["eligible_amount_cents"] for li in new_lines
    )
    if was_rejected:
        voucher["resubmission_count"] += 1
    voucher["status"] = "UNDER_REVIEW"
    voucher["submitted_by_user_id"] = user_id
    touch(voucher)
    return success_object(serialize_voucher(voucher))


@bp.route("/federal-aid/vouchers/<vid>/decide", methods=["POST"])
@require_roles("FHWAReviewer")
def decide_voucher(vid, user_id, user_role):
    voucher = STORE["vouchers"].get(vid)
    if voucher is None:
        raise err("ERR_NOT_FOUND", "Voucher not found")
    body = get_body()
    decision = as_enum(req_field(body, "decision"), "decision", ("APPROVE", "REJECT"))
    ineligible = body.get("ineligible_line_indexes")
    if decision == "APPROVE" and ineligible is not None:
        if not isinstance(ineligible, list):
            raise err(
                "ERR_INVALID_REQUEST", "ineligible_line_indexes must be an array"
            )
        for idx in ineligible:
            if isinstance(idx, bool) or not isinstance(idx, int):
                raise err(
                    "ERR_INVALID_REQUEST",
                    "ineligible_line_indexes entries must be integers",
                )
            if idx < 0 or idx >= len(voucher["line_items"]):
                raise err(
                    "ERR_INVALID_REQUEST",
                    "ineligible_line_indexes entries must be valid 0-based indexes into line_items",
                )
    if voucher["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Voucher is not in UNDER_REVIEW")
    auth = STORE["authorizations"][voucher["authorization_id"]]
    project = STORE["projects"][auth["project_id"]]
    if decision == "REJECT":
        voucher["status"] = "REJECTED"
        voucher["decided_by_user_id"] = user_id
        touch(voucher)
        return success_object(serialize_voucher(voucher))
    # APPROVE of a final voucher: certification (11) outranks open change
    # orders (24).
    if voucher["is_final"]:
        row_full = any(
            c["project_id"] == project["id"]
            and c["kind"] == "RIGHT_OF_WAY"
            and c["status"] == "CLEARED"
            and c["row_cert_level"] == "LEVEL_1_FULL"
            for c in STORE["clearances"].values()
        )
        if not row_full:
            raise err(
                "ERR_ROW_NOT_CERTIFIED",
                "Final voucher requires a LEVEL_1_FULL right-of-way certification",
            )
        open_co = any(
            co["authorization_id"] == auth["id"]
            and co["status"] in ("REQUESTED", "STATE_CONCURRED")
            for co in STORE["change_orders"].values()
        )
        if open_co:
            raise err(
                "ERR_OPEN_CHANGE_ORDERS",
                "Open change orders block approval of a final voucher",
            )
    indexes = list(ineligible) if ineligible is not None else []
    eligible_total, reimbursable = voucher_reimbursement(
        voucher["line_items"],
        indexes,
        auth["_share_dec"],
        auth["obligated_cents"],
        auth["reimbursed_cents"],
    )
    voucher["eligible_amount_cents"] = eligible_total
    voucher["federal_reimbursable_cents"] = reimbursable
    voucher["ineligible_line_indexes"] = indexes
    voucher["status"] = "APPROVED"
    voucher["decided_by_user_id"] = user_id
    touch(voucher)
    # CASCADE link 1 + 2: reimbursement posts; exact draw-down -> FULLY_DRAWN.
    auth["reimbursed_cents"] += reimbursable
    if auth["reimbursed_cents"] == auth["obligated_cents"]:
        auth["status"] = "FULLY_DRAWN"
    touch(auth)
    # CASCADE link 3: final voucher approval completes the project.
    if voucher["is_final"]:
        project["status"] = "COMPLETE"
        touch(project)
    return success_object(serialize_voucher(voucher))


@bp.route("/federal-aid/authorizations/<aid>/vouchers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_authorization_vouchers(aid, user_id, user_role):
    _resolve_authorization(aid)
    items = [v for v in STORE["vouchers"].values() if v["authorization_id"] == aid]
    items.sort(key=lambda v: v["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list([serialize_voucher(v) for v in page], total, limit, offset)
