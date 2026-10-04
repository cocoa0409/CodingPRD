"""Inquiry identity matching, disposition ladder, and risk scoring tests."""
from test_helpers import (
    admin,
    compliance,
    create_carrier,
    create_consumer,
    get_success_data,
    init_exchange_rules,
    make_claim_row,
    make_underwriter_headers,
    set_clock,
    setup_active_carrier_with_report,
    submit_batch,
    submit_inquiry,
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


class TestMatchScoreBands:
    def test_identity_match_score_multisignal_threshold_band_ladder(self, api):
        """PRD §3.4: "Each signal is graded `EXACT`, `FUZZY`, `MISMATCH`, or
        `ABSENT`, worth 50, 25, 0, and 0 points respectively. The individual
        match grade is taken from the strongest individual signal: the driver
        license comparison dominates, so a license match yields an `EXACT`
        individual grade; when the inquiry supplies no driver license, or no
        candidate matches it, the individual grade falls back to the
        name-plus-date-of-birth comparison, which grades at most `FUZZY`."
        PRD §3.4: "The score maps to a four-rung disposition ladder with
        inclusive lower bounds: at least 7000 yields `DEFINITE`, at least 5500
        yields `PROBABLE`, at least 4000 yields `POSSIBLE`, and anything below
        4000 yields `UNMATCHED`."

        Design: Difficulty/combinatorial_formula/identity_match_score_multisignal_threshold_band_ladder
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        dana = create_consumer(
            full_name="Dana Draper",
            date_of_birth="1988-08-08",
            address_line="40 Birch Ln, Plano TX",
            driver_license_number="DANA-1",
        )
        erin = create_consumer(
            full_name="Erin Ellery",
            date_of_birth="1992-03-03",
            address_line="9 Cedar Ct, Plano TX",
            driver_license_number="ERIN-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(
                    erin["id"],
                    "E-001",
                    loss_date="2025-05-05",
                    loss_type="OTHER",
                    paid_amount_cents=10000,
                    vehicle_identifier="VIN-ERIN-1",
                )
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        exact = validate_success(
            api.create_inquiry(carrier["id"], _inquiry_payload(dana), uw), 201
        )
        assert exact["individual_match_grade"] == "EXACT"
        assert exact["address_match_grade"] == "EXACT"
        assert exact["vehicle_match_grade"] == "ABSENT"
        assert exact["match_score"] == 6000
        assert exact["match_disposition"] == "PROBABLE"

        fuzzy_no_address = validate_success(
            api.create_inquiry(
                carrier["id"],
                _inquiry_payload(
                    dana,
                    subject_address="555 Nowhere Pkwy, El Paso TX",
                    subject_driver_license="",
                ),
                uw,
            ),
            201,
        )
        assert fuzzy_no_address["individual_match_grade"] == "FUZZY"
        assert fuzzy_no_address["address_match_grade"] == "ABSENT"
        assert fuzzy_no_address["match_score"] == 1250
        assert fuzzy_no_address["match_disposition"] == "UNMATCHED"
        assert fuzzy_no_address["matched_consumer_id"] is None
        assert fuzzy_no_address["report_id"] is None

        fuzzy_with_address = validate_success(
            api.create_inquiry(
                carrier["id"], _inquiry_payload(dana, subject_driver_license=""), uw
            ),
            201,
        )
        assert fuzzy_with_address["individual_match_grade"] == "FUZZY"
        assert fuzzy_with_address["address_match_grade"] == "EXACT"
        assert fuzzy_with_address["match_score"] == 2250
        assert fuzzy_with_address["match_disposition"] == "UNMATCHED"

        nobody = validate_success(
            api.create_inquiry(
                carrier["id"],
                {
                    "subject_name": "Xavier Yates",
                    "subject_dob": "1970-01-01",
                    "subject_address": "1 Nowhere Blvd, El Paso TX",
                    "subject_driver_license": "NOBODY-9",
                    "permissible_purpose": "UNDERWRITING",
                },
                uw,
            ),
            201,
        )
        assert nobody["match_score"] == 0
        assert nobody["match_disposition"] == "UNMATCHED"
        assert nobody["report_blocked_reason"] == "NONE"

    def test_identity_match_score_unmatched_inquiry_carries_no_report(self, api):
        """PRD §3.4: "An `UNMATCHED` inquiry resolves with `matched_consumer_id`
        null, no report, and `report_blocked_reason` of `NONE`."
        PRD §3.4: "a `FUZZY` individual grade from a name-and-birthdate-only
        match caps the achievable band at `POSSIBLE` unless the vehicle and
        address signals both grade `EXACT` — this asymmetry is the exchange's
        guard against attributing another household's losses to an applicant."

        Design: Difficulty/combinatorial_formula/identity_match_score_multisignal_threshold_band_ladder
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        dana = create_consumer(
            full_name="Dana Draper",
            date_of_birth="1988-08-08",
            address_line="40 Birch Ln, Plano TX",
            driver_license_number="DANA-1",
        )
        erin = create_consumer(
            full_name="Erin Ellery",
            date_of_birth="1992-03-03",
            address_line="9 Cedar Ct, Plano TX",
            driver_license_number="ERIN-1",
        )
        submit_batch(
            carrier,
            [make_claim_row(erin["id"], "E-001", loss_date="2025-05-05", paid_amount_cents=10000)],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        fuzzy = validate_success(
            api.create_inquiry(
                carrier["id"],
                _inquiry_payload(
                    dana,
                    subject_address="555 Nowhere Pkwy, El Paso TX",
                    subject_driver_license="",
                ),
                uw,
            ),
            201,
        )
        assert fuzzy["individual_match_grade"] == "FUZZY"
        assert fuzzy["match_disposition"] == "UNMATCHED"
        assert fuzzy["matched_consumer_id"] is None
        assert fuzzy["report_id"] is None
        assert fuzzy["report_blocked_reason"] == "NONE"


class TestDispositionBoundaries:
    def test_match_disposition_threshold_inclusive_at_7000_and_5500(self, api):
        """PRD §3.4: "The score maps to a four-rung disposition ladder with
        inclusive lower bounds: at least 7000 yields `DEFINITE`, at least 5500
        yields `PROBABLE`, at least 4000 yields `POSSIBLE`, and anything below
        4000 yields `UNMATCHED`."

        Design: Difficulty/boundary_precision_check/match_disposition_threshold_inclusive_at_7000_and_5500
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        bea = create_consumer(
            full_name="Bea Bounds",
            date_of_birth="1984-01-01",
            address_line="1 Boundary St, Houston TX",
            driver_license_number="B7-DL",
        )
        bo = create_consumer(
            full_name="Bo Bond",
            date_of_birth="1984-02-02",
            address_line="2 Boundary St, Houston TX",
            driver_license_number="B55-DL",
        )
        bund = create_consumer(
            full_name="Bo Bund",
            date_of_birth="1984-03-03",
            address_line="3 Boundary St, Houston TX",
            driver_license_number="B545-DL",
        )
        rows = []
        for i in range(1, 21):
            rows.append(
                make_claim_row(bea["id"], f"B7-{i:02d}", loss_date=f"2025-01-{i:02d}", loss_type="OTHER", cause_of_loss_code="O1", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT")
            )
        for i in range(1, 11):
            rows.append(
                make_claim_row(bo["id"], f"B55-{i:02d}", loss_date=f"2025-02-{i:02d}", loss_type="OTHER", cause_of_loss_code="O2", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT")
            )
        for i in range(1, 10):
            rows.append(
                make_claim_row(bund["id"], f"B545-{i:02d}", loss_date=f"2025-03-{i:02d}", loss_type="OTHER", cause_of_loss_code="O3", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT")
            )
        submit_batch(carrier, rows)
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        inq_bea = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(bea), uw), 201)
        assert inq_bea["match_score"] == 7000
        assert inq_bea["match_disposition"] == "DEFINITE"

        inq_bo = validate_success(
            api.create_inquiry(
                carrier["id"],
                _inquiry_payload(bo, subject_address="999 Vacant Lot, Houston TX"),
                uw,
            ),
            201,
        )
        assert inq_bo["match_score"] == 5500
        assert inq_bo["address_match_grade"] == "ABSENT"
        assert inq_bo["match_disposition"] == "PROBABLE"

        inq_bund = validate_success(
            api.create_inquiry(
                carrier["id"],
                _inquiry_payload(bund, subject_address="998 Vacant Lot, Houston TX"),
                uw,
            ),
            201,
        )
        assert inq_bund["match_score"] == 5450
        assert inq_bund["match_disposition"] == "POSSIBLE"

    def test_match_disposition_exactly_7000_definite_and_5450_possible(self, api):
        """PRD §3.4: "The score maps to a four-rung disposition ladder with
        inclusive lower bounds: at least 7000 yields `DEFINITE`, at least 5500
        yields `PROBABLE`, at least 4000 yields `POSSIBLE`, and anything below
        4000 yields `UNMATCHED`."

        Design: Difficulty/boundary_precision_check/match_disposition_threshold_inclusive_at_7000_and_5500
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        bea = create_consumer(
            full_name="Bea Bounds",
            date_of_birth="1984-01-01",
            address_line="1 Boundary St, Houston TX",
            driver_license_number="B7-DL",
        )
        bund = create_consumer(
            full_name="Bo Bund",
            date_of_birth="1984-03-03",
            address_line="3 Boundary St, Houston TX",
            driver_license_number="B545-DL",
        )
        rows = [
            make_claim_row(bea["id"], f"B7-{i:02d}", loss_date=f"2025-01-{i:02d}", loss_type="OTHER", cause_of_loss_code="O1", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT")
            for i in range(1, 21)
        ] + [
            make_claim_row(bund["id"], f"B545-{i:02d}", loss_date=f"2025-03-{i:02d}", loss_type="OTHER", cause_of_loss_code="O3", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT")
            for i in range(1, 10)
        ]
        submit_batch(carrier, rows)
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        inq_bea = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(bea), uw), 201)
        assert inq_bea["match_score"] == 7000
        assert inq_bea["match_disposition"] == "DEFINITE"
        # A DEFINITE disposition still issues a report.
        assert inq_bea["report_id"] is not None

        inq_bund = validate_success(
            api.create_inquiry(
                carrier["id"],
                _inquiry_payload(bund, subject_address="998 Vacant Lot, Houston TX"),
                uw,
            ),
            201,
        )
        assert inq_bund["match_score"] == 5450
        assert inq_bund["match_disposition"] == "POSSIBLE"
        assert inq_bund["report_id"] is not None


class TestDualRiskScores:
    def test_risk_score_count_vs_premium_weighted_diverge_on_same_report(self, api):
        """PRD §3.5: "The frequency variant, `risk_score_count`, is
        `claim_count_reported` multiplied by `risk_score_certainty`, rounded
        half up to an integer; it drives claim-frequency-based pricing, so a
        consumer with three zero-payment claims scores higher than one with a
        single large paid loss. The severity variant,
        `risk_score_premium_weighted_cents`, first caps each included claim's
        `paid_amount_cents` at `premium_weight_cap_cents`, sums the capped
        amounts, multiplies by `risk_score_certainty`, divides by 100, and
        rounds half up to integer cents; it drives severity-based pricing, so
        a single large loss outweighs several small ones."

        Design: Difficulty/dual_variant_calc/risk_score_count_vs_premium_weighted_diverge_on_same_report
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        alice = create_consumer(
            full_name="Alice Anderson",
            date_of_birth="1985-04-12",
            address_line="10 Elm St, Austin TX",
            driver_license_number="ALICE-1",
        )
        bob = create_consumer(
            full_name="Bob Barker",
            date_of_birth="1979-11-02",
            address_line="20 Oak Ave, Austin TX",
            driver_license_number="BOB-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(alice["id"], "A-001", loss_date="2025-01-10", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT"),
                make_claim_row(alice["id"], "A-002", loss_date="2025-02-10", loss_type="COMPREHENSIVE", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT"),
                make_claim_row(alice["id"], "A-003", loss_date="2025-03-10", loss_type="LIABILITY", paid_amount_cents=0, claim_status_code="CLOSED_WITHOUT_PAYMENT"),
                make_claim_row(bob["id"], "B-001", loss_date="2025-01-15", paid_amount_cents=400000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])

        inq_a = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(alice), uw), 201)
        inq_b = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(bob), uw), 201)
        assert inq_a["match_disposition"] == "PROBABLE"
        assert inq_a["match_score"] == 6150

        rep_a = get_success_data(api.get_report(inq_a["report_id"], uw))
        rep_b = get_success_data(api.get_report(inq_b["report_id"], uw))
        assert rep_a["risk_score_certainty"] == 61.50
        assert rep_a["risk_score_count"] == 185
        assert rep_a["risk_score_premium_weighted_cents"] == 0
        assert rep_b["risk_score_certainty"] == 60.50
        assert rep_b["risk_score_count"] == 61
        assert rep_b["risk_score_premium_weighted_cents"] == 242000
        # The two variants rank the two consumers in opposite orders.
        assert rep_a["risk_score_count"] > rep_b["risk_score_count"]
        assert rep_a["risk_score_premium_weighted_cents"] < rep_b["risk_score_premium_weighted_cents"]

    def test_risk_score_variants_both_persisted_on_report(self, api):
        """PRD §3.5: "The two variants are always computed together and diverge
        whenever the average capped paid amount per claim differs from 100
        cents — which is to say, almost always."
        PRD §3.5: "The identity certainty, `risk_score_certainty`, is the
        inquiry's `match_score` divided by 100 and expressed with exactly two
        decimals, rounded half up — a `match_score` of 7550 yields 75.50"

        Design: Difficulty/dual_variant_calc/risk_score_count_vs_premium_weighted_diverge_on_same_report
        """
        ctx = setup_active_carrier_with_report(
            claim_overrides={"loss_date": "2025-02-14", "paid_amount_cents": 100000},
        )
        carrier, consumer, report = ctx["carrier"], ctx["consumer"], ctx["report"]
        assert report is not None
        assert report["risk_score_certainty"] == 60.50
        assert report["risk_score_count"] == 61
        assert report["risk_score_premium_weighted_cents"] == 60500
        assert report["claim_count_reported"] == 1
        assert report["consumer_id"] == consumer["id"]
        assert report["carrier_id"] == carrier["id"]


class TestRoundingOrder:
    def test_risk_score_rounding_order_is_per_claim_cap_then_weight_then_round(self, api):
        """PRD §3.5: "The severity variant,
        `risk_score_premium_weighted_cents`, first caps each included claim's
        `paid_amount_cents` at `premium_weight_cap_cents`, sums the capped
        amounts, multiplies by `risk_score_certainty`, divides by 100, and
        rounds half up to integer cents"

        Design: Difficulty/combinatorial_formula/risk_score_rounding_order_is_per_claim_cap_then_weight_then_round
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        fay = create_consumer(
            full_name="Fay Fontaine",
            date_of_birth="1980-12-25",
            address_line="77 Maple Dr, Irving TX",
            driver_license_number="FAY-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(fay["id"], "F-001", loss_date="2024-04-01", loss_type="LIABILITY", paid_amount_cents=900000),
                make_claim_row(fay["id"], "F-002", loss_date="2024-05-01", paid_amount_cents=250000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        inq = validate_success(
            api.create_inquiry(carrier["id"], _inquiry_payload(fay), make_underwriter_headers(carrier["id"])),
            201,
        )
        report = get_success_data(api.get_report(inq["report_id"], make_underwriter_headers(carrier["id"])))
        assert report["risk_score_certainty"] == 61.00
        # (min(900000,500000) + min(250000,500000)) x 61.00 / 100 = 457500
        assert report["risk_score_premium_weighted_cents"] == 457500
        assert report["risk_score_premium_weighted_cents"] != 701500
        assert report["claim_count_reported"] == 2
        assert report["risk_score_count"] == 122

    def test_risk_score_cap_applied_per_claim_before_sum(self, api):
        """PRD §3.5: "The severity variant,
        `risk_score_premium_weighted_cents`, first caps each included claim's
        `paid_amount_cents` at `premium_weight_cap_cents`, sums the capped
        amounts, multiplies by `risk_score_certainty`, divides by 100, and
        rounds half up to integer cents"

        Design: Difficulty/combinatorial_formula/risk_score_rounding_order_is_per_claim_cap_then_weight_then_round
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        consumer = create_consumer(
            full_name="Fay Fontaine",
            date_of_birth="1980-12-25",
            address_line="77 Maple Dr, Irving TX",
            driver_license_number="FAY-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(consumer["id"], "F-001", loss_date="2024-04-01", loss_type="LIABILITY", paid_amount_cents=900000),
                make_claim_row(consumer["id"], "F-002", loss_date="2024-05-01", paid_amount_cents=250000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(consumer), uw), 201)
        report = get_success_data(api.get_report(inq["report_id"], uw))
        # Uncapped order would give 1150000 x 0.61 = 701500; capped order is 457500.
        assert report["risk_score_premium_weighted_cents"] == 457500
        entries, _ = validate_paginated(api.list_report_entries_for_report(report["id"], compliance()))
        assert {e["paid_amount_cents"] for e in entries} == {900000, 250000}


class TestEntryOrdering:
    def test_report_inclusion_orders_entries_loss_date_desc_then_created_at_asc(self, api, compliance_headers):
        """PRD §3.5: "Entries are ordered by `loss_date` descending with
        `created_at` ascending as the tie-break — never by `id` — and numbered
        with a 1-based `entry_sequence` in that order."

        Design: Corner/calculations/report_inclusion_orders_entries_loss_date_desc_then_created_at_asc
        """
        set_clock()
        init_exchange_rules()
        carrier = create_carrier()
        eli = create_consumer(
            full_name="Eli Elder",
            date_of_birth="1983-03-13",
            address_line="19 Elm Dr, Houston TX",
            driver_license_number="ELI-1",
        )
        submit_batch(
            carrier,
            [
                make_claim_row(eli["id"], "E-1", loss_date="2025-01-05", cause_of_loss_code="EL1", paid_amount_cents=11000),
                make_claim_row(eli["id"], "E-2", loss_date="2025-03-01", loss_type="PROPERTY", cause_of_loss_code="EL2", paid_amount_cents=22000),
                make_claim_row(eli["id"], "E-3", loss_date="2025-03-01", loss_type="OTHER", cause_of_loss_code="EL3", paid_amount_cents=33000),
            ],
        )
        carrier = get_success_data(api.get_carrier(carrier["id"], admin()))
        uw = make_underwriter_headers(carrier["id"])
        inq = validate_success(api.create_inquiry(carrier["id"], _inquiry_payload(eli), uw), 201)
        entries, _ = validate_paginated(
            api.list_report_entries_for_report(inq["report_id"], compliance_headers)
        )
        assert len(entries) == 3
        assert entries[0]["entry_sequence"] == 1
        assert entries[0]["cause_of_loss_code"] == "EL2"
        assert entries[1]["entry_sequence"] == 2
        assert entries[1]["cause_of_loss_code"] == "EL3"
        assert entries[2]["entry_sequence"] == 3
        assert entries[2]["cause_of_loss_code"] == "EL1"


class TestInquiryImmediateConsistency:
    def test_inquiry_response_reflects_all_writes_immediately(self, api):
        """PRD §3.4: "Every inquiry lands in `RESOLVED` status once matching
        completes, since matching runs synchronously at submission."
        PRD §3.4: "the inquiry persists the winning bundle's
        `individual_match_grade`, `address_match_grade`, and
        `vehicle_match_grade` — each the highest grade achieved across the
        candidate bundles — together with the `match_score` itself."

        Design: Corner/consistency/inquiry_response_reflects_all_writes_immediately
        """
        ctx = setup_active_carrier_with_report(
            consumer_overrides={
                "full_name": "Val Vann",
                "date_of_birth": "1984-11-17",
                "address_line": "6 Vine St, Victoria TX",
                "driver_license_number": "VAL-1",
            },
            claim_overrides={"loss_date": "2025-02-14", "paid_amount_cents": 100000},
        )
        carrier, consumer, inquiry = ctx["carrier"], ctx["consumer"], ctx["inquiry"]
        assert inquiry["matched_consumer_id"] == consumer["id"]
        assert inquiry["match_disposition"] == "PROBABLE"
        assert inquiry["match_score"] == 6050
        assert inquiry["report_id"] is not None
        report = get_success_data(
            api.get_report(inquiry["report_id"], make_underwriter_headers(carrier["id"]))
        )
        assert report["risk_score_certainty"] == 60.50
        assert report["risk_score_count"] == 61
        assert report["risk_score_premium_weighted_cents"] == 60500
