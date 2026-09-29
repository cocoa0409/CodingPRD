"""Declared entity defaults, server-stamped fields and the read/list surface."""

from test_helpers import (
    COMPLIANCE,
    NON_EXISTENT_UUID,
    OFFICER,
    OFFICER_2,
    PUBLIC,
    STEWARD,
    ApiErrorId,
    CandidateStatus,
    Category,
    CycleStatus,
    DataState,
    IndicatorDomain,
    InterviewStatus,
    Posture,
    PostingStatus,
    Sector,
    Subgroup,
    ValuationBasis,
    add_commitment,
    add_data_point,
    add_indicator,
    advance_to,
    assert_budget_identity,
    assert_close,
    assert_common_fields,
    assert_cycle,
    assert_indicator,
    assert_interview,
    build_scenario,
    create_cycle,
    make_indicator_sufficient,
    make_partner_representative_headers,
    open_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F

CYCLE_COUNTERS = (
    "sufficient_indicator_count",
    "completed_interview_count",
    "selected_priority_count",
    "review_flag_count",
    "board_deferral_count",
    "mid_cycle_adjustment_count",
    "annual_report_count",
)


def test_creating_a_cycle_returns_every_declared_counter_at_zero(api):
    """PRD §3.1: "A new cycle lands in `DRAFT` with `posture` at `OPEN`, every
    derived counter at zero, and `version` at 1."

    Design: Corner/entities/create_assessment_cycle_returns_201_with_all_declared_fields
    """
    empty, meta = validate_paginated(api.list_cycles(limit=10, offset=0))
    assert empty == [] and meta["total_count"] == 0

    cycle = validate_success(api.create_cycle(F.cycle_payload()), 201)
    assert_cycle(cycle, status=CycleStatus.DRAFT, posture=Posture.OPEN, version=1)
    for counter in CYCLE_COUNTERS:
        assert cycle[counter] == 0, f"{counter} should start at 0, got {cycle[counter]!r}"
    assert cycle["public_availability_met"] is False


def test_a_new_cycle_carries_a_bare_uuid_and_echoes_its_four_inputs(api):
    """PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with exactly
    three fractional-second digits, recording when the record was first stored."

    Design: Corner/entities/create_assessment_cycle_returns_201_with_all_declared_fields
    """
    cycle = validate_success(api.create_cycle(F.cycle_payload()), 201)

    assert_common_fields(cycle, expected_version=1)
    assert "_" not in cycle["id"], f"id carries a type prefix: {cycle['id']!r}"
    assert cycle["fiscal_year"] == C.FISCAL_YEAR
    assert cycle["service_area_name"] == C.SERVICE_AREA_NAME
    assert_close(cycle["prior_year_cost_to_charge_ratio"], C.PRIOR_YEAR_RATIO, "ratio")
    assert cycle["total_operating_expense_cents"] == C.TOTAL_OPERATING_EXPENSE_CENTS
    assert isinstance(cycle["total_operating_expense_cents"], int)


def test_a_new_cycle_has_no_adoption_publication_or_filing_record(api):
    """PRD §2.10: "Every field this document describes as a stamped instant —
    `completed_at`, `adopted_at`, `published_at`, `filed_at`, `submitted_at`,
    `approved_at`, `baseline_locked_at`, `hospital_signed_at`,
    `partner_signed_at`, `committed_at`, `released_at`, `locked_at` — is taken
    from the logical clock at the moment the transition is applied, and each is
    null until its transition has occurred."

    PRD §3.7: "On success the cycle's `status` moves `BOARD_REVIEW` to
    `ADOPTED`; `adopted_at` is stamped from the logical clock,
    `adoption_board_user_id` records the acting `X-User-ID`, and
    `votes_for_at_adoption` and `votes_against_at_adoption` preserve the tallies
    exactly as recorded."

    PRD §3.9: "On success the `public_url` and `public_comment_channel` are
    stored, `published_at` is stamped from the logical clock, the boolean
    `public_availability_met` is set to true, and `status` moves `ADOPTED` to
    `PUBLISHED`."

    PRD §3.9: "When both checks pass the `return_form_id` is stored on the
    cycle, the cycle's `filed_at` is stamped from the logical clock, and
    `status` moves to `FILED`."

    Design: Corner/entities/create_assessment_cycle_returns_201_with_all_declared_fields
    """
    cycle = validate_success(api.create_cycle(F.cycle_payload()), 201)

    for field in (
        "adopted_at",
        "adoption_board_user_id",
        "votes_for_at_adoption",
        "votes_against_at_adoption",
        "public_url",
        "public_comment_channel",
        "published_at",
        "return_form_id",
        "filed_at",
    ):
        assert cycle[field] is None, f"{field} should be null on a fresh cycle: {cycle[field]!r}"


def test_a_scheduled_session_leaves_every_completion_field_null(api):
    """PRD §3.3: "A new session starts with `status` at `SCHEDULED`, with
    `concern_ratings`, `attendee_count`, `completed_at` and `cancel_reason` all
    null."

    Design: Corner/entities/create_stakeholder_interview_applies_scheduled_and_null_completion_defaults
    """
    sc = build_scenario(api, stage="INDICATOR")
    advance_to(api, sc.cycle_id, CycleStatus.INPUT_GATHERING)

    interview = validate_success(
        api.create_interview(F.interview_payload(sc.cycle_id, sc.facilitator_party_id)), 201
    )
    assert_interview(
        interview,
        status=InterviewStatus.SCHEDULED,
        version=1,
        cycle_id=sc.cycle_id,
        facilitator_party_id=sc.facilitator_party_id,
        organization_name=C.ORGANIZATION_NAME,
        sector=Sector.SAFETY_NET_PROVIDER,
    )
    for field in ("concern_ratings", "attendee_count", "completed_at", "cancel_reason"):
        assert interview[field] is None, f"{field} should be null: {interview[field]!r}"
    assert sc.cycle()["completed_interview_count"] == 0


def test_a_posting_stamps_the_acting_user_rather_than_the_reports_creator(api):
    """PRD §3.9: "A new posting is created with `status` at `POSTED`,
    `posted_by_user_id` set to the acting `X-User-ID`, and `void_reason` and
    `voided_by_user_id` null."

    Design: Corner/entities/expense_posting_stamps_posted_by_user_id_from_header
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    assert report["created_by_user_id"] == OFFICER["X-User-ID"]

    posting = validate_success(
        api.create_posting(
            F.charge_based_posting_payload(report["id"], report["version"], 1234567),
            headers=OFFICER_2,
        ),
        201,
    )
    assert posting["posted_by_user_id"] == OFFICER_2["X-User-ID"]
    assert posting["status"] == PostingStatus.POSTED
    assert posting["void_reason"] is None
    assert posting["voided_by_user_id"] is None
    assert validate_success(api.get_report(report["id"]))["created_by_user_id"] == OFFICER[
        "X-User-ID"
    ]


def test_a_posting_freezes_its_ratio_and_basis_from_the_report_it_lands_on(api):
    """PRD §3.9: "Every posting also freezes `valuation_basis_at_posting` to the
    report's `valuation_basis` as it stood at the moment of posting, so a reader
    can tell which numbers were provisional when they were entered."

    Design: Corner/entities/expense_posting_stamps_posted_by_user_id_from_header
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    posting = validate_success(
        api.create_posting(
            F.charge_based_posting_payload(
                report["id"], report["version"], 1234567, category=Category.FINANCIAL_ASSISTANCE
            ),
            headers=OFFICER_2,
        ),
        201,
    )
    # 1234567 * 0.32 = 395061.44, rounded half up to whole cents.
    assert posting["valued_cents"] == 395061
    assert isinstance(posting["valued_cents"], int)
    assert_close(posting["ratio_applied"], C.PRIOR_YEAR_RATIO, "ratio_applied")
    assert posting["valuation_basis_at_posting"] == ValuationBasis.PROVISIONAL


def test_one_overall_observation_derives_severity_but_not_sufficiency(api):
    """PRD §3.2: "Otherwise `severity_score` is the community's rate divided by
    the indicator's `benchmark_value`, multiplied by 50, rounded half up to two
    decimal places, and then capped at 100.00 — the cap is applied *after* the
    rounding, never before."

    PRD §3.2: "Finally `data_state` is `SUFFICIENT` when `latest_overall_value`
    is not null *and* `subgroup_count` is at least 2, and `INSUFFICIENT` in every
    other case."

    Design: Corner/entities/health_indicator_derived_fields_recomputed_on_each_data_point
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    indicator = add_indicator(api, cycle["id"])
    assert_indicator(
        indicator, data_state=DataState.INSUFFICIENT, subgroup_count=0, evidence_count=0, version=1
    )

    add_data_point(api, indicator["id"], population_subgroup=Subgroup.OVERALL, value=C.OVERALL_VALUE)

    after = validate_success(api.get_indicator(indicator["id"]))
    assert_close(after["latest_overall_value"], C.OVERALL_VALUE, "latest_overall_value")
    # 18.6 / 12.0 * 50 = 77.50.
    assert_close(after["severity_score"], 77.50, "severity_score")
    assert after["disparity_ratio"] is None
    assert after["subgroup_count"] == 0
    assert after["evidence_count"] == 1
    assert after["data_state"] == DataState.INSUFFICIENT
    assert after["version"] == 2
    assert validate_success(api.get_cycle(cycle["id"]))["sufficient_indicator_count"] == 0


def test_the_second_named_subgroup_flips_data_state_and_the_cycle_counter(api):
    """PRD §3.2: "When fewer than two such subgroups exist, `disparity_ratio` is
    null; otherwise `disparity_ratio` is the largest representative rate divided
    by the smallest, rounded half up to two decimal places."

    PRD §3.2: "An indicator crossing from `INSUFFICIENT` to `SUFFICIENT` adds 1
    to the cycle's `sufficient_indicator_count`."

    Design: Corner/entities/health_indicator_derived_fields_recomputed_on_each_data_point
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    indicator = add_indicator(api, cycle["id"])

    make_indicator_sufficient(api, indicator["id"])

    after = validate_success(api.get_indicator(indicator["id"]))
    assert_close(after["severity_score"], 77.50, "severity_score")
    # 24.8 / 15.5 = 1.60.
    assert_close(after["disparity_ratio"], 1.60, "disparity_ratio")
    assert after["subgroup_count"] == 2
    assert after["evidence_count"] == 3
    assert after["data_state"] == DataState.SUFFICIENT
    # Three observations, three re-derivations of the owning indicator.
    assert after["version"] == 4
    assert validate_success(api.get_cycle(cycle["id"]))["sufficient_indicator_count"] == 1


def test_reading_one_indicator_echoes_the_row_the_create_returned(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    PRD §3.2: "A fresh indicator starts with `data_state` at `INSUFFICIENT`,
    `subgroup_count` at 0 and `evidence_count` at 0."

    Design: Corner/entities/get_health_indicator_returns_stored_row
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    created = validate_success(
        api.create_indicator(
            F.indicator_payload(
                cycle["id"],
                domain=IndicatorDomain.CHRONIC_DISEASE,
                name="Adult diabetes prevalence",
                benchmark_value=9.5,
            ),
            headers=STEWARD,
        ),
        201,
    )

    read = validate_success(api.get_indicator(created["id"], headers=COMPLIANCE))
    assert read["id"] == created["id"]
    assert read["cycle_id"] == cycle["id"]
    assert read["domain"] == IndicatorDomain.CHRONIC_DISEASE
    assert read["name"] == "Adult diabetes prevalence"
    assert_close(read["benchmark_value"], 9.5, "benchmark_value")
    assert read["version"] == 1
    assert read["data_state"] == DataState.INSUFFICIENT
    assert read["severity_score"] is None
    assert read["evidence_count"] == 0


def test_the_indicator_list_pages_within_one_cycle_and_excludes_the_other(api):
    """PRD §2.3: "For every list response the `meta` object carries `limit` and
    `offset` as they were applied, `total_count` as the number of records
    matching the filters *before* the page window was applied, and `has_more` as
    a boolean that is true when records matching the filters remain beyond the
    current window."

    Design: Corner/entities/list_health_indicators_paginates_and_filters_by_cycle
    """
    cycle_a = create_cycle(api)
    advance_to(api, cycle_a["id"], CycleStatus.DATA_COLLECTION)
    add_indicator(api, cycle_a["id"])
    add_indicator(
        api,
        cycle_a["id"],
        domain=IndicatorDomain.CHRONIC_DISEASE,
        name="Adult diabetes prevalence",
        benchmark_value=9.5,
    )
    cycle_b = create_cycle(
        api,
        fiscal_year=2027,
        service_area_name="Northside District",
        prior_year_cost_to_charge_ratio=C.ALT_PRIOR_YEAR_RATIO,
        total_operating_expense_cents=90000000,
    )
    advance_to(api, cycle_b["id"], CycleStatus.DATA_COLLECTION)
    other = add_indicator(
        api,
        cycle_b["id"],
        domain=IndicatorDomain.ACCESS_TO_CARE,
        name="Uninsured adult rate",
        benchmark_value=8.0,
    )

    first_page, first_meta = validate_paginated(
        api.list_indicators(cycle_id=cycle_a["id"], limit=1, offset=0)
    )
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 1 and first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_indicators(cycle_id=cycle_a["id"], limit=1, offset=1)
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert second_page[0]["id"] != first_page[0]["id"]
    assert other["id"] not in (first_page[0]["id"], second_page[0]["id"])


def test_a_domain_filter_composes_with_the_cycle_filter_and_the_page_window(api):
    """PRD §2.3: "Filters are additive: supplying two of them narrows the result
    set to records satisfying both, and supplying none returns everything the
    acting role is permitted to see."

    Design: Corner/entities/list_health_indicators_paginates_and_filters_by_cycle
    """
    cycle_a = create_cycle(api)
    advance_to(api, cycle_a["id"], CycleStatus.DATA_COLLECTION)
    add_indicator(api, cycle_a["id"])
    chronic = add_indicator(
        api,
        cycle_a["id"],
        domain=IndicatorDomain.CHRONIC_DISEASE,
        name="Adult diabetes prevalence",
        benchmark_value=9.5,
    )

    rows, meta = validate_paginated(
        api.list_indicators(
            cycle_id=cycle_a["id"], domain=IndicatorDomain.CHRONIC_DISEASE, limit=10, offset=0
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == chronic["id"]
    assert rows[0]["domain"] == IndicatorDomain.CHRONIC_DISEASE
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_an_unknown_indicator_id_in_the_path_reports_its_own_not_found_code(api):
    """PRD §2.6: "Path identifiers are resolved strictly left to right, so that
    the outermost segment's failure is what the client sees when several segments
    are wrong at once."

    Design: Corner/entities/get_indicator_with_unknown_id_returns_indicator_not_found
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)

    validate_error(
        api.get_indicator(NON_EXISTENT_UUID), ApiErrorId.INDICATOR_NOT_FOUND, 404
    )
    validate_error(api.get_cycle(NON_EXISTENT_UUID, headers=PUBLIC), ApiErrorId.CYCLE_NOT_FOUND, 404)


def test_the_nested_data_point_path_resolves_its_parent_before_the_body(api):
    """PRD §2.11: "3. Path identifier resolution, left to right — the thirteen
    `ERR_..._NOT_FOUND` codes."

    PRD §2.11: "4. Request-body shape, types, enums, ranges, decimal places and
    cross-field orderings — `ERR_VALIDATION`."

    Design: Corner/entities/get_indicator_with_unknown_id_returns_indicator_not_found
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)

    validate_error(
        api.create_data_point(NON_EXISTENT_UUID, F.data_point_payload(), headers=STEWARD),
        ApiErrorId.INDICATOR_NOT_FOUND,
        404,
    )
    broken = F.data_point_payload()
    broken.pop("value")
    validate_error(
        api.create_data_point(NON_EXISTENT_UUID, broken, headers=STEWARD),
        ApiErrorId.INDICATOR_NOT_FOUND,
        404,
    )


def test_each_required_cycle_input_is_individually_mandatory(api):
    """PRD §2.6: "Request-body shape validation itself covers required-field
    presence, JSON type correctness, enum membership, numeric ranges, and
    decimal-place limits, plus the four cross-field orderings the domain
    requires: a session's `ends_at` must be strictly later than its `starts_at`,
    a commitment's `effective_to` must be strictly later than its
    `effective_from`, an agreement's `term_end` must be the same day as or later
    than its `term_start`, and every entry in a `concern_ratings` object must be
    keyed by a health-domain enum member with an integer value between 1 and 5
    inclusive."

    Design: Corner/entities/create_assessment_cycle_without_total_operating_expense_rejected
    """
    without_expense = F.cycle_payload()
    without_expense.pop("total_operating_expense_cents")
    validate_error(api.create_cycle(without_expense), ApiErrorId.VALIDATION, 400)

    without_area = F.cycle_payload()
    without_area.pop("service_area_name")
    validate_error(api.create_cycle(without_area), ApiErrorId.VALIDATION, 400)

    rows, meta = validate_paginated(api.list_cycles(limit=10, offset=0))
    assert rows == []
    assert meta["total_count"] == 0


def test_enum_ordering_and_duration_constraints_all_report_validation(api):
    """PRD §3.3: "The `sector` is one of `SAFETY_NET_PROVIDER`,
    `PUBLIC_HEALTH_AGENCY`, `SCHOOL_DISTRICT`, `FAITH_BASED`,
    `RESIDENT_COALITION` or `PAYER`."

    PRD §3.3: "The window's `starts_at` is inclusive and its `ends_at` is
    exclusive, `ends_at` must be strictly later than `starts_at`, and the elapsed
    time between them may not exceed 240 minutes — four hours is the longest
    session the system will book."

    Design: Corner/entities/input_type_and_range_constraints_rejected_across_endpoints
    """
    sc = build_scenario(api, stage="INDICATOR")
    advance_to(api, sc.cycle_id, CycleStatus.INPUT_GATHERING)

    unknown_sector = F.interview_payload(
        sc.cycle_id, sc.facilitator_party_id, sector="NEIGHBORHOOD_GROUP"
    )
    validate_error(api.create_interview(unknown_sector), ApiErrorId.VALIDATION, 400)

    reversed_window = F.interview_payload(
        sc.cycle_id,
        sc.facilitator_party_id,
        starts_at="2026-04-06T15:00:00Z",
        ends_at="2026-04-06T14:00:00Z",
    )
    validate_error(api.create_interview(reversed_window), ApiErrorId.VALIDATION, 400)

    too_long = F.interview_payload(
        sc.cycle_id,
        sc.facilitator_party_id,
        starts_at="2026-04-06T09:00:00Z",
        ends_at="2026-04-06T14:00:00Z",
    )
    validate_error(api.create_interview(too_long), ApiErrorId.VALIDATION, 400)

    rows, meta = validate_paginated(api.list_interviews(cycle_id=sc.cycle_id, limit=10, offset=0))
    assert rows == []
    assert meta["total_count"] == 0


def test_body_foreign_keys_resolve_in_declaration_order(api):
    """PRD §2.6: "Foreign keys supplied in a request body are resolved after the
    body has passed its shape check, and in the order the body fields are
    declared for that endpoint."

    Design: Corner/entities/create_priority_candidate_with_unknown_indicator_id_returns_indicator_not_found
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)

    validate_error(
        api.create_candidate(F.candidate_payload(sc.cycle_id, NON_EXISTENT_UUID)),
        ApiErrorId.INDICATOR_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_candidate(F.candidate_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID)),
        ApiErrorId.CYCLE_NOT_FOUND,
        404,
    )

    created = validate_success(
        api.create_candidate(F.candidate_payload(sc.cycle_id, sc.indicator_id)), 201
    )
    assert created["status"] == CandidateStatus.DRAFT
    assert created["cycle_id"] == sc.cycle_id


def test_the_same_commitment_is_reachable_from_all_three_of_its_parents(api):
    """PRD §3.6: "A **resource commitment** is the many-to-many join that
    actually spends money and people: it binds a strategy, a contributing party
    and — optionally — a funding agreement over a date window."

    PRD §2.3: "Resource commitments filter on `strategy_id`, `party_id`,
    `partnership_id` and `status`."

    Design: Corner/entities/resource_commitment_junction_is_reachable_from_all_three_parents
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE", with_partner=True)
    internal = add_commitment(
        api, sc.strategy_id, sc.facilitator_party_id, fte_bp=1000, funding_cents=500000
    )

    by_strategy, strategy_meta = validate_paginated(
        api.list_commitments(strategy_id=sc.strategy_id, limit=10, offset=0)
    )
    assert strategy_meta["total_count"] == 2
    assert {row["id"] for row in by_strategy} == {sc.commitment_id, internal["id"]}

    by_party, party_meta = validate_paginated(
        api.list_commitments(party_id=sc.partner_party_id, limit=10, offset=0)
    )
    assert party_meta["total_count"] == 1
    assert by_party[0]["id"] == sc.commitment_id

    by_partnership, partnership_meta = validate_paginated(
        api.list_commitments(
            headers=make_partner_representative_headers(sc.partner_party_id),
            partnership_id=sc.agreement_id,
            limit=10,
            offset=0,
        )
    )
    assert partnership_meta["total_count"] == 1
    assert by_partnership[0]["id"] == sc.commitment_id
    assert internal["partnership_id"] is None


def test_two_pending_commitments_encumber_both_conserved_quantities(api):
    """PRD §3.6: "A strategy's `budget_available_cents` is its
    `authorized_budget_cents` less the sum of `funding_cents` over every
    commitment on that strategy whose `status` is `PENDING` or `COMMITTED`;
    released commitments are excluded."

    PRD §3.6: "A party's `committed_fte_bp` is likewise the sum of `fte_bp` over
    every commitment naming that `party_id` whose `status` is `PENDING` or
    `COMMITTED`, taken across all strategies and independent of dates; both sums
    are exact integer arithmetic with no rounding."

    Design: Corner/entities/resource_commitment_junction_is_reachable_from_all_three_parents
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE", with_partner=True)
    add_commitment(api, sc.strategy_id, sc.facilitator_party_id, fte_bp=1000, funding_cents=500000)

    strategy = sc.strategy()
    assert strategy["authorized_budget_cents"] == C.AUTHORIZED_BUDGET_CENTS
    # 5,000,000 less 1,500,000 partner funding less 500,000 internal funding.
    assert strategy["budget_available_cents"] == 3000000
    assert_budget_identity(strategy, C.COMMITMENT_FUNDING_CENTS + 500000)

    assert sc.partner()["committed_fte_bp"] == C.COMMITMENT_FTE_BP
    assert sc.facilitator()["committed_fte_bp"] == 1000
