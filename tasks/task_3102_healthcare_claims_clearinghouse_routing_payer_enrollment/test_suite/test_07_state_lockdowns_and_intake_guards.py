"""Breadth tests: terminal-state lockdowns, intake idempotency, credential
window enforcement, and the claim rejection origin payload."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_claim_payload
from test_helpers.fixtures import (
    create_edit_rule,
    get_claim,
    get_inquiry,
    respond_inquiry,
    set_clock,
    setup_claims_pipeline,
    submit_claim,
    submit_inquiry,
)
from test_helpers.test_users import CLEARINGHOUSE_OPS_HEADERS


class TestTerminalStateLockdown:
    def test_forward_on_rejected_claim_returns_invalid_state(self, api: ApiClient):
        """PRD §3.4: "`REJECTED_CLEARINGHOUSE` is terminal, never reaches the
        payer, and never enters adjudication". PRD §2.7: "Target state
        compatibility — the addressed resource must be in a state from which
        the requested transition is defined, else `ERR_INVALID_STATE`".

        Design: Corner/state_machines/claim_terminal_rejected_clearinghouse_accepts_no_further_transitions
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Terminal Provider",
                "tax_identification_number": "565656565",
                "national_provider_identifier": "1565656562",
            },
            payer_code="PAYTM",
        )
        create_edit_rule(
            api,
            world.payer_id,
            rule_code="DX_REQUIRED",
            severity="ERROR",
            expression="diagnosis_codes.nonempty",
            effective_from="2026-01-01T00:00:00Z",
        )
        claim = submit_claim(
            api,
            world,
            patient_control_number="PCN-TR1",
            idempotency_key="IDEM-TR1",
            diagnosis_codes=[],
        )
        assert claim["acceptance_status"] == "REJECTED_CLEARINGHOUSE"

        resp = api.forward_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, CLEARINGHOUSE_OPS_HEADERS
        )
        validate_error(resp, ApiErrorId.INVALID_STATE)

        claim_now = get_claim(api, claim["id"])
        assert claim_now["acceptance_status"] == "REJECTED_CLEARINGHOUSE"

    def test_responded_inquiry_rejects_second_response(self, api: ApiClient):
        """PRD §3.6: "Both `RESPONDED` and `TIMED_OUT` are terminal." PRD §2.7:
        "Target state compatibility — the addressed resource must be in a state
        from which the requested transition is defined, else
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/eligibility_inquiry_responded_accepts_no_second_response
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Idem Provider",
                "tax_identification_number": "676767676",
                "national_provider_identifier": "1676767670",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 3600,
            },
            payer_code="PAYID",
            transaction_types=("ELIGIBILITY_270",),
        )
        inquiry = submit_inquiry(api, world, subscriber_id="MBR-ID", idempotency_key="IDEM-EL1")
        first = respond_inquiry(api, world, inquiry["id"], benefit_summary={"coverage": "ACTIVE"})
        assert first["status"] == "RESPONDED"

        resp = api.respond_to_inquiry(
            inquiry["id"], {"benefit_summary": {"coverage": "INACTIVE"}}, world.payer_headers()
        )
        validate_error(resp, ApiErrorId.INVALID_STATE)

        now = get_inquiry(api, inquiry["id"])
        assert now["benefit_summary"]["coverage"] == "ACTIVE", (
            "the second response must not overwrite the first"
        )


class TestClaimRejectionOrigin:
    def test_clearinghouse_rejection_payload_carries_origin_and_rule_codes(self, api: ApiClient):
        """PRD §3.4: "If `edit_failures` contains at least one entry with
        severity `ERROR`, the claim transitions to `REJECTED_CLEARINGHOUSE`:
        the system writes a structured `rejection_payload` whose `origin` is
        `CLEARINGHOUSE`, carrying the offending `rule_codes` and a `message`".

        Design: Corner/state_machines/claim_rejection_returns_clearinghouse_origin_payload
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Origin Provider",
                "tax_identification_number": "787878787",
                "national_provider_identifier": "1787878788",
            },
            payer_code="PAYOG",
        )
        create_edit_rule(
            api,
            world.payer_id,
            rule_code="DX_REQUIRED",
            severity="ERROR",
            expression="diagnosis_codes.nonempty",
            effective_from="2026-01-01T00:00:00Z",
        )

        resp = api.create_claim(
            world.provider_id,
            create_claim_payload(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-OG1",
                idempotency_key="IDEM-OG1",
                diagnosis_codes=[],
                rendering_npi="1787878788",
                subscriber_id="MBR-OG",
            ),
            world.admin_headers(),
        )
        claim = validate_success(resp, expected_status=201)
        assert claim["acceptance_status"] == "REJECTED_CLEARINGHOUSE"
        assert claim["rejection_payload"]["origin"] == "CLEARINGHOUSE"
        assert "DX_REQUIRED" in claim["rejection_payload"]["rule_codes"]


