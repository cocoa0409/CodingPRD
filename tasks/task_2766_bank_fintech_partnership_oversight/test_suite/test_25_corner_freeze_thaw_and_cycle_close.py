"""Corner cases of the freeze/thaw asymmetry and of the six-step cycle close."""
from test_helpers import (
    PO,
    ApiErrorId,
    api_client,
    assert_complaint_bucket_partition,
    assert_same_instant,
    assign_root_cause,
    approve_wind_down_plan,
    close_cycle,
    create_batch,
    create_ledger_entry_payload,
    dispose_alert,
    dispose_complaint,
    draft_wind_down_plan,
    file_complaint,
    get_success_data,
    raise_alert,
    raise_sanctions_alert,
    read_custody_account,
    read_partner,
    reconcile_batch,
    seed_reserve_balance,
    set_clock,
    setup_contracted_partner,
    setup_live_partner,
    terminate_agreement,
    validate_error,
)

SANCTIONS_NOTE = "OFAC list match on an inbound originator name for this program"
CLEAR_NOTE = "secondary review confirmed a false positive on the originator name"


def _live_partner():
    """FBO 8,100,000 at 500 bps gives a 405,000 base; the reserve is seeded at
    the HEIGHTENED-multiplier figure so the launch gate sees a zero shortfall."""
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Sablefin Deposits Inc",
            "business_model": "DEPOSIT_WALLET",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 3.00,
            "end_user_account_count": 6000,
        },
        agreement_overrides={"reserve_requirement_bps": 500},
        fbo_balance_cents=8_100_000,
        reserve_balance_cents=506_250,
    )


class TestFreezeOutlivesItsCause:
    def test_a_sanctions_hit_freezes_both_accounts_and_clearing_it_leaves_them_frozen(self):
        """A single open sanctions alert satisfies the most severe rung of the posture ladder,
        so the re-derived `oversight_posture` becomes `FROZEN`, which in turn freezes both of that
        partner's custody accounts inside the same request. Note carefully that the posture may
        drop off `FROZEN` at that moment but the custody accounts do **not** thaw inside this
        request: unfreezing is deferred to the next oversight cycle close.

        Design: Corner/state_machines/a_sanctions_hit_alert_freezes_both_custody_accounts_and_clearing_it_does_not_unfreeze_them
        """
        ctx = _live_partner()
        partner_id = ctx["partner"]["id"]
        assert read_partner(partner_id)["oversight_posture"] == "OPEN"

        alert = raise_sanctions_alert(
            partner_id,
            triggered_at="2026-08-01T00:00:00Z",
            transaction_volume_cents=250_000,
            detection_note=SANCTIONS_NOTE,
        )
        assert alert["disposition"] == "OPEN"
        assert alert["sla_breach_count"] == 0
        assert alert["disposed_by_user_id"] is None
        assert_same_instant(alert["sla_due_at"], "2026-08-02T00:00:00Z", "sla_due_at")

        frozen = read_partner(partner_id)
        assert frozen["open_sanctions_alert_count"] == 1
        assert frozen["oversight_posture"] == "FROZEN"
        for account_id in (ctx["fbo"]["id"], ctx["reserve"]["id"]):
            account = read_custody_account(account_id)
            assert account["status"] == "FROZEN", account
            assert_same_instant(account["frozen_at"], "2026-08-01T00:00:00Z", "frozen_at")

        disposed = dispose_alert(alert["id"], "CLEARED", disposition_note=CLEAR_NOTE)
        assert disposed["disposition"] == "CLEARED"
        assert disposed["disposed_by_user_id"] == "co_1"

        recovered = read_partner(partner_id)
        assert recovered["open_sanctions_alert_count"] == 0
        assert recovered["oversight_posture"] == "OPEN"
        for account_id in (ctx["fbo"]["id"], ctx["reserve"]["id"]):
            still = read_custody_account(account_id)
            assert still["status"] == "FROZEN", (
                "clearing the cause does not thaw the account inside the same request"
            )
            assert still["frozen_at"] is not None

        blocked = api_client.create_ledger_entry(
            create_ledger_entry_payload(
                partner_id,
                ctx["reserve"]["id"],
                read_custody_account(ctx["reserve"]["id"])["version"],
                entry_type="RESERVE_FUND",
                amount_cents=10_000,
                effective_at="2026-08-05T00:00:00Z",
                memo="topping the reserve while the account is still frozen",
            ),
            PO,
        )
        validate_error(blocked, ApiErrorId.ERR_CUSTODY_ACCOUNT_NOT_ACTIVE, 409)

    def test_the_close_thaws_custody_and_writes_all_six_counters_in_one_request(self):
        """Symmetrically, a partner whose recomputed posture is no longer `FROZEN` has each of its
        `FROZEN` custody accounts returned to `ACTIVE`, setting `frozen_at` back to null and
        incrementing that account's `version` by 1 — this is the deferred thaw promised in §3.8,
        and it is the only place a frozen account ever reopens. Finally the six counters are
        persisted onto the cycle along with `closed_at` set to the logical clock.

        Design: Corner/state_machines/cycle_close_unfreezes_custody_and_writes_every_counter_in_one_request
        """
        ctx = _live_partner()
        partner_id = ctx["partner"]["id"]
        alert = raise_sanctions_alert(
            partner_id,
            triggered_at="2026-08-01T00:00:00Z",
            transaction_volume_cents=250_000,
            detection_note=SANCTIONS_NOTE,
        )
        dispose_alert(alert["id"], "CLEARED", disposition_note=CLEAR_NOTE)
        assert read_custody_account(ctx["fbo"]["id"])["status"] == "FROZEN"
        frozen_version = read_custody_account(ctx["reserve"]["id"])["version"]

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"], closing_note="August checkpoint")

        assert closed["status"] == "CLOSED", "the close never parks the cycle in CLOSING"
        assert_same_instant(closed["closed_at"], "2026-09-01T00:00:00Z", "closed_at")
        assert closed["partners_frozen_count"] == 0
        assert closed["marketing_approvals_expired_count"] == 0
        assert closed["complaints_escalated_count"] == 0
        assert closed["alerts_reopened_count"] == 0, "a CLEARED alert is not reopened"
        assert closed["growth_breach_partner_count"] == 0
        assert closed["plans_completed_count"] == 0

        for account_id in (ctx["fbo"]["id"], ctx["reserve"]["id"]):
            thawed = read_custody_account(account_id)
            assert thawed["status"] == "ACTIVE", thawed
            assert thawed["frozen_at"] is None
        assert read_custody_account(ctx["reserve"]["id"])["version"] == frozen_version + 1

        partner = read_partner(partner_id)
        assert partner["required_reserve_cents"] == 405_000, (
            "the recomputation reads the persisted OPEN multiplier of 1.00 over the "
            f"405000 base, got {partner['required_reserve_cents']}"
        )
        assert partner["reserve_shortfall_cents"] == 0
        assert partner["consecutive_shortfall_cycles"] == 0
        assert partner["concentration_ratio_pct"] == 100.00
        assert partner["growth_breach_count"] == 0
        assert partner["oversight_posture"] == "OPEN"


