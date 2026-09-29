"""Validation corners: uniqueness scopes, capacity aggregates and window edges."""

from test_helpers import (
    STEWARD,
    ApiErrorId,
    Category,
    CycleStatus,
    DataSourceType,
    IndicatorDomain,
    InterviewStatus,
    Sector,
    Subgroup,
    add_commitment,
    add_data_point,
    add_indicator,
    add_internal_party,
    advance_to,
    assert_close,
    build_scenario,
    create_cycle,
    open_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_a_second_cycle_for_the_same_fiscal_year_is_rejected_whatever_its_area(api):
    """PRD §3.1: "Only one cycle may ever exist for a given fiscal year; a second
    attempt is rejected with `ERR_DUPLICATE_FISCAL_YEAR`."

    Design: Corner/validations/duplicate_fiscal_year_and_duplicate_indicator_name_rejected
    """
    first = create_cycle(api, fiscal_year=C.FISCAL_YEAR)

    duplicate = api.create_cycle(
        F.cycle_payload(fiscal_year=C.FISCAL_YEAR, service_area_name="Lakeside County")
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_FISCAL_YEAR, 409)

    # A different year is free.
    other = create_cycle(api, fiscal_year=C.FISCAL_YEAR + 1)
    assert other["fiscal_year"] == C.FISCAL_YEAR + 1
    assert other["id"] != first["id"]


def test_an_indicator_name_is_reserved_inside_its_cycle_and_free_outside_it(api):
    """PRD §3.2: "Indicator names are unique within a cycle, so a repeat name on the
    same cycle is rejected with `ERR_DUPLICATE_INDICATOR_NAME`."

    Design: Corner/validations/duplicate_fiscal_year_and_duplicate_indicator_name_rejected
    """
    cycle_a = create_cycle(api, fiscal_year=C.FISCAL_YEAR)
    advance_to(api, cycle_a["id"], CycleStatus.DATA_COLLECTION)
    add_indicator(api, cycle_a["id"], name=C.INDICATOR_NAME)

    clash = api.create_indicator(
        F.indicator_payload(
            cycle_a["id"],
            domain=IndicatorDomain.CHRONIC_DISEASE,
            name=C.INDICATOR_NAME,
            benchmark_value=9.5,
        )
    )
    validate_error(clash, ApiErrorId.DUPLICATE_INDICATOR_NAME, 409)

    cycle_b = create_cycle(api, fiscal_year=C.FISCAL_YEAR + 1)
    advance_to(api, cycle_b["id"], CycleStatus.DATA_COLLECTION)
    reused = validate_success(
        api.create_indicator(F.indicator_payload(cycle_b["id"], name=C.INDICATOR_NAME)), 201
    )
    assert reused["name"] == C.INDICATOR_NAME
    assert reused["cycle_id"] == cycle_b["id"]


def test_a_scheduled_session_holds_its_organizations_only_seat_on_the_cycle(api):
    """PRD §3.3: "`organization_name` is unique within a cycle across sessions whose
    `status` is `SCHEDULED` or `COMPLETED`; a duplicate is rejected with
    `ERR_DUPLICATE_ORGANIZATION`."

    Design: Corner/validations/cancelled_interview_frees_the_organization_name
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")
    other_facilitator = add_internal_party(api, name="Population Health Analytics")

    # A second facilitator and a distant window, so neither the buffer rule nor a
    # validation error can be the cause.
    rebook = api.create_interview(
        F.interview_payload(
            sc.cycle_id,
            other_facilitator["id"],
            organization_name=C.ORGANIZATION_NAME,
            sector=Sector.SAFETY_NET_PROVIDER,
            starts_at="2026-04-09T14:00:00Z",
            ends_at="2026-04-09T15:00:00Z",
        )
    )
    validate_error(rebook, ApiErrorId.DUPLICATE_ORGANIZATION, 409)


def test_cancelling_the_session_releases_the_organization_name_for_rebooking(api):
    """PRD §3.3: "A cancelled session releases the name, so the same organization can
    be rebooked after a cancellation."

    Design: Corner/validations/cancelled_interview_frees_the_organization_name
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")
    other_facilitator = add_internal_party(api, name="Population Health Analytics")

    cancelled = validate_success(
        api.cancel_interview(sc.interview_id, "Clinic asked to reschedule")
    )
    assert cancelled["status"] == InterviewStatus.CANCELLED
    assert cancelled["cancel_reason"] == "Clinic asked to reschedule"

    rebooked = validate_success(
        api.create_interview(
            F.interview_payload(
                sc.cycle_id,
                other_facilitator["id"],
                organization_name=C.ORGANIZATION_NAME,
                sector=Sector.SAFETY_NET_PROVIDER,
                starts_at="2026-04-09T14:00:00Z",
                ends_at="2026-04-09T15:00:00Z",
            )
        ),
        201,
    )
    assert rebooked["organization_name"] == C.ORGANIZATION_NAME
    assert rebooked["status"] == InterviewStatus.SCHEDULED

    rows, meta = validate_paginated(api.list_interviews(cycle_id=sc.cycle_id))
    assert meta["total_count"] == 2
    assert {row["organization_name"] for row in rows} == {C.ORGANIZATION_NAME}
    assert {row["status"] for row in rows} == {
        InterviewStatus.CANCELLED,
        InterviewStatus.SCHEDULED,
    }


def test_the_capacity_rule_reads_the_partys_running_committed_total(api):
    """PRD §3.6: "Third, the contributing party's existing `committed_fte_bp` plus the
    requested `fte_bp` must not exceed that party's `fte_capacity_bp`, or the create
    fails with `ERR_PARTY_FTE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/two_commitments_individually_valid_exceed_party_fte_capacity
    """
    sc = build_scenario(api, stage="STRATEGY_DEVELOPMENT")
    team = add_internal_party(
        api, name="Behavioural Health Clinic Team", fte_capacity_bp=3000
    )

    first = add_commitment(
        api, sc.strategy_id, team["id"], fte_bp=2000, funding_cents=100000
    )
    assert first["fte_bp"] == 2000
    assert validate_success(api.get_party(team["id"]))["committed_fte_bp"] == 2000

    # 2000 + 2000 > 3000, even though the two windows do not overlap.
    over = api.create_commitment(
        F.commitment_payload(
            sc.strategy_id,
            team["id"],
            fte_bp=2000,
            funding_cents=100000,
            effective_from="2027-04-01",
            effective_to="2027-08-01",
        )
    )
    validate_error(over, ApiErrorId.PARTY_FTE_CAPACITY_EXCEEDED, 409)

    held = validate_success(api.get_party(team["id"]))
    assert held["committed_fte_bp"] == 2000
    assert held["fte_capacity_bp"] == 3000


def test_a_commitment_that_exactly_fills_the_capacity_is_accepted(api):
    """PRD §3.6: "Third, the contributing party's existing `committed_fte_bp` plus the
    requested `fte_bp` must not exceed that party's `fte_capacity_bp`, or the create
    fails with `ERR_PARTY_FTE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/two_commitments_individually_valid_exceed_party_fte_capacity
    """
    sc = build_scenario(api, stage="STRATEGY_DEVELOPMENT")
    team = add_internal_party(
        api, name="Behavioural Health Clinic Team", fte_capacity_bp=3000
    )
    add_commitment(api, sc.strategy_id, team["id"], fte_bp=2000, funding_cents=100000)

    # 2000 + 1000 == 3000 sits on the inclusive edge.
    exact = add_commitment(
        api,
        sc.strategy_id,
        team["id"],
        fte_bp=1000,
        funding_cents=100000,
        effective_from="2027-04-01",
        effective_to="2027-08-01",
    )
    assert exact["fte_bp"] == 1000

    filled = validate_success(api.get_party(team["id"]))
    assert filled["committed_fte_bp"] == 3000
    assert filled["fte_capacity_bp"] == 3000


def test_a_charge_based_category_rejects_a_direct_cost_and_rejects_nothing_at_all(api):
    """PRD §3.9: "`FINANCIAL_ASSISTANCE` and `SUBSIDIZED_SERVICES` are *charge-based*:
    they are recorded at gross charges and converted to cost, so a posting in either
    category requires `charges_cents` to be at least 1 and `direct_cost_cents` to be
    exactly 0."

    Design: Corner/validations/posting_basis_mismatch_rejected_in_both_directions
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    version = report["version"]

    both = api.create_posting(
        F.charge_based_posting_payload(
            report["id"],
            version,
            500000,
            category=Category.SUBSIDIZED_SERVICES,
            direct_cost_cents=200000,
        )
    )
    validate_error(both, ApiErrorId.POSTING_BASIS_MISMATCH, 409)

    neither = api.create_posting(
        F.charge_based_posting_payload(
            report["id"], version, 0, category=Category.FINANCIAL_ASSISTANCE
        )
    )
    validate_error(neither, ApiErrorId.POSTING_BASIS_MISMATCH, 409)

    # The rejections never advanced the report, so the original token still holds.
    accepted = validate_success(
        api.create_posting(
            F.charge_based_posting_payload(
                report["id"], version, 500000, category=Category.SUBSIDIZED_SERVICES
            )
        ),
        201,
    )
    # 500000 * 0.32 = 160000.
    assert accepted["valued_cents"] == 160000
    assert accepted["direct_cost_cents"] == 0


def test_a_cost_based_category_rejects_charges_and_demands_a_direct_cost(api):
    """PRD §3.9: "`COMMUNITY_HEALTH_IMPROVEMENT`, `CASH_AND_INKIND` and
    `COMMUNITY_BUILDING` are *cost-based*: they are recorded at actual cost already,
    so a posting in any of the three requires `direct_cost_cents` to be at least 1
    and `charges_cents` to be exactly 0."

    Design: Corner/validations/posting_basis_mismatch_rejected_in_both_directions
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    version = report["version"]

    charges_on_cost_category = api.create_posting(
        F.charge_based_posting_payload(
            report["id"], version, 500000, category=Category.CASH_AND_INKIND
        )
    )
    validate_error(charges_on_cost_category, ApiErrorId.POSTING_BASIS_MISMATCH, 409)

    zero_direct_cost = api.create_posting(
        F.cost_based_posting_payload(
            report["id"], version, 0, category=Category.COMMUNITY_HEALTH_IMPROVEMENT
        )
    )
    validate_error(zero_direct_cost, ApiErrorId.POSTING_BASIS_MISMATCH, 409)

    accepted = validate_success(
        api.create_posting(
            F.cost_based_posting_payload(
                report["id"], version, 500000, category=Category.CASH_AND_INKIND
            )
        ),
        201,
    )
    assert accepted["valued_cents"] == 500000
    assert accepted["charges_cents"] == 0
    assert accepted["ratio_applied"] is None


def test_the_lower_edge_of_the_evidence_window_is_inclusive(api):
    """PRD §3.2: "Every observation must fall inside the cycle's evidence window:
    `collected_on` must be on or after the first of January three years before the
    cycle's `fiscal_year` — for a cycle reporting on fiscal year 2026, that boundary
    is `2023-01-01` — and on or before the logical clock's current calendar date."

    Design: Corner/validations/data_point_evidence_window_edges_enforced_against_the_logical_clock
    """
    # PRD §2.10: the logical-clock capability returns "HTTP 204 with no body".
    assert api.set_clock(C.DEFAULT_CLOCK).status_code == 204
    cycle = create_cycle(api, fiscal_year=2026)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    indicator = add_indicator(api, cycle["id"])

    one_day_early = api.create_data_point(
        indicator["id"],
        F.data_point_payload(collected_on="2022-12-31"),
        headers=STEWARD,
    )
    validate_error(one_day_early, ApiErrorId.DATA_POINT_OUT_OF_WINDOW, 409)

    on_the_edge = validate_success(
        api.create_data_point(
            indicator["id"],
            F.data_point_payload(collected_on="2023-01-01"),
            headers=STEWARD,
        ),
        201,
    )
    assert on_the_edge["collected_on"] == "2023-01-01"

    stored = validate_success(api.get_indicator(indicator["id"]))
    assert stored["evidence_count"] == 1


def test_the_upper_edge_of_the_evidence_window_tracks_the_logical_clock(api):
    """PRD §3.2: "An observation outside that window is rejected with
    `ERR_DATA_POINT_OUT_OF_WINDOW`."

    PRD §3.2: "`latest_overall_value` is taken from the newest active observation
    whose `population_subgroup` is exactly `OVERALL`, where "newest" means ordering
    candidates by `collected_on` descending and, for ties on that date, by
    `created_at` descending, then taking the first; identifiers are never used as a
    tie-break."

    Design: Corner/validations/data_point_evidence_window_edges_enforced_against_the_logical_clock
    """
    # PRD §2.10: the logical-clock capability returns "HTTP 204 with no body".
    assert api.set_clock(C.DEFAULT_CLOCK).status_code == 204
    cycle = create_cycle(api, fiscal_year=2026)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    indicator = add_indicator(api, cycle["id"])
    add_data_point(
        api,
        indicator["id"],
        population_subgroup=Subgroup.OVERALL,
        value=18.6,
        collected_on="2023-01-01",
    )

    # The clock stands at 2026-08-01, so tomorrow's collection is not evidence yet.
    tomorrow = api.create_data_point(
        indicator["id"],
        F.data_point_payload(
            source_type=DataSourceType.COMMUNITY_SURVEY, value=19.2, collected_on="2026-08-02"
        ),
        headers=STEWARD,
    )
    validate_error(tomorrow, ApiErrorId.DATA_POINT_OUT_OF_WINDOW, 409)

    today = validate_success(
        api.create_data_point(
            indicator["id"],
            F.data_point_payload(
                source_type=DataSourceType.COMMUNITY_SURVEY, value=19.2, collected_on="2026-08-01"
            ),
            headers=STEWARD,
        ),
        201,
    )
    assert today["collected_on"] == "2026-08-01"

    stored = validate_success(api.get_indicator(indicator["id"]))
    assert stored["evidence_count"] == 2
    assert_close(stored["latest_overall_value"], 19.2, "latest_overall_value")
    # 19.2 / 12.0 * 50 = 80.00.
    assert_close(stored["severity_score"], 80.00, "severity_score")
