"""API client: one method per operation defined in the PRD's endpoint table.

Subclasses the framework's GenericApiClient and only supplies the domain-specific
endpoint methods; request transport, base URL resolution and the standard envelope
handling all come from the framework.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/knock"
CLOCK_PATH = "/_clock/set_current_utc"


class ApiClient(GenericApiClient):

    # ── Household intake ────────────────────────────────────────
    def create_homeowner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"{PREFIX}/homeowners/{homeowner_id}", headers=headers)

    # ── Partner roster ──────────────────────────────────────────
    def create_agent(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"{PREFIX}/agents/{agent_id}", headers=headers)

    def qualify_agent(self, agent_id, headers):
        return self._request("POST", f"{PREFIX}/agents/{agent_id}/qualify", headers=headers)

    def suspend_agent(self, agent_id, headers):
        return self._request("POST", f"{PREFIX}/agents/{agent_id}/suspend", headers=headers)

    def reinstate_agent(self, agent_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/agents/{agent_id}", payload, headers)

    # ── Property records ────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{PREFIX}/properties/{property_id}", headers=headers)

    def record_site_visit(self, property_id, headers):
        return self._request("POST", f"{PREFIX}/properties/{property_id}/site-visits", headers=headers)

    # ── Qualification ───────────────────────────────────────────
    def create_qualification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qualifications", payload, headers)

    def list_qualifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qualifications", headers=headers, params=params)

    def get_qualification(self, qualification_id, headers):
        return self._request("GET", f"{PREFIX}/qualifications/{qualification_id}", headers=headers)

    def revise_qualification(self, qualification_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/qualifications/{qualification_id}", payload, headers)

    def approve_qualification(self, qualification_id, headers):
        return self._request("POST", f"{PREFIX}/qualifications/{qualification_id}/approve", headers=headers)

    def deny_qualification(self, qualification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/qualifications/{qualification_id}/deny", payload, headers)

    # ── Bridge program ──────────────────────────────────────────
    def create_bridge_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bridge-programs", payload, headers)

    def list_bridge_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bridge-programs", headers=headers, params=params)

    def get_bridge_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/bridge-programs/{program_id}", headers=headers)

    def fund_bridge_program(self, program_id, payload, headers):
        return self._request("POST", f"{PREFIX}/bridge-programs/{program_id}/fund", payload, headers)

    def occupy_new(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/bridge-programs/{program_id}/occupy-new", headers=headers)

    def get_program_summary(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/bridge-programs/{program_id}/summary", headers=headers)

    def preview_disclosures(self, program_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bridge-programs/{program_id}/disclosures/preview", payload, headers
        )

    # ── Interim loan ────────────────────────────────────────────
    def create_interim_loan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interim-loans", payload, headers)

    def list_interim_loans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/interim-loans", headers=headers, params=params)

    def get_interim_loan(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/interim-loans/{loan_id}", headers=headers)

    def post_repayment(self, loan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/interim-loans/{loan_id}/repayments", payload, headers)

    def reopen_advance(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/interim-loans/{loan_id}/reopen-advance", headers=headers)

    # ── Bridge advance ──────────────────────────────────────────
    def create_bridge_advance(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bridge-advances", payload, headers)

    def list_bridge_advances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bridge-advances", headers=headers, params=params)

    def get_bridge_advance(self, advance_id, headers):
        return self._request("GET", f"{PREFIX}/bridge-advances/{advance_id}", headers=headers)

    def approve_bridge_advance(self, advance_id, headers):
        return self._request("POST", f"{PREFIX}/bridge-advances/{advance_id}/approve", headers=headers)

    def reject_bridge_advance(self, advance_id, headers):
        return self._request("POST", f"{PREFIX}/bridge-advances/{advance_id}/reject", headers=headers)

    def disburse_bridge_advance(self, advance_id, headers):
        return self._request("POST", f"{PREFIX}/bridge-advances/{advance_id}/disburse", headers=headers)

    # ── Carrying cost ───────────────────────────────────────────
    def create_carrying_cost(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carrying-costs", payload, headers)

    def list_carrying_costs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/carrying-costs", headers=headers, params=params)

    def get_carrying_cost(self, cost_id, headers):
        return self._request("GET", f"{PREFIX}/carrying-costs/{cost_id}", headers=headers)

    def repay_carrying_cost(self, cost_id, headers):
        return self._request("POST", f"{PREFIX}/carrying-costs/{cost_id}/repay", headers=headers)

    # ── Repair advance ──────────────────────────────────────────
    def create_repair_advance(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repair-advances", payload, headers)

    def list_repair_advances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/repair-advances", headers=headers, params=params)

    def get_repair_advance(self, repair_id, headers):
        return self._request("GET", f"{PREFIX}/repair-advances/{repair_id}", headers=headers)

    def approve_repair_advance(self, repair_id, headers):
        return self._request("POST", f"{PREFIX}/repair-advances/{repair_id}/approve", headers=headers)

    def disburse_repair_advance(self, repair_id, headers):
        return self._request("POST", f"{PREFIX}/repair-advances/{repair_id}/disburse", headers=headers)

    # ── Backup offer ────────────────────────────────────────────
    def create_backup_offer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/backup-offers", payload, headers)

    def list_backup_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/backup-offers", headers=headers, params=params)

    def get_backup_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/backup-offers/{offer_id}", headers=headers)

    def issue_backup_offer(self, offer_id, headers):
        return self._request("POST", f"{PREFIX}/backup-offers/{offer_id}/issue", headers=headers)

    def extend_backup_offer(self, offer_id, headers):
        return self._request("POST", f"{PREFIX}/backup-offers/{offer_id}/extend", headers=headers)

    def exercise_backup_offer(self, offer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/backup-offers/{offer_id}/exercise", payload, headers)

    # ── Listing / marketing ─────────────────────────────────────
    def create_listing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/listings", payload, headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/listings", headers=headers, params=params)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"{PREFIX}/listings/{listing_id}", headers=headers)

    def relist_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/listings/{listing_id}", payload, headers)

    def go_live_listing(self, listing_id, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/go-live", headers=headers)

    def under_contract_listing(self, listing_id, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/under-contract", headers=headers)

    def close_sale_listing(self, listing_id, headers):
        return self._request("POST", f"{PREFIX}/listings/{listing_id}/close-sale", headers=headers)

    # ── Referral ────────────────────────────────────────────────
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def update_referral(self, referral_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/referrals/{referral_id}", payload, headers)

    def complete_referral(self, referral_id, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/complete", headers=headers)

    def void_referral(self, referral_id, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/void", headers=headers)

    def reopen_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/reopen", payload, headers)

    # ── Coordination task ───────────────────────────────────────
    def create_coordination_task(self, payload, headers):
        return self._request("POST", f"{PREFIX}/coordination-tasks", payload, headers)

    def list_coordination_tasks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coordination-tasks", headers=headers, params=params)

    def get_coordination_task(self, task_id, headers):
        return self._request("GET", f"{PREFIX}/coordination-tasks/{task_id}", headers=headers)

    def complete_coordination_task(self, task_id, headers):
        return self._request("POST", f"{PREFIX}/coordination-tasks/{task_id}/complete", headers=headers)

    # ── Settlement disbursement ─────────────────────────────────
    def create_disbursement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"{PREFIX}/disbursements/{disbursement_id}", headers=headers)

    def get_disbursements_summary(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disbursements/summary", headers=headers, params=params)

    # ── Logical clock ───────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()