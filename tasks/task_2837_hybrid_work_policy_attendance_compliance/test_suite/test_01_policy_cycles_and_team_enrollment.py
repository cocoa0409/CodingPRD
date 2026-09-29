"""Opening a policy cycle, enrolling teams and deriving seat entitlement."""
from test_helpers import (
    UNKNOWN_POLICY_CYCLE_ID,
    ApiErrorId,
    api_client,
    assert_policy_cycle,
    assert_seat_entitlement_invariants,
    assert_team,
    canonical_instant,
    create_cycle,
    create_team,
    pin_clock,
    policy_cycle_payload,
    read_cycle,
    read_employee,
    register_employee,
    team_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import WPO


ENTITLEMENT_CYCLE = {
    "cycle_label": "FY27-ENT",
    "days_in_office_floor": 1,
    "badge_weight": 0.50,
    "network_weight": 0.50,
    "collaboration_target_score": 60.00,
    "equity_variance_threshold_pct": 15.00,
}


def _entitlement_cycle_with_four_teams():
    """One cycle carrying the four teams that straddle both buffer-tier edges."""
    pin_clock()
    cycle = create_cycle(**ENTITLEMENT_CYCLE)
    teams = {}
    for code, headcount in (
        ("TA-BASE25", 125),
        ("TB-BASE26", 130),
        ("TC-BASE10", 50),
        ("TD-BASE11", 51),
    ):
        teams[code] = create_team(
            cycle["id"],
            team_code=code,
            expected_days_in_office_per_week=1,
            core_collaboration_days=["WED"],
            headcount_planned=headcount,
        )
    return cycle, teams


def test_01_buffer_tier_is_keyed_on_base_entitlement_and_never_on_the_total():
    """A base of 25 takes the 12 percent tier even though the total lands at 28.

    PRD 3.1: "Step three: a buffer percentage is selected from three tiers,
    evaluated in declared order and keyed on `base_entitlement` alone — never on
    the eventual total — where a base of at most 10 takes 20 percent, a base of at
    most 25 takes 12 percent, and any larger base takes 6 percent."
    PRD 3.1: "Keying the tier off the 28-seat total instead would select 6 percent
    and yield 27, which is wrong."

    Design: Difficulty/combinatorial_formula/seat_entitlement_tier_keyed_on_base_not_total
    """
    cycle, teams = _entitlement_cycle_with_four_teams()

    base_25 = teams["TA-BASE25"]
    assert_team(base_25)
    assert base_25["expected_daily_attendance"] == 25
    assert base_25["base_entitlement"] == 25
    assert base_25["buffer_seats_entitled"] == 3, (
        "a base of 25 takes the 12 percent tier, so the buffer is 3 and not the "
        "2 seats the 6 percent tier would give"
    )
    assert base_25["entitled_seats"] == 28

    base_26 = teams["TB-BASE26"]
    assert_team(base_26)
    assert base_26["expected_daily_attendance"] == 26
    assert base_26["base_entitlement"] == 26
    assert base_26["buffer_seats_entitled"] == 2
    assert base_26["entitled_seats"] == 28
    assert base_25["entitled_seats"] == base_26["entitled_seats"], (
        "the two tiers meet at 28 entitled seats from either side of the boundary"
    )

    assert read_cycle(cycle["id"])["enrolled_team_count"] == 4


def test_02_expected_daily_attendance_rounds_up_before_the_smallest_tier_applies():
    """Fifty-one heads at one day a week round up to 11, which leaves the 20 percent tier.

    PRD 3.1: "Step one: `expected_daily_attendance` is the planned headcount
    multiplied by the expected days in office, divided by the five working days of
    a week, then rounded **up** to a whole number."
    PRD 3.1: "Step four: `buffer_seats_entitled` is `base_entitlement` multiplied
    by that percentage, rounded **up** to a whole number."

    Design: Difficulty/combinatorial_formula/seat_entitlement_tier_keyed_on_base_not_total
    """
    _, teams = _entitlement_cycle_with_four_teams()

    base_10 = teams["TC-BASE10"]
    assert base_10["expected_daily_attendance"] == 10
    assert base_10["base_entitlement"] == 10
    assert base_10["buffer_seats_entitled"] == 2, "a base of 10 takes 20 percent"
    assert base_10["entitled_seats"] == 12

    base_11 = teams["TD-BASE11"]
    assert base_11["expected_daily_attendance"] == 11, (
        "fifty-one heads over one day is 10.2 daily, rounded up to 11"
    )
    assert base_11["base_entitlement"] == 11
    assert base_11["buffer_seats_entitled"] == 2, (
        "eleven at 12 percent is 1.32, rounded up to 2"
    )
    assert base_11["entitled_seats"] == 13
    for team in (base_10, base_11):
        assert_seat_entitlement_invariants(team)


def test_03_a_new_cycle_starts_open_with_every_roll_up_at_zero():
    """The declared dials are echoed back and the three roll-ups start empty.

    PRD 3.1: "A new cycle starts in `OPEN` posture with `enrolled_team_count` at
    0, `aggregate_compliance_rate` at 0.00 and `formal_action_total` at 0."

    Design: Corner/entities/policy_cycle_creation_returns_declared_fields_and_system_defaults
    """
    pin_clock()
    payload = policy_cycle_payload(
        cycle_label="FY27-DEFAULTS",
        days_in_office_floor=3,
        badge_weight=0.70,
        network_weight=0.30,
        collaboration_target_score=65.50,
        equity_variance_threshold_pct=12.25,
    )
    data = validate_success(api_client.create_policy_cycle(payload, WPO), 201)
    assert_policy_cycle(data)
    assert data["cycle_label"] == "FY27-DEFAULTS"
    assert data["effective_from"] == payload["effective_from"]
    assert data["effective_to"] == payload["effective_to"]
    assert data["days_in_office_floor"] == 3
    assert data["badge_weight"] == 0.70
    assert data["network_weight"] == 0.30
    assert data["collaboration_target_score"] == 65.50
    assert data["equity_variance_threshold_pct"] == 12.25
    assert data["posture"] == "OPEN"
    assert data["enrolled_team_count"] == 0
    assert data["aggregate_compliance_rate"] == 0.00
    assert data["formal_action_total"] == 0
    assert data["version"] == 1
    assert read_cycle(data["id"])["id"] == data["id"]


def test_04_team_and_employee_reads_return_the_stored_row_with_its_entitlement():
    """A team read echoes every declared field and all four derived entitlement fields.

    PRD 3.1: "It also declares `core_collaboration_days`, an array of between zero
    and five distinct weekday codes drawn from `MON`, `TUE`, `WED`, `THU` and
    `FRI` on which the team is expected to co-locate — published in the policy
    communication and not consumed by any calculation — and `headcount_planned`,
    an integer from 1 through 5000."

    Design: Corner/entities/team_and_employee_retrieval_returns_the_stored_row_with_derived_entitlement
    """
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-READBACK", days_in_office_floor=2)
    team = create_team(
        cycle["id"],
        team_code="T-READ",
        expected_days_in_office_per_week=3,
        core_collaboration_days=["TUE", "WED", "THU"],
        headcount_planned=12,
        signal_corroboration_required=True,
    )
    fetched = validate_success(api_client.get_team(team["id"], WPO))
    assert_team(fetched)
    assert fetched["team_code"] == "T-READ"
    assert fetched["policy_cycle_id"] == cycle["id"]
    assert fetched["expected_days_in_office_per_week"] == 3
    assert fetched["core_collaboration_days"] == ["TUE", "WED", "THU"]
    assert fetched["headcount_planned"] == 12
    assert fetched["signal_corroboration_required"] is True
    assert fetched["expected_daily_attendance"] == 8
    assert fetched["base_entitlement"] == 8
    assert fetched["buffer_seats_entitled"] == 2
    assert fetched["entitled_seats"] == 10
    assert fetched["escalated_headcount"] == 0
    assert fetched["formal_action_count"] == 0

    employee = register_employee(team["id"], employee_number="E-READ")
    read_back = read_employee(employee["id"])
    assert read_back["team_id"] == team["id"]
    assert read_back["employee_number"] == "E-READ"
    assert read_back["status"] == "ACTIVE"
    assert read_back["current_eligibility_class"] == "ONSITE_REQUIRED"


def test_05_enrolling_a_team_under_an_unknown_cycle_is_a_not_found():
    """A `policy_cycle_id` that does not resolve refuses the enrolment outright.

    PRD 2.5: "Path parameters and payload foreign keys are resolved left to right,
    path segments before body fields, and the first identifier that fails to
    resolve determines the error."

    Design: Corner/entities/team_create_with_an_unknown_policy_cycle_returns_not_found
    """
    pin_clock()
    response = api_client.create_team(team_payload(UNKNOWN_POLICY_CYCLE_ID), WPO)
    validate_error(response, ApiErrorId.ERR_POLICY_CYCLE_NOT_FOUND.value, 404)


def test_06_creation_payloads_missing_a_required_field_are_refused_on_shape():
    """A cycle without `effective_to` and a team without `headcount_planned` both fail shape.

    PRD 2.10: "**Request shape** — missing required fields, undeclared enum
    members and out-of-range numbers, all `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_calls_missing_required_fields_returns_invalid_request
    """
    pin_clock()
    cycle_payload = policy_cycle_payload()
    cycle_payload.pop("effective_to")
    validate_error(
        api_client.create_policy_cycle(cycle_payload, WPO),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    cycle = create_cycle()
    broken_team = team_payload(cycle["id"])
    broken_team.pop("headcount_planned")
    validate_error(
        api_client.create_team(broken_team, WPO),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )


def test_07_the_clock_endpoint_needs_no_identity_and_every_stamp_follows_it():
    """The clock call carries no user, mutates nothing, and later rows stamp from it.

    PRD 2.1: "The single exception is the logical-clock endpoint `POST
    /_clock/set_current_utc`, which is a test-driving affordance and requires no
    authenticated user."
    PRD 2.6: "A caller of any role may rebind it by supplying a `current_utc`
    instant; that call returns 200, mutates no entity, and triggers no
    recomputation — it only changes what "now" means for subsequent requests."

    Design: Corner/endpoints/the_clock_endpoint_needs_no_identity_and_every_timestamp_follows_it
    """
    validate_success(api_client.set_clock("2026-09-01T09:00:00Z", {}), 200)

    cycle = create_cycle(cycle_label="FY27-CLOCK")
    assert canonical_instant(cycle["created_at"]) == "2026-09-01T09:00:00Z"
    assert canonical_instant(cycle["updated_at"]) == "2026-09-01T09:00:00Z"

    validate_success(api_client.set_clock("2026-09-14T09:00:00Z", {}), 200)
    after_rebind = read_cycle(cycle["id"])
    assert after_rebind["version"] == cycle["version"], (
        "rebinding the clock mutates no entity and triggers no recomputation"
    )
    assert canonical_instant(after_rebind["updated_at"]) == "2026-09-01T09:00:00Z"

    later_team = create_team(cycle["id"], team_code="T-LATER")
    assert canonical_instant(later_team["created_at"]) == "2026-09-14T09:00:00Z"