class TestClaimIntakeIdempotency:
    def test_replay_with_identical_payload_returns_original_claim(self, api: ApiClient):
        """PRD §3.4: "The `idempotency_key` is unique per provider among
        claims: replaying a submission with the same key and an identical
        payload returns the original response without creating a second claim".

        Design: Corner/validations/claim_intake_idempotency_key_replay_with_same_payload_returns_original
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Idem Replay Provider",
                "tax_identification_number": "121212121",
                "national_provider_identifier": "1121212124",
            },
            payer_code="PAYIR",
        )
        payload = create_claim_payload(
            payer_id=world.payer_id,
            submitter_credential_id=world.credential_id,
            patient_control_number="PCN-IR1",
            idempotency_key="IDEM-IR1",
            rendering_npi="1121212124",
            subscriber_id="MBR-IR",
        )
        first = validate_success(
            api.create_claim(world.provider_id, payload, world.admin_headers()),
            expected_status=201,
        )
        second = validate_success(
            api.create_claim(world.provider_id, payload, world.admin_headers()),
            expected_status=201,
        )
        assert first["id"] == second["id"], "replay must return the original claim"

        rows, meta = validate_paginated(
            api.list_claims(world.provider_id, CLEARINGHOUSE_OPS_HEADERS)
        )
        assert len(rows) == 1, "replay must not create a second claim"

    def test_replay_with_conflicting_payload_returns_idempotency_conflict(self, api: ApiClient):
        """PRD §3.4: "replaying a submission with the same key and an identical
        payload returns the original response without creating a second claim,
        while the same key with a different payload is
        `ERR_IDEMPOTENCY_CONFLICT`."

        Design: Corner/validations/claim_intake_idempotency_key_replay_with_different_payload_conflicts
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Conflict Provider",
                "tax_identification_number": "343434343",
                "national_provider_identifier": "1343434340",
            },
            payer_code="PAYCF",
        )
        payload = create_claim_payload(
            payer_id=world.payer_id,
            submitter_credential_id=world.credential_id,
            patient_control_number="PCN-CF1",
            idempotency_key="IDEM-CF1",
            total_charge_cents=100,
            rendering_npi="1343434340",
            subscriber_id="MBR-CF",
            lines=[{"cpt_code": "99213", "units": 1, "unit_charge_cents": 100}],
        )
        validate_success(
            api.create_claim(world.provider_id, payload, world.admin_headers()),
            expected_status=201,
        )

        conflicting = dict(payload)
        conflicting["total_charge_cents"] = 99999
        conflicting["lines"] = [{"cpt_code": "99213", "units": 1, "unit_charge_cents": 99999}]
        resp = api.create_claim(world.provider_id, conflicting, world.admin_headers())
        validate_error(resp, ApiErrorId.IDEMPOTENCY_CONFLICT)

        rows, meta = validate_paginated(
            api.list_claims(world.provider_id, CLEARINGHOUSE_OPS_HEADERS)
        )
        assert len(rows) == 1
        assert rows[0]["total_charge_cents"] == 100


class TestCredentialWindowEnforcement:
    def test_expired_credential_cannot_anchor_claim_intake(self, api: ApiClient):
        """PRD §3.1: "Only a credential that is `ACTIVE` **and** inside its
        `[effective_at, expires_at)` window at the logical now may anchor new
        claim intake; anything else surfaces `ERR_CREDENTIAL_NOT_ACTIVE`."

        Design: Corner/validations/claim_intake_with_credential_outside_effective_window_rejected
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Expired Cred Provider",
                "tax_identification_number": "565656565",
                "national_provider_identifier": "1565656562",
            },
            credential_overrides={
                "submitter_id": "SUB-EX1",
                "trading_partner_agreement_ref": "TPA-EX1",
                "effective_at": "2026-09-01T00:00:00Z",
                "expires_at": "2026-09-10T00:00:00Z",
            },
            payer_code="PAYEX",
        )
        # Move the logical clock past the credential's expires_at.
        set_clock(api, "2026-09-15T00:00:00Z")

        resp = api.create_claim(
            world.provider_id,
            create_claim_payload(
                payer_id=world.payer_id,
                submitter_credential_id=world.credential_id,
                patient_control_number="PCN-EX1",
                idempotency_key="IDEM-EX1",
                service_date="2026-09-15T00:00:00Z",
                rendering_npi="1565656562",
                subscriber_id="MBR-EX",
            ),
            world.admin_headers(),
        )
        validate_error(resp, ApiErrorId.CREDENTIAL_NOT_ACTIVE)

        rows, meta = validate_paginated(
            api.list_claims(world.provider_id, CLEARINGHOUSE_OPS_HEADERS)
        )
        assert len(rows) == 0, "no claim may be persisted against an expired credential"
