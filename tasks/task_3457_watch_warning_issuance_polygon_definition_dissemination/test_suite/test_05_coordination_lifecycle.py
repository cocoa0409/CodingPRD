"""Coordination workflow: decline-revert cycles, cascades, deadline expiry.

A cross-CWA (or HURRICANE) product cannot issue until every spawned
coordination request is ACKNOWLEDGED; declines and deadline expiries revert
the product to DRAFT and the loop reopens (PRD §3.5).
"""

from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    Bundle,
    create_forecaster,
    create_neighbor_agreement,
    create_office,
    create_watch_draft,
    create_zone,
    get_coordination_request,
    get_product,
    list_coordination_requests,
    make_forecaster_headers,
    respond_to_request,
    set_clock,
    setup_coordinated_offices,
    setup_pending_coordination_watch,
    submit_coordination,
    validate_error,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _three_office_hurricane_watch(api) -> Bundle:
    """Offices A, B, C with HURRICANE agreements AB (15 min) and AC (20 min);
    one zone in A; a HURRICANE watch over it. The hazard unions every agreement
    partner of the issuing office into the required set (PRD §3.5)."""
    office_a = create_office(api)
    office_b = create_office(api)
    office_c = create_office(api)
    create_neighbor_agreement(
        api, office_a["id"], office_b["id"], ["HURRICANE"], coordination_timeout_minutes=15
    )
    create_neighbor_agreement(
        api, office_a["id"], office_c["id"], ["HURRICANE"], coordination_timeout_minutes=20
    )
    zone_a = create_zone(api, office_a["id"], coastal=True)
    fc_a = create_forecaster(api, office_a["id"])
    fc_b = create_forecaster(api, office_b["id"])
    fc_c = create_forecaster(api, office_c["id"])
    headers_a = make_forecaster_headers(fc_a["id"])
    draft = create_watch_draft(
        api,
        office_a,
        headers_a,
        [zone_a["id"]],
        hazard_type="HURRICANE",
        effective_from="2026-09-01T06:00:00Z",
        expires_at="2026-09-01T18:00:00Z",
    )
    return Bundle(
        office_a=office_a,
        office_b=office_b,
        office_c=office_c,
        zone_a=zone_a,
        headers_a=headers_a,
        headers_b=make_forecaster_headers(fc_b["id"]),
        headers_c=make_forecaster_headers(fc_c["id"]),
        draft=draft,
    )


def _requests_by_target(api, product_id, headers):
    return {
        r["to_office_id"]: r for r in list_coordination_requests(api, product_id, headers)
    }


class TestDeclineRevertResubmitCycle:
    def test_decline_reverts_product_then_resubmission_reopens_cycle(self, api):
        """PRD §3.5: "A `DECLINED` outcome stamps `responded_at`, reverts the
        linked product from `PENDING_COORDINATION` back to `DRAFT`"
        PRD §3.5: "Either way the loop is open: the product may be re-submitted
        from `DRAFT`, and because each reversion mutates the product and
        advances its `version`, a client holding a pre-reversion version is
        stopped at issuance by the staleness check of §2.6."

        Design: Difficulty/non_linear_state_machine/product_coordination_decline_revert_resubmit_cycle
        """
        env = _three_office_hurricane_watch(api)
        assert env.draft["coordination_required"] is True
        submitted = submit_coordination(api, env.draft["id"], env.headers_a)
        assert submitted["status"] == "PENDING_COORDINATION"
        assert submitted["version"] == env.draft["version"] + 1

        req_ab = _requests_by_target(api, env.draft["id"], env.headers_a)[env.office_b["id"]]
        respond_to_request(api, req_ab["id"], env.headers_b, "DECLINED")

        product = get_product(api, env.draft["id"], env.headers_a)
        assert product["status"] == "DRAFT", "the decline reverted the product"
        assert product["version"] == submitted["version"] + 1, (
            "the reversion mutated the product and advanced its version"
        )

        resubmitted = submit_coordination(api, env.draft["id"], env.headers_a)
        assert resubmitted["status"] == "PENDING_COORDINATION", (
            "the cycle DRAFT -> PENDING_COORDINATION -> DRAFT -> PENDING_COORDINATION is open"
        )
        assert resubmitted["version"] == product["version"] + 1

    def test_resubmitted_watch_issues_once_fully_acknowledged(self, api):
        """PRD §3.5: "From `PENDING_COORDINATION`, every linked coordination
        request must be `ACKNOWLEDGED`"
        PRD §3.5: "Either way the loop is open: the product may be re-submitted
        from `DRAFT`"

        Design: Difficulty/non_linear_state_machine/product_coordination_decline_revert_resubmit_cycle
        """
        env = _three_office_hurricane_watch(api)
        submit_coordination(api, env.draft["id"], env.headers_a)
        req_ab = _requests_by_target(api, env.draft["id"], env.headers_a)[env.office_b["id"]]
        respond_to_request(api, req_ab["id"], env.headers_b, "DECLINED")

        resubmitted = submit_coordination(api, env.draft["id"], env.headers_a)
        second_round = list_coordination_requests(
            api, env.draft["id"], env.headers_a, status="REQUESTED"
        )
        assert len(second_round) == 2, "resubmission spawned a fresh request per required office"
        for request in second_round:
            target_headers = (
                env.headers_b if request["to_office_id"] == env.office_b["id"] else env.headers_c
            )
            respond_to_request(api, request["id"], target_headers, "ACKNOWLEDGED")

        resp = api.issue_product(
            env.draft["id"], {"expected_product_version": resubmitted["version"]}, env.headers_a
        )
        product = validate_success(resp)
        assert product["status"] == "ISSUED"
        assert product["version"] == resubmitted["version"] + 1
        for request in list_coordination_requests(api, env.draft["id"], env.headers_a, status="ACKNOWLEDGED"):
            assert request["status"] == "ACKNOWLEDGED"


