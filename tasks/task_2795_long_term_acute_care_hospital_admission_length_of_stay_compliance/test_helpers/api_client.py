"""
The HTTP client: one named method per declared operation.

Tests never build paths or pick verbs themselves. They call
`api.discharge_stay(stay_id, payload, headers=nurse)` and get back the raw
`requests.Response`, which they then hand to `validate_success` or `validate_error`.
Keeping every path in one file means a route typo shows up once, here, instead of in
thirty test files.

`canonical_ts` exists because two implementations may both be right about an instant
and still disagree about how many fractional digits they print. Comparisons of returned
timestamps go through it, so "2026-08-01T00:00:00Z", "...:00.000Z" and "...:00.000000Z"
all compare equal.
"""

import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})$"
)


def canonical_ts(value: Optional[str]) -> Optional[str]:
    """Collapse an ISO 8601 UTC instant onto second precision with a trailing Z.

    Anything that is not a recognisable ISO instant comes back unchanged, so a malformed
    value still fails its assertion loudly rather than being normalised away.
    """
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, fraction, offset = match.groups()
    if offset not in ("Z", "z"):
        # A non-UTC offset is meaningful; leave it alone rather than pretend.
        return value
    if fraction and fraction.rstrip("0") not in ("", "."):
        return "{}T{}{}Z".format(date_part, time_part, fraction.rstrip("0"))
    return "{}T{}Z".format(date_part, time_part)


