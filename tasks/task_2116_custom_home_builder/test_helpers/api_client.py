"""API client: one method per endpoint published by the Custom Home Builder API."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Reference parties ────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def create_lender(self, payload, headers):
        return self._request("POST", "/lenders", payload, headers)

    def create_staff_member(self, payload, headers):
        return self._request("POST", "/staff-members", payload, headers)

    def create_subcontractor(self, payload, headers):
        return self._request("POST", "/subcontractors", payload, headers)

    # ─── Projects ─────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_contract_position(self, project_id, headers):
        return self._request(
            "GET", f"/projects/{project_id}/contract-position", headers=headers
        )

    def advance_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/advance", payload, headers)

    def final_walkthrough(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/final-walkthrough", payload, headers
        )

    # ─── Photo documents ──────────────────────────────────────────────────
    def create_photo_document(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/photo-documents", payload, headers
        )

    def list_photo_documents(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/photo-documents", headers=headers, params=params
        )

    def publish_photo_document(self, photo_id, headers):
        return self._request(
            "POST", f"/photo-documents/{photo_id}/publish", {}, headers
        )

    # ─── Allowance items ──────────────────────────────────────────────────
    def create_allowance_item(self, payload, headers):
        return self._request("POST", "/allowance-items", payload, headers)

    def get_allowance_item(self, allowance_item_id, headers):
        return self._request(
            "GET", f"/allowance-items/{allowance_item_id}", headers=headers
        )

    def list_allowance_items(self, headers, params=None):
        return self._request("GET", "/allowance-items", headers=headers, params=params)

    def settle_allowance_item(self, allowance_item_id, payload, headers):
        return self._request(
            "POST", f"/allowance-items/{allowance_item_id}/settle", payload, headers
        )

    # ─── Selections ───────────────────────────────────────────────────────
    def create_selection(self, payload, headers):
        return self._request("POST", "/selections", payload, headers)

    def get_selection(self, selection_id, headers):
        return self._request("GET", f"/selections/{selection_id}", headers=headers)

    def list_allowance_item_selections(self, allowance_item_id, headers, params=None):
        return self._request(
            "GET",
            f"/allowance-items/{allowance_item_id}/selections",
            headers=headers,
            params=params,
        )

    def decide_selection(self, selection_id, payload, headers):
        return self._request(
            "POST", f"/selections/{selection_id}/decision", payload, headers
        )

    # ─── Change orders ────────────────────────────────────────────────────
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def price_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/price", payload, headers
        )

    def submit_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/submit", {}, headers
        )

    def decide_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/client-decision", payload, headers
        )

    def void_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/change-orders/{change_order_id}/void", payload, headers
        )

    # ─── Schedule tasks ───────────────────────────────────────────────────
    def create_schedule_task(self, payload, headers):
        return self._request("POST", "/schedule-tasks", payload, headers)

    def get_schedule_task(self, task_id, headers):
        return self._request("GET", f"/schedule-tasks/{task_id}", headers=headers)

    def list_schedule_tasks(self, headers, params=None):
        return self._request("GET", "/schedule-tasks", headers=headers, params=params)

    def release_schedule_task(self, task_id, headers):
        return self._request("POST", f"/schedule-tasks/{task_id}/release", {}, headers)

    def progress_schedule_task(self, task_id, payload, headers):
        return self._request(
            "POST", f"/schedule-tasks/{task_id}/progress", payload, headers
        )

    # ─── Cost entries ─────────────────────────────────────────────────────
    def create_cost_entry(self, payload, headers):
        return self._request("POST", "/cost-entries", payload, headers)

    def get_cost_entry(self, cost_entry_id, headers):
        return self._request("GET", f"/cost-entries/{cost_entry_id}", headers=headers)

    def list_cost_entries(self, headers, params=None):
        return self._request("GET", "/cost-entries", headers=headers, params=params)

    def review_cost_entry(self, cost_entry_id, payload, headers):
        return self._request(
            "POST", f"/cost-entries/{cost_entry_id}/review", payload, headers
        )

    # ─── Draw requests ────────────────────────────────────────────────────
    def create_draw_request(self, payload, headers):
        return self._request("POST", "/draw-requests", payload, headers)

    def get_draw_request(self, draw_id, headers):
        return self._request("GET", f"/draw-requests/{draw_id}", headers=headers)

    def list_draw_requests(self, headers, params=None):
        return self._request("GET", "/draw-requests", headers=headers, params=params)

    def submit_draw_request(self, draw_id, headers):
        return self._request("POST", f"/draw-requests/{draw_id}/submit", {}, headers)

    def lender_decision(self, draw_id, payload, headers):
        return self._request(
            "POST", f"/draw-requests/{draw_id}/lender-decision", payload, headers
        )

    def void_draw_request(self, draw_id, payload, headers):
        return self._request("POST", f"/draw-requests/{draw_id}/void", payload, headers)

    # ─── Lien waivers ─────────────────────────────────────────────────────
    def get_lien_waiver(self, waiver_id, headers):
        return self._request("GET", f"/lien-waivers/{waiver_id}", headers=headers)

    def list_lien_waivers(self, headers, params=None):
        return self._request("GET", "/lien-waivers", headers=headers, params=params)

    def receive_lien_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/lien-waivers/{waiver_id}/receive", payload, headers
        )

    def review_lien_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/lien-waivers/{waiver_id}/review", payload, headers
        )

    # ─── Defect tickets ───────────────────────────────────────────────────
    def create_defect_ticket(self, payload, headers):
        return self._request("POST", "/defect-tickets", payload, headers)

    def get_defect_ticket(self, ticket_id, headers):
        return self._request("GET", f"/defect-tickets/{ticket_id}", headers=headers)

    def list_defect_tickets(self, headers, params=None):
        return self._request("GET", "/defect-tickets", headers=headers, params=params)

    def triage_defect_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/defect-tickets/{ticket_id}/triage", payload, headers
        )

    def submit_defect_for_review(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/defect-tickets/{ticket_id}/submit-for-review", payload, headers
        )

    def client_review_defect(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/defect-tickets/{ticket_id}/client-review", payload, headers
        )


api_client = ApiClient()
