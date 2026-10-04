"""Living allowance disbursement: the three-input nested gate (period cap,
term total, hours-earned cap) with its pinned order, and immediate visibility
of accepted payments (PRD §2.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_payment,
    get_enrollment,
    make_grantee_staff_headers,
    pay_allowance,
    setup_active_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNestedMinGate:
    def _setup_51000_certified(self, api):
        """51000 certified minutes -> earned cap floor(2200000 x 51000/102000)
        == 1100000 exactly."""
        return setup_active_enrollment(minutes_chunks=[48000, 3000])

    def test_eleven_period_cap_payments_land_exactly_on_earned_cap(self, api):
        """Eleven payments of exactly 100000 cents (the period cap) are all
        accepted; the 11th lands paid exactly on the 1100000 earned cap.

        PRD §3.6: "Period cap: a single payment may not exceed 100000 cents ($1,000.00). Exactly 100000 is allowed; anything more is `ERR_ALLOWANCE_PERIOD_CAP_EXCEEDED`."
        PRD §3.6: "Landing exactly on the earned cap is allowed; exceeding it is `ERR_ALLOWANCE_EARNED_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/living_allowance_nested_min_gate
        """
        scenario = self._setup_51000_certified(api)
        pay_allowance(scenario["enrollment_id"], scenario["org_id"], 100000, 11)
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["allowance_paid_cents"] == 1100000

    def test_earned_cap_and_period_cap_reject_with_distinct_errors(self, api):
        """Past the earned cap, a 1000-cent payment draws the earned-cap error
        while a 100001-cent payment draws the period-cap error first — and
        neither moves the ledger.

        PRD §3.6: "Three fiscal gates then fire in pinned order, and which error a bad payment draws depends on which gate it hits first"
        PRD §3.6: "Landing exactly on the earned cap is allowed; exceeding it is `ERR_ALLOWANCE_EARNED_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/living_allowance_nested_min_gate
        """
        scenario = self._setup_51000_certified(api)
        pay_allowance(scenario["enrollment_id"], scenario["org_id"], 100000, 11)
        staff = make_grantee_staff_headers(scenario["org_id"])
        over_earned = api.create_allowance_payment(
            scenario["enrollment_id"], {"amount_cents": 1000}, staff
        )
        validate_error(over_earned, ApiErrorId.ERR_ALLOWANCE_EARNED_CAP_EXCEEDED)
        over_period = api.create_allowance_payment(
            scenario["enrollment_id"], {"amount_cents": 100001}, staff
        )
        validate_error(over_period, ApiErrorId.ERR_ALLOWANCE_PERIOD_CAP_EXCEEDED)
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["allowance_paid_cents"] == 1100000, "rejections move nothing"


class TestSuspendedEnrollmentPayment:
    def _setup_suspended(self, api):
        scenario = setup_active_enrollment()
        staff = make_grantee_staff_headers(scenario["org_id"])
        validate_success(
            api.suspend_enrollment(
                scenario["enrollment_id"], {"reason": "Conduct investigation"}, staff
            )
        )
        return scenario, staff

    def test_state_error_beats_fiscal_error_on_suspended_enrollment(self, api):
        """A 200000-cent payment on a SUSPENDED enrollment violates both the
        ACTIVE-state precondition and the period cap; the state check fires
        first and returns 409 ERR_ENROLLMENT_NOT_ACTIVE.

        PRD §3.6: "the enrollment must be `ACTIVE`, a state check that precedes every fiscal check (`ERR_ENROLLMENT_NOT_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/suspended_enrollment_state_beats_allowance_fiscal
        """
        scenario, staff = self._setup_suspended(api)
        resp = api.create_allowance_payment(
            scenario["enrollment_id"], {"amount_cents": 200000}, staff
        )
        err = validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
        assert resp.status_code == 409
        assert err["error_id"] != ApiErrorId.ERR_ALLOWANCE_PERIOD_CAP_EXCEEDED

    def test_rejected_payment_leaves_ledger_untouched(self, api):
        """The rejected payment adds nothing to allowance_paid_cents.

        PRD §3.6: "An accepted payment adds its `amount_cents` to the enrollment's `allowance_paid_cents`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_enrollment_state_beats_allowance_fiscal
        """
        scenario, staff = self._setup_suspended(api)
        api.create_allowance_payment(scenario["enrollment_id"], {"amount_cents": 200000}, staff)
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["allowance_paid_cents"] == 0


class TestTermTotalExhaustion:
    def test_twenty_two_payments_exhaust_then_one_cent_rejected(self, api):
        """At full 102000 certified minutes the earned cap equals the 2200000
        term total; 22 payments of 100000 exactly exhaust it and a 23rd payment
        of 1 cent is a term-total breach.

        PRD §3.6: "Term total: the payment must not push `allowance_paid_cents` past the term's allowance total from the term table. A breach is `ERR_ALLOWANCE_EXHAUSTED`."

        Design: Corner/validations/allowance_exhausted_at_term_total
        """
        scenario = setup_active_enrollment(minutes_chunks=[48000, 48000, 6000])
        pay_allowance(scenario["enrollment_id"], scenario["org_id"], 100000, 22)
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["allowance_paid_cents"] == 2200000
        staff = make_grantee_staff_headers(scenario["org_id"])
        resp = api.create_allowance_payment(scenario["enrollment_id"], {"amount_cents": 1}, staff)
        validate_error(resp, ApiErrorId.ERR_ALLOWANCE_EXHAUSTED)
        assert get_enrollment(scenario["enrollment_id"])["allowance_paid_cents"] == 2200000


class TestImmediateConsistency:
    def test_payment_visible_immediately_in_enrollment_and_list(self, api, officer_headers):
        """The accepted payment is reflected on the enrollment read and in the
        payments list of the same instant; the payment resource itself carries
        id and created_at but no updated_at/version.

        PRD §3.6: "An accepted payment adds its `amount_cents` to the enrollment's `allowance_paid_cents`."
        PRD §2.5: "A LivingAllowancePayment is an immutable disbursement record: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it, and no operation ever modifies a payment after creation."

        Design: Corner/consistency model/payment_visible_immediately_in_enrollment_and_list
        """
        scenario = setup_active_enrollment(minutes_chunks=[48000])
        staff = make_grantee_staff_headers(scenario["org_id"])
        resp = api.create_allowance_payment(
            scenario["enrollment_id"], {"amount_cents": 100000, "note": "Period 1"}, staff
        )
        payment = validate_success(resp, 201)
        assert_payment(payment)
        enrollment = get_enrollment(scenario["enrollment_id"])
        assert enrollment["allowance_paid_cents"] == 100000
        rows, meta = validate_paginated(
            api.list_allowance_payments(scenario["enrollment_id"], officer_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["amount_cents"] == 100000
        assert rows[0]["note"] == "Period 1"
