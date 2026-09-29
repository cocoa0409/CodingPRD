"""
One method per endpoint of the Design System Governance API.

Every method returns the raw HTTP response so that tests can assert both the
status code and the envelope. Query parameters are only sent when a test supplies
them, so that "parameter omitted" and "parameter supplied" are distinguishable —
the API's declared defaults depend on the difference.

The module also owns instant canonicalisation. Instants are compared through
`canonical_instant` so that a response writing an instant with a different number
of fractional digits than the request is still recognised as the same instant.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH
from .types import Headers, Params, Payload

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$"
)


def canonical_instant(value: Any) -> Any:
    """
    Reduce an ISO 8601 UTC instant to a single canonical spelling.

    Instants are written with exactly three fractional digits, so a value that
    arrives with none, one or six digits is still comparable against the literal
    a test asked for. Values that are not instants are returned untouched so that
    the helper can be applied to a field that may legitimately be null.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    y, mo, d, h, mi, s, frac = match.groups()
    frac = (frac or "")[:6].ljust(6, "0")
    micro = int(frac)
    stamp = datetime(
        int(y), int(mo), int(d), int(h), int(mi), int(s), micro, tzinfo=timezone.utc
    )
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"


def instants_equal(left: Any, right: Any) -> bool:
    """True when two values denote the same instant regardless of digit width."""
    return canonical_instant(left) == canonical_instant(right)


