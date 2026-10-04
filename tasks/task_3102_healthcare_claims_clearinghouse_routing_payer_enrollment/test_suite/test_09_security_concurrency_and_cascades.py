"""Breadth tests: error envelope behavior, role exclusivity, optimistic
concurrency, terminate cascade, outage recovery, and read-after-write
consistency."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_payer_payload
from test_helpers.fixtures import (
    create_outage,
    get_enrollment,
    get_inquiry,
    get_payer,
    set_clock,
    setup_active_provider_with_credential,
    setup_claims_pipeline,
    setup_forwarded_claim,
    setup_world,
    submit_claim,
    submit_inquiry,
)
from test_helpers.test_users import (
    CLEARINGHOUSE_OPS_HEADERS,
    make_payer_operator_headers,
    make_provider_admin_headers,
)


class TestUserContextHeader:
    def test_missing_role_header_rejected(self, api: ApiClient):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400) before any role-permission evaluation takes place."

        Design: Corner/errors/error_unauthenticated_request_missing_role_header
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        resp = api.list_providers(headers={"X-User-ID": "anon-1"})
        validate_error(resp, ApiErrorId.MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestPayerCodeMismatch:
    def test_decision_with_wrong_payer_code_rejected(self, api: ApiClient):
        """PRD §2.1: "every `PayerOperator` request that targets a payer-owned
        decision surface ... must carry a third header, `X-Payer-Code`, whose
        value is compared against the `payer_id_code` of the payer that owns
        the resource being acted on — a mismatch is rejected with
        `ERR_PAYER_CODE_MISMATCH` (HTTP 403)".

        Design: Corner/errors/error_payer_code_mismatch_on_payer_operator_action
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "Mismatch Provider",
                "tax_identification_number": "232323232",
                "national_provider_identifier": "1232323232",
            },
            payer_overrides={"display_name": "Payer Y"},
            payer_code="PAYMY",
        )
        payer_x = get_success_data(
            api.create_payer(
                create_payer_payload(payer_id_code="PAYMX", display_name="Payer X"),
                CLEARINGHOUSE_OPS_HEADERS,
            )
        )

        admin = world.admin_headers()
        enrollment = get_success_data(
            api.create_enrollment(
                world.provider_id,
                {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
                admin,
            )
        )
        validate_success(api.submit_enrollment(world.provider_id, enrollment["id"], admin))
        resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
        assert resp.status_code == 200, f"Setup failed: advance-to-review {resp.text}"
        current = get_enrollment(api, world, enrollment["id"])

        # Payer X's operator tries to decide payer Y's enrollment.
        resp = api.record_payer_decision(
            enrollment["id"],
            {"decision": "APPROVE", "expected_enrollment_version": current["version"]},
            make_payer_operator_headers(payer_x["id"], "PAYMX"),
        )
        validate_error(resp, ApiErrorId.PAYER_CODE_MISMATCH)

        after = get_enrollment(api, world, enrollment["id"])
        assert after["status"] == "PAYER_REVIEW"


class TestRoleExclusivity:
    def test_provider_admin_cannot_register_payers(self, api: ApiClient):
        """PRD §4: the endpoint table authorizes only ClearinghouseOps for
        `POST /clearinghouse/payers`. PRD §2.1: "A request whose role is not
        permitted to invoke the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/roles/provider_admin_cannot_call_clearinghouse_ops_exclusive_endpoint
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        provider = get_success_data(
            api.create_provider(
                {
                    "legal_name": "RBAC Provider",
                    "tax_identification_number": "454545454",
                    "national_provider_identifier": "1454545454",
                    "billing_model": "PROVIDER_FUNDED",
                },
                CLEARINGHOUSE_OPS_HEADERS,
            )
        )

        resp = api.create_payer(
            create_payer_payload(payer_id_code="PAYRB", display_name="RBAC Payer"),
            make_provider_admin_headers(provider["id"]),
        )
        validate_error(resp, ApiErrorId.INSUFFICIENT_PERMISSIONS)

    def test_clearinghouse_ops_cannot_acknowledge_claim(self, api: ApiClient):
        """PRD §4: the endpoint table authorizes only PayerOperator for
        `POST /clearinghouse/claims/{id}/payer-ack`. PRD §2.1: "A request whose
        role is not permitted to invoke the target endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/roles/clearinghouse_ops_cannot_call_payer_operator_exclusive_endpoint
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "Ops Provider",
                "tax_identification_number": "565656566",
                "national_provider_identifier": "1565656570",
            },
            payer_code="PAYOP",
        )
        claim = setup_forwarded_claim(
            api,
            world,
            claim_overrides={"patient_control_number": "PCN-OP1", "idempotency_key": "IDEM-OP1"},
        )

        resp = api.ack_claim(claim["id"], CLEARINGHOUSE_OPS_HEADERS)
        validate_error(resp, ApiErrorId.INSUFFICIENT_PERMISSIONS)


