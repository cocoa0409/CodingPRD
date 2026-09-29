"""The payout-batch lifecycle: generation, validation, approval, payment, voiding and hold release."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BATCH_NOT_VALIDATED,
    ERR_LINE_NOT_HELD,
)
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_null,
    assert_total_count,
    assert_version_bumped,
    assert_version_unchanged,
)
from test_helpers.fixtures import (
    approve_batch,
    attributed_order,
    batch_lines,
    build_program,
    first_line,
    generate_batch,
    ledger_entries,
    pay_batch,
    pin_clock,
    read_affiliate,
    read_batch,
    read_line,
    release_line_hold,
    valid_tax_document,
    validate_batch,
    void_batch,
)
from test_helpers.test_users import (
    FINANCE_ANALYST_ID,
    FINANCE_CONTROLLER,
    FINANCE_CONTROLLER_ID,
)

# §2.9: the clock every temporal rule is read against.  The operational setup
# sits at the start of July and the settlement run at the start of August, so
# the thirty-day validation hold on a 2026-07-04 order has elapsed.
SETUP_CLOCK = f.JUL_05_00_00
SETTLEMENT_CLOCK = f.AUG_05_00_00


class TestVoidingADraftBatch:
    def test_void_from_draft_voids_the_line_and_unstamps_the_accrual(self, api):
        """Voiding a DRAFT settlement run voids its line, frees the accrual and moves no money.

        PRD §3.9: "A `FinanceController` may void a batch that is `DRAFT`, `VALIDATED`
        or `APPROVED`, supplying a reason recorded in `void_reason`. Every line moves to
        `VOIDED` whatever state it was in, every ledger entry stamped to this batch is
        un-stamped back to null, and **no ledger entry is created or deleted** — the
        audit trail of what was earned is untouched by the failure to pay it."

        Design: Corner/state_machines/void_from_draft_voids_lines_and_unstamps_ledger_without_balance_movement
        """
        program = build_program(api, setup_clock=SETUP_CLOCK)
        # No tax document is filed for this partner at all, so §3.9's line math
        # falls back: "in every other case — no document at all, `PENDING`,
        # `EXPIRED` or `REJECTED` — the line uses the default backup withholding
        # rate of 2400 basis points."
        order = attributed_order(api, program, order_total_cents=100000)

        # §3.5: gross is 100000 * 400 / 10000 = 4000, and a fresh `CONTENT`
        # partner sits in `MEDIUM`, so `LAST_CLICK_RAW` grants the full share:
        # "Under it `credit_share_bps` is 10000, so the payable commission equals
        # the gross commission exactly".
        assert_cents(order["conversion"], "gross_commission_cents", 4000)
        assert_cents(order["conversion"], "payable_commission_cents", 4000)

        pin_clock(api, SETTLEMENT_CLOCK)
        batch = generate_batch(api, program["network_id"])
        line = first_line(api, batch["id"])

        # Before the void the run is a plain `DRAFT` holding one `INCLUDED` line.
        # §3.9: "The `withholding_cents` is the withholding base multiplied by
        # `withholding_bps`, divided by 10000 and rounded half up to a whole
        # cent" — 4000 * 2400 / 10000 = 960 — "The line's `net_cents` is the
        # withholding base less `withholding_cents`" — 4000 - 960 = 3040.
        assert_field(batch, "state", "DRAFT")
        assert_field(batch, "line_count", 1)
        assert_cents(batch, "gross_commission_cents", 4000)
        assert_cents(batch, "clawback_cents", 0)
        assert_cents(batch, "network_fee_cents", 0)
        assert_cents(batch, "withholding_cents", 960)
        assert_cents(batch, "net_payable_cents", 3040)

        assert_field(line, "state", "INCLUDED")
        assert_bps(line, "withholding_bps", 2400)
        assert_cents(line, "gross_cents", 4000)
        assert_cents(line, "net_before_fees_cents", 4000)
        assert_cents(line, "withholding_cents", 960)
        assert_cents(line, "net_cents", 3040)

        # The accrual is claimed by the DRAFT batch before the void.
        claimed = ledger_entries(api, conversion_id=order["conversion_id"])
        assert len(claimed) == 1, (
            "the attribution run appends exactly one ACCRUAL entry for the order"
        )
        assert_field(claimed[0], "payout_batch_id", batch["id"])

        voided = void_batch(api, batch["id"], reason="period reopened by the network")

        assert_fields(
            voided,
            {"state": "VOIDED", "void_reason": "period reopened by the network"},
        )
        assert_field(read_line(api, line["id"]), "state", "VOIDED")

        entries = assert_total_count(
            api.list_ledger_entries(
                FINANCE_CONTROLLER, {"conversion_id": order["conversion_id"]}
            ),
            1,
        )
        assert_fields(entries[0], {"entry_type": "ACCRUAL"})
        assert_cents(entries[0], "amount_cents", 4000)
        assert_null(entries[0], "payout_batch_id")

        # §3.9: "for a `DRAFT` or `VALIDATED` batch there is no balance movement
        # at all, because neither state has reserved anything."
        partner = read_affiliate(api, program["affiliate_id"])
        assert_cents(partner, "accrued_balance_cents", 4000)
        assert_cents(partner, "reserved_balance_cents", 0)
        assert_cents(partner, "lifetime_paid_cents", 0)


class TestApprovalGateBeforePayment:
    def test_pay_is_refused_on_a_draft_and_on_a_validated_batch(self, api):
        """A settlement run cannot be paid before it is approved, from either earlier state.

        PRD §2.10: "The batch's `state` is `DRAFT` when validating, `VALIDATED` when
        approving, and `APPROVED` when paying — otherwise `ERR_BATCH_NOT_VALIDATED`
        (409). Applies to batch validation, approval and payment, and catches for example
        approving a `DRAFT` batch or paying a `VALIDATED` one."

        Design: Corner/state_machines/validated_batch_requires_approval_before_pay_then_settles_to_paid
        """
        program = build_program(api, setup_clock=SETUP_CLOCK)
        # §3.9: "when that document's `status` is `VALID` the line uses its
        # `treaty_withholding_bps`" — a W9 claiming 0 leaves withholding at 0.
        valid_tax_document(api, program["affiliate_id"])
        attributed_order(api, program, order_total_cents=100000)

        pin_clock(api, SETTLEMENT_CLOCK)
        draft = generate_batch(api, program["network_id"])
        assert_field(draft, "state", "DRAFT")
        assert_cents(draft, "net_payable_cents", 4000)

        early = api.pay_payout_batch(
            draft["id"], f.pay_batch_payload("WIRE-EARLY"), FINANCE_CONTROLLER
        )
        assert_error_response(early, ERR_BATCH_NOT_VALIDATED, 409)
        still_draft = read_batch(api, draft["id"])
        assert_field(still_draft, "state", "DRAFT")
        assert_version_unchanged(still_draft, draft["version"], "payout batch")

        # §3.9: "The gross check runs first and is exact" — the statement's
        # 4000 matches the batch's own recomputed gross exactly, and "A variance
        # of exactly zero cents sets `reconciliation_status` to `MATCHED`."
        validated = validate_batch(
            api, draft["id"], statement_gross_cents=4000, statement_fee_cents=0
        )
        assert_fields(
            validated,
            {
                "state": "VALIDATED",
                "reconciliation_status": "MATCHED",
                "prepared_by_user_id": FINANCE_ANALYST_ID,
            },
        )
        assert_cents(validated, "network_fee_variance_cents", 0)
        assert_bps(validated, "network_fee_variance_bps", 0)
        assert_cents(validated, "net_payable_cents", 4000)

        too_soon = api.pay_payout_batch(
            draft["id"], f.pay_batch_payload("WIRE-TOO-SOON"), FINANCE_CONTROLLER
        )
        assert_error_response(too_soon, ERR_BATCH_NOT_VALIDATED, 409)
        still_validated = read_batch(api, draft["id"])
        assert_field(still_validated, "state", "VALIDATED")
        assert_version_unchanged(
            still_validated, validated["version"], "payout batch"
        )

    def test_approval_reserves_the_pre_fee_figure_then_payment_settles_the_line(self, api):
        """Approval reserves the partner's pre-fee balance and payment settles it to PAID.

        PRD §3.9: "A `FinanceController` pays an `APPROVED` batch, supplying a
        `payment_reference`, which must be present. The batch moves to `PAID`, records
        the reference, and every `INCLUDED` line moves to `PAID`. For each paid line a
        `SETTLEMENT` ledger entry is appended for the negative of that line's
        `net_before_fees_cents`, stamped to this batch; the partner's
        `reserved_balance_cents` falls by that same `net_before_fees_cents` and its
        `lifetime_paid_cents` rises by the line's `net_cents` — the difference between
        the two is the network's fee and the tax withheld, which the partner never
        receives."

        Design: Corner/state_machines/validated_batch_requires_approval_before_pay_then_settles_to_paid
        """
        program = build_program(api, setup_clock=SETUP_CLOCK)
        valid_tax_document(api, program["affiliate_id"])
        attributed_order(api, program, order_total_cents=100000)

        pin_clock(api, SETTLEMENT_CLOCK)
        batch = generate_batch(api, program["network_id"])
        line = first_line(api, batch["id"])
        validated = validate_batch(
            api, batch["id"], statement_gross_cents=4000, statement_fee_cents=0
        )

        # §2.8: "The user who prepared a payout batch may not approve it." — the
        # analyst prepared this run and the controller approves it.
        approved = approve_batch(api, batch["id"], validated["version"])
        assert_fields(
            approved,
            {"state": "APPROVED", "approved_by_user_id": FINANCE_CONTROLLER_ID},
        )

        # §3.9: "for every `INCLUDED` line the line's `net_before_fees_cents` moves
        # out of the partner's `accrued_balance_cents` and into its
        # `reserved_balance_cents`" — and "the amount reserved is the pre-fee figure".
        reserved = read_affiliate(api, program["affiliate_id"])
        assert_cents(reserved, "accrued_balance_cents", 0)
        assert_cents(reserved, "reserved_balance_cents", 4000)
        assert_cents(reserved, "lifetime_paid_cents", 0)

        paid = pay_batch(api, batch["id"], payment_reference="WIRE-2026-08-05")
        assert_fields(
            paid, {"state": "PAID", "payment_reference": "WIRE-2026-08-05"}
        )

        paid_line = read_line(api, line["id"])
        assert_field(paid_line, "state", "PAID")
        assert_cents(paid_line, "net_before_fees_cents", 4000)
        assert_cents(paid_line, "net_cents", 4000)

        entries = assert_total_count(
            api.list_ledger_entries(
                FINANCE_CONTROLLER, {"affiliate_id": program["affiliate_id"]}
            ),
            2,
        )
        assert [entry["entry_type"] for entry in entries] == [
            "ACCRUAL",
            "SETTLEMENT",
        ], "the ledger holds the accrual then the settlement, oldest first"
        assert_cents(entries[0], "amount_cents", 4000)
        assert_cents(entries[1], "amount_cents", -4000)
        assert_field(entries[1], "payout_batch_id", batch["id"])

        settled = read_affiliate(api, program["affiliate_id"])
        assert_cents(settled, "reserved_balance_cents", 0)
        assert_cents(settled, "accrued_balance_cents", 0)
        assert_cents(settled, "lifetime_paid_cents", 4000)


class TestBelowMinimumHoldOnAPayoutLine:
    def test_line_under_the_minimum_payout_is_generated_held_and_left_out_of_the_payable_totals(
        self, api
    ):
        """A 200-cent line is born held below the minimum, yet still counts in the batch gross.

        PRD §3.9: "A line whose recomputed `net_cents` falls below the 2,500-cent
        minimum payout moves to `HELD_BELOW_MINIMUM` with `hold_reason`
        `BELOW_MINIMUM_PAYOUT`; the boundary is inclusive on the pay side, so exactly
        2500 stays `INCLUDED` and 2499 holds. That check runs at generation, again at
        validation, and again after a clawback recompute."

        Design: Corner/state_machines/held_below_minimum_line_released_to_included_then_second_release_rejected
        """
        program = build_program(api, setup_clock=SETUP_CLOCK)
        valid_tax_document(api, program["affiliate_id"])
        # §3.5: 5000 * 400 / 10000 = 200, taken in full because a fresh `CONTENT`
        # partner is `MEDIUM` and the raw variant grants `credit_share_bps` 10000.
        order = attributed_order(api, program, order_total_cents=5000)
        assert_cents(order["conversion"], "payable_commission_cents", 200)

        pin_clock(api, SETTLEMENT_CLOCK)
        batch = generate_batch(api, program["network_id"])
        lines = batch_lines(api, batch["id"])
        assert len(lines) == 1, "one partner among the claimed entries yields one line"
        line = lines[0]

        assert_fields(
            line, {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"}
        )
        assert_cents(line, "gross_cents", 200)
        assert_cents(line, "clawback_cents", 0)
        assert_cents(line, "net_before_fees_cents", 200)
        assert_bps(line, "withholding_bps", 0)
        assert_cents(line, "withholding_cents", 0)
        assert_cents(line, "net_cents", 200)

        # §3.9: "Which lines contribute also differs by total:
        # `gross_commission_cents` and `clawback_cents` include **every** line
        # whatever its state, except that a `VOIDED` line contributes to neither,
        # so that the reconciliation check sees the full statement-side gross;
        # while `network_fee_cents`, `withholding_cents` and `net_payable_cents`
        # include only lines that are `INCLUDED` or `PAID`."
        assert_field(batch, "state", "DRAFT")
        assert_field(batch, "line_count", 1)
        assert_cents(batch, "gross_commission_cents", 200)
        assert_cents(batch, "network_fee_cents", 0)
        assert_cents(batch, "withholding_cents", 0)
        assert_cents(batch, "net_payable_cents", 0)

    def test_releasing_the_below_minimum_hold_restores_the_line_and_a_second_release_is_refused(
        self, api
    ):
        """Releasing the hold waives the floor for that line, and the released line cannot be released twice.

        PRD §3.9: "On success the line returns to `INCLUDED`, its `hold_reason` clears
        to null, `released_by_user_id` records the controller, the line is recomputed, and
        the batch's `network_fee_cents`, `withholding_cents` and `net_payable_cents` are
        recomputed with the batch's `version` incremented while its `state` stays exactly
        as it was. Releasing a below-minimum hold waives the minimum-payout floor for
        that line only."

        Design: Corner/state_machines/held_below_minimum_line_released_to_included_then_second_release_rejected
        """
        program = build_program(api, setup_clock=SETUP_CLOCK)
        # §3.9 gates release on a live form: "Release additionally requires the
        # partner to hold a tax document that is `VALID` and whose `expires_on`
        # is strictly after the logical clock."
        valid_tax_document(api, program["affiliate_id"])
        attributed_order(api, program, order_total_cents=5000)

        pin_clock(api, SETTLEMENT_CLOCK)
        batch = generate_batch(api, program["network_id"])
        line = first_line(api, batch["id"])
        assert_field(line, "state", "HELD_BELOW_MINIMUM")

        released = release_line_hold(
            api,
            line["id"],
            reason="controller override: partner requested settlement of the residual balance",
        )
        assert_field(released, "state", "INCLUDED")
        assert_field(released, "released_by_user_id", FINANCE_CONTROLLER_ID)
        assert_null(released, "hold_reason")
        assert_cents(released, "net_cents", 200)

        after_release = read_batch(api, batch["id"])
        assert_cents(after_release, "net_payable_cents", 200)
        assert_field(after_release, "state", "DRAFT")
        assert_version_bumped(after_release, batch["version"], "payout batch")

        # §2.10: "The line's `state` is one of `HELD_TAX_DOC`, `HELD_BELOW_MINIMUM`
        # or `HELD_FRAUD`, and the owning batch is in `DRAFT` or `VALIDATED` —
        # otherwise `ERR_LINE_NOT_HELD` (409)."  The line is now `INCLUDED`.
        second = api.release_hold(
            line["id"],
            f.release_hold_payload("duplicate release attempt"),
            FINANCE_CONTROLLER,
        )
        assert_error_response(second, ERR_LINE_NOT_HELD, 409)

        assert_field(read_line(api, line["id"]), "state", "INCLUDED")
        assert_version_unchanged(
            read_batch(api, batch["id"]), after_release["version"], "payout batch"
        )
