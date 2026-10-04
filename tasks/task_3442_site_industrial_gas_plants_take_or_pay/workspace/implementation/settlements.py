"""Monthly take-or-pay settlement statements (PRD 3.8)."""
from flask import Blueprint

from helpers import (authenticate, require_role, json_body, respond,
                     v_period, v_enum, v_int, v_num, forbid,
                     as_int, as_decimal, parse_period, by_created, paginate)
from store import db, base_entity, pub, touch, ApiError
from domain import compute_settlement

bp = Blueprint("settlements", __name__)


@bp.route("/gas-supply/supply-contracts/<contractId>/settlements",
          methods=["POST"])
def create_settlement(contractId):
    _uid, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    c = db["contracts"].get(contractId)
    if c is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "SupplyContract not found")
    body = json_body()
    # Tier 4: contract must be ACTIVE or RENEWAL_OPEN
    if c["status"] not in ("ACTIVE", "RENEWAL_OPEN"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409,
                       "Settlement requires an ACTIVE or RENEWAL_OPEN contract")
    # Tier 6: period must lie within [start month, end month]
    pym = parse_period(body.get("period_month"))
    if pym is not None:
        start_ym = (c["_start"].year, c["_start"].month)
        end_ym = (c["_end"].year, c["_end"].month)
        if pym < start_ym or pym > end_ym:
            raise ApiError("ERR_PERIOD_OUT_OF_TERM", 422,
                           "period_month outside the contract term")
    # Tier 7: per-(contract, period) uniqueness rules
    variant_raw = body.get("variant")
    if variant_raw in ("PROVISIONAL", "FINAL") and pym is not None:
        pstr = "%04d-%02d" % pym
        existing = [s for s in db["statements"].values()
                    if s["contract_id"] == c["id"]
                    and s["period_month"] == pstr
                    and s["status"] != "SUPERSEDED"]
        if variant_raw == "PROVISIONAL" and existing:
            raise ApiError("ERR_DUPLICATE_SETTLEMENT", 409,
                           "A non-SUPERSEDED statement already exists for "
                           "this period")
        if (variant_raw == "FINAL"
                and any(s["status"] == "FINAL" for s in existing)):
            raise ApiError("ERR_DUPLICATE_SETTLEMENT", 409,
                           "A FINAL statement already exists for this period")
    # Tier 8: makeup-credit sufficiency (computable only when the FINAL inputs
    # needed for the subtotal are present and usable; otherwise the structural
    # tier below fires instead)
    metered = as_int(body.get("metered_volume_nm3"))
    projected = as_int(body.get("projected_volume_nm3"))
    pindex = as_decimal(body.get("power_index_actual"))
    apply_makeup = None
    if body.get("apply_makeup_cents") is not None:
        apply_makeup = as_int(body.get("apply_makeup_cents"))
    if (variant_raw == "FINAL" and pym is not None and metered is not None
            and pindex is not None and apply_makeup is not None
            and apply_makeup >= 0):
        pre = compute_settlement(c, pym[0], pym[1], "FINAL", metered, None,
                                 body.get("power_index_actual"), apply_makeup)
        limit = min(c["makeup_credit_balance_cents"], pre["subtotal_cents"])
        if apply_makeup > limit:
            raise ApiError("ERR_MAKEUP_CREDIT_EXCEEDED", 422,
                           "apply_makeup_cents exceeds min(pre-grant bank "
                           "balance, subtotal)")
    # Tier 9 structural: variant inputs, cross-variant prohibition
    period_month = v_period(body, "period_month")
    variant = v_enum(body, "variant", ("PROVISIONAL", "FINAL"))
    pindex_raw = None
    if variant == "FINAL":
        forbid(body, "projected_volume_nm3")
        metered = v_int(body, "metered_volume_nm3", min_value=0)
        pindex_raw = v_num(body, "power_index_actual")
        apply_makeup = v_int(body, "apply_makeup_cents", required=False,
                             min_value=0)
        projected = None
    else:
        forbid(body, "metered_volume_nm3")
        forbid(body, "power_index_actual")
        forbid(body, "apply_makeup_cents")
        projected = v_int(body, "projected_volume_nm3", min_value=0)
        metered = None
        apply_makeup = None
    pym = parse_period(period_month)
    calc = compute_settlement(c, pym[0], pym[1], variant, metered, projected,
                              pindex_raw, apply_makeup)
    ent = base_entity()
    ent.update({
        "contract_id": c["id"],
        "period_month": period_month,
        "variant": variant,
        "metered_volume_nm3": metered if variant == "FINAL" else None,
        "projected_volume_nm3": projected if variant == "PROVISIONAL" else None,
        "power_index_actual": pindex_raw if variant == "FINAL" else None,
        "apply_makeup_cents": apply_makeup if variant == "FINAL" else None,
        "status": variant,
    })
    ent.update(calc)
    db["statements"][ent["id"]] = ent
    if variant == "FINAL":
        # Supersede the period's provisional, then mutate the credit bank (14)
        for s in db["statements"].values():
            if (s["id"] != ent["id"] and s["contract_id"] == c["id"]
                    and s["period_month"] == period_month
                    and s["status"] == "PROVISIONAL"):
                s["status"] = "SUPERSEDED"
                touch(s)
        c["makeup_credit_balance_cents"] = (
            c["makeup_credit_balance_cents"]
            + calc["makeup_credit_granted_cents"]
            - calc["makeup_credit_applied_cents"])
        touch(c)
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/supply-contracts/<contractId>/settlements",
          methods=["GET"])
def list_settlements(contractId):
    authenticate()
    if contractId not in db["contracts"]:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "SupplyContract not found")
    items = by_created([s for s in db["statements"].values()
                        if s["contract_id"] == contractId])
    page, meta = paginate(items)
    return respond([pub(s) for s in page], "array", 200, meta)
