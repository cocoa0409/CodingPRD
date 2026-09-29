"""Validation-ladder precedence: which error wins when a request breaks two rules.

PRD section 2.8 makes the reported error a contract rather than an accident: the
rungs are evaluated from the top and the first failing rung answers. Each pair
below is exercised twice — once with both defects present, so the higher rung must
answer, and once with only the lower defect present, so the lower rung's own code
is observably reachable through the same endpoint.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTIVITY_NOT_ENDED,
    ERR_ACTIVITY_NOT_SCHEDULED,
    ERR_INVALID_REQUEST,
    ERR_INVENTORY_NOT_FOUND,
    ERR_PLAN_UPDATE_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_VENUE_NOT_EQUITY_ELIGIBLE,
    ERR_VENUE_TIME_CONFLICT,
)
from test_helpers.test_users import DIRECTOR, STAFF
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

# A future evening slot: the logical clock starts at 2026-08-01T00:00:00Z, so an
# activity on 2026-08-20 has not yet ended.
FUTURE_START = "2026-08-20T18:00:00.000Z"
FUTURE_END = "2026-08-20T20:00:00.000Z"
ADJACENT_START = "2026-08-20T20:00:00.000Z"
ADJACENT_END = "2026-08-20T22:00:00.000Z"
OVERLAP_START = "2026-08-20T19:00:00.000Z"
OVERLAP_END = "2026-08-20T21:00:00.000Z"


# --------------------------------------------------------------------------
# Authorization (rung 2) against path resolution (rung 3) on inventory certify
# --------------------------------------------------------------------------
def test_staff_certifying_a_missing_dataset_reports_the_role_error(api):
    """A staff caller aiming the director-only certify endpoint at an unknown id
    is refused for the role, not for the missing row.

    "Validation is therefore a strictly ordered ladder, evaluated from the top,
    and the first rule that fails determines the response."

    Design: Difficulty/priority_pair_validation_conflict/role_check_outranks_path_existence_on_inventory_certify
    """
    plan = fx.create_plan(api)
    fx.create_land_use_inventory(api, plan["id"])

    response = api.certify_inventory_dataset(C.BOGUS_UUID, {}, STAFF)

    validate_error(response, ERR_ROLE_NOT_PERMITTED)


def test_director_certifying_a_missing_dataset_reports_the_path_error(api):
    """With the authorized role in place the same URL reaches path resolution and
    reports the unknown dataset.

    "Every id embedded in the URL path resolves to an existing row, validated
    left to right"

    Design: Difficulty/priority_pair_validation_conflict/role_check_outranks_path_existence_on_inventory_certify
    """
    plan = fx.create_plan(api)
    fx.create_land_use_inventory(api, plan["id"])

    response = api.certify_inventory_dataset(C.BOGUS_UUID, {}, DIRECTOR)

    validate_error(response, ERR_INVENTORY_NOT_FOUND)


def test_neither_rejected_certify_attempt_touches_the_real_dataset(api):
    """Both refusals leave the plan's genuine draft dataset in DRAFT at version 1.

    "A new dataset enters `DRAFT` with `referencing_scenario_count` at zero, and
    the caller's `X-User-ID` is stamped into `authored_by_user_id`."

    Design: Difficulty/priority_pair_validation_conflict/role_check_outranks_path_existence_on_inventory_certify
    """
    plan = fx.create_plan(api)
    dataset = fx.create_land_use_inventory(api, plan["id"])
    assert dataset["status"] == C.INVENTORY_STATUS_DRAFT
    assert dataset["version"] == 1

    validate_error(
        api.certify_inventory_dataset(C.BOGUS_UUID, {}, STAFF), ERR_ROLE_NOT_PERMITTED
    )
    validate_error(
        api.certify_inventory_dataset(C.BOGUS_UUID, {}, DIRECTOR),
        ERR_INVENTORY_NOT_FOUND,
    )

    after = validate_success(api.get_inventory_dataset(dataset["id"], STAFF))
    assert after["status"] == C.INVENTORY_STATUS_DRAFT
    assert after["version"] == 1
    assert after["referencing_scenario_count"] == 0


# --------------------------------------------------------------------------
# Request shape (rung 4) against body foreign keys (rung 5) on dataset creation
# --------------------------------------------------------------------------
def test_illegal_acreage_field_outranks_the_unknown_plan_in_the_body(api):
    """A demographic dataset carrying acreage *and* naming an unknown plan is
    rejected as a schema violation.

    "For a dataset creation the checks run in the ladder order of section 2.8 — the
    shape of the acreage payload first, then the existence of the plan, then the
    plan's not-yet-adopted status, and only then the vintage comparison."

    Design: Difficulty/priority_pair_validation_conflict/input_schema_check_outranks_body_foreign_key_existence
    """
    fx.create_plan(api)

    payload = f.tabular_inventory_payload(
        C.BOGUS_UUID, C.INVENTORY_DEMOGRAPHIC, record_count=4200, vacant_acres=400
    )
    response = api.create_inventory_dataset(payload, STAFF)

    validate_error(response, ERR_INVALID_REQUEST)


def test_dropping_the_illegal_acreage_field_surfaces_the_unknown_plan(api):
    """With the acreage field gone the same unknown plan reference reaches the
    body foreign-key rung.

    "Every foreign key supplied in the body resolves to an existing row"

    Design: Difficulty/priority_pair_validation_conflict/input_schema_check_outranks_body_foreign_key_existence
    """
    fx.create_plan(api)

    payload = f.tabular_inventory_payload(
        C.BOGUS_UUID, C.INVENTORY_DEMOGRAPHIC, record_count=4200
    )
    response = api.create_inventory_dataset(payload, STAFF)

    validate_error(response, ERR_PLAN_UPDATE_NOT_FOUND)


def test_no_dataset_row_survives_either_rejected_creation(api):
    """Neither rejected creation leaves a partial dataset behind on the real plan.

    "Supplying acreage on a non-land-use dataset, or omitting it on a land-use
    one, is a schema violation."

    Design: Difficulty/priority_pair_validation_conflict/input_schema_check_outranks_body_foreign_key_existence
    """
    plan = fx.create_plan(api)

    validate_error(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                C.BOGUS_UUID, C.INVENTORY_DEMOGRAPHIC, record_count=4200,
                vacant_acres=400,
            ),
            STAFF,
        ),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(
                plan["id"], C.INVENTORY_DEMOGRAPHIC, record_count=4200,
                vacant_acres=400,
            ),
            STAFF,
        ),
        ERR_INVALID_REQUEST,
    )

    rows, meta = validate_paginated(api.list_plan_inventory_datasets(plan["id"], STAFF))
    assert meta["total_count"] == 0
    assert rows == []


# --------------------------------------------------------------------------
# State precondition (rung 6) against the logical-clock gate (rung 15)
# --------------------------------------------------------------------------
def test_cancelled_activity_reports_the_state_error_not_the_clock_gate(api):
    """Closing a cancelled activity whose end has not yet arrived reports the
    status guard, which is listed ahead of the clock gate.

    "it is guarded three ways: the activity must be `SCHEDULED`, the logical clock
    must have reached the activity's `end_at` — an activity cannot be closed before
    it has happened, otherwise `ERR_ACTIVITY_NOT_ENDED` — and at least one
    participation record must have been captured, otherwise
    `ERR_NO_PARTICIPATION_RECORDS`."

    Design: Difficulty/priority_pair_validation_conflict/activity_state_check_outranks_clock_gate_on_complete
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(api, turnover_buffer_minutes=0)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Cancelled Workshop",
        venue_id=venue["id"],
        start_at=FUTURE_START,
        end_at=FUTURE_END,
    )
    cancelled = fx.cancel_activity(
        api, activity["id"], reason="Venue lost to a scheduling conflict."
    )
    assert cancelled["status"] == C.ACTIVITY_STATUS_CANCELLED

    response = api.complete_engagement_activity(activity["id"], {}, STAFF)

    validate_error(response, ERR_ACTIVITY_NOT_SCHEDULED)


