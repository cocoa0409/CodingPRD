"""The weekly operations checkpoint: auto-transitions, floored accrual and
mortality, molt cycling, auto-depletion, idempotence at zero elapsed weeks,
and the forward capacity projection.
"""

from test_helpers import (
    ADMIN,
    PLANNER,
    api_client,
    assert_instant_equal,
    create_and_place_flock,
    create_complex,
    create_disease_event,
    create_house,
    create_planned_flock,
    confirm_disease_event,
    read_flock,
    read_house,
    run_ops,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def test_run_ops_growing_to_laying_at_week_18(api):
    """A 20-week checkpoint transitions GROWING -> LAYING at the week-start
    the flock reaches 18, accrues exactly the two laying weeks, and floors
    ten-basis-point mortality per week.

    PRD §3.2: "(3) otherwise, if it is `GROWING` at eighteen weeks or older,
    it advances to `LAYING`; (4) a flock now in `LAYING` accrues eggs — the
    whole-dozen floor of its `current_hen_count` times the lay rate times
    seven days divided by twelve eggs per dozen — into the complex's ungraded
    bucket matching the flock's `program`; (5) mortality removes the
    whole-bird floor of one-tenth of one percent (ten basis points) of
    `current_hen_count`; (6) `age_weeks` advances by one."
    PRD §2.4: "Each checkpoint increments the complex's `ops_run_index` (a
    monotone counter starting at 0), re-stamps `last_ops_run_at` to the
    current clock, and increments the complex's `version`."

    Design: Corner/state_machines/run_ops_growing_to_laying_at_week_18
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Accrual Farm")
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-09-01T00:00:00Z",
        placed_hen_count=90_000,
    )
    assert flock["status"] == "GROWING" and flock["age_weeks"] == 0

    set_clock("2027-01-19T00:00:00Z")  # exactly 20 weeks later
    complex_after = run_ops(complex_["id"])

    flock_after = read_flock(flock["id"])
    assert flock_after["status"] == "LAYING"
    assert flock_after["age_weeks"] == 20
    # 20 floored 10bps mortality rounds from 90000 -> 88227.
    assert flock_after["current_hen_count"] == 88_227
    # Ages 18 and 19 accrued at the 0.85 band: 43833 + 43789.
    assert complex_after["ungraded_conventional_dozen"] == 87_622
    assert complex_after["ops_run_index"] == 1
    assert_instant_equal(
        complex_after["last_ops_run_at"], "2027-01-19T00:00:00Z",
        "last_ops_run_at",
    )


def test_run_ops_idempotent_at_zero_elapsed_weeks(api):
    """A checkpoint with zero whole weeks elapsed mutates no flock and
    accrues nothing, yet still advances the ops counter.

    PRD §2.4: "A checkpoint taken with zero elapsed weeks leaves flock state
    untouched but still runs every janitorial check and still advances the
    counter — it is idempotent for flock state, not for bookkeeping."

    Design: Corner/complexity_layers/run_ops_idempotent_at_zero_elapsed_weeks
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=90_000,
    )
    assert flock["status"] == "LAYING" and flock["age_weeks"] == 18

    first = run_ops(complex_["id"])
    assert first["ops_run_index"] == 1
    assert first["ungraded_conventional_dozen"] == 0

    set_clock("2026-09-08T00:00:00Z")
    second = run_ops(complex_["id"])
    assert second["ops_run_index"] == 2
    # One elapsed week at age 18: floor(90000 * 0.85 * 7 / 12) = 44625.
    assert second["ungraded_conventional_dozen"] == 44_625

    third = run_ops(complex_["id"])  # same clock: zero further weeks
    assert third["ops_run_index"] == 3
    assert third["ungraded_conventional_dozen"] == 44_625

    flock_after = read_flock(flock["id"])
    assert flock_after["current_hen_count"] == 89_910  # one week of mortality
    assert flock_after["age_weeks"] == 19


