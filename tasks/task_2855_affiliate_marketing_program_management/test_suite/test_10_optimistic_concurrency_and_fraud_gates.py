"""Version-guarded writes across the program, and the fraud-score suspension gate.

Every guarded route takes the parent version the caller last observed; a
legitimate intervening write advances that version, the replayed guard is
refused with its own 412 and nothing is persisted, and the refreshed guard then
succeeds.  The last class covers the point-in-time fraud score that suspends an
active partner at its threshold but not one point below it.
"""

import pytest

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_STALE_AFFILIATE_VERSION,
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_CONVERSION_VERSION,
    ERR_STALE_POLICY_VERSION,
)
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_null,
    assert_object_response,
    assert_one_decimal_score,
    assert_pagination_meta,
    assert_total_count,
    assert_version_bumped,
    assert_version_unchanged,
)
from test_helpers.fixtures import (
    attributed_order,
    build_program,
    create_conversion,
    create_network,
    draft_policy,
    file_tax_document,
    first_line,
    generate_batch,
    ingest_click,
    open_case,
    pin_clock,
    read_affiliate,
    read_batch,
    read_conversion,
    read_line,
    release_line_hold,
    screened_partner,
    valid_tax_document,
    validate_batch,
)
from test_helpers.test_users import (
    FINANCE_CONTROLLER,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

CLOCK = f.JUL_05_00_00
SETTLEMENT_CLOCK = f.AUG_05_00_00


class TestStaleAffiliateVersionGuardOnDecide:
    def test_tax_filing_staleness_blocks_a_decision_until_the_guard_is_refreshed(
        self, api
    ):
        """A tax filing advances the applicant's version, so a cached decide guard is refused.

        PRD §2.7: "Deciding an application requires `expected_affiliate_version`
        matching the applicant partner's current `version`. A mismatch is rejected with
        `ERR_STALE_AFFILIATE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_affiliate_version_on_decide_rejected_then_fresh_version_succeeds
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        screened = screened_partner(api, network["id"])
        affiliate_id = screened["affiliate_id"]
        application_id = screened["application_id"]
        stale_affiliate_version = screened["affiliate"]["version"]
        application_version = screened["application"]["version"]
        assert_fields(
            screened["application"],
            {"review_state": "SCREENED", "screening_outcome": "PASS"},
        )

        # §3.8: "Filing creates the document at `PENDING`, sets the partner's mirrored
        # `tax_document_status` to `PENDING`, and increments the partner's `version`
        # while leaving the partner's own `status` untouched."
        file_tax_document(api, affiliate_id)
        refreshed = read_affiliate(api, affiliate_id)
        assert_version_bumped(refreshed, stale_affiliate_version, "applicant partner")
        assert_fields(
            refreshed,
            {"status": "PENDING_APPLICATION", "tax_document_status": "PENDING"},
        )
        fresh_affiliate_version = refreshed["version"]

        refused = api.decide_application(
            application_id,
            f.decide_payload("APPROVE", stale_affiliate_version),
            PARTNER_MANAGER,
        )
        assert_error_response(refused, ERR_STALE_AFFILIATE_VERSION, 412)

        # §2.7: "If that value differs from the parent's current `version`, the write is
        # refused and nothing is persisted."
        after_refusal = read_affiliate(api, affiliate_id)
        assert_version_unchanged(
            after_refusal, fresh_affiliate_version, "applicant partner"
        )
        assert_field(after_refusal, "status", "PENDING_APPLICATION")
        application_after = assert_object_response(
            api.get_application(application_id, PARTNER_MANAGER)
        )
        assert_version_unchanged(application_after, application_version, "application")
        assert_field(application_after, "review_state", "SCREENED")

        approved = assert_object_response(
            api.decide_application(
                application_id,
                f.decide_payload("APPROVE", fresh_affiliate_version),
                PARTNER_MANAGER,
            )
        )
        assert_field(approved, "review_state", "APPROVED")
        assert_version_bumped(approved, application_version, "application")

        # §3.2: "It cascades the applicant partner `PENDING_APPLICATION → ACTIVE`."
        activated = read_affiliate(api, affiliate_id)
        assert_fields(activated, {"status": "ACTIVE", "suspension_cause": "NONE"})
        assert_version_bumped(
            activated, fresh_affiliate_version, "applicant partner"
        )


class TestStaleConversionVersionGuardOnAttribution:
    def test_late_click_staleness_blocks_attribution_until_the_guard_is_refreshed(
        self, api
    ):
        """A click ingested inside the cookie window makes a cached attribution guard stale.

        PRD §2.7: "Running attribution on an order requires
        `expected_conversion_version` matching that order's current `version`. A mismatch
        is rejected with `ERR_STALE_CONVERSION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_conversion_version_on_attribute_rejected_after_late_click
        """
        program = build_program(
            api,
            setup_clock=CLOCK,
            returning_customer_rate_bps=400,
            link_kwargs={"cookie_window_days": 30, "device_graph_enabled": False},
        )
        early_click = ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_10_00, device_id="D1"
        )
        conversion = create_conversion(
            api,
            order_total_cents=5000,
            is_new_customer=False,
            placed_at=f.JUL_04_12_00,
            device_id="D1",
            other_channel_touch="NONE",
        )
        conversion_id = conversion["id"]
        stale_conversion_version = conversion["version"]
        assert_field(conversion, "candidate_click_count", 1)

        # §3.4: "For every order that is still `UNATTRIBUTED` and whose cookie window the
        # new click falls inside, the server recomputes that order's
        # `candidate_click_count` and increments that order's `version` by 1."
        late_click = ingest_click(
            api, program["link_id"], occurred_at=f.JUL_04_11_00, device_id="D1"
        )
        refreshed = read_conversion(api, conversion_id)
        assert_version_bumped(refreshed, stale_conversion_version, "order")
        assert_fields(
            refreshed,
            {"candidate_click_count": 2, "attribution_status": "UNATTRIBUTED"},
        )
        fresh_conversion_version = refreshed["version"]

        refused = api.attribute_conversion(
            conversion_id,
            f.attribute_payload(stale_conversion_version),
            TRACKING_INGESTOR,
        )
        assert_error_response(refused, ERR_STALE_CONVERSION_VERSION, 412)

        # §2.7: "If that value differs from the parent's current `version`, the write is
        # refused and nothing is persisted."
        after_refusal = read_conversion(api, conversion_id)
        assert_version_unchanged(after_refusal, fresh_conversion_version, "order")
        assert_field(after_refusal, "attribution_status", "UNATTRIBUTED")
        assert_total_count(
            api.list_attribution_decisions(conversion_id, PROGRAM_ADMIN), 0
        )
        assert_total_count(
            api.list_ledger_entries(PROGRAM_ADMIN, {"conversion_id": conversion_id}), 0
        )

        attributed = assert_object_response(
            api.attribute_conversion(
                conversion_id,
                f.attribute_payload(fresh_conversion_version),
                TRACKING_INGESTOR,
            )
        )
        assert_field(attributed, "attribution_status", "AFFILIATE_ATTRIBUTED")
        assert_version_bumped(attributed, fresh_conversion_version, "order")
        assert_field(attributed, "candidate_click_count", 2)
        assert_field(attributed, "attributed_affiliate_id", program["affiliate_id"])
        # §3.5: "The eligible set is ranked by `occurred_at` descending, and ties on that
        # instant are broken by `created_at` descending, so the most recently recorded of
        # two simultaneous clicks wins."
        assert attributed["attributed_click_id"] == late_click["id"], (
            "the 11:00 click is the last click inside the window, not the 10:00 click "
            f"{early_click['id']}"
        )
        assert_cents(attributed, "gross_commission_cents", 200)  # 5000 * 400 / 10000
        assert_cents(attributed, "payable_commission_cents", 200)  # credit share 10000

        rows, meta = assert_list_response(
            api.list_attribution_decisions(conversion_id, PROGRAM_ADMIN)
        )
        assert_pagination_meta(meta, total_count=2)
        selected = [row for row in rows if row["selected"]]
        assert len(selected) == 1, (
            "§3.5 writes one row per variant with "
            f"\"a `selected` boolean that is true on exactly one row per run\", got {len(selected)}"
        )
        assert_field(selected[0], "algorithm_variant", "LAST_CLICK_RAW")
        assert_bps(selected[0], "credit_share_bps", 10000)
        assert_cents(selected[0], "computed_commission_cents", 200)
        assert_fields(
            selected[0],
            {
                "winning_click_occurred_at": f.JUL_04_11_00,
                "device_match_mode": "DEVICE_EXACT",
            },
        )


class TestStaleBatchVersionGuardOnApproval:
    def test_hold_release_staleness_blocks_approval_until_the_guard_is_refreshed(
        self, api
    ):
        """Releasing a tax hold re-prices the batch, so a cached approval guard is refused.

        PRD §2.7: "Approving a payout batch requires `expected_batch_version` matching
        that batch's current `version`. A mismatch is rejected with
        `ERR_STALE_BATCH_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_batch_version_on_approve_rejected_after_release_hold
        """
        program = build_program(
            api,
            setup_clock=CLOCK,
            fee_bps=0,
            returning_customer_rate_bps=400,
            link_kwargs={"cookie_window_days": 30},
        )
        affiliate_id = program["affiliate_id"]
        order = attributed_order(
            api, program, order_total_cents=100000, is_new_customer=False
        )
        assert_cents(order["conversion"], "payable_commission_cents", 4000)

        pin_clock(api, SETTLEMENT_CLOCK)
        batch = generate_batch(api, program["network_id"])
        batch_id = batch["id"]
        assert_cents(batch, "gross_commission_cents", 4000)
        assert_cents(batch, "network_fee_cents", 0)
        # §3.9: with no document on file "the line uses the default backup withholding
        # rate of 2400 basis points", so 4000 - 960 = 3040 is payable at generation.
        assert_cents(batch, "net_payable_cents", 3040)
        line = first_line(api, batch_id)
        line_id = line["id"]
        assert_field(line, "state", "INCLUDED")

        # §3.9: "A line whose partner's `tax_document_status` is anything other than
        # `VALID` at validation time moves to `HELD_TAX_DOC` with `hold_reason`
        # `TAX_DOCUMENT_NOT_VALID`."
        validated = validate_batch(api, batch_id, 4000, 0)
        assert_field(validated, "state", "VALIDATED")
        assert_cents(validated, "net_payable_cents", 0)
        stale_batch_version = validated["version"]
        held_line = read_line(api, line_id)
        assert_fields(
            held_line,
            {"state": "HELD_TAX_DOC", "hold_reason": "TAX_DOCUMENT_NOT_VALID"},
        )

        # §3.9: "On success the line returns to `INCLUDED`, its `hold_reason` clears to
        # null, `released_by_user_id` records the controller, the line is recomputed, and
        # the batch's `network_fee_cents`, `withholding_cents` and `net_payable_cents` are
        # recomputed with the batch's `version` incremented while its `state` stays
        # exactly as it was."
        valid_tax_document(api, affiliate_id)
        released_line = release_line_hold(
            api, line_id, reason="W9 verified after validation"
        )
        assert_fields(released_line, {"state": "INCLUDED", "hold_reason": None})
        assert_bps(released_line, "withholding_bps", 0)
        assert_cents(released_line, "withholding_cents", 0)
        assert_cents(released_line, "net_cents", 4000)
        repriced = read_batch(api, batch_id)
        assert_version_bumped(repriced, stale_batch_version, "payout batch")
        assert_field(repriced, "state", "VALIDATED")
        assert_cents(repriced, "net_payable_cents", 4000)
        fresh_batch_version = repriced["version"]

        refused = api.approve_payout_batch(
            batch_id, f.approve_batch_payload(stale_batch_version), FINANCE_CONTROLLER
        )
        assert_error_response(refused, ERR_STALE_BATCH_VERSION, 412)

        # §2.7: "If that value differs from the parent's current `version`, the write is
        # refused and nothing is persisted."
        after_refusal = read_batch(api, batch_id)
        assert_version_unchanged(after_refusal, fresh_batch_version, "payout batch")
        assert_field(after_refusal, "state", "VALIDATED")
        assert_cents(read_affiliate(api, affiliate_id), "reserved_balance_cents", 0)

        # §3.9: "On success the batch moves to `APPROVED` with `approved_by_user_id`
        # recorded, and for every `INCLUDED` line the line's `net_before_fees_cents` moves
        # out of the partner's `accrued_balance_cents` and into its
        # `reserved_balance_cents`, with each reserved partner's `version` incremented."
        approved = assert_object_response(
            api.approve_payout_batch(
                batch_id,
                f.approve_batch_payload(fresh_batch_version),
                FINANCE_CONTROLLER,
            )
        )
        assert_field(approved, "state", "APPROVED")
        assert_version_bumped(approved, fresh_batch_version, "payout batch")
        settled_partner = read_affiliate(api, affiliate_id)
        assert_cents(settled_partner, "reserved_balance_cents", 4000)
        assert_cents(settled_partner, "accrued_balance_cents", 0)


class TestStalePolicyVersionGuardOnActivation:
    @pytest.mark.parametrize(
        "guard_offset",
        [
            pytest.param(-1, id="one_below_the_current_version"),
            pytest.param(1, id="one_above_the_current_version"),
        ],
    )
    def test_activation_refuses_a_guard_that_is_not_the_cards_current_version(
        self, api, guard_offset
    ):
        """A rate card activates only on the version the activator actually observed.

        PRD §2.7: "Activating a rate card requires `expected_policy_version` matching
        that policy's current `version`. A mismatch is rejected with
        `ERR_STALE_POLICY_VERSION` (HTTP 412) — a schedule that has been edited since the
        activator read it cannot be activated on the stale view."

        Design: Corner/cross_cutting_complexity_layers/policy_activation_rejects_a_stale_expected_policy_version
        """
        pin_clock(api, CLOCK)
        policy = draft_policy(api)
        policy_id = policy["id"]
        current_version = policy["version"]
        # §3.3: "A new rate card is written with `status` `DRAFT` and a null
        # `superseded_by_policy_id`."
        assert_fields(policy, {"status": "DRAFT", "version": 1})

        refused = api.activate_commission_policy(
            policy_id,
            f.activate_policy_payload(current_version + guard_offset),
            PROGRAM_ADMIN,
        )
        assert_error_response(refused, ERR_STALE_POLICY_VERSION, 412)

        # §2.7: "If that value differs from the parent's current `version`, the write is
        # refused and nothing is persisted."
        after_refusal = assert_object_response(
            api.get_commission_policy(policy_id, PROGRAM_ADMIN)
        )
        assert_version_unchanged(after_refusal, current_version, "rate card")
        assert_field(after_refusal, "status", "DRAFT")
        assert_total_count(
            api.list_commission_policies(PROGRAM_ADMIN, {"status": "ACTIVE"}), 0
        )

        # §3.3: "Activation moves the card `DRAFT → ACTIVE` and increments its `version`."
        activated = assert_object_response(
            api.activate_commission_policy(
                policy_id, f.activate_policy_payload(current_version), PROGRAM_ADMIN
            )
        )
        assert_field(activated, "status", "ACTIVE")
        assert_version_bumped(activated, current_version, "rate card")
        assert_null(activated, "superseded_by_policy_id")
        active_rows = assert_total_count(
            api.list_commission_policies(PROGRAM_ADMIN, {"status": "ACTIVE"}), 1
        )
        assert_field(active_rows[0], "id", policy_id)


class TestFraudScoreAutoSuspensionThreshold:
    """The point-in-time fraud score is the sum of the open cases' severity weights.

    §3.7: "It counts only cases whose `state` is `OPEN`, `REMEDIATION_REQUESTED`,
    `REMEDIATION_SUBMITTED`, `ESCALATED` or `UPHELD`, sums their `severity_weight`
    values, and caps the result at 100."
    """

    def test_open_cases_summing_to_sixty_five_leave_the_partner_active(self, api):
        """Cookie stuffing plus an unauthorized coupon score 65 and do not suspend.

        PRD §3.7: "Whenever a recompute leaves an `ACTIVE` partner's point-in-time
        `fraud_risk_score` at 70 or above, the program suspends that partner in the same
        request, setting `status` to `SUSPENDED` and `suspension_cause` to
        `FRAUD_SCORE_BREACH`, and the suspension cascade described in §2.11 runs in full:
        every `ACTIVE` partner whose `parent_affiliate_id` is this partner is suspended
        with `suspension_cause` `PARENT_SUSPENSION`; for every partner newly suspended in
        the request, its `ACTIVE` tracking links are disabled with `disabled_reason`
        `AFFILIATE_SUSPENDED` and its `INCLUDED` payout lines on batches that are `DRAFT`
        or `VALIDATED` move to `HELD_FRAUD` with `hold_reason` `AFFILIATE_SUSPENDED`; and
        the `network_fee_cents`, `withholding_cents` and `net_payable_cents` totals of
        every touched batch are recomputed."

        Design: Corner/cross_cutting_complexity_layers/fraud_point_in_time_score_auto_suspends_at_seventy_but_not_at_sixty_five
        """
        program = build_program(
            api, setup_clock=CLOCK, with_policy=False, with_link=False
        )
        affiliate_id = program["affiliate_id"]
        assert_field(program["affiliate"], "status", "ACTIVE")

        # §3.7: "a `severity_weight` copied from the fixed severity table at creation: 40
        # for `COOKIE_STUFFING`, 30 for `FORCED_CLICK`, 25 for `UNAUTHORIZED_COUPON` and
        # 20 for `TRADEMARK_BIDDING`."
        stuffing = open_case(
            api, affiliate_id, violation_type="COOKIE_STUFFING", detected_at=CLOCK
        )
        assert_field(stuffing, "severity_weight", 40)
        coupon = open_case(
            api, affiliate_id, violation_type="UNAUTHORIZED_COUPON", detected_at=CLOCK
        )
        assert_field(coupon, "severity_weight", 25)
        assert_fields(stuffing, {"state": "OPEN"})
        assert_fields(coupon, {"state": "OPEN"})

        partner = read_affiliate(api, affiliate_id)
        assert_field(partner, "fraud_risk_score", 65)  # 40 + 25, one point under 70
        # Both cases were detected at the current clock, so the age is 0 whole days and
        # the decay is 1.00 on each: 40 + 25 = 65.0 on the trailing variant too.
        assert_one_decimal_score(partner, "fraud_risk_score_trailing", 65.0)
        assert_fields(partner, {"status": "ACTIVE", "suspension_cause": "NONE"})

    def test_open_cases_summing_to_exactly_seventy_auto_suspend_the_partner(self, api):
        """Adding a forced-click case to a cookie-stuffing case hits 70 and suspends at once.

        PRD §3.7: "Whenever a recompute leaves an `ACTIVE` partner's point-in-time
        `fraud_risk_score` at 70 or above, the program suspends that partner in the same
        request, setting `status` to `SUSPENDED` and `suspension_cause` to
        `FRAUD_SCORE_BREACH`, and the suspension cascade described in §2.11 runs in full:
        every `ACTIVE` partner whose `parent_affiliate_id` is this partner is suspended
        with `suspension_cause` `PARENT_SUSPENSION`; for every partner newly suspended in
        the request, its `ACTIVE` tracking links are disabled with `disabled_reason`
        `AFFILIATE_SUSPENDED` and its `INCLUDED` payout lines on batches that are `DRAFT`
        or `VALIDATED` move to `HELD_FRAUD` with `hold_reason` `AFFILIATE_SUSPENDED`; and
        the `network_fee_cents`, `withholding_cents` and `net_payable_cents` totals of
        every touched batch are recomputed."

        Design: Corner/cross_cutting_complexity_layers/fraud_point_in_time_score_auto_suspends_at_seventy_but_not_at_sixty_five
        """
        program = build_program(
            api, setup_clock=CLOCK, with_policy=False, with_link=False
        )
        affiliate_id = program["affiliate_id"]
        assert_field(program["affiliate"], "status", "ACTIVE")

        stuffing = open_case(
            api, affiliate_id, violation_type="COOKIE_STUFFING", detected_at=CLOCK
        )
        assert_field(stuffing, "severity_weight", 40)
        after_first = read_affiliate(api, affiliate_id)
        assert_field(after_first, "fraud_risk_score", 40)  # 40 alone stays under 70
        assert_fields(after_first, {"status": "ACTIVE", "suspension_cause": "NONE"})

        forced = open_case(
            api, affiliate_id, violation_type="FORCED_CLICK", detected_at=CLOCK
        )
        assert_field(forced, "severity_weight", 30)
        # §3.7: the suspension is a side effect of the create, not a case transition.
        assert_field(forced, "state", "OPEN")

        suspended = read_affiliate(api, affiliate_id)
        assert_field(suspended, "fraud_risk_score", 70)  # 40 + 30, exactly the threshold
        assert_one_decimal_score(suspended, "fraud_risk_score_trailing", 70.0)
        assert_fields(
            suspended,
            {"status": "SUSPENDED", "suspension_cause": "FRAUD_SCORE_BREACH"},
        )
