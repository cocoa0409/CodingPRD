"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- School ------------------------------------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def set_partnership_status(self, school_id, payload, headers):
        return self._request(
            "PATCH", f"/schools/{school_id}/partnership-status", payload, headers
        )

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def list_school_grade_kit_specs(self, school_id, headers, params=None):
        return self._request(
            "GET", f"/schools/{school_id}/grade-kit-specs", headers=headers, params=params
        )

    def get_impact_summary(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}/impact-summary", headers=headers)

    # ---- SupplyItem --------------------------------------------------------
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/supply-items", payload, headers)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/supply-items/{item_id}", headers=headers)

    # ---- GradeKitSpec / KitSpecLine ---------------------------------------
    def create_grade_kit_spec(self, payload, headers):
        return self._request("POST", "/grade-kit-specs", payload, headers)

    def get_grade_kit_spec(self, spec_id, headers):
        return self._request("GET", f"/grade-kit-specs/{spec_id}", headers=headers)

    def set_grade_kit_spec_status(self, spec_id, payload, headers):
        return self._request("PATCH", f"/grade-kit-specs/{spec_id}/status", payload, headers)

    def create_kit_spec_line(self, payload, headers):
        return self._request("POST", "/kit-spec-lines", payload, headers)

    def get_kit_spec_line(self, line_id, headers):
        return self._request("GET", f"/kit-spec-lines/{line_id}", headers=headers)

    def list_kit_spec_lines(self, headers, params=None):
        return self._request("GET", "/kit-spec-lines", headers=headers, params=params)

    # ---- DriveCycle --------------------------------------------------------
    def create_drive_cycle(self, payload, headers):
        return self._request("POST", "/drive-cycles", payload, headers)

    def get_drive_cycle(self, cycle_id, headers):
        return self._request("GET", f"/drive-cycles/{cycle_id}", headers=headers)

    def set_drive_cycle_status(self, cycle_id, payload, headers):
        return self._request("PATCH", f"/drive-cycles/{cycle_id}/status", payload, headers)

    def list_cycle_collection_sites(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/drive-cycles/{cycle_id}/collection-sites", headers=headers, params=params
        )

    # ---- CollectionSite ----------------------------------------------------
    def create_collection_site(self, payload, headers):
        return self._request("POST", "/collection-sites", payload, headers)

    def get_collection_site(self, site_id, headers):
        return self._request("GET", f"/collection-sites/{site_id}", headers=headers)

    def set_site_operational_status(self, site_id, payload, headers):
        return self._request(
            "PATCH", f"/collection-sites/{site_id}/operational-status", payload, headers
        )

    def set_site_pledge_status(self, site_id, payload, headers):
        return self._request(
            "PATCH", f"/collection-sites/{site_id}/pledge-status", payload, headers
        )

    def list_site_volunteer_events(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/collection-sites/{site_id}/volunteer-events", headers=headers, params=params
        )

    # ---- DonationBatch -----------------------------------------------------
    def create_donation_batch(self, payload, headers):
        return self._request("POST", "/donation-batches", payload, headers)

    def get_donation_batch(self, batch_id, headers):
        return self._request("GET", f"/donation-batches/{batch_id}", headers=headers)

    def list_donation_batches(self, headers, params=None):
        return self._request("GET", "/donation-batches", headers=headers, params=params)

    def transition_donation_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/donation-batches/{batch_id}/transitions", payload, headers
        )

    # ---- InventoryPosition -------------------------------------------------
    def adjust_inventory_position(self, payload, headers):
        return self._request("POST", "/inventory-positions/adjustments", payload, headers)

    def get_inventory_position(self, position_id, headers):
        return self._request("GET", f"/inventory-positions/{position_id}", headers=headers)

    def list_inventory_positions(self, headers, params=None):
        return self._request("GET", "/inventory-positions", headers=headers, params=params)

    # ---- CashDonation ------------------------------------------------------
    def create_cash_donation(self, payload, headers):
        return self._request("POST", "/cash-donations", payload, headers)

    def get_cash_donation(self, donation_id, headers):
        return self._request("GET", f"/cash-donations/{donation_id}", headers=headers)

    def list_cash_donations(self, headers, params=None):
        return self._request("GET", "/cash-donations", headers=headers, params=params)

    # ---- PurchaseOrder -----------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def get_purchase_order(self, order_id, headers):
        return self._request("GET", f"/purchase-orders/{order_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def transition_purchase_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/purchase-orders/{order_id}/transitions", payload, headers
        )

    # ---- VolunteerEvent ----------------------------------------------------
    def create_volunteer_event(self, payload, headers):
        return self._request("POST", "/volunteer-events", payload, headers)

    def transition_volunteer_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/volunteer-events/{event_id}/transitions", payload, headers
        )

    # ---- DistributionEvent -------------------------------------------------
    def create_distribution_event(self, payload, headers):
        return self._request("POST", "/distribution-events", payload, headers)

    def get_distribution_event(self, event_id, headers):
        return self._request("GET", f"/distribution-events/{event_id}", headers=headers)

    def list_distribution_events(self, headers, params=None):
        return self._request("GET", "/distribution-events", headers=headers, params=params)

    def transition_distribution_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/distribution-events/{event_id}/transitions", payload, headers
        )

    def list_event_student_registrations(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/distribution-events/{event_id}/student-registrations",
            headers=headers,
            params=params,
        )

    # ---- StudentRegistration ----------------------------------------------
    def create_student_registration(self, payload, headers):
        return self._request("POST", "/student-registrations", payload, headers)

    def get_student_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/student-registrations/{registration_id}", headers=headers
        )

    def transition_student_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/student-registrations/{registration_id}/transitions", payload, headers
        )

    # ---- TeacherRequest ----------------------------------------------------
    def create_teacher_request(self, payload, headers):
        return self._request("POST", "/teacher-requests", payload, headers)

    def get_teacher_request(self, request_id, headers):
        return self._request("GET", f"/teacher-requests/{request_id}", headers=headers)

    def list_teacher_requests(self, headers, params=None):
        return self._request("GET", "/teacher-requests", headers=headers, params=params)

    def transition_teacher_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/teacher-requests/{request_id}/transitions", payload, headers
        )

    # ---- Logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
