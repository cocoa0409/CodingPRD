"""One client method per endpoint in the PRD's HTTP surface table.

"Every path in this specification is absolute -- the API is mounted at the
server root, so a storage field is addressed at `/storage-fields/{id}` with no
additional prefix." No method here adds a prefix.

Every method returns the raw requests.Response so tests can assert on status
codes as well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class StorageApiClient(GenericApiClient):
    """Typed surface for the Underground Gas Storage Operations API."""

    # ─── Storage fields ────────────────────────────────────────────────────
    def create_storage_field(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/storage-fields", payload, headers)

    def get_storage_field(self, field_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/storage-fields/{field_id}", None, headers)

    def set_season(self, field_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/storage-fields/{field_id}/season", payload, headers)

    def list_field_regulatory_reports(
        self, field_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/storage-fields/{field_id}/regulatory-reports", params, headers
        )

    # ─── Wells ─────────────────────────────────────────────────────────────
    def create_well(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/wells", payload, headers)

    def list_wells(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/wells", params, headers)

    def get_well(self, well_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/wells/{well_id}", None, headers)

    def change_well_service(
        self, well_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/wells/{well_id}/service-change", payload, headers)

    # ─── Mechanical integrity tests ────────────────────────────────────────
    def create_mit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/mechanical-integrity-tests", payload, headers)

    def list_mits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/mechanical-integrity-tests", params, headers)

    def get_mit(self, mit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/mechanical-integrity-tests/{mit_id}", None, headers)

    def record_mit_result(
        self, mit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/mechanical-integrity-tests/{mit_id}/record-result", payload, headers
        )

    # ─── Remediation programs ──────────────────────────────────────────────
    def list_remediation_programs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/remediation-programs", params, headers)

    def get_remediation_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/remediation-programs/{program_id}", None, headers)

    def complete_remediation_program(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/remediation-programs/{program_id}/complete", payload, headers
        )

    # ─── Compressor units and runs ─────────────────────────────────────────
    def create_compressor_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compressor-units", payload, headers)

    def list_compressor_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/compressor-units", params, headers)

    def get_compressor_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/compressor-units/{unit_id}", None, headers)

    def list_unit_runs(
        self, unit_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/compressor-units/{unit_id}/runs", params, headers)

    def create_compressor_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compressor-runs", payload, headers)

    def complete_compressor_run(
        self, run_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/compressor-runs/{run_id}/complete", payload or {}, headers
        )

    # ─── Shippers ──────────────────────────────────────────────────────────
    def create_shipper(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shippers", payload, headers)

    def get_shipper(self, shipper_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shippers/{shipper_id}", None, headers)

    # ─── Storage contracts ─────────────────────────────────────────────────
    def create_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/storage-contracts", payload, headers)

    def list_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/storage-contracts", params, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/storage-contracts/{contract_id}", None, headers)

    def activate_contract(
        self, contract_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/storage-contracts/{contract_id}/activate", payload or {}, headers
        )

    def cash_out(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/storage-contracts/{contract_id}/cash-out", payload, headers
        )

    def cash_out_reversal(
        self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/storage-contracts/{contract_id}/cash-out-reversal", payload, headers
        )

    def list_ledger_entries(
        self, contract_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/storage-contracts/{contract_id}/imbalance-ledger-entries",
            params,
            headers,
        )

    # ─── Nominations ───────────────────────────────────────────────────────
    def create_nomination(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/nominations", payload, headers)

    def list_nominations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/nominations", params, headers)

    def get_nomination(self, nomination_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/nominations/{nomination_id}", None, headers)

    def submit_nomination(
        self, nomination_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/nominations/{nomination_id}/submit", payload or {}, headers
        )

    def confirm_nomination(
        self, nomination_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/nominations/{nomination_id}/confirm", payload or {}, headers
        )

    # ─── Gas movement tickets ──────────────────────────────────────────────
    def create_ticket(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/gas-movement-tickets", payload, headers)

    def list_tickets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/gas-movement-tickets", params, headers)

    def get_ticket(self, ticket_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/gas-movement-tickets/{ticket_id}", None, headers)

    def confirm_ticket(self, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/gas-movement-tickets/{ticket_id}/confirm", payload, headers
        )

    def reverse_ticket(self, ticket_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/gas-movement-tickets/{ticket_id}/reverse", payload, headers
        )

    # ─── Emergency events ──────────────────────────────────────────────────
    def create_emergency_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/emergency-events", payload, headers)

    def list_emergency_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/emergency-events", params, headers)

    def get_emergency_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/emergency-events/{event_id}", None, headers)

    def advance_emergency_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/emergency-events/{event_id}/advance", payload, headers)

    # ─── Regulatory reports ────────────────────────────────────────────────
    def create_regulatory_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/regulatory-reports", payload, headers)

    def submit_regulatory_report(
        self, report_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/regulatory-reports/{report_id}/submit", payload or {}, headers
        )

    def record_agency_response(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/regulatory-reports/{report_id}/record-agency-response", payload, headers
        )

    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        """PRD §2.4: accepts a `to_iso8601` instant and returns `current_utc`."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Escape hatch for negative-shape probes ────────────────────────────
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request -- used only where a test must bypass a
        typed method to probe malformed input or an unknown path."""
        return self._request(method, path, payload, headers, params)
