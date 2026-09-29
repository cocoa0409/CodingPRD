"""The property improvement plan: scope, cost allocation, deadlines, completion,
verification, extensions and the compliance sweep (PRD 3.7)."""

from flask import Blueprint

import calc
import domain
import envelope
import store
import validation
from auth import ROLE_BSD, ROLE_FDM, ROLE_OWNER, authenticate
from errors import ApiError
from serialize import dump, dump_all
from store import touch

bp = Blueprint("pips", __name__)

CATEGORIES = (
    "LIFE_SAFETY",
    "GUESTROOM",
    "EXTERIOR",
    "TECHNOLOGY",
    "FOOD_BEVERAGE",
)
PRIORITIES = ("CRITICAL", "MAJOR", "MINOR")
ITEM_SPECS = [
    {"name": "category", "type": "enum", "required": True, "values": CATEGORIES},
    {"name": "priority", "type": "enum", "required": True, "values": PRIORITIES},
    {"name": "description", "type": "string", "required": True, "min_len": 1,
     "max_len": 500},
    {"name": "estimated_cost", "type": "number", "required": True, "minimum": "0.00"},
]
SWEEPABLE_STATUSES = ("ACCEPTED", "IN_PROGRESS", "DEFAULTED")
WORKING_PLAN_STATUSES = ("ACCEPTED", "IN_PROGRESS")


def _owner_of_pip(principal, pip):
    domain.require_agreement_owner(principal, store.agreement_of_pip(pip))


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


@bp.post("/agreements/<agreement_id>/pips")
def create_pip(agreement_id):
    authenticate((ROLE_BSD,))
    agreement = store.get_agreement(agreement_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "scope_notes", "type": "string", "required": True, "min_len": 1,
          "max_len": 2000}],
    )
    if agreement["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")
    row = domain.new_pip_row(agreement)
    row["scope_notes"] = fields["scope_notes"]
    store.pips[row["id"]] = row
    return envelope.created(dump(row))


@bp.get("/agreements/<agreement_id>/pips")
def list_agreement_pips(agreement_id):
    principal = authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    limit, offset = envelope.pagination()
    status = validation.query_filter("status")
    rows = store.ordered(
        store.pips,
        lambda p: p["agreement_id"] == agreement["id"]
        and (status is None or p["status"] == status),
    )
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.get("/pips/<pip_id>")
def read_pip(pip_id):
    principal = authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    pip = store.get_pip(pip_id)
    _owner_of_pip(principal, pip)
    return envelope.ok(dump(pip))


# ---------------------------------------------------------------------------
# Scope lines
# ---------------------------------------------------------------------------


@bp.post("/pips/<pip_id>/items")
def create_item(pip_id):
    authenticate((ROLE_BSD,))
    pip = store.get_pip(pip_id)
    payload = validation.body()
    fields = validation.take(payload, ITEM_SPECS)
    if pip["status"] != "SCOPED":
        raise ApiError("ERR_PIP_NOT_SCOPED")
    row = domain.new_item_row(pip)
    for spec in ITEM_SPECS:
        row[spec["name"]] = fields[spec["name"]]
    store.pip_items[row["id"]] = row
    domain.pip_recount(pip)
    domain.pip_recost(pip)
    touch(pip)
    return envelope.created(dump(row))


@bp.get("/pips/<pip_id>/items")
def list_items(pip_id):
    principal = authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    pip = store.get_pip(pip_id)
    _owner_of_pip(principal, pip)
    limit, offset = envelope.pagination()
    status = validation.query_filter("status")
    rows = store.ordered(
        store.pip_items,
        lambda i: i["pip_id"] == pip["id"] and (status is None or i["status"] == status),
    )
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


# ---------------------------------------------------------------------------
# Acceptance and the frozen cost allocation
# ---------------------------------------------------------------------------


@bp.post("/pips/<pip_id>/accept")
def accept_pip(pip_id):
    principal = authenticate((ROLE_OWNER,))
    pip = store.get_pip(pip_id)
    _owner_of_pip(principal, pip)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "acknowledgement", "type": "string", "required": True, "min_len": 1}],
    )
    if pip["status"] != "SCOPED":
        raise ApiError("ERR_PIP_NOT_SCOPED")
    items = store.items_of_pip(pip)
    if not items:
        raise ApiError("ERR_PIP_NOT_SCOPED", "The plan carries no scope line to price.")
    agreement = store.agreement_of_pip(pip)
    if agreement["status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_EXECUTED")

    accepted_at = domain.now()
    pip["accepted_at"] = accepted_at
    pip["acknowledgement"] = fields["acknowledgement"]
    domain.pip_recost(pip)
    allocation = calc.pip_cost_allocation(
        pip["total_estimated_cost"], domain.room_count_of_agreement(agreement)
    )
    pip.update(allocation)
    for item in items:
        domain.item_stamp_due_dates(item, accepted_at)
        touch(item)
    domain.pip_refresh_deadline(pip)
    pip["status"] = "ACCEPTED"
    touch(pip)
    return envelope.ok(dump(pip))


# ---------------------------------------------------------------------------
# Reporting work complete and verifying it
# ---------------------------------------------------------------------------