class TestDeclineCascade:
    def test_decline_responds_and_reverts_product(self, api):
        """PRD §3.5: "A `DECLINED` outcome stamps `responded_at`, reverts the
        linked product from `PENDING_COORDINATION` back to `DRAFT`"

        Design: Difficulty/transitive_cascade/decline_cascade_reverts_product_and_cancels_sibling_requests
        """
        env = _three_office_hurricane_watch(api)
        submit_coordination(api, env.draft["id"], env.headers_a)
        req_ab = _requests_by_target(api, env.draft["id"], env.headers_a)[env.office_b["id"]]
        answered = respond_to_request(api, req_ab["id"], env.headers_b, "DECLINED")
        assert answered["status"] == "DECLINED"
        assert answered["responded_at"] is not None
        product = get_product(api, env.draft["id"], env.headers_a)
        assert product["status"] == "DRAFT", "hop 2: reverted because of the decline"

    def test_decline_cancels_still_requested_sibling(self, api):
        """PRD §3.5: "and — as a consequence of that reversion, not of the
        decline itself — cancels every still-`REQUESTED` sibling request into
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/decline_cascade_reverts_product_and_cancels_sibling_requests
        """
        env = _three_office_hurricane_watch(api)
        submit_coordination(api, env.draft["id"], env.headers_a)
        requests = _requests_by_target(api, env.draft["id"], env.headers_a)
        respond_to_request(api, requests[env.office_b["id"]]["id"], env.headers_b, "DECLINED")
        sibling = get_coordination_request(
            api, requests[env.office_c["id"]]["id"], env.headers_a
        )
        assert sibling["status"] == "CANCELLED", (
            "hop 3: cancelled by the product's reversion, not by any response"
        )
        assert sibling["responded_at"] is None, "nobody ever responded to the sibling"


class TestIssueCoordinationGate:
    def test_issue_blocked_while_coordination_requested(self, api):
        """PRD §3.5: "From `PENDING_COORDINATION`, every linked coordination
        request must be `ACKNOWLEDGED`"
        PRD §2.8: "Seventh, state-machine preconditions for the invoked
        transition (`ERR_INVALID_PRODUCT_STATE`, `ERR_INVALID_COORDINATION_STATE`,
        `ERR_INVALID_EVENT_STATE`, `ERR_INVALID_EM_ACTION_STATE`,
        `ERR_INVALID_STORM_STATE`, `ERR_RECORD_NOT_SETTLABLE`,
        `ERR_COORDINATION_NOT_ACKED`)."

        Design: Difficulty/cross_entity_state_dependency/issue_blocked_until_coordination_acknowledged
        """
        bundle = setup_pending_coordination_watch(api)
        resp = api.issue_product(
            bundle.product["id"],
            {"expected_product_version": bundle.product["version"]},
            bundle.headers_a,
        )
        validate_error(resp, ApiErrorId.ERR_COORDINATION_NOT_ACKED)
        product = get_product(api, bundle.product["id"], bundle.headers_a)
        assert product["status"] == "PENDING_COORDINATION"
        assert product["version"] == bundle.product["version"], (
            "the failed attempt mutates nothing"
        )

    def test_issue_succeeds_after_acknowledgment(self, api):
        """PRD §3.5: "From `PENDING_COORDINATION`, every linked coordination
        request must be `ACKNOWLEDGED` — unless a `MeteorologistInCharge`
        issues with `coordination_override` set to true, which sweeps the
        non-terminal requests into `OVERRIDDEN`"

        Design: Difficulty/cross_entity_state_dependency/issue_blocked_until_coordination_acknowledged
        """
        bundle = setup_pending_coordination_watch(api)
        resp = api.issue_product(
            bundle.product["id"],
            {"expected_product_version": bundle.product["version"]},
            bundle.headers_a,
        )
        validate_error(resp, ApiErrorId.ERR_COORDINATION_NOT_ACKED)
        for request in bundle.requests:
            respond_to_request(api, request["id"], bundle.headers_b, "ACKNOWLEDGED")
        resp = api.issue_product(
            bundle.product["id"],
            {"expected_product_version": bundle.product["version"]},
            bundle.headers_a,
        )
        product = validate_success(resp)
        assert product["status"] == "ISSUED", (
            "the identical issue call succeeds once every request is ACKNOWLEDGED"
        )


