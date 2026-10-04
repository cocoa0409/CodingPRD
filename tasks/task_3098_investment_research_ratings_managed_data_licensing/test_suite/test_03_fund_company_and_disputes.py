"""Fund company lifecycle, fund liquidation, and data-quality dispute tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_constituent_ok,
    compute_quantitative_rating,
    create_fund,
    create_fund_company,
    get_success_data,
    ingest_holdings,
    investigate_dispute_ok,
    raise_dispute_ok,
    resolve_dispute_ok,
    setup_licensed_index,
    setup_rateable_fund,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["research_ops_headers"]


class TestFundCompanySuspensionCascade:
    def test_company_suspension_cascades_to_funds_and_rating_suppression(self, api):
        """PRD §3.1: "Suspending a fund company — a `ResearchOps` operation
        legal only while the company's `company_status` is `ACTIVE` —
        cascades: every `ACTIVE` fund of the company moves to `SUSPENDED`, and
        each such fund's non-terminal ratings (those in `PROVISIONAL` or
        `COMMITTEE_REVIEW`) have their `suppression_reason` set to
        `DISPUTE_HOLD`, blocking their publication until the hold clears."

        Design: Difficulty/transitive_cascade/fund_company_suspension_cascades_to_funds_and_rating_suppression
        """
        company, fund, methodology = setup_rateable_fund(
            legal_name="Cascade Sponsor",
            fund_overrides={"ticker": "FCSC"},
            methodology_overrides=dict(methodology_code="QV4"),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])

        resp = api.suspend_fund_company(company["id"], OPS)
        company_after = validate_success(resp)
        assert company_after["company_status"] == "SUSPENDED"

        fund_after = get_success_data(api.get_fund(fund["id"], OPS))
        assert fund_after["fund_status"] == "SUSPENDED"

        rating_after = get_success_data(api.get_rating(rating["id"], OPS))
        assert rating_after["suppression_reason"] == "DISPUTE_HOLD"
        assert rating_after["rating_status"] == "PROVISIONAL"

    def test_company_suspension_blocks_publication_of_suppressed_rating(self, api):
        """PRD §3.1: "each such fund's non-terminal ratings (those in
        `PROVISIONAL` or `COMMITTEE_REVIEW`) have their `suppression_reason`
        set to `DISPUTE_HOLD`, blocking their publication until the hold
        clears."
        PRD §3.5: "the rating's `suppression_reason` is `NONE` (a rating
        suppressed by `DISPUTE_HOLD` or `CONFLICT_HOLD` is rejected with
        `ERR_SUPPRESSED_RATING`, HTTP 409)"

        Design: Difficulty/transitive_cascade/fund_company_suspension_cascades_to_funds_and_rating_suppression
        """
        company, fund, methodology = setup_rateable_fund(
            legal_name="Cascade Blocker",
            fund_overrides={"ticker": "FCSB"},
            methodology_overrides=dict(methodology_code="QV4B"),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        get_success_data(api.suspend_fund_company(company["id"], OPS))
        resp = api.publish_rating(rating["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_SUPPRESSED_RATING, expected_status=409)


class TestFundLiquidation:
    def test_fund_liquidation_cascades_rating_withdrawal_and_index_stripping(self, api):
        """PRD §3.1: "moves the fund to `LIQUIDATED`, withdraws every
        non-terminal rating of the fund (`PROVISIONAL`, `COMMITTEE_REVIEW`,
        and `PUBLISHED` ratings all move to `WITHDRAWN`), and deletes the
        fund's row from every constituent list of any index in `LIVE` or
        `DRAFT` status."

        Design: Corner/state_machines/fund_liquidation_cascades_rating_withdrawal_and_index_stripping
        """
        company, fund, methodology = setup_rateable_fund(
            legal_name="Liquidating Co",
            fund_overrides={"ticker": "FLQ"},
            methodology_overrides=dict(methodology_code="QL1"),
        )
        rating = compute_quantitative_rating(fund["id"], methodology["id"])
        get_success_data(api.publish_rating(rating["id"], OPS))

        # DRAFT index with the fund as its only constituent (no license needed
        # while the index remains DRAFT)
        _licensee, _agreement, index = setup_licensed_index(
            methodology,
            index_overrides={"index_code": "IXL", "single_constituent_cap_bp": 5000},
        )
        add_constituent_ok(index["id"], fund["id"], 4000)

        resp = api.liquidate_fund(fund["id"], OPS)
        fund_after = validate_success(resp)
        assert fund_after["fund_status"] == "LIQUIDATED"

        rating_after = get_success_data(api.get_rating(rating["id"], OPS))
        assert rating_after["rating_status"] == "WITHDRAWN"

        constituents, _meta = validate_paginated(api.list_index_constituents(index["id"], OPS))
        assert constituents == []


class TestOffboardLockdown:
    def test_offboard_terminal_lockdown(self, api):
        """PRD §3.1: "Offboarding is terminal and legal only from `ACTIVE`,
        only when every fund of the company has reached `LIQUIDATED`, and only
        with zero open disputes"
        PRD §3.1: "Suspending a fund company — a `ResearchOps` operation legal
        only while the company's `company_status` is `ACTIVE`"

        Design: Corner/state_machines/offboard_terminal_lockdown
        """
        company = create_fund_company(legal_name="Terminal Co")
        fund = create_fund(company["id"], ticker="TOF")
        get_success_data(api.liquidate_fund(fund["id"], OPS))
        resp = api.offboard_fund_company(company["id"], OPS)
        assert validate_success(resp)["company_status"] == "OFFBOARDED"

        resp2 = api.suspend_fund_company(company["id"], OPS)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        after = get_success_data(api.get_fund_company(company["id"], OPS))
        assert after["company_status"] == "OFFBOARDED"


class TestDisputeLifecycle:
    def test_dispute_cycle_conserves_open_dispute_count(self, api):
        """PRD §3.7: "Investigation increments the issuer's
        `open_dispute_count` by 1"
        PRD §3.7: "Either outcome decrements the issuer's `open_dispute_count`
        by 1"
        PRD §3.7: "An `ACCEPTED` resolution on a numeric disputed field
        additionally updates the corresponding fund field to the
        `corrected_value`"

        Design: Difficulty/compensating_invariant/dispute_open_close_cycle_conserves_open_dispute_count
        """
        company = create_fund_company(legal_name="Dispute Sponsor")
        fund = create_fund(company["id"], ticker="DINV", trailing_return_3y_bp=5000)
        d1 = raise_dispute_ok(
            fund["id"], company["id"], disputed_field="TRAILING_RETURN_3Y", corrected_value=6000
        )
        d2 = raise_dispute_ok(
            fund["id"], company["id"], disputed_field="TRAILING_RETURN_3Y", corrected_value=7000
        )
        investigate_dispute_ok(d1["id"])
        investigate_dispute_ok(d2["id"])

        mid = get_success_data(api.get_fund_company(company["id"], OPS))
        assert mid["open_dispute_count"] == 2

        resolve_dispute_ok(d1["id"], "REJECTED", "data verified")
        fund_after_reject = get_success_data(api.get_fund(fund["id"], OPS))
        assert fund_after_reject["trailing_return_3y_bp"] == 5000

        resolve_dispute_ok(d2["id"], "ACCEPTED", "correction applied")
        fund_after_accept = get_success_data(api.get_fund(fund["id"], OPS))
        assert fund_after_accept["trailing_return_3y_bp"] == 7000

        company_after = get_success_data(api.get_fund_company(company["id"], OPS))
        assert company_after["open_dispute_count"] == 0

        d1_after = get_success_data(api.get_dispute(d1["id"], OPS))
        d2_after = get_success_data(api.get_dispute(d2["id"], OPS))
        assert d1_after["dispute_status"] == "RESOLVED_REJECTED"
        assert d2_after["dispute_status"] == "RESOLVED_ACCEPTED"

    def test_rejected_dispute_writes_nothing_to_fund_field(self, api):
        """PRD §3.7: "An `ACCEPTED` resolution on a numeric disputed field
        additionally updates the corresponding fund field to the
        `corrected_value`"
        PRD §3.7: "Resolution moves the dispute to `RESOLVED_ACCEPTED` or
        `RESOLVED_REJECTED`, both terminal."

        Design: Difficulty/compensating_invariant/dispute_open_close_cycle_conserves_open_dispute_count
        """
        company = create_fund_company(legal_name="Reject Only Co")
        fund = create_fund(company["id"], ticker="DINR", trailing_return_3y_bp=5000)
        dispute = raise_dispute_ok(
            fund["id"], company["id"], disputed_field="TRAILING_RETURN_3Y", corrected_value=9999
        )
        investigate_dispute_ok(dispute["id"])
        resolve_dispute_ok(dispute["id"], "REJECTED", "verified correct")
        fund_after = get_success_data(api.get_fund(fund["id"], OPS))
        assert fund_after["trailing_return_3y_bp"] == 5000
        company_after = get_success_data(api.get_fund_company(company["id"], OPS))
        assert company_after["open_dispute_count"] == 0

    def test_dispute_by_non_issuer_rejected(self, api):
        """PRD §3.7: "The raiser must be the fund's issuer:
        `raised_by_company_id` must equal the fund's `fund_company_id`, which
        for a `FundCompanyRep` is also their `X-User-ID`; and a numeric
        `disputed_field` without a `corrected_value` is invalid. Either
        violation is rejected with `ERR_DISPUTE_NOT_ISSUER` (HTTP 422)."

        Design: Corner/validations/dispute_by_non_issuer_rejected
        """
        owner = create_fund_company(legal_name="Owner Co")
        other = create_fund_company(legal_name="Other Co")
        fund = create_fund(owner["id"], ticker="FOWN")
        from test_helpers import make_fund_company_rep_headers, raise_dispute_payload

        resp = api.raise_dispute(
            fund["id"],
            raise_dispute_payload(
                other["id"], disputed_field="RISK_SCORE", corrected_value=1200
            ),
            make_fund_company_rep_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_ISSUER, expected_status=422)
        disputes, meta = validate_paginated(api.list_fund_disputes(fund["id"], OPS))
        assert disputes == []
        assert meta["total_count"] == 0

    def test_reinstate_company_blocked_by_open_disputes(self, api):
        """PRD §3.1: "Reinstatement is legal only from `SUSPENDED` and only
        while the company's `open_dispute_count` is 0; an attempt with open
        disputes outstanding is rejected with `ERR_OPEN_DISPUTES_REMAIN`
        (HTTP 409)."

        Design: Corner/validations/reinstate_company_blocked_by_open_disputes
        """
        company = create_fund_company(legal_name="Reinstate Co")
        fund = create_fund(company["id"], ticker="FRCF")
        dispute = raise_dispute_ok(
            fund["id"], company["id"], disputed_field="RISK_SCORE", corrected_value=1100
        )
        investigate_dispute_ok(dispute["id"])
        get_success_data(api.suspend_fund_company(company["id"], OPS))

        resp = api.reinstate_fund_company(company["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTES_REMAIN, expected_status=409)
        after = get_success_data(api.get_fund_company(company["id"], OPS))
        assert after["company_status"] == "SUSPENDED"


class TestDataQualityScore:
    def test_quality_score_computed_on_read(self, api):
        """PRD §3.7: "A fund company's `quality_score_bp`, computed on every
        read of the company, starts from 10000 and subtracts 1500 basis points
        for each dispute against the company's funds that was resolved
        `RESOLVED_ACCEPTED` within the trailing 365 logical days, then
        subtracts a further 500 basis points times the company's current
        `open_dispute_count`, floored at 0."

        Design: Corner/calculations/data_quality_score_computed_on_read
        """
        company = create_fund_company(legal_name="Quality Co")
        fund = create_fund(company["id"], ticker="FQD")
        d_acc = raise_dispute_ok(fund["id"], company["id"], corrected_value=3500)
        d_o1 = raise_dispute_ok(fund["id"], company["id"], corrected_value=3600)
        d_o2 = raise_dispute_ok(fund["id"], company["id"], corrected_value=3700)
        investigate_dispute_ok(d_acc["id"])
        investigate_dispute_ok(d_o1["id"])
        investigate_dispute_ok(d_o2["id"])
        resolve_dispute_ok(d_acc["id"], "ACCEPTED", "fixed")

        got = validate_success(api.get_fund_company(company["id"], OPS))
        # 10000 - 1500*1 (accepted) - 500*2 (still open) = 7500
        assert got["quality_score_bp"] == 7500
        assert got["open_dispute_count"] == 2
