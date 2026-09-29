"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cosmetology"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    The PRD renders instants with three fractional digits, but a payload may be
    supplied with none (``2026-08-01T00:00:00Z``).  Comparing a sent literal to
    a returned literal therefore needs the two put in the same shape first.
    """
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Cosmetology Board Compliance API."""

    # --- Reference registries -------------------------------------------
    def create_violation_code(self, payload, headers):
        return self._request("POST", f"{PREFIX}/violation-codes", payload, headers)

    def get_violation_code(self, violation_code_id, headers):
        return self._request(
            "GET", f"{PREFIX}/violation-codes/{violation_code_id}", headers=headers
        )

    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    # --- Practitioners and training -------------------------------------
    def create_practitioner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/practitioners", payload, headers)

    def get_practitioner(self, practitioner_id, headers):
        return self._request(
            "GET", f"{PREFIX}/practitioners/{practitioner_id}", headers=headers
        )

    def list_practitioners(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/practitioners", headers=headers, params=params
        )

    def apply_license_action(self, practitioner_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/practitioners/{practitioner_id}/license-actions",
            payload,
            headers,
        )

    def create_training_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-records", payload, headers)

    def get_training_record(self, training_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/training-records/{training_record_id}", headers=headers
        )

    def list_training_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/training-records", headers=headers, params=params
        )

    # --- Establishments and build-out -----------------------------------
    def create_establishment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/establishments", payload, headers)

    def get_establishment(self, establishment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/establishments/{establishment_id}", headers=headers
        )

    def list_establishments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/establishments", headers=headers, params=params
        )

    def create_workstation(self, establishment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/establishments/{establishment_id}/workstations",
            payload,
            headers,
        )

    def get_workstation(self, workstation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/workstations/{workstation_id}", headers=headers
        )

    def list_workstations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/workstations", headers=headers, params=params
        )

    def post_licence_at_workstation(self, workstation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/workstations/{workstation_id}/posting", payload, headers
        )

    def list_workstation_sanitation_logs(self, workstation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/workstations/{workstation_id}/sanitation-logs",
            headers=headers,
            params=params,
        )

    # --- Booth rentals ---------------------------------------------------
    def create_booth_rental(self, payload, headers):
        return self._request("POST", f"{PREFIX}/booth-rentals", payload, headers)

    def get_booth_rental(self, booth_rental_id, headers):
        return self._request(
            "GET", f"{PREFIX}/booth-rentals/{booth_rental_id}", headers=headers
        )

    def list_booth_rentals(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/booth-rentals", headers=headers, params=params
        )

    def activate_booth_rental(self, booth_rental_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/booth-rentals/{booth_rental_id}/activation",
            payload if payload is not None else {},
            headers,
        )

    def terminate_booth_rental(self, booth_rental_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/booth-rentals/{booth_rental_id}/termination",
            payload if payload is not None else {},
            headers,
        )

    # --- Sanitation ------------------------------------------------------
    def create_sanitation_log(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sanitation-logs", payload, headers)

    # --- Inspections -----------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/inspections", headers=headers, params=params
        )

    def start_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def create_finding(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/findings", payload, headers
        )

    def submit_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def finalize_inspection(self, inspection_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/finalize",
            payload if payload is not None else {},
            headers,
        )

    def declare_hazard(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/hazard-declaration",
            payload,
            headers,
        )

    def clear_hazard(self, inspection_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/inspections/{inspection_id}/hazard-clearance",
            payload,
            headers,
        )

    def get_violation_finding(self, violation_finding_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/violation-findings/{violation_finding_id}",
            headers=headers,
        )

    def list_violation_findings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/violation-findings", headers=headers, params=params
        )

    # --- Citations, hearings, payments -----------------------------------
    def create_citation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"{PREFIX}/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/citations", headers=headers, params=params
        )

    def contest_citation(self, citation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/citations/{citation_id}/contest", payload, headers
        )

    def schedule_hearing(self, citation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/citations/{citation_id}/hearings", payload, headers
        )

    def list_citation_hearings(self, citation_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/citations/{citation_id}/hearings",
            headers=headers,
            params=params,
        )

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"{PREFIX}/hearings/{hearing_id}", headers=headers)

    def record_hearing_decision(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hearings/{hearing_id}/decision", payload, headers
        )

    def pay_citation(self, citation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/citations/{citation_id}/payments", payload, headers
        )

    # --- Infection incidents ---------------------------------------------
    def create_infection_incident(self, payload, headers):
        return self._request("POST", f"{PREFIX}/infection-incidents", payload, headers)

    def get_infection_incident(self, incident_id, headers):
        return self._request(
            "GET", f"{PREFIX}/infection-incidents/{incident_id}", headers=headers
        )

    def list_infection_incidents(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/infection-incidents", headers=headers, params=params
        )

    def notify_infection_incident(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/infection-incidents/{incident_id}/notification",
            payload,
            headers,
        )

    def resolve_infection_incident(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/infection-incidents/{incident_id}/resolution",
            payload,
            headers,
        )

    # --- Ledger ----------------------------------------------------------
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ledger-entries/{ledger_entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ledger-entries", headers=headers, params=params
        )

    # --- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
