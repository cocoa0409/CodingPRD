"""Label account routes."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    envelope_ok,
    get_json,
    paginate,
    pagination_params,
    require_roles,
    touch,
)
from services import (
    get_label,
    new_entity,
    ser_dispute,
    ser_label,
    ser_title,
)

bp = Blueprint("labels", __name__)

READ_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "Investigator")
TITLE_READ_ROLES = ("PlatformAdmin", "ChartManager", "ChartOps", "LabelRep", "Investigator")


@bp.route("/labels", methods=["POST"])
def create_label():
    require_roles("PlatformAdmin")
    payload = get_json()
    account_code = payload.get("account_code")
    for l in db.label_accounts.values():
        if l["account_code"] == account_code:
            raise errors.ApiError("ERR_VALIDATION", "account_code must be unique", 422)

    label = new_entity()
    label.update(
        legal_name=payload.get("legal_name"),
        account_code=account_code,
        strike_count=0,
        account_status="ACTIVE",
    )
    db.label_accounts[label["id"]] = label
    return envelope_ok(ser_label(label), response_type="object", status=201)


@bp.route("/labels/<lid>", methods=["GET"])
def get_label_route(lid):
    require_roles(*READ_ROLES)
    label = get_label(lid)
    return envelope_ok(ser_label(label), response_type="object")


@bp.route("/labels/<lid>/titles", methods=["GET"])
def list_label_titles(lid):
    require_roles(*TITLE_READ_ROLES)
    label = get_label(lid)
    limit, offset = pagination_params()
    items = sorted(
        [t for t in db.title_products.values() if t["label_account_id"] == label["id"]],
        key=lambda t: (t["created_at"], t["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_title(t) for t in page], response_type="array", pagination=page_meta)


@bp.route("/labels/<lid>/disputes", methods=["GET"])
def list_label_disputes(lid):
    require_roles("PlatformAdmin", "ChartManager", "ChartOps", "LabelRep", "Investigator")
    label = get_label(lid)
    limit, offset = pagination_params()
    items = sorted(
        [d for d in db.genre_disputes.values() if d["filed_by_label_id"] == label["id"]],
        key=lambda d: (d["created_at"], d["_seq"]),
    )
    page, page_meta = paginate(items, limit, offset)
    return envelope_ok([ser_dispute(d) for d in page], response_type="array", pagination=page_meta)


@bp.route("/label-accounts/<lid>/reinstate", methods=["POST"])
def reinstate_label(lid):
    require_roles("ChartManager")
    label = get_label(lid)
    if label["account_status"] != "SUSPENDED":
        raise errors.invalid_state("Label account is not SUSPENDED")
    label["account_status"] = "ACTIVE"
    touch(label)
    return envelope_ok(ser_label(label), response_type="object", status=200)
