"""Request-payload builders.

Each builder produces a valid body for one endpoint, with the required fields as
parameters and the optional fields omitted unless asked for, so that a test that
wants a default can simply leave the field out and a test that wants an explicit
value can pass it.

Two conventions matter for correctness. Every cent amount is an integer count of
cents and every proportion is an integer count of basis points, never a decimal
or a string. And an optional field is omitted from the body entirely when it is
not requested, rather than being sent as null, because omitting a field and
sending null are different requests.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import SERVER_START_CLOCK_CANONICAL

_SEQUENCE = itertools.count(1)


def _next() -> int:
    """A per-process counter for building unique codes inside one test."""
    return next(_SEQUENCE)


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the keys whose value is the omission sentinel."""
    return {key: value for key, value in payload.items() if value is not _OMIT}


class _Omit:
    """Sentinel meaning 'leave this optional field out of the body'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<omit>"


_OMIT = _Omit()
OMIT: Any = _OMIT


# ── Unique code helpers ────────────────────────────────────────────────────


def unique_property_code(prefix: str = "PROP") -> str:
    """A property code: 3 to 16 characters of uppercase letters, digits, hyphens."""
    return f"{prefix}-{_next():04d}"


def unique_room_type_code(prefix: str = "RT") -> str:
    """A room-type code: 2 to 12 uppercase alphanumeric characters."""
    return f"{prefix}{_next():04d}"


def unique_channel_code(prefix: str = "CH") -> str:
    """A channel code: 2 to 16 characters of uppercase letters, digits, hyphens."""
    return f"{prefix}-{_next():04d}"


def unique_rate_plan_code(prefix: str = "RP") -> str:
    """A plan code: 2 to 16 characters of uppercase letters, digits, hyphens."""
    return f"{prefix}-{_next():04d}"


def unique_promotion_code(prefix: str = "PM") -> str:
    """A promotion code: 2 to 16 characters of uppercase letters, digits, hyphens."""
    return f"{prefix}-{_next():04d}"


def unique_external_rate_code(prefix: str = "EXT") -> str:
    """A partner rate code: 2 to 24 of uppercase letters, digits, underscore, hyphen."""
    return f"{prefix}_{_next():04d}"


def content_hash(seed: str = "hash") -> str:
    """A content fingerprint: 4 to 64 characters of lowercase letters and digits."""
    return f"{seed.lower()}{_next():04d}"


def endpoint_url(code: str) -> str:
    """A partner endpoint: 8 to 200 characters beginning ``https://``."""
    return f"https://{code.lower().replace('-', '')}.example.com/ari"


# ── Clock ──────────────────────────────────────────────────────────────────


def clock_payload(current_utc: str = SERVER_START_CLOCK_CANONICAL) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ── Property, room type, inventory day ─────────────────────────────────────


def property_payload(
    code: Optional[str] = None,
    name: str = "Test Property",
    currency_code: Any = _OMIT,
    overbooking_pct_bp: Any = _OMIT,
    booking_horizon_days: Any = _OMIT,
    mix_window_days: Any = _OMIT,
    rate_mismatch_tolerance_cents: Any = _OMIT,
    required_image_count: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "code": code if code is not None else unique_property_code(),
            "name": name,
            "currency_code": currency_code,
            "overbooking_pct_bp": overbooking_pct_bp,
            "booking_horizon_days": booking_horizon_days,
            "mix_window_days": mix_window_days,
            "rate_mismatch_tolerance_cents": rate_mismatch_tolerance_cents,
            "required_image_count": required_image_count,
        }
    )


def room_type_payload(
    code: Optional[str] = None,
    name: str = "Test Room Type",
    physical_capacity_units: int = 10,
    master_description_hash: str = "kingv1",
    master_image_count: int = 5,
    overbooking_pct_bp: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "code": code if code is not None else unique_room_type_code(),
            "name": name,
            "physical_capacity_units": physical_capacity_units,
            "master_description_hash": master_description_hash,
            "master_image_count": master_image_count,
            "overbooking_pct_bp": overbooking_pct_bp,
        }
    )


def room_type_patch_payload(
    name: Any = _OMIT,
    physical_capacity_units: Any = _OMIT,
    master_description_hash: Any = _OMIT,
    master_image_count: Any = _OMIT,
    overbooking_pct_bp: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "name": name,
            "physical_capacity_units": physical_capacity_units,
            "master_description_hash": master_description_hash,
            "master_image_count": master_image_count,
            "overbooking_pct_bp": overbooking_pct_bp,
        }
    )


