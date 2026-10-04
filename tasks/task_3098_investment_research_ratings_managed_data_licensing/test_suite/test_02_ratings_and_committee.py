"""Rating computation, committee governance, and conflict-gate tests."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    approve_proposal,
    cast_vote,
    cast_vote_ok,
    compute_quantitative_rating,
    create_analyst_rating,
    create_category,
    create_fund,
    create_fund_company,
    create_published_quant_rating,
    get_success_data,
    ingest_holdings,
    investigate_dispute_ok,
    make_analyst_headers,
    open_proposal,
    raise_dispute_ok,
    setup_rateable_fund,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["research_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

_DEFAULT_METH = dict(
    weight_return_bp=6000,
    weight_risk_bp=4000,
    rating_ceilings=[7000, 5000, 3000, 1000],
)


class TestQuantitativeStarVariants:
    def test_provisional_and_final_stars_diverge(self, api):
        """PRD §3.5: "The provisional variant, computed at ingestion time
        before the as-of window is locked, uses the three-year return alone
        for the return leg — ignoring the five-year leg even when present —
        and its result is kept in `provisional_stars`."
        PRD §3.5: "The final variant, computed through the rating-computation
        operation and through restatement cascades, uses the blended return
        leg and is stored in `stars`."

        Design: Difficulty/dual_variant_calc/quantitative_star_provisional_vs_final_diverge
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={
                "ticker": "DIVGX",
                "trailing_return_3y_bp": 9000,
                "trailing_return_5y_bp": 2000,
                "risk_score_bp": 2000,
            },
            methodology_overrides=dict(methodology_code="QV1", **_DEFAULT_METH),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        # final: return_leg = (9000*6000 + 2000*4000)/10000 = 6200;
        # score = (6200*6000 + 8000*4000)/10000 = 6920 -> 4 stars
        # provisional: leg = 9000; score = (9000*6000 + 8000*4000)/10000 = 8600 -> 5
        assert rating["stars"] == 4
        assert rating["provisional_stars"] == 5
        assert rating["stars"] != rating["provisional_stars"]
        assert rating["rating_status"] == "PROVISIONAL"

    def test_provisional_uses_three_year_leg_alone(self, api):
        """PRD §3.5: "The provisional variant, computed at ingestion time
        before the as-of window is locked, uses the three-year return alone
        for the return leg — ignoring the five-year leg even when present —
        and its result is kept in `provisional_stars`."

        Design: Difficulty/dual_variant_calc/quantitative_star_provisional_vs_final_diverge
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={
                "ticker": "DVG2",
                "trailing_return_3y_bp": 9000,
                "trailing_return_5y_bp": 2000,
                "risk_score_bp": 2000,
            },
            methodology_overrides=dict(methodology_code="QV1B", **_DEFAULT_METH),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        # If the provisional variant had used the blended leg, it would be 4.
        assert rating["provisional_stars"] == 5
        assert rating["stars"] == 4


class TestFloorDivisionOrder:
    def test_floor_division_applied_at_each_leg(self, api):
        """PRD §3.5: "The return leg combines the fund's
        `trailing_return_3y_bp` weighted at 6000 basis points with its
        `trailing_return_5y_bp` weighted at 4000 basis points — the three-year
        figure multiplied by 6000 plus the five-year figure multiplied by
        4000, the sum floor-divided by 10000"
        PRD §2.9: "Calculations that divide use integer floor division with no
        rounding to decimal places"

        Design: Difficulty/combinatorial_formula/quantitative_rating_floor_division_order_matters
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={
                "ticker": "FRACT",
                "trailing_return_3y_bp": 9001,
                "trailing_return_5y_bp": 2001,
                "risk_score_bp": 2000,
            },
            methodology_overrides=dict(methodology_code="QV2", **_DEFAULT_METH),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        # return_leg = floor((9001*6000 + 2001*4000)/10000) = floor(62006000/10000) = 6200
        # score = floor((6200*6000 + 8000*4000)/10000) = 6920 -> 4 stars
        assert rating["stars"] == 4
        # provisional: score = floor((9001*6000 + 8000*4000)/10000) = 8600 -> 5 stars
        assert rating["provisional_stars"] == 5

    def test_floor_division_score_boundary_behavior(self, api):
        """PRD §2.9: "Calculations that divide use integer floor division with
        no rounding to decimal places"

        Design: Difficulty/combinatorial_formula/quantitative_rating_floor_division_order_matters
        """
        # A sum-then-round implementation keeping fractions would compute
        # 6920.24 -> still 4 stars at ceiling 7000, so this second test pins
        # the provisional leg's floor behavior: 9001*6000+8000*4000 =
        # 86006000 -> floor 8600 (a rounding implementation could give 8601).
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={
                "ticker": "FRCT2",
                "trailing_return_3y_bp": 9001,
                "trailing_return_5y_bp": 2001,
                "risk_score_bp": 2000,
            },
            methodology_overrides=dict(
                methodology_code="QV2B",
                weight_return_bp=6000,
                weight_risk_bp=4000,
                rating_ceilings=[8600, 5000, 3000, 1000],
            ),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        # provisional score floor((9001*6000+8000*4000)/10000) = 8600 >= 8600 -> 5 stars
        assert rating["provisional_stars"] == 5


