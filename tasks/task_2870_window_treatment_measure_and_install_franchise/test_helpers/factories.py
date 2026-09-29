"""Request-body builders for every write endpoint.

Type fidelity matters here and follows the PRD field by field:

* monetary amounts are JSON **integers** of cents, never strings and never dollars;
* inch readings are JSON numbers with at most three decimal places;
* `requested_at`, `scheduled_start_at`, `scheduled_end_at`, `hold_start_at`,
  `hold_end_at` and `current_utc` are all **instants**, so a full ISO 8601 UTC
  instant is sent rather than a date-only value;
* `royalty_rate_pct` is a decimal fraction carrying at most four decimal places.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional, Sequence

from .constants import (
    BILLABLE_FLOOR_IN,
    DISCOUNT_TIERS,
    FABRIC_RATE_CENTS_PER_SQFT,
    INSTALL_FEE_BASE_CENTS,
    INSTALL_FEE_PER_MOTORIZED_CENTS,
    INSTALL_FEE_PER_OPENING_CENTS,
    LIFT_UPLIFT_CENTS,
    MOTOR_PRICE_CENTS,
    OVERSIZE_SURCHARGE_RATE,
    OVERSIZE_WIDTH_THRESHOLD_IN,
    SQFT_DIVISOR,
)
from .types import Json


def _with_optional(payload: Json, **optional: Any) -> Json:
    """Attach only the optional fields the caller actually supplied."""
    for key, value in optional.items():
        if value is not None:
            payload[key] = value
    return payload


# ─── Territory ────────────────────────────────────────────────────────────────


def territory_payload(legal_name: str = "Northgate Blinds LLC",
                      postal_codes: Optional[Sequence[str]] = None,
                      royalty_rate_pct: Optional[float] = None,
                      lead_capacity_per_week: Optional[int] = None,
                      credit_limit_cents: Optional[int] = None,
                      liability_window: Optional[str] = None) -> Json:
    """A territory charter. Four commercial terms are optional and each defaults."""
    payload: Json = {
        "legal_name": legal_name,
        "postal_codes": list(postal_codes if postal_codes is not None else ["30301"]),
    }
    return _with_optional(payload,
                          royalty_rate_pct=royalty_rate_pct,
                          lead_capacity_per_week=lead_capacity_per_week,
                          credit_limit_cents=credit_limit_cents,
                          liability_window=liability_window)


def territory_patch(status: Optional[str] = None,
                    royalty_rate_pct: Optional[float] = None,
                    lead_capacity_per_week: Optional[int] = None,
                    credit_limit_cents: Optional[int] = None,
                    liability_window: Optional[str] = None) -> Json:
    """A re-statement of a territory's standing or terms — any subset of five fields."""
    return _with_optional({}, status=status,
                          royalty_rate_pct=royalty_rate_pct,
                          lead_capacity_per_week=lead_capacity_per_week,
                          credit_limit_cents=credit_limit_cents,
                          liability_window=liability_window)


# ─── Designer ─────────────────────────────────────────────────────────────────


def designer_payload(territory_id: str, full_name: str = "Dana Reed",
                     home_postal_code: str = "30301",
                     certifications: Optional[Sequence[str]] = None) -> Json:
    """Hire a designer into a territory."""
    payload: Json = {
        "territory_id": territory_id,
        "full_name": full_name,
        "home_postal_code": home_postal_code,
    }
    if certifications is not None:
        payload["certifications"] = list(certifications)
    return payload


def designer_patch(status: Optional[str] = None,
                   certifications: Optional[Sequence[str]] = None) -> Json:
    """Reinstate, retire or re-certify a designer."""
    payload: Json = {}
    if status is not None:
        payload["status"] = status
    if certifications is not None:
        payload["certifications"] = list(certifications)
    return payload


# ─── Sample library ───────────────────────────────────────────────────────────


