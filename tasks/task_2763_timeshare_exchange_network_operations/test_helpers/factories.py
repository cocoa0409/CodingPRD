"""Payload factories — input fields only, one per operation.

Every cash amount is sent as a JSON number of integer cents (PRD §2.6).
"""

# Fee schedule of the tier used by most scenarios.
PLUS_TIER = {
    "tier_code": "PLUS",
    "annual_dues_cents": 19900,
    "base_exchange_fee_cents": 20900,
    "priority_surcharge_cents": 2500,
    "priority_window_days": 365,
    "deposit_first_bonus_pct": 10,
    "max_active_requests": 3,
    "cancellation_fee_cents": 8900,
    "reinstatement_fee_cents": 10900,
    "extension_fee_cents_per_month": 3400,
}

RESORT_A = {
    "name": "Aspen Ridge Club",
    "region_code": "US-CO",
    "required_annual_deposit_units": 2,
    "initial_quality_rating": "GOLD_CROWN",
    "units_per_size": 2,
    "demand_index": 4,
}

RESORT_B = {
    "name": "Coral Bay Villas",
    "region_code": "MX-QR",
    "required_annual_deposit_units": 1,
    "initial_quality_rating": "SILVER_CROWN",
    "units_per_size": 1,
    "demand_index": 5,
}

RESORT_C = {
    "name": "Pine Hollow Lodge",
    "region_code": "US-MI",
    "required_annual_deposit_units": 1,
    "initial_quality_rating": "STANDARD",
    "units_per_size": 3,
    "demand_index": 2,
}


def membership_tier_payload(**overrides) -> dict:
    payload = dict(PLUS_TIER)
    payload.update(overrides)
    return payload


def resort_payload(**overrides) -> dict:
    payload = dict(RESORT_A)
    payload.update(overrides)
    return payload


def season_band_payload(resort_id, **overrides) -> dict:
    payload = {
        "resort_id": resort_id,
        "band_code": "GOLD",
        "start_month_day": "04-01",
        "end_month_day": "06-30",
    }
    payload.update(overrides)
    return payload


def member_payload(tier_id, **overrides) -> dict:
    payload = {
        "email": "m1@example.com",
        "full_name": "Dana Oyelaran",
        "tier_id": tier_id,
    }
    payload.update(overrides)
    return payload


def dues_payment_payload(expected_member_version, **overrides) -> dict:
    payload = {
        "amount_cents": 100000,
        "paid_through_date": "2030-12-31",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def deposit_payload(member_id, resort_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "resort_id": resort_id,
        "unit_size": "ONE_BR",
        "check_in_date": "2027-06-15",
    }
    payload.update(overrides)
    return payload


def exchange_request_payload(member_id, requested_resort_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "requested_resort_id": requested_resort_id,
        "requested_unit_size": "ONE_BR",
        "window_start_date": "2027-06-01",
        "window_end_date": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def confirmation_payload(exchange_request_id, **overrides) -> dict:
    payload = {"exchange_request_id": exchange_request_id}
    payload.update(overrides)
    return payload


def quality_review_payload(confirmation_id, expected_resort_version, **overrides) -> dict:
    payload = {
        "confirmation_id": confirmation_id,
        "cleanliness_score": 9,
        "service_score": 8,
        "amenities_score": 7,
        "expected_resort_version": expected_resort_version,
    }
    payload.update(overrides)
    return payload


def extension_payload(months, expected_deposit_version, **overrides) -> dict:
    payload = {
        "months": months,
        "expected_deposit_version": expected_deposit_version,
    }
    payload.update(overrides)
    return payload


def matching_run_payload(note="operations run", **overrides) -> dict:
    payload = {"note": note}
    payload.update(overrides)
    return payload


def getaway_booking_payload(member_id, **overrides) -> dict:
    payload = {"member_id": member_id}
    payload.update(overrides)
    return payload


def trading_power_dispute_payload(member_id, deposit_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "subject_type": "TRADING_POWER",
        "deposit_id": deposit_id,
        "narrative": "The banked week was valued below the published schedule.",
    }
    payload.update(overrides)
    return payload


def resort_quality_dispute_payload(
    member_id, resort_id, confirmation_id, **overrides
) -> dict:
    payload = {
        "member_id": member_id,
        "subject_type": "RESORT_QUALITY",
        "resort_id": resort_id,
        "confirmation_id": confirmation_id,
        "narrative": "The unit was not in the advertised condition on arrival.",
    }
    payload.update(overrides)
    return payload


def dispute_info_request_payload(question="Please send the arrival photographs.") -> dict:
    return {"question": question}


def dispute_response_payload(answer="Photographs attached as requested.") -> dict:
    return {"answer": answer}


def dispute_resolution_payload(outcome, resolution_note, **overrides) -> dict:
    payload = {"outcome": outcome, "resolution_note": resolution_note}
    payload.update(overrides)
    return payload


def resort_status_change_payload(to_status, reason=None) -> dict:
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    return payload


def member_status_change_payload(to_status, reason=None) -> dict:
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    return payload


def tier_change_payload(tier_id) -> dict:
    return {"tier_id": tier_id}


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def resort_patch_payload(**fields) -> dict:
    """Operator profile edit; only the named fields are sent."""
    return dict(fields)
