"""Launch-decision adoption thresholds, severity overrides, and proposal OCC
(PRD §3.1, §3.2, §2.7).

The statutory score alone gates adoption; the risk-adjusted variant never
gates. The adoption thresholds are inclusive at 60 (FULL_GO_TEAM) and 20
(LIMITED), and every proposal is optimistic-concurrency checked against the
accident case's version.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_launch_decision,
    adopt_launch_decision_payload,
    assert_case_scores,
    create_case,
    find_decision,
    get_case,
    get_investigation_for_case,
    get_proposed_decision,
    propose_launch_decision,
    propose_launch_decision_payload,
    set_clock,
    validate_error,
    validate_success,
)

MD_PROPOSER = TEST_USERS["md_proposer_headers"]
MD_ADOPTER = TEST_USERS["md_adopter_headers"]

HAZMAT_58 = dict(
    report_number="NTSB-2026-0101",
    category="HAZMAT",
    occurred_at="2026-08-30T04:12:00Z",
    location_state="LA",
    fatalities_count=2,
    injuries_count=3,
    damage_estimate_cents=5000000,
    is_public_transport=False,
)


class TestAdoptionThresholds:
    def test_risk_adjusted_score_never_gates_adoption(self, api):
        """PRD §3.1: "It is observability-only: it never gates any adoption
        decision." PRD §3.2: "adopting `FULL_GO_TEAM` requires the case's
        `statutory_score` to be at least 60 and adopting `LIMITED` requires at
        least 20, while `DECLINED` carries no threshold — a shortfall is
        `ERR_LAUNCH_THRESHOLD_NOT_MET`".

        Design: Difficulty/dual_variant_calc/dual_variant_launch_scores_diverge_on_hazmat_case
        """
        set_clock()
        case = create_case(**HAZMAT_58)
        # statutory 58 / risk-adjusted 73.8: the risk score clears 60 but only
        # the statutory variant may gate.
        assert case["statutory_score"] == 58
        assert case["risk_adjusted_score"] == pytest.approx(73.8, abs=1e-6)

        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        full_decision = get_proposed_decision(case)
        resp = api.adopt_launch_decision(
            case["id"], full_decision["decision_id"], {"iic_user_id": "iic-1"}, MD_ADOPTER
        )
        validate_error(resp, ApiErrorId.ERR_LAUNCH_THRESHOLD_NOT_MET)

        case = get_case(case["id"])
        assert case["status"] == "SCREENING"
        assert find_decision(case, full_decision["decision_id"])["status"] == "PROPOSED"

        # The same case adopts cleanly as LIMITED (58 >= 20).
        case = propose_launch_decision(case, mode="LIMITED")
        limited_decision = get_proposed_decision(case)
        case = adopt_launch_decision(
            case["id"], limited_decision["decision_id"], iic_user_id=None
        )
        assert case["status"] == "LIMITED_TRACK"

    def test_clamped_score_of_one_hundred_still_adopts_full_go_team(self, api):
        """PRD §3.2: "Adopting `FULL_GO_TEAM` moves the case to `LAUNCHED` and
        creates its investigation — at most one investigation ever exists per
        accident case — with `accident_case_id` pointing back to the case, the
        adopted `iic_user_id`, phase `GO_TEAM_ASSEMBLED`, `docket_status`
        `SEALED`, and `docket_completeness_pct` at zero."

        Design: Difficulty/combinatorial_formula/combinatorial_statutory_score_clamp_and_modal_bump
        """
        set_clock()
        case = create_case(
            report_number="NTSB-2026-0102",
            category="AVIATION",
            occurred_at="2026-08-29T19:40:00Z",
            location_state="AK",
            fatalities_count=5,
            injuries_count=15,
            damage_estimate_cents=10000000,
            is_public_transport=True,
        )
        assert case["statutory_score"] == 100  # 120 unclamped
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        decision = get_proposed_decision(case)
        case = adopt_launch_decision(case["id"], decision["decision_id"])
        assert case["status"] == "LAUNCHED"

        investigation = get_investigation_for_case(case["id"])
        assert investigation["accident_case_id"] == case["id"]
        assert investigation["iic_user_id"] == "iic-1"
        assert investigation["phase"] == "GO_TEAM_ASSEMBLED"
        assert investigation["docket_status"] == "SEALED"
        assert investigation["docket_completeness_pct"] == 0

    def test_launch_threshold_sixty_is_inclusive(self, api):
        """PRD §3.1: "From the statutory score alone, the server derives
        `suggested_mode`: `FULL_GO_TEAM` when the score is at least 60,
        `LIMITED` when it is at least 20 but below 60, and `DECLINED` below
        20." PRD §3.2: "adopting `FULL_GO_TEAM` requires the case's
        `statutory_score` to be at least 60 and adopting `LIMITED` requires at
        least 20, while `DECLINED` carries no threshold — a shortfall is
        `ERR_LAUNCH_THRESHOLD_NOT_MET`".

        Design: Difficulty/boundary_precision_check/boundary_launch_threshold_sixty_inclusive
        """
        set_clock()
        # 40 (one fatality) + 0 + 0 + 20 (public conveyance) = exactly 60.
        case = create_case(
            report_number="NTSB-2026-0105",
            category="HIGHWAY",
            occurred_at="2026-08-31T06:00:00Z",
            location_state="VA",
            fatalities_count=1,
            injuries_count=0,
            damage_estimate_cents=0,
            is_public_transport=True,
        )
        assert case["statutory_score"] == 60
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        decision = get_proposed_decision(case)
        case = adopt_launch_decision(case["id"], decision["decision_id"])
        assert case["status"] == "LAUNCHED", "60 >= 60 must adopt (inclusive)"

    def test_launch_threshold_rejects_fifty_nine_and_damage_tier_is_inclusive(self, api):
        """PRD §3.1: "Damage contributes nothing at zero cents, 5 points below
        one million cents (ten thousand dollars), 15 points from one million
        cents up to but below ten million cents (one hundred thousand dollars),
        and 25 points at ten million cents or more — tier lower bounds are
        inclusive, so an estimate of exactly one million cents scores 15."
        PRD §3.2: "a shortfall is `ERR_LAUNCH_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/boundary_launch_threshold_sixty_inclusive
        """
        set_clock()
        # 40 + 15 (exactly one million cents takes the 15-point tier) + 4 + 0
        # = 59; a 5-point tier read would yield 49, so 59 pins inclusivity.
        case = create_case(
            report_number="NTSB-2026-0106",
            category="HIGHWAY",
            occurred_at="2026-08-31T07:00:00Z",
            location_state="MD",
            fatalities_count=1,
            injuries_count=4,
            damage_estimate_cents=1000000,
            is_public_transport=False,
        )
        assert case["statutory_score"] == 59
        assert case["suggested_mode"] == "LIMITED"
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        decision = get_proposed_decision(case)
        resp = api.adopt_launch_decision(
            case["id"], decision["decision_id"], {"iic_user_id": "iic-1"}, MD_ADOPTER
        )
        validate_error(resp, ApiErrorId.ERR_LAUNCH_THRESHOLD_NOT_MET)
        case = get_case(case["id"])
        assert case["status"] == "SCREENING"
        assert find_decision(case, decision["decision_id"])["status"] == "PROPOSED"


class TestProposalOverridesAndOcc:
    def test_severity_override_on_propose_recomputes_scores_immediately(self, api):
        """PRD §3.2: "when any override is present, the case's severity fields
        are updated and both scores plus `suggested_mode` are recomputed before
        any snapshot is taken" and "`snapshot_statutory_score` with
        `snapshot_risk_adjusted_score` capturing the case's scores after any
        overrides of that proposal". PRD §3.2: "each accepted proposal
        increments the case's `version`."

        Design: Corner/entities/severity_override_on_propose_recomputes_scores_immediately
        """
        set_clock()
        case = create_case(
            report_number="NTSB-2026-0003",
            category="MARINE",
            occurred_at="2026-08-29T03:10:00Z",
            location_state="WA",
            fatalities_count=1,
            injuries_count=4,
            damage_estimate_cents=1000000,
            is_public_transport=False,
        )
        # 40 + 15 + 4 + 0 = 59 before the override.
        assert case["statutory_score"] == 59

        resp = api.propose_launch_decision(
            case["id"],
            propose_launch_decision_payload(
                "FULL_GO_TEAM",
                case["version"],
                is_public_transport=True,
                rationale="Vessel confirmed under public-ferry contract.",
            ),
            MD_PROPOSER,
        )
        updated = validate_success(resp, expected_status=201)
        # 40 + 15 + 4 + 20 = 79 statutory; 40.0 + 18.8 + 5.0 + 10.0 = 73.8.
        assert updated["statutory_score"] == 79
        assert updated["risk_adjusted_score"] == pytest.approx(73.8, abs=1e-6)
        assert updated["suggested_mode"] == "FULL_GO_TEAM"
        assert updated["version"] == case["version"] + 1
        decision = get_proposed_decision(updated)
        assert decision["snapshot_statutory_score"] == 79
        assert_case_scores(updated)

        adopted = adopt_launch_decision(case["id"], decision["decision_id"])
        assert adopted["status"] == "LAUNCHED"

    def test_occ_stale_case_version_rejected_and_fresh_propose_supersedes(self, api):
        """PRD §2.7: "If the case's current `version` has advanced beyond that
        value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "At most one decision per case is `PROPOSED` at any moment:
        appending the new decision — status `PROPOSED`, `proposed_by_user_id`
        taken from the caller's `X-User-ID`, `proposed_at` stamped from the
        logical clock, and `snapshot_statutory_score` with
        `snapshot_risk_adjusted_score` capturing the case's scores after any
        overrides of that proposal — automatically moves any previously
        proposed decision to `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_rejected_and_fresh_propose_supersedes
        """
        set_clock()
        case = create_case()
        stale_version = case["version"]
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        first_decision = get_proposed_decision(case)
        assert case["version"] == stale_version + 1

        resp = api.propose_launch_decision(
            case["id"],
            propose_launch_decision_payload("LIMITED", stale_version),
            MD_PROPOSER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        resp = api.propose_launch_decision(
            case["id"],
            propose_launch_decision_payload("LIMITED", case["version"]),
            MD_PROPOSER,
        )
        updated = validate_success(resp, expected_status=201)
        assert updated["version"] == case["version"] + 1

        refreshed = get_case(case["id"])
        assert len(refreshed["launch_decisions"]) == 2
        assert (
            find_decision(refreshed, first_decision["decision_id"])["status"]
            == "SUPERSEDED"
        )
        proposed = get_proposed_decision(refreshed)  # exactly one PROPOSED
        assert proposed["decision_id"] != first_decision["decision_id"]
        assert proposed["mode"] == "LIMITED"
