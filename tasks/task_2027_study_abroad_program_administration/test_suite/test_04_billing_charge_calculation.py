"""Billing statement creation and payment lifecycle (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    APPLICATION_FEE_CENTS,
    HOME_TUITION_PER_TERM_CENTS,
    INSURANCE_PREMIUM_CENTS,
    approve_application,
    assert_billing_statement,
    clear_application,
    commit_application,
    create_committed_application,
    create_open_program,
    create_partner_agreement,
    create_student,
    create_submitted_application,
    get_statement_for_application,
    make_student_headers,
    record_payment,
    setup_committed_with_statement,
    setup_open_program_with_application,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    BURSAR_HEADERS,
    COORD_A_HEADERS,
)


class TestDualVariantBilling:
    def test_program_fee_variant_charge(self, api):
        """PRD §3.4: "Two billing models produce different charges from the same student
        data. Under the home-tuition model, `base_cents` is the university-wide home tuition
        constant of 2400000 cents ($24,000 per term); under the program-fee model, `base_cents`
        is the program's own `program_fee_cents`. ... `aid_portable_cents` is the lesser of
        the application's `aid_award_cents_snapshot` and the floor of the cap percentage times
        `base_cents` — the cap is 100% of base under `HOME_TUITION` and 60% of base under
        `PROGRAM_FEE`. The resulting `charge_cents` is the base plus the premium plus the fee
        minus the portable aid ..."

        Design: Difficulty/dual_variant_calc/billing_home_tuition_vs_program_fee_charge
        """
        # PROGRAM_FEE variant: fee 1800000, insurance required, aid 900000.
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Fee Student", "email": "fee@uni.edu", "aid_award_cents": 900000},
            program_overrides={
                "name": "Lyon Spring 2027",
                "billing_model": "PROGRAM_FEE",
                "program_fee_cents": 1800000,
            },
        )
        statement = get_statement_for_application(application["id"])
        assert_billing_statement(statement)
        assert statement["base_cents"] == 1800000
        # aid_portable = min(900000, floor(0.60 * 1800000) = 1080000) = 900000
        assert statement["aid_portable_cents"] == 900000
        # charge = 1800000 + 35000 + 5000 - 900000
        assert statement["charge_cents"] == 940000
        assert statement["outstanding_cents"] == 940000

    def test_home_tuition_variant_charge(self, api):
        """PRD §3.4: "Under the home-tuition model, `base_cents` is the university-wide home
        tuition constant of 2400000 cents ($24,000 per term) ... the cap is 100% of base under
        `HOME_TUITION` and 60% of base under `PROGRAM_FEE`."

        Design: Difficulty/dual_variant_calc/billing_home_tuition_vs_program_fee_charge
        """
        # HOME_TUITION variant: base 2400000, insurance required, aid 900000.
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Tuition Student", "email": "tuition@uni.edu", "aid_award_cents": 900000},
            program_overrides={
                "name": "Kyoto Year 2027",
                "host_institution": "Kyoto University",
                "country_code": "JP",
                "billing_model": "HOME_TUITION",
            },
        )
        statement = get_statement_for_application(application["id"])
        assert_billing_statement(statement)
        assert statement["base_cents"] == 2400000
        # aid_portable = min(900000, floor(1.00 * 2400000)) = 900000
        assert statement["aid_portable_cents"] == 900000
        # charge = 2400000 + 35000 + 5000 - 900000
        assert statement["charge_cents"] == 1540000


class TestAidCapMinBranch:
    def test_aid_cap_binds_when_snapshot_exceeds_cap(self, api):
        """PRD §3.4: "`aid_portable_cents` is the lesser of the application's
        `aid_award_cents_snapshot` and the floor of the cap percentage times `base_cents` —
        the cap is 100% of base under `HOME_TUITION` and 60% of base under `PROGRAM_FEE`."

        Design: Difficulty/combinatorial_formula/billing_aid_cap_min_branch
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Rich Aid", "email": "rich@uni.edu", "aid_award_cents": 1500000},
            program_overrides={"billing_model": "PROGRAM_FEE", "program_fee_cents": 1800000},
        )
        statement = get_statement_for_application(application["id"])
        # cap branch: floor(0.60 * 1800000) = 1080000 < 1500000 snapshot
        assert statement["aid_portable_cents"] == 1080000
        # charge = 1800000 + 35000 + 5000 - 1080000
        assert statement["charge_cents"] == 760000
        assert statement["outstanding_cents"] == 760000

    def test_aid_snapshot_binds_when_below_cap(self, api):
        """PRD §3.4: "`aid_portable_cents` is the lesser of the application's
        `aid_award_cents_snapshot` and the floor of the cap percentage times `base_cents` ..."

        Design: Difficulty/combinatorial_formula/billing_aid_cap_min_branch
        """
        # aid 500000 < cap 1080000 -> snapshot branch binds.
        program, student, application = create_committed_application(
            student_overrides={"aid_award_cents": 500000},
            program_overrides={"billing_model": "PROGRAM_FEE", "program_fee_cents": 1800000},
        )
        statement = get_statement_for_application(application["id"])
        assert statement["aid_portable_cents"] == 500000
        assert statement["charge_cents"] == 1800000 + 35000 + 5000 - 500000


