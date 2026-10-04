"""API client: one method per endpoint defined in PRD §4.

All business endpoints live under the /carpetloop prefix. The logical-clock
administration endpoint POST /_clock/set_current_utc (PRD §2.5) lives OUTSIDE
the prefix and is sent unprefixed by set_clock().

Creation endpoints return 201 (PRD §4); actions and reads return 200. These
methods return raw Response objects — use validate_success(resp, 201) /
validate_error(resp, ...) from the framework to assert.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/carpetloop"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.5) — OUTSIDE the /carpetloop prefix.
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        """POST /_clock/set_current_utc — set the server's logical clock."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # ProductCollection
    # ------------------------------------------------------------------
    def create_collection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/collections", payload, headers)

    def get_collection(self, collection_id, headers):
        return self._request(
            "GET", f"{PREFIX}/collections/{collection_id}", headers=headers
        )

    def sunset_collection(self, collection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/collections/{collection_id}/sunset", {}, headers
        )

    # ------------------------------------------------------------------
    # TileBatch
    # ------------------------------------------------------------------
    def create_batch(self, collection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/collections/{collection_id}/batches", payload, headers
        )

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"{PREFIX}/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/batches", headers=headers, params=params)

    def release_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/batches/{batch_id}/release", {}, headers
        )

    # ------------------------------------------------------------------
    # FeedstockLot
    # ------------------------------------------------------------------
    def create_feedstock_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/feedstock-lots", payload, headers)

    def get_feedstock_lot(self, lot_id, headers):
        return self._request(
            "GET", f"{PREFIX}/feedstock-lots/{lot_id}", headers=headers
        )

    def list_feedstock_lots(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/feedstock-lots", headers=headers, params=params
        )

    def qc_feedstock_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/feedstock-lots/{lot_id}/qc", payload, headers
        )

    def allocate_feedstock(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/feedstock-lots/{lot_id}/allocate", payload, headers
        )

    def deallocate_feedstock(self, lot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/feedstock-lots/{lot_id}/deallocate", payload, headers
        )

    # ------------------------------------------------------------------
    # CustomerSite
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    def install_site(self, site_id, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/install", {}, headers)

    def decommission_site(self, site_id, headers):
        return self._request(
            "POST", f"{PREFIX}/sites/{site_id}/decommission", {}, headers
        )

    # ------------------------------------------------------------------
    # InstalledZone
    # ------------------------------------------------------------------
    def create_zone(self, site_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sites/{site_id}/zones", payload, headers
        )

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"{PREFIX}/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/zones", headers=headers, params=params)

    # ------------------------------------------------------------------
    # ReplacementOrder
    # ------------------------------------------------------------------
    def create_replacement_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/replacement-orders", payload, headers)

    def get_replacement_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/replacement-orders/{order_id}", headers=headers
        )

    def list_replacement_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/replacement-orders", headers=headers, params=params
        )

    def match_replacement_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/replacement-orders/{order_id}/match", {}, headers
        )

    def complete_replacement_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/replacement-orders/{order_id}/complete", {}, headers
        )

    def cancel_replacement_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/replacement-orders/{order_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # TakeBackRequest
    # ------------------------------------------------------------------
    def create_takeback_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/take-back-requests", payload, headers)

    def get_takeback_request(self, takeback_id, headers):
        return self._request(
            "GET", f"{PREFIX}/take-back-requests/{takeback_id}", headers=headers
        )

    def list_takeback_requests(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/take-back-requests", headers=headers, params=params
        )

    def schedule_takeback(self, takeback_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/take-back-requests/{takeback_id}/schedule",
            payload,
            headers,
        )

    def collect_takeback(self, takeback_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/take-back-requests/{takeback_id}/collect",
            payload,
            headers,
        )

    def cancel_takeback(self, takeback_id, headers):
        return self._request(
            "POST", f"{PREFIX}/take-back-requests/{takeback_id}/cancel", {}, headers
        )

    def sort_takeback(self, takeback_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/take-back-requests/{takeback_id}/sort", payload, headers
        )

    # ------------------------------------------------------------------
    # PCFReport
    # ------------------------------------------------------------------
    def create_pcf_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pcf-reports", payload, headers)

    def get_pcf_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pcf-reports/{report_id}", headers=headers
        )

    def list_pcf_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/pcf-reports", headers=headers, params=params
        )

    def submit_pcf_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/pcf-reports/{report_id}/submit", {}, headers
        )

    def revise_pcf_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/pcf-reports/{report_id}/revise", {}, headers
        )

    def verify_pcf_report(self, report_id, payload, headers):
        """POST .../verification — payload carries action ASSIGN|CLEAR|FAIL plus
        verifier_org (ASSIGN) or findings_count (FAIL) as applicable."""
        return self._request(
            "POST",
            f"{PREFIX}/pcf-reports/{report_id}/verification",
            payload,
            headers,
        )

    def publish_pcf_report(self, report_id, headers):
        return self._request(
            "POST", f"{PREFIX}/pcf-reports/{report_id}/publish", {}, headers
        )

    # ------------------------------------------------------------------
    # CarbonClaim
    # ------------------------------------------------------------------
    def create_carbon_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carbon-claims", payload, headers)

    def get_carbon_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/carbon-claims/{claim_id}", headers=headers
        )

    def list_carbon_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/carbon-claims", headers=headers, params=params
        )

    def submit_carbon_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/carbon-claims/{claim_id}/submit", {}, headers
        )

    def review_carbon_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/carbon-claims/{claim_id}/review", payload, headers
        )

    def publish_carbon_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/carbon-claims/{claim_id}/publish", {}, headers
        )

    # ------------------------------------------------------------------
    # OffsetRetirement (nested under CarbonClaim)
    # ------------------------------------------------------------------
    def create_offset_retirement(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/carbon-claims/{claim_id}/offsets", payload, headers
        )

    def list_offset_retirements(self, claim_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/carbon-claims/{claim_id}/offsets",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # ManufacturingTarget
    # ------------------------------------------------------------------
    def create_manufacturing_target(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/manufacturing-targets", payload, headers
        )

    def get_manufacturing_target(self, target_id, headers):
        return self._request(
            "GET", f"{PREFIX}/manufacturing-targets/{target_id}", headers=headers
        )

    def create_target_reading(self, target_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/manufacturing-targets/{target_id}/readings",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # SpecPackage
    # ------------------------------------------------------------------
    def create_spec_package(self, payload, headers):
        return self._request("POST", f"{PREFIX}/spec-packages", payload, headers)

    def get_spec_package(self, package_id, headers):
        return self._request(
            "GET", f"{PREFIX}/spec-packages/{package_id}", headers=headers
        )

    def list_spec_packages(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/spec-packages", headers=headers, params=params
        )


api_client = ApiClient()
