"""Non-linear state machines, cascades and ordering that crosses entities."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    activate_promo_schedule,
    advance_clock,
    api_client,
    assert_port_request,
    check_migration_eligibility,
    create_account,
    create_activated_line,
    create_active_protection_case,
    create_bare_line,
    create_device_plan,
    create_draft_port_request,
    create_migration_request,
    create_promo_schedule,
    get_promo_schedule,
    get_migration_request,
    create_rejection_code,
    get_account,
    get_device_plan,
    get_line,
    get_port_request,
    record_rejection,
    submit_port_request,
)

CARE = TEST_USERS["customer_service_headers"]


class TestPortRequestBranchingFork:
    """PENDING forks to REJECTED or CANCELLED with divergent side-effect sets."""

    def test_rejection_branch_records_the_failure_and_releases_the_number(self, api):
        """PRD §3.2: "The request moves from `PENDING` to `REJECTED`, and, importantly,
        the attached line's `number_status` is returned to `UNASSIGNED`, releasing the
        number the submission had reserved."

        Design: Difficulty/non_linear_state_machine/port_request_branching_fork_reject_or_cancel
        """
        create_rejection_code("PIN_INVALID")
        account = create_account()
        line = create_bare_line(account["id"], "4155550501", billing_mode="PREPAID")
        request = submit_port_request(create_draft_port_request(line))

        record_rejection(request["id"], "PIN_INVALID")
        recorded = get_port_request(request["id"])

        assert recorded["request_state"] == "REJECTED"
        assert recorded["rejection_count"] == 1
        assert recorded["last_rejection_code"] == "PIN_INVALID"
        assert get_line(line["id"])["number_status"] == "UNASSIGNED"
        assert_port_request(recorded)

    def test_cancellation_branch_is_terminal_and_records_no_rejection(self, api):
        """PRD §3.1: "A request still in `PENDING` may be cancelled by a care agent, which
        returns the attached line's `number_status` to `UNASSIGNED`; the operator supplies
        no body for this."

        Design: Difficulty/non_linear_state_machine/port_request_branching_fork_reject_or_cancel
        """
        account = create_account()
        line = create_bare_line(account["id"], "4155550502", billing_mode="PREPAID")
        request = submit_port_request(create_draft_port_request(line))

        api_client.cancel_port_request(request["id"], {}, ADMIN)
        cancelled = get_port_request(request["id"])

        assert cancelled["request_state"] == "CANCELLED"
        assert cancelled["rejection_count"] == 0
        assert get_line(line["id"])["number_status"] == "UNASSIGNED"


class TestMigrationEligibilityCycleAndFork:
    """Eligibility forks to APPROVED or BLOCKED and can be re-entered."""

    def test_unprotected_line_without_open_obligation_schedules_the_cutover(self, api):
        """PRD §3.3: "If instead the attached line's `port_protection_status` is
        `UNPROTECTED` and no `PortRequest` on the attached line is in `PENDING` or
        `RESUBMITTED`, the request goes to `APPROVED` and the attached line's
        `number_status` is set to `RESERVED`, holding the number for the migration."
        PRD §3.3: "once `requested_cutover_at` is set to an instant at or after the
        current logical clock instant, the request moves on to `CUTOVER_SCHEDULED` with
        `updated_at` recomputed."

        Design: Difficulty/non_linear_state_machine/migration_request_eligibility_cycle_and_fork
        """
        account = create_account()
        line = create_activated_line(account["id"], "4155550601", billing_mode="PREPAID")
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )

        result = check_migration_eligibility(migration["id"])

        assert result["migration_state"] != "BLOCKED"
        assert result["migration_state"] == "CUTOVER_SCHEDULED"
        assert get_line(line["id"])["number_status"] == "RESERVED"

    def test_eligibility_check_requires_a_prepaid_line(self, api):
        """PRD §3.3: "The care agent first asks for an eligibility check, which requires
        that the attached line's `billing_mode` is `PREPAID` and moves the request from
        `DRAFT` to `ELIGIBILITY_CHECK` with `updated_at` recomputed."

        Design: Difficulty/non_linear_state_machine/migration_request_eligibility_cycle_and_fork
        """
        account = create_account()
        line = create_bare_line(account["id"], "4155550602", billing_mode="POSTPAID")
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )

        response = api_client.check_migration_eligibility(
            migration["id"], {}, CARE
        )
        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_INVALID_STATE"

        result = get_migration_request(migration["id"])

        assert result["migration_state"] == "DRAFT"


class TestPortCutoverClockCascade:
    """A single clock advance propagates through four links on four entities."""

    def test_clock_reaching_the_requested_instant_completes_the_port(self, api):
        """PRD §3.8: "For a port-in, the trigger is the clock reaching the request's
        `requested_cutover_at` while the request is in `ACCEPTED_PENDING_CUTOVER`; for a
        migration, the trigger is the clock reaching the migration's
        `requested_cutover_at` while the migration is in `CUTOVER_SCHEDULED`."

        Design: Difficulty/transitive_cascade/port_cutover_clock_cascade_reaches_promo_vesting
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155550701", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="7777", account_number_at_losing_carrier="ACC7",
            requested_cutover_at="2026-09-10T00:00:00Z",
        )
        submit_port_request(request)
        api_client.accept_port_request(request["id"], {}, ADMIN)

        advance_clock("2026-09-10T00:00:00Z")

        ported = get_port_request(request["id"])
        assert ported["request_state"] == "PORTED"
        assert ported["cutover_completed_at"] is not None

    def test_port_cutover_moves_the_line_into_its_final_number_state(self, api):
        """PRD §3.8: "First, `cutover_completed_at` is stamped with the current logical
        clock instant, the attached line's `service_status` is set to `ACTIVE`, and its
        `number_status` is set to `PORTED_IN`."

        Design: Difficulty/transitive_cascade/port_cutover_clock_cascade_reaches_promo_vesting
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155550701", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="7777", account_number_at_losing_carrier="ACC7",
            requested_cutover_at="2026-09-10T00:00:00Z",
        )
        submit_port_request(request)
        api_client.accept_port_request(request["id"], {}, ADMIN)

        advance_clock("2026-09-10T00:00:00Z")

        cut_over = get_line(line["id"])
        assert cut_over["service_status"] == "ACTIVE"
        assert cut_over["number_status"] == "PORTED_IN"

    def test_line_opened_at_and_tenure_are_stamped_by_the_same_cascade(self, api):
        """PRD §3.8: "Second, because the line's `service_status` has just become
        `ACTIVE`, `line_opened_at` is stamped with the current logical clock instant when
        it is still null."

        Design: Difficulty/transitive_cascade/port_cutover_clock_cascade_reaches_promo_vesting
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155550702", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="7777", account_number_at_losing_carrier="ACC7",
            requested_cutover_at="2026-09-10T00:00:00Z",
        )
        submit_port_request(request)
        api_client.accept_port_request(request["id"], {}, ADMIN)

        advance_clock("2026-09-10T00:00:00Z")

        cut_over = get_line(line["id"])
        assert cut_over["line_opened_at"] is not None
        assert cut_over["loyalty_tenure_months"] >= 0
        assert cut_over["retention_cycle_count"] >= 0


