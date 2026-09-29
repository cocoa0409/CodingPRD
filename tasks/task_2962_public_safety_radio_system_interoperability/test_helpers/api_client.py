"""Typed HTTP client for the Public Safety Radio Interoperability API.

One method per endpoint in PRD Section 4. Every method returns the raw
``requests.Response`` so tests can assert status codes themselves.

Instant canonicalisation
------------------------
PRD 2.5 declares that timestamps are "an ISO 8601 UTC timestamp with three
fractional digits, for example `2026-08-01T00:00:00.000Z`", while PRD 2.8 says
"Datetime inputs are accepted with zero, three, or six fractional-second
digits and must end in `Z`". Tests therefore compare instants through
``canonical_instant`` / ``instants_equal`` rather than by raw string equality,
so an expectation written as ``2026-08-01T00:00:00Z`` matches a stored
``2026-08-01T00:00:00.000Z``.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import (
    PATH_AGENCIES,
    PATH_CHANGE_REQUESTS,
    PATH_CLOCK,
    PATH_INTEROP_PATCHES,
    PATH_KEYSETS,
    PATH_MIGRATION_READINESS,
    PATH_OTAR_CAMPAIGNS,
    PATH_SITE_EVENTS,
    PATH_SITES,
    PATH_TALKGROUPS,
    PATH_TALKPATH_REQUESTS,
    PATH_TEMPLATES,
    PATH_UNITS,
)

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$"
)


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    ``None`` passes through unchanged, as does any string that is not a
    recognisable UTC instant (so a malformed value still fails its assertion
    loudly rather than being silently repaired).
    """
    if value is None or not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    seconds, frac = match.group(1), match.group(2) or ""
    millis = (frac + "000")[:3]
    return f"{seconds}.{millis}Z"


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    """Compare two instants irrespective of fractional-second width."""
    return canonical_instant(actual) == canonical_instant(expected)


