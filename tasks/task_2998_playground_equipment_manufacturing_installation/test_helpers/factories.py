"""Payload factories — one per creatable resource, input fields only.

Conventions enforced here, because getting them wrong breaks every downstream
assertion:

* Every monetary amount is an integer count of cents (PRD 2.7).  No strings,
  no floats.
* Every geometric measure is a whole number of centimetres.
* Calendar fields (`effective_from`, `fundraising_deadline`, `valid_until`,
  `pledged_at`, `certification_expires_on`, `scheduled_start_date`,
  `scheduled_end_date`, `failure_date`) are `YYYY-MM-DD` date strings.
* The logical-clock field `current_utc` is a full ISO-8601 UTC instant, e.g.
  `2026-08-01T00:00:00Z`.
* `code` is 1..40 chars of uppercase letters, digits and underscore only.
* `region_code` is exactly two uppercase letters.
* `color_options` entries are distinct uppercase strings; index 0 is the
  no-cost default colour.

Every factory merges `overrides` into a defaults dict rather than splatting
them into a call, so a caller may override any field without a duplicate
keyword-argument error.
"""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def _merge(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(defaults)
    payload.update(overrides)
    # An explicit None for an optional reference means "send null"; a caller who
    # wants the field omitted entirely passes it through _drop() below.
    return payload


def drop_fields(payload: Dict[str, Any], *names: str) -> Dict[str, Any]:
    """Return a copy of payload with the named keys removed.

    Used by required-field tests and by callers that want a declared-optional
    input omitted rather than sent as null.
    """
    out = dict(payload)
    for name in names:
        out.pop(name, None)
    return out


# --------------------------------------------------------------------------
# PlaygroundStandard
# --------------------------------------------------------------------------
def standard_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": TEST_DEFAULTS["STANDARD_CODE"],
            "edition_year": TEST_DEFAULTS["STANDARD_EDITION_YEAR"],
            "effective_from": TEST_DEFAULTS["STANDARD_EFFECTIVE_FROM"],
            "min_use_zone_clearance_cm": TEST_DEFAULTS["MIN_USE_ZONE_CLEARANCE_CM"],
            "max_fall_height_cm_toddler": TEST_DEFAULTS["MAX_FALL_HEIGHT_CM_TODDLER"],
            "max_fall_height_cm_preschool": TEST_DEFAULTS[
                "MAX_FALL_HEIGHT_CM_PRESCHOOL"
            ],
            "max_fall_height_cm_school_age": TEST_DEFAULTS[
                "MAX_FALL_HEIGHT_CM_SCHOOL_AGE"
            ],
            "requires_accessible_route": False,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# ComponentModel
# --------------------------------------------------------------------------
def component_model_payload(**overrides: Any) -> Dict[str, Any]:
    """A TODDLER_6_23M POST, ground level, default colour CEDAR."""
    return _merge(
        {
            "sku": "POST-STD-120",
            "category": "POST",
            "age_group": "TODDLER_6_23M",
            "deck_height_cm": 0,
            "use_zone_footprint_cm": 30,
            "color_options": ["CEDAR", "FOREST_GREEN"],
            "unit_price_cents": 10750,
            "hardware_bag_count": 2,
            "warranty_years": 15,
            "parts_support_until_year": 2040,
            "accessible_transfer_ready": False,
        },
        overrides,
    )


def post_model_payload(**overrides: Any) -> Dict[str, Any]:
    return component_model_payload(**overrides)


def deck_model_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sku": "DECK-TDL-122",
            "category": "DECK",
            "age_group": "TODDLER_6_23M",
            "deck_height_cm": 122,
            "use_zone_footprint_cm": 183,
            "color_options": ["CEDAR", "SKY_BLUE"],
            "unit_price_cents": 64350,
            "hardware_bag_count": 6,
            "warranty_years": 15,
            "parts_support_until_year": 2040,
            "accessible_transfer_ready": True,
        },
        overrides,
    )


def slide_model_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sku": "SLIDE-HD-122",
            "category": "PLASTIC_SLIDE",
            "age_group": "TODDLER_6_23M",
            "deck_height_cm": 122,
            "use_zone_footprint_cm": 183,
            "color_options": ["YELLOW", "CRIMSON"],
            "unit_price_cents": 215450,
            "hardware_bag_count": 4,
            "warranty_years": 10,
            "parts_support_until_year": 2040,
            "accessible_transfer_ready": False,
        },
        overrides,
    )


def climber_model_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sku": "CLIMB-MTL-122",
            "category": "METAL_CLIMBER",
            "age_group": "TODDLER_6_23M",
            "deck_height_cm": 122,
            "use_zone_footprint_cm": 213,
            "color_options": ["GRAPHITE", "CRIMSON"],
            "unit_price_cents": 215450,
            "hardware_bag_count": 5,
            "warranty_years": 10,
            "parts_support_until_year": 2040,
            "accessible_transfer_ready": True,
        },
        overrides,
    )


def hardware_kit_model_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sku": "HDW-KIT-STD",
            "category": "HARDWARE_KIT",
            "age_group": "TODDLER_6_23M",
            "deck_height_cm": 0,
            "use_zone_footprint_cm": 15,
            "color_options": ["GALVANIZED"],
            "unit_price_cents": 4500,
            "hardware_bag_count": 1,
            "warranty_years": 10,
            "parts_support_until_year": 2040,
            "accessible_transfer_ready": False,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# DesignProject
