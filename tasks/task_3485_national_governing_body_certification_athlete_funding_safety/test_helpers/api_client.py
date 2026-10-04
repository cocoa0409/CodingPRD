"""API client: one method per endpoint defined in the PRD endpoint table.

The business surface is mounted under /api. The single platform endpoint —
the logical clock — is deliberately mounted OUTSIDE that prefix:
POST /_clock/set_current_utc. set_clock() therefore uses the bare path and
must never gain the /api prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/api"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Platform (UNPREFIXED — do not add /api)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Governing bodies
    # ------------------------------------------------------------------
    def create_governing_body(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/governing-bodies", payload, headers)

    def get_governing_body(self, governing_body_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/governing-bodies/{governing_body_id}", headers=headers
        )

    def transition_governing_body(self, governing_body_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/transitions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Certification cycles
    # ------------------------------------------------------------------
    def create_certification_cycle(self, governing_body_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/certification-cycles",
            payload,
            headers,
        )

    def list_certification_cycles(self, governing_body_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/certification-cycles",
            headers=headers,
            params=params,
        )

    def transition_certification_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/certification-cycles/{cycle_id}/transitions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Complaints
    # ------------------------------------------------------------------
    def create_complaint(self, governing_body_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/complaints",
            payload,
            headers,
        )

    def list_complaints(self, governing_body_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/complaints",
            headers=headers,
            params=params,
        )

    def transition_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/complaints/{complaint_id}/transitions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Athletes
    # ------------------------------------------------------------------
    def create_athlete(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/athletes", payload, headers)

    def list_athletes(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/athletes", headers=headers, params=params)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"{API_PREFIX}/athletes/{athlete_id}", headers=headers)

    def transition_athlete(self, athlete_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/athletes/{athlete_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Performance results
    # ------------------------------------------------------------------
    def create_result(self, athlete_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/athletes/{athlete_id}/results", payload, headers
        )

    def list_results(self, athlete_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/athletes/{athlete_id}/results",
            headers=headers,
            params=params,
        )

    def transition_result(self, result_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/results/{result_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Funding agreements
    # ------------------------------------------------------------------
    def create_funding_agreement(self, athlete_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/athletes/{athlete_id}/funding-agreements",
            payload,
            headers,
        )

    def list_funding_agreements(self, athlete_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/athletes/{athlete_id}/funding-agreements",
            headers=headers,
            params=params,
        )

    def get_funding_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/funding-agreements/{agreement_id}", headers=headers
        )

    def transition_funding_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/funding-agreements/{agreement_id}/transitions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Abuse reports
    # ------------------------------------------------------------------
    def create_abuse_report(self, athlete_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/athletes/{athlete_id}/abuse-reports", payload, headers
        )

    def list_abuse_reports(self, athlete_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/athletes/{athlete_id}/abuse-reports",
            headers=headers,
            params=params,
        )

    def transition_abuse_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/abuse-reports/{report_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Selection procedures and trials entries
    # ------------------------------------------------------------------
    def create_selection_procedure(self, governing_body_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/selection-procedures",
            payload,
            headers,
        )

    def list_selection_procedures(self, governing_body_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/governing-bodies/{governing_body_id}/selection-procedures",
            headers=headers,
            params=params,
        )

    def transition_selection_procedure(self, procedure_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/selection-procedures/{procedure_id}/transitions",
            payload,
            headers,
        )

    def create_trials_entry(self, procedure_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/selection-procedures/{procedure_id}/entries",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Rosters, nominations, slot decisions
    # ------------------------------------------------------------------
    def create_roster(self, procedure_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/selection-procedures/{procedure_id}/rosters",
            payload,
            headers,
        )

    def list_rosters(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/rosters", headers=headers, params=params)

    def get_roster(self, roster_id, headers):
        return self._request("GET", f"{API_PREFIX}/rosters/{roster_id}", headers=headers)

    def run_nominations(self, roster_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/rosters/{roster_id}/nominations", payload, headers
        )

    def transition_roster(self, roster_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/rosters/{roster_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    def create_appeal(self, roster_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/rosters/{roster_id}/appeals", payload, headers
        )

    def list_roster_appeals(self, roster_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/rosters/{roster_id}/appeals",
            headers=headers,
            params=params,
        )

    def list_athlete_appeals(self, athlete_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/athletes/{athlete_id}/appeals",
            headers=headers,
            params=params,
        )

    def transition_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/transitions", payload, headers
        )

    # ------------------------------------------------------------------
    # Commercial deals
    # ------------------------------------------------------------------
    def create_commercial_deal(self, athlete_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/athletes/{athlete_id}/commercial-deals",
            payload,
            headers,
        )

    def list_commercial_deals(self, athlete_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/athletes/{athlete_id}/commercial-deals",
            headers=headers,
            params=params,
        )

    def transition_commercial_deal(self, deal_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/commercial-deals/{deal_id}/transitions",
            payload,
            headers,
        )


api_client = ApiClient()


def set_clock(client, to_iso8601, headers):
    """First-class clock helper: drives the unprefixed platform endpoint.

    `client` is an ApiClient; `to_iso8601` is the ISO 8601 UTC instant to
    advance to; `headers` should be CommitteeAdmin headers. Returns the raw
    Response so callers can validate per their needs (fixtures use a lenient
    extraction tolerant of enveloped or bare `current_utc` bodies).
    """
    return client.set_clock(to_iso8601, headers)
