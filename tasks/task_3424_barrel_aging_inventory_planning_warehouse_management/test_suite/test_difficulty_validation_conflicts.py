"""Difficulty-design translations: validation-gate priority pairs.

PRD §2.10 pins a deterministic evaluation order across the ten gates and
states that an earlier gate masks every later one, so a request violating two
gates must surface the earlier gate's error.
"""
from test_helpers import (
    ApiErrorId,
    create_active_label,
    create_batch_with_component,
    create_commissioned_rickhouse,
    create_reservation,
    fill_placed_barrel,
    get_barrel_fresh,
    get_blend_batch_fresh,
    get_success_data,
    set_clock,
    setup_program_with_mature_barrel,
    validate_error,
    validate_success,
)


def test_commit_state_error_beats_age_violation(api, master_blender_headers):
    """PRD §2.10: "An earlier gate masks every later one."
    PRD §2.10: "the target entity's current state permits the requested
    transition, checked first; then the cross-entity readiness gates"
    PRD §3.5: "From `VALIDATED`, the commit re-checks that the label is still
    `ACTIVE`, re-checks every component's age at the `scheduled_bottling_date`
    against the same inclusive obligation (a component that has fallen
    under-age fails with `ERR_AGE_STATEMENT_VIOLATION`)"

    Design: Difficulty/priority_pair_validation_conflict/commit_state_error_beats_age_violation
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=1, positions_per_row=1, name="RH-PP",
    )
    barrel = fill_placed_barrel(ctx["slots"][0]["id"], min_maturation_months=12)
    label = create_active_label(name="Decade Reserve", age_statement_years=10, spirit_type="BOURBON")
    batch, _component = create_batch_with_component(
        label["id"], barrel["id"], 50.0, scheduled_bottling_date="2030-09-01T00:00:00Z"
    )

    # The commit violates BOTH gate 6 (batch still PROPOSED, never validated)
    # AND gate 7 (component age at bottling is 2 years < age_statement 10);
    # the state-machine error is evaluated first and masks the compliance one.
    validate_error(
        api.commit_blend_batch(batch["id"], master_blender_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    after = get_blend_batch_fresh(batch["id"])
    assert after["state"] == "PROPOSED", "rejected commit leaves the batch unchanged"
    barrel_after = get_barrel_fresh(barrel["id"])
    assert barrel_after["current_volume_ledger_liters"] == 200.00, "no commit draw happened"


def test_withdraw_safety_error_beats_reserved_referential(api, warehouse_manager_headers):
    """PRD §2.10: "An earlier gate masks every later one."
    PRD §3.4: "Compliance: there must exist a bonded-period report in `FILED`
    or `ACCEPTED` state whose period covers the current instant —
    `period_start` at or before now and `period_end` at or after now —
    otherwise the withdrawal is rejected with `ERR_COVERING_REPORT_NOT_FILED`
    (HTTP 409). Referential: no reservation on this barrel may be `ACTIVE`,
    else `ERR_BARREL_RESERVED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/withdraw_safety_error_beats_reserved_referential
    """
    ctx = setup_program_with_mature_barrel(
        program_overrides={
            "name": "Sponsor Pick",
            "min_quality_score": 0,
            "required_barrel_count": 1,
            "reservation_window_days": 45,
        }
    )
    barrel = ctx["barrel"]
    program = ctx["program"]
    reservation = create_reservation(program["id"], barrel["id"])
    assert reservation["state"] == "ACTIVE"

    set_clock("2028-09-02T00:00:00Z")
    dumped = validate_success(api.dump_barrel(barrel["id"], warehouse_manager_headers))
    assert dumped["maturation_status"] == "DUMPED", (
        "dump is permitted with an ACTIVE reservation; only withdrawal is guarded"
    )

    # The withdrawal violates BOTH gate 7 (no bonded-period report exists at
    # all, so none in FILED/ACCEPTED covers now) AND gate 9 (the barrel's
    # reservation is still ACTIVE); the compliance error masks the referential
    # one.
    validate_error(
        api.withdraw_barrel(barrel["id"], warehouse_manager_headers),
        ApiErrorId.ERR_COVERING_REPORT_NOT_FILED,
    )

    after = get_barrel_fresh(barrel["id"])
    assert after["custody_status"] == "BONDED", "rejected withdrawal leaves custody unchanged"
    reservations = get_success_data(
        api.list_barrel_reservations(barrel["id"], warehouse_manager_headers)
    )
    assert len(reservations) == 1
    assert reservations[0]["state"] == "ACTIVE", "no side effect fired on the rejected withdrawal"
