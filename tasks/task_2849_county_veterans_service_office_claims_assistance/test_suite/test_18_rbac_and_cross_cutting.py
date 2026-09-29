"""
Role boundaries, the two stale-version writes and derived-field freshness.

The role tests always pair every refusal with the one role the PRD does
authorise, so a blanket denial cannot pass for a role boundary.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    STATE_AUDITOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    accept_designation,
    accept_poa_payload,
    accept_report_action,
    approve_application_action,
    assert_caseload_weight,
    assert_combined_rating,
    assert_exact_whole,
    assert_pct_2dp,
    assign_representative_payload,
    benefit_application_payload,
    claim_payload,
    conditions,
    create_active_representative,
    create_claim_in_evidence_development,
    create_decided_claim,
    create_represented_veteran,
    create_screened_veteran,
    create_state_program,
    create_submitted_application,
    create_submitted_report,
    create_verified_veteran,
    create_veteran,
    evidence_item_payload,
    exam_site_payload,
    make_county_officer_headers,
    make_veteran_client_headers,
    offer_designation,
    read_application,
    read_claim,
    read_representative,
    read_state_program,
    read_veteran,
    receive_evidence,
    representative_payload,
    request_evidence,
    revoke_poa_payload,
    set_clock,
    state_program_payload,
    submit_for_peer_review,
    validate_error,
    validate_paginated,
    validate_success,
    veteran_version,
)


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module starts at the logical clock's opening instant."""
    set_clock(api, CLOCK_START_INSTANT)


def _officer(api):
    """One ACTIVE county officer whose accreditation runs well past the clock."""
    return create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )


class TestSystemAdminExclusiveConfigurationIsDeniedToEveryOtherRole:
    """Configuration endpoints name one role, and it is not the office's."""

    @pytest.fixture
    def other_role_headers(self, api):
        """One set of headers for each of the four non-administrative roles."""
        officer = _officer(api)
        veteran = create_veteran(api)
        return [
            INTAKE_CLERK_HEADERS,
            make_county_officer_headers(officer["id"]),
            STATE_AUDITOR_HEADERS,
            make_veteran_client_headers(veteran["id"]),
        ]

    def test_programme_configuration_is_refused_to_the_other_four_roles(
        self, api, other_role_headers
    ):
        """
        "The supplied role appears in the addressed endpoint's authorized-role list, else `ERR_UNAUTHORIZED` (403), on every endpoint."
        "A state program is a `SystemAdmin` configuration for exactly one fiscal year."

        Design: Corner/rbac/corner_system_admin_exclusive_configuration_is_denied_to_every_other_role
        """
        for headers in other_role_headers:
            validate_error(
                api.create_state_program(state_program_payload(), headers),
                "ERR_UNAUTHORIZED",
                403,
            )
        _rows, meta = validate_paginated(api.list_state_programs(SYSTEM_ADMIN_HEADERS))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_the_roster_and_the_site_registry_answer_only_to_the_administrator(
        self, api, other_role_headers
    ):
        """
        "Nobody can act on a veteran's behalf in this system without an entry in the accreditation registry, and the registry is owned exclusively by the `SystemAdmin`."
        "Contract examination facilities are configured by the `SystemAdmin`."

        Design: Corner/rbac/corner_system_admin_exclusive_configuration_is_denied_to_every_other_role
        """
        validate_error(
            api.create_representative(representative_payload(), STATE_AUDITOR_HEADERS),
            "ERR_UNAUTHORIZED",
            403,
        )
        validate_error(
            api.create_exam_site(exam_site_payload(), INTAKE_CLERK_HEADERS),
            "ERR_UNAUTHORIZED",
            403,
        )
        registered = validate_success(
            api.create_representative(representative_payload(), SYSTEM_ADMIN_HEADERS),
            201,
        )
        assert registered["accreditation_status"] == "PENDING"
        site = validate_success(
            api.create_exam_site(exam_site_payload(), SYSTEM_ADMIN_HEADERS), 201
        )
        assert_exact_whole(site["booked_slot_count"], 0, "booked_slot_count")