# --------------------------------------------------------------------------
def project_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "client_name": "Maple Grove School",
            "site_length_cm": TEST_DEFAULTS["SITE_LENGTH_CM"],
            "site_width_cm": TEST_DEFAULTS["SITE_WIDTH_CM"],
            "site_soil_type": "CLAY",
            "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
            "fundraising_deadline": TEST_DEFAULTS["FUNDRAISING_DEADLINE"],
            "required_age_groups": ["TODDLER_6_23M"],
            "accessible_route_required": False,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# PlayArea
# --------------------------------------------------------------------------
def play_area_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "age_group": "TODDLER_6_23M",
            "axis_origin_cm": 0,
            "axis_length_cm": 2000,
            "surfacing_material": "ENGINEERED_WOOD_FIBER",
            "surfacing_depth_cm": 30,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# ComponentPlacement
# --------------------------------------------------------------------------
def placement_payload(
    component_model_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "color_choice": "CEDAR",
        "x_start_cm": 200,
        "quantity": 1,
    }
    if component_model_id is not None:
        defaults["component_model_id"] = component_model_id
    return _merge(defaults, overrides)


# --------------------------------------------------------------------------
# DesignRendering
# --------------------------------------------------------------------------
def rendering_payload(pinned_standard_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"pinned_standard_id": pinned_standard_id}, overrides)


def community_votes_payload(
    yes_votes: int = 20, no_votes: int = 5, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"yes_votes": yes_votes, "no_votes": no_votes}, overrides)


# --------------------------------------------------------------------------
# Quote
# --------------------------------------------------------------------------
def quote_payload(
    project_id: str,
    rendering_id: str,
    expected_project_version: int,
    variant: str = "FIRM",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "rendering_id": rendering_id,
            "variant": variant,
            "valid_until": TEST_DEFAULTS["QUOTE_VALID_UNTIL"],
            "expected_project_version": expected_project_version,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# FundraisingPledge
# --------------------------------------------------------------------------
def pledge_payload(
    amount_cents: int = 500000, pledged_at: str = "2026-08-01", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents, "pledged_at": pledged_at}, overrides)


# --------------------------------------------------------------------------
# ManufacturingOrder
# --------------------------------------------------------------------------
def order_payload(quote_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"quote_id": quote_id}, overrides)


def kitting_payload(kitting_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"kitting_status": kitting_status}, overrides)


def bagging_payload(bagging_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"bagging_status": bagging_status}, overrides)


def lifecycle_payload(lifecycle_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"lifecycle_status": lifecycle_status}, overrides)


# --------------------------------------------------------------------------
# CertifiedInstaller
# --------------------------------------------------------------------------
def installer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "company_name": "Northline Installers",
            "certification_level": "MASTER",
            "certified_categories": [
                "POST",
                "DECK",
                "PLASTIC_SLIDE",
                "METAL_CLIMBER",
                "HARDWARE_KIT",
            ],
            "crew_capacity_per_day": TEST_DEFAULTS["CREW_CAPACITY_PER_DAY"],
            "certification_expires_on": TEST_DEFAULTS["CERTIFICATION_EXPIRES_ON"],
            "region_code": "MG",
        },
        overrides,
    )


def installer_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"status": status}, overrides)


# --------------------------------------------------------------------------
# InstallationJob
# --------------------------------------------------------------------------
def job_payload(
    order_id: str,
    installer_id: str,
    scheduled_start_date: str = "2026-08-10",
    scheduled_end_date: str = "2026-08-12",
    crew_size: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "order_id": order_id,
            "installer_id": installer_id,
            "scheduled_start_date": scheduled_start_date,
            "scheduled_end_date": scheduled_end_date,
            "crew_size": crew_size,
        },
        overrides,
    )


def reschedule_payload(
    expected_installer_version: int,
    scheduled_start_date: str,
    scheduled_end_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "expected_installer_version": expected_installer_version,
            "scheduled_start_date": scheduled_start_date,
            "scheduled_end_date": scheduled_end_date,
        },
        overrides,
    )


def rework_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# --------------------------------------------------------------------------
# InstallationInspection
# --------------------------------------------------------------------------
def inspection_payload(
    kind: str = "INSTALL_INSPECTION",
    result: str = "PASS",
    deficiency_count: int = 0,
    fall_height_measured_cm: int = 122,
    surfacing_depth_measured_cm: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "kind": kind,
            "result": result,
            "deficiency_count": deficiency_count,
            "fall_height_measured_cm": fall_height_measured_cm,
            "surfacing_depth_measured_cm": surfacing_depth_measured_cm,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# WarrantyClaim
# --------------------------------------------------------------------------
def warranty_claim_payload(
    project_id: str,
    placement_id: str,
    failure_date: str,
    quantity: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "project_id": project_id,
            "placement_id": placement_id,
            "quantity": quantity,
            "failure_date": failure_date,
        },
        overrides,
    )


def claim_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# --------------------------------------------------------------------------
# Retrofit / replacement part purchase
# --------------------------------------------------------------------------
def retrofit_payload(
    replacement_model_id: str, quantity: int = 1, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"replacement_model_id": replacement_model_id, "quantity": quantity},
        overrides,
    )


# --------------------------------------------------------------------------
# Standard supersession
# --------------------------------------------------------------------------
def supersede_payload(successor_standard_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"successor_standard_id": successor_standard_id}, overrides)


ALL_COLOR_OPTIONS: List[str] = [
    "CEDAR",
    "FOREST_GREEN",
    "SKY_BLUE",
    "YELLOW",
    "CRIMSON",
    "GRAPHITE",
    "GALVANIZED",
]
