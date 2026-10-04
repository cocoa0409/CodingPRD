"""Creation defaults, terminal-state lockdowns, required-field gates and the RBAC matrix."""
import pytest

from test_helpers import (
    ADMIN,
    CARE_ADVOCATE_FALLBACK,
    CLAIMS,
    CLAIMS_REVIEW,
    NETWORK,
    PHARMACIST,
    REVIEWER_2_ID,
    TEST_DEFAULTS,
    api_client,
    assert_bundle_entitlement,
    assert_employer_account,
    assert_member,
    assert_pathway_request,
    approve_preauthorization,
    create_bundle_entitlement_payload,
    create_claim_payload,
    create_clinic,
    create_clinic_contract_payload,
    create_contract,
    create_cycle,
    create_employer,
    create_employer_account_payload,
    create_member,
    create_member_payload,
    create_medication_order_payload,
    create_pathway_request_payload,
    create_plan,
    create_preauthorization,
    create_surrender_route_payload,
    drive_cycle_to_outcome_recorded,
    drive_cycle_to_transfer,
    make_care_advocate_headers,
    make_member_headers,
    select_clinic_for_plan,
    setup_advocate_and_member,
    setup_approved_authorization,
    setup_clock,
    setup_contracted_clinic,
    setup_employer_bundle,
    setup_member_plan_clinic,
    setup_member_with_plan,
    setup_recorded_outcome_cycle,
    setup_surrender_route,
    tick_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmployerAccountCreation:
    """A new sponsoring account comes back with server-minted fields and ACTIVE status."""

    def test_created_account_carries_every_declared_field(self):
        """PRD §3.1: "A newly registered account begins with `account_status` `ACTIVE`,
        `active_member_count` of zero, and `entitlement_count` of zero, and both counters
        are recomputed whenever the population it sponsors changes"
        PRD §2.5: "The `created_at` is an ISO 8601 UTC instant with three fractional
        digits, set when the row is first written and never changed."

        Design: Corner/entities/employer_account_create_returns_every_declared_field_and_starts_active
        """
        setup_clock()
        created = validate_success(api_client.create_employer_account(
            create_employer_account_payload(employer_name="Base Employer"), ADMIN), 201)

        assert_employer_account(created)
        assert created["employer_name"] == "Base Employer"
        assert created["plan_year"] == 2026
        assert created["funding_type"] == "SELF_FUNDED"
        assert created["allocation_method"] == "CONCURRENT_BUNDLE"
        assert created["account_status"] == "ACTIVE"
        assert created["active_member_count"] == 0
        assert created["entitlement_count"] == 0
        assert created["version"] >= 1

        read_back = validate_success(
            api_client.get_employer_account(created["id"], ADMIN), 200)
        assert read_back["id"] == created["id"]
        assert read_back["created_at"] == created["created_at"]

    def test_counters_track_the_population_and_the_entitlements(self):
        """PRD §3.1: "`active_member_count` tracks members whose `member_status` is
        `INTAKE`, `CARE_ACTIVE`, or `CARE_COMPLETE`, and `entitlement_count` tracks
        entitlements whose `bundle_status` is `ACTIVE` or `EXHAUSTED`."

        Design: Corner/entities/employer_account_create_returns_every_declared_field_and_starts_active
        """
        employer, bundle = setup_employer_bundle()
        advocate, member = setup_advocate_and_member(employer)

        after = validate_success(api_client.get_employer_account(employer["id"], ADMIN), 200)
        assert after["active_member_count"] == 1, "a CARE_ACTIVE member counts"
        assert after["entitlement_count"] == 1, "an ACTIVE entitlement counts"
        assert after["version"] > employer["version"]


class TestMemberRequiredFields:
    """A missing required input is a body-integrity refusal, not a foreign-key miss."""

    def test_member_without_required_track_returns_invalid_request(self):
        """PRD §2.9: "a missing required input, a value outside its declared enumeration,
        or an interval whose end precedes its start is refused outright with
        `ERR_INVALID_REQUEST` and a 400 status"

        Design: Corner/entities/member_create_missing_required_track_returns_invalid_request
        """
        setup_clock()
        employer = create_employer()
        payload = create_member_payload(employer["id"], external_ref="OMIT-1")
        del payload["required_track"]

        response = api_client.create_member(payload, CARE_ADVOCATE_FALLBACK)

        assert response.status_code == 400
        assert response.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"
        rows = validate_success(
            api_client.list_members(NETWORK, {"employer_account_id": employer["id"]}), 200)
        assert rows == []

    def test_member_with_unknown_employer_account_returns_generic_not_found(self):
        """PRD §2.9: "A foreign key supplied in a request body that does not resolve is a
        different matter: it is refused with the generic `ERR_NOT_FOUND` and a 404 status."

        Design: Corner/entities/member_create_missing_required_track_returns_invalid_request
        """
        setup_clock()
        payload = create_member_payload(
            "00000000-0000-4000-8000-000000000099", external_ref="ORPHAN-1")

        response = api_client.create_member(payload, CARE_ADVOCATE_FALLBACK)

        assert response.status_code == 404
        assert response.json()["data"]["error_id"] == "ERR_NOT_FOUND", (
            "a body foreign-key miss carries the generic identifier"
        )


class TestBundleEntitlementCreation:
    """A fresh grant is inert until it is deliberately activated."""

    def test_draft_grant_reports_zero_counters_and_annual_capped_allowance_after_activation(self):
        """PRD §3.1: "A fresh grant is stored with `bundle_status` `DRAFT` and every
        counter at zero: `cycles_consumed`, `cycles_committed`, `cycles_remaining`,
        `pharmacy_consumed_cents`, and `pharmacy_remaining_cents` all begin empty so that
        a design cannot be consumed before it has been deliberately opened."
        PRD §2.4: "Every entitlement maintains three derived counters that the client
        never sets and always reads back"

        Design: Corner/entities/bundle_entitlement_create_initializes_counters_and_starts_draft
        """
        setup_clock()
        employer = create_employer()

        created = validate_success(api_client.create_bundle_entitlement(
            create_bundle_entitlement_payload(
                employer["id"], bundle_type="DIAGNOSTIC_IUI", lifetime_max_cycles=6,
                max_cycles_per_year=3, max_transfers_per_cycle=1,
                pharmacy_pool_cents=250000, copay_max=True),
            ADMIN), 201)

        assert_bundle_entitlement(created)
        assert created["bundle_status"] == "DRAFT"
        assert created["cycles_remaining"] == 0
        assert created["cycles_consumed"] == 0
        assert created["cycles_committed"] == 0
        assert created["pharmacy_remaining_cents"] == 0
        assert created["pharmacy_consumed_cents"] == 0

        activated = validate_success(
            api_client.activate_bundle_entitlement(created["id"], ADMIN), 200)
        assert activated["bundle_status"] == "ACTIVE"
        assert activated["cycles_remaining"] == 3, (
            "the annual slice binds over the six-cycle lifetime allowance"
        )
        assert activated["pharmacy_remaining_cents"] == 250000

        account = validate_success(api_client.get_employer_account(employer["id"], ADMIN), 200)
        assert account["entitlement_count"] == 1


class TestClinicNotFound:
    """A path-segment miss carries the entity-specific identifier."""

    def test_clinic_read_with_an_unallocated_id_returns_clinic_not_found(self):
        """PRD §2.9: "The first identifier that does not resolve to an existing row
        determines the refusal, and the refusal carries the entity-specific identifier for
        that segment rather than a generic one"

        Design: Corner/entities/clinic_get_with_unknown_id_returns_clinic_not_found
        """
        setup_clock()

        response = api_client.get_clinic("00000000-0000-4000-8000-000000000099", NETWORK)

        assert response.status_code == 404
        body = response.json()
        assert body["data"]["error_id"] == "ERR_CLINIC_NOT_FOUND"
        assert body["data"]["error_id"] != "ERR_NOT_FOUND", (
            "the path-segment miss is entity-specific"
        )
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)


