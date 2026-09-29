"""What a freshly created record looks like before anything happens to it.

Every field a client cannot set — the certified status of a new entity, the
whole distress profile of a tract, the reserve tier of an investment, the
sponsor stamped from an identity header — is fixed by the specification, and a
malformed or unresolvable creation writes nothing at all.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    NON_EXISTENT_UUID,
    REVIEWER_ELIGIBILITY_USER_ID,
    SETUP_CLOCK,
    SPONSOR_DELTA_USER_ID,
    TEST_USERS,
    assert_append_only_fields,
    assert_cde,
    assert_cents,
    assert_census_tract,
    assert_instant,
    assert_pct,
    assert_qalicb,
    assert_qei,
    create_allocation_award_payload,
    create_cde_payload,
    create_census_tract_payload,
    create_qalicb_payload,
    create_qei_payload,
    eligibility_test_payload,
    is_valid_uuid,
    make_agency_headers,
    make_qalicb_sponsor_headers,
    make_reviewer_headers,
    plus_days,
    read_cde,
    read_qalicb,
    set_clock,
    setup_active_award,
    setup_funded_fund,
    validate_error,
    validate_paginated,
    validate_success,
)

SEVERE_TRACT = {
    "tract_code": "28049000100",
    "state_code": "MS",
    "poverty_rate_pct": 32.00,
    "mfi_ratio_pct": 55.00,
    "unemployment_ratio": 1.80,
}


def _register_severe_tract(api):
    """The canonical severe tract, registered at the clock's start value."""
    set_clock(api, CLOCK_DEFAULT_UTC)
    return validate_success(
        api.create_census_tract(
            create_census_tract_payload(**SEVERE_TRACT), make_agency_headers()
        ),
        201,
    )


