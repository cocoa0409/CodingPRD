"""API client: one method per endpoint defined in PRD section 4.

Every domain endpoint is mounted under the `/identity-protection` prefix.
The single exception is the platform logical-clock endpoint, which lives at
exactly `/_clock/set_current_utc` OUTSIDE the prefix (PRD section 2.4) — it is
deliberately not prefixed here.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Identity Protection & Return Fraud API client (PRD section 4)."""

    # ─── Platform clock (OUTSIDE the /identity-protection prefix) ──

    def set_clock(self, payload: dict, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc — platform endpoint, NOT prefixed
        (PRD section 2.4: "mounted outside the API prefix at exactly
        `/_clock/set_current_utc`")."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Taxpayers (PRD section 3.1) ───────────────────────────────

    def create_taxpayer(self, payload, headers):
        return self._request("POST", "/identity-protection/taxpayers", payload, headers)

    def get_taxpayer(self, taxpayer_id, headers):
        return self._request("GET", f"/identity-protection/taxpayers/{taxpayer_id}", headers=headers)

    def update_taxpayer(self, taxpayer_id, payload, headers):
        """PUT taxpayer profile — OCC-guarded on expected_taxpayer_version
        (PRD section 2.7)."""
        return self._request("PUT", f"/identity-protection/taxpayers/{taxpayer_id}", payload, headers)

    def opt_in_ip_pin(self, taxpayer_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/taxpayers/{taxpayer_id}/ip-pin-opt-in", payload, headers
        )

    def opt_out_ip_pin(self, taxpayer_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/taxpayers/{taxpayer_id}/ip-pin-opt-out", payload, headers
        )

    # ─── Identity theft reports (PRD section 3.3) ──────────────────

    def create_identity_theft_report(self, taxpayer_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/taxpayers/{taxpayer_id}/identity-theft-reports",
            payload, headers,
        )

    def list_identity_theft_reports(self, taxpayer_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/taxpayers/{taxpayer_id}/identity-theft-reports",
            headers=headers, params=params,
        )

    def confirm_identity_theft_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/identity-theft-reports/{report_id}/confirm",
            payload, headers,
        )

    def reject_identity_theft_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/identity-theft-reports/{report_id}/reject",
            payload, headers,
        )

    def reopen_identity_theft_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/identity-theft-reports/{report_id}/reopen",
            payload, headers,
        )

    # ─── Protection PINs (PRD section 3.2) ─────────────────────────

    def list_protection_pins(self, taxpayer_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/taxpayers/{taxpayer_id}/protection-pins",
            headers=headers, params=params,
        )

    def reissue_protection_pin(self, payload, headers):
        """POST /protection-pins — OCC-guarded on expected_taxpayer_version
        (PRD section 2.7)."""
        return self._request("POST", "/identity-protection/protection-pins", payload, headers)

    def run_annual_pin_regeneration(self, payload, headers):
        return self._request(
            "POST", "/identity-protection/ops/annual-pin-regeneration", payload, headers
        )

    # ─── Tax returns (PRD section 3.4) ─────────────────────────────

    def file_tax_return(self, payload, headers):
        return self._request("POST", "/identity-protection/tax-returns", payload, headers)

    def list_tax_returns(self, headers, params=None):
        return self._request("GET", "/identity-protection/tax-returns", headers=headers, params=params)

    def get_tax_return(self, return_id, headers):
        return self._request("GET", f"/identity-protection/tax-returns/{return_id}", headers=headers)

    def release_refund(self, return_id, headers, payload=None):
        """Schedule the refund disbursement (creates the RefundDisbursement)."""
        return self._request(
            "POST", f"/identity-protection/tax-returns/{return_id}/release-refund", payload, headers
        )

    def confirm_fraud(self, return_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/tax-returns/{return_id}/confirm-fraud", payload, headers
        )

    def list_dependent_claims(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/tax-returns/{return_id}/dependent-claims",
            headers=headers, params=params,
        )

    def list_return_filter_holds(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/tax-returns/{return_id}/filter-holds",
            headers=headers, params=params,
        )

    def list_return_disbursements(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/tax-returns/{return_id}/refund-disbursements",
            headers=headers, params=params,
        )

    # ─── Filter holds (PRD section 3.8) ────────────────────────────

    def mark_false_positive(self, hold_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/filter-holds/{hold_id}/mark-false-positive",
            payload, headers,
        )

    # ─── Identity verification cases (PRD section 3.5) ─────────────

    def create_verification_case(self, payload, headers):
        return self._request("POST", "/identity-protection/verification-cases", payload, headers)

    def list_verification_cases(self, headers, params=None):
        return self._request(
            "GET", "/identity-protection/verification-cases", headers=headers, params=params
        )

    def get_verification_case(self, case_id, headers):
        return self._request(
            "GET", f"/identity-protection/verification-cases/{case_id}", headers=headers
        )

    def request_documents(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/verification-cases/{case_id}/request-documents",
            payload, headers,
        )

    def submit_document(self, case_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/verification-cases/{case_id}/documents",
            payload, headers,
        )

    def list_documents(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/verification-cases/{case_id}/documents",
            headers=headers, params=params,
        )

    def verify_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/verification-cases/{case_id}/verify", payload, headers
        )

    def fail_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/verification-cases/{case_id}/fail", payload, headers
        )

    # ─── Service offices and appointments (PRD section 3.5) ────────

    def create_service_office(self, payload, headers):
        return self._request("POST", "/identity-protection/service-offices", payload, headers)

    def get_service_office(self, office_id, headers):
        return self._request(
            "GET", f"/identity-protection/service-offices/{office_id}", headers=headers
        )

    def book_appointment(self, office_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/service-offices/{office_id}/appointments",
            payload, headers,
        )

    def list_office_appointments(self, office_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/service-offices/{office_id}/appointments",
            headers=headers, params=params,
        )

    def list_case_appointments(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/verification-cases/{case_id}/appointments",
            headers=headers, params=params,
        )

    # ─── Dependent conflicts (PRD section 3.6) ─────────────────────

    def list_dependent_conflicts(self, headers, params=None):
        return self._request(
            "GET", "/identity-protection/dependent-conflicts", headers=headers, params=params
        )

    def get_dependent_conflict(self, conflict_id, headers):
        return self._request(
            "GET", f"/identity-protection/dependent-conflicts/{conflict_id}", headers=headers
        )

    def submit_conflict_evidence(self, conflict_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/dependent-conflicts/{conflict_id}/submit-evidence",
            payload, headers,
        )

    def resolve_dependent_conflict(self, conflict_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/dependent-conflicts/{conflict_id}/resolve",
            payload, headers,
        )

    # ─── Preparers and fraud scheme alerts (PRD section 3.7) ───────

    def create_preparer(self, payload, headers):
        return self._request("POST", "/identity-protection/preparers", payload, headers)

    def get_preparer(self, preparer_id, headers):
        return self._request("GET", f"/identity-protection/preparers/{preparer_id}", headers=headers)

    def list_preparer_alerts(self, preparer_id, headers, params=None):
        return self._request(
            "GET", f"/identity-protection/preparers/{preparer_id}/fraud-scheme-alerts",
            headers=headers, params=params,
        )

    def list_fraud_scheme_alerts(self, headers, params=None):
        return self._request(
            "GET", "/identity-protection/fraud-scheme-alerts", headers=headers, params=params
        )

    def get_fraud_scheme_alert(self, alert_id, headers):
        return self._request(
            "GET", f"/identity-protection/fraud-scheme-alerts/{alert_id}", headers=headers
        )

    def confirm_fraud_scheme_alert(self, alert_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/fraud-scheme-alerts/{alert_id}/confirm",
            payload, headers,
        )

    def clear_fraud_scheme_alert(self, alert_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/fraud-scheme-alerts/{alert_id}/clear",
            payload, headers,
        )

    # ─── Refund disbursements (PRD section 3.8) ────────────────────

    def release_disbursement(self, disbursement_id, payload, headers):
        """Execute a scheduled disbursement; payload carries
        expected_amount_cents (PRD section 3.8 money-consistency handshake)."""
        return self._request(
            "POST", f"/identity-protection/refund-disbursements/{disbursement_id}/release",
            payload, headers,
        )

    # ─── Advocate cases (PRD section 3.9) ──────────────────────────

    def create_advocate_case(self, payload, headers):
        return self._request("POST", "/identity-protection/advocate-cases", payload, headers)

    def list_advocate_cases(self, headers, params=None):
        return self._request(
            "GET", "/identity-protection/advocate-cases", headers=headers, params=params
        )

    def get_advocate_case(self, case_id, headers):
        return self._request(
            "GET", f"/identity-protection/advocate-cases/{case_id}", headers=headers
        )

    def expedite_advocate_case(self, case_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/advocate-cases/{case_id}/expedite", payload, headers
        )

    def resolve_advocate_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/identity-protection/advocate-cases/{case_id}/resolve", payload, headers
        )

    # ─── Filter model configs (PRD section 3.4) ────────────────────

    def create_filter_model_config(self, payload, headers):
        return self._request(
            "POST", "/identity-protection/filter-model-configs", payload, headers
        )

    def get_filter_model_config(self, config_id, headers):
        return self._request(
            "GET", f"/identity-protection/filter-model-configs/{config_id}", headers=headers
        )

    def activate_filter_model_config(self, config_id, headers, payload=None):
        return self._request(
            "POST", f"/identity-protection/filter-model-configs/{config_id}/activate",
            payload, headers,
        )


api_client = ApiClient()
