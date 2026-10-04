"""Cancellation/suspension proceedings (PRD 3.8): the enforcement arm."""
from flask import Blueprint, request

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from services.calcs import existing_stocks_deadlines
from services.cascade import cancel_product, suspend_product, vacatur_restore
from validate import (
    as_enum,
    as_int,
    as_str,
    paginate,
    parse_body,
    reject_unknown,
)

bp = Blueprint("proceedings", __name__)

NON_TERMINAL_PROCEEDING_STATUSES = ("INITIATED", "HEARING_HELD", "EFFECTIVE")


def get_proceeding_or_404(proceeding_id):
    proceeding = store["proceedings"].get(proceeding_id)
    if proceeding is None:
        err("ERR_NOT_FOUND", "Cancellation proceeding %s does not exist." % proceeding_id)
    return proceeding


@bp.post("/cancellation-proceedings")
def create_proceeding():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["product_id", "proceeding_type", "reason"])
    product_id = as_str(data, "product_id", required=True)
    proceeding_type = as_enum(
        data, "proceeding_type", constants.PROCEEDING_TYPES, required=True
    )
    reason = as_enum(data, "reason", constants.PROCEEDING_REASONS, required=True)

    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    if product["status"] == "CANCELLED":
        err("ERR_PRODUCT_TERMINAL", "The product is CANCELLED.")
    if product["status"] not in ("REGISTERED", "UNDER_REVIEW", "SUSPENDED"):
        err(
            "ERR_PRODUCT_NOT_REGISTERED",
            "Proceedings require the product REGISTERED, UNDER_REVIEW, or SUSPENDED.",
        )

    # Stage 9: at most one non-terminal proceeding per product via this route.
    for proc in store["proceedings"].values():
        if (
            proc["product_id"] == product_id
            and proc["status"] in NON_TERMINAL_PROCEEDING_STATUSES
        ):
            err(
                "ERR_DUPLICATE_OPEN_PROCEEDING",
                "Another non-terminal proceeding of this product exists.",
            )

    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "proceeding_type": proceeding_type,
            "reason": reason,
            "status": "INITIATED",
            "auto_created": False,
            "initiated_by_ref": caller["user_id"],
            "initiated_at": clock.now(),
            "hearing_held_at": None,
            "effective_at": None,
            "vacated_at": None,
            "pre_effective_product_status": None,
            "existing_stocks_authorized_units": None,
            "stocks_method": None,
            "depletion_rate_units_per_month": None,
            "allow_sale_until": None,
            "allow_use_until": None,
            "existing_stocks_disposals": [],
            "existing_stocks_disposed_units": 0,
        }
    )
    store["proceedings"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/cancellation-proceedings")
def list_proceedings():
    require_auth()
    rows = list(store["proceedings"].values())
    for key in ("product_id", "proceeding_type", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/cancellation-proceedings/<proceeding_id>")
def get_proceeding(proceeding_id):
    require_auth()
    return ok(get_proceeding_or_404(proceeding_id))


@bp.post("/cancellation-proceedings/<proceeding_id>/hear")
def hear_proceeding(proceeding_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["hearing_notes"])
    if "hearing_notes" in data and data["hearing_notes"] is not None:
        as_str(data, "hearing_notes")

    proceeding = get_proceeding_or_404(proceeding_id)
    # Hearings exist only for cancellations, and only from INITIATED.
    if proceeding["status"] != "INITIATED" or proceeding["proceeding_type"] != "CANCELLATION":
        err("ERR_PROCEEDING_INVALID_STEP", "Only an INITIATED CANCELLATION can be heard.")

    proceeding["hearing_held_at"] = clock.now()
    proceeding["status"] = "HEARING_HELD"
    if data.get("hearing_notes") is not None:
        proceeding["hearing_notes"] = data["hearing_notes"]
    touch(proceeding)
    return ok(proceeding)


@bp.post("/cancellation-proceedings/<proceeding_id>/issue-order")
def issue_order(proceeding_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(
        data,
        ["existing_stocks_authorized_units", "stocks_method", "depletion_rate_units_per_month"],
    )
    authorized_units = as_int(data, "existing_stocks_authorized_units", required=False)
    stocks_method = as_enum(data, "stocks_method", constants.STOCKS_METHODS, required=False)
    depletion_rate = as_int(data, "depletion_rate_units_per_month", required=False)

    proceeding = get_proceeding_or_404(proceeding_id)

    # Stage 7: the step gate differs by proceeding type.
    if proceeding["proceeding_type"] == "CANCELLATION":
        if proceeding["status"] != "HEARING_HELD":
            err(
                "ERR_PROCEEDING_INVALID_STEP",
                "A cancellation order issues only from HEARING_HELD.",
            )
    else:
        if proceeding["status"] != "INITIATED":
            err(
                "ERR_PROCEEDING_INVALID_STEP",
                "A suspension order issues only from INITIATED.",
            )

    # Segregation of duties: the issuer cannot be the initiator.
    if caller["user_id"] == proceeding["initiated_by_ref"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The proceeding's initiator cannot issue its order.",
        )

    # Existing-stocks conditional requiredness, keyed off the proceeding type.
    if proceeding["proceeding_type"] == "CANCELLATION":
        if authorized_units is None or stocks_method is None:
            err(
                "ERR_INVALID_REQUEST",
                "A cancellation order requires existing_stocks_authorized_units and stocks_method.",
            )
        if authorized_units < 0:
            err(
                "ERR_INVALID_REQUEST",
                "existing_stocks_authorized_units must be at least 0.",
            )
        if stocks_method == "DEPLETION":
            if depletion_rate is None or depletion_rate <= 0:
                err(
                    "ERR_INVALID_REQUEST",
                    "depletion_rate_units_per_month (> 0) is required for DEPLETION.",
                )
        elif depletion_rate is not None:
            err(
                "ERR_INVALID_REQUEST",
                "depletion_rate_units_per_month is forbidden unless stocks_method is DEPLETION.",
            )
    else:
        if (
            authorized_units is not None
            or stocks_method is not None
            or depletion_rate is not None
        ):
            err(
                "ERR_INVALID_REQUEST",
                "A suspension order must carry no existing-stocks fields.",
            )

    now = clock.now()
    product = store["products"][proceeding["product_id"]]
    proceeding["effective_at"] = now
    proceeding["pre_effective_product_status"] = product["status"]
    proceeding["status"] = "EFFECTIVE"
    if proceeding["proceeding_type"] == "CANCELLATION":
        proceeding["existing_stocks_authorized_units"] = authorized_units
        proceeding["stocks_method"] = stocks_method
        proceeding["depletion_rate_units_per_month"] = depletion_rate
        sale_until, use_until = existing_stocks_deadlines(
            now, stocks_method, authorized_units, depletion_rate
        )
        proceeding["allow_sale_until"] = sale_until
        proceeding["allow_use_until"] = use_until
        touch(proceeding)
        cancel_product(product, now)
    else:
        touch(proceeding)
        suspend_product(product, now)
    return ok(proceeding)


@bp.post("/cancellation-proceedings/<proceeding_id>/vacate")
def vacate_proceeding(proceeding_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["vacatur_reason"])
    as_str(data, "vacatur_reason", required=True)

    proceeding = get_proceeding_or_404(proceeding_id)
    if proceeding["status"] not in NON_TERMINAL_PROCEEDING_STATUSES:
        err(
            "ERR_PROCEEDING_INVALID_STEP",
            "Only an INITIATED, HEARING_HELD, or EFFECTIVE proceeding can be vacated.",
        )

    was_effective_cancellation = (
        proceeding["status"] == "EFFECTIVE"
        and proceeding["proceeding_type"] == "CANCELLATION"
    )
    now = clock.now()
    proceeding["vacated_at"] = now
    proceeding["status"] = "VACATED"
    touch(proceeding)

    if was_effective_cancellation:
        vacatur_restore(proceeding, now)
    # Vacating an EFFECTIVE SUSPENSION restores nothing (documented asymmetry).
    return ok(proceeding)


@bp.post("/cancellation-proceedings/<proceeding_id>/existing-stocks-disposals")
def record_disposal(proceeding_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["units", "method"])
    units = as_int(data, "units", required=True)
    method = as_enum(data, "method", constants.DISPOSAL_METHODS, required=True)

    proceeding = get_proceeding_or_404(proceeding_id)

    # Stage 7: EFFECTIVE with a stocks provision.
    if proceeding["status"] != "EFFECTIVE" or proceeding["stocks_method"] is None:
        err(
            "ERR_PROCEEDING_INVALID_STEP",
            "Disposals require an EFFECTIVE proceeding with a stocks provision.",
        )

    # Stage 9: the running total may never exceed the authorized ceiling.
    disposed = proceeding["existing_stocks_disposed_units"]
    if disposed + units > proceeding["existing_stocks_authorized_units"]:
        err(
            "ERR_EXISTING_STOCKS_QUANTITY_EXCEEDED",
            "The disposal would exceed existing_stocks_authorized_units.",
        )

    # Stage 11: SALE/RETURN within the sale window; all methods within the use window.
    now = clock.now()
    if now > proceeding["allow_use_until"]:
        err("ERR_EXISTING_STOCKS_WINDOW_CLOSED", "The use window has closed.")
    if method in ("SALE", "RETURN") and now > proceeding["allow_sale_until"]:
        err("ERR_EXISTING_STOCKS_WINDOW_CLOSED", "The sale window has closed for %s." % method)

    proceeding["existing_stocks_disposals"].append(
        {"disposed_at": now, "units": units, "method": method}
    )
    proceeding["existing_stocks_disposed_units"] = sum(
        d["units"] for d in proceeding["existing_stocks_disposals"]
    )
    touch(proceeding)
    return ok(proceeding)
