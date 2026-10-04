"""API client: one method per endpoint defined in the PRD.

All POST helpers auto-attach a fresh Idempotency-Key header per call unless the
caller supplies one (idempotency replay tests pass an explicit ``idem_key``).
"""
import uuid

from prd_bench_local_runner.testing import GenericApiClient


def _with_idem(headers, idem_key=None):
    h = dict(headers or {})
    h["Idempotency-Key"] = idem_key if idem_key is not None else str(uuid.uuid4())
    return h


class ApiClient(GenericApiClient):
    # ---- land parcels ----
    def create_land_parcel(self, payload, headers, idem_key=None):
        return self._request("POST", "/land-parcels", payload, _with_idem(headers, idem_key))

    # ---- option contracts ----
    def create_option_contract(self, payload, headers, idem_key=None):
        return self._request("POST", "/option-contracts", payload, _with_idem(headers, idem_key))

    def list_option_contracts(self, headers, params=None):
        return self._request("GET", "/option-contracts", headers=headers, params=params)

    def get_option_contract(self, contract_id, headers):
        return self._request("GET", f"/option-contracts/{contract_id}", headers=headers)

    def execute_option_contract(self, contract_id, headers, idem_key=None):
        return self._request("POST", f"/option-contracts/{contract_id}/execute", {}, _with_idem(headers, idem_key))

    def cure_option_contract(self, contract_id, headers, idem_key=None):
        return self._request("POST", f"/option-contracts/{contract_id}/cure", {}, _with_idem(headers, idem_key))

    def create_takedown(self, contract_id, payload, headers, idem_key=None):
        return self._request("POST", f"/option-contracts/{contract_id}/takedowns", payload, _with_idem(headers, idem_key))

    def list_contract_takedowns(self, contract_id, headers, params=None):
        return self._request("GET", f"/option-contracts/{contract_id}/takedowns", headers=headers, params=params)

    # ---- takedowns ----
    def execute_takedown(self, takedown_id, headers, idem_key=None):
        return self._request("POST", f"/takedowns/{takedown_id}/execute", {}, _with_idem(headers, idem_key))

    def get_takedown(self, takedown_id, headers):
        return self._request("GET", f"/takedowns/{takedown_id}", headers=headers)

    def list_takedowns(self, headers, params=None):
        return self._request("GET", "/takedowns", headers=headers, params=params)

    # ---- communities ----
    def create_community(self, payload, headers, idem_key=None):
        return self._request("POST", "/communities", payload, _with_idem(headers, idem_key))

    def get_community(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}", headers=headers)

    def open_community(self, community_id, headers, idem_key=None):
        return self._request("POST", f"/communities/{community_id}/open", {}, _with_idem(headers, idem_key))

    def advance_phase(self, community_id, headers, idem_key=None):
        return self._request("POST", f"/communities/{community_id}/advance-phase", {}, _with_idem(headers, idem_key))

    def create_product_series(self, community_id, payload, headers, idem_key=None):
        return self._request("POST", f"/communities/{community_id}/product-series", payload, _with_idem(headers, idem_key))

    def list_product_series(self, community_id, headers, params=None):
        return self._request("GET", f"/communities/{community_id}/product-series", headers=headers, params=params)

    def get_product_series(self, series_id, headers):
        return self._request("GET", f"/product-series/{series_id}", headers=headers)

    def list_lots(self, community_id, headers, params=None):
        return self._request("GET", f"/communities/{community_id}/lots", headers=headers, params=params)

    def list_community_homes(self, community_id, headers, params=None):
        return self._request("GET", f"/communities/{community_id}/homes", headers=headers, params=params)

    def list_incentives(self, community_id, headers, params=None):
        return self._request("GET", f"/communities/{community_id}/incentives", headers=headers, params=params)

    def list_pacing_plans(self, community_id, headers, params=None):
        return self._request("GET", f"/communities/{community_id}/pacing-plans", headers=headers, params=params)

    def list_community_capacity_commitments(self, community_id, headers, params=None):
        return self._request("GET", f"/communities/{community_id}/capacity-commitments", headers=headers, params=params)

    def get_pacing_summary(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}/pacing-summary", headers=headers)

    def create_home(self, community_id, payload, headers, idem_key=None):
        return self._request("POST", f"/communities/{community_id}/homes", payload, _with_idem(headers, idem_key))

    def create_incentive(self, community_id, payload, headers, idem_key=None):
        return self._request("POST", f"/communities/{community_id}/incentives", payload, _with_idem(headers, idem_key))

    def create_pacing_plan(self, community_id, payload, headers, idem_key=None):
        return self._request("POST", f"/communities/{community_id}/pacing-plans", payload, _with_idem(headers, idem_key))

    # ---- homes ----
    def get_home(self, home_id, headers):
        return self._request("GET", f"/homes/{home_id}", headers=headers)

    def list_homes(self, headers, params=None):
        return self._request("GET", "/homes", headers=headers, params=params)

    def advance_stage(self, home_id, headers, idem_key=None):
        return self._request("POST", f"/homes/{home_id}/advance-stage", {}, _with_idem(headers, idem_key))

    def list_home_sales_contracts(self, home_id, headers, params=None):
        return self._request("GET", f"/homes/{home_id}/sales-contracts", headers=headers, params=params)

    # ---- sales contracts ----
    def create_sales_contract(self, payload, headers, idem_key=None):
        return self._request("POST", "/sales-contracts", payload, _with_idem(headers, idem_key))

    def get_sales_contract(self, contract_id, headers):
        return self._request("GET", f"/sales-contracts/{contract_id}", headers=headers)

    def approve_sales_contract(self, contract_id, headers, idem_key=None):
        return self._request("POST", f"/sales-contracts/{contract_id}/approve", {}, _with_idem(headers, idem_key))

    def renegotiate_sales_contract(self, contract_id, payload, headers, idem_key=None):
        return self._request("POST", f"/sales-contracts/{contract_id}/renegotiate", payload, _with_idem(headers, idem_key))

    def close_sales_contract(self, contract_id, headers, idem_key=None):
        return self._request("POST", f"/sales-contracts/{contract_id}/close", {}, _with_idem(headers, idem_key))

    def terminate_sales_contract(self, contract_id, headers, idem_key=None):
        return self._request("POST", f"/sales-contracts/{contract_id}/terminate", {}, _with_idem(headers, idem_key))

    # ---- incentives ----
    def get_incentive(self, incentive_id, headers):
        return self._request("GET", f"/incentives/{incentive_id}", headers=headers)

    def cancel_incentive(self, incentive_id, headers, idem_key=None):
        return self._request("POST", f"/incentives/{incentive_id}/cancel", {}, _with_idem(headers, idem_key))

    # ---- trade partners / capacity ----
    def create_trade_partner(self, payload, headers, idem_key=None):
        return self._request("POST", "/trade-partners", payload, _with_idem(headers, idem_key))

    def get_trade_partner(self, partner_id, headers):
        return self._request("GET", f"/trade-partners/{partner_id}", headers=headers)

    def create_capacity_commitment(self, partner_id, payload, headers, idem_key=None):
        return self._request("POST", f"/trade-partners/{partner_id}/capacity-commitments", payload, _with_idem(headers, idem_key))

    def list_partner_capacity_commitments(self, partner_id, headers, params=None):
        return self._request("GET", f"/trade-partners/{partner_id}/capacity-commitments", headers=headers, params=params)

    def get_capacity_commitment(self, commitment_id, headers):
        return self._request("GET", f"/capacity-commitments/{commitment_id}", headers=headers)

    def reduce_capacity_commitment(self, commitment_id, payload, headers, idem_key=None):
        return self._request("POST", f"/capacity-commitments/{commitment_id}/reduce", payload, _with_idem(headers, idem_key))

    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers, idem_key=None):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, _with_idem(headers, idem_key))


api_client = ApiClient()
