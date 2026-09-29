"""One typed method per declared endpoint of the otolaryngology practice API.

Envelope convention, applied without exception across the whole suite: every
method here returns the raw HTTP response. Unwrapping to the ``data`` member is
the sole responsibility of the validators (``validate_success``,
``validate_error``, ``validate_paginated``, ``validate_unpaginated``,
``get_success_data``). No method in this module ever returns ``data`` directly,
so no call site can unwrap twice.
"""

import json
import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

# An ISO 8601 UTC instant with an optional fractional-second part.
_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def _canonicalise_instant(value: str) -> str:
    """Trim an over-precise fractional second down to milliseconds.

    PRD 2.4 fixes ``created_at`` at exactly three fractional digits. A server
    that emits microseconds is describing the same instant, so the extra digits
    are trimmed here -- in one place -- rather than being tolerated separately at
    every assertion. A value with three or fewer fractional digits, or no
    fractional part at all, is returned untouched.
    """
    match = _INSTANT_RE.match(value)
    if match is None:
        return value
    seconds, fraction, zone = match.groups()
    if fraction is None or len(fraction) <= 4:
        return value
    return "{0}{1}{2}".format(seconds, fraction[:4], zone)


def _canonicalise(node: Any) -> Any:
    """Recursively canonicalise every instant string inside a decoded body."""
    if isinstance(node, str):
        return _canonicalise_instant(node)
    if isinstance(node, list):
        return [_canonicalise(item) for item in node]
    if isinstance(node, dict):
        return {key: _canonicalise(item) for key, item in node.items()}
    return node


