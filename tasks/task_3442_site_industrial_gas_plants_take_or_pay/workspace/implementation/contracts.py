"""Take-or-pay supply contracts (PRD 3.2): formation, activation, amendments,
renewals, termination cascade."""
from flask import Blueprint, request

from helpers import (authenticate, require_role, json_body, respond,
                     v_str, v_int, v_num, v_enum, v_date, validation,
                     as_int, parse_date, add_months, by_created, paginate)
from store import db, base_entity, pub, touch, ApiError
from domain import MODE_MIN_MONTHLY_VOLUME_NM3, terminate_cascade

bp = Blueprint("contracts", __name__)


def _get_contract_or_404(contract_id):
    c = db["contracts"].get(contract_id)
    if c is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "SupplyContract not found")
    return c


@bp.route("/gas-supply/supply-contracts", methods=["POST"])
def create_contract():
    _uid, role = authenticate()
    require_role(role, {"SupplyPlanner"})
    body = json_body()
    # Tier 3: body-referenced entities (customer before evaluation, matching
    # the left-to-right precedence order of PRD 2.8)
    cid = body.get("customer_id")
    if isinstance(cid, str) and cid not in db["customers"]:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    ev = None
    eid = body.get("evaluation_id")
    if isinstance(eid, str):
        ev = db["evaluations"].get(eid)
        if ev is None:
            raise ApiError("ERR_EVALUATION_NOT_FOUND", 404,
                           "SupplyModeEvaluation not found")
    # Tier 4 state: the referenced evaluation must be ACCEPTED
    if ev is not None and ev["status"] != "ACCEPTED":
        raise ApiError("ERR_EVALUATION_NOT_ACCEPTED", 409,
                       "Evaluation is not ACCEPTED")
    # Tier 9 structural
    customer_id = v_str(body, "customer_id")
    evaluation_id = v_str(body, "evaluation_id")
    term_months = v_int(body, "term_months", min_value=1)
    start_raw = v_date(body, "start_date")
    min_volume = v_int(body, "min_monthly_volume_nm3", min_value=0)
    unit_price = v_int(body, "unit_price_cents_per_nm3", min_value=0)
    fee = v_int(body, "monthly_facility_fee_cents", min_value=0)
    escalation = v_num(body, "facility_fee_escalation_pct_annual", min_value=0)
    base_index = v_num(body, "base_power_index", min_value=0)
    kwh = v_num(body, "power_kwh_per_nm3", min_value=0)
    cap_pct = v_num(body, "makeup_credit_cap_pct", required=False)
    if cap_pct is None:
        cap_pct = 0.10
    if ev is not None and customer_id != ev["customer_id"]:
        validation("customer_id must equal the evaluation's customer_id")
    start = parse_date(start_raw)
    end = add_months(start, term_months)
    ent = base_entity()
    ent.update({
        "customer_id": customer_id,
        "evaluation_id": evaluation_id,
        "mode": ev["recommended_mode"],
        "product": ev["required_product"],
        "site_label": ev["site_label"],
        "term_months": term_months,
        "start_date": start_raw,
        "end_date": end.isoformat(),
        "min_monthly_volume_nm3": min_volume,
        "unit_price_cents_per_nm3": unit_price,
        "monthly_facility_fee_cents": fee,
        "facility_fee_escalation_pct_annual": escalation,
        "base_power_index": base_index,
        "power_kwh_per_nm3": kwh,
        "makeup_credit_cap_pct": cap_pct,
        "makeup_credit_balance_cents": 0,
        "failover_active": False,
        "status": "DRAFT",
        "_start": start,
        "_end": end,
    })
    db["contracts"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/supply-contracts/<contractId>", methods=["GET"])
def get_contract(contractId):
    authenticate()
    return respond(pub(_get_contract_or_404(contractId)))


@bp.route("/gas-supply/supply-contracts", methods=["GET"])
def list_contracts():
    authenticate()
    items = list(db["contracts"].values())
    for f in ("customer_id", "evaluation_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [c for c in items if c.get(f) == val]
    items = by_created(items)
    page, meta = paginate(items)
    return respond([pub(c) for c in page], "array", 200, meta)


@bp.route("/gas-supply/supply-contracts/<contractId>/activate", methods=["POST"])
def activate_contract(contractId):
    _uid, role = authenticate()
    require_role(role, {"SupplyPlanner"})
    c = _get_contract_or_404(contractId)
    # Tier 4, in scaffold-listed order: evaluation gate, then from-state
    ev = db["evaluations"].get(c["evaluation_id"])
    if ev is None or ev["status"] != "ACCEPTED":
        raise ApiError("ERR_EVALUATION_NOT_ACCEPTED", 409,
                       "Evaluation is not ACCEPTED")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT contract can be activated")
    # Tier 7: pipeline-connection gate, then mode volume floor
    if c["mode"] == "PIPELINE":
        has_primary = any(
            conn["contract_id"] == c["id"] and conn["status"] == "ACTIVE"
            and conn["purpose"] == "PRIMARY"
            for conn in db["connections"].values())
        if not has_primary:
            raise ApiError("ERR_PIPELINE_CONNECTION_REQUIRED", 409,
                           "PIPELINE-mode activation requires an ACTIVE "
                           "PRIMARY connection")
    if c["min_monthly_volume_nm3"] < MODE_MIN_MONTHLY_VOLUME_NM3[c["mode"]]:
        raise ApiError("ERR_MIN_VOLUME_BELOW_FLOOR", 422,
                       "min_monthly_volume_nm3 below the mode floor")
    # Tier 8: fiscal credit gate
    cust = db["customers"].get(c["customer_id"])
    if cust is not None and cust["credit_standing"] == "WATCH":
        raise ApiError("ERR_CUSTOMER_CREDIT_WATCH", 422,
                       "Customer credit standing WATCH blocks activation")
    c["status"] = "ACTIVE"
    touch(c)
    return respond(pub(c))


@bp.route("/gas-supply/supply-contracts/<contractId>/amendments",
          methods=["POST"])
def amend_contract(contractId):
    _uid, role = authenticate()
    require_role(role, {"SupplyPlanner"})
    c = _get_contract_or_404(contractId)
    body = json_body()
    # Tier 4 OCC guard
    expected = as_int(body.get("expected_contract_version"))
    if expected is not None and expected != c["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_contract_version does not match the contract "
                       "version")
    # Tier 4 from-state, per amendment kind
    kind_raw = body.get("kind")
    if kind_raw == "AMENDMENT":
        if c["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "AMENDMENT requires an ACTIVE contract")
    elif kind_raw == "RENEWAL":
        if c["status"] != "RENEWAL_OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "RENEWAL requires a RENEWAL_OPEN contract")
    # Tier 9 structural
    kind = v_enum(body, "kind", ("AMENDMENT", "RENEWAL"))
    v_int(body, "expected_contract_version")
    new_end = None
    if kind == "RENEWAL":
        new_end_raw = v_date(body, "new_end_date")
        new_end = parse_date(new_end_raw)
        if new_end <= c["_end"]:
            validation("new_end_date must be strictly later than the current "
                       "end_date")
    new_fee = v_int(body, "new_monthly_facility_fee_cents", required=False,
                    min_value=0)
    new_min = v_int(body, "new_min_monthly_volume_nm3", required=False,
                    min_value=0)
    new_price = v_int(body, "new_unit_price_cents_per_nm3", required=False,
                      min_value=0)
    # Effects: apply supplied terms going forward
    if new_fee is not None:
        c["monthly_facility_fee_cents"] = new_fee
    if new_min is not None:
        c["min_monthly_volume_nm3"] = new_min
    if new_price is not None:
        c["unit_price_cents_per_nm3"] = new_price
    if kind == "RENEWAL":
        c["end_date"] = new_end.isoformat()
        c["_end"] = new_end
        c["status"] = "ACTIVE"
    touch(c)
    return respond(pub(c))


@bp.route("/gas-supply/supply-contracts/<contractId>/terminate",
          methods=["POST"])
def terminate_contract(contractId):
    _uid, role = authenticate()
    require_role(role, {"SupplyPlanner"})
    c = _get_contract_or_404(contractId)
    if c["status"] not in ("DRAFT", "ACTIVE", "RENEWAL_OPEN"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only DRAFT, ACTIVE or RENEWAL_OPEN contracts can be "
                       "terminated")
    if c["status"] != "DRAFT":
        terminate_cascade(c)
    c["status"] = "TERMINATED"
    touch(c)
    return respond(pub(c))
