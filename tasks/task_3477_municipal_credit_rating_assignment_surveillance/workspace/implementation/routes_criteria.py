"""Criteria version governance (PRD §3.6): draft, list, get, activate with
supersede and portfolio-wide review fan-out."""
from flask import Blueprint, request

from auth import auth, authenticate
from constants import CREDIT_TYPES, ROLE_SURVEILLANCE_OFFICER, WEIGHT_SUM_REQUIRED
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_CRITERIA_VERSION_STATE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_WEIGHT_SUM_INVALID,
    raise_err,
)
from services_criteria import activate as activate_criteria
from services_scoring import weights_sum
from store import db, new_entity
from validators import (
    body,
    get_criteria_version,
    is_number,
    require_enum,
    require_fields,
)

bp = Blueprint("criteria", __name__)

WEIGHT_FIELDS = [
    "w_economy",
    "w_management",
    "w_budgetary_performance",
    "w_flexibility",
    "w_liquidity",
    "w_debt_profile",
]


@bp.route("/muni/criteria-versions", methods=["POST"])
def create_criteria_version():
    auth([ROLE_SURVEILLANCE_OFFICER])
    payload = body()
    require_fields(payload, ["jurisdiction_code", "credit_type", "version_label"] + WEIGHT_FIELDS)
    require_enum(payload, "credit_type", CREDIT_TYPES)
    for field in WEIGHT_FIELDS:
        if not is_number(payload[field]):
            raise_err(ERR_INVALID_REQUEST, "weight %s must be a number" % field)

    # Priority 10(c): the six weights must sum to exactly 1.000.
    if weights_sum([payload[f] for f in WEIGHT_FIELDS]) != WEIGHT_SUM_REQUIRED:
        raise_err(ERR_WEIGHT_SUM_INVALID, "the six criteria weights must sum to exactly 1.000")

    ent = new_entity()
    ent.update(
        jurisdiction_code=payload["jurisdiction_code"],
        credit_type=payload["credit_type"],
        version_label=payload["version_label"],
        status="DRAFT",
        activated_at=None,
        **{f: payload[f] for f in WEIGHT_FIELDS},
    )
    db.criteria_versions[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/criteria-versions", methods=["GET"])
def list_criteria_versions():
    authenticate()
    items = list(db.criteria_versions.values())
    for field in ("jurisdiction_code", "credit_type", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [c for c in items if c.get(field) == value]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/criteria-versions/<criteria_version_id>", methods=["GET"])
def get_one_criteria_version(criteria_version_id):
    authenticate()
    return success_object(get_criteria_version(criteria_version_id))


@bp.route("/muni/criteria-versions/<criteria_version_id>/activate", methods=["POST"])
def activate_version(criteria_version_id):
    auth([ROLE_SURVEILLANCE_OFFICER])
    criteria = get_criteria_version(criteria_version_id)
    # Priority 6: only a DRAFT version activates.
    if criteria["status"] != "DRAFT":
        raise_err(ERR_CRITERIA_VERSION_STATE_INVALID, "criteria version is not DRAFT")
    activate_criteria(criteria)
    return success_object(criteria)
