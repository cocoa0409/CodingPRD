"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock and reconciliation sweep ----
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers,
        )

    def run_sweep(self, headers):
        return self._request("POST", "/_ops/run_sweep", {}, headers)

    # ---- brands ----
    def create_brand(self, payload, headers):
        return self._request("POST", "/franchise/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/franchise/brands/{brand_id}", headers=headers)

    def list_brands(self, headers, params=None):
        return self._request("GET", "/franchise/brands", headers=headers, params=params)

    # ---- franchisees ----
    def create_franchisee(self, payload, headers):
        return self._request("POST", "/franchise/franchisees", payload, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request(
            "GET", f"/franchise/franchisees/{franchisee_id}", headers=headers,
        )

    def list_franchisees(self, headers, params=None):
        return self._request(
            "GET", "/franchise/franchisees", headers=headers, params=params,
        )

    def suspend_franchisee(self, franchisee_id, reason, headers):
        return self._request(
            "POST", f"/franchise/franchisees/{franchisee_id}/suspend",
            {"reason": reason}, headers,
        )

    # ---- territories ----
    def create_territory(self, payload, headers):
        return self._request("POST", "/franchise/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request(
            "GET", f"/franchise/territories/{territory_id}", headers=headers,
        )

    def list_territories(self, headers, params=None):
        return self._request(
            "GET", "/franchise/territories", headers=headers, params=params,
        )

    def offer_territory(self, territory_id, franchisee_id, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/offer",
            {"franchisee_id": franchisee_id}, headers,
        )

    def award_territory(self, territory_id, expected_territory_version, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/award",
            {"expected_territory_version": expected_territory_version}, headers,
        )

    def request_expansion(self, territory_id, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/request-expansion",
            {}, headers,
        )

    def withdraw_expansion(self, territory_id, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/withdraw-expansion",
            {}, headers,
        )

    def reallocate_territory(self, territory_id, target_territory_ids, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/reallocate",
            {"target_territory_ids": target_territory_ids}, headers,
        )

    def reclaim_territory(self, territory_id, headers):
        return self._request(
            "POST", f"/franchise/territories/{territory_id}/reclaim", {}, headers,
        )

    # ---- agreements ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/franchise/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/franchise/agreements/{agreement_id}", headers=headers,
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", "/franchise/agreements", headers=headers, params=params,
        )

    def offer_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/offer", {}, headers,
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/activate", {}, headers,
        )

    def renew_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/renew", {}, headers,
        )

    def activate_renewal(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/activate-renewal",
            {}, headers,
        )

    def suspend_agreement(self, agreement_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/suspend", payload, headers,
        )

    def reinstate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/reinstate", {}, headers,
        )

    def expire_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/franchise/agreements/{agreement_id}/expire", {}, headers,
        )

    # ---- transfer applications ----
    def create_transfer_application(self, payload, headers):
        return self._request(
            "POST", "/franchise/transfer-applications", payload, headers,
        )

    def get_transfer_application(self, application_id, headers):
        return self._request(
            "GET", f"/franchise/transfer-applications/{application_id}",
            headers=headers,
        )

    def list_transfer_applications(self, headers, params=None):
        return self._request(
            "GET", "/franchise/transfer-applications",
            headers=headers, params=params,
        )

    def begin_review(self, application_id, reviewer_operator_id, headers):
        return self._request(
            "POST", f"/franchise/transfer-applications/{application_id}/begin-review",
            {"reviewer_operator_id": reviewer_operator_id}, headers,
        )

    def request_revision(self, application_id, reason, headers):
        return self._request(
            "POST",
            f"/franchise/transfer-applications/{application_id}/request-revision",
            {"reason": reason}, headers,
        )

    def revise_transfer(self, application_id, purchase_price_cents, headers):
        return self._request(
            "POST", f"/franchise/transfer-applications/{application_id}/revise",
            {"purchase_price_cents": purchase_price_cents}, headers,
        )

    def approve_transfer(self, application_id, approval_operator_id, headers):
        return self._request(
            "POST", f"/franchise/transfer-applications/{application_id}/approve",
            {"approval_operator_id": approval_operator_id}, headers,
        )

    def reject_transfer(self, application_id, reason, headers):
        return self._request(
            "POST", f"/franchise/transfer-applications/{application_id}/reject",
            {"reason": reason}, headers,
        )

    def close_transfer(self, application_id, headers):
        return self._request(
            "POST", f"/franchise/transfer-applications/{application_id}/close",
            {}, headers,
        )

    def withdraw_transfer(self, application_id, headers):
        return self._request(
            "POST", f"/franchise/transfer-applications/{application_id}/withdraw",
            {}, headers,
        )

    # ---- referrals ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/franchise/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request(
            "GET", f"/franchise/referrals/{referral_id}", headers=headers,
        )

    def list_referrals(self, headers, params=None):
        return self._request(
            "GET", "/franchise/referrals", headers=headers, params=params,
        )

    def accept_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/franchise/referrals/{referral_id}/accept", {}, headers,
        )

    def decline_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/franchise/referrals/{referral_id}/decline", {}, headers,
        )

    def complete_referral(self, referral_id, settled_job_value_cents, headers):
        return self._request(
            "POST", f"/franchise/referrals/{referral_id}/complete",
            {"settled_job_value_cents": settled_job_value_cents}, headers,
        )

    def dispute_referral(self, referral_id, dispute_reason, headers):
        return self._request(
            "POST", f"/franchise/referrals/{referral_id}/dispute",
            {"dispute_reason": dispute_reason}, headers,
        )

    def resolve_referral_dispute(self, referral_id, headers):
        return self._request(
            "POST", f"/franchise/referrals/{referral_id}/resolve-dispute",
            {}, headers,
        )

    def settle_referral(self, referral_id, expected_agreement_version, headers):
        return self._request(
            "POST", f"/franchise/referrals/{referral_id}/settle",
            {"expected_agreement_version": expected_agreement_version}, headers,
        )

    # ---- leads ----
    def create_lead(self, payload, headers):
        return self._request("POST", "/franchise/leads", payload, headers)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/franchise/leads/{lead_id}", headers=headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/franchise/leads", headers=headers, params=params)

    def preview_lead_recipients(self, lead_id, headers):
        return self._request(
            "GET", f"/franchise/leads/{lead_id}/recipients", headers=headers,
        )

    def allocate_lead(self, lead_id, expected_franchisee_version, headers,
                      allocated_agreement_id=None):
        payload = {"expected_franchisee_version": expected_franchisee_version}
        if allocated_agreement_id is not None:
            payload["allocated_agreement_id"] = allocated_agreement_id
        return self._request(
            "POST", f"/franchise/leads/{lead_id}/allocate", payload, headers,
        )

    def release_lead(self, lead_id, headers):
        return self._request(
            "POST", f"/franchise/leads/{lead_id}/release", {}, headers,
        )

    def convert_lead(self, lead_id, headers):
        return self._request(
            "POST", f"/franchise/leads/{lead_id}/convert", {}, headers,
        )

    # ---- national accounts ----
    def create_national_account(self, payload, headers):
        return self._request("POST", "/franchise/national-accounts", payload, headers)

    def get_national_account(self, account_id, headers):
        return self._request(
            "GET", f"/franchise/national-accounts/{account_id}", headers=headers,
        )

    def list_national_accounts(self, headers, params=None):
        return self._request(
            "GET", "/franchise/national-accounts", headers=headers, params=params,
        )

    # ---- work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/franchise/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"/franchise/work-orders/{work_order_id}", headers=headers,
        )

    def list_work_orders(self, headers, params=None):
        return self._request(
            "GET", "/franchise/work-orders", headers=headers, params=params,
        )

    def dispatch_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/franchise/work-orders/{work_order_id}/dispatch", {}, headers,
        )

    def start_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/franchise/work-orders/{work_order_id}/start", {}, headers,
        )

    def complete_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/franchise/work-orders/{work_order_id}/complete", {}, headers,
        )

    def breach_work_order(self, work_order_id, headers):
        return self._request(
            "POST", f"/franchise/work-orders/{work_order_id}/breach", {}, headers,
        )

    # ---- brand standards audits ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/franchise/brand-standards-audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request(
            "GET", f"/franchise/brand-standards-audits/{audit_id}", headers=headers,
        )

    def list_audits(self, headers, params=None):
        return self._request(
            "GET", "/franchise/brand-standards-audits", headers=headers, params=params,
        )

    def conduct_audit(self, audit_id, headers, auditor_operator_id=None):
        payload = {} if auditor_operator_id is None else {
            "auditor_operator_id": auditor_operator_id,
        }
        return self._request(
            "POST", f"/franchise/brand-standards-audits/{audit_id}/conduct",
            payload, headers,
        )

    def publish_audit(self, audit_id, expected_agreement_version, headers):
        return self._request(
            "POST", f"/franchise/brand-standards-audits/{audit_id}/publish",
            {"expected_agreement_version": expected_agreement_version}, headers,
        )

    def reopen_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/franchise/brand-standards-audits/{audit_id}/reopen",
            {}, headers,
        )

    def remediation_transition(self, audit_id, payload, headers):
        return self._request(
            "POST",
            f"/franchise/brand-standards-audits/{audit_id}/remediation-transitions",
            payload, headers,
        )

    # ---- royalty statements ----
    def create_statement(self, payload, headers):
        return self._request("POST", "/franchise/royalty-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/franchise/royalty-statements/{statement_id}", headers=headers,
        )

    def preview_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/franchise/royalty-statements/{statement_id}/preview",
            headers=headers,
        )

    def list_statements(self, headers, params=None):
        return self._request(
            "GET", "/franchise/royalty-statements", headers=headers, params=params,
        )

    def issue_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/franchise/royalty-statements/{statement_id}/issue",
            {}, headers,
        )

    def pay_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/franchise/royalty-statements/{statement_id}/pay", {}, headers,
        )

    def void_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/franchise/royalty-statements/{statement_id}/void", {}, headers,
        )

    # ---- territory assignments ----
    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/franchise/territory-assignments/{assignment_id}",
            headers=headers,
        )

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", "/franchise/territory-assignments",
            headers=headers, params=params,
        )


api_client = ApiClient()