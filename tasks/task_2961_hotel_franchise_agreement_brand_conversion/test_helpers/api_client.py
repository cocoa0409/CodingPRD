"""One method per endpoint in the Hotel Franchise Conversion API (PRD §4).

Also holds the single place where ISO-8601 instants are canonicalised.  The
PRD renders every instant with exactly three fractional digits, but a test
that has to compare an instant should not care whether an implementation
emitted ``...T00:00:00Z`` or ``...T00:00:00.000Z``; :func:`canonical_instant`
normalises both to the millisecond form so no individual test has to.
"""

import re
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Render an ISO-8601 UTC instant as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Sub-second digits are padded or truncated to exactly three so instants
    that denote the same moment compare equal regardless of how many
    fractional digits the wire format carried.  Non-instant values (including
    ``None`` and plain ``YYYY-MM-DD`` dates) are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    day, clock, fraction, offset = match.groups()
    if offset != "Z":
        return value
    millis = (fraction or "")[:3].ljust(3, "0")
    return f"{day}T{clock}.{millis}Z"


class ApiClient(GenericApiClient):
    """Typed access to every documented route."""

    # ─── Logical clock (PRD §2.4) ─────────────────────────────────────

    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Brands and existing units (PRD §3.1) ─────────────────────────

    def create_brand(self, payload: dict, headers: dict):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id: str, headers: dict):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def list_brand_existing_units(self, brand_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/brands/{brand_id}/existing-units", headers=headers, params=params
        )

    def create_existing_unit(self, payload: dict, headers: dict):
        return self._request("POST", "/existing-units", payload, headers)

    def change_existing_unit_status(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/existing-units/{unit_id}/status", payload, headers
        )

    # ─── Owners (PRD §3.2) ────────────────────────────────────────────

    def create_owner(self, payload: dict, headers: dict):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: dict):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def update_owner_financial_profile(self, owner_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/owners/{owner_id}/financial-profile", payload, headers
        )

    # ─── Applications (PRD §3.3) ──────────────────────────────────────

    def create_application(self, payload: dict, headers: dict):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str, headers: dict):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers: dict, params: dict = None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def start_application_review(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/start-review", payload, headers
        )

    def record_financial_review(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/financial-review", payload, headers
        )

    def request_application_revision(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/request-revision", payload, headers
        )

    def resubmit_application(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/resubmit", payload, headers
        )

    def decide_application(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/decision", payload, headers
        )

    # ─── Impact study and encroachment claims (PRD §3.4) ──────────────

    def run_impact_analysis(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/impact-analysis", payload, headers
        )

    def finalize_impact(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/finalize-impact", payload, headers
        )

    def file_encroachment_claim(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/applications/{application_id}/encroachment-claims",
            payload,
            headers,
        )

    def get_encroachment_claim(self, claim_id: str, headers: dict):
        return self._request("GET", f"/encroachment-claims/{claim_id}", headers=headers)

    def list_encroachment_claims(self, headers: dict, params: dict = None):
        return self._request(
            "GET", "/encroachment-claims", headers=headers, params=params
        )

    def resolve_encroachment_claim(self, claim_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/encroachment-claims/{claim_id}/resolve", payload, headers
        )

    # ─── License agreements (PRD §3.6) ────────────────────────────────

    def draft_agreement(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/agreements", payload, headers
        )

    def list_application_agreements(self, application_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET",
            f"/applications/{application_id}/agreements",
            headers=headers,
            params=params,
        )

    def get_agreement(self, agreement_id: str, headers: dict):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def execute_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/execute", payload, headers
        )

    def advance_onboarding_milestone(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/onboarding-milestone", payload, headers
        )

    def open_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/open", payload, headers
        )

    # ─── Property improvement plans (PRD §3.7) ────────────────────────

    def create_pip(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/pips", payload, headers
        )

    def list_agreement_pips(self, agreement_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET", f"/agreements/{agreement_id}/pips", headers=headers, params=params
        )

    def get_pip(self, pip_id: str, headers: dict):
        return self._request("GET", f"/pips/{pip_id}", headers=headers)

    def create_pip_item(self, pip_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/pips/{pip_id}/items", payload, headers)

    def list_pip_items(self, pip_id: str, headers: dict, params: dict = None):
        return self._request("GET", f"/pips/{pip_id}/items", headers=headers, params=params)

    def accept_pip(self, pip_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/pips/{pip_id}/accept", payload, headers)

    def run_compliance_sweep(self, pip_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/pips/{pip_id}/compliance-sweep", payload, headers
        )

    def complete_pip_item(self, item_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/pip-items/{item_id}/complete", payload, headers
        )

    def verify_pip_item(self, item_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/pip-items/{item_id}/verify", payload, headers)

    def request_pip_item_extension(self, item_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/pip-items/{item_id}/extension-request", payload, headers
        )

    def decide_pip_item_extension(self, item_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/pip-items/{item_id}/extension-decision", payload, headers
        )

    # ─── Fee ledger and quality assurance (PRD §3.8) ──────────────────

    def report_revenue(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/revenue-reports", payload, headers
        )

    def get_fee_summary(self, agreement_id: str, headers: dict):
        return self._request(
            "GET", f"/agreements/{agreement_id}/fee-summary", headers=headers
        )

    def create_qa_inspection(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/qa-inspections", payload, headers
        )

    def list_agreement_qa_inspections(self, agreement_id: str, headers: dict, params: dict = None):
        return self._request(
            "GET",
            f"/agreements/{agreement_id}/qa-inspections",
            headers=headers,
            params=params,
        )

    def submit_inspection_cure(self, inspection_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/qa-inspections/{inspection_id}/cure-submission", payload, headers
        )

    def review_inspection_cure(self, inspection_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/qa-inspections/{inspection_id}/cure-review", payload, headers
        )

    # ─── Consent, termination and close-out (PRD §3.9) ────────────────

    def file_transfer_request(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/transfer-requests", payload, headers
        )

    def get_transfer_request(self, request_id: str, headers: dict):
        return self._request("GET", f"/transfer-requests/{request_id}", headers=headers)

    def list_transfer_requests(self, headers: dict, params: dict = None):
        return self._request("GET", "/transfer-requests", headers=headers, params=params)

    def decide_transfer_request(self, request_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/transfer-requests/{request_id}/decide", payload, headers
        )

    def terminate_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/terminate", payload, headers
        )

    def certify_de_identification(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/de-identification", payload, headers
        )

    def close_out_agreement(self, agreement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/agreements/{agreement_id}/close-out", payload, headers
        )