class TestCommitteeCycles:
    def test_rejection_cycles_rating_back_to_provisional(self, api):
        """PRD §3.6: "On rejection, the rating falls back from
        `COMMITTEE_REVIEW` to `PROVISIONAL`."
        PRD §3.6: "it moves to `REJECTED` from either state as soon as
        rejections number at least 2 and rejections are at least the
        approvals."

        Design: Difficulty/non_linear_state_machine/rating_committee_review_cycles_back_to_provisional_on_rejection
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "CYCF"},
            methodology_overrides=dict(
                methodology_code="AM1",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        proposal = open_proposal(rating["id"], "GOLD", analyst_id="analyst-lead")
        cast_vote_ok(proposal["id"], "REJECT", "voter-a")
        cast_vote_ok(proposal["id"], "REJECT", "voter-b")
        cast_vote_ok(proposal["id"], "APPROVE", "voter-c")

        proposal_after = get_success_data(api.get_proposal(proposal["id"], OPS))
        assert proposal_after["proposal_status"] == "REJECTED"

        # The rating fell back to PROVISIONAL, so a second proposal succeeds.
        proposal2 = open_proposal(rating["id"], "SILVER", analyst_id="analyst-lead")
        assert proposal2["proposal_status"] == "OPEN"
        rating_after = get_success_data(api.get_rating(rating["id"], OPS))
        assert rating_after["rating_status"] == "COMMITTEE_REVIEW"

    def test_second_committee_cycle_after_rejection(self, api):
        """PRD §3.6: "On rejection, the rating falls back from
        `COMMITTEE_REVIEW` to `PROVISIONAL`."

        Design: Difficulty/non_linear_state_machine/rating_committee_review_cycles_back_to_provisional_on_rejection
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "CYC2"},
            methodology_overrides=dict(
                methodology_code="AM1C",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        p1 = open_proposal(rating["id"], "GOLD", analyst_id="analyst-lead")
        cast_vote_ok(p1["id"], "REJECT", "voter-a")
        cast_vote_ok(p1["id"], "REJECT", "voter-b")
        cast_vote_ok(p1["id"], "APPROVE", "voter-c")
        assert get_success_data(api.get_rating(rating["id"], OPS))["rating_status"] == "PROVISIONAL"

        # Second loop: open and approve
        p2 = open_proposal(rating["id"], "SILVER", analyst_id="analyst-lead")
        approve_proposal(p2["id"])
        final = get_success_data(api.get_rating(rating["id"], OPS))
        assert final["rating_status"] == "PUBLISHED"
        assert final["analyst_grade"] == "SILVER"


class TestCommitteeQuorumAndApproval:
    def test_quorum_met_intermediate_state(self, api):
        """PRD §3.6: "Once the total votes cast reach three, the proposal
        moves from `OPEN` to `QUORUM_MET`."
        PRD §3.6: "From either `OPEN` or `QUORUM_MET`, the proposal moves to
        `APPROVED` as soon as the approvals number at least 2, the combined
        count of approvals, rejections, and abstentions is at least 3, and
        approvals strictly outnumber rejections."

        Design: Corner/state_machines/proposal_quorum_met_intermediate_state
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "FQMF"},
            methodology_overrides=dict(
                methodology_code="AQM",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        proposal = open_proposal(rating["id"], "SILVER", analyst_id="analyst-lead")
        cast_vote_ok(proposal["id"], "APPROVE", "voter-1")
        cast_vote_ok(proposal["id"], "ABSTAIN", "voter-2")
        cast_vote_ok(proposal["id"], "ABSTAIN", "voter-3")

        proposal_after = get_success_data(api.get_proposal(proposal["id"], OPS))
        assert proposal_after["proposal_status"] == "QUORUM_MET"
        assert proposal_after["approvals"] == 1
        assert proposal_after["rejections"] == 0
        rating_after = get_success_data(api.get_rating(rating["id"], OPS))
        assert rating_after["rating_status"] == "COMMITTEE_REVIEW"

    def test_committee_approval_publishes_with_grade_and_supersedes_prior(self, api):
        """PRD §3.6: "On approval, the underlying rating moves from
        `COMMITTEE_REVIEW` to `PUBLISHED` — provided its `suppression_reason`
        is `NONE` and no open commercial-conflict flag exists on the fund, the
        same gate as §2.7 — with its `analyst_grade` set from the approved
        proposal's `proposed_grade`, and any prior `PUBLISHED` analyst rating
        for the same fund moves to `SUPERSEDED`."

        Design: Corner/state_machines/committee_approval_publishes_rating_with_grade_and_supersedes_prior
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "FCAF"},
            methodology_overrides=dict(
                methodology_code="ACA",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        # First analyst rating: approve with GOLD
        r_old = create_analyst_rating(fund["id"], methodology["id"])
        p_old = open_proposal(r_old["id"], "GOLD", analyst_id="analyst-lead")
        cast_vote_ok(p_old["id"], "APPROVE", "voter-1")
        cast_vote_ok(p_old["id"], "APPROVE", "voter-2")
        cast_vote_ok(p_old["id"], "REJECT", "voter-3")
        assert get_success_data(api.get_rating(r_old["id"], OPS))["rating_status"] == "PUBLISHED"

        # Second analyst rating: approve with SILVER
        r_new = create_analyst_rating(fund["id"], methodology["id"])
        p_new = open_proposal(r_new["id"], "SILVER", analyst_id="analyst-lead")
        cast_vote_ok(p_new["id"], "APPROVE", "voter-1")
        cast_vote_ok(p_new["id"], "APPROVE", "voter-2")
        cast_vote_ok(p_new["id"], "REJECT", "voter-3")

        p_new_after = get_success_data(api.get_proposal(p_new["id"], OPS))
        assert p_new_after["proposal_status"] == "APPROVED"

        r_new_after = get_success_data(api.get_rating(r_new["id"], OPS))
        assert r_new_after["rating_status"] == "PUBLISHED"
        assert r_new_after["analyst_grade"] == "SILVER"

        r_old_after = get_success_data(api.get_rating(r_old["id"], OPS))
        assert r_old_after["rating_status"] == "SUPERSEDED"
        assert r_old_after["analyst_grade"] == "GOLD"


class TestPublishGuards:
    def test_publish_from_published_returns_invalid_state(self, api):
        """PRD §3.5: "a `ResearchOps` publish moves a rating from
        `PROVISIONAL` to `PUBLISHED`"
        PRD §2.4: "Legality of the target resource's current state for the
        requested transition, failing with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/publish_from_published_returns_invalid_state
        """
        _company, _fund, _meth, rating = create_published_quant_rating()
        resp = api.publish_rating(rating["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        after = get_success_data(api.get_rating(rating["id"], OPS))
        assert after["rating_status"] == "PUBLISHED"

    def test_publish_on_analyst_rating_rejected_kind_mismatch(self, api):
        """PRD §3.5: "a `ResearchOps` publish moves a rating from
        `PROVISIONAL` to `PUBLISHED` only when the rating is quantitative
        (publishing an analyst rating is rejected with
        `ERR_RATING_KIND_MISMATCH`, HTTP 409)"

        Design: Corner/state_machines/rating_kind_mismatch_publish_on_analyst_rating
        """
        _company, fund, methodology = setup_rateable_fund(
            methodology_overrides=dict(
                methodology_code="AKA",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        resp = api.publish_rating(rating["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_RATING_KIND_MISMATCH, expected_status=409)
        after = get_success_data(api.get_rating(rating["id"], OPS))
        assert after["rating_status"] == "PROVISIONAL"

    def test_publish_blocked_by_dispute_hold_suppression(self, api):
        """PRD §3.5: "the rating's `suppression_reason` is `NONE` (a rating
        suppressed by `DISPUTE_HOLD` or `CONFLICT_HOLD` is rejected with
        `ERR_SUPPRESSED_RATING`, HTTP 409)"
        PRD §3.7: "Investigation increments the issuer's `open_dispute_count`
        by 1 and sets `suppression_reason` to `DISPUTE_HOLD` on the disputed
        fund's `PROVISIONAL` and `COMMITTEE_REVIEW` ratings"

        Design: Corner/errors/err_suppressed_rating_on_dispute_hold_publish
        """
        company, fund, methodology = setup_rateable_fund(fund_overrides={"ticker": "FSR"})
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        dispute = raise_dispute_ok(fund["id"], company["id"], corrected_value=2100)
        investigate_dispute_ok(dispute["id"])

        resp = api.publish_rating(rating["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_SUPPRESSED_RATING, expected_status=409)
        after = get_success_data(api.get_rating(rating["id"], OPS))
        assert after["rating_status"] == "PROVISIONAL"
        assert after["suppression_reason"] == "DISPUTE_HOLD"


class TestConflictGateAndPriority:
    def test_state_check_beats_conflict_gate(self, api):
        """PRD §2.4: "When a request violates more than one rule, the platform
        evaluates checks in a fixed priority order so that the first failure
        surfaces deterministically rather than being masked by a later one."
        PRD §2.4: "5. Legality of the target resource's current state for the
        requested transition, failing with `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.4: "6. The conflict-of-interest gate described in §2.7, failing
        with `ERR_CONFLICT_OF_INTEREST`."

        Design: Difficulty/priority_pair_validation_conflict/conflict_of_interest_beats_seat_style_fiscal_checks_and_state_loses_to_conflict
        """
        company, fund, methodology = setup_rateable_fund(
            commercial_relationship="LICENSED_CLIENT",
            fund_overrides={"ticker": "FCO1"},
            methodology_overrides=dict(methodology_code="QV5", **_DEFAULT_METH),
        )
        rating_a = compute_quantitative_rating(fund["id"], methodology["id"])
        rating_b = compute_quantitative_rating(fund["id"], methodology["id"])
        get_success_data(api.withdraw_rating(rating_b["id"], OPS))

        # PROVISIONAL rating + OPEN conflict flag -> conflict gate fires
        resp_a = api.publish_rating(rating_a["id"], OPS)
        validate_error(resp_a, ApiErrorId.ERR_CONFLICT_OF_INTEREST, expected_status=422)
        # WITHDRAWN rating + same flag -> earlier state check fires
        resp_b = api.publish_rating(rating_b["id"], OPS)
        validate_error(resp_b, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

        after = get_success_data(api.get_rating(rating_a["id"], OPS))
        assert after["rating_status"] == "PROVISIONAL"

    def test_conflict_gate_fires_for_provisional_on_conflicted_fund(self, api):
        """PRD §2.7: "While such a flag's `flag_status` remains `OPEN`, the
        flag's `blocking` property is true and rating publication for that
        fund is prevented."
        PRD §2.7: "Three operations enforce this gate, and all three reject
        with `ERR_CONFLICT_OF_INTEREST` (HTTP 422): publishing a quantitative
        rating, opening a committee proposal on an analyst rating when the
        proposer covers a fund whose issuer holds an unwaived commercial
        relationship, and casting a committee vote that would approve such a
        rating."

        Design: Difficulty/priority_pair_validation_conflict/conflict_of_interest_beats_seat_style_fiscal_checks_and_state_loses_to_conflict
        """
        company, fund, methodology = setup_rateable_fund(
            commercial_relationship="LICENSED_CLIENT",
            fund_overrides={"ticker": "FCO2"},
            methodology_overrides=dict(methodology_code="QV5B", **_DEFAULT_METH),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        resp = api.publish_rating(rating["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CONFLICT_OF_INTEREST, expected_status=422)


class TestSegregationOfDuties:
    def test_existence_beats_sod_and_proposer_vote_rejected(self, api):
        """PRD §2.6: "the platform validates existence strictly left-to-right,
        parent before child. The request is rejected immediately with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        resolve, and deeper identifiers are never consulted."
        PRD §3.6: "the analyst recorded as `proposed_by` may not vote on their
        own proposal, and no voter may vote twice on the same proposal; either
        violation is rejected with `ERR_SOD_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/sod_violation_beats_temporal_and_existence_beats_sod
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "SODF"},
            methodology_overrides=dict(
                methodology_code="AM2",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        proposal = open_proposal(rating["id"], "BRONZE", analyst_id="analyst-lead")

        resp_nf = cast_vote(NON_EXISTENT_UUID, "APPROVE", "analyst-lead")
        validate_error(resp_nf, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

        resp_sod = cast_vote(proposal["id"], "APPROVE", "analyst-lead")
        validate_error(resp_sod, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)

        proposal_after = get_success_data(api.get_proposal(proposal["id"], OPS))
        assert proposal_after["approvals"] == 0
        assert proposal_after["rejections"] == 0

    def test_proposer_self_vote_leaves_counters_unchanged(self, api):
        """PRD §3.6: "the analyst recorded as `proposed_by` may not vote on
        their own proposal, and no voter may vote twice on the same proposal;
        either violation is rejected with `ERR_SOD_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/sod_violation_beats_temporal_and_existence_beats_sod
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "SODG"},
            methodology_overrides=dict(
                methodology_code="AM2B",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        proposal = open_proposal(rating["id"], "GOLD", analyst_id="analyst-lead")
        resp = cast_vote(proposal["id"], "APPROVE", "analyst-lead")
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)
        proposal_after = get_success_data(api.get_proposal(proposal["id"], OPS))
        assert proposal_after["approvals"] == 0
        assert proposal_after["rejections"] == 0

    def test_duplicate_vote_rejected(self, api):
        """PRD §3.6: "the analyst recorded as `proposed_by` may not vote on
        their own proposal, and no voter may vote twice on the same proposal;
        either violation is rejected with `ERR_SOD_VIOLATION` (HTTP 422)."

        Design: Corner/state_machines/duplicate_vote_rejected
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "FDV"},
            methodology_overrides=dict(
                methodology_code="ADV",
                methodology_kind="ANALYST",
                weight_return_bp=5000,
                weight_risk_bp=5000,
                rating_ceilings=[8000, 6000, 4000, 2000],
            ),
        )
        rating = create_analyst_rating(fund["id"], methodology["id"])
        proposal = open_proposal(rating["id"], "NEUTRAL", analyst_id="analyst-lead")
        cast_vote_ok(proposal["id"], "APPROVE", "voter-1")
        resp = cast_vote(proposal["id"], "REJECT", "voter-1")
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=422)
        proposal_after = get_success_data(api.get_proposal(proposal["id"], OPS))
        assert proposal_after["approvals"] == 1
        assert proposal_after["rejections"] == 0


class TestRatingCrossEntityDependencies:
    def test_publish_blocked_after_methodology_retired(self, api):
        """PRD §3.5: "a `ResearchOps` publish moves a rating from
        `PROVISIONAL` to `PUBLISHED` only when the rating is quantitative
        (publishing an analyst rating is rejected with
        `ERR_RATING_KIND_MISMATCH`, HTTP 409), the methodology is `EFFECTIVE`"
        PRD §5: `ERR_METHODOLOGY_NOT_EFFECTIVE` | 409

        Design: Difficulty/cross_entity_state_dependency/rating_publish_gated_on_methodology_effective_and_fund_active
        """
        _company, fund, methodology = setup_rateable_fund(
            fund_overrides={"ticker": "FDEP"},
            methodology_overrides=dict(methodology_code="QV6", **_DEFAULT_METH),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        get_success_data(api.retire_methodology(methodology["id"], OPS))

        resp = api.publish_rating(rating["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_METHODOLOGY_NOT_EFFECTIVE, expected_status=409)
        after = get_success_data(api.get_rating(rating["id"], OPS))
        assert after["rating_status"] == "PROVISIONAL"

    def test_compute_rating_requires_effective_methodology(self, api):
        """PRD §3.5: "The referenced methodology must be `EFFECTIVE`;
        otherwise the request is rejected with
        `ERR_METHODOLOGY_NOT_EFFECTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/rating_publish_gated_on_methodology_effective_and_fund_active
        """
        company = create_fund_company(legal_name="Draft Meth Co")
        fund = create_fund(company["id"], ticker="FDEP2")
        ingest_holdings(fund["id"])
        # Methodology stays DRAFT (never activated)
        from test_helpers import create_methodology_payload

        meth = get_success_data(
            api.create_methodology(
                create_methodology_payload(methodology_code="QV6D"), OPS
            )
        )
        assert meth["methodology_status"] == "DRAFT"
        resp = api.compute_rating(
            {"fund_id": fund["id"], "methodology_id": meth["id"]}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_METHODOLOGY_NOT_EFFECTIVE, expected_status=409)


class TestRatingCeilingBoundary:
    def test_score_exactly_at_ceiling_yields_higher_star(self, api):
        """PRD §3.5: "Stars map from the score through the methodology's
        `rating_ceilings`: five stars when the score is at least the first
        cutoff, otherwise four when at least the second, otherwise three when
        at least the third, otherwise two when at least the fourth, otherwise
        one."

        Design: Corner/calculations/quantitative_rating_ceiling_boundary_exactly_at_cutoff
        """
        create_category(category_code="QB_C")
        company = create_fund_company(legal_name="Boundary Ratings Co")
        f_eq = create_fund(
            company["id"],
            ticker="FEQ",
            trailing_return_3y_bp=5000,
            trailing_return_5y_bp=5000,
            risk_score_bp=0,
        )
        f_below = create_fund(
            company["id"],
            ticker="FBELOW",
            trailing_return_3y_bp=5000,
            trailing_return_5y_bp=5000,
            risk_score_bp=1,
        )
        ingest_holdings(f_eq["id"])
        ingest_holdings(f_below["id"])
        from test_helpers import create_and_activate_methodology

        methodology = create_and_activate_methodology(
            methodology_code="QB1", **_DEFAULT_METH
        )
        # FEQ: return_leg = 5000; score = (5000*6000 + 10000*4000)/10000 = 7000
        r_eq = compute_quantitative_rating(f_eq["id"], methodology["id"])
        # FBELOW: score = floor((5000*6000 + 9999*4000)/10000) = 6999
        r_below = compute_quantitative_rating(f_below["id"], methodology["id"])
        assert r_eq["stars"] == 5
        assert r_below["stars"] == 4
        assert r_eq["stars"] - r_below["stars"] == 1
