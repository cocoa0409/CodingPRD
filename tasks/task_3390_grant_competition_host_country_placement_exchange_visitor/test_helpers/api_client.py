"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Competition cycles (PRD §3.1)
    # ------------------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", "/exchange/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/exchange/cycles/{cycle_id}", headers=headers)

    def transition_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/exchange/cycles/{cycle_id}/transition", payload, headers,
        )

    # ------------------------------------------------------------------
    # Country programs (PRD §3.1)
    # ------------------------------------------------------------------
    def create_country_program(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/exchange/cycles/{cycle_id}/country-programs", payload, headers,
        )

    def get_country_program(self, program_id, headers):
        return self._request(
            "GET", f"/exchange/country-programs/{program_id}", headers=headers,
        )

    def list_country_programs(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/exchange/cycles/{cycle_id}/country-programs",
            headers=headers, params=params,
        )

    def patch_country_program(self, program_id, payload, headers):
        return self._request(
            "PATCH", f"/exchange/country-programs/{program_id}", payload, headers,
        )

    # ------------------------------------------------------------------
    # Applicants (PRD §3.2)
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", "/exchange/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request(
            "GET", f"/exchange/applicants/{applicant_id}", headers=headers,
        )

    # ------------------------------------------------------------------
    # Applications (PRD §3.2-§3.5)
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/exchange/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/exchange/applications/{application_id}", headers=headers,
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/exchange/applications", headers=headers, params=params,
        )

    def patch_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"/exchange/applications/{application_id}", payload, headers,
        )

    def transition_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/exchange/applications/{application_id}/transition",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Review scores (PRD §3.3)
    # ------------------------------------------------------------------
    def post_score(self, application_id, payload, headers):
        return self._request(
            "POST", f"/exchange/applications/{application_id}/scores",
            payload, headers,
        )

    def list_scores(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/exchange/applications/{application_id}/scores",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # Placement rounds (PRD §3.5)
    # ------------------------------------------------------------------
    def create_placement_round(self, application_id, payload, headers):
        return self._request(
            "POST", f"/exchange/applications/{application_id}/placement-rounds",
            payload, headers,
        )

    def list_placement_rounds(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/exchange/applications/{application_id}/placement-rounds",
            headers=headers, params=params,
        )

    def transition_placement_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/exchange/placement-rounds/{round_id}/transition",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Grants (PRD §3.6-§3.8)
    # ------------------------------------------------------------------
    def list_application_grants(self, application_id, headers):
        return self._request(
            "GET", f"/exchange/applications/{application_id}/grants",
            headers=headers,
        )

    def confirm_grant(self, application_id, payload, headers):
        return self._request(
            "POST", f"/exchange/applications/{application_id}/grant-confirmation",
            payload, headers,
        )

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/exchange/grants/{grant_id}", headers=headers)

    def transition_grant(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/exchange/grants/{grant_id}/transition", payload, headers,
        )

    # ------------------------------------------------------------------
    # Visa sponsorships (PRD §3.7)
    # ------------------------------------------------------------------
    def create_visa_sponsorship(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/exchange/grants/{grant_id}/visa-sponsorships",
            payload, headers,
        )

    def get_visa_sponsorship(self, visa_id, headers):
        return self._request(
            "GET", f"/exchange/visa-sponsorships/{visa_id}", headers=headers,
        )

    def list_grant_visa_sponsorships(self, grant_id, headers):
        return self._request(
            "GET", f"/exchange/grants/{grant_id}/visa-sponsorships",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Residency ledgers (PRD §3.9)
    # ------------------------------------------------------------------
    def list_visa_residency_ledgers(self, visa_id, headers):
        return self._request(
            "GET", f"/exchange/visa-sponsorships/{visa_id}/residency-ledgers",
            headers=headers,
        )

    def get_residency_ledger(self, ledger_id, headers):
        return self._request(
            "GET", f"/exchange/residency-ledgers/{ledger_id}", headers=headers,
        )

    def add_residency_stay(self, ledger_id, payload, headers):
        return self._request(
            "POST", f"/exchange/residency-ledgers/{ledger_id}/stays",
            payload, headers,
        )

    def transition_residency_ledger(self, ledger_id, payload, headers):
        return self._request(
            "POST", f"/exchange/residency-ledgers/{ledger_id}/transition",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Reports (PRD §3.9)
    # ------------------------------------------------------------------
    def create_report(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/exchange/grants/{grant_id}/reports", payload, headers,
        )

    def list_reports(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/exchange/grants/{grant_id}/reports",
            headers=headers, params=params,
        )

    def transition_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/exchange/reports/{report_id}/transition", payload, headers,
        )

    # ------------------------------------------------------------------
    # Emergency incidents (PRD §3.8)
    # ------------------------------------------------------------------
    def create_incident(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/exchange/grants/{grant_id}/incidents", payload, headers,
        )

    def list_incidents(self, grant_id, headers, params=None):
        return self._request(
            "GET", f"/exchange/grants/{grant_id}/incidents",
            headers=headers, params=params,
        )

    def resolve_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/exchange/incidents/{incident_id}/resolve", payload, headers,
        )

    # ------------------------------------------------------------------
    # Alumni profiles (PRD §3.9)
    # ------------------------------------------------------------------
    def list_applicant_alumni_profiles(self, applicant_id, headers):
        return self._request(
            "GET", f"/exchange/applicants/{applicant_id}/alumni-profiles",
            headers=headers,
        )

    def list_grant_alumni_profiles(self, grant_id, headers):
        return self._request(
            "GET", f"/exchange/grants/{grant_id}/alumni-profiles", headers=headers,
        )


api_client = ApiClient()
