"""TariffRate endpoints (PRD 3.7): rate design with floor, overlap, and
gradualism guards."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_CASE_STATE,
    ERR_BELOW_CUSTOMER_COST_FLOOR,
    ERR_TARIFF_WINDOW_OVERLAP,
    ERR_CLASS_NOT_IN_CASE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.calculations import (
    annual_revenue,
    customer_cost_floor_cents,
    gradualism_cap_check,
)
from services.core import new_record, public
from util import parse_datetime, fmt_datetime
from validate import (
    get_body,
    no_unknown_fields,
    opt_nullable_datetime,
    req_datetime,
    req_int,
    req_str,
    req_tiers,
    require_fk,
)

bp = Blueprint("tariff_rates", __name__)


def _windows_overlap(s1, e1, s2, e2):
    """Half-open [start, end) intersection; null end is infinity; adjacency OK."""
    a_end = parse_datetime(e1) if e1 is not None else None
    b_end = parse_datetime(e2) if e2 is not None else None
    a_start, b_start = parse_datetime(s1), parse_datetime(s2)
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


@bp.post("/tariff-rates")
def create_tariff():
    body = get_body()
    no_unknown_fields(body, {
        "rate_case_id", "customer_class_id", "label",
        "proposed_customer_charge_cents", "proposed_tiers",
        "effective_start", "effective_end",
    })
    rate_case_id = req_str(body, "rate_case_id")
    customer_class_id = req_str(body, "customer_class_id")
    label = req_str(body, "label")
    charge = req_int(body, "proposed_customer_charge_cents", non_negative=True)
    tiers = req_tiers(body, "proposed_tiers")
    eff_start = req_datetime(body, "effective_start")
    eff_end = opt_nullable_datetime(body, "effective_end")
    if eff_end is not None and parse_datetime(eff_end) <= parse_datetime(eff_start):
        raise_error(ERR_INVALID_DATE_RANGE, "effective_end must be strictly after effective_start")
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    cls = require_fk("customer_classes", customer_class_id, "customer_class_id")
    # State (p6): case in DISCOVERY, HEARING, or SETTLEMENT
    if case["status"] not in ("DISCOVERY", "HEARING", "SETTLEMENT"):
        raise_error(ERR_INVALID_CASE_STATE,
                    "tariffs may be proposed only in DISCOVERY, HEARING, or SETTLEMENT")
    proposed_revenue = annual_revenue(
        cls["customer_count"], cls["monthly_kwh_per_customer"], charge, tiers)
    # Business safety (p7): anti-subsidy floor at create time
    floor = customer_cost_floor_cents(case, cls)
    if proposed_revenue < floor:
        raise_error(ERR_BELOW_CUSTOMER_COST_FLOOR,
                    f"proposed revenue {proposed_revenue} is below the customer-cost floor {floor}")
    # Temporal (p8): half-open window overlap vs same-class non-REJECTED tariffs
    for other in db["tariff_rates"].values():
        if other["customer_class_id"] == customer_class_id and other["status"] != "REJECTED":
            if _windows_overlap(eff_start, eff_end, other["effective_start"], other["effective_end"]):
                raise_error(ERR_TARIFF_WINDOW_OVERLAP,
                            "effective window overlaps another tariff of the same class")
    # Referential (p9): the class must belong to this case
    if cls["rate_case_id"] != case["id"]:
        raise_error(ERR_CLASS_NOT_IN_CASE, "customer_class_id belongs to a different case")
    # Structural (p10): gradualism cap
    gradualism_cap_check(case, cls, proposed_revenue)
    rec = new_record("tariff_rates", {
        "rate_case_id": rate_case_id,
        "customer_class_id": customer_class_id,
        "label": label,
        "proposed_customer_charge_cents": charge,
        "proposed_tiers": tiers,
        "effective_start": fmt_datetime(parse_datetime(eff_start)),
        "effective_end": fmt_datetime(parse_datetime(eff_end)) if eff_end is not None else None,
        "proposed_revenue_cents": proposed_revenue,
        "status": "PROPOSED",
    })
    return success_object(public(rec), status=201)


@bp.get("/tariff-rates")
def list_tariffs():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "customer_class_id": query_arg("customer_class_id"),
        "status": query_arg("status"),
    }
    return list_response("tariff_rates", filters)


@bp.get("/tariff-rates/<tariff_id>")
def get_tariff(tariff_id):
    return get_one("tariff_rates", tariff_id)
