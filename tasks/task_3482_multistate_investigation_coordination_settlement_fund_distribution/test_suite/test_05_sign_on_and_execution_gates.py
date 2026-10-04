"""Sign-on campaign and execution: quorum boundary precision, the two
isolated collapse clauses, soft quorum failure inside the window, and the
temporal/referential gates on recording decisions.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    PAST_SIGN_ON_DEADLINE,
    api_client,
    assert_weights_sum_to_total,
    create_state_office,
    get_investigation,
    get_settlement,
    list_allocation_lines,
    make_lead_state_ag_headers,
    make_participating_state_ag_headers,
    record_sign_ons,
    set_clock,
    setup_executed_world,
    setup_sign_on_open_world,
    sign_on_payload,
    validate_error,
    validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]


def _same_instant(actual: str, expected: str) -> bool:
    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == (
        datetime.fromisoformat(expected.replace("Z", "+00:00"))
    )


def _lines_by_state(world):
    return {line["state_code"]: line for line in world["lines"]}


def test_quorum_exactly_8000_bps_executes():
    """PRD section 3.4: "Quorum is met when that ratio is at least 8000 basis
    points — exactly 8000 passes — **and** at least 3 states have signed."
    PRD section 3.4: "A quorum-met execution moves the settlement
    `SIGN_ON_OPEN` → `EXECUTED` and stamps `executed_at`."
    PRD section 2.4: "Before any test-driving call, the logical clock's value
    is exactly `2026-09-01T00:00:00Z`."

    Design: Difficulty/boundary_precision_check/quorum_exactly_8000_bps_executes
    """
    world = setup_executed_world()
    settlement = world["settlement"]
    # CA(100)+TX(300)+NY(400) signed = 800 of the 1000 eligible population =
    # exactly 8000 bps, and 3 signed states: the inclusive boundary passes.
    assert settlement["term_status"] == "EXECUTED"
    assert _same_instant(settlement["executed_at"], "2026-09-01T00:00:00Z")
    lines = _lines_by_state(world)
    assert set(lines) == {"CA", "TX", "NY"}, "FL declined and takes no line"
    assert (lines["CA"]["weight_bps"], lines["TX"]["weight_bps"],
            lines["NY"]["weight_bps"]) == (1250, 3750, 5000)
    assert_weights_sum_to_total(world["lines"])


def test_quorum_bps_clause_isolated_collapse():
    """PRD section 3.4: "Quorum is met when that ratio is at least 8000 basis
    points — exactly 8000 passes — **and** at least 3 states have signed."
    PRD section 3.4: "If the deadline has passed and quorum remains unmet, the
    settlement collapses: `SIGN_ON_OPEN` → `COLLAPSED`, the investigation's
    phase automatically returns `SETTLEMENT_PENDING` → `NEGOTIATION`, and the
    investigation's `active_settlement_id` is cleared to null, freeing the
    committee to propose again."

    Design: Corner/calculations/quorum_bps_clause_isolated_collapse
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    # CA+TX+FL signed: 600 of 1000 population = 6000 bps (fails the weight
    # clause) while the count clause is satisfied (3 signed states).
    record_sign_ons(world, {"CA": "SIGNED", "TX": "SIGNED", "FL": "SIGNED"})
    set_clock(PAST_SIGN_ON_DEADLINE)
    resp = api_client.execute_settlement(stl_id, CHAIR)
    assert validate_success(resp)["term_status"] == "COLLAPSED"
    inv = get_investigation(world["investigation"]["id"])
    assert inv["phase"] == "NEGOTIATION"
    assert inv["active_settlement_id"] is None


def test_quorum_count_clause_isolated_collapse():
    """PRD section 3.4: "Quorum is met when that ratio is at least 8000 basis
    points — exactly 8000 passes — **and** at least 3 states have signed."
    PRD section 3.4: "If the deadline has passed and quorum remains unmet, the
    settlement collapses: `SIGN_ON_OPEN` → `COLLAPSED`."

    Design: Corner/calculations/quorum_count_clause_isolated_collapse
    """
    specs = {
        "AA": {"state_code": "AA", "population": 500, "harm_measure_cents": 250,
               "appropriation_rule": "PREAPPROPRIATED", "cia_tier": "LEAD_ONLY"},
        "BB": {"state_code": "BB", "population": 300, "harm_measure_cents": 150,
               "appropriation_rule": "PREAPPROPRIATED", "cia_tier": "RESTRICTED"},
        "CC": {"state_code": "CC", "population": 100, "harm_measure_cents": 50,
               "appropriation_rule": "CERTIFICATION_REQUIRED", "cia_tier": "STANDARD"},
        "DD": {"state_code": "DD", "population": 100, "harm_measure_cents": 50,
               "appropriation_rule": "GENERAL_FUND_ONLY", "cia_tier": "STANDARD"},
    }
    world = setup_sign_on_open_world(
        office_codes=("AA", "BB", "CC", "DD"), lead_codes=("AA", "BB"),
        office_specs=specs,
    )
    # AA+BB signed: 800 of 1000 population = exactly 8000 bps (weight clause
    # satisfied) but only 2 signed states (< 3): the count clause fails.
    record_sign_ons(world, {"AA": "SIGNED", "BB": "SIGNED"})
    set_clock(PAST_SIGN_ON_DEADLINE)
    resp = api_client.execute_settlement(world["settlement"]["id"], CHAIR)
    assert validate_success(resp)["term_status"] == "COLLAPSED"


