"""API client: one method per endpoint in the organized-play program (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────
    def set_current_utc(self, current_utc, headers):
        return self._request(
            "POST", "/op/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ─── Stores ───────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/op/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/op/stores", headers=headers, params=params)

    def transition_store(self, store_id, payload, headers):
        return self._request(
            "POST", f"/op/stores/{store_id}/transition", payload, headers,
        )

    # ─── Set releases ─────────────────────────────────
    def create_set_release(self, payload, headers):
        return self._request("POST", "/op/set-releases", payload, headers)

    def list_set_releases(self, headers, params=None):
        return self._request("GET", "/op/set-releases", headers=headers, params=params)

    def get_set_release(self, set_release_id, headers):
        return self._request(
            "GET", f"/op/set-releases/{set_release_id}", headers=headers,
        )

    def transition_set_release(self, set_release_id, payload, headers):
        return self._request(
            "POST", f"/op/set-releases/{set_release_id}/transition", payload, headers,
        )

    # ─── Formats ──────────────────────────────────────
    def create_format(self, payload, headers):
        return self._request("POST", "/op/formats", payload, headers)

    def list_formats(self, headers, params=None):
        return self._request("GET", "/op/formats", headers=headers, params=params)

    def get_format(self, format_id, headers):
        return self._request("GET", f"/op/formats/{format_id}", headers=headers)

    def transition_format(self, format_id, payload, headers):
        return self._request(
            "POST", f"/op/formats/{format_id}/transition", payload, headers,
        )

    # ─── Event applications ───────────────────────────
    def create_event_application(self, payload, headers):
        return self._request("POST", "/op/event-applications", payload, headers)

    def list_event_applications(self, headers, params=None):
        return self._request(
            "GET", "/op/event-applications", headers=headers, params=params,
        )

    def get_event_application(self, application_id, headers):
        return self._request(
            "GET", f"/op/event-applications/{application_id}", headers=headers,
        )

    def patch_event_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"/op/event-applications/{application_id}", payload, headers,
        )

    def transition_event_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/op/event-applications/{application_id}/transition",
            payload, headers,
        )

    def get_prizing_summary(self, application_id, headers):
        return self._request(
            "GET", f"/op/event-applications/{application_id}/prizing-summary",
            headers=headers,
        )

    def create_prize_report(self, application_id, payload, headers):
        return self._request(
            "POST", f"/op/event-applications/{application_id}/prize-reports",
            payload, headers,
        )

    def redeem_code(self, application_id, payload, headers):
        return self._request(
            "POST", f"/op/event-applications/{application_id}/code-redemption",
            payload, headers,
        )

    def list_application_distributions(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/op/event-applications/{application_id}/prize-distributions",
            headers=headers, params=params,
        )

    # ─── Prize allocations ────────────────────────────
    def list_prize_allocations(self, headers, params=None):
        return self._request(
            "GET", "/op/prize-allocations", headers=headers, params=params,
        )

    def get_prize_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/op/prize-allocations/{allocation_id}", headers=headers,
        )

    def transition_prize_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/op/prize-allocations/{allocation_id}/transition",
            payload, headers,
        )

    # ─── Prize distributions ──────────────────────────
    def create_prize_distribution(self, payload, headers):
        return self._request("POST", "/op/prize-distributions", payload, headers)

    def list_prize_distributions(self, headers, params=None):
        return self._request(
            "GET", "/op/prize-distributions", headers=headers, params=params,
        )

    def get_prize_distribution(self, distribution_id, headers):
        return self._request(
            "GET", f"/op/prize-distributions/{distribution_id}", headers=headers,
        )

    def transition_prize_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/op/prize-distributions/{distribution_id}/transition",
            payload, headers,
        )

    # ─── Prize reports ────────────────────────────────
    def list_prize_reports(self, headers, params=None):
        return self._request(
            "GET", "/op/prize-reports", headers=headers, params=params,
        )

    def get_prize_report(self, report_id, headers):
        return self._request("GET", f"/op/prize-reports/{report_id}", headers=headers)

    # ─── Rules enforcement cases ──────────────────────
    def create_enforcement_case(self, payload, headers):
        return self._request("POST", "/op/enforcement-cases", payload, headers)

    def list_enforcement_cases(self, headers, params=None):
        return self._request(
            "GET", "/op/enforcement-cases", headers=headers, params=params,
        )

    def get_enforcement_case(self, case_id, headers):
        return self._request(
            "GET", f"/op/enforcement-cases/{case_id}", headers=headers,
        )

    def transition_enforcement_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/op/enforcement-cases/{case_id}/transition", payload, headers,
        )

    # ─── Code redemptions ─────────────────────────────
    def create_code_redemption(self, payload, headers):
        return self._request("POST", "/op/code-redemptions", payload, headers)

    def list_code_redemptions(self, headers, params=None):
        return self._request(
            "GET", "/op/code-redemptions", headers=headers, params=params,
        )

    def get_code_redemption(self, redemption_id, headers):
        return self._request(
            "GET", f"/op/code-redemptions/{redemption_id}", headers=headers,
        )

    def transition_code_redemption(self, redemption_id, payload, headers):
        return self._request(
            "POST", f"/op/code-redemptions/{redemption_id}/transition",
            payload, headers,
        )

    # ─── Product configurations ───────────────────────
    def create_product_configuration(self, payload, headers):
        return self._request("POST", "/op/product-configurations", payload, headers)

    def list_product_configurations(self, headers, params=None):
        return self._request(
            "GET", "/op/product-configurations", headers=headers, params=params,
        )

    def get_product_configuration(self, configuration_id, headers):
        return self._request(
            "GET", f"/op/product-configurations/{configuration_id}", headers=headers,
        )

    def transition_product_configuration(self, configuration_id, payload, headers):
        return self._request(
            "POST", f"/op/product-configurations/{configuration_id}/transition",
            payload, headers,
        )

    # ─── Allocation orders ────────────────────────────
    def create_allocation_order(self, payload, headers):
        return self._request("POST", "/op/allocation-orders", payload, headers)

    def list_allocation_orders(self, headers, params=None):
        return self._request(
            "GET", "/op/allocation-orders", headers=headers, params=params,
        )

    def get_allocation_order(self, order_id, headers):
        return self._request(
            "GET", f"/op/allocation-orders/{order_id}", headers=headers,
        )

    def transition_allocation_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/op/allocation-orders/{order_id}/transition", payload, headers,
        )

    # ─── Reprint plans ────────────────────────────────
    def create_reprint_plan(self, payload, headers):
        return self._request("POST", "/op/reprint-plans", payload, headers)

    def list_reprint_plans(self, headers, params=None):
        return self._request(
            "GET", "/op/reprint-plans", headers=headers, params=params,
        )

    def get_reprint_plan(self, plan_id, headers):
        return self._request("GET", f"/op/reprint-plans/{plan_id}", headers=headers)

    def transition_reprint_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/op/reprint-plans/{plan_id}/transition", payload, headers,
        )

    # ─── Judges ───────────────────────────────────────
    def create_judge(self, payload, headers):
        return self._request("POST", "/op/judges", payload, headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/op/judges", headers=headers, params=params)

    def get_judge(self, judge_ref, headers):
        return self._request("GET", f"/op/judges/{judge_ref}", headers=headers)

    def transition_judge(self, judge_ref, payload, headers):
        return self._request(
            "POST", f"/op/judges/{judge_ref}/transition", payload, headers,
        )


api_client = ApiClient()