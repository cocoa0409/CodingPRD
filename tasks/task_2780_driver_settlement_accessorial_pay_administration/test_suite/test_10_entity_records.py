"""Record shapes: what the server mints, what it defaults, and what it refuses to accept.

Creation responses are the only place a caller learns a server-minted id, so their shape is
part of the contract, as are the fields that stay null until a workflow computes them.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CLERK_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_append_only_record_shape,
    assert_timestamps_equal,
    factories,
    fixtures,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.types import (
    AccessorialType,
    ClaimStatus,
    ComponentType,
    DriverType,
    EscrowStatus,
    LineType,
    MileageGuide,
    MovementStatus,
    PayPackageStatus,
    PayStatus,
    PerDiemMethod,
    RateUnit,
    ReferenceType,
)


class TestPayPackageCreation:
    """A package is born configurable and unpayable."""

    def test_create_returns_a_draft_package_with_no_components_yet(self):
        """The 201 response echoes every supplied field and carries the server-minted id, a
        DRAFT status, version 1, a zero component count and null activation stamps.

        PRD 3.1: "A newly created package is `DRAFT`, its `component_count` is 0, its
        `has_pending_revision` is false, and its `supersedes_pay_package_id`, `activated_at` and
        `retired_at` are all null."

        Design: Corner/entities/create_pay_package_returns_draft_package_with_component_count_zero
        """
        fixtures.reset_clock()

        created = validate_success(
            api_client.create_pay_package(
                factories.pay_package_payload(
                    name="Leased Standard 2026",
                    driver_type=DriverType.LEASED_OPERATOR,
                    mileage_guide=MileageGuide.PRACTICAL,
                    per_diem_method=PerDiemMethod.DAY_BASED,
                    escrow_required=True,
                    escrow_target_cents=250000,
                    escrow_monthly_deduction_cents=40000,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert is_valid_uuid(created["id"])
        assert created["status"] == PayPackageStatus.DRAFT
        assert created["version"] == 1
        assert created["name"] == "Leased Standard 2026"
        assert created["driver_type"] == DriverType.LEASED_OPERATOR
        assert created["mileage_guide"] == MileageGuide.PRACTICAL
        assert created["per_diem_method"] == PerDiemMethod.DAY_BASED
        assert created["escrow_required"] is True
        assert created["escrow_target_cents"] == 250000
        assert created["escrow_monthly_deduction_cents"] == 40000
        assert created["component_count"] == 0
        assert created["has_pending_revision"] is False
        assert created["supersedes_pay_package_id"] is None
        assert created["activated_at"] is None
        assert created["retired_at"] is None

    def test_system_fields_move_only_through_the_activation_transition(self):
        """A caller cannot hand itself an ACTIVE package: appending a component leaves the status
        DRAFT and only activation stamps activated_at and moves the version.

        PRD 3.1: "A successful activation sets `status` to `ACTIVE`, stamps `activated_at` from
        the logical clock and increments the package's `version` by 1."
        PRD 2.11: "On the package side, `component_count` is the number of pay components whose
        `pay_package_id` is that package."

        Design: Corner/entities/pay_package_system_fields_are_server_initialised_and_only_move_by_transition
        """
        fixtures.reset_clock()
        created = validate_success(
            api_client.create_pay_package(
                factories.pay_package_payload(
                    name="Owner Op Baseline",
                    driver_type=DriverType.OWNER_OPERATOR,
                    mileage_guide=MileageGuide.HHG,
                    per_diem_method=PerDiemMethod.NONE,
                    escrow_required=False,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert created["status"] == PayPackageStatus.DRAFT
        assert created["created_at"] is not None
        assert created["updated_at"] is not None
        original_version = created["version"]

        validate_success(
            api_client.add_component(
                created["id"],
                factories.revenue_percent_component(rate_value=7000, sequence=1),
                ADMIN_HEADERS,
            ),
            201,
        )
        after_component = validate_success(
            api_client.get_pay_package(created["id"], ADMIN_HEADERS)
        )
        assert after_component["status"] == PayPackageStatus.DRAFT
        assert after_component["component_count"] == 1
        assert after_component["activated_at"] is None

        validate_success(api_client.activate_pay_package(created["id"], ADMIN_HEADERS))

        activated = validate_success(api_client.get_pay_package(created["id"], ADMIN_HEADERS))
        assert activated["status"] == PayPackageStatus.ACTIVE
        assert_timestamps_equal(activated["activated_at"], CLOCK_EPOCH)
        assert activated["version"] > original_version

    def test_an_undeclared_enum_member_and_a_negative_magnitude_are_both_invalid(self):
        """driver_type is a closed four-member enumeration and money magnitudes may not be
        negative, so each body is refused before any row is written.

        PRD 2.9 rung 5: "`ERR_INVALID_FIELD_VALUE` — enum fields carry a declared member; money
        and count fields are integers; client-supplied magnitudes (an `amount_cents` on a request,
        miles, minutes, `stop_count`, `rate_value`) are not negative".
        PRD 3.1: "Both default to 0 and neither may be negative."

        Design: Corner/entities/create_pay_package_with_undeclared_driver_type_returns_invalid_field_value
        """
        fixtures.reset_clock()

        bad_enum = api_client.create_pay_package(
            factories.pay_package_payload(
                name="Bad Enum",
                driver_type="OWNER_OPERATOR_LITE",
                mileage_guide=MileageGuide.PRACTICAL,
                per_diem_method=PerDiemMethod.NONE,
                escrow_required=False,
            ),
            ADMIN_HEADERS,
        )
        bad_magnitude = api_client.create_pay_package(
            factories.pay_package_payload(
                name="Bad Magnitude",
                driver_type=DriverType.OWNER_OPERATOR,
                mileage_guide=MileageGuide.PRACTICAL,
                per_diem_method=PerDiemMethod.NONE,
                escrow_required=True,
                escrow_target_cents=-5000,
                escrow_monthly_deduction_cents=40000,
            ),
            ADMIN_HEADERS,
        )

        validate_error(bad_enum, ApiErrorId.INVALID_FIELD_VALUE, 422)
        validate_error(bad_magnitude, ApiErrorId.INVALID_FIELD_VALUE, 422)
        packages, meta = validate_paginated(api_client.list_pay_packages(ADMIN_HEADERS))
        assert meta["total_count"] == 0
        assert packages == []

    def test_read_back_recomputes_the_component_count_and_lists_the_components_in_sequence(self):
        """The count is derived from the component rows rather than frozen at creation, and the
        sub-resource listing returns both legs in sequence order with their stored rates.

        PRD 3.1: "A component names its `component_type` ... the `unit` its rate is expressed in,
        the integer `rate_value` ... and an integer `sequence` of at least 1 that fixes the
        deterministic order in which the component is applied inside the package."
        PRD 2.11: "On the package side, `component_count` is the number of pay components whose
        `pay_package_id` is that package."

        Design: Corner/entities/get_pay_package_by_id_returns_the_stored_row_with_component_count
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Read Back",
        )

        read = validate_success(api_client.get_pay_package(package["id"], AUDITOR_HEADERS))
        components, meta = validate_paginated(
            api_client.list_components(package["id"], AUDITOR_HEADERS)
        )

        assert read["status"] == PayPackageStatus.ACTIVE
        assert read["component_count"] == 2
        assert_timestamps_equal(read["activated_at"], CLOCK_EPOCH)
        assert meta["total_count"] == 2
        assert [component["sequence"] for component in components] == [1, 2]
        assert components[0]["component_type"] == ComponentType.PER_MILE
        assert components[0]["unit"] == RateUnit.MILE
        assert components[0]["rate_value"] == 58
        assert components[1]["component_type"] == ComponentType.REVENUE_PERCENT
        assert components[1]["unit"] == RateUnit.PERCENT_BPS
        assert components[1]["rate_value"] == 2500
        for component in components:
            assert component["pay_package_id"] == package["id"]

    def test_a_component_write_against_an_unknown_package_is_a_404(self):
        """A well-formed component body aimed at a package id that does not resolve is a 404
        on that first path identifier, not a 201 against nothing.

        PRD 2.7: "Asking for the components of a pay-package id that does not exist yields
        `ERR_PAY_PACKAGE_NOT_FOUND` (HTTP 404)".
        PRD 2.9 rung 7: "`ERR_PAY_PACKAGE_NOT_FOUND` — the pay package addressed by the path, or
        named by `pay_package_id` in the body, exists."

        Design: Corner/entities/add_component_to_unknown_pay_package_returns_pay_package_not_found
        """
        fixtures.reset_clock()

        response = api_client.add_component(
            NON_EXISTENT_UUID,
            {"component_type": "PER_MILE", "unit": "MILE", "rate_value": 58, "sequence": 1},
            ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.PAY_PACKAGE_NOT_FOUND, 404)


