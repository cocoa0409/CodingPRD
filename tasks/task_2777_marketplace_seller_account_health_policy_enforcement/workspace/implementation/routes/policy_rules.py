"""The policy catalogue (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

import constants as C
import db
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError

bp = Blueprint("policy_rules", __name__)


@bp.post("/policy-rules")
@mw.require(C.ROLE_OFFICER)
def publish_rule():
    data = v.body()
    code = v.req_str(data, "code", 2, 32)
    category = v.req_enum(data, "category", C.POLICY_CATEGORIES)
    base_severity_weight = v.req_decimal(
        data, "base_severity_weight", 2, Decimal("0.50"), Decimal("8.00")
    )
    removal_scope = v.req_enum(data, "removal_scope", C.REMOVAL_SCOPES)
    requires_poa = v.req_bool(data, "requires_poa", default=True)

    for existing in db.POLICY_RULES.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_POLICY_CODE")

    row = db.new_row(
        "policy_rule",
        code=code,
        category=category,
        base_severity_weight=base_severity_weight,
        removal_scope=removal_scope,
        requires_poa=requires_poa,
        decay_exempt=category in ("INTELLECTUAL_PROPERTY", "RESTRICTED_PRODUCT"),
    )
    db.POLICY_RULES[row["id"]] = row
    return response.one(row, ser.policy_rule, 201)


@bp.get("/policy-rules")
@mw.require(C.ROLE_SELLER, C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_rules():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.POLICY_RULES)
    if "category" in request.args:
        wanted = request.args.get("category")
        rows = [r for r in rows if r["category"] == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.policy_rule, limit, offset, total)
