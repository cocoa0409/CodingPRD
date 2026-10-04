"""CollectionAgency and CollectionAction endpoints (PRD §3.7): AWG and
cross-servicing over ACTIVE debts, the agency selector, the 15-day AWG hearing
window, OCC-guarded collection events, and termination."""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    ACTION_TYPES,
    AWG_DISPOSABLE_PCT,
    AWG_HEARING_WINDOW_DAYS,
    AWG_WEEKLY_FLOOR_CENTS,
    ROLE_TREASURY_OPERATOR,
    ROLE_TREASURY_SUPERVISOR,
)
from db import STORE, clock_now, new_entity, touch
from errors import (
    err_awg_hearing_window_open,
    err_collect_amount_zero,
    err_collect_exceeds_balance,
    err_duplicate_agency_code,
    err_invalid_request,
    err_invalid_state,
    err_no_collection_agency_available,
    err_not_found,
    err_stale_version,
)
from middleware import (
    authenticate,
    get_body,
    list_page,
    require_roles,
    spec_field,
    validate_body,
)
from response import ok, ok_list
from serializers import serialize_action, serialize_agency
from services.ledger import assess_remittance
from services.matching import pick_collection_agency
from util import gen_id, pct_of_cents

bp = Blueprint("collections", __name__)


@bp.post("/collection-agencies")
def create_agency():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    data = validate_body(get_body(), [
        spec_field("agency_code", "str", required=True),
        spec_field("name", "str", required=True),
        spec_field("capacity_max_active", "int", required=True, ge=0),
    ])
    for existing in STORE["agencies"].values():
        if existing["agency_code"] == data["agency_code"]:
            raise err_duplicate_agency_code()
    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "agency_code": data["agency_code"],
        "name": data["name"],
        "capacity_max_active": data["capacity_max_active"],
    })
    STORE["agencies"][ent["id"]] = ent
    return ok(serialize_agency(ent), 201)


@bp.post("/debts/<string:debtId>/collection-actions")
def create_action(debtId):
    """Open an AWG or CROSS_SERVICING action on an ACTIVE debt; the debt flips
    to IN_COLLECTION (which is also why at most one open action exists)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    data = validate_body(get_body(), [
        spec_field("action_type", "enum", required=True, enum=ACTION_TYPES),
        spec_field("notice_sent_at", "dt", required=False),
        spec_field("disposable_pay_estimate_cents", "int", required=False),
    ])
    # Disjoint payloads (PRD §3.7): AWG requires both fields; CROSS_SERVICING
    # forbids both.
    if data["action_type"] == "AWG":
        if data["notice_sent_at"] is None:
            raise err_invalid_request("notice_sent_at is required when action_type is AWG")
        if data["disposable_pay_estimate_cents"] is None:
            raise err_invalid_request("disposable_pay_estimate_cents is required when action_type is AWG")
        if data["disposable_pay_estimate_cents"] < 0:
            raise err_invalid_request("disposable_pay_estimate_cents must be at least 0")
    else:
        if data["notice_sent_at"] is not None:
            raise err_invalid_request("notice_sent_at must be absent when action_type is CROSS_SERVICING")
        if data["disposable_pay_estimate_cents"] is not None:
            raise err_invalid_request("disposable_pay_estimate_cents must be absent when action_type is CROSS_SERVICING")

    debt = STORE["debts"].get(debtId)
    if debt is None:
        raise err_not_found("Debt not found")
    if debt["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE debt can enter collection")

    agency_id = None
    projected = None
    if data["action_type"] == "CROSS_SERVICING":
        agency = pick_collection_agency()
        if agency is None:
            # Selector gate: empty pool fails outright, debt unchanged.
            raise err_no_collection_agency_available()
        agency_id = agency["id"]
    else:
        # PROVISIONAL variant: 15% of the estimate rounded half up; the
        # statutory floor is deliberately not applied at projection time.
        projected = pct_of_cents(data["disposable_pay_estimate_cents"], AWG_DISPOSABLE_PCT)

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "debt_id": debtId,
        "collection_agency_id": agency_id,
        "action_type": data["action_type"],
        "notice_sent_at": data["notice_sent_at"],
        "disposable_pay_estimate_cents": data["disposable_pay_estimate_cents"],
        "projected_per_period_cents": projected,
        "collected_total_cents": 0,
        "status": "INITIATED",
    })
    STORE["actions"][ent["id"]] = ent
    debt["status"] = "IN_COLLECTION"
    touch(debt)
    return ok(serialize_action(ent), 201)


@bp.get("/collection-actions/<string:collectionActionId>")
def get_action(collectionActionId):
    authenticate()
    action = STORE["actions"].get(collectionActionId)
    if action is None:
        raise err_not_found("Collection action not found")
    return ok(serialize_action(action))


@bp.get("/collection-actions")
def list_actions():
    authenticate()
    items = list(STORE["actions"].values())
    debt_id = request.args.get("debt_id")
    collection_agency_id = request.args.get("collection_agency_id")
    status = request.args.get("status")
    if debt_id is not None:
        items = [a for a in items if a["debt_id"] == debt_id]
    if collection_agency_id is not None:
        items = [a for a in items if a["collection_agency_id"] == collection_agency_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset_n, total = list_page(items)
    return ok_list([serialize_action(a) for a in page], limit, offset_n, total)


@bp.post("/collection-actions/<string:collectionActionId>/activate")
def activate_action(collectionActionId):
    """INITIATED -> ACTIVE. AWG requires the 15-day hearing window to have
    elapsed (equality activates); CROSS_SERVICING has no waiting period."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    validate_body(get_body(), [])
    action = STORE["actions"].get(collectionActionId)
    if action is None:
        raise err_not_found("Collection action not found")
    if action["status"] != "INITIATED":
        raise err_invalid_state("Only an INITIATED action can be activated")
    if action["action_type"] == "AWG":
        if clock_now() < action["notice_sent_at"] + timedelta(days=AWG_HEARING_WINDOW_DAYS):
            raise err_awg_hearing_window_open()
    action["status"] = "ACTIVE"
    touch(action)
    return ok(serialize_action(action))


