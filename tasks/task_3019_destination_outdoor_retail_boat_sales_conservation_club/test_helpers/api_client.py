"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Platform capabilities
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def ops_run(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/ops-run", {}, headers)

    # ------------------------------------------------------------------
    # Stores
    # ------------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def get_dwell_summary(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}/dwell-summary", headers=headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/stores/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/stores/members/{member_id}", headers=headers)

    def update_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/stores/members/{member_id}", payload, headers)

    # ------------------------------------------------------------------
    # Attractions
    # ------------------------------------------------------------------
    def create_attraction(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/attractions", payload, headers)

    def list_attractions(self, headers, params=None):
        return self._request("GET", "/stores/attractions", headers=headers, params=params)

    def get_attraction(self, attraction_id, headers):
        return self._request(
            "GET", f"/stores/attractions/{attraction_id}", headers=headers
        )

    def list_attraction_sessions(self, attraction_id, headers, params=None):
        return self._request(
            "GET",
            f"/stores/attractions/{attraction_id}/sessions",
            headers=headers,
            params=params,
        )

    def open_attraction(self, attraction_id, headers):
        return self._request(
            "POST", f"/stores/attractions/{attraction_id}/open", {}, headers
        )

    # ------------------------------------------------------------------
    # Waivers
    # ------------------------------------------------------------------
    def create_waiver(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/stores/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/stores/waivers/{waiver_id}", headers=headers)

    def list_waiver_sessions(self, waiver_id, headers, params=None):
        return self._request(
            "GET", f"/stores/waivers/{waiver_id}/sessions", headers=headers, params=params
        )

    def list_waiver_fulfillments(self, waiver_id, headers, params=None):
        return self._request(
            "GET",
            f"/stores/waivers/{waiver_id}/fulfillments",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Attraction sessions
    # ------------------------------------------------------------------
    def create_session(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/attraction-sessions", payload, headers
        )

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/stores/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/stores/sessions/{session_id}", headers=headers)

    def check_in_session(self, session_id, headers):
        return self._request(
            "POST", f"/stores/attraction-sessions/{session_id}/check-in", {}, headers
        )

    def complete_session(self, session_id, headers):
        return self._request(
            "POST", f"/stores/attraction-sessions/{session_id}/complete", {}, headers
        )

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/stores/attraction-sessions/{session_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Boat units
    # ------------------------------------------------------------------
    def create_boat_unit(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/boat-units", payload, headers)

    def list_boat_units(self, headers, params=None):
        return self._request("GET", "/stores/boat-units", headers=headers, params=params)

    def get_boat_unit(self, boat_unit_id, headers):
        return self._request(
            "GET", f"/stores/boat-units/{boat_unit_id}", headers=headers
        )

    def update_boat_unit(self, boat_unit_id, payload, headers):
        return self._request(
            "PATCH", f"/stores/boat-units/{boat_unit_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Appraisals
    # ------------------------------------------------------------------
    def create_appraisal(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/appraisals", payload, headers)

    def list_appraisals(self, headers, params=None):
        return self._request("GET", "/stores/appraisals", headers=headers, params=params)

    def get_appraisal(self, appraisal_id, headers):
        return self._request(
            "GET", f"/stores/appraisals/{appraisal_id}", headers=headers
        )

    def list_appraisal_deals(self, appraisal_id, headers, params=None):
        return self._request(
            "GET",
            f"/stores/appraisals/{appraisal_id}/boat-deals",
            headers=headers,
            params=params,
        )

    def revise_appraisal(self, appraisal_id, payload, headers):
        return self._request(
            "PUT", f"/stores/trade-in-appraisals/{appraisal_id}", payload, headers
        )

    def accept_appraisal(self, appraisal_id, headers):
        return self._request(
            "POST", f"/stores/appraisals/{appraisal_id}/accept", {}, headers
        )

    def decline_appraisal(self, appraisal_id, payload, headers):
        return self._request(
            "POST", f"/stores/appraisals/{appraisal_id}/decline", payload, headers
        )

    # ------------------------------------------------------------------
    # Title filings
    # ------------------------------------------------------------------
    def create_title_filing(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/title-filings", payload, headers)

    def list_title_filings(self, headers, params=None):
        return self._request(
            "GET", "/stores/title-filings", headers=headers, params=params
        )

    def get_title_filing(self, filing_id, headers):
        return self._request(
            "GET", f"/stores/title-filings/{filing_id}", headers=headers
        )

    def submit_title_filing(self, filing_id, headers):
        return self._request(
            "POST", f"/stores/title-filings/{filing_id}/submit", {}, headers
        )

    def issue_title_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/stores/title-filings/{filing_id}/issue", payload, headers
        )

    def reject_title_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/stores/title-filings/{filing_id}/reject", payload, headers
        )

    # ------------------------------------------------------------------
    # Boat deals
    # ------------------------------------------------------------------
    def create_deal(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/boat-deals", payload, headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/stores/boat-deals", headers=headers, params=params)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/stores/boat-deals/{deal_id}", headers=headers)

    def contract_deal(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/stores/boat-deals/{deal_id}/contract", payload, headers
        )

    def fund_deal(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/stores/boat-deals/{deal_id}/funding", payload, headers
        )

    def refund_deal(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/stores/boat-deals/{deal_id}/refund", payload, headers
        )

    def settle_deal(self, deal_id, payload, headers):
        return self._request(
            "POST", f"/stores/boat-deals/{deal_id}/settle", payload, headers
        )

    def list_deal_service_orders(self, store_id, deal_id, headers, params=None):
        return self._request(
            "GET",
            f"/stores/{store_id}/boat-deals/{deal_id}/service-orders",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Permit sales and remit batches
    # ------------------------------------------------------------------
    def create_permit_sale(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/permit-sales", payload, headers)

    def list_permit_sales(self, headers, params=None):
        return self._request(
            "GET", "/stores/permit-sales", headers=headers, params=params
        )

    def get_permit_sale(self, sale_id, headers):
        return self._request("GET", f"/stores/permit-sales/{sale_id}", headers=headers)

    def list_sale_intakes(self, sale_id, headers, params=None):
        return self._request(
            "GET",
            f"/stores/permit-sales/{sale_id}/service-intakes",
            headers=headers,
            params=params,
        )

    def void_permit_sale(self, sale_id, headers):
        return self._request(
            "POST", f"/stores/permit-sales/{sale_id}/void", {}, headers
        )

    def create_remit_batch(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/permit-remit-batches", payload, headers
        )

    def list_remit_batches(self, headers, params=None):
        return self._request(
            "GET", "/stores/permit-remit-batches", headers=headers, params=params
        )

    def get_remit_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/stores/permit-remit-batches/{batch_id}", headers=headers
        )

    def seal_remit_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/stores/permit-remit-batches/{batch_id}/seal", payload, headers
        )

    def transmit_remit_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/stores/permit-remit-batches/{batch_id}/transmit", {}, headers
        )

    def acknowledge_remit_batch(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/permit-remit-batches/{batch_id}/acknowledge",
            payload,
            headers,
        )

    def reject_correction_remit_batch(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/permit-remit-batches/{batch_id}/reject-correction",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Club card applications
    # ------------------------------------------------------------------
    def create_club_card_application(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/club-card-applications", payload, headers
        )

    def list_club_card_applications(self, headers, params=None):
        return self._request(
            "GET", "/stores/club-card-applications", headers=headers, params=params
        )

    def get_club_card_application(self, application_id, headers):
        return self._request(
            "GET",
            f"/stores/club-card-applications/{application_id}",
            headers=headers,
        )

    def underwrite_club_card_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/club-card-applications/{application_id}/underwrite",
            payload,
            headers,
        )

    def decide_club_card_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/club-card-applications/{application_id}/decide",
            payload,
            headers,
        )

    def activate_club_card_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/stores/club-card-applications/{application_id}/activate",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Point events
    # ------------------------------------------------------------------
    def create_point_event(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/point-events", payload, headers)

    def list_point_events(self, headers, params=None):
        return self._request("GET", "/stores/point-events", headers=headers, params=params)

    def get_point_event(self, point_event_id, headers):
        return self._request(
            "GET", f"/stores/point-events/{point_event_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Service orders
    # ------------------------------------------------------------------
    def create_service_order(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/service-orders", payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request(
            "GET", "/stores/service-orders", headers=headers, params=params
        )

    def get_service_order(self, order_id, headers):
        return self._request(
            "GET", f"/stores/service-orders/{order_id}", headers=headers
        )

    def schedule_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/stores/service-orders/{order_id}/schedule", {}, headers
        )

    def start_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/stores/service-orders/{order_id}/start", {}, headers
        )

    def complete_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/stores/service-orders/{order_id}/complete", {}, headers
        )

    def deliver_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/stores/service-orders/{order_id}/deliver", {}, headers
        )

    def cancel_service_order(self, order_id, headers):
        return self._request(
            "POST", f"/stores/service-orders/{order_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Service intakes
    # ------------------------------------------------------------------
    def create_service_intake(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/service-intakes", payload, headers)

    def list_service_intakes(self, headers, params=None):
        return self._request(
            "GET", "/stores/service-intakes", headers=headers, params=params
        )

    def get_service_intake(self, intake_id, headers):
        return self._request(
            "GET", f"/stores/service-intakes/{intake_id}", headers=headers
        )

    def revise_service_intake(self, store_id, intake_id, payload, headers):
        return self._request(
            "PUT", f"/stores/{store_id}/service-intakes/{intake_id}", payload, headers
        )

    def verify_intake_permit(self, intake_id, headers):
        return self._request(
            "POST", f"/stores/service-intakes/{intake_id}/verify-permit", {}, headers
        )

    def order_intake_materials(self, intake_id, headers):
        return self._request(
            "POST", f"/stores/service-intakes/{intake_id}/order-materials", {}, headers
        )

    def begin_intake_curing(self, intake_id, headers):
        return self._request(
            "POST", f"/stores/service-intakes/{intake_id}/begin-curing", {}, headers
        )

    def mark_intake_ready(self, intake_id, headers):
        return self._request(
            "POST", f"/stores/service-intakes/{intake_id}/mark-ready", {}, headers
        )

    def release_service_intake(self, intake_id, headers):
        return self._request(
            "POST", f"/stores/service-intakes/{intake_id}/release", {}, headers
        )

    # ------------------------------------------------------------------
    # Event offerings and registrations
    # ------------------------------------------------------------------
    def create_event_offering(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/event-offerings", payload, headers
        )

    def list_event_offerings(self, headers, params=None):
        return self._request(
            "GET", "/stores/event-offerings", headers=headers, params=params
        )

    def get_event_offering(self, offering_id, headers):
        return self._request(
            "GET", f"/stores/event-offerings/{offering_id}", headers=headers
        )

    def list_attraction_event_offerings(self, attraction_id, headers, params=None):
        return self._request(
            "GET",
            f"/stores/attractions/{attraction_id}/event-offerings",
            headers=headers,
            params=params,
        )

    def publish_event_offering(self, offering_id, headers):
        return self._request(
            "POST", f"/stores/event-offerings/{offering_id}/publish", {}, headers
        )

    def cancel_event_offering(self, offering_id, headers):
        return self._request(
            "POST", f"/stores/event-offerings/{offering_id}/cancel", {}, headers
        )

    def create_event_registration(self, store_id, offering_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/{store_id}/event-offerings/{offering_id}/registrations",
            payload,
            headers,
        )

    def list_event_registrations(self, headers, params=None):
        return self._request(
            "GET", "/stores/event-registrations", headers=headers, params=params
        )

    def get_event_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/stores/event-registrations/{registration_id}", headers=headers
        )

    def confirm_event_registration(self, offering_id, registration_id, headers):
        return self._request(
            "POST",
            f"/stores/event-offerings/{offering_id}/registrations/{registration_id}/confirm",
            {},
            headers,
        )

    def cancel_event_registration(self, offering_id, registration_id, headers):
        return self._request(
            "POST",
            f"/stores/event-offerings/{offering_id}/registrations/{registration_id}/cancel",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Bay bookings
    # ------------------------------------------------------------------
    def create_bay_booking(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/bay-bookings", payload, headers)

    def list_bay_bookings(self, headers, params=None):
        return self._request(
            "GET", "/stores/bay-bookings", headers=headers, params=params
        )

    def get_bay_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/stores/bay-bookings/{booking_id}", headers=headers
        )

    def list_bay_bookings_for_bay(self, store_id, bay_no, headers, params=None):
        return self._request(
            "GET",
            f"/stores/{store_id}/load-bays/{bay_no}/bookings",
            headers=headers,
            params=params,
        )

    def check_in_bay_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/stores/bay-bookings/{booking_id}/check-in", {}, headers
        )

    def cancel_bay_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/stores/bay-bookings/{booking_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Order fulfillments
    # ------------------------------------------------------------------
    def create_order_fulfillment(self, store_id, payload, headers):
        return self._request(
            "POST", f"/stores/{store_id}/order-fulfillments", payload, headers
        )

    def list_order_fulfillments(self, headers, params=None):
        return self._request(
            "GET", "/stores/order-fulfillments", headers=headers, params=params
        )

    def get_order_fulfillment(self, fulfillment_id, headers):
        return self._request(
            "GET", f"/stores/order-fulfillments/{fulfillment_id}", headers=headers
        )

    def release_order_fulfillment(self, fulfillment_id, payload, headers):
        return self._request(
            "POST",
            f"/stores/order-fulfillments/{fulfillment_id}/release",
            payload,
            headers,
        )

    def cancel_order_fulfillment(self, fulfillment_id, headers):
        return self._request(
            "POST", f"/stores/order-fulfillments/{fulfillment_id}/cancel", {}, headers
        )


api_client = ApiClient()