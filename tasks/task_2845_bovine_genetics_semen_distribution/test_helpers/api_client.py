"""HTTP client exposing one method per endpoint declared by the PRD."""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]

PREFIX = "/genetics"


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    The PRD renders every instant with three fractional digits, but test
    payloads are written in the shorter `...Z` form.  Comparisons go through
    this helper so that sub-second width never turns into a false failure.
    """
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    if not text.endswith("Z"):
        return text
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


class ApiClient(GenericApiClient):
    """One method per row of the PRD endpoint table, plus the logical clock."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ----------------------------------------------------------- facilities
    def create_facility(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/facilities", payload, headers)

    def get_facility(self, facility_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/facilities/{facility_id}", None, headers)

    def set_facility_approval_status(
        self, facility_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/facilities/{facility_id}/approval-status", payload, headers
        )

    # ------------------------------------------------- country requirements
    def create_country_requirement(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/country-requirements", payload, headers)

    def get_country_requirement(
        self, requirement_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/country-requirements/{requirement_id}", None, headers
        )

    # ---------------------------------------------------------------- sires
    def create_sire(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sires", payload, headers)

    def get_sire(self, sire_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/sires/{sire_id}", None, headers)

    def list_sires(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/sires", None, headers, params)

    def contract_sire(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sires/{sire_id}/contract", payload, headers)

    def house_sire(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sires/{sire_id}/house", payload, headers)

    def clear_sire_for_collection(
        self, sire_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/sires/{sire_id}/collection-clearance", payload, headers
        )

    def set_sire_collection_status(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/sires/{sire_id}/collection-status", payload, headers
        )

    def retire_sire(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sires/{sire_id}/retire", payload, headers)

    def amend_sire_pedigree(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sires/{sire_id}/pedigree", payload, headers)

    # --------------------------------------------------------- health tests
    def order_health_test(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/sires/{sire_id}/health-tests", payload, headers
        )

    def get_health_test(self, test_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/health-tests/{test_id}", None, headers)

    def list_health_tests(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/health-tests", None, headers, params)

    def record_health_test_result(
        self, test_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/health-tests/{test_id}/result", payload, headers
        )

    # ---------------------------------------------------- collection bookings
    def create_booking(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/collection-bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/collection-bookings/{booking_id}", None, headers
        )

    def list_bookings(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/collection-bookings", None, headers, params)

    def cancel_booking(
        self, booking_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/collection-bookings/{booking_id}/cancel", payload, headers
        )

    def complete_booking(
        self, booking_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/collection-bookings/{booking_id}/complete", payload, headers
        )

    # ----------------------------------------------------------- ejaculates
    def get_ejaculate(self, ejaculate_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ejaculates/{ejaculate_id}", None, headers)

    def list_ejaculates(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/ejaculates", None, headers, params)

    def evaluate_ejaculate_qc(
        self, ejaculate_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/ejaculates/{ejaculate_id}/qc-evaluation", payload, headers
        )

    def cut_straw_lot(
        self, ejaculate_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/ejaculates/{ejaculate_id}/straw-lots", payload, headers
        )

    # ----------------------------------------------------------- straw lots
    def get_straw_lot(self, lot_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/straw-lots/{lot_id}", None, headers)

    def list_straw_lots(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/straw-lots", None, headers, params)

    def release_straw_lot(
        self, lot_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/straw-lots/{lot_id}/release", payload, headers
        )

    def reject_straw_lot(
        self, lot_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/straw-lots/{lot_id}/reject", payload, headers
        )

    def request_consignment_transfer(
        self, lot_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/straw-lots/{lot_id}/consignment-transfers", payload, headers
        )

    # --------------------------------------------------- genomic evaluations
    def file_genomic_evaluation(
        self, sire_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/sires/{sire_id}/genomic-evaluations", payload, headers
        )

    def get_genomic_evaluation(
        self, evaluation_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/genomic-evaluations/{evaluation_id}", None, headers
        )

    def list_genomic_evaluations(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/genomic-evaluations", None, headers, params
        )

    def publish_genomic_evaluation(
        self, evaluation_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/genomic-evaluations/{evaluation_id}/publish", payload, headers
        )

    def rollback_genomic_evaluation(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/genomic-evaluations/{evaluation_id}/rollback",
            payload,
            headers,
        )

    # --------------------------------------------------- export certificates
    def create_export_certificate(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/export-certificates", payload, headers)

    def get_export_certificate(
        self, certificate_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/export-certificates/{certificate_id}", None, headers
        )

    def list_export_certificates(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/export-certificates", None, headers, params
        )

    def submit_export_certificate(
        self, certificate_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/export-certificates/{certificate_id}/submit", payload, headers
        )

    def issue_export_certificate(
        self, certificate_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/export-certificates/{certificate_id}/issue", payload, headers
        )

    def reject_export_certificate(
        self, certificate_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/export-certificates/{certificate_id}/reject", payload, headers
        )

    def revoke_export_certificate(
        self, certificate_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/export-certificates/{certificate_id}/revoke", payload, headers
        )

    # --------------------------------------------------------- distributors
    def create_distributor(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/distributors", payload, headers)

    def get_distributor(
        self, distributor_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/distributors/{distributor_id}", None, headers)

    # ---------------------------------------------------------------- tanks
    def create_tank(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{PREFIX}/tanks", payload, headers)

    def get_tank(self, tank_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/tanks/{tank_id}", None, headers)

    def list_tanks(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/tanks", None, headers, params)

    def service_tank(
        self, tank_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/tanks/{tank_id}/ln2-service", payload, headers
        )

    # ------------------------------------------------- consignment transfers
    def get_consignment_transfer(
        self, transfer_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/consignment-transfers/{transfer_id}", None, headers
        )

    def list_consignment_transfers(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/consignment-transfers", None, headers, params
        )

    def approve_consignment_transfer(
        self, transfer_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/consignment-transfers/{transfer_id}/approve", payload, headers
        )

    def reject_consignment_transfer(
        self, transfer_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/consignment-transfers/{transfer_id}/reject", payload, headers
        )

    def dispatch_consignment_transfer(
        self, transfer_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/consignment-transfers/{transfer_id}/dispatch", payload, headers
        )

    def receive_consignment_transfer(
        self, transfer_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/consignment-transfers/{transfer_id}/receive", payload, headers
        )

    def report_consignment_usage(
        self, transfer_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/consignment-transfers/{transfer_id}/report-usage",
            payload,
            headers,
        )

    def return_consignment_transfer(
        self, transfer_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/consignment-transfers/{transfer_id}/return", payload, headers
        )

    # -------------------------------------------------------- customer herds
    def create_customer_herd(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/customer-herds", payload, headers)

    def get_customer_herd(self, herd_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{PREFIX}/customer-herds/{herd_id}", None, headers)

    def list_customer_herds(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/customer-herds", None, headers, params)

    def request_mating_recommendation(
        self, herd_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/customer-herds/{herd_id}/mating-recommendations", payload, headers
        )

    # -------------------------------------------------- mating recommendations
    def get_mating_recommendation(
        self, recommendation_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/mating-recommendations/{recommendation_id}", None, headers
        )

    def list_mating_recommendations(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/mating-recommendations", None, headers, params
        )

    def decide_mating_recommendation(
        self, recommendation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/mating-recommendations/{recommendation_id}/decision",
            payload,
            headers,
        )

    # --------------------------------------------------- inventory valuation
    def get_inventory_valuation(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/inventory-valuation", None, headers, params)

    # ----------------------------------------------------------- escape hatch
    def raw(
        self,
        method: str,
        path: str,
        payload: Payload = None,
        headers: Headers = None,
        params: Params = None,
    ) -> requests.Response:
        """Escape hatch for header-omission and malformed-request cases."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
