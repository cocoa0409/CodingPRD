"""Transitive cascade chains: remediation default and SLA breach."""
from test_helpers import (
    get_audit,
    api_client,
    TEST_USERS,
    create_national_account,
    create_work_order,
    dispatch_and_start,
    get_agreement,
    get_franchisee,
    get_national_account,
    get_work_order,
    make_franchisee_operator_headers,
    remediation_action,
    run_sweep,
    set_clock,
    setup_active_agreement,
    setup_published_failing_audit,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestStandardsDefaultCascade:
    def _escalated_remediation(self):
        _, franchisee, _, agreement, audit = setup_published_failing_audit()
        assert audit["remediation_due_iso"] == "2026-09-08T00:00:00Z", (
            f"a remediation opened at 2026-09-01T00:00:00Z is due 168 logical "
            f"hours later, got {audit['remediation_due_iso']}"
        )
        set_clock("2026-09-09T00:00:00Z")
        run_sweep()
        return franchisee, agreement, audit

    def test_defaulting_reaches_the_audit_the_agreement_and_the_franchisee(self, api):
        """PRD §3.8: "Defaulting moves the remediation to `DEFAULTED`, sets the
        agreement's `standards_status` to `DEFAULT`, recomputes the agreement's
        `open_remediation_count`, and — as the severest consequence available in
        this system — sets the agreement's franchisee's status to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/standards_default_cascade_audit_to_agreement_to_franchisee
        """
        franchisee, agreement, audit = self._escalated_remediation()

        remediation_action(
            audit["id"], "DEFAULT", reason="Remediation never submitted",
        )

        defaulted = get_audit(audit["id"])
        assert defaulted["remediation_status"] == "DEFAULTED", (
            f"hop 1: the remediation must reach DEFAULTED, got "
            f"{defaulted['remediation_status']}"
        )

        refreshed = get_agreement(agreement["id"])
        assert refreshed["standards_status"] == "DEFAULT", (
            f"hop 2: the default must drive the agreement's standards posture to "
            f"DEFAULT, got {refreshed['standards_status']}"
        )

        operator = get_franchisee(franchisee["id"])
        assert operator["status"] == "SUSPENDED", (
            f"hop 3: the default must suspend the agreement's franchisee, got "
            f"{operator['status']}"
        )

    def test_the_cascade_leaves_the_commercial_axis_and_lists_the_suspension(self, api):
        """PRD §3.8: "Because a defaulted agreement's standards status blocks
        renewal, blocks activation of a renewal, and blocks approval of a
        transfer, a single default can freeze an operator's entire relationship
        with the franchisor until the record is cleared."

        Design: Difficulty/transitive_cascade/standards_default_cascade_audit_to_agreement_to_franchisee
        """
        _, agreement, audit = self._escalated_remediation()
        remediation_action(audit["id"], "DEFAULT", reason="Remediation never submitted")

        refreshed = get_agreement(agreement["id"])
        assert refreshed["lifecycle_status"] == "ACTIVE", (
            "the cascade moved the standards axis and the franchisee, not the "
            f"commercial axis, got {refreshed['lifecycle_status']}"
        )

        resp = api.list_franchisees(ADMIN, {"status": "SUSPENDED"})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, (
            f"exactly one franchisee must be listed as SUSPENDED, got {meta['total_count']}"
        )


class TestSlaBreachCascade:
    def _program_with_one_breach_already_recorded(self):
        _, franchisee, _, agreement = setup_active_agreement()
        account = create_national_account(
            account_type="NATIONAL_ACCOUNT",
            contracted_brands=[agreement["brand_id"]],
            service_level_hours=8,
            sla_credit_per_breach_cents=7500,
            breach_tolerance=1,
            annual_commitment_cents=40000000,
        )
        operator = make_franchisee_operator_headers(franchisee["id"])
        wo1 = create_work_order(
            agreement["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
            service_level_hours=4, parts_cents=0, national_account_id=account["id"],
        )
        wo2 = create_work_order(
            agreement["id"], source="NATIONAL_ACCOUNT", priority="STANDARD",
            service_level_hours=4, parts_cents=0, national_account_id=account["id"],
        )
        # Both orders are dispatched at the 2026-09-01T00:00:00Z clock, so each
        # carries its own 04:00 deadline; the clock is then advanced past both.
        dispatch_and_start(wo1["id"], franchisee["id"])
        dispatch_and_start(wo2["id"], franchisee["id"])
        set_clock("2026-09-01T05:00:00Z")
        # PRD 3.4: a breach may be marked explicitly only from IN_PROGRESS and
        # only once the deadline has been reached. With tolerance 1 the program
        # absorbs its first breach and is suspended on the second.
        api_client.breach_work_order(wo1["id"], ADMIN)
        return franchisee, agreement, account, wo1, wo2

    def test_the_second_breach_crosses_tolerance_and_suspends_the_program(self, api):
        """PRD §3.4: "if the freshly recomputed `open_breach_count` exceeds the
        program's `breach_tolerance`, the program's status becomes `SUSPENDED`,
        which blocks all further dispatch for it. A program whose tolerance is
        three absorbs its third breach and is suspended on the fourth."

        Design: Difficulty/transitive_cascade/sla_breach_cascade_work_order_to_national_account_status
        """
        _, _, account, wo1, wo2 = self._program_with_one_breach_already_recorded()

        resp = api.breach_work_order(wo2["id"], ADMIN)
        breached = validate_success(resp, 200)
        assert breached["status"] == "SLA_BREACHED"

        program = get_national_account(account["id"])
        assert program["open_breach_count"] == 2, (
            f"hop 1: the second breach must raise the count to 2, got "
            f"{program['open_breach_count']}"
        )
        assert program["status"] == "SUSPENDED", (
            f"hop 2: crossing the tolerance of 1 must suspend the program, got "
            f"{program['status']}"
        )

    def test_breach_economics_and_the_untouched_agreement_axis(self, api):
        """PRD §3.4: "the program's `open_breach_count` is increased by one, its
        `sla_credit_accrued_cents` is increased by that program's
        `sla_credit_per_breach_cents`, its `accumulated_revenue_cents` is
        increased by the work order's `revenue_cents`".

        Design: Difficulty/transitive_cascade/sla_breach_cascade_work_order_to_national_account_status
        """
        _, agreement, account, wo1, wo2 = self._program_with_one_breach_already_recorded()
        api.breach_work_order(wo2["id"], ADMIN)

        program = get_national_account(account["id"])
        assert program["sla_credit_accrued_cents"] == 15000, (
            f"two breaches at 7500 cents each must accrue 15000, got "
            f"{program['sla_credit_accrued_cents']}"
        )
        assert get_work_order(wo1["id"])["status"] == "SLA_BREACHED"
        assert get_work_order(wo2["id"])["status"] == "SLA_BREACHED"

        refreshed = get_agreement(agreement["id"])
        assert refreshed["lifecycle_status"] == "ACTIVE", (
            f"the cascade did not touch the agreement, got {refreshed['lifecycle_status']}"
        )