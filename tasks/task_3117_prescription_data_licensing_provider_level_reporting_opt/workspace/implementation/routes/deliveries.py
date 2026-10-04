"""ReportDelivery endpoints: compile, release, recall, reissue."""

from flask import Blueprint

from db import db
from errors import (
    err_not_found,
    err_delivery_invalid_state,
    err_client_suspended,
    err_opt_out_violation,
    err_jurisdiction_restricted,
    err_delivery_window_missed,
    err_product_version_stale,
    err_no_deliverable_cells,
    err_insufficient_entitlement,
)
from middleware import require_role, ALL_ROLES
from response import success_object
from services.calculations import (
    calc_delivery_fee,
    prescriber_has_active_opt_out,
    credit_client,
    debit_client,
    recall_delivery,
)
from services.common import body_json, check_str_list, touch

bp = Blueprint("deliveries", __name__)


def _get_delivery(did):
    delivery = db.deliveries.get(did)
    if delivery is None:
        raise err_not_found("Delivery not found")
    return delivery


def _jurisdiction_restricted(prescriber):
    """True when an effective restrictive rule governs the prescriber's state."""
    today = db.logical_clock.date().isoformat()
    for rule in db.jurisdiction_rules.values():
        if rule["state_code"] != prescriber["state_code"]:
            continue
        if not rule["restrict_prescriber_identifiable"]:
            continue
        if rule["effective_from"] <= today and (
            rule["effective_to"] is None or today < rule["effective_to"]
        ):
            return True
    return False


def _compile_core(delivery, is_reissue):
    """Run the compile/reissue check gauntlet in PRD priority order, then mutate."""
    period = db.periods[delivery["period_id"]]
    product = db.products[period["product_id"]]
    client = db.clients[product["client_id"]]

    # Priority 11: delivery state.
    if is_reissue:
        if delivery["status"] != "RECALLED":
            raise err_delivery_invalid_state("Delivery must be RECALLED to reissue")
    else:
        if delivery["status"] != "SCHEDULED":
            raise err_delivery_invalid_state("Delivery must be SCHEDULED to compile")

    # Priority 13: client and product both ACTIVE.
    if client["status"] != "ACTIVE" or product["status"] != "ACTIVE":
        raise err_client_suspended()

    # Payload: optional include_prescriber_ids (existence validated first, left-to-right).
    data = body_json()
    include_ids = None
    if "include_prescriber_ids" in data and data["include_prescriber_ids"] is not None:
        include_ids = check_str_list(data, "include_prescriber_ids")
        for pid in include_ids:
            if pid not in db.prescribers:
                raise err_not_found("Prescriber not found")

    # Priorities 15/16: safety checks on the supplied panel.
    if include_ids is not None:
        for pid in include_ids:
            if prescriber_has_active_opt_out(pid):
                raise err_opt_out_violation()
        for pid in include_ids:
            if _jurisdiction_restricted(db.prescribers[pid]):
                raise err_jurisdiction_restricted()

    # Priority 19: temporal window against the logical clock.
    if db.logical_clock.date().isoformat() < period["period_end_date"]:
        raise err_delivery_window_missed()

    # Priority 21: pinned methodology version currency.
    methodology = db.methodologies[product["methodology_id"]]
    if product["pinned_methodology_version"] != methodology["version"]:
        raise err_product_version_stale()

    # Priority 22: at least one matching CURRENT cell.
    matching = [
        c for c in db.projection_cells.values()
        if c["methodology_id"] == product["methodology_id"]
        and c["status"] == "CURRENT"
        and c["period_code"] == delivery["period_code"]
    ]
    if not matching:
        raise err_no_deliverable_cells()

    # Priority 25: entitlement balance covers the cells about to be compiled.
    if client["entitlement_cells_balance"] < len(matching):
        raise err_insufficient_entitlement()

    # Success path.
    matching.sort(key=lambda c: (c["geography_code"], c["specialty"], c["created_at"]))
    compiled_ids = [c["id"] for c in matching]
    if include_ids is not None:
        included = list(include_ids)
    else:
        included = [
            pid for pid in product["prescriber_ids"]
            if not prescriber_has_active_opt_out(pid)
            and not _jurisdiction_restricted(db.prescribers[pid])
        ]
    delivery["compiled_cell_ids"] = compiled_ids
    delivery["included_prescriber_ids"] = included
    delivery["fee_cents"] = calc_delivery_fee(product, len(compiled_ids))
    debit_client(client["id"], len(compiled_ids))
    if is_reissue:
        delivery["status"] = "REISSUED"
        delivery["must_recompile"] = False
    else:
        delivery["status"] = "COMPILED"
    touch(delivery)
    return delivery


@bp.route("/report-deliveries/<did>", methods=["GET"])
def get_delivery(did):
    require_role(ALL_ROLES)
    return success_object(_get_delivery(did))


@bp.route("/report-deliveries/<did>/compile", methods=["POST"])
def compile_delivery(did):
    require_role(["PlatformAdmin"])
    delivery = _get_delivery(did)
    return success_object(_compile_core(delivery, is_reissue=False))


@bp.route("/report-deliveries/<did>/release", methods=["POST"])
def release_delivery(did):
    require_role(["PlatformAdmin"])
    delivery = _get_delivery(did)
    if delivery["status"] not in ("COMPILED", "REISSUED") or delivery["must_recompile"]:
        raise err_delivery_invalid_state("Delivery must be COMPILED or REISSUED to release")
    delivery["status"] = "RELEASED"
    touch(delivery)
    return success_object(delivery)


@bp.route("/report-deliveries/<did>/recall", methods=["POST"])
def recall_delivery_endpoint(did):
    require_role(["PlatformAdmin"])
    delivery = _get_delivery(did)
    if delivery["status"] not in ("COMPILED", "RELEASED", "REISSUED"):
        raise err_delivery_invalid_state("Delivery must be COMPILED, RELEASED or REISSUED to recall")
    recall_delivery(delivery)
    return success_object(delivery)


@bp.route("/report-deliveries/<did>/reissue", methods=["POST"])
def reissue_delivery(did):
    require_role(["PlatformAdmin"])
    delivery = _get_delivery(did)
    return success_object(_compile_core(delivery, is_reissue=True))