def _contracted_partner(**partner_overrides):
    """A contracted partner whose reserve is seeded to the 250,000-floor requirement
    scaled by the HEIGHTENED multiplier, so the shortfall rung is off the ladder."""
    defaults = {
        "legal_name": "Tidewater Wallet Inc",
        "business_model": "DEPOSIT_WALLET",
        "funding_stage": "SERIES_A",
        "months_runway": 24,
        "disclosed_complaints_per_10k": 4.00,
        "end_user_account_count": 100_000,
    }
    defaults.update(partner_overrides)
    ctx = setup_contracted_partner(
        partner_overrides=defaults,
        agreement_overrides={"dispute_owner": "PARTNER"},
    )
    seed_reserve_balance(ctx["partner"]["id"], ctx["reserve"], 312_500)
    return ctx


class TestCloseStepOrdering:
    def test_the_close_escalates_the_overdue_complaint_before_recomputing_the_rate(self):
        """The step order is normative and must be followed exactly, because each step reads state
        that an earlier step wrote: step 1 changes the complaint counts that step 3 reads, and the
        posture step 3 derives is the posture step 4 acts on.

        Design: Corner/state_machines/cycle_close_escalates_an_overdue_complaint_before_recomputing_the_rate_that_reads_it
        """
        ctx = _contracted_partner()
        partner_id = ctx["partner"]["id"]
        set_clock("2026-08-01T10:00:00Z")
        complaint = file_complaint(
            partner_id,
            channel="SOCIAL",
            category="DISCLOSURE",
            severity="HIGH",
            received_at="2026-08-01T09:30:00Z",
            narrative="a public post about an undisclosed monthly maintenance fee",
        )
        assert complaint["status"] == "RECEIVED"
        assert complaint["escalation_count"] == 0
        assert complaint["handling_owner"] == "PARTNER", "copied from the agreement dispute_owner"
        assert_same_instant(
            complaint["response_due_at"], "2026-08-10T23:59:59.999Z", "response_due_at"
        )

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"])
        assert closed["complaints_escalated_count"] == 1
        assert closed["alerts_reopened_count"] == 0

        escalated = get_success_data(api_client.get_complaint(complaint["id"], PO))
        assert escalated["status"] == "ESCALATED", escalated["status"]
        assert escalated["escalation_count"] == 1

        partner = read_partner(partner_id)
        assert partner["open_complaint_count"] == 0
        assert partner["escalated_complaint_count"] == 1
        assert_complaint_bucket_partition(partner, expected_total=1)
        assert partner["complaint_rate_bps"] == 0, (
            "one escalated complaint against 100000 accounts rounds to 0 bps, and the "
            f"escalation done by step 1 is what step 3 counts, got {partner['complaint_rate_bps']}"
        )
        assert partner["oversight_posture"] == "OPEN"

    def test_a_pending_alert_returns_to_open_at_the_close_that_finds_its_sla_breached(self):
        """Every monitoring alert whose `disposition` is `PARTNER_RESPONSE_PENDING` and whose
        `sla_due_at` falls strictly before the logical clock is returned to `OPEN`, processed in
        ascending `triggered_at` order with ties broken by ascending `created_at`. Each reopen
        increments that alert's `sla_breach_count` by 1 and the cycle's `alerts_reopened_count` by 1.

        Design: Corner/state_machines/a_partner_response_pending_alert_returns_to_open_at_the_close_that_finds_its_sla_breached
        """
        ctx = _contracted_partner(legal_name="Ravenhill Wallet Inc")
        partner_id = ctx["partner"]["id"]
        alert = raise_alert(
            partner_id,
            alert_type="STRUCTURING",
            triggered_at="2026-08-01T00:00:00Z",
            transaction_volume_cents=900_000,
            detection_note="six deposits of 9,800 dollars inside a single business day",
        )
        assert alert["disposition"] == "OPEN"
        assert alert["sla_breach_count"] == 0
        assert_same_instant(alert["sla_due_at"], "2026-08-04T00:00:00Z", "sla_due_at")
        assert read_partner(partner_id)["open_sanctions_alert_count"] == 0

        pending = dispose_alert(
            alert["id"],
            "PARTNER_RESPONSE_PENDING",
            disposition_note="awaiting the partner's transaction narrative",
        )
        assert pending["disposition"] == "PARTNER_RESPONSE_PENDING"
        assert pending["sla_breach_count"] == 0

        set_clock("2026-09-01T00:00:00Z")
        closed = close_cycle(ctx["cycle"]["id"])
        assert closed["alerts_reopened_count"] == 1
        assert closed["complaints_escalated_count"] == 0
        assert closed["partners_frozen_count"] == 0

        reopened = get_success_data(api_client.get_alert(alert["id"], PO))
        assert reopened["disposition"] == "OPEN", "the pending state is forfeited"
        assert reopened["sla_breach_count"] == 1
        assert read_partner(partner_id)["open_sanctions_alert_count"] == 0, (
            "a STRUCTURING alert never enters the sanctions count"
        )


