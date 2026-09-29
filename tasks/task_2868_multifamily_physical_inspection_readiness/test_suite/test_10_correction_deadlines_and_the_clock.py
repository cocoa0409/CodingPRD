"""The twenty-four-hour obligation and the exclusive clock boundary.

The correction deadline is inclusive - a repair landing on the deadline instant
counts - while the overdue trip is exclusive, so the two rules disagree by
exactly one millisecond on the same instant.
"""

from test_helpers import (
    ApiErrorId,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    constants as K,
    factories as F,
    fixtures as X,
)

MAPLE_ONE_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 2,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
CEDAR_UNIT = [
    {"unit_number": "101", "bedroom_count": 1, "occupancy_status": "OCCUPIED"}
]
DUE_AT = "2026-08-04T09:00:00.000Z"
ONE_MILLISECOND_LATE = "2026-08-04T09:00:00.001Z"
FIRST_CORRECTED_AT = "2026-08-04T09:00:00.000Z"
SECOND_CORRECTION_AT = "2026-08-06T09:00:00.000Z"


def _life_threatening_finding(api):
    """A sweep-sourced life-threatening finding due at 2026-08-04T09:00."""
    bundle = X.sweep_lifecycle(
        api,
        "LT_GAS",
        K.MAPLE_COURT,
        MAPLE_ONE_UNIT,
        definition_codes=("LT_GAS",),
        observed_at=K.SWEEP_OBSERVED_AT_1,
    )
    bundle["deficiency"] = X.read_deficiency(api, bundle["deficiency_id"])
    return bundle


def _corrected_severe_finding(api):
    """A severe sweep finding already corrected once, at the deadline instant."""
    bundle = X.sweep_lifecycle(
        api,
        "SEV_WINDOW",
        K.CEDAR_WALK,
        CEDAR_UNIT,
        observed_at=K.SWEEP_OBSERVED_AT_1,
    )
    bundle["corrected"] = assert_ok(
        api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=FIRST_CORRECTED_AT, note="Sash replaced"
            ),
            bundle["owner_headers"],
        )
    )
    return bundle


class TestTheDeadlineInstantIsInclusive:
    """`corrected_at` equal to `correction_due_at` still counts."""

    def test_a_correction_on_the_deadline_instant_is_accepted(self, api):
        """Twenty-four hours after the observation, to the millisecond.

        PRD: "For a deficiency whose `severity` is `LIFE_THREATENING`, the
        supplied `corrected_at` must be no later than the row's
        `correction_due_at`; a correction instant strictly after that deadline is
        rejected with `ERR_LT_CORRECTION_DEADLINE_PASSED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/life_threatening_correction_exactly_at_due_instant_accepted
        """
        bundle = _life_threatening_finding(api)
        assert_instant(
            bundle["deficiency"]["correction_due_at"], DUE_AT, "correction_due_at"
        )

        response = api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=DUE_AT,
                note="Connector replaced at the deadline instant",
            ),
            bundle["owner_headers"],
        )

        corrected = assert_ok(response)
        assert_fields(corrected, status="CORRECTED")
        assert_instant(corrected["corrected_at"], DUE_AT, "corrected_at")
        assert_instant(
            corrected["correction_due_at"], DUE_AT, "correction_due_at"
        )

    def test_the_accepted_correction_clears_the_restricted_posture(self, api):
        """A corrected row leaves all three counted sets, so the gate lifts.

        PRD: "The property recomputes `open_life_threatening_count`,
        `overdue_life_threatening_count` and `open_severe_count` and re-derives
        `readiness_posture`; the cited unit recomputes `open_deficiency_count`"

        PRD: "Deficiencies in `CORRECTED`, `VERIFIED` or `VOIDED` status
        contribute to none of the three."

        Design: Difficulty/boundary_precision_check/life_threatening_correction_exactly_at_due_instant_accepted
        """
        bundle = _life_threatening_finding(api)
        assert_fields(
            X.read_property(api, bundle["property_id"]),
            readiness_posture="RESTRICTED",
            open_life_threatening_count=1,
        )

        response = api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=DUE_AT,
                note="Connector replaced at the deadline instant",
            ),
            bundle["owner_headers"],
        )

        assert_ok(response)
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property,
            open_life_threatening_count=0,
            overdue_life_threatening_count=0,
            readiness_posture="READY",
        )


