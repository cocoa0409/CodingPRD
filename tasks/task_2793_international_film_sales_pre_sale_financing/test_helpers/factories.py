"""Request-payload factories.

Each factory returns the payload for exactly one declared operation, filled with
the canonical slate defaults, and lets a caller override any field with a keyword
argument.  Money is always a JSON number, never a string.
"""

from .constants import (
    ACCOUNT_BANK_NAME,
    ACCOUNT_REFERENCE,
    AGREEMENT_COMMISSION_PCT,
    AGREEMENT_EXPENSE_CAP,
    AGREEMENT_TERM_MONTHS,
    AGREEMENT_TERM_START,
    BOND_AMOUNT,
    BOND_PROVIDER,
    BUYER_EXPOSURE_LIMIT,
    BUYER_NAME,
    BUYER_RATING,
    CONTRACT_HOLDBACK_DAYS,
    CONTRACT_MG,
    CONTRACT_TERM_MONTHS,
    FACILITY_ADVANCE_RATE,
    FACILITY_CAP,
    FACILITY_DISCOUNT_RATE,
    FILM_BUDGET,
    FILM_CAST_SCORE,
    FILM_DELIVERY_DATE,
    FILM_GENRE,
    FILM_RELEASE_DATE,
    FILM_TITLE,
    LENDER_NAME,
    MARKET_CITY,
    MARKET_END,
    MARKET_NAME,
    MARKET_ROOMS,
    MARKET_START,
    MARKET_TABLES,
    MIN_LEGAL_ITEMS,
    MIN_TECHNICAL_ITEMS,
    TERRITORY_DE_CODE,
    TERRITORY_DE_INDEX,
)


