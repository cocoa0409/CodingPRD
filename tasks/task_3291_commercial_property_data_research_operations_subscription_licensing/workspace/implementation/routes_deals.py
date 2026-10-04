"""LeaseComparable and SaleTransaction endpoints (PRD 3.3, 3.5, 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers import lease_comparable as ser_comparable
from serializers import sale_transaction as ser_transaction

bp = Blueprint("deals", __name__, url_prefix="/data-research")


@bp.post("/properties/<property_id>/lease-comparables")
def create_lease_comparable(property_id):
    actor = auth.authorize(["ResearchAnalyst"])
    payload = core.body_of(request)
    tenant_name = core.require_string(payload, "tenant_name")
    lease_start = core.require_datetime(payload, "lease_start")
    lease_end = core.require_datetime(payload, "lease_end")
    escalated_rent_psf = core.optional_number(payload, "escalated_rent_psf", None)
    if escalated_rent_psf is None:
        raise core.ApiError("ERR_INVALID_REQUEST", "Missing required field 'escalated_rent_psf'.")
    effective_rent_psf = core.optional_number(payload, "effective_rent_psf", None)
    if effective_rent_psf is None:
        raise core.ApiError("ERR_INVALID_REQUEST", "Missing required field 'effective_rent_psf'.")
    renewal_option = core.optional_bool(payload, "renewal_option", False)
    prop = lookups.scoped_property(property_id, actor)

    if not lease_end > lease_start:
        raise core.ApiError("ERR_LEASE_WINDOW_INVALID")
    if lease_end < core.clock.now():
        raise core.ApiError("ERR_COMP_TEMPORAL_IMPOSSIBLE")

    record = {
        "property_id": prop["id"],
        "tenant_name": tenant_name,
        "lease_start": core.fmt_dt(lease_start),
        "lease_end": core.fmt_dt(lease_end),
        "escalated_rent_psf": float(escalated_rent_psf),
        "effective_rent_psf": float(effective_rent_psf),
        "renewal_option": renewal_option,
        "recorded_at": core.fmt_dt(core.clock.now()),
    }
    core.stamp_created(record)
    core.lease_comparables[record["id"]] = record
    return responses.ok_object(ser_comparable(record), 201)


@bp.get("/lease-comparables")
def list_lease_comparables():
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.lease_comparables.values())
    prop_filter = request.args.get("property_id")
    market_filter = request.args.get("market")
    if prop_filter:
        rows = [c for c in rows if c["property_id"] == prop_filter]
    if market_filter:
        rows = [c for c in rows if (core.properties.get(c["property_id"]) or {}).get("market") == market_filter]
    return responses.paged(rows, limit, offset, ser_comparable)


@bp.get("/lease-comparables/<lease_comparable_id>")
def get_lease_comparable(lease_comparable_id):
    auth.authorize(["ResearchAnalyst", "SeatUser", "LicensingAdmin"])
    record = lookups.get_comparable(lease_comparable_id)
    return responses.ok_object(ser_comparable(record))


@bp.post("/properties/<property_id>/sale-transactions")
def create_sale_transaction(property_id):
    actor = auth.authorize(["ResearchAnalyst"])
    payload = core.body_of(request)
    buyer_name = core.require_string(payload, "buyer_name")
    close_date = core.require_datetime(payload, "close_date")
    gross_sale_price_cents = core.require_int(payload, "gross_sale_price_cents")
    prop = lookups.scoped_property(property_id, actor)

    if prop["research_status"] not in ("RESEARCHING", "VERIFIED"):
        raise core.ApiError("ERR_SALE_PROPERTY_NOT_RESEARCHED")
    if gross_sale_price_cents <= 0:
        raise core.ApiError("ERR_SALE_PRICE_NOT_POSITIVE")

    rate, _source = calc.cap_rate_bps(prop, gross_sale_price_cents)
    record = {
        "property_id": prop["id"],
        "buyer_name": buyer_name,
        "close_date": core.fmt_dt(close_date),
        "gross_sale_price_cents": gross_sale_price_cents,
        "cap_rate_bps": rate,
        "subordination_deadline": core.fmt_dt(
            close_date + timedelta(days=core.SUBORDINATION_DEADLINE_DAYS)),
        "subordination_status": "PENDING",
        "subordinated_at": None,
        "subordinating_case_id": None,
        "rolled_attributions": 0,
    }
    core.stamp_created(record)
    core.sale_transactions[record["id"]] = record
    # `cap_rate_bps` is derived from the property's verified income, so recording
    # the sale recomputes the property's derived state.
    calc.refresh_property_state(prop, "PROVISIONAL")
    return responses.ok_object(ser_transaction(record), 201)


@bp.get("/sale-transactions")
def list_sale_transactions():
    auth.authorize(["ResearchAnalyst", "LicensingAdmin", "EnforcementOfficer"])
    limit, offset = core.pagination_args(request)
    rows = list(core.sale_transactions.values())
    for param, field in (
        ("property_id", "property_id"),
        ("subordinating_case_id", "subordinating_case_id"),
        ("subordination_status", "subordination_status"),
    ):
        wanted = request.args.get(param)
        if wanted:
            rows = [t for t in rows if t[field] == wanted]
    return responses.paged(rows, limit, offset, ser_transaction)


@bp.get("/sale-transactions/<transaction_id>")
def get_sale_transaction(transaction_id):
    auth.authorize(["ResearchAnalyst", "LicensingAdmin", "EnforcementOfficer"])
    record = lookups.get_transaction(transaction_id)
    return responses.ok_object(ser_transaction(record))


@bp.post("/sale-transactions/<transaction_id>/subordinations")
def subordinate_transaction(transaction_id):
    actor = auth.authorize(["EnforcementOfficer", "LicensingAdmin"])
    payload = core.body_of(request)
    case_id = core.require_string(payload, "subordinating_case_id")
    expected_version = core.require_int(payload, "expected_transaction_version")
    record = lookups.get_transaction(transaction_id)
    lookups.get_case(case_id)

    if record["subordination_status"] != "PENDING":
        raise core.ApiError("ERR_INVALID_STATE")
    if core.clock.now() >= core.parse_dt(record["subordination_deadline"]):
        raise core.ApiError("ERR_SUBORDINATION_DEADLINE_PASSED")
    if expected_version != record["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    record["subordination_status"] = "SUBORDINATED"
    record["subordinated_at"] = core.fmt_dt(core.clock.now())
    record["subordinating_case_id"] = case_id
    record["rolled_attributions"] = record["rolled_attributions"] + 1
    core.touch(record)

    prop = core.properties.get(record["property_id"])
    if prop is not None:
        lookups.recompute_verified_sale_value(prop)
        core.touch(prop)
    return responses.ok_object(ser_transaction(record))