def _prune(payload: Optional[Json]) -> Optional[Json]:
    """Drop keys whose value is None so optional fields can be passed positionally."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not None}


API_PREFIX = "/ltch"


class ApiClient(GenericApiClient):
    """One method per row of the endpoint table.

    Every method below names its path relative to the API mount point, because PRD 4
    states that "Every endpoint below is mounted under the `/ltch` prefix." The runner
    hands us `API_BASE_URL` as bare scheme://host:port, so the prefix is appended here,
    once, rather than repeated in fifty method bodies.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__(base_url)
        self.base_url = self.base_url.rstrip("/") + API_PREFIX

    # ── The logical clock ────────────────────────────
    def set_clock(self, current_utc: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    # ── Referring hospitals ─────────────────────────
    def create_referring_hospital(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", "/referring-hospitals", payload=payload, headers=headers)

    def get_referring_hospital(
        self, hospital_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/referring-hospitals/{}".format(hospital_id), headers=headers
        )

    # ── Patients ────────────────────────────────────
    def create_patient(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/patients", payload=payload, headers=headers)

    def get_patient(self, patient_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/patients/{}".format(patient_id), headers=headers)

    # ── Physicians ──────────────────────────────────
    def create_physician(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/physicians", payload=payload, headers=headers)

    def set_credential_status(
        self, physician_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/physicians/{}/credential-status".format(physician_id),
            payload=payload,
            headers=headers,
        )

    # ── DRG rate entries ────────────────────────────
    def create_drg_rate(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/drg-rates", payload=payload, headers=headers)

    # ── Admission criteria sets ─────────────────────
    def create_criteria_set(
        self, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", "/admission-criteria-sets", payload=payload, headers=headers)

    def get_criteria_set(
        self, criteria_set_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/admission-criteria-sets/{}".format(criteria_set_id), headers=headers
        )

    # ── Cost reporting periods ──────────────────────
    def create_period(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/cost-reporting-periods", payload=payload, headers=headers)

    def get_period(self, period_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/cost-reporting-periods/{}".format(period_id), headers=headers)

    def recompute_referral_shares(
        self, period_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/cost-reporting-periods/{}/recompute-referral-shares".format(period_id),
            payload={},
            headers=headers,
        )

    def close_period(self, period_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST",
            "/cost-reporting-periods/{}/close".format(period_id),
            payload={},
            headers=headers,
        )

    # ── Referrals ───────────────────────────────────
    def create_referral(self, payload: Json, headers: Optional[Json] = None) -> requests.Response:
        return self._request("POST", "/referrals", payload=payload, headers=headers)

    def get_referral(self, referral_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/referrals/{}".format(referral_id), headers=headers)

    def list_referrals(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/referrals", params=_prune(params), headers=headers)

    def screen_referral(
        self, referral_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/referrals/{}/screen".format(referral_id), payload={}, headers=headers
        )

    def submit_referral_info(
        self, referral_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/referrals/{}/submit-info".format(referral_id),
            payload=payload,
            headers=headers,
        )

    def withdraw_referral(
        self, referral_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/referrals/{}/withdraw".format(referral_id), payload={}, headers=headers
        )

    def admit_referral(
        self,
        referral_id: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/referrals/{}/admit".format(referral_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # ── Stays ───────────────────────────────────────
    def get_stay(self, stay_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/stays/{}".format(stay_id), headers=headers)

    def list_stays(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/stays", params=_prune(params), headers=headers)

    def discharge_stay(
        self, stay_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/stays/{}/discharge".format(stay_id), payload=payload, headers=headers
        )

    def recombine_stay(
        self, stay_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/stays/{}/recombine".format(stay_id), payload=payload, headers=headers
        )

    # ── Interruptions ───────────────────────────────
    def interrupt_stay(
        self, stay_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/stays/{}/interrupt".format(stay_id), payload=payload, headers=headers
        )

    def list_interruptions(
        self, stay_id: str, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            "/stays/{}/interruptions".format(stay_id),
            params=_prune(params),
            headers=headers,
        )

    def return_interruption(
        self, interruption_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/interruptions/{}/return".format(interruption_id),
            payload={},
            headers=headers,
        )

    # ── Interdisciplinary notes ─────────────────────
    def create_idt_note(
        self, stay_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/stays/{}/idt-notes".format(stay_id), payload=payload, headers=headers
        )

    def list_idt_notes(
        self, stay_id: str, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/stays/{}/idt-notes".format(stay_id), params=_prune(params), headers=headers
        )

    # ── Weaning plans ───────────────────────────────
    def create_weaning_plan(
        self, stay_id: str, payload: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/stays/{}/weaning-plans".format(stay_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_weaning_plan(self, plan_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/weaning-plans/{}".format(plan_id), headers=headers)

    def list_weaning_plans(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/weaning-plans", params=_prune(params), headers=headers)

    def record_sbt(
        self, plan_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/weaning-plans/{}/record-sbt".format(plan_id), payload=payload, headers=headers
        )

    def close_weaning_plan(
        self, plan_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", "/weaning-plans/{}/close".format(plan_id), payload=payload, headers=headers
        )

    # ── Payment determinations ──────────────────────
    def reprice_stay(
        self, stay_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/stays/{}/payment-determinations".format(stay_id),
            payload=payload,
            headers=headers,
        )

    def list_stay_determinations(
        self, stay_id: str, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            "/stays/{}/payment-determinations".format(stay_id),
            params=_prune(params),
            headers=headers,
        )

    def get_determination(
        self, determination_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/payment-determinations/{}".format(determination_id), headers=headers
        )

    def finalize_determination(
        self, determination_id: str, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/payment-determinations/{}/finalize".format(determination_id),
            payload={},
            headers=headers,
        )

    def void_determination(
        self, determination_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/payment-determinations/{}/void".format(determination_id),
            payload=payload,
            headers=headers,
        )

    # ── Denial risk reviews ─────────────────────────
    def list_stay_reviews(
        self, stay_id: str, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            "/stays/{}/denial-risk-reviews".format(stay_id),
            params=_prune(params),
            headers=headers,
        )

    def get_review(self, review_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/denial-risk-reviews/{}".format(review_id), headers=headers)

    def rescore_review(self, review_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST",
            "/denial-risk-reviews/{}/rescore".format(review_id),
            payload={},
            headers=headers,
        )

    def issue_query(
        self, review_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/denial-risk-reviews/{}/documentation-queries".format(review_id),
            payload=payload,
            headers=headers,
        )

    def resolve_review(
        self, review_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/denial-risk-reviews/{}/resolve".format(review_id),
            payload=payload,
            headers=headers,
        )

    # ── Documentation queries ───────────────────────
    def get_query(self, query_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request("GET", "/documentation-queries/{}".format(query_id), headers=headers)

    def list_queries(
        self, params: Optional[Json] = None, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/documentation-queries", params=_prune(params), headers=headers
        )

    def answer_query(
        self, query_id: str, payload: Json, headers: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            "/documentation-queries/{}/answer".format(query_id),
            payload=payload,
            headers=headers,
        )

    def close_query(self, query_id: str, headers: Optional[Json] = None) -> requests.Response:
        return self._request(
            "POST",
            "/documentation-queries/{}/close".format(query_id),
            payload={},
            headers=headers,
        )

    # ── Raw escape hatch ────────────────────────────
    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Json] = None,
        headers: Optional[Json] = None,
        params: Optional[Json] = None,
    ) -> requests.Response:
        """For probes that need a verb/path pairing no named method offers."""
        return self._request(method, path, payload=payload, headers=headers, params=params)


# One shared client for the whole suite; the base URL comes from the environment.
api_client = ApiClient()
