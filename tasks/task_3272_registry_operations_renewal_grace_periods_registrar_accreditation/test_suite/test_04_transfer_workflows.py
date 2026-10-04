"""Inter-registrar transfer workflow tests (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    get_domain,
    get_success_data,
    list_invoices,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_completed_transfer,
    setup_disputed_transfer,
    setup_two_registrars_with_domain,
    validate_error,
)


class TestTransferDisputeCycle:
    def test_dispute_then_uphold_cycles_back_to_completed(self, api):
        """PRD §3.5: "If the admin instead submits the adjudication with
        `uphold` set to true, the transfer cycles back to `COMPLETED`: the
        domain stays with the gaining registrar, the extension stands, and no
        money moves."

        Design: Difficulty/non_linear_state_machine/transfer_dispute_cycle_back_to_completed_on_uphold
        """
        reg_a, reg_b, domain, transfer = setup_disputed_transfer(
            name="cycle-domain")
        assert transfer["status"] == "DISPUTED"
        completed_domain = get_domain(domain["id"])
        assert completed_domain["registrar_id"] == reg_b["id"]
        expires_after_complete = completed_domain["expires_on"]

        resp = api.reverse_transfer(
            transfer["id"], make_admin_headers(), payload={"uphold": True})
        upheld = get_success_data(resp)
        assert upheld["status"] == "COMPLETED", (
            f"uphold must cycle the transfer back to COMPLETED, got "
            f"{upheld['status']}"
        )

        final_domain = get_domain(domain["id"])
        assert final_domain["registrar_id"] == reg_b["id"]
        assert final_domain["expires_on"] == expires_after_complete, (
            "the dispute cycle added no extra extension: expires_on must be "
            "identical before and after the uphold"
        )

        # No money moves on uphold: the TRANSFER invoice is not voided.
        transfer_invoices = [
            inv for inv in list_invoices(domain_id=domain["id"])
            if inv["kind"] == "TRANSFER"
        ]
        assert len(transfer_invoices) == 1
        assert transfer_invoices[0]["status"] == "OPEN"

    def test_domain_state_identical_across_full_dispute_uphold_loop(self, api):
        """PRD §3.5: "the transfer cycles back to `COMPLETED`: the domain
        stays with the gaining registrar, the extension stands, and no money
        moves."
        PRD §3.5: "Completion moves the transfer to `COMPLETED`, switches the
        domain's `registrar_id` to the gaining registrar and returns the
        domain to `ACTIVE`, extends `expires_on` by one year, recomputes
        `grace_deadline`, and mints a `TRANSFER` invoice against the *gaining*
        registrar at the effective schedule's `transfer_fee_cents`".

        Design: Difficulty/non_linear_state_machine/transfer_dispute_cycle_back_to_completed_on_uphold
        """
        reg_a, reg_b, domain, transfer = setup_completed_transfer(
            name="cycle-domain")
        after_complete = get_domain(domain["id"])
        # Original domain was created at 2026-01-01 for 1 year (fixture
        # default), so completion extends expiry to 2028-01-01.
        assert after_complete["expires_on"] == "2029-03-01T00:00:00.000Z"

        resp = api.dispute_transfer(
            transfer["id"], "fraudulent auth code use",
            make_operator_headers(reg_a["id"]))
        get_success_data(resp)
        resp = api.reverse_transfer(
            transfer["id"], make_admin_headers(), payload={"uphold": True})
        upheld = get_success_data(resp)
        assert upheld["status"] == "COMPLETED"

        after_loop = get_domain(domain["id"])
        assert after_loop["registrar_id"] == after_complete["registrar_id"]
        assert after_loop["expires_on"] == after_complete["expires_on"]
        assert after_loop["status"] == after_complete["status"] == "ACTIVE"


class TestTransferOverlapOccupation:
    def test_second_request_rejected_until_first_nacked(self, api):
        """PRD §3.5: "Only one transfer per domain may be open at a time: if
        another transfer for the domain is still `REQUESTED`, the request is
        rejected with `ERR_TRANSFER_ALREADY_PENDING`."
        PRD §3.5: "Refusal — a nack by the same losing party — moves it to
        `NACKED` and returns the domain to `ACTIVE` under the original
        registrar with no invoice."

        Design: Difficulty/resource_temporal_overlap/second_pending_transfer_overlaps_in_flight_transfer
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            name="overlap-domain")
        reg_c_resp = api.create_registrar(
            {
                "iana_number": 8603,
                "legal_name": "Overlap C",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        reg_c = get_success_data(reg_c_resp, expected_status=201)
        get_success_data(
            api.accredit_registrar(reg_c["id"], make_admin_headers()))

        set_clock("2027-05-08T00:00:00Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        transfer_b = get_success_data(resp, expected_status=201)

        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_c["id"]},
            make_operator_headers(reg_c["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_PENDING)

        resp = api.nack_transfer(
            transfer_b["id"], make_operator_headers(reg_a["id"]))
        nacked = get_success_data(resp)
        assert nacked["status"] == "NACKED"

        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_c["id"]},
            make_operator_headers(reg_c["id"]),
        )
        transfer_c = get_success_data(resp, expected_status=201)
        assert transfer_c["status"] == "REQUESTED"

    def test_domain_returns_to_active_after_nack_releases_occupation(self, api):
        """PRD §3.5: "Refusal — a nack by the same losing party — moves it to
        `NACKED` and returns the domain to `ACTIVE` under the original
        registrar with no invoice."
        PRD §3.5: "Only one transfer per domain may be open at a time: if
        another transfer for the domain is still `REQUESTED`, the request is
        rejected with `ERR_TRANSFER_ALREADY_PENDING`."

        Design: Difficulty/resource_temporal_overlap/second_pending_transfer_overlaps_in_flight_transfer
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            name="overlap-domain")
        set_clock("2027-05-08T00:00:00Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        transfer_b = get_success_data(resp, expected_status=201)
        assert get_domain(domain["id"])["status"] == "TRANSFERRING"

        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_PENDING)

        resp = api.nack_transfer(
            transfer_b["id"], make_operator_headers(reg_a["id"]))
        get_success_data(resp)

        after = get_domain(domain["id"])
        assert after["status"] == "ACTIVE"
        assert after["registrar_id"] == reg_a["id"]

        # The occupation has ended: a fresh request succeeds.
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        retry = get_success_data(resp, expected_status=201)
        assert retry["status"] == "REQUESTED"