def test_certifying_an_entity_returns_the_certified_default_shape(api):
    """Three inputs go in and a fully defaulted entity comes back.

    PRD: "A new entity starts with `certification_status` `CERTIFIED`, with
    `decertified_at` and `decertification_reason` both null, and with
    `award_count` at 0."

    PRD: "Before the clock has ever been set it reads exactly
    `2026-08-01T00:00:00.000Z`, and it must never fall back to the host's real
    time."

    Design: Corner/entities/create_cde_returns_201_with_certified_status_and_zero_award_count
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    created = validate_success(
        api.create_cde(
            create_cde_payload(
                legal_name="Gulf Coast Community Development Entity",
                certification_number="CDE-2869-101",
                service_area_scope="STATEWIDE",
            ),
            make_agency_headers(),
        ),
        201,
    )

    assert_cde(created)
    assert created["legal_name"] == "Gulf Coast Community Development Entity"
    assert created["certification_number"] == "CDE-2869-101"
    assert created["service_area_scope"] == "STATEWIDE"
    assert created["certification_status"] == "CERTIFIED"
    assert created["award_count"] == 0
    assert created["decertified_at"] is None
    assert created["decertification_reason"] is None
    assert_instant(created["created_at"], CLOCK_DEFAULT_UTC, "created_at")
    assert_instant(created["updated_at"], CLOCK_DEFAULT_UTC, "updated_at")


def test_reading_a_tract_returns_the_profile_computed_at_registration(api):
    """The register is configuration: the read and the write agree exactly.

    PRD: "A census tract in particular is immutable configuration: its
    statistics and its whole derived distress profile are computed once, when it
    is registered, and never revised."

    PRD: "`severe_criteria_met_count` counts how many of three independent
    criteria the tract meets, and is therefore an integer from 0 through 3: the
    `poverty_rate_pct` being at least 30.00 counts as one, the `mfi_ratio_pct`
    being at most 60.00 counts as one, and the `unemployment_ratio` being at
    least 1.50 counts as one."

    PRD: "Otherwise, a tract meeting at least 2 of the severe criteria *and*
    scoring at least 75.00 is `SEVERE`."

    Design: Corner/entities/get_census_tract_returns_the_stored_computed_distress_profile
    """
    registered = _register_severe_tract(api)
    fetched = validate_success(
        api.get_census_tract(registered["id"], TEST_USERS["eligibility_reviewer_headers"])
    )

    assert_census_tract(fetched)
    assert fetched["tract_code"] == "28049000100"
    assert fetched["state_code"] == "MS"
    assert fetched["is_low_income_community"] is True
    assert fetched["qualifies_by_contiguity"] is False
    assert fetched["eligible_for_qlici"] is True
    assert fetched["severe_criteria_met_count"] == 3
    assert_pct(fetched["distress_score"], 100.00, "distress_score")
    assert fetched["distress_tier"] == "SEVERE"
    assert fetched == registered, (
        "an immutable tract must read back field-for-field as it was registered"
    )


def test_listing_project_companies_applies_the_default_page(api):
    """No pagination inputs at all still yields a fully described page.

    PRD: "`limit` caps the number of items returned; it defaults to 10, has a
    minimum of 1 and a maximum of 100."

    PRD: "`total_count` is the number of items matching the filters before
    pagination is applied, and `has_more` is true when items remain beyond the
    returned page."

    Design: Corner/entities/list_qalicbs_returns_pagination_fields_with_default_limit
    """
    tract = _register_severe_tract(api)
    for legal_name, naics, sponsor in (
        ("Delta Foods LLC", "311412", SPONSOR_DELTA_USER_ID),
        ("Delta Machine Works LLC", "332710", SPONSOR_DELTA_USER_ID),
        ("Delta Clinic LLC", "621111", "sponsor-echo"),
    ):
        validate_success(
            api.create_qalicb(
                create_qalicb_payload(
                    tract["id"], legal_name=legal_name, naics_code=naics
                ),
                make_qalicb_sponsor_headers(sponsor),
            ),
            201,
        )

    rows, meta = validate_paginated(api.list_qalicbs(make_agency_headers()))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(rows) == 3
    for row in rows:
        assert_qalicb(row)
        assert row["eligibility_status"] == "PENDING"


def test_reading_an_unknown_investment_reports_the_investment_not_found_code(api):
    """Path resolution answers before ownership is even consulted.

    PRD: "The first identifier that resolves to nothing decides the response, and
    each resource has its own not-found code: `ERR_CDE_NOT_FOUND`,
    `ERR_ALLOCATION_AWARD_NOT_FOUND`, `ERR_CENSUS_TRACT_NOT_FOUND`,
    `ERR_QALICB_NOT_FOUND`, `ERR_INVESTMENT_FUND_NOT_FOUND`,
    `ERR_QEI_NOT_FOUND`, `ERR_QLICI_NOT_FOUND`,
    `ERR_REINVESTMENT_OBLIGATION_NOT_FOUND`, `ERR_CBA_NOT_FOUND` and
    `ERR_UNWIND_NOT_FOUND`, all HTTP 404."

    PRD: "Every path identifier resolves, left to right, on every operation that
    has one — otherwise the matching not-found code."

    Design: Corner/entities/get_qei_with_an_unknown_id_returns_qei_not_found
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    refused = api.get_qei(NON_EXISTENT_UUID, TEST_USERS["cde_sponsor_headers"])
    validate_error(refused, ApiErrorId.ERR_QEI_NOT_FOUND.value, 404)
    assert refused.json()["data"]["message"], "a 404 must carry a human-readable message"


