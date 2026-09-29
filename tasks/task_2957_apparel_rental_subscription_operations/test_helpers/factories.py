"""Request-payload builders.

Every money value these builders emit is a JSON integer of cents, every
calendar day is a ``YYYY-MM-DD`` string and every instant is a full ISO 8601
UTC timestamp.  Optional fields are omitted from the payload entirely when the
caller leaves them unset, so a default-application test really does exercise
the server's defaults rather than restating them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from test_helpers import constants as K

Body = Dict[str, Any]


def _prune(body: Body) -> Body:
    return {key: value for key, value in body.items() if value is not None}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str) -> Body:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Membership plans
# ---------------------------------------------------------------------------


def membership_plan_payload(
    code: str,
    name: str,
    item_slots: int,
    monthly_fee_cents: int,
    monthly_swaps_allowed: int,
    shipping_cadence_days: int,
    waiver_monthly_fee_cents: int,
    waiver_coverage_cents: int,
) -> Body:
    return {
        "code": code,
        "name": name,
        "item_slots": item_slots,
        "monthly_fee_cents": monthly_fee_cents,
        "monthly_swaps_allowed": monthly_swaps_allowed,
        "shipping_cadence_days": shipping_cadence_days,
        "waiver_monthly_fee_cents": waiver_monthly_fee_cents,
        "waiver_coverage_cents": waiver_coverage_cents,
    }


def sig4_plan_payload(**overrides: Any) -> Body:
    """The three-slot signature tier: 10,000 cents a month over 3 item slots."""
    body = membership_plan_payload(
        code=K.PLAN_SIG4_CODE,
        name=K.PLAN_SIG4_NAME,
        item_slots=K.PLAN_SIG4_ITEM_SLOTS,
        monthly_fee_cents=K.PLAN_SIG4_MONTHLY_FEE_CENTS,
        monthly_swaps_allowed=K.PLAN_SIG4_SWAPS_ALLOWED,
        shipping_cadence_days=K.PLAN_SIG4_CADENCE_DAYS,
        waiver_monthly_fee_cents=K.PLAN_SIG4_WAIVER_FEE_CENTS,
        waiver_coverage_cents=K.PLAN_SIG4_WAIVER_COVERAGE_CENTS,
    )
    body.update(overrides)
    return body


def solo1_plan_payload(**overrides: Any) -> Body:
    """A single-slot tier, used where the slot ceiling has to bite at one garment."""
    body = membership_plan_payload(
        code=K.PLAN_SOLO1_CODE,
        name=K.PLAN_SOLO1_NAME,
        item_slots=K.PLAN_SOLO1_ITEM_SLOTS,
        monthly_fee_cents=K.PLAN_SOLO1_MONTHLY_FEE_CENTS,
        monthly_swaps_allowed=K.PLAN_SOLO1_SWAPS_ALLOWED,
        shipping_cadence_days=K.PLAN_SOLO1_CADENCE_DAYS,
        waiver_monthly_fee_cents=K.PLAN_SOLO1_WAIVER_FEE_CENTS,
        waiver_coverage_cents=K.PLAN_SOLO1_WAIVER_COVERAGE_CENTS,
    )
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------


def technician_payload(
    employee_code: str,
    full_name: str,
    repair_certified: Optional[bool] = None,
    photography_certified: Optional[bool] = None,
    status: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "employee_code": employee_code,
            "full_name": full_name,
            "repair_certified": repair_certified,
            "photography_certified": photography_certified,
            "status": status,
        }
    )


def inspector_technician_payload(**overrides: Any) -> Body:
    """The technician who files inspections; certified for both kinds of sign-off."""
    body = technician_payload(
        K.TECH_INSPECTOR_CODE,
        K.TECH_INSPECTOR_NAME,
        repair_certified=True,
        photography_certified=True,
    )
    body.update(overrides)
    return body


def repairer_technician_payload(**overrides: Any) -> Body:
    """A second certified technician, so duty segregation has somebody to hand to."""
    body = technician_payload(
        K.TECH_REPAIRER_CODE,
        K.TECH_REPAIRER_NAME,
        repair_certified=True,
        photography_certified=True,
    )
    body.update(overrides)
    return body


def uncertified_technician_payload(**overrides: Any) -> Body:
    """A technician with both certification flags left to their defaults."""
    body = technician_payload(K.TECH_UNCERTIFIED_CODE, K.TECH_UNCERTIFIED_NAME)
    body.update(overrides)
    return body


def technician_patch_payload(
    repair_certified: Optional[bool] = None,
    photography_certified: Optional[bool] = None,
    status: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "repair_certified": repair_certified,
            "photography_certified": photography_certified,
            "status": status,
        }
    )


# ---------------------------------------------------------------------------
# Styles and depth plans
# ---------------------------------------------------------------------------


def style_payload(
    style_code: str,
    brand: str,
    category: str,
    retail_price_cents: int,
    acquisition_cost_cents: int,
    size_run: Sequence[str],
    expected_rental_turns_per_unit: int,
    planned_eol_value_cents: Optional[int] = None,
    forecast_monthly_requests: Optional[int] = None,
    avg_rental_days: Optional[int] = None,
    planned_depth_units: Optional[int] = None,
) -> Body:
    return _prune(
        {
            "style_code": style_code,
            "brand": brand,
            "category": category,
            "retail_price_cents": retail_price_cents,
            "acquisition_cost_cents": acquisition_cost_cents,
            "size_run": list(size_run),
            "expected_rental_turns_per_unit": expected_rental_turns_per_unit,
            "planned_eol_value_cents": planned_eol_value_cents,
            "forecast_monthly_requests": forecast_monthly_requests,
            "avg_rental_days": avg_rental_days,
            "planned_depth_units": planned_depth_units,
        }
    )


def gown_style_payload(**overrides: Any) -> Body:
    """A 48,000-cent gown with a three-size run: the suite's default style."""
    body = style_payload(
        style_code=K.STYLE_GOWN_CODE,
        brand=K.STYLE_GOWN_BRAND,
        category=K.CATEGORY_GOWN,
        retail_price_cents=K.STYLE_GOWN_RETAIL_CENTS,
        acquisition_cost_cents=K.STYLE_GOWN_ACQUISITION_CENTS,
        size_run=K.STYLE_GOWN_SIZE_RUN,
        expected_rental_turns_per_unit=K.STYLE_GOWN_TURNS_PER_UNIT,
        planned_eol_value_cents=K.STYLE_GOWN_EOL_VALUE_CENTS,
        forecast_monthly_requests=K.STYLE_GOWN_FORECAST_MONTHLY,
        avg_rental_days=K.STYLE_GOWN_AVG_RENTAL_DAYS,
        planned_depth_units=K.STYLE_GOWN_PLANNED_DEPTH,
    )
    body.update(overrides)
    return body


