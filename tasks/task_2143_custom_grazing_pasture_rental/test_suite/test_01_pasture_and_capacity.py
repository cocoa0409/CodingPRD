"""Pasture inventory, carrying-capacity ratings and the pasture lifecycle."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_capacity_assessment,
    assert_pasture,
    capacity_assessment_payload,
    create_pasture,
    file_capacity_assessment,
    make_grazier_headers,
    make_range_consultant_headers,
    pasture_payload,
    read_pasture,
    set_pasture_status,
    setup_north_bench_active_contract,
    setup_north_bench_available,
    setup_parties,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Carrying capacity: the two rating methods
# ===========================================================================

def test_dry_matter_assessment_rates_the_unit_and_becomes_effective(api):
    """PRD 3.2: "Under `DRY_MATTER`, the usable forage on the unit is its acreage
    multiplied by the dry-matter yield per acre, multiplied by the utilization
    percentage divided by 100."
    PRD 3.2: "A twelve-hundred-acre unit yielding 1800 pounds of dry matter at 25
    percent utilization rates at 683.54 animal-unit-months and 20769 head-days under
    the first method; the same unit with 5000 prior-season head-days rates at 139.80
    animal-unit-months and 4250 head-days under the second."

    Design: Difficulty/dual_variant_calc/capacity_rating_dry_matter_vs_stocking_history
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id, acres=1200, prior_season_head_days=5000)

    resp = api.create_capacity_assessment(
        pasture["id"],
        capacity_assessment_payload(
            pasture["version"], method="DRY_MATTER",
            forage_dry_matter_lbs_per_acre=1800, utilization_pct=25,
            assessment_date="2026-07-15",
        ),
        make_range_consultant_headers(world.consultant_id),
    )
    assessment = validate_success(resp, 201)
    assert_capacity_assessment(assessment)

    assert assessment["rated_aum"] == pytest.approx(683.54, abs=0.005)
    assert assessment["rated_head_days"] == 20769

    refreshed = read_pasture(pasture["id"], world.grazier_id)
    assert refreshed["effective_assessment_id"] == assessment["id"]
    assert refreshed["rated_aum"] == pytest.approx(683.54, abs=0.005)
    assert refreshed["rated_head_days"] == 20769
    assert refreshed["version"] == 2, "Filing an assessment increments the pasture's version"


