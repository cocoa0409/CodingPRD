"""API client: one method per endpoint in the PRD's endpoint table (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ──────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/network/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Members ────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/network/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/network/members", headers=headers,
                             params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/network/members/{member_id}",
                             headers=headers)

    def approve_member(self, member_id, headers):
        return self._request("POST", f"/network/members/{member_id}/approve",
                             {}, headers)

    def suspend_member(self, member_id, payload, headers):
        return self._request("POST", f"/network/members/{member_id}/suspend",
                             payload, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/network/members/{member_id}/reinstate",
                             {}, headers)

    def terminate_member(self, member_id, headers):
        return self._request("POST", f"/network/members/{member_id}/terminate",
                             {}, headers)

    def list_member_participants(self, member_id, headers, params=None):
        return self._request("GET", f"/network/members/{member_id}/participants",
                             headers=headers, params=params)

    def list_member_bin_ranges(self, member_id, headers, params=None):
        return self._request("GET", f"/network/members/{member_id}/bin-ranges",
                             headers=headers, params=params)

    def list_member_programs(self, member_id, headers, params=None):
        return self._request("GET", f"/network/members/{member_id}/programs",
                             headers=headers, params=params)

    # ─── Participants ───────────────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/network/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/network/participants", headers=headers,
                             params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/network/participants/{participant_id}",
                             headers=headers)

    def approve_participant(self, participant_id, headers):
        return self._request("POST",
                             f"/network/participants/{participant_id}/approve",
                             {}, headers)

    def suspend_participant(self, participant_id, headers):
        return self._request("POST",
                             f"/network/participants/{participant_id}/suspend",
                             {}, headers)

    def reinstate_participant(self, participant_id, headers):
        return self._request("POST",
                             f"/network/participants/{participant_id}/reinstate",
                             {}, headers)

    def terminate_participant(self, participant_id, headers):
        return self._request("POST",
                             f"/network/participants/{participant_id}/terminate",
                             {}, headers)

    def list_participant_merchants(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/network/participants/{participant_id}/merchants",
            headers=headers, params=params)

    # ─── Merchants ──────────────────────────────────────
    def create_merchant(self, payload, headers):
        return self._request("POST", "/network/merchants", payload, headers)

    def list_merchants(self, headers, params=None):
        return self._request("GET", "/network/merchants", headers=headers,
                             params=params)

    def get_merchant(self, merchant_id, headers):
        return self._request("GET", f"/network/merchants/{merchant_id}",
                             headers=headers)

    # ─── BIN ranges ─────────────────────────────────────
    def create_bin_range(self, payload, headers):
        return self._request("POST", "/network/bin-ranges", payload, headers)

    def list_bin_ranges(self, headers, params=None):
        return self._request("GET", "/network/bin-ranges", headers=headers,
                             params=params)

    def get_bin_range(self, bin_range_id, headers):
        return self._request("GET", f"/network/bin-ranges/{bin_range_id}",
                             headers=headers)

    def approve_bin_range(self, bin_range_id, payload, headers):
        return self._request("POST",
                             f"/network/bin-ranges/{bin_range_id}/approve",
                             payload, headers)

    def deactivate_bin_range(self, bin_range_id, headers):
        return self._request("POST",
                             f"/network/bin-ranges/{bin_range_id}/deactivate",
                             {}, headers)

    # ─── Programs ───────────────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/network/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/network/programs", headers=headers,
                             params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/network/programs/{program_id}",
                             headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/network/programs/{program_id}",
                             payload, headers)

    def create_certification_test(self, program_id, payload, headers):
        return self._request(
            "POST", f"/network/programs/{program_id}/certification-tests",
            payload, headers)

    def approve_program(self, program_id, payload, headers):
        return self._request("POST",
                             f"/network/programs/{program_id}/approve",
                             payload, headers)

    def enable_program_production(self, program_id, headers):
        return self._request("POST",
                             f"/network/programs/{program_id}/enable-production",
                             {}, headers)

    def retire_program(self, program_id, headers):
        return self._request("POST", f"/network/programs/{program_id}/retire",
                             {}, headers)

    # ─── Certification tests ────────────────────────────
    def list_certification_tests(self, headers, params=None):
        return self._request("GET", "/network/certification-tests",
                             headers=headers, params=params)

    def get_certification_test(self, test_id, headers):
        return self._request("GET", f"/network/certification-tests/{test_id}",
                             headers=headers)

    def pass_certification_test(self, test_id, headers):
        return self._request("POST",
                             f"/network/certification-tests/{test_id}/pass",
                             {}, headers)

    def fail_certification_test(self, test_id, payload, headers):
        return self._request("POST",
                             f"/network/certification-tests/{test_id}/fail",
                             payload, headers)

    # ─── Network rules ──────────────────────────────────
    def create_rule(self, payload, headers):
        return self._request("POST", "/network/rules", payload, headers)

    def list_rules(self, headers, params=None):
        return self._request("GET", "/network/rules", headers=headers,
                             params=params)

    def get_rule(self, rule_id, headers):
        return self._request("GET", f"/network/rules/{rule_id}", headers=headers)

    def publish_rule(self, rule_id, headers):
        return self._request("POST", f"/network/rules/{rule_id}/publish",
                             {}, headers)

    def retire_rule(self, rule_id, headers):
        return self._request("POST", f"/network/rules/{rule_id}/retire",
                             {}, headers)

    # ─── Rule violations ────────────────────────────────
    def create_rule_violation(self, payload, headers):
        return self._request("POST", "/network/rule-violations", payload,
                             headers)

    def list_rule_violations(self, headers, params=None):
        return self._request("GET", "/network/rule-violations", headers=headers,
                             params=params)

    def get_rule_violation(self, violation_id, headers):
        return self._request("GET", f"/network/rule-violations/{violation_id}",
                             headers=headers)

    def assess_rule_violation(self, violation_id, headers):
        return self._request("POST",
                             f"/network/rule-violations/{violation_id}/assess",
                             {}, headers)

    def appeal_rule_violation(self, violation_id, headers):
        return self._request("POST",
                             f"/network/rule-violations/{violation_id}/appeal",
                             {}, headers)

    def confirm_rule_violation(self, violation_id, headers):
        return self._request("POST",
                             f"/network/rule-violations/{violation_id}/confirm",
                             {}, headers)

    def waive_rule_violation(self, violation_id, headers):
        return self._request("POST",
                             f"/network/rule-violations/{violation_id}/waive",
                             {}, headers)

    # ─── Disputes & evidence ────────────────────────────
    def create_dispute(self, payload, headers):
        return self._request("POST", "/network/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/network/disputes", headers=headers,
                             params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/network/disputes/{dispute_id}",
                             headers=headers)

    def submit_evidence(self, dispute_id, payload, headers):
        return self._request("POST", f"/network/disputes/{dispute_id}/evidence",
                             payload, headers)

    def list_dispute_evidence(self, dispute_id, headers, params=None):
        return self._request("GET",
                             f"/network/disputes/{dispute_id}/evidence-list",
                             headers=headers, params=params)

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/network/disputes/{dispute_id}/decide",
                             payload, headers)

    def request_arbitration(self, dispute_id, headers):
        return self._request("POST",
                             f"/network/disputes/{dispute_id}/request-arbitration",
                             {}, headers)

    def arbitrate_dispute(self, dispute_id, payload, headers):
        return self._request("POST",
                             f"/network/disputes/{dispute_id}/arbitrate",
                             payload, headers)

    def close_dispute(self, dispute_id, headers):
        return self._request("POST", f"/network/disputes/{dispute_id}/close",
                             {}, headers)

    def list_evidence(self, headers, params=None):
        return self._request("GET", "/network/evidence", headers=headers,
                             params=params)

    def get_evidence(self, evidence_id, headers):
        return self._request("GET", f"/network/evidence/{evidence_id}",
                             headers=headers)

    # ─── Interchange rates ──────────────────────────────
    def create_interchange_rate(self, payload, headers):
        return self._request("POST", "/network/interchange-rates", payload,
                             headers)

    def list_interchange_rates(self, headers, params=None):
        return self._request("GET", "/network/interchange-rates",
                             headers=headers, params=params)

    def get_interchange_rate(self, rate_id, headers):
        return self._request("GET", f"/network/interchange-rates/{rate_id}",
                             headers=headers)

    def publish_interchange_rate(self, rate_id, headers):
        return self._request("POST",
                             f"/network/interchange-rates/{rate_id}/publish",
                             {}, headers)

    def retire_interchange_rate(self, rate_id, headers):
        return self._request("POST",
                             f"/network/interchange-rates/{rate_id}/retire",
                             {}, headers)

    def quote_interchange(self, payload, headers):
        return self._request("POST", "/network/interchange-rates/quote",
                             payload, headers)

    # ─── Fraud cases ────────────────────────────────────
    def create_fraud_case(self, payload, headers):
        return self._request("POST", "/network/fraud-cases", payload, headers)

    def list_fraud_cases(self, headers, params=None):
        return self._request("GET", "/network/fraud-cases", headers=headers,
                             params=params)

    def get_fraud_case(self, fraud_case_id, headers):
        return self._request("GET", f"/network/fraud-cases/{fraud_case_id}",
                             headers=headers)

    def confirm_fraud_case(self, fraud_case_id, headers):
        return self._request("POST",
                             f"/network/fraud-cases/{fraud_case_id}/confirm",
                             {}, headers)

    def dismiss_fraud_case(self, fraud_case_id, headers):
        return self._request("POST",
                             f"/network/fraud-cases/{fraud_case_id}/dismiss",
                             {}, headers)

    # ─── Fraud program cycles ───────────────────────────
    def create_fraud_program_cycle(self, payload, headers):
        return self._request("POST", "/network/fraud-program-cycles", payload,
                             headers)

    def list_fraud_program_cycles(self, headers, params=None):
        return self._request("GET", "/network/fraud-program-cycles",
                             headers=headers, params=params)

    def get_fraud_program_cycle(self, cycle_id, headers):
        return self._request("GET", f"/network/fraud-program-cycles/{cycle_id}",
                             headers=headers)

    def evaluate_fraud_program_cycle(self, cycle_id, headers):
        return self._request("POST",
                             f"/network/fraud-program-cycles/{cycle_id}/evaluate",
                             {}, headers)

    def list_cycle_remediation_plans(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/network/fraud-program-cycles/{cycle_id}/remediation-plans",
            headers=headers, params=params)

    # ─── Remediation plans ──────────────────────────────
    def list_remediation_plans(self, headers, params=None):
        return self._request("GET", "/network/remediation-plans",
                             headers=headers, params=params)

    def get_remediation_plan(self, plan_id, headers):
        return self._request("GET", f"/network/remediation-plans/{plan_id}",
                             headers=headers)

    def submit_remediation_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/network/remediation-plans/{plan_id}/submit",
                             {}, headers)

    def approve_remediation_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/network/remediation-plans/{plan_id}/approve",
                             {}, headers)

    def complete_remediation_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/network/remediation-plans/{plan_id}/complete",
                             {}, headers)

    def escalate_remediation_plan(self, plan_id, headers):
        return self._request("POST",
                             f"/network/remediation-plans/{plan_id}/escalate",
                             {}, headers)

    # ─── Settlement windows ─────────────────────────────
    def create_settlement_window(self, payload, headers):
        return self._request("POST", "/network/settlement-windows", payload,
                             headers)

    def list_settlement_windows(self, headers, params=None):
        return self._request("GET", "/network/settlement-windows",
                             headers=headers, params=params)

    def get_settlement_window(self, window_id, headers):
        return self._request("GET", f"/network/settlement-windows/{window_id}",
                             headers=headers)

    def open_settlement_window(self, window_id, headers):
        return self._request("POST",
                             f"/network/settlement-windows/{window_id}/open",
                             {}, headers)

    def reconcile_settlement_window(self, window_id, headers):
        return self._request("POST",
                             f"/network/settlement-windows/{window_id}/reconcile",
                             {}, headers)

    def close_settlement_window(self, window_id, headers):
        return self._request("POST",
                             f"/network/settlement-windows/{window_id}/close",
                             {}, headers)

    def list_window_lines(self, window_id, headers, params=None):
        return self._request("GET",
                             f"/network/settlement-windows/{window_id}/lines",
                             headers=headers, params=params)

    def get_window_positions(self, window_id, headers):
        return self._request("GET",
                             f"/network/settlement-windows/{window_id}/positions",
                             headers=headers)

    # ─── Settlement lines ───────────────────────────────
    def create_settlement_line(self, payload, headers):
        return self._request("POST", "/network/settlement-lines", payload,
                             headers)

    def list_settlement_lines(self, headers, params=None):
        return self._request("GET", "/network/settlement-lines",
                             headers=headers, params=params)

    def get_settlement_line(self, line_id, headers):
        return self._request("GET", f"/network/settlement-lines/{line_id}",
                             headers=headers)

    def commit_settlement_line(self, line_id, headers):
        return self._request("POST",
                             f"/network/settlement-lines/{line_id}/commit",
                             {}, headers)

    def reverse_settlement_line(self, line_id, headers):
        return self._request("POST",
                             f"/network/settlement-lines/{line_id}/reverse",
                             {}, headers)


api_client = ApiClient()
