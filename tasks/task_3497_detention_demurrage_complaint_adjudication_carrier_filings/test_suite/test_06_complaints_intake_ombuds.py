"""Complaint intake, the frozen incentive score, ombuds rounds, and the
filing-window / party / existence validation rungs."""
from test_helpers import (
    MISSING_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_congestion_report_payload,
    file_complaint,
    issue_invoice,
    make_alj_headers,
    make_carrier,
    make_carrier_rep_headers,
    make_ombuds_officer_headers,
    make_shipper,
    make_shipper_rep_headers,
    open_dispute,
    respond_dispute,
    set_logical_clock,
    setup_carrier_shipper,
    setup_complaint_in_ombuds,
    setup_published_tariff,
    setup_standard_billing,
    setup_standard_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]


class TestComplaintIntake:
    def test_complaint_intake_starts_docketed_with_frozen_score(self):
        """PRD §3.7: "At intake the server computes the complaint's
        `incentive_principle_score`, an integer between 0 and 100 that is frozen
        for the life of the complaint and never recomputed." and "A docketed
        complaint begins with `complaint_status` in `DOCKETED` and
        `ombuds_rounds` at zero."

        Design: Corner/state_machines/complaint_intake_starts_docketed_with_frozen_score
        """
        env = setup_standard_complaint(claimed=50_000)
        complaint = env["complaint"]
        assert complaint["complaint_status"] == "DOCKETED"
        assert complaint["ombuds_rounds"] == 0
        assert complaint["reparations_awarded_cents"] == 0
        assert complaint["incentive_principle_score"] == 100

        # Late-filed reports at full occupancy for the invoice's port and week
        # would cost 25 points if the score were recomputed — it must not move.
        for term in ("TERM-F1", "TERM-F2", "TERM-F3", "TERM-F4"):
            validate_success(api_client.create_congestion_report(
                create_congestion_report_payload(
                    port_code="USNYC", terminal_code=term,
                    week_start="2026-08-31T00:00:00Z", berth_occupancy_hours=168,
                    gate_closures_hours=0, vessel_dwell_hours_avg=120.0),
                DOCKET), 201)
        after = validate_success(api_client.get_complaint(complaint["id"], DOCKET), 200)
        assert after["incentive_principle_score"] == 100

    def test_complaint_with_empty_subject_set_rejected(self):
        """PRD §3.7: "The filing names the `respondent_carrier_id`, a non-empty
        `subject_invoice_ids` array — an empty set is rejected with
        `ERR_EMPTY_SUBJECT_SET` (HTTP 422)".

        Design: Corner/validations/complaint_with_empty_subject_set_rejected
        """
        env = setup_carrier_shipper()
        resp = api_client.create_complaint({
            "respondent_carrier_id": env["carrier"]["id"],
            "subject_invoice_ids": [],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(resp, ApiErrorId.ERR_EMPTY_SUBJECT_SET)

    def test_complaint_party_and_respondent_mismatches_rejected(self):
        """PRD §3.7: "Every subject invoice must exist, must bill the complaining
        shipper — otherwise `ERR_NOT_INVOICE_PARTY` (HTTP 422) — must have been
        issued by the respondent carrier — otherwise
        `ERR_RESPONDENT_NOT_INVOICE_CARRIER` (HTTP 422)".

        Design: Corner/validations/complaint_party_and_respondent_mismatches_rejected
        """
        env = setup_published_tariff()
        shipper2 = make_shipper(company_name="Billed Elsewhere Shippers",
                                contact_email="ops@billed.example")
        carrier_b = make_carrier(org_type="VOCC", org_name="Uninvolved Lines")
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(env["carrier"]["id"], shipper2["id"],
                                tariff_id=env["tariff"]["id"],
                                invoice_number="INV-REF-1",
                                container_number="MSKU9200007")

        r1 = api_client.create_complaint({
            "respondent_carrier_id": env["carrier"]["id"],
            "subject_invoice_ids": [invoice["id"]],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(r1, ApiErrorId.ERR_NOT_INVOICE_PARTY)

        r2 = api_client.create_complaint({
            "respondent_carrier_id": carrier_b["id"],
            "subject_invoice_ids": [invoice["id"]],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(shipper2["id"]))
        validate_error(r2, ApiErrorId.ERR_RESPONDENT_NOT_INVOICE_CARRIER)

    def test_complaint_over_voided_invoice_rejected_not_actionable(self):
        """PRD §3.7: "must stand in `ISSUED`, `DISPUTED`, or `PAID` status; a
        `VOIDED` invoice leaves nothing to adjudicate and is rejected with
        `ERR_INVOICE_NOT_ACTIONABLE` (HTTP 409)."

        Design: Corner/validations/complaint_over_voided_invoice_rejected_not_actionable
        """
        env = setup_standard_billing()
        d1 = open_dispute(env["invoice"]["id"], env["shipper"]["id"],
                          dispute_reason="MISSING_ELEMENTS")
        respond_dispute(d1["id"], env["carrier"]["id"], {"resolution": "WAIVE"})

        resp = api_client.create_complaint({
            "respondent_carrier_id": env["carrier"]["id"],
            "subject_invoice_ids": [env["invoice"]["id"]],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ACTIONABLE)

    def test_complaint_filed_at_exactly_180_days_accepted(self):
        """PRD §3.7: "The complaint itself must be filed no later than 180 days
        after the most recently issued of its subject invoices; a later filing is
        rejected with `ERR_COMPLAINT_FILING_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/calculations/complaint_filed_at_exactly_180_days_accepted
        """
        env = setup_standard_billing()
        set_logical_clock("2027-03-09T00:00:00Z")
        complaint = file_complaint(env["shipper"]["id"], env["carrier"]["id"],
                                   [env["invoice"]["id"]],
                                   reparations_claimed_cents=50_000)
        assert complaint["complaint_status"] == "DOCKETED"

    def test_complaint_unknown_invoice_reference_beats_party_and_window_failures(self):
        """PRD §2.7: "Every request walks an ordered ladder of checks, and
        evaluation stops at the first failure: the response carries that
        failure's error identifier and no later check is consulted." — rung
        "5. Existence of entities referenced in the request body (the same
        per-family 404 errors)." precedes the temporal and cross-reference rungs.

        Design: Corner/validations/complaint_unknown_invoice_reference_beats_party_and_window_failures
        """
        env = setup_published_tariff()
        shipper2 = make_shipper(company_name="Other Shippers",
                                contact_email="ops@other.example")
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(env["carrier"]["id"], shipper2["id"],
                                tariff_id=env["tariff"]["id"],
                                invoice_number="INV-PRIO-1",
                                container_number="MSKU9200001")
        set_logical_clock("2027-03-10T00:00:00Z")
        resp = api_client.create_complaint({
            "respondent_carrier_id": env["carrier"]["id"],
            "subject_invoice_ids": [invoice["id"], MISSING_UUID],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)


class TestExpiredWindowBeatsParty:
    def _expired_window_env(self):
        env = setup_published_tariff(carrier_name="Window Probe Carriers")
        shipper2 = make_shipper(company_name="Second Party Shippers",
                                contact_email="billing@secondparty.example")
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(env["carrier"]["id"], shipper2["id"],
                                tariff_id=env["tariff"]["id"],
                                invoice_number="INV-WIN-1",
                                container_number="MSKU4000009")
        set_logical_clock("2027-03-10T00:00:00Z")
        return env, invoice

    def test_expired_complaint_window_wins_over_party_mismatch(self):
        """PRD §2.7: the ladder's "9. Temporal windows" rung precedes
        "10. Cross-reference consistency between the request and existing
        resources", and "evaluation stops at the first failure".
        PRD §3.7: "a later filing is rejected with
        `ERR_COMPLAINT_FILING_WINDOW_EXPIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/expired_complaint_window_beats_wrong_billed_party
        """
        env, invoice = self._expired_window_env()
        resp = api_client.create_complaint({
            "respondent_carrier_id": env["carrier"]["id"],
            "subject_invoice_ids": [invoice["id"]],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(env["shipper"]["id"]))
        # Filed 2027-03-10, one day past issued_at 2026-09-10 + 180 days;
        # the invoice was also billed to a different shipper.
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_FILING_WINDOW_EXPIRED)

    def test_expired_complaint_window_stores_no_complaint(self):
        """PRD §3.7: "The complaint itself must be filed no later than 180 days
        after the most recently issued of its subject invoices; a later filing is
        rejected with `ERR_COMPLAINT_FILING_WINDOW_EXPIRED` (HTTP 422)." — a
        rejected filing persists nothing.

        Design: Difficulty/priority_pair_validation_conflict/expired_complaint_window_beats_wrong_billed_party
        """
        env, invoice = self._expired_window_env()
        resp = api_client.create_complaint({
            "respondent_carrier_id": env["carrier"]["id"],
            "subject_invoice_ids": [invoice["id"]],
            "reparations_claimed_cents": 10000,
        }, make_shipper_rep_headers(env["shipper"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_FILING_WINDOW_EXPIRED)
        rows, meta = validate_paginated(api_client.list_complaints(
            DOCKET, params={"shipper_id": env["shipper"]["id"]}))
        assert meta["total_count"] == 0
        assert rows == []


class TestOmbudsFlow:
    def test_ombuds_settle_resolves_informally_and_credits_shipper(self):
        """PRD §3.7: "Closing with `outcome` `SETTLED` requires a
        `settlement_amount_cents` figure — absent, the request fails with
        `ERR_INVALID_REQUEST` (HTTP 400) — and resolves the complaint as
        `RESOLVED_INFORMAL`: the figure is recorded as
        `informal_settlement_cents` and added to the shipper's
        `total_recovery_cents`."

        Design: Corner/state_machines/ombuds_settle_resolves_informally_and_credits_shipper
        """
        env = setup_complaint_in_ombuds(officer_id="om-1")
        data = validate_success(api_client.close_ombuds(
            env["complaint"]["id"],
            {"outcome": "SETTLED", "settlement_amount_cents": 40000},
            make_ombuds_officer_headers("om-1")), 200)
        assert data["complaint_status"] == "RESOLVED_INFORMAL"
        assert data["informal_settlement_cents"] == 40000
        assert data["ombuds_rounds"] == 0, "a settled round is not a failed round"
        shipper = api_client.get_shipper(env["shipper"]["id"], DOCKET).json()["data"]
        assert shipper["total_recovery_cents"] == 40000

    def test_terminal_resolved_complaint_rejects_further_actions(self):
        """PRD §3.7: "referral from any other status is rejected with
        `ERR_COMPLAINT_NOT_DOCKETED` (HTTP 409)" and "Formal adjudication is
        opened by an `AdministrativeLawJudge` on a `DOCKETED` complaint — any
        other status again yields `ERR_COMPLAINT_NOT_DOCKETED`".

        Design: Corner/state_machines/terminal_resolved_complaint_rejects_further_actions
        """
        env = setup_complaint_in_ombuds(officer_id="om-1")
        validate_success(api_client.close_ombuds(
            env["complaint"]["id"],
            {"outcome": "SETTLED", "settlement_amount_cents": 40000},
            make_ombuds_officer_headers("om-1")), 200)

        r1 = api_client.refer_ombuds(env["complaint"]["id"],
                                     {"ombuds_officer_id": "om-2"}, DOCKET)
        validate_error(r1, ApiErrorId.ERR_COMPLAINT_NOT_DOCKETED)
        r2 = api_client.open_adjudication(env["complaint"]["id"],
                                          make_alj_headers("alj-1"))
        validate_error(r2, ApiErrorId.ERR_COMPLAINT_NOT_DOCKETED)

        after = api_client.get_complaint(env["complaint"]["id"], DOCKET).json()["data"]
        assert after["complaint_status"] == "RESOLVED_INFORMAL"
        assert after["informal_settlement_cents"] == 40000

    def test_ombuds_cycle_completes_two_failed_rounds(self):
        """PRD §3.7: "Closing with `outcome` `FAILED` returns the complaint to
        `DOCKETED` and increments `ombuds_rounds` by one, consuming one of the
        two rounds the process allows."

        Design: Difficulty/non_linear_state_machine/complaint_ombuds_cycle_with_round_limit
        """
        env = setup_standard_complaint(claimed=50_000, carrier_name="Cycle Lines")
        cid = env["complaint"]["id"]
        for officer in ("om-1", "om-2"):
            validate_success(api_client.refer_ombuds(
                cid, {"ombuds_officer_id": officer}, DOCKET), 200)
            validate_success(api_client.close_ombuds(
                cid, {"outcome": "FAILED"},
                make_ombuds_officer_headers(officer)), 200)
        after = api_client.get_complaint(cid, DOCKET).json()["data"]
        assert after["complaint_status"] == "DOCKETED"
        assert after["ombuds_rounds"] == 2
        assert after["ombuds_officer_id"] == "om-2", (
            "the most recent round's officer is retained")

    def test_ombuds_third_referral_rejected_at_round_limit(self):
        """PRD §3.7: "referral is permitted only while `ombuds_rounds` stands
        below two — a referral after two completed failed rounds is rejected with
        `ERR_OMBUDS_ROUND_LIMIT_EXCEEDED` (HTTP 409)".

        Design: Difficulty/non_linear_state_machine/complaint_ombuds_cycle_with_round_limit
        """
        env = setup_standard_complaint(claimed=50_000, carrier_name="Cycle Lines")
        cid = env["complaint"]["id"]
        for officer in ("om-1", "om-2"):
            validate_success(api_client.refer_ombuds(
                cid, {"ombuds_officer_id": officer}, DOCKET), 200)
            validate_success(api_client.close_ombuds(
                cid, {"outcome": "FAILED"},
                make_ombuds_officer_headers(officer)), 200)
        resp = api_client.refer_ombuds(cid, {"ombuds_officer_id": "om-3"}, DOCKET)
        validate_error(resp, ApiErrorId.ERR_OMBUDS_ROUND_LIMIT_EXCEEDED)
        after = api_client.get_complaint(cid, DOCKET).json()["data"]
        assert after["complaint_status"] == "DOCKETED", "no state drift"
        assert after["ombuds_rounds"] == 2


class TestComplaintListing:
    def test_complaints_list_paginates_with_total_count_and_has_more(self):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults to
        10 when omitted, accepts a minimum of 1, and accepts a maximum of 100.
        `offset` skips a number of items before the page begins and defaults to
        0." and "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope."
        PRD §3.7: "the listing accepts `shipper_id` and `respondent_carrier_id`
        filters, and its `subject_invoice_ids` parameter carries a single invoice
        identifier and matches the complaints whose subject array contains it."

        Design: Corner/entities/complaints_list_paginates_with_total_count_and_has_more
        """
        env = setup_standard_billing()
        sid = env["shipper"]["id"]
        cid = env["carrier"]["id"]
        inv = env["invoice"]["id"]
        for claimed in (10000, 9000, 8000):
            file_complaint(sid, cid, [inv], reparations_claimed_cents=claimed)

        page1, meta1 = validate_paginated(api_client.list_complaints(
            TEST_USERS["reviewer_headers"],
            params={"shipper_id": sid, "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_complaints(
            TEST_USERS["reviewer_headers"],
            params={"shipper_id": sid, "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_rows, meta3 = validate_paginated(api_client.list_complaints(
            TEST_USERS["reviewer_headers"],
            params={"respondent_carrier_id": cid}))
        assert len(all_rows) == 3, "default limit 10 admits all three"

        by_invoice, meta4 = validate_paginated(api_client.list_complaints(
            TEST_USERS["reviewer_headers"], params={"subject_invoice_ids": inv}))
        assert len(by_invoice) == 3, "array-membership filter matches all three"
        for row in by_invoice:
            assert row["complaint_status"] == "DOCKETED"
