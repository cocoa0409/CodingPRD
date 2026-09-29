"""Tenant notice, the 48-hour lead floor, and recording entry at the door.

Notice is the owner's obligation on their own slots; entry windows on one unit
are compared half-open with no buffer, the mirror image of the inspection
scheduling rule.
"""

from test_helpers import (
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_instant,
    assert_integer,
    assert_null,
    assert_ok,
    assert_two_decimals,
    constants as K,
    factories as F,
    fixtures as X,
)
from test_helpers.test_users import make_property_owner_headers

MAPLE_TWO_UNITS = [
    {"unit_number": "101", "bedroom_count": 2, "occupancy_status": "OCCUPIED"},
    {"unit_number": "102", "bedroom_count": 1, "occupancy_status": "OCCUPIED"},
]
CEDAR_UNIT = [
    {
        "unit_number": "101",
        "bedroom_count": 1,
        "occupancy_status": "OCCUPIED",
        "occupant_display_name": "Household 101",
    }
]
FIRST_NOTIFIED_AT = "2026-08-05T09:00:00.000Z"
SECOND_NOTIFIED_AT = "2026-08-05T09:30:00.000Z"
MORNING_WINDOW = ("2026-09-10T09:00:00.000Z", "2026-09-10T11:00:00.000Z")
MIDDAY_WINDOW = ("2026-09-10T11:00:00.000Z", "2026-09-10T13:00:00.000Z")
TOUCHING_FIRST_WINDOW = ("2026-09-10T09:00:00.000Z", "2026-09-10T12:00:00.000Z")
TOUCHING_SECOND_WINDOW = ("2026-09-10T12:00:00.000Z", "2026-09-10T15:00:00.000Z")
LATE_INSPECTION_START = "2026-09-20T09:00:00.000Z"
LATE_INSPECTION_END = "2026-09-20T17:00:00.000Z"
SECOND_DRAWN_AT = "2026-08-02T00:10:00.000Z"
SHORT_LEAD_NOTIFIED_AT = "2026-09-09T09:00:00.000Z"
EXACT_LEAD_NOTIFIED_AT = "2026-09-08T09:00:00.000Z"
FULL_DAY_WINDOW = ("2026-09-10T09:00:00.000Z", "2026-09-10T17:00:00.000Z")
GRANT_RECORDED_AT = "2026-09-10T09:05:00.000Z"
REFUSAL_RECORDED_AT = "2026-09-10T11:05:00.000Z"


def _maple_two_slots_sampled(api):
    """A two-slot SAMPLED inspection, neither slot noticed yet."""
    bundle = X.adopted_standard(api, ("LT_GAS",))
    bundle.update(X.property_with_units(api, K.MAPLE_COURT, MAPLE_TWO_UNITS))
    sampled = X.sampled_inspection(
        api, bundle["property_id"], bundle["standard_id"]
    )
    bundle["inspection_id"] = sampled["inspection_id"]
    bundle["first_slot"] = sampled["slots"][bundle["unit_ids"]["101"]]
    bundle["second_slot"] = sampled["slots"][bundle["unit_ids"]["102"]]
    return bundle


def _notice(api, bundle, slot, notified_at, window):
    return api.issue_notice(
        slot["id"],
        F.notice_payload(
            notice_method="POSTED_AND_MAILED",
            notified_at=notified_at,
            access_window_start=window[0],
            access_window_end=window[1],
        ),
        bundle["owner_headers"],
    )


def _maple_two_slots_in_progress(api):
    """Both slots noticed on adjoining windows, and the walk under way."""
    bundle = _maple_two_slots_sampled(api)
    assert_ok(
        _notice(
            api, bundle, bundle["first_slot"], FIRST_NOTIFIED_AT, MORNING_WINDOW
        )
    )
    assert_ok(
        _notice(
            api, bundle, bundle["second_slot"], SECOND_NOTIFIED_AT, MIDDAY_WINDOW
        )
    )
    bundle["inspection"] = assert_ok(
        api.start_inspection(
            bundle["inspection_id"],
            F.start_inspection_payload(started_at=K.INSPECTION_STARTED_AT),
            X.INSPECTOR,
        )
    )
    return bundle


