"""API client: one method per endpoint the PRD defines.

Every path is rooted at the /fresh prefix, with the single exception of the
logical-clock endpoint.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fresh"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --------------------------------------------------------------- stores
    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def get_store(self, store_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    def list_stores(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/stores", headers=headers, params=params)

    def update_store(self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"{PREFIX}/stores/{store_id}", payload, headers)

    def get_store_margin_rollup(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}/margin-rollup", headers=headers, params=params
        )

    # ---------------------------------------------------- food bank partners
    def create_food_bank_partner(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/food-bank-partners", payload, headers)

    def get_food_bank_partner(self, partner_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/food-bank-partners/{partner_id}", headers=headers
        )

    def list_food_bank_partners(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/food-bank-partners", headers=headers, params=params
        )

    def update_food_bank_partner(
        self, partner_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/food-bank-partners/{partner_id}", payload, headers
        )

    # ------------------------------------------------------ markdown ladders
    def create_markdown_ladder(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/markdown-ladders", payload, headers)

    def get_markdown_ladder(self, ladder_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/markdown-ladders/{ladder_id}", headers=headers
        )

    def list_markdown_ladders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/markdown-ladders", headers=headers, params=params
        )

    def activate_markdown_ladder(self, ladder_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/markdown-ladders/{ladder_id}/activate", {}, headers
        )

    def retire_markdown_ladder(self, ladder_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/markdown-ladders/{ladder_id}/retire", {}, headers
        )

    # ---------------------------------------------------------- departments
    def create_department(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/departments", payload, headers)

    def get_department(self, department_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/departments/{department_id}", headers=headers)

    def list_departments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/departments", headers=headers, params=params)

    def update_department(
        self, department_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/departments/{department_id}", payload, headers
        )

    def get_department_margin_report(
        self, department_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"{PREFIX}/departments/{department_id}/margin-report",
            headers=headers,
            params=params,
        )

    def run_date_code_sweep(self, department_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/departments/{department_id}/run-date-code-sweep", {}, headers
        )

    # ---------------------------------------------------------------- items
    def create_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/items", payload, headers)

    def get_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/items/{item_id}", headers=headers)

    def list_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/items", headers=headers, params=params)

    def update_item(self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"{PREFIX}/items/{item_id}", payload, headers)

    # ----------------------------------------------------------------- lots
    def create_lot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/lots", headers=headers, params=params)

    def get_markdown_quote(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/lots/{lot_id}/markdown-quote", headers=headers)

    def create_markdown(self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/markdowns", payload, headers)

    def void_markdown(self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/markdown-void", payload, headers
        )

    def post_sale(self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/sales", payload, headers)

    def withdraw_lot(self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/lots/{lot_id}/withdraw", payload, headers)

    def create_scan_price_check(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/lots/{lot_id}/scan-price-checks", payload, headers
        )

    # -------------------------------------------------------- markdown labels
    def get_markdown_label(self, label_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/markdown-labels/{label_id}", headers=headers)

    def list_markdown_labels(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/markdown-labels", headers=headers, params=params
        )

    def print_markdown_label(self, label_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/markdown-labels/{label_id}/print", {}, headers
        )

    def apply_markdown_label(self, label_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/markdown-labels/{label_id}/apply", {}, headers
        )

    def void_markdown_label(self, label_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/markdown-labels/{label_id}/void", {}, headers
        )

    # ------------------------------------------------------ scan price checks
    def get_scan_price_check(self, check_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/scan-price-checks/{check_id}", headers=headers
        )

    def list_scan_price_checks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/scan-price-checks", headers=headers, params=params
        )

    # ------------------------------------------------------- donation pickups
    def create_donation_pickup(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/donation-pickups", payload, headers)

    def get_donation_pickup(self, pickup_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/donation-pickups/{pickup_id}", headers=headers
        )

    def list_donation_pickups(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/donation-pickups", headers=headers, params=params
        )

    def create_donation_assignment(
        self, pickup_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/donation-pickups/{pickup_id}/assignments", payload, headers
        )

    def seal_donation_pickup(self, pickup_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/donation-pickups/{pickup_id}/seal", {}, headers
        )

    def confirm_donation_pickup(self, pickup_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/donation-pickups/{pickup_id}/confirm", {}, headers
        )

    def complete_donation_pickup(self, pickup_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/donation-pickups/{pickup_id}/complete", {}, headers
        )

    def cancel_donation_pickup(
        self, pickup_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/donation-pickups/{pickup_id}/cancel", payload, headers
        )

    def reconcile_donation_pickup(self, pickup_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/donation-pickups/{pickup_id}/reconcile", {}, headers
        )

    # --------------------------------------------------- donation assignments
    def get_donation_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/donation-assignments/{assignment_id}", headers=headers
        )

    def list_donation_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/donation-assignments", headers=headers, params=params
        )

    # --------------------------------------------------------- shrink events
    def create_shrink_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/shrink-events", payload, headers)

    def get_shrink_event(self, shrink_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/shrink-events/{shrink_event_id}", headers=headers
        )

    def list_shrink_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{PREFIX}/shrink-events", headers=headers, params=params)

    def verify_shrink_event(self, shrink_event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/shrink-events/{shrink_event_id}/verify", {}, headers
        )

    def dispute_shrink_event(
        self, shrink_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/shrink-events/{shrink_event_id}/dispute", payload, headers
        )

    def resubmit_shrink_event(
        self, shrink_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/shrink-events/{shrink_event_id}/resubmit", payload, headers
        )

    def void_shrink_event(self, shrink_event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/shrink-events/{shrink_event_id}/void", {}, headers
        )

    # ----------------------------------------------------- compliance audits
    def create_compliance_audit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/compliance-audits", payload, headers)

    def get_compliance_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/compliance-audits/{audit_id}", headers=headers
        )

    def list_compliance_audits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/compliance-audits", headers=headers, params=params
        )

    def sweep_compliance_audit(self, audit_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/compliance-audits/{audit_id}/sweep", {}, headers
        )

    def escalate_compliance_audit(
        self, audit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/compliance-audits/{audit_id}/escalate", payload, headers
        )

    # -------------------------------------------------------- audit findings
    def get_audit_finding(self, finding_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/audit-findings/{finding_id}", headers=headers)

    def list_audit_findings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{PREFIX}/audit-findings", headers=headers, params=params
        )

    def remediate_audit_finding(
        self, finding_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/audit-findings/{finding_id}/remediate", payload, headers
        )

    # --------------------------------------------------- order recommendations
    def create_order_recommendation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/order-recommendations", payload, headers)

    def get_order_recommendation(self, recommendation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/order-recommendations/{recommendation_id}", headers=headers
        )

    def list_order_recommendations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/order-recommendations", headers=headers, params=params
        )

    def issue_order_recommendation(self, recommendation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/order-recommendations/{recommendation_id}/issue",
            {},
            headers,
        )


api_client = ApiClient()
