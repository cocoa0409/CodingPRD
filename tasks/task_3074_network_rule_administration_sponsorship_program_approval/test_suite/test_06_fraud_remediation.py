"""Fraud monitoring cycles, thresholds, remediation plans, and escalation."""
from test_helpers import (
    ApiErrorId,
    create_active_member,
    create_confirmed_fraud_case,
    create_cycle,
    evaluate_cycle,
    get_success_data,
    list_cycle_plans,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_fraud_analyst_headers

FA = TEST_USERS["fraud_analyst_headers"]
OP = TEST_USERS["network_operator_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]


def _mk_merchant(api, acquirer_id, volume, participant_id=None):
    payload = {"mcc": "5411", "region": "NA",
               "declared_monthly_volume_cents": volume}
    if participant_id:
        payload["participant_id"] = participant_id
    else:
        payload["acquirer_member_id"] = acquirer_id
    return get_success_data(api.create_merchant(payload, SM))


class TestMerchantThresholdBoundary:
    def _setup(self, api):
        acquirer = create_active_member(legal_name="Acq Bank",
                                        member_kind="ACQUIRER", region="NA")
        issuer = create_active_member(legal_name="Iss Bank",
                                      member_kind="ISSUER", region="NA")
        mc1 = _mk_merchant(api, acquirer["id"], 10000000)
        mc2 = _mk_merchant(api, acquirer["id"], 10000000)
        # Exactly at the threshold: 100000 * 10000 / 10000000 = 100 bps.
        create_confirmed_fraud_case(mc1["id"], issuer["id"], 100000)
        # One basis point of volume below: 99999 * 10000 / 10000000 < 100 bps.
        create_confirmed_fraud_case(mc2["id"], issuer["id"], 99999)
        cycle = create_cycle()
        set_clock("2026-09-20T00:00:00Z")
        return acquirer, issuer, mc1, mc2, cycle

    def test_merchant_exactly_at_100bps_flagged(self, api):
        """PRD §3.8: "the sum of `fraud_amount_cents` over the merchant's
        `CONFIRMED` cases whose `confirmed_at` falls at or after
        `period_start` and strictly before `period_end`, multiplied by ten
        thousand, divided by the merchant's `declared_monthly_volume_cents`
        (floored at one to avoid a zero denominator), compared exactly — by
        cross-multiplication, with no intermediate rounding — against a
        threshold of 100 basis points. A merchant at or above the threshold
        has its `fraud_monitoring_status` set to `REMEDIATION_REQUIRED` and a
        `RemediationPlan` created for it with `subject_type` `MERCHANT`".

        Design: Difficulty/boundary_precision_check/merchant_fraud_threshold_exactly_at_100bps
        """
        _, _, mc1, mc2, cycle = self._setup(api)
        evaluate_cycle(cycle["id"])
        mc1_now = get_success_data(api.get_merchant(mc1["id"], FA))
        assert mc1_now["fraud_monitoring_status"] == "REMEDIATION_REQUIRED"
        plans = list_cycle_plans(cycle["id"])
        merchant_plans = [p for p in plans
                          if p["subject_type"] == "MERCHANT"
                          and p["subject_id"] == mc1["id"]]
        assert len(merchant_plans) == 1, \
            "exactly one remediation plan must be created for the flagged merchant"

    def test_merchant_one_cent_below_threshold_not_flagged(self, api):
        """PRD §2.9: "Fraud-rate thresholds are compared in exact rational
        arithmetic: the comparison cross-multiplies rather than computing a
        rounded quotient, so a merchant whose true rate is an infinitesimal
        fraction below the threshold is not flagged, and one exactly at the
        threshold is."
        PRD §3.8: "`merchants_flagged` counts these."

        Design: Difficulty/boundary_precision_check/merchant_fraud_threshold_exactly_at_100bps
        """
        _, _, mc1, mc2, cycle = self._setup(api)
        completed = evaluate_cycle(cycle["id"])
        assert completed["merchants_flagged"] == 1
        mc2_now = get_success_data(api.get_merchant(mc2["id"], FA))
        assert mc2_now["fraud_monitoring_status"] == "NOT_MONITORED", \
            "99999*10000/10000000 = 99.999 bps is below the threshold"


class TestFraudInputSetFiltering:
    def test_fraud_rate_input_set_excludes_out_of_window(self, api):
        """PRD §3.8: "the sum of `fraud_amount_cents` over the merchant's
        `CONFIRMED` cases whose `confirmed_at` falls at or after
        `period_start` and strictly before `period_end`".

        Design: Corner/calculations/fraud_rate_input_set_excludes_out_of_window
        """
        acquirer = create_active_member(legal_name="A Bank",
                                        member_kind="ACQUIRER", region="NA")
        issuer = create_active_member(legal_name="I Bank", member_kind="ISSUER",
                                      region="NA")
        merchant = _mk_merchant(api, acquirer["id"], 10000000)

        # Case 1: confirmed BEFORE the cycle window.
        set_clock("2026-08-20T00:00:00Z")
        create_confirmed_fraud_case(merchant["id"], issuer["id"], 10000)
        # Case 2: REPORTED inside the window but never confirmed.
        set_clock("2026-09-05T00:00:00Z")
        get_success_data(api.create_fraud_case(
            {"merchant_id": merchant["id"],
             "reported_by_member_id": issuer["id"],
             "fraud_amount_cents": 10000}, FA))

        cycle = create_cycle(cycle_label="CX")
        set_clock("2026-09-20T00:00:00Z")
        completed = evaluate_cycle(cycle["id"])
        assert completed["merchants_flagged"] == 0, \
            "out-of-window confirmations and unconfirmed reports must be excluded"
        merchant_now = get_success_data(api.get_merchant(merchant["id"], FA))
        assert merchant_now["fraud_monitoring_status"] == "NOT_MONITORED"


class TestCycleTimingGate:
    def test_cycle_evaluation_before_period_end_rejected(self, api):
        """PRD §3.8: "Evaluation is the cycle's single act, performed by a
        `FraudAnalyst` once the logical clock has reached `period_end`;
        attempting it earlier is rejected with `ERR_WINDOW_EXPIRED`."

        Design: Corner/calculations/cycle_evaluation_before_period_end_rejected
        """
        cycle = create_cycle(cycle_label="CE",
                             period_start="2026-09-10T00:00:00Z",
                             period_end="2026-09-20T00:00:00Z")
        res = api.evaluate_fraud_program_cycle(cycle["id"], FA)
        validate_error(res, ApiErrorId.ERR_WINDOW_EXPIRED)
        set_clock("2026-09-21T00:00:00Z")
        data = validate_success(api.evaluate_fraud_program_cycle(cycle["id"],
                                                                 FA))
        assert data["status"] == "COMPLETED"


class TestFraudCaseMerchantGate:
    def _setup(self, api):
        acquirer = create_active_member(legal_name="Acq Bank",
                                        member_kind="ACQUIRER", region="NA")
        participant = get_success_data(api.create_participant(
            {"name": "P Co", "sponsor_member_id": acquirer["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.approve_participant(participant["id"], SM))
        mc1 = _mk_merchant(api, acquirer["id"], 5000000,
                           participant_id=participant["id"])
        mc2 = _mk_merchant(api, acquirer["id"], 5000000)
        f1 = get_success_data(api.create_fraud_case(
            {"merchant_id": mc1["id"],
             "reported_by_member_id": acquirer["id"],
             "fraud_amount_cents": 100}, FA))
        f2 = get_success_data(api.create_fraud_case(
            {"merchant_id": mc2["id"],
             "reported_by_member_id": acquirer["id"],
             "fraud_amount_cents": 100}, FA))
        # Terminate the participant; its merchant cascades to TERMINATED.
        get_success_data(api.suspend_participant(participant["id"], SM))
        get_success_data(api.terminate_participant(participant["id"], SM))
        return acquirer, participant, mc1, mc2, f1, f2

    def test_fraud_confirm_on_terminated_merchant_rejected(self, api):
        """PRD §3.8: "Confirmation requires the case to be `REPORTED` and the
        merchant to be `ACTIVE` — a case against a suspended or terminated
        merchant is rejected with `ERR_MERCHANT_NOT_ACTIVE`".
        PRD §2.8: "Terminating a participant terminates every merchant
        operating under it."

        Design: Difficulty/cross_entity_state_dependency/fraud_confirm_gated_on_merchant_state
        """
        _, _, mc1, _, f1, _ = self._setup(api)
        merchant_now = get_success_data(api.get_merchant(mc1["id"], FA))
        assert merchant_now["status"] == "TERMINATED"
        res = api.confirm_fraud_case(f1["id"], FA)
        validate_error(res, ApiErrorId.ERR_MERCHANT_NOT_ACTIVE)
        case_now = get_success_data(api.get_fraud_case(f1["id"], FA))
        assert case_now["status"] == "REPORTED"

    def test_fraud_confirm_on_active_merchant_succeeds(self, api):
        """PRD §3.8: "Confirmation requires the case to be `REPORTED` and the
        merchant to be `ACTIVE` — a case against a suspended or terminated
        merchant is rejected with `ERR_MERCHANT_NOT_ACTIVE` — and moves the
        case to the terminal `CONFIRMED` state, stamping `confirmed_at` with
        the current logical time."

        Design: Difficulty/cross_entity_state_dependency/fraud_confirm_gated_on_merchant_state
        """
        _, _, _, mc2, _, f2 = self._setup(api)
        merchant_now = get_success_data(api.get_merchant(mc2["id"], FA))
        assert merchant_now["status"] == "ACTIVE"
        data = validate_success(api.confirm_fraud_case(f2["id"], FA))
        assert data["status"] == "CONFIRMED"
        assert data["confirmed_at"] is not None


class TestRemediationLifecycle:
    def _setup_overdue_acquirer_plan(self, api):
        """Acquirer flagged at 100 bps (>= 50 threshold) in cycle C1; clock
        advanced past the plan's due date; cycle C2 evaluated, sweeping the
        plan to OVERDUE. Returns (acquirer, participant, merchant, plan)."""
        acquirer = create_active_member(legal_name="Acq Bank",
                                        member_kind="ACQUIRER", region="NA")
        participant = get_success_data(api.create_participant(
            {"name": "P Co", "sponsor_member_id": acquirer["id"],
             "program_name": "PP"}, SM))
        get_success_data(api.approve_participant(participant["id"], SM))
        merchant = _mk_merchant(api, acquirer["id"], 1000000,
                                participant_id=participant["id"])
        issuer = create_active_member(legal_name="Iss Bank",
                                      member_kind="ISSUER", region="NA")
        create_confirmed_fraud_case(merchant["id"], issuer["id"], 10000)
        c1 = create_cycle(cycle_label="C1")
        set_clock("2026-09-20T00:00:00Z")
        evaluate_cycle(c1["id"])
        plans = list_cycle_plans(c1["id"])
        acquirer_plans = [p for p in plans if p["subject_type"] == "ACQUIRER"]
        assert len(acquirer_plans) == 1, "setup expects one acquirer plan"
        plan = acquirer_plans[0]
        create_cycle(cycle_label="C2", period_start="2026-09-16T00:00:00Z",
                     period_end="2026-11-01T00:00:00Z")
        # C2's evaluation needs the clock at or past its period_end; the
        # plan's due date (2026-09-20 + 60 days) is past by then.
        c2 = [c for c in get_success_data(
            api.list_fraud_program_cycles(FA)) if c["cycle_label"] == "C2"][0]
        set_clock("2026-11-20T00:00:00Z")
        evaluate_cycle(c2["id"])
        return acquirer, participant, merchant, plan

    def test_remediation_overdue_sweep_at_next_evaluation(self, api):
        """PRD §3.8: "Third, evaluation sweeps: every `RemediationPlan` from
        any prior cycle still in `OPEN` or `SUBMITTED` whose `due_at` is now
        in the past transitions to `OVERDUE`."

        Design: Corner/state_machines/remediation_overdue_sweep_at_next_evaluation
        """
        acquirer = create_active_member(legal_name="A Bank",
                                        member_kind="ACQUIRER", region="NA")
        issuer = create_active_member(legal_name="I Bank", member_kind="ISSUER",
                                      region="NA")
        merchant = _mk_merchant(api, acquirer["id"], 10000000)
        # 100000 * 10000 / 10000000 = 100 bps: exactly at the merchant
        # threshold, so the first evaluation flags it with a plan.
        create_confirmed_fraud_case(merchant["id"], issuer["id"], 100000)
        c1 = create_cycle(cycle_label="C1")
        set_clock("2026-09-20T00:00:00Z")
        evaluate_cycle(c1["id"])
        plans = list_cycle_plans(c1["id"])
        assert len(plans) >= 1, \
            "setup expects at least one remediation plan from the first cycle"
        plan = plans[0]
        before = get_success_data(api.get_remediation_plan(plan["id"], FA))
        assert before["status"] == "OPEN", \
            "the clock alone must not move the plan out of OPEN"

        c2 = create_cycle(cycle_label="C2",
                          period_start="2026-09-16T00:00:00Z",
                          period_end="2026-11-01T00:00:00Z")
        set_clock("2026-11-25T00:00:00Z")
        evaluate_cycle(c2["id"])
        after = get_success_data(api.get_remediation_plan(plan["id"], FA))
        assert after["status"] == "OVERDUE", \
            "the next cycle's evaluation sweep moves the past-due plan to OVERDUE"

    def test_fraud_escalation_suspends_acquirer_with_cascade(self, api):
        """PRD §3.8: "Escalation is reserved for plans already `OVERDUE`: it
        moves the plan to the terminal `ESCALATED` state, and when the subject
        is an `ACQUIRER`, the subject member itself transitions from `ACTIVE`
        to `SUSPENDED` with `suspension_reason` set to
        `FRAUD_REMEDIATION_ESCALATION` — firing the full member suspension
        cascade of §2.8, participants and merchants and BIN ranges included."

        Design: Difficulty/transitive_cascade/fraud_escalation_suspends_acquirer_depth2
        """
        acquirer, participant, merchant, plan = \
            self._setup_overdue_acquirer_plan(api)
        plan_now = get_success_data(api.get_remediation_plan(plan["id"], FA))
        assert plan_now["status"] == "OVERDUE"

        res = api.escalate_remediation_plan(plan["id"], FA)
        data = validate_success(res)
        assert data["status"] == "ESCALATED"

        member_now = get_success_data(api.get_member(acquirer["id"], OP))
        assert member_now["status"] == "SUSPENDED"
        assert member_now["suspension_reason"] == "FRAUD_REMEDIATION_ESCALATION"
        participant_now = get_success_data(
            api.get_participant(participant["id"], FA))
        assert participant_now["status"] == "SUSPENDED", \
            "participant suspension is hop 2, caused by the member transition"
        merchant_now = get_success_data(api.get_merchant(merchant["id"], FA))
        assert merchant_now["status"] == "SUSPENDED", \
            "merchant suspension is hop 3 of the escalation chain"

    def test_fraud_escalation_suspends_only_acquirer_subject(self, api):
        """PRD §3.8: "when the subject is an `ACQUIRER`, the subject member
        itself transitions from `ACTIVE` to `SUSPENDED`".

        Design: Difficulty/transitive_cascade/fraud_escalation_suspends_acquirer_depth2
        """
        # A MERCHANT-subject plan: escalating it must NOT suspend the member.
        acquirer = create_active_member(legal_name="Acq Bank",
                                        member_kind="ACQUIRER", region="NA")
        issuer = create_active_member(legal_name="Iss Bank",
                                      member_kind="ISSUER", region="NA")
        merchant = _mk_merchant(api, acquirer["id"], 1000000)
        create_confirmed_fraud_case(merchant["id"], issuer["id"], 10000)
        c1 = create_cycle(cycle_label="C1")
        set_clock("2026-09-20T00:00:00Z")
        evaluate_cycle(c1["id"])
        merchant_plans = [p for p in list_cycle_plans(c1["id"])
                          if p["subject_type"] == "MERCHANT"]
        assert len(merchant_plans) == 1
        plan = merchant_plans[0]
        c2 = create_cycle(cycle_label="C2",
                          period_start="2026-09-16T00:00:00Z",
                          period_end="2026-11-01T00:00:00Z")
        set_clock("2026-11-20T00:00:00Z")
        evaluate_cycle(c2["id"])
        validate_success(api.escalate_remediation_plan(plan["id"], FA))
        member_now = get_success_data(api.get_member(acquirer["id"], OP))
        assert member_now["status"] == "ACTIVE", \
            "escalating a MERCHANT-subject plan must not suspend the acquirer"

    def test_segregation_submit_approve_same_user_denied(self, api):
        """PRD §3.8: "Approval moves it from `SUBMITTED` to `APPROVED`,
        records the approver in `approved_by_id`, enforces segregation of
        duties (the approver must differ from the submitter, else
        `ERR_SEGREGATION_OF_DUTIES`)".

        Design: Corner/rbac/segregation_submit_approve_same_user_denied
        """
        acquirer = create_active_member(legal_name="A Bank",
                                        member_kind="ACQUIRER", region="NA")
        issuer = create_active_member(legal_name="I Bank", member_kind="ISSUER",
                                      region="NA")
        merchant = _mk_merchant(api, acquirer["id"], 10000000)
        # 100000 * 10000 / 10000000 = 100 bps: exactly at the merchant
        # threshold, so evaluation flags it with a plan.
        create_confirmed_fraud_case(merchant["id"], issuer["id"], 100000)
        cycle = create_cycle(cycle_label="CS")
        set_clock("2026-09-20T00:00:00Z")
        evaluate_cycle(cycle["id"])
        plan = list_cycle_plans(cycle["id"])[0]
        validate_success(api.submit_remediation_plan(
            plan["id"], make_fraud_analyst_headers("fa-1")))

        res = api.approve_remediation_plan(
            plan["id"], make_fraud_analyst_headers("fa-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        res = api.approve_remediation_plan(
            plan["id"], make_fraud_analyst_headers("fa-2"))
        data = validate_success(res)
        assert data["status"] == "APPROVED"
