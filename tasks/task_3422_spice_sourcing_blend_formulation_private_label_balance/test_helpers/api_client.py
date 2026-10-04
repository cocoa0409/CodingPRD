"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Spice sourcing API client. All methods return the raw Response."""

    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Suppliers (PRD §3.1) ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/spice/suppliers", payload, headers)

    # --- Raw lots (PRD §3.1, §3.2) ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/spice/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/spice/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/spice/lots", headers=headers, params=params)

    def disposition_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/spice/lots/{lot_id}/disposition",
                             payload, headers)

    # --- Safety tests (PRD §3.2) ---
    def post_test(self, lot_id, payload, headers):
        return self._request("POST", f"/spice/lots/{lot_id}/tests", payload, headers)

    def list_tests(self, lot_id, headers, params=None):
        return self._request("GET", f"/spice/lots/{lot_id}/tests",
                             headers=headers, params=params)

    # --- Blend formulas and lines (PRD §3.3) ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/spice/formulas", payload, headers)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/spice/formulas/{formula_id}", headers=headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/spice/formulas", headers=headers, params=params)

    def add_formula_line(self, formula_id, payload, headers):
        return self._request("POST", f"/spice/formulas/{formula_id}/lines",
                             payload, headers)

    def list_formula_lines(self, formula_id, headers, params=None):
        return self._request("GET", f"/spice/formulas/{formula_id}/lines",
                             headers=headers, params=params)

    def activate_formula(self, formula_id, headers):
        return self._request("POST", f"/spice/formulas/{formula_id}/activate",
                             {}, headers)

    # --- Blend runs (PRD §3.4) ---
    def create_blend_run(self, payload, headers):
        return self._request("POST", "/spice/blend-runs", payload, headers)

    def get_blend_run(self, run_id, headers):
        return self._request("GET", f"/spice/blend-runs/{run_id}", headers=headers)

    def list_blend_runs(self, headers, params=None):
        return self._request("GET", "/spice/blend-runs", headers=headers, params=params)

    def commit_blend_run(self, run_id, headers):
        return self._request("POST", f"/spice/blend-runs/{run_id}/commit", {}, headers)

    def void_blend_run(self, run_id, headers):
        return self._request("POST", f"/spice/blend-runs/{run_id}/void", {}, headers)

    # --- Production lines (PRD §3.5) ---
    def create_line(self, payload, headers):
        return self._request("POST", "/spice/lines", payload, headers)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/spice/lines/{line_id}", headers=headers)

    # --- Production runs (PRD §3.5, §3.6) ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/spice/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/spice/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/spice/production-runs",
                             headers=headers, params=params)

    def complete_production_run(self, run_id, headers):
        return self._request("POST", f"/spice/production-runs/{run_id}/complete",
                             {}, headers)

    def cancel_production_run(self, run_id, headers):
        return self._request("POST", f"/spice/production-runs/{run_id}/cancel",
                             {}, headers)

    # --- Finished batches (PRD §3.6) ---
    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/spice/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/spice/batches", headers=headers, params=params)

    def ship_batch(self, batch_id, headers):
        return self._request("POST", f"/spice/batches/{batch_id}/ship", {}, headers)

    def hold_batch(self, batch_id, headers, note=None):
        payload = {} if note is None else {"note": note}
        return self._request("POST", f"/spice/batches/{batch_id}/hold", payload, headers)

    # --- Recall cases (PRD §3.7) ---
    def create_recall_case(self, payload, headers):
        return self._request("POST", "/spice/recall-cases", payload, headers)

    def get_recall_case(self, case_id, headers):
        return self._request("GET", f"/spice/recall-cases/{case_id}", headers=headers)

    def list_recall_cases(self, headers, params=None):
        return self._request("GET", "/spice/recall-cases", headers=headers, params=params)

    def initiate_recall_case(self, case_id, headers):
        return self._request("POST", f"/spice/recall-cases/{case_id}/initiate",
                             {}, headers)

    def close_recall_case(self, case_id, headers):
        return self._request("POST", f"/spice/recall-cases/{case_id}/close",
                             {}, headers)

    # --- Private-label agreements (PRD §3.8) ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/spice/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/spice/agreements/{agreement_id}", headers=headers)

    # --- Capacity reservations (PRD §3.8) ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/spice/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/spice/reservations/{reservation_id}",
                             headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/spice/reservations", headers=headers, params=params)


api_client = ApiClient()
