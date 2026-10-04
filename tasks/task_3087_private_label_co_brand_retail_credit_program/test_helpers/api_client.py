"""API client: one method per endpoint declared in the PRD (PRD §4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/servicing"


class ApiClient(GenericApiClient):
    # --- clock ------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def advance_clock(self, days, headers):
        return self._request("POST", f"{PREFIX}/_clock/advance",
                             {"days": days}, headers)

    # --- RetailPartner ----------------------------------------------------
    def create_partner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/partners", payload, headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/partners", headers=headers, params=params)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"{PREFIX}/partners/{partner_id}", headers=headers)

    def suspend_partner(self, partner_id, headers):
        return self._request("POST", f"{PREFIX}/partners/{partner_id}/suspend", {}, headers)

    def reinstate_partner(self, partner_id, headers):
        return self._request("POST", f"{PREFIX}/partners/{partner_id}/reinstate", {}, headers)

    def offboard_partner(self, partner_id, headers):
        return self._request("POST", f"{PREFIX}/partners/{partner_id}/offboard", {}, headers)

    def list_partner_credit_programs(self, partner_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/partners/{partner_id}/credit-programs",
                             headers=headers, params=params)

    # --- ProgramAgreement -------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def open_negotiation(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/open-negotiation",
                             {}, headers)

    def execute_agreement(self, agreement_id, expected_agreement_version, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/execute",
                             {"expected_agreement_version": expected_agreement_version}, headers)

    def reinstate_agreement(self, agreement_id, expected_agreement_version, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/reinstate",
                             {"expected_agreement_version": expected_agreement_version}, headers)

    def terminate_agreement(self, agreement_id, expected_agreement_version, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/terminate",
                             {"expected_agreement_version": expected_agreement_version}, headers)

    # --- CreditProgram ----------------------------------------------------
    def create_credit_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/credit-programs", payload, headers)

    def list_credit_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/credit-programs", headers=headers, params=params)

    def get_credit_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/credit-programs/{program_id}", headers=headers)

    def open_renewal(self, program_id, expected_program_version, to_status, headers):
        return self._request("POST", f"{PREFIX}/credit-programs/{program_id}/open-renewal",
                             {"expected_program_version": expected_program_version,
                              "to_status": to_status}, headers)

    def complete_renewal(self, program_id, expected_program_version, headers):
        return self._request("POST", f"{PREFIX}/credit-programs/{program_id}/complete-renewal",
                             {"expected_program_version": expected_program_version}, headers)

    def close_credit_program(self, program_id, expected_program_version, headers):
        return self._request("POST", f"{PREFIX}/credit-programs/{program_id}/close",
                             {"expected_program_version": expected_program_version}, headers)

    def get_program_summary(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/credit-programs/{program_id}/summary",
                             headers=headers)

    # --- Application ------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/applications/{application_id}", headers=headers)

    def decide_application(self, application_id, headers):
        return self._request("POST", f"{PREFIX}/applications/{application_id}/decide",
                             {}, headers)

    # --- Transaction ------------------------------------------------------
    def create_transaction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"{PREFIX}/transactions/{transaction_id}", headers=headers)

    # --- Account ----------------------------------------------------------
    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def post_payment(self, account_id, payment_amount_cents, headers):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/post-payment",
                             {"payment_amount_cents": payment_amount_cents}, headers)

    def schedule_payment(self, account_id, due_date, headers):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/schedule-payment",
                             {"due_date": due_date}, headers)

    def charge_off(self, account_id, headers):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/charge-off", {}, headers)

    def create_balance(self, account_id, principal_balance_cents, balance_bucket, headers):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/balances",
                             {"principal_balance_cents": principal_balance_cents,
                              "balance_bucket": balance_bucket}, headers)

    def list_account_balances(self, account_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}/balances",
                             headers=headers, params=params)

    def list_balances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/balances", headers=headers, params=params)

    def get_account_loyalty(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}/loyalty",
                             headers=headers)

    # --- PromoPlan --------------------------------------------------------
    def list_promo_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/promo-plans", headers=headers, params=params)

    def get_promo_plan(self, promo_plan_id, headers):
        return self._request("GET", f"{PREFIX}/promo-plans/{promo_plan_id}", headers=headers)

    def expire_promo_plan(self, promo_plan_id, headers):
        return self._request("POST", f"{PREFIX}/promo-plans/{promo_plan_id}/expire", {}, headers)

    def reopen_promo_plan(self, promo_plan_id, headers):
        return self._request("POST", f"{PREFIX}/promo-plans/{promo_plan_id}/reopen", {}, headers)

    # --- SettlementBatch --------------------------------------------------
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-batches", payload, headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/settlement-batches", headers=headers, params=params)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/settlement-batches/{batch_id}", headers=headers)

    def finalize_settlement_batch(self, batch_id, headers):
        return self._request("POST", f"{PREFIX}/settlement-batches/{batch_id}/finalize",
                             {}, headers)

    # --- DisputeCase ------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{PREFIX}/disputes/{dispute_id}", headers=headers)

    def review_dispute(self, dispute_id, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/review", {}, headers)

    def resolve_dispute(self, dispute_id, resolution_outcome, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/resolve",
                             {"resolution_outcome": resolution_outcome}, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/withdraw", {}, headers)

    # --- BenefitPosting ---------------------------------------------------
    def create_benefit_posting(self, payload, headers):
        return self._request("POST", f"{PREFIX}/benefit-postings", payload, headers)

    def list_benefit_postings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/benefit-postings", headers=headers, params=params)

    def get_benefit_posting(self, posting_id, headers):
        return self._request("GET", f"{PREFIX}/benefit-postings/{posting_id}", headers=headers)

    # --- WindDownTransfer -------------------------------------------------
    def create_transfer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfer-agreements", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transfer-agreements", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"{PREFIX}/transfer-agreements/{transfer_id}", headers=headers)

    def accept_transfer(self, transfer_id, accepted_by_role, headers):
        return self._request("POST", f"{PREFIX}/transfer-agreements/{transfer_id}/accept",
                             {"accepted_by_role": accepted_by_role}, headers)

    def execute_transfer(self, transfer_id, headers):
        return self._request("POST", f"{PREFIX}/transfer-agreements/{transfer_id}/execute",
                             {}, headers)

    def withdraw_transfer(self, transfer_id, headers):
        return self._request("POST", f"{PREFIX}/transfer-agreements/{transfer_id}/withdraw",
                             {}, headers)


api_client = ApiClient()


def _optional_params(**kwargs) -> Optional[dict]:
    """Drop keys whose value is None so query strings stay clean."""
    return {k: v for k, v in kwargs.items() if v is not None} or None