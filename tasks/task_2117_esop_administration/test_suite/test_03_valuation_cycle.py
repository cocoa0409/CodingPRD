"""The independent appraisal: pricing, the challenge cycle, approval and coverage."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_valuation,
    close_year,
    create_loan,
    create_plan,
    create_valuation_payload,
    get_plan,
    get_valuation,
    make_appraiser_headers,
    make_trustee_headers,
    resubmit_valuation_payload,
    set_clock,
    submit_valuation,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestSharePriceDetermination:
    def test_levered_plan_takes_capped_control_premium_before_discount(self, api):
        """PRD 3.3: "Second, the trust's ownership is measured and the control premium branch
        is decided. `ownership_bps_at_valuation` is the plan's `total_plan_shares` multiplied
        by 10000, divided by its `total_shares_outstanding`, floored to a whole basis point.
        When that measured ownership reaches 5000 basis points — that is, when the trust holds
        at least half of every outstanding share — the branch is taken: an uncapped premium is
        computed as the equity value multiplied by `control_premium_bps` divided by 10000,
        rounded half up to whole cents, and `control_premium_applied_cents` is the smaller of
        that uncapped premium and the hard ceiling of 1,000,000,000 cents, which is ten
        million dollars."
        PRD 3.3: "If the trust holds 600,000 of those shares, measured ownership is 6000 basis
        points and the premium branch is taken: the uncapped premium of 1,425,000,000 cents is
        capped to 1,000,000,000, the controlled value is 10,500,000,000, the marketable value
        is 7,875,000,000, and the price is 7875 cents."

        Design: Difficulty/combinatorial_formula/valuation_price_capped_premium_before_discount_mode_a
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Ironwood Levered")
        create_loan(plan["id"])
        plan = get_plan(plan["id"])

        payload = create_valuation_payload(plan["id"], plan["version"])
        valuation = validate_success(api.create_valuation(payload, APPRAISER), 201)

        assert_valuation(valuation)
        assert valuation["equity_value_cents"] == 9_500_000_000
        assert valuation["ownership_bps_at_valuation"] == 6000
        assert valuation["control_premium_applied_cents"] == 1_000_000_000, (
            "the uncapped 1,425,000,000-cent premium is capped to 1,000,000,000"
        )
        assert valuation["share_price_cents"] == 7875
        assert valuation["status"] == "SUBMITTED"

    def test_unlevered_plan_skips_premium_and_pins_discount_ordering(self, api):
        """PRD 3.3: "When measured ownership falls short of 5000 basis points, the branch is
        not taken and `control_premium_applied_cents` is 0."
        PRD 3.3: "Because the premium is capped, the two possible orderings are not
        interchangeable and do not agree. On the worked figures below, applying the premium
        first and the discount second yields a price of 7875 cents, while applying the
        discount first and the premium second would yield 8125 — the second reading is wrong."
        PRD 3.3: "If instead the trust holds no shares at all, measured ownership is 0 basis
        points, the premium is 0, the marketable value is 7,125,000,000, and the price is 7125
        cents."

        Design: Difficulty/combinatorial_formula/valuation_price_capped_premium_before_discount_mode_a
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        levered = create_plan(plan_name="Ironwood Levered")
        create_loan(levered["id"])
        levered = get_plan(levered["id"])
        unlevered = create_plan(plan_name="Ironwood Unlevered")

        levered_valuation = submit_valuation(levered["id"], levered["version"])
        unlevered_valuation = submit_valuation(unlevered["id"], unlevered["version"])

        assert unlevered_valuation["ownership_bps_at_valuation"] == 0
        assert unlevered_valuation["control_premium_applied_cents"] == 0
        assert unlevered_valuation["share_price_cents"] == 7125
        assert unlevered_valuation["equity_value_cents"] == 9_500_000_000
        assert levered_valuation["share_price_cents"] == 7875
        assert levered_valuation["share_price_cents"] != 8125, (
            "premium-then-discount is the pinned order; discount-then-premium would give 8125"
        )


class TestChallengeAndRevisionCycle:
    def test_challenge_resubmit_cycle_reprices_and_counts_rounds(self, api):
        """PRD 3.3: "A `Trustee` who is unconvinced challenges the appraisal, which drives it
        from `SUBMITTED` to `CHALLENGED`, increases `challenge_round` by 1, and records the
        trustee's `challenge_note` on the appraisal."
        PRD 3.3: "Revision overwrites all five valuation inputs from the request, and the
        price calculation re-runs from the top, rewriting `share_price_cents`,
        `equity_value_cents`, `control_premium_applied_cents` and `ownership_bps_at_valuation`
        against the plan's counters as they stand at the moment of the revision rather than as
        they stood at the original submission."

        Design: Difficulty/non_linear_state_machine/valuation_challenge_resubmit_cycle_reprices
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Cycle Plan", sponsor_name="Northgate Tooling Inc.")
        plan = close_year(plan["id"])
        valuation = submit_valuation(plan["id"], plan["version"])
        assert valuation["share_price_cents"] == 7125

        challenged = validate_success(api.challenge_valuation(
            valuation["id"], {"challenge_note": "Discount rate looks aggressive."}, TRUSTEE))
        assert challenged["status"] == "CHALLENGED"
        assert challenged["challenge_round"] == 1
        assert challenged["challenge_note"] == "Discount rate looks aggressive."

        revised = validate_success(api.resubmit_valuation(
            valuation["id"], resubmit_valuation_payload(marketability_discount_bps=3000),
            APPRAISER))
        assert revised["status"] == "SUBMITTED", "revision drives CHALLENGED back to SUBMITTED"
        assert revised["share_price_cents"] == 6650, "a 3000 bps discount reprices to 6650"

        validate_success(api.challenge_valuation(
            valuation["id"], {"challenge_note": "Still not reconciled to the peer set."},
            TRUSTEE))
        final = validate_success(api.resubmit_valuation(
            valuation["id"],
            resubmit_valuation_payload(enterprise_value_cents=11_000_000_000), APPRAISER))

        assert final["status"] == "SUBMITTED"
        assert final["challenge_round"] == 2
        assert final["equity_value_cents"] == 8_500_000_000
        assert final["share_price_cents"] == 6375
        assert final["challenge_note"] == "Still not reconciled to the peer set."
        assert get_plan(plan["id"])["open_valuation_count"] == 1, (
            "the appraisal never left the open set across the cycle"
        )

    def test_third_challenge_exhausts_the_round_budget(self, api):
        """PRD 3.3: "Challenges are bounded: an appraisal may be challenged only while its
        `challenge_round` is still below 2, so at most two challenges are possible, and an
        attempt to challenge a third time is refused with `ERR_CHALLENGE_ROUNDS_EXHAUSTED`."
        PRD 3.3: "A revision may itself be challenged again, so a single appraisal may
        traverse `SUBMITTED → CHALLENGED → SUBMITTED` at most twice before the challenge
        budget is exhausted."

        Design: Difficulty/non_linear_state_machine/valuation_challenge_resubmit_cycle_reprices
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Cycle Plan", sponsor_name="Northgate Tooling Inc.")
        plan = close_year(plan["id"])
        valuation = submit_valuation(plan["id"], plan["version"])

        for note in ("Discount rate looks aggressive.", "Still not reconciled to the peer set."):
            validate_success(api.challenge_valuation(valuation["id"], {"challenge_note": note},
                                                     TRUSTEE))
            validate_success(api.resubmit_valuation(
                valuation["id"], resubmit_valuation_payload(), APPRAISER))

        validate_error(
            api.challenge_valuation(valuation["id"], {"challenge_note": "Third time."}, TRUSTEE),
            ApiErrorId.ERR_CHALLENGE_ROUNDS_EXHAUSTED,
        )
        after = get_valuation(valuation["id"])
        assert after["status"] == "SUBMITTED", "the refused challenge leaves the appraisal open"
        assert after["challenge_round"] == 2, "the round counter stops at 2"


class TestApprovalGate:
    def test_approve_while_plan_open_is_refused(self, api):
        """PRD 3.3: "It requires the appraisal to be `SUBMITTED`, the plan to be in
        `VALUATION_PENDING` posture, and the appraisal's `plan_year` to equal the plan's
        `plan_year`."
        PRD 2.9: "Operations that require a specific posture are refused with
        `ERR_PLAN_STATE_INVALID` and HTTP 409 when the plan is in a different one."

        Design: Difficulty/cross_entity_state_dependency/valuation_approve_gated_by_plan_status_valuation_to_plan
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Gate Plan B", sponsor_name="Northgate Tooling Inc.")
        valuation = submit_valuation(plan["id"], plan["version"])

        validate_error(api.approve_valuation(valuation["id"], TRUSTEE),
                       ApiErrorId.ERR_PLAN_STATE_INVALID)

        after = get_valuation(valuation["id"])
        assert after["status"] == "SUBMITTED", "the appraisal row is untouched by the refusal"
        assert after["approved_by_user_id"] is None
        assert get_plan(plan["id"])["current_share_price_cents"] == 0, (
            "the plan acquires no price while the approval is refused"
        )

    def test_approve_succeeds_once_the_year_is_closed(self, api):
        """PRD 3.3: "On success the appraisal moves `SUBMITTED → APPROVED`,
        `approved_by_user_id` is set from the approving trustee's `X-User-ID`, and the plan's
        `current_share_price_cents` is set to the appraisal's `share_price_cents`."
        PRD 3.3: "The plan's `open_valuation_count` decreases by the number of appraisals that
        just left the open set, counting the approved one itself along with every sibling
        superseded by the approval, and the plan's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/valuation_approve_gated_by_plan_status_valuation_to_plan
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Gate Plan B", sponsor_name="Northgate Tooling Inc.")
        valuation = submit_valuation(plan["id"], plan["version"])
        validate_error(api.approve_valuation(valuation["id"], TRUSTEE),
                       ApiErrorId.ERR_PLAN_STATE_INVALID)

        closed = close_year(plan["id"])
        assert closed["plan_status"] == "VALUATION_PENDING"

        approved = validate_success(api.approve_valuation(valuation["id"], TRUSTEE))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "trustee-01"

        after = get_plan(plan["id"])
        assert after["current_share_price_cents"] == 7125
        assert after["open_valuation_count"] == 0, "the approved appraisal leaves the open set"


class TestCoverageIntervals:
    def test_overlapping_coverage_interval_is_refused(self, api):
        """PRD 3.3: "Treating each interval as running from its `effective_from_date`
        inclusive to its `effective_to_date` exclusive, a new appraisal's interval must not
        intersect the interval of any other appraisal of the same plan whose status is
        `SUBMITTED`, `CHALLENGED` or `APPROVED`; an intersection is refused with
        `ERR_VALUATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/valuation_coverage_half_open_overlap_on_plan
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Interval Plan", sponsor_name="Northgate Tooling Inc.")
        base = submit_valuation(plan["id"], plan["version"])
        version = get_plan(plan["id"])["version"]

        overlapping = create_valuation_payload(
            plan["id"], version, enterprise_value_cents=11_000_000_000,
            effective_from_date="2026-06-01", effective_to_date="2026-12-01",
        )
        validate_error(api.create_valuation(overlapping, APPRAISER),
                       ApiErrorId.ERR_VALUATION_PERIOD_OVERLAP)

        assert get_plan(plan["id"])["open_valuation_count"] == 1, (
            "the refused submission adds nothing to the open set"
        )
        assert get_valuation(base["id"])["status"] == "SUBMITTED", (
            "the incumbent appraisal is unaffected by the refused attempt"
        )

    def test_adjacent_coverage_interval_is_admitted(self, api):
        """PRD 3.3: "Intervals that merely touch are legal — one ending exactly on the day
        another begins does not overlap it."
        PRD 3.3: "The appraisal is stored `SUBMITTED`, the submitting appraiser's `X-User-ID`
        is stamped onto `appraiser_user_id`, the plan's `open_valuation_count` increases by 1,
        and the plan's `version` increments by 1."

        Design: Difficulty/resource_temporal_overlap/valuation_coverage_half_open_overlap_on_plan
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Interval Plan", sponsor_name="Northgate Tooling Inc.")
        base = submit_valuation(plan["id"], plan["version"])
        version = get_plan(plan["id"])["version"]

        adjacent = create_valuation_payload(
            plan["id"], version, plan_year=2027, enterprise_value_cents=11_000_000_000,
            effective_from_date="2027-01-01", effective_to_date="2028-01-01",
        )
        created = validate_success(api.create_valuation(adjacent, APPRAISER), 201)

        assert created["status"] == "SUBMITTED"
        assert created["effective_from_date"] == "2027-01-01"
        assert created["appraiser_user_id"] == "appraiser-01"
        assert get_valuation(base["id"])["effective_to_date"] == "2027-01-01", (
            "the incumbent's exclusive end is the new appraisal's inclusive start"
        )
        assert get_plan(plan["id"])["open_valuation_count"] == 2


class TestValuationConcurrencyAndDuties:
    def test_stale_expected_plan_version_on_valuation_create_returns_412(self, api):
        """PRD 2.7: "Submitting a valuation — the `POST /valuations` request — requires the
        non-optional input field `expected_plan_version`, carrying the client's last observed
        `version` of the target `EsopPlan`. If that value does not equal the plan's current
        `version`, the submission is rejected with `ERR_STALE_PLAN_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_plan_version_on_valuation_create_returns_412
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="OCC Valuation", sponsor_name="Corner Corp",
                           distribution_policy="LUMP_SUM")
        closed = close_year(plan["id"])
        first = submit_valuation(plan["id"], closed["version"])

        stale = create_valuation_payload(
            plan["id"], closed["version"], plan_year=2027,
            enterprise_value_cents=11_000_000_000,
            effective_from_date="2027-01-01", effective_to_date="2028-01-01",
        )
        validate_error(api.create_valuation(stale, APPRAISER),
                       ApiErrorId.ERR_STALE_PLAN_VERSION)
        after_refusal = get_plan(plan["id"])
        assert after_refusal["open_valuation_count"] == 1, (
            "the refused submission creates no appraisal"
        )

        stale["expected_plan_version"] = after_refusal["version"]
        retried = validate_success(api.create_valuation(stale, APPRAISER), 201)
        assert retried["status"] == "SUBMITTED"

        final_plan = get_plan(plan["id"])
        assert final_plan["open_valuation_count"] == 2
        assert final_plan["version"] == after_refusal["version"] + 1, (
            "the plan's version advances by exactly 1 on the accepted submission"
        )
        assert get_valuation(first["id"])["status"] == "SUBMITTED"

    def test_appraiser_cannot_approve_any_valuation(self, api):
        """PRD 2.1: "When the headers are well formed but the named role does not appear in
        the authorized-role list for the endpoint being called, the request is refused with
        `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD 2.1: "The `Appraiser` is the independent valuation professional who produces
        appraisals and revises them when they are challenged, but who is barred from approving
        anything."
        PRD 2.12: "A caller who is not authorized for an endpoint learns that before any
        resource is looked up, so an unauthorized caller cannot use 404 versus 403 to probe
        which identifiers exist."

        Design: Corner/rbac/appraiser_cannot_approve_own_or_any_valuation
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="RBAC Plan", sponsor_name="Corner Corp",
                           distribution_policy="LUMP_SUM")
        closed = close_year(plan["id"])
        valuation = submit_valuation(plan["id"], closed["version"])

        validate_error(api.approve_valuation(valuation["id"], APPRAISER),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)

        after = get_valuation(valuation["id"])
        assert after["status"] == "SUBMITTED"
        assert after["approved_by_user_id"] is None
        assert get_plan(plan["id"])["current_share_price_cents"] == 0

    def test_trustee_cannot_approve_valuation_they_submitted(self, api):
        """PRD 2.8: "A trustee whose `X-User-ID` equals the `appraiser_user_id` recorded on a
        valuation may not approve that valuation."
        PRD 2.8: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403."
        PRD 3.3: "The approving trustee must not be the appraiser who submitted it, and no
        other appraisal of the same plan and the same plan year may already be `APPROVED` — a
        second approval for a plan year that already has one is refused with
        `ERR_NO_APPROVED_VALUATION`."

        Design: Corner/rbac/trustee_cannot_approve_valuation_they_submitted
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="SoD Plan", sponsor_name="Corner Corp",
                           distribution_policy="LUMP_SUM")
        closed = close_year(plan["id"])
        valuation = submit_valuation(plan["id"], closed["version"],
                                     headers=make_appraiser_headers("dual-hat-07"))
        assert valuation["appraiser_user_id"] == "dual-hat-07"

        validate_error(api.approve_valuation(valuation["id"], make_trustee_headers("dual-hat-07")),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(api.approve_valuation(valuation["id"], TRUSTEE))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "trustee-01"
        assert get_plan(plan["id"])["current_share_price_cents"] == 7125
