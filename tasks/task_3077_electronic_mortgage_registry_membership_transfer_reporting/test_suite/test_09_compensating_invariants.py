"""Compensating invariants: rights conservation across a rejected match, and
the exactly-one-FINAL-report invariant across forced regeneration."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    assert_loan_rights_conserved,
    create_active_member,
    create_transfer_payload,
    member_rep,
    read_loan,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_paginated,
    validate_success,
)


class TestRightsConservationThroughRejection:
    def test_rejection_flags_qa_without_rolling_rights_back(self, api):
        """PRD §3.4: "the transfer itself flips from `CONFIRMED` to `REJECTED`,
        the match flips to `EXPIRED`, but the rights movement on the loan is
        **not** rolled back — the loan keeps its new holders."

        Design: Difficulty/compensating_invariant/rights_conservation_through_rejected_match
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=90000000)

        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan["id"], b["id"], loan["version"],
                    transfer_type="BENEFICIAL",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-con-1",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )

        before = read_loan(loan["id"])
        assert_loan_rights_conserved(before)
        assert before["current_investor_id"] == b["id"], before
        assert before["current_servicer_id"] == a["id"], before

        validate_success(api.reject_match(tr["id"], member_rep(a["id"])))

        after = read_loan(loan["id"])
        assert_loan_rights_conserved(after)
        # Conservation holds without rollback: the investor is still B.
        assert after["current_investor_id"] == b["id"], after
        assert after["current_servicer_id"] == a["id"], after
        assert after["status"] == "ACTIVE", after

        transfer_after = validate_success(api.get_transfer(tr["id"], ADMIN))
        assert transfer_after["status"] == "REJECTED", transfer_after

    def test_each_transfer_step_reassigns_rather_than_duplicates_holders(self, api):
        """PRD §3.4: "On acceptance the transfer is born in `CONFIRMED` status
        (there is no pending state for the transfer itself), the rights move
        immediately — `current_investor_id` takes the receiving member for
        `BENEFICIAL` or `BOTH`, `current_servicer_id` for `SERVICING` or `BOTH` —
        and the loan's `version` advances by one with `updated_at` refreshed."

        Design: Difficulty/compensating_invariant/rights_conservation_through_rejected_match
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=90000000)

        at_registration = read_loan(loan["id"])
        assert_loan_rights_conserved(at_registration)
        assert at_registration["current_investor_id"] == a["id"]
        assert at_registration["current_servicer_id"] == a["id"]

        validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan["id"], b["id"], loan["version"],
                    transfer_type="BOTH",
                    effective_date="2026-01-05T00:00:00Z",
                    idempotency_key="k-con-2",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )

        after = read_loan(loan["id"])
        assert_loan_rights_conserved(after)
        # BOTH moved both rights to B; no field still points at A.
        assert after["current_investor_id"] == b["id"], after
        assert after["current_servicer_id"] == b["id"], after
        assert after["version"] == loan["version"] + 1, after


class TestExactlyOneFinalReport:
    def test_force_regenerate_voids_prior_and_keeps_single_final(self, api):
        """PRD §3.6: "Regeneration is nonetheless supported for corrections:
        submitting with `force_regenerate` set to true first flips the prior
        `FINAL` report for that member-year to `VOID` and then creates the new
        report in `FINAL`, preserving the invariant of exactly one live report
        per member-year as a compensating pair of writes rather than an
        overwrite."

        Design: Difficulty/compensating_invariant/exactly_one_final_annual_report_through_regeneration
        """
        set_clock("2026-12-31T00:00:00Z")
        a = create_active_member(org_id="1000000")

        rep1 = validate_success(
            api.create_annual_report(a["id"], {"report_year": 2026}, ADMIN),
            expected_status=201,
        )
        rep2 = validate_success(
            api.create_annual_report(
                a["id"], {"report_year": 2026, "force_regenerate": True}, ADMIN
            ),
            expected_status=201,
        )

        first = validate_success(api.get_annual_report(rep1["id"], ADMIN))
        second = validate_success(api.get_annual_report(rep2["id"], ADMIN))
        assert first["status"] == "VOID", first
        assert second["status"] == "FINAL", second

        finals, meta_final = validate_paginated(
            api.list_annual_reports(
                ADMIN, params={"member_id": a["id"], "report_year": 2026,
                               "status": "FINAL"}
            )
        )
        assert meta_final["total_count"] == 1, meta_final
        assert finals[0]["id"] == rep2["id"], finals

        everything, meta_all = validate_paginated(
            api.list_annual_reports(
                ADMIN, params={"member_id": a["id"], "report_year": 2026}
            )
        )
        # History is preserved, not deleted.
        assert meta_all["total_count"] == 2, meta_all

    def test_regeneration_twice_still_leaves_exactly_one_final(self, api):
        """PRD §3.6: "Exactly one `FINAL` report may exist for a given member and
        year: generating when one already exists fails with
        `ERR_DUPLICATE_ANNUAL_REPORT`."

        Design: Difficulty/compensating_invariant/exactly_one_final_annual_report_through_regeneration
        """
        set_clock("2026-12-31T00:00:00Z")
        a = create_active_member(org_id="1000000")

        validate_success(
            api.create_annual_report(a["id"], {"report_year": 2026}, ADMIN),
            expected_status=201,
        )
        validate_success(
            api.create_annual_report(
                a["id"], {"report_year": 2026, "force_regenerate": True}, ADMIN
            ),
            expected_status=201,
        )
        third = validate_success(
            api.create_annual_report(
                a["id"], {"report_year": 2026, "force_regenerate": True}, ADMIN
            ),
            expected_status=201,
        )

        finals, meta_final = validate_paginated(
            api.list_annual_reports(
                ADMIN, params={"member_id": a["id"], "report_year": 2026,
                               "status": "FINAL"}
            )
        )
        assert meta_final["total_count"] == 1, meta_final
        assert finals[0]["id"] == third["id"], finals

        voids, meta_void = validate_paginated(
            api.list_annual_reports(
                ADMIN, params={"member_id": a["id"], "report_year": 2026,
                               "status": "VOID"}
            )
        )
        assert meta_void["total_count"] == 2, meta_void