class TestOnlyTheIntakeClerkMayAssignARepresentative:
    """Assignment is front-desk work and nobody else's."""

    @pytest.fixture
    def screened(self, api):
        """A screened veteran, an officer to assign, and the other three roles."""
        officer = _officer(api)
        built = create_screened_veteran(api, make_county_officer_headers(officer["id"]))
        return {
            "veteran_id": built["veteran"]["id"],
            "officer_id": officer["id"],
            "denied_headers": [
                make_county_officer_headers(officer["id"]),
                SYSTEM_ADMIN_HEADERS,
                STATE_AUDITOR_HEADERS,
                make_veteran_client_headers(built["veteran"]["id"]),
            ],
        }

    def test_the_other_four_roles_are_all_refused(self, api, screened):
        """
        "Assignment is `IntakeClerk` work and drives the veteran from `SCREENED` to `ACTIVE`."

        Design: Corner/rbac/corner_only_the_intake_clerk_may_assign_a_representative
        """
        for headers in screened["denied_headers"]:
            validate_error(
                api.assign_representative(
                    screened["veteran_id"],
                    assign_representative_payload(screened["officer_id"]),
                    headers,
                ),
                "ERR_UNAUTHORIZED",
                403,
            )
        stored = read_veteran(api, screened["veteran_id"])
        assert stored["intake_status"] == "SCREENED"
        assert stored["assigned_representative_id"] is None

    def test_the_front_desk_makes_the_identical_call_succeed(self, api, screened):
        """
        "Either way, a successful assignment sets `assigned_representative_id` and `intake_status` to `ACTIVE` and increments the veteran's `version` by 1."

        Design: Corner/rbac/corner_only_the_intake_clerk_may_assign_a_representative
        """
        before = read_veteran(api, screened["veteran_id"])["version"]
        assigned = validate_success(
            api.assign_representative(
                screened["veteran_id"],
                assign_representative_payload(screened["officer_id"]),
                INTAKE_CLERK_HEADERS,
            ),
            200,
        )
        assert assigned["assigned_representative_id"] == screened["officer_id"]
        assert assigned["intake_status"] == "ACTIVE"
        assert_exact_whole(assigned["version"], before + 1, "version")


class TestCountyOfficerExclusiveClaimWorkIsDeniedToTheIntakeClerk:
    """The front desk opens cases; it does not screen them or work their claims."""

    def test_the_front_desk_may_not_take_an_eligibility_screen(self, api):
        """
        "An eligibility screen is a `CountyOfficer` action that takes no request body at all and produces a new, permanently immutable screen record."

        Design: Corner/rbac/corner_county_officer_exclusive_claim_work_is_denied_to_the_intake_clerk
        """
        officer = _officer(api)
        officer_headers = make_county_officer_headers(officer["id"])
        built = create_verified_veteran(api, officer_headers)
        validate_error(
            api.screen_veteran(built["veteran"]["id"], INTAKE_CLERK_HEADERS),
            "ERR_UNAUTHORIZED",
            403,
        )
        assert read_veteran(api, built["veteran"]["id"])["intake_status"] == (
            "INTAKE_STARTED"
        )
        screened = validate_success(
            api.screen_veteran(built["veteran"]["id"], officer_headers), 201
        )
        assert screened["basic_eligibility"] is True
        assert read_veteran(api, built["veteran"]["id"])["intake_status"] == "SCREENED"

    def test_the_front_desk_may_neither_open_a_claim_nor_request_its_evidence(
        self, api
    ):
        """
        "A claim is opened by a `CountyOfficer` against an already-`ACTIVE` designation."

        Design: Corner/rbac/corner_county_officer_exclusive_claim_work_is_denied_to_the_intake_clerk
        """
        base = create_represented_veteran(api, designee=_officer(api))
        body = claim_payload(
            base["veteran"]["id"],
            base["poa"]["id"],
            claimed_conditions=conditions("tinnitus"),
        )
        validate_error(
            api.create_claim(body, INTAKE_CLERK_HEADERS), "ERR_UNAUTHORIZED", 403
        )
        claim = validate_success(
            api.create_claim(body, base["officer_headers"]), 201
        )
        validate_error(
            api.create_evidence_item(
                claim["id"], evidence_item_payload(), INTAKE_CLERK_HEADERS
            ),
            "ERR_UNAUTHORIZED",
            403,
        )
        assert claim["status"] == "DRAFT"