class TestEscalationLoopConservesBuckets:
    def test_the_escalation_round_trip_conserves_the_four_bucket_counts(self):
        """It is legal from two source states and is the compensating action that brings an
        escalated complaint back into the open bucket. From `ESCALATED` it advances
        `ESCALATED → ROOT_CAUSE_ASSIGNED`, overwrites the code, decrements the partner's
        `escalated_complaint_count` by 1 and increments `open_complaint_count` by 1.

        Design: Corner/state_machines/the_escalation_loop_conserves_the_partners_four_complaint_bucket_counts
        """
        ctx = _contracted_partner(legal_name="Foxglove Wallet Inc")
        partner_id = ctx["partner"]["id"]
        complaint = file_complaint(
            partner_id,
            channel="EMAIL",
            category="SERVICING",
            severity="MEDIUM",
            received_at="2026-07-25T08:00:00Z",
            narrative="the servicing team never answered the second message",
        )
        after_intake = read_partner(partner_id)
        assert after_intake["open_complaint_count"] == 1
        assert after_intake["escalated_complaint_count"] == 0
        assert_complaint_bucket_partition(after_intake, expected_total=1)

        assigned = assign_root_cause(
            complaint["id"],
            root_cause_code="PARTNER_TRAINING_GAP",
            investigation_note="the partner's support staff were never trained on the escalation path",
        )
        assert assigned["status"] == "ROOT_CAUSE_ASSIGNED"
        assert assigned["root_cause_code"] == "PARTNER_TRAINING_GAP"
        after_assign = read_partner(partner_id)
        assert after_assign["open_complaint_count"] == 1, (
            "RECEIVED and ROOT_CAUSE_ASSIGNED are both open buckets"
        )
        assert after_assign["escalated_complaint_count"] == 0
        assert_complaint_bucket_partition(after_assign, expected_total=1)

        escalated = dispose_complaint(
            complaint["id"],
            "ESCALATED",
            resolution_note="referred to the joint oversight committee",
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_count"] == 1
        after_escalate = read_partner(partner_id)
        assert after_escalate["open_complaint_count"] == 0
        assert after_escalate["escalated_complaint_count"] == 1
        assert_complaint_bucket_partition(after_escalate, expected_total=1)

        reassigned = assign_root_cause(
            complaint["id"],
            root_cause_code="VENDOR_ERROR",
            investigation_note="the ticketing vendor dropped the second inbound message",
        )
        assert reassigned["status"] == "ROOT_CAUSE_ASSIGNED"
        assert reassigned["root_cause_code"] == "VENDOR_ERROR", "the code is overwritten"
        assert reassigned["escalation_count"] == 1, (
            "the round trip is recorded once and reassignment does not undo it"
        )
        final = read_partner(partner_id)
        assert final["open_complaint_count"] == 1
        assert final["escalated_complaint_count"] == 0
        assert final["resolved_complaint_count"] == 0
        assert final["withdrawn_complaint_count"] == 0
        assert_complaint_bucket_partition(final, expected_total=1)
        assert final["status"] == "CONTRACTED"


class TestWindDownExecuteGates:
    def test_execute_is_refused_while_a_sibling_batch_is_still_unfunded(self):
        """Both settlement dimensions of §3.5 must be clean across the whole partner: no settlement
        batch for that partner may have a `funding_status` of `UNFUNDED`, and none may have a
        `reconciliation_status` of `UNRECONCILED` or `VARIANCE_OPEN`. A single outstanding batch on
        either dimension refuses the request with `ERR_UNSETTLED_BATCHES_OUTSTANDING`.

        Design: Corner/state_machines/wind_down_plan_execute_is_refused_while_any_sibling_batch_is_unfunded
        """
        ctx = _live_partner()
        partner_id = ctx["partner"]["id"]
        batch = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=8_000_000,
            interchange_cents=120_000,
            returns_cents=45_000,
            partner_reported_net_cents=8_000_000,
        )
        reconciled = reconcile_batch(batch["id"], 8_000_000)
        assert reconciled["reconciliation_status"] == "MATCHED"
        assert reconciled["funding_status"] == "UNFUNDED", (
            "reconciliation is clean but the money has not moved yet"
        )

        terminated = terminate_agreement(
            ctx["agreement"]["id"], termination_trigger="VOLUNTARY", notice_days=30
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_trigger_fired"] == "VOLUNTARY"
        assert read_partner(partner_id)["status"] == "WIND_DOWN"

        plan = draft_wind_down_plan(
            partner_id,
            trigger_reason="VOLUNTARY",
            notice_days=30,
            target_completion_date="2026-10-15T00:00:00Z",
        )
        assert plan["status"] == "DRAFT"
        assert plan["revision_round"] == 1
        assert plan["approved_by_user_id"] is None
        assert plan["completed_at"] is None
        assert plan["created_by_user_id"] == "po_1"
        assert plan["residual_balance_cents"] == 8_606_250, (
            "the residual sums both custody accounts, 8100000 plus 506250, got "
            f"{plan['residual_balance_cents']}"
        )

        approved = approve_wind_down_plan(plan["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "rc_1"

        # The notice period has run: the plan was created at 2026-08-01 with 30 notice days.
        set_clock("2026-09-05T00:00:00Z")
        refused = api_client.execute_wind_down_plan(
            plan["id"], {"execution_note": "beginning the return of end-user funds"}, PO
        )
        validate_error(refused, ApiErrorId.ERR_UNSETTLED_BATCHES_OUTSTANDING, 409)

        untouched = get_success_data(api_client.get_wind_down_plan(plan["id"], PO))
        assert untouched["status"] == "APPROVED", "the refusal leaves the plan where it was"
        assert untouched["completed_at"] is None