def test_stocking_history_assessment_supersedes_the_dry_matter_rating(api):
    """PRD 3.2: "Under `STOCKING_HISTORY`, acreage, yield and utilization are all
    ignored and the unit is rated off what it actually carried: `rated_head_days` is
    last season's head-days multiplied by a safety factor of 0.85, again with the
    fraction discarded, and `rated_aum` is last season's head-days multiplied by that
    same 0.85 and then divided by 30.4 days per month, rounded half up to two decimals."
    PRD 3.2: "The system re-selects which assessment is in force: the one with the
    greatest `assessment_date` wins, and where two share the same greatest
    `assessment_date` the one created later wins."
    PRD 3.2: "Prior assessments are never averaged into the rating — the effective row
    simply replaces the previous picture."

    Design: Difficulty/dual_variant_calc/capacity_rating_dry_matter_vs_stocking_history
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id, acres=1200, prior_season_head_days=5000)
    first = file_capacity_assessment(
        pasture["id"], world.consultant_id, world.grazier_id,
        expected_pasture_version=pasture["version"], method="DRY_MATTER",
        forage_dry_matter_lbs_per_acre=1800, utilization_pct=25,
        assessment_date="2026-07-15",
    )

    current_version = read_pasture(pasture["id"], world.grazier_id)["version"]
    resp = api.create_capacity_assessment(
        pasture["id"],
        {
            "expected_pasture_version": current_version,
            "method": "STOCKING_HISTORY",
            "utilization_pct": 25,
            "assessment_date": "2026-07-20",
        },
        make_range_consultant_headers(world.consultant_id),
    )
    second = validate_success(resp, 201)

    assert second["rated_aum"] == pytest.approx(139.80, abs=0.005)
    assert second["rated_head_days"] == 4250
    assert first["rated_aum"] == pytest.approx(683.54, abs=0.005)
    assert first["rated_head_days"] == 20769

    refreshed = read_pasture(pasture["id"], world.grazier_id)
    assert refreshed["effective_assessment_id"] == second["id"], (
        "The later assessment_date takes force"
    )
    assert refreshed["rated_aum"] == pytest.approx(139.80, abs=0.005)
    assert refreshed["rated_head_days"] == 4250
    assert refreshed["version"] == 3


# ===========================================================================
# Pasture activation: the empty-assessment boundary
# ===========================================================================

def test_activating_an_unrated_pasture_is_refused(api):
    """PRD 3.2: "`DRAFT` may advance to `AVAILABLE`, but only if at least one capacity
    assessment exists for the unit; an unrated pasture is rejected with
    `ERR_NO_CAPACITY_ASSESSMENT`, and the empty-set case is the whole point of that
    check."

    Design: Difficulty/boundary_precision_check/pasture_activation_rejects_empty_assessment_set_then_accepts_one
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id)

    resp = api.set_pasture_status(
        pasture["id"], {"to_status": "AVAILABLE"}, make_grazier_headers(world.grazier_id)
    )
    validate_error(resp, ApiErrorId.ERR_NO_CAPACITY_ASSESSMENT.value, 409)

    unchanged = read_pasture(pasture["id"], world.grazier_id)
    assert unchanged["operational_status"] == "DRAFT"
    assert unchanged["rated_head_days"] == 0
    assert unchanged.get("effective_assessment_id") is None