class ApiClient(GenericApiClient):
    """A thin, explicit wrapper: one method per endpoint, no hidden state."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        response = super()._request(
            method, path, payload=payload, headers=headers, params=params
        )
        self._normalise_body(response)
        return response

    @staticmethod
    def _normalise_body(response: requests.Response) -> None:
        """Rewrite the response body with millisecond-precision instants."""
        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            return
        try:
            decoded = response.json()
        except ValueError:
            return
        canonical = _canonicalise(decoded)
        if canonical != decoded:
            response._content = json.dumps(canonical).encode("utf-8")

    # -- the logical clock -------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload=payload, headers=headers
        )

    # -- payer policies ----------------------------------------------------
    def create_payer_policy(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/payer-policies", payload=payload, headers=headers)

    def get_payer_policy(
        self, policy_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", "/payer-policies/{0}".format(policy_id), headers=headers)

    def patch_payer_policy(
        self, policy_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH",
            "/payer-policies/{0}".format(policy_id),
            payload=payload,
            headers=headers,
        )

    # -- patients ----------------------------------------------------------
    def create_patient(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/patients", payload=payload, headers=headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/patients/{0}".format(patient_id), headers=headers)

    def list_patients(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/patients", headers=headers, params=params)

    def patch_patient(
        self, patient_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", "/patients/{0}".format(patient_id), payload=payload, headers=headers
        )

    # -- allergy test orders ------------------------------------------------
    def create_allergy_test_order(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/allergy-test-orders", payload=payload, headers=headers
        )

    def get_allergy_test_order(
        self, order_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/allergy-test-orders/{0}".format(order_id), headers=headers
        )

    def list_allergy_test_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/allergy-test-orders", headers=headers, params=params
        )

    def administer_allergy_test_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/allergy-test-orders/{0}/administer".format(order_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def convert_allergy_test_order_to_serum(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/allergy-test-orders/{0}/convert-to-serum".format(order_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def record_allergy_test_reading(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/allergy-test-orders/{0}/readings".format(order_id),
            payload=payload,
            headers=headers,
        )

    # -- reaction events ----------------------------------------------------
    def create_reaction_event(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reaction-events", payload=payload, headers=headers)

    def get_reaction_event(
        self, event_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/reaction-events/{0}".format(event_id), headers=headers
        )

    def list_reaction_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/reaction-events", headers=headers, params=params)

    # -- immunotherapy vials ------------------------------------------------
    def create_immunotherapy_vial(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/immunotherapy-vials", payload=payload, headers=headers
        )

    def get_immunotherapy_vial(
        self, vial_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/immunotherapy-vials/{0}".format(vial_id), headers=headers
        )

    def list_immunotherapy_vials(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/immunotherapy-vials", headers=headers, params=params
        )

    def verify_immunotherapy_vial_label(
        self, vial_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/immunotherapy-vials/{0}/label-verification".format(vial_id),
            payload=payload,
            headers=headers,
        )

    def discard_immunotherapy_vial(
        self, vial_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/immunotherapy-vials/{0}/discard".format(vial_id),
            payload=payload,
            headers=headers,
        )

    # -- immunotherapy doses ------------------------------------------------
    def create_immunotherapy_dose(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/immunotherapy-doses", payload=payload, headers=headers
        )

    def get_immunotherapy_dose(
        self, dose_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/immunotherapy-doses/{0}".format(dose_id), headers=headers
        )

    def list_immunotherapy_doses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/immunotherapy-doses", headers=headers, params=params
        )

    def clear_dose_observation(
        self,
        dose_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/immunotherapy-doses/{0}/clear-observation".format(dose_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def void_immunotherapy_dose(
        self, dose_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/immunotherapy-doses/{0}/void".format(dose_id),
            payload=payload,
            headers=headers,
        )

    # -- sinuplasty cases ---------------------------------------------------
    def create_sinuplasty_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/sinuplasty-cases", payload=payload, headers=headers
        )

    def get_sinuplasty_case(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/sinuplasty-cases/{0}".format(case_id), headers=headers
        )

    def list_sinuplasty_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/sinuplasty-cases", headers=headers, params=params)

    def document_sinuplasty_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/sinuplasty-cases/{0}/documentation".format(case_id),
            payload=payload,
            headers=headers,
        )

    def get_candidacy_evaluation(
        self, case_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            "/sinuplasty-cases/{0}/candidacy-evaluation".format(case_id),
            headers=headers,
        )

    def submit_authorization(
        self,
        case_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/sinuplasty-cases/{0}/authorization-submissions".format(case_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def record_payer_decision(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/sinuplasty-cases/{0}/payer-decisions".format(case_id),
            payload=payload,
            headers=headers,
        )

    # -- diagnostic studies -------------------------------------------------
    def create_diagnostic_study(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/diagnostic-studies", payload=payload, headers=headers
        )

    def get_diagnostic_study(
        self, study_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/diagnostic-studies/{0}".format(study_id), headers=headers
        )

    def list_diagnostic_studies(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/diagnostic-studies", headers=headers, params=params
        )

    def record_study_results(
        self, study_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/diagnostic-studies/{0}/results".format(study_id),
            payload=payload,
            headers=headers,
        )

    def interpret_diagnostic_study(
        self,
        study_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/diagnostic-studies/{0}/interpretation".format(study_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # -- device dispenses ---------------------------------------------------
    def create_device_dispense(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/device-dispenses", payload=payload, headers=headers
        )

    def get_device_dispense(
        self, dispense_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/device-dispenses/{0}".format(dispense_id), headers=headers
        )

    def list_device_dispenses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/device-dispenses", headers=headers, params=params)

    def adjust_device_dispense(
        self,
        dispense_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/device-dispenses/{0}/adjustments".format(dispense_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def return_device_dispense(
        self, dispense_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/device-dispenses/{0}/trial-return".format(dispense_id),
            payload=payload,
            headers=headers,
        )

    def finalize_device_dispense(
        self,
        dispense_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/device-dispenses/{0}/finalize".format(dispense_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def settle_device_refund(
        self,
        dispense_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/device-dispenses/{0}/refund-settlement".format(dispense_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # -- endoscopes ---------------------------------------------------------
    def create_endoscope(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/endoscopes", payload=payload, headers=headers)

    def get_endoscope(self, scope_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/endoscopes/{0}".format(scope_id), headers=headers)

    def list_endoscopes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/endoscopes", headers=headers, params=params)

    def start_reprocessing(
        self,
        scope_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/endoscopes/{0}/reprocessing-start".format(scope_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def complete_reprocessing(
        self, scope_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/endoscopes/{0}/reprocessing-completion".format(scope_id),
            payload=payload,
            headers=headers,
        )

    # -- supply lots --------------------------------------------------------
    def create_supply_lot(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/supply-lots", payload=payload, headers=headers)

    def get_supply_lot(self, lot_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", "/supply-lots/{0}".format(lot_id), headers=headers)

    def list_supply_lots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/supply-lots", headers=headers, params=params)

    def adjust_supply_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/supply-lots/{0}/adjustments".format(lot_id),
            payload=payload,
            headers=headers,
        )

    # -- surgery-center blocks ---------------------------------------------
    def create_surgery_center_block(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/surgery-center-blocks", payload=payload, headers=headers
        )

    def get_surgery_center_block(
        self, block_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/surgery-center-blocks/{0}".format(block_id), headers=headers
        )

    def list_surgery_center_blocks(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/surgery-center-blocks", headers=headers, params=params
        )

    def close_surgery_center_block(
        self,
        block_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/surgery-center-blocks/{0}/close".format(block_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # -- procedure bookings -------------------------------------------------
    def create_procedure_booking(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/procedure-bookings", payload=payload, headers=headers
        )

    def get_procedure_booking(
        self, booking_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", "/procedure-bookings/{0}".format(booking_id), headers=headers
        )

    def list_procedure_bookings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/procedure-bookings", headers=headers, params=params
        )

    def start_procedure_booking(
        self,
        booking_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            "/procedure-bookings/{0}/start".format(booking_id),
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def complete_procedure_booking(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/procedure-bookings/{0}/complete".format(booking_id),
            payload=payload,
            headers=headers,
        )

    def cancel_procedure_booking(
        self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            "/procedure-bookings/{0}/cancel".format(booking_id),
            payload=payload,
            headers=headers,
        )
