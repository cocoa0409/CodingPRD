"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, payload: dict, headers: dict):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ─── ProcessingFacility ────────────────────────────────────────────────
    def create_facility(self, payload: dict, headers: dict):
        return self._request("POST", "/api/processing-facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: dict):
        return self._request("GET", f"/api/processing-facilities/{facility_id}",
                             headers=headers)

    def list_facilities(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/processing-facilities",
                             headers=headers, params=params)

    # ─── ServiceStandardRule ───────────────────────────────────────────────
    def create_service_rule(self, facility_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/api/processing-facilities/{facility_id}/service-standard-rules",
            payload, headers)

    def list_rules_for_facility(self, facility_id: str, headers: dict,
                                params: Optional[dict] = None):
        return self._request(
            "GET", f"/api/processing-facilities/{facility_id}/service-standard-rules",
            headers=headers, params=params)

    def get_rule_for_facility(self, facility_id: str, rule_id: str, headers: dict):
        return self._request(
            "GET",
            f"/api/processing-facilities/{facility_id}/service-standard-rules/{rule_id}",
            headers=headers)

    def retire_rule(self, rule_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", f"/api/service-standard-rules/{rule_id}/retire",
                             payload or {}, headers)

    def get_rule(self, rule_id: str, headers: dict):
        return self._request("GET", f"/api/service-standard-rules/{rule_id}",
                             headers=headers)

    def list_rules(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/service-standard-rules",
                             headers=headers, params=params)

    # ─── ServiceStandardQuery ──────────────────────────────────────────────
    def create_service_query(self, payload: dict, headers: dict):
        return self._request("POST", "/api/service-standard-queries", payload, headers)

    def get_service_query(self, query_id: str, headers: dict):
        return self._request("GET", f"/api/service-standard-queries/{query_id}",
                             headers=headers)

    def list_service_queries(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/service-standard-queries",
                             headers=headers, params=params)

    # ─── DeliveryUnit ──────────────────────────────────────────────────────
    def create_unit(self, payload: dict, headers: dict):
        return self._request("POST", "/api/delivery-units", payload, headers)

    def get_unit(self, unit_id: str, headers: dict):
        return self._request("GET", f"/api/delivery-units/{unit_id}", headers=headers)

    def list_units(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/delivery-units", headers=headers, params=params)

    # ─── DeliveryPoint ─────────────────────────────────────────────────────
    def create_point(self, unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/api/delivery-units/{unit_id}/delivery-points",
                             payload, headers)

    def get_point(self, unit_id: str, point_id: str, headers: dict):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/delivery-points/{point_id}",
            headers=headers)

    def get_point_flat(self, point_id: str, headers: dict):
        return self._request("GET", f"/api/delivery-points/{point_id}", headers=headers)

    def list_points(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/api/delivery-units/{unit_id}/delivery-points",
                             headers=headers, params=params)

    def list_points_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/delivery-points", headers=headers, params=params)

    def activate_point(self, unit_id: str, point_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/delivery-points/{point_id}/activate",
            payload, headers)

    def mark_vacant(self, unit_id: str, point_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/delivery-points/{point_id}/mark-vacant",
            {}, headers)

    def mark_occupied(self, unit_id: str, point_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/delivery-points/{point_id}/mark-occupied",
            {}, headers)

    def mark_seasonal(self, unit_id: str, point_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/delivery-points/{point_id}/mark-seasonal",
            {}, headers)

    def discontinue_point(self, unit_id: str, point_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/delivery-points/{point_id}/discontinue",
            {}, headers)

    # ─── Carrier ───────────────────────────────────────────────────────────
    def create_carrier(self, unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/api/delivery-units/{unit_id}/carriers",
                             payload, headers)

    def get_carrier(self, unit_id: str, carrier_id: str, headers: dict):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/carriers/{carrier_id}",
            headers=headers)

    def get_carrier_flat(self, carrier_id: str, headers: dict):
        return self._request("GET", f"/api/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/api/delivery-units/{unit_id}/carriers",
                             headers=headers, params=params)

    def list_carriers_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/carriers", headers=headers, params=params)

    # ─── CarrierRoute ──────────────────────────────────────────────────────
    def create_route(self, unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/api/delivery-units/{unit_id}/routes",
                             payload, headers)

    def get_route(self, unit_id: str, route_id: str, headers: dict):
        return self._request("GET", f"/api/delivery-units/{unit_id}/routes/{route_id}",
                             headers=headers)

    def get_route_flat(self, route_id: str, headers: dict):
        return self._request("GET", f"/api/routes/{route_id}", headers=headers)

    def list_routes(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/api/delivery-units/{unit_id}/routes",
                             headers=headers, params=params)

    def list_routes_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/routes", headers=headers, params=params)

    def suspend_route(self, unit_id: str, route_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/routes/{route_id}/suspend",
            {}, headers)

    def reactivate_route(self, unit_id: str, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/routes/{route_id}/reactivate",
            payload, headers)

    # ─── RouteSequenceEntry ────────────────────────────────────────────────
    def replace_sequence(self, unit_id: str, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/routes/{route_id}/sequence-entries",
            payload, headers)

    def list_sequence_entries(self, unit_id: str, route_id: str, headers: dict,
                              params: Optional[dict] = None):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/routes/{route_id}/sequence-entries",
            headers=headers, params=params)

    def get_sequence_entry_flat(self, entry_id: str, headers: dict):
        return self._request("GET", f"/api/sequence-entries/{entry_id}", headers=headers)

    def list_sequence_entries_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/sequence-entries", headers=headers,
                             params=params)

    # ─── RouteEvaluation ───────────────────────────────────────────────────
    def create_evaluation(self, unit_id: str, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations",
            payload, headers)

    def get_evaluation(self, unit_id: str, route_id: str, eval_id: str, headers: dict):
        return self._request(
            "GET",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}",
            headers=headers)

    def get_evaluation_flat(self, eval_id: str, headers: dict):
        return self._request("GET", f"/api/evaluations/{eval_id}", headers=headers)

    def list_evaluations(self, unit_id: str, route_id: str, headers: dict,
                         params: Optional[dict] = None):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations",
            headers=headers, params=params)

    def list_evaluations_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/evaluations", headers=headers, params=params)

    def begin_count(self, unit_id: str, route_id: str, eval_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/begin-count",
            {}, headers)

    def submit_counts(self, unit_id: str, route_id: str, eval_id: str, payload: dict,
                      headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/submit-counts",
            payload, headers)

    def record_consultation(self, unit_id: str, route_id: str, eval_id: str,
                            payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/record-consultation",
            payload, headers)

    def order_recollection(self, unit_id: str, route_id: str, eval_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/order-recollection",
            {}, headers)

    def close_rejected(self, unit_id: str, route_id: str, eval_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/close-rejected",
            {}, headers)

    # ─── RouteAdjustment ───────────────────────────────────────────────────
    def create_adjustment(self, unit_id: str, route_id: str, eval_id: str,
                          payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments",
            payload, headers)

    def get_adjustment(self, unit_id: str, route_id: str, eval_id: str, adj_id: str,
                       headers: dict):
        return self._request(
            "GET",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments/{adj_id}",
            headers=headers)

    def get_adjustment_flat(self, adj_id: str, headers: dict):
        return self._request("GET", f"/api/adjustments/{adj_id}", headers=headers)

    def list_adjustments(self, unit_id: str, route_id: str, eval_id: str, headers: dict,
                         params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments",
            headers=headers, params=params)

    def list_adjustments_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/adjustments", headers=headers, params=params)

    def submit_adjustment(self, unit_id: str, route_id: str, eval_id: str, adj_id: str,
                          headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments/{adj_id}/submit",
            {}, headers)

    def approve_adjustment(self, unit_id: str, route_id: str, eval_id: str, adj_id: str,
                           headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments/{adj_id}/approve",
            {}, headers)

    def reject_adjustment(self, unit_id: str, route_id: str, eval_id: str, adj_id: str,
                          headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments/{adj_id}/reject",
            {}, headers)

    def withdraw_adjustment(self, unit_id: str, route_id: str, eval_id: str, adj_id: str,
                            headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/evaluations/{eval_id}/adjustments/{adj_id}/withdraw",
            {}, headers)

    # ─── AuxiliaryAssignment ───────────────────────────────────────────────
    def create_auxiliary(self, unit_id: str, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/auxiliary-assignments",
            payload, headers)

    def get_auxiliary_flat(self, aux_id: str, headers: dict):
        return self._request("GET", f"/api/auxiliary-assignments/{aux_id}",
                             headers=headers)

    def list_auxiliary(self, unit_id: str, route_id: str, headers: dict,
                       params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/auxiliary-assignments",
            headers=headers, params=params)

    def list_auxiliary_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/auxiliary-assignments", headers=headers,
                             params=params)

    def approve_auxiliary(self, unit_id: str, route_id: str, aux_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/auxiliary-assignments/{aux_id}/approve",
            {}, headers)

    def deny_auxiliary(self, unit_id: str, route_id: str, aux_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/auxiliary-assignments/{aux_id}/deny",
            {}, headers)

    def complete_auxiliary(self, unit_id: str, route_id: str, aux_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/auxiliary-assignments/{aux_id}/complete",
            {}, headers)

    def curtail_auxiliary(self, unit_id: str, route_id: str, aux_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/routes/{route_id}/auxiliary-assignments/{aux_id}/curtail",
            {}, headers)

    # ─── ChangeOfAddress ───────────────────────────────────────────────────
    def create_coa(self, unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/api/delivery-units/{unit_id}/coas",
                             payload, headers)

    def get_coa(self, unit_id: str, coa_id: str, headers: dict):
        return self._request("GET", f"/api/delivery-units/{unit_id}/coas/{coa_id}",
                             headers=headers)

    def get_coa_flat(self, coa_id: str, headers: dict):
        return self._request("GET", f"/api/coas/{coa_id}", headers=headers)

    def list_coas(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/api/delivery-units/{unit_id}/coas",
                             headers=headers, params=params)

    def list_coas_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/coas", headers=headers, params=params)

    def verify_coa(self, unit_id: str, coa_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/coas/{coa_id}/verify", {}, headers)

    def reject_coa_validation(self, unit_id: str, coa_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/coas/{coa_id}/reject-validation",
            {}, headers)

    def activate_coa_now(self, unit_id: str, coa_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/coas/{coa_id}/activate-now",
            {}, headers)

    def suspend_coa(self, unit_id: str, coa_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/coas/{coa_id}/suspend", {}, headers)

    def resume_coa(self, unit_id: str, coa_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/coas/{coa_id}/resume", {}, headers)

    def cancel_coa(self, unit_id: str, coa_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/coas/{coa_id}/cancel", {}, headers)

    # ─── HoldMail ──────────────────────────────────────────────────────────
    def create_hold(self, unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/api/delivery-units/{unit_id}/holds",
                             payload, headers)

    def get_hold(self, unit_id: str, hold_id: str, headers: dict):
        return self._request("GET", f"/api/delivery-units/{unit_id}/holds/{hold_id}",
                             headers=headers)

    def get_hold_flat(self, hold_id: str, headers: dict):
        return self._request("GET", f"/api/holds/{hold_id}", headers=headers)

    def list_holds(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/api/delivery-units/{unit_id}/holds",
                             headers=headers, params=params)

    def list_holds_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/holds", headers=headers, params=params)

    def complete_hold_early(self, unit_id: str, hold_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/holds/{hold_id}/complete-early",
            {}, headers)

    def cancel_hold(self, unit_id: str, hold_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/holds/{hold_id}/cancel", {}, headers)

    # ─── DeliveryScanEvent / compliance ────────────────────────────────────
    def create_scan_event(self, unit_id: str, route_id: str, payload: dict,
                          headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/routes/{route_id}/scan-events",
            payload, headers)

    def list_scan_events(self, unit_id: str, route_id: str, headers: dict,
                         params: Optional[dict] = None):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/routes/{route_id}/scan-events",
            headers=headers, params=params)

    def list_scan_events_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/scan-events", headers=headers, params=params)

    def get_scan_event_flat(self, event_id: str, headers: dict):
        return self._request("GET", f"/api/scan-events/{event_id}", headers=headers)

    def get_scan_compliance(self, unit_id: str, headers: dict,
                            params: Optional[dict] = None):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/scan-compliance",
            headers=headers, params=params)

    # ─── CustomerInquiry ───────────────────────────────────────────────────
    def create_inquiry(self, unit_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/api/delivery-units/{unit_id}/inquiries",
                             payload, headers)

    def get_inquiry(self, unit_id: str, inquiry_id: str, headers: dict):
        return self._request(
            "GET", f"/api/delivery-units/{unit_id}/inquiries/{inquiry_id}",
            headers=headers)

    def get_inquiry_flat(self, inquiry_id: str, headers: dict):
        return self._request("GET", f"/api/inquiries/{inquiry_id}", headers=headers)

    def list_inquiries(self, unit_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/api/delivery-units/{unit_id}/inquiries",
                             headers=headers, params=params)

    def list_inquiries_flat(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/api/inquiries", headers=headers, params=params)

    def begin_investigation(self, unit_id: str, inquiry_id: str, headers: dict):
        return self._request(
            "POST",
            f"/api/delivery-units/{unit_id}/inquiries/{inquiry_id}/begin-investigation",
            {}, headers)

    def resolve_inquiry(self, unit_id: str, inquiry_id: str, payload: dict,
                        headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/inquiries/{inquiry_id}/resolve",
            payload, headers)

    def reopen_inquiry(self, unit_id: str, inquiry_id: str, headers: dict):
        return self._request(
            "POST", f"/api/delivery-units/{unit_id}/inquiries/{inquiry_id}/reopen",
            {}, headers)


api_client = ApiClient()


def raw_request(client: ApiClient, method: str, path: str,
                payload: Any = None, headers: Optional[Dict[str, str]] = None,
                params: Optional[dict] = None):
    """Escape hatch for endpoints with no dedicated method (e.g. header-less probes)."""
    return client._request(method, path, payload, headers, params)