def inventory_day_payload(stay_date: str) -> Dict[str, Any]:
    return {"stay_date": stay_date}


# ── Channel and connectivity ───────────────────────────────────────────────


def channel_payload(
    code: Optional[str] = None,
    channel_kind: str = "OTA_PUBLIC",
    commission_bp: int = 1750,
    sell_adjustment_bp: Any = _OMIT,
    allows_member_rate: Any = _OMIT,
    allows_opaque_rate: Any = _OMIT,
    geo_market_codes: Any = _OMIT,
    requires_content_parity: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "code": code if code is not None else unique_channel_code(),
            "channel_kind": channel_kind,
            "commission_bp": commission_bp,
            "sell_adjustment_bp": sell_adjustment_bp,
            "allows_member_rate": allows_member_rate,
            "allows_opaque_rate": allows_opaque_rate,
            "geo_market_codes": geo_market_codes,
            "requires_content_parity": requires_content_parity,
        }
    )


def connection_payload(
    protocol: str = "JSON_PUSH",
    url: Optional[str] = None,
    heartbeat_interval_minutes: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "protocol": protocol,
            "endpoint_url": url if url is not None else endpoint_url("partner"),
            "heartbeat_interval_minutes": heartbeat_interval_minutes,
        }
    )


def heartbeat_payload(status: str = "OK", failure_code: Any = _OMIT) -> Dict[str, Any]:
    return _compact({"status": status, "failure_code": failure_code})


def freeze_window_payload(
    starts_at: str, ends_at: str, reason: Any = _OMIT
) -> Dict[str, Any]:
    return _compact({"starts_at": starts_at, "ends_at": ends_at, "reason": reason})


# ── Rate plans ─────────────────────────────────────────────────────────────


def rate_plan_payload(
    code: Optional[str] = None,
    rate_class: str = "PUBLIC",
    floor_amount_cents: int = 18000,
    ceiling_amount_cents: int = 40000,
    base_amount_cents: Any = 25000,
    parent_rate_plan_id: Any = _OMIT,
    offset_kind: Any = _OMIT,
    offset_bp: Any = _OMIT,
    offset_amount_cents: Any = _OMIT,
    package_inclusion_cents: Any = _OMIT,
    member_only: Any = _OMIT,
    negotiated_account_code: Any = _OMIT,
) -> Dict[str, Any]:
    """A root plan by default: it carries its own base amount and no parent."""
    return _compact(
        {
            "code": code if code is not None else unique_rate_plan_code(),
            "rate_class": rate_class,
            "floor_amount_cents": floor_amount_cents,
            "ceiling_amount_cents": ceiling_amount_cents,
            "base_amount_cents": base_amount_cents,
            "parent_rate_plan_id": parent_rate_plan_id,
            "offset_kind": offset_kind,
            "offset_bp": offset_bp,
            "offset_amount_cents": offset_amount_cents,
            "package_inclusion_cents": package_inclusion_cents,
            "member_only": member_only,
            "negotiated_account_code": negotiated_account_code,
        }
    )


def derived_rate_plan_payload(
    parent_rate_plan_id: str,
    code: Optional[str] = None,
    offset_kind: str = "PERCENT",
    offset_bp: Any = _OMIT,
    offset_amount_cents: Any = _OMIT,
    rate_class: str = "PUBLIC",
    floor_amount_cents: int = 18000,
    ceiling_amount_cents: int = 40000,
    package_inclusion_cents: Any = _OMIT,
    member_only: Any = _OMIT,
    negotiated_account_code: Any = _OMIT,
) -> Dict[str, Any]:
    """A derived plan: it names a parent and never carries its own base amount."""
    return _compact(
        {
            "code": code if code is not None else unique_rate_plan_code(),
            "rate_class": rate_class,
            "floor_amount_cents": floor_amount_cents,
            "ceiling_amount_cents": ceiling_amount_cents,
            "parent_rate_plan_id": parent_rate_plan_id,
            "offset_kind": offset_kind,
            "offset_bp": offset_bp,
            "offset_amount_cents": offset_amount_cents,
            "package_inclusion_cents": package_inclusion_cents,
            "member_only": member_only,
            "negotiated_account_code": negotiated_account_code,
        }
    )


