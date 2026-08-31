"""Work permits: the lead-time rule, the decision fork, revocation and expiry."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_work_permit,
    create_party,
    create_permit,
    brief_party,
    read_party,
    read_permit,
    setup_approved_plan,
    setup_briefed_party,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def test_permit_request_with_exactly_the_required_lead_time_is_accepted(api):
    """PRD 3.5: "The number of whole days separating the logical clock date from `window_start_date` must be greater than or equal to the governing agency's `permit_lead_days`, and the comparison is inclusive — a gap of exactly the required number of days is accepted."
    PRD 3.5: "On creation the permit copies the `land_manager_id` from the segment, lands in `REQUESTED`, and leaves `allowed_work_types`, `max_party_size`, `issued_by_user_id`, `issued_at`, `denial_reason` and `revocation_reason` null with `consumed_party_count` at 0."

    Design: Difficulty/boundary_precision_check/permit_lead_time_inclusive_at_exactly_fourteen_days
    """
    world = setup_approved_plan()

    accepted = validate_success(
        api.create_work_permit(
            {
                "work_plan_id": world["plan_id"],
                "trail_segment_id": world["seg_id"],
                "window_start_date": "2026-08-15",
                "window_end_date": "2026-08-20",
                "requested_work_types": ["TREAD_WORK"],
            },
            world["lead_headers"],
        ),
        201,
    )
    assert_work_permit(accepted)
    assert accepted["status"] == "REQUESTED"
    assert accepted["window_start_date"] == "2026-08-15"
    assert accepted["land_manager_id"] == world["lm_id"]
    assert accepted["consumed_party_count"] == 0


def test_permit_request_one_day_short_of_the_lead_time_is_refused(api):
    """PRD 3.5: "Anything shorter is refused with `ERR_PERMIT_LEAD_TIME_INSUFFICIENT`."
    PRD 3.5: "For an agency running the default two-week notice period, a request logged on the first of a month for work starting on the fifteenth is exactly on the line and is accepted; work starting on the fourteenth is not."

    Design: Difficulty/boundary_precision_check/permit_lead_time_inclusive_at_exactly_fourteen_days
    """
    world = setup_approved_plan()

    response = api.create_work_permit(
        {
            "work_plan_id": world["plan_id"],
            "trail_segment_id": world["seg_id"],
            "window_start_date": "2026-08-14",
            "window_end_date": "2026-08-20",
            "requested_work_types": ["TREAD_WORK"],
        },
        world["lead_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PERMIT_LEAD_TIME_INSUFFICIENT.value, 422)


def test_denying_a_permit_records_the_reason_and_blocks_the_referencing_party(api):
    """PRD 3.5: "Denying instead moves the permit `REQUESTED → DENIED`, requires a non-empty `denial_reason`, stores that reason together with `issued_by_user_id`, and pushes every referencing work party whose `schedule_status` is `PLANNED` or `CONFIRMED` into `readiness_status` `BLOCKED` with `block_reason` `PERMIT_REVOKED`."

    Design: Corner/state_machines/permit_denied_branch_records_reason_and_blocks_referencing_party
    """
    world = setup_approved_plan()
    permit = create_permit(
        world["plan_id"],
        world["seg_id"],
        world["lead_id"],
        requested_work_types=["TREAD_WORK"],
    )
    party = create_party(
        world["plan_id"], world["seg_id"], world["lead_id"], permit["id"]
    )
    brief_party(party["id"], world["lead_id"])

    denied = validate_success(
        api.decide_work_permit(
            permit["id"],
            {"decision": "DENY", "denial_reason": "Spotted owl seasonal restriction."},
            world["lm_headers"],
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "Spotted owl seasonal restriction."
    assert denied["allowed_work_types"] is None
    assert denied["max_party_size"] is None

    blocked = read_party(party["id"])
    assert blocked["readiness_status"] == "BLOCKED"
    assert blocked["block_reason"] == "PERMIT_REVOKED"
    assert blocked["schedule_status"] == "PLANNED"


def test_a_revoked_permit_cannot_be_revoked_a_second_time(api):
    """PRD 3.5: "Revocation is the officer's emergency brake on an already-issued permit, moving it `ISSUED → REVOKED`."
    PRD 3.5: "`DENIED`, `CONSUMED`, `EXPIRED` and `REVOKED` are all terminal."
    PRD 2.7: "State legality — the target resource currently sits in a state from which the requested transition is declared, terminal states included, otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/revoked_permit_cannot_be_revoked_again_terminal_lockdown
    """
    world = setup_briefed_party()

    revoked = validate_success(
        api.revoke_work_permit(
            world["permit_id"],
            {"revocation_reason": "Elk calving closure."},
            world["lm_headers"],
        )
    )
    assert revoked["status"] == "REVOKED"

    response = api.revoke_work_permit(
        world["permit_id"], {"revocation_reason": "Duplicate revoke."}, world["lm_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    stored = read_permit(world["permit_id"])
    assert stored["revocation_reason"] == "Elk calving closure.", (
        "the second attempt must not overwrite the stored reason"
    )


def test_clock_advance_past_the_window_expires_the_permit_and_blocks_its_party(api):
    """PRD 3.5: "A clock advance that carries the date strictly past `window_end_date` moves an `ISSUED` permit to `EXPIRED`, and every referencing party in `PLANNED` or `CONFIRMED` acquires `readiness_status` `BLOCKED` with `block_reason` `PERMIT_EXPIRED`."
    PRD 2.5: "The response to a clock advance reports the resulting `current_utc`, together with `segments_recomputed`, `permits_expired` and `parties_blocked` counts describing what the sweep touched."

    Design: Corner/state_machines/issued_permit_expires_on_clock_advance_and_blocks_party
    """
    world = setup_briefed_party()

    advance = validate_success(
        api.set_clock({"to_iso8601": "2026-10-01T00:00:00.000Z"}, COORD)
    )
    assert advance["current_utc"] == "2026-10-01T00:00:00.000Z"
    assert advance["permits_expired"] == 1
    assert advance["parties_blocked"] == 1

    assert read_permit(world["permit_id"])["status"] == "EXPIRED"
    party = read_party(world["party_id"])
    assert party["readiness_status"] == "BLOCKED"
    assert party["block_reason"] == "PERMIT_EXPIRED"
