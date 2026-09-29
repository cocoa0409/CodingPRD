"""Install jobs: scheduling, commissioning, exceptions and sign-off."""

from flask import Blueprint

import calc
from core import (ROLE_DESIGNER, ROLE_FRANCHISEE, ROLE_FRANCHISOR, append_ledger, auth,
                  check_calendar_conflict, check_range, fail, get_body, get_designer,
                  get_job, get_opening, get_order, list_response, money, new_row,
                  openings_of_order, openings_of_quote, recompute_designer_score,
                  rederive_territory, req_enum, req_fk, req_instant, req_int, req_postal,
                  req_str, respond_object, require_designer_active,
                  require_designer_assignment, require_territory_active,
                  require_territory_ownership, require_territory_ownership_row,
                  royalty_on, serialize, store, territory_of_job, territory_of_order,
                  touch)
from routes_order import replace_order

bp = Blueprint("install", __name__)

EXCEPTION_REASONS = ("OUT_OF_SQUARE", "OBSTRUCTION", "DAMAGED_GOODS")
HUB_ENUM = ("NONE",) + calc.HUB_PLATFORMS
RESTING_COMMISSIONING = ("NOT_REQUIRED", "VERIFIED")


def _order_of(job):
    return store.vendor_orders.get(job["vendor_order_id"])


def _vendor_of(job):
    order = _order_of(job)
    return store.vendors.get(order["vendor_id"]) if order else None


def _require_scheduled(job):
    """The first dimension is always examined before the second (PRD 3.9)."""
    if job["install_status"] != "SCHEDULED":
        fail("ERR_INSTALL_JOB_NOT_SCHEDULED",
             "install status is %s" % job["install_status"])