class TestPromoClawbackCascade:
    """Each claw-back runs three hops on the line's own objects."""

    def test_each_plan_absorbs_only_its_own_lines_reversed_credit(self, api):
        """PRD §3.4: "Second, because the line's promotional posture has just changed, the
        attached line's `DeviceInstallmentPlan` has its `remaining_balance_cents`
        incremented by the schedule's `provisional_total_cents` — the previously credited
        amount is pushed back onto the device balance the customer still owes."

        Design: Difficulty/transitive_cascade/promo_clawback_cascade_lands_on_the_plans_own_balance
        """
        first = create_clawback_pair(offset=0)
        second = create_clawback_pair(offset=1)
        api_client.claw_back_promo_schedule(first["schedule"]["id"], {}, ADMIN)
        api_client.claw_back_promo_schedule(second["schedule"]["id"], {}, ADMIN)

        plan_one = get_device_plan(first["plan"]["id"])
        plan_two = get_device_plan(second["plan"]["id"])
        assert plan_one["remaining_balance_cents"] == 72000
        assert plan_two["remaining_balance_cents"] == 72000

    def test_account_ledger_reaches_the_sum_of_both_reversals(self, api):
        """PRD §3.4: "Independently of the hops, the account's `promo_clawed_back_cents`
        is incremented by the reversal amount and `net_promo_credit_cents` is recomputed."

        Design: Difficulty/transitive_cascade/promo_clawback_cascade_lands_on_the_plans_own_balance
        """
        first = create_clawback_pair(offset=10)
        second = create_clawback_pair(offset=11, account_id=first["account"]["id"])
        api_client.claw_back_promo_schedule(first["schedule"]["id"], {}, ADMIN)
        api_client.claw_back_promo_schedule(second["schedule"]["id"], {}, ADMIN)

        account = get_account(first["account"]["id"])
        assert account["promo_credited_cents"] == 64000
        assert account["promo_clawed_back_cents"] == 64000
        assert account["net_promo_credit_cents"] == 0

    def test_recomputed_installment_follows_the_grown_balance(self, api):
        """PRD §3.4: "Third, because that balance has just increased, the plan's
        `monthly_installment_cents` and its `plan_state` are recomputed through the
        installment-balance rule in §3.5."

        Design: Difficulty/transitive_cascade/promo_clawback_cascade_lands_on_the_plans_own_balance
        """
        pair = create_clawback_pair(offset=20)
        api_client.claw_back_promo_schedule(pair["schedule"]["id"], {}, ADMIN)

        plan = get_device_plan(pair["plan"]["id"])
        assert plan["remaining_balance_cents"] == 72000
        assert plan["monthly_installment_cents"] == 72000 // 24


