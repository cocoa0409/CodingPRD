"""Reference data: country profiles, providers and local bank accounts."""
from decimal import Decimal

from flask import Blueprint

import serial
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    BANK_ACCOUNT_STATUSES,
    FILING_TYPES,
    PLATFORM_ADMIN,
    REGIONS,
    SERVICE_SCOPES,
    ApiError,
)
from response import created, object_response, page_response
from store import new_row, touch

bp = Blueprint("estate", __name__)


# ---------------------------------------------------------------------------
# Country profiles
# ---------------------------------------------------------------------------
@bp.post("/payroll/country-profiles")
@require(PLATFORM_ADMIN)
def create_country_profile():
    body = v.json_body()
    country_code = v.req_country_code(body, "country_code")
    local_currency = v.req_currency(body, "local_currency")
    region = v.req_enum(body, "data_residency_region", REGIONS)
    deadline_days = v.req_int(body, "statutory_filing_deadline_days", 1, 90)
    materiality_pct = v.req_pct(body, "materiality_pct", Decimal("0.01"), Decimal("50.00"))
    materiality_floor = v.req_int(body, "materiality_floor_minor", 0)
    penalty_rate = v.req_int(body, "penalty_daily_rate_minor", 1)
    filing_types = v.req_enum_list(body, "required_filing_types", FILING_TYPES, 1, 3)
    holidays = v.opt_date_list(body, "local_holidays", 0, 40, default=[])

    for row in store.country_profiles.values():
        if row["country_code"] == country_code:
            raise ApiError(
                "ERR_DUPLICATE_COUNTRY_CODE",
                "A country profile with this country_code already exists.",
            )

    row = new_row(
        {
            "country_code": country_code,
            "local_currency": local_currency,
            "data_residency_region": region,
            "statutory_filing_deadline_days": deadline_days,
            "materiality_pct": materiality_pct,
            "materiality_floor_minor": materiality_floor,
            "penalty_daily_rate_minor": penalty_rate,
            "required_filing_types": filing_types,
            "local_holidays": holidays,
            "open_filing_obligation_count": 0,
        }
    )
    store.country_profiles[row["id"]] = row
    return created(serial.country_profile(row))


@bp.get("/payroll/country-profiles/<ident>")
@require(*ALL_ROLES)
def read_country_profile(ident):
    return object_response(serial.country_profile(store.get_country(ident)))


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
@bp.post("/payroll/providers")
@require(PLATFORM_ADMIN)
def create_provider():
    body = v.json_body()
    legal_name = v.req_str(body, "legal_name", 1, 120)
    scope = v.req_enum_list(body, "service_scope", SERVICE_SCOPES, 1, 4)
    regions = v.req_enum_list(body, "data_residency_regions", REGIONS, 1, 5)
    annual_fee = v.req_int(body, "annual_fee_minor", 1)
    cap_pct = v.req_pct(body, "indemnity_cap_pct", Decimal("0.00"), Decimal("100.00"))

    row = new_row(
        {
            "legal_name": legal_name,
            "service_scope": scope,
            "data_residency_regions": regions,
            "annual_fee_minor": annual_fee,
            "indemnity_cap_pct": cap_pct,
            "statutory_filing_capable": "STATUTORY_FILING" in scope,
            "status": "ACTIVE",
            "service_score": Decimal("100.00"),
            "score_variant_applied": "ENGAGEMENT_TO_DATE",
            "open_penalty_minor": 0,
        }
    )
    store.providers[row["id"]] = row
    return created(serial.provider(row))


@bp.get("/payroll/providers/<ident>")
@require(*ALL_ROLES)
def read_provider(ident):
    return object_response(serial.provider(store.get_provider(ident)))


# ---------------------------------------------------------------------------
# Local bank accounts
# ---------------------------------------------------------------------------
@bp.post("/payroll/bank-accounts")
@require(PLATFORM_ADMIN)
def create_bank_account():
    body = v.json_body()
    engagement_id = v.req_id(body, "engagement_id")
    account_ref = v.req_str(body, "account_ref", 1, 40)
    currency = v.req_currency(body, "account_currency")
    region = v.req_enum(body, "residency_region", REGIONS)
    daily_cap = v.req_int(body, "daily_cap_minor", 1)
    window_hours = v.req_int(body, "settlement_window_hours", 1, 96)
    buffer_hours = v.req_int(body, "buffer_hours", 0, 48)

    engagement = store.get_engagement(engagement_id)
    if region != engagement["data_residency_region"]:
        raise ApiError(
            "ERR_DATA_RESIDENCY_VIOLATION",
            "The account residency region must equal the engagement's contracted region.",
        )
    country = store.country_of_engagement(engagement)
    if currency != country["local_currency"]:
        raise ApiError(
            "ERR_CURRENCY_MISMATCH",
            "The account currency must equal the country's local currency.",
        )
    for row in store.bank_accounts.values():
        if row["engagement_id"] == engagement_id and row["account_ref"] == account_ref:
            raise ApiError(
                "ERR_DUPLICATE_ACCOUNT_REF",
                "This account_ref is already registered for the engagement.",
            )

    row = new_row(
        {
            "engagement_id": engagement_id,
            "account_ref": account_ref,
            "account_currency": currency,
            "residency_region": region,
            "daily_cap_minor": daily_cap,
            "settlement_window_hours": window_hours,
            "buffer_hours": buffer_hours,
            "status": "PENDING_VERIFICATION",
        }
    )
    store.bank_accounts[row["id"]] = row
    return created(serial.bank_account(row))


@bp.post("/payroll/bank-accounts/<ident>/verify")
@require(PLATFORM_ADMIN)
def verify_bank_account(ident):
    account = store.get_bank_account(ident)
    account["status"] = "VERIFIED"
    touch(account)
    return object_response(serial.bank_account(account))


@bp.get("/payroll/engagements/<ident>/bank-accounts")
@require(*ALL_ROLES)
def list_engagement_bank_accounts(ident):
    limit, offset = v.pagination()
    status = v.query_enum("status", BANK_ACCOUNT_STATUSES)
    engagement = store.get_engagement(ident)
    rows = [a for a in store.bank_accounts.values() if a["engagement_id"] == engagement["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return page_response(store.ordered(rows), serial.bank_account, limit, offset)
