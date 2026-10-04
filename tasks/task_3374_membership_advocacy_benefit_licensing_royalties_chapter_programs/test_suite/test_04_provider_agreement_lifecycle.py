"""Provider onboarding, license-agreement lifecycle, role split on the
transitions endpoint, ownership, and the provider OCC rule."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_provider_payload, create_license_agreement_payload,
    set_clock, create_licensed_provider, get_provider,
    create_draft_agreement, create_active_agreement,
    setup_provider_with_active_agreement, get_agreement,
    make_provider_manager_headers,
)

GOV = TEST_USERS["governance_officer_headers"]
OVA = TEST_USERS["oversight_analyst_headers"]
MSA = TEST_USERS["member_services_headers"]


class TestProviderCreatedAsApplicant:
    def test_provider_created_as_applicant(self, api):
        """PRD §3.3: "A `GovernanceOfficer` registers a provider with its
        `legal_name`; the provider begins life as an `APPLICANT` with a
        `royalty_balance_cents` of 0."

        Design: Corner/entities/provider_created_as_applicant
        """
        set_clock()
        resp = api.create_provider(
            create_provider_payload(legal_name="Summit Insurance Group"), GOV)
        provider = validate_success(resp, expected_status=201)
        assert provider["status"] == "APPLICANT"
        assert provider["royalty_balance_cents"] == 0
        assert provider["escalations_trailing_12mo"] == 0
        assert provider["version"] == 1
        assert provider["id"]
        assert provider["created_at"]
        assert provider["updated_at"]


class TestAdmitAuthorization:
    def test_provider_admit_forbidden_for_member_services(self, api):
        """PRD §2.1: "Beyond authentication, every endpoint restricts which
        roles may call it, and certain action endpoints further restrict
        which role may supply which action; a caller whose role is not
        entitled to the endpoint or the requested action is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §4: `POST /api/providers/{id}/admit`
        — "Admit or re-admit a provider" — lists only GovernanceOfficer.

        Design: Corner/validations/provider_admit_forbidden_for_member_services
        """
        set_clock()
        provider = validate_success(
            api.create_provider(
                create_provider_payload(legal_name="Plainview Insurance"), GOV),
            expected_status=201)
        resp = api.admit_provider(provider["id"], MSA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_provider(provider["id"])
        assert after["status"] == "APPLICANT"
        assert after["version"] == 1


class TestAgreementActivationRequiresLicensedProvider:
    def test_agreement_create_rejected_while_provider_applicant(self, api):
        """PRD §3.3: "The provider must be `LICENSED` — drafting against an
        `APPLICANT` or `SUSPENDED` provider is rejected with
        `ERR_PROVIDER_NOT_LICENSED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_provider_licensed
        """
        set_clock()
        provider = validate_success(
            api.create_provider(
                create_provider_payload(legal_name="Cascade Home Warranty"), GOV),
            expected_status=201)
        assert provider["status"] == "APPLICANT"
        payload = create_license_agreement_payload(
            provider["version"], product_category="HOME_SERVICES")
        resp = api.create_license_agreement(
            provider["id"], payload, make_provider_manager_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_LICENSED)

    def test_agreement_create_succeeds_after_admission(self, api):
        """PRD §3.3: "Admission by a `GovernanceOfficer` moves the provider
        `APPLICANT` → `LICENSED`, incrementing the provider's `version` by
        one." PRD §3.3: "A successful draft is created in `DRAFT` status with
        `probation_count`, `recognized_royalty_cents`, and
        `provisional_outstanding_cents` all at 0, records its `provider_id`,
        and — because drafting is a provider mutation — increments the
        provider's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/agreement_activation_requires_provider_licensed
        """
        set_clock()
        provider = validate_success(
            api.create_provider(
                create_provider_payload(legal_name="Cascade Home Warranty"), GOV),
            expected_status=201)
        # Failed attempt while APPLICANT mutates nothing.
        resp = api.create_license_agreement(
            provider["id"],
            create_license_agreement_payload(
                provider["version"], product_category="HOME_SERVICES"),
            make_provider_manager_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_LICENSED)

        admitted = validate_success(api.admit_provider(provider["id"], GOV))
        assert admitted["status"] == "LICENSED"
        assert admitted["version"] == 2

        agreement = validate_success(
            api.create_license_agreement(
                provider["id"],
                create_license_agreement_payload(
                    admitted["version"], product_category="HOME_SERVICES"),
                make_provider_manager_headers(provider["id"])),
            expected_status=201)
        assert agreement["status"] == "DRAFT"
        assert get_provider(provider["id"])["version"] == 3


class TestAgreementProbationReinstateCycle:
    def _setup_active_travel_agreement(self):
        provider, agreement = setup_provider_with_active_agreement(
            "TRAVEL_SERVICES", "Voyager Travel Services Inc")
        assert agreement["version"] == 2
        return provider, agreement

    def test_probate_moves_active_to_probation_and_ratchets_count(self, api):
        """PRD §3.3: "Probation (`PROBATE`, `OversightAnalyst` only) moves
        `ACTIVE` → `PROBATION` with no preconditions beyond the state itself,
        incrementing `probation_count` by one."

        Design: Difficulty/non_linear_state_machine/agreement_probation_reinstate_cycle
        """
        set_clock()
        _provider, agreement = self._setup_active_travel_agreement()
        probated = validate_success(
            api.transition_agreement(agreement["id"], {"action": "PROBATE"}, OVA))
        assert probated["status"] == "PROBATION"
        assert probated["probation_count"] == 1
        assert probated["version"] == 3

    def test_reinstate_closes_cycle_without_resetting_count(self, api):
        """PRD §3.3: "Reinstatement (`REINSTATE`, `OversightAnalyst` only)
        moves `PROBATION` → `ACTIVE` and requires both a `LICENSED` provider
        (`ERR_PROVIDER_NOT_LICENSED` otherwise) and an agreement
        `escalations_trailing_12mo` below 3". PRD §3.3: "Every successful
        transition increments the agreement's `version` by one and refreshes
        its `updated_at`."

        Design: Difficulty/non_linear_state_machine/agreement_probation_reinstate_cycle
        """
        set_clock()
        _provider, agreement = self._setup_active_travel_agreement()
        probated = validate_success(
            api.transition_agreement(agreement["id"], {"action": "PROBATE"}, OVA))
        assert probated["probation_count"] == 1
        set_clock("2027-10-01T00:00:00Z")
        reinstated = validate_success(
            api.transition_agreement(agreement["id"], {"action": "REINSTATE"}, OVA))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["probation_count"] == 1
        assert reinstated["version"] == 4


class TestInvalidAgreementTransitions:
    def test_activate_action_from_probation_rejected(self, api):
        """PRD §3.3: "Every other combination — activating from `PROBATION`,
        reinstating from `ACTIVE`, probating from `DRAFT`, or any action at
        all from `TERMINATED` — is rejected with `ERR_AGREEMENT_STATE`
        (HTTP 409), as is any of these actions offered by the wrong role
        producing `ERR_FORBIDDEN` instead."

        Design: Corner/state_machines/activate_action_from_probation_rejected
        """
        set_clock()
        _provider, agreement = setup_provider_with_active_agreement(
            "INSURANCE_AUTO", "Blue River Insurance")
        probated = validate_success(
            api.transition_agreement(agreement["id"], {"action": "PROBATE"}, OVA))
        assert probated["status"] == "PROBATION"

        resp = api.transition_agreement(agreement["id"], {"action": "ACTIVATE"}, GOV)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_STATE)
        after = get_agreement(agreement["id"])
        assert after["status"] == "PROBATION"
        assert after["probation_count"] == 1

    def test_activate_outside_window_rejected(self, api):
        """PRD §3.3: "the current clock date must lie within the agreement's
        window with both bounds inclusive — `effective_from` on or before the
        clock date and the clock date on or before `effective_to`, otherwise
        `ERR_AGREEMENT_NOT_IN_WINDOW` (HTTP 422)".

        Design: Corner/validations/activate_outside_window_rejected
        """
        set_clock()
        provider = create_licensed_provider("Timely Insurance")
        agreement = create_draft_agreement(
            provider["id"], "INSURANCE_HEALTH",
            effective_from="2026-01-01", effective_to="2026-12-31")
        set_clock("2027-06-01T00:00:00Z")
        resp = api.transition_agreement(agreement["id"], {"action": "ACTIVATE"}, GOV)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_IN_WINDOW)
        assert get_agreement(agreement["id"])["status"] == "DRAFT"


class TestAgreementActionRoleSplit:
    def test_agreement_action_role_split(self, api):
        """PRD §2.8 rung 2: "agreement transitions restrict `ACTIVATE` and
        `TERMINATE` to `GovernanceOfficer` and restrict `PROBATE` and
        `REINSTATE` to `OversightAnalyst`; otherwise `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/agreement_action_role_split
        """
        set_clock()
        provider = create_licensed_provider("Split Duty Insurance")
        agreement = create_draft_agreement(provider["id"], "INSURANCE_AUTO")

        resp = api.transition_agreement(agreement["id"], {"action": "ACTIVATE"}, OVA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_agreement(agreement["id"])["status"] == "DRAFT"

        activated = validate_success(
            api.transition_agreement(agreement["id"], {"action": "ACTIVATE"}, GOV))
        assert activated["status"] == "ACTIVE"

        resp = api.transition_agreement(agreement["id"], {"action": "PROBATE"}, GOV)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_agreement(agreement["id"])["status"] == "ACTIVE"

        probated = validate_success(
            api.transition_agreement(agreement["id"], {"action": "PROBATE"}, OVA))
        assert probated["status"] == "PROBATION"
        assert probated["probation_count"] == 1


class TestAgreementOwnershipAndOcc:
    def test_agreement_create_forbidden_for_other_provider(self, api):
        """PRD §2.1: "When `X-User-Role` is `ProviderManager`, `X-User-ID` is
        the `id` of the acting `Provider`; drafting a license agreement
        compares it to the provider identified in the path, and submitting a
        royalty statement compares it to the provider that owns the target
        agreement — a mismatch is `ERR_FORBIDDEN`."

        Design: Corner/validations/agreement_create_forbidden_for_other_provider
        """
        set_clock()
        provider_a = create_licensed_provider("Northstar Insurance")
        provider_b = validate_success(
            api.create_provider(
                create_provider_payload(legal_name="Southfield Services"), GOV),
            expected_status=201)
        # The presented version is current (2 after admission): only the
        # ownership check can fire.
        payload = create_license_agreement_payload(
            provider_a["version"], product_category="INSURANCE_AUTO")
        resp = api.create_license_agreement(
            provider_a["id"], payload,
            make_provider_manager_headers(provider_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_provider(provider_a["id"])["version"] == 2

    def test_occ_stale_provider_version_rejected(self, api):
        """PRD §2.7: "If the value does not match the provider's current
        `version`, the request is rejected with `ERR_STALE_PROVIDER_VERSION`
        (HTTP 412)." PRD §3.3: "This increment is exactly what makes a second
        drafter working from a stale provider read fail its OCC check."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_provider_version_rejected
        """
        set_clock()
        provider = validate_success(
            api.create_provider(
                create_provider_payload(legal_name="Optimist Insurance"), GOV),
            expected_status=201)
        stale_version = provider["version"]  # 1, observed before admission
        validate_success(api.admit_provider(provider["id"], GOV))  # now 2

        payload = create_license_agreement_payload(
            stale_version, product_category="INSURANCE_LIFE")
        resp = api.create_license_agreement(
            provider["id"], payload, make_provider_manager_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_PROVIDER_VERSION)

        rows, _ = validate_paginated(
            api.list_provider_agreements(provider["id"], GOV))
        assert len(rows) == 0
        assert get_provider(provider["id"])["version"] == 2