def sample_kit_payload(territory_id: str, kit_code: str = "KIT-001",
                       replacement_value_cents: int = 50000) -> Json:
    """Add a fabric sample kit. `replacement_value_cents` is an integer of cents."""
    return {
        "territory_id": territory_id,
        "kit_code": kit_code,
        "replacement_value_cents": int(replacement_value_cents),
    }


def sample_checkout_payload(sample_kit_id: str, consultation_id: str,
                            hold_start_at: str, hold_end_at: str) -> Json:
    """Check a kit out on a closed hold interval of two full instants."""
    return {
        "sample_kit_id": sample_kit_id,
        "consultation_id": consultation_id,
        "hold_start_at": hold_start_at,
        "hold_end_at": hold_end_at,
    }


# ─── Lead ─────────────────────────────────────────────────────────────────────


def lead_payload(customer_name: str = "Ana Ruiz", postal_code: str = "30301",
                 source: str = "WEB_FORM",
                 requested_at: str = "2026-08-01T08:00:00.000Z",
                 child_occupied_dwelling: Optional[bool] = None) -> Json:
    """Intake a homeowner inquiry. `requested_at` is an instant, not a date."""
    payload: Json = {
        "customer_name": customer_name,
        "postal_code": postal_code,
        "source": source,
        "requested_at": requested_at,
    }
    if child_occupied_dwelling is not None:
        payload["child_occupied_dwelling"] = bool(child_occupied_dwelling)
    return payload


# ─── Consultation ─────────────────────────────────────────────────────────────


def consultation_payload(lead_id: str, designer_id: str,
                         scheduled_start_at: str = "2026-08-03T14:00:00.000Z",
                         scheduled_end_at: str = "2026-08-03T15:00:00.000Z",
                         service_postal_code: str = "30301") -> Json:
    """Book an in-home consultation on a designer's calendar."""
    return {
        "lead_id": lead_id,
        "designer_id": designer_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "service_postal_code": service_postal_code,
    }


# ─── Opening ──────────────────────────────────────────────────────────────────


def opening_payload(consultation_id: str, label: str = "Den window",
                    room_type: str = "OFFICE", mount_type: str = "INSIDE",
                    width_top_in: float = 24.000,
                    width_middle_in: Optional[float] = None,
                    width_bottom_in: Optional[float] = None,
                    height_left_in: float = 48.000,
                    height_center_in: Optional[float] = None,
                    height_right_in: Optional[float] = None,
                    depth_in: float = 3.000,
                    replaces_opening_id: Optional[str] = None) -> Json:
    """Record one measured opening: six wall readings plus the pocket depth.

    All eight readings are JSON numbers of inches. When only `width_top_in` and
    `height_left_in` are given the remaining readings repeat them, which describes
    a perfectly square opening.
    """
    payload: Json = {
        "consultation_id": consultation_id,
        "label": label,
        "room_type": room_type,
        "mount_type": mount_type,
        "width_top_in": width_top_in,
        "width_middle_in": (width_middle_in if width_middle_in is not None
                            else width_top_in),
        "width_bottom_in": (width_bottom_in if width_bottom_in is not None
                            else width_top_in),
        "height_left_in": height_left_in,
        "height_center_in": (height_center_in if height_center_in is not None
                             else height_left_in),
        "height_right_in": (height_right_in if height_right_in is not None
                            else height_left_in),
        "depth_in": depth_in,
    }
    if replaces_opening_id is not None:
        payload["replaces_opening_id"] = replaces_opening_id
    return payload


def configuration_payload(fabric_code: str = "LT-SHEER",
                          lift_system: str = "CORDED",
                          motorization_option: Optional[str] = None) -> Json:
    """Set fabric, lift and motor package on one opening.

    `motorization_option` is optional and defaults to `NONE`.
    """
    payload: Json = {"fabric_code": fabric_code, "lift_system": lift_system}
    if motorization_option is not None:
        payload["motorization_option"] = motorization_option
    return payload


# ─── Quote ────────────────────────────────────────────────────────────────────


