"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/toll/_clock/set_current_utc", payload, headers)

    def advance_day(self, payload, headers):
        return self._request("POST", "/toll/_clock/advance_day", payload, headers)

    # --- Agency ---
    def create_agency(self, payload, headers):
        return self._request("POST", "/toll/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/toll/agencies/{agency_id}", headers=headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/toll/agencies", headers=headers, params=params)

    def suspend_agency(self, agency_id, headers):
        return self._request("POST", f"/toll/agencies/{agency_id}/suspend", headers=headers)

    def reactivate_agency(self, agency_id, headers):
        return self._request("POST", f"/toll/agencies/{agency_id}/reactivate", headers=headers)

    # --- RateSchedule ---
    def create_rate_schedule(self, agency_id, payload, headers):
        return self._request("POST", f"/toll/agencies/{agency_id}/rate-schedules", payload, headers)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/toll/rate-schedules/{schedule_id}", headers=headers)

    def list_agency_rate_schedules(self, agency_id, headers, params=None):
        return self._request("GET", f"/toll/agencies/{agency_id}/rate-schedules", headers=headers, params=params)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/toll/rate-schedules", headers=headers, params=params)

    # --- DiscountPlan ---
    def create_discount_plan(self, agency_id, payload, headers):
        return self._request("POST", f"/toll/agencies/{agency_id}/discount-plans", payload, headers)

    def get_discount_plan(self, plan_id, headers):
        return self._request("GET", f"/toll/discount-plans/{plan_id}", headers=headers)

    def list_agency_discount_plans(self, agency_id, headers, params=None):
        return self._request("GET", f"/toll/agencies/{agency_id}/discount-plans", headers=headers, params=params)

    def list_discount_plans(self, headers, params=None):
        return self._request("GET", "/toll/discount-plans", headers=headers, params=params)

    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/toll/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/toll/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/toll/accounts", headers=headers, params=params)

    def create_replenishment(self, account_id, payload, headers):
        return self._request("POST", f"/toll/accounts/{account_id}/replenishments", payload, headers)

    def create_adjustment(self, account_id, payload, headers):
        return self._request("POST", f"/toll/accounts/{account_id}/adjustments", payload, headers)

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/toll/accounts/{account_id}/reinstate", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/toll/accounts/{account_id}/close", headers=headers)

    # --- Transponder ---
    def create_transponder(self, account_id, payload, headers):
        return self._request("POST", f"/toll/accounts/{account_id}/transponders", payload, headers)

    def get_transponder(self, transponder_id, headers):
        return self._request("GET", f"/toll/transponders/{transponder_id}", headers=headers)

    def list_account_transponders(self, account_id, headers, params=None):
        return self._request("GET", f"/toll/accounts/{account_id}/transponders", headers=headers, params=params)

    def list_transponders(self, headers, params=None):
        return self._request("GET", "/toll/transponders", headers=headers, params=params)

    def report_lost(self, transponder_id, headers):
        return self._request("POST", f"/toll/transponders/{transponder_id}/report_lost", headers=headers)

    def report_found(self, transponder_id, headers):
        return self._request("POST", f"/toll/transponders/{transponder_id}/report_found", headers=headers)

    def retire_transponder(self, transponder_id, headers):
        return self._request("POST", f"/toll/transponders/{transponder_id}/retire", headers=headers)

    # --- TollTransaction ---
    def post_toll_transaction(self, payload, headers):
        return self._request("POST", "/toll/toll-transactions", payload, headers)

    def get_toll_transaction(self, transaction_id, headers):
        return self._request("GET", f"/toll/toll-transactions/{transaction_id}", headers=headers)

    def list_toll_transactions(self, headers, params=None):
        return self._request("GET", "/toll/toll-transactions", headers=headers, params=params)

    def void_toll_transaction(self, transaction_id, headers):
        return self._request("POST", f"/toll/toll-transactions/{transaction_id}/void", headers=headers)

    # --- ImageBill ---
    def get_image_bill(self, image_bill_id, headers):
        return self._request("GET", f"/toll/image-bills/{image_bill_id}", headers=headers)

    def list_image_bills(self, headers, params=None):
        return self._request("GET", "/toll/image-bills", headers=headers, params=params)

    def resolve_image_bill(self, image_bill_id, payload, headers):
        return self._request("POST", f"/toll/image-bills/{image_bill_id}/resolve", payload, headers)

    def void_image_bill(self, image_bill_id, headers):
        return self._request("POST", f"/toll/image-bills/{image_bill_id}/void", headers=headers)

    # --- Violation ---
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/toll/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/toll/violations", headers=headers, params=params)

    def issue_notice(self, violation_id, headers):
        return self._request("POST", f"/toll/violations/{violation_id}/issue_notice", headers=headers)

    def pay_violation(self, violation_id, headers):
        return self._request("POST", f"/toll/violations/{violation_id}/pay", headers=headers)

    def dismiss_violation(self, violation_id, headers):
        return self._request("POST", f"/toll/violations/{violation_id}/dismiss", headers=headers)

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/toll/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/toll/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/toll/disputes", headers=headers, params=params)

    def begin_review_dispute(self, dispute_id, headers):
        return self._request("POST", f"/toll/disputes/{dispute_id}/begin_review", headers=headers)

    def uphold_dispute(self, dispute_id, headers):
        return self._request("POST", f"/toll/disputes/{dispute_id}/uphold", headers=headers)

    def reject_dispute(self, dispute_id, headers):
        return self._request("POST", f"/toll/disputes/{dispute_id}/reject", headers=headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/toll/disputes/{dispute_id}/withdraw", headers=headers)

    # --- SettlementFile ---
    def generate_settlement_file(self, payload, headers):
        return self._request("POST", "/toll/settlement-files/generate", payload, headers)

    def get_settlement_file(self, settlement_file_id, headers):
        return self._request("GET", f"/toll/settlement-files/{settlement_file_id}", headers=headers)

    def list_settlement_files(self, headers, params=None):
        return self._request("GET", "/toll/settlement-files", headers=headers, params=params)

    def transmit_settlement_file(self, settlement_file_id, headers):
        return self._request("POST", f"/toll/settlement-files/{settlement_file_id}/transmit", headers=headers)

    def acknowledge_settlement_file(self, settlement_file_id, headers):
        return self._request("POST", f"/toll/settlement-files/{settlement_file_id}/acknowledge", headers=headers)

    def flag_settlement_exception(self, settlement_file_id, payload, headers):
        return self._request("POST", f"/toll/settlement-files/{settlement_file_id}/flag_exception", payload, headers)

    def resolve_settlement_exceptions(self, settlement_file_id, headers):
        return self._request("POST", f"/toll/settlement-files/{settlement_file_id}/resolve_exceptions", headers=headers)

    def reconcile_settlement_file(self, settlement_file_id, headers):
        return self._request("POST", f"/toll/settlement-files/{settlement_file_id}/reconcile", headers=headers)

    # --- PlateDataAgreement ---
    def create_plate_data_agreement(self, payload, headers):
        return self._request("POST", "/toll/plate-data-agreements", payload, headers)

    def get_plate_data_agreement(self, agreement_id, headers):
        return self._request("GET", f"/toll/plate-data-agreements/{agreement_id}", headers=headers)

    def list_plate_data_agreements(self, headers, params=None):
        return self._request("GET", "/toll/plate-data-agreements", headers=headers, params=params)

    def revoke_plate_data_agreement(self, agreement_id, headers):
        return self._request("POST", f"/toll/plate-data-agreements/{agreement_id}/revoke", headers=headers)


api_client = ApiClient()
