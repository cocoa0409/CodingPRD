"""Wholesale price-cap governance tests (PRD §2.7, §3.7)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_admin_headers,
    set_clock,
    validate_error,
)


class TestPriceCapBaselineCompounding:
    def test_second_increase_compounds_against_jan1_baseline(self, api):
        """PRD §2.7: "Multiple increases within the same calendar year
        compound against that same January-1 baseline, not against each
        other."
        PRD §2.7: "For each of the four fees, the proposed fee may not exceed
        the corresponding baseline fee multiplied by 1.10, with the ceiling
        rounded half-up to whole cents; a violation is rejected with
        `ERR_PRICE_CAP_EXCEEDED`."

        Baseline 700 -> ceiling 770. A mid-year schedule at 750 passes; a
        second 2027 increase to 780 must fail against the SAME 700 baseline
        (780 > 770), even though 780 <= 750 * 1.10 = 825.

        Design: Difficulty/combinatorial_formula/price_cap_compounds_against_jan1_baseline_not_prior_increase
        """
        set_clock("2027-03-15T00:00:00Z")
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-11-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        baseline = get_success_data(resp, expected_status=201)

        resp = api.create_price_schedule(
            {
                "create_fee_cents": 750,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2028-01-10T00:00:00Z",
                "supersedes_schedule_id": baseline["id"],
            },
            make_admin_headers(),
        )
        mid = get_success_data(resp, expected_status=201)
        assert mid["status"] == "PROPOSED"

        resp = api.create_price_schedule(
            {
                "create_fee_cents": 780,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2028-01-20T00:00:00Z",
                "supersedes_schedule_id": mid["id"],
            },
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_CAP_EXCEEDED)

    def test_increase_at_exactly_cap_ceiling_accepted(self, api):
        """PRD §2.7: "the proposed fee may not exceed the corresponding
        baseline fee multiplied by 1.10, with the ceiling rounded half-up to
        whole cents; a violation is rejected with `ERR_PRICE_CAP_EXCEEDED`."

        Boundary: baseline 700 -> ceiling 770. A fee of exactly 770 is at the
        ceiling and must pass; 771 is over it and must fail.

        Design: Difficulty/combinatorial_formula/price_cap_compounds_against_jan1_baseline_not_prior_increase
        """
        set_clock("2027-03-15T00:00:00Z")
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-11-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        baseline = get_success_data(resp, expected_status=201)

        resp = api.create_price_schedule(
            {
                "create_fee_cents": 770,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2028-01-10T00:00:00Z",
                "supersedes_schedule_id": baseline["id"],
            },
            make_admin_headers(),
        )
        accepted = get_success_data(resp, expected_status=201)
        assert accepted["status"] == "PROPOSED"

        resp = api.create_price_schedule(
            {
                "create_fee_cents": 771,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2028-01-20T00:00:00Z",
                "supersedes_schedule_id": baseline["id"],
            },
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_CAP_EXCEEDED)
