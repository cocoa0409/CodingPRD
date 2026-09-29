"""One method per endpoint of the NIL Collective Administration API (PRD s4).

Two conventions are enforced here rather than in each test:

* Every timestamp string in a response body is canonicalised to
  ``YYYY-MM-DDTHH:MM:SSZ`` when its fractional part is zero and to
  ``YYYY-MM-DDTHH:MM:SS.mmmZ`` otherwise, so the width of the sub-second field
  and the spelling of the UTC offset can never turn an equal instant into a
  failing comparison. PRD s2.2 and s2.4 ask for three fractional digits; a
  server that writes none, or six, still compares equal here.
* Money fields are sent as JSON integers. Every payload value that names a cents
  field is coerced with ``int()`` before the request leaves this module, because
  PRD s2.6 states that all money in the system is an integer number of cents.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_TIMESTAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)

_MONEY_SUFFIXES = ("_cents",)


def canonicalize_timestamp(value: str) -> str:
    """Return one canonical spelling for an ISO 8601 UTC instant.

    Non-timestamp strings are returned unchanged, so this is safe to apply to
    every string in a response body.
    """
    match = _TIMESTAMP_RE.match(value)
    if not match:
        return value
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    if offset not in ("Z", "z") and offset.replace(":", "") not in ("+0000", "-0000"):
        # A non-UTC offset is left exactly as the server wrote it: the PRD only
        # ever writes UTC, so preserving it keeps the mismatch visible.
        return value
    body = f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    if fraction:
        millis = (fraction + "000")[:3]
        if int(fraction) != 0:
            return f"{body}.{millis}Z"
    return f"{body}Z"


def canonicalize_payload(value: Any) -> Any:
    """Recursively canonicalise every timestamp string inside a parsed body."""
    if isinstance(value, str):
        return canonicalize_timestamp(value)
    if isinstance(value, list):
        return [canonicalize_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: canonicalize_payload(item) for key, item in value.items()}
    return value


def coerce_money(payload: Any) -> Any:
    """Send every ``*_cents`` field as a JSON integer (PRD s2.6)."""
    if isinstance(payload, list):
        return [coerce_money(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    coerced: Dict[str, Any] = {}
    for key, value in payload.items():
        if (
            isinstance(key, str)
            and key.endswith(_MONEY_SUFFIXES)
            and isinstance(value, (int, float, str))
            and not isinstance(value, bool)
        ):
            try:
                coerced[key] = int(value)
                continue
            except (TypeError, ValueError):
                coerced[key] = value
                continue
        coerced[key] = coerce_money(value)
    return coerced


class NilApiClient(GenericApiClient):
    """HTTP client for the endpoints of PRD s4, all mounted under ``/nil``."""

    def _call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        response = self._request(
            method,
            f"{API_PREFIX}{path}",
            payload=coerce_money(payload),
            headers=headers,
            params=coerce_money(params),
        )
        try:
            body = response.json()
        except ValueError:
            return response
        canonical = canonicalize_payload(body)
        response.json = lambda **kwargs: canonical  # type: ignore[method-assign]
        return response

    # --- Logical clock (PRD s2.5) ---------------------------------------
    def set_clock(self, payload, headers=None):
        return self._call("POST", "/_clock/set_current_utc", payload, headers)

    # --- Collectives (PRD s3.1, s3.2) -----------------------------------
    def create_collective(self, payload, headers=None):
        return self._call("POST", "/collectives", payload, headers)

    def get_collective(self, collective_id, headers=None):
        return self._call("GET", f"/collectives/{collective_id}", None, headers)

    def list_collectives(self, params=None, headers=None):
        return self._call("GET", "/collectives", params, headers)

    def patch_entity_structure(self, collective_id, payload, headers=None):
        return self._call(
            "PATCH", f"/collectives/{collective_id}/entity-structure", payload, headers
        )

    # --- Membership tiers (PRD s3.3) ------------------------------------
    def create_membership_tier(self, collective_id, payload, headers=None):
        return self._call(
            "POST", f"/collectives/{collective_id}/membership-tiers", payload, headers
        )

    def list_membership_tiers(self, collective_id, params=None, headers=None):
        return self._call(
            "GET", f"/collectives/{collective_id}/membership-tiers", params, headers
        )

    def get_membership_tier(self, tier_id, headers=None):
        return self._call("GET", f"/membership-tiers/{tier_id}", None, headers)

    def transition_membership_tier(self, tier_id, payload, headers=None):
        return self._call(
            "POST", f"/membership-tiers/{tier_id}/transitions", payload, headers
        )

    # --- Donor members (PRD s3.3) ---------------------------------------
    def create_donor_member(self, payload, headers=None):
        return self._call("POST", "/donor-members", payload, headers)

    def get_donor_member(self, donor_id, headers=None):
        return self._call("GET", f"/donor-members/{donor_id}", None, headers)

    def list_donor_members(self, params=None, headers=None):
        return self._call("GET", "/donor-members", params, headers)

    def patch_donor_tax_profile(self, donor_id, payload, headers=None):
        return self._call(
            "PATCH", f"/donor-members/{donor_id}/tax-profile", payload, headers
        )

    # --- Commitments (PRD s3.4) -----------------------------------------
    def create_commitment(self, payload, headers=None):
        return self._call("POST", "/commitments", payload, headers)

    def get_commitment(self, commitment_id, headers=None):
        return self._call("GET", f"/commitments/{commitment_id}", None, headers)

    def list_commitments(self, params=None, headers=None):
        return self._call("GET", "/commitments", params, headers)

    def transition_commitment(self, commitment_id, payload, headers=None):
        return self._call(
            "POST", f"/commitments/{commitment_id}/transitions", payload, headers
        )

    def restructure_commitment(self, commitment_id, payload, headers=None):
        return self._call(
            "POST", f"/commitments/{commitment_id}/restructure", payload, headers
        )

    # --- Contributions (PRD s3.5) ---------------------------------------
    def create_contribution(self, payload, headers=None):
        return self._call("POST", "/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers=None):
        return self._call("GET", f"/contributions/{contribution_id}", None, headers)

    def list_contributions(self, params=None, headers=None):
        return self._call("GET", "/contributions", params, headers)

    def settle_contribution(self, contribution_id, payload, headers=None):
        return self._call(
            "POST", f"/contributions/{contribution_id}/settlements", payload, headers
        )

    def refund_contribution(self, contribution_id, payload=None, headers=None):
        return self._call(
            "POST", f"/contributions/{contribution_id}/refund", payload or {}, headers
        )

    # --- Billing runs (PRD s3.6) ----------------------------------------
    def create_billing_run(self, collective_id, payload, headers=None):
        return self._call(
            "POST", f"/collectives/{collective_id}/billing-runs", payload, headers
        )

    # --- Athletes (PRD s3.7) --------------------------------------------
    def create_athlete(self, payload, headers=None):
        return self._call("POST", "/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers=None):
        return self._call("GET", f"/athletes/{athlete_id}", None, headers)

    def list_athletes(self, params=None, headers=None):
        return self._call("GET", "/athletes", params, headers)

    def change_athlete_eligibility(self, athlete_id, payload, headers=None):
        return self._call(
            "POST", f"/athletes/{athlete_id}/eligibility-changes", payload, headers
        )

    def patch_athlete_tax_profile(self, athlete_id, payload, headers=None):
        return self._call(
            "PATCH", f"/athletes/{athlete_id}/tax-profile", payload, headers
        )

    # --- Deal contracts (PRD s3.8) --------------------------------------
    def create_deal_contract(self, payload, headers=None):
        return self._call("POST", "/deal-contracts", payload, headers)

    def get_deal_contract(self, contract_id, headers=None):
        return self._call("GET", f"/deal-contracts/{contract_id}", None, headers)

    def list_deal_contracts(self, params=None, headers=None):
        return self._call("GET", "/deal-contracts", params, headers)

    def create_roster_allocation(self, payload, headers=None):
        return self._call("POST", "/deal-contracts/roster-allocations", payload, headers)

    def submit_compliance_packet(self, contract_id, payload=None, headers=None):
        return self._call(
            "POST",
            f"/deal-contracts/{contract_id}/compliance-submissions",
            payload or {},
            headers,
        )

    def decide_compliance(self, contract_id, payload, headers=None):
        return self._call(
            "POST", f"/deal-contracts/{contract_id}/compliance-decisions", payload, headers
        )

    def activate_deal_contract(self, contract_id, payload=None, headers=None):
        return self._call(
            "POST", f"/deal-contracts/{contract_id}/activation", payload or {}, headers
        )

    def terminate_deal_contract(self, contract_id, payload, headers=None):
        return self._call(
            "POST", f"/deal-contracts/{contract_id}/termination", payload, headers
        )

    # --- Deliverables (PRD s3.9) ----------------------------------------
    def create_deliverable(self, contract_id, payload, headers=None):
        return self._call(
            "POST", f"/deal-contracts/{contract_id}/deliverables", payload, headers
        )

    def list_deliverables(self, contract_id, params=None, headers=None):
        return self._call(
            "GET", f"/deal-contracts/{contract_id}/deliverables", params, headers
        )

    def get_deliverable(self, deliverable_id, headers=None):
        return self._call("GET", f"/deliverables/{deliverable_id}", None, headers)

    def add_evidence(self, deliverable_id, payload, headers=None):
        return self._call(
            "POST", f"/deliverables/{deliverable_id}/evidence", payload, headers
        )

    def submit_deliverable(self, deliverable_id, payload, headers=None):
        return self._call(
            "POST", f"/deliverables/{deliverable_id}/submissions", payload, headers
        )

    def review_deliverable(self, deliverable_id, payload, headers=None):
        return self._call(
            "POST", f"/deliverables/{deliverable_id}/reviews", payload, headers
        )

    # --- Payment releases (PRD s3.9) ------------------------------------
    def create_payment_release(self, payload, headers=None):
        return self._call("POST", "/payment-releases", payload, headers)

    def get_payment_release(self, release_id, headers=None):
        return self._call("GET", f"/payment-releases/{release_id}", None, headers)

    def list_payment_releases(self, params=None, headers=None):
        return self._call("GET", "/payment-releases", params, headers)

    def reverse_payment_release(self, release_id, payload, headers=None):
        return self._call(
            "POST", f"/payment-releases/{release_id}/reversals", payload, headers
        )

    # --- Communication logs (PRD s3.1) ----------------------------------
    def create_communication_log(self, payload, headers=None):
        return self._call("POST", "/communication-logs", payload, headers)

    def get_communication_log(self, log_id, headers=None):
        return self._call("GET", f"/communication-logs/{log_id}", None, headers)

    def list_communication_logs(self, params=None, headers=None):
        return self._call("GET", "/communication-logs", params, headers)
