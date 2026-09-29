"""API client: one method per endpoint of the petition verification service.

All paths are absolute from the server root; the service is mounted without a
prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- verification standards ------------------------------------------
    def create_verification_standard(self, payload, headers):
        return self._request("POST", "/verification-standards", payload, headers)

    def get_verification_standard(self, standard_id, headers):
        return self._request(
            "GET", f"/verification-standards/{standard_id}", headers=headers
        )

    def list_verification_standards(self, headers, params=None):
        return self._request(
            "GET", "/verification-standards", headers=headers, params=params
        )

    # --- counties ---------------------------------------------------------
    def create_county(self, payload, headers):
        return self._request("POST", "/counties", payload, headers)

    def get_county(self, county_id, headers):
        return self._request("GET", f"/counties/{county_id}", headers=headers)

    def list_counties(self, headers, params=None):
        return self._request("GET", "/counties", headers=headers, params=params)

    # --- voter roll -------------------------------------------------------
    def create_voter_record(self, payload, headers):
        return self._request("POST", "/voter-records", payload, headers)

    def get_voter_record(self, voter_record_id, headers):
        return self._request(
            "GET", f"/voter-records/{voter_record_id}", headers=headers
        )

    def list_voter_records(self, headers, params=None):
        return self._request("GET", "/voter-records", headers=headers, params=params)

    def set_voter_registration_status(self, voter_record_id, payload, headers):
        return self._request(
            "PUT",
            f"/voter-records/{voter_record_id}/registration-status",
            payload,
            headers,
        )

    # --- petitions --------------------------------------------------------
    def create_petition(self, payload, headers):
        return self._request("POST", "/petitions", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/petitions", headers=headers, params=params)

    def submit_petition(self, petition_id, headers, payload=None):
        return self._request(
            "POST", f"/petitions/{petition_id}/submit", payload or {}, headers
        )

    def format_decision(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/petitions/{petition_id}/format-decision", payload, headers
        )

    def put_title_summary(self, petition_id, payload, headers):
        return self._request(
            "PUT", f"/petitions/{petition_id}/title-summary", payload, headers
        )

    def clear_for_circulation(self, petition_id, headers, payload=None):
        return self._request(
            "POST",
            f"/petitions/{petition_id}/clear-for-circulation",
            payload or {},
            headers,
        )

    def file_signatures(self, petition_id, headers, payload=None):
        return self._request(
            "POST", f"/petitions/{petition_id}/file-signatures", payload or {}, headers
        )

    def create_verification_round(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/petitions/{petition_id}/verification-rounds", payload, headers
        )

    def create_cure_period(self, petition_id, headers, payload=None):
        return self._request(
            "POST", f"/petitions/{petition_id}/cure-periods", payload or {}, headers
        )

    def create_challenge(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/petitions/{petition_id}/challenges", payload, headers
        )

    def issue_determination(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/petitions/{petition_id}/determination", payload, headers
        )

    def get_distribution_report(self, petition_id, headers):
        return self._request(
            "GET", f"/petitions/{petition_id}/distribution-report", headers=headers
        )

    def get_verification_invoice(self, petition_id, headers):
        return self._request(
            "GET", f"/petitions/{petition_id}/verification-invoice", headers=headers
        )

    # --- circulators ------------------------------------------------------
    def create_circulator(self, payload, headers):
        return self._request("POST", "/circulators", payload, headers)

    def get_circulator(self, circulator_id, headers):
        return self._request("GET", f"/circulators/{circulator_id}", headers=headers)

    def list_circulators(self, headers, params=None):
        return self._request("GET", "/circulators", headers=headers, params=params)

    def record_training(self, circulator_id, payload, headers):
        return self._request(
            "POST", f"/circulators/{circulator_id}/training", payload, headers
        )

    def file_paid_disclosure(self, circulator_id, payload, headers):
        return self._request(
            "PUT", f"/circulators/{circulator_id}/paid-disclosure", payload, headers
        )

    def file_affidavit(self, circulator_id, payload, headers):
        return self._request(
            "POST", f"/circulators/{circulator_id}/affidavit", payload, headers
        )

    def suspend_circulator(self, circulator_id, headers, payload=None):
        return self._request(
            "POST", f"/circulators/{circulator_id}/suspend", payload or {}, headers
        )

    def reinstate_circulator(self, circulator_id, headers, payload=None):
        return self._request(
            "POST", f"/circulators/{circulator_id}/reinstate", payload or {}, headers
        )

    def revoke_circulator(self, circulator_id, headers, payload=None):
        return self._request(
            "POST", f"/circulators/{circulator_id}/revoke", payload or {}, headers
        )

    # --- circulation assignments -----------------------------------------
    def create_circulation_assignment(self, payload, headers):
        return self._request("POST", "/circulation-assignments", payload, headers)

    def get_circulation_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/circulation-assignments/{assignment_id}", headers=headers
        )

    def list_circulation_assignments(self, headers, params=None):
        return self._request(
            "GET", "/circulation-assignments", headers=headers, params=params
        )

    def terminate_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/circulation-assignments/{assignment_id}/terminate",
            payload or {},
            headers,
        )

    # --- signature batches ------------------------------------------------
    def create_signature_batch(self, payload, headers):
        return self._request("POST", "/signature-batches", payload, headers)

    def get_signature_batch(self, batch_id, headers):
        return self._request("GET", f"/signature-batches/{batch_id}", headers=headers)

    def list_signature_batches(self, headers, params=None):
        return self._request(
            "GET", "/signature-batches", headers=headers, params=params
        )

    def add_signature(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/signature-batches/{batch_id}/signatures", payload, headers
        )

    def verify_affidavit(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/signature-batches/{batch_id}/verify-affidavit", payload, headers
        )

    def invalidate_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/signature-batches/{batch_id}/invalidate", payload, headers
        )

    def reinstate_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/signature-batches/{batch_id}/reinstate", payload or {}, headers
        )

    # --- signature records ------------------------------------------------
    def get_signature_record(self, signature_record_id, headers):
        return self._request(
            "GET", f"/signature-records/{signature_record_id}", headers=headers
        )

    def list_signature_records(self, headers, params=None):
        return self._request(
            "GET", "/signature-records", headers=headers, params=params
        )

    def validate_signature_record(self, signature_record_id, headers, payload=None):
        return self._request(
            "POST",
            f"/signature-records/{signature_record_id}/validate",
            payload if payload is not None else {},
            headers,
        )

    # --- verification rounds ---------------------------------------------
    def get_verification_round(self, round_id, headers):
        return self._request(
            "GET", f"/verification-rounds/{round_id}", headers=headers
        )

    def list_verification_rounds(self, headers, params=None):
        return self._request(
            "GET", "/verification-rounds", headers=headers, params=params
        )

    def tally_round(self, round_id, headers, payload=None):
        return self._request(
            "POST", f"/verification-rounds/{round_id}/tally", payload or {}, headers
        )

    def void_round(self, round_id, payload, headers):
        return self._request(
            "POST", f"/verification-rounds/{round_id}/void", payload, headers
        )

    # --- cure periods -----------------------------------------------------
    def get_cure_period(self, cure_period_id, headers):
        return self._request("GET", f"/cure-periods/{cure_period_id}", headers=headers)

    def list_cure_periods(self, headers, params=None):
        return self._request("GET", "/cure-periods", headers=headers, params=params)

    def expire_cure_period(self, cure_period_id, headers, payload=None):
        return self._request(
            "POST", f"/cure-periods/{cure_period_id}/expire", payload or {}, headers
        )

    # --- challenges -------------------------------------------------------
    def get_challenge(self, challenge_id, headers):
        return self._request("GET", f"/challenges/{challenge_id}", headers=headers)

    def list_challenges(self, headers, params=None):
        return self._request("GET", "/challenges", headers=headers, params=params)

    def escalate_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST", f"/challenges/{challenge_id}/escalate", payload, headers
        )

    def rule_on_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST", f"/challenges/{challenge_id}/rule", payload, headers
        )

    def dismiss_challenge(self, challenge_id, headers, payload=None):
        return self._request(
            "POST", f"/challenges/{challenge_id}/dismiss", payload or {}, headers
        )

    # --- fraud referrals --------------------------------------------------
    def create_fraud_referral(self, payload, headers):
        return self._request("POST", "/fraud-referrals", payload, headers)

    def get_fraud_referral(self, referral_id, headers):
        return self._request("GET", f"/fraud-referrals/{referral_id}", headers=headers)

    def list_fraud_referrals(self, headers, params=None):
        return self._request("GET", "/fraud-referrals", headers=headers, params=params)

    def refer_to_ag(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"/fraud-referrals/{referral_id}/refer-to-ag", payload or {}, headers
        )

    def adjudicate_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/fraud-referrals/{referral_id}/adjudicate", payload, headers
        )


api_client = ApiClient()