def _two_inspections_sampling_one_unit(api):
    """Two inspections of one property, each holding a slot on unit 101."""
    bundle = X.adopted_standard(api, ("LT_GAS",))
    bundle.update(X.property_with_units(api, K.CEDAR_WALK, CEDAR_UNIT))
    unit_id = bundle["unit_ids"]["101"]
    first = X.sampled_inspection(
        api, bundle["property_id"], bundle["standard_id"]
    )
    second_inspection = assert_created(
        api.create_inspection(
            F.inspection_payload(
                bundle["property_id"],
                bundle["standard_id"],
                scheduled_start=LATE_INSPECTION_START,
                scheduled_end=LATE_INSPECTION_END,
            ),
            X.INSPECTOR,
        )
    )
    assert_ok(
        api.draw_sample(
            second_inspection["id"],
            F.draw_sample_payload(drawn_at=SECOND_DRAWN_AT),
            X.INSPECTOR,
        )
    )
    bundle["first_inspection_id"] = first["inspection_id"]
    bundle["second_inspection_id"] = second_inspection["id"]
    bundle["first_slot"] = first["slots"][unit_id]
    bundle["second_slot"] = X.selections_by_unit(
        api, second_inspection["id"]
    )[unit_id]
    assert_ok(
        _notice(
            api,
            bundle,
            bundle["first_slot"],
            FIRST_NOTIFIED_AT,
            TOUCHING_FIRST_WINDOW,
        )
    )
    return bundle


