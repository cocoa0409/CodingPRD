"""Billing evidence: immutable monthly rows behind account verification."""

from flask import Blueprint, request

from auth import begin, guard_listing
from calc import BILLING_SOURCES, billing_derivations, month_label
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import billing_json
from services import get_account, get_billing_record, listing_of_account
from store import new_record, ordered, store
from validators import body, path_uuid, req_cents, req_enum, req_id, req_month

bp = Blueprint("billing", __name__)


@bp.post("/billing-history-records")
def create_record():
    begin("Broker", "Seller")
    data = body()
    account_id = data.get("account_id")
    if isinstance(account_id, str):
        existing = store.service_accounts.get(account_id)
        if existing is not None:
            guard_listing(listing_of_account(existing))

    account_id = req_id(data, "account_id")
    period_month = req_month(data, "period_month")
    billed_service = req_cents(data, "billed_service_cents")
    billed_chemical = req_cents(data, "billed_chemical_cents")
    billed_repair = req_cents(data, "billed_repair_cents")
    collected = req_cents(data, "collected_cents",
                          maximum=billed_service + billed_chemical + billed_repair)
    source = req_enum(data, "source", BILLING_SOURCES)

    account = get_account(account_id)
    if account["verification_status"] == "EXCLUDED":
        raise ApiError("ERR_ACCOUNT_EXCLUDED",
                       "An account already dropped from the list accepts no new evidence.")

    if period_month >= month_label(store.clock.year, store.clock.month):
        raise ApiError("ERR_TEMPORAL_WINDOW_VIOLATION",
                       "The billing month has not finished yet.")

    for row in store.billing_history_records.values():
        if (row["account_id"] == account_id and row["period_month"] == period_month
                and row["source"] == source):
            raise ApiError("ERR_DUPLICATE_BILLING_PERIOD",
                           "A billing month has already been recorded for this account from "
                           "this source.")

    record = new_record(ledger=True)
    record.update({
        "account_id": account_id,
        "period_month": period_month,
        "billed_service_cents": billed_service,
        "billed_chemical_cents": billed_chemical,
        "billed_repair_cents": billed_repair,
        "collected_cents": collected,
        "source": source,
    })
    record.update(billing_derivations(billed_service, billed_chemical, billed_repair, collected,
                                      account["chemical_billing_method"]))
    store.billing_history_records[record["id"]] = record
    return object_response(billing_json(record), 201)


@bp.get("/billing-history-records/<identifier>")
def read_record(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    existing = store.billing_history_records.get(identifier)
    if existing is not None:
        account = store.service_accounts.get(existing["account_id"])
        if account is not None:
            guard_listing(listing_of_account(account))
    path_uuid(identifier)
    return object_response(billing_json(get_billing_record(identifier)))


@bp.get("/billing-history-records")
def list_records():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in ("account_id", "period_month", "source")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.billing_history_records, keep), billing_json, limit, offset)
