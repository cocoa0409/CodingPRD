"""API client: one method per endpoint defined in PRD section 4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Wood batches ---
    def create_wood_batch(self, payload, headers):
        return self._request("POST", "/piano-works/wood-batches", payload, headers)

    def list_wood_batches(self, headers, params=None):
        return self._request("GET", "/piano-works/wood-batches", headers=headers, params=params)

    def get_wood_batch(self, batch_id, headers):
        return self._request("GET", f"/piano-works/wood-batches/{batch_id}", headers=headers)

    def record_moisture_reading(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/wood-batches/{batch_id}/moisture-readings", payload, headers
        )

    def reject_wood_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/wood-batches/{batch_id}/reject", payload or {}, headers
        )

    # --- Build orders ---
    def create_build_order(self, payload, headers):
        return self._request("POST", "/piano-works/build-orders", payload, headers)

    def list_build_orders(self, headers, params=None):
        return self._request("GET", "/piano-works/build-orders", headers=headers, params=params)

    def get_build_order(self, build_id, headers):
        return self._request("GET", f"/piano-works/build-orders/{build_id}", headers=headers)

    def list_build_stage_logs(self, build_id, headers):
        return self._request(
            "GET", f"/piano-works/build-orders/{build_id}/stage-logs", headers=headers
        )

    def get_build_valuation(self, build_id, headers):
        return self._request(
            "GET", f"/piano-works/build-orders/{build_id}/valuation", headers=headers
        )

    def advance_build_order(self, build_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/build-orders/{build_id}/advance", payload, headers
        )

    # --- People ---
    def create_craftsman(self, payload, headers):
        return self._request("POST", "/piano-works/craftsmen", payload, headers)

    def get_craftsman(self, craftsman_id, headers):
        return self._request("GET", f"/piano-works/craftsmen/{craftsman_id}", headers=headers)

    def create_apprentice(self, payload, headers):
        return self._request("POST", "/piano-works/apprentices", payload, headers)

    def get_apprentice(self, apprentice_id, headers):
        return self._request("GET", f"/piano-works/apprentices/{apprentice_id}", headers=headers)

    # --- Skill endorsements ---
    def create_skill_endorsement(self, payload, headers):
        return self._request("POST", "/piano-works/skill-endorsements", payload, headers)

    def list_skill_endorsements(self, headers, params=None):
        return self._request(
            "GET", "/piano-works/skill-endorsements", headers=headers, params=params
        )

    def get_skill_endorsement(self, endorsement_id, headers):
        return self._request(
            "GET", f"/piano-works/skill-endorsements/{endorsement_id}", headers=headers
        )

    def log_endorsement_hours(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/skill-endorsements/{endorsement_id}/log-hours", payload, headers
        )

    def assess_endorsement(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/skill-endorsements/{endorsement_id}/assess", payload, headers
        )

    def review_endorsement(self, endorsement_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/skill-endorsements/{endorsement_id}/review", payload, headers
        )

    # --- Instruments ---
    def list_instruments(self, headers, params=None):
        return self._request("GET", "/piano-works/instruments", headers=headers, params=params)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/piano-works/instruments/{instrument_id}", headers=headers)

    def bank_intake_instrument(self, instrument_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/instruments/{instrument_id}/bank-intake", payload or {}, headers
        )

    # --- Artists ---
    def create_artist(self, payload, headers):
        return self._request("POST", "/piano-works/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/piano-works/artists/{artist_id}", headers=headers)

    def log_artist_performance(self, artist_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/artists/{artist_id}/performances", payload, headers
        )

    def review_artist(self, artist_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/artists/{artist_id}/review", payload or {}, headers
        )

    # --- Concert loans ---
    def create_concert_loan(self, payload, headers):
        return self._request("POST", "/piano-works/concert-loans", payload, headers)

    def list_concert_loans(self, headers, params=None):
        return self._request("GET", "/piano-works/concert-loans", headers=headers, params=params)

    def get_concert_loan(self, loan_id, headers):
        return self._request("GET", f"/piano-works/concert-loans/{loan_id}", headers=headers)

    def confirm_concert_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/concert-loans/{loan_id}/confirm", payload, headers
        )

    def return_concert_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/concert-loans/{loan_id}/return", payload, headers
        )

    # --- Restoration cases ---
    def create_restoration(self, payload, headers):
        return self._request("POST", "/piano-works/restorations", payload, headers)

    def list_restorations(self, headers, params=None):
        return self._request("GET", "/piano-works/restorations", headers=headers, params=params)

    def get_restoration(self, case_id, headers):
        return self._request("GET", f"/piano-works/restorations/{case_id}", headers=headers)

    def advance_restoration(self, case_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/restorations/{case_id}/advance", payload, headers
        )

    def resolve_restoration_authenticity(self, case_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/restorations/{case_id}/resolve-authenticity", payload, headers
        )

    def complete_restoration(self, case_id, payload, headers):
        return self._request(
            "POST", f"/piano-works/restorations/{case_id}/complete", payload, headers
        )

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