def test_the_first_assessment_lets_the_same_activation_succeed(api):
    """PRD 3.2: "`DRAFT` may advance to `AVAILABLE`, but only if at least one capacity
    assessment exists for the unit; an unrated pasture is rejected with
    `ERR_NO_CAPACITY_ASSESSMENT`, and the empty-set case is the whole point of that
    check."
    PRD 3.2: "The advance to `AVAILABLE` recomputes `effective_assessment_id`,
    `rated_aum`, `rated_head_days`, `capacity_utilization_pct` and `grazing_posture`,
    and increments the pasture's `version`."

    Design: Difficulty/boundary_precision_check/pasture_activation_rejects_empty_assessment_set_then_accepts_one
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id)
    assessment = file_capacity_assessment(
        pasture["id"], world.consultant_id, world.grazier_id,
        expected_pasture_version=pasture["version"],
    )

    resp = api.set_pasture_status(
        pasture["id"], {"to_status": "AVAILABLE"}, make_grazier_headers(world.grazier_id)
    )
    activated = validate_success(resp, 200)
    assert_pasture(activated)

    assert activated["operational_status"] == "AVAILABLE"
    assert activated["effective_assessment_id"] == assessment["id"]
    assert activated["rated_head_days"] == 20769
    assert activated["grazing_posture"] == "OPEN"


# ===========================================================================
# Pasture creation and its declared starting state
# ===========================================================================

def test_new_pasture_lands_in_draft_with_zero_ratings_and_open_posture(api):
    """PRD 3.2: "A new unit lands in `operational_status` `DRAFT` with
    `grazing_posture` `OPEN`, `rated_aum` and `rated_head_days` at 0, a null
    `effective_assessment_id`, a `drought_destock_flag` of false, and
    `committed_head_days`, `capacity_utilization_pct`, `stocked_head_count` and
    `open_critical_ticket_count` all at 0."
    PRD 3.2: "The owning grazier is taken from `X-User-ID` and stored as the unit's
    `grazier_id` — it is never accepted from the body."

    Design: Corner/entities/create_pasture_returns_draft_with_zero_ratings_and_open_posture
    """
    world = setup_parties()

    resp = api.create_pasture(
        pasture_payload(), make_grazier_headers(world.grazier_id)
    )
    pasture = validate_success(resp, 201)
    assert_pasture(pasture)

    assert pasture["grazier_id"] == world.grazier_id
    assert pasture["operational_status"] == "DRAFT"
    assert pasture["rated_aum"] == 0
    assert pasture["rated_head_days"] == 0
    assert pasture.get("effective_assessment_id") is None
    assert pasture["drought_destock_flag"] is False
    assert pasture["committed_head_days"] == 0
    assert pasture["capacity_utilization_pct"] == 0
    assert pasture["stocked_head_count"] == 0
    assert pasture["open_critical_ticket_count"] == 0
    assert pasture["grazing_posture"] == "OPEN"
    assert pasture["version"] == 1


def test_pasture_with_an_undeclared_forage_type_is_rejected(api):
    """PRD 3.2: "A `Grazier` creates a pasture unit by supplying a `name` for it, its
    grazeable `acres` (which must be greater than zero), the dominant `forage_type` —
    one of `NATIVE_RANGE`, `IMPROVED_PASTURE`, `COOL_SEASON_MIX` or `WARM_SEASON_MIX` —
    the `water_source_type` that supplies stock water, one of `WELL`, `CREEK`,
    `PIPELINE` or `POND`, and the perimeter `fence_class`, one of `CLASS_A`, `CLASS_B`
    or `CLASS_C`."
    PRD 2.8: "The body carries every required field, every enum value is a declared
    member of its enumeration, and every numeric field is inside its declared range —
    otherwise `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_pasture_with_unknown_forage_type_enum_returns_validation
    """
    world = setup_parties()

    resp = api.create_pasture(
        {
            "name": "Bad Stand", "acres": 400, "forage_type": "ALFALFA_HAY",
            "water_source_type": "WELL", "fence_class": "CLASS_B",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_pasture_with_zero_acres_is_rejected(api):
    """PRD 3.2: "A `Grazier` creates a pasture unit by supplying a `name` for it, its
    grazeable `acres` (which must be greater than zero), the dominant `forage_type` —
    one of `NATIVE_RANGE`, `IMPROVED_PASTURE`, `COOL_SEASON_MIX` or `WARM_SEASON_MIX` —
    the `water_source_type` that supplies stock water, one of `WELL`, `CREEK`,
    `PIPELINE` or `POND`, and the perimeter `fence_class`, one of `CLASS_A`, `CLASS_B`
    or `CLASS_C`."
    PRD 2.8: "Ranges include: `acres` greater than 0; `utilization_pct` greater than 0
    and no greater than 60; `shrink_pct` and `out_shrink_pct` between 0 and 10
    inclusive; `drought_index` between 0 and 5 inclusive; head counts and weights
    greater than 0; and the `event_type` supplied when recording a scale ticket
    restricted to `INTERIM` or `OUT`, since the `IN` ticket is created by receiving
    rather than posted directly."

    Design: Corner/validations/create_pasture_with_zero_acres_returns_validation
    """
    world = setup_parties()

    resp = api.create_pasture(
        {
            "name": "Nothing Here", "acres": 0, "forage_type": "NATIVE_RANGE",
            "water_source_type": "WELL", "fence_class": "CLASS_C",
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_assessment_utilization_above_sixty_is_rejected_and_leaves_the_rating_alone(api):
    """PRD 3.2: "The consultant states the `method` — either `DRY_MATTER` or
    `STOCKING_HISTORY` — the harvest-efficiency `utilization_pct` (greater than 0 and
    no greater than 60, the take-half-leave-half factor), and the `assessment_date` on
    which the range was walked."
    PRD 2.8: "Ranges include: `acres` greater than 0; `utilization_pct` greater than 0
    and no greater than 60; `shrink_pct` and `out_shrink_pct` between 0 and 10
    inclusive; `drought_index` between 0 and 5 inclusive; head counts and weights
    greater than 0; and the `event_type` supplied when recording a scale ticket
    restricted to `INTERIM` or `OUT`, since the `IN` ticket is created by receiving
    rather than posted directly."

    Design: Corner/validations/capacity_assessment_utilization_above_sixty_returns_validation
    """
    world = setup_north_bench_available()
    original = read_pasture(world.pasture_id, world.grazier_id)

    resp = api.create_capacity_assessment(
        world.pasture_id,
        capacity_assessment_payload(
            original["version"], utilization_pct=65, assessment_date="2026-08-01"
        ),
        make_range_consultant_headers(world.consultant_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)

    unchanged = read_pasture(world.pasture_id, world.grazier_id)
    assert unchanged["rated_head_days"] == 20769
    assert unchanged["effective_assessment_id"] == world.assessment["id"]


def test_capacity_assessments_are_append_only_rows_that_a_new_filing_supersedes(api):
    """PRD 2.4: "Three record types are append-only ledger rows rather than living
    resources and therefore carry only `id` and `created_at`, with no `updated_at` and
    no `version` at all: capacity assessments, drought readings, and weight events."
    PRD 2.4: "Nothing ever mutates one of those rows in place; a superseding capacity
    assessment is a new row, not an edit."
    PRD 3.2: "Prior assessments are never averaged into the rating — the effective row
    simply replaces the previous picture."

    Design: Corner/entities/capacity_assessment_is_append_only_with_no_version_field
    """
    world = setup_north_bench_available()
    first = world.assessment
    assert "updated_at" not in first, "A capacity assessment must not carry updated_at"
    assert "version" not in first, "A capacity assessment must not carry version"

    current_version = read_pasture(world.pasture_id, world.grazier_id)["version"]
    second = validate_success(
        api.create_capacity_assessment(
            world.pasture_id,
            capacity_assessment_payload(
                current_version, forage_dry_matter_lbs_per_acre=900,
                assessment_date="2026-08-01",
            ),
            make_range_consultant_headers(world.consultant_id),
        ),
        201,
    )

    listed, meta = validate_paginated(
        api.list_capacity_assessments(
            make_grazier_headers(world.grazier_id), params={"pasture_id": world.pasture_id}
        )
    )
    assert meta["total_count"] == 2, "Both rows survive; nothing was edited in place"

    reread_first = validate_success(
        api.get_capacity_assessment(first["id"], make_grazier_headers(world.grazier_id))
    )
    assert reread_first["rated_head_days"] == 20769, "The superseded row keeps its rating"
    assert second["rated_head_days"] == 10384

    refreshed = read_pasture(world.pasture_id, world.grazier_id)
    assert refreshed["effective_assessment_id"] == second["id"]
    assert refreshed["rated_head_days"] == 10384


# ===========================================================================
# Pasture lifecycle terminals and guards
# ===========================================================================

def test_a_closed_pasture_cannot_be_reopened(api):
    """PRD 3.2: "`CLOSED` is terminal — nothing leaves it — and any transition not
    named here is rejected with `ERR_PASTURE_INVALID_STATE`."
    PRD 2.10: "If the pasture's `operational_status` is `CLOSED`, the posture is
    `CLOSED`."

    Design: Corner/state_machines/closed_pasture_cannot_be_reopened_to_available
    """
    world = setup_north_bench_available()
    set_pasture_status(world.pasture_id, world.grazier_id, "CLOSED")

    resp = api.set_pasture_status(
        world.pasture_id, {"to_status": "AVAILABLE"},
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_PASTURE_INVALID_STATE.value, 409)

    unchanged = read_pasture(world.pasture_id, world.grazier_id)
    assert unchanged["operational_status"] == "CLOSED"
    assert unchanged["grazing_posture"] == "CLOSED"


def test_closing_a_pasture_carrying_a_live_contract_is_refused(api):
    """PRD 3.2: "`AVAILABLE` may go to `CLOSED` on the same terms, with one additional
    guard: no contract on the unit may still be in `PENDING_SIGNATURE`, `SUSPENDED`,
    `ACTIVE` or `EARLY_REMOVAL_PENDING`, or the close is rejected with
    `ERR_PASTURE_HAS_ACTIVE_CONTRACTS`."

    Design: Corner/state_machines/closing_a_pasture_with_a_live_contract_is_refused
    """
    world = setup_north_bench_active_contract()

    resp = api.set_pasture_status(
        world.pasture_id, {"to_status": "CLOSED"}, make_grazier_headers(world.grazier_id)
    )
    validate_error(resp, ApiErrorId.ERR_PASTURE_HAS_ACTIVE_CONTRACTS.value, 409)

    unchanged = read_pasture(world.pasture_id, world.grazier_id)
    assert unchanged["operational_status"] == "AVAILABLE"
    assert unchanged["grazing_posture"] == "OPEN"


# ===========================================================================
# Optimistic concurrency on the pasture
# ===========================================================================

def test_replaying_a_stale_expected_pasture_version_is_rejected(api):
    """PRD 2.6: "If `expected_pasture_version` does not equal the pasture's current
    `version`, the request is rejected with `ERR_STALE_PASTURE_VERSION` (HTTP 412)."
    PRD 2.6: "Filing a capacity assessment against a pasture requires the request to
    carry `expected_pasture_version`, a non-optional field holding the pasture
    `version` the client last observed."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_pasture_version_on_a_second_assessment_returns_412
    """
    world = setup_parties()
    pasture = create_pasture(world.grazier_id)
    stale_version = pasture["version"]
    first = file_capacity_assessment(
        pasture["id"], world.consultant_id, world.grazier_id,
        expected_pasture_version=stale_version,
    )
    set_pasture_status(pasture["id"], world.grazier_id, "AVAILABLE")

    resp = api.create_capacity_assessment(
        pasture["id"],
        capacity_assessment_payload(
            stale_version, forage_dry_matter_lbs_per_acre=900,
            assessment_date="2026-08-01",
        ),
        make_range_consultant_headers(world.consultant_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PASTURE_VERSION.value, 412)

    _, meta = validate_paginated(
        api.list_capacity_assessments(
            make_grazier_headers(world.grazier_id), params={"pasture_id": pasture["id"]}
        )
    )
    assert meta["total_count"] == 1, "The rejected filing wrote no row"

    refreshed = read_pasture(pasture["id"], world.grazier_id)
    assert refreshed["version"] == 3
    assert refreshed["effective_assessment_id"] == first["id"]
    assert refreshed["rated_head_days"] == 20769


def test_pasture_version_moves_by_exactly_one_per_mutation(api):
    """PRD 2.4: "Most resources additionally carry `updated_at` — an ISO 8601 UTC
    timestamp refreshed on every mutation — and `version`, an integer that starts at 1
    when the resource is created and increments by exactly one on every mutation of
    that resource."
    PRD 3.2: "The pasture's `capacity_utilization_pct` and then its `grazing_posture`
    are recomputed, and the pasture's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/pasture_version_increments_by_one_on_every_mutation
    """
    world = setup_parties()

    created = validate_success(
        api.create_pasture(pasture_payload(), make_grazier_headers(world.grazier_id)), 201
    )
    assert created["version"] == 1

    validate_success(
        api.create_capacity_assessment(
            created["id"],
            capacity_assessment_payload(created["version"]),
            make_range_consultant_headers(world.consultant_id),
        ),
        201,
    )

    after_assessment = validate_success(
        api.get_pasture(created["id"], make_grazier_headers(world.grazier_id))
    )
    assert after_assessment["version"] == 2

    activated = validate_success(
        api.set_pasture_status(
            created["id"], {"to_status": "AVAILABLE"},
            make_grazier_headers(world.grazier_id),
        )
    )
    assert activated["version"] == 3

    after_read = validate_success(
        api.get_pasture(created["id"], make_grazier_headers(world.grazier_id))
    )
    assert after_read["version"] == 3, "A read-only GET must not move the version"
