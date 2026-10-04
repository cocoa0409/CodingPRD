"""API client: one method per endpoint declared by the contract."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- platform utilities ---
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_role_permissions(self, role, permissions, headers):
        return self._request(
            "POST", "/_rbac/role-permissions", {"role": role, "permissions": permissions}, headers
        )

    def simulate_payment(self, catering_order_id, outcome, headers):
        return self._request(
            "POST",
            "/_payments/simulate",
            {"catering_order_id": catering_order_id, "outcome": outcome},
            headers,
        )

    # --- Store ---
    def create_store(self, payload, headers):
        return self._request("POST", "/deli/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/deli/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/deli/stores", headers=headers, params=params)

    def run_production_day_for_store(self, store_id, headers, payload=None):
        return self._request(
            "POST", f"/deli/stores/{store_id}/run-production-day", payload or {}, headers
        )

    def get_posture_report(self, store_id, headers):
        return self._request("GET", "/deli/posture-report", headers=headers, params={"store_id": store_id})

    # --- DeliItem ---
    def create_item(self, payload, headers):
        return self._request("POST", "/deli/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/deli/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/deli/items", headers=headers, params=params)

    def update_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/deli/items/{item_id}", payload, headers)

    def item_slicer_usage(self, item_id, headers):
        return self._request("GET", f"/deli/items/{item_id}/slicer-usage", headers=headers)

    def item_sanitation_usage(self, item_id, headers):
        return self._request("GET", f"/deli/items/{item_id}/sanitation-usage", headers=headers)

    def item_certification_usage(self, item_id, headers):
        return self._request("GET", f"/deli/items/{item_id}/certification-usage", headers=headers)

    # --- Associate ---
    def create_associate(self, payload, headers):
        return self._request("POST", "/deli/associates", payload, headers)

    def get_associate(self, associate_id, headers):
        return self._request("GET", f"/deli/associates/{associate_id}", headers=headers)

    def list_associates(self, headers, params=None):
        return self._request("GET", "/deli/associates", headers=headers, params=params)

    def suspend_associate(self, associate_id, reason, headers):
        return self._request(
            "POST", f"/deli/associates/{associate_id}/suspend", {"reason": reason}, headers
        )

    def reinstate_associate(self, associate_id, headers):
        return self._request("POST", f"/deli/associates/{associate_id}/reinstate", {}, headers)

    def associate_sanitation_usage(self, associate_id, headers):
        return self._request(
            "GET", f"/deli/associates/{associate_id}/sanitation-usage", headers=headers
        )

    def associate_certification_usage(self, associate_id, headers):
        return self._request(
            "GET", f"/deli/associates/{associate_id}/certification-usage", headers=headers
        )

    # --- Certification ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/deli/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/deli/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/deli/certifications", headers=headers, params=params)

    def renew_certification(self, certification_id, expires_at, headers):
        return self._request(
            "POST",
            f"/deli/certifications/{certification_id}/renew",
            {"expires_at": expires_at},
            headers,
        )

    def revoke_certification(self, certification_id, revoked_by_manager_id, headers):
        return self._request(
            "POST",
            f"/deli/certifications/{certification_id}/revoke",
            {"revoked_by_manager_id": revoked_by_manager_id},
            headers,
        )

    def reopen_certification(self, certification_id, headers):
        return self._request(
            "POST", f"/deli/certifications/{certification_id}/reopen", {}, headers
        )

    def certification_waste_usage(self, certification_id, headers):
        return self._request(
            "GET", f"/deli/certifications/{certification_id}/waste-usage", headers=headers
        )

    # --- ProductionBatch ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/deli/production-batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/deli/production-batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/deli/production-batches", headers=headers, params=params)

    def start_batch(self, batch_id, expected_store_version, headers):
        return self._request(
            "POST",
            f"/deli/production-batches/{batch_id}/start",
            {"expected_store_version": expected_store_version},
            headers,
        )

    def complete_batch(self, batch_id, produced_lbs, headers):
        return self._request(
            "POST",
            f"/deli/production-batches/{batch_id}/complete",
            {"produced_lbs": produced_lbs},
            headers,
        )

    def rework_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/deli/production-batches/{batch_id}/rework", payload, headers
        )

    def mark_down_batch(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/deli/production-batches/{batch_id}/mark-down", payload or {}, headers
        )

    # --- SlicerAsset ---
    def create_slicer(self, payload, headers):
        return self._request("POST", "/deli/slicers", payload, headers)

    def get_slicer(self, slicer_id, headers):
        return self._request("GET", f"/deli/slicers/{slicer_id}", headers=headers)

    def list_slicers(self, headers, params=None):
        return self._request("GET", "/deli/slicers", headers=headers, params=params)

    def assign_slicer_operator(self, slicer_id, assigned_operator_id, headers):
        return self._request(
            "POST",
            f"/deli/slicers/{slicer_id}/assign-operator",
            {"assigned_operator_id": assigned_operator_id},
            headers,
        )

    def update_slicer(self, slicer_id, payload, headers):
        return self._request("PATCH", f"/deli/slicers/{slicer_id}", payload, headers)

    # --- SanitationCycle ---
    def create_sanitation_cycle(self, payload, headers):
        return self._request("POST", "/deli/sanitation-cycles", payload, headers)

    def get_sanitation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/deli/sanitation-cycles/{cycle_id}", headers=headers)

    def list_sanitation_cycles(self, headers, params=None):
        return self._request("GET", "/deli/sanitation-cycles", headers=headers, params=params)

    def complete_sanitation_cycle(self, cycle_id, verified_by_associate_id, headers):
        return self._request(
            "POST",
            f"/deli/sanitation-cycles/{cycle_id}/complete",
            {"verified_by_associate_id": verified_by_associate_id},
            headers,
        )

    def reopen_sanitation_cycle(self, cycle_id, reason, headers):
        return self._request(
            "POST", f"/deli/sanitation-cycles/{cycle_id}/reopen", {"reason": reason}, headers
        )

    def abort_sanitation_cycle(self, cycle_id, reason, headers):
        return self._request(
            "POST", f"/deli/sanitation-cycles/{cycle_id}/abort", {"reason": reason}, headers
        )

    # --- SubTicket ---
    def create_sub_ticket(self, payload, headers):
        return self._request("POST", "/deli/sub-tickets", payload, headers)

    def get_sub_ticket(self, ticket_id, headers):
        return self._request("GET", f"/deli/sub-tickets/{ticket_id}", headers=headers)

    def list_sub_tickets(self, headers, params=None):
        return self._request("GET", "/deli/sub-tickets", headers=headers, params=params)

    def ticket_sub_ticket(self, ticket_id, headers):
        return self._request("POST", f"/deli/sub-tickets/{ticket_id}/ticket", {}, headers)

    def complete_sub_ticket(self, ticket_id, net_weight_lbs, headers):
        return self._request(
            "POST",
            f"/deli/sub-tickets/{ticket_id}/complete",
            {"net_weight_lbs": net_weight_lbs},
            headers,
        )

    def pickup_sub_ticket(self, ticket_id, headers):
        return self._request("POST", f"/deli/sub-tickets/{ticket_id}/pickup", {}, headers)

    def abandon_sub_ticket(self, ticket_id, headers):
        return self._request("POST", f"/deli/sub-tickets/{ticket_id}/abandon", {}, headers)

    def requeue_sub_ticket(self, ticket_id, headers):
        return self._request("POST", f"/deli/sub-tickets/{ticket_id}/requeue", {}, headers)

    def get_sub_queue(self, headers, params=None):
        return self._request("GET", "/deli/sub-queue", headers=headers, params=params)

    # --- Promotion ---
    def create_promotion(self, payload, headers):
        return self._request("POST", "/deli/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/deli/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/deli/promotions", headers=headers, params=params)

    def activate_promotion(self, promotion_id, headers):
        return self._request("POST", f"/deli/promotions/{promotion_id}/activate", {}, headers)

    def settle_promotion(self, promotion_id, headers):
        return self._request("POST", f"/deli/promotions/{promotion_id}/settle", {}, headers)

    def reopen_promotion(self, promotion_id, headers):
        return self._request("POST", f"/deli/promotions/{promotion_id}/reopen", {}, headers)

    def cancel_promotion(self, promotion_id, headers):
        return self._request("POST", f"/deli/promotions/{promotion_id}/cancel", {}, headers)

    # --- BreadSupplyOrder ---
    def create_bread_order(self, payload, headers):
        return self._request("POST", "/deli/bread-supply-orders", payload, headers)

    def get_bread_order(self, bread_order_id, headers):
        return self._request("GET", f"/deli/bread-supply-orders/{bread_order_id}", headers=headers)

    def list_bread_orders(self, headers, params=None):
        return self._request("GET", "/deli/bread-supply-orders", headers=headers, params=params)

    def submit_bread_order(self, bread_order_id, headers):
        return self._request(
            "POST", f"/deli/bread-supply-orders/{bread_order_id}/submit", {}, headers
        )

    def confirm_bread_order(self, bread_order_id, expected_promotion_version, headers):
        return self._request(
            "POST",
            f"/deli/bread-supply-orders/{bread_order_id}/confirm",
            {"expected_promotion_version": expected_promotion_version},
            headers,
        )

    def deliver_bread_order(self, bread_order_id, delivered_units, headers):
        return self._request(
            "POST",
            f"/deli/bread-supply-orders/{bread_order_id}/deliver",
            {"delivered_units": delivered_units},
            headers,
        )

    def reopen_bread_order(self, bread_order_id, reason, headers):
        return self._request(
            "POST", f"/deli/bread-supply-orders/{bread_order_id}/reopen", {"reason": reason}, headers
        )

    # --- ScalePriceFile ---
    def create_price_file(self, payload, headers):
        return self._request("POST", "/deli/price-files", payload, headers)

    def get_price_file(self, price_file_id, headers):
        return self._request("GET", f"/deli/price-files/{price_file_id}", headers=headers)

    def list_price_files(self, headers, params=None):
        return self._request("GET", "/deli/price-files", headers=headers, params=params)

    def activate_price_file(self, price_file_id, headers):
        return self._request("POST", f"/deli/price-files/{price_file_id}/activate", {}, headers)

    def retract_price_file(self, price_file_id, headers):
        return self._request("POST", f"/deli/price-files/{price_file_id}/retract", {}, headers)

    def reactivate_price_file(self, price_file_id, headers):
        return self._request("POST", f"/deli/price-files/{price_file_id}/reactivate", {}, headers)

    def run_production_day(self, headers, store_id=None):
        payload = {"store_id": store_id} if store_id else {}
        return self._request("PATCH", "/deli/run-production-day", payload, headers)

    def set_posture_gate(self, store_id, posture_gate_flag, headers):
        return self._request(
            "POST",
            "/deli/posture-gate",
            {"store_id": store_id, "posture_gate_flag": posture_gate_flag},
            headers,
        )

    def get_active_price_file(self, store_id, headers):
        return self._request(
            "GET", "/deli/active-price-file", headers=headers, params={"store_id": store_id}
        )

    # --- Label ---
    def create_label(self, payload, headers):
        return self._request("POST", "/deli/labels", payload, headers)

    def get_label(self, label_id, headers):
        return self._request("GET", f"/deli/labels/{label_id}", headers=headers)

    def list_labels(self, headers, params=None):
        return self._request("GET", "/deli/labels", headers=headers, params=params)

    # --- CateringOrder ---
    def create_catering_order(self, payload, headers):
        return self._request("POST", "/deli/catering-orders", payload, headers)

    def get_catering_order(self, order_id, headers):
        return self._request("GET", f"/deli/catering-orders/{order_id}", headers=headers)

    def list_catering_orders(self, headers, params=None):
        return self._request("GET", "/deli/catering-orders", headers=headers, params=params)

    def confirm_catering_order(self, order_id, headers):
        return self._request("POST", f"/deli/catering-orders/{order_id}/confirm", {}, headers)

    def revise_catering_order(self, order_id, payload, headers):
        return self._request("POST", f"/deli/catering-orders/{order_id}/revise", payload, headers)

    def start_catering_production(self, order_id, headers):
        return self._request(
            "POST", f"/deli/catering-orders/{order_id}/start-production", {}, headers
        )

    def mark_catering_ready(self, order_id, headers):
        return self._request("POST", f"/deli/catering-orders/{order_id}/mark-ready", {}, headers)

    def pickup_catering_order(self, order_id, headers):
        return self._request("POST", f"/deli/catering-orders/{order_id}/pickup", {}, headers)

    def cancel_catering_order(self, order_id, reason, headers):
        return self._request(
            "POST", f"/deli/catering-orders/{order_id}/cancel", {"reason": reason}, headers
        )

    # --- WasteRecord ---
    def create_waste_record(self, payload, headers):
        return self._request("POST", "/deli/waste-records", payload, headers)

    def get_waste_record(self, waste_id, headers):
        return self._request("GET", f"/deli/waste-records/{waste_id}", headers=headers)

    def list_waste_records(self, headers, params=None):
        return self._request("GET", "/deli/waste-records", headers=headers, params=params)

    def mark_down_waste_record(self, waste_id, markdown_by_associate_id, markdown_sold_lbs, headers):
        return self._request(
            "POST",
            f"/deli/waste-records/{waste_id}/mark-down",
            {
                "markdown_by_associate_id": markdown_by_associate_id,
                "markdown_sold_lbs": markdown_sold_lbs,
            },
            headers,
        )

    def discard_waste_record(self, waste_id, discard_lbs, headers):
        return self._request(
            "POST", f"/deli/waste-records/{waste_id}/discard", {"discard_lbs": discard_lbs}, headers
        )

    def verify_waste_record(
        self, waste_id, verifier_associate_id, verified_by_certification_id, expected_batch_version, headers
    ):
        return self._request(
            "POST",
            f"/deli/waste-records/{waste_id}/verify",
            {
                "verifier_associate_id": verifier_associate_id,
                "verified_by_certification_id": verified_by_certification_id,
                "expected_batch_version": expected_batch_version,
            },
            headers,
        )

    def unverify_waste_record(self, waste_id, reason, headers):
        return self._request(
            "POST", f"/deli/waste-records/{waste_id}/unverify", {"reason": reason}, headers
        )

    def void_waste_record(self, waste_id, reason, headers):
        return self._request(
            "POST", f"/deli/waste-records/{waste_id}/void", {"reason": reason}, headers
        )


api_client = ApiClient()