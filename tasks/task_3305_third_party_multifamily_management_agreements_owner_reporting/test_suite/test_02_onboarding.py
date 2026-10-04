"""Onboarding pipeline: guards, net position, agreement gate (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_onboarding,
    get_success_data,
    setup_owner,
    setup_property,
    setup_resident,
    start_onboarding,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import drive_onboarding_to_ready
from test_helpers.factories import create_agreement_payload


class TestResidentDataGuard:
    def test_onboarding_guarded_transition_requires_resident_data(self, api, pm_headers, acct_headers):
        """PRD §3.3: "Once at least one resident row exists for the property,
        the accountant may mark resident data verified, moving the onboarding
        from `INTAKE` to `DATA_VERIFIED`; with no residents at all the step
        is rejected with `ERR_NO_RESIDENT_DATA`."

        Design: Corner/state_machines/onboarding_guarded_transition_requires_resident_data
        """
        owner = setup_owner(legal_name="Guard Owner LP")
        prop = setup_property(owner, name="Guard Property", unit_count=15)
        ob = start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")

        resp = api.verify_resident_data(ob["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_NO_RESIDENT_DATA)

        setup_resident(prop, unit_label="G1", full_name="Res G",
                       lease_end_date="2027-08-31T00:00:00Z")
        verified = validate_success(api.verify_resident_data(ob["id"], acct_headers))
        assert_onboarding(verified)
        assert verified["status"] == "DATA_VERIFIED"


class TestOnboardingNetPosition:
    def test_onboarding_net_position_sign_convention(self, api, pm_headers, acct_headers):
        """PRD §3.3: "Import computes the onboarding net position:
        `net_position_cents` is deposits received plus prepaid rent minus
        delinquency, in whole cents."

        Design: Corner/calculations/onboarding_net_position_sign_convention
        """
        owner = setup_owner(legal_name="Net Owner LP")
        prop = setup_property(owner, name="Net Property", unit_count=30)
        ob = start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")
        setup_resident(prop, unit_label="N1", full_name="Res N",
                       lease_end_date="2027-08-31T00:00:00Z")
        get_success_data(api.verify_resident_data(ob["id"], acct_headers))

        imported = validate_success(
            api.import_ledger(
                ob["id"],
                {
                    "deposits_received_cents": 600000,
                    "prepaid_rent_cents": 80000,
                    "delinquency_cents": 50000,
                },
                acct_headers,
            )
        )
        assert imported["net_position_cents"] == 630000, (
            f"600000 + 80000 - 50000 must equal 630000, got {imported['net_position_cents']}"
        )
        assert imported["status"] == "LEDGER_IMPORTED"


class TestOnboardingAgreementGate:
    def test_onboarding_activation_requires_active_agreement(self, api, pm_headers):
        """PRD §3.3: "From `READY`, a `PortfolioManager` activates the
        onboarding, which requires the property's `ManagementAgreement` to be
        `ACTIVE` — otherwise `ERR_AGREEMENT_NOT_ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/onboarding_activation_requires_active_agreement
        """
        owner = setup_owner(legal_name="Cross One LP")
        prop = setup_property(owner, name="Cross Property", unit_count=60)
        # Agreement created but left DRAFT (never activated).
        get_success_data(
            api.create_agreement(
                owner["id"],
                create_agreement_payload(property_id=prop["id"]),
                pm_headers,
            )
        )
        ob = start_onboarding(prop)
        setup_resident(prop, unit_label="13A", full_name="Res Thirteen")
        ob = drive_onboarding_to_ready(ob)
        assert ob["status"] == "READY"

        resp = api.activate_onboarding(ob["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        still_ready = validate_success(api.get_onboarding(ob["id"], pm_headers))
        assert still_ready["status"] == "READY", (
            f"onboarding must remain READY after the rejected activation, got {still_ready['status']}"
        )

    def test_onboarding_activation_succeeds_once_agreement_active(self, api, pm_headers):
        """PRD §3.3: "From `READY`, a `PortfolioManager` activates the
        onboarding, which requires the property's `ManagementAgreement` to be
        `ACTIVE` — otherwise `ERR_AGREEMENT_NOT_ACTIVE` — and on success moves
        the onboarding to `ACTIVATED` and the property's `management_posture`
        to `MANAGED`".

        Design: Difficulty/cross_entity_state_dependency/onboarding_activation_requires_active_agreement
        """
        owner = setup_owner(legal_name="Cross One B LP")
        prop = setup_property(owner, name="Cross Property B", unit_count=60)
        ag = get_success_data(
            api.create_agreement(
                owner["id"],
                create_agreement_payload(property_id=prop["id"]),
                pm_headers,
            )
        )
        ob = start_onboarding(prop)
        setup_resident(prop, unit_label="13B", full_name="Res Thirteen B")
        ob = drive_onboarding_to_ready(ob)

        # Activate the agreement, then the onboarding succeeds.
        get_success_data(
            api.activate_agreement(
                ag["id"], {"expected_agreement_version": ag["version"]}, pm_headers
            )
        )
        activated = validate_success(api.activate_onboarding(ob["id"], pm_headers))
        assert activated["status"] == "ACTIVATED"
        prop_after = validate_success(api.get_property(prop["id"], pm_headers))
        assert prop_after["management_posture"] == "MANAGED"
