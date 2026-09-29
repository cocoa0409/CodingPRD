"""One method per endpoint of the inland marine underwriting API.

Every path is mounted under the ``/inland-marine`` prefix except the
administrative clock endpoint, which is deliberately outside it. List methods
take the filter parameters the specification publishes for that collection and
pass them through as query-string parameters alongside ``limit`` and ``offset``.

The equipment-item removal endpoint uses the HTTP DELETE method but returns HTTP
200 with the updated item, because the item is retained in status REMOVED rather
than erased, so the method here returns the raw response like every other.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/inland-marine"


def _query(limit: Optional[int], offset: Optional[int], **filters: Any) -> Dict[str, Any]:
    """Assemble a query string from pagination plus the supplied filters."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    for key, value in filters.items():
        if value is not None:
            params[key] = value
    return params


class ApiClient(GenericApiClient):
    """Typed façade over the endpoint table."""

    # ─── The logical clock ────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers=None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload: Dict[str, Any], headers=None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Rate development ─────────────────────────────────────────────────────

    def create_rate_rule(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rate-rules", payload, headers)

    def publish_rate_rule(self, rule_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/rate-rules/{rule_id}/publish",
                             payload if payload is not None else {}, headers)

    def get_rate_rule(self, rule_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/rate-rules/{rule_id}", None, headers)

    # ─── Policies ─────────────────────────────────────────────────────────────

    def create_policy(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies", payload, headers)

    def get_policy(self, policy_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", None, headers)

    def get_premium_summary(self, policy_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/policies/{policy_id}/premium-summary",
                             None, headers)

    def list_coverage_parts(self, policy_id, headers=None, limit=None, offset=None,
                            part_type=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/coverage-parts", None, headers,
            params=_query(limit, offset, part_type=part_type))

    def list_ledger_entries(self, policy_id, headers=None, limit=None, offset=None,
                            ledger=None, entry_type=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/ledger-entries", None, headers,
            params=_query(limit, offset, ledger=ledger, entry_type=entry_type))

    def quote_policy(self, policy_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/quote",
                             payload if payload is not None else {}, headers)

    def refer_policy(self, policy_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/refer",
                             payload if payload is not None else {}, headers)

    def decide_referral(self, policy_id, payload, headers=None) -> requests.Response:
        return self._request("POST",
                             f"{PREFIX}/policies/{policy_id}/referral-decision",
                             payload, headers)

    def bind_policy(self, policy_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/bind",
                             payload if payload is not None else {}, headers)

    def activate_policy(self, policy_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/activate",
                             payload if payload is not None else {}, headers)

    def cancel_policy(self, policy_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/cancel",
                             payload, headers)

    def create_coverage_part(self, policy_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/coverage-parts",
                             payload, headers)

    def create_claim(self, policy_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/policies/{policy_id}/claims",
                             payload, headers)

    # ─── Coverage parts ───────────────────────────────────────────────────────

    def get_coverage_part(self, part_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/coverage-parts/{part_id}", None, headers)

    def patch_coverage_part(self, part_id, payload, headers=None) -> requests.Response:
        return self._request("PATCH", f"{PREFIX}/coverage-parts/{part_id}",
                             payload, headers)

    def list_part_equipment_items(self, part_id, headers=None, limit=None, offset=None,
                                  status=None, coverage_part_id=None,
                                  assigned_jobsite_id=None,
                                  applied_rate_rule_id=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/coverage-parts/{part_id}/equipment-items", None, headers,
            params=_query(limit, offset, status=status,
                          coverage_part_id=coverage_part_id,
                          assigned_jobsite_id=assigned_jobsite_id,
                          applied_rate_rule_id=applied_rate_rule_id))

    def list_value_reports(self, part_id, headers=None, limit=None, offset=None,
                           status=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/coverage-parts/{part_id}/value-reports", None, headers,
            params=_query(limit, offset, status=status))

    def create_equipment_item(self, part_id, payload, headers=None) -> requests.Response:
        return self._request("POST",
                             f"{PREFIX}/coverage-parts/{part_id}/equipment-items",
                             payload, headers)

    def create_installation_floater(self, part_id, payload, headers=None) -> requests.Response:
        return self._request("POST",
                             f"{PREFIX}/coverage-parts/{part_id}/installation-floaters",
                             payload, headers)

    def create_transit_shipment(self, part_id, payload, headers=None) -> requests.Response:
        return self._request("POST",
                             f"{PREFIX}/coverage-parts/{part_id}/transit-shipments",
                             payload, headers)

    def create_value_report(self, part_id, payload, headers=None) -> requests.Response:
        return self._request("POST",
                             f"{PREFIX}/coverage-parts/{part_id}/value-reports",
                             payload, headers)

    def run_reporting_sweep(self, part_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST",
                             f"{PREFIX}/coverage-parts/{part_id}/reporting-sweep",
                             payload if payload is not None else {}, headers)

    # ─── Equipment items ──────────────────────────────────────────────────────

    def get_equipment_item(self, item_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/equipment-items/{item_id}", None, headers)

    def list_equipment_items(self, headers=None, limit=None, offset=None, status=None,
                             coverage_part_id=None, assigned_jobsite_id=None,
                             applied_rate_rule_id=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/equipment-items", None, headers,
            params=_query(limit, offset, status=status,
                          coverage_part_id=coverage_part_id,
                          assigned_jobsite_id=assigned_jobsite_id,
                          applied_rate_rule_id=applied_rate_rule_id))

    def assign_jobsite(self, item_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/equipment-items/{item_id}/assign-jobsite",
                             payload, headers)

    def activate_equipment_item(self, item_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/equipment-items/{item_id}/activate",
                             payload if payload is not None else {}, headers)

    def delete_equipment_item(self, item_id, headers=None) -> requests.Response:
        return self._request("DELETE", f"{PREFIX}/equipment-items/{item_id}",
                             None, headers)

    # ─── Jobsites ─────────────────────────────────────────────────────────────

    def create_jobsite(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/jobsites", payload, headers)

    def get_jobsite(self, jobsite_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/jobsites/{jobsite_id}", None, headers)

    def record_security_survey(self, jobsite_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/jobsites/{jobsite_id}/security-survey",
                             payload, headers)

    # ─── Installation floaters ────────────────────────────────────────────────

    def get_installation_floater(self, floater_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/installation-floaters/{floater_id}",
                             None, headers)

    def list_installation_floaters(self, headers=None, limit=None, offset=None,
                                   status=None, coverage_part_id=None,
                                   jobsite_id=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/installation-floaters", None, headers,
            params=_query(limit, offset, status=status,
                          coverage_part_id=coverage_part_id, jobsite_id=jobsite_id))

    def activate_installation_floater(self, floater_id, headers=None,
                                      payload=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/installation-floaters/{floater_id}/activate",
            payload if payload is not None else {}, headers)

    def terminate_installation_floater(self, floater_id, payload,
                                       headers=None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/installation-floaters/{floater_id}/terminate",
            payload, headers)

    # ─── Conveyances ──────────────────────────────────────────────────────────

    def create_vehicle(self, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/vehicles/{vehicle_id}", None, headers)

    def approve_vehicle(self, vehicle_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/vehicles/{vehicle_id}/approve",
                             payload if payload is not None else {}, headers)

    # ─── Transit shipments ────────────────────────────────────────────────────

    def get_transit_shipment(self, shipment_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/transit-shipments/{shipment_id}",
                             None, headers)

    def list_transit_shipments(self, headers=None, limit=None, offset=None, status=None,
                               coverage_part_id=None, vehicle_id=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/transit-shipments", None, headers,
            params=_query(limit, offset, status=status,
                          coverage_part_id=coverage_part_id, vehicle_id=vehicle_id))

    def depart_shipment(self, shipment_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/transit-shipments/{shipment_id}/depart",
                             payload if payload is not None else {}, headers)

    def deliver_shipment(self, shipment_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/transit-shipments/{shipment_id}/deliver",
                             payload if payload is not None else {}, headers)

    # ─── Value reports ────────────────────────────────────────────────────────

    def get_value_report(self, report_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/value-reports/{report_id}", None, headers)

    def list_superseded_reports(self, report_id, headers=None, limit=None,
                                offset=None, status=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/value-reports/{report_id}/superseded-reports", None,
            headers, params=_query(limit, offset, status=status))

    def adjudicate_value_report(self, report_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/value-reports/{report_id}/adjudicate",
                             payload if payload is not None else {}, headers)

    # ─── Claims ───────────────────────────────────────────────────────────────

    def get_claim(self, claim_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", None, headers)

    def list_claims(self, headers=None, limit=None, offset=None, policy_id=None,
                    coverage_part_id=None, equipment_item_id=None,
                    transit_shipment_id=None, installation_floater_id=None,
                    adjustment_status=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/claims", None, headers,
            params=_query(limit, offset, policy_id=policy_id,
                          coverage_part_id=coverage_part_id,
                          equipment_item_id=equipment_item_id,
                          transit_shipment_id=transit_shipment_id,
                          installation_floater_id=installation_floater_id,
                          adjustment_status=adjustment_status))

    def list_claim_ledger_entries(self, claim_id, headers=None, limit=None,
                                  offset=None, ledger=None,
                                  entry_type=None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/ledger-entries", None, headers,
            params=_query(limit, offset, ledger=ledger, entry_type=entry_type))

    def get_settlement_worksheet(self, claim_id, headers=None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/settlement-worksheet",
                             None, headers)

    def inspect_claim(self, claim_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/inspect",
                             payload, headers)

    def adjust_claim(self, claim_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/adjust",
                             payload, headers)

    def settle_claim(self, claim_id, headers=None, payload=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/settle",
                             payload if payload is not None else {}, headers)

    def record_salvage_recovery(self, claim_id, payload, headers=None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/salvage-recovery",
                             payload, headers)