class TestDriverRecords:
    """Registration, lookup and the derived escrow axis a filter reads."""

    def test_the_escrow_status_filter_excludes_a_driver_who_never_needed_escrow(self):
        """Two drivers registered side by side land on different escrow axes purely because of
        their packages, and filtering by COLLECTING returns only the one that accrues.

        PRD 2.3: "Drivers may be filtered by `employment_status`, `driver_type`, `escrow_status`
        and `pay_package_id`."
        PRD 3.3: "A driver assigned a package whose `escrow_required` is false simply stays in
        `NOT_REQUIRED`, which is why that is the initial state rather than an unreachable
        placeholder."

        Design: Corner/entities/list_drivers_filtered_by_escrow_status_excludes_not_required_drivers
        """
        fixtures.reset_clock()
        escrow_package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=True,
            name="Leased With Escrow",
        )
        plain_package = fixtures.active_package(
            driver_type=DriverType.COMPANY_SOLO,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            revenue_bps=None,
            escrow_required=False,
            name="Company No Escrow",
        )
        collecting = fixtures.active_driver(
            escrow_package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Cora Collecting",
            home_state="TX",
        )
        not_required = fixtures.active_driver(
            plain_package["id"],
            driver_type=DriverType.COMPANY_SOLO,
            per_diem_elected=False,
            legal_name="Nate Notrequired",
            home_state="TX",
        )
        assert collecting["escrow_status"] == EscrowStatus.COLLECTING
        assert not_required["escrow_status"] == EscrowStatus.NOT_REQUIRED
        assert not_required["escrow_target_cents"] == 0

        filtered, meta = validate_paginated(
            api_client.list_drivers(
                ADMIN_HEADERS, {"escrow_status": EscrowStatus.COLLECTING}
            )
        )

        assert meta["total_count"] == 1
        assert [driver["id"] for driver in filtered] == [collecting["id"]]
        unfiltered, all_meta = validate_paginated(api_client.list_drivers(ADMIN_HEADERS))
        assert all_meta["total_count"] == 2

    def test_a_well_formed_but_unknown_driver_id_is_a_404(self):
        """The path identifier parses as a UUID and simply resolves to nothing, which is a
        not-found rather than a field-validation failure.

        PRD 2.9 rung 6: "`ERR_DRIVER_NOT_FOUND` — the driver addressed by the path, or named by
        `driver_id` in the body, exists."

        Design: Corner/entities/get_driver_with_unknown_uuid_returns_driver_not_found
        """
        fixtures.reset_clock()

        response = api_client.get_driver(NON_EXISTENT_UUID, ADMIN_HEADERS)

        validate_error(response, ApiErrorId.DRIVER_NOT_FOUND, 404)