def dress_style_payload(**overrides: Any) -> Body:
    body = style_payload(
        style_code=K.STYLE_DRESS_CODE,
        brand=K.STYLE_DRESS_BRAND,
        category=K.CATEGORY_DRESS,
        retail_price_cents=K.STYLE_DRESS_RETAIL_CENTS,
        acquisition_cost_cents=K.STYLE_DRESS_ACQUISITION_CENTS,
        size_run=K.STYLE_DRESS_SIZE_RUN,
        expected_rental_turns_per_unit=K.STYLE_DRESS_TURNS_PER_UNIT,
        planned_eol_value_cents=K.STYLE_DRESS_EOL_VALUE_CENTS,
        forecast_monthly_requests=K.STYLE_DRESS_FORECAST_MONTHLY,
        avg_rental_days=K.STYLE_DRESS_AVG_RENTAL_DAYS,
        planned_depth_units=K.STYLE_DRESS_PLANNED_DEPTH,
    )
    body.update(overrides)
    return body


def knit_style_payload(**overrides: Any) -> Body:
    body = style_payload(
        style_code=K.STYLE_KNIT_CODE,
        brand=K.STYLE_KNIT_BRAND,
        category=K.CATEGORY_KNITWEAR,
        retail_price_cents=K.STYLE_KNIT_RETAIL_CENTS,
        acquisition_cost_cents=K.STYLE_KNIT_ACQUISITION_CENTS,
        size_run=K.STYLE_KNIT_SIZE_RUN,
        expected_rental_turns_per_unit=K.STYLE_KNIT_TURNS_PER_UNIT,
        planned_eol_value_cents=K.STYLE_KNIT_EOL_VALUE_CENTS,
        forecast_monthly_requests=K.STYLE_KNIT_FORECAST_MONTHLY,
        avg_rental_days=K.STYLE_KNIT_AVG_RENTAL_DAYS,
        planned_depth_units=K.STYLE_KNIT_PLANNED_DEPTH,
    )
    body.update(overrides)
    return body