def test_lay_accrual_floors_per_flock_per_week(api):
    """The fractional dozen is truncated per flock per week: 44580, not 44581.

    PRD §2.6: "Weekly lay accrual and weekly mortality are each **rounded
    down** (floored) per flock per week."
    PRD §3.2: "(4) a flock now in `LAYING` accrues eggs — the whole-dozen
    floor of its `current_hen_count` times the lay rate times seven days
    divided by twelve eggs per dozen".

    Design: Corner/calculations/lay_accrual_floors_per_flock_per_week
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=89_910,
    )
    assert flock["age_weeks"] == 18 and flock["status"] == "LAYING"

    set_clock("2026-09-08T00:00:00Z")
    complex_after = run_ops(complex_["id"])

    # floor(89910 * 0.85 * 7 / 12) = floor(44580.375) = 44580.
    assert complex_after["ungraded_conventional_dozen"] == 44_580
    flock_after = read_flock(flock["id"])
    # floor(89910 * 10 / 10000) = 89 hens of mortality.
    assert flock_after["current_hen_count"] == 89_821
    assert flock_after["age_weeks"] == 19


def test_flock_auto_depleted_at_age_80(api):
    """The week start at which age reaches eighty depletes the flock with no
    operator action and freezes the age counter.

    PRD §3.2: "(1) if the flock's `age_weeks` has reached eighty weeks, it is
    depleted to `DEPLETED` with `current_hen_count` zeroed and no further
    steps".
    PRD §3.2: "Depletion (age eighty), depopulation (§3.3), and
    quarantine-driven cancellation of still-`PLANNED` flocks are the terminal
    exits; flocks in `DEPLETED`, `DEPOPULATED`, or `CANCELLED` contribute
    nothing to `hen_inventory`."

    Design: Corner/state_machines/flock_auto_depleted_at_age_80
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=60_000,
    )
    assert flock["age_weeks"] == 18

    set_clock("2027-11-16T00:00:00Z")  # 63 weeks later: deplete fires at 80
    run_ops(complex_["id"])

    flock_after = read_flock(flock["id"])
    assert flock_after["status"] == "DEPLETED"
    assert flock_after["current_hen_count"] == 0
    assert flock_after["age_weeks"] == 80
    assert read_house(house["id"])["hen_inventory"] == 0

    validate_error(api.molt_flock(flock["id"], PLANNER), ERR.ERR_INVALID_STATE)


def test_molt_from_growing_returns_invalid_state(api):
    """Molt is defined only from LAYING; from GROWING the state check at
    layer (7) reports before the eligibility constraint.

    PRD §3.2: "A planner may also induce a molt on a `LAYING` flock, but only
    when the flock is at least fifty weeks old and has never molted; otherwise
    the request is `ERR_MOLT_NOT_ALLOWED`, which is also what a second molt
    attempt earns."
    PRD §2.11: "validation proceeds in layers and the **first** failing layer
    determines the error. The layers, in order: ... (7) state-machine
    legality, including cross-entity state gates, reported as
    `ERR_INVALID_STATE`; ... (13) structural business constraints (...
    molt eligibility ...)".

    Design: Corner/state_machines/molt_from_growing_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-09-01T00:00:00Z",
        placed_hen_count=10_000,
    )
    assert flock["status"] == "GROWING"

    response = api.molt_flock(flock["id"], PLANNER)
    error = validate_error(response, ERR.ERR_INVALID_STATE)
    assert error["error_id"] != ERR.ERR_MOLT_NOT_ALLOWED.value
    assert read_flock(flock["id"])["status"] == "GROWING"


def test_molt_below_minimum_age_rejected(api):
    """A LAYING flock younger than fifty weeks fails the eligibility rule.

    PRD §3.2: "A planner may also induce a molt on a `LAYING` flock, but only
    when the flock is at least fifty weeks old and has never molted; otherwise
    the request is `ERR_MOLT_NOT_ALLOWED`, which is also what a second molt
    attempt earns."

    Design: Corner/validations/molt_below_minimum_age_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-04-28T00:00:00Z",
        placed_hen_count=10_000,
    )
    assert flock["status"] == "LAYING" and flock["age_weeks"] == 18

    validate_error(api.molt_flock(flock["id"], PLANNER), ERR.ERR_MOLT_NOT_ALLOWED)
    after = read_flock(flock["id"])
    assert after["status"] == "LAYING"
    assert after["molt_count"] == 0


