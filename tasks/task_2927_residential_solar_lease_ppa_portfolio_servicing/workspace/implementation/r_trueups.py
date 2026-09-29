"""Annual guarantee true-ups and the credit cap (PRD §3.4)."""
from flask import Blueprint

import calc
from calc import ANNUAL_CREDIT_CAP_PCT
from core import (
    ApiError, D, clock, fmt_instant, rhu_int, sorted_rows, stamp_new, store, touch,
)
from guards import homeowner_agreement_ids, homeowner_scope, lookup
from r_periods import month_elapsed
from serialize import true_up_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("true_up_routes", __name__)

METHODS = ("MONTHLY_ROLLING", "ANNUAL_TRUE_UP")
TRUE_UP_STATUSES = ("DRAFT", "POSTED", "VOID")

TRUE_UP_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "contract_year", "kind": "int", "required": True, "min": 1},
    {"name": "method", "kind": "enum", "required": True, "values": METHODS},
    {"name": "expected_agreement_version", "kind": "int", "required": True},
]


@bp.post("/servicing/guarantee-true-ups")
def create_true_up():
    authenticate(("PortfolioAdmin", "ServicingAgent"))
    body = validate_body(TRUE_UP_SPECS)
    ag = lookup("agreements", body["agreement_id"])
    cy = body["contract_year"]
    # rung 9 — optimistic concurrency on the parent agreement
    if body["expected_agreement_version"] != ag["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION",
                       "expected_agreement_version does not match the agreement's "
                       "current version.")
    rows = [p for p in store.periods.values()
            if p["agreement_id"] == ag["id"] and p["contract_year"] == cy]
    rows.sort(key=lambda p: (p["period_year"], p["period_month"], p["_seq"]))
    # rung 11
    for p in rows:
        if not month_elapsed(p["period_year"], p["period_month"]):
            raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                           "At least one month of that contract year has not "
                           "fully elapsed.")
    # rung 12
    if len(rows) != 12:
        raise ApiError("ERR_PERIODS_INCOMPLETE",
                       "Twelve metered months are required for contract year %d." % cy)

    tariff = store.tariffs.get(ag["tariff_id"])
    total_metered = sum(p["metered_kwh"] for p in rows)
    total_adjusted = sum(p["adjusted_expected_kwh"] for p in rows)
    if body["method"] == "MONTHLY_ROLLING":
        annual_floor = 0
        credit_rate = 0
        annual_shortfall = sum(p["shortfall_kwh"] for p in rows)
        gross_credit = sum(p["credit_cents"] for p in rows)
    else:
        annual_floor = rhu_int(D(total_adjusted) * (D(1) - D(ag["guarantee_band_pct"])))
        annual_shortfall = max(0, annual_floor - total_metered)
        if ag["product_type"] == "PPA":
            credit_rate = calc.escalated_rate_millicents(ag, cy)
        else:
            credit_rate = tariff["retail_rate_per_kwh_millicents"] if tariff else 0
        gross_credit = rhu_int(D(annual_shortfall) * D(credit_rate) / D(1000))
    already = sum(p["credit_cents"] for p in rows if p["status"] == "CREDIT_ISSUED")
    net_credit = max(0, gross_credit - already)

    true_up = {
        "agreement_id": ag["id"],
        "contract_year": cy,
        "method": body["method"],
        "total_metered_kwh": total_metered,
        "total_adjusted_expected_kwh": total_adjusted,
        "annual_guarantee_floor_kwh": annual_floor,
        "annual_shortfall_kwh": annual_shortfall,
        "credit_rate_millicents": credit_rate,
        "gross_credit_cents": gross_credit,
        "already_issued_credit_cents": already,
        "net_credit_cents": net_credit,
        "covered_period_ids": [p["id"] for p in rows],
        "posted_at": None,
        "posted_by_user_id": None,
        "voided_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(true_up)
    store.true_ups[true_up["id"]] = true_up
    touch(ag)
    return created(true_up_view(true_up))


@bp.get("/servicing/guarantee-true-ups/<true_up_id>")
def get_true_up(true_up_id):
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent", "Homeowner"))
    true_up = lookup("true_ups", true_up_id)
    homeowner_scope(role, user_id, store.agreements.get(true_up["agreement_id"]))
    return ok(true_up_view(true_up))


@bp.get("/servicing/guarantee-true-ups")
def list_true_ups():
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent", "Homeowner"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("contract_year", "int", None),
        ("method", "enum", METHODS),
        ("status", "enum", TRUE_UP_STATUSES),
    ])
    rows = list(store.true_ups.values())
    if role == "Homeowner":
        if "agreement_id" in flt:
            homeowner_scope(role, user_id, store.agreements.get(flt["agreement_id"]))
        owned = homeowner_agreement_ids(user_id)
        rows = [r for r in rows if r["agreement_id"] in owned]
    rows = apply_filters(sorted_rows(rows), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([true_up_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/guarantee-true-ups/<true_up_id>/post")
def post_true_up(true_up_id):
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent"))
    validate_body([])
    true_up = lookup("true_ups", true_up_id)
    ag = store.agreements[true_up["agreement_id"]]
    cy = true_up["contract_year"]
    # rung 8 — the specific code takes precedence over the generic one
    if true_up["status"] == "POSTED":
        raise ApiError("ERR_TRUE_UP_ALREADY_POSTED",
                       "This true-up is already POSTED.")
    others = [t for t in store.true_ups.values()
              if t["agreement_id"] == ag["id"] and t["contract_year"] == cy
              and t["status"] == "POSTED" and t["id"] != true_up["id"]]
    if others:
        raise ApiError("ERR_TRUE_UP_ALREADY_POSTED",
                       "A true-up for that agreement and contract year is already "
                       "POSTED.")
    if true_up["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a DRAFT true-up may be posted.")
    # rung 14 — the annual credit cap
    cap = rhu_int(ANNUAL_CREDIT_CAP_PCT * D(calc.annual_contract_value_cents(ag, cy)))
    posted_sum = sum(t["net_credit_cents"] for t in others)
    if posted_sum + true_up["net_credit_cents"] > cap:
        raise ApiError("ERR_CREDIT_CAP_EXCEEDED",
                       "Posting would breach the contract year's credit cap.")

    true_up["status"] = "POSTED"
    true_up["posted_by_user_id"] = user_id
    true_up["posted_at"] = fmt_instant(clock.now())
    ag["credit_earned_cents"] += true_up["net_credit_cents"]
    ag["credit_balance_cents"] += true_up["net_credit_cents"]
    touch(true_up)
    touch(ag)
    return ok(true_up_view(true_up))


@bp.post("/servicing/guarantee-true-ups/<true_up_id>/void")
def void_true_up(true_up_id):
    user_id, role = authenticate(("PortfolioAdmin", "ServicingAgent"))
    validate_body([])
    true_up = lookup("true_ups", true_up_id)
    ag = store.agreements[true_up["agreement_id"]]
    # rung 7 — segregation of duties, ahead of every state check
    if true_up["posted_by_user_id"] is not None and true_up["posted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who posted a true-up may not void it.")
    if true_up["status"] not in ("DRAFT", "POSTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a DRAFT or POSTED true-up may be voided.")
    if true_up["status"] == "POSTED":
        ag["credit_earned_cents"] -= true_up["net_credit_cents"]
        ag["credit_balance_cents"] -= true_up["net_credit_cents"]
        touch(ag)
    true_up["status"] = "VOID"
    true_up["voided_by_user_id"] = user_id
    touch(true_up)
    return ok(true_up_view(true_up))
