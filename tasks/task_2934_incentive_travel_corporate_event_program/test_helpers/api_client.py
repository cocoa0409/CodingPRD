"""API client: one method per endpoint defined in the PRD (§4).

Every collection is mounted at the URL root, so no path nests another
resource's id (PRD §2.11).
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant so sub-second width never breaks a compare.

    The API renders instants with three fractional digits (PRD §2.4); test
    literals are usually written without them. Both forms normalise to the same
    whole-second string here so tests compare instants, not spellings.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        text = text[: text.index(".")]
    return text + "Z"


class ApiClient(GenericApiClient):
    """PRD endpoint surface. All monetary values are integers in whole cents."""

    # ── Program ─────────────────────────────────────────────────────────────
    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def advance_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/advance", payload, headers)

    def set_gross_up_policy(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/gross-up-policy", payload, headers)

    def notify_qualifiers(self, program_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/programs/{program_id}/notify-qualifiers", payload, headers)

    def cancel_program(self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/programs/{program_id}/cancel", payload, headers)

    def get_program_measurement(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/programs/{program_id}/measurement", headers=headers)

    # ── AwardTier ───────────────────────────────────────────────────────────
    def create_award_tier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/award-tiers", payload, headers)

    def get_award_tier(self, tier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/award-tiers/{tier_id}", headers=headers)

    def list_award_tiers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/award-tiers", headers=headers, params=params)

    # ── Qualifier ───────────────────────────────────────────────────────────
    def create_qualifier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/qualifiers", payload, headers)

    def get_qualifier(self, qualifier_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/qualifiers/{qualifier_id}", headers=headers)

    def list_qualifiers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/qualifiers", headers=headers, params=params)

    def review_qualifier(self, qualifier_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/qualifiers/{qualifier_id}/review", payload, headers)

    # ── Destination ─────────────────────────────────────────────────────────
    def create_destination(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/destinations", payload, headers)

    def get_destination(self, destination_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/destinations/{destination_id}", headers=headers)

    def list_destinations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/destinations", headers=headers, params=params)

    def site_inspect_destination(self, destination_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/destinations/{destination_id}/site-inspection", payload, headers
        )

    def shortlist_destination(self, destination_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/destinations/{destination_id}/shortlist", payload, headers
        )

    # ── SupplierContract ────────────────────────────────────────────────────
    def create_supplier_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/supplier-contracts", payload, headers)

    def get_supplier_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/supplier-contracts/{contract_id}", headers=headers)

    def list_supplier_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/supplier-contracts", headers=headers, params=params)

    def negotiate_contract(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/supplier-contracts/{contract_id}/negotiate", payload, headers
        )

    def execute_contract(self, contract_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/supplier-contracts/{contract_id}/execute", payload, headers
        )

    def withdraw_contract(self, contract_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/supplier-contracts/{contract_id}/withdraw", payload, headers
        )

    def get_exposure_projection(self, contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/supplier-contracts/{contract_id}/exposure-projection", headers=headers
        )

    # ── DepositMilestone ────────────────────────────────────────────────────
    def create_deposit_milestone(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/deposit-milestones", payload, headers)

    def get_deposit_milestone(self, milestone_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/deposit-milestones/{milestone_id}", headers=headers)

    def list_deposit_milestones(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/deposit-milestones", headers=headers, params=params)

    def pay_deposit_milestone(self, milestone_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/deposit-milestones/{milestone_id}/pay", payload, headers
        )

    # ── Registration ────────────────────────────────────────────────────────
    def create_registration(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def respond_registration(self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/registrations/{registration_id}/respond", payload, headers
        )

    def confirm_registration(self, registration_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/registrations/{registration_id}/confirm", payload, headers
        )

    def cancel_registration(self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/registrations/{registration_id}/cancel", payload, headers
        )

    def air_registration(self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/registrations/{registration_id}/air", payload, headers)

    def survey_registration(self, registration_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/registrations/{registration_id}/survey", payload, headers
        )

    # ── OnsiteActivity ──────────────────────────────────────────────────────
    def create_onsite_activity(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/onsite-activities", payload, headers)

    def get_onsite_activity(self, activity_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/onsite-activities/{activity_id}", headers=headers)

    def list_onsite_activities(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/onsite-activities", headers=headers, params=params)

    def close_onsite_activity(self, activity_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/onsite-activities/{activity_id}/close", payload, headers
        )

    # ── ActivitySignup ──────────────────────────────────────────────────────
    def create_activity_signup(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/activity-signups", payload, headers)

    def get_activity_signup(self, signup_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/activity-signups/{signup_id}", headers=headers)

    def list_activity_signups(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/activity-signups", headers=headers, params=params)

    def cancel_activity_signup(self, signup_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request(
            "POST", f"/activity-signups/{signup_id}/cancel", payload, headers
        )

    # ── TaxAwardReport ──────────────────────────────────────────────────────
    def create_tax_award_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/tax-award-reports", payload, headers)

    def get_tax_award_report(self, report_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tax-award-reports/{report_id}", headers=headers)

    def list_tax_award_reports(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/tax-award-reports", headers=headers, params=params)

    def file_tax_award_report(self, report_id: str, headers: Dict[str, str], payload: Any = None):
        return self._request("POST", f"/tax-award-reports/{report_id}/file", payload, headers)

    def void_tax_award_report(self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/tax-award-reports/{report_id}/void", payload, headers)

    # ── Logical clock (PRD §2.5) ────────────────────────────────────────────
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