class ApiClient(GenericApiClient):
    """One method per PRD Section 4 endpoint."""

    # -- Logical clock -----------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_CLOCK, payload, headers)

    # -- Member agencies ---------------------------------------------------

    def create_agency(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_AGENCIES, payload, headers)

    def list_agencies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_AGENCIES, None, headers, params=params)

    def get_agency(self, agency_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_AGENCIES}/{agency_id}", None, headers)

    def update_console_config(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PATH_AGENCIES}/{agency_id}/console-config", payload, headers
        )

    def create_fee_assessment(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_AGENCIES}/{agency_id}/fee-assessments", payload, headers
        )

    def create_payment(
        self, agency_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_AGENCIES}/{agency_id}/payments", payload, headers
        )

    def get_governance_standing(self, agency_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_AGENCIES}/{agency_id}/governance-standing", None, headers
        )

    # -- Sites -------------------------------------------------------------

    def create_site(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_SITES, payload, headers)

    def list_sites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_SITES, None, headers, params=params)

    def get_site(self, site_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_SITES}/{site_id}", None, headers)

    def submit_coverage(
        self, site_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PATH_SITES}/{site_id}/coverage", payload, headers
        )

    # -- Programming templates --------------------------------------------

    def create_template(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_TEMPLATES, payload, headers)

    def create_template_revision(
        self, template_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_TEMPLATES}/{template_id}/revisions", payload, headers
        )

    def list_templates(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_TEMPLATES, None, headers, params=params)

    def get_template(self, template_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_TEMPLATES}/{template_id}", None, headers)

    def publish_template(
        self, template_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_TEMPLATES}/{template_id}/publish", payload, headers
        )

    # -- Programming change requests --------------------------------------

    def create_change_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_CHANGE_REQUESTS, payload, headers)

    def list_change_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", PATH_CHANGE_REQUESTS, None, headers, params=params)

    def get_change_request(self, change_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_CHANGE_REQUESTS}/{change_request_id}", None, headers
        )

    def submit_change_request(
        self,
        change_request_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"{PATH_CHANGE_REQUESTS}/{change_request_id}/submit", payload, headers
        )

    def review_change_request(
        self, change_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PATH_CHANGE_REQUESTS}/{change_request_id}/review-decision",
            payload,
            headers,
        )

    def deploy_change_request(
        self,
        change_request_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict] = None,
    ):
        return self._request(
            "POST", f"{PATH_CHANGE_REQUESTS}/{change_request_id}/deploy", payload, headers
        )

    # -- Subscriber units --------------------------------------------------

    def create_unit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_UNITS, payload, headers)

    def list_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_UNITS, None, headers, params=params)

    def get_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_UNITS}/{unit_id}", None, headers)

    def unit_lifecycle(
        self, unit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_UNITS}/{unit_id}/lifecycle", payload, headers
        )

    # -- Keysets -----------------------------------------------------------

    def create_keyset(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_KEYSETS, payload, headers)

    def list_keysets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_KEYSETS, None, headers, params=params)

    def get_keyset(self, keyset_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_KEYSETS}/{keyset_id}", None, headers)

    def decide_keyset(
        self, keyset_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_KEYSETS}/{keyset_id}/approval", payload, headers
        )

    def compromise_keyset(
        self, keyset_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_KEYSETS}/{keyset_id}/compromise", payload, headers
        )

    # -- OTAR campaigns ----------------------------------------------------

    def create_otar_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_OTAR_CAMPAIGNS, payload, headers)

    def list_otar_campaigns(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", PATH_OTAR_CAMPAIGNS, None, headers, params=params)

    def get_otar_campaign(self, campaign_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_OTAR_CAMPAIGNS}/{campaign_id}", None, headers
        )

    def execute_otar_campaign(
        self, campaign_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_OTAR_CAMPAIGNS}/{campaign_id}/execute", payload, headers
        )

    # -- Talkgroups --------------------------------------------------------

    def create_talkgroup(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_TALKGROUPS, payload, headers)

    def list_talkgroups(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_TALKGROUPS, None, headers, params=params)

    def get_talkgroup(self, talkgroup_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_TALKGROUPS}/{talkgroup_id}", None, headers)

    def talkgroup_status(
        self, talkgroup_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_TALKGROUPS}/{talkgroup_id}/status", payload, headers
        )

    # -- Interoperability patches -----------------------------------------

    def create_interop_patch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_INTEROP_PATCHES, payload, headers)

    def list_interop_patches(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", PATH_INTEROP_PATCHES, None, headers, params=params)

    def get_interop_patch(self, patch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_INTEROP_PATCHES}/{patch_id}", None, headers
        )

    def decide_interop_patch(
        self, patch_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_INTEROP_PATCHES}/{patch_id}/decision", payload, headers
        )

    def release_interop_patch(
        self, patch_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_INTEROP_PATCHES}/{patch_id}/release", payload, headers
        )

    # -- Site events -------------------------------------------------------

    def create_site_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_SITE_EVENTS, payload, headers)

    def list_site_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", PATH_SITE_EVENTS, None, headers, params=params)

    def get_site_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PATH_SITE_EVENTS}/{event_id}", None, headers)

    def advance_site_event(
        self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PATH_SITE_EVENTS}/{event_id}/advance", payload, headers
        )

    # -- Talkpath requests -------------------------------------------------

    def create_talkpath_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", PATH_TALKPATH_REQUESTS, payload, headers)

    def list_talkpath_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", PATH_TALKPATH_REQUESTS, None, headers, params=params
        )

    def get_talkpath_request(self, request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PATH_TALKPATH_REQUESTS}/{request_id}", None, headers
        )

    def release_talkpath_request(
        self, request_id: str, headers: Dict[str, str], payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"{PATH_TALKPATH_REQUESTS}/{request_id}/release", payload, headers
        )

    # -- Migration readiness ----------------------------------------------

    def get_migration_readiness(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", PATH_MIGRATION_READINESS, None, headers, params=params
        )