def test_announcing_an_award_without_the_authority_amount_writes_nothing(api):
    """A shape failure at rung 4 leaves even the allocatee's counter alone.

    PRD: "On every write operation, every required input field is present, of its
    declared type, inside any declared range, and every enumerated field carries a
    declared value — otherwise `ERR_INVALID_REQUEST`."

    PRD: "Announcement also raises the allocatee's `award_count` by 1 and
    increments that entity's `version`."

    Design: Corner/entities/create_allocation_award_without_allocation_amount_returns_invalid_request
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    cde = validate_success(
        api.create_cde(
            create_cde_payload(certification_number="CDE-2869-102"), make_agency_headers()
        ),
        201,
    )

    payload = create_allocation_award_payload(cde["id"])
    payload.pop("allocation_amount_cents")
    refused = api.create_allocation_award(payload, make_agency_headers())
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _, meta = validate_paginated(api.list_allocation_awards(make_agency_headers()))
    assert meta["total_count"] == 0, "a refused announcement persists no award"
    assert read_cde(api, cde["id"])["award_count"] == 0


def test_registering_a_business_defaults_every_derived_counter(api):
    """Nothing about eligibility is client-supplied at registration time.

    PRD: "A new business starts with `eligibility_status` `PENDING`,
    `last_certified_at` and `latest_test_result` both null,
    `consecutive_failed_test_count` at 0, and `funding_qlici_count` at 0 — that
    counter tracks how many of its sub-allocations have a `status` other than
    `REPAID`."

    Design: Corner/entities/new_qalicb_defaults_to_pending_with_null_certification_and_zero_counters
    """
    tract = _register_severe_tract(api)
    created = validate_success(
        api.create_qalicb(
            create_qalicb_payload(tract["id"]),
            make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
        ),
        201,
    )

    assert_qalicb(created)
    assert created["eligibility_status"] == "PENDING"
    assert created["last_certified_at"] is None
    assert created["latest_test_result"] is None
    assert created["consecutive_failed_test_count"] == 0
    assert created["funding_qlici_count"] == 0
    assert created["sponsor_user_id"] == SPONSOR_DELTA_USER_ID


def test_issuing_an_investment_derives_its_reserve_tier_and_its_deadline(api):
    """Four inputs go in; the reserve, the net and both clocks come out derived.

    PRD: "The tier is selected from the **gross** `qei_amount_cents`, never from a
    net or post-fee figure: a gross below 500000000 cents draws a `reserve_bps` of
    500, a gross that is at least 500000000 but below 1500000000 draws 400, and a
    gross of 1500000000 or more draws 300."

    PRD: "The `net_deployable_cents` are the gross amount less those permitted
    fees, and `uninvested_cash_cents` opens at exactly that net figure."

    PRD: "`issued_at` is stamped from the logical clock and anchors every
    compliance-year window for the next seven years; `issued_by_user_id` records
    the acting sponsor; `deployment_deadline_at` is the issuance instant advanced
    by 365 days, and it is the last instant at which any sub-allocation may be
    placed from this investment."

    Design: Corner/entities/qei_reserve_and_deadline_fields_are_computed_not_client_controlled
    """
    scenario = setup_active_award(api, clock=SETUP_CLOCK, certification_suffix=103)
    setup_funded_fund(api, scenario)
    signed_version = scenario.award["version"]

    issued = validate_success(
        api.create_qei(
            create_qei_payload(
                scenario.award["id"], scenario.fund["id"], signed_version
            ),
            scenario.cde_headers,
        ),
        201,
    )

    assert_qei(issued)
    assert issued["reserve_bps"] == 500
    assert_cents(issued["permitted_fees_cents"], 5_000_000, "permitted_fees_cents")
    assert_cents(issued["net_deployable_cents"], 95_000_000, "net_deployable_cents")
    assert_cents(issued["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents")
    assert_instant(issued["issued_at"], SETUP_CLOCK, "issued_at")
    assert_instant(
        issued["deployment_deadline_at"],
        plus_days(SETUP_CLOCK, 365),
        "deployment_deadline_at",
    )
    assert issued["issued_by_user_id"] == scenario.cde["id"]
    assert issued["deployment_status"] == "ISSUED"
    assert issued["compliance_status"] == "COMPLIANT"
    assert_pct(issued["substantially_all_pct_direct"], 0.00, "substantially_all_pct_direct")
    assert issued["compliance_years_completed"] == 0
    assert_cents(issued["accrued_unpaid_fee_cents"], 0, "accrued_unpaid_fee_cents")
    assert issued["recapture_trigger_type"] == "NONE"

    award = validate_success(
        api.get_allocation_award(scenario.award["id"], make_agency_headers())
    )
    assert_cents(
        award["remaining_authority_cents"], 4_900_000_000, "remaining_authority_cents"
    )
    assert award["version"] == signed_version + 1


def test_the_registering_identity_wins_over_a_sponsor_named_in_the_body(api):
    """A body that claims a different sponsor is silently ignored.

    PRD: "The `sponsor_user_id` is stamped from the acting `X-User-ID` and is never
    read from the body — any value supplied there is ignored."

    PRD: "`id` (string): a server-minted UUID. It carries no type prefix of any
    kind."

    PRD: "`created_at` (string): the ISO 8601 UTC instant, with three fractional
    digits, at which the row was created."

    Design: Corner/entities/qalicb_sponsor_and_identity_fields_are_stamped_by_the_system_not_the_body
    """
    tract = _register_severe_tract(api)
    payload = create_qalicb_payload(tract["id"])
    payload["sponsor_user_id"] = "sponsor-echo"
    payload["id"] = "qalicb-supplied-by-the-client"

    created = validate_success(
        api.create_qalicb(payload, make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID)),
        201,
    )

    assert created["sponsor_user_id"] == SPONSOR_DELTA_USER_ID
    assert is_valid_uuid(created["id"]), "the identifier must be a server-minted UUID"
    assert created["id"] != "qalicb-supplied-by-the-client"
    assert_instant(created["created_at"], CLOCK_DEFAULT_UTC, "created_at")
    assert_instant(created["updated_at"], CLOCK_DEFAULT_UTC, "updated_at")

    fetched = read_qalicb(api, created["id"])
    assert fetched["sponsor_user_id"] == SPONSOR_DELTA_USER_ID


def test_an_undeclared_measurement_convention_is_refused_before_the_award_exists(api):
    """Only two conventions are declared, and the enum is checked at rung 4.

    PRD: "the compliance-measurement convention as `substantially_all_method`,
    which is either `DIRECT_TRACING` or `AGGREGATE_BALANCE` and is fixed for the
    award's whole life."

    PRD: "The award opens with `lifecycle_status` `ANNOUNCED` and
    `compliance_posture` `UNRESTRICTED`; `remaining_authority_cents` is initialised
    to the full `allocation_amount_cents`; `issued_qei_count`, `at_risk_qei_count`,
    `recaptured_qei_count` and `cba_breach_count` all start at 0,
    `severe_distress_share_pct` starts at 0.00, and `last_agency_report_year`
    starts null."

    Design: Corner/entities/create_allocation_award_with_an_unknown_substantially_all_method_returns_invalid_request
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    cde = validate_success(
        api.create_cde(
            create_cde_payload(certification_number="CDE-2869-104"), make_agency_headers()
        ),
        201,
    )

    refused = api.create_allocation_award(
        create_allocation_award_payload(
            cde["id"], substantially_all_method="TIME_WEIGHTED"
        ),
        make_agency_headers(),
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert read_cde(api, cde["id"])["award_count"] == 0

    accepted = validate_success(
        api.create_allocation_award(
            create_allocation_award_payload(
                cde["id"], substantially_all_method="DIRECT_TRACING"
            ),
            make_agency_headers(),
        ),
        201,
    )
    assert accepted["substantially_all_method"] == "DIRECT_TRACING"
    assert accepted["lifecycle_status"] == "ANNOUNCED"
    assert accepted["compliance_posture"] == "UNRESTRICTED"
    assert_cents(
        accepted["remaining_authority_cents"], 5_000_000_000, "remaining_authority_cents"
    )
    assert accepted["issued_qei_count"] == 0
    assert accepted["at_risk_qei_count"] == 0
    assert accepted["recaptured_qei_count"] == 0
    assert accepted["cba_breach_count"] == 0
    assert_pct(accepted["severe_distress_share_pct"], 0.00, "severe_distress_share_pct")
    assert accepted["last_agency_report_year"] is None
    assert read_cde(api, cde["id"])["award_count"] == 1


SECOND_TEST_CLOCK = "2026-08-15T00:00:00.000Z"


def test_an_eligibility_observation_carries_no_version_and_is_never_rewritten(api):
    """A second test appends a second row; the first one is left exactly as it was.

    PRD: "Four record types are append-only observations rather than mutable
    resources, and they carry only `id` and `created_at` — both `updated_at` and
    `version` are absent from them entirely: census tracts, eligibility tests,
    annual compliance tests and job reports."

    PRD: "Each test row records the `performed_by_user_id` of the reviewer and its
    `performed_at` instant from the logical clock."

    PRD: "eligibility tests are returned oldest `performed_at` first"

    Design: Corner/entities/eligibility_test_rows_are_immutable_with_no_version_field_and_no_update_endpoint
    """
    tract = _register_severe_tract(api)
    qalicb = validate_success(
        api.create_qalicb(
            create_qalicb_payload(tract["id"]),
            make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
        ),
        201,
    )
    reviewer = make_reviewer_headers(REVIEWER_ELIGIBILITY_USER_ID)

    first = validate_success(
        api.run_eligibility_test(qalicb["id"], eligibility_test_payload(), reviewer),
        201,
    )
    assert_append_only_fields(first, "eligibility test")
    assert first["performed_by_user_id"] == REVIEWER_ELIGIBILITY_USER_ID
    assert_instant(first["performed_at"], CLOCK_DEFAULT_UTC, "performed_at")
    assert first["result"] == "PASS"
    first_snapshot = dict(first)

    set_clock(api, SECOND_TEST_CLOCK)
    second = validate_success(
        api.run_eligibility_test(
            qalicb["id"],
            eligibility_test_payload(
                gross_income_lic_pct=90.00,
                services_lic_pct=90.00,
                tangible_property_lic_pct=90.00,
                collectibles_pct=0.00,
                nonqualified_financial_property_pct=0.00,
                location_prong_passed=True,
            ),
            reviewer,
        ),
        201,
    )
    assert_append_only_fields(second, "eligibility test")
    assert_instant(second["performed_at"], SECOND_TEST_CLOCK, "performed_at")
    assert second["id"] != first["id"], "a re-test appends a row, it never rewrites one"

    rows, meta = validate_paginated(api.list_eligibility_tests(qalicb["id"], reviewer))
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert_instant(rows[0]["performed_at"], CLOCK_DEFAULT_UTC, "oldest performed_at")
    assert_instant(rows[1]["performed_at"], SECOND_TEST_CLOCK, "newest performed_at")
    assert rows[0] == first_snapshot, "the earlier observation must read back unchanged"

    business = read_qalicb(api, qalicb["id"])
    assert business["eligibility_status"] == "CERTIFIED"
    assert_instant(business["last_certified_at"], SECOND_TEST_CLOCK, "last_certified_at")


def test_an_unresolvable_tract_answers_before_the_eligibility_rule_is_reached(api):
    """Rung 7 resolves the foreign key; the tract rule at rung 17 never runs.

    PRD: "Every foreign key in the body resolves, in input-declaration order, on
    award announcement, census-tract registration, business registration,
    investment issuance, sub-allocation deployment and agreement creation —
    otherwise the matching not-found code."

    PRD: "The tract named must be `eligible_for_qlici`; a business whose principal
    location does not qualify is refused with `ERR_TRACT_NOT_LIC_ELIGIBLE`."

    Design: Corner/entities/create_qalicb_referencing_an_unknown_census_tract_returns_census_tract_not_found
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    refused = api.create_qalicb(
        create_qalicb_payload(NON_EXISTENT_UUID),
        make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
    )
    validate_error(refused, ApiErrorId.ERR_CENSUS_TRACT_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_qalicbs(make_agency_headers()))
    assert meta["total_count"] == 0, "an unresolvable tract registers no business"