class TestCoordinationDeadlineExpiry:
    def test_coordination_deadline_expiry_reverts_product(self, api):
        """PRD §3.5: "A successful submit spawns one coordination request per
        required office, each in `REQUESTED` status, carrying the `product_id`,
        the issuing `from_office_id`, the target `to_office_id`, and the
        product's `hazard_type` copied at submit time, with `requested_at`
        stamped from the logical clock and `deadline_at` set that many minutes
        later as the agreement's `coordination_timeout_minutes` dictates"
        PRD §2.9: "A single clock advance first expires every `ISSUED` product
        whose expiration instant has been reached, then expires every
        unanswered coordination request whose deadline has been reached"
        PRD §3.5: "if its product is still pending, no `REQUESTED` requests
        remain afterward, and the requests are not all `ACKNOWLEDGED`, the
        product likewise reverts to `DRAFT`."

        Design: Corner/state_machines/coordination_deadline_expiry_reverts_product_and_stamps_deadline
        """
        bundle = setup_coordinated_offices(api, timeout_minutes=15)
        set_clock(api, "2026-09-01T09:00:00Z")
        draft = create_watch_draft(
            api,
            bundle.office_a,
            bundle.headers_a,
            [bundle.zone_a["id"], bundle.zone_b["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T12:00:00Z",
            expires_at="2026-09-01T20:00:00Z",
        )
        submitted = submit_coordination(api, draft["id"], bundle.headers_a)
        request = list_coordination_requests(api, draft["id"], bundle.headers_a)[0]
        assert _instant(request["deadline_at"]) - _instant(request["requested_at"]) == timedelta(
            minutes=15
        )
        assert _instant(request["deadline_at"]) == _instant("2026-09-01T09:15:00Z")

        set_clock(api, "2026-09-01T09:15:00Z")
        request = get_coordination_request(api, request["id"], bundle.headers_a)
        assert request["status"] == "EXPIRED", "the deadline has been reached at 09:15"
        assert request["responded_at"] is None
        product = get_product(api, draft["id"], bundle.headers_a)
        assert product["status"] == "DRAFT", "expiry reverted the pending product"
        assert product["version"] == submitted["version"] + 1

    def test_acknowledge_twice_returns_invalid_coordination_state(self, api):
        """PRD §3.5: "Answering a request that is no longer `REQUESTED` is
        rejected with `ERR_INVALID_COORDINATION_STATE`."

        Design: Corner/state_machines/acknowledge_twice_returns_invalid_coordination_state
        """
        bundle = setup_coordinated_offices(api, timeout_minutes=15)
        set_clock(api, "2026-09-01T09:00:00Z")
        draft = create_watch_draft(
            api,
            bundle.office_a,
            bundle.headers_a,
            [bundle.zone_a["id"], bundle.zone_b["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T12:00:00Z",
            expires_at="2026-09-01T20:00:00Z",
        )
        submit_coordination(api, draft["id"], bundle.headers_a)
        request = list_coordination_requests(api, draft["id"], bundle.headers_a)[0]
        set_clock(api, "2026-09-01T09:01:00Z")
        answered = respond_to_request(api, request["id"], bundle.headers_b, "ACKNOWLEDGED")
        assert answered["status"] == "ACKNOWLEDGED"

        resp = api.respond_coordination_request(
            request["id"], {"outcome": "ACKNOWLEDGED"}, bundle.headers_b
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_COORDINATION_STATE)
        request = get_coordination_request(api, request["id"], bundle.headers_a)
        assert request["status"] == "ACKNOWLEDGED"
        assert request["responded_at"] == answered["responded_at"], (
            "the rejected second respond kept the first response's stamp"
        )