class TestClinicEnumConstraints:
    """Closed enumerations are enforced at the request boundary."""

    def test_clinic_with_out_of_enum_network_tier_returns_invalid_request(self):
        """PRD §3.3: "The `network_tier` is one of `PREFERRED`, `STANDARD`, or
        `OUT_OF_NETWORK`."
        PRD §2.9: "every required input present and inside its declared enumeration"

        Design: Corner/entities/clinic_create_out_of_enum_network_tier_returns_invalid_request
        """
        setup_clock()

        response = api_client.create_clinic(
            {"legal_name": "Bad Tier Clinic", "npi": "2000000099", "state_code": "TX",
             "network_tier": "TIER_ZERO", "min_live_birth_rate_bps": 0,
             "max_multiple_birth_rate_bps": 10000, "required_quality_report_count": 0,
             "maturity_report_threshold": 2, "bundles_offered": ["IVF_RETRIEVAL_TRANSFER"]},
            NETWORK)

        assert response.status_code == 400
        assert response.json()["data"]["error_id"] == "ERR_INVALID_REQUEST"
        rows = validate_success(api_client.list_clinics(NETWORK), 200)
        assert rows == [], "the rejected clinic was not persisted"


class TestComputedFieldsIgnoreClientInput:
    """Derived readings are the server's to compute."""

    def test_client_supplied_quality_readings_are_ignored(self):
        """PRD §2.4: "Every entitlement maintains three derived counters that the client
        never sets and always reads back"
        PRD §3.3: "A newly registered clinic reads `clinic_status` `IN_REVIEW`, with its
        two rate readings, its composite quality score, and its `cycles_reported` all at
        zero."

        Design: Corner/entities/clinic_quality_readings_computed_with_client_values_ignored_input
        """
        setup_clock()

        created = validate_success(api_client.create_clinic(
            {"legal_name": "Computed Field Clinic", "npi": "2000000002", "state_code": "TX",
             "network_tier": "STANDARD", "min_live_birth_rate_bps": 0,
             "max_multiple_birth_rate_bps": 10000, "required_quality_report_count": 0,
             "maturity_report_threshold": 2, "bundles_offered": ["IVF_RETRIEVAL_TRANSFER"],
             "live_birth_rate_bps": 9999, "composite_quality_bps": 12345},
            NETWORK), 201)

        assert created["live_birth_rate_bps"] == 0, "the client's 9999 is ignored"
        assert created["multiple_birth_rate_bps"] == 0
        assert created["composite_quality_bps"] == 0, (
            "no maturity bonus applies to an empty workset"
        )
        assert created["cycles_reported"] == 0
        assert created["clinic_status"] == "IN_REVIEW"


