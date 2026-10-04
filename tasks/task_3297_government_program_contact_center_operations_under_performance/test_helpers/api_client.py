"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def transition_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/transition", payload, headers
        )

    def list_contract_surge_windows(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/surge-windows", headers=headers, params=params
        )

    def list_contract_incidents(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/incidents", headers=headers, params=params
        )

    # --- service levels ---
    def create_service_level(self, payload, headers):
        return self._request("POST", "/service-levels", payload, headers)

    def list_service_levels(self, headers, params=None):
        return self._request("GET", "/service-levels", headers=headers, params=params)

    def get_service_level(self, sl_id, headers):
        return self._request("GET", f"/service-levels/{sl_id}", headers=headers)

    def transition_service_level(self, sl_id, payload, headers):
        return self._request(
            "POST", f"/service-levels/{sl_id}/transition", payload, headers
        )

    def list_service_level_invoice_lines(self, sl_id, headers, params=None):
        return self._request(
            "GET", f"/service-levels/{sl_id}/invoice-lines", headers=headers, params=params
        )

    # --- agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def transition_agent(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/transition", payload, headers)

    def list_agent_completions(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agents/{agent_id}/completions", headers=headers, params=params
        )

    # --- training / certifications ---
    def create_training_course(self, payload, headers):
        return self._request("POST", "/training-courses", payload, headers)

    def get_training_course(self, course_id, headers):
        return self._request("GET", f"/training-courses/{course_id}", headers=headers)

    def complete_training_course(self, course_id, payload, headers):
        return self._request(
            "POST", f"/training-courses/{course_id}/complete", payload, headers
        )

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/certifications/{cert_id}", headers=headers)

    def list_course_completions(self, headers, params=None):
        return self._request("GET", "/course-completions", headers=headers, params=params)

    def get_course_completion(self, completion_id, headers):
        return self._request(
            "GET", f"/course-completions/{completion_id}", headers=headers
        )

    # --- queues ---
    def create_queue(self, payload, headers):
        return self._request("POST", "/queues", payload, headers)

    def list_queues(self, headers, params=None):
        return self._request("GET", "/queues", headers=headers, params=params)

    def get_queue(self, queue_id, headers):
        return self._request("GET", f"/queues/{queue_id}", headers=headers)

    def patch_queue(self, queue_id, payload, headers):
        return self._request("PATCH", f"/queues/{queue_id}", payload, headers)

    def transition_queue(self, queue_id, payload, headers):
        return self._request("POST", f"/queues/{queue_id}/transition", payload, headers)

    def list_queue_calls(self, queue_id, headers, params=None):
        return self._request(
            "GET", f"/queues/{queue_id}/calls", headers=headers, params=params
        )

    # --- calls ---
    def create_call(self, payload, headers):
        return self._request("POST", "/calls", payload, headers)

    def list_calls(self, headers, params=None):
        return self._request("GET", "/calls", headers=headers, params=params)

    def get_call(self, call_id, headers):
        return self._request("GET", f"/calls/{call_id}", headers=headers)

    def transition_call(self, call_id, payload, headers):
        return self._request("POST", f"/calls/{call_id}/transition", payload, headers)

    # --- quality reviews ---
    def create_quality_review(self, payload, headers):
        return self._request("POST", "/quality-reviews", payload, headers)

    def list_quality_reviews(self, headers, params=None):
        return self._request("GET", "/quality-reviews", headers=headers, params=params)

    def get_quality_review(self, review_id, headers):
        return self._request("GET", f"/quality-reviews/{review_id}", headers=headers)

    def transition_quality_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/quality-reviews/{review_id}/transition", payload, headers
        )

    # --- coaching plans ---
    def create_coaching_plan(self, payload, headers):
        return self._request("POST", "/coaching-plans", payload, headers)

    def list_coaching_plans(self, headers, params=None):
        return self._request("GET", "/coaching-plans", headers=headers, params=params)

    def get_coaching_plan(self, plan_id, headers):
        return self._request("GET", f"/coaching-plans/{plan_id}", headers=headers)

    def transition_coaching_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/coaching-plans/{plan_id}/transition", payload, headers
        )

    # --- knowledge articles ---
    def create_knowledge_article(self, payload, headers):
        return self._request("POST", "/knowledge-articles", payload, headers)

    def list_knowledge_articles(self, headers, params=None):
        return self._request("GET", "/knowledge-articles", headers=headers, params=params)

    def get_knowledge_article(self, article_id, headers):
        return self._request("GET", f"/knowledge-articles/{article_id}", headers=headers)

    def transition_knowledge_article(self, article_id, payload, headers):
        return self._request(
            "POST", f"/knowledge-articles/{article_id}/transition", payload, headers
        )

    def list_article_training_courses(self, article_id, headers, params=None):
        return self._request(
            "GET",
            f"/knowledge-articles/{article_id}/training-courses",
            headers=headers,
            params=params,
        )

    # --- surge windows ---
    def create_surge_window(self, payload, headers):
        return self._request("POST", "/surge-windows", payload, headers)

    def list_surge_windows(self, headers, params=None):
        return self._request("GET", "/surge-windows", headers=headers, params=params)

    def get_surge_window(self, window_id, headers):
        return self._request("GET", f"/surge-windows/{window_id}", headers=headers)

    def transition_surge_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/surge-windows/{window_id}/transition", payload, headers
        )

    # --- incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/incidents/{incident_id}", headers=headers)

    def transition_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/transition", payload, headers)

    # --- invoices / lines / cure periods ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/invoices/{invoice_id}/transition", payload, headers
        )

    def prepare_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/prepare", {}, headers)

    def recompute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/recompute", {}, headers)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/invoices/{invoice_id}/lines", headers=headers, params=params
        )

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/invoice-lines/{line_id}", headers=headers)

    def list_line_cure_periods(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/invoice-lines/{line_id}/cure-periods", headers=headers, params=params
        )

    def pay_cure_remedy(self, cure_period_id, headers):
        return self._request(
            "POST", f"/cure-periods/{cure_period_id}/pay-remedy", {}, headers
        )


api_client = ApiClient()