class TestDeterminationAndReportReviewBelongToTheStateAuditorAlone:
    """The county prepares and certifies; the state decides and accepts."""

    def test_the_award_determination_is_refused_to_the_other_four_roles(self, api):
        """
        "Adjudication belongs to the `StateAuditor` alone."

        Design: Corner/rbac/corner_determination_and_report_review_belong_to_the_state_auditor_alone
        """
        ctx = create_submitted_application(
            api, application_kwargs={"assessed_property_value_cents": 8500000}
        )
        application_id = ctx["application"]["id"]
        for headers in [
            INTAKE_CLERK_HEADERS,
            ctx["officer_headers"],
            SYSTEM_ADMIN_HEADERS,
            ctx["veteran_headers"],
        ]:
            validate_error(
                api.application_determination(
                    application_id, approve_application_action(), headers
                ),
                "ERR_UNAUTHORIZED",
                403,
            )
        assert read_application(api, application_id)["determination_status"] == (
            "SUBMITTED"
        )
        approved = validate_success(
            api.application_determination(
                application_id, approve_application_action(), STATE_AUDITOR_HEADERS
            ),
            200,
        )
        assert approved["determination_status"] == "APPROVED"

    def test_the_quarterly_report_review_is_refused_to_the_certifying_office(self, api):
        """
        "**Accepting** (`ACCEPT`) is `StateAuditor` work available only from `SUBMITTED` and sets `status` to the terminal `ACCEPTED`."

        Design: Corner/rbac/corner_determination_and_report_review_belong_to_the_state_auditor_alone
        """
        officer_headers = make_county_officer_headers(_officer(api)["id"])
        report = create_submitted_report(api, officer_headers)
        for headers in [officer_headers, SYSTEM_ADMIN_HEADERS, INTAKE_CLERK_HEADERS]:
            validate_error(
                api.review_outcome_report(
                    report["id"], accept_report_action(), headers
                ),
                "ERR_UNAUTHORIZED",
                403,
            )
        accepted = validate_success(
            api.review_outcome_report(
                report["id"], accept_report_action(), STATE_AUDITOR_HEADERS
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["certified_by_representative_id"] == officer_headers["X-User-ID"]


class TestVeteranClientMayActOnlyOnTheirOwnDesignation:
    """A veteran-facing endpoint is scoped to the acting veteran's own row."""

    @pytest.fixture
    def two_veterans(self, api):
        """Two screened veterans and one representative offered to the first."""
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(rep["id"])
        owner = create_screened_veteran(api, officer_headers)["veteran"]
        stranger = create_screened_veteran(api, officer_headers)["veteran"]
        return {
            "rep_id": rep["id"],
            "owner_id": owner["id"],
            "stranger_headers": make_veteran_client_headers(stranger["id"]),
            "poa": offer_designation(api, owner["id"], rep["id"]),
        }

    def test_a_stranger_cannot_accept_someone_elses_designation(self, api, two_veterans):
        """
        "A `VeteranClient` acts only on their own rows, else `ERR_ACTOR_NOT_OWNER` (403), on power-of-attorney acceptance, power-of-attorney revocation and decision-review status actions."
        "Only the veteran can accept, and acceptance is the more heavily guarded of the two stale-version writes in the system."

        Design: Corner/rbac/corner_veteran_client_may_act_only_on_their_own_designation
        """
        validate_error(
            api.accept_power_of_attorney(
                two_veterans["poa"]["id"],
                accept_poa_payload(veteran_version(api, two_veterans["owner_id"])),
                two_veterans["stranger_headers"],
            ),
            "ERR_ACTOR_NOT_OWNER",
            403,
        )
        assert validate_success(
            api.get_power_of_attorney(two_veterans["poa"]["id"], INTAKE_CLERK_HEADERS)
        )["status"] == "OFFERED"
        accepted = accept_designation(
            api, two_veterans["poa"]["id"], two_veterans["owner_id"]
        )
        assert accepted["status"] == "ACTIVE"

    def test_a_stranger_cannot_revoke_someone_elses_designation(self, api, two_veterans):
        """
        "A `VeteranClient` revoking their own `ACTIVE` designation triggers the full representation cascade"

        Design: Corner/rbac/corner_veteran_client_may_act_only_on_their_own_designation
        """
        accept_designation(api, two_veterans["poa"]["id"], two_veterans["owner_id"])
        validate_error(
            api.revoke_power_of_attorney(
                two_veterans["poa"]["id"],
                revoke_poa_payload(),
                two_veterans["stranger_headers"],
            ),
            "ERR_ACTOR_NOT_OWNER",
            403,
        )
        assert_exact_whole(
            read_representative(api, two_veterans["rep_id"])["active_poa_count"],
            1,
            "active_poa_count",
        )
        revoked = validate_success(
            api.revoke_power_of_attorney(
                two_veterans["poa"]["id"],
                revoke_poa_payload(),
                make_veteran_client_headers(two_veterans["owner_id"]),
            ),
            200,
        )
        assert revoked["status"] == "REVOKED"
        assert_exact_whole(
            read_representative(api, two_veterans["rep_id"])["active_poa_count"],
            0,
            "active_poa_count",
        )


class TestBothOptimisticConcurrencyRulesRejectASupersededRead:
    """The two guarded writes each refuse a version the client no longer holds."""

    def test_a_designation_acceptance_quoting_a_superseded_veteran_version(self, api):
        """
        "The request must carry `expected_veteran_version`, a non-optional integer field holding the client's last observed `version` of the veteran the designation names."
        "If that value does not equal the veteran's current `version` at the moment of the write, the acceptance is rejected with `ERR_STALE_VETERAN_VERSION` (HTTP 412) and nothing at all is changed."

        Design: Corner/cross-cutting complexity layers/corner_both_optimistic_concurrency_rules_reject_a_superseded_read
        """
        rep = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(rep["id"])
        veteran = create_screened_veteran(api, officer_headers)["veteran"]
        poa = offer_designation(api, veteran["id"], rep["id"])
        observed = veteran_version(api, veteran["id"])
        validate_success(
            api.update_veteran(
                veteran["id"], {"household_income_cents": 9000000}, INTAKE_CLERK_HEADERS
            )
        )
        validate_error(
            api.accept_power_of_attorney(
                poa["id"],
                accept_poa_payload(observed),
                make_veteran_client_headers(veteran["id"]),
            ),
            "ERR_STALE_VETERAN_VERSION",
            412,
        )
        assert validate_success(
            api.get_power_of_attorney(poa["id"], INTAKE_CLERK_HEADERS)
        )["status"] == "OFFERED"
        assert_exact_whole(
            read_representative(api, rep["id"])["active_poa_count"],
            0,
            "active_poa_count",
        )
        accepted = accept_designation(api, poa["id"], veteran["id"])
        assert accepted["status"] == "ACTIVE"
        assert_exact_whole(
            read_representative(api, rep["id"])["active_poa_count"],
            1,
            "active_poa_count",
        )

    def test_an_application_quoting_a_superseded_program_version(self, api):
        """
        "Retuning a program's configuration increments its `version` and therefore invalidates any `expected_program_version` a client captured earlier."
        "If that value does not equal the program's current `version` at the moment of the write, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412) and nothing is created."

        Design: Corner/cross-cutting complexity layers/corner_both_optimistic_concurrency_rules_reject_a_superseded_read
        """
        officer_headers = make_county_officer_headers(_officer(api)["id"])
        veteran = create_screened_veteran(api, officer_headers)["veteran"]
        program = create_state_program(
            api, program_type="PROPERTY_TAX_EXEMPTION", fiscal_year=2026, min_rating_pct=0
        )
        observed = read_state_program(api, program["id"])["version"]
        assert_exact_whole(observed, 1, "version")
        retuned = validate_success(
            api.update_state_program(
                program["id"], {"annual_pool_cents": 300000000}, SYSTEM_ADMIN_HEADERS
            )
        )
        assert_exact_whole(retuned["version"], 2, "version")
        stale_body = benefit_application_payload(
            veteran["id"],
            program["id"],
            2026,
            observed,
            assessed_property_value_cents=8500000,
        )
        validate_error(
            api.create_state_benefit_application(stale_body, INTAKE_CLERK_HEADERS),
            "ERR_STALE_PROGRAM_VERSION",
            412,
        )
        _rows, meta = validate_paginated(
            api.list_state_benefit_applications(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")
        filed = validate_success(
            api.create_state_benefit_application(
                benefit_application_payload(
                    veteran["id"],
                    program["id"],
                    2026,
                    2,
                    assessed_property_value_cents=8500000,
                ),
                INTAKE_CLERK_HEADERS,
            ),
            201,
        )
        assert filed["determination_status"] == "SUBMITTED"


class TestEveryDerivedFieldIsCurrentInTheWritingResponse:
    """No client ever has to poke a row to make its computed fields correct."""

    def test_the_claim_score_is_current_the_moment_an_item_changes_status(self, api):
        """
        "When an evidence item changes status, the parent claim's `evidence_completeness_pct` is recomputed."
        A received nexus letter weighs 25.88 of the 55 points a single-condition
        claim needs, which is 47.05 percent, and adding a 20.00-point service
        treatment record carries the same claim to 83.42 percent.

        Design: Corner/consistency model/corner_every_derived_field_is_current_in_the_writing_response
        """
        preparer = _officer(api)
        ctx = create_claim_in_evidence_development(
            api,
            create_represented_veteran(api, designee=preparer),
            claimed_conditions=conditions("tinnitus"),
        )
        nexus = request_evidence(
            api,
            ctx["claim"]["id"],
            ctx["officer_headers"],
            evidence_type="NEXUS_LETTER",
            provider_name="Dr. Salazar",
            nexus_opinion_strength="AT_LEAST_AS_LIKELY_AS_NOT",
        )
        receive_evidence(api, nexus["id"], ctx["officer_headers"])
        assert_pct_2dp(
            read_claim(api, ctx["claim"]["id"])["evidence_completeness_pct"], 47.05
        )
        record = request_evidence(
            api,
            ctx["claim"]["id"],
            ctx["officer_headers"],
            evidence_type="SERVICE_TREATMENT_RECORD",
            provider_name="National Personnel Records Center",
        )
        receive_evidence(api, record["id"], ctx["officer_headers"])
        assert_pct_2dp(
            read_claim(api, ctx["claim"]["id"])["evidence_completeness_pct"], 83.42
        )

    def test_the_workload_number_is_current_the_moment_a_claim_changes_status(self, api):
        """
        "When a claim changes status, the preparing representative's `caseload_weight` is recomputed before the response is written."
        One `ACTIVE` designation weighs 1 point, so the preparer who is also the
        designee weighs 4 points while the claim develops evidence and 6 once it
        sits in peer review.

        Design: Corner/consistency model/corner_every_derived_field_is_current_in_the_writing_response
        """
        preparer = _officer(api)
        reviewer = create_active_representative(
            api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
        )
        ctx = create_claim_in_evidence_development(
            api,
            create_represented_veteran(api, designee=preparer),
            claimed_conditions=conditions("tinnitus"),
        )
        assert_caseload_weight(
            read_representative(api, preparer["id"])["caseload_weight"], 4
        )
        submitted = submit_for_peer_review(
            api, ctx["claim"]["id"], reviewer["id"], ctx["officer_headers"]
        )
        assert submitted["status"] == "PEER_REVIEW"
        assert_caseload_weight(
            read_representative(api, preparer["id"])["caseload_weight"], 6
        )

    def test_the_rating_and_the_band_are_current_the_moment_a_decision_lands(self, api):
        """
        "When a decision is recorded, the veteran's `combined_rating_pct` and `priority_group` are recomputed."
        "A client never has to poke a resource to make its derived fields correct."

        Design: Corner/consistency model/corner_every_derived_field_is_current_in_the_writing_response
        """
        ctx = create_decided_claim(api, awarded_rating_pct=30)
        assert ctx["claim"]["status"] == "DECIDED"
        assert_combined_rating(ctx["veteran"]["combined_rating_pct"], 30)
        assert ctx["veteran"]["priority_group"] == "P2"
        assert read_veteran(api, ctx["veteran"]["id"])["priority_group"] == "P2"
