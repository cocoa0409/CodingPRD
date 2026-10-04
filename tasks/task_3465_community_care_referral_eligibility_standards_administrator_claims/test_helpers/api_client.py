"""API client: one method per endpoint defined in the PRD.

All paths carry the /community-care mount prefix, including the logical
clock endpoint POST /community-care/_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/community-care/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- care stations -------------------------------------------------------
    def create_care_station(self, payload, headers):
        return self._request("POST", "/community-care/care-stations", payload, headers)

    # ---- third-party administrators ------------------------------------------
    def create_tpa(self, payload, headers):
        return self._request("POST", "/community-care/tpas", payload, headers)

    def get_tpa(self, tpa_id, headers):
        return self._request("GET", f"/community-care/tpas/{tpa_id}", headers=headers)

    # ---- community providers ---------------------------------------------------
    def create_provider(self, tpa_id, payload, headers):
        return self._request(
            "POST", f"/community-care/tpas/{tpa_id}/providers", payload, headers
        )

    def list_providers(self, tpa_id, headers, params=None):
        return self._request(
            "GET", f"/community-care/tpas/{tpa_id}/providers",
            headers=headers, params=params,
        )

    def decide_credential(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/community-care/providers/{provider_id}/credential-decision",
            payload, headers,
        )

    # ---- veterans --------------------------------------------------------------
    def create_veteran(self, payload, headers):
        return self._request("POST", "/community-care/veterans", payload, headers)

    def get_veteran(self, veteran_id, headers):
        return self._request(
            "GET", f"/community-care/veterans/{veteran_id}", headers=headers
        )

    def list_veterans(self, headers, params=None):
        return self._request("GET", "/community-care/veterans", headers=headers,
                             params=params)

    # ---- eligibility assessments -------------------------------------------------
    def create_eligibility_assessment(self, veteran_id, payload, headers):
        return self._request(
            "POST", f"/community-care/veterans/{veteran_id}/eligibility-assessments",
            payload, headers,
        )

    def list_eligibility_assessments(self, veteran_id, headers, params=None):
        return self._request(
            "GET", f"/community-care/veterans/{veteran_id}/eligibility-assessments",
            headers=headers, params=params,
        )

    # ---- referral authorizations ---------------------------------------------------
    def create_referral_authorization(self, payload, headers):
        return self._request(
            "POST", "/community-care/referral-authorizations", payload, headers
        )

    def get_referral_authorization(self, authorization_id, headers):
        return self._request(
            "GET", f"/community-care/referral-authorizations/{authorization_id}",
            headers=headers,
        )

    def list_referral_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/community-care/referral-authorizations",
            headers=headers, params=params,
        )

    def authorize_referral(self, authorization_id, headers):
        return self._request(
            "POST", f"/community-care/referral-authorizations/{authorization_id}/authorize",
            {}, headers,
        )

    def cancel_referral(self, authorization_id, headers):
        return self._request(
            "POST", f"/community-care/referral-authorizations/{authorization_id}/cancel",
            {}, headers,
        )

    # ---- extension requests -----------------------------------------------------------
    def create_extension_request(self, authorization_id, payload, headers):
        return self._request(
            "POST",
            f"/community-care/referral-authorizations/{authorization_id}/extension-requests",
            payload, headers,
        )

    def list_extension_requests(self, authorization_id, headers, params=None):
        return self._request(
            "GET",
            f"/community-care/referral-authorizations/{authorization_id}/extension-requests",
            headers=headers, params=params,
        )

    def decide_extension_request(self, authorization_id, extension_id, payload, headers):
        return self._request(
            "POST",
            f"/community-care/referral-authorizations/{authorization_id}"
            f"/extension-requests/{extension_id}/decide",
            payload, headers,
        )

    # ---- appointments --------------------------------------------------------------------
    def create_appointment(self, authorization_id, payload, headers):
        return self._request(
            "POST",
            f"/community-care/referral-authorizations/{authorization_id}/appointments",
            payload, headers,
        )

    def list_appointments(self, authorization_id, headers, params=None):
        return self._request(
            "GET",
            f"/community-care/referral-authorizations/{authorization_id}/appointments",
            headers=headers, params=params,
        )

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/community-care/appointments/{appointment_id}", headers=headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/community-care/appointments/{appointment_id}/complete",
            {}, headers,
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/community-care/appointments/{appointment_id}/cancel",
            {}, headers,
        )

    # ---- medical documentation -------------------------------------------------------------
    def submit_documentation(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/community-care/appointments/{appointment_id}/documentation",
            payload, headers,
        )

    def get_documentation(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/community-care/appointments/{appointment_id}/documentation",
            headers=headers, params=params,
        )

    def review_documentation(self, documentation_id, payload, headers):
        return self._request(
            "POST", f"/community-care/medical-documentation/{documentation_id}/review",
            payload, headers,
        )

    # ---- claims -----------------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/community-care/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/community-care/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/community-care/claims", headers=headers,
                             params=params)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/community-care/claims/{claim_id}/adjudicate", payload, headers
        )

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/community-care/claims/{claim_id}/resubmit", payload, headers
        )

    def reverse_claim_payment(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/community-care/claims/{claim_id}/reverse-payment",
            payload, headers,
        )

    # ---- urgent care --------------------------------------------------------------------------
    def create_urgent_care_visit(self, payload, headers):
        return self._request(
            "POST", "/community-care/urgent-care-visits", payload, headers
        )

    def list_urgent_care_visits(self, veteran_id, headers, params=None):
        return self._request(
            "GET", f"/community-care/veterans/{veteran_id}/urgent-care-visits",
            headers=headers, params=params,
        )

    # ---- prescription fill requests -------------------------------------------------------------
    def create_prescription_fill_request(self, payload, headers):
        return self._request(
            "POST", "/community-care/prescription-fill-requests", payload, headers
        )

    def get_prescription_fill_request(self, request_id, headers):
        return self._request(
            "GET", f"/community-care/prescription-fill-requests/{request_id}",
            headers=headers,
        )

    def list_prescription_fill_requests(self, headers, params=None):
        return self._request(
            "GET", "/community-care/prescription-fill-requests",
            headers=headers, params=params,
        )

    def decide_prescription_fill_request(self, request_id, payload, headers):
        return self._request(
            "POST",
            f"/community-care/prescription-fill-requests/{request_id}/decide",
            payload, headers,
        )


api_client = ApiClient()