def reprice_payload(
    expected_rate_plan_version: int,
    base_amount_cents: Any = _OMIT,
    offset_bp: Any = _OMIT,
    offset_amount_cents: Any = _OMIT,
    floor_amount_cents: Any = _OMIT,
    ceiling_amount_cents: Any = _OMIT,
    package_inclusion_cents: Any = _OMIT,
) -> Dict[str, Any]:
    """A repricing body: the concurrency echo is required, everything else optional."""
    return _compact(
        {
            "expected_rate_plan_version": expected_rate_plan_version,
            "base_amount_cents": base_amount_cents,
            "offset_bp": offset_bp,
            "offset_amount_cents": offset_amount_cents,
            "floor_amount_cents": floor_amount_cents,
            "ceiling_amount_cents": ceiling_amount_cents,
            "package_inclusion_cents": package_inclusion_cents,
        }
    )


# ── Channel mappings ───────────────────────────────────────────────────────


def mapping_payload(
    rate_plan_id: str,
    channel_id: str,
    room_type_id: str,
    external_rate_code: Optional[str] = None,
    content_description_hash: Any = _OMIT,
    content_image_count: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "rate_plan_id": rate_plan_id,
            "channel_id": channel_id,
            "room_type_id": room_type_id,
            "external_rate_code": (
                external_rate_code
                if external_rate_code is not None
                else unique_external_rate_code()
            ),
            "content_description_hash": content_description_hash,
            "content_image_count": content_image_count,
        }
    )


def mapping_content_payload(
    content_description_hash: Any = _OMIT, content_image_count: Any = _OMIT
) -> Dict[str, Any]:
    return _compact(
        {
            "content_description_hash": content_description_hash,
            "content_image_count": content_image_count,
        }
    )


def observed_rate_payload(observed_rate_cents: int, observed_stay_date: str) -> Dict[str, Any]:
    """Both surveillance inputs are required."""
    return {
        "observed_rate_cents": observed_rate_cents,
        "observed_stay_date": observed_stay_date,
    }


# ── Promotions ─────────────────────────────────────────────────────────────


def promotion_payload(
    start_date: str,
    end_date: str,
    code: Optional[str] = None,
    promo_kind: str = "MEMBER_RATE",
    discount_kind: str = "PERCENT",
    discount_bp: Any = _OMIT,
    discount_amount_cents: Any = _OMIT,
    geo_market_codes: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "code": code if code is not None else unique_promotion_code(),
            "promo_kind": promo_kind,
            "discount_kind": discount_kind,
            "discount_bp": discount_bp,
            "discount_amount_cents": discount_amount_cents,
            "start_date": start_date,
            "end_date": end_date,
            "geo_market_codes": geo_market_codes,
        }
    )


def percent_promotion_payload(
    start_date: str,
    end_date: str,
    discount_bp: int,
    code: Optional[str] = None,
    promo_kind: str = "MEMBER_RATE",
    geo_market_codes: Any = _OMIT,
) -> Dict[str, Any]:
    return promotion_payload(
        start_date=start_date,
        end_date=end_date,
        code=code,
        promo_kind=promo_kind,
        discount_kind="PERCENT",
        discount_bp=discount_bp,
        geo_market_codes=geo_market_codes,
    )


def amount_promotion_payload(
    start_date: str,
    end_date: str,
    discount_amount_cents: int,
    code: Optional[str] = None,
    promo_kind: str = "GEO_OFFER",
    geo_market_codes: Any = _OMIT,
) -> Dict[str, Any]:
    return promotion_payload(
        start_date=start_date,
        end_date=end_date,
        code=code,
        promo_kind=promo_kind,
        discount_kind="AMOUNT",
        discount_amount_cents=discount_amount_cents,
        geo_market_codes=geo_market_codes,
    )


def reject_payload(reason: Any = _OMIT) -> Dict[str, Any]:
    """A rejection body; the reason is optional and is stored as null when omitted."""
    return _compact({"reason": reason})


# ── Restrictions ───────────────────────────────────────────────────────────


def restriction_payload(
    room_type_id: str,
    restriction_type: str,
    start_date: str,
    end_date: str,
    rate_plan_id: Any = _OMIT,
    value_nights: Any = _OMIT,
) -> Dict[str, Any]:
    """``origin`` is never supplied in the body; a placed restriction is MANUAL."""
    return _compact(
        {
            "room_type_id": room_type_id,
            "restriction_type": restriction_type,
            "start_date": start_date,
            "end_date": end_date,
            "rate_plan_id": rate_plan_id,
            "value_nights": value_nights,
        }
    )


