"""API client: one method per endpoint defined in the PRD.

Money values are always sent and read as integer cents rendered as JSON numbers,
never as strings. Timestamp comparisons go through :func:`canonical_iso` so that
tests compare instants rather than raw fractional-second string widths.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def canonical_iso(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO 8601 UTC timestamp for equality comparison.

    Accepts a trailing ``Z`` or an explicit offset and any fractional-second
    width, and returns a single canonical rendering with millisecond precision.
    Returns ``None`` unchanged so optional timestamp fields can be compared
    directly.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware :class:`datetime`."""
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ApiClient(GenericApiClient):
    """One method per row of the PRD's endpoint table."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------------- leagues
    def create_league(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    def set_league_sanctioning_status(
        self, league_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/leagues/{league_id}/sanctioning-status", payload, headers
        )

    # -------------------------------------------------- sport classifications
    def create_sport_classification(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/sport-classifications", payload, headers)

    def get_sport_classification(
        self, sport_classification_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/sport-classifications/{sport_classification_id}", headers=headers
        )

    def list_sport_classifications(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/sport-classifications", headers=headers, params=params
        )

    # ------------------------------------------------------- league policies
    def create_league_policy(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/league-policies", payload, headers)

    def get_league_policy(self, league_policy_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league-policies/{league_policy_id}", headers=headers
        )

    def list_league_policies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/league-policies", headers=headers, params=params)

    def bind_league_policy(
        self,
        league_policy_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/league-policies/{league_policy_id}/bind", payload or {}, headers
        )

    def activate_league_policy(
        self,
        league_policy_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/league-policies/{league_policy_id}/activate",
            payload or {},
            headers,
        )

    def run_off_league_policy(
        self,
        league_policy_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/league-policies/{league_policy_id}/run-off",
            payload or {},
            headers,
        )

    def cancel_league_policy(
        self,
        league_policy_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/league-policies/{league_policy_id}/cancel", payload or {}, headers
        )

    def create_renewal_quote(
        self, league_policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/league-policies/{league_policy_id}/renewal-quote", payload, headers
        )

    def accept_renewal_quote(
        self,
        league_policy_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/league-policies/{league_policy_id}/renewal-acceptance",
            payload or {},
            headers,
        )

    def get_loss_experience(self, league_policy_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/league-policies/{league_policy_id}/loss-experience", headers=headers
        )

    # ---------------------------------------------------------- participants
    def create_participant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/participants", headers=headers, params=params)

    # ----------------------------------------------------------- enrollments
    def create_enrollment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def withdraw_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/withdraw", payload, headers
        )

    # ---------------------------------------------------- family health plans
    def create_family_health_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/family-health-plans", payload, headers)

    def get_family_health_plan(
        self, family_health_plan_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/family-health-plans/{family_health_plan_id}", headers=headers
        )

    def list_family_health_plans(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/family-health-plans", headers=headers, params=params
        )

    def verify_family_health_plan(
        self, family_health_plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/family-health-plans/{family_health_plan_id}/verification",
            payload,
            headers,
        )

    # -------------------------------------------------- sanctioned activities
    def create_sanctioned_activity(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/sanctioned-activities", payload, headers)

    def get_sanctioned_activity(
        self, sanctioned_activity_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/sanctioned-activities/{sanctioned_activity_id}", headers=headers
        )

    def list_sanctioned_activities(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/sanctioned-activities", headers=headers, params=params
        )

    def record_sanction_decision(
        self, sanctioned_activity_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/sanctioned-activities/{sanctioned_activity_id}/sanction-decision",
            payload,
            headers,
        )

    # -------------------------------------------------------- injury reports
    def create_injury_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/injury-reports", payload, headers)

    def get_injury_report(self, injury_report_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/injury-reports/{injury_report_id}", headers=headers
        )

    def list_injury_reports(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/injury-reports", headers=headers, params=params)

    def return_injury_report_for_correction(
        self, injury_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/injury-reports/{injury_report_id}/return-for-correction",
            payload,
            headers,
        )

    def resubmit_injury_report(
        self, injury_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/injury-reports/{injury_report_id}/resubmit", payload, headers
        )

    def record_verification_decision(
        self, injury_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/injury-reports/{injury_report_id}/verification-decision",
            payload,
            headers,
        )

    # ---------------------------------------------------------------- claims
    def get_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def request_eob(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claims/{claim_id}/request-eob", payload, headers
        )

    def confirm_no_other_coverage(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claims/{claim_id}/confirm-no-other-coverage", payload, headers
        )

    def certify_catastrophic(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claims/{claim_id}/cat-certification", payload, headers
        )

    def revoke_catastrophic_certification(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/claims/{claim_id}/cat-certification-revocation", payload, headers
        )

    def adjudicate_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/claims/{claim_id}/adjudicate", payload, headers)

    def withdraw_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/claims/{claim_id}/withdraw", payload, headers)

    # --------------------------------------------------------- provider bills
    def create_provider_bill(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/provider-bills", payload, headers)

    def get_provider_bill(self, provider_bill_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/provider-bills/{provider_bill_id}", headers=headers
        )

    def list_provider_bills(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/provider-bills", headers=headers, params=params)

    def reprice_provider_bill(
        self,
        provider_bill_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/provider-bills/{provider_bill_id}/reprice", payload or {}, headers
        )

    def void_provider_bill(
        self, provider_bill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/provider-bills/{provider_bill_id}/void", payload, headers
        )

    # ---------------------------------------------------- coordination records
    def create_coordination_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/coordination-records", payload, headers)

    def get_coordination_record(
        self, coordination_record_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/coordination-records/{coordination_record_id}", headers=headers
        )

    def list_coordination_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/coordination-records", headers=headers, params=params
        )

    # -------------------------------------------------------- benefit payments
    def create_benefit_payment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/benefit-payments", payload, headers)

    def get_benefit_payment(self, benefit_payment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/benefit-payments/{benefit_payment_id}", headers=headers
        )

    def list_benefit_payments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/benefit-payments", headers=headers, params=params)

    def void_benefit_payment(
        self, benefit_payment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/benefit-payments/{benefit_payment_id}/void", payload, headers
        )


api_client = ApiClient()