def test_scheduled_but_unfinished_activity_reports_the_clock_gate(api):
    """A sibling activity that is still scheduled and equally unfinished shows the
    clock gate is reachable through the same endpoint.

    "completing an activity requires the clock to have reached `end_at`
    (`ERR_ACTIVITY_NOT_ENDED`)"

    Design: Difficulty/priority_pair_validation_conflict/activity_state_check_outranks_clock_gate_on_complete
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(api, name="Westside Library Annex", turnover_buffer_minutes=0)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Future Workshop",
        venue_id=venue["id"],
        start_at=FUTURE_START,
        end_at=FUTURE_END,
    )
    assert activity["status"] == C.ACTIVITY_STATUS_SCHEDULED

    response = api.complete_engagement_activity(activity["id"], {}, STAFF)

    validate_error(response, ERR_ACTIVITY_NOT_ENDED)


def test_neither_refused_completion_credits_the_plan_ledger(api):
    """Both refusals leave the two activities in their prior status and the plan's
    weighted participation at zero.

    "Activities still `SCHEDULED` have not been held and are excluded; activities
    `CANCELLED` have been withdrawn from the engagement record and are excluded too."

    Design: Difficulty/priority_pair_validation_conflict/activity_state_check_outranks_clock_gate_on_complete
    """
    plan = fx.create_plan(api)
    venue_a = fx.create_venue(api, name="Eastside Community Room", turnover_buffer_minutes=0)
    venue_b = fx.create_venue(api, name="Westside Library Annex", turnover_buffer_minutes=0)
    dead = fx.create_activity(
        api, plan["id"], activity_type=C.ACTIVITY_WORKSHOP, title="Cancelled Workshop",
        venue_id=venue_a["id"], start_at=FUTURE_START, end_at=FUTURE_END,
    )
    fx.cancel_activity(api, dead["id"], reason="Withdrawn from the engagement record.")
    live = fx.create_activity(
        api, plan["id"], activity_type=C.ACTIVITY_WORKSHOP, title="Future Workshop",
        venue_id=venue_b["id"], start_at=FUTURE_START, end_at=FUTURE_END,
    )

    validate_error(
        api.complete_engagement_activity(dead["id"], {}, STAFF), ERR_ACTIVITY_NOT_SCHEDULED
    )
    validate_error(
        api.complete_engagement_activity(live["id"], {}, STAFF), ERR_ACTIVITY_NOT_ENDED
    )

    assert validate_success(api.get_engagement_activity(dead["id"], STAFF))["status"] == (
        C.ACTIVITY_STATUS_CANCELLED
    )
    assert validate_success(api.get_engagement_activity(live["id"], STAFF))["status"] == (
        C.ACTIVITY_STATUS_SCHEDULED
    )
    after = fx.read_plan(api, plan["id"])
    assert after["participation_weight_total"] == 0.0
    assert after["underrepresented_weight_total"] == 0.0
    assert after["equity_share_pct"] == 0.0

# --------------------------------------------------------------------------
# Venue occupancy (rung 11) against outreach equity eligibility (rung 20)
# --------------------------------------------------------------------------
def test_double_booked_outreach_reports_the_occupancy_conflict(api):
    """An outreach session booked at a non-transit venue over an existing workshop
    reports the occupancy clash, not the equity refusal.

    "Note that this equity test sits well below the venue occupancy test on the
    validation ladder, so a targeted-outreach booking that is both double-booked and
    ineligible reports the occupancy conflict."

    Design: Difficulty/priority_pair_validation_conflict/venue_time_conflict_outranks_equity_eligibility_on_outreach
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(
        api,
        name="Hilltop Grange Hall",
        seated_capacity=60,
        turnover_buffer_minutes=0,
        ada_accessible=True,
        transit_served=False,
    )
    fx.create_activity(
        api, plan["id"], activity_type=C.ACTIVITY_WORKSHOP, title="Hilltop Workshop",
        venue_id=venue["id"], start_at=FUTURE_START, end_at=FUTURE_END,
    )

    response = api.create_engagement_activity(
        f.engagement_activity_payload(
            plan["id"],
            activity_type=C.ACTIVITY_TARGETED_OUTREACH,
            title="Renter Outreach",
            venue_id=venue["id"],
            start_at=OVERLAP_START,
            end_at=OVERLAP_END,
            interpretation_offered=True,
        ),
        STAFF,
    )

    validate_error(response, ERR_VENUE_TIME_CONFLICT)