class TestOptimisticConcurrency:
    def test_stale_enrollment_version_rejected(self, api: ApiClient):
        """PRD §2.8: "Recording a payer decision on an enrollment requires
        `expected_enrollment_version` carrying the enrollment's current
        `version` ... a mismatch with the parent entity's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_enrollment_version_returns_412
        """
        world = setup_world(
            api,
            provider_overrides={
                "legal_name": "OCC Provider",
                "tax_identification_number": "676767677",
                "national_provider_identifier": "1676767688",
            },
            payer_code="PAYOC",
        )
        admin = world.admin_headers()
        enrollment = get_success_data(
            api.create_enrollment(
                world.provider_id,
                {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
                admin,
            )
        )
        validate_success(api.submit_enrollment(world.provider_id, enrollment["id"], admin))
        resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
        assert resp.status_code == 200, f"Setup failed: advance-to-review {resp.text}"
        current = get_enrollment(api, world, enrollment["id"])

        resp = api.record_payer_decision(
            enrollment["id"],
            {
                "decision": "APPROVE",
                "expected_enrollment_version": current["version"] - 1,
            },
            world.payer_headers(),
        )
        validate_error(resp, ApiErrorId.STALE_VERSION)

        after = get_enrollment(api, world, enrollment["id"])
        assert after["status"] == "PAYER_REVIEW"


class TestTerminateCascade:
    def test_terminate_revokes_credentials(self, api: ApiClient):
        """PRD §3.1: "Termination, also from `ACTIVE`, demands a clean ledger —
        no usage invoice still `OPEN` or `FINALIZED`, and no claim anywhere in
        `RECEIVED`, `VALIDATING`, `ACCEPTED`, or `FORWARDED` — and its blast
        radius is wider still: every non-`REVOKED` credential flips to
        `REVOKED`, every `APPROVED` enrollment flips to `CANCELLED`, and
        `version` increments. `TERMINATED` is terminal."

        Design: Corner/cross_cutting_layers/cascading_provider_suspend_also_cascades_to_credentials_via_terminate
        """
        provider, credential = setup_active_provider_with_credential(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Term Provider",
                "tax_identification_number": "787878788",
                "national_provider_identifier": "1787878796",
            },
            credential_overrides={
                "submitter_id": "SUB-TM1",
                "trading_partner_agreement_ref": "TPA-TM1",
            },
        )

        terminated = validate_success(
            api.terminate_provider(provider["id"], CLEARINGHOUSE_OPS_HEADERS)
        )
        assert terminated["status"] == "TERMINATED"

        cred_now = validate_success(
            api.get_credential(provider["id"], credential["id"], CLEARINGHOUSE_OPS_HEADERS)
        )
        assert cred_now["status"] == "REVOKED", (
            f"terminate must cascade the credential to REVOKED, got {cred_now['status']}"
        )


class TestOutageRecovery:
    def test_resolve_returns_queued_inquiry_to_pending_with_fresh_deadline(self, api: ApiClient):
        """PRD §3.6: "When the last matching outage resolves, the inquiry
        returns to `PENDING` and its `deadline_at` is recomputed as the logical
        now plus the payer's full `eligibility_lead_time_seconds` — the SLA
        restarts in full on recovery rather than resuming from where it
        paused."

        Design: Corner/cross_cutting_layers/outage_resolve_returns_queued_inquiry_to_pending
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Outage Provider",
                "tax_identification_number": "898989899",
                "national_provider_identifier": "1898989904",
            },
            payer_overrides={
                "claims_lead_time_days": 5,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 3600,
            },
            payer_code="PAYOU",
            transaction_types=("ELIGIBILITY_270",),
        )
        inquiry = submit_inquiry(api, world, subscriber_id="MBR-OU", idempotency_key="IDEM-OU1")
        assert inquiry["status"] == "PENDING"
        original_deadline = inquiry["deadline_at"]

        outage = create_outage(
            api, world.payer_id, severity="FULL", affects_transaction_types=["ELIGIBILITY_270"]
        )
        queued = get_inquiry(api, inquiry["id"])
        assert queued["status"] == "QUEUED_OUTAGE", (
            "opening an eligibility outage must queue the pending inquiry"
        )

        # Advance the clock before resolving so a resumed (rather than
        # restarted) deadline would be observably stale.
        set_clock(api, "2026-09-01T00:30:00Z")
        resolved = validate_success(api.resolve_outage(outage["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert resolved["status"] == "RESOLVED"

        payer = get_payer(api, world.payer_id)
        assert payer["connectivity_status"] == "ONLINE"

        restored = get_inquiry(api, inquiry["id"])
        assert restored["status"] == "PENDING"
        assert restored["deadline_at"] != original_deadline, (
            "deadline must restart in full on recovery, not resume the paused value"
        )


class TestImmediateConsistency:
    def test_claim_create_response_matches_immediate_read(self, api: ApiClient):
        """PRD §3.4: "A persisted claim is born in `RECEIVED` and the system
        immediately moves it to `VALIDATING`, evaluating every payer edit rule
        in force at that instant ... With zero `ERROR` entries the claim
        becomes `ACCEPTED`."

        Design: Corner/consistency_model/immediate_consistency_claim_response_reflects_post_state
        """
        world = setup_claims_pipeline(
            api,
            provider_overrides={
                "legal_name": "IC Provider",
                "tax_identification_number": "909090910",
                "national_provider_identifier": "1909090916",
            },
            payer_code="PAYIC",
        )
        claim = submit_claim(
            api,
            world,
            patient_control_number="PCN-IC1",
            idempotency_key="IDEM-IC1",
        )
        assert claim["acceptance_status"] == "ACCEPTED"

        fetched = validate_success(api.get_claim(claim["id"], CLEARINGHOUSE_OPS_HEADERS))
        assert fetched["acceptance_status"] == "ACCEPTED"
        assert fetched["id"] == claim["id"]
