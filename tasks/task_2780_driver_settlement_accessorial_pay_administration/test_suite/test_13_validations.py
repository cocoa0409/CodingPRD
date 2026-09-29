"""Preconditions: what a request must satisfy, in which order, and how each gate is cured.

Every case pairs the refusal with the identical request succeeding once the one blocking fact
has changed, so a handler that rejects the shape outright rather than the state is caught.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    api_client,
    assert_timestamps_equal,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.types import (
    AccessorialType,
    AdvanceStatus,
    AdvanceType,
    ClaimStatus,
    ComponentType,
    DriverType,
    EmploymentStatus,
    EscrowStatus,
    EscrowTxnType,
    MileageGuide,
    MovementStatus,
    PayPackageStatus,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
    VoidReasonCode,
)


class TestComponentUniqueness:
    """One component per type, one component per sequence."""

    def test_a_repeated_component_type_and_a_repeated_sequence_are_both_duplicates(self):
        """The package already holds PER_MILE at sequence 1 and REVENUE_PERCENT at sequence 2, so a
        second PER_MILE at a free sequence and an ACTIVITY at a taken sequence each violate one half
        of the same rule, and neither is stored.

        PRD 3.1: "A package holds at most one component of each `component_type`, and no two
        components in the same package may share a `sequence` — either collision is
        `ERR_DUPLICATE_COMPONENT` (HTTP 409)."

        Design: Corner/validations/second_component_of_the_same_type_or_sequence_is_a_duplicate
        """
        fixtures.reset_clock()
        package = fixtures.create_package(
            components=fixtures.linehaul_components(),
            activate=False,
            per_diem_method=PerDiemMethod.NONE,
            name="Leased Duplicate Component",
        )
        assert package["component_count"] == 2

        duplicate_type = api_client.add_component(
            package["id"],
            factories.per_mile_component(rate_value=71, sequence=3),
            ADMIN_HEADERS,
        )
        validate_error(duplicate_type, ApiErrorId.DUPLICATE_COMPONENT, 409)

        duplicate_sequence = api_client.add_component(
            package["id"],
            factories.activity_component(rate_value=5000, sequence=2),
            ADMIN_HEADERS,
        )
        validate_error(duplicate_sequence, ApiErrorId.DUPLICATE_COMPONENT, 409)

        reread = get_success_data(api_client.get_pay_package(package["id"], ADMIN_HEADERS))
        assert reread["component_count"] == 2
        components = get_success_data(api_client.list_components(package["id"], ADMIN_HEADERS))
        assert len(components) == 2
        by_sequence = {component["sequence"]: component for component in components}
        assert by_sequence[1]["component_type"] == ComponentType.PER_MILE
        assert by_sequence[1]["rate_value"] == 58, "the refused 71 never overwrote anything"
        assert by_sequence[2]["component_type"] == ComponentType.REVENUE_PERCENT


class TestActivationPreconditions:
    """A satisfiable precondition, not a permanent rejection of the row."""

    def test_activation_needs_a_linehaul_component_and_succeeds_once_one_is_appended(self):
        """A package holding only an ACTIVITY component cannot pay linehaul, so it stays DRAFT with
        activated_at null; appending PER_MILE makes the identical activation succeed.

        PRD 3.1: "The package must hold at least one component, and at least one of those
        components must be of type `PER_MILE` or `REVENUE_PERCENT`, so that every activated package
        is capable of paying linehaul; a package holding neither is rejected with
        `ERR_PACKAGE_HAS_NO_LINEHAUL_COMPONENT` (HTTP 422)."
        PRD 3.1: "A successful activation sets `status` to `ACTIVE`, stamps `activated_at` from the
        logical clock and increments the package's `version` by 1."

        Design: Corner/validations/activation_requires_a_linehaul_component_and_passes_once_one_exists
        """
        fixtures.reset_clock()
        package = fixtures.create_package(
            components=[factories.activity_component(rate_value=5000, sequence=1)],
            activate=False,
            per_diem_method=PerDiemMethod.NONE,
            name="Leased No Linehaul",
        )
        assert package["component_count"] == 1

        refused = api_client.activate_pay_package(package["id"], ADMIN_HEADERS)

        validate_error(refused, ApiErrorId.PACKAGE_HAS_NO_LINEHAUL_COMPONENT, 422)
        still_draft = get_success_data(api_client.get_pay_package(package["id"], ADMIN_HEADERS))
        assert still_draft["status"] == PayPackageStatus.DRAFT
        assert still_draft["activated_at"] is None

        validate_success(
            api_client.add_component(
                package["id"],
                factories.per_mile_component(rate_value=58, sequence=2),
                ADMIN_HEADERS,
            ),
            201,
        )
        activated = validate_success(
            api_client.activate_pay_package(package["id"], ADMIN_HEADERS)
        )

        assert activated["status"] == PayPackageStatus.ACTIVE
        assert_timestamps_equal(activated["activated_at"], CLOCK_EPOCH, "activated_at")
        assert activated["component_count"] == 2


class TestValidationPrecedence:
    """One body, two violations, one determined answer."""

    def test_a_missing_field_outranks_an_undeclared_enum_value_in_the_same_body(self):
        """driver_type is absent and mileage_guide is MOON; the shape check runs first, so the
        answer is the missing-field error, and supplying driver_type proves MOON was reachable.

        PRD 2.9: "Checks are evaluated in the fixed order below and the first failure is reported."
        PRD 2.9 rung 4: "`ERR_MISSING_REQUIRED_FIELD` — every field the endpoint requires is
        present and not null."

        Design: Corner/validations/missing_required_field_outranks_invalid_field_value_in_one_body
        """
        fixtures.reset_clock()

        both_wrong = api_client.create_pay_package(
            {
                "name": "Both Wrong",
                "mileage_guide": "MOON",
                "per_diem_method": PerDiemMethod.NONE,
                "escrow_required": False,
            },
            ADMIN_HEADERS,
        )

        validate_error(both_wrong, ApiErrorId.MISSING_REQUIRED_FIELD, 422)
        assert both_wrong.json()["data"]["error_id"] != ApiErrorId.INVALID_FIELD_VALUE, (
            "MOON is also wrong, but the shape check outranks the value check"
        )

        one_wrong = api_client.create_pay_package(
            {
                "name": "One Wrong",
                "driver_type": DriverType.LEASED_OPERATOR,
                "mileage_guide": "MOON",
                "per_diem_method": PerDiemMethod.NONE,
                "escrow_required": False,
            },
            ADMIN_HEADERS,
        )

        validate_error(one_wrong, ApiErrorId.INVALID_FIELD_VALUE, 422)
        packages, meta = validate_paginated(api_client.list_pay_packages(ADMIN_HEADERS))
        assert meta["total_count"] == 0, "neither attempt stored a row"
        assert packages == []


class TestDeliveryReadsTheSnapshotAndNotTheDriversCurrentPackage:
    """A package retired mid-transit still pays the load it was pinned onto."""

    def test_a_package_retired_mid_transit_still_pays_the_load_it_was_pinned_onto(self):
        """Retiring the package while the truck is rolling leaves the driver pointing at a RETIRED
        row, and reassigning the driver to a live package does not re-rate the movement: delivery
        pays 46080 off the retired snapshot either way.

        PRD 3.1: "`RETIRED` is terminal: a retired package can never be re-activated, revised or
        newly assigned, yet it stays fully readable, because loads dispatched while it was
        `ACTIVE` still point at it and are still paid from its components."
        PRD 3.4: "From this moment on, every pay computation on this load reads the snapshot and
        never the driver's current package, so a revision activated mid-week cannot retroactively
        re-rate a truck that is already rolling."
        PRD 3.1: "Drivers already pointing at the predecessor keep their `pay_package_id`
        untouched; only *new* assignments to the retired package are refused."

        Design: Corner/validations/delivering_under_a_retired_package_is_blocked_until_a_live_one_is_assigned
        """
        fixtures.reset_clock()
        retiring = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Retired Guide",
        )
        driver = fixtures.active_driver(
            retiring["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Rex Retired",
            home_state="TX",
        )
        load = fixtures.tender_load(driver["id"], stop_count=1)
        fixtures.set_clock(fixtures.TS_DISPATCH)
        fixtures.dispatch(load["id"])
        retired = validate_success(
            api_client.retire_pay_package(retiring["id"], ADMIN_HEADERS)
        )
        assert retired["status"] == PayPackageStatus.RETIRED
        replacement = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Replacement Guide",
        )
        validate_success(
            api_client.assign_pay_package(
                driver["id"],
                factories.assign_package_payload(replacement["id"]),
                ADMIN_HEADERS,
            )
        )
        assert fixtures.read_driver(driver["id"])["pay_package_id"] == replacement["id"]

        fixtures.set_clock(fixtures.TS_DELIVER)
        delivered = validate_success(
            api_client.deliver_load(load["id"], factories.deliver_payload(), CLERK_HEADERS)
        )

        assert delivered["movement_status"] == MovementStatus.DELIVERED
        assert delivered["pay_status"] == PayStatus.ACCRUED
        assert delivered["linehaul_pay_cents"] == 46080
        assert delivered["pay_package_id_snapshot"] == retiring["id"], (
            "pay is still read from the package pinned at dispatch"
        )


class TestSettlementPeriodOverlap:
    """Half-open windows, compared only against periods that still occupy the calendar."""

    def test_a_touching_window_is_free_and_a_voided_period_stops_blocking(self):
        """Three outcomes on one driver: an overlapping window is refused, a window starting exactly
        at the exclusive upper bound is accepted, and voiding the first period frees a window fully
        contained in it.

        PRD 3.7: "Pay periods may not double-count work, so the requested window may not overlap
        the `[period_start, period_end)` window of any other non-voided settlement of the same
        driver; an overlap is rejected with `ERR_SETTLEMENT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Corner/validations/settlement_periods_are_half_open_and_only_non_voided_ones_block
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Period Overlap",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Oren Overlap",
            home_state="TX",
        )
        fixtures.set_clock(fixtures.TS_SETTLE)
        first = fixtures.open_settlement(
            driver["id"], "2026-08-03T00:00:00Z", "2026-08-10T00:00:00Z"
        )

        overlapping = api_client.create_settlement(
            factories.settlement_payload(
                driver["id"], "2026-08-09T00:00:00Z", "2026-08-16T00:00:00Z"
            ),
            CLERK_HEADERS,
        )
        validate_error(overlapping, ApiErrorId.SETTLEMENT_PERIOD_OVERLAP, 409)

        touching = validate_success(
            api_client.create_settlement(
                factories.settlement_payload(
                    driver["id"], "2026-08-10T00:00:00Z", "2026-08-17T00:00:00Z"
                ),
                CLERK_HEADERS,
            ),
            201,
        )
        assert_timestamps_equal(
            touching["period_start"], "2026-08-10T00:00:00Z", "period_start"
        )

        voided = validate_success(
            api_client.void_settlement(
                first["id"],
                factories.void_payload(VoidReasonCode.WRONG_PERIOD),
                ADMIN_HEADERS,
            )
        )
        assert voided["status"] == SettlementStatus.VOIDED

        contained = validate_success(
            api_client.create_settlement(
                factories.settlement_payload(
                    driver["id"], "2026-08-05T00:00:00Z", "2026-08-08T00:00:00Z"
                ),
                CLERK_HEADERS,
            ),
            201,
        )
        assert contained["status"] == SettlementStatus.DRAFT
        settlements, meta = validate_paginated(
            api_client.list_settlements(AUDITOR_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 3


class TestAdvanceExposureCeiling:
    """The ceiling is checked against the sum, not against the request alone."""

    def test_the_ceiling_sums_the_request_with_the_outstanding_balance(self):
        """With 100000 already outstanding a 60000 request totals 160000 and is refused, while
        50000 lands exactly on the 150000 ceiling and is accepted.

        PRD 3.6: "Exposure per driver is capped: the requested `amount_cents` plus the driver's
        current `advance_outstanding_cents` may not exceed 150,000 cents, and a request that would
        breach that ceiling is rejected with `ERR_ADVANCE_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/advance_limit_sums_the_request_with_the_outstanding_balance
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Advance Limit",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Lila Limit",
            home_state="TX",
        )
        fixtures.set_clock("2026-08-02T09:00:00Z")
        fixtures.issue_advance(driver["id"], 100000, installment_cents=20000)
        assert fixtures.read_driver(driver["id"])["advance_outstanding_cents"] == 100000

        over = api_client.create_advance(
            factories.advance_payload(
                driver["id"], 60000, AdvanceType.FUEL_CARD, installment_cents=15000
            ),
            CLERK_HEADERS,
        )

        validate_error(over, ApiErrorId.ADVANCE_LIMIT_EXCEEDED, 422)
        assert fixtures.read_driver(driver["id"])["advance_outstanding_cents"] == 100000
        advances, meta = validate_paginated(
            api_client.list_advances(AUDITOR_HEADERS, {"driver_id": driver["id"]})
        )
        assert meta["total_count"] == 1, "the refused advance was never issued"

        exactly_at = validate_success(
            api_client.create_advance(
                factories.advance_payload(
                    driver["id"], 50000, AdvanceType.FUEL_CARD, installment_cents=15000
                ),
                CLERK_HEADERS,
            ),
            201,
        )

        assert exactly_at["status"] == AdvanceStatus.ISSUED
        assert exactly_at["outstanding_cents"] == 50000
        assert exactly_at["recovered_cents"] == 0
        assert fixtures.read_driver(driver["id"])["advance_outstanding_cents"] == 150000


