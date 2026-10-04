"""API client: one method per endpoint defined in the PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- system / logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/touring/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- talents ----
    def create_talent(self, payload, headers):
        return self._request("POST", "/touring/talents", payload, headers)

    def list_talents(self, headers, params=None):
        return self._request("GET", "/touring/talents", headers=headers, params=params)

    def get_talent(self, talent_id, headers):
        return self._request("GET", f"/touring/talents/{talent_id}", headers=headers)

    def suspend_talent(self, talent_id, payload, headers):
        return self._request("POST", f"/touring/talents/{talent_id}/suspend", payload, headers)

    def reinstate_talent(self, talent_id, headers):
        return self._request("POST", f"/touring/talents/{talent_id}/reinstate", {}, headers)

    def call_up_talent(self, talent_id, payload, headers):
        return self._request("POST", f"/touring/talents/{talent_id}/call-up", payload, headers)

    def list_call_up_decisions(self, talent_id, headers):
        return self._request("GET", f"/touring/talents/{talent_id}/call-up-decisions", headers=headers)

    def get_appearance_compliance(self, talent_id, headers):
        return self._request("GET", f"/touring/talents/{talent_id}/appearance-compliance", headers=headers)

    def list_talent_medical_cases(self, talent_id, headers):
        return self._request("GET", f"/touring/talents/{talent_id}/medical-cases", headers=headers)

    def list_talent_visa_cases(self, talent_id, headers):
        return self._request("GET", f"/touring/talents/{talent_id}/visa-cases", headers=headers)

    def list_talent_agreements(self, talent_id, headers):
        return self._request("GET", f"/touring/talents/{talent_id}/agreements", headers=headers)

    # ---- agreements ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/touring/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/touring/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/touring/agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/touring/agreements/{agreement_id}", payload, headers)

    def activate_agreement(self, agreement_id, expected_agreement_version, headers):
        return self._request("POST", f"/touring/agreements/{agreement_id}/activate",
                             {"expected_agreement_version": expected_agreement_version}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/touring/agreements/{agreement_id}/terminate", {}, headers)

    # ---- arenas / anchors ----
    def create_arena(self, payload, headers):
        return self._request("POST", "/touring/arenas", payload, headers)

    def get_arena(self, arena_id, headers):
        return self._request("GET", f"/touring/arenas/{arena_id}", headers=headers)

    def create_broadcast_anchor(self, payload, headers):
        return self._request("POST", "/touring/broadcast-anchors", payload, headers)

    def get_broadcast_anchor(self, anchor_id, headers):
        return self._request("GET", f"/touring/broadcast-anchors/{anchor_id}", headers=headers)

    # ---- events ----
    def create_event(self, payload, headers):
        return self._request("POST", "/touring/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/touring/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/touring/events/{event_id}", headers=headers)

    def lock_event(self, event_id, expected_event_version, headers):
        return self._request("POST", f"/touring/events/{event_id}/lock",
                             {"expected_event_version": expected_event_version}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/touring/events/{event_id}/complete", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/touring/events/{event_id}/cancel", {}, headers)

    # ---- bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/touring/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/touring/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/touring/bookings/{booking_id}", headers=headers)

    def scratch_booking(self, booking_id, headers):
        return self._request("POST", f"/touring/bookings/{booking_id}/scratch", {}, headers)

    def no_show_booking(self, event_id, booking_id, headers):
        return self._request("POST", f"/touring/events/{event_id}/bookings/{booking_id}/no-show",
                             {}, headers)

    # ---- storylines / chapters ----
    def create_storyline(self, payload, headers):
        return self._request("POST", "/touring/storylines", payload, headers)

    def get_storyline(self, storyline_id, headers):
        return self._request("GET", f"/touring/storylines/{storyline_id}", headers=headers)

    def list_storyline_chapters(self, storyline_id, headers):
        return self._request("GET", f"/touring/storylines/{storyline_id}/chapters", headers=headers)

    def activate_storyline(self, storyline_id, headers):
        return self._request("POST", f"/touring/storylines/{storyline_id}/activate", {}, headers)

    def conclude_storyline(self, storyline_id, headers):
        return self._request("POST", f"/touring/storylines/{storyline_id}/conclude", {}, headers)

    def revive_storyline(self, storyline_id, headers):
        return self._request("POST", f"/touring/storylines/{storyline_id}/revive", {}, headers)

    def create_chapter(self, payload, headers):
        return self._request("POST", "/touring/chapters", payload, headers)

    def list_chapters(self, headers, params=None):
        return self._request("GET", "/touring/chapters", headers=headers, params=params)

    def list_event_chapters(self, event_id, headers):
        return self._request("GET", f"/touring/events/{event_id}/chapters", headers=headers)

    # ---- distribution ----
    def create_streaming_partner(self, payload, headers):
        return self._request("POST", "/touring/streaming-partners", payload, headers)

    def list_streaming_partners(self, headers, params=None):
        return self._request("GET", "/touring/streaming-partners", headers=headers, params=params)

    def get_streaming_partner(self, partner_id, headers):
        return self._request("GET", f"/touring/streaming-partners/{partner_id}", headers=headers)

    def create_territory_right(self, payload, headers):
        return self._request("POST", "/touring/territory-rights", payload, headers)

    def list_territory_rights(self, headers, params=None):
        return self._request("GET", "/touring/territory-rights", headers=headers, params=params)

    def get_territory_right(self, right_id, headers):
        return self._request("GET", f"/touring/territory-rights/{right_id}", headers=headers)

    def create_distribution_window(self, payload, headers):
        return self._request("POST", "/touring/distribution-windows", payload, headers)

    def list_distribution_windows(self, headers, params=None):
        return self._request("GET", "/touring/distribution-windows", headers=headers, params=params)

    def get_distribution_window(self, window_id, headers):
        return self._request("GET", f"/touring/distribution-windows/{window_id}", headers=headers)

    def publish_distribution_window(self, window_id, headers):
        return self._request("POST", f"/touring/distribution-windows/{window_id}/publish", {}, headers)

    def revoke_distribution_window(self, window_id, headers):
        return self._request("POST", f"/touring/distribution-windows/{window_id}/revoke", {}, headers)

    # ---- merch / royalties ----
    def create_merch_sale(self, payload, headers):
        return self._request("POST", "/touring/merch-sales", payload, headers)

    def get_merch_sale(self, sale_id, headers):
        return self._request("GET", f"/touring/merch-sales/{sale_id}", headers=headers)

    def list_merch_sales(self, headers, params=None):
        return self._request("GET", "/touring/merch-sales", headers=headers, params=params)

    def list_event_merch_sales(self, event_id, headers):
        return self._request("GET", f"/touring/events/{event_id}/merch-sales", headers=headers)

    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/touring/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/touring/royalty-statements/{statement_id}", headers=headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/touring/royalty-statements", headers=headers, params=params)

    def recompute_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/touring/royalty-statements/{statement_id}/recompute", {}, headers)

    def finalize_royalty_statement(self, statement_id, headers):
        return self._request("POST", f"/touring/royalty-statements/{statement_id}/finalize", {}, headers)

    # ---- medical ----
    def create_medical_case(self, payload, headers):
        return self._request("POST", "/touring/medical-cases", payload, headers)

    def get_medical_case(self, case_id, headers):
        return self._request("GET", f"/touring/medical-cases/{case_id}", headers=headers)

    def list_medical_evaluations(self, case_id, headers):
        return self._request("GET", f"/touring/medical-cases/{case_id}/evaluations", headers=headers)

    def create_medical_evaluation(self, case_id, payload, headers):
        return self._request("POST", f"/touring/medical-cases/{case_id}/evaluations", payload, headers)

    def create_medical_clearance(self, case_id, payload, headers):
        return self._request("POST", f"/touring/medical-cases/{case_id}/clearances", payload, headers)

    def list_medical_clearances(self, case_id, headers):
        return self._request("GET", f"/touring/medical-cases/{case_id}/clearances", headers=headers)

    # ---- visas ----
    def create_visa_case(self, payload, headers):
        return self._request("POST", "/touring/visa-cases", payload, headers)

    def get_visa_case(self, case_id, headers):
        return self._request("GET", f"/touring/visa-cases/{case_id}", headers=headers)

    def submit_visa_case(self, case_id, headers):
        return self._request("POST", f"/touring/visa-cases/{case_id}/submit", {}, headers)

    def grant_visa_case(self, case_id, headers):
        return self._request("POST", f"/touring/visa-cases/{case_id}/grant", {}, headers)

    def deny_visa_case(self, case_id, headers):
        return self._request("POST", f"/touring/visa-cases/{case_id}/deny", {}, headers)


api_client = ApiClient()
