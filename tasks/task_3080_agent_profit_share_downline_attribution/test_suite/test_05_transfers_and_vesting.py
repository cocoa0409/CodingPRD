"""Transfers and vesting: effective-date windows, center-activity gates, OCC,
downline preservation, vesting variants, and departure forfeiture."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_agent_payload,
    create_center,
    create_commission_event_payload,
    create_departure_payload,
    enroll_agent,
    get_agent,
    get_success_data,
    open_period,
    post_commission,
    prelim_close,
    request_transfer,
    setup_center_with_mca,
    setup_final_closed_single_sponsor_period,
    setup_two_centers_with_agent,
    validate_error,
    validate_success,
    find_distribution,
)
from test_helpers import (
    TEST_USERS,
    make_agent_headers,
    make_market_center_admin_headers,
    create_transfer_request_payload,
)

PA = TEST_USERS["platform_admin_headers"]


def _agent_version(agent_id):
    return get_agent(agent_id)["version"]


class TestTransferWindowConflict:
    def _setup_closed_period_and_transferer(self, api):
        mc1 = create_center(name="MC One")
        mc2 = create_center(name="MC Two")
        mca = enroll_agent(mc1["id"], full_name="MCA One", email="mca1@x.com")
        d1 = enroll_agent(mc1["id"], sponsor_id=mca["id"], full_name="D One",
                          email="d1@x.com")
        post_commission(d1["id"], 10000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-d1-1")
        period = open_period(mc1["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        return {"mc1": mc1, "mc2": mc2, "mca": mca, "d1": d1, "period": period}

    def test_effective_date_inside_closed_month_rejected(self, api):
        """PRD §3.11: "the effective_date must not fall inside any source-center
        period whose month contains it and whose status is PRELIMINARY_CLOSED,
        FINAL_CLOSE_PENDING, or FINAL_CLOSED (else ERR_TRANSFER_WINDOW_CONFLICT,
        HTTP 422)"

        Design: Difficulty/resource_temporal_overlap/transfer_effective_date_inside_closed_period_occupancy
        """
        ctx = self._setup_closed_period_and_transferer(api)
        d1 = ctx["d1"]
        resp = api.create_transfer_request(
            d1["id"],
            create_transfer_request_payload(ctx["mc2"]["id"], _agent_version(d1["id"]),
                                            effective_date="2026-09-15T00:00:00Z"),
            make_agent_headers(d1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_CONFLICT)

    def test_effective_date_in_adjacent_month_accepted(self, api):
        """PRD §3.11: "the effective_date must not fall inside any source-center
        period whose month contains it and whose status is PRELIMINARY_CLOSED,
        FINAL_CLOSE_PENDING, or FINAL_CLOSED (else ERR_TRANSFER_WINDOW_CONFLICT,
        HTTP 422)"
        PRD §3.11: "The request starts in status REQUESTED."

        Design: Difficulty/resource_temporal_overlap/transfer_effective_date_inside_closed_period_occupancy
        """
        ctx = self._setup_closed_period_and_transferer(api)
        d1 = ctx["d1"]
        tr = request_transfer(d1["id"], ctx["mc2"]["id"],
                              effective_date="2026-10-01T00:00:00Z")
        assert tr["status"] == "REQUESTED", (
            "the adjacent month has no closed period, so the request is accepted"
        )


class TestTransferCompleteGates:
    def test_complete_requires_both_centers_active(self, api):
        """PRD §3.11: "Completion, by a MarketCenterAdmin, requires both centers
        ACTIVE (else ERR_CENTER_NOT_ACTIVE) and the logical clock to have reached
        the effective_date (else ERR_TRANSFER_NOT_EFFECTIVE, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/transfer_complete_requires_both_centers_active
        """
        ctx = setup_two_centers_with_agent()
        a1, mc2 = ctx["a1"], ctx["mc2"]
        tr = request_transfer(a1["id"], mc2["id"], effective_date="2026-09-10T00:00:00Z")
        headers = make_market_center_admin_headers(a1["id"])
        validate_success(api.approve_transfer(tr["id"], headers), 200)
        validate_success(api.suspend_market_center(mc2["id"], PA), 200)
        validate_success(api.set_clock("2026-09-10T00:00:00Z", PA), 200)
        resp = api.complete_transfer(tr["id"], headers)
        validate_error(resp, ApiErrorId.ERR_CENTER_NOT_ACTIVE)

    def test_complete_succeeds_after_reactivation(self, api):
        """PRD §3.11: "Completion, by a MarketCenterAdmin, requires both centers
        ACTIVE (else ERR_CENTER_NOT_ACTIVE) and the logical clock to have reached
        the effective_date (else ERR_TRANSFER_NOT_EFFECTIVE, HTTP 422)."
        PRD §3.11: "Completion rewrites the agent's market_center_id to the
        destination while leaving membership_status untouched"

        Design: Difficulty/cross_entity_state_dependency/transfer_complete_requires_both_centers_active
        """
        ctx = setup_two_centers_with_agent()
        a1, mc2 = ctx["a1"], ctx["mc2"]
        tr = request_transfer(a1["id"], mc2["id"], effective_date="2026-09-10T00:00:00Z")
        headers = make_market_center_admin_headers(a1["id"])
        validate_success(api.approve_transfer(tr["id"], headers), 200)
        validate_success(api.suspend_market_center(mc2["id"], PA), 200)
        validate_success(api.set_clock("2026-09-10T00:00:00Z", PA), 200)
        validate_error(api.complete_transfer(tr["id"], headers),
                       ApiErrorId.ERR_CENTER_NOT_ACTIVE)
        validate_success(api.reactivate_market_center(mc2["id"], PA), 200)
        completed = validate_success(api.complete_transfer(tr["id"], headers), 200)
        assert completed["status"] == "COMPLETED"
        agent = get_agent(a1["id"])
        assert agent["market_center_id"] == mc2["id"], (
            f"the transfer re-homes the agent, got {agent['market_center_id']}"
        )


class TestTransferValidations:
    def test_transfer_to_same_center_rejected(self, api):
        """PRD §3.11: "the destination must differ from the current center (else
        ERR_TRANSFER_SELF_CENTER, HTTP 422) and must exist and be ACTIVE (a
        suspended destination yields ERR_CENTER_NOT_ACTIVE)"

        Design: Corner/validations/transfer_to_same_center_rejected
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        resp = api.create_transfer_request(
            a1["id"],
            create_transfer_request_payload(ctx["center"]["id"], _agent_version(a1["id"])),
            make_agent_headers(a1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_SELF_CENTER)

    def test_second_transfer_while_in_progress_rejected(self, api):
        """PRD §3.11: "no other transfer request for the same agent may be
        REQUESTED or APPROVED (else ERR_TRANSFER_IN_PROGRESS)."

        Design: Corner/validations/second_transfer_while_in_progress_rejected
        """
        mc1 = create_center(name="MC One")
        mc2 = create_center(name="MC Two")
        mc3 = create_center(name="MC Three")
        a1 = enroll_agent(mc1["id"])
        request_transfer(a1["id"], mc2["id"])
        resp = api.create_transfer_request(
            a1["id"],
            create_transfer_request_payload(mc3["id"], _agent_version(a1["id"]),
                                            effective_date="2026-11-01T00:00:00Z"),
            make_agent_headers(a1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_IN_PROGRESS)

    def test_complete_before_effective_date_rejected(self, api):
        """PRD §3.11: "Completion, by a MarketCenterAdmin, requires both centers
        ACTIVE (else ERR_CENTER_NOT_ACTIVE) and the logical clock to have reached
        the effective_date (else ERR_TRANSFER_NOT_EFFECTIVE, HTTP 422)."

        Design: Corner/validations/transfer_complete_before_effective_date_rejected
        """
        ctx = setup_two_centers_with_agent()
        a1, mc2 = ctx["a1"], ctx["mc2"]
        tr = request_transfer(a1["id"], mc2["id"])  # effective 2026-10-01; clock at 2026-09-01
        headers = make_market_center_admin_headers(a1["id"])
        validate_success(api.approve_transfer(tr["id"], headers), 200)
        resp = api.complete_transfer(tr["id"], headers)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_EFFECTIVE)

    def test_complete_at_exact_effective_date(self, api):
        """PRD §3.11: "Completion, by a MarketCenterAdmin, requires both centers
        ACTIVE (else ERR_CENTER_NOT_ACTIVE) and the logical clock to have reached
        the effective_date (else ERR_TRANSFER_NOT_EFFECTIVE, HTTP 422)."
        PRD §3.11: "Completion rewrites the agent's market_center_id to the
        destination while leaving membership_status untouched"

        Design: Corner/validations/transfer_complete_before_effective_date_rejected
        """
        ctx = setup_two_centers_with_agent()
        a1, mc2 = ctx["a1"], ctx["mc2"]
        tr = request_transfer(a1["id"], mc2["id"])
        headers = make_market_center_admin_headers(a1["id"])
        validate_success(api.approve_transfer(tr["id"], headers), 200)
        validate_success(api.set_clock("2026-10-01T00:00:00Z", PA), 200)
        completed = validate_success(api.complete_transfer(tr["id"], headers), 200)
        assert completed["status"] == "COMPLETED"


class TestTransferPreservesDownlineAndCapYear:
    def _setup_transferring_agent(self, api):
        mc1 = create_center(name="MC One")
        mc2 = create_center(name="MC Two")
        mca = enroll_agent(mc1["id"], full_name="MCA One", email="mca1@x.com")
        s1 = enroll_agent(mc1["id"], sponsor_id=mca["id"], full_name="S One",
                          email="s1@x.com")
        post_commission(s1["id"], 40000.00, "2026-09-05T00:00:00Z", mca["id"],
                        external_ref="ref-s1")
        tr = request_transfer(s1["id"], mc2["id"], effective_date="2026-09-10T00:00:00Z")
        headers = make_market_center_admin_headers(mca["id"])
        validate_success(api.approve_transfer(tr["id"], headers), 200)
        validate_success(api.set_clock("2026-09-10T00:00:00Z", PA), 200)
        return {"mc1": mc1, "mc2": mc2, "mca": mca, "s1": s1, "tr": tr,
                "admin_headers": headers}

    def test_transfer_rehomes_without_resetting_cap_year(self, api):
        """PRD §3.11: "Completion rewrites the agent's market_center_id to the
        destination while leaving membership_status untouched, and — the defining
        property of the design — preserves everything else: downline_preserved is
        always true, the sponsorship closure follows the transferring agent
        verbatim with no edge rewritten, and the cap year (cap_year_start,
        cap_year_end, accrued_company_dollar, and cap_status) carries over
        unchanged with no reset."

        Design: Corner/endpoints/transfer_complete_preserves_downline_and_cap_year
        """
        ctx = self._setup_transferring_agent(api)
        completed = validate_success(api.complete_transfer(
            ctx["tr"]["id"], ctx["admin_headers"]), 200)
        assert completed["downline_preserved"] is True
        agent = get_agent(ctx["s1"]["id"])
        assert agent["market_center_id"] == ctx["mc2"]["id"]
        assert agent["membership_status"] == "ACTIVE", (
            "the transfer does not depart the agent"
        )
        assert agent["accrued_company_dollar"] == pytest.approx(12000.00, abs=0.01), (
            f"the cap accrual carries over unchanged, got {agent['accrued_company_dollar']}"
        )
        assert agent["cap_year_start"].startswith("2026-09-01"), (
            f"cap year NOT reset by transfer, got {agent['cap_year_start']}"
        )

    def test_transfer_preserves_the_sponsorship_edge(self, api):
        """PRD §3.11: "Completion rewrites the agent's market_center_id to the
        destination while leaving membership_status untouched, and — the defining
        property of the design — preserves everything else: downline_preserved is
        always true, the sponsorship closure follows the transferring agent
        verbatim with no edge rewritten, and the cap year (cap_year_start,
        cap_year_end, accrued_company_dollar, and cap_status) carries over
        unchanged with no reset."

        Design: Corner/endpoints/transfer_complete_preserves_downline_and_cap_year
        """
        ctx = self._setup_transferring_agent(api)
        validate_success(api.complete_transfer(ctx["tr"]["id"], ctx["admin_headers"]), 200)
        body = api.list_sponsorship_edges(
            PA, params={"child_agent_id": ctx["s1"]["id"], "status": "ACTIVE"}).json()
        edges = body["data"]
        assert len(edges) == 1, f"exactly one ACTIVE edge must follow the agent, got {len(edges)}"
        assert edges[0]["parent_agent_id"] == ctx["mca"]["id"]
        assert edges[0]["depth_level"] == 1


class TestVestingVariants:
    def test_vesting_variants_diverge_at_1095_day_boundary(self, api):
        """PRD §3.10: "The provisional variant counts whole calendar months
        between join_date and departure_date as service_months_provisional —
        computed from the year-month difference, reduced by one when the
        departure day-of-month precedes the join day-of-month — and
        vested_ratio_provisional is that count divided by thirty-six, capped at
        one, four decimals half-up; an agent departing the day before their
        join-day anniversary in month thirty-six scores thirty-five thirty-sixths,
        0.9722."
        PRD §3.10: "Adjudication uses the final variant only: the schedule moves
        from ACCRUING to VESTED when service_days_final reaches at least 1095 days
        — the boundary is inclusive, so exactly 1095 days vests in full — and to
        FORFEITED otherwise."

        Design: Corner/calculations/vesting_variants_diverge_at_1095_day_boundary
        """
        ctx = setup_center_with_mca(join_date="2023-09-01T00:00:00Z")
        a1 = ctx["mca"]
        validate_success(api.depart_agent(
            a1["id"], {"departure_date": "2026-08-31T00:00:00Z"},
            make_market_center_admin_headers(a1["id"])), 200)
        schedules = get_success_data(api.get_vesting_schedule(a1["id"], PA))
        assert len(schedules) == 1
        vs = schedules[0]
        assert vs["service_days_final"] == 1095, (
            f"exact-day variant counts 1095 days, got {vs['service_days_final']}"
        )
        assert vs["service_months_provisional"] == 35, (
            f"whole-month variant scores 35 months, got {vs['service_months_provisional']}"
        )
        assert vs["vested_ratio_final"] == pytest.approx(1.0, abs=0.0001), (
            f"1095 >= 1095 inclusive, got {vs['vested_ratio_final']}"
        )
        assert vs["vested_ratio_provisional"] == pytest.approx(0.9722, abs=0.0001), (
            f"35/36, got {vs['vested_ratio_provisional']}"
        )
        assert vs["status"] == "VESTED"
        assert get_agent(a1["id"])["vested"] is True


class TestDepartureForfeiture:
    def test_unvested_departure_forfeits_projection(self, api):
        """PRD §3.10: "A forfeited agent's vested becomes false, and every
        outstanding distribution of theirs in status PROJECTION or PAYABLE moves
        to FORFEITED, each transition recomputing the owning period's
        distributed_total (and, for a forfeited PAYABLE, the agent's
        pending_payable_profit_share); the agent is excluded from all future
        entitlement sets."

        Design: Corner/calculations/departure_forfeits_unvested_projection_distributions
        """
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        d1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="D One",
                          email="d1@x.com")
        post_commission(d1["id"], 5000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-d1")
        period = open_period(center["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        validate_success(api.depart_agent(
            mca["id"], {"departure_date": "2026-09-10T00:00:00Z"},
            make_market_center_admin_headers(mca["id"])), 200)
        dist = find_distribution(period["id"], mca["id"])
        assert dist["status"] == "FORFEITED", (
            f"9 service days < 1095: the PROJECTION is forfeited, got {dist['status']}"
        )

    def test_unvested_departure_recomputes_period_totals(self, api):
        """PRD §3.10: "A forfeited agent's vested becomes false, and every
        outstanding distribution of theirs in status PROJECTION or PAYABLE moves
        to FORFEITED, each transition recomputing the owning period's
        distributed_total (and, for a forfeited PAYABLE, the agent's
        pending_payable_profit_share); the agent is excluded from all future
        entitlement sets."
        PRD §3.8: "Conservation holds at all times: the sum of distribution
        amounts plus center_retained_amount equals the current pool"

        Design: Corner/calculations/departure_forfeits_unvested_projection_distributions
        """
        center = create_center()
        mca = enroll_agent(center["id"], full_name="MCA One", email="mca1@x.com")
        d1 = enroll_agent(center["id"], sponsor_id=mca["id"], full_name="D One",
                          email="d1@x.com")
        post_commission(d1["id"], 5000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-d1")
        period = open_period(center["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        validate_success(api.depart_agent(
            mca["id"], {"departure_date": "2026-09-10T00:00:00Z"},
            make_market_center_admin_headers(mca["id"])), 200)
        period = get_success_data(api.get_period(period["id"], PA))
        assert period["distributed_total"] == pytest.approx(0.00, abs=0.01)
        assert period["center_retained_amount"] == pytest.approx(780.00, abs=0.01), (
            f"the pool is unchanged at 780.00, got {period['center_retained_amount']}"
        )
        schedules = get_success_data(api.get_vesting_schedule(mca["id"], PA))
        assert schedules[0]["status"] == "FORFEITED"


class TestCommissionRequiresActiveAgent:
    def test_posting_against_departed_agent_rejected(self, api):
        """PRD §3.2: "Only ACTIVE agents may have commissions posted against
        them; posting against an agent in any other membership state fails with
        ERR_INVALID_STATE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/commission_requires_agent_active
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        validate_success(api.depart_agent(
            a1["id"], create_departure_payload(),
            make_market_center_admin_headers(a1["id"])), 200)
        payload = create_commission_event_payload(
            a1["id"], _agent_version(a1["id"]), gross_commission=1000.00,
            occurred_on="2026-09-11T00:00:00Z", external_ref="ref-dep")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_departed_agent_posting_blocked_even_before_cap_year_start(self, api):
        """PRD §3.2: "Only ACTIVE agents may have commissions posted against
        them; posting against an agent in any other membership state fails with
        ERR_INVALID_STATE (HTTP 409)."
        PRD §3.10: "On departure, membership_status moves from ACTIVE to DEPARTED
        — terminal — and the vesting schedule is evaluated in two variants."

        Design: Difficulty/cross_entity_state_dependency/commission_requires_agent_active
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        validate_success(api.depart_agent(
            a1["id"], create_departure_payload(),
            make_market_center_admin_headers(a1["id"])), 200)
        # Even a posting whose occurred_on precedes the current cap-year window
        # is rejected as a state violation: the write is gated on the agent's
        # membership, not on the business date.
        payload = create_commission_event_payload(
            a1["id"], _agent_version(a1["id"]), gross_commission=1000.00,
            occurred_on="2026-09-05T00:00:00Z", external_ref="ref-dep2")
        resp = api.create_commission_event(
            payload, make_market_center_admin_headers(a1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
