"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so a test can assert on the
status code and on the envelope, rather than on a pre-digested value.  The
``/lab`` prefix and the shape of each path live here and nowhere else.

``canonical_instant`` / ``same_instant`` exist because PRD section 2.5
promises ISO 8601 UTC timestamps with exactly three fractional digits.
Expected instants a test carries are normalised through them before
comparison so a server rendering the same instant with a different
fractional width is compared on value rather than on spelling.
"""

import os
import re

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

_INSTANT_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})$"
)


def canonical_instant(value):
    """Render an ISO 8601 UTC instant with exactly three fractional digits."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value.strip())
    if not match:
        return value
    frac = (match.group("frac") or "")[:6]
    frac = (frac + "000")[:3]
    tz = match.group("tz")
    if tz in ("Z", "z"):
        suffix = "Z"
    else:
        suffix = tz.replace(":", "")
        suffix = "{0}:{1}".format(suffix[:3], suffix[3:])
    return "{0}T{1}.{2}{3}".format(
        match.group("date"), match.group("time"), frac, suffix
    )


def same_instant(left, right):
    """True when two ISO 8601 renderings denote the same UTC instant."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    def __init__(self, base_url=None):
        if base_url is None:
            base_url = os.environ.get("API_BASE_URL") or os.environ.get(
                "_PRD_BENCH_API_URL"
            )
        super().__init__(base_url=base_url)

    # --- Logical clock (PRD section 2.4; PlatformAdmin only) ----------------

    def set_clock(self, to_iso8601, headers=None):
        return self.post(
            API_PREFIX + "/_clock/set_current_utc",
            json={"to_iso8601": to_iso8601},
            headers=headers,
        )

    # --- Accounts (PRD section 3.1) ------------------------------------------

    def create_account(self, payload, headers=None):
        return self.post(API_PREFIX + "/accounts", json=payload, headers=headers)

    def get_account(self, account_id, headers=None):
        return self.get(
            "{0}/accounts/{1}".format(API_PREFIX, account_id), headers=headers
        )

    def update_account(self, account_id, payload, headers=None):
        return self._request(
            "PATCH",
            "{0}/accounts/{1}".format(API_PREFIX, account_id),
            payload,
            headers,
        )

    def get_pull_through_projection(self, account_id, headers=None):
        return self.get(
            "{0}/accounts/{1}/pull-through-projection".format(API_PREFIX, account_id),
            headers=headers,
        )

    # --- Enterprise agreements (PRD section 3.2) ------------------------------

    def create_enterprise_agreement(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/enterprise-agreements", json=payload, headers=headers
        )

    def get_enterprise_agreement(self, agreement_id, headers=None):
        return self.get(
            "{0}/enterprise-agreements/{1}".format(API_PREFIX, agreement_id),
            headers=headers,
        )

    def list_enterprise_agreements(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/enterprise-agreements", headers=headers, params=params
        )

    def renew_enterprise_agreement(self, agreement_id, payload, headers=None):
        return self.post(
            "{0}/enterprise-agreements/{1}/renew".format(API_PREFIX, agreement_id),
            json=payload,
            headers=headers,
        )

    def terminate_enterprise_agreement(self, agreement_id, headers=None):
        return self.post(
            "{0}/enterprise-agreements/{1}/terminate".format(API_PREFIX, agreement_id),
            json={},
            headers=headers,
        )

    # --- Instruments (PRD section 3.3) -----------------------------------------

    def create_instrument(self, payload, headers=None):
        return self.post(API_PREFIX + "/instruments", json=payload, headers=headers)

    def get_instrument(self, instrument_id, headers=None):
        return self.get(
            "{0}/instruments/{1}".format(API_PREFIX, instrument_id), headers=headers
        )

    def list_instruments(self, headers=None, params=None):
        return self.get(API_PREFIX + "/instruments", headers=headers, params=params)

    def install_instrument(self, instrument_id, headers=None):
        return self.post(
            "{0}/instruments/{1}/install".format(API_PREFIX, instrument_id),
            json={},
            headers=headers,
        )

    def decommission_instrument(self, instrument_id, headers=None):
        return self.post(
            "{0}/instruments/{1}/decommission".format(API_PREFIX, instrument_id),
            json={},
            headers=headers,
        )

    # --- Service contracts (PRD section 3.4) -----------------------------------

    def create_service_contract(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/service-contracts", json=payload, headers=headers
        )

    def get_service_contract(self, contract_id, headers=None):
        return self.get(
            "{0}/service-contracts/{1}".format(API_PREFIX, contract_id),
            headers=headers,
        )

    def list_service_contracts(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/service-contracts", headers=headers, params=params
        )

    def renew_service_contract(self, contract_id, payload, headers=None):
        return self.post(
            "{0}/service-contracts/{1}/renew".format(API_PREFIX, contract_id),
            json=payload,
            headers=headers,
        )

    def cancel_service_contract(self, contract_id, headers=None):
        return self.post(
            "{0}/service-contracts/{1}/cancel".format(API_PREFIX, contract_id),
            json={},
            headers=headers,
        )

    # --- Service requests, engineers and loaners (PRD section 3.5) --------------

    def create_service_request(self, payload, headers=None):
        return self.post(
            API_PREFIX + "/service-requests", json=payload, headers=headers
        )

    def get_service_request(self, request_id, headers=None):
        return self.get(
            "{0}/service-requests/{1}".format(API_PREFIX, request_id),
            headers=headers,
        )

    def list_service_requests(self, headers=None, params=None):
        return self.get(
            API_PREFIX + "/service-requests", headers=headers, params=params
        )

    def dispatch_service_request(self, request_id, headers=None):
        return self.post(
            "{0}/service-requests/{1}/dispatch".format(API_PREFIX, request_id),
            json={},
            headers=headers,
        )

    def resolve_service_request(self, request_id, payload, headers=None):
        return self.post(
            "{0}/service-requests/{1}/resolve".format(API_PREFIX, request_id),
            json=payload,
            headers=headers,
        )

    def reserve_loaner(self, request_id, headers=None):
        return self.post(
            "{0}/service-requests/{1}/loaner".format(API_PREFIX, request_id),
            json={},
            headers=headers,
        )

    def create_engineer(self, payload, headers=None):
        return self.post(API_PREFIX + "/engineers", json=payload, headers=headers)

    def create_loaner_unit(self, payload, headers=None):
        return self.post(API_PREFIX + "/loaner-units", json=payload, headers=headers)

    def list_loaner_units(self, headers=None, params=None):
        return self.get(API_PREFIX + "/loaner-units", headers=headers, params=params)

    # --- Catalog, orders and surges (PRD sections 3.6 and 3.7) -------------------

    def create_catalog_item(self, payload, headers=None):
        return self.post(API_PREFIX + "/catalog-items", json=payload, headers=headers)

    def list_catalog_items(self, headers=None, params=None):
        return self.get(API_PREFIX + "/catalog-items", headers=headers, params=params)

    def create_order(self, payload, headers=None):
        return self.post(API_PREFIX + "/orders", json=payload, headers=headers)

    def get_order(self, order_id, headers=None):
        return self.get("{0}/orders/{1}".format(API_PREFIX, order_id), headers=headers)

    def list_orders(self, headers=None, params=None):
        return self.get(API_PREFIX + "/orders", headers=headers, params=params)

    def submit_order(self, order_id, headers=None):
        return self.post(
            "{0}/orders/{1}/submit".format(API_PREFIX, order_id),
            json={},
            headers=headers,
        )

    def ship_order(self, order_id, headers=None):
        return self.post(
            "{0}/orders/{1}/ship".format(API_PREFIX, order_id),
            json={},
            headers=headers,
        )

    def cancel_order(self, order_id, headers=None):
        return self.post(
            "{0}/orders/{1}/cancel".format(API_PREFIX, order_id),
            json={},
            headers=headers,
        )

    def create_surge_event(self, payload, headers=None):
        return self.post(API_PREFIX + "/surge-events", json=payload, headers=headers)

    def resolve_surge_event(self, surge_id, headers=None):
        return self.post(
            "{0}/surge-events/{1}/resolve".format(API_PREFIX, surge_id),
            json={},
            headers=headers,
        )


api_client = ApiClient()
