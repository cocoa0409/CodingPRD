"""Entity assertions and domain invariant checkers.

Field-level shape checks follow the PRD resource descriptions. Per PRD
Section 2.4, ModelStrain, HealthScreen, Allocation, and WelfareInspection
carry only ``id`` and ``created_at`` — the assertions for those four demand
the ABSENCE of ``updated_at`` and ``version`` as well as the presence of the
rest, because a faithful serializer must not invent them.

The compute_* helpers re-derive the PRD-pinned arithmetic (Sections 3.3, 3.4,
3.6, 3.8) so tests compare server output against an independently written
implementation of the same formulas.
"""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import (
    BARRIER_RANKS,
    SURVIVAL_RATE,
    TIER1_QTY,
    TIER1_DISCOUNT,
    TIER2_QTY,
    TIER2_DISCOUNT,
    IMMUNO_SURCHARGE,
    VF_PREMIUM,
    GERM_FREE_PREMIUM,
    LIGHT_MAX_G,
    HEAVY_MIN_G,
    LIGHT_PER_BOX,
    STANDARD_PER_BOX,
    HEAVY_PER_BOX,
    CAGE_DENSITY,
    SECONDS_PER_DAY,
    DAYS_PER_WEEK,
)


# ---------------------------------------------------------------------------
# Small shared checkers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_light_fields(data: dict, entity: str):
    """PRD Section 2.4 light resources: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def barrier_rank(level: str) -> int:
    """PRD Section 2.6 rank of a barrier level string."""
    return BARRIER_RANKS[level]


def assert_barrier_rank_at_least(level: str, minimum: str):
    assert barrier_rank(level) >= barrier_rank(minimum), (
        f"barrier level {level} must be at least {minimum}"
    )


def _assert_enum_member(value, members, field):
    assert value in members, f"{field} must be one of {sorted(members)}, got {value!r}"


_BARRIER_LEVELS = {"CONVENTIONAL", "MPF", "VF", "GERM_FREE"}


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_facility(data: dict):
    _assert_common_fields(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["registration_number"], str) and data["registration_number"]
    _assert_enum_member(
        data["registration_status"],
        {"REGISTERED", "UNDER_INSPECTION", "SUSPENDED", "REVOKED"},
        "registration_status",
    )
    assert is_iso8601_timestamp(data["registration_expires_at"])
    assert data.get("suspension_reason") is None or isinstance(data["suspension_reason"], str)


def assert_room(data: dict):
    _assert_common_fields(data, "BarrierRoom")
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert isinstance(data["room_code"], str) and data["room_code"]
    _assert_enum_member(data["barrier_level"], _BARRIER_LEVELS, "barrier_level")
    assert isinstance(data["excluded_agents"], list) and len(data["excluded_agents"]) >= 1
    assert all(isinstance(a, str) and a for a in data["excluded_agents"])
    assert isinstance(data["cage_capacity"], int) and data["cage_capacity"] >= 1
    assert isinstance(data["occupied_cages"], int) and data["occupied_cages"] >= 0
    assert data["occupied_cages"] <= data["cage_capacity"], (
        "occupied_cages must never exceed cage_capacity (PRD Section 3.4)"
    )
    _assert_enum_member(data["status"], {"ACTIVE", "QUARANTINED", "DECOMMISSIONED"}, "status")
    assert data.get("quarantined_at") is None or is_iso8601_timestamp(data["quarantined_at"])


def assert_strain(data: dict):
    _assert_light_fields(data, "ModelStrain")
    assert isinstance(data["strain_code"], str) and data["strain_code"]
    _assert_enum_member(data["species"], {"MOUSE", "RAT"}, "species")
    _assert_enum_member(
        data["immune_class"], {"IMMUNOCOMPETENT", "IMMUNOCOMPROMISED"}, "immune_class"
    )
    _assert_enum_member(data["breeding_type"], {"INBRED", "OUTBRED", "HYBRID"}, "breeding_type")
    _assert_enum_member(data["min_barrier_level"], _BARRIER_LEVELS, "min_barrier_level")
    assert isinstance(data["gestation_days"], int) and data["gestation_days"] > 0
    assert isinstance(data["wean_age_days"], int) and data["wean_age_days"] > 0
    assert isinstance(data["typical_litter_size"], int) and data["typical_litter_size"] >= 1
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0


def assert_colony(data: dict):
    _assert_common_fields(data, "Colony")
    for fk in ("room_id", "strain_id", "protocol_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert isinstance(data["breeding_pair_count"], int) and data["breeding_pair_count"] >= 1
    assert isinstance(data["generation_number"], int) and data["generation_number"] >= 0
    _assert_enum_member(
        data["lifecycle_status"],
        {"FOUNDING", "EXPANDING", "PRODUCTION", "PHASING_OUT", "RETIRED"},
        "lifecycle_status",
    )
    _assert_enum_member(
        data["genetic_status"], {"CLEAR", "PANEL_DUE", "DRIFT_DETECTED"}, "genetic_status"
    )
    assert is_iso8601_timestamp(data["last_snp_panel_at"])
    assert isinstance(data["snp_panel_interval_weeks"], int) and data["snp_panel_interval_weeks"] >= 1
    assert isinstance(data["confirmed_available_count"], int) and data["confirmed_available_count"] >= 0
    assert isinstance(data["projected_pipeline_count"], int) and data["projected_pipeline_count"] >= 0
    # PRD Section 3.2: identical inputs always yield projected >= confirmed.
    assert data["projected_pipeline_count"] >= data["confirmed_available_count"]


def assert_cohort(data: dict):
    _assert_common_fields(data, "Cohort")
    assert is_valid_uuid(data.get("colony_id", "")), "colony_id must be a UUID"
    assert is_iso8601_timestamp(data["birth_date"])
    assert isinstance(data["count_male"], int) and data["count_male"] >= 0
    assert isinstance(data["count_female"], int) and data["count_female"] >= 0
    assert isinstance(data["initial_count_total"], int) and data["initial_count_total"] >= 0
    assert isinstance(data["reserved_male"], int) and data["reserved_male"] >= 0
    assert isinstance(data["reserved_female"], int) and data["reserved_female"] >= 0
    assert data["reserved_male"] <= data["count_male"], (
        "reserved_male can never exceed count_male"
    )
    assert data["reserved_female"] <= data["count_female"], (
        "reserved_female can never exceed count_female"
    )
    assert isinstance(data["avg_weight_g_male"], (int, float)) and data["avg_weight_g_male"] > 0
    assert isinstance(data["avg_weight_g_female"], (int, float)) and data["avg_weight_g_female"] > 0
    _assert_enum_member(data["health_status"], _BARRIER_LEVELS, "health_status")
    _assert_enum_member(
        data["status"],
        {"WEANED", "HOLD", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED", "SHIPPED", "CULLED"},
        "status",
    )
    assert isinstance(data["age_weeks"], int) and data["age_weeks"] >= 0


def assert_health_screen(data: dict):
    _assert_light_fields(data, "HealthScreen")
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a UUID"
    _assert_enum_member(
        data["panel_type"],
        {"QUARTERLY_SENTINEL", "OUTBREAK_DIAGNOSTIC", "PRE_SHIPMENT"},
        "panel_type",
    )
    assert is_iso8601_timestamp(data["scheduled_at"])
    _assert_enum_member(
        data["status"],
        {"SCHEDULED", "RESULTED_NEGATIVE", "RESULTED_POSITIVE"},
        "status",
    )
    assert isinstance(data.get("results", []), list)
    for entry in data.get("results", []):
        assert isinstance(entry.get("agent"), str)
        assert isinstance(entry.get("positive"), bool)
    assert data.get("resulted_at") is None or is_iso8601_timestamp(data["resulted_at"])


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    _assert_enum_member(
        data["account_status"], {"ACTIVE", "CREDIT_HOLD", "SUSPENDED"}, "account_status"
    )
    _assert_enum_member(
        data["accepted_min_health_status"], _BARRIER_LEVELS, "accepted_min_health_status"
    )
    assert isinstance(data["is_commercial"], bool)
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0
    assert isinstance(data["credit_exposure_cents"], int) and data["credit_exposure_cents"] >= 0
    # PRD Section 3.6: identical order data yields NET_BILLED <= GROSS.
    assert data["outstanding_balance_cents"] <= data["credit_exposure_cents"]


def assert_order(data: dict):
    _assert_common_fields(data, "CustomerOrder")
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("strain_id", "")), "strain_id must be a UUID"
    assert isinstance(data["quantity_male"], int) and data["quantity_male"] >= 0
    assert isinstance(data["quantity_female"], int) and data["quantity_female"] >= 0
    assert data["quantity_male"] + data["quantity_female"] >= 1
    assert isinstance(data["min_age_weeks"], int) and data["min_age_weeks"] >= 0
    assert isinstance(data["max_age_weeks"], int) and data["max_age_weeks"] >= data["min_age_weeks"]
    assert data["min_weight_g"] > 0
    assert data["max_weight_g"] > data["min_weight_g"]
    assert is_iso8601_timestamp(data["required_delivery_date"])
    _assert_enum_member(data["min_health_status"], _BARRIER_LEVELS, "min_health_status")
    _assert_enum_member(
        data["status"],
        {"SUBMITTED", "SOURCING", "BACKORDERED", "ALLOCATED", "SCHEDULED", "SHIPPED",
         "DELIVERED", "CLOSED", "CANCELLED", "REJECTED"},
        "status",
    )
    assert data.get("quoted_total_cents") is None or (
        isinstance(data["quoted_total_cents"], int) and data["quoted_total_cents"] >= 0
    )
    assert isinstance(data["allocated_male"], int) and data["allocated_male"] >= 0
    assert isinstance(data["allocated_female"], int) and data["allocated_female"] >= 0


def assert_allocation(data: dict):
    _assert_light_fields(data, "Allocation")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("cohort_id", "")), "cohort_id must be a UUID"
    assert isinstance(data["qty_male"], int) and data["qty_male"] >= 0
    assert isinstance(data["qty_female"], int) and data["qty_female"] >= 0
    _assert_enum_member(data["status"], {"RESERVED", "RELEASED", "CONSUMED"}, "status")


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["vehicle_code"], str) and data["vehicle_code"]
    _assert_enum_member(data["vehicle_barrier_cert"], _BARRIER_LEVELS, "vehicle_barrier_cert")
    assert is_iso8601_timestamp(data["sanitized_at"])
    assert is_iso8601_timestamp(data["departure_date"])
    assert is_iso8601_timestamp(data["planned_arrival_date"])
    assert data.get("actual_arrival_at") is None or is_iso8601_timestamp(data["actual_arrival_at"])
    assert isinstance(data["box_count"], int) and data["box_count"] >= 0
    assert data.get("received_male") is None or isinstance(data["received_male"], int)
    assert data.get("received_female") is None or isinstance(data["received_female"], int)
    _assert_enum_member(
        data["status"],
        {"PLANNED", "LOADED", "IN_TRANSIT", "ARRIVED", "ACCEPTED",
         "REJECTED_AT_RECEIPT", "CANCELLED"},
        "status",
    )


def assert_protocol(data: dict):
    _assert_common_fields(data, "IACUCProtocol")
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert isinstance(data["protocol_number"], str) and data["protocol_number"]
    assert isinstance(data["pi_name"], str) and data["pi_name"]
    _assert_enum_member(data["species"], {"MOUSE", "RAT"}, "species")
    assert isinstance(data["approved_animal_quota"], int) and data["approved_animal_quota"] >= 1
    assert isinstance(data["animals_used"], int) and data["animals_used"] >= 0
    # PRD Section 3.4: the accumulator must remain at or below the quota.
    assert data["animals_used"] <= data["approved_animal_quota"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data.get("submitted_by_user_id") is None or isinstance(data["submitted_by_user_id"], str)
    _assert_enum_member(
        data["status"],
        {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED",
         "SUSPENDED", "EXPIRED", "WITHDRAWN", "REJECTED"},
        "status",
    )


def assert_inspection(data: dict):
    _assert_light_fields(data, "WelfareInspection")
    # Polymorphic site rule (PRD Section 3.9): exactly one of the two site keys.
    site_flags = [data.get("facility_id") is not None, data.get("customer_id") is not None]
    assert sum(site_flags) == 1, "exactly one of facility_id / customer_id must be set"
    _assert_enum_member(
        data["inspection_type"], {"ROUTINE", "FOR_CAUSE", "PRE_PLACEMENT"}, "inspection_type"
    )
    assert is_iso8601_timestamp(data["scheduled_date"])
    assert isinstance(data.get("findings", []), list)
    for finding in data.get("findings", []):
        assert isinstance(finding.get("deficiency"), str)
        _assert_enum_member(finding.get("severity"), {"MINOR", "SIGNIFICANT"}, "severity")
    assert data.get("corrective_deadline") is None or is_iso8601_timestamp(data["corrective_deadline"])
    assert data.get("reported_by_user_id") is None or isinstance(data["reported_by_user_id"], str)
    _assert_enum_member(
        data["status"],
        {"SCHEDULED", "CORRECTIVE_ACTION", "CLOSED_VERIFIED", "ESCALATED"},
        "status",
    )


def assert_contract(data: dict):
    _assert_common_fields(data, "ServiceContract")
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("source_strain_id", "")), "source_strain_id must be a UUID"
    _assert_enum_member(
        data["contract_type"], {"CUSTOM_GENERATION", "CRYOPRESERVATION"}, "contract_type"
    )
    _assert_enum_member(
        data["ip_ownership"],
        {"CUSTOMER_EXCLUSIVE", "SHARED", "VENDOR_RETAINED"},
        "ip_ownership",
    )
    assert data.get("new_strain_spec") is None or isinstance(data["new_strain_spec"], dict)
    assert data.get("exclusivity_fee_cents") is None or isinstance(data["exclusivity_fee_cents"], int)
    assert data.get("royalty_rate_pct") is None or isinstance(data["royalty_rate_pct"], (int, float))
    assert data.get("straw_count") is None or isinstance(data["straw_count"], int)
    assert data.get("viability_pct") is None or isinstance(data["viability_pct"], (int, float))
    assert data.get("generated_strain_id") is None or is_valid_uuid(data["generated_strain_id"])
    _assert_enum_member(
        data["milestone_status"],
        {"DRAFT", "EXECUTED", "IN_PROGRESS", "VALIDATION", "VALIDATION_FAILED",
         "COMPLETED", "CLOSED", "CANCELLED"},
        "milestone_status",
    )


# ---------------------------------------------------------------------------
# PRD-pinned calculators (independent re-implementations for comparison)
# ---------------------------------------------------------------------------

def _parse_iso(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def compute_age_weeks(birth_iso: str, as_of_iso: str) -> int:
    """PRD Section 3.3: floor elapsed to whole days, then to whole weeks."""
    elapsed_seconds = (_parse_iso(as_of_iso) - _parse_iso(birth_iso)).total_seconds()
    age_days = math.floor(elapsed_seconds / SECONDS_PER_DAY)
    return age_days // DAYS_PER_WEEK


def _round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_expected_quote(
    quantity_total: int,
    base_price_cents: int,
    immune_class: str,
    min_health_status: str,
) -> int:
    """PRD Section 3.6 quote arithmetic with the pinned evaluation order:
    tier discount first (rounded half-up), then surcharges (rounded half-up).
    """
    subtotal = Decimal(quantity_total * base_price_cents)
    if quantity_total >= TIER2_QTY:
        discount = Decimal(str(TIER2_DISCOUNT))
    elif quantity_total >= TIER1_QTY:
        discount = Decimal(str(TIER1_DISCOUNT))
    else:
        discount = Decimal("0")
    discounted = _round_half_up_cents(subtotal * (Decimal("1") - discount))
    surcharge = Decimal("0")
    if immune_class == "IMMUNOCOMPROMISED":
        surcharge += Decimal(str(IMMUNO_SURCHARGE))
    if min_health_status == "GERM_FREE":
        surcharge += Decimal(str(GERM_FREE_PREMIUM))
    elif min_health_status == "VF":
        surcharge += Decimal(str(VF_PREMIUM))
    return _round_half_up_cents(Decimal(discounted) * (Decimal("1") + surcharge))


def box_capacity_for_weight(avg_weight_g: float) -> int:
    """PRD Section 3.8 per-box capacity by weight tier."""
    if avg_weight_g < LIGHT_MAX_G:
        return LIGHT_PER_BOX
    if avg_weight_g >= HEAVY_MIN_G:
        return HEAVY_PER_BOX
    return STANDARD_PER_BOX


def compute_expected_box_count(lines) -> int:
    """PRD Section 3.8: ceiling per (allocation, sex) line first, then sum.

    ``lines`` is an iterable of (quantity, avg_weight_g) pairs; zero-quantity
    lines contribute nothing (no line exists for them).
    """
    total = 0
    for qty, avg_weight in lines:
        if qty <= 0:
            continue
        total += math.ceil(qty / box_capacity_for_weight(avg_weight))
    return total


def compute_occupied_cages(pair_counts, cohort_totals) -> int:
    """PRD Section 3.4: one cage per non-retired breeding pair, plus the
    per-cohort ceiling of live headcount divided by the cage density."""
    return sum(pair_counts) + sum(
        math.ceil(total / CAGE_DENSITY) for total in cohort_totals
    )


def compute_projected_pipeline(
    confirmed_available: int,
    breeding_pair_count: int,
    typical_litter_size: int,
    lifecycle_status: str,
    genetic_status: str,
) -> int:
    """PRD Section 3.2: the PROJECTED variant adds the expected next-litter
    yield only for a PRODUCTION colony that is not DRIFT_DETECTED."""
    if lifecycle_status == "PRODUCTION" and genetic_status != "DRIFT_DETECTED":
        return confirmed_available + math.floor(
            breeding_pair_count * typical_litter_size * SURVIVAL_RATE
        )
    return confirmed_available


def assert_cohort_availability_invariants(cohort: dict):
    """PRD Section 3.3 availability bookkeeping: reserved never exceeds count,
    and the available figures are the count-minus-reserved differences."""
    assert cohort["reserved_male"] <= cohort["count_male"]
    assert cohort["reserved_female"] <= cohort["count_female"]
    available_male = cohort["count_male"] - cohort["reserved_male"]
    available_female = cohort["count_female"] - cohort["reserved_female"]
    assert available_male >= 0 and available_female >= 0


def assert_order_coverage_invariants(order: dict):
    """PRD Section 3.7: allocated totals never exceed the requested totals."""
    assert 0 <= order["allocated_male"] <= order["quantity_male"]
    assert 0 <= order["allocated_female"] <= order["quantity_female"]


__all__ = [
    "barrier_rank",
    "assert_barrier_rank_at_least",
    "assert_facility",
    "assert_room",
    "assert_strain",
    "assert_colony",
    "assert_cohort",
    "assert_health_screen",
    "assert_customer",
    "assert_order",
    "assert_allocation",
    "assert_shipment",
    "assert_protocol",
    "assert_inspection",
    "assert_contract",
    "compute_age_weeks",
    "compute_expected_quote",
    "box_capacity_for_weight",
    "compute_expected_box_count",
    "compute_occupied_cages",
    "compute_projected_pipeline",
    "assert_cohort_availability_invariants",
    "assert_order_coverage_invariants",
]
