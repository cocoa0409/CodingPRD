"""Placement program terms: subsidy pool rounding and cap, the amendment
cycle, accrual-vs-final period reconciliation, auto-completion, segregation
of duties, and amendment OCC (PRD sections 2.8, 3.3).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_program,
    close_program_periods,
    create_account,
    create_active_program,
    create_kit,
    create_order,
    create_passed_lot,
    create_program,
    deliver_order,
    hardware_line,
    make_account_manager_headers,
    make_finance_admin_headers,
    order_line,
    program_amendment_payload,
    program_review_payload,
    ship_order,
    submit_order,
    submit_program,
    validate_error,
    validate_success,
)
from test_helpers import api_client

FA = TEST_USERS["finance_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def _get_program(program_id: str) -> dict:
    return validate_success(api_client.get_placement_program(program_id, FA))


def _amend(program_id: str, payload: dict, headers: dict):
    return api_client.post_placement_amendment(program_id, payload, headers)


class TestSubsidyPoolRoundingOrder:
    def test_three_lines_round_per_line_then_sum(self, api):
        """Three 101c lines at subsidy 0.155 give 3 x round(15.655) = 48c;
        the forbidden sum-then-round order would produce 47c.

        PRD §3.3: "At that moment the server computes `subsidy_pool_cents` with a pinned rounding order: for each hardware line, the line's `quantity` times its `unit_price_cents` times the program's `subsidy_pct` is rounded half up to whole cents first, and only then are the per-line amounts summed."
        PRD §3.3: "Submitting the program for review is the same `AccountManager`'s action and moves `DRAFT` to `PENDING_APPROVAL`."

        Design: Difficulty/combinatorial_formula/subsidy_pool_per_line_rounding
        """
        program = create_program(
            subsidy_pct=0.155,
            hardware_lines=[
                hardware_line("part-a", 1, 101),
                hardware_line("part-b", 1, 101),
                hardware_line("part-c", 1, 101),
            ],
        )
        submitted = submit_program(program["id"])
        assert submitted["subsidy_pool_cents"] == 48, (
            f"per-line rounding must give 3 x 16 = 48, got "
            f"{submitted['subsidy_pool_cents']}"
        )
        assert submitted["program_state"] == "PENDING_APPROVAL"

    def test_two_lines_still_distinguish_rounding_order(self, api):
        """Two 101c lines at 0.155 give 16 + 16 = 32c per-line; the
        sum-first order would give round(31.31) = 31c.

        PRD §3.3: "At that moment the server computes `subsidy_pool_cents` with a pinned rounding order: for each hardware line, the line's `quantity` times its `unit_price_cents` times the program's `subsidy_pct` is rounded half up to whole cents first, and only then are the per-line amounts summed."

        Design: Difficulty/combinatorial_formula/subsidy_pool_per_line_rounding
        """
        program = create_program(
            subsidy_pct=0.155,
            hardware_lines=[
                hardware_line("part-a", 1, 101),
                hardware_line("part-b", 1, 101),
            ],
        )
        submitted = submit_program(program["id"])
        assert submitted["subsidy_pool_cents"] == 32
        assert submitted["program_state"] == "PENDING_APPROVAL"


class TestProgramAmendmentCycle:
    def test_reject_loop_discards_amendment(self, api):
        """CREATE moves ACTIVE -> UNDER_AMENDMENT; REJECT returns to ACTIVE
        with the committed annual spend untouched and the pending amendment
        cleared.

        PRD §3.3: "Rejecting the amendment clears `pending_amendment` without applying anything and likewise returns the program to `ACTIVE`."
        PRD §2.8: "Creating an amendment against a placement program requires the request to carry `expected_program_version` holding the program's `version` as the client last observed it."

        Design: Difficulty/non_linear_state_machine/program_amendment_cycle
        """
        program = create_active_program(am_user_id="am-c1", fa_user_id="fa-c1")
        created = validate_success(
            _amend(
                program["id"],
                program_amendment_payload(
                    "CREATE",
                    expected_program_version=program["version"],
                    new_committed_annual_reagent_cents=14_000_000,
                ),
                make_account_manager_headers("am-c1"),
            )
        )
        assert created["program_state"] == "UNDER_AMENDMENT"
        rejected = validate_success(
            _amend(
                program["id"],
                program_amendment_payload("REJECT"),
                make_finance_admin_headers("fa-c1"),
            )
        )
        assert rejected["program_state"] == "ACTIVE"
        after = _get_program(program["id"])
        assert after["committed_annual_reagent_cents"] == 12_000_000
        assert after["pending_amendment"] is None

    def test_approve_loop_applies_amendment_and_recomputes_pool(self, api):
        """After a full REJECT loop, a second CREATE + APPROVE applies the
        amended subsidy_pct and recomputes the pool as
        round(1 x 500,000c x 0.20) = 100,000c.

        PRD §3.3: "Approving the amendment is `FinanceAdmin` work gated on the approver differing from the amendment's creator — again `ERR_SEGREGATION_OF_DUTIES` — and applies the pending values to `committed_annual_reagent_cents` and/or `subsidy_pct`, clears `pending_amendment` to null, recomputes `subsidy_pool_cents` under the same per-line rounding rule, and returns the program to `ACTIVE`."
        PRD §3.3: "Rejecting the amendment clears `pending_amendment` without applying anything and likewise returns the program to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/program_amendment_cycle
        """
        program = create_active_program(am_user_id="am-c2", fa_user_id="fa-c2")
        am = make_account_manager_headers("am-c2")
        fa = make_finance_admin_headers("fa-c2")
        # First full loop: CREATE then REJECT.
        validate_success(
            _amend(
                program["id"],
                program_amendment_payload(
                    "CREATE",
                    expected_program_version=program["version"],
                    new_committed_annual_reagent_cents=14_000_000,
                ),
                am,
            )
        )
        rejected = validate_success(
            _amend(program["id"], program_amendment_payload("REJECT"), fa)
        )
        assert rejected["program_state"] == "ACTIVE"
        # Second full loop: CREATE then APPROVE applies the new subsidy.
        validate_success(
            _amend(
                program["id"],
                program_amendment_payload(
                    "CREATE",
                    expected_program_version=rejected["version"],
                    new_subsidy_pct=0.20,
                ),
                am,
            )
        )
        approved = validate_success(
            _amend(program["id"], program_amendment_payload("APPROVE"), fa)
        )
        assert approved["program_state"] == "ACTIVE"
        assert float(approved["subsidy_pct"]) == pytest.approx(0.20)
        assert approved["subsidy_pool_cents"] == 100_000
        assert approved["pending_amendment"] is None


class TestCommitmentReconciliationVariants:
    def test_interim_close_sets_shortfall_flag_only(self, api):
        """At period 6 of 12 with zero delivered spend, the accrual variant
        flags expected 6,000,000c > 0 — but the program stays ACTIVE with no
        penalty.

        PRD §3.3: "While `period_index` is below `term_months`, closing the period runs the accrual reconciliation: expected spend to date is the annual commitment times `period_index`, divided by 12, rounded half up to whole cents, and `shortfall_flag` is set to true exactly when `delivered_spend_cents` is strictly below that expectation."
        PRD §3.3: "The `period_index` then increments and the program stays `ACTIVE`; no penalty and no state change accompany an interim close."

        Design: Difficulty/dual_variant_calc/commitment_accrual_vs_final_reconciliation
        """
        program = create_active_program()
        sixth = close_program_periods(program["id"], 6)
        assert sixth["shortfall_flag"] is True
        assert sixth["program_state"] == "ACTIVE"
        assert sixth["period_index"] == 7
        assert sixth["penalty_cents"] == 0

    def test_final_close_breaches_and_posts_penalty(self, api):
        """The twelfth close is the final variant: shortfall
        12,000,000c - 0 posts a 10% penalty of 1,200,000c, moves the program
        to BREACHED, and flips the account's credit hold.

        PRD §3.3: "When `period_index` equals `term_months`, the close is final: the shortfall is `committed_total_cents` minus `delivered_spend_cents`, floored at zero."
        PRD §3.3: "A positive shortfall posts a `penalty_cents` of 10% of the shortfall rounded half up to whole cents, moves the program to `BREACHED`, and — because a breached program is what makes an account's `credit_hold` true — immediately blocks the account from submitting further reagent orders."

        Design: Difficulty/dual_variant_calc/commitment_accrual_vs_final_reconciliation
        """
        program = create_active_program()
        final = close_program_periods(program["id"], 12)
        assert final["program_state"] == "BREACHED"
        assert final["penalty_cents"] == 1_200_000, (
            "10% of the 12,000,000c shortfall, got "
            f"{final['penalty_cents']}"
        )
        account = validate_success(
            api_client.get_account(program["account_id"], AM)
        )
        assert account["credit_hold"] is True


class TestSubsidyCap:
    def test_subsidy_cap_exceeded_at_submit(self, api):
        """Pool 1 x 3,000,000c x 0.20 = 600,000c exceeds 40% of the
        1,000,000c commitment (400,000c); SUBMIT is rejected and the program
        never leaves DRAFT.

        PRD §3.3: "The pool is then capped: it must not exceed 40% of `committed_annual_reagent_cents`, and a program whose pool breaks the cap is rejected with `ERR_SUBSIDY_CAP_EXCEEDED` (HTTP 422) and never leaves `DRAFT`."

        Design: Corner/validations/subsidy_cap_exceeded_at_submit
        """
        program = create_program(
            committed_annual_reagent_cents=1_000_000,
            subsidy_pct=0.20,
            hardware_lines=[hardware_line("instrument", 1, 3_000_000)],
        )
        resp = api_client.review_placement_program(
            program["id"], program_review_payload("SUBMIT"),
            make_account_manager_headers("am-creator"),
        )
        validate_error(resp, ApiErrorId.ERR_SUBSIDY_CAP_EXCEEDED)
        assert _get_program(program["id"])["program_state"] == "DRAFT"


class TestProgramAutoCompletion:
    def test_delivery_to_exact_commitment_completes_program(self, api):
        """A delivery bringing delivered_spend_cents exactly EQUAL to
        committed_total_cents (>=, not >) completes the program with no
        explicit close call.

        PRD §3.3: "When a delivery posts attributed spend and the program's `delivered_spend_cents` reaches at least its `committed_total_cents`, the program transitions itself from `ACTIVE` to `COMPLETED` as a side effect of the delivery; from then on, any order referencing it fails submission with `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409)."
        PRD §3.3: "The program starts in `DRAFT` with the creator recorded as `created_by_user_id`; `period_index` starts at 1; `delivered_spend_cents` and `pipeline_spend_cents` start at 0; `shortfall_flag` starts false; `penalty_cents` starts at 0; and `committed_total_cents` is derived as the annual commitment multiplied by the term in months and divided by 12."

        Design: Corner/state_machines/program_auto_completes_at_exact_commitment
        """
        account = create_account()
        kit = create_kit(price_cents=600_000)
        create_passed_lot(kit_id=kit["id"], quantity_units=5)
        program = create_active_program(
            account_id=account["id"], committed_annual_reagent_cents=1_200_000
        )
        assert program["committed_total_cents"] == 1_200_000
        order = create_order(
            account["id"], [order_line(kit["kit_code"], 2)],
            program_id=program["id"],
        )
        submit_order(order["id"], account["id"])
        ship_order(order["id"])
        deliver_order(order["id"])
        after = _get_program(program["id"])
        assert after["delivered_spend_cents"] == 1_200_000
        assert after["program_state"] == "COMPLETED"


class TestSegregationOfDuties:
    def test_program_creator_cannot_approve(self, api):
        """The creating X-User-ID cannot approve even under the FinanceAdmin
        role; a different FinanceAdmin id approves cleanly.

        PRD §3.3: "Approval is `FinanceAdmin` work, and it is where segregation of duties bites: the approver's `X-User-ID` must differ from the program's `created_by_user_id`, and a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/rbac/program_approve_segregation_of_duties
        """
        program = create_program(am_user_id="am-sod")
        submit_program(program["id"], am_user_id="am-sod")
        resp = api_client.review_placement_program(
            program["id"], program_review_payload("APPROVE"),
            make_finance_admin_headers("am-sod"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = approve_program(program["id"], fa_user_id="fa-sod")
        assert approved["program_state"] == "ACTIVE", (
            "the rejected self-approval must leave the program PENDING_APPROVAL"
        )

    def test_amendment_creator_cannot_approve(self, api):
        """The segregation anchor for amendments is the AMENDMENT creator:
        the amendment author cannot approve their own amendment even though
        a different FinanceAdmin approved the program itself.

        PRD §3.3: "Approving the amendment is `FinanceAdmin` work gated on the approver differing from the amendment's creator — again `ERR_SEGREGATION_OF_DUTIES` — and applies the pending values to `committed_annual_reagent_cents` and/or `subsidy_pct`, clears `pending_amendment` to null, recomputes `subsidy_pool_cents` under the same per-line rounding rule, and returns the program to `ACTIVE`."

        Design: Corner/rbac/amendment_approve_segregation_of_duties
        """
        program = create_active_program(am_user_id="am-sod2", fa_user_id="fa-sod2")
        validate_success(
            _amend(
                program["id"],
                program_amendment_payload(
                    "CREATE",
                    expected_program_version=program["version"],
                    new_subsidy_pct=0.15,
                ),
                make_account_manager_headers("am-sod2"),
            )
        )
        resp = _amend(
            program["id"],
            program_amendment_payload("APPROVE"),
            make_finance_admin_headers("am-sod2"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = _get_program(program["id"])
        assert after["program_state"] == "UNDER_AMENDMENT"
        assert float(after["subsidy_pct"]) == pytest.approx(0.10)


class TestAmendmentOptimisticConcurrency:
    def test_stale_version_rejected_then_current_version_succeeds(self, api):
        """Amendment CREATE carrying a version one behind the program's
        current version is rejected 412; the same call at the observed
        version enters UNDER_AMENDMENT.

        PRD §2.8: "Creating an amendment against a placement program requires the request to carry `expected_program_version` holding the program's `version` as the client last observed it."
        PRD §2.8: "Amendment creation legitimately moves a program from `ACTIVE` to `UNDER_AMENDMENT` and advances its version, so a client presenting an older value is working from a stale program view; the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_amendment
        """
        program = create_active_program(am_user_id="am-occ", fa_user_id="fa-occ")
        observed = program["version"]
        resp = _amend(
            program["id"],
            program_amendment_payload(
                "CREATE",
                expected_program_version=observed - 1,
                new_subsidy_pct=0.15,
            ),
            make_account_manager_headers("am-occ"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        created = validate_success(
            _amend(
                program["id"],
                program_amendment_payload(
                    "CREATE",
                    expected_program_version=observed,
                    new_subsidy_pct=0.15,
                ),
                make_account_manager_headers("am-occ"),
            )
        )
        assert created["program_state"] == "UNDER_AMENDMENT", (
            "the OCC gate, not the state machine, rejected the first call"
        )