class TestMemberListingFilters:
    """The member collection carries independent foreign-key filters and pagination."""

    def test_member_list_filters_by_advocate_clinic_state_and_paginates(self):
        """PRD §2.3: "Collection reads accept `limit` and `offset` as query parameters.
        `limit` caps the number of rows returned and defaults to 10"
        PRD §2.3: "`total_count` is the number of rows matching the filters before
        pagination and `has_more` reports whether further rows remain beyond the current
        window."

        Design: Corner/entities/members_list_filters_by_care_advocate_and_clinic_with_pagination
        """
        scenario = setup_member_plan_clinic()
        employer = scenario["employer"]
        advocate = scenario["advocate"]
        clinic = scenario["clinic"]

        second = validate_success(api_client.create_member(
            create_member_payload(employer["id"], external_ref="BASE-2",
                                  full_name="Unassigned Member", state_code="CA",
                                  required_track="DIAGNOSTIC_IUI"),
            CARE_ADVOCATE_FALLBACK), 201)

        data, meta = validate_paginated(api_client.list_members(
            NETWORK, {"care_advocate_id": advocate["id"], "limit": 1, "offset": 0}))
        assert len(data) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

        data, meta = validate_paginated(api_client.list_members(
            NETWORK, {"employer_account_id": employer["id"]}))
        assert len(data) == 2
        assert meta["total_count"] == 2

        data, meta = validate_paginated(api_client.list_members(
            NETWORK, {"employer_account_id": employer["id"], "limit": 1, "offset": 1}))
        assert len(data) == 1
        assert meta["total_count"] == 2

        data, meta = validate_paginated(api_client.list_members(
            NETWORK, {"clinic_id": clinic["id"]}))
        assert len(data) == 1, "only the member whose clinic of record was set"

        data, meta = validate_paginated(api_client.list_members(NETWORK, {"state_code": "CA"}))
        assert len(data) == 1
        assert data[0]["id"] == second["id"]

        data, meta = validate_paginated(api_client.list_members(NETWORK, {}))
        assert len(data) == 2
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        fresh = validate_success(api_client.get_member(second["id"], NETWORK), 200)
        assert fresh["care_advocate_id"] is None
        assert fresh["member_status"] == "INTAKE"
        assert_member(fresh)


