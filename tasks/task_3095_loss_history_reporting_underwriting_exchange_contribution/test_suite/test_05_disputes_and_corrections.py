"""Dispute lifecycle, reinvestigation deadlines, and claim-fate fork tests."""
from test_helpers import (
    ApiErrorId,
    admin,
    compliance,
    create_carrier,
    create_consumer,
    file_dispute,
    get_claim,
    get_success_data,
    init_exchange_rules,
    list_consumer_active_claims,
    make_claim_row,
    make_consumer_headers,
    make_underwriter_headers,
    set_clock,
    setup_active_carrier_with_report,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def _inquiry_payload(consumer, **overrides):
    payload = {
        "subject_name": consumer["full_name"],
        "subject_dob": consumer["date_of_birth"],
        "subject_address": consumer["address_line"],
        "subject_driver_license": consumer["driver_license_number"],
        "permissible_purpose": "UNDERWRITING",
    }
    payload.update(overrides)
    return payload


def _setup_hank(api):
    set_clock()
    init_exchange_rules()
    carrier = create_carrier()
    hank = create_consumer(
        full_name="Hank Hobbs",
        date_of_birth="1969-02-14",
        address_line="8 Hickory Hl, Lubbock TX",
        driver_license_number="HANK-1",
    )
    submit_batch(
        carrier,
        [
            make_claim_row(hank["id"], "H-001", loss_date="2025-01-01", paid_amount_cents=100000),
            make_claim_row(hank["id"], "H-002", loss_date="2025-02-01", cause_of_loss_code="COL2", paid_amount_cents=200000),
            make_claim_row(hank["id"], "H-003", loss_date="2025-03-01", cause_of_loss_code="COL3", paid_amount_cents=300000),
        ],
    )
    carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
    claims = list_consumer_active_claims(hank)
    by_number = {c["claim_number"]: c for c in claims}
    return carrier, hank, by_number


class TestDisputeResolutionFork:
    def test_dispute_resolution_branches_fork_three_distinct_claim_fates(self, api, compliance_headers):
        """PRD §3.7: "`VERIFIED_ACCURATE` returns the claim to `ACTIVE` —
        restoring it to the reportable population — and closes the dispute as
        `RESOLVED_VERIFIED` with a `DISPUTE_RESOLVED` event. `DELETED` moves
        the claim to `WITHDRAWN`, permanently excluding it from all future
        reports, and closes the dispute as `RESOLVED_DELETED` with
        `CLAIM_WITHDRAWN` and `DISPUTE_RESOLVED` events. `AMENDED` creates the
        correcting claim in the same request from the supplied
        `corrected_loss_date`, `corrected_loss_type`,
        `corrected_cause_of_loss_code`, `corrected_paid_amount_cents`,
        `corrected_claim_status_code`, and optional
        `corrected_vehicle_identifier`: the replacement becomes an `ACTIVE`
        claim whose `amendment_of_id` points at the disputed claim and whose
        `retention_expires_on` is freshly computed, the disputed claim becomes
        `AMENDED`, and the dispute closes as `RESOLVED_AMENDED` with
        `CLAIM_AMENDED` and `DISPUTE_RESOLVED` events."

        Design: Difficulty/non_linear_state_machine/dispute_resolution_branches_fork_three_distinct_claim_fates
        """
        carrier, hank, claims = _setup_hank(api)

        d1, hank = file_dispute(hank, claims["H-001"]["id"], dispute_reason="WRONG_AMOUNT", dispute_statement="Amount is wrong")
        d2, hank = file_dispute(hank, claims["H-002"]["id"], dispute_reason="WRONG_DATE", dispute_statement="Date is wrong")
        d3, hank = file_dispute(hank, claims["H-003"]["id"], dispute_reason="NOT_MY_CLAIM", dispute_statement="Not mine")
        for d in (d1, d2, d3):
            validate_success(api.begin_reinvestigation(d["id"], compliance_headers), 200)

        r1 = validate_success(
            api.resolve_dispute(d1["id"], {"resolution_code": "VERIFIED_ACCURATE", "resolution_notes": "Verified with carrier"}, compliance_headers),
            200,
        )
        assert r1["status"] == "RESOLVED_VERIFIED"
        assert get_claim(claims["H-001"]["id"])["status"] == "ACTIVE"

        r2 = validate_success(
            api.resolve_dispute(
                d2["id"],
                {
                    "resolution_code": "AMENDED",
                    "resolution_notes": "Date corrected",
                    "corrected_loss_date": "2025-02-15",
                    "corrected_loss_type": "COLLISION",
                    "corrected_cause_of_loss_code": "COL2",
                    "corrected_paid_amount_cents": 200000,
                    "corrected_claim_status_code": "CLOSED_WITH_PAYMENT",
                },
                compliance_headers,
            ),
            200,
        )
        assert r2["status"] == "RESOLVED_AMENDED"
        assert get_claim(claims["H-002"]["id"])["status"] == "AMENDED"
        amendments, _ = validate_paginated(
            api.list_claim_amendments(claims["H-002"]["id"], compliance_headers)
        )
        assert len(amendments) == 1
        assert amendments[0]["amendment_of_id"] == claims["H-002"]["id"]
        assert amendments[0]["loss_date"] == "2025-02-15"
        assert amendments[0]["status"] == "ACTIVE"

        r3 = validate_success(
            api.resolve_dispute(d3["id"], {"resolution_code": "DELETED", "resolution_notes": "Wrong household"}, compliance_headers),
            200,
        )
        assert r3["status"] == "RESOLVED_DELETED"
        assert get_claim(claims["H-003"]["id"])["status"] == "WITHDRAWN"

        active, _ = validate_paginated(
            api.list_consumer_claims(hank["id"], compliance_headers, params={"status": "ACTIVE"})
        )
        assert len(active) == 2
        withdrawn, _ = validate_paginated(
            api.list_consumer_claims(hank["id"], compliance_headers, params={"status": "WITHDRAWN"})
        )
        assert len(withdrawn) == 1

    def test_dispute_resolution_fork_amended_branch_creates_active_replacement(self, api, compliance_headers):
        """PRD §3.7: "`AMENDED` creates the correcting claim in the same
        request from the supplied `corrected_loss_date`, `corrected_loss_type`,
        `corrected_cause_of_loss_code`, `corrected_paid_amount_cents`,
        `corrected_claim_status_code`, and optional
        `corrected_vehicle_identifier`: the replacement becomes an `ACTIVE`
        claim whose `amendment_of_id` points at the disputed claim and whose
        `retention_expires_on` is freshly computed, the disputed claim becomes
        `AMENDED`, and the dispute closes as `RESOLVED_AMENDED` with
        `CLAIM_AMENDED` and `DISPUTE_RESOLVED` events."
        PRD §3.7: "`VERIFIED_ACCURATE` returns the claim to `ACTIVE` —
        restoring it to the reportable population — and closes the dispute as
        `RESOLVED_VERIFIED` with a `DISPUTE_RESOLVED` event."

        Design: Difficulty/non_linear_state_machine/dispute_resolution_branches_fork_three_distinct_claim_fates
        """
        carrier, hank, claims = _setup_hank(api)
        d1, hank = file_dispute(hank, claims["H-001"]["id"], dispute_reason="WRONG_AMOUNT")
        d2, hank = file_dispute(hank, claims["H-002"]["id"], dispute_reason="WRONG_DATE")
        validate_success(api.begin_reinvestigation(d1["id"], compliance_headers), 200)
        validate_success(api.begin_reinvestigation(d2["id"], compliance_headers), 200)

        validate_success(
            api.resolve_dispute(d1["id"], {"resolution_code": "VERIFIED_ACCURATE", "resolution_notes": "ok"}, compliance_headers),
            200,
        )
        assert get_claim(claims["H-001"]["id"])["status"] == "ACTIVE"

        validate_success(
            api.resolve_dispute(
                d2["id"],
                {
                    "resolution_code": "AMENDED",
                    "resolution_notes": "Date corrected",
                    "corrected_loss_date": "2025-02-15",
                    "corrected_loss_type": "COLLISION",
                    "corrected_cause_of_loss_code": "COL2",
                    "corrected_paid_amount_cents": 200000,
                    "corrected_claim_status_code": "CLOSED_WITH_PAYMENT",
                },
                compliance_headers,
            ),
            200,
        )
        assert get_claim(claims["H-002"]["id"])["status"] == "AMENDED"
        active, _ = validate_paginated(
            api.list_consumer_claims(hank["id"], compliance_headers, params={"status": "ACTIVE"})
        )
        assert len(active) == 3  # H-001 back + H-003 untouched + replacement of H-002


class TestDisputeDeadlineAndCap:
    def test_dispute_overdue_inclusive_deadline_vs_outstanding_cap_boundary(self, api, compliance_headers):
        """PRD §3.7: "Both actions require the logical clock to be strictly
        before `reinvestigation_due_at` — at or past the deadline the boundary
        is inclusive and the action is rejected with `ERR_DISPUTE_OVERDUE`
        (HTTP 409)."
        PRD §3.8: "The exchange caps concurrent consumer-impact activity: a
        carrier's outstanding notices — those in `DRAFT` or `SENT` — may not
        reach `max_outstanding_inquiries`. The boundary is inclusive, so when a
        carrier's outstanding count already equals the cap, the next filing and
        the next send are both rejected with `ERR_INQUIRY_CAP_EXCEEDED` (HTTP
        409)."

        Design: Difficulty/boundary_precision_check/dispute_overdue_inclusive_deadline_vs_outstanding_cap_boundary
        """
        from test_helpers import create_notice_for_report

        set_clock()
        init_exchange_rules(max_outstanding_inquiries=1)
        carrier = create_carrier()
        nora = create_consumer(
            full_name="Nora Nolan",
            date_of_birth="1986-06-06",
            address_line="5 Nutmeg St, Midland TX",
            driver_license_number="NORA-1",
        )
        submit_batch(carrier, [make_claim_row(nora["id"], "N-001", loss_date="2025-07-07", paid_amount_cents=45000)])
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        claim = list_consumer_active_claims(nora)[0]
        dispute, nora = file_dispute(nora, claim["id"], dispute_reason="WRONG_AMOUNT", dispute_statement="Wrong amount")
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(nora), uw), 201)
        notice = create_notice_for_report(carrier, inq["report_id"], action_type="NON_RENEWAL", report_influence_rank=2)
        validate_success(api.send_notice(notice["id"], uw), 200)

        # At exactly reinvestigation_due_at the boundary is inclusive: overdue.
        set_clock("2026-10-01T00:00:00Z")
        begin_resp = api.begin_reinvestigation(dispute["id"], compliance_headers)
        validate_error(begin_resp, ApiErrorId.ERR_DISPUTE_OVERDUE, 409)

        # Outstanding == cap: the next filing fails.
        file_resp = api.create_notice(
            carrier["id"],
            {"report_id": inq["report_id"], "action_type": "DECLINE", "notice_reason_codes": ["LOSS-SEV"], "report_influence_rank": 1},
            uw,
        )
        validate_error(file_resp, ApiErrorId.ERR_INQUIRY_CAP_EXCEEDED, 409)

        still = get_success_data(api.get_dispute(dispute["id"], compliance_headers))
        assert still["status"] == "FILED"

    def test_dispute_overdue_deadline_inclusive_and_cap_inclusive(self, api, compliance_headers):
        """PRD §3.7: "Both actions require the logical clock to be strictly
        before `reinvestigation_due_at` — at or past the deadline the boundary
        is inclusive and the action is rejected with `ERR_DISPUTE_OVERDUE`
        (HTTP 409)."
        PRD §3.8: "The exchange caps concurrent consumer-impact activity: a
        carrier's outstanding notices — those in `DRAFT` or `SENT` — may not
        reach `max_outstanding_inquiries`. The boundary is inclusive, so when a
        carrier's outstanding count already equals the cap, the next filing and
        the next send are both rejected with `ERR_INQUIRY_CAP_EXCEEDED` (HTTP
        409)."

        Design: Difficulty/boundary_precision_check/dispute_overdue_inclusive_deadline_vs_outstanding_cap_boundary
        """
        from test_helpers import create_notice_for_report

        set_clock()
        init_exchange_rules(max_outstanding_inquiries=1)
        carrier = create_carrier()
        nora = create_consumer(
            full_name="Nora Nolan",
            date_of_birth="1986-06-06",
            address_line="5 Nutmeg St, Midland TX",
            driver_license_number="NORA-1",
        )
        submit_batch(carrier, [make_claim_row(nora["id"], "N-001", loss_date="2025-07-07", paid_amount_cents=45000)])
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        claim = list_consumer_active_claims(nora)[0]
        dispute, nora = file_dispute(nora, claim["id"], dispute_reason="WRONG_AMOUNT", dispute_statement="Wrong amount")
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(nora), uw), 201)
        create_notice_for_report(carrier, inq["report_id"], action_type="NON_RENEWAL", report_influence_rank=2)

        # Second filing at outstanding == cap == 1 fails even in DRAFT.
        file_resp = api.create_notice(
            carrier["id"],
            {"report_id": inq["report_id"], "action_type": "DECLINE", "notice_reason_codes": ["LOSS-SEV"], "report_influence_rank": 1},
            uw,
        )
        validate_error(file_resp, ApiErrorId.ERR_INQUIRY_CAP_EXCEEDED, 409)

        # Resolve is equally closed at the inclusive deadline.
        set_clock("2026-10-01T00:00:00Z")
        resolve_resp = api.resolve_dispute(
            dispute["id"], {"resolution_code": "VERIFIED_ACCURATE", "resolution_notes": "late"}, compliance_headers
        )
        validate_error(resolve_resp, ApiErrorId.ERR_DISPUTE_OVERDUE, 409)
        still = get_success_data(api.get_dispute(dispute["id"], compliance_headers))
        assert still["status"] == "FILED"


