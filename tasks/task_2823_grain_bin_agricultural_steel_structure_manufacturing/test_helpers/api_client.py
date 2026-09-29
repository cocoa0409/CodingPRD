"""API client: one method per endpoint declared in the PRD.

All paths are mounted at the server root; there is no URL prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical plant clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- jurisdictions ----------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def list_jurisdictions(self, headers, params=None):
        return self._request("GET", "/jurisdictions", payload=params, headers=headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}", headers=headers
        )

    # ---------------- grain profiles ----------------
    def create_grain_profile(self, payload, headers):
        return self._request("POST", "/grain-profiles", payload, headers)

    def list_grain_profiles(self, headers, params=None):
        return self._request("GET", "/grain-profiles", payload=params, headers=headers)

    def get_grain_profile(self, grain_profile_id, headers):
        return self._request(
            "GET", f"/grain-profiles/{grain_profile_id}", headers=headers
        )

    # ---------------- coating specs ----------------
    def create_coating_spec(self, payload, headers):
        return self._request("POST", "/coating-specs", payload, headers)

    def list_coating_specs(self, headers, params=None):
        return self._request("GET", "/coating-specs", payload=params, headers=headers)

    def get_coating_spec(self, coating_spec_id, headers):
        return self._request(
            "GET", f"/coating-specs/{coating_spec_id}", headers=headers
        )

    # ---------------- roll-forming lines ----------------
    def create_roll_forming_line(self, payload, headers):
        return self._request("POST", "/roll-forming-lines", payload, headers)

    def list_roll_forming_lines(self, headers, params=None):
        return self._request(
            "GET", "/roll-forming-lines", payload=params, headers=headers
        )

    def get_roll_forming_line(self, line_id, headers):
        return self._request("GET", f"/roll-forming-lines/{line_id}", headers=headers)

    # ---------------- engineers ----------------
    def create_engineer(self, payload, headers):
        return self._request("POST", "/engineers", payload, headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/engineers", payload=params, headers=headers)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/engineers/{engineer_id}", headers=headers)

    def lapse_engineer(self, engineer_id, headers, payload=None):
        return self._request(
            "POST", f"/engineers/{engineer_id}/lapse", payload or {}, headers
        )

    # ---------------- dealers ----------------
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", "/dealers", payload=params, headers=headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def set_credit_limit(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"/dealers/{dealer_id}/credit-limit", payload, headers
        )

    def list_dealer_installation_crews(self, dealer_id, headers, params=None):
        return self._request(
            "GET",
            f"/dealers/{dealer_id}/installation-crews",
            payload=params,
            headers=headers,
        )

    # ---------------- installation crews ----------------
    def create_installation_crew(self, payload, headers):
        return self._request("POST", "/installation-crews", payload, headers)

    def list_installation_crews(self, headers, params=None):
        return self._request(
            "GET", "/installation-crews", payload=params, headers=headers
        )

    def get_installation_crew(self, crew_id, headers):
        return self._request("GET", f"/installation-crews/{crew_id}", headers=headers)

    # ---------------- bin designs ----------------
    def create_bin_design(self, payload, headers):
        return self._request("POST", "/bin-designs", payload, headers)

    def list_bin_designs(self, headers, params=None):
        return self._request("GET", "/bin-designs", payload=params, headers=headers)

    def get_bin_design(self, design_id, headers):
        return self._request("GET", f"/bin-designs/{design_id}", headers=headers)

    def create_design_analysis(self, design_id, payload, headers):
        return self._request(
            "POST", f"/bin-designs/{design_id}/analyses", payload, headers
        )

    def list_design_analyses(self, design_id, headers, params=None):
        return self._request(
            "GET", f"/bin-designs/{design_id}/analyses", payload=params, headers=headers
        )

    def submit_design_for_review(self, design_id, headers, payload=None):
        return self._request(
            "POST", f"/bin-designs/{design_id}/submit-review", payload or {}, headers
        )

    def request_design_revision(self, design_id, payload, headers):
        return self._request(
            "POST", f"/bin-designs/{design_id}/request-revision", payload, headers
        )

    def revise_bin_design(self, design_id, payload, headers):
        return self._request(
            "POST", f"/bin-designs/{design_id}/revise", payload, headers
        )

    def seal_bin_design(self, design_id, headers, payload=None):
        return self._request(
            "POST", f"/bin-designs/{design_id}/seal", payload or {}, headers
        )

    # ---------------- coil lots ----------------
    def create_coil_lot(self, payload, headers):
        return self._request("POST", "/coil-lots", payload, headers)

    def list_coil_lots(self, headers, params=None):
        return self._request("GET", "/coil-lots", payload=params, headers=headers)

    def get_coil_lot(self, coil_lot_id, headers):
        return self._request("GET", f"/coil-lots/{coil_lot_id}", headers=headers)

    # ---------------- roll-forming runs ----------------
    def create_roll_forming_run(self, payload, headers):
        return self._request("POST", "/roll-forming-runs", payload, headers)

    def list_roll_forming_runs(self, headers, params=None):
        return self._request(
            "GET", "/roll-forming-runs", payload=params, headers=headers
        )

    def get_roll_forming_run(self, run_id, headers):
        return self._request("GET", f"/roll-forming-runs/{run_id}", headers=headers)

    def complete_roll_forming_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/roll-forming-runs/{run_id}/complete", payload, headers
        )

    def void_roll_forming_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/roll-forming-runs/{run_id}/void", payload or {}, headers
        )

    # ---------------- dealer orders ----------------
    def create_dealer_order(self, payload, headers):
        return self._request("POST", "/dealer-orders", payload, headers)

    def list_dealer_orders(self, headers, params=None):
        return self._request("GET", "/dealer-orders", payload=params, headers=headers)

    def get_dealer_order(self, order_id, headers):
        return self._request("GET", f"/dealer-orders/{order_id}", headers=headers)

    def list_kit_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/dealer-orders/{order_id}/kit-lines", payload=params, headers=headers
        )

    def confirm_dealer_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/dealer-orders/{order_id}/confirm", payload or {}, headers
        )

    def post_order_payment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/dealer-orders/{order_id}/payments", payload, headers
        )

    def cancel_dealer_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/dealer-orders/{order_id}/cancel", payload or {}, headers
        )

    def assign_crew_to_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/dealer-orders/{order_id}/assign-crew", payload, headers
        )

    # ---------------- freight loads ----------------
    def create_freight_load(self, payload, headers):
        return self._request("POST", "/freight-loads", payload, headers)

    def list_freight_loads(self, headers, params=None):
        return self._request("GET", "/freight-loads", payload=params, headers=headers)

    def get_freight_load(self, load_id, headers):
        return self._request("GET", f"/freight-loads/{load_id}", headers=headers)

    def assign_order_to_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/freight-loads/{load_id}/assign-order", payload, headers
        )

    def dispatch_freight_load(self, load_id, headers, payload=None):
        return self._request(
            "POST", f"/freight-loads/{load_id}/dispatch", payload or {}, headers
        )

    def deliver_freight_load(self, load_id, headers, payload=None):
        return self._request(
            "POST", f"/freight-loads/{load_id}/deliver", payload or {}, headers
        )

    def cancel_freight_load(self, load_id, headers, payload=None):
        return self._request(
            "POST", f"/freight-loads/{load_id}/cancel", payload or {}, headers
        )

    # ---------------- field failures ----------------
    def create_field_failure(self, payload, headers):
        return self._request("POST", "/field-failures", payload, headers)

    def list_field_failures(self, headers, params=None):
        return self._request("GET", "/field-failures", payload=params, headers=headers)

    def get_field_failure(self, failure_id, headers):
        return self._request("GET", f"/field-failures/{failure_id}", headers=headers)

    def start_field_failure_analysis(self, failure_id, headers, payload=None):
        return self._request(
            "POST", f"/field-failures/{failure_id}/start-analysis", payload or {}, headers
        )

    def determine_field_failure(self, failure_id, headers, payload=None):
        return self._request(
            "POST", f"/field-failures/{failure_id}/determine", payload or {}, headers
        )


api_client = ApiClient()
