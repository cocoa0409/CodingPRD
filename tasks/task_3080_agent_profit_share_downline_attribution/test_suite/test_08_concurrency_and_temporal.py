"""Temporal rules, optimistic concurrency, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_commission_event_payload,
    create_departure_payload,
    create_transfer_request_payload,
    enroll_agent,
    get_agent,
    setup_center_with_mca,
    setup_two_centers_with_agent,
    validate_error,
    validate_success,
)
from test_helpers import (
    TEST_USERS,
    make_agent_headers,
    make_market_center_admin_headers,
)

PA = TEST_USERS["platform_admin_headers"]


def _agent_version(agent_id):
    return get_agent(agent_id)["version"]


class TestDepartedAgentStatePrecedence:
    def _setup_departed(self, api):
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        validate_success(api.depart_agent(
            a1["id"], create_departure_payload(),
            make_market_center_admin_headers(a1["id"])), 200)
        return ctx, a1

    def test_state_error_beats_fiscal_error(self, api):
        """PRD §2.5: "When a request violates multiple rules, exactly one error
        is returned, chosen by the following global priority order. Authentication
        comes first (missing or unrecognized headers, ERR_UNAUTHENTICATED), then
        role authorization (ERR_FORBIDDEN), then path-parameter existence checks
        evaluated left-to-right along the URL hierarchy (each with its
        resource-specific not-found error), then existence of body-referenced
        identifiers, then field well-formedness (ERR_VALIDATION), then state
        eligibility for the requested transition (ERR_INVALID_STATE), then the
        business rules in their documented order: temporal windows, referential
        constraints, business constraints, fiscal positivity, segregation of
        duties, and finally the optimistic-concurrency stale-version check
        (ERR_STALE_AGENT_VERSION), which is evaluated last."
        PRD §3.2: "Only ACTIVE agents may have commissions posted against them;
        posting against an agent in any other membership state fails with
        ERR_INVALID_STATE (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_departed_agent_commission
        """
        ctx, a1 = self._setup_departed(api)
        payload = create_commission_event_payload(
            a1["id"], _agent_version(a1["id"]), gross_commission=-50.00,
            occurred_on="2026-09-11T00:00:00Z", external_ref="ref-bad")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fiscal_check_fires_alone_for_active_agent(self, api):
        """PRD §3.5: "Posting is guarded by the stale-version rule of §2.7 and by
        two business checks: gross_commission must be greater than zero (else
        ERR_NONPOSITIVE_AMOUNT, HTTP 422), and occurred_on must not precede the
        agent's current cap_year_start — backdated postings into a closed cap year
        are rejected with ERR_BACKDATED_COMMISSION (HTTP 422)."
        PRD §2.5: "When a request violates multiple rules, exactly one error is
        returned, chosen by the following global priority order. Authentication
        comes first (missing or unrecognized headers, ERR_UNAUTHENTICATED), then
        role authorization (ERR_FORBIDDEN), then path-parameter existence checks
        evaluated left-to-right along the URL hierarchy (each with its
        resource-specific not-found error), then existence of body-referenced
        identifiers, then field well-formedness (ERR_VALIDATION), then state
        eligibility for the requested transition (ERR_INVALID_STATE), then the
        business rules in their documented order: temporal windows, referential
        constraints, business constraints, fiscal positivity, segregation of
        duties, and finally the optimistic-concurrency stale-version check
        (ERR_STALE_AGENT_VERSION), which is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_departed_agent_commission
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        # Isolated fiscal failure on an ACTIVE agent: the state precondition is
        # satisfied, so the fiscal rule surfaces on its own.
        payload = create_commission_event_payload(
            a1["id"], _agent_version(a1["id"]), gross_commission=-50.00,
            occurred_on="2026-09-11T00:00:00Z", external_ref="ref-neg")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_AMOUNT)

    def test_departed_agent_blocks_next_post_immediately(self, api):
        """PRD §3.2: "Only ACTIVE agents may have commissions posted against
        them; posting against an agent in any other membership state fails with
        ERR_INVALID_STATE (HTTP 409)."
        PRD §3.10: "On departure, membership_status moves from ACTIVE to DEPARTED
        — terminal — and the vesting schedule is evaluated in two variants."

        Design: Corner/consistency_model/depart_immediately_blocks_commission_posting
        """
        ctx, a1 = self._setup_departed(api)
        agent = get_agent(a1["id"])
        assert agent["membership_status"] == "DEPARTED", (
            "the re-read confirms DEPARTED before the next write"
        )
        payload = create_commission_event_payload(
            a1["id"], agent["version"], gross_commission=1000.00,
            occurred_on="2026-09-11T00:00:00Z", external_ref="ref-x")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCommissionTemporalAndFiscal:
    def test_backdated_commission_rejected(self, api):
        """PRD §3.5: "Posting is guarded by the stale-version rule of §2.7 and by
        two business checks: gross_commission must be greater than zero (else
        ERR_NONPOSITIVE_AMOUNT, HTTP 422), and occurred_on must not precede the
        agent's current cap_year_start — backdated postings into a closed cap year
        are rejected with ERR_BACKDATED_COMMISSION (HTTP 422)."

        Design: Corner/validations/backdated_commission_before_cap_year_rejected
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        payload = create_commission_event_payload(
            a1["id"], _agent_version(a1["id"]), gross_commission=1000.00,
            occurred_on="2026-08-15T00:00:00Z", external_ref="ref-old")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_BACKDATED_COMMISSION)

    def test_zero_gross_rejected(self, api):
        """PRD §3.5: "Posting is guarded by the stale-version rule of §2.7 and by
        two business checks: gross_commission must be greater than zero (else
        ERR_NONPOSITIVE_AMOUNT, HTTP 422), and occurred_on must not precede the
        agent's current cap_year_start — backdated postings into a closed cap year
        are rejected with ERR_BACKDATED_COMMISSION (HTTP 422)."

        Design: Corner/validations/nonpositive_gross_rejected
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        payload = create_commission_event_payload(
            a1["id"], _agent_version(a1["id"]), gross_commission=0.00,
            occurred_on="2026-09-05T00:00:00Z", external_ref="ref-zero")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_AMOUNT)

    def test_void_settled_event_rejected(self, api):
        """PRD §3.5: "A MarketCenterAdmin may settle a POSTED event (moving it to
        SETTLED, which makes it eligible for the final replay) or void it (moving
        it to VOID) — both terminal."

        Design: Corner/errors/void_settled_event_returns_invalid_state
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        headers = make_market_center_admin_headers(a1["id"])
        ev = validate_success(api.create_commission_event(
            create_commission_event_payload(
                a1["id"], _agent_version(a1["id"]), gross_commission=1000.00,
                occurred_on="2026-09-05T00:00:00Z", external_ref="ref-1"),
            headers), 201)
        validate_success(api.settle_commission_event(ev["id"], headers), 200)
        resp = api.void_commission_event(ev["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        settled = validate_success(api.get_commission_event(ev["id"], PA), 200)
        assert settled["status"] == "SETTLED"
        assert settled["company_dollar"] == pytest.approx(300.00, abs=0.01)


class TestOptimisticConcurrency:
    def test_stale_version_on_commission_post(self, api):
        """PRD §2.7: "Two write operations are guarded by optimistic concurrency
        on the agent row: posting a commission event and creating a transfer
        request for an agent. Both require a non-optional request field
        expected_agent_version carrying the version the client last observed on
        that Agent. If the agent's current version differs from the supplied
        value — because any other write has advanced it since the client's last
        read — the request is rejected with ERR_STALE_AGENT_VERSION (HTTP 412),
        preventing the client from writing against state it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_commission_post
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        headers = make_market_center_admin_headers(a1["id"])
        stale = _agent_version(a1["id"])
        first = validate_success(api.create_commission_event(
            create_commission_event_payload(a1["id"], stale, gross_commission=1000.00,
                                            occurred_on="2026-09-05T00:00:00Z",
                                            external_ref="ref-1"), headers), 201)
        assert first["status"] == "POSTED"
        resp = api.create_commission_event(
            create_commission_event_payload(a1["id"], stale, gross_commission=2000.00,
                                            occurred_on="2026-09-06T00:00:00Z",
                                            external_ref="ref-2"), headers)
        validate_error(resp, ApiErrorId.ERR_STALE_AGENT_VERSION)
        agent = get_agent(a1["id"])
        assert agent["accrued_company_dollar"] == pytest.approx(300.00, abs=0.01), (
            "only the first split applied"
        )

    def test_stale_version_on_transfer_request(self, api):
        """PRD §2.7: "Two write operations are guarded by optimistic concurrency
        on the agent row: posting a commission event and creating a transfer
        request for an agent. Both require a non-optional request field
        expected_agent_version carrying the version the client last observed on
        that Agent. If the agent's current version differs from the supplied
        value — because any other write has advanced it since the client's last
        read — the request is rejected with ERR_STALE_AGENT_VERSION (HTTP 412),
        preventing the client from writing against state it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_transfer_request
        """
        ctx = setup_two_centers_with_agent()
        a1, mc2 = ctx["a1"], ctx["mc2"]
        stale = _agent_version(a1["id"])
        validate_success(api.create_commission_event(
            create_commission_event_payload(a1["id"], stale, gross_commission=1000.00,
                                            occurred_on="2026-09-05T00:00:00Z",
                                            external_ref="ref-1"),
            make_market_center_admin_headers(a1["id"])), 201)
        resp = api.create_transfer_request(
            a1["id"],
            create_transfer_request_payload(mc2["id"], stale),
            make_agent_headers(a1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_AGENT_VERSION)


class TestPeriodAndEnrollmentValidations:
    def test_ledger_entry_rejected_after_preliminary_close(self, api):
        """PRD §3.6: "While OPEN, the period accepts ledger entries recording the
        center's costs and corrections."

        Design: Corner/errors/ledger_entry_on_preliminary_closed_period_rejected
        """
        from test_helpers import (
            create_ledger_entry_payload,
            open_period,
            post_commission,
            prelim_close,
        )
        ctx = setup_center_with_mca()
        mca = ctx["mca"]
        post_commission(mca["id"], 20000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-1")
        period = open_period(ctx["center"]["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        resp = api.create_ledger_entry(
            period["id"], create_ledger_entry_payload("EXPENSE", 10.00),
            make_market_center_admin_headers(mca["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_duplicate_period_month_rejected(self, api):
        """PRD §3.6: "Each market center keeps one profit-share period per
        calendar month, identified by period_month in YYYY-MM format and unique
        per center — a duplicate is rejected with ERR_PERIOD_MONTH_CONFLICT
        (HTTP 409)."

        Design: Corner/validations/duplicate_period_month_rejected
        """
        from test_helpers import create_period_payload
        ctx = setup_center_with_mca()
        mca = ctx["mca"]
        headers = make_market_center_admin_headers(mca["id"])
        validate_success(api.create_period(
            ctx["center"]["id"], create_period_payload(period_month="2026-09"),
            headers), 201)
        resp = api.create_period(
            ctx["center"]["id"], create_period_payload(period_month="2026-09"),
            headers)
        validate_error(resp, ApiErrorId.ERR_PERIOD_MONTH_CONFLICT)

    def test_cross_center_sponsor_rejected(self, api):
        """PRD §3.3: "Two referential constraints guard enrollment, checked in
        this relative order after the temporal checks of §3.5: the sponsor must
        be an ACTIVE agent enrolled in the same market center as the enrollee
        (else ERR_SPONSOR_CROSS_CENTER, HTTP 422), and the new sponsor chain must
        neither be the enrollee themself nor loop back through the enrollee (else
        ERR_SPONSOR_CYCLE, HTTP 422)."

        Design: Corner/validations/cross_center_sponsor_rejected
        """
        from test_helpers import create_agent_payload, create_center
        mc1 = create_center(name="MC One")
        mc2 = create_center(name="MC Two")
        ext = enroll_agent(mc2["id"], full_name="Ext Agent", email="ext@x.com")
        resp = api.create_agent(
            mc1["id"],
            create_agent_payload(full_name="A One", email="a1@x.com",
                                 sponsor_agent_id=ext["id"]),
            PA,
        )
        validate_error(resp, ApiErrorId.ERR_SPONSOR_CROSS_CENTER)


class TestImmediateConsistency:
    def test_posting_response_carries_split_and_reread_matches(self, api):
        """PRD §2.4: "Several agent-facing workflows increment the acting agent's
        version as a side effect — onboarding activation, departure, commission
        posting, voiding, transfer completion, and distribution transitions that
        recompute agent totals. Clients must treat version as an opaque counter
        and rely on GET /agents/{id} to observe the current value before any
        version-guarded write."
        PRD §3.5: "compute the raw company dollar as gross commission times the
        rate, rounded; compute the remaining headroom as the cap minus the
        agent's current accrued_company_dollar (floored at zero); the event's
        company_dollar is the smaller of the raw figure and the headroom;
        agent_retained is the gross minus that company dollar, rounded to two
        decimals."

        Design: Corner/consistency_model/commission_post_immediately_visible_and_versioned
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        v0 = _agent_version(a1["id"])
        ev = validate_success(api.create_commission_event(
            create_commission_event_payload(a1["id"], v0, gross_commission=1000.00,
                                            occurred_on="2026-09-05T00:00:00Z",
                                            external_ref="ref-1"),
            make_market_center_admin_headers(a1["id"])), 201)
        assert ev["company_dollar"] == pytest.approx(300.00, abs=0.01)
        assert ev["agent_retained"] == pytest.approx(700.00, abs=0.01)
        assert ev["status"] == "POSTED"
        agent = get_agent(a1["id"])
        assert agent["accrued_company_dollar"] == pytest.approx(300.00, abs=0.01), (
            "the re-read shows the accrued split immediately"
        )
        assert agent["version"] == v0 + 1, (
            f"posting increments the version by one ({v0} -> {agent['version']})"
        )
