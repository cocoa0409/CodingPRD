"""Funding grants and center expense waterfall (PRD 3.8)."""

from flask import Blueprint

from helpers import (
    authn,
    base_entity,
    body,
    bump,
    err,
    get_center,
    now,
    opt_str,
    paginate,
    req_date,
    req_int,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    today,
    validation,
)
from storage import STORE

bp = Blueprint("funding", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer", "Guest")


def grant_view(grant):
    out = serialize(grant)
    out["remaining_cents"] = grant["amount_cents"] - grant["spent_cents"]
    return out


@bp.route("/funding-grants", methods=["POST"])
def create_grant():
    _, role = authn()
    require_role(role, ("PlatformAdmin",))
    b = body()
    center_id = req_str(b, "center_id")
    donor_name = req_str(b, "donor_name")
    amount = req_int(b, "amount_cents", minimum=1)
    spend_by = req_date(b, "spend_by_date")
    if spend_by < today():
        validation("spend_by_date must not be earlier than the current date")
    purpose = opt_str(b, "purpose")
    center = get_center(center_id)

    grant = base_entity()
    grant.update({
        "center_id": center["id"],
        "donor_name": donor_name,
        "amount_cents": amount,
        "spent_cents": 0,
        "spend_by_date": spend_by.isoformat(),
        "purpose": purpose,
        "status": "ACTIVE",
    })
    STORE.grants[grant["id"]] = grant
    return success_object(grant_view(grant), status=201)


@bp.route("/centers/<cid>/funding-grants", methods=["GET"])
def list_grants(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)
    items = [g for g in STORE.grants.values() if g["center_id"] == center["id"]]
    page, meta = paginate(items, serializer=grant_view)
    return success_list(page, meta)


@bp.route("/centers/<cid>/expenses", methods=["POST"])
def post_expense(cid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    amount = req_int(b, "amount_cents", minimum=1)
    description = req_str(b, "description")
    expected = req_int(b, "expected_center_version")
    center = get_center(cid)

    if expected != center["version"]:
        err("ERR_STALE_VERSION", 412, "Center version has advanced; re-read before posting")

    candidates = sorted(
        (g for g in STORE.grants.values() if g["center_id"] == cid and g["status"] == "ACTIVE"),
        key=lambda g: (g["spend_by_date"], g["created_at"], g["_seq"]),
    )
    total_remaining = sum(g["amount_cents"] - g["spent_cents"] for g in candidates)
    if amount > total_remaining:
        err("ERR_BUDGET_EXCEEDED", 409, "Expense exceeds total remaining grant budget")

    debits = []
    left = amount
    for g in candidates:
        if left == 0:
            break
        remaining = g["amount_cents"] - g["spent_cents"]
        d = min(remaining, left)
        if d <= 0:
            continue
        g["spent_cents"] += d
        left -= d
        if g["amount_cents"] - g["spent_cents"] == 0:
            g["status"] = "EXHAUSTED"
        bump(g)
        debits.append({"grant_id": g["id"], "amount_cents": d})

    center["expense_ledger"].append({
        "posted_at": now(),
        "amount_cents": amount,
        "description": description,
    })
    bump(center)

    return success_object({"posted_cents": amount, "debits": debits}, status=201)
