"""One method per endpoint of the Comprehensive Plan Update API.

Two mechanical concerns are handled here so that no test has to think about them:

1. **Instant canonicalisation.** PRD section 2.4: "All datetime values accepted in
   request bodies must be ISO 8601 UTC with three fractional digits; a malformed
   instant is rejected with ERR_INVALID_REQUEST."  Test literals are therefore
   normalised to exactly three fractional digits and a trailing `Z` on the way out,
   so `2026-08-20T20:00:00Z` and `2026-08-20T20:00:00.000Z` are the same request.

2. **Envelope discipline.** Every method returns the raw `requests.Response`.
   Unwrapping is the caller's job, via `validate_success` / `validate_error` /
   `validate_paginated` / `get_success_data`, each of which already returns the
   inner `data`. Nothing here indexes `["data"]`.
"""

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?"
    r"(?:[Zz]|\+00:?00)$"
)


def canonical_instant(value: str) -> str:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits + Z.

    Non-instant strings are returned untouched so that titles, notes, enum members
    and jurisdiction codes pass through unharmed.
    """
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    date_part, time_part, frac = match.group(1), match.group(2), match.group(3) or ""
    frac = (frac + "000")[:3]
    return f"{date_part}T{time_part}.{frac}Z"


def canonicalise(payload: Any) -> Any:
    """Recursively canonicalise every instant-looking string in a payload."""
    if isinstance(payload, dict):
        return {k: canonicalise(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [canonicalise(v) for v in payload]
    if isinstance(payload, str):
        return canonical_instant(payload)
    return payload


class PlanningApiClient(GenericApiClient):
    """Endpoint methods for the `/planning` mount plus the clock control."""

    # ------------------------------------------------------------------ plumbing
    def _send(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(
            method,
            path,
            payload=canonicalise(payload) if payload is not None else None,
            headers=headers,
            params=canonicalise(params) if params else None,
        )

    @staticmethod
    def _page(params: Optional[Dict], limit, offset) -> Optional[Dict]:
        merged: Dict[str, Any] = dict(params or {})
        if limit is not None:
            merged["limit"] = limit
        if offset is not None:
            merged["offset"] = offset
        return merged or None

    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601: str, headers=None):
        return self._send(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------ plan updates
    def create_plan_update(self, payload, headers=None):
        return self._send("POST", "/planning/plan-updates", payload, headers)

    def get_plan_update(self, plan_id, headers=None):
        return self._send("GET", f"/planning/plan-updates/{plan_id}", None, headers)

    def list_plan_updates(self, headers=None, params=None, limit=None, offset=None):
        return self._send(
            "GET",
            "/planning/plan-updates",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def submit_plan_to_state(self, plan_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/plan-updates/{plan_id}/state-submission",
            payload if payload is not None else {},
            headers,
        )

    def record_state_determination(self, plan_id, payload, headers=None):
        return self._send(
            "POST", f"/planning/plan-updates/{plan_id}/state-determination", payload, headers
        )

    def get_compliance_summary(self, plan_id, headers=None):
        return self._send(
            "GET", f"/planning/plan-updates/{plan_id}/compliance-summary", None, headers
        )

    # ------------------------------------------------------- inventory datasets
    def create_inventory_dataset(self, payload, headers=None):
        return self._send("POST", "/planning/inventory-datasets", payload, headers)

    def get_inventory_dataset(self, inventory_id, headers=None):
        return self._send(
            "GET", f"/planning/inventory-datasets/{inventory_id}", None, headers
        )

    def list_plan_inventory_datasets(
        self, plan_id, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            f"/planning/plan-updates/{plan_id}/inventory-datasets",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def certify_inventory_dataset(self, inventory_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/inventory-datasets/{inventory_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    # --------------------------------------------------------- growth scenarios
    def create_growth_scenario(self, payload, headers=None):
        return self._send("POST", "/planning/growth-scenarios", payload, headers)

    def get_growth_scenario(self, scenario_id, headers=None):
        return self._send(
            "GET", f"/planning/growth-scenarios/{scenario_id}", None, headers
        )

    def list_growth_scenarios(self, headers=None, params=None, limit=None, offset=None):
        return self._send(
            "GET",
            "/planning/growth-scenarios",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def adopt_growth_scenario(self, scenario_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/growth-scenarios/{scenario_id}/adopt",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------ housing allocations
    def create_housing_allocation(self, payload, headers=None):
        return self._send("POST", "/planning/housing-allocations", payload, headers)

    def list_plan_housing_allocations(
        self, plan_id, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            f"/planning/plan-updates/{plan_id}/housing-allocations",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    # ------------------------------------------------------------ plan elements
    def create_plan_element(self, payload, headers=None):
        return self._send("POST", "/planning/plan-elements", payload, headers)

    def get_plan_element(self, element_id, headers=None):
        return self._send("GET", f"/planning/plan-elements/{element_id}", None, headers)

    def list_plan_elements(
        self, plan_id, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            f"/planning/plan-updates/{plan_id}/plan-elements",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def patch_plan_element(self, element_id, payload, headers=None):
        return self._send(
            "PATCH", f"/planning/plan-elements/{element_id}", payload, headers
        )

    def submit_element_review(self, element_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/plan-elements/{element_id}/submit-review",
            payload if payload is not None else {},
            headers,
        )

    def record_review_decision(self, element_id, payload, headers=None):
        return self._send(
            "POST",
            f"/planning/plan-elements/{element_id}/review-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------- consistency links
    def create_consistency_link(self, payload, headers=None):
        return self._send("POST", "/planning/consistency-links", payload, headers)

    def get_consistency_link(self, link_id, headers=None):
        return self._send(
            "GET", f"/planning/consistency-links/{link_id}", None, headers
        )

    def list_consistency_links(
        self, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            "/planning/consistency-links",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def reconcile_consistency_link(self, link_id, payload, headers=None):
        return self._send(
            "POST",
            f"/planning/consistency-links/{link_id}/reconcile",
            payload,
            headers,
        )

    # -------------------------------------------------------------------- venues
    def create_venue(self, payload, headers=None):
        return self._send("POST", "/planning/venues", payload, headers)

    # ---------------------------------------------------- engagement activities
    def create_engagement_activity(self, payload, headers=None):
        return self._send("POST", "/planning/engagement-activities", payload, headers)

    def get_engagement_activity(self, activity_id, headers=None):
        return self._send(
            "GET", f"/planning/engagement-activities/{activity_id}", None, headers
        )

    def list_engagement_activities(
        self, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            "/planning/engagement-activities",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def complete_engagement_activity(self, activity_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/engagement-activities/{activity_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def cancel_engagement_activity(self, activity_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/engagement-activities/{activity_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------- participation records
    def create_participation_record(self, payload, headers=None):
        return self._send("POST", "/planning/participation-records", payload, headers)

    def list_activity_participation_records(
        self, activity_id, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            f"/planning/engagement-activities/{activity_id}/participation-records",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    # -------------------------------------------------- environmental reviews
    def create_environmental_review(self, payload, headers=None):
        return self._send("POST", "/planning/environmental-reviews", payload, headers)

    def get_environmental_review(self, review_id, headers=None):
        return self._send(
            "GET", f"/planning/environmental-reviews/{review_id}", None, headers
        )

    def list_environmental_reviews(
        self, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            "/planning/environmental-reviews",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def circulate_environmental_review(self, review_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/environmental-reviews/{review_id}/circulate",
            payload if payload is not None else {},
            headers,
        )

    def select_preferred_alternative(self, review_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/environmental-reviews/{review_id}/select-preferred-alternative",
            payload if payload is not None else {},
            headers,
        )

    def certify_environmental_review(self, review_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/environmental-reviews/{review_id}/certify",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------- plan alternatives
    def create_plan_alternative(self, payload, headers=None):
        return self._send("POST", "/planning/plan-alternatives", payload, headers)

    def list_review_alternatives(
        self, review_id, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            f"/planning/environmental-reviews/{review_id}/plan-alternatives",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    # ------------------------------------------------------------------ hearings
    def create_hearing(self, payload, headers=None):
        return self._send("POST", "/planning/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers=None):
        return self._send("GET", f"/planning/hearings/{hearing_id}", None, headers)

    def list_plan_hearings(
        self, plan_id, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            f"/planning/plan-updates/{plan_id}/hearings",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def open_hearing(self, hearing_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/hearings/{hearing_id}/open",
            payload if payload is not None else {},
            headers,
        )

    def record_hearing_outcome(self, hearing_id, payload, headers=None):
        return self._send(
            "POST", f"/planning/hearings/{hearing_id}/outcome", payload, headers
        )

    # ---------------------------------------------------------------- amendments
    def create_amendment(self, payload, headers=None):
        return self._send("POST", "/planning/amendments", payload, headers)

    def get_amendment(self, amendment_id, headers=None):
        return self._send("GET", f"/planning/amendments/{amendment_id}", None, headers)

    def list_amendments(self, headers=None, params=None, limit=None, offset=None):
        return self._send(
            "GET",
            "/planning/amendments",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def adopt_amendment(self, amendment_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/amendments/{amendment_id}/adopt",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_amendment(self, amendment_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/amendments/{amendment_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    def rescind_amendment(self, amendment_id, payload, headers=None):
        return self._send(
            "POST", f"/planning/amendments/{amendment_id}/rescind", payload, headers
        )

    # ------------------------------------------------------ implementation actions
    def create_implementation_action(self, payload, headers=None):
        return self._send("POST", "/planning/implementation-actions", payload, headers)

    def get_implementation_action(self, action_id, headers=None):
        return self._send(
            "GET", f"/planning/implementation-actions/{action_id}", None, headers
        )

    def list_implementation_actions(
        self, headers=None, params=None, limit=None, offset=None
    ):
        return self._send(
            "GET",
            "/planning/implementation-actions",
            None,
            headers,
            params=self._page(params, limit, offset),
        )

    def record_indicator_reading(self, action_id, payload, headers=None):
        return self._send(
            "POST",
            f"/planning/implementation-actions/{action_id}/record-reading",
            payload,
            headers,
        )

    def complete_implementation_action(self, action_id, payload=None, headers=None):
        return self._send(
            "POST",
            f"/planning/implementation-actions/{action_id}/complete",
            payload if payload is not None else {},
            headers,
        )
