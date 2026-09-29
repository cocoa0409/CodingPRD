"""The two posture gates use different posture sets, the logical clock bounds are
inclusive in the permitting direction, and three singleton rules per partner."""
from test_helpers import (
    CO,
    IA,
    PO,
    RC,
    ApiErrorId,
    account_census_payload,
    api_client,
    approve_wind_down_plan,
    clear_variance,
    create_agreement_payload,
    create_alert_payload,
    create_batch,
    create_complaint_payload,
    create_diligence_review_payload,
    create_marketing_review_payload,
    create_partner,
    create_wind_down_plan_payload,
    dispose_complaint,
    draft_wind_down_plan,
    file_complaint,
    fund_batch,
    get_success_data,
    open_cycle,
    post_ledger_entry,
    raise_sanctions_alert,
    read_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    set_clock,
    setup_ballast_partner,
    setup_live_partner,
    terminate_agreement,
    validate_error,
    validate_success,
)


class TestPostureGatesUseDifferentPostureSets:
    def test_restricted_stops_marketing_only_and_the_frozen_custody_gate_preempts_the_inflow_gate(self):
        """`RESTRICTED` and `FROZEN` both block marketing filings, resubmissions and approvals,
        refused with `ERR_POSTURE_BLOCKS_MARKETING` (HTTP 403). `FROZEN` additionally blocks every
        end-user credit into custody, refused with `ERR_POSTURE_BLOCKS_INFLOW` (HTTP 403), and
        freezes both of the partner's custody accounts. Any entry, of any type, requires the
        custody account it moves to be `ACTIVE`; a `FROZEN` or `CLOSED` account yields
        `ERR_CUSTODY_ACCOUNT_NOT_ACTIVE`.

        Design: Corner/validations/the_restricted_posture_blocks_marketing_but_not_inflow_and_the_frozen_custody_gate_preempts_the_inflow_gate
        """
        ctx = setup_live_partner(
            partner_overrides={"legal_name": "Restricted Posture Wallet Inc"},
            agreement_overrides={"reserve_requirement_bps": 500},
            fbo_balance_cents=0,
            reserve_balance_cents=312_500,
        )
        partner_id = ctx["partner"]["id"]
        setup_ballast_partner(
            60_000_000, cycle_open=False, legal_name="Restricted Ballast Partner Inc"
        )
        get_success_data(
            api_client.report_account_census(
                partner_id, account_census_payload(end_user_account_count=100), PO
            )
        )

        for narrative in (
            "monthly maintenance fee charged twice in the same statement cycle",
            "card declined at the point of sale with funds available",
            "transfer held for six business days without notice",
        ):
            file_complaint(partner_id, narrative=narrative)

        restricted = read_partner(partner_id)
        assert restricted["complaint_rate_bps"] == 300, (
            f"three complaints over 100 accounts is 300 basis points, got "
            f"{restricted['complaint_rate_bps']}"
        )
        assert restricted["open_sanctions_alert_count"] == 0
        assert restricted["oversight_posture"] == "RESTRICTED", (
            "300 basis points has reached the 250 rung but nothing has reached the freeze rung"
        )

        blocked_filing = api_client.create_marketing_review(
            create_marketing_review_payload(partner_id, ctx["agreement"]["id"]), PO
        )
        validate_error(blocked_filing, ApiErrorId.ERR_POSTURE_BLOCKS_MARKETING, 403)

        permitted_inflow = validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "END_USER_CREDIT", 1_000_000),
            expected_status=201,
        )
        assert permitted_inflow["amount_cents"] == 1_000_000, (
            "the inflow gate names FROZEN only, so a RESTRICTED partner still takes money in"
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 1_000_000

        raise_sanctions_alert(partner_id, triggered_at="2026-07-31T10:00:00Z")
        frozen = read_partner(partner_id)
        assert frozen["oversight_posture"] == "FROZEN"
        assert frozen["open_sanctions_alert_count"] == 1
        assert read_custody_account(ctx["fbo"]["id"])["status"] == "FROZEN"

        refused_inflow = post_ledger_entry(
            partner_id, ctx["fbo"], "END_USER_CREDIT", 1_000_000
        )
        validate_error(refused_inflow, ApiErrorId.ERR_CUSTODY_ACCOUNT_NOT_ACTIVE, 409)
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 1_000_000


class TestLogicalClockBoundaries:
    def test_stamps_effective_dates_and_cycle_elapse_are_all_inclusive_at_the_clock(self):
        """A `received_at` after the logical clock is refused with `ERR_TIMESTAMP_IN_FUTURE`. The
        cycle's `period_end` must also be at or before the logical clock; a period that has not
        yet elapsed cannot be closed and the attempt is refused with
        `ERR_CYCLE_PERIOD_NOT_ELAPSED`. Finally, `effective_date` is the instant from which the
        agreement governs, and it must not precede the logical clock at the moment of drafting — a
        backdated agreement is refused with `ERR_EFFECTIVE_DATE_IN_PAST`.

        Design: Corner/validations/the_logical_clock_boundaries_are_inclusive_for_stamps_and_effective_dates_and_for_cycle_elapse
        """
        cycle = open_cycle()
        partner = create_partner(legal_name="Clockwise Payments Inc")
        partner_id = partner["id"]

        one_second_ahead = api_client.create_complaint(
            create_complaint_payload(partner_id, received_at="2026-08-01T00:00:01Z"), CO
        )
        validate_error(one_second_ahead, ApiErrorId.ERR_TIMESTAMP_IN_FUTURE, 422)

        exactly_now = validate_success(
            api_client.create_complaint(
                create_complaint_payload(partner_id, received_at="2026-08-01T00:00:00Z"), CO
            ),
            expected_status=201,
        )
        assert exactly_now["status"] == "RECEIVED", (
            "a stamp exactly equal to the clock is not in the future"
        )

        alert_ahead = api_client.create_alert(
            create_alert_payload(partner_id, triggered_at="2026-08-01T00:00:01Z"), CO
        )
        validate_error(alert_ahead, ApiErrorId.ERR_TIMESTAMP_IN_FUTURE, 422)

        premature = api_client.close_cycle(cycle["id"], {}, PO)
        validate_error(premature, ApiErrorId.ERR_CYCLE_PERIOD_NOT_ELAPSED, 409)

        set_clock("2026-08-31T23:59:59Z")
        one_second_short = api_client.close_cycle(cycle["id"], {}, PO)
        validate_error(one_second_short, ApiErrorId.ERR_CYCLE_PERIOD_NOT_ELAPSED, 409)

        set_clock("2026-09-01T00:00:00Z")
        closed = get_success_data(api_client.close_cycle(cycle["id"], {}, PO))
        assert closed["status"] == "CLOSED", (
            "a period_end exactly equal to the clock has elapsed"
        )

        backdated = api_client.create_agreement(
            create_agreement_payload(
                partner_id,
                read_partner(partner_id)["version"],
                effective_date="2026-08-31T23:59:59Z",
            ),
            PO,
        )
        validate_error(backdated, ApiErrorId.ERR_EFFECTIVE_DATE_IN_PAST, 422)
        assert (
            get_success_data(api_client.list_agreements(PO, {"partner_id": partner_id})) == []
        ), "the refusal wrote no draft"


class TestWindDownGateLadder:
    def test_stage_gate_then_notice_halves_then_the_settlement_drain_gate(self):
        """A wind-down plan may only be created, submitted, decided or executed while the partner's
        `status` is `WIND_DOWN`, else `ERR_PARTNER_NOT_IN_WIND_DOWN` (409). And the notice period
        must be real: `notice_days` must be at least 30, and `target_completion_date` must fall at
        or after the plan's `created_at` advanced by `notice_days` days; a violation of either is
        refused with `ERR_WIND_DOWN_NOTICE_NOT_ELAPSED`. A single outstanding batch on either
        dimension refuses the request with `ERR_UNSETTLED_BATCHES_OUTSTANDING` — the bank does not
        begin returning end-user funds while an unreconciled or unfunded settlement could still
        move the balances. Every check in the system sits at a fixed rank; checks are evaluated in
        ascending rank order, **the first failure wins, and every later check is skipped**.

        Design: Corner/validations/the_wind_down_gates_check_partner_status_then_notice_elapse_then_outstanding_batches
        """
        ctx = setup_live_partner(
            partner_overrides={"legal_name": "Windrose Exit Payments Inc"},
            agreement_overrides={
                "reserve_requirement_bps": 500,
                "termination_triggers": ["VOLUNTARY"],
            },
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]

        while_live = api_client.create_wind_down_plan(
            create_wind_down_plan_payload(partner_id), PO
        )
        validate_error(while_live, ApiErrorId.ERR_PARTNER_NOT_IN_WIND_DOWN, 409)

        settled = create_batch(
            partner_id,
            gross_settlement_cents=8_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=8_000_000,
        )
        reconcile_batch(settled["id"], 8_000_000)
        assert fund_batch(settled["id"], funding_reference="WIRE-WINDROSE-1")[
            "funding_status"
        ] == "FUNDED"

        terminated = terminate_agreement(ctx["agreement"]["id"], "VOLUNTARY", 30)
        assert terminated["status"] == "TERMINATED"
        assert read_partner(partner_id)["status"] == "WIND_DOWN"

        uncontracted_trigger = api_client.create_wind_down_plan(
            create_wind_down_plan_payload(partner_id, trigger_reason="SANCTIONS_EVENT"), PO
        )
        validate_error(
            uncontracted_trigger, ApiErrorId.ERR_TERMINATION_TRIGGER_NOT_CONTRACTED, 422
        )

        below_minimum = api_client.create_wind_down_plan(
            create_wind_down_plan_payload(partner_id, notice_days=29), PO
        )
        validate_error(below_minimum, ApiErrorId.ERR_WIND_DOWN_NOTICE_NOT_ELAPSED, 409)

        target_too_early = api_client.create_wind_down_plan(
            create_wind_down_plan_payload(
                partner_id,
                notice_days=45,
                target_completion_date="2026-09-14T00:00:00Z",
            ),
            PO,
        )
        validate_error(target_too_early, ApiErrorId.ERR_WIND_DOWN_NOTICE_NOT_ELAPSED, 409)

        plan = draft_wind_down_plan(partner_id)
        assert plan["notice_days"] == 30
        approved = approve_wind_down_plan(plan["id"])
        assert approved["status"] == "APPROVED", (
            "notice_days 30 against a 2026-10-15 target clears the static half of the rule"
        )

        premature = api_client.execute_wind_down_plan(plan["id"], {}, PO)
        validate_error(premature, ApiErrorId.ERR_WIND_DOWN_NOTICE_NOT_ELAPSED, 409)

        # An outstanding batch now violates the drain gate as well as the notice guard, and the
        # drain gate is the lower rank of the two.
        outstanding = create_batch(
            partner_id,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-15T00:00:00Z",
            gross_settlement_cents=4_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=4_000_000,
        )
        assert read_batch(outstanding["id"])["funding_status"] == "UNFUNDED"
        both_violated = api_client.execute_wind_down_plan(plan["id"], {}, PO)
        validate_error(both_violated, ApiErrorId.ERR_UNSETTLED_BATCHES_OUTSTANDING, 409)

        set_clock("2026-09-16T00:00:00Z")
        after_notice = api_client.execute_wind_down_plan(plan["id"], {}, PO)
        validate_error(after_notice, ApiErrorId.ERR_UNSETTLED_BATCHES_OUTSTANDING, 409)

        assert get_success_data(api_client.get_wind_down_plan(plan["id"], PO))["status"] == (
            "APPROVED"
        )
        assert read_partner(partner_id)["status"] == "WIND_DOWN"


class TestOneOpenArtefactPerPartner:
    def test_three_singleton_rules_with_three_different_open_sets(self):
        """At most one diligence file per partner may sit in `DRAFT`, `SUBMITTED` or
        `INFO_REQUESTED` at any moment; a second attempt is refused with
        `ERR_DILIGENCE_ALREADY_OPEN`. At most one agreement per partner may sit in `DRAFT` or
        `PENDING_RISK_APPROVAL`, and none may be drafted at all once an agreement has reached
        `EXECUTED` and has not since been terminated; either situation is refused with
        `ERR_AGREEMENT_ALREADY_OPEN`. At most one plan per partner may be live at a time, where
        live means a `status` of `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or `IN_EXECUTION`; a
        second is refused with `ERR_PLAN_ALREADY_OPEN`.

        Design: Corner/validations/at_most_one_open_artefact_per_partner_is_enforced_for_reviews_agreements_and_plans
        """
        partner = create_partner(legal_name="Singleton Artefact Payments Inc")
        partner_id = partner["id"]
        first_version = partner["version"]

        review = validate_success(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner_id, first_version), PO
            ),
            expected_status=201,
        )
        get_success_data(api_client.submit_diligence_review(review["id"], {}, PO))
        in_diligence = read_partner(partner_id)
        assert in_diligence["status"] == "IN_DILIGENCE"
        assert in_diligence["version"] > first_version, "each create cascaded a partner write"

        second_file = api_client.create_diligence_review(
            create_diligence_review_payload(partner_id, in_diligence["version"]), PO
        )
        validate_error(second_file, ApiErrorId.ERR_DILIGENCE_ALREADY_OPEN, 409)

        get_success_data(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO)
        )
        passed = read_partner(partner_id)
        assert passed["status"] == "DILIGENCE_PASSED"

        renewal = validate_success(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    partner_id, passed["version"], review_type="RENEWAL"
                ),
                PO,
            ),
            expected_status=201,
        )
        assert renewal["status"] == "DRAFT", (
            "the decided file left the open set, so a renewal file may be opened"
        )

        agreement = validate_success(
            api_client.create_agreement(
                create_agreement_payload(partner_id, read_partner(partner_id)["version"]), PO
            ),
            expected_status=201,
        )
        assert agreement["status"] == "DRAFT"

        while_drafted = api_client.create_agreement(
            create_agreement_payload(partner_id, read_partner(partner_id)["version"]), PO
        )
        validate_error(while_drafted, ApiErrorId.ERR_AGREEMENT_ALREADY_OPEN, 409)

        get_success_data(api_client.submit_agreement_for_approval(agreement["id"], {}, PO))
        executed = get_success_data(
            api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, RC)
        )
        assert executed["status"] == "EXECUTED"

        while_executed = api_client.create_agreement(
            create_agreement_payload(partner_id, read_partner(partner_id)["version"]), PO
        )
        # The singleton keeps firing after execution, so the open set is not merely the two
        # pre-execution states.
        validate_error(while_executed, ApiErrorId.ERR_AGREEMENT_ALREADY_OPEN, 409)

        terminated = terminate_agreement(agreement["id"], "VOLUNTARY", 30)
        assert terminated["status"] == "TERMINATED"
        assert read_partner(partner_id)["status"] == "WIND_DOWN"

        plan = draft_wind_down_plan(partner_id)
        assert plan["status"] == "DRAFT"
        second_plan = api_client.create_wind_down_plan(
            create_wind_down_plan_payload(partner_id), PO
        )
        validate_error(second_plan, ApiErrorId.ERR_PLAN_ALREADY_OPEN, 409)


