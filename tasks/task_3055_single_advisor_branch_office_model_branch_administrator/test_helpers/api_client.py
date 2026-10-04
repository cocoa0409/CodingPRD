"""API client: one method per endpoint defined in the PRD (all under /branch-office)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Advisors ----
    def create_advisor(self, payload, headers):
        return self._request("POST", "/branch-office/advisors", payload, headers)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/branch-office/advisors/{advisor_id}", headers=headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", "/branch-office/advisors", headers=headers, params=params)

    def list_advisor_goodwill_transfers(self, advisor_id, headers):
        return self._request("GET", f"/branch-office/advisors/{advisor_id}/goodwill-transfers", headers=headers)

    def list_advisor_solicitation_requests(self, advisor_id, headers):
        return self._request("GET", f"/branch-office/advisors/{advisor_id}/solicitation-requests", headers=headers)

    def list_advisor_production_records(self, advisor_id, headers):
        return self._request("GET", f"/branch-office/advisors/{advisor_id}/production-records", headers=headers)

    def enroll_training(self, advisor_id, payload, headers):
        return self._request("POST", f"/branch-office/advisors/{advisor_id}/enroll-training", payload, headers)

    def assign_branch(self, advisor_id, payload, headers):
        return self._request("POST", f"/branch-office/advisors/{advisor_id}/assign-branch", payload, headers)

    def declare_retirement(self, advisor_id, headers):
        return self._request("POST", f"/branch-office/advisors/{advisor_id}/declare-retirement", {}, headers)

    def rescind_retirement(self, advisor_id, headers):
        return self._request("POST", f"/branch-office/advisors/{advisor_id}/rescind-retirement", {}, headers)

    def terminate_advisor(self, advisor_id, headers):
        return self._request("POST", f"/branch-office/advisors/{advisor_id}/terminate", {}, headers)

    # ---- Territories & contacts ----
    def create_territory(self, payload, headers):
        return self._request("POST", "/branch-office/territories", payload, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"/branch-office/territories/{territory_id}", headers=headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", "/branch-office/territories", headers=headers, params=params)

    def assign_territory(self, territory_id, payload, headers):
        return self._request("POST", f"/branch-office/territories/{territory_id}/assign", payload, headers)

    def retire_territory(self, territory_id, headers):
        return self._request("POST", f"/branch-office/territories/{territory_id}/retire", {}, headers)

    def create_contact(self, territory_id, payload, headers):
        return self._request("POST", f"/branch-office/territories/{territory_id}/contacts", payload, headers)

    def list_contacts(self, territory_id, headers, params=None):
        return self._request("GET", f"/branch-office/territories/{territory_id}/contacts", headers=headers, params=params)

    # ---- Branches ----
    def create_branch(self, payload, headers):
        return self._request("POST", "/branch-office/branches", payload, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/branch-office/branches/{branch_id}", headers=headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/branch-office/branches", headers=headers, params=params)

    def patch_branch(self, branch_id, payload, headers):
        return self._request("PATCH", f"/branch-office/branches/{branch_id}", payload, headers)

    def approve_site(self, branch_id, payload, headers):
        return self._request("POST", f"/branch-office/branches/{branch_id}/approve-site", payload, headers)

    def open_branch(self, branch_id, headers):
        return self._request("POST", f"/branch-office/branches/{branch_id}/open", {}, headers)

    def suspend_branch(self, branch_id, headers):
        return self._request("POST", f"/branch-office/branches/{branch_id}/suspend", {}, headers)

    def reinstate_branch(self, branch_id, headers):
        return self._request("POST", f"/branch-office/branches/{branch_id}/reinstate", {}, headers)

    def close_branch(self, branch_id, headers):
        return self._request("POST", f"/branch-office/branches/{branch_id}/close", {}, headers)

    def list_branch_financial_periods(self, branch_id, headers):
        return self._request("GET", f"/branch-office/branches/{branch_id}/financial-periods", headers=headers)

    def list_branch_leases(self, branch_id, headers):
        return self._request("GET", f"/branch-office/branches/{branch_id}/leases", headers=headers)

    def list_branch_administrators(self, branch_id, headers):
        return self._request("GET", f"/branch-office/branches/{branch_id}/administrators", headers=headers)

    def list_branch_goodwill_transfers(self, branch_id, headers):
        return self._request("GET", f"/branch-office/branches/{branch_id}/goodwill-transfers", headers=headers)

    def list_branch_charges(self, branch_id, headers):
        return self._request("GET", f"/branch-office/branches/{branch_id}/charges", headers=headers)

    # ---- Branch office administrators ----
    def create_administrator(self, payload, headers):
        return self._request("POST", "/branch-office/administrators", payload, headers)

    def get_administrator(self, administrator_id, headers):
        return self._request("GET", f"/branch-office/administrators/{administrator_id}", headers=headers)

    def list_administrators(self, headers, params=None):
        return self._request("GET", "/branch-office/administrators", headers=headers, params=params)

    def assign_administrator(self, branch_id, payload, headers):
        return self._request("POST", f"/branch-office/branches/{branch_id}/assign-administrator", payload, headers)

    def place_on_leave(self, administrator_id, headers):
        return self._request("POST", f"/branch-office/administrators/{administrator_id}/place-on-leave", {}, headers)

    def return_from_leave(self, administrator_id, headers):
        return self._request("POST", f"/branch-office/administrators/{administrator_id}/return-from-leave", {}, headers)

    def release_administrator(self, administrator_id, headers):
        return self._request("POST", f"/branch-office/administrators/{administrator_id}/release", {}, headers)

    # ---- Training ----
    def submit_milestone(self, program_id, headers):
        return self._request("POST", f"/branch-office/training-programs/{program_id}/submit-milestone", {}, headers)

    def evaluate_milestone(self, program_id, payload, headers):
        return self._request("POST", f"/branch-office/training-programs/{program_id}/evaluate", payload, headers)

    def get_training_program(self, program_id, headers):
        return self._request("GET", f"/branch-office/training-programs/{program_id}", headers=headers)

    def list_training_programs(self, headers, params=None):
        return self._request("GET", "/branch-office/training-programs", headers=headers, params=params)

    def list_evaluations(self, program_id, headers):
        return self._request("GET", f"/branch-office/training-programs/{program_id}/evaluations", headers=headers)

    # ---- Production ----
    def create_production_record(self, payload, headers):
        return self._request("POST", "/branch-office/production-records", payload, headers)

    def reverse_production_record(self, record_id, headers):
        return self._request("POST", f"/branch-office/production-records/{record_id}/reverse", {}, headers)

    def list_production_records(self, headers, params=None):
        return self._request("GET", "/branch-office/production-records", headers=headers, params=params)

    # ---- Financial periods & charges ----
    def create_financial_period(self, payload, headers):
        return self._request("POST", "/branch-office/financial-periods", payload, headers)

    def get_financial_period(self, period_id, headers):
        return self._request("GET", f"/branch-office/financial-periods/{period_id}", headers=headers)

    def post_charge(self, period_id, payload, headers):
        return self._request("POST", f"/branch-office/financial-periods/{period_id}/charges", payload, headers)

    def reverse_charge(self, charge_id, headers):
        return self._request("POST", f"/branch-office/charges/{charge_id}/reverse", {}, headers)

    def list_period_charges(self, period_id, headers):
        return self._request("GET", f"/branch-office/financial-periods/{period_id}/charges", headers=headers)

    def close_period(self, period_id, headers):
        return self._request("POST", f"/branch-office/financial-periods/{period_id}/close", {}, headers)

    def reopen_period(self, period_id, headers):
        return self._request("POST", f"/branch-office/financial-periods/{period_id}/reopen", {}, headers)

    def finalize_period(self, period_id, headers):
        return self._request("POST", f"/branch-office/financial-periods/{period_id}/finalize", {}, headers)

    # ---- Goodwill transfers ----
    def create_goodwill_transfer(self, payload, headers):
        return self._request("POST", "/branch-office/goodwill-transfers", payload, headers)

    def get_goodwill_transfer(self, transfer_id, headers):
        return self._request("GET", f"/branch-office/goodwill-transfers/{transfer_id}", headers=headers)

    def list_goodwill_transfers(self, headers, params=None):
        return self._request("GET", "/branch-office/goodwill-transfers", headers=headers, params=params)

    def counter_offer(self, transfer_id, payload, headers):
        return self._request("POST", f"/branch-office/goodwill-transfers/{transfer_id}/counter-offer", payload, headers)

    def accept_transfer(self, transfer_id, headers):
        return self._request("POST", f"/branch-office/goodwill-transfers/{transfer_id}/accept", {}, headers)

    def decline_transfer(self, transfer_id, headers):
        return self._request("POST", f"/branch-office/goodwill-transfers/{transfer_id}/decline", {}, headers)

    def complete_transfer(self, transfer_id, headers):
        return self._request("POST", f"/branch-office/goodwill-transfers/{transfer_id}/complete", {}, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/branch-office/goodwill-transfers/{transfer_id}/cancel", {}, headers)

    # ---- Product shelf & solicitations ----
    def create_shelf_entry(self, payload, headers):
        return self._request("POST", "/branch-office/product-shelf", payload, headers)

    def approve_shelf_entry(self, entry_id, headers):
        return self._request("POST", f"/branch-office/product-shelf/{entry_id}/approve", {}, headers)

    def retire_shelf_entry(self, entry_id, headers):
        return self._request("POST", f"/branch-office/product-shelf/{entry_id}/retire", {}, headers)

    def list_shelf_entries(self, headers, params=None):
        return self._request("GET", "/branch-office/product-shelf", headers=headers, params=params)

    def create_solicitation_request(self, payload, headers):
        return self._request("POST", "/branch-office/solicitation-requests", payload, headers)

    def approve_solicitation(self, request_id, headers):
        return self._request("POST", f"/branch-office/solicitation-requests/{request_id}/approve", {}, headers)

    def deny_solicitation(self, request_id, headers):
        return self._request("POST", f"/branch-office/solicitation-requests/{request_id}/deny", {}, headers)

    def withdraw_solicitation(self, request_id, headers):
        return self._request("POST", f"/branch-office/solicitation-requests/{request_id}/withdraw", {}, headers)

    def list_solicitation_requests(self, headers, params=None):
        return self._request("GET", "/branch-office/solicitation-requests", headers=headers, params=params)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/branch-office/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
