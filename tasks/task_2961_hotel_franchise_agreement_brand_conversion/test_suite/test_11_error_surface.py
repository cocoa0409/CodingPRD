"""Authentication, path resolution and the stage-specific refusals each
resource family reports."""

from test_helpers import (
    BSD_HEADERS,
    FDM_DECIDER_HEADERS,
    FDM_HEADERS,
    NON_EXISTENT_UUID,
    QA_HEADERS,
    ApiErrorId,
    assert_integer,
    assert_money,
    factories,
    fixtures,
    get_success_data,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_unrecognised_role,
    headers_without_user_id,
    make_owner_headers,
    validate_error,
    validate_paginated_list,
)

GUESTROOM_MAJOR_LINE = {
    "category": "GUESTROOM",
    "priority": "MAJOR",
    "description": "Guestroom soft goods and case goods replacement",
    "estimated_cost": 2_400_000.00,
}
LAKESIDE_UNIT = {
    "unit_name": "Solaris Lakeside",
    "market_code": "SEADT",
    "x_miles": 1.20,
    "y_miles": 1.60,
    "room_count": 100,
    "adr_amount": 310.00,
    "occupancy_pct": 72.00,
    "territory_start_date": "2016-06-01",
    "territory_end_date": "2026-09-30",
}
MIDTOWN_UNIT = {
    "unit_name": "Solaris Midtown",
    "market_code": "SEADT",
    "x_miles": 2.40,
    "y_miles": 0.00,
    "room_count": 90,
    "adr_amount": 265.00,
    "occupancy_pct": 70.00,
    "territory_start_date": "2017-02-01",
    "territory_end_date": "2026-09-30",
}


def test_an_absent_or_empty_header_is_an_authentication_failure_and_a_bad_role_is_another(api):
    """PRD §2.1: both identity headers must be present and non-empty, and an
    empty header is treated exactly like an absent one rather than as a bad
    value - so an empty role is a missing header, not an invalid role, while an
    unrecognised role is the invalid-role failure.  None of the four refusals
    creates anything: the brand code they all carried is still free afterwards.

    Design: Corner/errors/request_with_a_missing_auth_header_or_an_invalid_role_is_rejected
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    payload = factories.build_solaris_brand_payload()

    for headers, expected in (
        (headers_without_user_id(), ApiErrorId.MISSING_AUTH_HEADER),
        (headers_with_empty_user_id(), ApiErrorId.MISSING_AUTH_HEADER),
        (headers_with_empty_role(), ApiErrorId.MISSING_AUTH_HEADER),
        (headers_with_unrecognised_role("RegionalDirector"), ApiErrorId.INVALID_ROLE),
    ):
        response = api.create_brand(payload, headers)
        validate_error(response, expected)
        assert response.status_code == 401, (
            f"an authentication failure is a 401, got {response.status_code}"
        )

    brand = get_success_data(api.create_brand(payload, BSD_HEADERS), 201)
    assert brand["code"] == "SOLARIS", (
        "no refused request may have taken the code, or this would be a conflict"
    )


def test_each_resource_family_reports_its_own_not_found_identifier(api):
    """PRD §2.9: an identifier in the path that names no row terminates the
    request with that resource family's own 404, and the rule holds for reads
    and writes alike - ten families, ten distinct identifiers, all against the
    same absent uuid.

    Design: Corner/errors/unknown_path_ids_return_the_entity_specific_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    probes = (
        (api.get_brand(NON_EXISTENT_UUID, FDM_HEADERS), ApiErrorId.BRAND_NOT_FOUND),
        (api.get_owner(NON_EXISTENT_UUID, FDM_HEADERS), ApiErrorId.OWNER_NOT_FOUND),
        (
            api.change_existing_unit_status(
                NON_EXISTENT_UUID,
                factories.build_unit_status_payload("SUSPENDED", "Probe."),
                BSD_HEADERS,
            ),
            ApiErrorId.EXISTING_UNIT_NOT_FOUND,
        ),
        (api.get_application(NON_EXISTENT_UUID, FDM_HEADERS), ApiErrorId.APPLICATION_NOT_FOUND),
        (api.get_encroachment_claim(NON_EXISTENT_UUID, BSD_HEADERS), ApiErrorId.CLAIM_NOT_FOUND),
        (api.get_agreement(NON_EXISTENT_UUID, FDM_HEADERS), ApiErrorId.AGREEMENT_NOT_FOUND),
        (api.get_pip(NON_EXISTENT_UUID, BSD_HEADERS), ApiErrorId.PIP_NOT_FOUND),
        (
            api.verify_pip_item(
                NON_EXISTENT_UUID,
                factories.build_item_verification_payload("VERIFY", verification_notes="Probe."),
                BSD_HEADERS,
            ),
            ApiErrorId.PIP_ITEM_NOT_FOUND,
        ),
        (
            api.review_inspection_cure(
                NON_EXISTENT_UUID,
                factories.build_cure_review_payload("FAIL", review_notes="Probe."),
                QA_HEADERS,
            ),
            ApiErrorId.INSPECTION_NOT_FOUND,
        ),
        (
            api.get_transfer_request(NON_EXISTENT_UUID, FDM_HEADERS),
            ApiErrorId.TRANSFER_REQUEST_NOT_FOUND,
        ),
    )
    for response, expected in probes:
        validate_error(response, expected)
        assert response.status_code == 404, (
            f"{expected} must be a 404, got {response.status_code}"
        )