class TestBodyForeignKeyOnPlanCreation:
    """A body foreign key miss on the plan route carries the generic identifier."""

    def test_plan_with_unknown_bundle_entitlement_returns_generic_not_found(self):
        """PRD §2.9: "A foreign key supplied in a request body that does not resolve is a
        different matter: it is refused with the generic `ERR_NOT_FOUND` and a 404 status."

        Design: Corner/entities/treatment_plan_create_rejects_unknown_bundle_entitlement
        """
        employer, bundle = setup_employer_bundle()
        advocate, member = setup_advocate_and_member(employer)

        response = api_client.create_treatment_plan(
            {"member_id": member["id"],
             "bundle_entitlement_id": "00000000-0000-4000-8000-000000000076",
             "pathway_type": "STANDARD_IVF", "planned_cycles": 1},
            make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 404
        assert response.json()["data"]["error_id"] == "ERR_NOT_FOUND"
        assert response.json()["data"]["error_id"] != "ERR_BUNDLE_NOT_FOUND"
        rows = validate_success(
            api_client.list_treatment_plans(NETWORK, {"member_id": member["id"]}), 200)
        assert rows == []


class TestMemberInitialStateLockdown:
    """A member cannot skip the intake hop."""

    def test_complete_care_from_intake_returns_invalid_state(self):
        """PRD §3.2: "A member may be closed only when they are `CARE_ACTIVE` and when
        nothing is still running underneath them"
        PRD §3.2: "A new member starts life in `INTAKE`, with `care_advocate_id` empty,
        `clinic_id` empty, `pathway_selected` reading `NONE`, `completed_cycles` and
        `live_births_recorded` at zero, and `intake_completed_at` unset."

        Design: Corner/state_machines/member_created_in_intake_and_cannot_complete_care_from_intake
        """
        setup_clock()
        employer = create_employer()
        advocate = create_advocate_helpers()
        member = validate_success(api_client.create_member(
            create_member_payload(employer["id"]), CARE_ADVOCATE_FALLBACK), 201)

        assert member["member_status"] == "INTAKE"
        assert member["intake_completed_at"] is None
        assert member["care_advocate_id"] is None
        assert member["version"] == 1

        response = api_client.complete_care(
            member["id"], make_care_advocate_headers(advocate["id"]))

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        unchanged = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        assert unchanged["member_status"] == "INTAKE"


def create_advocate_helpers():
    from test_helpers import create_advocate
    return create_advocate()


class TestCycleTerminalStateLockdown:
    """OUTCOME_RECORDED is terminal for a cycle."""

    def test_terminal_cycle_refuses_cancel_and_forward_hops(self):
        """PRD §3.6: "A cycle in `OUTCOME_PENDING` or already `OUTCOME_RECORDED` cannot be
        cancelled; the route back from a recorded outcome runs through a claim reversal"
        PRD §3.6: "each step performed by a `ClinicCoordinator` and each refused with
        `ERR_INVALID_STATE` when the cycle is not in the state that step departs from."

        Design: Corner/state_machines/treatment_cycle_revert_from_terminal_outcome_recorded_returns_invalid_state
        """
        scenario = setup_recorded_outcome_cycle()
        cycle = scenario["cycle"]
        clinic = scenario["clinic"]
        headers = make_clinic_coordinator_helpers(clinic["id"])

        recorded = validate_success(api_client.get_treatment_cycle(cycle["id"], NETWORK), 200)
        assert recorded["cycle_status"] == "OUTCOME_RECORDED"
        assert recorded["consumption_marker"] == "CONSUMED"
        version_before = recorded["version"]

        cancel = api_client.cancel_cycle(cycle["id"], headers)
        assert cancel.status_code == 409
        assert cancel.json()["data"]["error_id"] == "ERR_INVALID_STATE"

        restart = api_client.start_stimulation(cycle["id"], headers)
        assert restart.status_code == 409
        assert restart.json()["data"]["error_id"] == "ERR_INVALID_STATE"

        unchanged = validate_success(api_client.get_treatment_cycle(cycle["id"], NETWORK), 200)
        assert unchanged["consumption_marker"] == "CONSUMED", (
            "a failed cancel does not release the cycle's slot"
        )
        assert unchanged["version"] == version_before

        bundle = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)
        assert bundle["cycles_consumed"] == 1
        assert bundle["cycles_remaining"] == TEST_DEFAULTS["LIFETIME_MAX_CYCLES"] - 1


