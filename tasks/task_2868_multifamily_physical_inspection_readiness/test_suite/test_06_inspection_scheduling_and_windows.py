"""Scheduling an inspection: the buffered window scan and its rivals.

Inspection windows are compared as closed intervals expanded by a 72-hour
cooldown at each end, and the referential check on the cited standard answers
before that temporal scan ever runs.
"""

from test_helpers import (
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_total_count,
    constants as K,
    factories as F,
    fixtures as X,
)

BUFFER_TOUCH_START = "2026-09-16T17:00:00.000Z"
BUFFER_TOUCH_END = "2026-09-17T09:00:00.000Z"
BUFFER_CLEAR_START = "2026-09-16T17:00:00.001Z"
CROWDING_START = "2026-09-11T09:00:00.000Z"
CROWDING_END = "2026-09-11T17:00:00.000Z"
CEDAR_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 1,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
MAPLE_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
DRAFT_STANDARD = {
    "code": "NSPIRE-2027",
    "name": "NSPIRE 2027 draft",
    "effective_date": "2027-01-01T00:00:00.000Z",
    "unit_weight_pct": 40.00,
    "inside_weight_pct": 35.00,
    "outside_weight_pct": 25.00,
}


def _property_holding_one_inspection(api, blueprint, unit_specs):
    """An adopted standard, a property, and one SCHEDULED inspection on it."""
    bundle = X.adopted_standard(api, ("LT_GAS",))
    bundle.update(X.property_with_units(api, blueprint, unit_specs))
    bundle["first_inspection"] = X.scheduled_inspection(
        api, bundle["property_id"], bundle["standard_id"]
    )
    bundle["first_inspection_id"] = bundle["first_inspection"]["id"]
    return bundle