def _driver_ready_for_loads():
    """An ACTIVE leased operator on a per-mile package, ready to be tendered a load."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=False,
        name="Leased Entity Records",
    )
    return fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Lena Loadwright",
        home_state="TX",
    )


class TestLoadRecords:
    """What a tender requires, what it defaults, and what stays null until delivery."""

    def test_both_guide_distances_are_required_on_a_tender(self):
        """A load carries the distance under both guides so that a mileage dispute can later
        re-grade it, so omitting hhg_miles is refused; supplying it is accepted.

        PRD 2.9 rung 4: "`ERR_MISSING_REQUIRED_FIELD` — every field the endpoint requires is
        present and not null."
        PRD 3.4: "The tender carries the `driver_id`, the `linehaul_revenue_cents` the carrier
        bills the shipper ... and **both** mileage figures for the same movement:
        `practical_miles` ... and `hhg_miles`".

        Design: Corner/entities/create_load_without_hhg_miles_returns_missing_required_field
        """
        fixtures.reset_clock()
        driver = _driver_ready_for_loads()

        incomplete = api_client.create_load(
            {
                "driver_id": driver["id"],
                "linehaul_revenue_cents": 180000,
                "practical_miles": 780,
            },
            ADMIN_HEADERS,
        )
        validate_error(incomplete, ApiErrorId.MISSING_REQUIRED_FIELD, 422)

        complete = validate_success(
            api_client.create_load(
                factories.load_payload(driver["id"], practical_miles=780, hhg_miles=742),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert complete["practical_miles"] == 780
        assert complete["hhg_miles"] == 742
        assert complete["movement_status"] == MovementStatus.TENDERED
        assert complete["pay_status"] == PayStatus.UNPAID

    def test_omitted_optional_fields_take_their_declared_defaults(self):
        """No stop_count and no tarp_required means one stop and no tarp, and the movement
        stamps that only later steps fill in start out null.

        PRD 3.4: "`stop_count` — the total number of stops including the final delivery, at least
        1, defaulting to 1 when omitted — and `tarp_required`, a boolean defaulting to false".
        PRD 3.4: "A tendered load starts with `movement_status` `TENDERED`, `pay_status` `UNPAID`,
        `hours_worked_minutes` 0, and `settlement_id`, `pay_package_id_snapshot`, `dispatched_at`
        and `delivered_at` all null."

        Design: Corner/entities/create_load_omitting_optional_fields_applies_declared_defaults
        """
        fixtures.reset_clock()
        driver = _driver_ready_for_loads()

        load = validate_success(
            api_client.create_load(
                {
                    "driver_id": driver["id"],
                    "linehaul_revenue_cents": 180000,
                    "practical_miles": 780,
                    "hhg_miles": 742,
                },
                ADMIN_HEADERS,
            ),
            201,
        )

        assert load["stop_count"] == 1
        assert load["tarp_required"] is False
        assert load["hours_worked_minutes"] == 0
        assert load["movement_status"] == MovementStatus.TENDERED
        assert load["pay_status"] == PayStatus.UNPAID
        assert load["settlement_id"] is None
        assert load["pay_package_id_snapshot"] is None
        assert load["dispatched_at"] is None
        assert load["delivered_at"] is None

    def test_the_pay_fields_stay_null_through_dispatch_and_are_filled_by_delivery(self):
        """Dispatch pins the package snapshot but computes no money; only delivery selects the
        guide, the paid miles and the winning linehaul component.

        PRD 3.4: "Before delivery, `applied_mileage_guide`, `base_guide_miles`, `paid_miles`,
        `linehaul_pay_cents` and `linehaul_line_type` are all null."
        PRD 3.4: "Dispatching a tendered load advances `TENDERED` → `IN_TRANSIT`, sets
        `dispatched_at` ... and — the critical act — **pins** `pay_package_id_snapshot` to the
        driver's current `pay_package_id`".

        Design: Corner/entities/the_pay_fields_of_a_load_stay_null_until_delivery_computes_them
        """
        fixtures.reset_clock()
        driver = _driver_ready_for_loads()
        load = fixtures.tender_load(driver["id"], stop_count=1)
        for field in (
            "applied_mileage_guide",
            "base_guide_miles",
            "paid_miles",
            "linehaul_pay_cents",
            "linehaul_line_type",
        ):
            assert load[field] is None, f"{field} is computed by delivery, not by tender"

        fixtures.set_clock(fixtures.TS_DISPATCH)
        fixtures.dispatch(load["id"])
        in_transit = fixtures.read_load(load["id"])
        assert in_transit["movement_status"] == MovementStatus.IN_TRANSIT
        assert in_transit["pay_package_id_snapshot"] is not None
        for field in (
            "applied_mileage_guide",
            "base_guide_miles",
            "paid_miles",
            "linehaul_pay_cents",
            "linehaul_line_type",
        ):
            assert in_transit[field] is None, f"{field} is still null in transit"

        fixtures.set_clock(fixtures.TS_DELIVER)
        fixtures.deliver(load["id"])
        delivered = fixtures.read_load(load["id"])

        assert delivered["applied_mileage_guide"] == MileageGuide.PRACTICAL
        assert delivered["base_guide_miles"] == 780
        assert delivered["paid_miles"] == 780
        assert delivered["linehaul_pay_cents"] == 46080
        assert delivered["linehaul_line_type"] == LineType.LINEHAUL_PER_MILE
        assert delivered["pay_status"] == PayStatus.ACCRUED


class TestSettlementLineRecords:
    """A statement line is a log entry, not an editable row."""

    def test_a_generated_line_carries_no_version_or_updated_at(self):
        """The line exposes an id and a created_at and nothing else from the mutable-record
        convention, and it carries the reference pair and quantity behind the money.

        PRD 2.4: "**`updated_at` and `version` are absent from a `PayComponent`, from an
        `EscrowTransaction` and from a `SettlementLine`**."
        PRD 3.7: "a `reference_type` of `LOAD`, `ACCESSORIAL_CLAIM`, `ADVANCE`,
        `RETRO_CORRECTION` or `DRIVER` together with the `reference_id` it resolves to".

        Design: Corner/entities/settlement_line_rows_are_immutable_and_carry_no_version_field
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Line Shape",
        )
        driver = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Sam Statement",
            home_state="TX",
        )
        load = fixtures.delivered_load(driver["id"], stop_count=1)
        settlement = fixtures.prepared_settlement(driver["id"])
        assert settlement["line_count"] == 1

        lines = fixtures.read_settlement_lines(settlement["id"])

        assert len(lines) == 1
        line = lines[0]
        assert_append_only_record_shape(line)
        assert line["settlement_id"] == settlement["id"]
        assert line["line_type"] == LineType.LINEHAUL_PER_MILE
        assert line["reference_type"] == ReferenceType.LOAD
        assert line["reference_id"] == load["id"]
        assert line["quantity"] == 780
        assert line["rate_value"] == 58
        assert line["amount_cents"] == 46080
        assert line["sequence"] == 1


