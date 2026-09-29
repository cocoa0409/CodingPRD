"""Payload factories — one per entity, carrying only PRD input fields."""

from .constants import TEST_DEFAULTS


def create_agency_payload(**overrides) -> dict:
    """Agency create body. federal_donee_status / donee_certification_expires_on
    are optional and are only sent when a test overrides them."""
    payload = {
        "name": "State Department of Transportation",
        "agency_code": "DOT-01",
        "agency_type": "STATE_AGENCY",
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": "Austin Surplus Yard",
        "venue_code": "AUS-01",
        "concurrent_lot_capacity": 2,
        "buyer_premium_pct": TEST_DEFAULTS["BUYER_PREMIUM_PCT"],
        "sales_tax_pct": TEST_DEFAULTS["SALES_TAX_PCT"],
    }
    payload.update(overrides)
    return payload


def create_bidder_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Lone Star Salvage LLC",
        "email": "bids@lonestarsalvage.example",
        "bidder_type": "BUSINESS",
    }
    payload.update(overrides)
    return payload


def create_turn_in_payload(turning_in_agency_id: str, **overrides) -> dict:
    payload = {
        "turning_in_agency_id": turning_in_agency_id,
        "custody_location": "Austin Yard 4",
    }
    payload.update(overrides)
    return payload


def create_asset_payload(turn_in_id: str, **overrides) -> dict:
    """A FURNITURE asset by default — the one category with no conditionally
    required fields."""
    payload = {
        "turn_in_id": turn_in_id,
        "category": "FURNITURE",
        "description": "Four-drawer lateral file cabinets, lot of six",
        "acquisition_cost_cents": TEST_DEFAULTS["FURNITURE_COST_CENTS"],
        "acquisition_date": TEST_DEFAULTS["FURNITURE_ACQUISITION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_vehicle_asset_payload(turn_in_id: str, **overrides) -> dict:
    """A VEHICLE asset, which the PRD requires to carry vin, odometer_reading
    and title_number."""
    payload = {
        "turn_in_id": turn_in_id,
        "category": "VEHICLE",
        "description": "2019 Ford F-250 three-quarter ton pickup",
        "acquisition_cost_cents": TEST_DEFAULTS["PICKUP_COST_CENTS"],
        "acquisition_date": TEST_DEFAULTS["PICKUP_ACQUISITION_DATE"],
        "vin": "1FT7W2BT9KEB12345",
        "odometer_reading": 184320,
        "title_number": "TX-88231",
    }
    payload.update(overrides)
    return payload


def create_it_asset_payload(turn_in_id: str, **overrides) -> dict:
    payload = {
        "turn_in_id": turn_in_id,
        "category": "IT_EQUIPMENT",
        "description": "Rack-mounted database server, dual socket",
        "acquisition_cost_cents": TEST_DEFAULTS["SERVER_COST_CENTS"],
        "acquisition_date": TEST_DEFAULTS["SERVER_ACQUISITION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_heavy_equipment_asset_payload(turn_in_id: str, **overrides) -> dict:
    payload = {
        "turn_in_id": turn_in_id,
        "category": "HEAVY_EQUIPMENT",
        "description": "Nine-ton vibratory road roller",
        "acquisition_cost_cents": TEST_DEFAULTS["ROLLER_COST_CENTS"],
        "acquisition_date": TEST_DEFAULTS["ROLLER_ACQUISITION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_restricted_asset_payload(turn_in_id: str, **overrides) -> dict:
    """A RESTRICTED_MILITARY asset. is_restricted true obliges demil_code."""
    payload = {
        "turn_in_id": turn_in_id,
        "category": "RESTRICTED_MILITARY",
        "description": "Armoured personnel carrier hull, demilitarization pending",
        "acquisition_cost_cents": TEST_DEFAULTS["ROLLER_COST_CENTS"],
        "acquisition_date": TEST_DEFAULTS["ROLLER_ACQUISITION_DATE"],
        "is_restricted": True,
        "demil_code": "C",
    }
    payload.update(overrides)
    return payload


def create_condition_assessment_payload(expected_asset_version: int, **overrides) -> dict:
    payload = {
        "condition_code": "C4",
        "functional": True,
        "repair_cost_estimate_cents": 185000,
        "assessed_on": "2026-07-28",
        "expected_asset_version": expected_asset_version,
    }
    payload.update(overrides)
    return payload


def create_clearance_certificate_payload(**overrides) -> dict:
    payload = {
        "cert_type": "DATA_SANITIZATION",
        "method": "NIST_PURGE",
        "serials_verified": True,
        "certified_on": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def create_screening_cycle_payload(asset_id: str, **overrides) -> dict:
    payload = {
        "asset_id": asset_id,
        "opens_at": "2026-08-01T00:00:00Z",
        "tier_window_days": 5,
    }
    payload.update(overrides)
    return payload


def create_screening_request_payload(
    screening_cycle_id: str, requesting_agency_id: str, **overrides
) -> dict:
    payload = {
        "screening_cycle_id": screening_cycle_id,
        "requesting_agency_id": requesting_agency_id,
        "intended_use": "Municipal public works fleet replacement",
        "justification": (
            "The city is short one three-quarter ton truck for brush collection."
        ),
        "needed_by_date": "2026-09-15",
    }
    payload.update(overrides)
    return payload


def create_transfer_order_payload(
    asset_id: str, recipient_agency_id: str, screening_request_id: str, **overrides
) -> dict:
    payload = {
        "asset_id": asset_id,
        "recipient_agency_id": recipient_agency_id,
        "screening_request_id": screening_request_id,
    }
    payload.update(overrides)
    return payload


def create_auction_lot_payload(asset_id: str, venue_id: str, **overrides) -> dict:
    """reserve_price_cents is optional; omitting it makes the server compute the
    reserve from fair market value."""
    payload = {
        "asset_id": asset_id,
        "venue_id": venue_id,
        "opens_at": "2026-09-01T00:00:00Z",
        "closes_at": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_bid_payload(bidder_id: str, amount_cents: int, **overrides) -> dict:
    payload = {"bidder_id": bidder_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    """use_deposit is optional and is only sent when a test overrides it."""
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_proceeds_distribution_payload(
    auction_lot_id: str, expected_auction_lot_version: int, basis: str = "ACCRUAL",
    **overrides,
) -> dict:
    payload = {
        "auction_lot_id": auction_lot_id,
        "basis": basis,
        "expected_auction_lot_version": expected_auction_lot_version,
    }
    payload.update(overrides)
    return payload