def make_clinic_coordinator_helpers(clinic_id: str):
    from test_helpers import make_clinic_coordinator_headers
    return make_clinic_coordinator_headers(clinic_id)


class TestPathwayRequestPreconditions:
    """Pathway review begins only once the consent record is complete."""

    def test_begin_review_without_consent_returns_invalid_state(self):
        """PRD §3.8: "Clinical review of a pathway request begins only when the consent
        record is complete: the request must be in `DRAFT`, `consent_signed` must be true,
        and `consent_signed_on` must be set; a request whose consent is incomplete cannot
        be moved into review at all."

        Design: Corner/state_machines/pathway_request_begin_review_without_consent_returns_invalid_state
        """
        employer, bundle = setup_employer_bundle()
        advocate, member = setup_advocate_and_member(employer)
        request = validate_success(api_client.create_pathway_request(
            create_pathway_request_payload(
                member["id"], pathway_type="PRESERVATION", consent_signed=False,
                consent_signed_on=None, coverage_pct=80),
            make_care_advocate_headers(advocate["id"])), 201)

        assert request["pathway_status"] == "DRAFT"
        assert request["consent_signed"] is False
        assert request["pathway_cost_cents"] == 0

        response = api_client.begin_pathway_review(
            request["id"], maken_url_reviewer())

        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        unchanged = validate_success(api_client.get_pathway_request(request["id"], NETWORK), 200)
        assert unchanged["pathway_status"] == "DRAFT"
        member_now = validate_success(api_client.get_member(member["id"], NETWORK), 200)
        assert member_now["pathway_selected"] == "NONE"

        withdrawn = validate_success(api_client.withdraw_pathway_request(
            request["id"], make_care_advocate_headers(advocate["id"])), 200)
        assert withdrawn["pathway_status"] == "WITHDRAWN"


def maken_url_reviewer():
    from test_helpers import make_clinical_reviewer_headers
    return make_clinical_reviewer_headers("rev-consent")


