"""One method per endpoint in the API's endpoint catalogue.

Every path is rooted at the API prefix. Endpoints specified with no request body
still send an empty JSON object so that the transport is identical across calls.
"""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .types import JsonDict

P = "/kiosk-ops"


class ApiClient(GenericApiClient):
    """Typed surface over the Sushi Kiosk Franchise Ops API."""

    # --- Logical clock -----------------------------------------------------
    def set_clock(self, payload: JsonDict, headers: Optional[JsonDict] = None):
        """Sets the server's logical UTC clock. Requires no authentication."""
        return self._request(
            "POST", f"{P}/_clock/set_current_utc", payload, headers or {}
        )

    # --- Host stores -------------------------------------------------------
    def create_host_store(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/host-stores", payload, headers)

    def get_host_store(self, host_store_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/host-stores/{host_store_id}", None, headers)

    def list_host_stores(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/host-stores", None, headers, params)

    def set_pos_integration(
        self, host_store_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/host-stores/{host_store_id}/pos-integration", payload, headers
        )

    def attest_space(self, host_store_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST",
            f"{P}/host-stores/{host_store_id}/space-attestation",
            payload,
            headers,
        )

    # --- License agreements ------------------------------------------------
    def create_license_agreement(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/license-agreements", payload, headers)

    def get_license_agreement(self, agreement_id: str, headers: JsonDict):
        return self._request(
            "GET", f"{P}/license-agreements/{agreement_id}", None, headers
        )

    def list_license_agreements(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request("GET", f"{P}/license-agreements", None, headers, params)

    def activate_license_agreement(self, agreement_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/license-agreements/{agreement_id}/activate", {}, headers
        )

    def suspend_license_agreement(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/license-agreements/{agreement_id}/suspend", payload, headers
        )

    def reinstate_license_agreement(self, agreement_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/license-agreements/{agreement_id}/reinstate", {}, headers
        )

    def terminate_license_agreement(
        self, agreement_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/license-agreements/{agreement_id}/terminate", payload, headers
        )

    # --- Chefs and certifications -----------------------------------------
    def create_chef(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/chefs", payload, headers)

    def get_chef(self, chef_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/chefs/{chef_id}", None, headers)

    def list_chefs(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/chefs", None, headers, params)

    def log_training(self, chef_id: str, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/chefs/{chef_id}/training", payload, headers)

    def create_certification(self, chef_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/chefs/{chef_id}/certifications", payload, headers
        )

    def list_certifications(
        self, chef_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request(
            "GET", f"{P}/chefs/{chef_id}/certifications", None, headers, params
        )

    def revoke_certification(
        self,
        chef_id: str,
        certification_id: str,
        payload: JsonDict,
        headers: JsonDict,
    ):
        return self._request(
            "POST",
            f"{P}/chefs/{chef_id}/certifications/{certification_id}/revoke",
            payload,
            headers,
        )

    def place_chef(self, chef_id: str, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/chefs/{chef_id}/placement", payload, headers)

    # --- Kiosks ------------------------------------------------------------
    def create_kiosk(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/kiosks", payload, headers)

    def get_kiosk(self, kiosk_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/kiosks/{kiosk_id}", None, headers)

    def list_kiosks(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/kiosks", None, headers, params)

    def get_kiosk_risk_summary(self, kiosk_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/kiosks/{kiosk_id}/risk-summary", None, headers)

    def commission_kiosk(self, kiosk_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/kiosks/{kiosk_id}/commission", payload, headers
        )

    def suspend_kiosk(self, kiosk_id: str, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/kiosks/{kiosk_id}/suspend", payload, headers)

    def reinstate_kiosk(self, kiosk_id: str, headers: JsonDict):
        return self._request("POST", f"{P}/kiosks/{kiosk_id}/reinstate", {}, headers)

    def decommission_kiosk(self, kiosk_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/kiosks/{kiosk_id}/decommission", payload, headers
        )

    # --- Production plans --------------------------------------------------
    def create_production_plan(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/production-plans", payload, headers)

    def get_production_plan(self, plan_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/production-plans/{plan_id}", None, headers)

    def list_production_plans(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request("GET", f"{P}/production-plans", None, headers, params)

    def release_production_plan(self, plan_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/production-plans/{plan_id}/release", {}, headers
        )

    def lock_production_plan(self, plan_id: str, headers: JsonDict):
        return self._request("POST", f"{P}/production-plans/{plan_id}/lock", {}, headers)

    def reconcile_production_plan(self, plan_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/production-plans/{plan_id}/reconcile", {}, headers
        )

    def void_production_plan(self, plan_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/production-plans/{plan_id}/void", payload, headers
        )

    # --- Rice batches ------------------------------------------------------
    def create_rice_batch(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/rice-batches", payload, headers)

    def get_rice_batch(self, batch_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/rice-batches/{batch_id}", None, headers)

    def list_rice_batches(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/rice-batches", None, headers, params)

    def record_acidification_reading(
        self, batch_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/rice-batches/{batch_id}/acidification-reading", payload, headers
        )

    def verify_ttc(self, batch_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/rice-batches/{batch_id}/verify-ttc", {}, headers
        )

    def request_variance(self, batch_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/rice-batches/{batch_id}/variance-request", payload, headers
        )

    def decide_variance(self, batch_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/rice-batches/{batch_id}/variance-decision", payload, headers
        )

    def revoke_variance(self, batch_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/rice-batches/{batch_id}/revoke-variance", payload, headers
        )

    # --- Fish lots and cold chain -----------------------------------------
    def create_fish_lot(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/fish-lots", payload, headers)

    def get_fish_lot(self, fish_lot_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/fish-lots/{fish_lot_id}", None, headers)

    def list_fish_lots(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/fish-lots", None, headers, params)

    def record_parasite_destruction(
        self, fish_lot_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/fish-lots/{fish_lot_id}/parasite-destruction", payload, headers
        )

    def create_cold_chain_reading(
        self, fish_lot_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/fish-lots/{fish_lot_id}/cold-chain-readings", payload, headers
        )

    def list_cold_chain_readings(
        self, fish_lot_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request(
            "GET", f"{P}/fish-lots/{fish_lot_id}/cold-chain-readings", None, headers, params
        )

    def release_fish_lot(
        self, fish_lot_id: str, headers: JsonDict, payload: Optional[JsonDict] = None
    ):
        return self._request(
            "POST", f"{P}/fish-lots/{fish_lot_id}/release", payload or {}, headers
        )

    def destroy_fish_lot(self, fish_lot_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/fish-lots/{fish_lot_id}/destroy", payload, headers
        )

    # --- Pack lots ---------------------------------------------------------
    def create_pack_lot(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/pack-lots", payload, headers)

    def get_pack_lot(self, pack_lot_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/pack-lots/{pack_lot_id}", None, headers)

    def list_pack_lots(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/pack-lots", None, headers, params)

    def markdown_pack_lot(self, pack_lot_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/pack-lots/{pack_lot_id}/markdown", {}, headers
        )

    def discard_pack_lot(self, pack_lot_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/pack-lots/{pack_lot_id}/discard", payload, headers
        )

    def list_discard_events(
        self, pack_lot_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request(
            "GET", f"{P}/pack-lots/{pack_lot_id}/discard-events", None, headers, params
        )

    def void_pack_lot(self, pack_lot_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/pack-lots/{pack_lot_id}/void", payload, headers
        )

    # --- POS sales feeds ---------------------------------------------------
    def create_pos_sales_feed(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/pos-sales-feeds", payload, headers)

    def get_pos_sales_feed(self, feed_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/pos-sales-feeds/{feed_id}", None, headers)

    def list_pos_sales_feeds(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/pos-sales-feeds", None, headers, params)

    def reconcile_pos_sales_feed(self, feed_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/pos-sales-feeds/{feed_id}/reconcile", {}, headers
        )

    def reject_pos_sales_feed(self, feed_id: str, payload: JsonDict, headers: JsonDict):
        return self._request(
            "POST", f"{P}/pos-sales-feeds/{feed_id}/reject", payload, headers
        )

    # --- Settlement statements --------------------------------------------
    def create_settlement_statement(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/settlement-statements", payload, headers)

    def get_settlement_statement(self, statement_id: str, headers: JsonDict):
        return self._request(
            "GET", f"{P}/settlement-statements/{statement_id}", None, headers
        )

    def list_settlement_statements(
        self, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request("GET", f"{P}/settlement-statements", None, headers, params)

    def issue_settlement_statement(self, statement_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/settlement-statements/{statement_id}/issue", {}, headers
        )

    def acknowledge_settlement_statement(self, statement_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/settlement-statements/{statement_id}/acknowledge", {}, headers
        )

    def dispute_settlement_statement(
        self, statement_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST",
            f"{P}/settlement-statements/{statement_id}/dispute",
            payload,
            headers,
        )

    def revise_settlement_statement(
        self, statement_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/settlement-statements/{statement_id}/revise", payload, headers
        )

    def pay_settlement_statement(
        self, statement_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/settlement-statements/{statement_id}/pay", payload, headers
        )

    def void_settlement_statement(
        self, statement_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST", f"{P}/settlement-statements/{statement_id}/void", payload, headers
        )

    # --- Food safety audits and findings ----------------------------------
    def create_audit(self, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/audits", payload, headers)

    def get_audit(self, audit_id: str, headers: JsonDict):
        return self._request("GET", f"{P}/audits/{audit_id}", None, headers)

    def list_audits(self, headers: JsonDict, params: Optional[JsonDict] = None):
        return self._request("GET", f"{P}/audits", None, headers, params)

    def start_audit(self, audit_id: str, headers: JsonDict):
        return self._request("POST", f"{P}/audits/{audit_id}/start", {}, headers)

    def create_finding(self, audit_id: str, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/audits/{audit_id}/findings", payload, headers)

    def list_findings(
        self, audit_id: str, headers: JsonDict, params: Optional[JsonDict] = None
    ):
        return self._request(
            "GET", f"{P}/audits/{audit_id}/findings", None, headers, params
        )

    def submit_audit(self, audit_id: str, headers: JsonDict):
        return self._request("POST", f"{P}/audits/{audit_id}/submit", {}, headers)

    def correct_finding(
        self, audit_id: str, finding_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST",
            f"{P}/audits/{audit_id}/findings/{finding_id}/correct",
            payload,
            headers,
        )

    def waive_finding(
        self, audit_id: str, finding_id: str, payload: JsonDict, headers: JsonDict
    ):
        return self._request(
            "POST",
            f"{P}/audits/{audit_id}/findings/{finding_id}/waive",
            payload,
            headers,
        )

    def request_reverification(self, audit_id: str, headers: JsonDict):
        return self._request(
            "POST", f"{P}/audits/{audit_id}/request-reverification", {}, headers
        )

    def verify_audit(self, audit_id: str, payload: JsonDict, headers: JsonDict):
        return self._request("POST", f"{P}/audits/{audit_id}/verify", payload, headers)


api_client = ApiClient()