class TestCommitCreatesStatement:
    def test_commit_creates_issued_billing_statement(self, api):
        """PRD §3.4: "In the same operation the server creates the application's **billing
        statement** in `ISSUED` status. Statements are never created directly; commit is
        their only origin."

        Design: Corner/state_machines/commit_creates_issued_billing_statement
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "No Aid", "email": "noaid@uni.edu", "aid_award_cents": 0},
        )
        assert application["status"] == "COMMITTED"

        resp = api.list_billing_statements(
            BURSAR_HEADERS, params={"application_id": application["id"]},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, (
            f"Commit must create exactly one billing statement, got {len(data)}"
        )
        statement = data[0]
        assert_billing_statement(statement)
        assert statement["status"] == "ISSUED"
        assert statement["base_cents"] == 1800000
        assert statement["insurance_premium_cents"] == 35000
        assert statement["application_fee_cents"] == 5000
        assert statement["aid_portable_cents"] == 0
        # charge = 1800000 + 35000 + 5000 - 0
        assert statement["charge_cents"] == 1840000
        assert statement["outstanding_cents"] == 1840000
        assert statement["amount_paid_cents"] == 0


class TestPaymentProgression:
    def test_billing_payment_progression(self, api):
        """PRD §3.4: "A payment strictly below the outstanding balance moves an `ISSUED`
        statement to `PARTIALLY_PAID`, and further partial payments keep it in
        `PARTIALLY_PAID`; a payment exactly equal to the outstanding balance moves the
        statement — from either `ISSUED` or `PARTIALLY_PAID` — to `PAID`, forcing
        `outstanding_cents` to 0."

        Design: Corner/state_machines/billing_payment_progression
        """
        program, student, application, statement = setup_committed_with_statement(
            aid_award_cents=0,
        )
        assert statement["outstanding_cents"] == 1840000

        partial = record_payment(statement["id"], 500000)
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["outstanding_cents"] == 1340000

        paid = record_payment(statement["id"], 1340000)
        assert paid["status"] == "PAID"
        assert paid["outstanding_cents"] == 0

        resp = api.record_payment(statement["id"], {"amount_cents": 1}, BURSAR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPaymentAmountRules:
    def test_overpayment_and_nonpositive_payment(self, api):
        """PRD §3.4: "The amount must be positive (`ERR_PAYMENT_NOT_POSITIVE`) and no greater
        than the current `outstanding_cents` (`ERR_OVERPAYMENT`)."

        Design: Corner/validations/overpayment_and_nonpositive_payment
        """
        program, student, application, statement = setup_committed_with_statement(
            aid_award_cents=0,
        )
        outstanding = statement["outstanding_cents"]
        assert outstanding == 1840000

        resp_over = api.record_payment(
            statement["id"], {"amount_cents": outstanding + 1}, BURSAR_HEADERS,
        )
        validate_error(resp_over, ApiErrorId.ERR_OVERPAYMENT)

        resp_zero = api.record_payment(
            statement["id"], {"amount_cents": 0}, BURSAR_HEADERS,
        )
        validate_error(resp_zero, ApiErrorId.ERR_PAYMENT_NOT_POSITIVE)

        after = get_statement_for_application(application["id"])
        assert after["status"] == "ISSUED"
        assert after["outstanding_cents"] == 1840000, (
            "Rejected payments must leave the statement unchanged"
        )
