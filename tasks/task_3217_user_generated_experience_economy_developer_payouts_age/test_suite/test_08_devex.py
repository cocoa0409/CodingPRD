"""DevEx: the progressive USD ladder, progressive/flat withholding, optimistic
concurrency on submit, the minimum request, and segregation of duties between
approving and paying officers (PRD §2.6, §3.2, §3.12)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_devex_request,
    create_devex_request_payload,
    fund_user,
    get_user,
    make_creator_headers,
    make_finance_officer_headers,
    setup_devex_eligible_user,
    submit_devex_request,
    validate_error,
    validate_success,
)

OFFICER_1_ID = "officer-1"
OFFICER_2_ID = "officer-2"


class TestProgressiveLadder:
    def test_devex_progressive_ladder_nested_min_max_mode_a(self, api):
        """PRD §3.12: "The `usd_payout_cents` comes from the progressive DevEx ladder
        applied marginally to `requested_robux`: the first 30,000 Robux convert at 0.35
        cents per Robux, Robux from 30,001 through 100,000 at 0.38, Robux from 100,001
        through 1,000,000 at 0.40, and every Robux from 1,000,001 upward at 0.42; the
        bracket sums are aggregated and rounded half-up only at the end."

        Design: Difficulty/combinatorial_formula/devex_progressive_ladder_nested_min_max_mode_a
        """
        user = setup_devex_eligible_user(target_earned_robux=150000)
        assert user["earned_robux_lifetime"] >= 150000

        req = submit_devex_request(user["id"], 150000)
        approved = validate_success(
            api.approve_devex_request(req["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )
        assert_devex_request(approved)
        assert approved["status"] == "APPROVED"
        # 30000*0.35 + 70000*0.38 + 50000*0.40 = 10500 + 26600 + 20000 = 57100.
        assert approved["usd_payout_cents"] == 57100, (
            f"150000 Robux across brackets A/B/C must price at 57100 cents, got "
            f"{approved['usd_payout_cents']}"
        )
        assert (
            approved["net_payout_cents"]
            == approved["usd_payout_cents"] - approved["withholding_tax_cents"]
        ), "net_payout_cents must equal usd_payout_cents minus withholding_tax_cents"

    def test_devex_ladder_bracket_boundaries(self, api):
        """PRD §3.12: "The `usd_payout_cents` comes from the progressive DevEx ladder
        applied marginally to `requested_robux`: the first 30,000 Robux convert at 0.35
        cents per Robux, Robux from 30,001 through 100,000 at 0.38, Robux from 100,001
        through 1,000,000 at 0.40, and every Robux from 1,000,001 upward at 0.42; the
        bracket sums are aggregated and rounded half-up only at the end."

        Design: Difficulty/combinatorial_formula/devex_progressive_ladder_nested_min_max_mode_a
        """
        user = setup_devex_eligible_user(target_earned_robux=130000)

        # Exactly 30000 sits entirely in bracket A: 30000 * 0.35 = 10500.
        req1 = submit_devex_request(user["id"], 30000)
        approved1 = validate_success(
            api.approve_devex_request(req1["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )
        assert approved1["usd_payout_cents"] == 10500, (
            f"30000 Robux must price at 30000*0.35=10500, got {approved1['usd_payout_cents']}"
        )

        # 100000 spans A and B: 30000*0.35 + 70000*0.38 = 10500 + 26600 = 37100.
        req2 = submit_devex_request(user["id"], 100000)
        approved2 = validate_success(
            api.approve_devex_request(req2["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )
        assert approved2["usd_payout_cents"] == 37100, (
            f"100000 Robux must price at 10500+26600=37100, got {approved2['usd_payout_cents']}"
        )


class TestWithholding:
    def test_devex_withholding_nested_rounding_mode_b(self, api):
        """PRD §3.12: "For a `W9` filer the withholding is progressive in cents:
        nothing on the first 10,000 cents, ten percent on cents from 10,001 through
        50,000, twenty-four percent on cents from 50,001 through 200,000, and thirty
        percent on every cent from 200,001 upward."
        PRD §3.12: "The `withholding_tax_cents` is then computed from
        `usd_payout_cents` — never from the net — using brackets keyed on the user's
        tax `form_type`."
        PRD §3.12: "The withholding aggregate rounds half-up at the end, and
        `net_payout_cents` is `usd_payout_cents` minus `withholding_tax_cents`."

        Design: Difficulty/combinatorial_formula/devex_withholding_nested_rounding_mode_b
        """
        user = setup_devex_eligible_user(target_earned_robux=50000, form_type="W9")

        req = submit_devex_request(user["id"], 50000)
        approved = validate_success(
            api.approve_devex_request(req["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )
        # Ladder: 30000*0.35 + 20000*0.38 = 10500 + 7600 = 18100.
        assert approved["usd_payout_cents"] == 18100, (
            f"50000 Robux must price at 18100, got {approved['usd_payout_cents']}"
        )
        # W9 withholding on 18100: first 10000 at 0%; remaining 8100 at 10% = 810.
        assert approved["withholding_tax_cents"] == 810, (
            f"W9 withholding on 18100 cents must be 810, got {approved['withholding_tax_cents']}"
        )
        assert approved["net_payout_cents"] == 17290, (
            f"net must be 18100-810=17290, got {approved['net_payout_cents']}"
        )

    def test_devex_withholding_w8ben_flat_thirty_percent(self, api):
        """PRD §3.12: "For `W8BEN` and `W8BENE` filers the withholding is a flat thirty
        percent of the full `usd_payout_cents`, with no brackets."

        Design: Difficulty/combinatorial_formula/devex_withholding_nested_rounding_mode_b
        """
        user = setup_devex_eligible_user(target_earned_robux=50000, form_type="W8BEN")

        req = submit_devex_request(user["id"], 50000)
        approved = validate_success(
            api.approve_devex_request(req["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )
        assert approved["usd_payout_cents"] == 18100
        # Flat 30% on the full ladder output: round_half_up(18100 * 0.30) = 5430.
        assert approved["withholding_tax_cents"] == 5430, (
            f"W8BEN flat 30% on 18100 must be 5430, got {approved['withholding_tax_cents']}"
        )
        assert approved["net_payout_cents"] == 12670


class TestDevexOptimisticConcurrency:
    def test_devex_submit_stale_user_version_returns_412(self, api):
        """PRD §2.6: "Submitting a DevEx request requires the client to pass
        `expected_user_version`, the `version` of the target `User` the client last
        observed; because marketplace sales, engagement payouts, and parental-control
        edits all advance the user's `version`, a client whose snapshot of
        `earned_robux_lifetime` is stale would otherwise lock Robux against an
        out-of-date eligibility decision. If the supplied value does not match the
        user's current `version`, the submission is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/endpoints/devex_submit_stale_user_version_returns_412
        """
        user = setup_devex_eligible_user(target_earned_robux=30000)
        stale_version = user["version"]

        # A completed currency purchase advances the user's version, making the
        # captured snapshot stale.
        fund_user(user["id"], 2000000)
        fresh = get_user(user["id"])
        assert fresh["version"] != stale_version, (
            "currency purchase confirmation must advance the user version"
        )

        resp = api.create_devex_request(
            create_devex_request_payload(30000, stale_version),
            make_creator_headers(user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412


class TestDevexMinimum:
    def test_devex_minimum_not_met_below_30000(self, api):
        """PRD §3.12: "The amount must be at least 30,000 Robux — anything less is
        rejected with `ERR_DEVEX_MINIMUM_NOT_MET` — and may not exceed the user's
        `earned_robux_lifetime` net of the Robux already locked by other in-flight
        requests."

        Design: Corner/errors/devex_minimum_not_met_below_30000
        """
        user = setup_devex_eligible_user(target_earned_robux=30000)
        fresh = get_user(user["id"])

        resp = api.create_devex_request(
            create_devex_request_payload(29999, fresh["version"]),
            make_creator_headers(user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEVEX_MINIMUM_NOT_MET)
        assert resp.status_code == 422


class TestDevexSegregationOfDuties:
    def test_devex_mark_paid_by_same_officer_who_approved_rejected(self, api):
        """PRD §3.12: "A `FinanceOfficer` marks an `APPROVED` request `PAID`, but the
        marking officer's identifier must differ from the approving officer's — the
        same person cannot approve and pay, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/devex_mark_paid_by_same_officer_who_approved_rejected
        """
        user = setup_devex_eligible_user(target_earned_robux=30000)
        req = submit_devex_request(user["id"], 30000)
        validate_success(
            api.approve_devex_request(req["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )

        resp = api.mark_devex_paid(req["id"], make_finance_officer_headers(OFFICER_1_ID))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert resp.status_code == 422

        after = validate_success(
            api.get_devex_request(req["id"], TEST_USERS["platform_admin_headers"]), 200
        )
        assert after["status"] == "APPROVED", (
            f"rejected mark-paid must leave the request APPROVED, got {after['status']}"
        )

    def test_devex_mark_paid_by_different_officer_succeeds(self, api):
        """PRD §3.12: "A `FinanceOfficer` marks an `APPROVED` request `PAID`, but the
        marking officer's identifier must differ from the approving officer's — the
        same person cannot approve and pay, and a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`. Marking paid converts the lock into a real debit:
        the user's `robux_balance` drops by `requested_robux`, and `paid_at` is
        stamped."

        Design: Corner/state_machines/devex_mark_paid_by_different_officer_succeeds
        """
        user = setup_devex_eligible_user(target_earned_robux=30000)
        # Give the user a Robux balance so the paid debit has headroom.
        _order, credited = fund_user(user["id"], 2000000)
        balance_before = get_user(user["id"])["robux_balance"]

        req = submit_devex_request(user["id"], 30000)
        validate_success(
            api.approve_devex_request(req["id"], make_finance_officer_headers(OFFICER_1_ID)), 200
        )
        paid = validate_success(
            api.mark_devex_paid(req["id"], make_finance_officer_headers(OFFICER_2_ID)), 200
        )
        assert paid["status"] == "PAID"

        balance_after = get_user(user["id"])["robux_balance"]
        assert balance_after == balance_before - 30000, (
            f"marking paid must debit requested_robux: {balance_before} -> {balance_after}"
        )
