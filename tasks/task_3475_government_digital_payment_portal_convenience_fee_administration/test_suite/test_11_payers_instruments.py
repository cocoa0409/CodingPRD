"""Payers and instruments: email uniqueness, masked storage, ECHECK
micro-deposit self-loop to deactivation, payer ownership, role admission,
immediate read-after-write."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instrument,
    assert_payer,
    create_agency,
    create_instrument_payload,
    create_payer_payload,
    create_quote,
    make_agency_admin_headers,
    make_anonymous_headers,
    make_payer_headers,
    register_payer,
    set_clock,
    setup_cf_checkout,
    validate_error,
    validate_paginated,
    validate_success,
    verify_ach_payload,
)

PA = TEST_USERS["platform_admin_headers"]


class TestPayerRegistration:
    def test_duplicate_payer_email_rejected(self, api):
        """PRD §3.3: "Payer registration is open to `Anonymous` callers and
        to `PlatformAdmin`, taking `full_name`, an `email` that must be
        unique across all payers — a duplicate is rejected with
        `ERR_DUPLICATE_PAYER_EMAIL` — and `billing_zip`."

        Design: Corner/errors/err_duplicate_payer_email
        """
        set_clock()
        register_payer()  # pat@example.com
        resp = api_client.create_payer(
            create_payer_payload(
                full_name="Patrick Parker II", email="pat@example.com", billing_zip="73103"
            ),
            TEST_USERS["anonymous_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYER_EMAIL)

    def test_immediate_read_after_write_consistent(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."

        Design: Corner/consistency/immediate_read_after_write_consistent
        """
        set_clock()
        created = register_payer()
        read = api_client.get_payer(created["id"], PA)
        fetched = validate_success(read, 200)
        assert_payer(fetched)
        assert fetched["full_name"] == "Pat Parker"
        assert fetched["email"] == "pat@example.com"
        assert fetched["billing_zip"] == "73102"
        assert fetched["version"] == 1
        assert fetched["created_at"] == created["created_at"], "no read-your-writes gap"