@bp.route("/blinds/install-jobs", methods=["POST"])
def create_job():
    actor = auth(ROLE_FRANCHISEE, ROLE_DESIGNER)
    body = get_body()
    order = req_fk(body, "vendor_order_id", get_order)
    designer = req_fk(body, "designer_id", get_designer)
    order_territory = territory_of_order(order) if order is not None else None
    if order is not None:
        require_territory_ownership_row(actor, order_territory)
    if designer is not None:
        require_territory_ownership(actor, designer["territory_id"])
    order = get_order(req_str(body, "vendor_order_id", 1, None))
    designer = get_designer(req_str(body, "designer_id", 1, None))
    start = req_instant(body, "scheduled_start_at")
    end = req_instant(body, "scheduled_end_at")
    postal_code = req_postal(body, "service_postal_code")
    check_range(end > start, "scheduled_end_at must be strictly after scheduled_start_at")
    order_territory = territory_of_order(order)
    if (order_territory is None
            or designer["territory_id"] != order_territory["id"]):
        fail("ERR_CROSS_TERRITORY_FORBIDDEN",
             "the designer belongs to a different territory than the order")
    require_territory_active(order_territory)
    require_designer_active(designer)
    if order["status"] != "RECEIVED":
        fail("ERR_ORDER_NOT_RECEIVED", "order status is %s" % order["status"])
    check_calendar_conflict(designer["id"], start, end, postal_code)
    channels = len([o for o in openings_of_order(order)
                    if (o.get("motorization_option") or "NONE") != "NONE"])
    row = new_row({
        "vendor_order_id": order["id"],
        "designer_id": designer["id"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "service_postal_code": postal_code,
        "install_status": "SCHEDULED",
        "commissioning_status": "NOT_REQUIRED" if channels == 0 else "PENDING",
        "motorized_channel_count": channels,
        "paired_channel_count": 0,
        "hub_platform": "NONE",
        "commissioning_attempt_count": 0,
        "exception_reason": "NONE",
        "exception_opening_id": None,
        "liable_party": "NONE",
        "remeasure_charge_cents": 0,
        "exception_raised_at": None,
        "completed_at": None,
    })
    store.install_jobs[row["id"]] = row
    return respond_object(serialize(row), 201)


@bp.route("/blinds/install-jobs/<job_id>", methods=["GET"])
def read_job(job_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    job = get_job(job_id)
    require_territory_ownership_row(actor, territory_of_job(job))
    return respond_object(serialize(job), 200)


@bp.route("/blinds/install-jobs", methods=["GET"])
def list_jobs():
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER)
    rows = list(store.install_jobs.values())
    return list_response(rows, ("vendor_order_id", "designer_id", "install_status",
                                "commissioning_status"))


# --------------------------------------------------------------------------
# Commissioning (PRD 3.9)
# --------------------------------------------------------------------------
@bp.route("/blinds/install-jobs/<job_id>/commissioning/pair", methods=["POST"])
def pair_commissioning(job_id):
    actor = auth(ROLE_DESIGNER)
    job = get_job(job_id)
    require_designer_assignment(actor, job["designer_id"])
    body = get_body()
    paired = req_int(body, "paired_channel_count")
    hub_platform = req_enum(body, "hub_platform", HUB_ENUM)
    check_range(paired >= 0, "paired_channel_count must be at least 0")
    _require_scheduled(job)
    if job["commissioning_status"] not in ("PENDING", "FAILED"):
        fail("ERR_COMMISSIONING_NOT_APPLICABLE",
             "commissioning status is %s" % job["commissioning_status"])
    designer = store.designers.get(job["designer_id"])
    if designer is None or "MOTORIZATION" not in designer["certifications"]:
        fail("ERR_MOTORIZATION_CERT_REQUIRED",
             "the installer holds no MOTORIZATION certification")
    vendor = _vendor_of(job)
    supported = vendor["supported_hub_platforms"] if vendor else []
    if hub_platform not in supported:
        fail("ERR_HUB_PLATFORM_UNSUPPORTED",
             "the manufacturer does not support %s" % hub_platform)
    if paired > job["motorized_channel_count"]:
        fail("ERR_CHANNEL_COUNT_EXCEEDS_ORDER",
             "the order carries only %s channels" % job["motorized_channel_count"])
    if job["commissioning_attempt_count"] >= calc.COMMISSIONING_MAX_ATTEMPTS:
        fail("ERR_COMMISSIONING_ATTEMPT_LIMIT", "the three-attempt cap is reached")
    job["hub_platform"] = hub_platform
    job["paired_channel_count"] = paired
    job["commissioning_attempt_count"] = job["commissioning_attempt_count"] + 1
    job["commissioning_status"] = "PAIRED"
    touch(job)
    return respond_object(serialize(job), 200)


@bp.route("/blinds/install-jobs/<job_id>/commissioning/verify", methods=["POST"])
def verify_commissioning(job_id):
    actor = auth(ROLE_DESIGNER)
    job = get_job(job_id)
    require_designer_assignment(actor, job["designer_id"])
    _require_scheduled(job)
    if job["commissioning_status"] != "PAIRED":
        fail("ERR_COMMISSIONING_NOT_PAIRED",
             "commissioning status is %s" % job["commissioning_status"])
    if job["paired_channel_count"] == job["motorized_channel_count"]:
        job["commissioning_status"] = "VERIFIED"
    else:
        job["commissioning_status"] = "FAILED"
    touch(job)
    return respond_object(serialize(job), 200)


# --------------------------------------------------------------------------
# Exception and the four-hop cascade (PRD 3.9)
# --------------------------------------------------------------------------
@bp.route("/blinds/install-jobs/<job_id>/exception", methods=["POST"])
def raise_exception(job_id):
    actor = auth(ROLE_DESIGNER)
    job = get_job(job_id)
    body = get_body()
    req_fk(body, "opening_id", get_opening)
    require_designer_assignment(actor, job["designer_id"])
    opening = get_opening(req_str(body, "opening_id", 1, None))
    reason = req_enum(body, "exception_reason", EXCEPTION_REASONS)
    order = _order_of(job)
    if order is None or opening["id"] not in order["opening_ids"]:
        fail("ERR_OPENING_NOT_ON_QUOTE", "the opening is not on this job's order")
    _require_scheduled(job)
    if opening.get("install_outcome") != "PENDING":
        fail("ERR_OPENING_NOT_ON_QUOTE",
             "opening %s is already resolved" % opening["id"])
    liable_party = calc.liable_party_for(reason, opening)
    charge = 0
    if liable_party == "MEASURER":
        charge = calc.remeasure_charge_cents(opening["list_price_cents"])
    job["exception_reason"] = reason
    job["exception_opening_id"] = opening["id"]
    job["exception_raised_at"] = store.clock
    job["liable_party"] = liable_party
    job["remeasure_charge_cents"] = charge
    job["install_status"] = "EXCEPTION_RAISED"
    touch(job)
    territory = territory_of_order(order)
    if liable_party == "MEASURER" and territory is not None:
        append_ledger(territory, "REMEASURE_CHARGEBACK", charge,
                      opening["list_price_cents"], "INSTALL_JOB", job["id"],
                      "remeasure_chargeback")
    opening["measure_status"] = "REMEASURE_REQUIRED"
    opening["install_outcome"] = "NOT_INSTALLED"
    touch(opening)
    replaced = False
    if order["status"] == "RECEIVED":
        replace_order(order, "INSTALL_EXCEPTION", liable_party)
        replaced = True
    if territory is not None and not replaced:
        rederive_territory(territory)
    designer = store.designers.get(job["designer_id"])
    if designer is not None:
        recompute_designer_score(designer)
    return respond_object(serialize(job), 200)


# --------------------------------------------------------------------------
# Sign-off and the royalty true-up (PRD 3.9)
# --------------------------------------------------------------------------
@bp.route("/blinds/install-jobs/<job_id>/complete", methods=["POST"])
def complete_job(job_id):
    actor = auth(ROLE_DESIGNER)
    job = get_job(job_id)
    require_designer_assignment(actor, job["designer_id"])
    _require_scheduled(job)
    order = _order_of(job)
    if order is None or order["status"] != "RECEIVED":
        fail("ERR_ORDER_NOT_RECEIVED",
             "order status is %s" % (order["status"] if order else "unknown"))
    if job["commissioning_status"] not in RESTING_COMMISSIONING:
        fail("ERR_COMMISSIONING_NOT_VERIFIED",
             "commissioning status is %s" % job["commissioning_status"])
    job["install_status"] = "COMPLETED"
    job["completed_at"] = store.clock
    touch(job)
    for opening in openings_of_order(order):
        if opening.get("install_outcome") == "PENDING":
            opening["install_outcome"] = "INSTALLED"
            touch(opening)
    territory = territory_of_order(order)
    quote = store.quotes.get(order["quote_id"])
    if quote is not None and territory is not None:
        installed_subtotal = sum(
            o["list_price_cents"] for o in openings_of_quote(quote["id"])
            if o.get("install_outcome") == "INSTALLED" and not o.get("credited"))
        final_discount = money(installed_subtotal * quote["discount_pct"])
        final_basis = installed_subtotal - final_discount
        previous = quote["recognized_net_sales_cents"]
        delta = royalty_on(territory, final_basis) - royalty_on(territory, previous)
        territory["net_sales_cents"] = (
            territory["net_sales_cents"] + (final_basis - previous))
        quote["recognized_net_sales_cents"] = final_basis
        touch(quote)
        if delta > 0:
            append_ledger(territory, "NET_SALES_ROYALTY", delta, final_basis,
                          "INSTALL_JOB", job["id"], "install_trueup")
        elif delta < 0:
            append_ledger(territory, "ROYALTY_REVERSAL", delta, final_basis,
                          "INSTALL_JOB", job["id"], "install_trueup")
        rederive_territory(territory)
    designer = store.designers.get(job["designer_id"])
    if designer is not None:
        recompute_designer_score(designer)
    return respond_object(serialize(job), 200)
