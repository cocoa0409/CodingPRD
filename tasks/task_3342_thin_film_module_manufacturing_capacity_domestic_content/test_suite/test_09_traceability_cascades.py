"""Component-lot traceability: verification loop, quarantine cascade, the
suspend/resume compensation cascade, and RBAC on traceability endpoints."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_reservation,
    create_component_lot_payload,
    create_customer,
    create_delivery_payload,
    create_promoted_line,
    create_ramping_line,
    create_verified_lot,
    get_delivery,
    get_line,
    get_reservation,
    make_customer_admin_headers,
    set_clock,
    setup_active_reservation,
    setup_scheduled_delivery,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
SCA = TEST_USERS["supply_chain_auditor_headers"]
RC = TEST_USERS["recycling_coordinator_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


def test_lot_quarantine_verify_remediation_cycle(api):
    """PRD §3.5: "Verification moves a lot `PENDING_INSPECTION → VERIFIED`, or
    `QUARANTINED → VERIFIED` once remediation is recorded. Quarantine moves a
    lot `PENDING_INSPECTION → QUARANTINED` with no further effect, but
    quarantining a lot that is currently `VERIFIED` fires the traceability
    cascade: every delivery in `SCHEDULED` or `RESCHEDULED` whose `lot_ids`
    contain that lot transitions to `RECALLED` and its `content_status` is set
    to `NON_QUALIFYING`."

    Design: Corner/state_machines/lot_quarantine_verify_remediation_cycle
    """
    resp = api.create_component_lot(create_component_lot_payload(), SCA)
    lot = validate_success(resp, 201)
    assert lot["status"] == "PENDING_INSPECTION"

    quarantined = validate_success(api.quarantine_lot(lot["id"], SCA), 200)
    assert quarantined["status"] == "QUARANTINED"

    remediated = validate_success(api.verify_lot(lot["id"], SCA), 200)
    assert remediated["status"] == "VERIFIED", (
        "QUARANTINED -> VERIFIED remediation must succeed"
    )


def test_recycling_coordinator_cannot_register_lot(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.5: "A `SupplyChainAuditor` registers each component lot with a
    `supplier_name`, a unique `lot_code`, a `component_type` of
    `SEMICONDUCTOR_FEEDSTOCK`, `GLASS`, `BACKSHEET`, `FRAME`, or
    `JUNCTION_BOX`, the `country_of_origin` as an ISO 3166-1 alpha-2 code
    (which feeds the manufactured-products percentage of §3.7), and the
    `lot_cost_usd` acquisition cost (zero or more — it feeds the
    manufactured-products cost numerator when the origin country matches the
    factory site country)."

    Design: Corner/rbac/recycling_coordinator_cannot_register_lot
    """
    resp = api.create_component_lot(create_component_lot_payload(), RC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_customer_admin_cannot_confirm_delivery(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.6: "Confirmation is performed by a `LogisticsCoordinator` and moves a
    delivery from `SCHEDULED` or `RESCHEDULED` to `DELIVERED`."

    Design: Corner/rbac/customer_admin_cannot_confirm_delivery
    """
    scenario = setup_scheduled_delivery(volume_mw=2.0)
    delivery, customer = scenario["delivery"], scenario["customer"]
    set_clock("2027-03-15T00:00:00Z")  # inside the window; role still gates

    resp = api.confirm_delivery(
        delivery["id"], make_customer_admin_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_delivery(delivery["id"])["schedule_status"] == "SCHEDULED"


class TestLotCheckPrecedesConstrainedCheck:
    """On scheduling, traceability runs before the reservation-state gate."""

    def test_unverified_lot_wins_over_constrained_reservation(self, api):
        """PRD §2.5: "On delivery scheduling, the traceability check (every
        referenced lot verified, else `ERR_LOT_NOT_VERIFIED`) runs first, then
        the window-overlap check (`ERR_WINDOW_OVERLAP`), then the
        cumulative-volume check (`ERR_VOLUME_EXCEEDS_CONTRACT`), and finally the
        reservation-state gate (`ERR_RESERVATION_CONSTRAINED`)."

        Design: Difficulty/priority_pair_validation_conflict/lot_check_precedes_constrained_check
        """
        scenario = setup_active_reservation()
        customer, reservation, line = (
            scenario["customer"], scenario["reservation"], scenario["line"],
        )
        # Force the reservation CONSTRAINED via the suspension cascade.
        validate_success(api.suspend_line(line["id"], PM), 200)
        assert get_reservation(reservation["id"])["status"] == "CONSTRAINED"

        # Lot registered but never verified (PENDING_INSPECTION).
        lot = validate_success(
            api.create_component_lot(
                create_component_lot_payload(lot_code="LOT-PEND-1"), SCA
            ),
            201,
        )
        resp = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-06-01T00:00:00Z",
                scheduled_window_end="2027-07-01T00:00:00Z",
                volume_mw=1.0,
                lot_ids=[lot["id"]],
            ),
            make_customer_admin_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_VERIFIED)

    def test_quarantined_lot_rejected_on_active_reservation(self, api):
        """PRD §3.6: "Scheduling enforces, in order: every lot referenced must
        be `VERIFIED` — a lot in `PENDING_INSPECTION` or `QUARANTINED` rejects
        the schedule with `ERR_LOT_NOT_VERIFIED` (HTTP 422); the window must be
        well-formed (`scheduled_window_end` strictly after
        `scheduled_window_start`) and must not overlap any sibling window of the
        same reservation in `SCHEDULED` or `RESCHEDULED` status; and the
        cumulative volume — the sum of `volume_mw` over that reservation's
        deliveries in `SCHEDULED`, `RESCHEDULED`, and `DELIVERED` status plus
        the new volume — must not exceed the reservation's `contracted_mw`,
        else `ERR_VOLUME_EXCEEDS_CONTRACT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/lot_check_precedes_constrained_check
        """
        scenario = setup_active_reservation()
        customer, reservation = scenario["customer"], scenario["reservation"]

        lot = validate_success(
            api.create_component_lot(
                create_component_lot_payload(lot_code="LOT-Q-1"), SCA
            ),
            201,
        )
        validate_success(api.quarantine_lot(lot["id"], SCA), 200)

        resp = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-06-01T00:00:00Z",
                scheduled_window_end="2027-07-01T00:00:00Z",
                volume_mw=1.0,
                lot_ids=[lot["id"]],
            ),
            make_customer_admin_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_VERIFIED)


class TestConfirmRequiresActiveReservation:
    """Delivery confirmation is gated on the reservation being ACTIVE."""

    def test_confirm_on_constrained_reservation_rejected(self, api):
        """PRD §3.6: "Every lot in `lot_ids` must still be `VERIFIED` at confirm
        time — a lot quarantined after scheduling blocks confirmation with
        `ERR_LOT_NOT_VERIFIED` — and the reservation must be `ACTIVE` (a
        `CONSTRAINED` reservation rejects with `ERR_RESERVATION_CONSTRAINED`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_active_reservation
        """
        scenario = setup_scheduled_delivery(volume_mw=2.0)
        delivery, line = scenario["delivery"], scenario["line"]

        # Suspend after scheduling: reservation cascades to CONSTRAINED.
        validate_success(api.suspend_line(line["id"], PM), 200)
        assert get_reservation(scenario["reservation"]["id"])["status"] == "CONSTRAINED"
        set_clock("2027-03-15T00:00:00Z")  # inside the window

        resp = api.confirm_delivery(delivery["id"], LC)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_CONSTRAINED)
        assert get_delivery(delivery["id"])["schedule_status"] == "SCHEDULED"

    def test_confirm_on_active_reservation_succeeds(self, api):
        """PRD §3.6: "Confirmation is performed by a `LogisticsCoordinator` and
        moves a delivery from `SCHEDULED` or `RESCHEDULED` to `DELIVERED`. The
        logical clock's current instant must fall within the scheduled window,
        inclusive of both `scheduled_window_start` and `scheduled_window_end`;
        confirming outside the window is rejected with
        `ERR_DELIVERY_WINDOW_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_active_reservation
        """
        scenario = setup_scheduled_delivery(volume_mw=2.0)
        delivery, reservation = scenario["delivery"], scenario["reservation"]

        set_clock("2027-03-15T00:00:00Z")
        resp = api.confirm_delivery(delivery["id"], LC)
        data = validate_success(resp, 200)
        assert data["schedule_status"] == "DELIVERED"
        assert get_reservation(reservation["id"])["delivered_mw"] == pytest.approx(
            2.0, abs=1e-9
        )


class TestLotQuarantineRecallCascade:
    """Quarantining a VERIFIED lot recalls every SCHEDULED/RESCHEDULED delivery
    containing it; the reservation itself stays ACTIVE."""

    def test_quarantine_recalls_scheduled_delivery_and_blocks_confirm(self, api):
        """PRD §3.5: "but quarantining a lot that is currently `VERIFIED` fires
        the traceability cascade: every delivery in `SCHEDULED` or `RESCHEDULED`
        whose `lot_ids` contain that lot transitions to `RECALLED` and its
        `content_status` is set to `NON_QUALIFYING`. A reservation whose only
        qualified supply path is broken by such a recall stays `ACTIVE` — there
        is no automatic reservation transition — but delivery confirmation
        against it is blocked until verified lots are substituted through
        rescheduling."
        PRD §2.5: "A request whose target resource is not in a state from which
        the requested transition is defined is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Difficulty/transitive_cascade/lot_quarantine_recalls_delivery_three_hop
        """
        scenario = setup_scheduled_delivery(volume_mw=2.0)
        lot, delivery, reservation = (
            scenario["lot"], scenario["delivery"], scenario["reservation"],
        )

        validate_success(api.quarantine_lot(lot["id"], SCA), 200)

        recalled = get_delivery(delivery["id"])
        assert recalled["schedule_status"] == "RECALLED"
        assert recalled["content_status"] == "NON_QUALIFYING"
        assert get_reservation(reservation["id"])["status"] == "ACTIVE", (
            "the reservation itself is NOT transitioned by the recall cascade"
        )

        # Confirm from RECALLED is not a defined transition.
        resp = api.confirm_delivery(delivery["id"], LC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_quarantine_recalls_rescheduled_delivery_too(self, api):
        """PRD §3.5: "but quarantining a lot that is currently `VERIFIED` fires
        the traceability cascade: every delivery in `SCHEDULED` or `RESCHEDULED`
        whose `lot_ids` contain that lot transitions to `RECALLED` and its
        `content_status` is set to `NON_QUALIFYING`."

        Design: Difficulty/transitive_cascade/lot_quarantine_recalls_delivery_three_hop
        """
        scenario = setup_scheduled_delivery(volume_mw=2.0)
        lot, delivery, customer = (
            scenario["lot"], scenario["delivery"], scenario["customer"],
        )
        resp = api.reschedule_delivery(
            delivery["id"],
            {
                "scheduled_window_start": "2027-05-01T00:00:00Z",
                "scheduled_window_end": "2027-06-01T00:00:00Z",
            },
            make_customer_admin_headers(customer["id"]),
        )
        assert validate_success(resp, 200)["schedule_status"] == "RESCHEDULED"

        validate_success(api.quarantine_lot(lot["id"], SCA), 200)
        recalled = get_delivery(delivery["id"])
        assert recalled["schedule_status"] == "RECALLED"
        assert recalled["content_status"] == "NON_QUALIFYING"


class TestLineSuspendCascade:
    """Suspending a line constrains its ACTIVE reservations and blocks new
    deliveries; resuming compensates exactly."""

    def test_suspend_constrains_blocks_delivery_resume_restores(self, api):
        """PRD §3.2: "Suspension cascades: every `ACTIVE` reservation on the
        line whose series is discontinued or whose required line output is
        blocked transitions to `CONSTRAINED`, and the line's `version`
        increments. Resuming moves the line `SUSPENDED → RAMPING` and
        compensates the cascade: every `CONSTRAINED` reservation on the line
        returns to `ACTIVE`, with another version increment."
        PRD §3.4: "While a reservation sits in `CONSTRAINED` (via the suspension
        cascade of §3.2), new deliveries against it are rejected with
        `ERR_RESERVATION_CONSTRAINED` (HTTP 409); the constraint lifts
        automatically when the line resumes."

        Design: Difficulty/transitive_cascade/line_suspend_constrains_reservation_blocks_delivery
        """
        scenario = setup_active_reservation()
        customer, reservation, line = (
            scenario["customer"], scenario["reservation"], scenario["line"],
        )
        lot = create_verified_lot()

        resp = api.suspend_line(line["id"], PM)
        assert validate_success(resp, 200)["status"] == "SUSPENDED"
        assert get_reservation(reservation["id"])["status"] == "CONSTRAINED"

        resp = api.create_delivery(
            create_delivery_payload(
                reservation_id=reservation["id"],
                scheduled_window_start="2027-06-01T00:00:00Z",
                scheduled_window_end="2027-07-01T00:00:00Z",
                volume_mw=1.0,
                lot_ids=[lot["id"]],
            ),
            make_customer_admin_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_CONSTRAINED)

        resp = api.resume_line(line["id"], PM)
        assert validate_success(resp, 200)["status"] == "RAMPING"
        assert get_reservation(reservation["id"])["status"] == "ACTIVE"

    def test_suspend_from_at_capacity_also_cascades(self, api):
        """PRD §3.2: "A `PlantManager` may suspend a line from either `RAMPING`
        or `AT_CAPACITY`, moving it to `SUSPENDED`. Suspension cascades: every
        `ACTIVE` reservation on the line whose series is discontinued or whose
        required line output is blocked transitions to `CONSTRAINED`, and the
        line's `version` increments. Resuming moves the line `SUSPENDED →
        RAMPING` and compensates the cascade: every `CONSTRAINED` reservation on
        the line returns to `ACTIVE`, with another version increment."

        Design: Difficulty/transitive_cascade/line_suspend_constrains_reservation_blocks_delivery
        """
        customer = create_customer()
        bundle = create_promoted_line()
        line = bundle["line"]
        assert line["status"] == "AT_CAPACITY"
        reservation = create_active_reservation(customer, line, bundle["series"])

        resp = api.suspend_line(line["id"], PM)
        assert validate_success(resp, 200)["status"] == "SUSPENDED"
        assert get_reservation(reservation["id"])["status"] == "CONSTRAINED", (
            "the cascade applies from AT_CAPACITY as well as RAMPING"
        )

        resp = api.resume_line(line["id"], PM)
        assert validate_success(resp, 200)["status"] == "RAMPING"
        assert get_reservation(reservation["id"])["status"] == "ACTIVE"