class TestBufferedWindowConflict:
    """The 72-hour cooldown is applied to both windows, closed-interval."""

    def test_expanded_windows_touching_at_one_instant_conflict(self, api):
        """Six clear days apart still collides once both ends are buffered.

        PRD: "A requested window conflicts if the interval from
        `scheduled_start` to `scheduled_end`, expanded by a 72-hour cooldown
        buffer at each end, intersects the identically expanded window of any
        other inspection on the same property whose `status` is anything other
        than `CANCELLED` or `CLOSED`. The arithmetic is closed-interval: two
        expanded intervals that merely touch at an endpoint **do** conflict."

        Design: Difficulty/resource_temporal_overlap/inspection_window_rejected_when_expanded_buffers_touch_at_exactly_one_instant
        """
        bundle = _property_holding_one_inspection(api, K.CEDAR_WALK, CEDAR_UNIT)

        response = api.create_inspection(
            F.inspection_payload(
                bundle["property_id"],
                bundle["standard_id"],
                scheduled_start=BUFFER_TOUCH_START,
                scheduled_end=BUFFER_TOUCH_END,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.INSPECTION_WINDOW_CONFLICT)
        rows = assert_total_count(
            api.list_inspections(X.INSPECTOR, property_id=bundle["property_id"]),
            1,
        )
        assert [row["id"] for row in rows] == [bundle["first_inspection_id"]]

    def test_one_millisecond_later_the_same_window_is_accepted(self, api):
        """Nudging the request 1ms clears the touching endpoint.

        PRD: "A conflict is rejected with `ERR_INSPECTION_WINDOW_CONFLICT` (HTTP
        409). Cancelled and closed inspections are invisible to this check, so a
        cancelled visit does not block its own replacement."

        Design: Difficulty/resource_temporal_overlap/inspection_window_rejected_when_expanded_buffers_touch_at_exactly_one_instant
        """
        bundle = _property_holding_one_inspection(api, K.CEDAR_WALK, CEDAR_UNIT)
        assert_error(
            api.create_inspection(
                F.inspection_payload(
                    bundle["property_id"],
                    bundle["standard_id"],
                    scheduled_start=BUFFER_TOUCH_START,
                    scheduled_end=BUFFER_TOUCH_END,
                ),
                X.INSPECTOR,
            ),
            ApiErrorId.INSPECTION_WINDOW_CONFLICT,
        )

        response = api.create_inspection(
            F.inspection_payload(
                bundle["property_id"],
                bundle["standard_id"],
                scheduled_start=BUFFER_CLEAR_START,
                scheduled_end=BUFFER_TOUCH_END,
            ),
            X.INSPECTOR,
        )

        accepted = assert_created(response)
        assert_fields(accepted, status="SCHEDULED")
        assert_instant(
            accepted["scheduled_start"], BUFFER_CLEAR_START, "scheduled_start"
        )
        rows = assert_total_count(
            api.list_inspections(X.INSPECTOR, property_id=bundle["property_id"]),
            2,
        )
        assert set(row["id"] for row in rows) == {
            bundle["first_inspection_id"],
            accepted["id"],
        }


class TestSchedulingPrecedence:
    """A DRAFT standard answers before the buffered window scan is consulted."""

    def test_a_draft_standard_answers_before_the_window_conflict(self, api):
        """Both faults are 409s; the referential one wins.

        PRD: "The cited standard must be in `ADOPTED`, else
        `ERR_STANDARD_NOT_ADOPTED`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_inspection_rejected_with_standard_not_adopted_not_window_conflict
        """
        bundle = _property_holding_one_inspection(api, K.MAPLE_COURT, MAPLE_UNIT)
        draft = X.draft_standard(api, ("LT_GAS",), **DRAFT_STANDARD)
        assert_fields(draft["standard"], adoption_status="DRAFT")

        response = api.create_inspection(
            F.inspection_payload(
                bundle["property_id"],
                draft["standard_id"],
                scheduled_start=CROWDING_START,
                scheduled_end=CROWDING_END,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.STANDARD_NOT_ADOPTED)
        assert_total_count(
            api.list_inspections(X.INSPECTOR, standard_id=draft["standard_id"]),
            0,
        )

    def test_the_rejected_request_leaves_one_inspection_on_the_property(self, api):
        """The refused schedule writes nothing at all.

        PRD: "A new inspection begins in `SCHEDULED` with `drawn_at`,
        `started_at`, `scored_at`, `rescored_at` and `finalized_at` all null,
        `sample_tier_value` and `sample_size` at 0, `inspected_unit_count` and
        `refused_unit_count` at 0"

        Design: Difficulty/priority_pair_validation_conflict/schedule_inspection_rejected_with_standard_not_adopted_not_window_conflict
        """
        bundle = _property_holding_one_inspection(api, K.MAPLE_COURT, MAPLE_UNIT)
        draft = X.draft_standard(api, ("LT_GAS",), **DRAFT_STANDARD)

        response = api.create_inspection(
            F.inspection_payload(
                bundle["property_id"],
                draft["standard_id"],
                scheduled_start=CROWDING_START,
                scheduled_end=CROWDING_END,
            ),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.STANDARD_NOT_ADOPTED)
        rows = assert_total_count(
            api.list_inspections(X.INSPECTOR, property_id=bundle["property_id"]),
            1,
        )
        assert [row["id"] for row in rows] == [bundle["first_inspection_id"]]
        survivor = X.read_inspection(api, bundle["first_inspection_id"])
        assert_fields(survivor, status="SCHEDULED", sample_size=0)
        assert_null(survivor, "drawn_at", "started_at")


class TestStartingOnSite:
    """The walk may only begin from NOTIFIED."""

    def test_starting_an_unsampled_inspection_is_rejected(self, api):
        """A SCHEDULED inspection cannot skip sampling and notice.

        PRD: "The inspector begins the walk by supplying the `started_at`
        instant. Three conditions hold: the inspection's `status` is `NOTIFIED`;
        the property's `readiness_posture` is not `FROZEN`, else
        `ERR_PROPERTY_FROZEN`; and every slot with `selection_status` `ACTIVE`
        and `selection_basis` `SAMPLED` has a `notice_lead_hours` of at least
        48.00"

        PRD: "the target row's `status`, `repair_status`, `verification_status`
        or `adoption_status` admits the requested transition, else the state
        error for that resource type: `ERR_STANDARD_ALREADY_ADOPTED`,
        `ERR_INSPECTION_INVALID_STATE`"

        Design: Corner/errors/starting_an_unsampled_inspection_is_rejected_as_invalid_state
        """
        bundle = _property_holding_one_inspection(api, K.CEDAR_WALK, CEDAR_UNIT)
        scheduled = bundle["first_inspection"]
        assert_integer(scheduled["version"], 1, "version")

        response = api.start_inspection(
            bundle["first_inspection_id"],
            F.start_inspection_payload(started_at=K.INSPECTION_STARTED_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.INSPECTION_INVALID_STATE)
        unchanged = X.read_inspection(api, bundle["first_inspection_id"])
        assert_fields(unchanged, status="SCHEDULED", version=1)
        assert_null(unchanged, "started_at")