def _setup_molt_cycle_flock(api):
    """60000 hens placed at age 0 on 2026-09-01, advanced 50 weeks by run-ops:
    LAYING at age 50 with the conventional bucket holding 977577 dozen."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Molt Ridge", region_code="WEST")
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-09-01T00:00:00Z",
        placed_hen_count=60_000,
    )
    set_clock("2027-08-17T00:00:00Z")
    complex_mid = run_ops(complex_["id"])
    assert complex_mid["ungraded_conventional_dozen"] == 977_577, (
        f"setup bucket {complex_mid['ungraded_conventional_dozen']} != 977577"
    )
    flock_mid = read_flock(flock["id"])
    assert flock_mid["status"] == "LAYING" and flock_mid["age_weeks"] == 50
    assert flock_mid["current_hen_count"] == 57_097
    return complex_, house, flock, complex_mid["ungraded_conventional_dozen"]


def test_molt_cycle_laying_molt_laying_with_zero_molt_accrual(api):
    """The LAYING -> MOLT -> LAYING loop returns to the prior state with
    molt_count 1; the four molt weeks accrue nothing and the post-molt week
    lays at 0.85 * 0.95.

    PRD §3.2: "A planner may also induce a molt on a `LAYING` flock, but only
    when the flock is at least fifty weeks old and has never molted".
    PRD §3.2: "(2) otherwise, if it is in `MOLT` and at least four weeks have
    elapsed since `molt_start_age_weeks`, it returns to `LAYING` with
    `molt_count` set to 1 and `molt_start_age_weeks` cleared".
    PRD §3.2: "Once a flock has completed a molt — `molt_count` of 1 — the
    band rate is multiplied by 0.95 from the week of its return to lay
    onward."

    Design: Difficulty/non_linear_state_machine/flock_molt_cycle_laying_molt_laying
    """
    complex_, _, flock, bucket_pre = _setup_molt_cycle_flock(api)

    molted = validate_success(api.molt_flock(flock["id"], PLANNER))
    assert molted["status"] == "MOLT"
    assert molted["molt_start_age_weeks"] == 50

    set_clock("2027-09-21T00:00:00Z")  # +35 days = 5 weeks
    complex_post = run_ops(complex_["id"])
    bucket_post = complex_post["ungraded_conventional_dozen"]

    flock_after = read_flock(flock["id"])
    assert flock_after["status"] == "LAYING"
    assert flock_after["molt_count"] == 1
    assert flock_after["molt_start_age_weeks"] is None
    assert flock_after["age_weeks"] == 55
    # Exactly one laying week accrued in the second checkpoint: age 54 at
    # the post-molt rate 0.85 * 0.95 over 56871 hens -> 26788 dozen.
    assert bucket_post - bucket_pre == 26_788


def test_second_molt_rejected_after_cycle(api):
    """The loop is single-shot: a second molt attempt earns
    ERR_MOLT_NOT_ALLOWED.

    PRD §3.2: "A planner may also induce a molt on a `LAYING` flock, but only
    when the flock is at least fifty weeks old and has never molted; otherwise
    the request is `ERR_MOLT_NOT_ALLOWED`, which is also what a second molt
    attempt earns."

    Design: Difficulty/non_linear_state_machine/flock_molt_cycle_laying_molt_laying
    """
    complex_, _, flock, _ = _setup_molt_cycle_flock(api)
    validate_success(api.molt_flock(flock["id"], PLANNER))
    set_clock("2027-09-21T00:00:00Z")
    run_ops(complex_["id"])
    assert read_flock(flock["id"])["status"] == "LAYING"

    response = api.molt_flock(flock["id"], PLANNER)
    validate_error(response, ERR.ERR_MOLT_NOT_ALLOWED)
    after = read_flock(flock["id"])
    assert after["status"] == "LAYING"
    assert after["molt_count"] == 1


def test_capacity_projection_offsets_and_age_exclusion(api):
    """The projection freezes hens at the current count, so offsets 0 and 4
    agree; age 51 drops to the 0.85 band; a projected age of 80 excludes the
    flock entirely.

    PRD §3.6: "for each, the projected age is `age_weeks` plus the offset, a
    projected age of eighty or more excludes the flock, a projected age below
    eighteen contributes zero, and otherwise the flock contributes the
    whole-dozen floor of its `current_hen_count` times the lay rate at that
    projected age and molt state, times seven, divided by twelve."
    PRD §3.6: "The projection deliberately freezes each flock at its current
    hen count — future mortality is ignored".

    Design: Corner/calculations/capacity_projection_offsets_and_age_exclusion
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Projection Farm")
    house = create_house(complex_["id"], capacity_hens=100_000)
    flock = create_and_place_flock(
        house["id"], placement_date="2026-02-17T00:00:00Z",
        placed_hen_count=50_000,
    )
    assert flock["age_weeks"] == 28 and flock["status"] == "LAYING"

    def projected(offset):
        data = validate_success(
            api.get_capacity_projection(complex_["id"], offset, PLANNER)
        )
        assert data["week_offset"] == offset
        return data

    p0 = projected(0)
    assert p0["total_dozen"] == 26_833  # floor(50000 * 0.92 * 7 / 12)
    p4 = projected(4)
    assert p4["total_dozen"] == 26_833  # hens frozen: identical to offset 0
    p23 = projected(23)
    assert p23["total_dozen"] == 24_791  # age 51: the 0.85 band
    p52 = projected(52)
    assert p52["total_dozen"] == 0  # projected age 80: auto-deplete exclusion
    for projection in (p0, p4, p23, p52):
        assert projection["conventional_dozen"] == projection["total_dozen"]
        assert projection["cage_free_dozen"] == 0
        assert projection["organic_dozen"] == 0


