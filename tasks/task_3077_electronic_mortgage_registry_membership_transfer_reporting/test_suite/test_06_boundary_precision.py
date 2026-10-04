"""Boundary precision: the ten-day reporting window's last on-time day versus
its first late day, and the MIN check digit as a single-position boundary."""
import pytest

from test_helpers import (
    ADMIN,
    TEST_USERS,
    create_active_member,
    create_transfer_payload,
    api_client,
    member_rep,
    read_loan,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_error,
    validate_success,
)

BORROWER = TEST_USERS["borrower_inquirer_headers"]


class TestTransferDeadlineBoundary:
    def test_day_ten_is_on_time_day_eleven_is_late(self, api):
        """PRD §3.4: "The boundary is exact: the tenth day after the effective
        date is the last on-time day, and the eleventh day is the first late
        day."

        Design: Difficulty/boundary_precision_check/transfer_deadline_day_ten_is_ontime_day_eleven_is_late
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan_x = register_loan(a["id"], loan_amount_cents=10000000)
        loan_y = register_loan(a["id"], loan_amount_cents=10000000)

        # Exactly ten days after the effective date: the last on-time day.
        set_clock("2026-01-15T00:00:00Z")
        tr_x = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan_x["id"], b["id"], loan_x["version"],
                    transfer_type="BENEFICIAL",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-bnd-x",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )

        # One day later: the first late day.
        set_clock("2026-01-16T00:00:00Z")
        tr_y = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan_y["id"], b["id"], loan_y["version"],
                    transfer_type="BENEFICIAL",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-bnd-y",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )

        assert tr_x["status"] == "CONFIRMED" and tr_y["status"] == "CONFIRMED"
        assert tr_x["days_late"] == 0, tr_x
        assert tr_x["late_fee_cents"] == 0, tr_x
        assert tr_y["days_late"] == 1, tr_y
        assert tr_y["late_fee_cents"] == 2500, tr_y

    def test_same_day_report_is_on_time_with_zero_fee(self, api):
        """PRD §3.4: "A transfer reported in time accrues zero fee but is still
        stored with its computed zeros."

        Design: Difficulty/boundary_precision_check/transfer_deadline_day_ten_is_ontime_day_eleven_is_late
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=10000000)

        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan["id"], b["id"], loan["version"],
                    transfer_type="SERVICING",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-bnd-0",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )
        assert tr["days_late"] == 0, tr
        assert tr["late_fee_cents"] == 0, tr


class TestMinCheckDigitBoundary:
    def test_valid_min_resolves_and_flipped_check_digit_is_not_found(self, api):
        """PRD §2.6: "A loan's `min` concatenates three parts into exactly
        eighteen digits: the registering member's seven-digit `org_id`, then the
        member's ten-digit registration `serial` zero-padded on the left, then a
        single Luhn check digit computed over the first seventeen digits."
        PRD §3.9: "An unknown `min` is reported as `ERR_LOAN_NOT_FOUND`."

        Design: Difficulty/boundary_precision_check/borrower_inquiry_min_checkdigit_last_digit_rejects
        """
        set_clock("2026-01-05T00:00:00Z")
        a = create_active_member(org_id="1000000")
        loan = register_loan(a["id"], loan_amount_cents=10000000)
        assert loan["min"] == "100000000000000016", loan

        ok = api.borrower_inquiry("100000000000000016", BORROWER)
        data = validate_success(ok)
        assert data["min"] == "100000000000000016", data
        assert data["loan_id"] == loan["id"], data
        assert data["current_investor_org_id"] == "1000000", data
        assert data["current_servicer_org_id"] == "1000000", data

        # Same 17-digit payload with the check digit flipped: not a match.
        bad = api.borrower_inquiry("100000000000000017", BORROWER)
        assert bad.status_code == 404, bad.text
        validate_error(bad, "ERR_LOAN_NOT_FOUND")

    def test_check_digit_recomputed_per_member_org_id(self, api):
        """PRD §2.6: "The serial that feeds this construction is per-member:
        each member's first successfully registered loan receives serial 1, each
        subsequent successful registration increments it, serials are never
        reused, and they survive member termination."

        Design: Difficulty/boundary_precision_check/borrower_inquiry_min_checkdigit_last_digit_rejects
        """
        set_clock("2026-01-05T00:00:00Z")
        a = create_active_member(org_id="1000000")
        b = create_active_member(org_id="1000001", org_id_type="LEI",
                                 member_type="INVESTOR")
        loan_a = register_loan(a["id"], loan_amount_cents=10000000)
        loan_b = register_loan(b["id"], loan_amount_cents=10000000)

        # org 1000000 serial 1 -> ...16; org 1000001 serial 1 -> ...14. A
        # one-digit org_id difference changes the minted check digit.
        assert loan_a["min"] == "100000000000000016", loan_a
        assert loan_b["min"] == "100000100000000014", loan_b

        # A's minted MIN does not resolve B's loan even though both are serial 1.
        ok = api.borrower_inquiry("100000100000000014", BORROWER)
        data = validate_success(ok)
        assert data["loan_id"] == loan_b["id"], data
