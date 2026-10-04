"""API client: one method per endpoint declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Member food banks ────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/network/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/network/members/{member_id}", headers=headers)

    def certify_member(self, member_id, headers):
        return self._request("POST", f"/network/members/{member_id}/certify", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/network/members/{member_id}/reinstate", {}, headers)

    def list_member_audits(self, member_id, headers, params=None):
        return self._request("GET", f"/network/members/{member_id}/audits",
                             headers=headers, params=params)

    def list_member_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/network/members/{member_id}/share-ledger",
                             headers=headers, params=params)

    def list_member_store_programs(self, member_id, headers, params=None):
        return self._request("GET", f"/network/members/{member_id}/store-programs",
                             headers=headers, params=params)

    # ── Donor agreements ─────────────────────────────────────────────
    def create_donor_agreement(self, payload, headers):
        return self._request("POST", "/network/donor-agreements", payload, headers)

    def get_donor_agreement(self, agreement_id, headers):
        return self._request("GET", f"/network/donor-agreements/{agreement_id}",
                             headers=headers)

    def activate_donor_agreement(self, agreement_id, headers):
        return self._request("POST", f"/network/donor-agreements/{agreement_id}/activate",
                             {}, headers)

    def get_poundage_summary(self, agreement_id, headers, params=None):
        return self._request("GET", f"/network/donor-agreements/{agreement_id}/poundage-summary",
                             headers=headers, params=params)

    def list_agreement_loads(self, agreement_id, headers, params=None):
        return self._request("GET", f"/network/donor-agreements/{agreement_id}/loads",
                             headers=headers, params=params)

    def list_agreement_recalls(self, agreement_id, headers, params=None):
        return self._request("GET", f"/network/donor-agreements/{agreement_id}/recalls",
                             headers=headers, params=params)

    # ── Donated loads ────────────────────────────────────────────────
    def create_load(self, payload, headers):
        return self._request("POST", "/network/loads", payload, headers)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/network/loads/{load_id}", headers=headers)

    def post_load(self, load_id, headers):
        return self._request("POST", f"/network/loads/{load_id}/post", {}, headers)

    def award_load(self, load_id, headers, payload=None):
        return self._request("POST", f"/network/loads/{load_id}/award", payload or {}, headers)

    def record_freight_decision(self, load_id, payload, headers):
        return self._request("POST", f"/network/loads/{load_id}/freight-decision",
                             payload, headers)

    def dispatch_load(self, load_id, payload, headers):
        return self._request("POST", f"/network/loads/{load_id}/dispatch", payload, headers)

    def deliver_load(self, load_id, headers):
        return self._request("POST", f"/network/loads/{load_id}/deliver", {}, headers)

    def cancel_load(self, load_id, headers):
        return self._request("POST", f"/network/loads/{load_id}/cancel", {}, headers)

    # ── Bids ─────────────────────────────────────────────────────────
    def create_bid(self, load_id, payload, headers):
        return self._request("POST", f"/network/loads/{load_id}/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/network/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/network/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/network/bids/{bid_id}/withdraw", {}, headers)

    # ── Share ledger ─────────────────────────────────────────────────
    def create_share_grant(self, payload, headers):
        return self._request("POST", "/network/share-ledger/grants", payload, headers)

    # ── Recalls and holds ────────────────────────────────────────────
    def create_recall(self, payload, headers):
        return self._request("POST", "/network/recalls", payload, headers)

    def trace_recall(self, recall_id, headers):
        return self._request("POST", f"/network/recalls/{recall_id}/trace", {}, headers)

    def resolve_recall(self, recall_id, headers):
        return self._request("POST", f"/network/recalls/{recall_id}/resolve", {}, headers)

    def list_recall_holds(self, headers, params=None):
        return self._request("GET", "/network/recall-holds", headers=headers, params=params)

    def get_recall_hold(self, hold_id, headers):
        return self._request("GET", f"/network/recall-holds/{hold_id}", headers=headers)

    # ── Audits ───────────────────────────────────────────────────────
    def create_audit(self, payload, headers):
        return self._request("POST", "/network/audits", payload, headers)

    def complete_audit(self, audit_id, headers):
        return self._request("POST", f"/network/audits/{audit_id}/complete", {}, headers)

    # ── Retail store programs and pickups ────────────────────────────
    def create_store_program(self, payload, headers):
        return self._request("POST", "/network/store-programs", payload, headers)

    def get_store_program(self, program_id, headers):
        return self._request("GET", f"/network/store-programs/{program_id}", headers=headers)

    def schedule_pickup(self, program_id, payload, headers):
        return self._request("POST", f"/network/store-programs/{program_id}/pickups",
                             payload, headers)

    def list_program_pickups(self, program_id, headers, params=None):
        return self._request("GET", f"/network/store-programs/{program_id}/pickups",
                             headers=headers, params=params)

    def complete_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/network/store-pickups/{pickup_id}/complete",
                             payload, headers)

    def miss_pickup(self, pickup_id, headers):
        return self._request("POST", f"/network/store-pickups/{pickup_id}/miss", {}, headers)


api_client = ApiClient()
