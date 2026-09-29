"""Entity assertions, instant canonicalisation and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# --- Instant handling -------------------------------------------------------
# PRD §2.4: "All instants exchanged by this API — request fields and response fields
# alike — are ISO 8601 UTC with three fractional digits." Comparisons are made on a
# canonical form so that a response carrying 2026-08-01T00:00:00.000Z matches the
# literal 2026-08-01T00:00:00Z used in request payloads.


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant to whole-second precision with a Z suffix."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        head, _, frac = text.partition(".")
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return f"{text}Z"


def assert_instant_equals(actual, expected, label="instant"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_field(data: dict, field: str):
    """The field is present and holds an ISO 8601 UTC instant."""
    assert field in data, f"{field} must be present"
    assert is_iso8601_timestamp(data[field]), f"{field} must be an ISO 8601 instant, got {data[field]!r}"


def assert_nullable_field_present(data: dict, field: str):
    """PRD §2.4: an unset field is present with a null value rather than omitted."""
    assert field in data, f"{field} must be present in the payload even when unset"


# --- Common field families --------------------------------------------------


def assert_versioned_common_fields(data: dict):
    """Entities that carry id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert_instant_field(data, "created_at")
    assert_instant_field(data, "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_newly_created(data: dict):
    """A newly created resource has version 1 and updated_at equal to created_at."""
    assert data["version"] == 1, f"a new resource has version 1, got {data['version']}"
    assert_instant_equals(data["updated_at"], data["created_at"], "updated_at == created_at")


# --- Entity assertions ------------------------------------------------------

COMMUNITY_MONEY_FIELDS = (
    "concession_budget_cents",
    "facility_commitment_cents",
    "committed_concession_cents",
    "construction_impact_credit_cents",
)


def assert_community(data: dict):
    assert_versioned_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["market_code"], str) and 2 <= len(data["market_code"]) <= 8
    assert isinstance(data["total_planned_units"], int) and data["total_planned_units"] >= 1
    mix = data["product_mix"]
    assert set(mix.keys()) == {"DETACHED", "COTTAGE", "TOWNHOME"}, (
        "product_mix has exactly three keys: DETACHED, COTTAGE and TOWNHOME"
    )
    assert sum(mix.values()) == data["total_planned_units"], (
        "product_mix values sum exactly to total_planned_units"
    )
    for field in COMMUNITY_MONEY_FIELDS:
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
        assert data[field] >= 0, f"{field} must not be negative"
    assert isinstance(data["maintenance_tech_headcount"], int)
    assert data["maintenance_tech_headcount"] >= 1
    assert isinstance(data["single_ownership_covenant"], bool)
    assert data["plat_status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REVISION_REQUESTED",
        "REJECTED",
    )
    assert isinstance(data["plat_revision_round"], int) and data["plat_revision_round"] >= 0
    assert data["lifecycle_status"] in ("PLANNING", "CONSTRUCTION", "LEASE_UP", "STABILIZED")
    assert data["management_mode"] in (
        "DEVELOPER_SELF_MANAGED",
        "PM_TRANSITION_PENDING",
        "PM_MANAGED",
    )
    assert data["facility_status"] in (
        "CONSTRUCTION_DRAW",
        "ADVANCE_ELIGIBLE",
        "CONVERSION_PENDING",
        "PERM_CONVERTED",
    )
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    for field in ("released_unit_count", "available_unit_count", "leased_unit_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert 0.0 <= float(data["occupancy_ratio"]) <= 1.0
    assert 0.0 <= float(data["amenity_delivery_ratio"]) <= 1.0
    for field in ("plat_submitted_by_user_id", "plat_package_reference", "pm_company_name", "pm_effective_from"):
        assert_nullable_field_present(data, field)


def assert_phase(data: dict):
    assert_versioned_common_fields(data)
    assert is_valid_uuid(data["community_id"])
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert data["kind"] in ("HOUSING", "AMENITY")
    assert isinstance(data["planned_unit_count"], int) and data["planned_unit_count"] >= 0
    assert isinstance(data["amenity_weight"], int) and data["amenity_weight"] >= 0
    if data["kind"] == "HOUSING":
        assert data["planned_unit_count"] >= 1 and data["amenity_weight"] == 0
    else:
        assert data["amenity_weight"] >= 1 and data["planned_unit_count"] == 0
    assert_instant_field(data, "construction_window_start")
    assert_instant_field(data, "construction_window_end")
    assert data["status"] in (
        "PLANNED",
        "UNDER_CONSTRUCTION",
        "SECTIONS_RELEASED",
        "CONSTRUCTION_HALTED",
        "COMPLETE",
    )
    assert isinstance(data["halt_count"], int) and data["halt_count"] >= 0
    assert isinstance(data["released_homesite_count"], int)
    assert isinstance(data["leased_homesite_count"], int)
    assert_nullable_field_present(data, "pre_halt_status")
    assert_nullable_field_present(data, "predecessor_phase_id")


def assert_homesite(data: dict):
    assert_versioned_common_fields(data)
    assert is_valid_uuid(data["phase_id"])
    assert isinstance(data["lot_number"], str) and 1 <= len(data["lot_number"]) <= 12
    assert data["product_type"] in ("DETACHED", "COTTAGE", "TOWNHOME")
    assert isinstance(data["bedrooms"], int) and 1 <= data["bedrooms"] <= 5
    assert isinstance(data["square_feet"], int) and 400 <= data["square_feet"] <= 4000
    assert data["status"] in (
        "PLANNED",
        "AVAILABLE",
        "LEASED",
        "NOTICE_GIVEN",
        "IN_TURN",
        "OFF_MARKET",
    )
    assert isinstance(data["turn_cycle_count"], int) and data["turn_cycle_count"] >= 0
    for field in (
        "off_market_reason",
        "occupancy_certificate_number",
        "occupancy_certificate_issued_at",
        "released_at",
        "last_turn_ready_at",
    ):
        assert_nullable_field_present(data, field)


def assert_market_rent_schedule(data: dict):
    assert_versioned_common_fields(data)
    assert is_valid_uuid(data["community_id"])
    assert data["product_type"] in ("DETACHED", "COTTAGE", "TOWNHOME")
    assert_instant_field(data, "effective_from")
    assert data["repricing_mode"] in ("MANUAL", "ABSORPTION_INDEXED")
    assert isinstance(data["asking_rent_cents"], int) and data["asking_rent_cents"] >= 1
    assert isinstance(data["applied_growth_bps"], int)
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")
    assert_nullable_field_present(data, "superseded_at")
    assert isinstance(data["published_by_user_id"], str) and data["published_by_user_id"]


def assert_concession_program(data: dict):
    assert_versioned_common_fields(data)
    assert is_valid_uuid(data["community_id"])
    assert isinstance(data["program_code"], str) and 2 <= len(data["program_code"]) <= 24
    assert data["tier"] in ("NONE", "LIGHT", "MODERATE", "AGGRESSIVE")
    assert isinstance(data["free_weeks"], int) and 0 <= data["free_weeks"] <= 12
    assert data["amortization_mode"] in (
        "STRAIGHT_LINE_NET_EFFECTIVE",
        "UPFRONT_FREE_RENT",
    )
    assert isinstance(data["eligible_product_types"], list)
    assert data["eligible_product_types"], "eligible_product_types is a non-empty subset"
    assert set(data["eligible_product_types"]) <= {"DETACHED", "COTTAGE", "TOWNHOME"}
    assert isinstance(data["restricted_posture_eligible"], bool)
    assert isinstance(data["max_budget_cents"], int) and data["max_budget_cents"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert_nullable_field_present(data, "superseded_at")


def assert_household(data: dict):
    assert_versioned_common_fields(data)
    assert isinstance(data["primary_applicant_name"], str)
    assert 1 <= len(data["primary_applicant_name"]) <= 120
    assert "@" in data["email"]
    assert isinstance(data["household_size"], int) and 1 <= data["household_size"] <= 8
    assert isinstance(data["monthly_income_cents"], int)
    assert data["monthly_income_cents"] >= 0
    assert data["credit_tier"] in ("A", "B", "C")
    assert isinstance(data["active_lease_count"], int) and data["active_lease_count"] >= 0


LEASE_MONEY_FIELDS = (
    "base_rent_cents",
    "community_services_fee_cents",
    "gross_monthly_charge_cents",
    "total_concession_cents",
    "monthly_concession_credit_cents",
    "first_period_charge_cents",
    "net_effective_rent_cents",
    "concession_applied_cents",
    "concession_remaining_cents",
    "construction_impact_credit_cents",
)


def assert_lease(data: dict):
    assert_versioned_common_fields(data)
    assert is_valid_uuid(data["homesite_id"])
    assert is_valid_uuid(data["household_id"])
    assert data["term_months"] in (12, 18, 24)
    assert_instant_field(data, "start_date")
    assert_instant_field(data, "end_date")
    for field in LEASE_MONEY_FIELDS:
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
        assert data[field] >= 0, f"{field} must not be negative"
    assert data["gross_monthly_charge_cents"] == (
        data["base_rent_cents"] + data["community_services_fee_cents"]
    ), "gross_monthly_charge_cents is base_rent_cents plus community_services_fee_cents"
    assert data["lease_status"] in (
        "DRAFT",
        "PENDING_SIGNATURE",
        "EXECUTED",
        "ACTIVE",
        "ENDING",
        "ENDED",
        "CANCELLED",
    )
    assert data["concession_status"] in (
        "NONE",
        "REQUESTED",
        "APPROVED",
        "REJECTED",
        "AMORTIZING",
        "EXHAUSTED",
        "REVOKED",
    )
    assert isinstance(data["concession_schedule"], list)
    assert isinstance(data["credits_applied_count"], int)
    for field in (
        "concession_program_id",
        "concession_requested_by_user_id",
        "concession_decided_by_user_id",
        "cancellation_reason",
        "signed_by_name",
        "executed_at",
        "notice_date",
        "move_out_date",
    ):
        assert_nullable_field_present(data, field)


def assert_turn_work_order(data: dict):
    assert_versioned_common_fields(data)
    assert is_valid_uuid(data["homesite_id"])
    assert_instant_field(data, "window_start")
    assert_instant_field(data, "window_end")
    assert isinstance(data["window_hours"], int) and data["window_hours"] >= 1
    assert data["scope"] in ("MAKE_READY", "DETACHED_YARD_RESTORE", "MAJOR_REHAB")
    assert isinstance(data["tech_count"], int) and 1 <= data["tech_count"] <= 3
    for field in (
        "material_cost_cents",
        "labor_cost_cents",
        "total_turn_cost_cents",
        "tenant_recoverable_cents",
        "community_opex_cents",
        "capital_reserve_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert_nullable_field_present(data, "completed_at")
    assert_turn_allocation_sums(data)


def assert_absorption_review(data: dict):
    """PRD §2.4: the review carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert_instant_field(data, "created_at")
    assert "updated_at" not in data, "AbsorptionReview has no updated_at field"
    assert "version" not in data, "AbsorptionReview has no version field"
    assert is_valid_uuid(data["community_id"])
    assert data["product_type"] in ("DETACHED", "COTTAGE", "TOWNHOME")
    assert_instant_field(data, "window_start")
    assert_instant_field(data, "window_end")
    assert isinstance(data["planned_absorption_units"], int)
    assert data["planned_absorption_units"] >= 1
    assert isinstance(data["actual_absorption_units"], int)
    assert isinstance(data["available_supply_units"], int)
    assert data["posture_at_review"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert float(data["pacing_index"]) >= 0.0
    assert data["concession_tier"] in ("NONE", "LIGHT", "MODERATE", "AGGRESSIVE")
    assert isinstance(data["recommended_growth_bps"], int)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_valuation(data: dict):
    assert data["basis"] in ("TRAILING_ACTUAL", "FORWARD_STABILIZED")
    for field in (
        "in_place_monthly_cents",
        "pro_forma_monthly_cents",
        "annual_gross_cents",
        "vacancy_deduction_cents",
        "egi_cents",
        "opex_cents",
        "noi_cents",
        "value_cents",
        "loan_to_value_bps",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["covenant_satisfied"], bool)
    assert data["noi_cents"] == data["egi_cents"] - data["opex_cents"]
    assert data["covenant_satisfied"] is (data["loan_to_value_bps"] <= 6500)


# --- Domain invariants ------------------------------------------------------


def assert_turn_allocation_sums(order: dict):
    """PRD §3.10: the three buckets always sum to exactly total_turn_cost_cents."""
    total = (
        order["tenant_recoverable_cents"]
        + order["community_opex_cents"]
        + order["capital_reserve_cents"]
    )
    assert total == order["total_turn_cost_cents"], (
        "tenant_recoverable_cents + community_opex_cents + capital_reserve_cents "
        f"must equal total_turn_cost_cents ({total} != {order['total_turn_cost_cents']})"
    )


def assert_concession_schedule_sums(lease: dict):
    """PRD §3.8: the credit_cents values across concession_schedule sum to
    total_concession_cents exactly."""
    schedule = lease["concession_schedule"]
    assert sum(entry["credit_cents"] for entry in schedule) == lease["total_concession_cents"]
    for position, entry in enumerate(schedule, start=1):
        assert entry["period_index"] == position, (
            "concession_schedule period_index runs from 1 upward"
        )


def assert_concession_ledger_identity(community: dict, leases: list, program=None):
    """PRD §2.11: committed_concession_cents equals the sum of concession_remaining_cents
    across the community's leases whose concession_status is APPROVED or AMORTIZING."""
    expected = sum(
        lease["concession_remaining_cents"]
        for lease in leases
        if lease["concession_status"] in ("APPROVED", "AMORTIZING")
    )
    assert community["committed_concession_cents"] == expected, (
        "community committed_concession_cents must equal the sum of concession_remaining_cents "
        f"over APPROVED/AMORTIZING leases ({community['committed_concession_cents']} != {expected})"
    )
    if program is not None:
        program_expected = sum(
            lease["concession_remaining_cents"]
            for lease in leases
            if lease["concession_status"] in ("APPROVED", "AMORTIZING")
            and lease.get("concession_program_id") == program["id"]
        )
        assert program["committed_cents"] == program_expected, (
            "program committed_cents must equal the sum of concession_remaining_cents "
            f"over its APPROVED/AMORTIZING leases ({program['committed_cents']} != {program_expected})"
        )


def assert_community_counters(community: dict, homesites: list):
    """PRD §2.6: the aggregate counters are recomputed from the community's homesites."""
    released = sum(1 for h in homesites if h["released_at"] is not None)
    available = sum(1 for h in homesites if h["status"] == "AVAILABLE")
    leased = sum(1 for h in homesites if h["status"] in ("LEASED", "NOTICE_GIVEN"))
    assert community["released_unit_count"] == released
    assert community["available_unit_count"] == available
    assert community["leased_unit_count"] == leased


def assert_ratio_equals(actual, expected, label="ratio"):
    """Ratios are held to four decimal places (PRD §2.8)."""
    assert round(float(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected}, got {actual}"
    )
