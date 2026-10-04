"""Transfer corner tests (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    get_domain,
    get_success_data,
    get_transfer,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_requested_transfer,
    setup_two_registrars_with_domain,
    validate_error,
)


class TestTransferAutoAck:
    def test_auto_ack_after_five_days_of_silence(self, api):
        """PRD §3.5: "If five days pass after `requested_at` with neither an
        ack nor a nack, the system auto-acknowledges the transfer into
        `AUTO_ACKED`."
        PRD §3.5: "Completion is the gaining registrar's act on an `ACKED` or
        `AUTO_ACKED` transfer".

        Design: Corner/state_machines/transfer_auto_ack_after_five_days_of_silence
        """
        reg_a, reg_b, domain, transfer = setup_requested_transfer(
            clock="2027-03-01T00:00:01Z",
            request_clock="2027-05-08T00:00:00Z",
            name="autoack-domain")

        set_clock("2027-05-12T23:00:00Z")
        at_4d23h = get_transfer(transfer["id"])
        assert at_4d23h["status"] == "REQUESTED"

        set_clock("2027-05-13T00:00:01Z")
        at_5d1s = get_transfer(transfer["id"])
        assert at_5d1s["status"] == "AUTO_ACKED"

        resp = api.complete_transfer(
            transfer["id"], make_operator_headers(reg_b["id"]))
        completed = get_success_data(resp)
        assert completed["status"] == "COMPLETED"
        assert get_domain(domain["id"])["registrar_id"] == reg_b["id"]

    def test_ack_before_auto_ack_deadline_preempts_it(self, api):
        """PRD §3.5: "Acknowledgement moves the transfer to `ACKED`."
        PRD §3.5: "If five days pass after `requested_at` with neither an ack
        nor a nack, the system auto-acknowledges the transfer into
        `AUTO_ACKED`."

        Design: Corner/state_machines/transfer_auto_ack_after_five_days_of_silence
        """
        reg_a, reg_b, domain, transfer = setup_requested_transfer(
            clock="2027-03-01T00:00:01Z",
            request_clock="2027-05-08T00:00:00Z",
            name="autoack-domain")

        set_clock("2027-05-12T23:00:00Z")
        resp = api.ack_transfer(
            transfer["id"], transfer["auth_code"],
            make_operator_headers(reg_a["id"]))
        acked = get_success_data(resp)
        assert acked["status"] == "ACKED"

        # Past the 5-day mark the explicit ack stands: no auto-ack flips an
        # already-acked transfer.
        set_clock("2027-05-13T00:00:01Z")
        assert get_transfer(transfer["id"])["status"] == "ACKED"


class TestTransferAuthCode:
    def test_wrong_auth_code_rejected_transfer_stays_requested(self, api):
        """PRD §3.5: "the submitted code must match the stored hash (a
        mismatch fails with `ERR_AUTH_CODE_INVALID`)".

        Design: Corner/validations/ack_with_wrong_auth_code_rejected_and_transfer_stays_requested
        """
        reg_a, reg_b, domain, transfer = setup_requested_transfer(
            clock="2027-03-01T00:00:01Z",
            request_clock="2027-05-08T00:00:00Z",
            name="authcode-domain")

        resp = api.ack_transfer(
            transfer["id"], "definitely-wrong",
            make_operator_headers(reg_a["id"]))
        validate_error(resp, ApiErrorId.ERR_AUTH_CODE_INVALID)
        assert get_transfer(transfer["id"])["status"] == "REQUESTED"

        # A retry with the right code within the TTL still succeeds.
        resp = api.ack_transfer(
            transfer["id"], transfer["auth_code"],
            make_operator_headers(reg_a["id"]))
        acked = get_success_data(resp)
        assert acked["status"] == "ACKED"

    def test_ack_after_auth_code_ttl_rejected(self, api):
        """PRD §3.5: "the clock must be at or before `auth_code_expires_at`
        (later attempts fail with `ERR_AUTH_CODE_EXPIRED`)".
        PRD §3.5: "A successful request flips the domain to `TRANSFERRING`
        and creates the transfer record in `REQUESTED` status with
        `from_registrar_id` copied from the domain's current sponsoring
        registrar, `requested_at` stamped from the logical clock, and
        `auth_code_expires_at` set to fourteen days after the request."

        Design: Corner/errors/error_auth_code_expired_after_14_days
        """
        reg_a, reg_b, domain, transfer = setup_requested_transfer(
            clock="2027-03-01T00:00:01Z",
            request_clock="2027-05-08T00:00:00Z",
            name="ttl-domain")
        assert transfer["auth_code_expires_at"] == "2027-05-22T00:00:00.000Z"

        set_clock("2027-05-22T00:00:01Z")
        resp = api.ack_transfer(
            transfer["id"], transfer["auth_code"],
            make_operator_headers(reg_a["id"]))
        validate_error(resp, ApiErrorId.ERR_AUTH_CODE_EXPIRED)

    def test_ack_by_non_party_registrar_forbidden(self, api):
        """PRD §3.5: "Acknowledging requires submitting the `auth_code`: the
        acting registrar must be the `from_registrar_id` party (anyone else
        gets `ERR_NOT_TRANSFER_PARTY`, HTTP 403)".

        Design: Corner/validations/ack_by_non_party_registrar_forbidden
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            clock="2027-03-01T00:00:01Z", name="party-domain")
        resp = api.create_registrar(
            {
                "iana_number": 9106,
                "legal_name": "Party C",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        reg_c = get_success_data(resp, expected_status=201)
        get_success_data(
            api.accredit_registrar(reg_c["id"], make_admin_headers()))

        set_clock("2027-05-08T00:00:00Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        transfer = get_success_data(resp, expected_status=201)

        resp = api.ack_transfer(
            transfer["id"], "whatever", make_operator_headers(reg_c["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_TRANSFER_PARTY)