class TestInstrumentCreation:
    def test_instrument_create_with_status_field_is_ignored_input(self, api):
        """PRD §3.3: "Only masked data is stored: the server mints a gateway
        `token_ref` at creation, and raw card or bank account numbers are
        never persisted."
        PRD §3.3: "`CARD` and `WALLET` instruments are created `ACTIVE` and
        never pass through verification, while `ECHECK` instruments start
        `PENDING_VERIFICATION`."
        PRD §2.5: "a `version`, an integer starting at 1 that increments on
        every mutation of the resource."

        Design: Corner/entities/instrument_create_with_status_field_is_ignored_input
        """
        payer = register_payer()
        resp = api_client.create_instrument(
            payer["id"],
            create_instrument_payload(
                "CARD",
                card_brand="VISA",
                card_cost_bucket="CONSUMER_CREDIT",
                last4="4242",
                status="DEACTIVATED",  # smuggled system fields must not take effect
                token_ref="hack",
                version=99,
            ),
            make_payer_headers(payer["id"]),
        )
        instrument = validate_success(resp, 201)
        assert_instrument(instrument)
        assert instrument["status"] == "ACTIVE"
        assert instrument["token_ref"] != "hack"
        assert instrument["version"] == 1
        assert instrument["last4"] == "4242"
        assert not any(k in instrument for k in ("pan", "card_number", "account_number"))

    def test_instrument_create_with_out_of_enum_method_returns_invalid_request(self, api):
        """PRD §2.8: "a request with a missing required field, a malformed
        value, an out-of-enum value, or a non-positive amount is rejected as
        malformed with `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/instrument_create_with_out_of_enum_method_returns_invalid_request
        """
        payer = register_payer()
        resp = api_client.create_instrument(
            payer["id"],
            {"method": "BITCOIN", "last4": "0000"},
            make_payer_headers(payer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, _ = validate_paginated(
            api_client.list_instruments(payer["id"], make_payer_headers(payer["id"]))
        )
        assert rows == []


class TestEcheckVerificationSelfLoop:
    def _pending_echeck_ctx(self):
        return setup_cf_checkout(with_echeck=True, echeck_verified=False)

    def _get_instrument(self, payer_id, instrument_id):
        rows, _ = validate_paginated(
            api_client.list_instruments(payer_id, make_payer_headers(payer_id))
        )
        by_id = {row["id"]: row for row in rows}
        return by_id[instrument_id]

    def test_first_two_ach_failures_keep_instrument_pending(self, api):
        """PRD §3.3: "Reporting `FAILURE` increments `ach_verify_failures`
        and leaves the instrument pending — except the failure that brings
        `ach_verify_failures` to 3, which moves the instrument to
        `DEACTIVATED` with `ach_verify_failures` equal to 3."

        Design: Difficulty/non_linear_state_machine/instrument_pending_self_loop_to_deactivated
        """
        ctx = self._pending_echeck_ctx()
        inst = ctx["echeck"]
        assert inst["status"] == "PENDING_VERIFICATION"
        for expected_failures in (1, 2):
            resp = api_client.verify_ach_instrument(
                inst["id"], verify_ach_payload("FAILURE"), make_payer_headers(ctx["payer"]["id"])
            )
            body = validate_success(resp, 200)
            assert body["status"] == "PENDING_VERIFICATION"
            assert body["ach_verify_failures"] == expected_failures
        persisted = self._get_instrument(ctx["payer"]["id"], inst["id"])
        assert persisted["status"] == "PENDING_VERIFICATION"
        assert persisted["ach_verify_failures"] == 2

    def test_third_ach_failure_deactivates_and_blocks_authorize(self, api):
        """PRD §3.4: "the instrument must be usable, meaning `ACTIVE` — a
        `PENDING_VERIFICATION` or `DEACTIVATED` instrument is rejected with
        `ERR_INSTRUMENT_NOT_USABLE`".

        Design: Difficulty/non_linear_state_machine/instrument_pending_self_loop_to_deactivated
        """
        ctx = self._pending_echeck_ctx()
        inst = ctx["echeck"]
        for _ in range(2):
            api_client.verify_ach_instrument(
                inst["id"], verify_ach_payload("FAILURE"), make_payer_headers(ctx["payer"]["id"])
            )
        resp = api_client.verify_ach_instrument(
            inst["id"], verify_ach_payload("FAILURE"), make_payer_headers(ctx["payer"]["id"])
        )
        body = validate_success(resp, 200)
        assert body["status"] == "DEACTIVATED"
        assert body["ach_verify_failures"] == 3
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 50000, "ECHECK")
        resp2 = api_client.authorize_payment(
            {"quote_id": quote["id"], "instrument_id": inst["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_INSTRUMENT_NOT_USABLE)
        persisted = self._get_instrument(ctx["payer"]["id"], inst["id"])
        assert persisted["status"] == "DEACTIVATED", "DEACTIVATED is terminal"


class TestPayerOwnershipAndRoles:
    def test_payer_cannot_read_other_payer_record(self, api):
        """PRD §3.3: "A `Payer` may read only its own payer record; reading
        another payer's record is rejected with `ERR_NOT_RESOURCE_OWNER`".

        Design: Corner/rbac/payer_cannot_read_other_payer_record
        """
        payer1 = register_payer()
        payer2 = register_payer(full_name="Sam Sub", email="sam@example.com", billing_zip="73104")
        resp = api_client.get_payer(payer1["id"], make_payer_headers(payer2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        admin_read = api_client.get_payer(payer1["id"], PA)
        assert validate_success(admin_read, 200)["email"] == "pat@example.com"

    def test_anonymous_cannot_get_agency(self, api):
        """PRD §2.1: "`Anonymous` — the unauthenticated registration caller,
        admitted only to payer registration. `X-User-ID` is ignored for this
        role."
        PRD §2.1: "Once the caller context is established, the caller's role
        must appear in the target endpoint's authorized role list, or the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/anonymous_cannot_get_agency
        """
        set_clock()
        agency = create_agency()
        resp = api_client.get_agency(agency["id"], make_anonymous_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
