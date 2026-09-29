"""
Contract-compliance audits, the compliance penalty ledger and the two
independent customer state axes.

Every test starts against an empty database and builds each precondition from
the endpoints the PRD declares.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    DEFAULT_CLOCK_INSTANT,
    DIRECTOR_HEADERS,
    SPECIALIST_HEADERS,
    AccrualMethod,
    AllocationPosture,
    ApiErrorId,
    AuditStatus,
    Channel,
    ComplianceAuditStatus,
    DeductionValidationPolicy,
    MONDAY_AUG_10,
    MONDAY_JUL_06,
    MONDAY_JUL_20,
    MONDAY_SEP_28,
    PENALTY_POINTS_FINDINGS_ISSUED,
    PENALTY_POINTS_RESTRICTED_ALLOCATION,
    ProgramStatus,
    SpendStatus,
    TradingStatus,
    assert_auto_credit_hold_reason,
    assert_compliance_audit,
    assert_money,
    assert_posture_precedence,
    create_compliance_audit_payload,
    credit_hold_payload,
    is_iso8601_timestamp,
    read_allocation,
    read_customer,
    read_promotion,
    record_finding,
    same_instant,
    set_clock,
    setup_allocation_context,
    setup_compliance_audit,
    setup_customer,
    setup_program,
    setup_reference_data,
    setup_restricted_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

MANUAL_HOLD_REASON = "Aged unresolved chargebacks under manual review"


def _customer_on_manual_credit_hold(api):
    """
    A retailer moved to `CREDIT_HOLD` by hand, its compliance axis untouched.

    The hold is placed by a `DeductionSpecialist`, which is one of the two roles
    the endpoint permits.
    """
    set_clock(api, DEFAULT_CLOCK_INSTANT)
    program = setup_program(
        api,
        total_budget_amount=5000000.00,
        accrual_method_default=AccrualMethod.CONSUMPTION.value,
    )
    customer = setup_customer(
        api,
        program["id"],
        channel=Channel.GROCERY.value,
        deduction_validation_policy=DeductionValidationPolicy.EVIDENCE_BASED.value,
    )
    held = validate_success(
        api.place_customer_credit_hold(
            customer["id"], credit_hold_payload(reason=MANUAL_HOLD_REASON),
            SPECIALIST_HEADERS,
        )
    )
    return program, held


class TestIndependentCustomerAxes:
    """The commercial axis and the compliance axis advance on their own."""

    def test_a_manual_hold_and_an_opened_audit_each_move_only_their_own_axis(self, api):
        """
        A hand-placed credit hold leaves `audit_status` `CLEAR`, and opening the
        audit afterwards leaves the hold and its reason exactly as they were.

        PRD: "A `DeductionSpecialist` or a `TradeMarketingDirector` may place an `ACTIVE` customer on credit hold, supplying a free-text `reason`; the customer's `trading_status` moves `ACTIVE` → `CREDIT_HOLD`, the supplied text is stored as `credit_hold_reason`, `version` is incremented by 1 and `updated_at` refreshed."
        PRD: "The compliance axis is deliberately untouched: `audit_status` keeps whatever value it had."
        PRD: "Opening an audit never touches the commercial axis: `trading_status` is unaffected."
        PRD: "Audit activity moves `audit_status` and never rewrites `trading_status` directly; a credit hold moves `trading_status` and never touches `audit_status`."

        Design: Difficulty/non_linear_state_machine/customer_trading_and_audit_axes_advance_independently
        """
        _program, customer = _customer_on_manual_credit_hold(api)

        assert customer["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert customer["credit_hold_reason"] == MANUAL_HOLD_REASON
        assert customer["audit_status"] == AuditStatus.CLEAR.value
        assert customer["compliance_penalty_points"] == 0

        audit = setup_compliance_audit(
            api, customer["id"], scope_start=MONDAY_JUL_06, scope_end=MONDAY_JUL_20
        )
        assert_compliance_audit(audit)
        assert audit["status"] == ComplianceAuditStatus.SCHEDULED.value

        after = read_customer(api, customer["id"])
        assert after["audit_status"] == AuditStatus.AUDIT_IN_PROGRESS.value
        assert after["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert after["credit_hold_reason"] == MANUAL_HOLD_REASON
        assert after["compliance_penalty_points"] == 0

    def test_issued_findings_score_the_retailer_without_rewriting_the_manual_hold(self, api):
        """
        Findings issued on a retailer already on hold add 10 points and move the
        compliance axis, while the commercial axis keeps the hold it had: a score
        of 10 is far short of the suspension threshold of 25.

        PRD: "The first finding moves the audit `SCHEDULED` → `IN_PROGRESS`; each subsequent finding is an `IN_PROGRESS` → `IN_PROGRESS` self-transition."
        PRD: "The audit moves `IN_PROGRESS` → `FINDINGS_ISSUED` and stamps `issued_at` from the logical clock; the customer's `audit_status` moves `AUDIT_IN_PROGRESS` → `FINDINGS_OPEN` and 10 penalty points are added through the ledger of §2.10, which can carry `trading_status` `ACTIVE` → `CREDIT_HOLD` on the independent commercial axis and thereby block that retailer's settlements."
        PRD: "The score drives the customer's commercial axis and only ever moves it forward: an `ACTIVE` customer whose score reaches 10 or more is moved to `CREDIT_HOLD` with `credit_hold_reason` set to the text `AUTO: compliance penalty points <points>`, and a customer already on `CREDIT_HOLD` whose score reaches 25 or more is moved to `SUSPENDED`."
        PRD: "Both thresholds are inclusive: a score of exactly 10 puts an `ACTIVE` customer on hold, and a score of exactly 25 suspends a customer already on hold."

        Design: Difficulty/non_linear_state_machine/customer_trading_and_audit_axes_advance_independently
        """
        _program, customer = _customer_on_manual_credit_hold(api)
        audit = setup_compliance_audit(
            api, customer["id"], scope_start=MONDAY_JUL_06, scope_end=MONDAY_JUL_20
        )

        with_finding = record_finding(api, audit["id"], 1200.00)
        assert with_finding["status"] == ComplianceAuditStatus.IN_PROGRESS.value
        assert with_finding["findings_count"] == 1
        assert_money(with_finding["recovery_claim_amount"], 1200.00,
                     "recovery_claim_amount")

        midway = read_customer(api, customer["id"])
        assert midway["compliance_penalty_points"] == 0
        assert midway["audit_status"] == AuditStatus.AUDIT_IN_PROGRESS.value

        issued = validate_success(
            api.issue_audit_findings(audit["id"], AUDITOR_HEADERS)
        )
        assert issued["status"] == ComplianceAuditStatus.FINDINGS_ISSUED.value
        assert is_iso8601_timestamp(issued["issued_at"])
        assert same_instant(issued["issued_at"], DEFAULT_CLOCK_INSTANT)

        final = read_customer(api, customer["id"])
        assert final["audit_status"] == AuditStatus.FINDINGS_OPEN.value
        assert final["compliance_penalty_points"] == PENALTY_POINTS_FINDINGS_ISSUED
        assert final["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert final["credit_hold_reason"] == MANUAL_HOLD_REASON


class TestAuditStateMachine:
    """The audit's own status ladder and what each move does to the customer."""

    def test_an_audit_is_born_scheduled_with_an_empty_findings_tally(self, api):
        """
        A freshly opened audit carries no findings, no recovery claim and no
        issuance stamp, and it moves only the retailer's compliance axis.

        PRD: "The audit is created in `status` `SCHEDULED` with `findings_count` 0, `recovery_claim_amount` 0.00, `issued_at` null and `auditor_user_id` set to the acting auditor; the customer's `audit_status` moves `CLEAR` → `AUDIT_IN_PROGRESS` and its `version` is incremented by 1."
        PRD: "Opening an audit never touches the commercial axis: `trading_status` is unaffected."

        Design: Corner/state_machines/audit_opens_in_scheduled_with_zero_findings
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_reference_data(api)
        customer = context["customer"]

        audit = validate_success(
            api.create_compliance_audit(
                customer["id"],
                create_compliance_audit_payload(
                    scope_start=MONDAY_JUL_06, scope_end=MONDAY_SEP_28
                ),
                AUDITOR_HEADERS,
            ),
            expected_status=201,
        )
        assert_compliance_audit(audit)
        assert audit["status"] == ComplianceAuditStatus.SCHEDULED.value
        assert audit["version"] == 1
        assert audit["findings_count"] == 0
        assert_money(audit["recovery_claim_amount"], 0.00, "recovery_claim_amount")
        assert audit["issued_at"] is None
        assert audit["customer_id"] == customer["id"]

        after = read_customer(api, customer["id"])
        assert after["audit_status"] == AuditStatus.AUDIT_IN_PROGRESS.value
        assert after["trading_status"] == TradingStatus.ACTIVE.value
        assert after["compliance_penalty_points"] == 0
        assert after["credit_hold_reason"] is None

    def test_issuance_is_refused_until_the_first_finding_has_been_recorded(self, api):
        """
        Issuing findings on an audit still `SCHEDULED` is refused, and the same
        call succeeds once one finding has moved the audit to `IN_PROGRESS`.

        PRD: "A `ComplianceAuditor` or `TradeMarketingDirector` issues findings on an audit that is `IN_PROGRESS` and whose `findings_count` is at least 1 — an audit still `SCHEDULED` has nothing to issue, and the terminal `FINDINGS_ISSUED` cannot be issued twice, both being refused with `ERR_AUDIT_STATE_INVALID` (HTTP 409)."
        PRD: "The first finding moves the audit `SCHEDULED` → `IN_PROGRESS`; each subsequent finding is an `IN_PROGRESS` → `IN_PROGRESS` self-transition."

        Design: Corner/state_machines/issue_findings_requires_fieldwork_to_have_started
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_reference_data(api)
        customer = context["customer"]
        audit = setup_compliance_audit(
            api, customer["id"], scope_start=MONDAY_JUL_06, scope_end=MONDAY_SEP_28
        )
        assert audit["status"] == ComplianceAuditStatus.SCHEDULED.value

        validate_error(
            api.issue_audit_findings(audit["id"], AUDITOR_HEADERS),
            ApiErrorId.AUDIT_STATE_INVALID.value,
        )

        refused_customer = read_customer(api, customer["id"])
        assert refused_customer["compliance_penalty_points"] == 0
        assert refused_customer["audit_status"] == AuditStatus.AUDIT_IN_PROGRESS.value

        with_finding = record_finding(api, audit["id"], 750.00)
        assert with_finding["status"] == ComplianceAuditStatus.IN_PROGRESS.value
        assert with_finding["findings_count"] == 1
        assert_money(with_finding["recovery_claim_amount"], 750.00,
                     "recovery_claim_amount")

        issued = validate_success(
            api.issue_audit_findings(audit["id"], AUDITOR_HEADERS)
        )
        assert issued["status"] == ComplianceAuditStatus.FINDINGS_ISSUED.value
        assert same_instant(issued["issued_at"], DEFAULT_CLOCK_INSTANT)

    def test_issuing_findings_moves_the_retailer_on_both_axes_at_once(self, api):
        """
        Two findings accumulate into one recovery claim, and issuing them moves
        the compliance axis to `FINDINGS_OPEN` while the 10 points they score
        carry the commercial axis from `ACTIVE` to `CREDIT_HOLD`.

        PRD: "Either way `findings_count` is incremented by 1, the supplied `recovery_amount` is added to `recovery_claim_amount` — the running total of every finding amount recorded on the audit, rounded to 2 decimal places — and the audit's `version` is incremented by 1."
        PRD: "The audit moves `IN_PROGRESS` → `FINDINGS_ISSUED` and stamps `issued_at` from the logical clock; the customer's `audit_status` moves `AUDIT_IN_PROGRESS` → `FINDINGS_OPEN` and 10 penalty points are added through the ledger of §2.10, which can carry `trading_status` `ACTIVE` → `CREDIT_HOLD` on the independent commercial axis and thereby block that retailer's settlements."
        PRD: "The score drives the customer's commercial axis and only ever moves it forward: an `ACTIVE` customer whose score reaches 10 or more is moved to `CREDIT_HOLD` with `credit_hold_reason` set to the text `AUTO: compliance penalty points <points>`, and a customer already on `CREDIT_HOLD` whose score reaches 25 or more is moved to `SUSPENDED`."

        Design: Corner/state_machines/issuing_audit_findings_moves_the_customer_on_both_axes
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_reference_data(api)
        customer = context["customer"]
        audit = setup_compliance_audit(
            api, customer["id"], scope_start=MONDAY_JUL_06, scope_end=MONDAY_SEP_28
        )

        record_finding(api, audit["id"], 750.00)
        second = record_finding(api, audit["id"], 500.00)
        assert second["status"] == ComplianceAuditStatus.IN_PROGRESS.value
        assert second["findings_count"] == 2
        assert_money(second["recovery_claim_amount"], 1250.00, "recovery_claim_amount")

        issued = validate_success(
            api.issue_audit_findings(audit["id"], AUDITOR_HEADERS)
        )
        assert issued["status"] == ComplianceAuditStatus.FINDINGS_ISSUED.value
        assert issued["findings_count"] == 2
        assert_money(issued["recovery_claim_amount"], 1250.00, "recovery_claim_amount")
        assert is_iso8601_timestamp(issued["issued_at"])
        assert same_instant(issued["issued_at"], DEFAULT_CLOCK_INSTANT)

        after = read_customer(api, customer["id"])
        assert after["audit_status"] == AuditStatus.FINDINGS_OPEN.value
        assert after["compliance_penalty_points"] == PENALTY_POINTS_FINDINGS_ISSUED
        assert after["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert_auto_credit_hold_reason(after)
        assert after["credit_hold_reason"] == "AUTO: compliance penalty points 10"


class TestOnlyOneOpenAuditPerCustomer:
    """A retailer already under fieldwork cannot be re-audited."""

    def test_a_second_audit_on_the_same_retailer_is_refused(self, api):
        """
        A second audit, even over a different scope window, is refused while the
        first one still holds the retailer's compliance axis.

        PRD: "Only one audit may be open per customer: the customer's `audit_status` must be `CLEAR`, so a retailer already under fieldwork or still carrying issued findings cannot be re-audited, and the attempt is refused with `ERR_AUDIT_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/errors/second_audit_on_the_same_customer_is_refused
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_reference_data(api)
        customer = context["customer"]
        first = setup_compliance_audit(
            api, customer["id"], scope_start=MONDAY_JUL_06, scope_end=MONDAY_SEP_28
        )

        validate_error(
            api.create_compliance_audit(
                customer["id"],
                create_compliance_audit_payload(
                    scope_start=MONDAY_JUL_20, scope_end=MONDAY_AUG_10
                ),
                AUDITOR_HEADERS,
            ),
            ApiErrorId.AUDIT_ALREADY_OPEN.value,
        )

        rows, meta = validate_paginated(
            api.list_customer_compliance_audits(customer["id"], DIRECTOR_HEADERS)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == ComplianceAuditStatus.SCHEDULED.value

        after = read_customer(api, customer["id"])
        assert after["audit_status"] == AuditStatus.AUDIT_IN_PROGRESS.value


class TestCompliancePenaltyLedger:
    """Which populations the running compliance score counts, and which it does not."""

    def test_a_frozen_allocation_stops_contributing_the_points_it_scored_when_restricted(self, api):
        """
        An overspending child promotion restricts the cell and scores its retailer
        10 points, and the year-end lock that reposts the cell to `FROZEN` takes
        those points straight back out of the score while the hold it caused
        stays in place.

        PRD: "the first time a promotion reaches `OVERSPENT` the owning allocation's `overspend_event_count` is incremented and its `posture` moves from `OPEN` to `RESTRICTED` (hop 3); and a `RESTRICTED` allocation contributes penalty points to its customer, which can move that customer's `trading_status` from `ACTIVE` to `CREDIT_HOLD` (hop 4)."
        PRD: "The score is a weighted count of three populations: each of the customer's budget allocations currently in `RESTRICTED` posture contributes 10 points; each `ESCALATED` dispute raised on one of the customer's deductions contributes 5 points; and each compliance audit of that customer currently in `FINDINGS_ISSUED` contributes 10 points."
        PRD: "Allocations in `FROZEN` posture contribute nothing — a year-end program lock is not the retailer's fault."
        PRD: "It is recomputed when the owning program is locked, when a child promotion reaches `OVERSPENT`, and whenever the allocation is read, using a strict precedence of `FROZEN` over `RESTRICTED` over `OPEN`: if the owning program's `status` is `LOCKED` the posture is `FROZEN`; otherwise, if the allocation's `overspend_event_count` is 1 or more the posture is `RESTRICTED`; otherwise it is `OPEN`."
        PRD: "The score drives the customer's commercial axis and only ever moves it forward: an `ACTIVE` customer whose score reaches 10 or more is moved to `CREDIT_HOLD` with `credit_hold_reason` set to the text `AUTO: compliance penalty points <points>`, and a customer already on `CREDIT_HOLD` whose score reaches 25 or more is moved to `SUSPENDED`."

        Design: Corner/calculations/penalty_score_counts_restricted_but_not_frozen_allocations
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_restricted_allocation(api)

        overspent = read_promotion(api, context["promotion"]["id"])
        assert overspent["spend_status"] == SpendStatus.OVERSPENT.value

        restricted = read_allocation(api, context["allocation"]["id"])
        assert restricted["posture"] == AllocationPosture.RESTRICTED.value
        assert restricted["overspend_event_count"] == 1
        assert_posture_precedence(restricted, ProgramStatus.OPEN.value)

        scored = read_customer(api, context["customer"]["id"])
        assert scored["compliance_penalty_points"] == PENALTY_POINTS_RESTRICTED_ALLOCATION
        assert scored["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert scored["audit_status"] == AuditStatus.CLEAR.value
        assert_auto_credit_hold_reason(scored)

        locked = validate_success(
            api.lock_program(context["program"]["id"], DIRECTOR_HEADERS)
        )
        assert locked["status"] == ProgramStatus.LOCKED.value

        frozen = read_allocation(api, context["allocation"]["id"])
        assert frozen["posture"] == AllocationPosture.FROZEN.value
        assert frozen["overspend_event_count"] == 1
        assert_posture_precedence(frozen, ProgramStatus.LOCKED.value)

        rescored = read_customer(api, context["customer"]["id"])
        assert rescored["compliance_penalty_points"] == 0
        assert rescored["trading_status"] == TradingStatus.CREDIT_HOLD.value

    def test_issued_findings_alone_carry_a_clean_retailer_onto_credit_hold(self, api):
        """
        With every budget cell in `OPEN` posture and no dispute anywhere, a single
        issued audit scores exactly the inclusive hold threshold of 10 points, and
        the retailer is put on hold with the automatic reason text.

        PRD: "each compliance audit of that customer currently in `FINDINGS_ISSUED` contributes 10 points."
        PRD: "Both thresholds are inclusive: a score of exactly 10 puts an `ACTIVE` customer on hold, and a score of exactly 25 suspends a customer already on hold."
        PRD: "The score drives the customer's commercial axis and only ever moves it forward: an `ACTIVE` customer whose score reaches 10 or more is moved to `CREDIT_HOLD` with `credit_hold_reason` set to the text `AUTO: compliance penalty points <points>`, and a customer already on `CREDIT_HOLD` whose score reaches 25 or more is moved to `SUSPENDED`."
        PRD: "The audit moves `IN_PROGRESS` → `FINDINGS_ISSUED` and stamps `issued_at` from the logical clock; the customer's `audit_status` moves `AUDIT_IN_PROGRESS` → `FINDINGS_OPEN` and 10 penalty points are added through the ledger of §2.10, which can carry `trading_status` `ACTIVE` → `CREDIT_HOLD` on the independent commercial axis and thereby block that retailer's settlements."

        Design: Corner/complexity_layers/findings_issuance_alone_reaches_the_credit_hold_threshold
        """
        set_clock(api, DEFAULT_CLOCK_INSTANT)
        context = setup_allocation_context(api)
        customer = context["customer"]

        open_cell = read_allocation(api, context["allocation"]["id"])
        assert open_cell["posture"] == AllocationPosture.OPEN.value
        assert open_cell["overspend_event_count"] == 0

        before = read_customer(api, customer["id"])
        assert before["compliance_penalty_points"] == 0
        assert before["trading_status"] == TradingStatus.ACTIVE.value

        audit = setup_compliance_audit(
            api, customer["id"], scope_start=MONDAY_JUL_06, scope_end=MONDAY_SEP_28
        )
        record_finding(api, audit["id"], 1200.00)
        issued = validate_success(
            api.issue_audit_findings(audit["id"], AUDITOR_HEADERS)
        )
        assert issued["status"] == ComplianceAuditStatus.FINDINGS_ISSUED.value

        after = read_customer(api, customer["id"])
        assert after["compliance_penalty_points"] == PENALTY_POINTS_FINDINGS_ISSUED
        assert after["compliance_penalty_points"] == 10
        assert after["trading_status"] == TradingStatus.CREDIT_HOLD.value
        assert after["audit_status"] == AuditStatus.FINDINGS_OPEN.value
        assert after["credit_hold_reason"] == "AUTO: compliance penalty points 10"
        assert_auto_credit_hold_reason(after)

        still_open = read_allocation(api, context["allocation"]["id"])
        assert still_open["posture"] == AllocationPosture.OPEN.value
        assert still_open["overspend_event_count"] == 0
