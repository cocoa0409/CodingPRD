"""HTTP client exposing one method per endpoint of the dispensing API.

Every method takes the caller's headers explicitly, because the acting role
and the acting user id are part of nearly every rule in the contract. Success
statuses follow the contract: a creation answers 201, a read or a modification
of an existing resource answers 200, and the two carve-outs (setting the
logical clock, recording a supplier standards attestation) answer 200.

Instant-valued fields come back as ISO-8601 UTC with three fractional digits.
`canonical_instant` collapses any equivalent spelling to that form so that a
comparison never fails on fractional-second width alone.
"""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Return an instant in the contract's canonical `...THH:MM:SS.mmmZ` form.

    A value that is not an instant (a plain calendar date, None, a number) is
    returned untouched, so the helper is safe to apply to any field.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    day, clock, frac, _zone = match.groups()
    millis = (frac or "")[:3].ljust(3, "0")
    return "{}T{}.{}Z".format(day, clock, millis)


def instants_equal(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two instants ignoring how many fractional digits each carries."""
    return canonical_instant(left) == canonical_instant(right)


class DmeApiClient(GenericApiClient):
    """One method per row of the contract's endpoint table."""

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def canonical_instant(value: Optional[str]) -> Optional[str]:
        return canonical_instant(value)

    def _p(self, suffix: str) -> str:
        return "{}{}".format(API_PREFIX, suffix)

    # -- logical clock ------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # -- clinics ------------------------------------------------------------
    def create_clinic(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", self._p("/clinics"), payload, headers)

    def get_clinic(self, clinic_id: str, headers: Dict[str, str]):
        return self._request("GET", self._p("/clinics/{}".format(clinic_id)), None, headers)

    def get_dispensing_summary(self, clinic_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", self._p("/clinics/{}/dispensing-summary".format(clinic_id)), None, headers
        )

    # -- physicians ---------------------------------------------------------
    def create_physician(self, clinic_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/clinics/{}/physicians".format(clinic_id)), payload, headers
        )

    def list_physicians(
        self, clinic_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", self._p("/clinics/{}/physicians".format(clinic_id)), None, headers, params
        )

    # -- fitters ------------------------------------------------------------
    def create_fitter(self, clinic_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/clinics/{}/fitters".format(clinic_id)), payload, headers
        )

    def list_fitters(
        self, clinic_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", self._p("/clinics/{}/fitters".format(clinic_id)), None, headers, params
        )

    def get_fitter(self, fitter_id: str, headers: Dict[str, str]):
        return self._request("GET", self._p("/fitters/{}".format(fitter_id)), None, headers)

    # -- patients -----------------------------------------------------------
    def create_patient(self, clinic_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/clinics/{}/patients".format(clinic_id)), payload, headers
        )

    def list_patients(
        self, clinic_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", self._p("/clinics/{}/patients".format(clinic_id)), None, headers, params
        )

    # -- suppliers ----------------------------------------------------------
    def create_supplier(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", self._p("/suppliers"), payload, headers)

    def get_supplier(self, supplier_id: str, headers: Dict[str, str]):
        return self._request("GET", self._p("/suppliers/{}".format(supplier_id)), None, headers)

    def standards_attestation(
        self, supplier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            self._p("/suppliers/{}/standards-attestation".format(supplier_id)),
            payload,
            headers,
        )

    # -- products -----------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", self._p("/products"), payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", self._p("/products/{}".format(product_id)), None, headers)

    def list_supplier_products(
        self, supplier_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", self._p("/suppliers/{}/products".format(supplier_id)), None, headers, params
        )

    # -- par levels ---------------------------------------------------------
    def create_par_level(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", self._p("/par-levels"), payload, headers)

    def get_par_level(self, par_level_id: str, headers: Dict[str, str]):
        return self._request("GET", self._p("/par-levels/{}".format(par_level_id)), None, headers)

    def list_par_levels(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", self._p("/par-levels"), None, headers, params)

    def receive_stock(self, par_level_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/par-levels/{}/stock-receipts".format(par_level_id)), payload, headers
        )

    # -- encounters ---------------------------------------------------------
    def create_encounter(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", self._p("/encounters"), payload, headers)

    def get_encounter(self, encounter_id: str, headers: Dict[str, str]):
        return self._request("GET", self._p("/encounters/{}".format(encounter_id)), None, headers)

    def list_encounters(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", self._p("/encounters"), None, headers, params)

    def sign_medical_necessity_note(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            self._p("/encounters/{}/medical-necessity-note".format(encounter_id)),
            payload,
            headers,
        )

    def attest_ioas(self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/encounters/{}/ioas-attestation".format(encounter_id)), payload, headers
        )

    def create_reservation(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", self._p("/encounters/{}/reservations".format(encounter_id)), payload, headers
        )

    def create_custom_fab_order(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            self._p("/encounters/{}/custom-fab-orders".format(encounter_id)),
            payload,
            headers,
        )

    def create_fitting_record(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", self._p("/encounters/{}/fitting-records".format(encounter_id)), payload, headers
        )

    def dispense(self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/encounters/{}/dispense".format(encounter_id)), payload, headers
        )

    # -- fitting records ----------------------------------------------------
    def get_fitting_record(self, record_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", self._p("/fitting-records/{}".format(record_id)), None, headers
        )

    def list_fitting_records(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", self._p("/fitting-records"), None, headers, params)

    # -- coverage verifications --------------------------------------------
    def create_coverage_verification(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            self._p("/encounters/{}/coverage-verifications".format(encounter_id)),
            payload,
            headers,
        )

    def list_coverage_verifications(
        self, encounter_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            self._p("/encounters/{}/coverage-verifications".format(encounter_id)),
            None,
            headers,
            params,
        )

    # -- prior authorization -----------------------------------------------
    def create_prior_auth_request(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            self._p("/encounters/{}/prior-auth-requests".format(encounter_id)),
            payload,
            headers,
        )

    def list_prior_auth_requests(
        self, encounter_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            self._p("/encounters/{}/prior-auth-requests".format(encounter_id)),
            None,
            headers,
            params,
        )

    def decide_prior_auth(self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/prior-auth-requests/{}/decision".format(request_id)), payload, headers
        )

    def appeal_prior_auth(self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/prior-auth-requests/{}/appeal".format(request_id)), payload, headers
        )

    # -- advance beneficiary notices ---------------------------------------
    def create_abn_notice(
        self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", self._p("/encounters/{}/abn-notices".format(encounter_id)), payload, headers
        )

    def list_abn_notices(
        self, encounter_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET",
            self._p("/encounters/{}/abn-notices".format(encounter_id)),
            None,
            headers,
            params,
        )

    def sign_abn_notice(self, notice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/abn-notices/{}/signature".format(notice_id)), payload, headers
        )

    # -- custom fabrication orders -----------------------------------------
    def get_custom_fab_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", self._p("/custom-fab-orders/{}".format(order_id)), None, headers
        )

    def list_custom_fab_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", self._p("/custom-fab-orders"), None, headers, params)

    def create_fabrication_event(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            self._p("/custom-fab-orders/{}/fabrication-events".format(order_id)),
            payload,
            headers,
        )

    def fitting_check(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            self._p("/custom-fab-orders/{}/fitting-check".format(order_id)),
            payload,
            headers,
        )

    # -- returns ------------------------------------------------------------
    def create_return(self, encounter_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/encounters/{}/returns".format(encounter_id)), payload, headers
        )

    def list_returns(
        self, encounter_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", self._p("/encounters/{}/returns".format(encounter_id)), None, headers, params
        )

    def inspect_return(self, return_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/returns/{}/inspection".format(return_id)), payload, headers
        )

    def issue_refit(self, return_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", self._p("/returns/{}/refit".format(return_id)), payload, headers
        )

    # -- raw escape hatch ---------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(method, path, payload, headers, params)
