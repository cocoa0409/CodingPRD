"""Gating states that live on a neighbouring record, and interval collisions.

In each case the request itself is unimpeachable; what refuses it is the state of another
entity or the presence of an earlier claim.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    LAYOVER_DAILY_CENTS,
    TARPING_FLAT_CENTS,
)
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    DriverType,
    EscrowStatus,
    MileageGuide,
    MovementStatus,
    PayPackageStatus,
    PayStatus,
    PerDiemMethod,
)


def _in_transit_tarping_environment():
    """A tarp-required load left IN_TRANSIT with a documented TARPING claim already
    SUBMITTED against it."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Tarp",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Otto Overhead",
        home_state="TX",
    )
    load = fixtures.tender_load(driver["id"], stop_count=1, tarp_required=True)
    fixtures.set_clock(fixtures.TS_DISPATCH)
    fixtures.dispatch(load["id"])
    in_transit = fixtures.read_load(load["id"])
    assert in_transit["movement_status"] == MovementStatus.IN_TRANSIT

    claim = fixtures.submit_claim(
        load["id"],
        driver["id"],
        AccessorialType.TARPING,
        "2026-08-03T09:00:00Z",
        "2026-08-03T10:00:00Z",
        "doc://tarp-photo-12",
        CLERK_HEADERS,
    )
    assert claim["status"] == ClaimStatus.SUBMITTED
    return {"driver": driver, "load": load, "claim": claim}


class TestClaimApprovalDependsOnTheParentLoadState:
    """The blocking state is on the load, not on the claim."""

    def test_approval_is_refused_while_the_load_is_still_in_transit(self):
        """The claim is documented, priced-at-a-flat-rate and otherwise perfect, and it is the
        load's movement axis that refuses it.

        PRD 2.9 rung 22: "`ERR_LOAD_NOT_DELIVERED` — the load's `movement_status` is the one the
        operation needs: `TENDERED` to dispatch, `IN_TRANSIT` to deliver, `DELIVERED` to approve
        an accessorial claim against it or to file a mileage dispute on it."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_delivered_load
        """
        env = _in_transit_tarping_environment()

        response = api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS)

        validate_error(response, ApiErrorId.LOAD_NOT_DELIVERED, 409)
        claim = fixtures.read_claim(env["claim"]["id"])
        assert claim["status"] == ClaimStatus.SUBMITTED
        assert claim["amount_cents"] == 0
        assert claim["billable_units"] == 0
        assert claim["version"] == env["claim"]["version"], "a refused approval is not a mutation"

    def test_the_identical_request_succeeds_once_the_load_is_delivered(self):
        """Delivering the load — a write to neither the claim nor the request — is enough to make
        the very same approval succeed and price the tarping at its flat rate.

        PRD 3.5: "A `PayrollAdmin` or `SettlementClerk` may approve a claim whose `status` is
        `SUBMITTED` when its referenced load's `movement_status` is `DELIVERED`".
        PRD 3.5: "**`TARPING`.** Tarping is a flat event: `billable_units` is 1 and `amount_cents`
        is 7,500 cents."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_delivered_load
        """
        env = _in_transit_tarping_environment()
        validate_error(
            api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS),
            ApiErrorId.LOAD_NOT_DELIVERED,
            409,
        )

        fixtures.set_clock(fixtures.TS_DELIVER)
        fixtures.deliver(env["load"]["id"])
        delivered = fixtures.read_load(env["load"]["id"])
        assert delivered["movement_status"] == MovementStatus.DELIVERED
        assert delivered["pay_status"] == PayStatus.ACCRUED

        approved = validate_success(
            api_client.approve_accessorial_claim(env["claim"]["id"], CLERK_HEADERS)
        )

        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["billable_units"] == 1
        assert approved["amount_cents"] == TARPING_FLAT_CENTS
        assert approved["amount_cents"] == 7500


def _draft_package_and_unassigned_driver():
    """A fully componented package deliberately left in DRAFT, and a freshly registered
    driver with no package at all."""
    package = fixtures.create_package(
        components=fixtures.linehaul_components(),
        activate=False,
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.DAY_BASED,
        escrow_required=True,
        escrow_target_cents=250000,
        escrow_monthly_deduction_cents=40000,
        name="Leased Draft Package",
    )
    assert package["status"] == PayPackageStatus.DRAFT
    driver = fixtures.create_driver(
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=True,
        legal_name="Pete Pending",
        home_state="TX",
    )
    assert driver["pay_package_id"] is None
    assert driver["escrow_status"] == EscrowStatus.NOT_REQUIRED
    return {"package": package, "driver": driver}


