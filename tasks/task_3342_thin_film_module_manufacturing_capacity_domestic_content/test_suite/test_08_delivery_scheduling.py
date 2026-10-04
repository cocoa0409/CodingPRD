"""Delivery scheduling: half-open window overlap, cumulative volume cap,
confirmation windows, and reschedule-then-confirm."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_delivery_payload,
    create_verified_lot,
    get_delivery,
    get_reservation,
    make_customer_admin_headers,
    set_clock,
    setup_active_reservation,
    setup_scheduled_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)

LC = TEST_USERS["logistics_coordinator_headers"]


class TestDeliveryWindowsHalfOpenTouching:
    """Windows use half-open [start, end) semantics: strict overlap conflicts,
    touching endpoints do not."""

    def test_overlap_rejected_touching_accepted(self, api):
        """PRD §3.6: "Window overlap uses half-open interval semantics: two
        windows conflict only when the new start is strictly before the existing
        end and the existing start is strictly before the new end. Touching
        windows — where one window's end equals the other's start — are
        allowed."

        Design: Difficulty/resource_temporal_overlap/delivery_windows_half_open_touching
        """
        scenario = setup_scheduled_delivery(
            volume_mw=1.0,
            window_start="2027-03-01T00:00:00Z",
            window_end="2027-04-01T00:00:00Z",
        )
        reservation, customer, lot = (
            scenario["reservation"], scenario["customer"], scenario["lot"],
        )
        headers = make_customer_admin_headers(customer["id"])

        # Strict overlap: 2027-03-15 lies inside [2027-03-01, 2027-04-01).
        overlapping = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-03-15T00:00:00Z",
                scheduled_window_end="2027-04-15T00:00:00Z",
                volume_mw=1.0,
                lot_ids=[lot["id"]],
            ),
            headers,
        )
        validate_error(overlapping, ApiErrorId.ERR_WINDOW_OVERLAP)

        # Touching: new start == existing end is NOT a conflict.
        touching = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-04-01T00:00:00Z",
                scheduled_window_end="2027-05-01T00:00:00Z",
                volume_mw=1.0,
                lot_ids=[lot["id"]],
            ),
            headers,
        )
        data = validate_success(touching, 201)
        assert data["schedule_status"] == "SCHEDULED"

    def test_reschedule_overlap_rejected_original_window_kept(self, api):
        """PRD §3.6: "The same overlap rule applies when the owning
        `CustomerAdmin` reschedules a delivery, moving it `SCHEDULED →
        RESCHEDULED` with a new `scheduled_window_start` and
        `scheduled_window_end`."

        Design: Difficulty/resource_temporal_overlap/delivery_windows_half_open_touching
        """
        scenario = setup_scheduled_delivery(
            volume_mw=1.0,
            window_start="2027-03-01T00:00:00Z",
            window_end="2027-04-01T00:00:00Z",
        )
        reservation, customer, lot = (
            scenario["reservation"], scenario["customer"], scenario["lot"],
        )
        headers = make_customer_admin_headers(customer["id"])
        second = validate_success(
            api.create_delivery(
                create_delivery_payload(
                    reservation_id=reservation["id"],
                    scheduled_window_start="2027-05-01T00:00:00Z",
                    scheduled_window_end="2027-06-01T00:00:00Z",
                    volume_mw=1.0,
                    lot_ids=[lot["id"]],
                ),
                headers,
            ),
            201,
        )

        # Rescheduling the second delivery into the first's window conflicts.
        resp = api.reschedule_delivery(
            second["id"],
            {
                "scheduled_window_start": "2027-03-15T00:00:00Z",
                "scheduled_window_end": "2027-04-15T00:00:00Z",
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)
        unchanged = get_delivery(second["id"])
        assert unchanged["schedule_status"] == "SCHEDULED"
        assert unchanged["scheduled_window_start"] == "2027-05-01T00:00:00Z"


class TestOverlapCheckPrecedesVolumeCheck:
    """On scheduling, window overlap is evaluated before cumulative volume."""

    def test_overlap_wins_when_both_violated(self, api):
        """PRD §2.5: "On delivery scheduling, the traceability check (every
        referenced lot verified, else `ERR_LOT_NOT_VERIFIED`) runs first, then
        the window-overlap check (`ERR_WINDOW_OVERLAP`), then the
        cumulative-volume check (`ERR_VOLUME_EXCEEDS_CONTRACT`), and finally the
        reservation-state gate (`ERR_RESERVATION_CONSTRAINED`)."

        Design: Difficulty/priority_pair_validation_conflict/overlap_check_precedes_volume_check
        """
        scenario = setup_scheduled_delivery(
            volume_mw=6.0,
            window_start="2027-03-01T00:00:00Z",
            window_end="2027-04-01T00:00:00Z",
        )
        reservation, customer, lot = (
            scenario["reservation"], scenario["customer"], scenario["lot"],
        )

        # Overlaps D1 AND breaches the volume cap (6.0 + 6.0 > 10.0 contracted).
        resp = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-03-15T00:00:00Z",
                scheduled_window_end="2027-04-15T00:00:00Z",
                volume_mw=6.0,
                lot_ids=[lot["id"]],
            ),
            make_customer_admin_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_volume_cap_fires_without_overlap(self, api):
        """PRD §3.6: "and the cumulative volume — the sum of `volume_mw` over
        that reservation's deliveries in `SCHEDULED`, `RESCHEDULED`, and
        `DELIVERED` status plus the new volume — must not exceed the
        reservation's `contracted_mw`, else `ERR_VOLUME_EXCEEDS_CONTRACT`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/overlap_check_precedes_volume_check
        """
        scenario = setup_scheduled_delivery(
            volume_mw=6.0,
            window_start="2027-03-01T00:00:00Z",
            window_end="2027-04-01T00:00:00Z",
        )
        reservation, customer, lot = (
            scenario["reservation"], scenario["customer"], scenario["lot"],
        )

        # Disjoint window: only the volume rule can fail (6.0 + 5.0 > 10.0).
        resp = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-05-01T00:00:00Z",
                scheduled_window_end="2027-06-01T00:00:00Z",
                volume_mw=5.0,
                lot_ids=[lot["id"]],
            ),
            make_customer_admin_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOLUME_EXCEEDS_CONTRACT)


def test_delivery_cumulative_volume_cap(api):
    """PRD §3.6: "and the cumulative volume — the sum of `volume_mw` over that
    reservation's deliveries in `SCHEDULED`, `RESCHEDULED`, and `DELIVERED`
    status plus the new volume — must not exceed the reservation's
    `contracted_mw`, else `ERR_VOLUME_EXCEEDS_CONTRACT` (HTTP 422)."

    Design: Corner/validations/delivery_cumulative_volume_cap
    """
    scenario = setup_scheduled_delivery(
        volume_mw=7.0,
        window_start="2027-03-01T00:00:00Z",
        window_end="2027-04-01T00:00:00Z",
    )
    reservation, customer, lot = (
        scenario["reservation"], scenario["customer"], scenario["lot"],
    )

    resp = api.create_delivery(
        create_delivery_payload(
            reservation_id=reservation["id"],
            scheduled_window_start="2027-05-01T00:00:00Z",
            scheduled_window_end="2027-06-01T00:00:00Z",
            volume_mw=4.0,  # 7.0 + 4.0 == 11.0 > 10.0 contracted
            lot_ids=[lot["id"]],
        ),
        make_customer_admin_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VOLUME_EXCEEDS_CONTRACT)


def test_delivery_window_end_before_start_rejected(api):
    """PRD §3.6: "the window must be well-formed (`scheduled_window_end`
    strictly after `scheduled_window_start`) and must not overlap any sibling
    window of the same reservation in `SCHEDULED` or `RESCHEDULED` status"
    PRD §2.5: "then the window-overlap check (`ERR_WINDOW_OVERLAP`), then the
    cumulative-volume check (`ERR_VOLUME_EXCEEDS_CONTRACT`), and finally the
    reservation-state gate (`ERR_RESERVATION_CONSTRAINED`)."

    Design: Corner/validations/delivery_window_end_before_start_rejected
    """
    scenario = setup_active_reservation()
    lot = create_verified_lot()

    resp = api.create_delivery(
        create_delivery_payload(
            reservation_id=scenario["reservation"]["id"],
            scheduled_window_start="2027-04-01T00:00:00Z",
            scheduled_window_end="2027-03-01T00:00:00Z",  # end before start
            volume_mw=1.0,
            lot_ids=[lot["id"]],
        ),
        make_customer_admin_headers(scenario["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_confirm_before_window_rejected(api):
    """PRD §3.6: "The logical clock's current instant must fall within the
    scheduled window, inclusive of both `scheduled_window_start` and
    `scheduled_window_end`; confirming outside the window is rejected with
    `ERR_DELIVERY_WINDOW_NOT_OPEN` (HTTP 409)."
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and before any set call it must continue to read
    this default — it must never fall back to wall-clock time."

    Design: Corner/validations/confirm_before_window_rejected
    """
    scenario = setup_scheduled_delivery(volume_mw=2.0)
    delivery = scenario["delivery"]

    # Clock left at the 2026-09-01 startup default, before the 2027 window.
    resp = api.confirm_delivery(delivery["id"], LC)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_NOT_OPEN)
    assert get_delivery(delivery["id"])["schedule_status"] == "SCHEDULED"


def test_rescheduled_delivery_confirm_delivered(api):
    """PRD §3.6: "Confirmation is performed by a `LogisticsCoordinator` and
    moves a delivery from `SCHEDULED` or `RESCHEDULED` to `DELIVERED`."
    PRD §3.6: "On confirmation the reservation's `delivered_mw` grows by the
    delivery's `volume_mw` and the reservation's `version` increments by 1; the
    delivered batch also feeds the actual-yield energy settlement of §3.3."

    Design: Corner/state_machines/rescheduled_delivery_confirm_delivered
    """
    scenario = setup_scheduled_delivery(volume_mw=2.0)
    delivery, customer, reservation = (
        scenario["delivery"], scenario["customer"], scenario["reservation"],
    )

    resp = api.reschedule_delivery(
        delivery["id"],
        {
            "scheduled_window_start": "2027-03-10T00:00:00Z",
            "scheduled_window_end": "2027-04-10T00:00:00Z",
        },
        make_customer_admin_headers(customer["id"]),
    )
    assert validate_success(resp, 200)["schedule_status"] == "RESCHEDULED"

    set_clock("2027-03-15T00:00:00Z")  # inside the new window
    resp = api.confirm_delivery(delivery["id"], LC)
    data = validate_success(resp, 200)
    assert data["schedule_status"] == "DELIVERED"
    assert get_reservation(reservation["id"])["delivered_mw"] == pytest.approx(
        2.0, abs=1e-9
    )


def test_fk_reverse_deliveries_by_reservation(api):
    """PRD §4: "Deliveries scheduled against this reservation"
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/fk_reverse_deliveries_by_reservation
    """
    scenario = setup_scheduled_delivery(volume_mw=2.0)

    resp = api.list_reservation_deliveries(
        scenario["reservation"]["id"],
        make_customer_admin_headers(scenario["customer"]["id"]),
    )
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly 1 delivery, got {len(data)}"
    assert data[0]["id"] == scenario["delivery"]["id"]
