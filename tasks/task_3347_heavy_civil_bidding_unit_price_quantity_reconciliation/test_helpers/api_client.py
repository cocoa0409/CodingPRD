"""API client: one method per endpoint declared in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/construction"


class ApiClient(GenericApiClient):
    # --- logical clock ------------------------------------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- sessions -----------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions", payload, headers)

    # --- sureties -----------------------------------------------------------
    def create_surety(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sureties", payload, headers)

    def list_sureties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sureties", params, headers)

    def get_surety(self, surety_id, headers):
        return self._request("GET", f"{PREFIX}/sureties/{surety_id}", headers=headers)

    def suspend_surety(self, surety_id, headers):
        return self._request("POST", f"{PREFIX}/sureties/{surety_id}/suspend", {}, headers)

    def reinstate_surety(self, surety_id, headers):
        return self._request("POST", f"{PREFIX}/sureties/{surety_id}/reinstate", {}, headers)

    # --- surety commitments -------------------------------------------------
    def create_surety_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/surety-commitments", payload, headers)

    def list_surety_commitments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/surety-commitments", params, headers)

    def get_surety_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/surety-commitments/{commitment_id}", headers=headers
        )

    def release_surety_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/surety-commitments/{commitment_id}/release-commitment",
            {}, headers,
        )

    # --- projects -----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", params, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def get_project_summary(self, project_id, headers):
        return self._request(
            "GET", f"{PREFIX}/projects/{project_id}/summary", headers=headers
        )

    def seal_bid(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/seal-bid", {}, headers)

    def open_bid(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/open-bid", {}, headers)

    def recall_bid(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/recall-bid", payload, headers
        )

    def reset_bid(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/reset-bid", {}, headers)

    def start_work(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/start-work", {}, headers)

    # --- bid items ----------------------------------------------------------
    def create_bid_item(self, project_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/bid-items", payload, headers
        )

    def list_bid_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bid-items", params, headers)

    def get_bid_item(self, bid_item_id, headers):
        return self._request("GET", f"{PREFIX}/bid-items/{bid_item_id}", headers=headers)

    def price_bid_item(self, project_id, bid_item_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/bid-items/{bid_item_id}/price",
            payload, headers,
        )

    def submit_bid_item(self, project_id, bid_item_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/bid-items/{bid_item_id}/submit",
            {}, headers,
        )

    def unsubmit_bid_item(self, project_id, bid_item_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/bid-items/{bid_item_id}/unsubmit",
            {}, headers,
        )

    def close_bid_item(self, project_id, bid_item_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/bid-items/{bid_item_id}/close",
            {}, headers,
        )

    # --- subcontractor quotes ----------------------------------------------
    def create_quote(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subcontractor-quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subcontractor-quotes", params, headers)

    def get_quote(self, quote_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subcontractor-quotes/{quote_id}", headers=headers
        )

    def carry_quote(self, quote_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subcontractor-quotes/{quote_id}/carry", {}, headers
        )

    def withdraw_quote(self, quote_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subcontractor-quotes/{quote_id}/withdraw", {}, headers
        )

    def select_quote(self, quote_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subcontractor-quotes/{quote_id}/select", {}, headers
        )

    def reject_quote(self, quote_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subcontractor-quotes/{quote_id}/reject", {}, headers
        )

    # --- bonds --------------------------------------------------------------
    def create_bond(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bonds", payload, headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bonds", params, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"{PREFIX}/bonds/{bond_id}", headers=headers)

    def issue_bond(self, bond_id, headers):
        return self._request("POST", f"{PREFIX}/bonds/{bond_id}/issue", {}, headers)

    def execute_bond(self, bond_id, headers):
        return self._request("POST", f"{PREFIX}/bonds/{bond_id}/execute", {}, headers)

    def release_bond(self, bond_id, headers):
        return self._request("POST", f"{PREFIX}/bonds/{bond_id}/release-bond", {}, headers)

    # --- progress measurements ---------------------------------------------
    def create_measurement(self, bid_item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bid-items/{bid_item_id}/measurements", payload, headers
        )

    def list_measurements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/measurements", params, headers)

    def get_measurement(self, measurement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/measurements/{measurement_id}", headers=headers
        )

    def approve_measurement(self, measurement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/measurements/{measurement_id}/approve", {}, headers
        )

    def pay_measurement(self, measurement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/measurements/{measurement_id}/pay", {}, headers
        )

    def void_measurement(self, measurement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/measurements/{measurement_id}/void", {}, headers
        )

    # --- quantity reconciliations ------------------------------------------
    def create_reconciliation(self, project_id, headers):
        return self._request(
            "POST", f"{PREFIX}/projects/{project_id}/reconciliations", {}, headers
        )

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reconciliations", params, headers)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reconciliations/{reconciliation_id}", headers=headers
        )

    def finalize_reconciliation(self, project_id, reconciliation_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/reconciliations/{reconciliation_id}/finalize",
            payload, headers,
        )

    def release_retention(self, project_id, reconciliation_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/projects/{project_id}/reconciliations/{reconciliation_id}"
            "/release-retention",
            {}, headers,
        )

    # --- differing site conditions -----------------------------------------
    def create_condition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/differing-site-conditions", payload, headers)

    def list_conditions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/differing-site-conditions", params, headers)

    def get_condition(self, condition_id, headers):
        return self._request(
            "GET", f"{PREFIX}/differing-site-conditions/{condition_id}", headers=headers
        )

    def document_condition(self, condition_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/differing-site-conditions/{condition_id}/document",
            payload, headers,
        )

    def submit_claim(self, condition_id, headers):
        return self._request(
            "POST", f"{PREFIX}/differing-site-conditions/{condition_id}/submit-claim",
            {}, headers,
        )

    def return_for_documentation(self, condition_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/differing-site-conditions/{condition_id}/return-for-documentation",
            {}, headers,
        )

    def engineer_determination(self, condition_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/differing-site-conditions/{condition_id}/engineer-determination",
            payload, headers,
        )

    def deny_condition(self, condition_id, headers):
        return self._request(
            "POST", f"{PREFIX}/differing-site-conditions/{condition_id}/deny", {}, headers
        )

    # --- engineer determinations -------------------------------------------
    def list_determinations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/engineer-determinations", params, headers)

    def get_determination(self, determination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/engineer-determinations/{determination_id}", headers=headers
        )

    def finalize_determination(self, determination_id, headers):
        return self._request(
            "POST", f"{PREFIX}/engineer-determinations/{determination_id}/finalize",
            {}, headers,
        )


api_client = ApiClient()
