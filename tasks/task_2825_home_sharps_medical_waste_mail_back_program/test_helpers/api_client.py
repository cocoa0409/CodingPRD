"""ApiClient: one method per endpoint declared by the PRD.

Every business resource is mounted under the `/sharps` prefix; the logical clock
endpoint lives outside it.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD 2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # State sharps rules (PRD 3.1)
    # ------------------------------------------------------------------
    def create_state_rule(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/state-rules", payload, headers)

    def get_state_rule(self, state_rule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/state-rules/{state_rule_id}", None, headers)

    def list_state_rules(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/state-rules", params, headers)

    # ------------------------------------------------------------------
    # Packaging specifications (PRD 3.1)
    # ------------------------------------------------------------------
    def create_packaging_spec(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/packaging-specs", payload, headers)

    def get_packaging_spec(self, packaging_spec_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sharps/packaging-specs/{packaging_spec_id}", None, headers
        )

    def list_packaging_specs(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/packaging-specs", params, headers)

    # ------------------------------------------------------------------
    # Treatment facilities (PRD 3.1)
    # ------------------------------------------------------------------
    def create_treatment_facility(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/treatment-facilities", payload, headers)

    def get_treatment_facility(self, facility_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sharps/treatment-facilities/{facility_id}", None, headers
        )

    def list_treatment_facilities(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/sharps/treatment-facilities", params, headers)

    def treatment_facility_status_action(
        self, facility_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sharps/treatment-facilities/{facility_id}/status-actions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Sponsors and sponsorship programs (PRD 3.2)
    # ------------------------------------------------------------------
    def create_sponsor(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/sponsors/{sponsor_id}", None, headers)

    def list_sponsors(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/sponsors", params, headers)

    def sponsor_status_action(
        self, sponsor_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/sponsors/{sponsor_id}/status-actions", payload, headers
        )

    def create_sponsorship_program(
        self, sponsor_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/sponsors/{sponsor_id}/programs", payload, headers
        )

    def list_sponsor_programs(
        self, sponsor_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/sharps/sponsors/{sponsor_id}/programs", params, headers
        )

    def get_sponsorship_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/programs/{program_id}", None, headers)

    def list_sponsorship_programs(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/sharps/programs", params, headers)

    def create_funding_adjustment(
        self, program_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/programs/{program_id}/funding-adjustments", payload, headers
        )

    # ------------------------------------------------------------------
    # Sponsor ledger (PRD 3.2)
    # ------------------------------------------------------------------
    def get_ledger_entry(self, ledger_entry_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sharps/ledger-entries/{ledger_entry_id}", None, headers
        )

    def list_ledger_entries(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/ledger-entries", params, headers)

    # ------------------------------------------------------------------
    # Patients (PRD 3.3, 3.9)
    # ------------------------------------------------------------------
    def create_patient(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/patients/{patient_id}", None, headers)

    def list_patients(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/patients", params, headers)

    def review_patient_eligibility(
        self, patient_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/patients/{patient_id}/eligibility-review", payload, headers
        )

    def patient_status_action(
        self, patient_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/patients/{patient_id}/status-actions", payload, headers
        )

    # ------------------------------------------------------------------
    # Enrollments (PRD 3.3)
    # ------------------------------------------------------------------
    def create_enrollment(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/enrollments/{enrollment_id}", None, headers)

    def list_enrollments(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/enrollments", params, headers)

    def submit_enrollment(
        self, enrollment_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/sharps/enrollments/{enrollment_id}/submit", payload or {}, headers
        )

    def record_sponsor_decision(
        self, enrollment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sharps/enrollments/{enrollment_id}/sponsor-decision",
            payload,
            headers,
        )

    def issue_kit(self, enrollment_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sharps/enrollments/{enrollment_id}/kits", payload, headers
        )

    # ------------------------------------------------------------------
    # Kits (PRD 3.4, 3.5)
    # ------------------------------------------------------------------
    def get_kit(self, kit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/kits/{kit_id}", None, headers)

    def list_kits(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/kits", params, headers)

    def acknowledge_kit_receipt(
        self, kit_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        return self._request(
            "POST", f"/sharps/kits/{kit_id}/acknowledge-receipt", payload or {}, headers
        )

    def seal_kit(self, kit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/sharps/kits/{kit_id}/seal", payload, headers)

    def void_kit(self, kit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/sharps/kits/{kit_id}/void", payload, headers)

    def print_return_label(self, kit_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/sharps/kits/{kit_id}/return-labels", payload, headers
        )

    # ------------------------------------------------------------------
    # Return labels (PRD 3.6)
    # ------------------------------------------------------------------
    def get_return_label(self, return_label_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sharps/return-labels/{return_label_id}", None, headers
        )

    def list_return_labels(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/return-labels", params, headers)

    def activate_return_label(
        self, return_label_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/return-labels/{return_label_id}/activate", payload, headers
        )

    def void_return_label(
        self, return_label_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/return-labels/{return_label_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Shipments (PRD 3.6, 3.7)
    # ------------------------------------------------------------------
    def get_shipment(self, shipment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/shipments/{shipment_id}", None, headers)

    def list_shipments(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/shipments", params, headers)

    def record_transport_event(
        self, shipment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sharps/shipments/{shipment_id}/transport-events", payload, headers
        )

    def screen_shipment_conformance(
        self, shipment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sharps/shipments/{shipment_id}/conformance-screening",
            payload,
            headers,
        )

    def list_shipment_non_conformance_events(
        self, shipment_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/sharps/shipments/{shipment_id}/non-conformance-events",
            params,
            headers,
        )

    def issue_destruction_certificate(
        self, shipment_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sharps/shipments/{shipment_id}/destruction-certificates",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Non-conformance events (PRD 3.7)
    # ------------------------------------------------------------------
    def get_non_conformance_event(self, event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sharps/non-conformance-events/{event_id}", None, headers
        )

    def list_non_conformance_events(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/sharps/non-conformance-events", params, headers)

    def notify_customer(self, event_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/sharps/non-conformance-events/{event_id}/notify-customer",
            payload,
            headers,
        )

    def remediate_non_conformance(
        self, event_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sharps/non-conformance-events/{event_id}/remediate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Destruction certificates (PRD 3.8)
    # ------------------------------------------------------------------
    def get_destruction_certificate(self, certificate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sharps/destruction-certificates/{certificate_id}", None, headers
        )

    def list_destruction_certificates(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        return self._request("GET", "/sharps/destruction-certificates", params, headers)

    def void_destruction_certificate(
        self, certificate_id: str, payload: dict, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sharps/destruction-certificates/{certificate_id}/void",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Auto-ship runs (PRD 3.9)
    # ------------------------------------------------------------------
    def create_auto_ship_run(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/sharps/auto-ship-runs", payload, headers)

    def get_auto_ship_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/sharps/auto-ship-runs/{run_id}", None, headers)

    def list_auto_ship_runs(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/sharps/auto-ship-runs", params, headers)

    # ------------------------------------------------------------------
    # Generic escape hatch for role-matrix sweeps
    # ------------------------------------------------------------------
    def call(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        payload: Any = None,
    ):
        return self._request(method, path, payload, headers)


api_client = ApiClient()
