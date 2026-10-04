"""Allotment runs and the posting lifecycle: bucket scheduling, first-month
proration, run eligibility windows, duplicate runs, per-case skipping, and the
availability boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    instants_equal,
    validate_error,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestPostingSchedule:
    def test_program_config_defaults_inherited_from_contract(self, api):
        """PRD §2.11: "A null override means the program inherits the contract
        default."
        PRD §3.4: "The modulus is the program's `posting_modulus` override when
        set, otherwise the contract's `default_posting_modulus`."
        PRD §3.4: "The posting's `available_at` is the available date at that
        hour, zero minutes, zero seconds UTC, and its `scheduled_date` is the
        available date."

        Design: Corner/entities/program_config_defaults_inherited_from_contract
        """
        ctx = fx.setup_active_contract(api)  # all defaults; FOOD without overrides
        fx.add_case(api, ctx, case_identifier="0000000003")  # bucket 3
        fx.fund_case(api, ctx)  # September run of 30000
        programs = fx.list_contract_programs(api, ctx.contract["id"])
        assert len(programs) == 1
        assert programs[0]["posting_modulus"] is None, (
            "override field must be null (inheritance, not copying)"
        )
        assert programs[0]["availability_hour_utc"] is None
        postings = fx.list_postings(api, ctx.purses["FOOD"]["id"])
        assert len(postings) == 1
        A.assert_benefit_posting(postings[0])
        # bucket 3 under default modulus 10: month-01 + 3 days = 2026-09-04.
        assert postings[0]["scheduled_date"] == "2026-09-04"
        # default availability hour 6.
        assert instants_equal(postings[0]["available_at"], "2026-09-04T06:00:00Z"), (
            f"available_at must be 2026-09-04T06:00:00Z, got {postings[0]['available_at']}"
        )

    def test_first_month_proration_literal(self, api):
        """PRD §3.4: "First-month proration applies when the case was created
        inside the benefit month: the credited `amount_cents` is the run amount
        multiplied by the number of days from the case-created date through the
        end of the month inclusive, divided by the number of calendar days in
        the month, rounded half up to whole cents exactly once; the posting's
        `prorated` flag is true precisely when the result differs from the run
        amount."
        PRD §3.4: "When the case's `created_at` UTC date falls inside the
        benefit month, the available date is the later of the base date and the
        case-created date; otherwise the available date is simply the base
        date."

        Design: Corner/calculations/first_month_proration_literal
        """
        ctx = fx.setup_active_contract(api)
        fx.set_clock(api, "2026-09-05T00:00:00Z")
        fx.add_case(api, ctx, case_identifier="0000000000")  # created 2026-09-05
        fx.fund_case(api, ctx)  # September run of 30000
        postings = fx.list_postings(api, ctx.purses["FOOD"]["id"])
        assert len(postings) == 1
        posting = postings[0]
        A.assert_benefit_posting(posting)
        # round_half_up(30000 * 26 / 30): 26 days from 09-05 through 09-30 incl.
        assert posting["amount_cents"] == 26000, (
            f"expected prorated 26000, got {posting['amount_cents']}"
        )
        assert posting["prorated"] is True
        # bucket day 2026-09-01 clamped up to the creation date 2026-09-05.
        assert instants_equal(posting["available_at"], "2026-09-05T06:00:00Z")


class TestAvailabilityBoundary:
    def test_posting_available_exactly_at_available_at(self, api):
        """PRD §3.4: "On the availability sweep — step 1 of the clock pipeline —
        a `SCHEDULED` posting whose `available_at` the current clock has reached
        or passed flips to `AVAILABLE`, provided its owning purse is not
        `CLOSED`; a `FROZEN` purse still receives availability."
        PRD §2.7: "while a posting is `SCHEDULED`, its credit raises only the
        ledger balance; once `AVAILABLE`, it raises both"

        Design: Difficulty/boundary_precision_check/posting_available_exactly_at_available_at
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000000")  # bucket 0 -> 09-01
        fx.fund_case(api, ctx)  # 30000, available_at 2026-09-01T06:00:00Z
        purse_id = ctx.purses["FOOD"]["id"]

        fx.set_clock(api, "2026-09-01T05:59:59Z")
        posting = fx.list_postings(api, purse_id)[0]
        purse = fx.get_purse(api, purse_id)
        assert posting["posting_status"] == "SCHEDULED"
        A.assert_purse_balances(purse, ledger_balance_cents=30000,
                                spendable_balance_cents=0)

        fx.set_clock(api, "2026-09-01T06:00:00Z")  # inclusive >= boundary
        posting = fx.list_postings(api, purse_id)[0]
        purse = fx.get_purse(api, purse_id)
        assert posting["posting_status"] == "AVAILABLE"
        A.assert_purse_balances(purse, ledger_balance_cents=30000,
                                spendable_balance_cents=30000)

    def test_posting_available_at_later_bucket_day_boundary(self, api):
        """PRD §3.4: "On the availability sweep — step 1 of the clock pipeline —
        a `SCHEDULED` posting whose `available_at` the current clock has reached
        or passed flips to `AVAILABLE`, provided its owning purse is not
        `CLOSED`; a `FROZEN` purse still receives availability."
        PRD §3.4: "The base date is the first day of `benefit_month` advanced by
        the bucket number of days, so bucket zero lands on the first of the
        month."

        Design: Difficulty/boundary_precision_check/posting_available_exactly_at_available_at
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000003")  # bucket 3 -> 09-04
        fx.fund_case(api, ctx)  # 30000, available_at 2026-09-04T06:00:00Z
        purse_id = ctx.purses["FOOD"]["id"]

        # One second before the bucket-3 availability instant: still future money.
        fx.set_clock(api, "2026-09-04T05:59:59Z")
        posting = fx.list_postings(api, purse_id)[0]
        purse = fx.get_purse(api, purse_id)
        assert posting["posting_status"] == "SCHEDULED"
        A.assert_purse_balances(purse, ledger_balance_cents=30000,
                                spendable_balance_cents=0)

        fx.set_clock(api, "2026-09-04T06:00:00Z")
        posting = fx.list_postings(api, purse_id)[0]
        purse = fx.get_purse(api, purse_id)
        assert posting["posting_status"] == "AVAILABLE"
        A.assert_purse_balances(purse, ledger_balance_cents=30000,
                                spendable_balance_cents=30000)


class TestAllotmentRuns:
    def test_posting_month_too_far_ahead_rejected(self, api):
        """PRD §3.4: "The `benefit_month` must be the current or the next
        calendar month, and a run against a `DISASTER` program additionally
        requires the current clock date to fall inside that program's disaster
        window; either violation is rejected with `ERR_POSTING_MONTH_INVALID`."

        Design: Corner/validations/posting_month_too_far_ahead_rejected
        """
        ctx = fx.setup_active_contract(api)  # clock at the 2026-09-01 default
        resp = api.run_allotment(
            ctx.contract["id"],
            f.allotment_run_payload(ctx.programs["FOOD"]["id"],
                                    benefit_month="2026-11"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_POSTING_MONTH_INVALID)

    def test_duplicate_allotment_run_rejected(self, api):
        """PRD §3.4: "A repeat run for the same program and benefit month is
        rejected with `ERR_DUPLICATE_POSTING_RUN`."

        Design: Corner/validations/duplicate_allotment_run_rejected
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        first = fx.run_allotment(api, ctx.contract["id"], ctx.programs["FOOD"]["id"])
        assert first["created_count"] == 1
        resp = api.run_allotment(
            ctx.contract["id"],
            f.allotment_run_payload(ctx.programs["FOOD"]["id"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POSTING_RUN)

    def test_allotment_run_skips_suspended_cases(self, api):
        """PRD §3.4: "Eligible purses are the purses of the named program whose
        owning case's `account_status` is `OPEN` or `DORMANT` and whose own
        `purse_status` is not `CLOSED`; purses of `SUSPENDED` cases are skipped,
        as are closed purses."
        PRD §3.4: "The run's response reports `created_count`, `skipped_count`,
        and the `posting_ids` created."

        Design: Corner/endpoints/allotment_run_skips_suspended_cases
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000000")  # case A
        fx.add_case(api, ctx, case_identifier="0000000001", key="case_b")
        fx.set_case_status(api, ctx.case_b["id"], "SUSPENDED")
        run = fx.run_allotment(api, ctx.contract["id"], ctx.programs["FOOD"]["id"])
        assert run["created_count"] == 1, f"expected 1 created, got {run['created_count']}"
        assert run["skipped_count"] == 1, f"expected 1 skipped, got {run['skipped_count']}"
        postings_a = fx.list_postings(api, ctx.purses["FOOD"]["id"])
        assert len(postings_a) == 1 and postings_a[0]["amount_cents"] == 30000
        purse_b = fx.get_purse_for_program(api, ctx.case_b["id"],
                                           ctx.programs["FOOD"]["id"])
        assert fx.list_postings(api, purse_b["id"]) == [], (
            "the SUSPENDED case's purse must hold no posting"
        )
