"""Coincident objections, and which rung of the ladder the server reports."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CORRIDOR_STATION_CONFLICT,
    ERR_EXTENSION_LIMIT_REACHED,
    ERR_INVALID_STATE,
    ERR_LANDOWNER_PAYMENT_HOLD,
    ERR_OPTION_EXPIRED,
    ERR_TITLE_CURATIVE_BLOCKING,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_null,
    assert_status,
)
from test_helpers.factories import crossing_payload, exercise_payload
from test_helpers.fixtures import (
    advance_option_to_executed,
    amend_landowner,
    caprock_qualified_parcel,
    client,
    crossings_on_corridor,
    draft_option,
    extend_option,
    ledger_rows,
    leases_for_option,
    plan_corridor,
    propose_crossing,
    raise_curative,
    read_landowner,
    read_option,
    read_parcel,
    register_parcel,
    set_clock,
)
from test_helpers.test_users import LAND_AGENT, PORTFOLIO_MANAGER, PORTFOLIO_MANAGER_2


def _expired_option_under_a_hold():
    """A thirty-day option run past its expiry while its owner is on hold."""
    setup = caprock_qualified_parcel()
    landowner_id = setup["landowner"]["id"]
    option = draft_option(
        setup["parcel"]["id"], landowner_id, option_term_days=30, extension_count_allowed=2
    )
    executed = advance_option_to_executed(option["id"], landowner_id)
    assert_instant_equals(
        executed["option_expiry_at"], "2026-08-31T00:00:00Z", "option_expiry_at"
    )
    held = amend_landowner(landowner_id, payment_hold=True)
    assert held["payment_hold"] is True
    sweeps = set_clock("2026-09-01T00:00:00Z")
    assert sweeps["expired_option_count"] == 1
    return landowner_id, option["id"]


def _exhausted_option_under_a_hold():
    """A one-extension option that already spent it, whose owner is on hold."""
    setup = caprock_qualified_parcel()
    landowner_id = setup["landowner"]["id"]
    option = draft_option(
        setup["parcel"]["id"],
        landowner_id,
        option_term_days=365,
        extension_count_allowed=1,
        base_rent_per_acre_cents=120000,
    )
    executed = advance_option_to_executed(option["id"], landowner_id)
    assert_cents_equals(
        executed["total_option_paid_cents"], 312500, "total_option_paid_cents"
    )
    extended = extend_option(option["id"])
    assert extended["extensions_used"] == 1
    assert_cents_equals(
        extended["total_option_paid_cents"], 687500, "total_option_paid_cents"
    )
    assert_instant_equals(
        extended["option_expiry_at"], "2028-01-28T00:00:00Z", "option_expiry_at"
    )
    held = amend_landowner(landowner_id, payment_hold=True)
    assert held["payment_hold"] is True
    return landowner_id, option["id"]


def _title_blocked_and_station_conflicted():
    """A corridor already crossed, plus a second parcel with a blocking defect."""
    setup = caprock_qualified_parcel()
    clean_parcel_id = setup["parcel"]["id"]
    blocked_parcel = register_parcel(
        setup["landowner"]["id"],
        apn="R-1188-007",
        county_fips="48453",
        gross_acres=90.00,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    raise_curative(
        blocked_parcel["id"],
        item_type="TAX_LIEN",
        severity="BLOCKING",
        curative_cost_cents=190000,
    )
    corridor = plan_corridor()
    first_crossing = propose_crossing(corridor["id"], clean_parcel_id)
    return corridor, clean_parcel_id, blocked_parcel["id"], first_crossing


def test_an_expired_option_reports_its_expiry_rather_than_the_payment_hold():
    """
    Two independent objections are live on the same exercise: the instrument has
    run out of term and the owner's money is frozen. The caller is told the option
    is dead.

    PRD: "On an option exercise, an option whose term has run out reports
    `ERR_OPTION_EXPIRED` **in preference to** `ERR_LANDOWNER_PAYMENT_HOLD`, even
    when the landowner is also under a payment hold. Instrument staleness
    outranks money."

    Design: Difficulty/priority_pair_validation_conflict/expired_option_beats_payment_hold_on_exercise
    """
    landowner_id, option_id = _expired_option_under_a_hold()

    response = client().exercise_option(
        option_id, exercise_payload("NOL-2982-0004"), PORTFOLIO_MANAGER_2
    )

    error = validate_error(response, ERR_OPTION_EXPIRED, 422)
    assert read_landowner(landowner_id)["payment_hold"] is True
    assert error["error_id"] != ERR_LANDOWNER_PAYMENT_HOLD


def test_expiry_outranks_the_generic_state_rule_and_no_lease_is_minted():
    """
    The clock advance also drove the agreement to expired, so the generic
    from-state rung was true as well; it is never even evaluated, and the refused
    exercise originates nothing.

    PRD: "When more than one objection to a request is true, the server reports
    **exactly one** — the objection with the lowest priority number in the ladder
    below. Evaluation stops at the first violated rung; no later rung is even
    evaluated."

    Design: Difficulty/priority_pair_validation_conflict/expired_option_beats_payment_hold_on_exercise
    """
    _landowner_id, option_id = _expired_option_under_a_hold()
    assert_status(read_option(option_id), "EXPIRED", "option")

    response = client().exercise_option(
        option_id, exercise_payload("NOL-2982-0004"), PORTFOLIO_MANAGER_2
    )

    error = validate_error(response, ERR_OPTION_EXPIRED, 422)
    assert error["error_id"] != ERR_INVALID_STATE
    option = read_option(option_id)
    assert_status(option, "EXPIRED", "option")
    assert_null(option["exercised_at"], "exercised_at")
    assert leases_for_option(option_id) == [], "a refused exercise minted a lease"


def test_a_title_blocked_proposal_reports_title_not_the_station_collision():
    """
    The requested crossing is both on a defective parcel and inside another
    crossing's buffered station range and window. Title compliance is reported,
    and the status line shows the title rung's 422 rather than the conflict's 409.

    PRD: "On a crossing-agreement proposal, a parcel with an open blocking title
    defect reports `ERR_TITLE_CURATIVE_BLOCKING` **in preference to**
    `ERR_CORRIDOR_STATION_CONFLICT`, even when the proposed station range and
    window also collide with an existing crossing. Title compliance outranks
    scheduling."

    Design: Difficulty/priority_pair_validation_conflict/title_blocking_beats_corridor_station_conflict
    """
    corridor, clean_parcel_id, blocked_parcel_id, first = (
        _title_blocked_and_station_conflicted()
    )
    assert read_parcel(blocked_parcel_id)["blocking_curative_open_count"] == 1
    assert read_parcel(clean_parcel_id)["blocking_curative_open_count"] == 0
    assert_cents_equals(first["compensation_cents"], 900000, "compensation_cents")

    response = client().create_crossing_agreement(
        crossing_payload(
            corridor["id"],
            blocked_parcel_id,
            station_start_m=1200,
            station_end_m=1400,
            occupancy_window_start="2026-09-10T00:00:00Z",
            occupancy_window_end="2026-09-20T00:00:00Z",
        ),
        LAND_AGENT,
    )

    error = validate_error(response, ERR_TITLE_CURATIVE_BLOCKING, 422)
    assert error["error_id"] != ERR_CORRIDOR_STATION_CONFLICT


def test_the_shadowed_station_conflict_would_have_fired_on_its_own():
    """
    Proposed against the clean parcel instead, the identical station range and
    window are refused as a corridor conflict with a 409 — which is what the
    title rung was shadowing, and the corridor keeps exactly one crossing either
    way.

    PRD: "A conflict exists against any other crossing on the **same** corridor
    in status `PROPOSED` or `GRANTED` when **both** a buffer-expanded station
    overlap and a half-open time overlap hold: the new crossing's
    `station_start_m` is less than the existing crossing's `station_end_m` plus
    the corridor's `buffer_m`, **and** the new crossing's `station_end_m` plus
    that same buffer is greater than the existing crossing's `station_start_m`,
    **and** the new `occupancy_window_start` is before the existing
    `occupancy_window_end`, **and** the new `occupancy_window_end` is after the
    existing `occupancy_window_start`."

    Design: Difficulty/priority_pair_validation_conflict/title_blocking_beats_corridor_station_conflict
    """
    corridor, clean_parcel_id, blocked_parcel_id, first = (
        _title_blocked_and_station_conflicted()
    )
    blocked = read_parcel(blocked_parcel_id)
    assert_acres_equals(blocked["raw_setback_acres"], 18.00, "raw_setback_acres")
    assert_acres_equals(blocked["buildable_acres"], 72.00, "buildable_acres")

    conflict = client().create_crossing_agreement(
        crossing_payload(
            corridor["id"],
            clean_parcel_id,
            station_start_m=1200,
            station_end_m=1400,
            occupancy_window_start="2026-09-10T00:00:00Z",
            occupancy_window_end="2026-09-20T00:00:00Z",
        ),
        LAND_AGENT,
    )
    validate_error(conflict, ERR_CORRIDOR_STATION_CONFLICT, 409)

    blocked_attempt = client().create_crossing_agreement(
        crossing_payload(
            corridor["id"],
            blocked_parcel_id,
            station_start_m=1200,
            station_end_m=1400,
            occupancy_window_start="2026-09-10T00:00:00Z",
            occupancy_window_end="2026-09-20T00:00:00Z",
        ),
        LAND_AGENT,
    )
    validate_error(blocked_attempt, ERR_TITLE_CURATIVE_BLOCKING, 422)

    crossings = crossings_on_corridor(corridor["id"])
    assert [row["id"] for row in crossings] == [first["id"]], (
        f"corridor should carry only {first['id']}, got {[r['id'] for r in crossings]}"
    )


def test_an_exhausted_extension_allowance_outranks_the_payment_hold():
    """
    The option is still well inside its term, so expiry is not in play; the
    contest is genuinely between the allowance it bought and the owner's frozen
    money, and deal structure wins.

    PRD: "On an option extension, an agreement that has already used every
    extension it bought reports `ERR_EXTENSION_LIMIT_REACHED` **in preference
    to** `ERR_LANDOWNER_PAYMENT_HOLD`. Deal structure outranks money."

    Design: Difficulty/priority_pair_validation_conflict/extension_limit_beats_payment_hold
    """
    _landowner_id, option_id = _exhausted_option_under_a_hold()

    response = client().extend_option(option_id, {}, PORTFOLIO_MANAGER)

    error = validate_error(response, ERR_EXTENSION_LIMIT_REACHED, 422)
    assert error["error_id"] != ERR_LANDOWNER_PAYMENT_HOLD
    assert error["error_id"] != ERR_OPTION_EXPIRED
    assert_status(read_option(option_id), "EXECUTED", "option")


def test_a_refused_extension_increments_nothing_and_mints_no_ledger_row():
    """
    The refusal is total: the counter does not move, the paid balances on both the
    agreement and the owner stand still, and no third consideration row appears.

    PRD: "On success `extensions_used` is incremented by 1 and `option_expiry_at`
    is pushed out by a further 180 days."

    Design: Difficulty/priority_pair_validation_conflict/extension_limit_beats_payment_hold
    """
    landowner_id, option_id = _exhausted_option_under_a_hold()
    rows_before = ledger_rows(option_id)
    assert len(rows_before) == 2, f"expected two rows before, got {len(rows_before)}"

    response = client().extend_option(option_id, {}, PORTFOLIO_MANAGER)
    validate_error(response, ERR_EXTENSION_LIMIT_REACHED, 422)

    option = read_option(option_id)
    assert option["extensions_used"] == 1
    assert_cents_equals(
        option["total_option_paid_cents"], 687500, "total_option_paid_cents"
    )
    assert_instant_equals(
        option["option_expiry_at"], "2028-01-28T00:00:00Z", "option_expiry_at"
    )
    assert_cents_equals(
        read_landowner(landowner_id)["total_paid_cents"], 687500, "total_paid_cents"
    )
    assert len(ledger_rows(option_id)) == 2