def test_quorum_unmet_before_deadline_returns_error_without_collapse():
    """PRD section 3.4: "If the current logical time is at or before the
    deadline and quorum is not met, execution is rejected with
    `ERR_QUORUM_NOT_MET` (HTTP 422) and nothing changes."

    Design: Corner/calculations/quorum_unmet_before_deadline_returns_error_without_collapse
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    # Only CA signed: 1000 bps and 1 state, both legs unmet, inside the window.
    record_sign_ons(world, {"CA": "SIGNED"})
    resp = api_client.execute_settlement(stl_id, CHAIR)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
    settlement = get_settlement(stl_id)
    assert settlement["term_status"] == "SIGN_ON_OPEN"
    assert len(settlement["sign_ons"]) == 1
    entry = settlement["sign_ons"][0]
    assert entry["state_code"] == "CA" and entry["status"] == "SIGNED", (
        "a soft quorum failure locks and lapses nothing"
    )


def test_sign_on_window_closed_for_participant():
    """PRD section 3.4: "the current logical time must be at or before
    `sign_on_deadline` (else `ERR_SIGN_ON_WINDOW_CLOSED`, HTTP 422)."
    PRD section 3.4: "Opening stamps `sign_on_opened_at` with the current
    logical time and fixes `sign_on_deadline` exactly 45 days later."

    Design: Corner/errors/sign_on_window_closed_for_participant
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    set_clock(PAST_SIGN_ON_DEADLINE)  # one day past opened_at + 45 days
    resp = api_client.record_sign_on(
        stl_id, sign_on_payload("SIGNED"),
        make_participating_state_ag_headers(world["offices"]["NY"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SIGN_ON_WINDOW_CLOSED)
    settlement = get_settlement(stl_id)
    assert all(
        entry["state_code"] != "NY" for entry in settlement["sign_ons"]
    ), "a rejected late sign-on records no entry"


def test_referential_beats_temporal_on_late_sign_on():
    """PRD section 3.4: "Four gates guard the recording, in the ladder order
    of §2.8: the settlement must be in `SIGN_ON_OPEN` (else
    `ERR_INVALID_STATE`); the caller's office must hold an `ACTIVE`
    participation in the settlement's investigation (else
    `ERR_NOT_A_PARTICIPANT`, HTTP 422); the current logical time must be at or
    before `sign_on_deadline` (else `ERR_SIGN_ON_WINDOW_CLOSED`, HTTP 422)."
    PRD section 2.8: "Every request is evaluated against a fixed ladder of
    checks, and the first failure wins."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_late_sign_on
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    zz = create_state_office(
        state_code="ZZ", population=50, harm_measure_cents=25,
        appropriation_rule="PREAPPROPRIATED",
    )  # registered but never invited: fails the referential participation gate
    set_clock(PAST_SIGN_ON_DEADLINE)  # the temporal gate also fails
    resp = api_client.record_sign_on(
        stl_id, sign_on_payload("SIGNED"),
        make_participating_state_ag_headers(zz["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_A_PARTICIPANT)


def test_duplicate_sign_on_rejected():
    """PRD section 3.4: "the office must not already hold a sign-on entry on
    this settlement — one decision per office, with a second attempt rejected
    as `ERR_DUPLICATE_SIGN_ON` (HTTP 409)."

    Design: Corner/errors/duplicate_sign_on_rejected
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    record_sign_ons(world, {"CA": "SIGNED"})
    resp = api_client.record_sign_on(
        stl_id, sign_on_payload("DECLINED"),
        # CA is a designated lead, so its caller authenticates as LeadStateAG.
        make_lead_state_ag_headers(world["offices"]["CA"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGN_ON)
    settlement = get_settlement(stl_id)
    assert len(settlement["sign_ons"]) == 1
    assert settlement["sign_ons"][0]["status"] == "SIGNED", (
        "a recorded decision cannot be flipped by replaying the endpoint"
    )


def test_collapsed_settlement_rejects_sign_on():
    """PRD section 3.4: "If the deadline has passed and quorum remains unmet,
    the settlement collapses: `SIGN_ON_OPEN` → `COLLAPSED`."
    PRD section 3.4: "the settlement must be in `SIGN_ON_OPEN` (else
    `ERR_INVALID_STATE`)."
    PRD section 3.7: "`CLOSED_OUT` and `COLLAPSED` are the settlement's
    terminal term statuses."

    Design: Corner/state_machines/collapsed_settlement_rejects_sign_on
    """
    world = setup_sign_on_open_world()
    stl_id = world["settlement"]["id"]
    # 6000 bps signed (CA+TX+FL), NY silent; past the deadline the execute
    # collapses the settlement.
    record_sign_ons(world, {"CA": "SIGNED", "TX": "SIGNED", "FL": "SIGNED"})
    set_clock(PAST_SIGN_ON_DEADLINE)
    resp = api_client.execute_settlement(stl_id, CHAIR)
    assert validate_success(resp)["term_status"] == "COLLAPSED"
    resp_late = api_client.record_sign_on(
        stl_id, sign_on_payload("SIGNED"),
        make_participating_state_ag_headers(world["offices"]["NY"]["id"]),
    )
    validate_error(resp_late, ApiErrorId.ERR_INVALID_STATE)
    settlement = get_settlement(stl_id)
    assert all(
        entry["state_code"] != "NY" for entry in settlement["sign_ons"]
    ), "a terminal settlement accrues no further sign-on entries"