def cape_style_payload(**overrides: Any) -> Body:
    """A style planned for exactly one turn per unit, so the turns ceiling is reachable."""
    body = style_payload(
        style_code=K.STYLE_CAPE_CODE,
        brand=K.STYLE_CAPE_BRAND,
        category=K.CATEGORY_BLAZER,
        retail_price_cents=K.STYLE_CAPE_RETAIL_CENTS,
        acquisition_cost_cents=K.STYLE_CAPE_ACQUISITION_CENTS,
        size_run=K.STYLE_CAPE_SIZE_RUN,
        expected_rental_turns_per_unit=K.STYLE_CAPE_TURNS_PER_UNIT,
        planned_eol_value_cents=K.STYLE_CAPE_EOL_VALUE_CENTS,
        forecast_monthly_requests=K.STYLE_CAPE_FORECAST_MONTHLY,
        avg_rental_days=K.STYLE_CAPE_AVG_RENTAL_DAYS,
        planned_depth_units=K.STYLE_CAPE_PLANNED_DEPTH,
    )
    body.update(overrides)
    return body


def depth_plan_payload(
    forecast_monthly_requests: Optional[int] = None,
    avg_rental_days: Optional[int] = None,
    planned_depth_units: Optional[int] = None,
) -> Body:
    return _prune(
        {
            "forecast_monthly_requests": forecast_monthly_requests,
            "avg_rental_days": avg_rental_days,
            "planned_depth_units": planned_depth_units,
        }
    )


# ---------------------------------------------------------------------------
# Rental units
# ---------------------------------------------------------------------------


def rental_unit_payload(
    unit_code: str,
    size: str,
    acquisition_cost_cents: Optional[int] = None,
    condition_grade: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "unit_code": unit_code,
            "size": size,
            "acquisition_cost_cents": acquisition_cost_cents,
            "condition_grade": condition_grade,
        }
    )


def retirement_payload(retirement_reason: str) -> Body:
    return {"retirement_reason": retirement_reason}


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def member_payload(
    membership_plan_id: str,
    full_name: str,
    email: str,
    waiver_active: Optional[bool] = None,
    preferred_categories: Optional[Sequence[str]] = None,
    size_profile: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "membership_plan_id": membership_plan_id,
            "full_name": full_name,
            "email": email,
            "waiver_active": waiver_active,
            "preferred_categories": (
                list(preferred_categories) if preferred_categories is not None else None
            ),
            "size_profile": size_profile,
        }
    )


def style_preferences_payload(
    preferred_categories: Optional[Sequence[str]] = None,
    size_profile: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "preferred_categories": (
                list(preferred_categories) if preferred_categories is not None else None
            ),
            "size_profile": size_profile,
        }
    )


def settlement_payload(amount_cents: int, memo: Optional[str] = None) -> Body:
    return _prune({"amount_cents": amount_cents, "memo": memo})


# ---------------------------------------------------------------------------
# Reservations and swaps
# ---------------------------------------------------------------------------


def reservation_payload(
    style_id: str,
    requested_size: str,
    requested_start_date: str,
    requested_end_date: str,
    preferred_unit_id: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "style_id": style_id,
            "requested_size": requested_size,
            "requested_start_date": requested_start_date,
            "requested_end_date": requested_end_date,
            "preferred_unit_id": preferred_unit_id,
        }
    )