class TestTenantNotice:
    """The parent inspection moves only when the last slot is noticed."""

    def test_the_last_outstanding_notice_bubbles_the_inspection(self, api):
        """The first notice leaves SAMPLED; the second reaches NOTIFIED.

        PRD: "If the owning inspection is in `SAMPLED` and, after this write,
        every one of its slots with `selection_status` `ACTIVE` has
        `access_status` `NOTIFIED`, the inspection bubbles `SAMPLED -> NOTIFIED`
        with its `version` incremented by 1."

        Design: Corner/state_machines/notice_on_the_last_active_slot_bubbles_the_inspection_to_notified
        """
        bundle = _maple_two_slots_sampled(api)
        assert_ok(
            _notice(
                api,
                bundle,
                bundle["first_slot"],
                FIRST_NOTIFIED_AT,
                MORNING_WINDOW,
            )
        )
        after_first = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(after_first, status="SAMPLED")

        response = _notice(
            api, bundle, bundle["second_slot"], SECOND_NOTIFIED_AT, MIDDAY_WINDOW
        )

        noticed_slot = assert_ok(response)
        assert_fields(noticed_slot, access_status="NOTIFIED")
        bubbled = X.read_inspection(api, bundle["inspection_id"])
        assert_fields(bubbled, status="NOTIFIED")
        assert_integer(bubbled["version"], after_first["version"] + 1, "version")
        assert_fields(
            X.read_selection(api, bundle["first_slot"]["id"]),
            access_status="NOTIFIED",
        )

    def test_a_foreign_owner_may_not_notice_another_propertys_slot(self, api):
        """The acting principal must be the inspection's own property.

        PRD: "Only a `PropertyOwner` may record it, and only for their own
        property: the acting `X-User-ID` must equal the `property_id` of the
        inspection owning the slot."

        Design: Corner/rbac/notice_issued_by_a_foreign_property_owner_is_rejected_as_not_owner
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(X.property_with_units(api, K.CEDAR_WALK, CEDAR_UNIT))
        stranger_id = X.create_property(api, K.BIRCH_ROW, total_unit_count=1)["id"]
        sampled = X.sampled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )
        slot = sampled["slots"][bundle["unit_ids"]["101"]]

        response = api.issue_notice(
            slot["id"],
            F.notice_payload(
                notified_at=FIRST_NOTIFIED_AT,
                access_window_start=FULL_DAY_WINDOW[0],
                access_window_end=FULL_DAY_WINDOW[1],
            ),
            make_property_owner_headers(stranger_id),
        )

        assert_error(response, ApiErrorId.FORBIDDEN_NOT_OWNER)
        untouched = X.read_selection(api, slot["id"])
        assert_fields(untouched, access_status="NOT_NOTIFIED")
        assert_null(untouched, "notified_at", "notice_lead_hours")
        assert_fields(
            X.read_inspection(api, sampled["inspection_id"]), status="SAMPLED"
        )


class TestNoticeLeadFloor:
    """`notice_lead_hours` gates the start of the walk at exactly 48.00."""

    def test_a_twenty_four_hour_lead_blocks_the_start(self, api):
        """One day of warning is half the required lead.

        PRD: "derives `notice_lead_hours` as the interval from `notified_at` to
        the owning inspection's `scheduled_start`, expressed in hours and rounded
        half up to two decimal places."

        PRD: "every slot with `selection_status` `ACTIVE` and `selection_basis`
        `SAMPLED` has a `notice_lead_hours` of at least 48.00 - two full days of
        advance notice - else `ERR_NOTICE_WINDOW_TOO_SHORT` (HTTP 422). The
        boundary is inclusive: exactly `48.00` passes."

        Design: Corner/state_machines/start_inspection_rejected_when_notice_lead_is_under_forty_eight_hours
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(X.property_with_units(api, K.CEDAR_WALK, CEDAR_UNIT))
        sampled = X.sampled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )
        slot = sampled["slots"][bundle["unit_ids"]["101"]]
        noticed = assert_ok(
            api.issue_notice(
                slot["id"],
                F.notice_payload(
                    notified_at=SHORT_LEAD_NOTIFIED_AT,
                    access_window_start=FULL_DAY_WINDOW[0],
                    access_window_end=FULL_DAY_WINDOW[1],
                ),
                bundle["owner_headers"],
            )
        )
        assert_two_decimals(noticed["notice_lead_hours"], 24.00, "notice_lead_hours")

        response = api.start_inspection(
            sampled["inspection_id"],
            F.start_inspection_payload(started_at=K.INSPECTION_STARTED_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.NOTICE_WINDOW_TOO_SHORT)
        unchanged = X.read_inspection(api, sampled["inspection_id"])
        assert_fields(unchanged, status="NOTIFIED")
        assert_null(unchanged, "started_at")
        assert_fields(
            X.read_selection(api, slot["id"]), access_status="NOTIFIED"
        )

    def test_a_lead_of_exactly_forty_eight_hours_passes_the_floor(self, api):
        """The inclusive boundary lets the walk begin.

        PRD: "every slot with `selection_status` `ACTIVE` and `selection_basis`
        `SAMPLED` has a `notice_lead_hours` of at least 48.00 - two full days of
        advance notice - else `ERR_NOTICE_WINDOW_TOO_SHORT` (HTTP 422). The
        boundary is inclusive: exactly `48.00` passes."

        Design: Corner/calculations/notice_lead_of_exactly_forty_eight_hours_passes_the_floor
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(X.property_with_units(api, K.CEDAR_WALK, CEDAR_UNIT))
        sampled = X.sampled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )
        slot = sampled["slots"][bundle["unit_ids"]["101"]]
        noticed = assert_ok(
            api.issue_notice(
                slot["id"],
                F.notice_payload(
                    notified_at=EXACT_LEAD_NOTIFIED_AT,
                    access_window_start=FULL_DAY_WINDOW[0],
                    access_window_end=FULL_DAY_WINDOW[1],
                ),
                bundle["owner_headers"],
            )
        )
        assert_two_decimals(noticed["notice_lead_hours"], 48.00, "notice_lead_hours")

        response = api.start_inspection(
            sampled["inspection_id"],
            F.start_inspection_payload(started_at=K.INSPECTION_STARTED_AT),
            X.INSPECTOR,
        )

        started = assert_ok(response)
        assert_fields(started, status="IN_PROGRESS")
        assert_instant(
            started["started_at"], K.INSPECTION_STARTED_AT, "started_at"
        )


class TestRecordingAccessAtTheDoor:
    """Entry outcomes reconcile the inspection's two unit counters."""

    def test_a_refusal_alongside_a_grant_splits_the_two_counters(self, api):
        """With no spare candidate the refusal produces no replacement slot.

        PRD: "When the candidate pool is empty the refusal is simply recorded
        without a replacement: the refused slot keeps `selection_status` `ACTIVE`
        alongside `access_status` `REFUSED`"

        PRD: "the inspection recomputes `refused_unit_count` as the number of its
        slots with `selection_status` `ACTIVE` and `access_status` `REFUSED`,
        recomputes `sample_size` as the number with `selection_status` `ACTIVE`,
        keeps its `status` at `IN_PROGRESS`"

        Design: Corner/state_machines/granted_access_reconciles_inspected_and_refused_unit_counts
        """
        bundle = _maple_two_slots_in_progress(api)
        granted = assert_ok(
            api.record_access(
                bundle["first_slot"]["id"],
                F.access_payload("GRANTED", recorded_at=GRANT_RECORDED_AT),
                X.INSPECTOR,
            )
        )
        assert_fields(granted, access_status="GRANTED")

        response = api.record_access(
            bundle["second_slot"]["id"],
            F.access_payload(
                "REFUSED",
                recorded_at=REFUSAL_RECORDED_AT,
                refusal_reason="Household declined entry at the door",
            ),
            X.INSPECTOR,
        )

        refused = assert_ok(response)
        assert_fields(
            refused,
            access_status="REFUSED",
            selection_status="ACTIVE",
            refusal_reason="Household declined entry at the door",
        )
        assert_null(refused, "replaced_selection_id")
        for slot in X.list_selections(api, bundle["inspection_id"]):
            assert slot["selection_basis"] != "REPLACEMENT"
        first = X.read_selection(api, bundle["first_slot"]["id"])
        assert_fields(first, access_status="GRANTED")
        assert_instant(
            first["access_recorded_at"], GRANT_RECORDED_AT, "access_recorded_at"
        )
        assert_fields(
            X.read_inspection(api, bundle["inspection_id"]),
            status="IN_PROGRESS",
            inspected_unit_count=1,
            refused_unit_count=1,
            sample_size=2,
        )

    def test_access_on_a_never_noticed_slot_is_rejected(self, api):
        """A slot still in NOT_NOTIFIED cannot record an entry outcome.

        PRD: "Both branches require the slot's `access_status` to be `NOTIFIED`,
        its `selection_status` to be `ACTIVE`, and the owning inspection's
        `status` to be `IN_PROGRESS`."

        PRD: "the target row's `status`, `repair_status`, `verification_status`
        or `adoption_status` admits the requested transition, else the state
        error for that resource type: `ERR_STANDARD_ALREADY_ADOPTED`,
        `ERR_INSPECTION_INVALID_STATE`, `ERR_SELECTION_INVALID_STATE`"

        Design: Corner/errors/recording_access_on_a_never_noticed_slot_is_rejected_as_invalid_state
        """
        bundle = X.adopted_standard(api, ("LT_GAS",))
        bundle.update(X.property_with_units(api, K.CEDAR_WALK, CEDAR_UNIT))
        sampled = X.sampled_inspection(
            api, bundle["property_id"], bundle["standard_id"]
        )
        slot = sampled["slots"][bundle["unit_ids"]["101"]]
        assert_fields(slot, access_status="NOT_NOTIFIED")

        response = api.record_access(
            slot["id"],
            F.access_payload("GRANTED", recorded_at=GRANT_RECORDED_AT),
            X.INSPECTOR,
        )

        assert_error(response, ApiErrorId.SELECTION_INVALID_STATE)
        untouched = X.read_selection(api, slot["id"])
        assert_fields(
            untouched, access_status="NOT_NOTIFIED", selection_status="ACTIVE"
        )
        assert_null(untouched, "access_recorded_at")
        assert_fields(
            X.read_inspection(api, sampled["inspection_id"]),
            status="SAMPLED",
            inspected_unit_count=0,
        )


class TestUnitEntryWindowOverlap:
    """Entry windows on one unit are half-open and carry no buffer."""

    def test_a_window_beginning_where_another_ends_is_accepted(self, api):
        """Two inspections may share unit 101 back to back on the same morning.

        PRD: "the requested entry window must not overlap the entry window of any
        other sample slot with `selection_status` `ACTIVE` on the same `unit_id`;
        here the arithmetic is half-open, including the start instant and
        excluding the end instant, and with no buffer at all, so a window that
        begins exactly when another ends is **accepted**."

        Design: Difficulty/resource_temporal_overlap/unit_access_windows_touching_at_one_instant_are_accepted_half_open
        """
        bundle = _two_inspections_sampling_one_unit(api)

        response = _notice(
            api,
            bundle,
            bundle["second_slot"],
            FIRST_NOTIFIED_AT,
            TOUCHING_SECOND_WINDOW,
        )

        noticed = assert_ok(response)
        assert_fields(noticed, access_status="NOTIFIED", selection_status="ACTIVE")
        assert_instant(
            noticed["access_window_start"],
            TOUCHING_SECOND_WINDOW[0],
            "access_window_start",
        )
        assert_fields(
            X.read_selection(api, bundle["first_slot"]["id"]),
            access_status="NOTIFIED",
            selection_status="ACTIVE",
        )
        assert_fields(
            X.read_inspection(api, bundle["first_inspection_id"]), status="NOTIFIED"
        )
        assert_fields(
            X.read_inspection(api, bundle["second_inspection_id"]), status="NOTIFIED"
        )

    def test_each_slot_takes_its_lead_from_its_own_inspection(self, api):
        """One delivery instant yields two different leads, ten days apart.

        PRD: "derives `notice_lead_hours` as the interval from `notified_at` to
        the owning inspection's `scheduled_start`, expressed in hours and rounded
        half up to two decimal places."

        Design: Difficulty/resource_temporal_overlap/unit_access_windows_touching_at_one_instant_are_accepted_half_open
        """
        bundle = _two_inspections_sampling_one_unit(api)

        response = _notice(
            api,
            bundle,
            bundle["second_slot"],
            FIRST_NOTIFIED_AT,
            TOUCHING_SECOND_WINDOW,
        )

        noticed = assert_ok(response)
        assert_two_decimals(
            noticed["notice_lead_hours"], 1104.00, "notice_lead_hours"
        )
        assert_two_decimals(
            X.read_selection(api, bundle["first_slot"]["id"])["notice_lead_hours"],
            864.00,
            "notice_lead_hours",
        )
