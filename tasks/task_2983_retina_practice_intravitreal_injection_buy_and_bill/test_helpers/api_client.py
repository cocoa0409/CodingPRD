"""
Domain API client: exactly one method per endpoint declared in the PRD's
endpoint catalogue.

Every method returns the raw ``requests.Response`` so a test can assert on the
HTTP status code as well as the envelope.  Nothing here interprets the response;
validation lives in ``assertions.py`` and in the framework validators.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """
    Normalise an ISO-8601 UTC instant to second precision with a ``Z`` suffix.

    The contract permits a trailing fractional-second component, so two spellings
    of the same instant ("...T09:00:00Z" and "...T09:00:00.000Z") must compare
    equal.  Comparisons in tests go through this function on both sides.
    """
    if value is None:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        text = text[: text.index(".")]
    return text + "Z"


class ApiClient(GenericApiClient):
    """One method per endpoint of the retina buy-and-bill contract."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Payers
    # ------------------------------------------------------------------
    def create_payer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/payers", payload, headers)

    def get_payer(self, payer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/payers/{payer_id}", None, headers)

    def list_payers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/payers", params, headers)

    # ------------------------------------------------------------------
    # Drugs
    # ------------------------------------------------------------------
    def create_drug(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/drugs", payload, headers)

    def get_drug(self, drug_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/drugs/{drug_id}", None, headers)

    def list_drugs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/drugs", params, headers)

    # ------------------------------------------------------------------
    # Payer drug policies
    # ------------------------------------------------------------------
    def create_payer_drug_policy(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/payer-drug-policies", payload, headers)

    def get_payer_drug_policy(self, policy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/payer-drug-policies/{policy_id}", None, headers)

    def list_payer_drug_policies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/payer-drug-policies", params, headers)

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/patients/{patient_id}", None, headers)

    def list_patients(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/patients", params, headers)

    # ------------------------------------------------------------------
    # Clinicians
    # ------------------------------------------------------------------
    def create_clinician(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/clinicians/{clinician_id}", None, headers)

    def list_clinicians(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/clinicians", params, headers)

    def suspend_clinician(
        self, clinician_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/clinicians/{clinician_id}/suspend", payload, headers)

    # ------------------------------------------------------------------
    # Imaging studies
    # ------------------------------------------------------------------
    def create_imaging_study(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/imaging-studies", payload, headers)

    def get_imaging_study(self, study_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/imaging-studies/{study_id}", None, headers)

    def list_imaging_studies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/imaging-studies", params, headers)

    # ------------------------------------------------------------------
    # Treatment plans
    # ------------------------------------------------------------------
    def create_treatment_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/treatment-plans", payload, headers)

    def get_treatment_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/treatment-plans/{plan_id}", None, headers)

    def list_treatment_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/treatment-plans", params, headers)

    def activate_treatment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/treatment-plans/{plan_id}/activate", payload, headers)

    def suspend_treatment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/treatment-plans/{plan_id}/suspend", payload, headers)

    def resume_treatment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/treatment-plans/{plan_id}/resume", payload, headers)

    def discontinue_treatment_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/treatment-plans/{plan_id}/discontinue", payload, headers)

    # ------------------------------------------------------------------
    # Drug lots and inventory
    # ------------------------------------------------------------------
    def create_drug_lot(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/drug-lots", payload, headers)

    def get_drug_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/drug-lots/{lot_id}", None, headers)

    def list_drug_lots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/drug-lots", params, headers)

    def get_drug_lot_exposure(
        self, lot_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/drug-lots/{lot_id}/exposure", params, headers)

    def quarantine_drug_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/drug-lots/{lot_id}/quarantine", payload, headers)

    def release_drug_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/drug-lots/{lot_id}/release", payload, headers)

    def run_expiration_sweep(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/inventory/expiration-sweep", payload, headers)

    # ------------------------------------------------------------------
    # Vials
    # ------------------------------------------------------------------
    def get_vial(self, vial_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/vials/{vial_id}", None, headers)

    def list_vials(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/vials", params, headers)

    # ------------------------------------------------------------------
    # Prior authorizations
    # ------------------------------------------------------------------
    def create_prior_authorization(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/prior-authorizations", payload, headers)

    def get_prior_authorization(self, pa_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/prior-authorizations/{pa_id}", None, headers)

    def list_prior_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/prior-authorizations", params, headers)

    def submit_prior_authorization(
        self, pa_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/prior-authorizations/{pa_id}/submit", payload, headers)

    def decide_prior_authorization(
        self, pa_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/prior-authorizations/{pa_id}/decision", payload, headers)

    def appeal_prior_authorization(
        self, pa_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/prior-authorizations/{pa_id}/appeal", payload, headers)

    # ------------------------------------------------------------------
    # Injection encounters
    # ------------------------------------------------------------------
    def create_injection_encounter(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/injection-encounters", payload, headers)

    def get_injection_encounter(
        self, encounter_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/injection-encounters/{encounter_id}", None, headers)

    def list_injection_encounters(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/injection-encounters", params, headers)

    def document_injection_encounter(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/injection-encounters/{encounter_id}/document", payload, headers
        )

    def attest_wastage(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/injection-encounters/{encounter_id}/attest-wastage", payload, headers
        )

    def void_injection_encounter(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/injection-encounters/{encounter_id}/void", payload, headers
        )

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/claims/{claim_id}", None, headers)

    def list_claims(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/claims", params, headers)

    def submit_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/claims/{claim_id}/submit", payload, headers)

    def post_remittance(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/claims/{claim_id}/remittance", payload, headers)

    def appeal_drug_line(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/claims/{claim_id}/appeal-drug-line", payload, headers)

    # ------------------------------------------------------------------
    # Assistance enrollments
    # ------------------------------------------------------------------
    def create_assistance_enrollment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/assistance-enrollments", payload, headers)

    def get_assistance_enrollment(
        self, enrollment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/assistance-enrollments/{enrollment_id}", None, headers)

    def list_assistance_enrollments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/assistance-enrollments", params, headers)

    def approve_assistance_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assistance-enrollments/{enrollment_id}/approve", payload, headers
        )

    def terminate_assistance_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/assistance-enrollments/{enrollment_id}/terminate", payload, headers
        )

    # ------------------------------------------------------------------
    # Adverse events
    # ------------------------------------------------------------------
    def create_adverse_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/adverse-events", payload, headers)

    def get_adverse_event(self, event_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/adverse-events/{event_id}", None, headers)

    def list_adverse_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/adverse-events", params, headers)

    def start_adverse_event_investigation(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/adverse-events/{event_id}/start-investigation", payload, headers
        )

    def adjudicate_adverse_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/adverse-events/{event_id}/adjudicate", payload, headers)

    # ------------------------------------------------------------------
    # Lot recalls
    # ------------------------------------------------------------------
    def create_lot_recall(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/lot-recalls", payload, headers)

    def get_lot_recall(self, recall_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/lot-recalls/{recall_id}", None, headers)

    def list_lot_recalls(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/lot-recalls", params, headers)

    def send_recall_notifications(
        self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/lot-recalls/{recall_id}/send-notifications", payload, headers
        )

    def ship_recall_return(
        self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/lot-recalls/{recall_id}/ship-return", payload, headers)

    def reconcile_recall_credit(
        self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/lot-recalls/{recall_id}/reconcile-credit", payload, headers
        )

    def close_lot_recall(
        self, recall_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/lot-recalls/{recall_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Recall notifications
    # ------------------------------------------------------------------
    def get_recall_notification(
        self, notification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/recall-notifications/{notification_id}", None, headers)

    def list_recall_notifications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/recall-notifications", params, headers)

    def acknowledge_recall_notification(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-notifications/{notification_id}/acknowledge", payload, headers
        )

    def mark_recall_notification_unreachable(
        self, notification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/recall-notifications/{notification_id}/mark-unreachable", payload, headers
        )
