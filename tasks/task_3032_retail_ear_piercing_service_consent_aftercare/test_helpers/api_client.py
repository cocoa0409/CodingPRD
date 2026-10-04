"""API client: one method per endpoint of the piercing-services API.

``_request`` is inherited from the framework's ``GenericApiClient``.
Every method returns the raw ``requests.Response`` so tests can assert
status codes themselves.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the retail ear-piercing service API."""

    # ─── Jurisdictions ─────────────────────────────────────────────────────
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/piercing-services/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/piercing-services/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/piercing-services/jurisdictions/{jurisdiction_id}", headers=headers)

    def list_jurisdiction_stores(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/jurisdictions/{jurisdiction_id}/stores", headers=headers, params=params
        )

    def list_jurisdiction_consents(self, jurisdiction_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/jurisdictions/{jurisdiction_id}/consents", headers=headers, params=params
        )

    def supersede_jurisdiction(self, jurisdiction_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/jurisdictions/{jurisdiction_id}/supersede", payload, headers
        )

    # ─── Stores ────────────────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/piercing-services/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/piercing-services/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/piercing-services/stores/{store_id}", headers=headers)

    def get_store_posture(self, store_id, headers):
        return self._request("GET", f"/piercing-services/stores/{store_id}/posture", headers=headers)

    def list_store_incidents(self, store_id, headers, params=None):
        return self._request("GET", f"/piercing-services/stores/{store_id}/incidents", headers=headers, params=params)

    def list_store_piercers(self, store_id, headers, params=None):
        return self._request("GET", f"/piercing-services/stores/{store_id}/piercers", headers=headers, params=params)

    def list_store_cartridge_lots(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/stores/{store_id}/cartridge-lots", headers=headers, params=params
        )

    def list_store_cycles(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/stores/{store_id}/sterilization-cycles", headers=headers, params=params
        )

    def list_store_appointments(self, store_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/stores/{store_id}/appointments", headers=headers, params=params
        )

    def freeze_store(self, store_id, headers):
        return self._request("POST", f"/piercing-services/stores/{store_id}/posture/freeze", headers=headers)

    def unfreeze_store(self, store_id, headers):
        return self._request("POST", f"/piercing-services/stores/{store_id}/posture/unfreeze", headers=headers)

    def clear_store_posture(self, store_id, headers):
        return self._request("POST", f"/piercing-services/stores/{store_id}/posture/clear", headers=headers)

    def close_store(self, store_id, headers):
        return self._request("POST", f"/piercing-services/stores/{store_id}/close", headers=headers)

    # ─── Piercers ──────────────────────────────────────────────────────────
    def create_piercer(self, payload, headers):
        return self._request("POST", "/piercing-services/piercers", payload, headers)

    def list_piercers(self, headers, params=None):
        return self._request("GET", "/piercing-services/piercers", headers=headers, params=params)

    def get_piercer(self, piercer_id, headers):
        return self._request("GET", f"/piercing-services/piercers/{piercer_id}", headers=headers)

    def get_piercer_eligibility_audit(self, piercer_id, headers):
        return self._request(
            "GET", f"/piercing-services/piercers/{piercer_id}/eligibility-audit", headers=headers
        )

    def list_piercer_certifications(self, piercer_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/piercers/{piercer_id}/certifications", headers=headers, params=params
        )

    def reinstate_piercer(self, piercer_id, headers):
        return self._request("POST", f"/piercing-services/piercers/{piercer_id}/reinstate", headers=headers)

    def deactivate_piercer(self, piercer_id, headers):
        return self._request("POST", f"/piercing-services/piercers/{piercer_id}/deactivate", headers=headers)

    # ─── Certifications ────────────────────────────────────────────────────
    def create_certification(self, payload, headers):
        return self._request("POST", "/piercing-services/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/piercing-services/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/piercing-services/certifications/{certification_id}", headers=headers)

    def recertify(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/certifications/{certification_id}/recertify", payload, headers
        )

    def revoke_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/certifications/{certification_id}/revoke", payload, headers
        )

    # ─── Sterilization cycles ──────────────────────────────────────────────
    def create_sterilization_cycle(self, payload, headers):
        return self._request("POST", "/piercing-services/sterilization-cycles", payload, headers)

    def list_sterilization_cycles(self, headers, params=None):
        return self._request("GET", "/piercing-services/sterilization-cycles", headers=headers, params=params)

    def get_sterilization_cycle(self, cycle_id, headers):
        return self._request("GET", f"/piercing-services/sterilization-cycles/{cycle_id}", headers=headers)

    def complete_sterilization_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/sterilization-cycles/{cycle_id}/complete", payload, headers
        )

    def quarantine_sterilization_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/sterilization-cycles/{cycle_id}/quarantine", payload or {}, headers
        )

    def release_sterilization_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/sterilization-cycles/{cycle_id}/release", payload or {}, headers
        )

    def recall_sterilization_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/sterilization-cycles/{cycle_id}/recall", payload or {}, headers
        )

    # ─── Cartridge lots ────────────────────────────────────────────────────
    def create_cartridge_lot(self, payload, headers):
        return self._request("POST", "/piercing-services/cartridge-lots", payload, headers)

    def list_cartridge_lots(self, headers, params=None):
        return self._request("GET", "/piercing-services/cartridge-lots", headers=headers, params=params)

    def get_cartridge_lot(self, lot_id, headers):
        return self._request("GET", f"/piercing-services/cartridge-lots/{lot_id}", headers=headers)

    def discard_cartridge_lot(self, lot_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/cartridge-lots/{lot_id}/discard", payload or {}, headers)

    # ─── Customers ─────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/piercing-services/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/piercing-services/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/piercing-services/customers/{customer_id}", headers=headers)

    def list_customer_consents(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/customers/{customer_id}/consents", headers=headers, params=params
        )

    def list_customer_appointments(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/customers/{customer_id}/appointments", headers=headers, params=params
        )

    def list_customer_open_incidents(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/customers/{customer_id}/open-incidents", headers=headers, params=params
        )

    def clear_customer_flag(self, customer_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/customers/{customer_id}/clear-flag", payload or {}, headers
        )

    def close_customer(self, customer_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/customers/{customer_id}/close", payload or {}, headers)

    def redeem_aftercare_credit(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/customers/{customer_id}/credit-redemptions", payload, headers
        )

    # ─── Consents ──────────────────────────────────────────────────────────
    def create_consent(self, payload, headers):
        return self._request("POST", "/piercing-services/consents", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/piercing-services/consents", headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/piercing-services/consents/{consent_id}", headers=headers)

    def verify_consent(self, consent_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/consents/{consent_id}/verify", payload or {}, headers)

    def reject_consent(self, consent_id, payload, headers):
        return self._request("POST", f"/piercing-services/consents/{consent_id}/reject", payload, headers)

    def revoke_consent(self, consent_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/consents/{consent_id}/revoke", payload or {}, headers)

    def renew_consent(self, consent_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/consents/{consent_id}/renew", payload or {}, headers)

    def record_guardian_verification(self, consent_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/consents/{consent_id}/guardian-verification", payload, headers
        )

    # ─── Appointments ──────────────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/piercing-services/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/piercing-services/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/piercing-services/appointments/{appointment_id}", headers=headers)

    def list_appointment_screenings(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/appointments/{appointment_id}/screenings", headers=headers, params=params
        )

    def list_appointment_sessions(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/appointments/{appointment_id}/sessions", headers=headers, params=params
        )

    def confirm_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/confirm", payload or {}, headers
        )

    def check_in_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/check-in", payload or {}, headers
        )

    def screen_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/screen", payload, headers
        )

    def start_service(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/start-service", payload or {}, headers
        )

    def refuse_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/refuse", payload, headers
        )

    def complete_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/complete", payload or {}, headers
        )

    def abort_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/abort", payload or {}, headers
        )

    def reschedule_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/reschedule", payload, headers
        )

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/appointments/{appointment_id}/cancel", payload or {}, headers
        )

    # ─── Screenings ────────────────────────────────────────────────────────
    def create_screening(self, payload, headers):
        return self._request("POST", "/piercing-services/screenings", payload, headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/piercing-services/screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/piercing-services/screenings/{screening_id}", headers=headers)

    def evaluate_screening(self, screening_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/screenings/{screening_id}/evaluate", payload or {}, headers
        )

    def override_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/screenings/{screening_id}/override", payload, headers
        )

    def escalate_screening(self, screening_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/screenings/{screening_id}/escalate", payload or {}, headers
        )

    # ─── Piercing sessions ─────────────────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/piercing-services/sessions", payload, headers)

    def quote_fee(self, payload, headers):
        return self._request("POST", "/piercing-services/sessions/fee-quote", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/piercing-services/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/piercing-services/sessions/{session_id}", headers=headers)

    def list_session_incidents(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/sessions/{session_id}/incidents", headers=headers, params=params
        )

    def list_session_healing_outcomes(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/piercing-services/sessions/{session_id}/healing-outcomes", headers=headers, params=params
        )

    def record_healing_assessment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/sessions/{session_id}/healing-assessment", payload, headers
        )

    def re_pierce_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/sessions/{session_id}/re-pierce", payload or {}, headers
        )

    def downgrade_session(self, session_id, payload, headers):
        return self._request("POST", f"/piercing-services/sessions/{session_id}/downgrade", payload, headers)

    def acknowledge_follow_up(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/sessions/{session_id}/follow-up/acknowledge", payload or {}, headers
        )

    # ─── Incidents ─────────────────────────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/piercing-services/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/piercing-services/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/piercing-services/incidents/{incident_id}", headers=headers)

    def triage_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/incidents/{incident_id}/triage", payload or {}, headers)

    def escalate_incident(self, incident_id, headers, payload=None):
        return self._request("POST", f"/piercing-services/incidents/{incident_id}/escalate", payload or {}, headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/piercing-services/incidents/{incident_id}/resolve", payload, headers)

    def issue_refund(self, incident_id, payload, headers):
        return self._request("POST", f"/piercing-services/incidents/{incident_id}/issue-refund", payload, headers)

    def reopen_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/piercing-services/incidents/{incident_id}/reopen", payload, headers)

    # ─── Healing outcomes ──────────────────────────────────────────────────
    def create_healing_outcome(self, payload, headers):
        return self._request("POST", "/piercing-services/healing-outcomes", payload, headers)

    def list_healing_outcomes(self, headers, params=None):
        return self._request("GET", "/piercing-services/healing-outcomes", headers=headers, params=params)

    def get_healing_outcome(self, outcome_id, headers):
        return self._request("GET", f"/piercing-services/healing-outcomes/{outcome_id}", headers=headers)

    def downgrade_healing_outcome(self, outcome_id, payload, headers):
        return self._request(
            "POST", f"/piercing-services/healing-outcomes/{outcome_id}/downgrade", payload, headers
        )

    def claim_re_pierce(self, outcome_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/healing-outcomes/{outcome_id}/claim-re-pierce", payload or {}, headers
        )

    def close_healing_outcome(self, outcome_id, headers, payload=None):
        return self._request(
            "POST", f"/piercing-services/healing-outcomes/{outcome_id}/close", payload or {}, headers
        )

    # ─── Test-driving clock ────────────────────────────────────────────────
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/piercing-services/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )


api_client = ApiClient()