"""Grant cycles, applications, allocations, match, and disbursements."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error, get_success_data,
    create_member, create_counselor, create_course, complete_course_enrollment,
    create_certification, certify, set_clock,
    setup_chartered_member_with_counselor, create_grant_cycle,
    create_grant_application, submit_application, advance_cycle_to_awarded,
    award_application, activate_award, post_disbursement,
    setup_cycle_with_award, setup_active_award_with_disbursement,
    make_member_admin_headers, make_grant_officer_headers,
)
from test_helpers.assertions import assert_grant_award

DIRECTOR = TEST_USERS["network_director_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]


class TestMatchRequirementVariants:
    def test_match_requirement_reduced_vs_standard(self, api):
        """PRD §3.5: "The award carries a `required_match_cents` computed at
        creation: take the total of the formula and competitive components
        first, then select the rate by member tenure — ten percent when the
        member was chartered within the preceding twenty-four months (the
        provisional-period rate), otherwise twenty-five percent — and round the
        product up to whole cents."

        Design: Difficulty/dual_variant_calc/match_requirement_reduced_vs_standard
        """
        # Old member chartered ~36 months before the award.
        set_clock("2024-03-01T00:00:00Z")
        m_old, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Old Roots Housing", "ein": "222222222",
                              "state_code": "TX", "service_regions": ["48001"]},
            course_code="HO-101",
            delivery_start="2024-03-02T00:00:00Z", delivery_end="2024-03-20T00:00:00Z",
            in_session_at="2024-03-10T00:00:00Z")

        # New member chartered ~12 months before the award.
        set_clock("2026-03-01T00:00:00Z")
        m_new, _c2, _cert2 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "New Leaf Housing", "ein": "333333333",
                              "state_code": "TX", "service_regions": ["48002"]},
            course_code="HO-201",
            delivery_start="2026-03-02T00:00:00Z", delivery_end="2026-03-20T00:00:00Z",
            in_session_at="2026-03-10T00:00:00Z")

        set_clock("2027-03-01T00:00:00Z")
        cycle = create_grant_cycle(fiscal_year=2027, formula_pool_cents=1000000,
                                   competitive_pool_cents=0)
        app_old = create_grant_application(
            cycle, m_old, requested_formula_cents=100000,
            requested_competitive_cents=0, pledged_match_cents=50000)
        cycle = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        app_new = create_grant_application(
            cycle, m_new, requested_formula_cents=100000,
            requested_competitive_cents=0, pledged_match_cents=50000)
        submit_application(app_old, m_old)
        submit_application(app_new, m_new)
        advance_cycle_to_awarded(cycle)

        aw_old = award_application(app_old)
        aw_new = award_application(app_new)
        assert_grant_award(aw_old)
        assert_grant_award(aw_new)
        assert aw_old["formula_component_cents"] == aw_new["formula_component_cents"]
        assert aw_old["required_match_cents"] == 25000
        assert aw_new["required_match_cents"] == 10000
        assert aw_old["required_match_cents"] != aw_new["required_match_cents"]

    def test_match_requirement_rounds_up_to_whole_cents(self, api):
        """PRD §3.5: "match requirements are rounded up to whole cents" (§2.6)
        and §3.5: "ten percent when the member was chartered within the
        preceding twenty-four months (the provisional-period rate), otherwise
        twenty-five percent — and round the product up to whole cents."

        Design: Difficulty/dual_variant_calc/match_requirement_reduced_vs_standard
        """
        # Total 100001 cents at the reduced 10% rate -> ceil(10000.1) = 10001.
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Ceil Match Org", "ein": "222222223",
                              "state_code": "TX", "service_regions": ["48003"]},
            course_code="HO-202")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2049, formula_pool_cents=1000000,
            requested_formula_cents=100001, activate=False)
        assert award["formula_component_cents"] == 100001
        assert award["competitive_component_cents"] == 0
        # reduced rate 10%: ceil(0.10 * 100001) = 10001
        assert award["required_match_cents"] == 10001


class TestCompetitiveAllocationTiers:
    def test_competitive_allocation_tiered_rates(self, api):
        """PRD §3.4: "A score of at least 75 but below 90 funds 80 percent of
        the request, rounded down to whole cents."
        PRD §3.4: "Committing an award adds its formula component to the
        cycle's `formula_committed_cents` and its competitive component to the
        cycle's `competitive_committed_cents`."

        Design: Difficulty/combinatorial_formula/competitive_allocation_tiered_rates
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Tier Alpha", "ein": "444444441",
                              "state_code": "OH", "service_regions": ["39001"]},
            program_area="RENTAL", course_code="RE-101")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2028, formula_pool_cents=0,
            competitive_pool_cents=1000000, requested_formula_cents=0,
            requested_competitive_cents=50000, pledged_match_cents=20000,
            review_score=80, activate=False, program_area="RENTAL")
        assert award["competitive_component_cents"] == 40000
        assert award["formula_component_cents"] == 0
        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["competitive_committed_cents"] == 40000

    def test_competitive_full_tier_at_90(self, api):
        """PRD §3.4: "A score of at least 90 funds the full request."
        PRD §3.4: "The competitive component tiers on the application's
        `review_score`, applied marginally to the request rather than
        cumulatively across tiers."

        Design: Difficulty/combinatorial_formula/competitive_allocation_tiered_rates
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Tier Ninety", "ein": "444444442",
                              "state_code": "OH", "service_regions": ["39002"]},
            program_area="RENTAL", course_code="RE-102")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2050, formula_pool_cents=0,
            competitive_pool_cents=1000000, requested_formula_cents=0,
            requested_competitive_cents=50000, pledged_match_cents=20000,
            review_score=95, activate=False, program_area="RENTAL")
        assert award["competitive_component_cents"] == 50000


class TestFormulaWaterfall:
    def test_formula_allocation_rounding_waterfall(self, api):
        """PRD §3.4: "the member's formula allocation is the smaller of its raw
        share and its `requested_formula_cents`, and when the request falls
        below the raw share the excess redistributes to uncapped members
        through the same waterfall."
        PRD §3.4: "each member's share is rounded down to whole cents first,
        then the residual cents are distributed one at a time to members in
        order of decreasing weight"

        Design: Difficulty/combinatorial_formula/formula_allocation_rounding_waterfall
        """
        m_x, _c1, _cert1 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "X Housing", "ein": "555555551",
                              "state_code": "WA", "service_regions": ["53001"]},
            program_area="COMMUNITY_DEVELOPMENT", course_code="CD-101")
        m_y, _c2, _cert2 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Y Housing", "ein": "555555552",
                              "state_code": "WA", "service_regions": ["53002"]},
            program_area="COMMUNITY_DEVELOPMENT", course_code="CD-102")

        cycle = create_grant_cycle(fiscal_year=2029, formula_pool_cents=100000,
                                   competitive_pool_cents=0)
        app_x = create_grant_application(
            cycle, m_x, program_area="COMMUNITY_DEVELOPMENT",
            requested_formula_cents=30000, requested_competitive_cents=0,
            pledged_match_cents=10000)
        cycle = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        app_y = create_grant_application(
            cycle, m_y, program_area="COMMUNITY_DEVELOPMENT",
            requested_formula_cents=90000, requested_competitive_cents=0,
            pledged_match_cents=25000)
        submit_application(app_x, m_x)
        submit_application(app_y, m_y)
        advance_cycle_to_awarded(cycle)

        aw_x = award_application(app_x)
        aw_y = award_application(app_y)
        assert aw_x["formula_component_cents"] == 30000
        assert aw_y["formula_component_cents"] == 70000
        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["formula_committed_cents"] == 100000

    def test_formula_allocation_weights_households_served(self, api):
        """PRD §3.4: "Each eligible member's weight is one plus the households
        it served in the prior fiscal year (per the rollup in §3.8), multiplied
        by the regional need factor for the member's state — 1.0 by default.
        Each member's raw share is the formula pool multiplied by its weight
        divided by the total weight across the eligible set."

        Design: Difficulty/combinatorial_formula/formula_allocation_rounding_waterfall
        """
        # Two equal members (0 households each) split a 100001 pool evenly:
        # raw 50000.5 each -> floor 50000 each -> one residual cent to the
        # earliest-created application (tie-break by creation timestamp).
        m_a, _c1, _cert1 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Even A", "ein": "555555553",
                              "state_code": "WA", "service_regions": ["53003"]},
            program_area="COMMUNITY_DEVELOPMENT", course_code="CD-201")
        m_b, _c2, _cert2 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Even B", "ein": "555555554",
                              "state_code": "WA", "service_regions": ["53004"]},
            program_area="COMMUNITY_DEVELOPMENT", course_code="CD-202")

        cycle = create_grant_cycle(fiscal_year=2051, formula_pool_cents=100001,
                                   competitive_pool_cents=0)
        app_a = create_grant_application(
            cycle, m_a, program_area="COMMUNITY_DEVELOPMENT",
            requested_formula_cents=100000, requested_competitive_cents=0,
            pledged_match_cents=10000)
        cycle = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        app_b = create_grant_application(
            cycle, m_b, program_area="COMMUNITY_DEVELOPMENT",
            requested_formula_cents=100000, requested_competitive_cents=0,
            pledged_match_cents=10000)
        submit_application(app_a, m_a)
        submit_application(app_b, m_b)
        advance_cycle_to_awarded(cycle)

        aw_a = award_application(app_a)
        aw_b = award_application(app_b)
        assert aw_a["formula_component_cents"] == 50001  # residual cent to first-created
        assert aw_b["formula_component_cents"] == 50000
        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["formula_committed_cents"] == 100001


class TestCompetitiveScoreFloor:
    def _two_member_cycle(self, api, fiscal_year, ein_hi, ein_lo, region_hi, region_lo):
        m_hi, _c1, _cert1 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": f"Sixty {ein_hi}", "ein": ein_hi,
                              "state_code": "NV", "service_regions": [region_hi]},
            program_area="RENTAL", course_code=f"RE-{ein_hi[-3:]}")
        m_lo, _c2, _cert2 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": f"FiftyNine {ein_lo}", "ein": ein_lo,
                              "state_code": "NV", "service_regions": [region_lo]},
            program_area="RENTAL", course_code=f"RE-{ein_lo[-3:]}")
        cycle = create_grant_cycle(fiscal_year=fiscal_year, formula_pool_cents=0,
                                   competitive_pool_cents=100000)
        app_hi = create_grant_application(
            cycle, m_hi, program_area="RENTAL", requested_formula_cents=0,
            requested_competitive_cents=10000, pledged_match_cents=5000)
        cycle = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        app_lo = create_grant_application(
            cycle, m_lo, program_area="RENTAL", requested_formula_cents=0,
            requested_competitive_cents=10000, pledged_match_cents=5000)
        submit_application(app_hi, m_hi)
        submit_application(app_lo, m_lo)
        return cycle, app_hi, app_lo

    def test_competitive_score_floor_exactly_60(self, api):
        """PRD §3.4: "A score of at least 60 but below 75 funds 50 percent of
        the request, rounded down to whole cents. A score below 60 funds
        nothing: the competitive component is zero, and an application with a
        competitive request but a score below the competitive floor of 60
        cannot be awarded that component — attempting the award is rejected
        with `ERR_COMPETITIVE_SCORE_TOO_LOW`"

        Design: Difficulty/boundary_precision_check/competitive_score_floor_exactly_60
        """
        cycle, app60, app59 = self._two_member_cycle(
            api, 2034, "999999960", "999999959", "32001", "32002")
        api.lock_formula(cycle["id"], OFFICER)
        api.open_competitive_review(cycle["id"], OFFICER)
        api.score_application(app60["id"], {"review_score": 60},
                              make_grant_officer_headers("go-rev-60"))
        api.score_application(app59["id"], {"review_score": 59},
                              make_grant_officer_headers("go-rev-59"))
        api.finalize_cycle(cycle["id"], OFFICER)

        resp60 = api.award_application(app60["id"], make_grant_officer_headers("go-appr-60"))
        aw60 = validate_success(resp60, expected_status=201)
        assert aw60["competitive_component_cents"] == 5000

        resp59 = api.award_application(app59["id"], make_grant_officer_headers("go-appr-59"))
        validate_error(resp59, ApiErrorId.ERR_COMPETITIVE_SCORE_TOO_LOW)

    def test_competitive_score_59_denied_but_60_funded_pool_commitment(self, api):
        """PRD §3.4: "the cycle's `competitive_committed_cents` likewise may
        never exceed `competitive_pool_cents`, with overflow rejected as
        `ERR_POOL_EXHAUSTED`. Committing an award adds its formula component to
        the cycle's `formula_committed_cents` and its competitive component to
        the cycle's `competitive_committed_cents`."

        Design: Difficulty/boundary_precision_check/competitive_score_floor_exactly_60
        """
        cycle, app60, app59 = self._two_member_cycle(
            api, 2052, "999999961", "999999958", "32011", "32012")
        api.lock_formula(cycle["id"], OFFICER)
        api.open_competitive_review(cycle["id"], OFFICER)
        api.score_application(app60["id"], {"review_score": 60},
                              make_grant_officer_headers("go-rev-60"))
        api.score_application(app59["id"], {"review_score": 59},
                              make_grant_officer_headers("go-rev-59"))
        api.finalize_cycle(cycle["id"], OFFICER)

        resp59 = api.award_application(app59["id"], make_grant_officer_headers("go-appr-59"))
        validate_error(resp59, ApiErrorId.ERR_COMPETITIVE_SCORE_TOO_LOW)
        cycle_mid = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_mid["competitive_committed_cents"] == 0

        aw60 = award_application(app60)
        assert aw60["competitive_component_cents"] == 5000
        cycle_after = validate_success(api.get_grant_cycle(cycle["id"], OFFICER))
        assert cycle_after["competitive_committed_cents"] == 5000


class TestValidationPriorityOnAward:
    def test_state_vs_business_safety_on_application_award(self, api):
        """PRD §2.9: "then whether the target resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`); then
        segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`)"
        PRD §3.4: "Awarding happens per application, after the cycle is
        `AWARDED`"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_application_award
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Prio Housing", "ein": "888888881",
                              "state_code": "AZ", "service_regions": ["04001"]},
            course_code="HO-601")
        cycle = create_grant_cycle(fiscal_year=2038, formula_pool_cents=100000,
                                   competitive_pool_cents=100000)
        app = create_grant_application(
            cycle, member, requested_formula_cents=10000,
            requested_competitive_cents=10000, pledged_match_cents=5000)
        submit_application(app, member)
        resp = api.lock_formula(cycle["id"], OFFICER)
        validate_success(resp)
        # Score while UNDER_REVIEW, by the same officer who will try to award.
        api.score_application(app["id"], {"review_score": 80},
                              make_grant_officer_headers("go-reviewer-1"))

        resp = api.award_application(app["id"], make_grant_officer_headers("go-reviewer-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        app_after = validate_success(api.get_grant_application(app["id"], OFFICER))
        assert app_after["application_status"] == "UNDER_REVIEW"

    def test_segregation_of_duties_blocks_same_officer_award_when_cycle_awarded(self, api):
        """PRD §3.4: "the awarding officer must not be the operator who
        recorded the application's review score (`ERR_SEGREGATION_OF_DUTIES`)"
        PRD §2.1: "the operator who awards a grant application must differ from
        the one who recorded its competitive review score."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_application_award
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Prio Two Housing", "ein": "888888883",
                              "state_code": "AZ", "service_regions": ["04003"]},
            course_code="HO-602")
        cycle = create_grant_cycle(fiscal_year=2053, formula_pool_cents=100000,
                                   competitive_pool_cents=100000)
        app = create_grant_application(
            cycle, member, requested_formula_cents=10000,
            requested_competitive_cents=10000, pledged_match_cents=5000)
        submit_application(app, member)
        api.lock_formula(cycle["id"], OFFICER)
        api.open_competitive_review(cycle["id"], OFFICER)
        api.score_application(app["id"], {"review_score": 80},
                              make_grant_officer_headers("go-same-1"))
        api.finalize_cycle(cycle["id"], OFFICER)

        resp = api.award_application(app["id"], make_grant_officer_headers("go-same-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        app_after = validate_success(api.get_grant_application(app["id"], OFFICER))
        assert app_after["application_status"] == "UNDER_REVIEW"


class TestMatchAndActivation:
    def test_match_verify_then_activate_happy_path(self, api):
        """PRD §3.5: "Activation moves the award from `DISBURSING` to `ACTIVE`
        and is permitted only once `verified_match_cents` is at least
        `required_match_cents`; activating short of the requirement is rejected
        with `ERR_MATCH_NOT_MET`."
        PRD §3.5: "each verification by a `GrantOfficer` adds the supplied
        `additional_match_cents` to `verified_match_cents` and increments the
        award's `version` by one."

        Design: Corner/endpoints/match_verify_then_activate_happy_path
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Match Org", "ein": "500000001",
                              "state_code": "CA", "service_regions": ["06048"]},
            course_code="HO-411")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2042, formula_pool_cents=100000,
            requested_formula_cents=50000, activate=False)
        assert award["required_match_cents"] == 5000

        resp = api.activate_award(award["id"], {"expected_award_version": award["version"]}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_MATCH_NOT_MET)

        resp = api.verify_match(award["id"], {"additional_match_cents": 5000}, OFFICER)
        award = validate_success(resp)
        assert award["verified_match_cents"] == 5000

        resp = api.activate_award(award["id"], {"expected_award_version": award["version"]}, OFFICER)
        award = validate_success(resp)
        assert award["award_status"] == "ACTIVE"

    def test_verify_match_grows_monotonically(self, api):
        """PRD §3.5: "Match verification grows monotonically: each verification
        by a `GrantOfficer` adds the supplied `additional_match_cents` to
        `verified_match_cents` and increments the award's `version` by one."

        Design: Corner/endpoints/match_verify_then_activate_happy_path
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Match Two Org", "ein": "500000003",
                              "state_code": "CA", "service_regions": ["06062"]},
            course_code="HO-412")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2054, formula_pool_cents=100000,
            requested_formula_cents=50000, activate=False)
        v0 = award["version"]
        resp = api.verify_match(award["id"], {"additional_match_cents": 2000}, OFFICER)
        award = validate_success(resp)
        assert award["verified_match_cents"] == 2000
        assert award["version"] == v0 + 1
        resp = api.verify_match(award["id"], {"additional_match_cents": 1500}, OFFICER)
        award = validate_success(resp)
        assert award["verified_match_cents"] == 3500
        assert award["version"] == v0 + 2


class TestDerivedFieldReconciliation:
    def test_derived_field_reconciliation_on_disbursement_post(self, api):
        """PRD §3.5: "Posting moves the tranche to `POSTED` and ledger-syncs
        the award: `disbursed_cents` grows by exactly the tranche amount. A
        pending tranche may be voided instead, moving it to `VOIDED`."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_disbursement_post
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Recon2 Org", "ein": "800000005",
                              "state_code": "CA", "service_regions": ["06059"]},
            course_code="HO-813")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2048, formula_pool_cents=100000,
            requested_formula_cents=40000, verify_match_cents=4000)

        d1 = post_disbursement(award["id"], 10000)
        assert d1["disbursement_status"] == "POSTED"
        resp = api.create_disbursement({"award_id": award["id"], "amount_cents": 5000}, OFFICER)
        d2 = validate_success(resp, expected_status=201)
        resp = api.void_disbursement(d2["id"], OFFICER)
        d2 = validate_success(resp)
        assert d2["disbursement_status"] == "VOIDED"

        award_after = validate_success(api.get_grant_award(award["id"], OFFICER))
        assert award_after["disbursed_cents"] == 10000

    def test_post_over_award_total_rejected_pool_exhausted(self, api):
        """PRD §3.5: "Posting a tranche requires the award to be `DISBURSING`
        or `ACTIVE` and requires that the award's already-disbursed total plus
        this tranche not exceed the sum of the award's formula and competitive
        components; an over-posting is rejected with `ERR_POOL_EXHAUSTED`."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_disbursement_post
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Over Post Org", "ein": "800000006",
                              "state_code": "CA", "service_regions": ["06063"]},
            course_code="HO-814")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2055, formula_pool_cents=100000,
            requested_formula_cents=40000, verify_match_cents=4000)

        resp = api.create_disbursement({"award_id": award["id"], "amount_cents": 40000}, OFFICER)
        d1 = validate_success(resp, expected_status=201)
        resp = api.create_disbursement({"award_id": award["id"], "amount_cents": 1}, OFFICER)
        d2 = validate_success(resp, expected_status=201)
        api.post_disbursement(d1["id"], OFFICER)
        resp = api.post_disbursement(d2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_POOL_EXHAUSTED)