@bp.post("/collection-actions/<string:collectionActionId>/collect")
def collect_action(collectionActionId):
    """Record a collection event on an ACTIVE action (self-transition),
    OCC-guarded on the debt's version (PRD §2.7)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    body = get_body()
    data = validate_body(body, [
        spec_field("expected_debt_version", "int", required=True),
        spec_field("disposable_pay_cents", "int", required=False),
        spec_field("remitted_amount_cents", "int", required=False),
    ])
    action = STORE["actions"].get(collectionActionId)
    if action is None:
        raise err_not_found("Collection action not found")
    # Type-conditional fields (tier 4), resolvable once the action is loaded.
    if action["action_type"] == "AWG":
        if data["disposable_pay_cents"] is None:
            raise err_invalid_request("disposable_pay_cents is required for an AWG collect")
        if data["disposable_pay_cents"] < 0:
            raise err_invalid_request("disposable_pay_cents must be at least 0")
        if data["remitted_amount_cents"] is not None:
            raise err_invalid_request("remitted_amount_cents must be absent for an AWG collect")
    else:
        if data["remitted_amount_cents"] is None:
            raise err_invalid_request("remitted_amount_cents is required for a CROSS_SERVICING collect")
        if data["remitted_amount_cents"] <= 0:
            raise err_invalid_request("remitted_amount_cents must be greater than 0")
        if data["disposable_pay_cents"] is not None:
            raise err_invalid_request("disposable_pay_cents must be absent for a CROSS_SERVICING collect")

    if action["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE action can collect")
    debt = STORE["debts"].get(action["debt_id"])
    if data["expected_debt_version"] != debt["version"]:
        raise err_stale_version()

    if action["action_type"] == "AWG":
        # STATUTORY_FINAL: min(15% of D rounded half up, D minus the protected
        # weekly floor floored at zero); collected is capped at the balance.
        pay = data["disposable_pay_cents"]
        garnishment = min(
            pct_of_cents(pay, AWG_DISPOSABLE_PCT),
            max(0, pay - AWG_WEEKLY_FLOOR_CENTS),
        )
        if garnishment == 0:
            raise err_collect_amount_zero()
        collected = min(garnishment, debt["current_balance_cents"])
    else:
        if data["remitted_amount_cents"] > debt["current_balance_cents"]:
            raise err_collect_exceeds_balance()
        collected = data["remitted_amount_cents"]

    # One request, three records: debt balance + version, creditor ledger net
    # of the §2.9 fee (tiered on the pre-event YTD), action collected total.
    debt["current_balance_cents"] -= collected
    paid_off = debt["current_balance_cents"] == 0
    if paid_off and debt["status"] in ("ACTIVE", "IN_COLLECTION"):
        debt["status"] = "PAID_IN_FULL"
    touch(debt)
    creditor = STORE["creditors"].get(debt["creditor_agency_id"])
    if creditor is not None:
        assess_remittance(creditor, collected)
    action["collected_total_cents"] += collected
    if paid_off:
        action["status"] = "COMPLETED"
    touch(action)
    return ok(serialize_action(action))


@bp.post("/collection-actions/<string:collectionActionId>/terminate")
def terminate_action(collectionActionId):
    """INITIATED/ACTIVE -> TERMINATED; the debt returns to ACTIVE since the
    terminated action was the only open one (PRD §3.7)."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    validate_body(get_body(), [])
    action = STORE["actions"].get(collectionActionId)
    if action is None:
        raise err_not_found("Collection action not found")
    if action["status"] not in ("INITIATED", "ACTIVE"):
        raise err_invalid_state("Only an open (INITIATED or ACTIVE) action can be terminated")
    action["status"] = "TERMINATED"
    touch(action)
    debt = STORE["debts"].get(action["debt_id"])
    if debt is not None and debt["status"] == "IN_COLLECTION":
        debt["status"] = "ACTIVE"
        touch(debt)
    return ok(serialize_action(action))