class TestDriverAssignmentDependsOnThePackageState:
    """Here the write targets the driver while the blocking state sits on the package."""

    def test_a_draft_package_cannot_be_assigned(self):
        """The package holds both linehaul components and is otherwise ready, but a package must
        be ACTIVE before a driver may be put on it.

        PRD 2.9 rung 18: "`ERR_PAY_PACKAGE_NOT_ACTIVE` — the package is `DRAFT` when a component
        is appended and when it is activated, and `ACTIVE` when it is revised, retired or assigned
        to a driver."

        Design: Difficulty/cross_entity_state_dependency/driver_assignment_requires_active_package
        """
        env = _draft_package_and_unassigned_driver()

        response = api_client.assign_pay_package(
            env["driver"]["id"],
            factories.assign_package_payload(env["package"]["id"]),
            ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.PAY_PACKAGE_NOT_ACTIVE, 409)
        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["pay_package_id"] is None
        assert driver["escrow_status"] == EscrowStatus.NOT_REQUIRED

    def test_activating_the_package_lets_the_same_assignment_through_and_opens_escrow(self):
        """Activation is a write to the package alone, and it turns the identical assignment into
        a success that also drives the driver's escrow axis off NOT_REQUIRED.

        PRD 3.1: "A successful activation sets `status` to `ACTIVE`, stamps `activated_at` from
        the logical clock and increments the package's `version` by 1."
        PRD 3.3: "moves the escrow axis `NOT_REQUIRED` → `COLLECTING`, copies
        `escrow_target_cents` and `escrow_monthly_deduction_cents` from the package, leaves
        `escrow_balance_cents` at 0 so that the first settlement begins accrual".

        Design: Difficulty/cross_entity_state_dependency/driver_assignment_requires_active_package
        """
        env = _draft_package_and_unassigned_driver()
        validate_error(
            api_client.assign_pay_package(
                env["driver"]["id"],
                factories.assign_package_payload(env["package"]["id"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.PAY_PACKAGE_NOT_ACTIVE,
            409,
        )

        activated = validate_success(
            api_client.activate_pay_package(env["package"]["id"], ADMIN_HEADERS)
        )
        assert activated["status"] == PayPackageStatus.ACTIVE
        assert activated["component_count"] == 2

        validate_success(
            api_client.assign_pay_package(
                env["driver"]["id"],
                factories.assign_package_payload(env["package"]["id"]),
                ADMIN_HEADERS,
            )
        )

        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["pay_package_id"] == env["package"]["id"]
        assert driver["escrow_status"] == EscrowStatus.COLLECTING
        assert driver["escrow_target_cents"] == 250000
        assert driver["escrow_monthly_deduction_cents"] == 40000
        assert driver["escrow_balance_cents"] == 0


def _stored_detention_environment():
    """A delivered load already carrying one APPROVED detention ticket for 08:00-10:30, worth
    1000 cents, whose stored interval is extended by the 15-minute buffer."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Buffer Overlap",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Quinn Queue",
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock("2026-08-06T09:00:00Z")
    stored = fixtures.approved_claim(
        load["id"],
        driver["id"],
        AccessorialType.DETENTION,
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:30:00Z",
        "doc://det-q1",
    )
    assert stored["billable_units"] == 2
    assert stored["amount_cents"] == 1000
    return {"driver": driver, "load": load, "stored": stored}


class TestDetentionIntervalBufferOverlapOnTheSameLoad:
    """Collisions are measured on instants, scoped to the load, with a 15-minute tail."""

    def test_a_ticket_inside_the_buffer_tail_collides(self):
        """10:35 is past the stored end_at but inside the 15-minute extension, so the second
        ticket at the same door is refused.

        PRD 3.5: "each already-stored interval is extended by 15 minutes past its `end_at` before
        the comparison, so two detention tickets filed back-to-back at the same door collide
        rather than both paying."

        Design: Difficulty/resource_temporal_overlap/detention_interval_buffer_overlap_same_load
        """
        env = _stored_detention_environment()

        response = api_client.create_accessorial_claim(
            factories.detention_claim_payload(
                env["load"]["id"],
                env["driver"]["id"],
                "2026-08-05T10:35:00Z",
                "2026-08-05T12:00:00Z",
                document_ref="doc://det-q2",
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ACCESSORIAL_OVERLAP, 409)
        claims, meta = validate_paginated(
            api_client.list_accessorial_claims(ADMIN_HEADERS, {"load_id": env["load"]["id"]})
        )
        assert meta["total_count"] == 1, "the refused claim was never stored"

    def test_a_ticket_starting_exactly_at_the_buffer_edge_is_accepted_and_priced(self):
        """The extended upper bound is exclusive, so a start at exactly 10:45 clears the buffer
        and the new ticket is stored and payable on its own merits.

        PRD 3.5: "the new interval may not overlap the interval of any other non-rejected claim
        **on the same load**, where each interval is treated as half-open — its start instant is
        inside, its end instant is outside".

        Design: Difficulty/resource_temporal_overlap/detention_interval_buffer_overlap_same_load
        """
        env = _stored_detention_environment()
        validate_error(
            api_client.create_accessorial_claim(
                factories.detention_claim_payload(
                    env["load"]["id"],
                    env["driver"]["id"],
                    "2026-08-05T10:35:00Z",
                    "2026-08-05T12:00:00Z",
                    document_ref="doc://det-q2",
                ),
                CLERK_HEADERS,
            ),
            ApiErrorId.ACCESSORIAL_OVERLAP,
            409,
        )

        accepted = validate_success(
            api_client.create_accessorial_claim(
                factories.detention_claim_payload(
                    env["load"]["id"],
                    env["driver"]["id"],
                    "2026-08-05T10:45:00Z",
                    "2026-08-05T13:00:00Z",
                    document_ref="doc://det-q3",
                ),
                CLERK_HEADERS,
            ),
            201,
        )
        approved = validate_success(
            api_client.approve_accessorial_claim(accepted["id"], CLERK_HEADERS)
        )

        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["billable_units"] == 1
        assert approved["amount_cents"] == 500
        claims, meta = validate_paginated(
            api_client.list_accessorial_claims(ADMIN_HEADERS, {"load_id": env["load"]["id"]})
        )
        assert meta["total_count"] == 2
        assert fixtures.read_claim(env["stored"]["id"])["amount_cents"] == 1000


def _stored_layover_environment():
    """One driver with two delivered loads, the first already carrying an APPROVED layover
    covering the calendar dates 5, 6 and 7 of August."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Layover Overlap",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Rae Restbreak",
        home_state="TX",
    )
    first_load = fixtures.delivered_load(driver["id"], stop_count=1)
    second_load = fixtures.delivered_load(
        driver["id"],
        dispatched_at="2026-08-08T08:00:00Z",
        delivered_at="2026-08-08T12:00:00Z",
        stop_count=1,
    )
    fixtures.set_clock("2026-08-12T09:00:00Z")
    stored = fixtures.approved_claim(
        driver_id=driver["id"],
        load_id=first_load["id"],
        accessorial_type=AccessorialType.LAYOVER,
        start_at="2026-08-05T20:00:00Z",
        end_at="2026-08-07T06:00:00Z",
    )
    assert stored["billable_units"] == 2
    assert stored["amount_cents"] == 2 * LAYOVER_DAILY_CENTS
    return {
        "driver": driver,
        "first_load": first_load,
        "second_load": second_load,
        "stored": stored,
    }


class TestLayoverCalendarDayOverlapAcrossTheDriverLoads:
    """Layover collisions are date-set collisions scoped to the driver, not the load."""

    def test_a_layover_sharing_one_calendar_date_on_another_load_collides(self):
        """The two intervals are twelve hours apart and sit on different loads, so no instant
        test would flag them, yet they share the calendar date of 7 August and collide.

        PRD 3.5: "A `LAYOVER` claim is compared differently: it may share no UTC calendar date
        with any other non-rejected `LAYOVER` claim **of the same driver**, comparing inclusive
        calendar-date sets rather than instants, so two layovers on two different loads that touch
        the same date still collide".

        Design: Difficulty/resource_temporal_overlap/layover_calendar_day_overlap_same_driver
        """
        env = _stored_layover_environment()

        response = api_client.create_accessorial_claim(
            factories.accessorial_claim_payload(
                env["second_load"]["id"],
                env["driver"]["id"],
                AccessorialType.LAYOVER,
                "2026-08-07T18:00:00Z",
                "2026-08-08T10:00:00Z",
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.LAYOVER_OVERLAP, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.ACCESSORIAL_OVERLAP, (
            "the two claims sit on different loads, so the interval rule is not the one that fires"
        )

    def test_a_layover_on_disjoint_dates_is_accepted_and_paid_per_day(self):
        """Moving the second layover onto dates 9, 10 and 11 clears the date-set test, and it
        prices at two payable days because the first day of a layover is unpaid.

        PRD 3.5: "The first of those days is unpaid, so `billable_units` is that count less 1,
        floored at zero, and then capped at 3 payable days. `amount_cents` is `billable_units`
        multiplied by 12,500 cents per day."

        Design: Difficulty/resource_temporal_overlap/layover_calendar_day_overlap_same_driver
        """
        env = _stored_layover_environment()
        validate_error(
            api_client.create_accessorial_claim(
                factories.accessorial_claim_payload(
                    env["second_load"]["id"],
                    env["driver"]["id"],
                    AccessorialType.LAYOVER,
                    "2026-08-07T18:00:00Z",
                    "2026-08-08T10:00:00Z",
                ),
                CLERK_HEADERS,
            ),
            ApiErrorId.LAYOVER_OVERLAP,
            409,
        )

        accepted = validate_success(
            api_client.create_accessorial_claim(
                factories.accessorial_claim_payload(
                    env["second_load"]["id"],
                    env["driver"]["id"],
                    AccessorialType.LAYOVER,
                    "2026-08-09T18:00:00Z",
                    "2026-08-11T10:00:00Z",
                ),
                CLERK_HEADERS,
            ),
            201,
        )
        approved = validate_success(
            api_client.approve_accessorial_claim(accepted["id"], CLERK_HEADERS)
        )

        assert approved["status"] == ClaimStatus.APPROVED
        assert approved["billable_units"] == 2
        assert approved["amount_cents"] == 25000
        claims, meta = validate_paginated(
            api_client.list_accessorial_claims(
                ADMIN_HEADERS, {"driver_id": env["driver"]["id"]}
            )
        )
        assert meta["total_count"] == 2
