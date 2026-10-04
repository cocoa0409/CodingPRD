"""Market conduct data calls: exam priority scoring, the two-pass cost-share
assessment, participation gates, and per-insurer response uniqueness."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_allocation_invariant,
    assert_market_conduct_response,
    assert_money_equals,
    factories,
    fixtures,
    make_insurer_user_headers,
    make_state_regulator_headers,
    validate_error,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]


class TestMarketConduct:
    def test_exam_priority_tiered_min_formula(self, api):
        """PRD §3.7: "The complaint component takes the response's complaint rate — one hundred million times `complaint_count` divided by `direct_premium_cents` — caps that rate at 50, and multiplies the capped rate by a weight of 0.5."
        PRD §3.7: "otherwise a ratio below 0.7000 contributes 50 points, below 1.0000 contributes 35, below 1.5000 contributes 20, below 2.0000 contributes 10, and a ratio of at least 2.0000 contributes nothing."
        PRD §3.7: "a share of at least 25 percent contributes 20 points, a share of at least 10 percent but under 25 contributes 10, and anything smaller contributes nothing. The score is the sum of the three components, capped at 100, then rounded half-up to two decimal places."
        PRD §3.7: "sets its `escalation_flag` — true when the responding insurer is `UNDER_SUPERVISION` at that moment and false otherwise"

        Design: Difficulty/combinatorial_formula/exam_priority_tiered_min_formula
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90010", state["code"])
        fixtures.create_active_standard(api)
        filing = fixtures.create_filing(
            api, insurer, reported_surplus_cents=1200000,
            asset_risk_cents=1000000, underwriting_risk_cents=1000000,
            other_risk_cents=1000000,
        )
        fixtures.submit_filing(api, filing)
        fixtures.validate_filing(api, filing["id"])
        insurer = fixtures.read_insurer(api, insurer["id"])
        assert insurer["status"] == "UNDER_SUPERVISION", (
            "ratio 0.6928 lands in MANDATORY_CONTROL territory"
        )
        call = fixtures.create_call(
            api, state, call_code="MC-100", topic="claims handling",
            total_cost_cents=100000,
        )
        resp = api.create_response(
            call["id"],
            factories.response_payload(200000000, 40),
            make_insurer_user_headers(insurer["id"]),
        )
        data = validate_success(resp, 201)
        assert_market_conduct_response(data)
        # rate 20.0 -> capped component 10.0; ratio tier 50; sole share -> 20.
        assert_money_equals(data["exam_priority_score"], 80.0, "exam_priority_score")
        assert data["escalation_flag"] is True

    def test_cost_share_two_pass_renormalization(self, api):
        """PRD §3.7: "In pass one, each response's share is its premium divided by the premium sum over all responses; any response whose pass-one share falls below 5 percent is excluded, marked `cost_share_excluded` true, and allocated zero cents"
        PRD §3.7: "In pass two, each surviving response's share is recomputed against the premium sum of the survivors only, and its raw allocation is the call's `total_cost_cents` multiplied by that share."
        PRD §3.7: "The invariant on completion is exact: the allocated cents across all responses sum to `total_cost_cents`."

        Design: Difficulty/combinatorial_formula/cost_share_two_pass_renormalization
        """
        bundle = fixtures.setup_call_with_responses(
            api, [950000000, 40000000, 10000000],
            call_code="MC-200", total_cost_cents=1000000, naic_start=90020,
        )
        fixtures.close_call(api, bundle.call["id"], bundle.state)
        responses = fixtures.list_responses(api, bundle.call["id"])
        by_code = {r["insurer_naic_code"]: r for r in responses}
        # Pass-1 shares 0.95 / 0.04 / 0.01: only the largest survives the floor.
        assert by_code["90020"]["cost_share_excluded"] is False
        assert by_code["90020"]["allocated_cost_cents"] == 1000000
        assert by_code["90021"]["cost_share_excluded"] is True
        assert by_code["90021"]["allocated_cost_cents"] == 0
        assert by_code["90022"]["cost_share_excluded"] is True
        assert by_code["90022"]["allocated_cost_cents"] == 0
        assert_allocation_invariant(responses, 1000000)

    def test_cost_share_largest_remainder_tiebreak(self, api):
        """PRD §3.7: "Each survivor's `allocated_cost_cents` is the raw allocation rounded down to a whole cent; the leftover cents — the difference between `total_cost_cents` and the sum of the floored allocations — are then distributed one cent at a time to the survivors in descending order of their raw allocations' fractional parts, breaking ties by `insurer_naic_code` ascending, so the insurer codes decide ties deterministically and resource ids never do."

        Design: Corner/calculations/cost_share_largest_remainder_tiebreak
        """
        bundle = fixtures.setup_call_with_responses(
            api, [100000000, 100000000, 100000000],
            call_code="MC-820", total_cost_cents=100003, naic_start=90060,
        )
        fixtures.close_call(api, bundle.call["id"], bundle.state)
        responses = fixtures.list_responses(api, bundle.call["id"])
        by_code = {r["insurer_naic_code"]: r for r in responses}
        # Floors give 33334 x 3 == 100002; the 1-cent remainder breaks the
        # three-way fractional tie by ascending insurer code.
        assert by_code["90060"]["allocated_cost_cents"] == 33335
        assert by_code["90061"]["allocated_cost_cents"] == 33334
        assert by_code["90062"]["allocated_cost_cents"] == 33334
        assert_allocation_invariant(responses, 100003)

    def test_exam_priority_neutral_when_no_filing(self, api):
        """PRD §3.7: "The capital component reads the insurer's `latest_rbc_ratio`: when the insurer has no validated filing and the ratio is null, it contributes a neutral 25 points"
        PRD §3.7: "a share of at least 25 percent contributes 20 points"
        PRD §3.7: "true when the responding insurer is `UNDER_SUPERVISION` at that moment and false otherwise"

        Design: Corner/calculations/exam_priority_neutral_when_no_filing
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90085", state["code"])
        call = fixtures.create_call(api, state, call_code="MC-821")
        resp = api.create_response(
            call["id"],
            factories.response_payload(100000000, 0),
            make_insurer_user_headers(insurer["id"]),
        )
        data = validate_success(resp, 201)
        # 0 complaint points + 25 neutral + 20 sole-responder share points.
        assert_money_equals(data["exam_priority_score"], 45.0, "exam_priority_score")
        assert data["escalation_flag"] is False

    def test_call_close_and_respond_state_errors(self, api):
        """PRD §3.7: "Closing the call requires the acting regulator's State `code` to equal the call's `lead_state_code` (`ERR_FORBIDDEN`), the call to be `OPEN` (`ERR_CALL_NOT_OPEN`, 409), and at least one response to exist (`ERR_CALL_NO_RESPONSES`, 422)."
        PRD §3.7: "Responding is `InsurerUser` work against an `OPEN` call — otherwise `ERR_CALL_NOT_OPEN` (409), a gate that applies identically to closing — and each insurer may respond at most once per call (`ERR_DUPLICATE_RESPONSE`, 409), with the state gate evaluated before the duplicate check."

        Design: Corner/state_machines/call_close_and_respond_state_errors
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90082", state["code"])
        call = fixtures.create_call(api, state, call_code="MC-813")
        resp = api.close_call(
            call["id"], make_state_regulator_headers(state["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CALL_NO_RESPONSES)
        fixtures.add_response(api, call["id"], insurer, 5000000, 1)
        closed = fixtures.close_call(api, call["id"], state)
        assert closed["status"] == "CLOSED"
        resp = api.create_response(
            call["id"],
            factories.response_payload(5000000, 1),
            make_insurer_user_headers(insurer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CALL_NOT_OPEN)

    def test_call_cost_below_minimum_rejected(self, api):
        """PRD §3.7: "a `total_cost_cents` examination cost pool that must be at least 100000 cents (`ERR_CALL_COST_BELOW_MINIMUM`, 422)"

        Design: Corner/validations/call_cost_below_minimum_rejected
        """
        state = fixtures.create_state(api, code="CA")
        resp = api.create_market_conduct_call(
            factories.call_payload(call_code="MC-823", total_cost_cents=99999),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CALL_COST_BELOW_MINIMUM)

    def test_duplicate_response_rejected(self, api):
        """PRD §3.7: "each insurer may respond at most once per call (`ERR_DUPLICATE_RESPONSE`, 409)"

        Design: Corner/validations/duplicate_response_rejected
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90087", state["code"])
        call = fixtures.create_call(api, state, call_code="MC-822")
        fixtures.add_response(api, call["id"], insurer, 1000000, 0)
        resp = api.create_response(
            call["id"],
            factories.response_payload(2000000, 1),
            make_insurer_user_headers(insurer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESPONSE)
