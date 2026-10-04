"""Agency lifecycle: creation envelope, activation gates, suspend cascade,
asymmetric reactivation, offboard exposure gate, computed attestation standing."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_agency,
    api_client,
    assert_agency,
    capture,
    close_batch,
    confirm_batch,
    create_agency,
    create_agency_payload,
    create_attestation_payload,
    create_settlement_account,
    create_settlement_account_payload,
    file_attestation,
    get_agency,
    get_quote,
    get_service,
    get_transaction,
    make_payer_headers,
    offboard_agency,
    open_batch,
    pay,
    reconcile_batch,
    set_clock,
    setup_active_agency,
    setup_captured_card,
    setup_open_card_quote,
    submit_batch,
    suspend_agency,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


class TestAgencyCreation:
    def test_agency_create_returns_declared_fields_and_envelope(self, api):
        """PRD §3.1: "The agency is born in `ONBOARDING` status with
        `version` 1, and its `activated_at` remains null until its first
        activation."
        PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body".

        Design: Corner/entities/agency_create_returns_declared_fields_and_envelope
        """
        set_clock()
        resp = api_client.create_agency(create_agency_payload(), PA)
        agency = validate_success(resp, 201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert_agency(agency)
        assert agency["legal_name"] == "Department of Public Safety"
        assert agency["agency_type"] == "STATE"
        assert agency["default_fee_model"] == "CONVENIENCE_FEE"
        assert agency["status"] == "ONBOARDING"
        assert agency["activated_at"] is None
        assert agency["version"] == 1

    def test_agency_get_unknown_id_returns_not_found(self, api):
        """PRD §2.8: "Each unresolved reference reports its own resource's
        not-found error, all HTTP 404: `ERR_AGENCY_NOT_FOUND`".
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format".

        Design: Corner/entities/agency_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api_client.get_agency("00000000-0000-4000-8000-0000000000ff", PA)
        validate_error(resp, ApiErrorId.ERR_AGENCY_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"].strip()


class TestActivationGates:
    def test_no_verified_account_blocks_activation(self, api):
        """PRD §3.1: "the agency must hold at least one `VERIFIED` settlement
        account, otherwise `ERR_NO_VERIFIED_ACCOUNT`, and it must hold a
        `PCI_DSS_AOC` attestation that is `CURRENT` at the logical clock,
        otherwise `ERR_COMPLIANCE_LAPSED`."

        Design: Corner/errors/err_no_verified_account_on_agency_activate
        """
        set_clock()
        agency = create_agency()
        create_settlement_account(agency["id"], agency["version"])  # stays PENDING_VERIFICATION
        file_attestation(agency["id"])  # CURRENT at the default clock
        resp = api_client.activate_agency(agency["id"], PA)
        validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_ACCOUNT)
        assert get_agency(agency["id"])["status"] == "ONBOARDING"

    def test_attestation_status_computed_against_clock(self, api):
        """PRD §3.1: "The attestation's `status` is computed, never stored:
        it reads `CURRENT` while the logical clock is earlier than
        `expires_at` and `EXPIRED` once the clock reaches or passes it."

        Design: Corner/entities/attestation_status_computed_against_clock
        """
        set_clock()
        agency = create_agency()
        file_attestation(agency["id"], expires_at="2026-10-01T00:00:00Z")

        def status_at(clock):
            set_clock(clock)
            data, _ = validate_paginated(api_client.list_attestations(agency["id"], CA))
            assert len(data) == 1
            return data[0]["status"]

        assert status_at("2026-09-01T00:00:00Z") == "CURRENT"
        assert status_at("2026-09-30T23:59:59Z") == "CURRENT"
        assert status_at("2026-10-01T00:00:00Z") == "EXPIRED", (
            "clock >= expires_at flips the computed standing with no write in between"
        )


class TestSuspendCascade:
    def _setup_with_open_quote_and_inflight_txn(self):
        ctx = setup_open_card_quote()  # OPEN quote + card instrument
        inflight = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], 50000, "CARD")
        return ctx, inflight["transaction"]

    def test_suspend_cascades_services_and_quotes_but_spares_inflight(self, api):
        """PRD §3.1: "Suspending an `ACTIVE` agency cascades downward in two
        links. First, every service of the agency in `ACTIVE` status moves to
        `DEACTIVATED`; second, for each service so deactivated, every fee
        quote of that service still `OPEN` moves to `VOIDED`. In-flight
        transactions in `AUTHORIZED` or `CAPTURED` are unaffected and may
        still capture and settle."

        Design: Difficulty/transitive_cascade/agency_suspend_deactivates_services_voids_quotes
        """
        ctx, txn2 = self._setup_with_open_quote_and_inflight_txn()
        suspended = suspend_agency(ctx["agency"]["id"])
        assert suspended["status"] == "SUSPENDED"  # link 1
        assert get_service(ctx["service"]["id"])["status"] == "DEACTIVATED"  # link 2
        assert get_quote(ctx["quote"]["id"])["status"] == "VOIDED"  # link 3
        mid = get_transaction(txn2["id"])
        assert mid["funds_status"] == "AUTHORIZED", "in-flight funds are unaffected by the cascade"
        captured = capture(txn2["id"])
        assert captured["funds_status"] == "CAPTURED", "in-flight transactions may still capture"

    def test_reactivation_does_not_restore_deactivated_services(self, api):
        """PRD §3.1: "Reactivation applies the same two gates, and it does
        not restore services that an earlier suspension deactivated — each
        such service needs its own activation."

        Design: Difficulty/transitive_cascade/agency_suspend_deactivates_services_voids_quotes
        """
        ctx, _txn2 = self._setup_with_open_quote_and_inflight_txn()
        suspend_agency(ctx["agency"]["id"])
        reactivated = activate_agency(ctx["agency"]["id"])
        assert reactivated["status"] == "ACTIVE"
        assert get_service(ctx["service"]["id"])["status"] == "DEACTIVATED", (
            "the cascade is not symmetric: services need their own activation"
        )


class TestOffboardGate:
    def test_offboard_blocked_until_exposure_zero(self, api):
        """PRD §3.1: "Offboarding is the terminal transition, `ACTIVE` to
        `OFFBOARDED`, and it is refused with `ERR_OFFBOARD_BLOCKED` while the
        agency carries any unsettled exposure: any payment transaction in
        `AUTHORIZED`, `CAPTURED` or `RE_PRESENTED`, or any settlement batch
        in `OPEN`, `CLOSED`, `SUBMITTED`, `CONFIRMED` or `EXCEPTION`."

        Design: Corner/errors/err_offboard_blocked
        """
        ctx = setup_captured_card(capture_clock="2026-09-10T00:00:00Z")
        resp = api_client.offboard_agency(ctx["agency"]["id"], PA)
        validate_error(resp, ApiErrorId.ERR_OFFBOARD_BLOCKED)  # CAPTURED txn is unsettled exposure
        # settle and fully reconcile the exposure
        batch = open_batch(ctx["agency"]["id"], "2026-09-11")
        close_batch(batch["id"])
        submit_batch(batch["id"])
        set_clock("2026-09-12T00:00:00Z")
        confirm_batch(batch["id"], 100000)
        reconciled = reconcile_batch(batch["id"])
        assert reconciled["status"] == "RECONCILED"
        offboarded = offboard_agency(ctx["agency"]["id"])
        assert offboarded["status"] == "OFFBOARDED"
        assert get_service(ctx["service"]["id"])["status"] == "DEACTIVATED"
        assert get_quote(ctx["quote"]["id"])["status"] == "CONSUMED", (
            "the offboard cascade voids only OPEN quotes; the consumed one is untouched"
        )