class TestDocumentationRequirementIsPerType:
    """Paperwork is demanded by accessorial type, not by every claim."""

    def test_an_undocumented_detention_is_refused_while_a_stop_off_approves(self):
        """Both claims sit on the same delivered load with no document_ref, and only the detention
        is refused; attaching a document makes the identical approval pay 2000.

        PRD 3.5: "when either `documentation_required` is false or `document_ref` is non-null — a
        missing document on a detention, tarping or breakdown claim is `ERR_DOCUMENTATION_MISSING`
        (HTTP 422)"
        PRD 3.5: "`documentation_required` is computed at submission as true when
        `accessorial_type` is `DETENTION`, `TARPING` or `BREAKDOWN`, and false for `LAYOVER` and
        `STOP_OFF`."

        Design: Corner/validations/documentation_is_required_only_for_detention_tarping_and_breakdown
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Documentation",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Dora Docket",
            home_state="TX",
        )
        load = fixtures.delivered_load(driver["id"], stop_count=3)
        fixtures.set_clock("2026-08-05T09:00:00Z")
        detention = fixtures.submit_claim(
            load["id"],
            driver["id"],
            AccessorialType.DETENTION,
            "2026-08-04T08:00:00Z",
            "2026-08-04T11:00:00Z",
            None,
            CLERK_HEADERS,
        )
        stop_off = fixtures.submit_claim(
            load["id"],
            driver["id"],
            AccessorialType.STOP_OFF,
            "2026-08-04T12:00:00Z",
            "2026-08-04T13:00:00Z",
            None,
            CLERK_HEADERS,
        )
        assert detention["documentation_required"] is True
        assert stop_off["documentation_required"] is False

        refused = api_client.approve_accessorial_claim(detention["id"], CLERK_HEADERS)

        validate_error(refused, ApiErrorId.DOCUMENTATION_MISSING, 422)
        unpriced = fixtures.read_claim(detention["id"])
        assert unpriced["status"] == ClaimStatus.SUBMITTED
        assert unpriced["amount_cents"] == 0

        approved_stop_off = validate_success(
            api_client.approve_accessorial_claim(stop_off["id"], CLERK_HEADERS)
        )
        assert approved_stop_off["status"] == ClaimStatus.APPROVED
        assert approved_stop_off["billable_units"] == 2
        assert approved_stop_off["amount_cents"] == 10000
        assert approved_stop_off["document_ref"] is None, "STOP_OFF needs no paperwork"

        validate_success(
            api_client.attach_claim_document(
                detention["id"],
                factories.claim_document_payload("doc://detention-log-doc"),
                CLERK_HEADERS,
            )
        )
        approved_detention = validate_success(
            api_client.approve_accessorial_claim(detention["id"], CLERK_HEADERS)
        )

        assert approved_detention["status"] == ClaimStatus.APPROVED
        assert approved_detention["billable_units"] == 4, "180 minutes less the 120 free"
        assert approved_detention["amount_cents"] == 2000
        assert approved_detention["document_ref"] == "doc://detention-log-doc"


class TestEscrowReturnIsTimeGated:
    """Termination starts a 45-day clock that the return has to wait out."""

    def test_the_return_is_refused_before_the_due_instant_and_succeeds_exactly_on_it(self):
        """A settlement approval deposits 3686, terminating on 15 August fixes the due instant at
        29 September, and only then does the principal leave as a single negative ledger row.

        PRD 3.3: "closing moves the axis `COLLECTING` → `CLOSING` or `FUNDED` → `CLOSING`, computes
        `escrow_return_due_at` as the driver's `terminated_at` plus 45 days, writes no ledger row at
        all — the principal is untouched — and bumps the driver's `version`."
        PRD 3.3: "A return may only be executed while `escrow_status` is `CLOSING`, only at or after
        `escrow_return_due_at` (an earlier attempt is rejected with `ERR_ESCROW_RETURN_NOT_DUE`,
        HTTP 409)"
        PRD 3.3: "the server appends a ledger entry with `txn_type` `RETURN_DISBURSEMENT` and
        `reason_code` `TERMINATION_RETURN` whose `amount_cents` is the negation of the whole current
        `escrow_balance_cents`; that append itself drives `escrow_balance_cents` to 0"

        Design: Corner/validations/escrow_return_waits_out_the_escrow_return_days_clock_after_termination
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=True,
            escrow_target_cents=250000,
            escrow_monthly_deduction_cents=40000,
            name="Leased Escrow Return",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Elsa Escrow",
            home_state="TX",
        )
        fixtures.delivered_load(driver["id"], stop_count=1)
        settlement = fixtures.approved_settlement(driver["id"])
        assert settlement["escrow_deduction_cents"] == 3686
        assert settlement["net_pay_cents"] == 42394
        funded = fixtures.read_driver(driver["id"])
        assert funded["escrow_balance_cents"] == 3686
        assert funded["escrow_status"] == EscrowStatus.COLLECTING

        fixtures.set_clock("2026-08-15T12:00:00Z")
        fixtures.set_driver_status(driver["id"], EmploymentStatus.TERMINATED)
        closing = validate_success(api_client.close_escrow(driver["id"], ADMIN_HEADERS))
        assert closing["escrow_status"] == EscrowStatus.CLOSING
        assert_timestamps_equal(
            closing["escrow_return_due_at"], "2026-09-29T12:00:00Z", "escrow_return_due_at"
        )

        fixtures.set_clock("2026-09-01T00:00:00Z")
        early = api_client.return_escrow(
            driver["id"], ADMIN_HEADERS, factories.escrow_return_payload("ACH-ESR-EARLY")
        )

        validate_error(early, ApiErrorId.ESCROW_RETURN_NOT_DUE, 409)
        waiting = fixtures.read_driver(driver["id"])
        assert waiting["escrow_status"] == EscrowStatus.CLOSING
        assert waiting["escrow_balance_cents"] == 3686
        assert waiting["escrow_returned_at"] is None

        fixtures.set_clock("2026-09-29T12:00:00Z")
        returned = validate_success(
            api_client.return_escrow(
                driver["id"], ADMIN_HEADERS, factories.escrow_return_payload("ACH-ESR-DUE")
            )
        )

        assert returned["escrow_status"] == EscrowStatus.RETURNED
        assert returned["escrow_balance_cents"] == 0
        assert_timestamps_equal(
            returned["escrow_returned_at"], "2026-09-29T12:00:00Z", "escrow_returned_at"
        )
        disbursements, meta = validate_paginated(
            api_client.list_escrow_transactions(
                AUDITOR_HEADERS,
                {
                    "driver_id": driver["id"],
                    "txn_type": EscrowTxnType.RETURN_DISBURSEMENT,
                },
            )
        )
        assert meta["total_count"] == 1
        assert disbursements[0]["amount_cents"] == -3686
        assert disbursements[0]["balance_after_cents"] == 0
