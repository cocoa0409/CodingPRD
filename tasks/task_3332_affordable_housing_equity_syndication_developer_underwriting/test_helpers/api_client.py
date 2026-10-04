"""API client: one method per endpoint in PRD §4.

Every method returns the raw ``requests.Response`` so tests can assert status
codes and error ids directly. Bodies that carry a single field or a single
action accept either the bare value or a full payload dict, so a test can be
written either way:

    api.record_milestone(project_id, "CONSTRUCTION_START", headers)
    api.record_milestone(project_id, {"milestone": "CONSTRUCTION_START"}, headers)

Setup code should prefer the payload factories in ``test_helpers.factories``.
"""

from prd_bench_local_runner.testing import GenericApiClient

__all__ = ["ApiClient", "api_client"]


class ApiClient(GenericApiClient):
    """HTTP client for the Affordable Housing Equity Syndication API."""

    # ------------------------------------------------------------------ #
    # Developers                                                          #
    # ------------------------------------------------------------------ #

    def create_developer(self, payload, headers):
        """POST /developers — onboard a sponsor (PlatformAdmin)."""
        return self._request("POST", "/developers", payload, headers)

    def get_developer(self, developer_id, headers):
        """GET /developers/{developer_id}."""
        return self._request("GET", f"/developers/{developer_id}", headers=headers)

    # ------------------------------------------------------------------ #
    # Investors                                                           #
    # ------------------------------------------------------------------ #

    def create_investor(self, payload, headers):
        """POST /investors — onboard an institutional investor (PlatformAdmin)."""
        return self._request("POST", "/investors", payload, headers)

    def get_investor(self, investor_id, headers):
        """GET /investors/{investor_id}."""
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    # ------------------------------------------------------------------ #
    # Funds                                                               #
    # ------------------------------------------------------------------ #

    def create_fund(self, payload, headers):
        """POST /funds — form a syndication fund (Underwriter, PlatformAdmin)."""
        return self._request("POST", "/funds", payload, headers)

    def get_fund(self, fund_id, headers):
        """GET /funds/{fund_id} — recomputes both valuations on read."""
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def update_fund(self, fund_id, payload, headers):
        """PUT /funds/{fund_id} — reprice a fund (Underwriter; OCC on the fund)."""
        return self._request("PUT", f"/funds/{fund_id}", payload, headers)

    def create_subscription(self, fund_id, payload, headers):
        """POST /funds/{fund_id}/subscriptions (Investor, PlatformAdmin).

        The payload must carry ``expected_fund_version``.
        """
        return self._request("POST", f"/funds/{fund_id}/subscriptions", payload, headers)

    # ------------------------------------------------------------------ #
    # Subscriptions                                                       #
    # ------------------------------------------------------------------ #

    def list_subscriptions(self, headers, params=None):
        """GET /subscriptions — filterable by fund_id, investor_id, status."""
        return self._request("GET", "/subscriptions", payload=params, headers=headers)

    def get_subscription(self, subscription_id, headers):
        """GET /subscriptions/{subscription_id}."""
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers
        )

    def create_payin(self, subscription_id, amount_cents, headers):
        """POST /subscriptions/{subscription_id}/payins (owning Investor).

        ``amount_cents`` may be an int or a full payload dict.
        """
        if isinstance(amount_cents, dict):
            payload = amount_cents
        else:
            payload = {"amount_cents": amount_cents}
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/payins", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Projects                                                            #
    # ------------------------------------------------------------------ #

    def create_project(self, payload, headers):
        """POST /projects (Underwriter)."""
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        """GET /projects — filterable by developer_id, fund_id, status.

        For an entity-backed Developer actor the listing is filtered by
        ``X-User-ID`` instead of being rejected.
        """
        return self._request("GET", "/projects", payload=params, headers=headers)

    def get_project(self, project_id, headers):
        """GET /projects/{project_id}."""
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def update_project(self, project_id, payload, headers):
        """PUT /projects/{project_id} (Underwriter; OCC on the project).

        The payload must carry ``expected_project_version``.
        """
        return self._request("PUT", f"/projects/{project_id}", payload, headers)

    def commit_project(self, project_id, headers, payload=None):
        """POST /projects/{project_id}/commit (Underwriter only)."""
        return self._request(
            "POST", f"/projects/{project_id}/commit", payload or {}, headers
        )

    def record_milestone(self, project_id, milestone, headers):
        """POST /projects/{project_id}/milestones (AssetManager, Underwriter).

        ``milestone`` may be the milestone string or a full payload dict.
        """
        if isinstance(milestone, dict):
            payload = milestone
        else:
            payload = {"milestone": milestone}
        return self._request(
            "POST", f"/projects/{project_id}/milestones", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Capital calls                                                       #
    # ------------------------------------------------------------------ #

    def list_capital_calls(self, project_id, headers, params=None):
        """GET /projects/{project_id}/capital-calls — filter by milestone, status."""
        return self._request(
            "GET",
            f"/projects/{project_id}/capital-calls",
            payload=params,
            headers=headers,
        )

    def create_capital_call(self, project_id, payload, headers):
        """POST /projects/{project_id}/capital-calls (AssetManager, Underwriter).

        The payload must carry ``expected_project_version``.
        """
        return self._request(
            "POST", f"/projects/{project_id}/capital-calls", payload, headers
        )

    def transition_capital_call(self, call_id, action, headers, funded_amount_cents=None):
        """POST /capital-calls/{call_id}/transitions.

        ``action`` is one of ISSUE, SETTLE, ADJUST, REISSUE and may also be a
        full payload dict. ``funded_amount_cents`` is only meaningful for
        SETTLE.
        """
        if isinstance(action, dict):
            payload = dict(action)
        else:
            payload = {"action": action}
            if funded_amount_cents is not None:
                payload["funded_amount_cents"] = funded_amount_cents
        return self._request(
            "POST", f"/capital-calls/{call_id}/transitions", payload, headers
        )

    def issue_capital_call(self, call_id, headers):
        """Convenience: transition with action=ISSUE (AssetManager)."""
        return self.transition_capital_call(call_id, "ISSUE", headers)

    def settle_capital_call(self, call_id, funded_amount_cents, headers):
        """Convenience: transition with action=SETTLE (Investor)."""
        return self.transition_capital_call(
            call_id, "SETTLE", headers, funded_amount_cents=funded_amount_cents
        )

    def adjust_capital_call(self, call_id, headers):
        """Convenience: transition with action=ADJUST (AssetManager)."""
        return self.transition_capital_call(call_id, "ADJUST", headers)

    def reissue_capital_call(self, call_id, headers):
        """Convenience: transition with action=REISSUE (AssetManager)."""
        return self.transition_capital_call(call_id, "REISSUE", headers)

    # ------------------------------------------------------------------ #
    # Allocations                                                         #
    # ------------------------------------------------------------------ #

    def list_allocations(self, project_id, headers, params=None):
        """GET /projects/{project_id}/allocations — filter by status."""
        return self._request(
            "GET", f"/projects/{project_id}/allocations", payload=params, headers=headers
        )

    def create_allocation(self, project_id, payload, headers):
        """POST /projects/{project_id}/allocations (Underwriter, AssetManager).

        One endpoint carries every action: CREATE, CLOSE, RESCIND,
        RECORD_DELIVERY and DISTRIBUTE. The action lives in the payload.
        """
        return self._request(
            "POST", f"/projects/{project_id}/allocations", payload, headers
        )

    def record_allocation_delivery(
        self, project_id, allocation_id, delivered_credit_dollars_cents, headers
    ):
        """Convenience: allocation action=RECORD_DELIVERY (AssetManager)."""
        return self.create_allocation(
            project_id,
            {
                "action": "RECORD_DELIVERY",
                "allocation_id": allocation_id,
                "delivered_credit_dollars_cents": delivered_credit_dollars_cents,
            },
            headers,
        )

    def close_allocation(self, project_id, allocation_id, headers):
        """Convenience: allocation action=CLOSE (AssetManager)."""
        return self.create_allocation(
            project_id, {"action": "CLOSE", "allocation_id": allocation_id}, headers
        )

    def rescind_allocation(self, project_id, allocation_id, headers):
        """Convenience: allocation action=RESCIND (AssetManager)."""
        return self.create_allocation(
            project_id, {"action": "RESCIND", "allocation_id": allocation_id}, headers
        )

    def distribute_allocation(self, project_id, allocation_id, headers):
        """Convenience: allocation action=DISTRIBUTE (AssetManager)."""
        return self.create_allocation(
            project_id, {"action": "DISTRIBUTE", "allocation_id": allocation_id}, headers
        )

    # ------------------------------------------------------------------ #
    # Guarantees                                                          #
    # ------------------------------------------------------------------ #

    def list_guarantees(self, project_id, headers, params=None):
        """GET /projects/{project_id}/guarantees — filter by type, status."""
        return self._request(
            "GET", f"/projects/{project_id}/guarantees", payload=params, headers=headers
        )

    def create_guarantee(self, project_id, payload, headers):
        """POST /projects/{project_id}/guarantees (AssetManager, Underwriter)."""
        return self._request(
            "POST", f"/projects/{project_id}/guarantees", payload, headers
        )

    def draw_guarantee(self, guarantee_id, requested_amount_cents, headers):
        """POST /guarantees/{guarantee_id}/draw (AssetManager only).

        ``requested_amount_cents`` may be an int or a full payload dict; a zero
        draw is the reinstatement path.
        """
        if isinstance(requested_amount_cents, dict):
            payload = requested_amount_cents
        else:
            payload = {"requested_amount_cents": requested_amount_cents}
        return self._request(
            "POST", f"/guarantees/{guarantee_id}/draw", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Compliance reviews                                                  #
    # ------------------------------------------------------------------ #

    def list_reviews(self, project_id, headers, params=None):
        """GET /projects/{project_id}/reviews — filter by status, period index."""
        return self._request(
            "GET", f"/projects/{project_id}/reviews", payload=params, headers=headers
        )

    def create_review(self, project_id, payload, headers):
        """POST /projects/{project_id}/reviews (AssetManager, ComplianceOfficer)."""
        return self._request(
            "POST", f"/projects/{project_id}/reviews", payload, headers
        )

    def resolve_review(
        self,
        review_id,
        headers,
        outcome=None,
        corrected_reserve_balance_cents=None,
        payload=None,
    ):
        """POST /reviews/{review_id}/resolve (AssetManager, ComplianceOfficer).

        Omitting ``outcome`` derives the classification from the risk score.
        ``outcome=NONCOMPLIANT`` and ``outcome=ESCALATED`` are
        ComplianceOfficer-only.
        """
        if payload is None:
            payload = {}
            if outcome is not None:
                payload["outcome"] = outcome
            if corrected_reserve_balance_cents is not None:
                payload["corrected_reserve_balance_cents"] = (
                    corrected_reserve_balance_cents
                )
        return self._request("POST", f"/reviews/{review_id}/resolve", payload, headers)

    # ------------------------------------------------------------------ #
    # Exit events                                                         #
    # ------------------------------------------------------------------ #

    def list_exit_events(self, project_id, headers, params=None):
        """GET /projects/{project_id}/exit-events — filter by status."""
        return self._request(
            "GET", f"/projects/{project_id}/exit-events", payload=params, headers=headers
        )

    def create_exit_event(self, project_id, payload, headers):
        """POST /projects/{project_id}/exit-events (Underwriter, AssetManager)."""
        return self._request(
            "POST", f"/projects/{project_id}/exit-events", payload, headers
        )

    def exercise_exit_event(self, exit_event_id, action, headers):
        """POST /exit-events/{exit_event_id}/exercise.

        ``action`` is one of ISSUE_NOTICE, OPEN_ROFR, EXERCISE, DECLINE, CLOSE
        and may also be a full payload dict.
        """
        if isinstance(action, dict):
            payload = action
        else:
            payload = {"action": action}
        return self._request(
            "POST", f"/exit-events/{exit_event_id}/exercise", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Logical clock                                                       #
    # ------------------------------------------------------------------ #

    def set_current_utc(self, current_utc, headers):
        """POST /_clock/set_current_utc (PlatformAdmin only).

        ``current_utc`` may be an ISO 8601 string or a full payload dict. The
        response echoes the new clock value in ``data``.
        """
        if isinstance(current_utc, dict):
            payload = current_utc
        else:
            payload = {"current_utc": current_utc}
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