class TestPathwaySpecificReferences:
    """The pathway-specific references are required on disjoint enumeration members."""

    def test_surrogacy_without_carrier_and_donor_without_agency_are_distinct_errors(self):
        """PRD §3.8: "`gestational_carrier_ref` for a surrogacy request, and
        `donor_agency_ref` for a donor-egg or donor-sperm request. Supplying a carrier
        reference on a donor request, or an agency reference on a surrogacy request, has no
        effect; omitting the reference its own pathway demands is refused, with
        `ERR_SURROGACY_CARRIER_REQUIRED` for surrogacy and `ERR_DONOR_AGENCY_REQUIRED` for
        the donor pathways."

        Design: Corner/state_machines/surrogacy_pathway_without_carrier_ref_returns_surrogacy_carrier_required
        """
        employer, bundle = setup_employer_bundle()
        advocate, member = setup_advocate_and_member(employer)
        headers = make_care_advocate_headers(advocate["id"])

        # Each pathway is filed without the reference its own enumeration member
        # demands; the omission is what the filing refuses.
        surrogacy = api_client.create_pathway_request(
            create_pathway_request_payload(
                member["id"], pathway_type="SURROGACY", consent_signed=True,
                consent_signed_on="2026-08-20T00:00:00Z", coverage_pct=50),
            headers)
        donor = api_client.create_pathway_request(
            create_pathway_request_payload(
                member["id"], pathway_type="DONOR_EGG", consent_signed=True,
                consent_signed_on="2026-08-20T00:00:00Z", coverage_pct=50),
            headers)

        sur_response = surrogacy
        don_response = donor

        assert sur_response.status_code == 400
        assert sur_response.json()["data"]["error_id"] == "ERR_SURROGACY_CARRIER_REQUIRED"
        assert don_response.status_code == 400
        assert don_response.json()["data"]["error_id"] == "ERR_DONOR_AGENCY_REQUIRED"
        assert sur_response.json()["data"]["error_id"] != don_response.json()["data"]["error_id"]


class TestClinicTerminalStateLockdown:
    """TERMINATED is terminal for a clinic."""

    def test_second_terminate_returns_invalid_state(self):
        """PRD §3.4: "Terminating the clinic is available only from `SUSPENDED`, moves the
        clinic to `TERMINATED`, and is terminal: no contract and no plan may reference the
        clinic afterwards."

        Design: Corner/state_machines/clinic_terminate_twice_returns_invalid_state_on_the_second_attempt
        """
        setup_clock()
        clinic, contract = setup_contracted_clinic()

        suspended = validate_success(api_client.suspend_clinic(clinic["id"], NETWORK), 200)
        assert suspended["clinic_status"] == "SUSPENDED"
        terminated = validate_success(api_client.terminate_clinic(clinic["id"], NETWORK), 200)
        assert terminated["clinic_status"] == "TERMINATED"

        contract_after = validate_success(api_client.get_clinic_contract(contract["id"], NETWORK), 200)
        assert contract_after["contracting_status"] == "TERMINATED"

        second = api_client.terminate_clinic(clinic["id"], NETWORK)
        assert second.status_code == 409
        assert second.json()["data"]["error_id"] == "ERR_INVALID_STATE"

        active = validate_success(api_client.list_clinic_contracts(
            NETWORK, {"clinic_id": clinic["id"], "contracting_status": "ACTIVE"}), 200)
        assert active == []


class TestClaimReviewerCannotAdjudicate:
    """ClaimsReviewer owns only the appeal decision."""

    def test_claims_reviewer_adjudicate_is_unauthorized(self):
        """PRD §5: "`ERR_UNAUTHORIZED` | 403 Forbidden"
        PRD §2.1: "A request whose role is not permitted for the requested operation is
        refused with `ERR_UNAUTHORIZED` and a 403 status."

        Design: Corner/rbac/claims_reviewer_cannot_adjudicate_returns_unauthorized
        """
        scenario = setup_claim_for_rbac()
        claim = scenario["claim"]

        refused = api_client.adjudicate_claim(claim["id"], CLAIMS_REVIEW)
        assert refused.status_code == 403
        assert refused.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        allowed = validate_success(api_client.adjudicate_claim(claim["id"], CLAIMS), 200)
        assert allowed["claim_status"] == "ADJUDICATED"