def _merge(base, overrides):
    """Apply overrides; a value of None removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def clock_payload(to_iso8601, **overrides):
    return _merge({"to_iso8601": to_iso8601}, overrides)


# --------------------------------------------------------------------------
# Film
# --------------------------------------------------------------------------
def film_payload(**overrides):
    return _merge(
        {
            "title": FILM_TITLE,
            "genre": FILM_GENRE,
            "production_budget_usd": FILM_BUDGET,
            "principal_cast_score": FILM_CAST_SCORE,
            "estimated_delivery_date": FILM_DELIVERY_DATE,
            "theatrical_release_date": FILM_RELEASE_DATE,
        },
        overrides,
    )


def film_amendment_payload(**overrides):
    """An amendment touches only completion_status, principal_cast_score,
    theatrical_release_date and estimated_delivery_date."""
    return dict(overrides)


def state_payload(to_status, **overrides):
    return _merge({"to_status": to_status}, overrides)


# --------------------------------------------------------------------------
# Sales agency agreement
# --------------------------------------------------------------------------
def agreement_payload(**overrides):
    return _merge(
        {
            "commission_pct": AGREEMENT_COMMISSION_PCT,
            "expense_cap_usd": AGREEMENT_EXPENSE_CAP,
            "term_months": AGREEMENT_TERM_MONTHS,
            "term_start_date": AGREEMENT_TERM_START,
        },
        overrides,
    )


def expense_payload(amount_usd, memo="market travel and shipping", **overrides):
    return _merge({"amount_usd": amount_usd, "memo": memo}, overrides)


# --------------------------------------------------------------------------
# Territory and comparable titles
# --------------------------------------------------------------------------
def territory_payload(**overrides):
    return _merge(
        {
            "code": TERRITORY_DE_CODE,
            "name": "Germany",
            "region": "EMEA",
            "market_tier": 1,
            "currency_code": "EUR",
            "base_value_index": TERRITORY_DE_INDEX,
        },
        overrides,
    )


def comparable_payload(gross_license_fee_usd, release_year, **overrides):
    return _merge(
        {
            "name": "Comparable Title",
            "genre": FILM_GENRE,
            "cast_score": 80,
            "gross_license_fee_usd": gross_license_fee_usd,
            "release_year": release_year,
            "verified": True,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Buyer
# --------------------------------------------------------------------------
def buyer_payload(**overrides):
    return _merge(
        {
            "company_name": BUYER_NAME,
            "credit_rating": BUYER_RATING,
            "exposure_limit_usd": BUYER_EXPOSURE_LIMIT,
        },
        overrides,
    )


def buyer_amendment_payload(**overrides):
    """Only status, credit_rating and exposure_limit_usd are amendable."""
    return dict(overrides)


# --------------------------------------------------------------------------
# Territory valuation
# --------------------------------------------------------------------------
def valuation_payload(film_id, territory_id, method="CAST_ADJUSTED", **overrides):
    return _merge(
        {"film_id": film_id, "territory_id": territory_id, "method": method}, overrides
    )


def publish_payload(expected_film_version, **overrides):
    return _merge({"expected_film_version": expected_film_version}, overrides)


# --------------------------------------------------------------------------
# Market, screening slots, buyer meetings
# --------------------------------------------------------------------------
def market_payload(**overrides):
    return _merge(
        {
            "name": MARKET_NAME,
            "city": MARKET_CITY,
            "start_date": MARKET_START,
            "end_date": MARKET_END,
            "screening_room_count": MARKET_ROOMS,
            "meeting_table_count": MARKET_TABLES,
        },
        overrides,
    )


def screening_slot_payload(market_id, film_id, room_number, start_at, end_at, **overrides):
    return _merge(
        {
            "market_id": market_id,
            "film_id": film_id,
            "room_number": room_number,
            "start_at": start_at,
            "end_at": end_at,
            "slot_type": "BUYER_SCREENING",
            "capacity": 120,
        },
        overrides,
    )


def buyer_meeting_payload(
    market_id, buyer_id, film_id, table_number, start_at, end_at, **overrides
):
    return _merge(
        {
            "market_id": market_id,
            "buyer_id": buyer_id,
            "film_id": film_id,
            "table_number": table_number,
            "start_at": start_at,
            "end_at": end_at,
        },
        overrides,
    )


def meeting_completion_payload(outcome="INTERESTED", **overrides):
    return _merge({"to_status": "COMPLETED", "outcome": outcome}, overrides)


# --------------------------------------------------------------------------
# Pre-sale contract
# --------------------------------------------------------------------------
def contract_payload(film_id, buyer_id, territory_id, expected_buyer_version, **overrides):
    return _merge(
        {
            "film_id": film_id,
            "buyer_id": buyer_id,
            "territory_id": territory_id,
            "minimum_guarantee_usd": CONTRACT_MG,
            "license_term_months": CONTRACT_TERM_MONTHS,
            "holdback_days": CONTRACT_HOLDBACK_DAYS,
            "expected_buyer_version": expected_buyer_version,
        },
        overrides,
    )


def counter_payload(counter_minimum_guarantee_usd, **overrides):
    return _merge(
        {"counter_minimum_guarantee_usd": counter_minimum_guarantee_usd}, overrides
    )


def revise_payload(minimum_guarantee_usd, **overrides):
    return _merge({"minimum_guarantee_usd": minimum_guarantee_usd}, overrides)


def lapse_payload(reason="offer expired unanswered", **overrides):
    return _merge({"reason": reason}, overrides)


def milestone_payload(label, pct_of_mg, due_date, **overrides):
    return _merge(
        {"label": label, "pct_of_mg": pct_of_mg, "due_date": due_date}, overrides
    )


# --------------------------------------------------------------------------
# Deliverable package
# --------------------------------------------------------------------------
def package_payload(
    technical_items_count=MIN_TECHNICAL_ITEMS, legal_items_count=MIN_LEGAL_ITEMS, **overrides
):
    return _merge(
        {
            "technical_items_count": technical_items_count,
            "legal_items_count": legal_items_count,
        },
        overrides,
    )


def qc_pass_payload(**overrides):
    return _merge({"result": "PASS"}, overrides)


def qc_fail_payload(rejection_reason="QC_FAIL", **overrides):
    return _merge({"result": "FAIL", "rejection_reason": rejection_reason}, overrides)


# --------------------------------------------------------------------------
# Receipts
# --------------------------------------------------------------------------
def receipt_payload(amount_usd, received_at, **overrides):
    return _merge({"amount_usd": amount_usd, "received_at": received_at}, overrides)


def reversal_payload(reason="wire posted against the wrong picture", **overrides):
    return _merge({"reason": reason}, overrides)


# --------------------------------------------------------------------------
# Banking facility
# --------------------------------------------------------------------------
def facility_payload(**overrides):
    return _merge(
        {
            "lender_name": LENDER_NAME,
            "discount_rate_pct": FACILITY_DISCOUNT_RATE,
            "advance_rate_pct": FACILITY_ADVANCE_RATE,
            "facility_cap_usd": FACILITY_CAP,
            "completion_bond_required": True,
        },
        overrides,
    )


def completion_bond_payload(**overrides):
    return _merge(
        {"bond_provider": BOND_PROVIDER, "bond_amount_usd": BOND_AMOUNT}, overrides
    )


# --------------------------------------------------------------------------
# Collection account and waterfall
# --------------------------------------------------------------------------
def account_payload(**overrides):
    return _merge(
        {"bank_name": ACCOUNT_BANK_NAME, "account_reference": ACCOUNT_REFERENCE}, overrides
    )


def tier_payload(tier_order, tier_type, pct_of_available, cap_usd=None, **overrides):
    payload = {
        "tier_order": tier_order,
        "tier_type": tier_type,
        "recipient_name": f"{tier_type} recipient",
        "pct_of_available": pct_of_available,
    }
    if cap_usd is not None:
        payload["cap_usd"] = cap_usd
    return _merge(payload, overrides)


def distribute_payload(amount_in_usd, **overrides):
    return _merge({"amount_in_usd": amount_in_usd}, overrides)
