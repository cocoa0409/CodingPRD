"""Which of two simultaneously broken rules answers, and the exact side of each threshold."""

import pytest

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_APPROVAL_LIMIT_EXCEEDED,
    ERR_BATCH_NOT_VALIDATED,
    ERR_FRAUD_HOLD_NOT_CLEARABLE,
    ERR_INVALID_EFFECTIVE_WINDOW,
    ERR_POLICY_WINDOW_OVERLAP,
    ERR_TAX_DOCUMENT_INVALID,
)
from test_helpers.assertions import (
    assert_cents,
    assert_error_response,
    assert_fields,
    assert_list_response,
    assert_null,
    assert_object_response,
    assert_pagination_meta,
    assert_total_count,
    assert_version_unchanged,
)
from test_helpers.fixtures import (
    activated_partner,
    attributed_order,
    batch_lines,
    build_program,
    create_network,
    draft_and_activate_policy,
    draft_policy,
    first_line,
    generate_batch,
    mint_link,
    pin_clock,
    read_affiliate,
    read_batch,
    read_conversion,
    read_line,
    suspend_partner,
    valid_tax_document,
    validate_batch,
)
from test_helpers.test_users import (
    FINANCE_CONTROLLER,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

# ── the settlement timeline every payout test in this file shares ────────────
# §3.6: the validation sweep needs "thirty days have elapsed since its
# `placed_at` as measured against the logical clock", so the order is placed in
# August and the batch is generated in mid-September.
SETUP_CLOCK = "2026-08-12T12:00:00.000Z"
CLICK_AT = "2026-08-10T10:00:00.000Z"
PLACED_AT = "2026-08-12T09:00:00.000Z"
BATCH_CLOCK = "2026-09-15T00:00:00.000Z"
PERIOD_START = "2026-08-01T00:00:00.000Z"
PERIOD_END = "2026-09-01T00:00:00.000Z"

# ── the cookie-window timeline, in whole milliseconds ───────────────────────
WINDOW_CLOCK = "2026-09-01T00:00:00.000Z"
WINDOW_PLACED_AT = "2026-08-31T12:00:00.000Z"
#: §3.5: `placed_at` less `cookie_window_days` of "86,400 seconds each" — the
#: inclusive lower bound of a 30-day window anchored at WINDOW_PLACED_AT.
WINDOW_LOWER_BOUND = "2026-08-01T12:00:00.000Z"
ONE_MS_BEFORE_LOWER_BOUND = "2026-08-01T11:59:59.999Z"

RETURNING_RATE_BPS = 400


def _settling_partner(api, network_id, order_total_cents, device_id, order_ref):
    """An `ACTIVE` partner with a valid `W9` holding one attributed August order."""
    partner = activated_partner(api, network_id)
    # §3.9: "when that document's `status` is `VALID` the line uses its
    # `treaty_withholding_bps`", and §3.8: "A `W9` filing must declare a
    # `treaty_withholding_bps` of zero, since there is no treaty to claim."
    valid_tax_document(api, partner["affiliate_id"])
    link = mint_link(api, partner["affiliate_id"])
    order = attributed_order(
        api,
        {"link_id": link["id"]},
        order_total_cents=order_total_cents,
        click_at=CLICK_AT,
        placed_at=PLACED_AT,
        device_id=device_id,
        order_ref=order_ref,
    )
    return {
        "affiliate_id": partner["affiliate_id"],
        "conversion": order["conversion"],
        "conversion_id": order["conversion_id"],
    }


def _over_limit_draft_batch(api):
    """A `DRAFT` batch whose only line carries a `net_payable_cents` of 6,000,000."""
    program = build_program(
        api,
        setup_clock=SETUP_CLOCK,
        returning_customer_rate_bps=RETURNING_RATE_BPS,
    )
    valid_tax_document(api, program["affiliate_id"])
    # 150000000 * 400 / 10000 = 6000000, one million cents above the ceiling.
    order = attributed_order(
        api,
        program,
        order_total_cents=150_000_000,
        click_at=CLICK_AT,
        placed_at=PLACED_AT,
        order_ref="ORD-LIMIT-1",
    )
    assert_cents(order["conversion"], "payable_commission_cents", 6_000_000)

    pin_clock(api, BATCH_CLOCK)
    batch = generate_batch(
        api, program["network_id"], period_start=PERIOD_START, period_end=PERIOD_END
    )
    batch = read_batch(api, batch["id"])
    assert_fields(batch, {"state": "DRAFT"})
    assert_cents(batch, "net_payable_cents", 6_000_000)
    return program, batch


class TestBatchStateOutranksApprovalLimit:
    def test_approving_an_over_limit_draft_batch_reports_the_state_error(self, api):
        """A draft batch above the approval ceiling answers the state error, not the ceiling.

        PRD §2.10: "The batch's `net_payable_cents` is at most 5,000,000 cents —
        otherwise `ERR_APPROVAL_LIMIT_EXCEEDED` (422). Applies to batch approval, and
        is ranked below the state check so that approving an over-limit `DRAFT` batch
        reports the state error."

        Design: Difficulty/priority_pair_validation_conflict/batch_state_check_outranks_approval_limit_on_approve
        """
        _program, batch = _over_limit_draft_batch(api)

        response = api.approve_payout_batch(
            batch["id"], f.approve_batch_payload(batch["version"]), FINANCE_CONTROLLER
        )

        error = assert_error_response(response, ERR_BATCH_NOT_VALIDATED, 409)
        assert error["error_id"] != ERR_APPROVAL_LIMIT_EXCEEDED, (
            "the lower-numbered state check of §2.10 rule 25 must decide the response, "
            "not the fiscal ceiling of rule 49"
        )

        after = read_batch(api, batch["id"])
        assert_fields(after, {"state": "DRAFT"})
        assert_cents(after, "net_payable_cents", 6_000_000)
        assert_null(after, "approved_by_user_id")
        assert_version_unchanged(after, batch["version"], "payout batch")

    def test_approving_an_over_limit_validated_batch_reports_the_ceiling(self, api):
        """Once the state precondition holds, the same over-limit total trips the ceiling.

        PRD §3.9: "A `FinanceController` approves a `VALIDATED` batch, supplying the
        expected batch version. Approval requires the acting user to differ from the
        batch's `prepared_by_user_id`, and requires the batch's `net_payable_cents` to
        be at most 5,000,000 cents."

        Design: Difficulty/priority_pair_validation_conflict/batch_state_check_outranks_approval_limit_on_approve
        """
        _program, batch = _over_limit_draft_batch(api)

        # §3.9: "if `statement_gross_cents` differs at all from the batch's own
        # recomputed `gross_commission_cents`, the request fails".
        validated = validate_batch(
            api,
            batch["id"],
            statement_gross_cents=batch["gross_commission_cents"],
            statement_fee_cents=0,
        )
        assert_fields(validated, {"state": "VALIDATED"})
        assert_cents(validated, "net_payable_cents", 6_000_000)

        response = api.approve_payout_batch(
            batch["id"],
            f.approve_batch_payload(validated["version"]),
            FINANCE_CONTROLLER,
        )

        assert_error_response(response, ERR_APPROVAL_LIMIT_EXCEEDED, 422)

        after = read_batch(api, batch["id"])
        assert_fields(after, {"state": "VALIDATED"})
        assert_null(after, "approved_by_user_id")
        assert_version_unchanged(after, validated["version"], "payout batch")


def _batch_with_untaxed_partner(api):
    """A `DRAFT` batch whose one line belongs to a partner with no tax form at all."""
    program = build_program(
        api,
        setup_clock=SETUP_CLOCK,
        returning_customer_rate_bps=RETURNING_RATE_BPS,
    )
    # 100000 * 400 / 10000 = 4000 gross; a fresh CONTENT partner sits in MEDIUM,
    # so §3.5 grants `credit_share_bps` 10000 and payable equals gross.
    order = attributed_order(
        api,
        program,
        order_total_cents=100_000,
        click_at=CLICK_AT,
        placed_at=PLACED_AT,
        order_ref="ORD-HOLD-1",
    )
    assert_cents(order["conversion"], "payable_commission_cents", 4_000)

    pin_clock(api, BATCH_CLOCK)
    batch = generate_batch(
        api, program["network_id"], period_start=PERIOD_START, period_end=PERIOD_END
    )
    line = first_line(api, batch["id"])
    # §3.9: with no document on file "the line uses the default backup withholding
    # rate of 2400 basis points", so 4000 - (4000 * 2400 / 10000) = 3040.
    assert_cents(line, "net_cents", 3_040)
    return program, read_batch(api, batch["id"]), line


class TestFraudHoldOutranksTaxDocumentCheck:
    def test_releasing_a_fraud_held_line_without_a_tax_form_reports_the_fraud_hold(
        self, api
    ):
        """A fraud-held line on a partner with no tax form answers the fraud-hold error.

        PRD §2.10: "The partner has a tax document whose `status` is `VALID` and whose
        `expires_on` is strictly after the logical clock — otherwise
        `ERR_TAX_DOCUMENT_INVALID` (422). Applies to hold release, and is deliberately
        ranked below the fraud-hold check so that a fraud-held line on a partner with an
        expired form reports the fraud hold."

        Design: Difficulty/priority_pair_validation_conflict/fraud_hold_check_outranks_tax_document_check_on_release_hold
        """
        program, batch, line = _batch_with_untaxed_partner(api)
        assert_fields(line, {"state": "INCLUDED"})

        # §3.7: a `ComplianceAnalyst` suspension moves the partner's `INCLUDED`
        # payout lines on batches that are `DRAFT` or `VALIDATED` "to `HELD_FRAUD`
        # with `hold_reason` `AFFILIATE_SUSPENDED`".
        suspend_partner(api, program["affiliate_id"])

        held = read_line(api, line["id"])
        assert_fields(held, {"state": "HELD_FRAUD", "hold_reason": "AFFILIATE_SUSPENDED"})
        partner = read_affiliate(api, program["affiliate_id"])
        assert_fields(partner, {"tax_document_status": "NONE"})

        response = api.release_hold(
            line["id"], f.release_hold_payload("manual override attempt"), FINANCE_CONTROLLER
        )

        error = assert_error_response(response, ERR_FRAUD_HOLD_NOT_CLEARABLE, 409)
        assert error["error_id"] != ERR_TAX_DOCUMENT_INVALID, (
            "the fraud-hold check outranks the tax-document check on the same call"
        )

        after = read_line(api, line["id"])
        assert_fields(after, {"state": "HELD_FRAUD"})
        assert_cents(after, "net_cents", 3_040)
        assert_null(after, "released_by_user_id")
        assert_version_unchanged(after, held["version"], "payout line")

        # §3.9: `net_payable_cents` includes "only lines that are `INCLUDED` or `PAID`".
        assert_cents(read_batch(api, batch["id"]), "net_payable_cents", 0)

    def test_releasing_a_tax_held_line_without_a_tax_form_reports_the_tax_error(self, api):
        """With no fraud hold in the way, the missing tax form decides the release.

        PRD §3.9: "Release additionally requires the partner to hold a tax document that
        is `VALID` and whose `expires_on` is strictly after the logical clock."

        Design: Difficulty/priority_pair_validation_conflict/fraud_hold_check_outranks_tax_document_check_on_release_hold
        """
        _program, batch, line = _batch_with_untaxed_partner(api)

        # §3.9: "A line whose partner's `tax_document_status` is anything other than
        # `VALID` at validation time moves to `HELD_TAX_DOC`".
        validated = validate_batch(
            api,
            batch["id"],
            statement_gross_cents=batch["gross_commission_cents"],
            statement_fee_cents=0,
        )
        assert_fields(validated, {"state": "VALIDATED"})

        held = read_line(api, line["id"])
        assert_fields(
            held, {"state": "HELD_TAX_DOC", "hold_reason": "TAX_DOCUMENT_NOT_VALID"}
        )

        response = api.release_hold(
            line["id"], f.release_hold_payload("finance waiver"), FINANCE_CONTROLLER
        )

        assert_error_response(response, ERR_TAX_DOCUMENT_INVALID, 422)

        after = read_line(api, line["id"])
        assert_fields(after, {"state": "HELD_TAX_DOC"})
        assert_null(after, "released_by_user_id")
        assert_version_unchanged(after, held["version"], "payout line")


# ── rate-card windows ────────────────────────────────────────────────────────
POLICY_CLOCK = "2026-08-01T00:00:00.000Z"
INCUMBENT_FROM = "2026-01-01T00:00:00.000Z"
INCUMBENT_TO = "2027-01-01T00:00:00.000Z"
INSIDE_LATER = "2026-09-01T00:00:00.000Z"
INSIDE_EARLIER = "2026-06-01T00:00:00.000Z"


def _active_incumbent_card(api):
    """An `ACTIVE` APPAREL/CONTENT card spanning the whole of 2026."""
    incumbent = draft_policy(
        api,
        product_category="APPAREL",
        partner_type_scope=["CONTENT"],
        effective_from=INCUMBENT_FROM,
        effective_to=INCUMBENT_TO,
        policy_code="APPAREL-CONTENT-P1",
    )
    activated = assert_object_response(
        api.activate_commission_policy(
            incumbent["id"],
            f.activate_policy_payload(incumbent["version"]),
            PROGRAM_ADMIN,
        )
    )
    assert_fields(activated, {"status": "ACTIVE"})
    return activated


class TestEffectiveWindowOutranksPolicyOverlap:
    def test_activating_an_inverted_window_inside_an_active_one_reports_the_ordering_error(
        self, api
    ):
        """An inverted window nested inside a live card answers the ordering error.

        PRD §3.3: "Both conditions are enforced only at activation, and in a fixed
        order: the ordering check comes first, so a card whose `effective_to` is at or
        before its `effective_from` is refused with `ERR_INVALID_EFFECTIVE_WINDOW`
        before any overlap is even considered."

        Design: Difficulty/priority_pair_validation_conflict/effective_window_check_outranks_policy_overlap_on_activate
        """
        pin_clock(api, POLICY_CLOCK)
        incumbent = _active_incumbent_card(api)

        # Both endpoints sit strictly inside the incumbent's window, so the overlap
        # rule is violated too — and the inverted ordering must still decide.
        candidate = draft_policy(
            api,
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            effective_from=INSIDE_LATER,
            effective_to=INSIDE_EARLIER,
            policy_code="APPAREL-CONTENT-P2",
        )

        response = api.activate_commission_policy(
            candidate["id"],
            f.activate_policy_payload(candidate["version"]),
            PROGRAM_ADMIN,
        )

        error = assert_error_response(response, ERR_INVALID_EFFECTIVE_WINDOW, 422)
        assert error["error_id"] != ERR_POLICY_WINDOW_OVERLAP, (
            "the ordering check runs before any overlap is even considered"
        )

        after = assert_object_response(
            api.get_commission_policy(candidate["id"], PROGRAM_ADMIN)
        )
        assert_fields(after, {"status": "DRAFT"})
        assert_version_unchanged(after, candidate["version"], "commission policy")

        untouched = assert_object_response(
            api.get_commission_policy(incumbent["id"], PROGRAM_ADMIN)
        )
        assert_fields(untouched, {"status": "ACTIVE"})
        assert_null(untouched, "superseded_by_policy_id")
        assert_version_unchanged(untouched, incumbent["version"], "incumbent policy")

    def test_activating_a_correctly_ordered_overlapping_window_reports_the_overlap(
        self, api
    ):
        """With the endpoints the right way round, the same nesting trips the overlap rule.

        PRD §2.10: "No active rate card with the same product category and an
        intersecting partner-type scope has a window overlapping the activating policy's
        window, unless the two windows are exactly equal — otherwise
        `ERR_POLICY_WINDOW_OVERLAP` (409). Applies to rate-card activation."

        Design: Difficulty/priority_pair_validation_conflict/effective_window_check_outranks_policy_overlap_on_activate
        """
        pin_clock(api, POLICY_CLOCK)
        incumbent = _active_incumbent_card(api)

        candidate = draft_policy(
            api,
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            effective_from=INSIDE_EARLIER,
            effective_to=INSIDE_LATER,
            policy_code="APPAREL-CONTENT-P3",
        )

        response = api.activate_commission_policy(
            candidate["id"],
            f.activate_policy_payload(candidate["version"]),
            PROGRAM_ADMIN,
        )

        assert_error_response(response, ERR_POLICY_WINDOW_OVERLAP, 409)

        after = assert_object_response(
            api.get_commission_policy(candidate["id"], PROGRAM_ADMIN)
        )
        assert_fields(after, {"status": "DRAFT"})
        assert_version_unchanged(after, candidate["version"], "commission policy")

        untouched = assert_object_response(
            api.get_commission_policy(incumbent["id"], PROGRAM_ADMIN)
        )
        assert_fields(untouched, {"status": "ACTIVE"})
        assert_null(untouched, "superseded_by_policy_id")


def _window_program(api):
    """A program whose one link carries an explicit 30-day cookie window."""
    return build_program(
        api,
        setup_clock=WINDOW_CLOCK,
        returning_customer_rate_bps=RETURNING_RATE_BPS,
        link_kwargs={"cookie_window_days": 30, "device_graph_enabled": False},
    )


class TestCookieWindowMillisecondBoundary:
    def test_click_exactly_on_the_inclusive_lower_bound_attributes(self, api):
        """A click landing exactly 30 days before the order is still inside the window.

        PRD §3.5: "A click qualifies only when all of the following hold: its
        `click_type` is `ORGANIC_CLICK`, so a `FORCED_CLICK` and an `IFRAME_IMPRESSION`
        never attribute at all; the tracking link that produced it is currently
        `ACTIVE`; the click's `occurred_at` is at or after the instant obtained by
        subtracting the link's own `cookie_window_days`, converted to days of 86,400
        seconds each, from the order's `placed_at`; the click's `occurred_at` is
        strictly earlier than the order's `placed_at`, so the window is half-open with
        an inclusive lower bound and a strict upper bound; and the click matches the
        order's device."

        Design: Difficulty/boundary_precision_check/cookie_window_half_open_millisecond_boundary_on_attribute
        """
        program = _window_program(api)
        pin_clock(api, WINDOW_CLOCK)

        order = attributed_order(
            api,
            program,
            order_total_cents=133_000,
            click_at=WINDOW_LOWER_BOUND,
            placed_at=WINDOW_PLACED_AT,
            device_id="D1",
        )

        conversion = order["conversion"]
        assert_fields(
            conversion,
            {
                "candidate_click_count": 1,
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "attributed_affiliate_id": program["affiliate_id"],
                "attributed_click_id": order["click_id"],
            },
        )
        # §3.5: gross is "the order's `order_total_cents` multiplied by that rate in
        # basis points, divided by 10,000" — 133000 * 400 / 10000 = 5320 — and the
        # `LAST_CLICK_RAW` share of 10000 bps leaves payable equal to gross.
        assert_cents(conversion, "gross_commission_cents", 5_320)
        assert_cents(conversion, "payable_commission_cents", 5_320)

        stored = read_conversion(api, order["conversion_id"], TRACKING_INGESTOR)
        assert_fields(stored, {"candidate_click_count": 1})
        assert_cents(stored, "payable_commission_cents", 5_320)

        partner = read_affiliate(api, program["affiliate_id"])
        assert_cents(partner, "accrued_balance_cents", 5_320)
        assert_fields(partner, {"attributed_conversion_count": 1})

        entries = assert_total_count(
            api.list_ledger_entries(
                FINANCE_CONTROLLER, {"affiliate_id": program["affiliate_id"]}
            ),
            1,
        )
        assert_fields(entries[0], {"entry_type": "ACCRUAL"})
        assert_cents(entries[0], "amount_cents", 5_320)

    @pytest.mark.parametrize(
        "click_at",
        [
            pytest.param(
                ONE_MS_BEFORE_LOWER_BOUND, id="one_millisecond_before_the_lower_bound"
            ),
            pytest.param(WINDOW_PLACED_AT, id="exactly_on_the_strict_upper_bound"),
        ],
    )
    def test_click_one_millisecond_outside_the_cookie_window_never_attributes(
        self, api, click_at
    ):
        """A click a single millisecond outside either end of the window is not a candidate.

        PRD §3.5: "A click qualifies only when all of the following hold: its
        `click_type` is `ORGANIC_CLICK`, so a `FORCED_CLICK` and an `IFRAME_IMPRESSION`
        never attribute at all; the tracking link that produced it is currently
        `ACTIVE`; the click's `occurred_at` is at or after the instant obtained by
        subtracting the link's own `cookie_window_days`, converted to days of 86,400
        seconds each, from the order's `placed_at`; the click's `occurred_at` is
        strictly earlier than the order's `placed_at`, so the window is half-open with
        an inclusive lower bound and a strict upper bound; and the click matches the
        order's device."

        Design: Difficulty/boundary_precision_check/cookie_window_half_open_millisecond_boundary_on_attribute
        """
        program = _window_program(api)
        pin_clock(api, WINDOW_CLOCK)

        order = attributed_order(
            api,
            program,
            order_total_cents=133_000,
            click_at=click_at,
            placed_at=WINDOW_PLACED_AT,
            device_id="D1",
        )

        conversion = order["conversion"]
        assert_fields(
            conversion, {"candidate_click_count": 0, "attribution_status": "UNATTRIBUTED"}
        )
        assert_null(
            conversion,
            "attributed_affiliate_id",
            "attributed_click_id",
            "commission_policy_id",
        )
        assert_cents(conversion, "gross_commission_cents", 0)
        assert_cents(conversion, "payable_commission_cents", 0)

        # §3.5: "Two audit rows are written even in this case, one per algorithm
        # variant, each with `candidate_click_count` 0, `credit_share_bps` 0,
        # `computed_commission_cents` 0 and a `dedup_reason` of `NO_ELIGIBLE_CLICK`".
        rows, meta = assert_list_response(
            api.list_attribution_decisions(order["conversion_id"], PROGRAM_ADMIN)
        )
        assert_pagination_meta(meta, total_count=2)
        for row in rows:
            assert_fields(
                row,
                {
                    "candidate_click_count": 0,
                    "credit_share_bps": 0,
                    "computed_commission_cents": 0,
                    "dedup_reason": "NO_ELIGIBLE_CLICK",
                    "device_match_mode": "NONE",
                },
            )
            assert_null(row, "winning_click_occurred_at")
        assert sum(1 for row in rows if row["selected"]) == 1, (
            "a `selected` boolean that is true on exactly one row per run"
        )

        partner = read_affiliate(api, program["affiliate_id"])
        assert_cents(partner, "accrued_balance_cents", 0)
        assert_fields(partner, {"attributed_conversion_count": 0})
        assert_total_count(
            api.list_ledger_entries(
                FINANCE_CONTROLLER, {"affiliate_id": program["affiliate_id"]}
            ),
            0,
        )


def _floor_program(api):
    """A network and an `ACTIVE` APPAREL/CONTENT card that prices at 400 bps."""
    pin_clock(api, SETUP_CLOCK)
    network = create_network(api)
    draft_and_activate_policy(
        api,
        product_category="APPAREL",
        partner_type_scope=["CONTENT"],
        returning_customer_rate_bps=RETURNING_RATE_BPS,
        effective_from=INCUMBENT_FROM,
        effective_to=INCUMBENT_TO,
    )
    return network["id"]


class TestMinimumPayoutFloorBoundary:
    def test_line_exactly_at_the_minimum_payout_floor_stays_included(self, api):
        """A line landing exactly on the 2,500-cent floor is payable.

        PRD §3.9: "A line whose recomputed `net_cents` falls below the 2,500-cent
        minimum payout moves to `HELD_BELOW_MINIMUM` with `hold_reason`
        `BELOW_MINIMUM_PAYOUT`; the boundary is inclusive on the pay side, so exactly
        2500 stays `INCLUDED` and 2499 holds."

        Design: Difficulty/boundary_precision_check/minimum_payout_floor_inclusive_boundary_on_batch_generation
        """
        network_id = _floor_program(api)
        # 62500 * 400 / 10000 = 2500, and a zero-fee network with a zero-treaty `W9`
        # carries that figure through to the line's `net_cents` unchanged.
        partner = _settling_partner(api, network_id, 62_500, "FA", "ORD-FLR-A")
        assert_cents(partner["conversion"], "payable_commission_cents", 2_500)

        pin_clock(api, BATCH_CLOCK)
        batch = generate_batch(
            api, network_id, period_start=PERIOD_START, period_end=PERIOD_END
        )

        line = first_line(api, batch["id"])
        assert_cents(line, "net_cents", 2_500)
        assert_fields(line, {"state": "INCLUDED"})
        assert_null(line, "hold_reason")

        stored = read_batch(api, batch["id"])
        assert_fields(stored, {"line_count": 1})
        assert_cents(stored, "gross_commission_cents", 2_500)
        assert_cents(stored, "net_payable_cents", 2_500)
        assert_cents(stored, "withholding_cents", 0)

    def test_line_one_cent_below_the_minimum_payout_floor_holds(self, api):
        """A line one cent under the floor holds and drops out of the payable total.

        PRD §3.9: "A line whose recomputed `net_cents` falls below the 2,500-cent
        minimum payout moves to `HELD_BELOW_MINIMUM` with `hold_reason`
        `BELOW_MINIMUM_PAYOUT`; the boundary is inclusive on the pay side, so exactly
        2500 stays `INCLUDED` and 2499 holds."

        Design: Difficulty/boundary_precision_check/minimum_payout_floor_inclusive_boundary_on_batch_generation
        """
        network_id = _floor_program(api)
        # 62475 * 400 / 10000 = 2499 exactly, one cent short of the floor.
        partner = _settling_partner(api, network_id, 62_475, "FB", "ORD-FLR-B")
        assert_cents(partner["conversion"], "payable_commission_cents", 2_499)

        pin_clock(api, BATCH_CLOCK)
        batch = generate_batch(
            api, network_id, period_start=PERIOD_START, period_end=PERIOD_END
        )

        line = first_line(api, batch["id"])
        assert_cents(line, "net_cents", 2_499)
        assert_fields(
            line, {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"}
        )

        stored = read_batch(api, batch["id"])
        assert_fields(stored, {"line_count": 1})
        assert_cents(stored, "gross_commission_cents", 2_499)
        assert_cents(stored, "net_payable_cents", 0)

    def test_batch_rollup_counts_the_held_line_in_gross_but_not_in_payable(self, api):
        """Two lines a cent apart across the floor split the batch's two totals.

        PRD §3.9: "Which lines contribute also differs by total:
        `gross_commission_cents` and `clawback_cents` include **every** line whatever
        its state, except that a `VOIDED` line contributes to neither, so that the
        reconciliation check sees the full statement-side gross; while
        `network_fee_cents`, `withholding_cents` and `net_payable_cents` include only
        lines that are `INCLUDED` or `PAID`."

        Design: Difficulty/boundary_precision_check/minimum_payout_floor_inclusive_boundary_on_batch_generation
        """
        network_id = _floor_program(api)
        _settling_partner(api, network_id, 62_500, "FA", "ORD-FLR-A")
        _settling_partner(api, network_id, 62_475, "FB", "ORD-FLR-B")

        pin_clock(api, BATCH_CLOCK)
        batch = generate_batch(
            api, network_id, period_start=PERIOD_START, period_end=PERIOD_END
        )

        lines = batch_lines(api, batch["id"])
        assert len(lines) == 2, f"expected one line per partner, got {len(lines)}"
        by_net = {line["net_cents"]: line for line in lines}
        assert set(by_net) == {2_500, 2_499}, (
            f"expected lines of 2500 and 2499 net cents, got {sorted(by_net)}"
        )
        assert_fields(by_net[2_500], {"state": "INCLUDED"})
        assert_null(by_net[2_500], "hold_reason")
        assert_fields(
            by_net[2_499],
            {"state": "HELD_BELOW_MINIMUM", "hold_reason": "BELOW_MINIMUM_PAYOUT"},
        )

        stored = read_batch(api, batch["id"])
        assert_fields(stored, {"line_count": 2})
        assert_cents(stored, "gross_commission_cents", 4_999)
        assert_cents(stored, "net_payable_cents", 2_500)
        assert_cents(stored, "withholding_cents", 0)