class TestProtectionBeatsResubmissionCooldown:
    """The safety pair outranks the temporal pair on a resubmission."""

    def test_active_protection_refuses_the_resubmission(self, api):
        """PRD §3.2: "the attached line's `port_protection_status` must be
        `UNPROTECTED` (otherwise `ERR_PORT_PROTECTION_ACTIVE`, 403)"

        Design: Difficulty/priority_pair_validation_conflict/protection_beats_resubmission_cooldown
        """
        create_rejection_code("PORT_BLOCK", retry_after_hours=48)
        account = create_account()
        line = create_bare_line(account["id"], "4155550901", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="9999", account_number_at_losing_carrier="ACC9",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request)
        record_rejection(request["id"], "PORT_BLOCK")
        create_active_protection_case(line)
        assert get_line(line["id"])["port_protection_status"] == "PROTECTED"
        advance_clock("2026-09-02T12:00:00Z")

        response = api_client.resubmit_port_request(
            request["id"],
            {"transfer_pin": "9999", "account_number_at_losing_carrier": "ACC9"},
            CARE,
        )

        assert response.status_code == 403
        assert response.json()["data"]["error_id"] == "ERR_PORT_PROTECTION_ACTIVE"

    def test_the_request_stays_rejected_after_the_refused_resubmission(self, api):
        """PRD §3.2: "First, the most recent `rejection_code` must resolve to a catalog
        row whose `resubmission_allowed` is true; if the carrier marked that objection as
        final, the resubmission is refused with `ERR_RESUBMISSION_NOT_ALLOWED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/protection_beats_resubmission_cooldown
        """
        create_rejection_code("PORT_BLOCK", retry_after_hours=48)
        account = create_account()
        line = create_bare_line(account["id"], "4155550901", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="9999", account_number_at_losing_carrier="ACC9",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request)
        record_rejection(request["id"], "PORT_BLOCK")
        create_active_protection_case(line)

        unchanged = get_port_request(request["id"])
        assert unchanged["request_state"] == "REJECTED"
        assert unchanged["rejection_count"] == 1


class TestTransferPinBeatsResubmissionCooldown:
    """With the line unprotected the PIN check is reached, not the cooling-off."""

    def test_mismatched_pin_refuses_the_resubmission(self, api):
        """PRD §3.2: "the supplied `transfer_pin` must be exactly four digits and must
        match the `account_number_at_losing_carrier` supplied on the same call (otherwise
        `ERR_TRANSFER_PIN_MISMATCH`, 422)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_pin_beats_resubmission_cooldown
        """
        create_rejection_code("PORT_BLOCK", retry_after_hours=48)
        account = create_account()
        line = create_bare_line(account["id"], "4155551001", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="1010", account_number_at_losing_carrier="ACCA",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request, account_number_at_losing_carrier="ACCA")
        record_rejection(request["id"], "PORT_BLOCK")
        advance_clock("2026-09-02T12:00:00Z")

        response = api_client.resubmit_port_request(
            request["id"],
            {"transfer_pin": "1010", "account_number_at_losing_carrier": "OTHER"},
            CARE,
        )

        assert response.json()["data"]["error_id"] == "ERR_TRANSFER_PIN_MISMATCH"

    def test_the_request_is_unchanged_by_the_refused_resubmission(self, api):
        """PRD §2.9: "On a port-request submission or resubmission, the state check for
        the request comes first, then the attached line's port-protection check, then the
        transfer-credential check, then the resubmission-eligibility and cooling-off
        checks, and finally the duplicate-reservation check."

        Design: Difficulty/priority_pair_validation_conflict/transfer_pin_beats_resubmission_cooldown
        """
        create_rejection_code("PORT_BLOCK", retry_after_hours=48)
        account = create_account()
        line = create_bare_line(account["id"], "4155551001", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="1010", account_number_at_losing_carrier="ACCA",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request, account_number_at_losing_carrier="ACCA")
        record_rejection(request["id"], "PORT_BLOCK")

        unchanged = get_port_request(request["id"])
        assert unchanged["request_state"] == "REJECTED"


# --- local helpers -----------------------------------------------------------


def create_clawback_pair(offset, account_id=None):
    """One line carrying an ACTIVE 40000 plan and an ACTIVE 32000 schedule.

    PRD §3.4 permits a reversal only while the schedule is `ACTIVE` ("A platform
    operator may claw a schedule back while it is `ACTIVE`, and only then"), so the
    schedule is set applying — its window starts at the clock instant — before the
    claw-back runs.
    """
    account = (
        get_account(account_id) if account_id else create_account(existing_deposit_cents=50000)
    )
    line = create_activated_line(
        account["id"], f"41555508{offset:02d}", billing_mode="PREPAID"
    )
    advance_clock("2026-09-02T00:00:00Z")
    plan = create_device_plan(
        line,
        device_price_cents=40000,
        down_payment_cents=0,
        installment_months=24,
        activation_at="2026-09-02T00:00:00Z",
    )
    schedule = create_promo_schedule(
        line, monthly_credit_cents=1000, installment_months=12,
        retention_requirement_cycles=12, window_start="2026-09-02T00:00:00Z",
    )
    activate_promo_schedule(schedule["id"])
    return {"account": account, "line": get_line(line["id"]), "plan": plan,
            "schedule": get_promo_schedule(schedule["id"])}