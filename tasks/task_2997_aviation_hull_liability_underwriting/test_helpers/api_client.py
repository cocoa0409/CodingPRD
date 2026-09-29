"""HTTP client for the aviation hull and liability underwriting API.

One method per endpoint of the PRD's endpoint table.  Every path is mounted
beneath the /aviation prefix.  Methods return the raw response so that tests can
assert both the status code and the envelope.
"""

import re
from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, JsonDict

BASE = "/aviation"

_FRACTIONAL_SECONDS = re.compile(r"\.\d+")


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Canonicalise an ISO-8601 instant for comparison.

    This is the single place in the suite where instant formatting is
    normalised: any fractional-second component is dropped and any explicit
    UTC designator is expressed as a trailing Z, so that two spellings of the
    same instant compare equal.  Values that are not instants pass through
    untouched.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    text = _FRACTIONAL_SECONDS.sub("", text)
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    elif text.endswith("-00:00"):
        text = text[: -len("-00:00")] + "Z"
    return text


class AviationApiClient(GenericApiClient):
    """Endpoint methods for the aviation underwriting API."""

    # ------------------------------------------------------------------
    # Escape hatches for tests that must address a path directly
    # ------------------------------------------------------------------
    def raw_get(
        self, path: str, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(
        self, path: str, payload: JsonDict = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", path, payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # The logical underwriting clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Operators
    # ------------------------------------------------------------------
    def create_operator(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/operators", payload=payload, headers=headers)

    def get_operator(self, operator_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/operators/{operator_id}", headers=headers)

    # ------------------------------------------------------------------
    # Aircraft
    # ------------------------------------------------------------------
    def create_aircraft(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/aircraft", payload=payload, headers=headers)

    def get_aircraft(self, aircraft_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/aircraft/{aircraft_id}", headers=headers)

    # ------------------------------------------------------------------
    # Pilots
    # ------------------------------------------------------------------
    def create_pilot(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/pilots", payload=payload, headers=headers)

    def get_pilot(self, pilot_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/pilots/{pilot_id}", headers=headers)

    def verify_pilot_hours(
        self, pilot_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/pilots/{pilot_id}/hours-verifications",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def create_policy(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/policies", payload=payload, headers=headers)

    def list_policies(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/policies", headers=headers, params=params)

    def get_policy(self, policy_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/policies/{policy_id}", headers=headers)

    def bind_policy(
        self, policy_id: str, payload: JsonDict = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/policies/{policy_id}/bind", payload=payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Aircraft schedules
    # ------------------------------------------------------------------
    def create_schedule(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/schedules", payload=payload, headers=headers)

    def list_schedules(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/schedules", headers=headers, params=params)

    def get_schedule(self, schedule_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/schedules/{schedule_id}", headers=headers)

    def revise_schedule_value(
        self, schedule_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/schedules/{schedule_id}/value-revisions",
            payload=payload,
            headers=headers,
        )

    def record_warranty_finding(
        self, schedule_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/schedules/{schedule_id}/warranty-findings",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Endorsements
    # ------------------------------------------------------------------
    def create_endorsement(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/endorsements", payload=payload, headers=headers)

    def list_endorsements(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/endorsements", headers=headers, params=params)

    def get_endorsement(
        self, endorsement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/endorsements/{endorsement_id}", headers=headers)

    def quote_endorsement(
        self, endorsement_id: str, payload: JsonDict = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/endorsements/{endorsement_id}/quote",
            payload=payload or {},
            headers=headers,
        )

    def refer_endorsement(
        self, endorsement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/endorsements/{endorsement_id}/referral",
            payload=payload,
            headers=headers,
        )

    def bind_endorsement(
        self, endorsement_id: str, payload: JsonDict = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/endorsements/{endorsement_id}/bind",
            payload=payload or {},
            headers=headers,
        )

    def void_endorsement(
        self, endorsement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/endorsements/{endorsement_id}/void",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # War risk markets and placements
    # ------------------------------------------------------------------
    def create_war_market(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/war-markets", payload=payload, headers=headers)

    def get_war_market(self, market_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/war-markets/{market_id}", headers=headers)

    def create_war_placement(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/war-placements", payload=payload, headers=headers
        )

    def list_war_placements(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/war-placements", headers=headers, params=params)

    def get_war_placement(
        self, placement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/war-placements/{placement_id}", headers=headers)

    def cancel_war_placement(
        self, placement_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/war-placements/{placement_id}/cancellation",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload: JsonDict, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{BASE}/claims", payload=payload, headers=headers)

    def list_claims(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/claims", headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{BASE}/claims/{claim_id}", headers=headers)

    def record_investigation(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/claims/{claim_id}/investigations",
            payload=payload,
            headers=headers,
        )

    def decide_coverage(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/claims/{claim_id}/coverage-decision",
            payload=payload,
            headers=headers,
        )

    def dispose_salvage(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/claims/{claim_id}/salvage-disposition",
            payload=payload,
            headers=headers,
        )

    def settle_claim(
        self, claim_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/claims/{claim_id}/settlement", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Damage assessments
    # ------------------------------------------------------------------
    def create_damage_assessment(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/damage-assessments", payload=payload, headers=headers
        )

    def list_damage_assessments(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/damage-assessments", headers=headers, params=params
        )

    def get_damage_assessment(
        self, assessment_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/damage-assessments/{assessment_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Premium ledger
    # ------------------------------------------------------------------
    def list_premium_transactions(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/premium-transactions", headers=headers, params=params
        )

    def get_premium_transaction(
        self, transaction_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/premium-transactions/{transaction_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Fleet declarations
    # ------------------------------------------------------------------
    def create_fleet_declaration(
        self, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/fleet-declarations", payload=payload, headers=headers
        )

    def list_fleet_declarations(
        self, headers: Headers = None, params: JsonDict = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/fleet-declarations", headers=headers, params=params
        )

    def get_fleet_declaration(
        self, declaration_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/fleet-declarations/{declaration_id}", headers=headers
        )

    def accept_fleet_declaration(
        self, declaration_id: str, payload: JsonDict, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/fleet-declarations/{declaration_id}/acceptance",
            payload=payload,
            headers=headers,
        )


__all__ = ["AviationApiClient", "canonical_instant", "BASE"]
