"""Store registration, reads, the fund ledger, MWR program list and the
period-close checkpoint (PRD 3.1, 3.6, 3.9)."""

from flask import Blueprint

import constants as C
import derive
import lookups
import service_fund
import serialize
import validation as V
from db import db, new_record, sorted_records
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("stores", __name__)


@bp.post("/stores")
def create_store():
    V.authenticate(("SurchargeFundController",))
    body = V.raw_body()
    name = V.want_string(body, "name", required=True, min_len=1, max_len=120)
    channel = V.want_enum(body, "channel", C.CHANNELS, required=True)
    region = V.want_enum(body, "region", C.REGIONS, required=True)
    surcharge_rate_bp = V.want_int(body, "surcharge_rate_bp", required=False, minimum=0,
                                   maximum=1000, default=500)
    exchange_markup_bp = V.want_int(body, "exchange_markup_bp", required=False, minimum=0,
                                    maximum=5000, default=0)
    capacity = V.want_int(body, "shelf_block_capacity_facings", required=False, minimum=1,
                          default=24)

    # Field consistency runs after the payload has been schema-validated.
    if channel == "COMMISSARY" and exchange_markup_bp != 0:
        raise ApiError("ERR_MARKUP_FORBIDDEN_IN_COMMISSARY")

    store = new_record()
    store.update({
        "name": name,
        "channel": channel,
        "region": region,
        "surcharge_rate_bp": surcharge_rate_bp,
        "exchange_markup_bp": exchange_markup_bp,
        "shelf_block_capacity_facings": capacity,
        "period_close_index": 0,
    })
    db.stores[store["id"]] = store
    return object_response(serialize.store_out(store), 201)


@bp.get("/stores")
def list_stores():
    V.authenticate((
        "SurchargeFundController",
        "AssortmentPlanner",
        "ComplianceOfficer",
        "MwrBoardOfficer",
    ))
    limit, offset = V.pagination()
    channel = V.query_enum("channel", C.CHANNELS)
    region = V.query_enum("region", C.REGIONS)
    rows = sorted_records(db.stores)
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if region is not None:
        rows = [r for r in rows if r["region"] == region]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.store_out(r) for r in page], limit, offset, total)


@bp.get("/stores/<store_id>")
def read_store(store_id):
    V.authenticate((
        "SurchargeFundController",
        "AssortmentPlanner",
        "ComplianceOfficer",
        "MwrBoardOfficer",
        "StoreCashier",
    ))
    store = lookups.store(store_id)
    return object_response(serialize.store_out(store), 200)


@bp.post("/stores/<store_id>/close-period")
def close_period(store_id):
    V.authenticate(("SurchargeFundController",))
    store = lookups.store(store_id)
    service_fund.close_period(store)
    return object_response(serialize.store_out(store), 200)


@bp.get("/stores/<store_id>/fund-ledger")
def read_fund_ledger(store_id):
    V.authenticate(("SurchargeFundController", "MwrBoardOfficer", "ComplianceOfficer"))
    store = lookups.store(store_id)
    limit, offset = V.pagination()
    fund = V.query_enum("fund", C.FUNDS)
    entry_type = V.query_enum("entry_type", C.ENTRY_TYPES)
    rows = derive.ledger_entries_of(store["id"])
    if fund is not None:
        rows = [r for r in rows if r["fund"] == fund]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.ledger_entry_out(r) for r in page], limit, offset, total)


@bp.get("/stores/<store_id>/mwr-programs")
def read_store_programs(store_id):
    V.authenticate(("MwrBoardOfficer", "SurchargeFundController"))
    store = lookups.store(store_id)
    limit, offset = V.pagination()
    status = V.query_enum("status", C.PROGRAM_STATUSES)
    rows = service_fund.programs_of_store(store["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.program_out(r) for r in page], limit, offset, total)
