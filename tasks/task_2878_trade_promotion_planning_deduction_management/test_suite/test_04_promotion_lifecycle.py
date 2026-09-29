"""
Promotion lifecycle: submission, rework, approval and the operations checkpoint.

Every test builds its own preconditions against an empty database and exercises
the lifecycle rules of PRD §3.3, §3.6 and §3.7 — the bounded revision loop, the
state guards on submit and on tactic maintenance, the dense approval
precondition set, and the four identifier lists the activation run reports.
"""

from test_helpers import (
    ApiErrorId,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_AUG_31,
    assert_money,
    assert_ratio,
    cancel_tactic_payload,
    create_accrual_payload,
    create_deduction_payload,
    create_volume_fact_payload,
    current_promotion_version,
    instant,
    match_deduction_payload,
    patch_tactic_payload,
    read_allocation,
    read_promotion,
    read_tactic,
    request_changes_payload,
    same_instant,
    set_clock,
    setup_allocation_context,
    setup_approved_promotion,
    setup_approved_promotion_with_lines,
    setup_draft_promotion,
    setup_promotion_with_lines,
    setup_promotion_with_tpr_line,
    setup_verified_commitment_document,
    setup_verified_evidence_document,
    validate_deduction_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPromotionRevisionCycle:
    """The rework loop out of `SUBMITTED` is bounded at two revisions."""

    def test_two_rework_loops_are_permitted_and_end_in_draft(
        self, api, key_account_manager, director
    ):
        """
        Two full submit / request-changes / revise loops leave `revision_round` at 2.

        PRD: "Each revise increments `revision_round` by 1, and it is permitted only while `revision_round` is still below 2."
        PRD: "The full cycle is therefore `DRAFT` → `SUBMITTED` → `CHANGES_REQUESTED` → `DRAFT`, traversable twice; a third attempt to revise is refused with `ERR_MAX_REVISION_ROUNDS` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/promotion_revision_cycle_bounded_at_two_rounds
        """
        context = setup_promotion_with_tpr_line(
            api,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_31,
        )
        promotion_id = context["promotion"]["id"]
        assert context["promotion"]["revision_round"] == 0

        for expected_round in (1, 2):
            submitted = validate_success(
                api.submit_promotion(promotion_id, key_account_manager)
            )
            assert submitted["lifecycle_status"] == "SUBMITTED"
            sent_back = validate_success(
                api.request_changes_promotion(
                    promotion_id, request_changes_payload(), director
                )
            )
            assert sent_back["lifecycle_status"] == "CHANGES_REQUESTED"
            revised = validate_success(
                api.revise_promotion(promotion_id, key_account_manager)
            )
            assert revised["lifecycle_status"] == "DRAFT"
            assert revised["revision_round"] == expected_round

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "DRAFT"
        assert promotion["revision_round"] == 2
        assert_money(
            promotion["tactic_subtotal_amount"], 10000.00, "tactic_subtotal_amount"
        )
        assert_ratio(promotion["allowance_rate"], 0.020, "allowance_rate")
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")

    def test_third_revise_is_refused_and_leaves_the_promotion_in_rework(
        self, api, key_account_manager, director
    ):
        """
        A third revise is refused and the promotion stays in `CHANGES_REQUESTED`.

        PRD: "Each revise increments `revision_round` by 1, and it is permitted only while `revision_round` is still below 2."
        PRD: "The full cycle is therefore `DRAFT` → `SUBMITTED` → `CHANGES_REQUESTED` → `DRAFT`, traversable twice; a third attempt to revise is refused with `ERR_MAX_REVISION_ROUNDS` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/promotion_revision_cycle_bounded_at_two_rounds
        """
        context = setup_promotion_with_tpr_line(
            api,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=8000,
            rate_per_case=1.250,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_31,
        )
        promotion_id = context["promotion"]["id"]
        tactic_id = context["tactic"]["id"]

        for _ in range(2):
            validate_success(api.submit_promotion(promotion_id, key_account_manager))
            validate_success(
                api.request_changes_promotion(
                    promotion_id, request_changes_payload(), director
                )
            )
            validate_success(api.revise_promotion(promotion_id, key_account_manager))

        validate_success(api.submit_promotion(promotion_id, key_account_manager))
        sent_back = validate_success(
            api.request_changes_promotion(
                promotion_id, request_changes_payload(), director
            )
        )
        assert sent_back["lifecycle_status"] == "CHANGES_REQUESTED"
        assert sent_back["revision_round"] == 2

        validate_error(
            api.revise_promotion(promotion_id, key_account_manager),
            ApiErrorId.MAX_REVISION_ROUNDS.value,
        )

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "CHANGES_REQUESTED"
        assert promotion["revision_round"] == 2
        assert read_tactic(api, tactic_id)["status"] == "PLANNED"


class TestSubmitFromChangesRequested:
    """`CHANGES_REQUESTED` is not a submittable state; a revise comes first."""

    def test_submit_from_changes_requested_needs_a_revise_first(
        self, api, key_account_manager, director
    ):
        """
        Submit is refused out of `CHANGES_REQUESTED` and accepted after the revise.

        PRD: "A `KeyAccountManager` submits a promotion that is currently `DRAFT`, moving `lifecycle_status` `DRAFT` → `SUBMITTED`."
        PRD: "**Rung 43** — the promotion's `lifecycle_status` permits the requested transition, on promotion submit, request-changes, revise, approve and withdraw, on tactic create, tactic patch and tactic cancel, on document attach, on accrual post and on analyze: `ERR_PROMOTION_STATE_INVALID`."
        PRD: "A `KeyAccountManager` revises a promotion that is currently `CHANGES_REQUESTED`, moving `lifecycle_status` `CHANGES_REQUESTED` → `DRAFT`, which unlocks tactic editing again."

        Design: Corner/state_machines/submit_after_changes_requested_needs_a_revise_first
        """
        context = setup_promotion_with_tpr_line(
            api,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=2000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_10,
        )
        promotion_id = context["promotion"]["id"]

        validate_success(api.submit_promotion(promotion_id, key_account_manager))
        sent_back = validate_success(
            api.request_changes_promotion(
                promotion_id, request_changes_payload(), director
            )
        )
        assert sent_back["lifecycle_status"] == "CHANGES_REQUESTED"
        assert sent_back["revision_round"] == 0

        validate_error(
            api.submit_promotion(promotion_id, key_account_manager),
            ApiErrorId.PROMOTION_STATE_INVALID.value,
        )
        assert read_promotion(api, promotion_id)["lifecycle_status"] == (
            "CHANGES_REQUESTED"
        )

        revised = validate_success(
            api.revise_promotion(promotion_id, key_account_manager)
        )
        assert revised["lifecycle_status"] == "DRAFT"
        assert revised["revision_round"] == 1

        resubmitted = validate_success(
            api.submit_promotion(promotion_id, key_account_manager)
        )
        assert resubmitted["lifecycle_status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == 1


class TestActivationRunLifecycleWalk:
    """One checkpoint run can carry a wholly past promotion two states forward."""

    def test_one_run_walks_approved_then_live_then_ended(
        self, api, finance_analyst
    ):
        """
        A promotion whose window is entirely past reaches `ENDED` in a single run.

        PRD: "Promotions are processed in `created_at` ascending order, and within a single run **activation is evaluated before ending**: every `APPROVED` promotion whose `window_start` is at or before the clock date moves `APPROVED` → `LIVE`, and then every `LIVE` promotion whose `window_end` is at or before the clock date moves `LIVE` → `ENDED`."
        PRD: "The consequence is that a promotion whose entire window lies in the past traverses `APPROVED` → `LIVE` → `ENDED` in one call."
        PRD: "Tactic lines move in step: a line whose window contains the clock date — its `window_start` at or before the clock date and its `window_end` strictly after it — moves `PLANNED` → `ACTIVE`; a line whose `window_end` is at or before the clock date moves `ACTIVE` → `COMPLETED`, or `PLANNED` → `COMPLETED` when its owning promotion made the `LIVE` → `ENDED` move in the same run without the line ever having been activated."

        Design: Corner/state_machines/one_activation_run_walks_approved_then_live_then_ended
        """
        context = setup_approved_promotion(
            api,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=2000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_10,
        )
        promotion_id = context["promotion"]["id"]
        tactic_id = context["tactic"]["id"]
        version_after_approve = context["promotion"]["version"]
        assert context["promotion"]["lifecycle_status"] == "APPROVED"

        set_clock(api, instant("2026-09-01"))
        run = validate_success(
            api.create_promotion_activation_run(finance_analyst)
        )

        assert promotion_id in run["promotions_activated"]
        assert promotion_id in run["promotions_ended"]
        assert tactic_id in run["tactics_completed"]
        assert tactic_id not in run["tactics_activated"]

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "ENDED"
        assert promotion["version"] > version_after_approve
        assert read_tactic(api, tactic_id)["status"] == "COMPLETED"

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["committed_amount"], 2000.00, "committed_amount")

    def test_activation_run_touches_only_the_line_covering_the_clock_date(
        self, api, finance_analyst, director
    ):
        """
        Only the line whose half-open window contains the clock date activates.

        PRD: "Tactic lines move in step: a line whose window contains the clock date — its `window_start` at or before the clock date and its `window_end` strictly after it — moves `PLANNED` → `ACTIVE`; a line whose `window_end` is at or before the clock date moves `ACTIVE` → `COMPLETED`, or `PLANNED` → `COMPLETED` when its owning promotion made the `LIVE` → `ENDED` move in the same run without the line ever having been activated."
        PRD: "Promotions are processed in `created_at` ascending order, and within a single run **activation is evaluated before ending**: every `APPROVED` promotion whose `window_start` is at or before the clock date moves `APPROVED` → `LIVE`, and then every `LIVE` promotion whose `window_end` is at or before the clock date moves `LIVE` → `ENDED`."

        Design: Corner/state_machines/activation_run_touches_only_the_line_covering_the_clock_date
        """
        context = setup_approved_promotion_with_lines(
            api,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 1000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
                {
                    "tactic_type": "TPR",
                    "planned_units": 1000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_24,
                    "window_end": MONDAY_AUG_31,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )
        promotion_id = context["promotion"]["id"]
        early_id = context["tactics"][0]["id"]
        late_id = context["tactics"][1]["id"]

        set_clock(api, instant(MONDAY_AUG_03))
        run = validate_success(
            api.create_promotion_activation_run(finance_analyst)
        )

        assert run["promotions_activated"] == [promotion_id]
        assert run["promotions_ended"] == []
        assert run["tactics_activated"] == [early_id]
        assert run["tactics_completed"] == []

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "LIVE"
        assert read_tactic(api, early_id)["status"] == "ACTIVE"
        assert read_tactic(api, late_id)["status"] == "PLANNED"

        rows, meta = validate_paginated(
            api.list_promotion_tactics(
                promotion_id, director, params={"status": "PLANNED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == late_id

        assert_money(
            promotion["tactic_subtotal_amount"], 2000.00, "tactic_subtotal_amount"
        )
        assert promotion["committed_units"] == 2000


class TestCancellingALineDropsItFromTheRollup:
    """A cancelled line leaves the planning population and can lower the band."""

    def test_cancelling_a_line_drops_it_out_of_the_planning_rollup(
        self, api, key_account_manager
    ):
        """
        Cancelling the larger line pulls `allowance_rate` back down across a band boundary.

        PRD: "A `KeyAccountManager` may cancel a line that is still `PLANNED` on a promotion that is still `DRAFT`, optionally recording a `cancel_reason`; the line moves `PLANNED` → `CANCELLED`, which is terminal, and the row is preserved so the planning history stays auditable."
        PRD: "Cancellation drops the line out of `tactic_subtotal_amount`, which can pull `allowance_rate` back down across a band boundary, and out of `committed_units`; it re-evaluates commitment coverage, so cancelling the only `DISPLAY` line can flip `commitment_verified` from false to true; and it releases the line from the three trade-calendar contention sets of §3.4, all of which read only lines in `PLANNED`, `ACTIVE` or `COMPLETED`."
        PRD: "**Step two:** the off-invoice `allowance_rate` is selected from a three-band schedule read against `tactic_subtotal_amount` and **nothing else** — a subtotal below ten thousand dollars earns no allowance at all, a rate of 0.000; a subtotal from ten thousand dollars up to but not including fifty thousand dollars earns 2.0 percent, a rate of 0.020; a subtotal of fifty thousand dollars or more earns 3.5 percent, a rate of 0.035."

        Design: Corner/state_machines/cancelling_a_line_drops_it_out_of_the_planning_rollup
        """
        context = setup_promotion_with_lines(
            api,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 4000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_10,
                },
                {
                    "tactic_type": "TPR",
                    "planned_units": 8000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_17,
                    "window_end": MONDAY_AUG_24,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
        )
        promotion_id = context["promotion"]["id"]
        doomed_id = context["tactics"][0]["id"]
        surviving_id = context["tactics"][1]["id"]

        before = context["promotion"]
        assert_money(before["tactic_subtotal_amount"], 12000.00, "subtotal before")
        assert_ratio(before["allowance_rate"], 0.020, "allowance_rate before")
        assert_money(before["planned_total_spend"], 12240.00, "total before")

        cancelled = validate_success(
            api.cancel_tactic(
                doomed_id,
                key_account_manager,
                cancel_tactic_payload(cancel_reason="Retailer pulled the endcap"),
            )
        )
        assert cancelled["status"] == "CANCELLED"

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "DRAFT"
        assert_money(
            promotion["tactic_subtotal_amount"], 8000.00, "tactic_subtotal_amount"
        )
        assert_ratio(promotion["allowance_rate"], 0.000, "allowance_rate")
        assert_money(
            promotion["off_invoice_allowance_amount"],
            0.00,
            "off_invoice_allowance_amount",
        )
        assert_money(promotion["planned_total_spend"], 8000.00, "planned_total_spend")
        assert promotion["committed_units"] == 8000
        assert read_tactic(api, surviving_id)["status"] == "PLANNED"


class TestApprovalWithEveryGateSatisfied:
    """Approval succeeds when paperwork, dollars and units all clear."""

    def test_promotion_approval_passes_when_every_gate_is_satisfied(
        self, api, key_account_manager, director
    ):
        """
        A covered promotion sitting exactly on its unit ceiling is approved and reserves both quantities.

        PRD: "A successful approval moves `lifecycle_status` `SUBMITTED` → `APPROVED` and records the acting director's identifier in `approved_by_user_id`."
        PRD: "The allocation then reserves both quantities at once: `committed_amount` rises by the promotion's `planned_total_spend`, `committed_units` rises by the promotion's `committed_units`, and `available_amount` and `unreserved_units` are recomputed from those."
        PRD: "The **money and units identity** on a budget allocation: `planned_amount` always equals `committed_amount` plus `available_amount`, and `planned_incremental_units` always equals `committed_units` plus `unreserved_units`."

        Design: Corner/validations/promotion_approval_passes_when_every_gate_is_satisfied
        """
        context = setup_allocation_context(
            api,
            planned_amount=50000.00,
            baseline_units=40000,
            planned_incremental_units=10000,
        )
        assert_money(
            context["allocation"]["available_amount"], 50000.00, "available_amount"
        )
        assert context["allocation"]["unreserved_units"] == 10000

        context = setup_promotion_with_lines(
            api,
            context,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 8000,
                    "rate_per_case": 1.250,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_17,
                },
                {
                    "tactic_type": "DISPLAY",
                    "planned_units": 2000,
                    "fixed_fee": 3000.00,
                    "window_start": MONDAY_AUG_03,
                    "window_end": MONDAY_AUG_17,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
            },
        )
        promotion_id = context["promotion"]["id"]
        setup_verified_commitment_document(
            api,
            promotion_id,
            covers_tactic_type="DISPLAY",
            received_at=instant("2026-08-01", hour=9),
        )

        validate_success(api.submit_promotion(promotion_id, key_account_manager))
        approved = validate_success(api.approve_promotion(promotion_id, director))

        assert approved["lifecycle_status"] == "APPROVED"
        assert approved["commitment_verified"] is True
        assert approved["approved_by_user_id"] == director["X-User-ID"]
        assert_money(
            approved["tactic_subtotal_amount"], 13000.00, "tactic_subtotal_amount"
        )
        assert_ratio(approved["allowance_rate"], 0.020, "allowance_rate")
        assert_money(
            approved["off_invoice_allowance_amount"],
            260.00,
            "off_invoice_allowance_amount",
        )
        assert_money(approved["planned_total_spend"], 13260.00, "planned_total_spend")
        assert approved["committed_units"] == 10000

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["committed_amount"], 13260.00, "committed_amount")
        assert_money(allocation["available_amount"], 36740.00, "available_amount")
        assert allocation["committed_units"] == 10000
        assert allocation["unreserved_units"] == 0


class TestActivationRunIdentifierLists:
    """The checkpoint reports exactly which promotions and lines it moved."""

    def test_activation_run_returns_per_entity_id_lists(
        self, api, key_account_manager, director, finance_analyst
    ):
        """
        Only the promotion and line the clock has reached appear in the run's lists.

        PRD: "The run takes no payload and reports back the `run_at` instant it used together with four lists — `promotions_activated`, `promotions_ended`, `tactics_activated` and `tactics_completed`."
        PRD: "Promotions are processed in `created_at` ascending order, and within a single run **activation is evaluated before ending**: every `APPROVED` promotion whose `window_start` is at or before the clock date moves `APPROVED` → `LIVE`, and then every `LIVE` promotion whose `window_end` is at or before the clock date moves `LIVE` → `ENDED`."

        Design: Corner/endpoints/activation_run_returns_per_entity_id_lists
        """
        context = setup_allocation_context(
            api, planned_amount=90000.00, planned_incremental_units=30000
        )

        context = setup_promotion_with_tpr_line(
            api,
            context,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_10,
            },
            planned_units=2000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_10,
        )
        promotion_one_id = context["promotion"]["id"]
        tactic_one_id = context["tactic"]["id"]
        validate_success(api.submit_promotion(promotion_one_id, key_account_manager))
        validate_success(api.approve_promotion(promotion_one_id, director))

        context = setup_promotion_with_tpr_line(
            api,
            context,
            promotion_overrides={
                "window_start": MONDAY_AUG_10,
                "window_end": MONDAY_AUG_17,
            },
            planned_units=2000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_10,
            window_end=MONDAY_AUG_17,
        )
        promotion_two_id = context["promotion"]["id"]
        tactic_two_id = context["tactic"]["id"]
        validate_success(api.submit_promotion(promotion_two_id, key_account_manager))
        validate_success(api.approve_promotion(promotion_two_id, director))

        set_clock(api, instant(MONDAY_AUG_03))
        run = validate_success(
            api.create_promotion_activation_run(finance_analyst)
        )

        assert same_instant(run["run_at"], instant(MONDAY_AUG_03))
        assert run["promotions_activated"] == [promotion_one_id]
        assert run["tactics_activated"] == [tactic_one_id]
        assert run["promotions_ended"] == []
        assert run["tactics_completed"] == []

        assert read_promotion(api, promotion_one_id)["lifecycle_status"] == "LIVE"
        assert read_tactic(api, tactic_one_id)["status"] == "ACTIVE"
        assert read_promotion(api, promotion_two_id)["lifecycle_status"] == "APPROVED"
        assert read_tactic(api, tactic_two_id)["status"] == "PLANNED"

        rows, meta = validate_paginated(
            api.list_promotions(
                director,
                params={
                    "allocation_id": context["allocation"]["id"],
                    "lifecycle_status": "APPROVED",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == promotion_two_id


class TestPromotionReadSpendMonitor:
    """The promotion read is the live over-spend monitor and never mutates."""

    def test_promotion_read_is_the_live_spend_monitor(
        self, api, key_account_manager, director, finance_analyst,
        deduction_specialist, compliance_auditor
    ):
        """
        Recognised spend takes the greater of the accrual and deduction views, and two reads agree.

        PRD: "`recognized_spend_amount` is the **greater** of two views — the accrual-book view, `gross_accrued_amount` minus `reversed_accrual_amount`, and the deduction-book view, `consumed_deduction_amount` — rounded to 2 decimal places."
        PRD: "Otherwise `spend_ratio` is `recognized_spend_amount` divided by `planned_total_spend`, rounded half up to 4 decimal places, and `spend_status` follows exact boundaries: a ratio strictly greater than 1.0000 is `OVERSPENT`; a ratio at or above 0.9000 but not exceeding 1.0000 is `OVERSPEND_WARNING`; anything below 0.9000 is `WITHIN_BUDGET`."
        PRD: "`accrued_balance` is `gross_accrued_amount` minus `reversed_accrual_amount` minus `consumed_deduction_amount`, rounded to 2 decimal places, and it may legitimately be negative when a retailer has deducted more than was ever accrued."

        Design: Corner/endpoints/promotion_read_is_the_live_spend_monitor
        """
        context = setup_allocation_context(
            api,
            planned_amount=50000.00,
            baseline_units=20000,
            planned_incremental_units=10000,
        )
        context = setup_promotion_with_tpr_line(
            api,
            context,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
                "accrual_method": "CONSUMPTION",
            },
            planned_units=5000,
            rate_per_case=1.000,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_17,
        )
        promotion_id = context["promotion"]["id"]
        customer_id = context["customer"]["id"]
        brand_id = context["brand"]["id"]

        setup_verified_evidence_document(
            api,
            promotion_id,
            covers_tactic_type="TPR",
            received_at=instant("2026-08-04", hour=8),
            units_verified=1500,
        )
        validate_success(api.submit_promotion(promotion_id, key_account_manager))
        validate_success(api.approve_promotion(promotion_id, director))

        set_clock(api, instant(MONDAY_AUG_03))
        validate_success(api.create_promotion_activation_run(finance_analyst))

        validate_success(
            api.create_volume_fact(
                create_volume_fact_payload(
                    customer_id,
                    brand_id,
                    fact_type="CONSUMPTION",
                    period_start=MONDAY_AUG_03,
                    units=1000,
                    source="EDI_852",
                ),
                finance_analyst,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_accrual(
                promotion_id, create_accrual_payload(MONDAY_AUG_03), finance_analyst
            ),
            expected_status=201,
        )

        deduction = validate_success(
            api.create_deduction(
                create_deduction_payload(
                    customer_id,
                    claim_reference="MM-CLAIM-0021",
                    claimed_amount=1500.00,
                    deduction_date=MONDAY_AUG_03,
                ),
                deduction_specialist,
            ),
            expected_status=201,
        )
        validate_success(
            api.match_deduction(
                deduction["id"],
                match_deduction_payload(promotion_id),
                deduction_specialist,
            )
        )
        validated = validate_success(
            api.validate_deduction(
                deduction["id"],
                validate_deduction_payload(
                    current_promotion_version(api, promotion_id)
                ),
                finance_analyst,
            )
        )
        assert validated["status"] == "VALIDATED"
        assert_money(validated["validated_amount"], 1500.00, "validated_amount")

        first = validate_success(api.get_promotion(promotion_id, compliance_auditor))
        second = validate_success(api.get_promotion(promotion_id, compliance_auditor))

        assert_money(first["gross_accrued_amount"], 1000.00, "gross_accrued_amount")
        assert_money(
            first["consumed_deduction_amount"], 1500.00, "consumed_deduction_amount"
        )
        assert_money(first["accrued_balance"], -500.00, "accrued_balance")
        assert_money(
            first["recognized_spend_amount"], 1500.00, "recognized_spend_amount"
        )
        assert_ratio(first["spend_ratio"], 0.3000, "spend_ratio")
        assert first["spend_status"] == "WITHIN_BUDGET"
        assert first["version"] == second["version"]


class TestSubmitRequiresAPlannedLine:
    """A promotion with nothing planned cannot enter director review."""

    def test_submit_requires_at_least_one_planned_line(
        self, api, key_account_manager, director
    ):
        """
        Submitting a promotion that carries no tactic line at all is refused.

        PRD: "Two further conditions apply: the funding allocation must still be `APPROVED`, or the request is refused with `ERR_ALLOCATION_NOT_APPROVED`; and the promotion must carry at least one tactic line whose `status` is `PLANNED`, or the request is refused with `ERR_PROMOTION_HAS_NO_TACTICS` (HTTP 422)."
        PRD: "**Rung 84** — a promotion has at least one planned tactic line, on promotion submit: `ERR_PROMOTION_HAS_NO_TACTICS`."

        Design: Corner/errors/submit_requires_at_least_one_planned_line
        """
        context = setup_draft_promotion(
            api, window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17
        )
        promotion_id = context["promotion"]["id"]
        assert_money(
            context["promotion"]["tactic_subtotal_amount"],
            0.00,
            "tactic_subtotal_amount",
        )

        validate_error(
            api.submit_promotion(promotion_id, key_account_manager),
            ApiErrorId.PROMOTION_HAS_NO_TACTICS.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_tactics(promotion_id, director)
        )
        assert rows == []
        assert meta["total_count"] == 0

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "DRAFT"
        assert_money(promotion["planned_total_spend"], 0.00, "planned_total_spend")
        assert promotion["committed_units"] == 0


class TestCancelledLineMaintenance:
    """A cancelled line is refused with the tactic-state code, not the promotion's."""

    def test_cancelled_line_can_no_longer_be_maintained(
        self, api, key_account_manager
    ):
        """
        Patching a `CANCELLED` line under a `DRAFT` promotion reports the tactic state.

        PRD: "Cancellation is also what makes it possible for a non-`PLANNED` line to sit under a `DRAFT` promotion — the situation in which a second cancel or a patch of that same line is refused with `ERR_TACTIC_STATE_INVALID` (HTTP 409) rather than with the promotion-state code."
        PRD: "**Rung 44** — the tactic line's own `status` is `PLANNED`, on tactic patch and tactic cancel: `ERR_TACTIC_STATE_INVALID`."

        Design: Corner/errors/cancelled_line_can_no_longer_be_maintained
        """
        context = setup_promotion_with_lines(
            api,
            lines=[
                {
                    "tactic_type": "TPR",
                    "planned_units": 2000,
                    "rate_per_case": 1.000,
                    "window_start": MONDAY_AUG_10,
                    "window_end": MONDAY_AUG_17,
                },
                {
                    "tactic_type": "DISPLAY",
                    "planned_units": 500,
                    "fixed_fee": 1400.00,
                    "window_start": MONDAY_AUG_10,
                    "window_end": MONDAY_AUG_17,
                },
            ],
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
            },
        )
        promotion_id = context["promotion"]["id"]
        dead_id = context["tactics"][1]["id"]

        cancelled = validate_success(
            api.cancel_tactic(
                dead_id,
                key_account_manager,
                cancel_tactic_payload(cancel_reason="Placement never ran"),
            )
        )
        assert cancelled["status"] == "CANCELLED"

        validate_error(
            api.patch_tactic(
                dead_id,
                patch_tactic_payload(
                    current_promotion_version(api, promotion_id), fixed_fee=900.00
                ),
                key_account_manager,
            ),
            ApiErrorId.TACTIC_STATE_INVALID.value,
        )

        dead_line = read_tactic(api, dead_id)
        assert dead_line["status"] == "CANCELLED"
        assert_money(dead_line["fixed_fee"], 1400.00, "fixed_fee")

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "DRAFT"
        assert_money(
            promotion["tactic_subtotal_amount"], 2000.00, "tactic_subtotal_amount"
        )
        assert promotion["committed_units"] == 2000
