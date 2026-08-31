"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Landfill sites ───────────────────────────────

    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_energy_balance(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}/energy-balance", headers=headers)

    # ─── Gas wells and tuning readings ────────────────

    def create_well(self, payload, headers):
        return self._request("POST", "/wells", payload, headers)

    def get_well(self, well_id, headers):
        return self._request("GET", f"/wells/{well_id}", headers=headers)

    def list_wells(self, headers, params=None):
        return self._request("GET", "/wells", headers=headers, params=params)

    def create_reading(self, well_id, payload, headers):
        return self._request("POST", f"/wells/{well_id}/readings", payload, headers)

    def list_readings(self, well_id, headers, params=None):
        return self._request(
            "GET", f"/wells/{well_id}/readings", headers=headers, params=params
        )

    def set_well_status(self, well_id, payload, headers):
        return self._request("POST", f"/wells/{well_id}/status", payload, headers)

    # ─── Work orders and condensate hauls ─────────────

    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def set_work_order_status(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/status", payload, headers
        )

    def create_condensate_haul(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/condensate-hauls", payload, headers
        )

    def list_condensate_hauls(self, work_order_id, headers, params=None):
        return self._request(
            "GET",
            f"/work-orders/{work_order_id}/condensate-hauls",
            headers=headers,
            params=params,
        )

    # ─── Processing plants ────────────────────────────

    def create_plant(self, payload, headers):
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def list_plants(self, headers, params=None):
        return self._request("GET", "/plants", headers=headers, params=params)

    def set_plant_status(self, plant_id, payload, headers):
        return self._request("POST", f"/plants/{plant_id}/status", payload, headers)

    # ─── Downtime events ──────────────────────────────

    def create_downtime_event(self, payload, headers):
        return self._request("POST", "/downtime-events", payload, headers)

    def get_downtime_event(self, event_id, headers):
        return self._request("GET", f"/downtime-events/{event_id}", headers=headers)

    def list_downtime_events(self, headers, params=None):
        return self._request("GET", "/downtime-events", headers=headers, params=params)

    def close_downtime_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/downtime-events/{event_id}/close", payload, headers
        )

    # ─── Offtake contracts ────────────────────────────

    def create_offtake_contract(self, payload, headers):
        return self._request("POST", "/offtake-contracts", payload, headers)

    def get_offtake_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/offtake-contracts/{contract_id}", headers=headers
        )

    def list_offtake_contracts(self, headers, params=None):
        return self._request(
            "GET", "/offtake-contracts", headers=headers, params=params
        )

    def set_contract_status(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/offtake-contracts/{contract_id}/status", payload, headers
        )

    # ─── Pipeline nominations ─────────────────────────

    def create_nomination(self, payload, headers):
        return self._request("POST", "/pipeline-nominations", payload, headers)

    def get_nomination(self, nomination_id, headers):
        return self._request(
            "GET", f"/pipeline-nominations/{nomination_id}", headers=headers
        )

    def list_nominations(self, headers, params=None):
        return self._request(
            "GET", "/pipeline-nominations", headers=headers, params=params
        )

    def set_nomination_status(self, nomination_id, payload, headers):
        return self._request(
            "POST", f"/pipeline-nominations/{nomination_id}/status", payload, headers
        )

    # ─── Injection batches ────────────────────────────

    def create_injection_batch(self, payload, headers):
        return self._request("POST", "/injection-batches", payload, headers)

    def get_injection_batch(self, batch_id, headers):
        return self._request("GET", f"/injection-batches/{batch_id}", headers=headers)

    def list_injection_batches(self, headers, params=None):
        return self._request(
            "GET", "/injection-batches", headers=headers, params=params
        )

    def set_injection_batch_status(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/injection-batches/{batch_id}/status", payload, headers
        )

    def meter_trueup(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/injection-batches/{batch_id}/meter-trueup", payload, headers
        )

    # ─── Attribute batches ────────────────────────────

    def create_attribute_batch(self, payload, headers):
        return self._request("POST", "/attribute-batches", payload, headers)

    def get_attribute_batch(self, batch_id, headers):
        return self._request("GET", f"/attribute-batches/{batch_id}", headers=headers)

    def list_attribute_batches(self, headers, params=None):
        return self._request(
            "GET", "/attribute-batches", headers=headers, params=params
        )

    def set_attribute_batch_status(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/attribute-batches/{batch_id}/status", payload, headers
        )

    # ─── Compliance reports ───────────────────────────

    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}", headers=headers)

    def list_compliance_reports(self, headers, params=None):
        return self._request(
            "GET", "/compliance-reports", headers=headers, params=params
        )

    def set_compliance_report_status(self, report_id, payload, headers):
        return self._request(
            "POST", f"/compliance-reports/{report_id}/status", payload, headers
        )

    # ─── Royalty statements ───────────────────────────

    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/royalty-statements/{statement_id}", headers=headers
        )

    def list_royalty_statements(self, headers, params=None):
        return self._request(
            "GET", "/royalty-statements", headers=headers, params=params
        )

    def set_royalty_statement_status(self, statement_id, payload, headers):
        return self._request(
            "POST", f"/royalty-statements/{statement_id}/status", payload, headers
        )


api_client = ApiClient()