def test_projection_excludes_planned_and_terminal_flocks(api):
    """Only GROWING / LAYING / MOLT flocks enter the projection; PLANNED and
    CANCELLED contribute nothing even while the complex is QUARANTINE.

    PRD §3.6: "Given a `week_offset` from 0 to 52, the projection walks the
    complex's flocks in `GROWING`, `LAYING`, or `MOLT`".
    PRD §3.3: "Link two: every `PLANNED` flock of the complex is cancelled to
    `CANCELLED`".

    Design: Corner/calculations/projection_excludes_planned_and_terminal_flocks
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Empty Barns")
    house1 = create_house(complex_["id"], house_code="H1", capacity_hens=100_000)
    house2 = create_house(complex_["id"], house_code="H2", capacity_hens=50_000)
    flock = create_planned_flock(
        house1["id"], placement_date="2026-12-01T00:00:00Z",
        placed_hen_count=80_000,
    )
    # Quarantine cascade on the empty second house cancels the PLANNED flock.
    event = create_disease_event(
        complex_["id"], [house2["id"]], pathogen="NEWCASTLE"
    )
    confirm_disease_event(event["id"])
    assert read_flock(flock["id"])["status"] == "CANCELLED"

    data = validate_success(
        api.get_capacity_projection(complex_["id"], 0, PLANNER)
    )
    assert data["total_dozen"] == 0
    assert data["conventional_dozen"] == 0