class TestDisputeExclusion:
    def test_under_dispute_claims_are_excluded_from_new_reports(self, api, compliance_headers):
        """PRD §3.5: "Its inclusion set is then determined: all of the matched
        consumer's loss claims whose status is `ACTIVE`, whose contributing
        carrier is not `WITHDRAWN`, and whose `loss_date` is strictly newer
        than the logical clock date minus `retention_years` years."
        PRD §3.5: "Claims under dispute are outside the inclusion set because
        they are not `ACTIVE`."

        Design: Corner/calculations/under_dispute_claims_are_excluded_from_new_reports
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        fay = create_consumer(
            full_name="Fay Farrell",
            date_of_birth="1979-06-17",
            address_line="24 Fern St, Denton TX",
            driver_license_number="FAY2-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(fay["id"], "F2-1", loss_date="2025-04-01", cause_of_loss_code="FF1", paid_amount_cents=44000),
                make_claim_row(fay["id"], "F2-2", loss_date="2025-05-01", loss_type="PROPERTY", cause_of_loss_code="FF2", paid_amount_cents=55000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        inq1 = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(fay), uw), 201)
        rep1 = get_success_data(api.get_report(inq1["report_id"], uw))
        assert rep1["claim_count_reported"] == 2

        claims = list_consumer_active_claims(fay)
        target = next(c for c in claims if c["claim_number"] == "F2-2")
        file_dispute(fay, target["id"], dispute_reason="WRONG_AMOUNT", dispute_statement="Wrong amount")

        inq2 = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(fay), uw), 201)
        rep2 = get_success_data(api.get_report(inq2["report_id"], uw))
        assert rep2["claim_count_reported"] == 1
        entries, _ = validate_paginated(api.list_report_entries_for_report(rep2["id"], compliance_headers))
        assert len(entries) == 1
        assert entries[0]["cause_of_loss_code"] == "FF1"


class TestAmendmentConservation:
    def test_amendment_preserves_total_reportable_loss_count_for_consumer(self, api, compliance_headers):
        """PRD §3.7: "A `CarrierDataSteward` may file a replacement claim
        superseding an `ACTIVE` claim their carrier contributed, supplying
        fresh `loss_date`, `loss_type`, `cause_of_loss_code`,
        `paid_amount_cents`, `claim_status_code`, and optionally
        `vehicle_identifier`, together with `expected_claim_version` per §2.11.
        The replacement is born `ACTIVE` with `amendment_of_id` set to the
        superseded claim and a fresh `retention_expires_on`; the superseded
        claim transitions automatically to `AMENDED` and leaves the reportable
        population, and its `version` increments by one."

        Design: Difficulty/compensating_invariant/amendment_preserves_total_reportable_loss_count_for_consumer
        """
        from test_helpers import make_data_steward_headers

        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        tina = create_consumer(
            full_name="Tina Tatum",
            date_of_birth="1989-12-01",
            address_line="63 Tulip Trl, Garland TX",
            driver_license_number="TINA-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(tina["id"], "T-001", loss_date="2025-04-04", loss_type="PROPERTY", paid_amount_cents=110000),
                make_claim_row(tina["id"], "T-002", loss_date="2025-05-05", loss_type="PROPERTY", paid_amount_cents=120000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        claim1 = next(c for c in list_consumer_active_claims(tina) if c["claim_number"] == "T-001")

        inq_before = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(tina), uw), 201)
        rep_before = get_success_data(api.get_report(inq_before["report_id"], uw))
        assert rep_before["claim_count_reported"] == 2

        amend = validate_success(
            api.create_claim_amendment(
                claim1["id"],
                {
                    "loss_date": "2025-04-04",
                    "loss_type": "PROPERTY",
                    "cause_of_loss_code": claim1["cause_of_loss_code"],
                    "paid_amount_cents": 115000,
                    "claim_status_code": "CLOSED_WITH_PAYMENT",
                    "expected_claim_version": claim1["version"],
                },
                make_data_steward_headers(carrier["id"]),
            ),
            201,
        )
        assert amend["amendment_of_id"] == claim1["id"]
        assert amend["status"] == "ACTIVE"
        assert get_claim(claim1["id"])["status"] == "AMENDED"

        inq_after = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(tina), uw), 201)
        rep_after = get_success_data(api.get_report(inq_after["report_id"], uw))
        assert rep_after["claim_count_reported"] == 2
        entries, _ = validate_paginated(api.list_report_entries_for_report(rep_after["id"], compliance_headers))
        paid = sorted(e["paid_amount_cents"] for e in entries)
        assert paid == [115000, 120000]

    def test_amendment_pair_is_atomic_and_leaves_count_unchanged(self, api, compliance_headers):
        """PRD §3.7: "A `CarrierDataSteward` may file a replacement claim
        superseding an `ACTIVE` claim their carrier contributed, supplying
        fresh `loss_date`, `loss_type`, `cause_of_loss_code`,
        `paid_amount_cents`, `claim_status_code`, and optionally
        `vehicle_identifier`, together with `expected_claim_version` per §2.11.
        The replacement is born `ACTIVE` with `amendment_of_id` set to the
        superseded claim and a fresh `retention_expires_on`; the superseded
        claim transitions automatically to `AMENDED` and leaves the reportable
        population, and its `version` increments by one."
        PRD §3.5: "Its inclusion set is then determined: all of the matched
        consumer's loss claims whose status is `ACTIVE`, whose contributing
        carrier is not `WITHDRAWN`, and whose `loss_date` is strictly newer
        than the logical clock date minus `retention_years` years."

        Design: Difficulty/compensating_invariant/amendment_preserves_total_reportable_loss_count_for_consumer
        """
        from test_helpers import make_data_steward_headers

        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        tina = create_consumer(
            full_name="Tina Tatum",
            date_of_birth="1989-12-01",
            address_line="63 Tulip Trl, Garland TX",
            driver_license_number="TINA-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(tina["id"], "T-001", loss_date="2025-04-04", loss_type="PROPERTY", paid_amount_cents=110000),
                make_claim_row(tina["id"], "T-002", loss_date="2025-05-05", loss_type="PROPERTY", paid_amount_cents=120000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        claim1 = next(c for c in list_consumer_active_claims(tina) if c["claim_number"] == "T-001")
        validate_success(
            api.create_claim_amendment(
                claim1["id"],
                {
                    "loss_date": "2025-04-04",
                    "loss_type": "PROPERTY",
                    "cause_of_loss_code": claim1["cause_of_loss_code"],
                    "paid_amount_cents": 115000,
                    "claim_status_code": "CLOSED_WITH_PAYMENT",
                    "expected_claim_version": claim1["version"],
                },
                make_data_steward_headers(carrier["id"]),
            ),
            201,
        )
        active, _ = validate_paginated(
            api.list_consumer_claims(tina["id"], compliance_headers, params={"status": "ACTIVE"})
        )
        assert len(active) == 2
        amended, _ = validate_paginated(
            api.list_consumer_claims(tina["id"], compliance_headers, params={"status": "AMENDED"})
        )
        assert len(amended) == 1
        assert amended[0]["id"] == claim1["id"]


class TestDisputeCycleConservation:
    def test_dispute_cycle_verified_accurate_conserves_consumer_claim_population(self, api, compliance_headers):
        """PRD §3.7: "`VERIFIED_ACCURATE` returns the claim to `ACTIVE` —
        restoring it to the reportable population — and closes the dispute as
        `RESOLVED_VERIFIED` with a `DISPUTE_RESOLVED` event."
        PRD §3.5: "Its inclusion set is then determined: all of the matched
        consumer's loss claims whose status is `ACTIVE`, whose contributing
        carrier is not `WITHDRAWN`, and whose `loss_date` is strictly newer
        than the logical clock date minus `retention_years` years."

        Design: Difficulty/compensating_invariant/dispute_cycle_verified_accurate_conserves_consumer_claim_population
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        uma = create_consumer(
            full_name="Uma Ulrich",
            date_of_birth="1974-11-30",
            address_line="5 Umber Ave, McKinney TX",
            driver_license_number="UMA-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(uma["id"], "U-001", loss_date="2025-06-06", loss_type="LIABILITY", paid_amount_cents=200000)],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        claim = list_consumer_active_claims(uma)[0]

        inq_before = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(uma), uw), 201)
        rep_before = get_success_data(api.get_report(inq_before["report_id"], uw))
        assert rep_before["claim_count_reported"] == 1

        dispute, uma = file_dispute(uma, claim["id"], dispute_reason="NOT_MY_CLAIM", dispute_statement="I dispute this")
        validate_success(api.begin_reinvestigation(dispute["id"], compliance_headers), 200)
        validate_success(
            api.resolve_dispute(dispute["id"], {"resolution_code": "VERIFIED_ACCURATE", "resolution_notes": "Carrier confirmed"}, compliance_headers),
            200,
        )

        after = get_claim(claim["id"])
        assert after["status"] == "ACTIVE"
        assert after["paid_amount_cents"] == 200000

        inq_after = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(uma), uw), 201)
        rep_after = get_success_data(api.get_report(inq_after["report_id"], uw))
        assert rep_after["claim_count_reported"] == rep_before["claim_count_reported"]
        assert rep_after["risk_score_premium_weighted_cents"] == rep_before["risk_score_premium_weighted_cents"]

    def test_dispute_cycle_zero_drift_on_scores(self, api, compliance_headers):
        """PRD §3.7: "`VERIFIED_ACCURATE` returns the claim to `ACTIVE` —
        restoring it to the reportable population — and closes the dispute as
        `RESOLVED_VERIFIED` with a `DISPUTE_RESOLVED` event."
        PRD §3.5: "The severity variant, `risk_score_premium_weighted_cents`,
        first caps each included claim's `paid_amount_cents` at
        `premium_weight_cap_cents`, sums the capped amounts, multiplies by
        `risk_score_certainty`, divides by 100, and rounds half up to integer
        cents"

        Design: Difficulty/compensating_invariant/dispute_cycle_verified_accurate_conserves_consumer_claim_population
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        uma = create_consumer(
            full_name="Uma Ulrich",
            date_of_birth="1974-11-30",
            address_line="5 Umber Ave, McKinney TX",
            driver_license_number="UMA-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(uma["id"], "U-001", loss_date="2025-06-06", loss_type="LIABILITY", paid_amount_cents=200000)],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        claim = list_consumer_active_claims(uma)[0]

        inq_before = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(uma), uw), 201)
        rep_before = get_success_data(api.get_report(inq_before["report_id"], uw))

        dispute, uma = file_dispute(uma, claim["id"], dispute_reason="NOT_MY_CLAIM")
        validate_success(api.begin_reinvestigation(dispute["id"], compliance_headers), 200)
        validate_success(
            api.resolve_dispute(dispute["id"], {"resolution_code": "VERIFIED_ACCURATE", "resolution_notes": "ok"}, compliance_headers),
            200,
        )
        inq_after = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(uma), uw), 201)
        rep_after = get_success_data(api.get_report(inq_after["report_id"], uw))
        assert rep_after["risk_score_certainty"] == rep_before["risk_score_certainty"]
        assert rep_after["risk_score_count"] == rep_before["risk_score_count"]
        assert rep_after["claim_count_reported"] == rep_before["claim_count_reported"]