def min_stay_payload(
    room_type_id: str,
    start_date: str,
    end_date: str,
    value_nights: int,
    rate_plan_id: Any = _OMIT,
) -> Dict[str, Any]:
    """A MIN_STAY restriction, the one type that requires ``value_nights``."""
    return restriction_payload(
        room_type_id=room_type_id,
        restriction_type="MIN_STAY",
        start_date=start_date,
        end_date=end_date,
        rate_plan_id=rate_plan_id,
        value_nights=value_nights,
    )


def stop_sell_payload(
    room_type_id: str, start_date: str, end_date: str, rate_plan_id: Any = _OMIT
) -> Dict[str, Any]:
    """A STOP_SELL restriction, which must not carry ``value_nights``."""
    return restriction_payload(
        room_type_id=room_type_id,
        restriction_type="STOP_SELL",
        start_date=start_date,
        end_date=end_date,
        rate_plan_id=rate_plan_id,
    )


def closed_to_arrival_payload(
    room_type_id: str, start_date: str, end_date: str, rate_plan_id: Any = _OMIT
) -> Dict[str, Any]:
    """A CLOSED_TO_ARRIVAL restriction, which must not carry ``value_nights``."""
    return restriction_payload(
        room_type_id=room_type_id,
        restriction_type="CLOSED_TO_ARRIVAL",
        start_date=start_date,
        end_date=end_date,
        rate_plan_id=rate_plan_id,
    )


# ── Allotments ─────────────────────────────────────────────────────────────


def allocation_payload(
    channel_id: str,
    allocated_units: int,
    start_date: str,
    end_date: str,
    expected_room_type_version: int,
) -> Dict[str, Any]:
    """Every field is required, including the room type's concurrency echo."""
    return {
        "channel_id": channel_id,
        "allocated_units": allocated_units,
        "start_date": start_date,
        "end_date": end_date,
        "expected_room_type_version": expected_room_type_version,
    }


# ── Reservations ───────────────────────────────────────────────────────────


def reservation_payload(
    channel_id: str,
    rate_plan_id: str,
    room_type_id: str,
    arrival_date: str,
    nights: int = 1,
    member_flag: Any = _OMIT,
    geo_market_code: Any = _OMIT,
    negotiated_account_code: Any = _OMIT,
    override_overbooking: Any = _OMIT,
) -> Dict[str, Any]:
    """``property_id`` is never supplied; it is derived from the booking channel."""
    return _compact(
        {
            "channel_id": channel_id,
            "rate_plan_id": rate_plan_id,
            "room_type_id": room_type_id,
            "arrival_date": arrival_date,
            "nights": nights,
            "member_flag": member_flag,
            "geo_market_code": geo_market_code,
            "negotiated_account_code": negotiated_account_code,
            "override_overbooking": override_overbooking,
        }
    )


# ── Query parameters ───────────────────────────────────────────────────────


def quoted_rate_params(
    stay_date: str,
    member_flag: Any = _OMIT,
    geo_market_code: Any = _OMIT,
    negotiated_account_code: Any = _OMIT,
) -> Dict[str, Any]:
    return _compact(
        {
            "stay_date": stay_date,
            "member_flag": member_flag,
            "geo_market_code": geo_market_code,
            "negotiated_account_code": negotiated_account_code,
        }
    )


def performance_params(
    window_start_date: str, window_end_date: str, basis: Any = _OMIT
) -> Dict[str, Any]:
    """``basis`` is optional and defaults to the stay basis when omitted."""
    return _compact(
        {
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
            "basis": basis,
        }
    )


def pace_params(target_stay_date: str, baseline: Any = _OMIT) -> Dict[str, Any]:
    """``baseline`` is optional and defaults to the rolling baseline when omitted."""
    return _compact({"target_stay_date": target_stay_date, "baseline": baseline})


def mix_params(window_start_date: str, window_end_date: str) -> Dict[str, Any]:
    return {"window_start_date": window_start_date, "window_end_date": window_end_date}


def page_params(limit: Any = _OMIT, offset: Any = _OMIT, **filters: Any) -> Dict[str, Any]:
    """Pagination controls plus any list filters, omitting whatever was not asked for."""
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    params.update(filters)
    return _compact(params)