def swap_payload(
    expected_member_version: int,
    style_id: str,
    requested_size: str,
    requested_start_date: str,
    requested_end_date: str,
    preferred_unit_id: Optional[str] = None,
) -> Body:
    body = reservation_payload(
        style_id,
        requested_size,
        requested_start_date,
        requested_end_date,
        preferred_unit_id,
    )
    body["expected_member_version"] = expected_member_version
    return body


def fit_feedback_payload(
    fit_rating: str,
    occasion_match_score: int,
    keep_intent: Optional[bool] = None,
    comment: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "fit_rating": fit_rating,
            "occasion_match_score": occasion_match_score,
            "keep_intent": keep_intent,
            "comment": comment,
        }
    )


# ---------------------------------------------------------------------------
# Shipment legs
# ---------------------------------------------------------------------------


def shipment_payload(
    reservation_id: str,
    direction: str,
    planned_ship_date: str,
    carrier_reference: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "reservation_id": reservation_id,
            "direction": direction,
            "planned_ship_date": planned_ship_date,
            "carrier_reference": carrier_reference,
        }
    )


def outbound_shipment_payload(
    reservation_id: str,
    planned_ship_date: str,
    carrier_reference: Optional[str] = None,
) -> Body:
    return shipment_payload(
        reservation_id, K.DIRECTION_OUTBOUND, planned_ship_date, carrier_reference
    )


def inbound_shipment_payload(
    reservation_id: str,
    planned_ship_date: str,
    carrier_reference: Optional[str] = None,
) -> Body:
    return shipment_payload(
        reservation_id, K.DIRECTION_INBOUND, planned_ship_date, carrier_reference
    )


def dispatch_payload(carrier_reference: Optional[str] = None) -> Body:
    return _prune({"carrier_reference": carrier_reference})


def shipment_exception_payload(exception_reason: str) -> Body:
    return {"exception_reason": exception_reason}


def return_initiation_payload(
    planned_ship_date: Optional[str] = None,
    carrier_reference: Optional[str] = None,
) -> Body:
    return _prune(
        {"planned_ship_date": planned_ship_date, "carrier_reference": carrier_reference}
    )


# ---------------------------------------------------------------------------
# Reverse logistics
# ---------------------------------------------------------------------------


def inspection_payload(
    soil_level: str,
    damage_severity: str,
    condition_grade_after: str,
    biohazard_flag: Optional[bool] = None,
    notes: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "soil_level": soil_level,
            "damage_severity": damage_severity,
            "condition_grade_after": condition_grade_after,
            "biohazard_flag": biohazard_flag,
            "notes": notes,
        }
    )


def clean_inspection_payload(**overrides: Any) -> Body:
    """A pristine garment: nothing soiled, nothing damaged, still grade A."""
    body = inspection_payload(K.SOIL_NONE, K.DAMAGE_NONE, K.GRADE_A)
    body.update(overrides)
    return body


def repair_completion_payload(outcome: str) -> Body:
    return {"outcome": outcome}


# ---------------------------------------------------------------------------
# Damage claims
# ---------------------------------------------------------------------------


def dispute_payload(dispute_reason: str) -> Body:
    return {"dispute_reason": dispute_reason}


def dispute_resolution_payload(resolution: str) -> Body:
    return {"resolution": resolution}


# ---------------------------------------------------------------------------
# Resale listings
# ---------------------------------------------------------------------------


def resale_listing_payload(
    rental_unit_id: str,
    expected_rental_unit_version: int,
    channel: str,
    supersedes_listing_id: Optional[str] = None,
) -> Body:
    return _prune(
        {
            "rental_unit_id": rental_unit_id,
            "expected_rental_unit_version": expected_rental_unit_version,
            "channel": channel,
            "supersedes_listing_id": supersedes_listing_id,
        }
    )


def sale_payload(sale_price_cents: int) -> Body:
    return {"sale_price_cents": sale_price_cents}
