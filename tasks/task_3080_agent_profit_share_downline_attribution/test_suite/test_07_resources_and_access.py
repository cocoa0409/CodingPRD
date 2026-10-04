"""Resource surface: creation defaults, append-only ledger, sponsorship closure,
listings and pagination, envelope/not-found errors, and role-based access."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_agent_payload,
    create_center,
    create_commission_event_payload,
    enroll_agent,
    file_dispute,
    get_agent,
    get_success_data,
    open_period,
    post_commission,
    prelim_close,
    setup_center_with_mca,
    setup_dispute_fixture,
    setup_resolved_upheld_dispute,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    TEST_USERS,
    build_user_headers,
    make_agent_headers,
    make_alc_chair_headers,
    make_market_center_admin_headers,
    create_dispute_payload,
    create_ledger_entry_payload,
    create_period_payload,
    create_resolution_payload,
)

PA = TEST_USERS["platform_admin_headers"]
RD = TEST_USERS["regional_director_headers"]


class TestAgentCreationDefaults:
    def test_enrollment_defaults(self, api):
        """PRD §3.2: "A newly enrolled agent begins with membership_status
        ENROLLED_PENDING_DOCS and cap_status UNCAPPED — two independent state
        dimensions that evolve on the same row and never imply one another. The
        agent's cap year is initialized as the interval starting at join_date
        (inclusive, recorded in cap_year_start) and ending one year later
        (exclusive, recorded in cap_year_end), with accrued_company_dollar at
        0.00."

        Design: Corner/entities/agent_creation_defaults_and_initial_state
        """
        center = create_center()
        agent = validate_success(api.create_agent(
            center["id"],
            create_agent_payload(join_date="2026-09-01T00:00:00Z"),
            PA,
        ), 201)
        assert agent["membership_status"] == "ENROLLED_PENDING_DOCS"
        assert agent["cap_status"] == "UNCAPPED"
        assert agent["accrued_company_dollar"] == pytest.approx(0.00, abs=0.01)
        assert agent["cap_year_start"].startswith("2026-09-01"), (
            f"cap year anchored at join_date, got {agent['cap_year_start']}"
        )
        assert agent["cap_year_end"].startswith("2027-09-01"), (
            f"cap year ends one year later, got {agent['cap_year_end']}"
        )
        assert agent["vested"] is False
        assert agent["version"] == 1


class TestVestingScheduleCreation:
    def test_schedule_created_at_enrollment(self, api):
        """PRD §3.2: "A VestingSchedule is created one-to-one with the agent in
        status ACCRUING, its vesting_start_date equal to the agent's join_date."

        Design: Corner/entities/vesting_schedule_created_at_enrollment
        """
        center = create_center()
        agent = enroll_agent(center["id"], join_date="2026-09-01T00:00:00Z")
        schedules = get_success_data(api.get_vesting_schedule(agent["id"], PA))
        assert len(schedules) == 1, f"exactly one schedule row, got {len(schedules)}"
        vs = schedules[0]
        assert vs["status"] == "ACCRUING"
        assert vs["vesting_start_date"].startswith("2026-09-01"), (
            f"vesting_start_date equals join_date, got {vs['vesting_start_date']}"
        )
        assert vs["vested_ratio_provisional"] == pytest.approx(0.0, abs=0.0001)
        assert vs["vested_ratio_final"] == pytest.approx(0.0, abs=0.0001)


class TestLedgerAppendOnly:
    def test_entries_persist_with_amounts_and_no_version(self, api):
        """PRD §2.4: "ProfitShareLedgerEntry carries only id and created_at; it
        has neither updated_at nor version, because ledger entries are
        append-only."
        PRD §3.6: "While OPEN, the period accepts ledger entries recording the
        center's costs and corrections. Each entry carries an entry_type of
        EXPENSE or ADJUSTMENT, an amount, and an optional memo. An EXPENSE amount
        must be greater than zero (else ERR_NONPOSITIVE_AMOUNT) and debits
        profit; an ADJUSTMENT is signed and may be negative. Ledger entries are
        append-only and carry no version."

        Design: Corner/entities/ledger_entry_append_only_immutability
        """
        ctx = setup_center_with_mca()
        mca = ctx["mca"]
        period = open_period(ctx["center"]["id"], "2026-09", mca["id"])
        headers = make_market_center_admin_headers(mca["id"])
        le1 = validate_success(api.create_ledger_entry(
            period["id"],
            create_ledger_entry_payload("EXPENSE", 100.00, memo="rent"),
            headers,
        ), 201)
        le2 = validate_success(api.create_ledger_entry(
            period["id"], create_ledger_entry_payload("ADJUSTMENT", -25.00), headers), 201)
        rows = api.list_ledger_entries(period["id"], PA).json()["data"]
        assert len(rows) == 2, f"both entries persist, got {len(rows)}"
        by_id = {r["id"]: r for r in rows}
        assert by_id[le1["id"]]["entry_type"] == "EXPENSE"
        assert by_id[le1["id"]]["amount"] == pytest.approx(100.00, abs=0.01)
        assert by_id[le2["id"]]["entry_type"] == "ADJUSTMENT"
        assert by_id[le2["id"]]["amount"] == pytest.approx(-25.00, abs=0.01)
        for row in rows:
            assert "version" not in row, "ledger entries carry no version"
            assert "updated_at" not in row, "ledger entries carry no updated_at"


class TestAgentsListing:
    def _setup_three_agents(self, api):
        center = create_center()
        a1 = enroll_agent(center["id"], full_name="A One", email="a1@x.com")
        a2 = enroll_agent(center["id"], sponsor_id=a1["id"], full_name="A Two",
                          email="a2@x.com")
        a3 = enroll_agent(center["id"], sponsor_id=a1["id"], full_name="A Three",
                          email="a3@x.com", docs=False)
        return {"center": center, "a1": a1, "a2": a2, "a3": a3}

    def test_pagination_limit_offset(self, api):
        """PRD §2.3: "List endpoints accept limit and offset query parameters.
        limit defaults to 10, with a minimum of 1 and a maximum of 100. offset
        defaults to 0. Results are sorted by created_at ascending. The meta block
        of list responses carries the four pagination fields limit, offset,
        total_count, and has_more."

        Design: Corner/entities/agents_list_pagination_and_membership_filter
        """
        ctx = self._setup_three_agents(api)
        page1, meta1 = validate_paginated(api.list_agents(
            PA, params={"market_center_id": ctx["center"]["id"], "limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_agents(
            PA, params={"market_center_id": ctx["center"]["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

    def test_membership_status_filter(self, api):
        """PRD §2.3: "List endpoints accept limit and offset query parameters.
        limit defaults to 10, with a minimum of 1 and a maximum of 100. offset
        defaults to 0. Results are sorted by created_at ascending. The meta block
        of list responses carries the four pagination fields limit, offset,
        total_count, and has_more."
        PRD §3.2: "A newly enrolled agent begins with membership_status
        ENROLLED_PENDING_DOCS and cap_status UNCAPPED — two independent state
        dimensions that evolve on the same row and never imply one another."

        Design: Corner/entities/agents_list_pagination_and_membership_filter
        """
        ctx = self._setup_three_agents(api)
        rows, meta = validate_paginated(api.list_agents(
            PA, params={"market_center_id": ctx["center"]["id"],
                        "membership_status": "ACTIVE"}))
        ids = {r["id"] for r in rows}
        assert ids == {ctx["a1"]["id"], ctx["a2"]["id"]}, (
            f"the filter narrows to the two ACTIVE agents, got {ids}"
        )
        assert ctx["a3"]["id"] not in ids, "a3 is ENROLLED_PENDING_DOCS"


class TestSponsorReverseReachability:
    def test_agents_filter_by_sponsor(self, api):
        """PRD §3.3: "Anyone may inspect the graph: an agent's downline is the
        set of edges where the agent is the parent, their upline the edges where
        they are the child, and a global edge listing accepts filters on
        parent_agent_id, child_agent_id, status, and depth_level alongside the
        standard pagination parameters."

        Design: Corner/endpoints/agents_filter_by_sponsor_reverse_reachability
        """
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        s1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="S One",
                          email="s1@x.com", docs=False)
        s2 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="S Two",
                          email="s2@x.com", docs=False)
        rows, _ = validate_paginated(api.list_agents(
            PA, params={"sponsor_agent_id": mca["id"]}))
        assert {r["id"] for r in rows} == {s1["id"], s2["id"]}

    def test_downline_matches_sponsor_filter(self, api):
        """PRD §3.3: "Anyone may inspect the graph: an agent's downline is the
        set of edges where the agent is the parent, their upline the edges where
        they are the child, and a global edge listing accepts filters on
        parent_agent_id, child_agent_id, status, and depth_level alongside the
        standard pagination parameters."

        Design: Corner/endpoints/agents_filter_by_sponsor_reverse_reachability
        """
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        s1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="S One",
                          email="s1@x.com", docs=False)
        s2 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="S Two",
                          email="s2@x.com", docs=False)
        edges, _ = validate_paginated(api.list_downline(
            mca["id"], PA, params={"status": "ACTIVE"}))
        assert len(edges) == 2
        assert all(e["depth_level"] == 1 for e in edges)
        assert {e["child_agent_id"] for e in edges} == {s1["id"], s2["id"]}


class TestClosureDepthCap:
    def test_closure_caps_at_seven_levels(self, api):
        """PRD §3.3: "When an agent enrolls with a sponsor, the system walks the
        sponsor chain upward from the new sponsor — depth 1 is the direct
        sponsor, depth 2 the sponsor's sponsor, and so on — creating one edge per
        ancestor reached, stopping at depth 7 or at an ancestor whose own
        sponsor_agent_id is null. Depths beyond seven earn nothing and produce no
        edge."

        Design: Corner/calculations/downline_closure_caps_at_seven_levels
        """
        center = create_center()
        parent = enroll_agent(center["id"], full_name="A One", email="a1@x.com")
        agents = [parent]
        # Nine agents in the chain: the last enrollee's ancestors are a8..a1 at
        # depths 1..8, so the depth-7 edge names a2 and the chain root a1 falls
        # beyond the cap and earns no edge.
        for i in range(2, 10):
            child = enroll_agent(center["id"], sponsor_id=parent["id"],
                                 full_name=f"A {i}", email=f"a{i}@x.com", docs=False)
            agents.append(child)
            parent = child
        edges, _ = validate_paginated(api.list_upline(agents[-1]["id"], PA))
        active = [e for e in edges if e["status"] == "ACTIVE"]
        assert len(active) == 7, (
            f"exactly 7 ancestors within the depth cap, got {len(active)}"
        )
        assert {e["depth_level"] for e in active} == {1, 2, 3, 4, 5, 6, 7}
        deepest = next(e for e in active if e["depth_level"] == 7)
        assert deepest["parent_agent_id"] == agents[1]["id"], (
            "the depth-7 ancestor is a2 (the chain root a1 is beyond the cap)"
        )
        assert all(e["parent_agent_id"] != agents[0]["id"] for e in active), (
            "no edge references the depth-8 chain root"
        )


class TestNotFoundSweep:
    def test_get_missing_agent_returns_404(self, api):
        """PRD §2.5: "Left-to-right path validation means that on a nested path
        such as a market center's agent collection, the market center's existence
        is confirmed (else ERR_MARKET_CENTER_NOT_FOUND) before any agent id on
        the path is resolved (else ERR_AGENT_NOT_FOUND). Each resource class has
        its own not-found error identifier — ERR_MARKET_CENTER_NOT_FOUND,
        ERR_AGENT_NOT_FOUND, ERR_PERIOD_NOT_FOUND, ERR_DISPUTE_NOT_FOUND,
        ERR_DOCUMENT_NOT_FOUND, ERR_COMMISSION_EVENT_NOT_FOUND,
        ERR_TRANSFER_NOT_FOUND, ERR_RESOLUTION_NOT_FOUND, and
        ERR_DISTRIBUTION_NOT_FOUND — all carrying HTTP 404, and the same
        per-resource identifiers apply when a body field references a nonexistent
        resource."

        Design: Corner/entities/agent_get_not_found_returns_404
        """
        create_center()
        resp = api.get_agent(NON_EXISTENT_UUID, PA)
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_FOUND)

    def test_enroll_rejects_computed_field_override(self, api):
        """PRD §3.1: "Enrollment requires full_name, email (unique across the
        entire system), and join_date, and may optionally name a
        sponsor_agent_id."
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

        Design: Corner/entities/enroll_rejects_computed_field_override
        """
        center = create_center()
        payload = create_agent_payload(accrued_company_dollar=9999.00)
        resp = api.create_agent(center["id"], payload, PA)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_per_resource_not_found_ids(self, api):
        """PRD §2.5: "Left-to-right path validation means that on a nested path
        such as a market center's agent collection, the market center's existence
        is confirmed (else ERR_MARKET_CENTER_NOT_FOUND) before any agent id on
        the path is resolved (else ERR_AGENT_NOT_FOUND). Each resource class has
        its own not-found error identifier — ERR_MARKET_CENTER_NOT_FOUND,
        ERR_AGENT_NOT_FOUND, ERR_PERIOD_NOT_FOUND, ERR_DISPUTE_NOT_FOUND,
        ERR_DOCUMENT_NOT_FOUND, ERR_COMMISSION_EVENT_NOT_FOUND,
        ERR_TRANSFER_NOT_FOUND, ERR_RESOLUTION_NOT_FOUND, and
        ERR_DISTRIBUTION_NOT_FOUND — all carrying HTTP 404, and the same
        per-resource identifiers apply when a body field references a nonexistent
        resource."

        Design: Corner/errors/not_found_cascade_for_secondary_resources
        """
        create_center()
        cases = [
            (api.get_market_center(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_MARKET_CENTER_NOT_FOUND),
            (api.get_period(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_PERIOD_NOT_FOUND),
            (api.get_dispute(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_DISPUTE_NOT_FOUND),
            (api.get_commission_event(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_COMMISSION_EVENT_NOT_FOUND),
            (api.get_transfer_request(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_TRANSFER_NOT_FOUND),
            (api.get_resolution(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_RESOLUTION_NOT_FOUND),
            (api.get_distribution(NON_EXISTENT_UUID, PA), ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request carries two headers: X-User-ID identifying
        the caller and X-User-Role identifying the caller's role. A request
        missing either header, or carrying a role the system does not recognize,
        is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        create_center()
        resp = api.list_agents(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
        assert "api_request_id" in body["meta"]


class TestRbacDenialMatrix:
    def _setup(self, api):
        """Center with mca, r1, s2 (attestation names r1), alc; a POSTED event on
        mca, a FILED dispute by r1, and a PROPOSED resolution on the period."""
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        r1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="R One",
                          email="r1@x.com")
        s2 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="S Two",
                          email="s2@x.com", attested_sponsor_id=r1["id"])
        alc = enroll_agent(center["id"], full_name="ALC Chair", email="alc@x.com")
        docs = get_success_data(api.list_onboarding_documents(s2["id"], PA))
        att = next(d for d in docs if d["document_type"] == "SPONSOR_ATTESTATION")
        ev = post_commission(mca["id"], 20000.00, "2026-09-10T00:00:00Z", mca["id"],
                             external_ref="ref-1")
        dsp = file_dispute(r1["id"], s2["id"], att["id"])
        period = open_period(center["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        res = get_success_data(api.create_resolution(
            period["id"], create_resolution_payload(),
            make_market_center_admin_headers(mca["id"])))
        get_success_data(api.propose_resolution(
            res["id"], make_market_center_admin_headers(mca["id"])))
        return {"center": center, "mca": mca, "r1": r1, "s2": s2, "alc": alc,
                "att": att, "ev": ev, "dsp": dsp, "period": period, "res": res}

    def test_agent_cannot_create_center(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/rbac_denial_matrix_sample
        """
        ctx = self._setup(api)
        resp = api.create_market_center(
            {"name": "MC Bogus", "region_code": "X"},
            make_agent_headers(ctx["r1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_agent_cannot_settle_commission(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/rbac_denial_matrix_sample
        """
        ctx = self._setup(api)
        resp = api.settle_commission_event(
            ctx["ev"]["id"], make_agent_headers(ctx["mca"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        ev = get_success_data(api.get_commission_event(ctx["ev"]["id"], PA))
        assert ev["status"] == "POSTED", "the forbidden call leaves state untouched"

    def test_market_center_admin_cannot_file_dispute(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/rbac_denial_matrix_sample
        """
        ctx = self._setup(api)
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"], reason="role abuse"),
            make_market_center_admin_headers(ctx["r1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_agent_cannot_ratify_resolution(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/rbac_denial_matrix_sample
        """
        ctx = self._setup(api)
        resp = api.ratify_resolution(
            ctx["res"]["id"], make_agent_headers(ctx["alc"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        res = get_success_data(api.get_resolution(ctx["res"]["id"], PA))
        assert res["status"] == "PROPOSED"

    def test_market_center_admin_cannot_resolve_dispute(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/rbac_denial_matrix_sample
        """
        ctx = self._setup(api)
        resp = api.resolve_dispute(
            ctx["dsp"]["id"], {"outcome": "UPHELD"},
            make_market_center_admin_headers(ctx["mca"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        dsp = get_success_data(api.get_dispute(ctx["dsp"]["id"], PA))
        assert dsp["status"] == "FILED"


class TestAppealOwnership:
    def test_appeal_by_non_filer_forbidden(self, api):
        """PRD §3.4: "The appellant must be the original filer — X-User-ID
        compared to filer_agent_id, else ERR_FORBIDDEN — and appeal_count must
        still be zero, else ERR_APPEAL_EXHAUSTED (HTTP 422), since at most one
        appeal is permitted."

        Design: Corner/rbac/appeal_by_non_filer_forbidden
        """
        ctx = setup_dispute_fixture(include_r2=True)
        dsp = file_dispute(ctx["r1"]["id"], ctx["s2"]["id"], ctx["att"]["id"])
        get_success_data(api.open_dispute_review(dsp["id"], RD))
        get_success_data(api.resolve_dispute(dsp["id"], {"outcome": "UPHELD"}, RD))
        resp = api.appeal_dispute(
            dsp["id"], {"reason": "not the filer"}, make_agent_headers(ctx["r2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_dispute(dsp["id"], PA))
        assert after["status"] == "RESOLVED_UPHELD"
        assert after["appeal_count"] == 0