def quote_payload(consultation_id: str, expected_consultation_version: int) -> Json:
    """Build a quote. `expected_consultation_version` is non-optional."""
    return {
        "consultation_id": consultation_id,
        "expected_consultation_version": expected_consultation_version,
    }


# ─── Vendor ───────────────────────────────────────────────────────────────────


def vendor_payload(name: str = "Ridgeline Shade Works",
                   base_lead_time_days: int = 10,
                   remake_policy: str = "SHARED_50_50",
                   supported_lift_systems: Optional[Sequence[str]] = None,
                   motorization_extra_days: Optional[int] = None,
                   cutoff_hour_utc: Optional[int] = None,
                   concurrent_capacity: Optional[int] = None,
                   supported_hub_platforms: Optional[Sequence[str]] = None,
                   status: Optional[str] = None) -> Json:
    """Onboard a manufacturer. `supported_lift_systems` must be non-empty."""
    payload: Json = {
        "name": name,
        "base_lead_time_days": int(base_lead_time_days),
        "remake_policy": remake_policy,
        "supported_lift_systems": list(
            supported_lift_systems if supported_lift_systems is not None
            else ["CORDED"]
        ),
    }
    if motorization_extra_days is not None:
        payload["motorization_extra_days"] = int(motorization_extra_days)
    if cutoff_hour_utc is not None:
        payload["cutoff_hour_utc"] = int(cutoff_hour_utc)
    if concurrent_capacity is not None:
        payload["concurrent_capacity"] = int(concurrent_capacity)
    if supported_hub_platforms is not None:
        payload["supported_hub_platforms"] = list(supported_hub_platforms)
    if status is not None:
        payload["status"] = status
    return payload


# ─── Vendor order ─────────────────────────────────────────────────────────────


def vendor_order_payload(quote_id: str, opening_ids: Sequence[str],
                         expected_quote_version: int,
                         preferred_vendor_id: Optional[str] = None) -> Json:
    """Place a manufacturing order for a subset of an accepted quote's openings."""
    payload: Json = {
        "quote_id": quote_id,
        "opening_ids": list(opening_ids),
        "expected_quote_version": expected_quote_version,
    }
    if preferred_vendor_id is not None:
        payload["preferred_vendor_id"] = preferred_vendor_id
    return payload


def remake_payload(credit_scope: str = "REPLACEMENT") -> Json:
    """Request a remake. The body carries the single field `credit_scope`."""
    return {"credit_scope": credit_scope}


# ─── Install job ──────────────────────────────────────────────────────────────


def install_job_payload(vendor_order_id: str, designer_id: str,
                        scheduled_start_at: str = "2026-08-20T09:00:00.000Z",
                        scheduled_end_at: str = "2026-08-20T12:00:00.000Z",
                        service_postal_code: str = "30301") -> Json:
    """Schedule the installation of a received order."""
    return {
        "vendor_order_id": vendor_order_id,
        "designer_id": designer_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "service_postal_code": service_postal_code,
    }


def pair_payload(paired_channel_count: int, hub_platform: str) -> Json:
    """Report motorized channels paired to a smart-home hub."""
    return {
        "paired_channel_count": int(paired_channel_count),
        "hub_platform": hub_platform,
    }


def exception_payload(opening_id: str, exception_reason: str) -> Json:
    """Raise an install exception against one opening."""
    return {"opening_id": opening_id, "exception_reason": exception_reason}


# ─── Expected-value calculators ───────────────────────────────────────────────
# These reproduce the published arithmetic so a test can state the inputs and the
# expected integer side by side. Each mirrors the pinned rounding order exactly.