class ApiClient(GenericApiClient):
    """Typed wrapper over the design-system endpoints."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(
        self, to_iso8601: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        """Move the server's logical clock to the supplied instant."""
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    def set_clock_raw(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        """Post an arbitrary body to the clock endpoint."""
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ─── Teams ────────────────────────────────────────

    def create_team(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/teams", payload, headers)

    def get_team(self, team_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/teams/{team_id}", None, headers)

    def get_team_dashboard(
        self, team_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        """Read the team's adoption dashboard; `view` selects the index variant."""
        return self._request(
            "GET", f"{API_PREFIX}/teams/{team_id}/dashboard", None, headers, params
        )

    def create_adoption_scan(
        self, team_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/teams/{team_id}/adoption-scans", payload, headers
        )

    def list_adoption_scans(
        self, team_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/teams/{team_id}/adoption-scans", None, headers, params
        )

    # ─── Token sets and tokens ────────────────────────

    def create_token_set(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/token-sets", payload, headers)

    def list_token_sets(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/token-sets", None, headers, params)

    def get_token_set(self, token_set_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/token-sets/{token_set_id}", None, headers
        )

    def create_token(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/tokens", payload, headers)

    def list_tokens(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/tokens", None, headers, params)

    def get_token(self, token_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/tokens/{token_id}", None, headers)

    def update_token(
        self, token_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Re-point a token to a new raw value or a new alias target."""
        return self._request("PUT", f"{API_PREFIX}/tokens/{token_id}", payload, headers)

    def get_resolved_tokens(
        self, token_set_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        """Resolve every token name in the set for a given brand and mode."""
        return self._request(
            "GET",
            f"{API_PREFIX}/token-sets/{token_set_id}/resolved-tokens",
            None,
            headers,
            params,
        )

    # ─── Components ───────────────────────────────────

    def create_component(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/components", payload, headers)

    def list_components(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/components", None, headers, params)

    def get_component(self, component_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/components/{component_id}", None, headers
        )

    def promote_maturity(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Advance the component's maturity dimension one step."""
        return self._request(
            "POST",
            f"{API_PREFIX}/components/{component_id}/promote-maturity",
            payload,
            headers,
        )

    # ─── Dependency edges ─────────────────────────────

    def create_dependency(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Declare that the path component consumes another component."""
        return self._request(
            "POST",
            f"{API_PREFIX}/components/{component_id}/dependencies",
            payload,
            headers,
        )

    def list_dependencies(
        self, component_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/components/{component_id}/dependencies",
            None,
            headers,
            params,
        )

    def update_dependency(
        self, dependency_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Re-pin an existing edge to a new provider major version."""
        return self._request(
            "PUT",
            f"{API_PREFIX}/component-dependencies/{dependency_id}",
            payload,
            headers,
        )

    # ─── Platform implementations ─────────────────────

    def create_implementation(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/components/{component_id}/platform-implementations",
            payload,
            headers,
        )

    def list_implementations(
        self, component_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/components/{component_id}/platform-implementations",
            None,
            headers,
            params,
        )

    def get_implementation(
        self, implementation_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/platform-implementations/{implementation_id}",
            None,
            headers,
        )

    def ship_implementation(
        self, implementation_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Ship or re-ship the implementation through the four declared gates."""
        return self._request(
            "POST",
            f"{API_PREFIX}/platform-implementations/{implementation_id}/ship",
            payload,
            headers,
        )

    def create_accessibility_audit(
        self, implementation_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/platform-implementations/{implementation_id}"
            f"/accessibility-audits",
            payload,
            headers,
        )

    def list_accessibility_audits(
        self, implementation_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/platform-implementations/{implementation_id}"
            f"/accessibility-audits",
            None,
            headers,
            params,
        )

    # ─── Contribution proposals ───────────────────────

    def create_proposal(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/contribution-proposals", payload, headers
        )

    def list_proposals(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/contribution-proposals", None, headers, params
        )

    def get_proposal(self, proposal_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/contribution-proposals/{proposal_id}", None, headers
        )

    def submit_proposal(
        self, proposal_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        """Submit or resubmit the proposal into design critique; takes no payload."""
        return self._request(
            "POST",
            f"{API_PREFIX}/contribution-proposals/{proposal_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def file_acceptance_evidence(
        self, proposal_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/contribution-proposals/{proposal_id}/acceptance-evidence",
            payload,
            headers,
        )

    def create_review(
        self, proposal_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """File one review verdict at the design-critique or engineering gate."""
        return self._request(
            "POST",
            f"{API_PREFIX}/contribution-proposals/{proposal_id}/reviews",
            payload,
            headers,
        )

    def list_reviews(
        self, proposal_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/contribution-proposals/{proposal_id}/reviews",
            None,
            headers,
            params,
        )

    def accept_proposal(
        self, proposal_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Accept a ready proposal into a draft release."""
        return self._request(
            "POST",
            f"{API_PREFIX}/contribution-proposals/{proposal_id}/accept",
            payload,
            headers,
        )

    # ─── Releases ─────────────────────────────────────

    def create_release(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/releases", payload, headers)

    def publish_release(
        self, release_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        """Publish the release; takes no payload."""
        return self._request(
            "POST",
            f"{API_PREFIX}/releases/{release_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    # ─── Deprecation plans ────────────────────────────

    def create_deprecation_plan(
        self, component_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/components/{component_id}/deprecation-plans",
            payload,
            headers,
        )

    def list_deprecation_plans(
        self, component_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/components/{component_id}/deprecation-plans",
            None,
            headers,
            params,
        )

    def attach_migration_guide(
        self, plan_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Attach the migration guide to a draft plan, optionally announcing it."""
        return self._request(
            "POST",
            f"{API_PREFIX}/deprecation-plans/{plan_id}/migration-guide",
            payload,
            headers,
        )

    def advance_deprecation_plan(
        self, plan_id: str, headers: Headers, payload: Optional[Payload] = None
    ) -> requests.Response:
        """Advance the plan one step toward sunset and then removal."""
        return self._request(
            "POST",
            f"{API_PREFIX}/deprecation-plans/{plan_id}/advance",
            payload if payload is not None else {},
            headers,
        )

    def rescind_deprecation_plan(
        self, plan_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Rescind an announced or sunset plan, giving back its cascade."""
        return self._request(
            "POST",
            f"{API_PREFIX}/deprecation-plans/{plan_id}/rescind",
            payload,
            headers,
        )

    # ─── Exception grants ─────────────────────────────

    def create_exception_grant(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/exception-grants", payload, headers)

    def list_exception_grants(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/exception-grants", None, headers, params
        )

    def get_exception_grant(self, grant_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/exception-grants/{grant_id}", None, headers
        )

    def decide_exception_grant(
        self, grant_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Approve or deny a requested grant."""
        return self._request(
            "POST",
            f"{API_PREFIX}/exception-grants/{grant_id}/decision",
            payload,
            headers,
        )

    def repay_exception_grant(
        self, grant_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        """Retire the debt behind an approved or expired grant."""
        return self._request(
            "POST", f"{API_PREFIX}/exception-grants/{grant_id}/repay", payload, headers
        )

    # ─── Raw escape hatch ─────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Headers] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send a request to an arbitrary path under the design-system prefix."""
        return self._request(method, f"{API_PREFIX}{path}", payload, headers, params)