class TestRequestFieldConditionalRefusals:
    def test_a_resolution_needs_a_diagnosis_and_a_clearing_must_close_the_gap_exactly(self):
        """A `RESOLVED` outcome is legal from `ROOT_CAUSE_ASSIGNED` and from `ESCALATED`, and in
        both cases requires `root_cause_code` to be non-null — a complaint cannot be closed without
        a diagnosis, and an attempt to do so is refused with `ERR_ROOT_CAUSE_REQUIRED`. A
        `WITHDRAWN` outcome is legal only from `RECEIVED`. The correction must close the gap
        exactly: `variance_adjustment_cents` added to `partner_reported_net_cents` must equal
        `bank_reported_net_cents`, else `ERR_VARIANCE_NOT_EXPLAINED`. On success the correction is
        stored, `settlement_base_cents` is recomputed as `gross_settlement_cents` plus
        `interchange_cents`, less `returns_cents`, plus `variance_adjustment_cents`, and the batch
        advances `VARIANCE_OPEN → VARIANCE_CLEARED`.

        Design: Corner/validations/root_cause_discipline_and_variance_explanation_are_refusals_that_leave_the_row_untouched
        """
        ctx = setup_live_partner(
            partner_overrides={"legal_name": "Rootcause Settlements Inc"},
            agreement_overrides={"reserve_requirement_bps": 500},
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]

        undiagnosed = file_complaint(
            partner_id,
            channel="SOCIAL",
            received_at="2026-07-31T12:00:00Z",
            narrative="public post about a hold placed on a payroll deposit",
        )
        assert undiagnosed["root_cause_code"] is None, "intake records no diagnosis"

        set_clock("2026-09-01T00:00:00Z")
        closed = get_success_data(api_client.close_cycle(ctx["cycle"]["id"], {}, PO))
        assert closed["complaints_escalated_count"] == 1
        escalated = get_success_data(api_client.get_complaint(undiagnosed["id"], PO))
        assert escalated["status"] == "ESCALATED"
        assert escalated["root_cause_code"] is None

        no_diagnosis = api_client.dispose_complaint(
            undiagnosed["id"],
            {"outcome": "RESOLVED", "resolution_note": "goodwill credit applied to the account"},
            CO,
        )
        validate_error(no_diagnosis, ApiErrorId.ERR_ROOT_CAUSE_REQUIRED, 409)
        assert get_success_data(api_client.get_complaint(undiagnosed["id"], PO))["status"] == (
            "ESCALATED"
        ), "the refusal left the row untouched"

        # The same missing diagnosis is no obstacle to the other outcome, so the rule is
        # conditional on the requested outcome rather than on the row.
        withdrawable = file_complaint(
            partner_id,
            received_at="2026-09-01T00:00:00Z",
            narrative="caller withdrew the fee dispute after reviewing the statement",
        )
        assert withdrawable["root_cause_code"] is None
        assert dispose_complaint(withdrawable["id"], "WITHDRAWN")["status"] == "WITHDRAWN"

        batch = create_batch(
            partner_id,
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        opened = reconcile_batch(batch["id"], 8_200_000)
        assert opened["reconciliation_status"] == "VARIANCE_OPEN"
        assert opened["variance_cents"] == 100_000
        assert read_partner(partner_id)["unreconciled_variance_cents"] == 100_000

        half_closed = api_client.clear_settlement_variance(
            batch["id"],
            {
                "variance_adjustment_cents": 50_000,
                "root_cause_note": "half of the gap traced to a late interchange file",
            },
            IA,
        )
        validate_error(half_closed, ApiErrorId.ERR_VARIANCE_NOT_EXPLAINED, 422)

        wrong_sign = api_client.clear_settlement_variance(
            batch["id"],
            {
                "variance_adjustment_cents": -100_000,
                "root_cause_note": "the correction was entered against the wrong direction",
            },
            IA,
        )
        validate_error(wrong_sign, ApiErrorId.ERR_VARIANCE_NOT_EXPLAINED, 422)

        untouched = read_batch(batch["id"])
        assert untouched["reconciliation_status"] == "VARIANCE_OPEN"
        assert untouched["variance_adjustment_cents"] == 0
        assert read_partner(partner_id)["unreconciled_variance_cents"] == 100_000

        cleared = clear_variance(
            batch["id"], 100_000, root_cause_note="the whole gap was a late interchange file"
        )
        assert cleared["reconciliation_status"] == "VARIANCE_CLEARED"
        assert cleared["variance_adjustment_cents"] == 100_000
        assert cleared["settlement_base_cents"] == 8_200_000, (
            f"8000000 + 200000 - 100000 + 100000 is 8200000, got "
            f"{cleared['settlement_base_cents']}"
        )
        assert read_partner(partner_id)["unreconciled_variance_cents"] == 0