def expected_billable_sqft(ordered_width_in: float,
                           ordered_height_in: float) -> float:
    """Billable dimensions floor at 12.000 inches; area rounds up to the quarter."""
    width = max(Decimal(str(ordered_width_in)), Decimal(str(BILLABLE_FLOOR_IN)))
    height = max(Decimal(str(ordered_height_in)), Decimal(str(BILLABLE_FLOOR_IN)))
    raw = (width * height) / Decimal(SQFT_DIVISOR)
    quarters = (raw / Decimal("0.25")).to_integral_value(rounding=ROUND_CEILING)
    return float(quarters * Decimal("0.25"))


def expected_list_price_cents(billable_sqft: float, fabric_code: str,
                              lift_system: str,
                              motorization_option: str = "NONE",
                              billable_width_in: Optional[float] = None) -> int:
    """The two rounding steps in order: the fabric charge, then the surcharge."""
    fabric = (Decimal(str(billable_sqft))
              * Decimal(FABRIC_RATE_CENTS_PER_SQFT[fabric_code]))
    fabric_cents = int(fabric.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    combined = (fabric_cents + LIFT_UPLIFT_CENTS[lift_system]
                + MOTOR_PRICE_CENTS[motorization_option])
    rate = Decimal("0")
    if (billable_width_in is not None
            and Decimal(str(billable_width_in))
            > Decimal(str(OVERSIZE_WIDTH_THRESHOLD_IN))):
        rate = Decimal(str(OVERSIZE_SURCHARGE_RATE))
    surcharge = int((Decimal(combined) * rate).quantize(Decimal("1"),
                                                        rounding=ROUND_HALF_UP))
    return combined + surcharge


def expected_install_fee_cents(opening_count: int,
                               motorized_opening_count: int) -> int:
    """7500 base, plus 2500 per opening, plus 4500 per motorized opening."""
    return (INSTALL_FEE_BASE_CENTS
            + INSTALL_FEE_PER_OPENING_CENTS * opening_count
            + INSTALL_FEE_PER_MOTORIZED_CENTS * motorized_opening_count)


def expected_discount_pct(pre_discount_total_cents: int) -> float:
    """The tier is selected from the pre-discount total alone, every bound inclusive."""
    for threshold, pct in DISCOUNT_TIERS:
        if pre_discount_total_cents >= threshold:
            return pct
    return 0.0


def expected_discount_cents(subtotal_cents: int, discount_pct: float) -> int:
    """The discount base is the goods subtotal only; this is the sole rounding step."""
    return int((Decimal(subtotal_cents) * Decimal(str(discount_pct)))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_order_cost_cents(summed_list_price_cents: int) -> int:
    """42 percent of the summed retail figure, rounded half up once."""
    return int((Decimal(summed_list_price_cents) * Decimal("0.42"))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_remeasure_charge_cents(list_price_cents: int) -> int:
    """35 percent of the opening's list price, rounded half up and then capped."""
    raw = int((Decimal(list_price_cents) * Decimal("0.35"))
              .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(raw, 12000)


def quote_waterfall(list_prices: Sequence[int],
                    motorized_count: int) -> Dict[str, Any]:
    """The whole six-step waterfall, in the pinned order, from a set of list prices."""
    subtotal = sum(list_prices)
    install_fee = expected_install_fee_cents(len(list_prices), motorized_count)
    pre_discount = subtotal + install_fee
    pct = expected_discount_pct(pre_discount)
    discount = expected_discount_cents(subtotal, pct)
    return {
        "subtotal_cents": subtotal,
        "install_fee_cents": install_fee,
        "pre_discount_total_cents": pre_discount,
        "discount_pct": pct,
        "discount_cents": discount,
        "total_cents": pre_discount - discount,
        "net_sales_cents": subtotal - discount,
    }


def uniform_readings(width_in: float, height_in: float,
                     depth_in: float = 3.000) -> Dict[str, float]:
    """The eight readings of a perfectly square opening."""
    return {
        "width_top_in": width_in,
        "width_middle_in": width_in,
        "width_bottom_in": width_in,
        "height_left_in": height_in,
        "height_center_in": height_in,
        "height_right_in": height_in,
        "depth_in": depth_in,
    }
