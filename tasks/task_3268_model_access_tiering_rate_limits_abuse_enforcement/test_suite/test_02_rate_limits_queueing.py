"""Usage reporting, minute-window admission, burst credits, and queueing tests."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_abuse_case_payload,
    create_and_activate_organization,
    create_claimed_case,
    create_model_version_payload,
    create_usage_record_payload,
    enqueue_request,
    fill_window_with_direct_usage,
    issue_action,
    make_organization_admin_headers,
    make_trust_analyst_headers,
    set_clock,
    setup_enterprise_org,
    setup_org_with_model,
    setup_restricted_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def _windows_by_start(api, org_id, model_version_id):
    data, _meta = validate_paginated(
        api.list_organization_rate_limit_windows(
            org_id, ADMIN, params={"model_version_id": model_version_id}
        )
    )
    return {w["window_start"]: w for w in data}


class TestEnterpriseThrottleBurstInteraction:
    def _setup_throttled_enterprise(self, api):
        set_clock()
        org, _agreement = setup_enterprise_org(
            legal_name="Throttle Interact Inc", committed_tpm=8000, dedicated_capacity_pct=50
        )
        mv = validate_success(
            api.create_model_version(create_model_version_payload(), ADMIN),
            expected_status=201,
        )
        case, case_v = create_claimed_case(org["id"], severity="MEDIUM", analyst_id="analyst-1")
        issue_action(case["id"], case_v, "THROTTLE", issuer_id="analyst-1")
        return org, mv

    def test_throttled_burst_consumption_counters(self, api):
        """PRD §3.7: "`THROTTLE` leaves the organization `ACTIVE` but reduces its effective rate limits — both the requests-per-minute and tokens-per-minute ceilings — to one quarter of their base values, floored, with a floor of at least one in each dimension, for as long as the action remains unrevoked."
        PRD §2.7: "The window tracks `requests_used` (requests admitted so far, whether directly or by queue admission), `tokens_used` (the sum of input, output, and cached tokens admitted so far), and `burst_credits_used`."

        Design: Difficulty/combinatorial_formula/rate_limit_enterprise_throttle_burst_interaction
        """
        org, mv = self._setup_throttled_enterprise(api)
        org_headers = make_organization_admin_headers(org["id"])
        # Effective rpm = floor(ceil(8000/1000) * 0.25) = 2; effective tpm = 2000.
        r1 = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=2, input_tokens=1000, output_tokens=500
            ),
            org_headers,
        )
        validate_success(r1, expected_status=201)
        r2 = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=3, input_tokens=500, output_tokens=0
            ),
            org_headers,
        )
        validate_success(r2, expected_status=201)

        windows = _windows_by_start(api, org["id"], mv["id"])
        window = windows["2026-09-01T00:00:00Z"]
        assert window["requests_used"] == 5
        assert window["burst_credits_used"] == 3, (
            f"3 requests over the throttled base cap of 2 must consume 3 burst credits, got {window['burst_credits_used']}"
        )

    def test_throttled_burst_pool_sized_from_throttled_ceiling(self, api):
        """PRD §3.7: "The throttle is applied to the base caps before burst-pool sizing, so the burst pool is likewise sized from the throttled ceilings."
        PRD §2.7: "The pool size for a window is twice the organization's effective requests-per-minute ceiling (the ceiling after any active throttle is applied — see §3.7), and it refills at each window roll."

        Design: Difficulty/combinatorial_formula/rate_limit_enterprise_throttle_burst_interaction
        """
        org, mv = self._setup_throttled_enterprise(api)
        org_headers = make_organization_admin_headers(org["id"])
        # Throttled burst pool = 2 * 2 = 4; 2 base + 4 burst = 6 request slots total.
        r1 = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=6, input_tokens=6, output_tokens=0
            ),
            org_headers,
        )
        validate_success(r1, expected_status=201)
        r2 = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=1, input_tokens=1, output_tokens=0
            ),
            org_headers,
        )
        validate_error(r2, ApiErrorId.ERR_RATE_LIMITED)


class TestZeroRequestEdge:
    def test_zero_requests_admitted_and_consumes_token_slots(self, api):
        """PRD §3.4: "carries four non-negative counters: `requests`, `input_tokens`, `output_tokens`, and `cached_tokens`"
        PRD §2.7: "The window tracks `requests_used` (requests admitted so far, whether directly or by queue admission), `tokens_used` (the sum of input, output, and cached tokens admitted so far), and `burst_credits_used`."

        Design: Difficulty/boundary_precision_check/rate_limit_zero_request_edge
        """
        set_clock()
        org, mv = setup_org_with_model(legal_name="Zero Edge Co")
        org_headers = make_organization_admin_headers(org["id"])
        resp = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=0, input_tokens=25000, output_tokens=0
            ),
            org_headers,
        )
        validate_success(resp, expected_status=201)

        windows = _windows_by_start(api, org["id"], mv["id"])
        window = windows["2026-09-01T00:00:00Z"]
        assert window["requests_used"] == 0
        assert window["tokens_used"] == 25000

    def test_exact_cap_admitted_at_boundary(self, api):
        """PRD §2.7: "the request is admitted when the window's `requests_used` plus `r` is at most the effective requests-per-minute ceiling, and the window's `tokens_used` plus `t` is at most the effective tokens-per-minute ceiling."
        PRD §2.6: "`TIER_1`: at most 50 requests per minute and at most 50,000 tokens per minute."

        Design: Difficulty/boundary_precision_check/rate_limit_zero_request_edge
        """
        set_clock()
        org, mv = setup_org_with_model(legal_name="Exact Cap Co")
        org_headers = make_organization_admin_headers(org["id"])
        fill_window_with_direct_usage(
            org["id"], mv["id"], "2026-09-01T00:00:00Z", requests=0
        )
        resp = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=50, input_tokens=25000, output_tokens=0
            ),
            org_headers,
        )
        validate_success(resp, expected_status=201)
        windows = _windows_by_start(api, org["id"], mv["id"])
        window = windows["2026-09-01T00:00:00Z"]
        assert window["requests_used"] == 50


class TestMinuteWindowHalfOpen:
    def _setup_exhausted_window(self, api):
        set_clock()
        org, mv = setup_org_with_model(legal_name="Window Edge Co")
        org_headers = make_organization_admin_headers(org["id"])
        # TIER_1: base rpm 50, burst pool 100 -> 150 request slots in the 00:00 window.
        fill_window_with_direct_usage(
            org["id"], mv["id"], "2026-09-01T00:00:00Z", requests=50
        )
        fill_window_with_direct_usage(
            org["id"], mv["id"], "2026-09-01T00:00:00Z", requests=100
        )
        return org, mv, org_headers

    def test_request_beyond_cap_and_burst_rejected(self, api):
        """PRD §2.7: "When the base test fails but the burst pool still holds sufficient credits, the overage is covered by consuming burst credits and the request is admitted; otherwise it is rejected with `ERR_RATE_LIMITED` (HTTP 429)."

        Design: Difficulty/resource_temporal_overlap/rate_limit_window_half_open_minute
        """
        org, mv, org_headers = self._setup_exhausted_window(api)
        resp = api.create_usage_record(
            create_usage_record_payload(
                org["id"], mv["id"], requests=1, input_tokens=1, output_tokens=0
            ),
            org_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_LIMITED)
        windows = _windows_by_start(api, org["id"], mv["id"])
        assert windows["2026-09-01T00:00:00Z"]["requests_used"] == 150

    def test_next_minute_opens_fresh_window(self, api):
        """PRD §2.7: "Each window is identified by its `window_start`, an ISO 8601 UTC timestamp truncated to the minute, and is half-open: it covers the interval from `window_start` inclusive to sixty seconds later exclusive."
        PRD §2.7: "A window is scoped to a single organization and a single model version — there is at most one window per (organization, model version, minute) combination."

        Design: Difficulty/resource_temporal_overlap/rate_limit_window_half_open_minute
        """
        org, mv, org_headers = self._setup_exhausted_window(api)
        resp = api.create_usage_record(
            create_usage_record_payload(
                org["id"],
                mv["id"],
                minute_window_start="2026-09-01T00:01:00Z",
                requests=1,
                input_tokens=1,
                output_tokens=0,
            ),
            org_headers,
        )
        validate_success(resp, expected_status=201)
        windows = _windows_by_start(api, org["id"], mv["id"])
        assert windows["2026-09-01T00:00:00Z"]["requests_used"] == 150
        assert windows["2026-09-01T00:01:00Z"]["requests_used"] == 1


class TestQueueInvariant:
    def _setup_queue_and_case(self, api):
        set_clock()
        org, mv = setup_org_with_model(legal_name="Queue Invariant Co")
        fill_window_with_direct_usage(
            org["id"], mv["id"], "2026-09-01T00:00:00Z", requests=40
        )
        q1 = enqueue_request(org["id"], mv["id"], requests_cost=5, tokens_cost=10)
        q2 = enqueue_request(org["id"], mv["id"], requests_cost=5, tokens_cost=10)
        case, case_v = create_claimed_case(org["id"], severity="HIGH", analyst_id="analyst-1")
        return org, mv, q1, q2, case, case_v

    def test_head_of_line_admitted_at_minute_boundary(self, api):
        """PRD §2.8: "At each minute boundary crossed by the logical clock, a new window opens and the head-of-line item — the oldest by `enqueued_at` ascending — is admitted (transitioning to `ADMITTED`) while the target window has residual request and token capacity covering its declared costs; admission adds the item's costs to the window's `requests_used` and `tokens_used`."

        Design: Difficulty/compensating_invariant/queued_request_admission_then_drop_conserves_capacity
        """
        org, mv, q1, q2, case, case_v = self._setup_queue_and_case(api)
        set_clock("2026-09-01T00:01:00Z")

        data, meta = validate_paginated(
            api.list_organization_queued_requests(org["id"], ADMIN, params={"status": "ADMITTED"})
        )
        admitted_ids = {q["id"] for q in data}
        assert q1["id"] in admitted_ids, "head-of-line item must be admitted at the boundary"

        windows = _windows_by_start(api, org["id"], mv["id"])
        assert windows["2026-09-01T00:00:00Z"]["requests_used"] == 40
        assert windows["2026-09-01T00:01:00Z"]["requests_used"] == 5

    def test_dropped_items_do_not_change_counters(self, api):
        """PRD §2.8: "And if the organization is placed under enforcement — moving to `RESTRICTED`, `SUSPENDED`, or `TERMINATED` — every `QUEUED` item it owns is dropped (transitioning to `DROPPED`) as a cascade of the enforcement action."
        PRD §2.8: "admission adds the item's costs to the window's `requests_used` and `tokens_used`"

        Design: Difficulty/compensating_invariant/queued_request_admission_then_drop_conserves_capacity
        """
        org, mv, q1, q2, case, case_v = self._setup_queue_and_case(api)
        set_clock("2026-09-01T00:01:00Z")
        issue_action(case["id"], case_v, "RESTRICT", issuer_id="analyst-1")

        data, meta = validate_paginated(
            api.list_organization_queued_requests(org["id"], ADMIN, params={"status": "DROPPED"})
        )
        dropped_ids = {q["id"] for q in data}
        assert q2["id"] in dropped_ids, "the un-admitted queued item must be dropped on RESTRICT"

        windows = _windows_by_start(api, org["id"], mv["id"])
        assert windows["2026-09-01T00:00:00Z"]["requests_used"] == 40
        assert windows["2026-09-01T00:01:00Z"]["requests_used"] == 5, (
            "dropped items must not contribute to any window counter"
        )


class TestRestrictDropsQueuedRequests:
    def _setup_queued_org(self, api):
        set_clock()
        org, mv = setup_org_with_model(legal_name="Queue Cascade Co")
        q1 = enqueue_request(org["id"], mv["id"])
        q2 = enqueue_request(org["id"], mv["id"])
        q3 = enqueue_request(org["id"], mv["id"])
        case, case_v = create_claimed_case(org["id"], severity="HIGH", analyst_id="analyst-1")
        return org, mv, [q1, q2, q3], case, case_v

    def test_restrict_cascades_all_queued_to_dropped(self, api):
        """PRD §3.7: "`RESTRICT` moves the organization `ACTIVE → RESTRICTED`, requires a case severity whose rank is at least that of `RESTRICT`, drops every `QUEUED` request the organization holds, and increments the organization's `version`."

        Design: Difficulty/transitive_cascade/restriction_cascades_through_queued_requests
        """
        org, mv, queued, case, case_v = self._setup_queued_org(api)
        issue_action(case["id"], case_v, "RESTRICT", issuer_id="analyst-1")

        data, meta = validate_paginated(
            api.list_organization_queued_requests(org["id"], ADMIN, params={"status": "DROPPED"})
        )
        assert meta["total_count"] == 3
        dropped_ids = {q["id"] for q in data}
        for q in queued:
            assert q["id"] in dropped_ids

    def test_restrict_moves_organization_to_restricted(self, api):
        """PRD §3.7: "`RESTRICT` moves the organization `ACTIVE → RESTRICTED`, requires a case severity whose rank is at least that of `RESTRICT`, drops every `QUEUED` request the organization holds, and increments the organization's `version`."

        Design: Difficulty/transitive_cascade/restriction_cascades_through_queued_requests
        """
        org, mv, queued, case, case_v = self._setup_queued_org(api)
        issue_action(case["id"], case_v, "RESTRICT", issuer_id="analyst-1")
        org_data = validate_success(api.get_organization(org["id"], ADMIN))
        assert org_data["status"] == "RESTRICTED"


class TestValidationPriority:
    def test_state_error_beats_fiscal_error_on_resettle(self, api):
        """PRD §2.10: "Requests are validated in a fixed priority order, and the first failing check determines the response. The order is: authentication (presence and well-formedness of the identity headers) first; role authorization second; path-resource existence third — validated left-to-right, so a missing organization surfaces as `ERR_NOT_FOUND` (HTTP 404) before any child under it is examined; request-body shape fourth — missing required fields, ill-typed values, or enum members outside the declared set yield `ERR_INVALID_REQUEST` (HTTP 400); state-machine admissibility of the requested transition fifth, with violations rejected as `ERR_INVALID_STATE` (HTTP 409); the stale-version check sixth; and only then the domain business rules"

        Design: Difficulty/priority_pair_validation_conflict/state_before_business_fiscal_on_payment_settle
        """
        set_clock()
        org = validate_success(
            api.create_organization({"legal_name": "Priority Pair A Co"}, ADMIN),
            expected_status=201,
        )
        resp = api.create_payment_event(
            {"organization_id": org["id"], "kind": "REFUND", "amount_cents": -5000}, ADMIN
        )
        payment = validate_success(resp, expected_status=201)
        validate_success(api.settle_payment_event(payment["id"], ADMIN))

        resp = api.settle_payment_event(payment["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_model_unavailable_beats_org_status_blocked(self, api):
        """PRD §2.10: "Requests are validated in a fixed priority order, and the first failing check determines the response."
        PRD §3.3: "Any attempt to record usage against a `SUNSET` version — or against a `DEPRECATED` version by an unpinned organization without recent usage — is rejected with `ERR_MODEL_UNAVAILABLE` (HTTP 422)."
        PRD §3.4: "a `TERMINATED` organization blocks all new usage and payments, a `SUSPENDED` organization blocks new usage, and a `RESTRICTED` organization blocks new queue admissions; violations are rejected with `ERR_ORG_STATUS_BLOCKED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_before_business_constraint_on_usage
        """
        set_clock()
        org, mv = setup_org_with_model(
            legal_name="Priority Pair B Co",
            model_slug="claude-old",
            version_tag="3-0",
        )
        validate_success(api.deprecate_model_version(mv["id"], ADMIN))
        case, case_v = create_claimed_case(org["id"], severity="HIGH", analyst_id="analyst-1")
        issue_action(case["id"], case_v, "RESTRICT", issuer_id="analyst-1")
        # Drive the clock to sunset_at = 2026-09-01 + 30 days.
        set_clock("2026-10-01T00:00:00Z")

        resp = api.create_usage_record(
            create_usage_record_payload(
                org["id"],
                mv["id"],
                minute_window_start="2026-10-01T00:00:00Z",
                requests=1,
                input_tokens=10,
                output_tokens=0,
            ),
            make_organization_admin_headers(org["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MODEL_UNAVAILABLE)

        mv_data = validate_success(api.get_model_version(mv["id"], ADMIN))
        assert mv_data["status"] == "SUNSET", (
            f"model must have auto-transitioned to SUNSET at sunset_at, got {mv_data['status']}"
        )