def setup_claim_for_rbac() -> dict:
    scenario = setup_approved_authorization()
    claim = validate_success(api_client.create_claim(
        create_claim_payload(scenario["member"]["id"], scenario["preauthorization"]["id"],
                             service_category="CLINIC_BUNDLE", billed_cents=1450000),
        CLAIMS), 201)
    scenario["claim"] = claim
    return scenario


class TestMemberOwnership:
    """Member is entity-backed, so a member may read only their own records."""

    def test_another_member_cannot_read_the_claim(self):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
        acting `Member`; ownership checks on any resource that references a `Member`
        compare the resource's member foreign-key field to `X-User-ID`, so a member may
        read only their own records."

        Design: Corner/rbac/member_cannot_read_another_members_claim_returns_unauthorized
        """
        scenario = setup_claim_for_rbac()
        employer = scenario["employer"]
        claim = scenario["claim"]
        owner = scenario["member"]

        other = validate_success(api_client.create_member(
            create_member_payload(employer["id"], external_ref="BASE-3",
                                  full_name="Other Member"),
            CARE_ADVOCATE_FALLBACK), 201)

        foreign = api_client.get_claim(claim["id"], make_member_headers(other["id"]))
        assert foreign.status_code == 403
        assert foreign.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        own = validate_success(
            api_client.get_claim(claim["id"], make_member_headers(owner["id"])), 200)
        assert own["member_id"] == owner["id"]
        assert own["member_cost_share_cents"] >= 0

        own_claims, meta = validate_paginated(api_client.list_claims(
            NETWORK, {"member_id": other["id"]}))
        assert meta["total_count"] == 0


class TestMemberIsReadOnly:
    """Member holds no write operation at all."""

    def test_member_cannot_create_a_plan_or_select_a_clinic(self):
        """PRD §2.1: "A request whose role is not permitted for the requested operation is
        refused with `ERR_UNAUTHORIZED` and a 403 status."
        PRD §2.9: "header presence and role validity first; then authorization of the role
        for this operation"

        Design: Corner/rbac/member_cannot_create_a_treatment_plan_returns_unauthorized
        """
        employer, bundle = setup_employer_bundle()
        advocate, member = setup_advocate_and_member(employer)
        headers = make_member_headers(member["id"])

        plan_response = api_client.create_treatment_plan(
            {"member_id": member["id"], "bundle_entitlement_id": bundle["id"],
             "pathway_type": "STANDARD_IVF", "planned_cycles": 1},
            headers)
        assert plan_response.status_code == 403
        assert plan_response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        clinic_response = api_client.select_member_clinic(
            member["id"], {"clinic_id": "00000000-0000-4000-8000-000000000001"}, headers)
        assert clinic_response.status_code == 403
        assert clinic_response.json()["data"]["error_id"] == "ERR_UNAUTHORIZED"

        rows = validate_success(
            api_client.list_treatment_plans(NETWORK, {"member_id": member["id"]}), 200)
        assert rows == []
        readable = validate_success(api_client.get_member(member["id"], headers), 200)
        assert readable["member_status"] == "CARE_ACTIVE"


class TestAuthenticationBeforeAuthorization:
    """An unknown capacity is not the same failure as a missing header."""

    def test_unrecognized_role_is_refused_and_a_conforming_role_reaches_existence(self):
        """PRD §2.1: "Callers authenticate by presenting two headers on every request:
        `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which names
        the capacity in which that principal is acting."

        Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
        """
        setup_clock()
        employer = create_employer()
        advocate = create_advocate_helpers()
        member = create_member(employer["id"], advocate=advocate)

        unknown_role = api_client.get_member(
            member["id"], {"X-User-ID": "someone", "X-User-Role": "Physician"})
        assert unknown_role.status_code == 401
        assert unknown_role.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"

        conforming = api_client.get_member(
            member["id"], make_care_advocate_headers(advocate["id"]))
        assert conforming.status_code == 200
        assert validate_success(conforming, 200)["id"] == member["id"]