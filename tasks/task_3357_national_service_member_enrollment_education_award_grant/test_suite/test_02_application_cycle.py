"""Application cycle: dual cost-per-MSY bases, match rounding, the
clarification loop, and the submit/award gates (PRD §2.6, §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    award_application_payload,
    create_competition_payload,
    create_draft_application,
    make_grantee_staff_headers,
    match_line,
    request_clarification_payload,
    respond_clarification_payload,
    set_clock,
    setup_org_competition,
    slot_request,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_AFTER_CLOSE = "2026-10-02T00:00:00Z"


def _submitted_app(api, federal=4000000, slots=None, match=None):
    """Org + competition + DRAFT application submitted (UNDER_REVIEW)."""
    base = setup_org_competition()
    app = create_draft_application(
        base["comp_id"],
        base["org_id"],
        federal_share_requested_cents=federal,
        slot_requests=slots,
        match_lines=match,
    )
    submit_application(app["id"], base["org_id"])
    return {**base, "app_id": app["id"]}


class TestDualCostPerMsyBases:
    def test_federal_and_total_bases_computed_for_same_application(self, api, officer_headers):
        """The same slot_requests and federal share produce two valid bases:
        2 FULL_TIME slots give total_term_minutes 204000 and msy 2.0, a CASH
        match of 1000000 keeps 1000000 allowable, and the two cost figures
        diverge (2000000.0 federal vs 2500000.0 total).

        PRD §3.2: "Two cost-per-MSY figures follow, both rounded half up to 2 decimal places: `cost_per_msy_federal_cents`, the federal share requested per member-service year, and `cost_per_msy_total_cents`, the same ratio with the allowable match commitment added to the numerator."

        Design: Difficulty/dual_variant_calc/cost_per_msy_federal_vs_total_basis
        """
        base = setup_org_competition()
        app = create_draft_application(base["comp_id"], base["org_id"])
        fetched = validate_success(api.get_application(app["id"], officer_headers))
        assert fetched["total_term_minutes"] == 204000
        assert fetched["msy_requested"] == pytest.approx(2.0, abs=0.0005)
        assert fetched["allowable_match_commitment_cents"] == 1000000
        assert fetched["cost_per_msy_federal_cents"] == pytest.approx(2000000.0, abs=0.005)
        assert fetched["cost_per_msy_total_cents"] == pytest.approx(2500000.0, abs=0.005)

    def test_cap_binds_federal_basis_while_total_basis_exceeds_it(self, api, officer_headers):
        """The federal basis (2000000.0) satisfies the 2300000 cap while the
        total basis (2500000.0) exceeds it — only the federal basis is gated,
        so the application may still be submitted.

        PRD §3.2: "For any application with a nonzero allowable match, the total-cost basis is strictly larger than the federal basis — an application can sit under the cap on one and over it on the other, and as the next paragraph shows, only the federal basis is gated."
        PRD §3.2: "Second, the federal-basis cost per MSY must not exceed the statutory cap of 2300000.00 cents ($23,000.00 per member-service year); equality with the cap is allowed, and a breach is `ERR_COST_PER_MSY_EXCEEDS_CAP`."

        Design: Difficulty/dual_variant_calc/cost_per_msy_federal_vs_total_basis
        """
        base = setup_org_competition()
        app = create_draft_application(base["comp_id"], base["org_id"])
        fetched = validate_success(api.get_application(app["id"], officer_headers))
        federal_basis = fetched["cost_per_msy_federal_cents"]
        total_basis = fetched["cost_per_msy_total_cents"]
        assert federal_basis <= 2300000, "federal basis must satisfy the cap"
        assert total_basis > 2300000, "total basis exceeds the cap for the same application"
        assert total_basis > federal_basis
        submitted = submit_application(app["id"], base["org_id"])
        assert submitted["status"] == "UNDER_REVIEW", (
            "submit succeeds because the cap gates only the federal basis"
        )


class TestMatchPerLineRounding:
    def test_per_line_rounding_then_sum(self, api, officer_headers):
        """Three IN_KIND lines of 100001 cents round individually to 80001 and
        sum to 240003 (sum-then-round would give 240002 — a violation).

        PRD §2.6: "For match commitments and match reports, each line is rounded half up to integer cents first, and the line values are summed afterward — summing raw values and rounding once at the end is a violation, because the two orders can disagree by a cent."

        Design: Difficulty/combinatorial_formula/match_allowable_per_line_rounding
        """
        base = setup_org_competition()
        app = create_draft_application(
            base["comp_id"],
            base["org_id"],
            federal_share_requested_cents=1000000,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[
                match_line("IN_KIND", 100001),
                match_line("IN_KIND", 100001),
                match_line("IN_KIND", 100001),
            ],
        )
        fetched = validate_success(api.get_application(app["id"], officer_headers))
        assert fetched["allowable_match_commitment_cents"] == 240003, (
            "per-line rounding: 3 x round(100001 x 0.8) = 3 x 80001"
        )
        assert fetched["cost_per_msy_federal_cents"] == pytest.approx(1000000.0, abs=0.005)

    def test_per_line_rounded_commitment_satisfies_match_floor_at_submit(self, api):
        """240003 x 25 = 6000075 >= 1000000 x 6 = 6000000, so the per-line
        rounded commitment clears the 24% floor and the submit succeeds.

        PRD §3.2: "Third, the match must clear the statutory floor: the allowable match commitment multiplied by 25 must be at least the federal share requested multiplied by 6 — that is, allowable match of at least 24% of the federal share, with equality allowed — else `ERR_MATCH_BELOW_MINIMUM`."

        Design: Difficulty/combinatorial_formula/match_allowable_per_line_rounding
        """
        base = setup_org_competition()
        app = create_draft_application(
            base["comp_id"],
            base["org_id"],
            federal_share_requested_cents=1000000,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[
                match_line("IN_KIND", 100001),
                match_line("IN_KIND", 100001),
                match_line("IN_KIND", 100001),
            ],
        )
        resp = api.submit_application(app["id"], make_grantee_staff_headers(base["org_id"]))
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "UNDER_REVIEW"


class TestClarificationCycle:
    def test_clarification_loop_repeats(self, api, officer_headers):
        """The UNDER_REVIEW -> CLARIFICATION_REQUESTED -> UNDER_REVIEW loop
        runs twice in a row before any terminal decision.

        PRD §3.2: "Review is a conversation. A `CNCSProgramOfficer` may ask for clarification, moving the application `UNDER_REVIEW` → `CLARIFICATION_REQUESTED` and recording the payload's `question` as the application's `clarification_question`. The applicant answers by responding to the clarification; the payload's `response` is recorded as `clarification_response` and the application returns to `UNDER_REVIEW`. This loop may repeat without bound."

        Design: Difficulty/non_linear_state_machine/application_clarification_cycle
        """
        ctx = _submitted_app(api)
        staff = make_grantee_staff_headers(ctx["org_id"])
        first = validate_success(
            api.request_clarification(
                ctx["app_id"], request_clarification_payload("What is the recruitment plan?"), officer_headers
            )
        )
        assert first["status"] == "CLARIFICATION_REQUESTED"
        assert first["clarification_question"] == "What is the recruitment plan?"
        back = validate_success(
            api.respond_clarification(
                ctx["app_id"], respond_clarification_payload("Local college pipeline."), staff
            )
        )
        assert back["status"] == "UNDER_REVIEW"
        assert back["clarification_response"] == "Local college pipeline."
        second = validate_success(
            api.request_clarification(
                ctx["app_id"], request_clarification_payload("Clarify match source."), officer_headers
            )
        )
        assert second["status"] == "CLARIFICATION_REQUESTED", "the cycle repeats"
        final = validate_success(
            api.respond_clarification(
                ctx["app_id"], respond_clarification_payload("Second answer"), staff
            )
        )
        assert final["status"] == "UNDER_REVIEW"

    def test_each_clarification_hop_bumps_version_and_overwrites_fields(self, api, officer_headers):
        """Create v1, submit v2, clarify v3, respond v4, clarify v5, respond
        v6: every hop is a mutation, and the latest question/response win.

        PRD §2.5: "`version` (integer): a system-managed integer starting at 1 that increments on every mutation."
        PRD §3.2: "This loop may repeat without bound. Both fields remain null until their respective events set them."

        Design: Difficulty/non_linear_state_machine/application_clarification_cycle
        """
        ctx = _submitted_app(api)
        staff = make_grantee_staff_headers(ctx["org_id"])
        validate_success(
            api.request_clarification(ctx["app_id"], request_clarification_payload("Q1"), officer_headers)
        )
        validate_success(
            api.respond_clarification(ctx["app_id"], respond_clarification_payload("A1"), staff)
        )
        validate_success(
            api.request_clarification(
                ctx["app_id"], request_clarification_payload("Clarify match source."), officer_headers
            )
        )
        validate_success(
            api.respond_clarification(
                ctx["app_id"], respond_clarification_payload("Second answer"), staff
            )
        )
        app = validate_success(api.get_application(ctx["app_id"], officer_headers))
        assert app["status"] == "UNDER_REVIEW"
        assert app["version"] == 6, "create v1 + five mutation hops"
        assert app["clarification_question"] == "Clarify match source."
        assert app["clarification_response"] == "Second answer"


class TestSubmitAndAwardGates:
    def test_submit_twice_is_invalid_state(self, api, officer_headers):
        """A repeat submit from UNDER_REVIEW hits the generic transition guard.

        PRD §3.2: "A submit attempted from any state other than `DRAFT` hits the generic transition guard, `ERR_INVALID_STATE`."

        Design: Corner/state_machines/submit_twice_returns_invalid_state
        """
        ctx = _submitted_app(api)
        resp = api.submit_application(ctx["app_id"], make_grantee_staff_headers(ctx["org_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        app = validate_success(api.get_application(ctx["app_id"], officer_headers))
        assert app["status"] == "UNDER_REVIEW"

    def test_award_on_rejected_application_is_invalid_state(self, api, officer_headers):
        """Awarding a terminal REJECTED application is a 409; no GrantAward is
        created, and the rejection itself finalized the competition.

        PRD §3.2: "Awarding is permitted only from `UNDER_REVIEW` and only after the competition has been closed; an award attempt while the competition is still `OPEN` is rejected with `ERR_INVALID_STATE`."
        PRD §3.1: "Its final transition, `CLOSED` → `AWARDS_FINALIZED`, is fired by the system itself the moment no application of that competition remains in `DRAFT`, `UNDER_REVIEW`, or `CLARIFICATION_REQUESTED` — that is, when every application has been awarded or rejected."

        Design: Corner/state_machines/award_on_rejected_application_returns_invalid_state
        """
        ctx = _submitted_app(api)
        set_clock(CLOCK_AFTER_CLOSE)
        validate_success(api.close_competition(ctx["comp_id"], officer_headers))
        rejected = validate_success(
            api.reject_application(ctx["app_id"], {"reason": "Insufficient community need"}, officer_headers)
        )
        assert rejected["status"] == "REJECTED"
        resp = api.award_application(
            ctx["app_id"], award_application_payload(4000000), officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, meta = validate_paginated(
            api.list_awards(officer_headers, params={"application_id": ctx["app_id"]})
        )
        assert rows == [] and meta["total_count"] == 0
        comp = validate_success(api.get_competition(ctx["comp_id"], officer_headers))
        assert comp["status"] == "AWARDS_FINALIZED", "rejection also bubbles up"

    def test_cost_per_msy_exactly_at_cap_passes_one_cent_over_fails(self, api, officer_headers):
        """1 FULL_TIME slot: federal 2300000 yields cost exactly 2300000.0 and
        submits; federal 2300001 yields 2300001.0 (one cent of input over) and
        is rejected. (Re-derived from the PRD formula: with total_term_minutes
        102000 the one-cent-over basis is 2300001.0.)

        PRD §3.2: "Second, the federal-basis cost per MSY must not exceed the statutory cap of 2300000.00 cents ($23,000.00 per member-service year); equality with the cap is allowed, and a breach is `ERR_COST_PER_MSY_EXCEEDS_CAP`."

        Design: Corner/calculations/cost_per_msy_exactly_at_cap_passes_one_cent_over_fails
        """
        base = setup_org_competition()
        staff = make_grantee_staff_headers(base["org_id"])
        app_ok = create_draft_application(
            base["comp_id"], base["org_id"],
            federal_share_requested_cents=2300000,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[match_line("CASH", 560000)],
        )
        app_over = create_draft_application(
            base["comp_id"], base["org_id"],
            federal_share_requested_cents=2300001,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[match_line("CASH", 560000)],
        )
        ok_doc = validate_success(api.get_application(app_ok["id"], officer_headers))
        assert ok_doc["cost_per_msy_federal_cents"] == pytest.approx(2300000.0, abs=0.005)
        over_doc = validate_success(api.get_application(app_over["id"], officer_headers))
        assert over_doc["cost_per_msy_federal_cents"] == pytest.approx(2300001.0, abs=0.005)
        ok_resp = api.submit_application(app_ok["id"], staff)
        assert validate_success(ok_resp, 200)["status"] == "UNDER_REVIEW"
        over_resp = api.submit_application(app_over["id"], staff)
        validate_error(over_resp, ApiErrorId.ERR_COST_PER_MSY_EXCEEDS_CAP)
        assert validate_success(api.get_application(app_over["id"], officer_headers))["status"] == "DRAFT"

    def test_match_floor_exactly_24_percent_boundary(self, api):
        """CASH 240000 against federal 1000000 is exactly 24% and passes;
        CASH 239999 is one cent short of the floor and is rejected.

        PRD §3.2: "Third, the match must clear the statutory floor: the allowable match commitment multiplied by 25 must be at least the federal share requested multiplied by 6 — that is, allowable match of at least 24% of the federal share, with equality allowed — else `ERR_MATCH_BELOW_MINIMUM`."

        Design: Corner/calculations/match_floor_exactly_24_percent_boundary
        """
        base = setup_org_competition()
        staff = make_grantee_staff_headers(base["org_id"])
        app_ok = create_draft_application(
            base["comp_id"], base["org_id"],
            federal_share_requested_cents=1000000,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[match_line("CASH", 240000)],
        )
        app_short = create_draft_application(
            base["comp_id"], base["org_id"],
            federal_share_requested_cents=1000000,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[match_line("CASH", 239999)],
        )
        ok_resp = api.submit_application(app_ok["id"], staff)
        assert validate_success(ok_resp, 200)["status"] == "UNDER_REVIEW", (
            "240000 x 25 == 6000000 >= 1000000 x 6 == 6000000 (equality allowed)"
        )
        short_resp = api.submit_application(app_short["id"], staff)
        validate_error(short_resp, ApiErrorId.ERR_MATCH_BELOW_MINIMUM)

    def test_submit_after_window_close_is_window_closed(self, api, officer_headers):
        """Submitting one second after application_close_at is rejected and
        the application stays DRAFT.

        PRD §3.2: "First, the submission must land within the competition window — at or after `application_open_at` and at or before `application_close_at` — else `ERR_COMPETITION_WINDOW_CLOSED`."

        Design: Corner/validations/submit_after_window_close_returns_window_closed
        """
        base = setup_org_competition()
        app = create_draft_application(base["comp_id"], base["org_id"])
        set_clock(CLOCK_AFTER_CLOSE)
        resp = api.submit_application(app["id"], make_grantee_staff_headers(base["org_id"]))
        validate_error(resp, ApiErrorId.ERR_COMPETITION_WINDOW_CLOSED)
        assert validate_success(api.get_application(app["id"], officer_headers))["status"] == "DRAFT"

    def test_competition_close_before_window_end_is_invalid_state(self, api, officer_headers):
        """Closing while the window is still running is a premature close.

        PRD §3.1: "closing requires the current logical time to be strictly later than `application_close_at`, and a premature close is rejected with `ERR_INVALID_STATE`"

        Design: Corner/validations/competition_close_before_window_end_returns_invalid_state
        """
        set_clock()
        comp_resp = api.create_competition(create_competition_payload(), officer_headers)
        comp = validate_success(comp_resp, 201)
        set_clock("2026-09-15T00:00:00Z")
        resp = api.close_competition(comp["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert validate_success(api.get_competition(comp["id"], officer_headers))["status"] == "OPEN"

    def test_award_amount_above_request_rejected(self, api, officer_headers):
        """Awarding 4000001 against a 4000000 request is rejected; awarding
        exactly the request mints the GrantAward.

        PRD §3.2: "The officer commits a `federal_share_awarded_cents`, which must not exceed the `federal_share_requested_cents` (else `ERR_AWARD_EXCEEDS_REQUEST`)"

        Design: Corner/validations/award_amount_above_request_rejected
        """
        ctx = _submitted_app(api)
        set_clock(CLOCK_AFTER_CLOSE)
        validate_success(api.close_competition(ctx["comp_id"], officer_headers))
        over = api.award_application(
            ctx["app_id"], award_application_payload(4000001), officer_headers
        )
        validate_error(over, ApiErrorId.ERR_AWARD_EXCEEDS_REQUEST)
        app = validate_success(api.get_application(ctx["app_id"], officer_headers))
        assert app["status"] == "UNDER_REVIEW"
        exact = api.award_application(
            ctx["app_id"], award_application_payload(4000000), officer_headers
        )
        award = validate_success(exact, 201)
        assert award["status"] == "ACTIVE"
        assert award["federal_share_awarded_cents"] == 4000000