class TestOneMillisecondPastTheDeadline:
    """The same fixture, one millisecond later, is refused."""

    def test_a_correction_one_millisecond_late_is_rejected(self, api):
        """2026-08-04T09:00:00.001Z is strictly after the deadline.

        PRD: "For a deficiency whose `severity` is `LIFE_THREATENING`, the
        supplied `corrected_at` must be no later than the row's
        `correction_due_at`; a correction instant strictly after that deadline is
        rejected with `ERR_LT_CORRECTION_DEADLINE_PASSED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/life_threatening_correction_one_millisecond_past_due_rejected
        """
        bundle = _life_threatening_finding(api)

        response = api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=ONE_MILLISECOND_LATE, note="One millisecond late"
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.LT_CORRECTION_DEADLINE_PASSED)
        unchanged = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(unchanged, status="OPEN")
        assert_null(unchanged, "corrected_at")

    def test_the_refused_correction_leaves_the_property_restricted(self, api):
        """The life-threatening row is still open, so the posture holds.

        PRD: "Otherwise, if `open_life_threatening_count` is at least 1, the
        posture is `RESTRICTED`."

        Design: Difficulty/boundary_precision_check/life_threatening_correction_one_millisecond_past_due_rejected
        """
        bundle = _life_threatening_finding(api)

        response = api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=ONE_MILLISECOND_LATE, note="One millisecond late"
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.LT_CORRECTION_DEADLINE_PASSED)
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property,
            open_life_threatening_count=1,
            overdue_life_threatening_count=0,
            readiness_posture="RESTRICTED",
        )


class TestTheClockBoundaryIsExclusive:
    """The overdue trip needs the clock strictly past the deadline."""

    def test_the_clock_on_the_due_instant_is_a_no_op(self, api):
        """Exactly `correction_due_at` leaves the row alone, version included.

        PRD: "The boundary is exclusive: a clock value exactly equal to a
        deficiency's `correction_due_at` does **not** trip that deficiency."

        Design: Difficulty/boundary_precision_check/clock_exactly_at_due_instant_does_not_trip_overdue_but_one_millisecond_later_does
        """
        bundle = _life_threatening_finding(api)
        before = bundle["deficiency"]

        X.advance_clock(api, DUE_AT)

        untouched = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(untouched, status="OPEN")
        assert_integer(untouched["version"], before["version"], "version")
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property,
            overdue_life_threatening_count=0,
            readiness_posture="RESTRICTED",
        )

    def test_one_millisecond_later_the_clock_freezes_the_property(self, api):
        """The next millisecond flips the row and the whole posture.

        PRD: "Every `Deficiency` still in `OPEN` status whose
        `correction_due_at` lies strictly before the new clock value transitions
        to `OVERDUE`. The boundary is exclusive"

        PRD: "Each deficiency that flips has its `version` incremented, and every
        property touched by such a flip recomputes
        `overdue_life_threatening_count` and re-derives `readiness_posture`,
        incrementing that property's `version` too."

        Design: Difficulty/boundary_precision_check/clock_exactly_at_due_instant_does_not_trip_overdue_but_one_millisecond_later_does
        """
        bundle = _life_threatening_finding(api)
        X.advance_clock(api, DUE_AT)
        at_boundary = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(at_boundary, status="OPEN")
        assert_fields(
            X.read_property(api, bundle["property_id"]),
            readiness_posture="RESTRICTED",
        )

        X.advance_clock(api, ONE_MILLISECOND_LATE)

        tripped = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(tripped, status="OVERDUE")
        assert_integer(
            tripped["version"], at_boundary["version"] + 1, "version"
        )
        owning_property = X.read_property(api, bundle["property_id"])
        assert_fields(
            owning_property,
            overdue_life_threatening_count=1,
            open_life_threatening_count=1,
            readiness_posture="FROZEN",
        )


class TestCorrectingTwice:
    """`CORRECTED` is not a legal starting point for a correction."""

    def test_a_second_correction_cannot_move_the_corrected_at_forward(self, api):
        """A late repeat call must not launder the original instant.

        PRD: "The deficiency's `status` must be `OPEN` or `OVERDUE`, else
        `ERR_DEFICIENCY_INVALID_STATE` (HTTP 409)."

        Design: Corner/errors/correcting_an_already_corrected_deficiency_is_rejected_as_invalid_state
        """
        bundle = _corrected_severe_finding(api)
        assert_fields(bundle["corrected"], status="CORRECTED")

        response = api.record_correction(
            bundle["deficiency_id"],
            F.correction_payload(
                corrected_at=SECOND_CORRECTION_AT, note="Second attempt"
            ),
            bundle["owner_headers"],
        )

        assert_error(response, ApiErrorId.DEFICIENCY_INVALID_STATE)
        unchanged = X.read_deficiency(api, bundle["deficiency_id"])
        assert_fields(unchanged, status="CORRECTED")
        assert_instant(
            unchanged["corrected_at"], FIRST_CORRECTED_AT, "corrected_at"
        )
        assert_fields(
            X.read_property(api, bundle["property_id"]), open_severe_count=0
        )
