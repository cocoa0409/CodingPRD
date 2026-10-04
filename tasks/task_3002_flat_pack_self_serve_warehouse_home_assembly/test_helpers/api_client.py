"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/api/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/api/stores/{store_id}", headers=headers)

    def list_store_stock(self, store_id, headers, params=None):
        return self._request("GET", f"/api/stores/{store_id}/stock", headers=headers, params=params)

    def get_stock_signal(self, store_id, article_id, headers):
        return self._request("GET", f"/api/stores/{store_id}/articles/{article_id}/signal", headers=headers)

    def run_sweep(self, store_id, headers):
        return self._request("POST", f"/api/stores/{store_id}/run_sweep", {}, headers)

    # --- articles / cartons ---
    def create_article(self, payload, headers):
        return self._request("POST", "/api/articles", payload, headers)

    def get_article(self, article_id, headers):
        return self._request("GET", f"/api/articles/{article_id}", headers=headers)

    def update_article(self, article_id, payload, headers):
        return self._request("PATCH", f"/api/articles/{article_id}", payload, headers)

    def create_carton(self, article_id, payload, headers):
        return self._request("POST", f"/api/articles/{article_id}/cartons", payload, headers)

    def list_cartons(self, article_id, headers):
        return self._request("GET", f"/api/articles/{article_id}/cartons", headers=headers)

    # --- bin stock ---
    def create_bin_stock(self, payload, headers):
        return self._request("POST", "/api/bin-stock", payload, headers)

    def get_bin_stock(self, bin_stock_id, headers):
        return self._request("GET", f"/api/bin-stock/{bin_stock_id}", headers=headers)

    def list_bin_stock(self, headers, params=None):
        return self._request("GET", "/api/bin-stock", headers=headers, params=params)

    def adjust_bin_stock(self, bin_stock_id, payload, headers):
        return self._request("POST", f"/api/bin-stock/{bin_stock_id}/adjust", payload, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def enroll_customer(self, customer_id, headers):
        return self._request("POST", f"/api/customers/{customer_id}/enroll", {}, headers)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/customers/{customer_id}/orders", headers=headers, params=params)

    def list_customer_claims(self, customer_id, headers, params=None):
        return self._request("GET", f"/api/customers/{customer_id}/spare-part-claims", headers=headers, params=params)

    # --- orders / order lines ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/lines", headers=headers)

    def list_order_delivery_bookings(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/delivery-bookings", headers=headers)

    def list_order_assembly_jobs(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/assembly-jobs", headers=headers)

    def list_order_returns(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/returns", headers=headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}", headers=headers)

    def list_order_lines_global(self, headers, params=None):
        return self._request("GET", "/api/order-lines", headers=headers, params=params)

    def checkout_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/checkout", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    def pickup_complete(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/pickup-complete", {}, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/close", {}, headers)

    # --- reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/api/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/api/reservations", headers=headers, params=params)

    def fulfill_reservation(self, reservation_id, headers):
        return self._request("POST", f"/api/reservations/{reservation_id}/fulfill", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/api/reservations/{reservation_id}/cancel", {}, headers)

    # --- delivery slots / bookings ---
    def create_delivery_slot(self, payload, headers):
        return self._request("POST", "/api/delivery-slots", payload, headers)

    def get_delivery_slot(self, slot_id, headers):
        return self._request("GET", f"/api/delivery-slots/{slot_id}", headers=headers)

    def list_delivery_slots(self, headers, params=None):
        return self._request("GET", "/api/delivery-slots", headers=headers, params=params)

    def list_slot_bookings(self, slot_id, headers):
        return self._request("GET", f"/api/delivery-slots/{slot_id}/bookings", headers=headers)

    def create_delivery_booking(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/delivery-bookings", payload, headers)

    def get_delivery_booking(self, booking_id, headers):
        return self._request("GET", f"/api/delivery-bookings/{booking_id}", headers=headers)

    def cancel_delivery_booking(self, booking_id, headers):
        return self._request("POST", f"/api/delivery-bookings/{booking_id}/cancel", {}, headers)

    def start_delivery_booking(self, booking_id, headers):
        return self._request("POST", f"/api/delivery-bookings/{booking_id}/start", {}, headers)

    def complete_delivery_booking(self, booking_id, headers):
        return self._request("POST", f"/api/delivery-bookings/{booking_id}/complete", {}, headers)

    # --- assembly standards / jobs ---
    def create_assembly_standard(self, payload, headers):
        return self._request("POST", "/api/assembly-standards", payload, headers)

    def get_assembly_standard(self, standard_id, headers):
        return self._request("GET", f"/api/assembly-standards/{standard_id}", headers=headers)

    def list_assembly_standards(self, headers, params=None):
        return self._request("GET", "/api/assembly-standards", headers=headers, params=params)

    def create_assembly_job(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/assembly-jobs", payload, headers)

    def get_assembly_job(self, job_id, headers):
        return self._request("GET", f"/api/assembly-jobs/{job_id}", headers=headers)

    def dispatch_assembly_job(self, job_id, headers):
        return self._request("POST", f"/api/assembly-jobs/{job_id}/dispatch", {}, headers)

    def start_assembly_job(self, job_id, headers):
        return self._request("POST", f"/api/assembly-jobs/{job_id}/start", {}, headers)

    def hold_assembly_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/assembly-jobs/{job_id}/hold", payload, headers)

    def resume_assembly_job(self, job_id, headers):
        return self._request("POST", f"/api/assembly-jobs/{job_id}/resume", {}, headers)

    def complete_assembly_job(self, job_id, payload, headers):
        return self._request("POST", f"/api/assembly-jobs/{job_id}/complete", payload, headers)

    def cancel_assembly_job(self, job_id, headers):
        return self._request("POST", f"/api/assembly-jobs/{job_id}/cancel", {}, headers)

    # --- spare-part claims ---
    def create_spare_part_claim(self, payload, headers):
        return self._request("POST", "/api/spare-part-claims", payload, headers)

    def get_spare_part_claim(self, claim_id, headers):
        return self._request("GET", f"/api/spare-part-claims/{claim_id}", headers=headers)

    def list_spare_part_claims(self, headers, params=None):
        return self._request("GET", "/api/spare-part-claims", headers=headers, params=params)

    def review_spare_part_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/spare-part-claims/{claim_id}/review", payload, headers)

    def ship_spare_part_claim(self, claim_id, headers):
        return self._request("POST", f"/api/spare-part-claims/{claim_id}/ship", {}, headers)

    # --- returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/api/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/api/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/api/returns", headers=headers, params=params)

    def add_return_line(self, return_id, payload, headers):
        return self._request("POST", f"/api/returns/{return_id}/lines", payload, headers)

    def list_return_lines(self, return_id, headers):
        return self._request("GET", f"/api/returns/{return_id}/lines", headers=headers)

    def get_return_line(self, line_id, headers):
        return self._request("GET", f"/api/return-lines/{line_id}", headers=headers)

    def list_return_lines_global(self, headers, params=None):
        return self._request("GET", "/api/return-lines", headers=headers, params=params)

    def submit_return(self, return_id, headers):
        return self._request("POST", f"/api/returns/{return_id}/submit", {}, headers)

    def grade_return_line(self, return_id, line_id, payload, headers):
        return self._request("POST", f"/api/returns/{return_id}/lines/{line_id}/grade", payload, headers)

    def settle_return(self, return_id, headers):
        return self._request("POST", f"/api/returns/{return_id}/settle", {}, headers)

    def dispute_return(self, return_id, headers):
        return self._request("POST", f"/api/returns/{return_id}/dispute", {}, headers)

    def reopen_return(self, return_id, headers):
        return self._request("POST", f"/api/returns/{return_id}/reopen", {}, headers)


api_client = ApiClient()