class TestAccessorialClaimOwnership:
    """The claiming driver is denormalized from the load and must agree with it."""

    def test_a_claim_naming_a_driver_who_did_not_move_the_load_is_refused(self):
        """Both the load and the named driver exist, so this is not a not-found; the two simply
        disagree, and the same claim against the load's own driver is accepted unpriced.

        PRD 3.5: "The `driver_id` is denormalized from the load's own `driver_id` at creation and
        never re-derived afterwards, so it must agree with it: a claim naming a driver who did not
        move the load is rejected with `ERR_DRIVER_MISMATCH` (HTTP 422)."
        PRD 3.5: "A new claim is `SUBMITTED`, its `billable_units` and `amount_cents` are 0 until
        approval, its `settlement_id` and `approved_by_user_id` are null".

        Design: Corner/entities/accessorial_claim_naming_another_drivers_load_returns_driver_mismatch
        """
        fixtures.reset_clock()
        package = fixtures.active_package(
            driver_type=DriverType.LEASED_OPERATOR,
            mileage_guide=MileageGuide.PRACTICAL,
            per_diem_method=PerDiemMethod.NONE,
            escrow_required=False,
            name="Leased Claim Ownership",
        )
        hauler = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Ida Ithauled",
            home_state="TX",
        )
        bystander = fixtures.active_driver(
            package["id"],
            driver_type=DriverType.LEASED_OPERATOR,
            per_diem_elected=False,
            legal_name="Bea Bystander",
            home_state="TX",
        )
        load = fixtures.delivered_load(hauler["id"], stop_count=1)

        mismatched = api_client.create_accessorial_claim(
            factories.detention_claim_payload(
                load["id"],
                bystander["id"],
                "2026-08-05T08:00:00Z",
                "2026-08-05T11:00:00Z",
                document_ref="doc://det-mismatch",
            ),
            CLERK_HEADERS,
        )
        validate_error(mismatched, ApiErrorId.DRIVER_MISMATCH, 422)

        matched = validate_success(
            api_client.create_accessorial_claim(
                factories.detention_claim_payload(
                    load["id"],
                    hauler["id"],
                    "2026-08-05T08:00:00Z",
                    "2026-08-05T11:00:00Z",
                    document_ref="doc://det-match",
                ),
                CLERK_HEADERS,
            ),
            201,
        )

        assert matched["driver_id"] == hauler["id"]
        assert matched["accessorial_type"] == AccessorialType.DETENTION
        assert matched["status"] == ClaimStatus.SUBMITTED
        assert matched["billable_units"] == 0
        assert matched["amount_cents"] == 0
        assert matched["settlement_id"] is None
        assert matched["approved_by_user_id"] is None