@bp.post("/pip-items/<item_id>/complete")
def complete_item(item_id):
    principal = authenticate((ROLE_OWNER,))
    item = store.get_pip_item(item_id)
    pip = store.pip_of_item(item)
    _owner_of_pip(principal, pip)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "completion_evidence", "type": "string", "required": True,
          "min_len": 1}],
    )
    if item["status"] != "PENDING":
        raise ApiError("ERR_PIP_ITEM_STAGE_INVALID")
    if pip["status"] not in WORKING_PLAN_STATUSES:
        raise ApiError("ERR_PIP_NOT_ACCEPTED")
    if item["due_date"] is not None and domain.now() > item["due_date"]:
        raise ApiError("ERR_PIP_ITEM_PAST_DUE")

    item["status"] = "SUBMITTED"
    item["completion_evidence"] = fields["completion_evidence"]
    item["completed_at"] = domain.now()
    touch(item)
    if pip["status"] == "ACCEPTED":
        pip["status"] = "IN_PROGRESS"
    domain.pip_recount(pip)
    touch(pip)
    return envelope.ok(dump(item))


@bp.post("/pip-items/<item_id>/verify")
def verify_item(item_id):
    authenticate((ROLE_BSD,))
    item = store.get_pip_item(item_id)
    pip = store.pip_of_item(item)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "outcome", "type": "enum", "required": True,
             "values": ("VERIFY", "REJECT")},
            {"name": "verification_notes", "type": "string", "required": True,
             "min_len": 1},
        ],
    )
    if item["status"] != "SUBMITTED":
        raise ApiError("ERR_PIP_ITEM_STAGE_INVALID")

    if fields["outcome"] == "VERIFY":
        item["status"] = "VERIFIED"
        item["verified_at"] = domain.now()
    else:
        item["status"] = "PENDING"
        item["rejection_count"] = item["rejection_count"] + 1
    touch(item)
    domain.pip_recount(pip)
    if (
        fields["outcome"] == "VERIFY"
        and pip["items_verified_count"] == pip["items_total_count"]
    ):
        pip["status"] = "COMPLETED"
    touch(pip)
    return envelope.ok(dump(item))


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------


@bp.post("/pip-items/<item_id>/extension-request")
def request_extension(item_id):
    principal = authenticate((ROLE_OWNER,))
    item = store.get_pip_item(item_id)
    pip = store.pip_of_item(item)
    _owner_of_pip(principal, pip)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "requested_days", "type": "integer", "required": True},
            {"name": "reason", "type": "string", "required": True, "min_len": 1},
        ],
    )
    if item["status"] not in ("PENDING", "SUBMITTED", "OVERDUE"):
        raise ApiError("ERR_PIP_ITEM_STAGE_INVALID")
    if item["category"] == "LIFE_SAFETY":
        raise ApiError("ERR_LIFE_SAFETY_NOT_EXTENDABLE")
    if item["extension_request_count"] >= calc.MAX_EXTENSION_REQUESTS_PER_ITEM:
        raise ApiError("ERR_EXTENSION_LIMIT_EXCEEDED")
    if item["status"] == "OVERDUE" and pip["status"] != "DEFAULTED":
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED")

    item["extension_status"] = "PENDING"
    item["extension_requested_days"] = fields["requested_days"]
    item["extension_reason"] = fields["reason"]
    item["extension_request_count"] = item["extension_request_count"] + 1
    touch(item)
    return envelope.ok(dump(item))


@bp.post("/pip-items/<item_id>/extension-decision")
def decide_extension(item_id):
    authenticate((ROLE_BSD,))
    item = store.get_pip_item(item_id)
    pip = store.pip_of_item(item)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "outcome", "type": "enum", "required": True,
             "values": ("GRANT", "DENY")},
            {"name": "decision_notes", "type": "string", "required": False,
             "nullable": True},
        ],
    )
    if item["extension_status"] != "PENDING":
        raise ApiError("ERR_EXTENSION_NOT_PENDING")

    if fields["outcome"] == "DENY":
        item["extension_status"] = "DENIED"
        touch(item)
        return envelope.ok(dump(item))

    awarded = calc.grant_days(
        item["extension_requested_days"],
        item["extension_granted_days_total"],
        pip["extension_granted_days_total"],
    )
    item["extension_status"] = "GRANTED"
    item["extension_granted_days_total"] = (
        item["extension_granted_days_total"] + awarded
    )
    domain.item_recompute_due_date(item)
    was_overdue = item["status"] == "OVERDUE"
    recovered = False
    if was_overdue and item["due_date"] is not None and item["due_date"] >= domain.now():
        item["status"] = "PENDING"
        item["overdue_at"] = None
        recovered = True
    touch(item)

    domain.pip_refresh_extension_total(pip)
    domain.pip_refresh_deadline(pip)
    domain.pip_recount(pip)
    if (
        recovered
        and pip["status"] == "DEFAULTED"
        and not domain.blocking_overdue_items(pip)
    ):
        pip["status"] = "IN_PROGRESS"
    touch(pip)
    return envelope.ok(dump(item))


# ---------------------------------------------------------------------------
# The compliance sweep
# ---------------------------------------------------------------------------


@bp.post("/pips/<pip_id>/compliance-sweep")
def compliance_sweep(pip_id):
    authenticate((ROLE_BSD,))
    pip = store.get_pip(pip_id)
    validation.body()
    if pip["status"] not in SWEEPABLE_STATUSES:
        raise ApiError("ERR_PIP_NOT_SCOPED")

    stamp = domain.now()
    escalate = False
    for item in store.items_of_pip(pip):
        if item["status"] not in ("PENDING", "SUBMITTED"):
            continue
        if item["due_date"] is None or item["due_date"] >= stamp:
            continue
        item["status"] = "OVERDUE"
        item["overdue_at"] = stamp
        touch(item)
        if item["priority"] == "CRITICAL" or item["category"] == "LIFE_SAFETY":
            escalate = True
    domain.pip_recount(pip)
    if escalate:
        pip["status"] = "DEFAULTED"
    touch(pip)
    if escalate:
        domain.raise_pip_default_notice(store.agreement_of_pip(pip))
    return envelope.ok(dump(pip))
