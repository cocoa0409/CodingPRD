"""Accuracy records: the immutable ledger of realised actuals (PRD 3.9)."""
from flask import Blueprint

from auth import (ROLE_CUSTOMER_REP, ROLE_DEMAND_PLANNER,
                  ROLE_DEMAND_REVIEW_LEAD, ROLE_EXECUTIVE_SPONSOR,
                  ROLE_SOP_ADMIN, endpoint, find_or_404, phase_gate,
                  scope_list_customer, scope_row_customer)
from cascades import refresh_family_accuracy
from calcs import calc_accuracy_record
from envelope import respond_list, respond_object
from errors import ApiError
from store import new_row, ordered, public, public_all, store
from validators import (get_body, paginate, pagination, query_str, req_id,
                        req_int)

bp = Blueprint("accuracy", __name__)

WRITE_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER]
READ_ROLES = [ROLE_SOP_ADMIN, ROLE_DEMAND_PLANNER, ROLE_DEMAND_REVIEW_LEAD,
              ROLE_EXECUTIVE_SPONSOR, ROLE_CUSTOMER_REP]


@bp.post("/sop/accuracy-records")
@endpoint(WRITE_ROLES)
def create_accuracy_record():
    body = get_body()
    cycle_id = req_id(body, "cycle_id")
    item_id = req_id(body, "item_id")
    customer_id = req_id(body, "customer_id")
    actual_units = req_int(body, "actual_units", minimum=0)

    cycle = find_or_404("cycles", cycle_id, "ERR_CYCLE_NOT_FOUND")
    item = find_or_404("items", item_id, "ERR_ITEM_NOT_FOUND")
    customer = find_or_404("customers", customer_id, "ERR_CUSTOMER_NOT_FOUND")

    # A record may only be posted while the cycle is PUBLISHED. No role owns the
    # PUBLISHED phase, so the phase-actor rejection always wins here; the frozen
    # barrier deliberately does not cover accuracy-record creation.
    phase_gate(cycle, "PUBLISHED", frozen=False)

    # priority 140 -- the months implied by the scored triple must sit inside
    # the cycle horizon.
    for f in store.forecasts.values():
        if (f["cycle_id"] == cycle_id and f["item_id"] == item_id
                and f["customer_id"] == customer_id
                and f["status"] == "CONSENSUS_LOCKED"
                and (f["month"] < cycle["horizon_start_month"]
                     or f["month"] > cycle["horizon_end_month"])):
            raise ApiError("ERR_MONTH_OUTSIDE_HORIZON",
                           "Month %s falls outside the cycle horizon"
                           % f["month"])

    # priority 150 -- one record per cycle, item and customer triple
    for other in store.accuracy_records.values():
        if (other["cycle_id"] == cycle_id and other["item_id"] == item_id
                and other["customer_id"] == customer_id):
            raise ApiError("ERR_DUPLICATE_ACCURACY_RECORD",
                           "An accuracy record already exists for that cycle, "
                           "item and customer")

    # No updated_at and no version: an accuracy record is an audit fact (2.4).
    row = new_row(with_common=False)
    row.update({
        "cycle_id": cycle_id,
        "item_id": item_id,
        "customer_id": customer_id,
        "actual_units": actual_units,
    })
    row.update(calc_accuracy_record(cycle, item, customer, actual_units))
    store.accuracy_records[row["id"]] = row

    family = store.families.get(item["family_id"])
    if family is not None:
        refresh_family_accuracy(family)

    return respond_object(public(row), 201)


@bp.get("/sop/accuracy-records/<record_id>")
@endpoint(READ_ROLES)
def get_accuracy_record(record_id):
    row = find_or_404("accuracy_records", record_id,
                      "ERR_ACCURACY_RECORD_NOT_FOUND")
    scope_row_customer(row["customer_id"])
    return respond_object(public(row))


@bp.get("/sop/accuracy-records")
@endpoint(READ_ROLES)
def list_accuracy_records():
    limit, offset = pagination()
    scope_list_customer()
    cycle_id = query_str("cycle_id")
    item_id = query_str("item_id")
    customer_id = query_str("customer_id")
    rows = ordered(store.accuracy_records.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if item_id is not None:
        rows = [r for r in rows if r["item_id"] == item_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    page, total = paginate(rows, limit, offset)
    return respond_list(public_all(page), limit, offset, total)