def test_nothing_leaves_the_terminated_state_on_an_existing_hotel(api):
    """PRD §3.1: only four moves are declared on a hotel's status axis and none
    of them leaves TERMINATED, so a request to reopen a terminated hotel is
    refused - the unit stays TERMINATED and the brand's operating collection is
    empty under the OPERATING filter.

    Design: Corner/errors/reopening_a_terminated_existing_unit_is_rejected
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    unit = fixtures.create_existing_unit(api, brand["id"])
    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    terminated = fixtures.change_unit_status(
        api, unit["id"], "TERMINATED", "Franchise agreement expired."
    )
    assert terminated["status"] == "TERMINATED"

    response = api.change_existing_unit_status(
        unit["id"],
        factories.build_unit_status_payload("OPERATING", "Owner asked to reopen."),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.UNIT_STATUS_TRANSITION_INVALID)
    assert response.status_code == 409

    rows, meta = validate_paginated_list(
        api.list_brand_existing_units(brand["id"], BSD_HEADERS, {"status": "OPERATING"})
    )
    assert_integer(meta["total_count"], 0, "total_count")
    assert rows == []
    all_rows, _ = validate_paginated_list(api.list_brand_existing_units(brand["id"], BSD_HEADERS))
    assert all_rows[0]["status"] == "TERMINATED"


def test_the_two_review_axes_are_reported_in_the_order_the_gate_lists_them(api):
    """PRD §3.4 and §3.5: the final pass may only run from PRELIMINARY, and at
    the approval gate the financial review is checked before the impact study,
    so an approval on an application with neither axis started reports the
    financial review rather than the study.  Once the review passes and a
    preliminary study exists, the same approval reports the study's finality
    instead.

    Design: Corner/errors/application_review_gates_fire_in_priority_order_before_approval
    """
    world = fixtures.setup_reviewable_application(api)
    application_id = world["application_id"]

    premature_final = api.finalize_impact(
        application_id, {"analyst_notes": "Premature finalisation."}, BSD_HEADERS
    )
    validate_error(premature_final, ApiErrorId.IMPACT_STUDY_STAGE_INVALID)
    assert premature_final.status_code == 409
    assert (
        get_success_data(api.get_application(application_id, FDM_HEADERS))["impact_study_status"]
        == "NOT_STARTED"
    )

    premature_approval = api.decide_application(
        application_id,
        factories.build_decision_payload("APPROVE", decision_notes="Premature approval."),
        FDM_DECIDER_HEADERS,
    )
    body = validate_error(premature_approval, ApiErrorId.FINANCIAL_REVIEW_NOT_PASSED)
    assert premature_approval.status_code == 409
    assert body["error_id"] != "ERR_IMPACT_STUDY_NOT_FINAL", (
        "the financial review is checked before the impact study"
    )

    reviewed = fixtures.run_financial_review(api, application_id, "PORTFOLIO_ADJUSTED")
    assert reviewed["financial_review_status"] == "PASSED"
    assert reviewed["capacity_band_at_review"] == "STRONG"
    assert_money(reviewed["capacity_score_at_review"], 100.00, "capacity_score_at_review")

    studied = fixtures.run_impact_analysis(api, application_id)
    assert studied["impact_study_status"] == "PRELIMINARY"
    assert_money(studied["preliminary_impact_score"], 0.00, "preliminary_impact_score")
    assert_integer(
        studied["impact_unit_count_preliminary"], 0, "impact_unit_count_preliminary"
    )

    on_preliminary = api.decide_application(
        application_id,
        factories.build_decision_payload(
            "APPROVE", decision_notes="Approval on a preliminary study."
        ),
        FDM_DECIDER_HEADERS,
    )
    validate_error(on_preliminary, ApiErrorId.IMPACT_STUDY_NOT_FINAL)
    assert on_preliminary.status_code == 409

    application = get_success_data(api.get_application(application_id, FDM_HEADERS))
    assert application["status"] == "UNDER_REVIEW"
    assert application["decision_outcome"] is None


def test_a_draft_license_refuses_every_later_lifecycle_action_by_its_own_stage(api):
    """PRD §3.6 to §3.9: each later operation names the stage it needs, so a
    license still in DRAFT reports 'not executed' for scoping, 'not open' for
    revenue and termination, and 'not termination pending' for de-identification
    and close-out.  Nothing is written by any of them: the ledger is empty and
    both exit axes sit at their draft-time initial values.

    Design: Corner/errors/lifecycle_actions_on_a_draft_agreement_return_the_stage_specific_error
    """
    world = fixtures.setup_drafted_agreement(api)
    agreement_id = world["agreement_id"]
    owner_headers = make_owner_headers(world["owner_id"])

    refusals = (
        (
            api.create_pip(agreement_id, {"scope_notes": "Premature scoping."}, BSD_HEADERS),
            ApiErrorId.AGREEMENT_NOT_EXECUTED,
        ),
        (
            api.report_revenue(
                agreement_id,
                factories.build_revenue_report_payload("2026-11", 100_000.00),
                owner_headers,
            ),
            ApiErrorId.AGREEMENT_NOT_OPEN,
        ),
        (
            api.terminate_agreement(
                agreement_id,
                factories.build_termination_payload(
                    "MUTUAL", termination_notes="Premature termination."
                ),
                BSD_HEADERS,
            ),
            ApiErrorId.AGREEMENT_NOT_OPEN,
        ),
        (
            api.certify_de_identification(
                agreement_id, factories.build_de_identification_payload(), owner_headers
            ),
            ApiErrorId.AGREEMENT_NOT_TERMINATION_PENDING,
        ),
        (
            api.close_out_agreement(
                agreement_id, factories.build_close_out_payload(0.00), BSD_HEADERS
            ),
            ApiErrorId.AGREEMENT_NOT_TERMINATION_PENDING,
        ),
    )
    for response, expected in refusals:
        validate_error(response, expected)
        assert response.status_code == 409

    agreement = get_success_data(api.get_agreement(agreement_id, FDM_HEADERS))
    assert agreement["status"] == "DRAFT"
    assert_integer(agreement["reported_period_count"], 0, "reported_period_count")
    assert agreement["de_identification_status"] == "NOT_REQUIRED"
    assert agreement["post_termination_status"] == "NOT_APPLICABLE"

    _, meta = validate_paginated_list(api.list_agreement_pips(agreement_id, FDM_HEADERS))
    assert_integer(meta["total_count"], 0, "total_count")


def test_a_scoped_plan_refuses_the_sweep_the_verification_and_the_opening(api):
    """PRD §3.7 and §3.6: a plan that has never been accepted refuses a sweep,
    a PENDING line refuses verification, a line with no request on file refuses
    an extension decision - and the opening, whose life-safety and critical
    gates are both vacuous here, reports the onboarding ladders rather than the
    channel or the unaccepted plan, because that is the order the gate lists.

    Design: Corner/errors/plan_and_item_actions_on_a_scoped_plan_return_the_stage_specific_error
    """
    world = fixtures.setup_scoped_plan(api, scope_lines=[GUESTROOM_MAJOR_LINE])
    item_id = world["items"][0]["id"]

    sweep = api.run_compliance_sweep(world["plan_id"], {}, BSD_HEADERS)
    validate_error(sweep, ApiErrorId.PIP_NOT_SCOPED)
    verify = api.verify_pip_item(
        item_id,
        factories.build_item_verification_payload(
            "VERIFY", verification_notes="Nothing submitted yet."
        ),
        BSD_HEADERS,
    )
    validate_error(verify, ApiErrorId.PIP_ITEM_STAGE_INVALID)
    decision = api.decide_pip_item_extension(
        item_id,
        factories.build_extension_decision_payload("GRANT", decision_notes="No request on file."),
        BSD_HEADERS,
    )
    validate_error(decision, ApiErrorId.EXTENSION_NOT_PENDING)
    opening = api.open_agreement(world["agreement_id"], {}, BSD_HEADERS)
    body = validate_error(opening, ApiErrorId.ONBOARDING_INCOMPLETE)
    assert body["error_id"] not in ("ERR_CHANNEL_NOT_CONNECTED", "ERR_PIP_NOT_ACCEPTED"), (
        "the onboarding gate is checked before the channel gate and the plan gate"
    )
    for response in (sweep, verify, decision, opening):
        assert response.status_code == 409

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "SCOPED"
    assert_integer(plan["items_total_count"], 1, "items_total_count")
    assert_integer(plan["items_overdue_count"], 0, "items_overdue_count")

    rows, _ = validate_paginated_list(api.list_pip_items(world["plan_id"], BSD_HEADERS))
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["extension_status"] == "NONE"
    assert rows[0]["due_date"] is None, "a line has no deadline until the plan is accepted"

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["status"] == "EXECUTED"
    assert agreement["training_status"] == "NOT_STARTED"
    assert agreement["opened_at"] is None


def test_a_property_below_the_brand_key_minimum_cannot_be_approved(api):
    """PRD §3.5: the brand key-count minimum is checked at the approval gate,
    not at intake, so a 60-key property is filed and fully reviewed and only
    then refused.  Both review axes keep their results, and no decision-side
    counter moves - the brand still counts the application as open.

    Design: Corner/errors/approving_a_property_below_the_brand_room_minimum_is_rejected
    """
    world = fixtures.setup_reviewed_application(
        api,
        application_overrides={
            "property_name": "Harbor Point Annex",
            "room_count": 60,
            "current_affiliation": "INDEPENDENT",
        },
    )
    response = api.decide_application(
        world["application_id"],
        factories.build_decision_payload("APPROVE", decision_notes="Approved for conversion."),
        FDM_DECIDER_HEADERS,
    )
    validate_error(response, ApiErrorId.ROOM_COUNT_BELOW_BRAND_MINIMUM)
    assert response.status_code == 422

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert application["status"] == "UNDER_REVIEW"
    assert application["decision_outcome"] is None
    assert application["decided_at"] is None
    assert application["financial_review_status"] == "PASSED"
    assert application["impact_study_status"] == "FINAL"
    assert_money(application["final_impact_score"], 0.00, "final_impact_score")
    assert application["encroachment_verdict"] == "CLEAR"

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 1, "open_application_count")


def test_a_confirmed_encroachment_blocks_the_approval_until_a_waiver_is_supplied(api):
    """PRD §3.5: a verdict of ENCROACHMENT_CONFIRMED refuses the approval unless
    the caller supplies the documented override, and the identical request with
    the waiver flag set succeeds.  Both incumbent territories expired the day
    before the requested conversion date, so the territory rule that would
    otherwise outrank this one cannot fire.

    Design: Corner/errors/approving_a_confirmed_encroachment_needs_an_explicit_waiver
    """
    world = fixtures.setup_reviewed_application(
        api,
        existing_units=[LAKESIDE_UNIT, MIDTOWN_UNIT],
        application_overrides={
            "property_name": "Origin Point Hotel",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 16,
        },
    )
    application = world["application"]
    assert_money(application["base_impact_score"], 62.44, "base_impact_score")
    assert_money(application["final_impact_score"], 62.44, "final_impact_score")
    assert_integer(application["impact_unit_count_final"], 2, "impact_unit_count_final")
    assert application["encroachment_verdict"] == "ENCROACHMENT_CONFIRMED"

    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    refused = api.decide_application(
        world["application_id"],
        factories.build_decision_payload("APPROVE", decision_notes="Approved without a waiver."),
        FDM_DECIDER_HEADERS,
    )
    validate_error(refused, ApiErrorId.ENCROACHMENT_CONFIRMED)
    assert refused.status_code == 409
    assert (
        get_success_data(api.get_application(world["application_id"], FDM_HEADERS))["status"]
        == "UNDER_REVIEW"
    )
    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 1, "open_application_count")

    approved = fixtures.decide_application(
        api, world["application_id"], "APPROVE",
        decision_notes="Approved with an executive waiver.",
        encroachment_waiver_granted=True,
    )
    assert approved["status"] == "APPROVED"
    assert approved["decision_outcome"] == "APPROVE"
    assert approved["encroachment_waiver_granted"] is True

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 0, "open_application_count")
