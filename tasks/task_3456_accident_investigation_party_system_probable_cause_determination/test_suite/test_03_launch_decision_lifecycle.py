"""Launch-decision lifecycle: adoption, the reconsideration cycle, proposer
segregation of duties, and terminal-state lockdown (PRD §3.2, §3.8).

The reconsider cycle is PROPOSED -> ADOPTED -> PROPOSED -> ADOPTED. Because a
reconsideration payload carries no mode field (PRD §3.2: "a fresh optional
`rationale` and the same severity overrides"), the reconsidered decision keeps
its LIMITED mode, so the second adoption returns the case to LIMITED_TRACK and
must omit `iic_user_id` — the conditional-field rule is asserted directly.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adopt_launch_decision,
    adopt_launch_decision_payload,
    create_case,
    find_decision,
    get_case,
    get_proposed_decision,
    propose_launch_decision,
    propose_launch_decision_payload,
    reconsider_launch_decision,
    reconsider_launch_decision_payload,
    set_clock,
    setup_adopted_case,
    setup_launched_investigation,
    validate_error,
    validate_success,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]
MD_PROPOSER = TEST_USERS["md_proposer_headers"]
MD_ADOPTER = TEST_USERS["md_adopter_headers"]

MARINE_58 = dict(
    report_number="NTSB-2026-0104",
    category="MARINE",
    occurred_at="2026-08-27T11:00:00Z",
    location_state="OR",
    fatalities_count=1,
    injuries_count=3,
    damage_estimate_cents=5000000,
    is_public_transport=False,
)


def _propose_adopt_limited(case):
    """propose LIMITED (md-1) + adopt (md-2): case -> LIMITED_TRACK."""
    case = propose_launch_decision(case, mode="LIMITED")
    decision = get_proposed_decision(case)
    case = adopt_launch_decision(case["id"], decision["decision_id"], iic_user_id=None)
    return case, decision


class TestReconsiderCycle:
    def test_launch_decision_reconsider_cycle_returns_to_screening_and_readopts(self, api):
        """PRD §3.2: "Reconsideration of an `ADOPTED` decision — permitted only
        while the case is in `LIMITED_TRACK` or `DECLINED`, with `LAUNCHED` or
        `CLOSED_ADOPTED` cases rejected with `ERR_CASE_ALREADY_LAUNCHED` and a
        decision not currently `ADOPTED` rejected with
        `ERR_DECISION_STATE_INVALID` — returns the decision to `PROPOSED` and
        the case to `SCREENING`." PRD §3.2: "overrides are applied to the case,
        both scores and `suggested_mode` are recomputed, and the decision's
        snapshot fields are refreshed from the recomputed values, with the
        case's `version` incremented." PRD §3.2: "Adopting `LIMITED` moves the
        case to `LIMITED_TRACK`."

        Design: Difficulty/non_linear_state_machine/non_linear_launch_decision_reconsider_cycle
        """
        set_clock()
        case = create_case(**MARINE_58)
        assert case["statutory_score"] == 58

        case, decision = _propose_adopt_limited(case)
        assert case["status"] == "LIMITED_TRACK"
        assert find_decision(case, decision["decision_id"])["status"] == "ADOPTED"

        # Reconsider with a severity override: public-conveyance involvement
        # recomputes statutory to 40 + 15 + 3 + 20 = 78.
        resp = api.reconsider_launch_decision(
            case["id"],
            decision["decision_id"],
            reconsider_launch_decision_payload(
                is_public_transport=True,
                rationale="New evidence: the vessel was under public-ferry contract.",
            ),
            MD_PROPOSER,
        )
        reopened = validate_success(resp, expected_status=200)
        assert reopened["status"] == "SCREENING"
        assert reopened["statutory_score"] == 78
        assert reopened["suggested_mode"] == "FULL_GO_TEAM"
        assert reopened["version"] == case["version"] + 1
        reconsidered = find_decision(reopened, decision["decision_id"])
        assert reconsidered["status"] == "PROPOSED"
        assert reconsidered["snapshot_statutory_score"] == 78
        assert get_proposed_decision(reopened)["decision_id"] == decision["decision_id"]

        # The decision keeps its LIMITED mode (reconsideration carries no mode
        # field), so the second adoption must omit iic_user_id and returns the
        # case to LIMITED_TRACK: the cycle closes forward.
        readopted = adopt_launch_decision(
            reopened["id"], decision["decision_id"], iic_user_id=None
        )
        assert readopted["status"] == "LIMITED_TRACK"
        assert find_decision(readopted, decision["decision_id"])["status"] == "ADOPTED"

    def test_readopt_of_reconsidered_limited_decision_rejects_iic_user_id(self, api):
        """PRD §3.2: "The payload's `iic_user_id` is required exactly when the
        mode is `FULL_GO_TEAM` and must be absent for the other modes
        (`ERR_INVALID_REQUEST`)."

        Design: Difficulty/non_linear_state_machine/non_linear_launch_decision_reconsider_cycle
        """
        set_clock()
        case = create_case(**MARINE_58)
        case, decision = _propose_adopt_limited(case)
        case = reconsider_launch_decision(
            case["id"],
            decision["decision_id"],
            is_public_transport=True,
            rationale="New evidence: the vessel was under public-ferry contract.",
        )
        assert case["statutory_score"] == 78

        # The reconsidered decision is still mode LIMITED; carrying iic_user_id
        # violates the conditional-field rule even though the refreshed score
        # of 78 would satisfy the FULL_GO_TEAM threshold.
        resp = api.adopt_launch_decision(
            case["id"],
            decision["decision_id"],
            adopt_launch_decision_payload("iic-1"),
            MD_ADOPTER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = get_case(case["id"])
        assert after["status"] == "SCREENING"
        assert find_decision(after, decision["decision_id"])["status"] == "PROPOSED"


class TestDecisionStateGuards:
    def test_reconsider_on_proposed_decision_returns_state_invalid(self, api):
        """PRD §3.2: "a decision not currently `ADOPTED` rejected with
        `ERR_DECISION_STATE_INVALID`".

        Design: Corner/state_machines/reconsider_on_proposed_decision_returns_state_invalid
        """
        set_clock()
        case = create_case()
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        decision = get_proposed_decision(case)

        resp = api.reconsider_launch_decision(
            case["id"],
            decision["decision_id"],
            {"rationale": "Reopen prematurely."},
            MD_PROPOSER,
        )
        validate_error(resp, ApiErrorId.ERR_DECISION_STATE_INVALID)
        after = get_case(case["id"])
        assert after["status"] == "SCREENING"
        assert find_decision(after, decision["decision_id"])["status"] == "PROPOSED"

    def test_reconsider_after_launch_returns_case_already_launched(self, api):
        """PRD §3.2: "Reconsideration of an `ADOPTED` decision — permitted only
        while the case is in `LIMITED_TRACK` or `DECLINED`, with `LAUNCHED` or
        `CLOSED_ADOPTED` cases rejected with `ERR_CASE_ALREADY_LAUNCHED`".

        Design: Corner/errors/reconsider_after_launch_returns_case_already_launched
        """
        ctx = setup_launched_investigation()
        case = ctx["case"]
        assert case["status"] == "LAUNCHED"

        resp = api.reconsider_launch_decision(
            case["id"],
            ctx["decision_id"],
            {"fatalities_count": 3, "rationale": "Fatality count revised upward."},
            MD_PROPOSER,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_LAUNCHED)
        after = get_case(case["id"])
        assert after["status"] == "LAUNCHED"
        assert find_decision(after, ctx["decision_id"])["status"] == "ADOPTED"


class TestAdoptionSegregationAndConsistency:
    def test_proposer_cannot_adopt_own_launch_decision(self, api):
        """PRD §3.2: "and the director who proposed a decision may not adopt it
        (`ERR_SOD_PROPOSER_CANNOT_ADOPT`)."

        Design: Corner/validations/proposer_cannot_adopt_own_launch_decision
        """
        set_clock()
        case = create_case()
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        decision = get_proposed_decision(case)
        assert decision["proposed_by_user_id"] == "md-1"

        resp = api.adopt_launch_decision(
            case["id"],
            decision["decision_id"],
            adopt_launch_decision_payload("iic-1"),
            MD_PROPOSER,  # same identity as the proposer
        )
        validate_error(resp, ApiErrorId.ERR_SOD_PROPOSER_CANNOT_ADOPT)

        # The identical payload from a different ManagingDirector succeeds.
        adopted = adopt_launch_decision(case["id"], decision["decision_id"])
        assert adopted["status"] == "LAUNCHED"

    def test_adopt_response_immediately_reflects_launched_case(self, api):
        """PRD §1: "All mutations are immediately visible in the response that
        performs them." PRD §3.2: "A successful adoption stamps the decision's
        `adopted_at` from the logical clock and moves the case according to the
        mode." PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource."

        Design: Corner/consistency_model/adopt_response_immediately_reflects_launched_case
        """
        set_clock()
        case = create_case()
        case = propose_launch_decision(case, mode="FULL_GO_TEAM")
        decision = get_proposed_decision(case)

        resp = api.adopt_launch_decision(
            case["id"],
            decision["decision_id"],
            adopt_launch_decision_payload("iic-1"),
            MD_ADOPTER,
        )
        adopted = validate_success(resp, expected_status=200)
        # create -> 1, propose -> 2, adopt -> 3.
        assert adopted["status"] == "LAUNCHED"
        assert adopted["version"] == case["version"] + 1 == 3

        reread = get_case(case["id"])
        assert reread["status"] == adopted["status"] == "LAUNCHED"
        assert reread["version"] == adopted["version"]
        adopted_decision = find_decision(reread, decision["decision_id"])
        assert adopted_decision["status"] == "ADOPTED"
        assert adopted_decision["adopted_at"] is not None

    def test_board_adoption_marks_case_terminal_and_rejects_new_proposals(self, api):
        """PRD §3.2: "While a case remains in `SCREENING` — proposals against a
        case in any other status are rejected with `ERR_CASE_NOT_SCREENING`".
        PRD §3.8: "and the originating accident case moves from `LAUNCHED` to
        `CLOSED_ADOPTED`, its own terminal state."

        Design: Corner/state_machines/board_adoption_marks_case_terminal_and_rejects_new_proposals
        """
        ctx = setup_adopted_case()
        case = ctx["case"]
        assert case["status"] == "CLOSED_ADOPTED"

        # Even an OCC-fresh writer is locked out: the terminal state rejects
        # before any version comparison matters.
        resp = api.propose_launch_decision(
            case["id"],
            propose_launch_decision_payload("LIMITED", case["version"]),
            MD_PROPOSER,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_SCREENING)