def test_outreach_moved_clear_of_the_occupied_interval_reports_the_equity_refusal(api):
    """Starting the same outreach session at the exact instant the workshop ends
    clears the occupancy test at a zero buffer, so the equity rule answers.

    "A targeted-outreach session carries an additional equity requirement: its venue
    must be both `transit_served` and `ada_accessible`, and a booking at a venue
    failing either test is refused with `ERR_VENUE_NOT_EQUITY_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/venue_time_conflict_outranks_equity_eligibility_on_outreach
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(
        api,
        name="Hilltop Grange Hall",
        seated_capacity=60,
        turnover_buffer_minutes=0,
        ada_accessible=True,
        transit_served=False,
    )
    fx.create_activity(
        api, plan["id"], activity_type=C.ACTIVITY_WORKSHOP, title="Hilltop Workshop",
        venue_id=venue["id"], start_at=FUTURE_START, end_at=FUTURE_END,
    )

    response = api.create_engagement_activity(
        f.engagement_activity_payload(
            plan["id"],
            activity_type=C.ACTIVITY_TARGETED_OUTREACH,
            title="Renter Outreach",
            venue_id=venue["id"],
            start_at=ADJACENT_START,
            end_at=ADJACENT_END,
            interpretation_offered=True,
        ),
        STAFF,
    )

    validate_error(response, ERR_VENUE_NOT_EQUITY_ELIGIBLE)


def test_only_the_original_workshop_holds_the_ineligible_venue(api):
    """After both refusals the venue's calendar still shows the single workshop.

    "at a venue whose `turnover_buffer_minutes` is 0, an activity starting at the
    exact instant an earlier one ended is allowed, because neither comparison is
    satisfied at the boundary"

    Design: Difficulty/priority_pair_validation_conflict/venue_time_conflict_outranks_equity_eligibility_on_outreach
    """
    plan = fx.create_plan(api)
    venue = fx.create_venue(
        api,
        name="Hilltop Grange Hall",
        seated_capacity=60,
        turnover_buffer_minutes=0,
        ada_accessible=True,
        transit_served=False,
    )
    workshop = fx.create_activity(
        api, plan["id"], activity_type=C.ACTIVITY_WORKSHOP, title="Hilltop Workshop",
        venue_id=venue["id"], start_at=FUTURE_START, end_at=FUTURE_END,
    )

    for start_at, end_at, expected in (
        (OVERLAP_START, OVERLAP_END, ERR_VENUE_TIME_CONFLICT),
        (ADJACENT_START, ADJACENT_END, ERR_VENUE_NOT_EQUITY_ELIGIBLE),
    ):
        validate_error(
            api.create_engagement_activity(
                f.engagement_activity_payload(
                    plan["id"],
                    activity_type=C.ACTIVITY_TARGETED_OUTREACH,
                    title="Renter Outreach",
                    venue_id=venue["id"],
                    start_at=start_at,
                    end_at=end_at,
                    interpretation_offered=True,
                ),
                STAFF,
            ),
            expected,
        )

    rows, meta = validate_paginated(
        api.list_engagement_activities(STAFF, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [workshop["id"]]
    assert rows[0]["status"] == C.ACTIVITY_STATUS_SCHEDULED
