"""The error vocabulary: singleton and header guards, 404 resolution order, volume,
float, excise, franchise, sellability, transition, notice and destructive guards."""

from test_helpers import (
    ADMIN,
    APPT_ACTIVE,
    APPT_PROPOSED,
    APPT_TERMINATED,
    APPT_TERMINATION_REQUESTED,
    BASIS_WHOLE_KEG_REMOVAL,
    BATCH_BREWING,
    BATCH_CONDITIONING,
    BATCH_DUMPED,
    BATCH_PACKAGED,
    CELLAR,
    CHANNEL_TAPROOM,
    COMPLIANCE,
    CONTAINER_PINT_16OZ,
    DECISION_APPROVED,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    ERR_AMENDMENT_TARGET_NOT_FILED,
    ERR_APPOINTMENT_NOT_FOUND,
    ERR_APPOINTMENT_TRANSITION_INVALID,
    ERR_BATCH_HAS_PLANNED_RUNS,
    ERR_BATCH_NOT_CONDITIONING,
    ERR_BATCH_NOT_FOUND,
    ERR_BREWERY_ALREADY_EXISTS,
    ERR_BREWERY_NOT_FOUND,
    ERR_DUPLICATE_APPOINTMENT_SCOPE,
    ERR_DUPLICATE_CODE,
    ERR_EVENT_PERMIT_NOT_FOUND,
    ERR_FILING_TRANSITION_INVALID,
    ERR_FORMULA_NOT_APPROVED,
    ERR_KEG_ASSET_NOT_FOUND,
    ERR_KEG_NOT_TAPPED,
    ERR_KEG_SIZE_MISMATCH,
    ERR_KEG_TRANSITION_INVALID,
    ERR_LICENSE_EXPIRED,
    ERR_NOTICE_NOT_ACTIVE,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_TRANSITION_INVALID,
    ERR_PACKAGING_RUN_NOT_FOUND,
    ERR_PERIOD_ALREADY_FILED,
    ERR_PERIOD_NOT_CLOSED,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_TRANSITION_INVALID,
    ERR_RETURN_EXCEEDS_FILL,
    ERR_RUN_HAS_ALLOCATIONS,
    ERR_RUN_TRANSITION_INVALID,
    ERR_RUN_UNITS_EXHAUSTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STATE_LICENSE_NOT_FOUND,
    ERR_TANK_CAPACITY_EXCEEDED,
    ERR_TANK_TRANSITION_INVALID,
    ERR_TAPROOM_POUR_NOT_FOUND,
    ERR_TERMINATION_NOTICE_NOT_ELAPSED,
    ERR_UNAUTHENTICATED,
    ERR_UNITS_EXCEED_BATCH_VOLUME,
    FILING_FORMULA,
    FILING_LABEL,
    GOOD_CAUSE_NONPAYMENT,
    KEG_CLEANED,
    KEG_EMPTY_DIRTY,
    KEG_FILLED,
    KEG_SIZE_HALF_BBL,
    KEG_TAPPED,
    LABEL_NO_LABEL,
    LICENSE_EXPIRED,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_WHOLESALER_ONLY,
    MOVEMENT_TAP,
    NOTICE_ACTION_ACTIVATE,
    NOTICE_ACTIVE,
    ORDER_CANCELLED,
    PACKAGE_CAN_CASE_24,
    PACKAGE_HALF_BBL_KEG,
    RECON_OPEN,
    REG_DRAFT,
    REG_FORMULA_APPROVED,
    REG_FORMULA_PENDING,
    REGULATOR,
    REPORT_DRAFT,
    REPORT_FILED,
    ROLE_COMPLIANCE_OFFICER,
    RUN_COMPLETED,
    RUN_PLANNED,
    RUN_VOIDED,
    SANITATION_NOT_REQUIRED,
    SCOPE_ALL_BRANDS,
    TANK_ACTION_CIP,
    TANK_DIRTY,
    TANK_OCCUPIED,
    TAPROOM,
    TERMINATION_FINALIZE,
    TERMINATION_REQUEST,
    TERMINATION_WITHDRAW,
    UNKNOWN_UUID,
    assert_bbl,
    assert_cents,
    assert_instant_equals,
    assert_oz,
    cancel_order_payload,
    complete_run_payload,
    condition_payload,
    dump_payload,
    filing_decision_payload,
    formula_filing_payload,
    headers_blank_role,
    headers_for,
    keg_clean_payload,
    keg_fill_payload,
    keg_movement_payload,
    keg_return_payload,
    notice_payload,
    pour_payload,
    tank_service_payload,
    termination_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import appointment_payload
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_active_appointment,
    create_allocated_order,
    create_cleaned_keg,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_draft_beer,
    create_exempt_beer,
    create_filled_keg,
    create_keg,
    create_license,
    create_scheduled_batch,
    create_tank,
    create_tapped_keg,
    draft_report,
    plan_run,
    propose_appointment,
    reinstate_notice,
    set_clock,
    submit_order,
    suspend_notice,
)
from test_helpers.test_users import USER_ADMIN_1, USER_COMPLIANCE_1

AUGUST_START = "2026-08-01T00:00:00Z"
AUGUST_END = "2026-09-01T00:00:00Z"
DUMP_REASON = "diacetyl off-flavour confirmed by the lab"
CANCEL_REASON = "buyer withdrew the purchase order"


def _license_window(**overrides):
    payload = {
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "expires_at_utc": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _conditioning_batch(api, beer_id, capacity_bbl=30.00, actual_yield_bbl=16.000):
    tank = create_tank(api, code="FV-01", capacity_bbl=capacity_bbl)
    batch = create_conditioning_batch(
        api,
        beer_id,
        tank["id"],
        actual_yield_bbl=actual_yield_bbl,
        batch_code="B-1001",
        planned_volume_bbl=16.00,
        brew_start_utc="2026-08-01T06:00:00Z",
        brew_end_utc="2026-08-08T06:00:00Z",
    )
    return tank, batch


class TestSingletonAndHeaderGuards:
    def test_the_cheapest_surface_answers_four_distinct_refusals(self, api):
        """Missing singleton, blank role, replayed singleton and duplicate state code.

        PRD §2.8: "`ERR_BREWERY_NOT_FOUND` additionally answers any operation that
        needs the brewery singleton when no brewery row has been created at all."

        PRD §2.1: "If either header is absent, is supplied as an empty string, is
        blank, or if `X-User-Role` names anything other than one of the five roles
        below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §3.1: "Exactly one brewery row may ever exist; a second creation attempt
        is refused with `ERR_BREWERY_ALREADY_EXISTS`."

        PRD §2.8: "**Business-code uniqueness** — `ERR_DUPLICATE_CODE` (409) when the
        submitted human-authored code already exists."

        Design: Corner/errors/singleton_and_header_guards_reject_a_missing_brewery_blank_role_and_duplicates
        """
        validate_error(api.get_brewery(ADMIN), ERR_BREWERY_NOT_FOUND, 404)
        validate_error(api.get_brewery(headers_blank_role()), ERR_UNAUTHENTICATED, 401)

        created = validate_success(
            api.create_brewery(
                {
                    "legal_name": "Cascade Ridge Brewing",
                    "home_state_code": "OR",
                    "ttb_brewers_notice_number": "BR-OR-4417",
                },
                ADMIN,
            ),
            201,
        )
        validate_error(
            api.create_brewery(
                {
                    "legal_name": "Cascade Ridge Brewing II",
                    "home_state_code": "OR",
                    "ttb_brewers_notice_number": "BR-OR-9999",
                },
                ADMIN,
            ),
            ERR_BREWERY_ALREADY_EXISTS,
            409,
        )
        assert created["legal_name"] == "Cascade Ridge Brewing"
        assert (
            validate_success(api.get_brewery(ADMIN))["legal_name"]
            == "Cascade Ridge Brewing"
        )

        validate_success(
            api.drive_notice(notice_payload(NOTICE_ACTION_ACTIVATE), REGULATOR)
        )
        validate_success(
            api.create_state_license(
                dict(
                    state_code="ID",
                    license_type=LICENSE_SELF_DISTRIBUTION,
                    annual_barrel_cap=1000.00,
                    franchise_state=False,
                    **_license_window(),
                ),
                COMPLIANCE,
            ),
            201,
        )
        validate_error(
            api.create_state_license(
                dict(
                    state_code="ID",
                    license_type=LICENSE_WHOLESALER_ONLY,
                    annual_barrel_cap=0.00,
                    franchise_state=True,
                    **_license_window(),
                ),
                COMPLIANCE,
            ),
            ERR_DUPLICATE_CODE,
            409,
        )

        rows, meta = validate_paginated(api.list_state_licenses(COMPLIANCE))
        assert meta["total_count"] == 1
        assert rows[0]["license_type"] == LICENSE_SELF_DISTRIBUTION


class TestLeftToRightResolution:
    def test_the_path_parameter_is_resolved_before_the_body_foreign_key(self, api):
        """With both identifiers unknown the keg's own 404 wins; each read owns a code.

        PRD §2.8: "**Path-parameter existence** — resources named by URL path
        variables are resolved **left to right**, and the first identifier that
        resolves to nothing produces its own entity-specific 404."

        PRD §2.8: "**Body foreign-key existence** — identifiers carried in the request
        body are resolved next, using the same entity-specific 404 vocabulary."

        Design: Corner/errors/unknown_identifiers_resolve_left_to_right_into_entity_specific_not_founds
        """
        bootstrap_brewery(api)
        keg = create_keg(api, KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")

        validate_error(
            api.get_packaging_run(UNKNOWN_UUID, CELLAR), ERR_PACKAGING_RUN_NOT_FOUND, 404
        )
        validate_error(
            api.fill_keg_asset(UNKNOWN_UUID, keg_fill_payload(UNKNOWN_UUID), CELLAR),
            ERR_KEG_ASSET_NOT_FOUND,
            404,
        )
        validate_error(
            api.fill_keg_asset(keg["id"], keg_fill_payload(UNKNOWN_UUID), CELLAR),
            ERR_PACKAGING_RUN_NOT_FOUND,
            404,
        )
        validate_error(api.get_batch(UNKNOWN_UUID, CELLAR), ERR_BATCH_NOT_FOUND, 404)
        validate_error(
            api.get_state_license(UNKNOWN_UUID, COMPLIANCE),
            ERR_STATE_LICENSE_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_distributor_appointment(UNKNOWN_UUID, COMPLIANCE),
            ERR_APPOINTMENT_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_distribution_order(UNKNOWN_UUID, ADMIN), ERR_ORDER_NOT_FOUND, 404
        )
        validate_error(
            api.get_excise_report(UNKNOWN_UUID, ADMIN), ERR_REPORT_NOT_FOUND, 404
        )
        validate_error(
            api.get_event_permit(UNKNOWN_UUID, COMPLIANCE), ERR_EVENT_PERMIT_NOT_FOUND, 404
        )

        stored = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert stored["state"] == KEG_EMPTY_DIRTY
        assert stored["packaging_run_id"] is None


class TestVolumeGuards:
    def test_an_over_capacity_yield_and_an_over_batch_completion_are_both_refused(self, api):
        """Two ceilings on one chain: the vessel at conditioning, the batch at completion.

        PRD §3.2: "The payload carries `actual_yield_bbl`, which must be strictly
        greater than zero, must not exceed the occupied vessel's `capacity_bbl` — a
        yield above capacity is `ERR_TANK_CAPACITY_EXCEEDED` — and carries three
        decimal places."

        PRD §3.3: "The barrels the run removes, `bbl_removed`, are `units_produced`
        multiplied by the barrel content of the run's `package_type`, rounded half up
        to three decimal places, and that figure may not exceed the batch's current
        `remaining_bbl`; a request that would remove more than the batch has left is
        refused with `ERR_UNITS_EXCEED_BATCH_VOLUME`."

        Design: Corner/errors/volume_guards_reject_an_over_capacity_yield_and_an_over_batch_run
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = create_scheduled_batch(
            api,
            beer["id"],
            tank["id"],
            batch_code="B-1001",
            planned_volume_bbl=16.00,
            brew_start_utc="2026-08-01T06:00:00Z",
            brew_end_utc="2026-08-08T06:00:00Z",
        )
        validate_success(api.start_batch(batch["id"], CELLAR))

        validate_error(
            api.condition_batch(batch["id"], condition_payload(31.000), CELLAR),
            ERR_TANK_CAPACITY_EXCEEDED,
            422,
        )
        brewing = validate_success(api.get_batch(batch["id"], CELLAR))
        assert brewing["state"] == BATCH_BREWING
        assert brewing["actual_yield_bbl"] is None

        conditioned = validate_success(
            api.condition_batch(batch["id"], condition_payload(16.000), CELLAR)
        )
        assert conditioned["state"] == BATCH_CONDITIONING
        assert_bbl(conditioned["actual_yield_bbl"], 16.000, "actual_yield_bbl")
        assert_bbl(conditioned["remaining_bbl"], 16.000, "remaining_bbl")

        run = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=40,
            run_code="R-2",
        )
        validate_error(
            api.complete_packaging_run(run["id"], complete_run_payload(40), CELLAR),
            ERR_UNITS_EXCEED_BATCH_VOLUME,
            422,
        )

        stored_run = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert stored_run["state"] == RUN_PLANNED
        assert_bbl(stored_run["bbl_removed"], 0.000, "bbl_removed")
        assert stored_run["removed_at_utc"] is None
        stored_batch = validate_success(api.get_batch(batch["id"], CELLAR))
        assert stored_batch["state"] == BATCH_CONDITIONING
        assert_bbl(stored_batch["packaged_bbl"], 0.000, "packaged_bbl")
        assert_bbl(stored_batch["remaining_bbl"], 16.000, "remaining_bbl")


class TestKegFloatGuards:
    def test_four_independent_guards_stand_between_a_can_run_and_a_return(self, api):
        """Size, unit exhaustion, tapped state and return volume each refuse in turn.

        PRD §3.4: "The barrel content of the run's `package_type` must equal this
        keg's `size_bbl` exactly, so a half-barrel keg may only be filled from a
        `HALF_BBL_KEG` run and a quarter-barrel keg only from a `QUARTER_BBL_KEG` run;
        any mismatch, including every attempt to rack a keg from a `CAN_CASE_24` run,
        is refused with `ERR_KEG_SIZE_MISMATCH`."

        PRD §3.4: "And the run must have containers left to give: its
        `kegs_filled_count` must be strictly less than its `units_produced`, otherwise
        the fill is refused with `ERR_RUN_UNITS_EXHAUSTED`."

        PRD §3.5: "The cited keg's `state` must be exactly `TAPPED`; a keg that is
        merely `FILLED`, or has already been returned to `EMPTY_DIRTY`, or was deployed
        out of the building, cannot be poured from, and the attempt is refused with
        `ERR_KEG_NOT_TAPPED`."

        PRD §3.4: "It requires `returned_volume_gal`, the volume of beer physically
        left in the keg expressed in US gallons, present and at least 0; converted at
        128 fluid ounces to the gallon, it may not exceed the keg's `filled_volume_oz`,
        and a return claiming more beer came back than went in is refused with
        `ERR_RETURN_EXCEEDS_FILL`."

        Design: Corner/errors/keg_float_guards_reject_a_size_mismatch_an_exhausted_run_an_untapped_pour_and_an_oversized_return
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
        _, batch = _conditioning_batch(api, beer["id"])
        can_run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_CAN_CASE_24,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-CAN",
        )
        keg_run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=1,
            run_code="R-KEG",
        )
        first = create_cleaned_keg(api, KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        second = create_cleaned_keg(api, KEG_SIZE_HALF_BBL, keg_serial="KEG-0002")

        validate_error(
            api.fill_keg_asset(first["id"], keg_fill_payload(can_run["id"]), CELLAR),
            ERR_KEG_SIZE_MISMATCH,
            422,
        )
        assert (
            validate_success(api.get_keg_asset(first["id"], CELLAR))["state"]
            == KEG_CLEANED
        )

        filled = validate_success(
            api.fill_keg_asset(first["id"], keg_fill_payload(keg_run["id"]), CELLAR)
        )
        assert filled["state"] == KEG_FILLED
        assert_oz(filled["filled_volume_oz"], 1984.00, "filled_volume_oz")

        validate_error(
            api.fill_keg_asset(second["id"], keg_fill_payload(keg_run["id"]), CELLAR),
            ERR_RUN_UNITS_EXHAUSTED,
            409,
        )
        assert (
            validate_success(api.get_keg_asset(second["id"], CELLAR))["state"]
            == KEG_CLEANED
        )
        assert (
            validate_success(api.get_packaging_run(keg_run["id"], CELLAR))[
                "kegs_filled_count"
            ]
            == 1
        )

        validate_error(
            api.create_taproom_pour(
                pour_payload(first["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            ERR_KEG_NOT_TAPPED,
            409,
        )
        _, pour_meta = validate_paginated(
            api.list_taproom_pours(TAPROOM, {"keg_asset_id": first["id"]})
        )
        assert pour_meta["total_count"] == 0

        tapped = validate_success(
            api.move_keg_asset(first["id"], keg_movement_payload(MOVEMENT_TAP), TAPROOM)
        )
        assert tapped["state"] == KEG_TAPPED

        validate_error(
            api.move_keg_asset(first["id"], keg_return_payload(16.0), CELLAR),
            ERR_RETURN_EXCEEDS_FILL,
            422,
        )

        stored_keg = validate_success(api.get_keg_asset(first["id"], CELLAR))
        assert stored_keg["state"] == KEG_TAPPED
        assert stored_keg["returned_volume_oz"] is None
        assert stored_keg["depletion_variance_oz"] is None
        stored_run = validate_success(api.get_packaging_run(keg_run["id"], CELLAR))
        assert stored_run["reconciliation_state"] == RECON_OPEN
        assert stored_run["kegs_outstanding_count"] == 1


class TestExcisePeriodGuards:
    def test_five_refusals_along_one_returns_life(self, api):
        """Early, self-filed, replayed, duplicated and amendment-of-a-draft filings.

        PRD §3.8: "Filing is a `ComplianceOfficer` act and is legal only from `DRAFT`;
        attempted on a return whose `state` is `FILED` or `SUPERSEDED` it is refused
        with `ERR_REPORT_TRANSITION_INVALID`."

        PRD §3.8: "The acting `X-User-ID` must differ from `prepared_by_user_id`, or
        the filing is refused with `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.8: "The period must have closed: the logical clock must have reached or
        passed `period_end_utc`, and an early filing is refused with
        `ERR_PERIOD_NOT_CLOSED`."

        PRD §3.8: "When `amends_report_id` is null, no other return in `FILED` may
        already cover the same pairing of `period_start_utc` and `period_end_utc`, and
        a duplicate is refused with `ERR_PERIOD_ALREADY_FILED`."

        PRD §3.8: "When `amends_report_id` is non-null, the target return's `state`
        must be `FILED`; a target sitting in `DRAFT` or already in `SUPERSEDED` is
        refused with `ERR_AMENDMENT_TARGET_NOT_FILED`."

        Design: Corner/errors/excise_period_guards_reject_early_duplicate_self_filed_and_draft_amending_returns
        """
        bootstrap_brewery(api)
        set_clock(api, "2026-08-15T00:00:00Z")
        first = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
        )

        validate_error(
            api.file_excise_report(first["id"], COMPLIANCE), ERR_PERIOD_NOT_CLOSED, 422
        )
        early = validate_success(api.get_excise_report(first["id"], ADMIN))
        assert early["state"] == REPORT_DRAFT
        assert early["filed_at_utc"] is None

        set_clock(api, AUGUST_END)
        validate_error(
            api.file_excise_report(
                first["id"], headers_for(ROLE_COMPLIANCE_OFFICER, USER_ADMIN_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        assert (
            validate_success(api.get_excise_report(first["id"], ADMIN))["state"]
            == REPORT_DRAFT
        )

        filed = validate_success(api.file_excise_report(first["id"], COMPLIANCE))
        assert filed["state"] == REPORT_FILED
        assert filed["filed_by_user_id"] == USER_COMPLIANCE_1
        assert_instant_equals(filed["filed_at_utc"], AUGUST_END, "filed_at_utc")
        assert_cents(filed["total_tax_due_cents"], 0, "total_tax_due_cents")

        validate_error(
            api.file_excise_report(first["id"], COMPLIANCE),
            ERR_REPORT_TRANSITION_INVALID,
            409,
        )

        duplicate = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
        )
        validate_error(
            api.file_excise_report(duplicate["id"], COMPLIANCE),
            ERR_PERIOD_ALREADY_FILED,
            409,
        )
        assert (
            validate_success(api.get_excise_report(duplicate["id"], ADMIN))["state"]
            == REPORT_DRAFT
        )

        amendment = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
            amends_report_id=duplicate["id"],
        )
        validate_error(
            api.file_excise_report(amendment["id"], COMPLIANCE),
            ERR_AMENDMENT_TARGET_NOT_FILED,
            422,
        )

        _, meta = validate_paginated(
            api.list_excise_reports(ADMIN, {"state": REPORT_FILED})
        )
        assert meta["total_count"] == 1


class TestFranchiseGuards:
    def test_a_double_scope_a_bare_withdraw_and_an_early_finalize_are_refused(self, api):
        """Only reaching ACTIVE is blocked, and the notice period must actually elapse.

        PRD §3.6: "Approval is where the trap closes, and only a `ComplianceOfficer`
        may spring it."

        PRD §3.6: "Overlap is defined precisely: an `ALL_BRANDS` scope overlaps every
        other scope, including any `SINGLE_BRAND` scope; two `SINGLE_BRAND` scopes
        overlap only when their `appointed_beer_id` values are the same brand."

        PRD §3.6: "A `FINALIZE` is likewise legal only from `TERMINATION_REQUESTED`
        and moves the appointment to `TERMINATED`, but only once the logical clock has
        reached or passed `termination_effective_utc`; arriving early is refused with
        `ERR_TERMINATION_NOTICE_NOT_ELAPSED`."

        Design: Corner/errors/franchise_guards_reject_a_double_scope_a_bare_withdraw_and_an_early_finalize
        """
        bootstrap_brewery(api, home_state_code="OR")
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            termination_notice_days=90,
            **_license_window(),
        )
        incumbent = create_active_appointment(
            api, license_row["id"], brand_scope=SCOPE_ALL_BRANDS
        )
        challenger = propose_appointment(
            api,
            license_row["id"],
            brand_scope=SCOPE_ALL_BRANDS,
            distributor_name="Rainier Wholesale",
        )
        assert challenger["state"] == APPT_PROPOSED

        validate_error(
            api.approve_appointment(challenger["id"], COMPLIANCE),
            ERR_DUPLICATE_APPOINTMENT_SCOPE,
            409,
        )
        assert (
            validate_success(
                api.get_distributor_appointment(challenger["id"], COMPLIANCE)
            )["state"]
            == APPT_PROPOSED
        )

        validate_error(
            api.terminate_appointment(
                incumbent["id"], termination_payload(TERMINATION_WITHDRAW), COMPLIANCE
            ),
            ERR_APPOINTMENT_TRANSITION_INVALID,
            409,
        )

        requested = validate_success(
            api.terminate_appointment(
                incumbent["id"],
                termination_payload(
                    TERMINATION_REQUEST, good_cause_code=GOOD_CAUSE_NONPAYMENT
                ),
                COMPLIANCE,
            )
        )
        assert requested["state"] == APPT_TERMINATION_REQUESTED
        assert_instant_equals(
            requested["termination_effective_utc"],
            "2026-10-30T00:00:00Z",
            "termination_effective_utc",
        )

        validate_error(
            api.terminate_appointment(
                incumbent["id"], termination_payload(TERMINATION_FINALIZE), COMPLIANCE
            ),
            ERR_TERMINATION_NOTICE_NOT_ELAPSED,
            409,
        )

        set_clock(api, "2026-10-30T00:00:00Z")
        finalised = validate_success(
            api.terminate_appointment(
                incumbent["id"], termination_payload(TERMINATION_FINALIZE), COMPLIANCE
            )
        )
        promoted = validate_success(api.approve_appointment(challenger["id"], COMPLIANCE))

        assert finalised["state"] == APPT_TERMINATED
        assert finalised["terminated_at_utc"] is not None
        assert promoted["state"] == APPT_ACTIVE
        stored_license = validate_success(api.get_state_license(license_row["id"], ADMIN))
        assert stored_license["active_appointment_count"] == 1
        assert validate_success(api.get_brewery(ADMIN))[
            "franchise_locked_state_codes"
        ] == ["WA"]


class TestAppointmentAgainstALapsedLicence:
    def test_a_lapsed_licence_reports_expiry_rather_than_a_status_failure(self, api):
        """The window error is distinct from the status error and from a stale version.

        PRD §3.6: "And a licence whose window has closed — the logical clock has
        reached or passed the exclusive `expires_at_utc`, so an instant exactly equal
        to `expires_at_utc` already counts as lapsed — refuses the same four
        operations with `ERR_LICENSE_EXPIRED`."

        Design: Corner/errors/appointment_against_a_lapsed_license_returns_license_expired
        """
        bootstrap_brewery(api, home_state_code="OR")
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            **_license_window(expires_at_utc="2026-08-10T00:00:00Z"),
        )
        set_clock(api, "2026-08-10T00:00:00Z")
        lapsed = validate_success(api.get_state_license(license_row["id"], COMPLIANCE))
        assert lapsed["status"] == LICENSE_EXPIRED

        validate_error(
            api.create_distributor_appointment(
                appointment_payload(
                    license_row["id"],
                    lapsed["version"],
                    distributor_name="Evergreen Beverage Co",
                    brand_scope=SCOPE_ALL_BRANDS,
                ),
                ADMIN,
            ),
            ERR_LICENSE_EXPIRED,
            409,
        )

        stored = validate_success(api.get_state_license(license_row["id"], COMPLIANCE))
        assert stored["status"] == LICENSE_EXPIRED
        assert stored["active_appointment_count"] == 0
        _, meta = validate_paginated(
            api.list_distributor_appointments(
                COMPLIANCE, {"state_license_id": license_row["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestUnapprovedFormulaBlocksTheSale:
    def test_the_tap_waits_for_the_formula_and_ignores_the_certificate(self, api):
        """A decision on a dormant dimension is refused; only the formula gates the tap.

        PRD §3.1: "A `FORMULA` filing is legal only when `registration_state` is
        `DRAFT` and `requires_formula` is true, and requires an `ingredient_list` that
        is present and non-empty; it advances `registration_state` from `DRAFT` to
        `FORMULA_PENDING`, leaves `label_state` untouched, and increments the beer's
        `version` by 1."

        PRD §3.1: "Every one of those decisions increments the beer's `version` by 1,
        and a decision on a dimension that is not pending — or a revocation of a
        certificate that was never approved — is refused with
        `ERR_FILING_TRANSITION_INVALID`."

        PRD §3.1: "`taproom_sellable` is true exactly when the brewery's
        `notice_status` is `ACTIVE` **and** the beer's `registration_state` is either
        `FORMULA_APPROVED` or `FORMULA_EXEMPT`; a certificate of label approval is
        emphatically **not** required to pour draft beer across the bar."

        PRD §3.4: "A `TAP` movement is legal only from `FILLED` and moves the keg to
        `TAPPED`. Beyond the notice, it demands that the filled beer's
        `taproom_sellable` be true — the formula dimension must be settled, though no
        certificate of label approval is needed to pour draft."

        Design: Corner/errors/sale_of_an_unapproved_formula_is_refused_and_a_decision_without_a_filing_is_invalid
        """
        bootstrap_brewery(api)
        beer = create_draft_beer(
            api, name="Barrel Reserve", abv_pct=9.2, price_per_bbl_cents=60000
        )
        assert beer["registration_state"] == REG_DRAFT
        assert beer["label_state"] == LABEL_NO_LABEL
        assert beer["taproom_sellable"] is False
        _, batch = _conditioning_batch(api, beer["id"])
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        keg = create_filled_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")

        validate_error(
            api.decide_beer_filing(
                beer["id"],
                FILING_LABEL,
                filing_decision_payload(DECISION_APPROVED, cola_id="COLA-2026-0001"),
                REGULATOR,
            ),
            ERR_FILING_TRANSITION_INVALID,
            409,
        )
        unlabelled = validate_success(api.get_beer(beer["id"], COMPLIANCE))
        assert unlabelled["label_state"] == LABEL_NO_LABEL
        assert unlabelled["cola_id"] is None

        validate_error(
            api.move_keg_asset(keg["id"], keg_movement_payload(MOVEMENT_TAP), TAPROOM),
            ERR_FORMULA_NOT_APPROVED,
            422,
        )
        assert validate_success(api.get_keg_asset(keg["id"], CELLAR))["state"] == KEG_FILLED

        pending = validate_success(
            api.create_beer_filing(beer["id"], formula_filing_payload(), COMPLIANCE)
        )
        assert pending["registration_state"] == REG_FORMULA_PENDING
        assert pending["taproom_sellable"] is False
        validate_error(
            api.move_keg_asset(keg["id"], keg_movement_payload(MOVEMENT_TAP), TAPROOM),
            ERR_FORMULA_NOT_APPROVED,
            422,
        )

        approved = validate_success(
            api.decide_beer_filing(
                beer["id"],
                FILING_FORMULA,
                filing_decision_payload(DECISION_APPROVED),
                REGULATOR,
            )
        )
        tapped = validate_success(
            api.move_keg_asset(keg["id"], keg_movement_payload(MOVEMENT_TAP), TAPROOM)
        )

        assert approved["registration_state"] == REG_FORMULA_APPROVED
        assert approved["taproom_sellable"] is True
        assert approved["label_state"] == LABEL_NO_LABEL
        assert approved["distribution_sellable"] is False
        assert tapped["state"] == KEG_TAPPED
        assert tapped["deployment_channel"] == CHANNEL_TAPROOM
        assert tapped["tapped_at_utc"] is not None


class TestTransitionInvalidFamily:
    def test_four_entities_each_answer_their_own_transition_code(self, api):
        """One refusal per machine, and not one of them moves a ledger figure.

        PRD §3.2: "A service action the current `status` does not declare — a
        clean-in-place on an idle vessel, a return-to-service on a dirty one — is
        refused with `ERR_TANK_TRANSITION_INVALID`."

        PRD §3.4: "Any clean, fill or movement that the keg's current `state` does not
        declare — including anything at all attempted from `DECOMMISSIONED`, which is
        terminal — is refused with `ERR_KEG_TRANSITION_INVALID`."

        PRD §3.3: "`VOIDED` is terminal: a void attempted on a run already in
        `VOIDED`, like a completion attempted on a run that is not `PLANNED`, is
        refused with `ERR_RUN_TRANSITION_INVALID`."

        PRD §3.7: "`SHIPPED`, `REJECTED` and `CANCELLED` are all terminal: an
        allocation or cancellation attempted from any of them is refused with
        `ERR_ORDER_TRANSITION_INVALID`."

        Design: Corner/errors/transition_invalid_family_across_tank_keg_run_and_order
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            **_license_window(),
        )
        tank, batch = _conditioning_batch(api, beer["id"])
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-DIST-1",
        )
        keg = create_filled_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        order = submit_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=2.00,
            ship_to_state_code="ID",
            distance_miles=100,
            requested_ship_utc="2026-08-20T15:00:00Z",
            order_code="SO-7001",
        )
        cancelled = validate_success(
            api.cancel_order(order["id"], cancel_order_payload(CANCEL_REASON), ADMIN)
        )
        assert cancelled["state"] == ORDER_CANCELLED

        validate_error(
            api.service_tank(tank["id"], tank_service_payload(TANK_ACTION_CIP), CELLAR),
            ERR_TANK_TRANSITION_INVALID,
            409,
        )
        validate_error(
            api.clean_keg_asset(keg["id"], keg_clean_payload(), CELLAR),
            ERR_KEG_TRANSITION_INVALID,
            409,
        )
        validate_error(
            api.complete_packaging_run(run["id"], complete_run_payload(10), CELLAR),
            ERR_RUN_TRANSITION_INVALID,
            409,
        )
        validate_error(
            api.allocate_order(order["id"], ADMIN), ERR_ORDER_TRANSITION_INVALID, 409
        )

        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_OCCUPIED
        assert stored_tank["cip_cycle_count"] == 0
        assert stored_tank["last_cip_utc"] is None
        stored_keg = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert stored_keg["state"] == KEG_FILLED
        assert_oz(stored_keg["filled_volume_oz"], 1984.00, "filled_volume_oz")
        stored_run = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert stored_run["state"] == RUN_COMPLETED
        assert_bbl(stored_run["bbl_removed"], 5.000, "bbl_removed")
        stored_order = validate_success(api.get_distribution_order(order["id"], ADMIN))
        assert stored_order["state"] == ORDER_CANCELLED
        assert stored_order["allocation_lines"] == []
        assert_bbl(stored_order["allocated_bbl"], 0.000, "allocated_bbl")
        stored_batch = validate_success(api.get_batch(batch["id"], CELLAR))
        assert_bbl(stored_batch["packaged_bbl"], 5.000, "packaged_bbl")
        assert_bbl(stored_batch["remaining_bbl"], 11.000, "remaining_bbl")


class TestSuspendedNoticeBlocksThePour:
    def test_the_bar_closes_on_suspension_and_reopens_on_the_next_request(self, api):
        """The notice gate is re-read per request, and an unknown pour has its own 404.

        PRD §3.5: "The brewery's `notice_status` must be `ACTIVE`, or the pour is
        refused with `ERR_NOTICE_NOT_ACTIVE`."

        PRD §2.8: "The vocabulary is `ERR_BREWERY_NOT_FOUND`, `ERR_BEER_NOT_FOUND`,
        `ERR_TANK_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_PACKAGING_RUN_NOT_FOUND`,
        `ERR_KEG_ASSET_NOT_FOUND`, `ERR_TAPROOM_POUR_NOT_FOUND`,
        `ERR_STATE_LICENSE_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_REPORT_NOT_FOUND` and
        `ERR_EVENT_PERMIT_NOT_FOUND`."

        PRD §3.1: "`REINSTATE` takes `SUSPENDED` back to `ACTIVE`, re-stamping
        `notice_effective_utc` from the logical clock and clearing
        `suspension_reason`."

        PRD §3.5: "A successful pour raises the keg's `poured_volume_oz` by the poured
        ounces and lowers its `remaining_volume_oz` by the same amount, and the pour
        immediately joins the metered taxable base of any reporting period whose
        window contains its `poured_at_utc`."

        Design: Corner/errors/suspended_notice_blocks_a_pour_until_the_notice_is_reinstated
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
        _, batch = _conditioning_batch(api, beer["id"])
        run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code="R-TAP-1",
        )
        keg = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        assert keg["state"] == KEG_TAPPED
        suspend_notice(api, reason="records audit opened by the state")

        validate_error(
            api.create_taproom_pour(
                pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            ERR_NOTICE_NOT_ACTIVE,
            409,
        )
        validate_error(
            api.get_taproom_pour(UNKNOWN_UUID, TAPROOM), ERR_TAPROOM_POUR_NOT_FOUND, 404
        )

        reinstated = reinstate_notice(api)
        poured = validate_success(
            api.create_taproom_pour(
                pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )

        assert reinstated["notice_status"] == NOTICE_ACTIVE
        assert_oz(poured["volume_oz"], 16.00, "volume_oz")
        assert poured["sanitation_verdict"] == SANITATION_NOT_REQUIRED
        assert poured["poured_at_utc"] is not None
        _, meta = validate_paginated(
            api.list_taproom_pours(TAPROOM, {"keg_asset_id": keg["id"]})
        )
        assert meta["total_count"] == 1
        stored_keg = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert_oz(stored_keg["poured_volume_oz"], 16.00, "poured_volume_oz")
        assert_oz(stored_keg["remaining_volume_oz"], 1968.00, "remaining_volume_oz")


class TestVoidAndDumpGuards:
    def test_both_destructive_verbs_wait_for_their_downstream_commitments(self, api):
        """Reserved beer blocks the void; a planned run blocks the dump.

        PRD §3.3: "From `COMPLETED` the void is a full compensation, and it is
        guarded: it is refused with `ERR_RUN_HAS_ALLOCATIONS` if the run's
        `allocated_bbl` is non-zero, or its `shipped_bbl` is non-zero, or its
        `kegs_filled_count` is non-zero, because beer that has already been reserved,
        shipped or racked into kegs cannot be un-removed."

        PRD §3.2: "From `CONDITIONING` the vessel likewise moves `OCCUPIED → DIRTY`,
        and because a yield had already been measured the batch's `total_loss_bbl` is
        set to `actual_yield_bbl` minus `packaged_bbl`; a dump from `CONDITIONING` is
        additionally refused with `ERR_BATCH_HAS_PLANNED_RUNS` while any packaging run
        of the batch is still in `PLANNED`, since an unclosed run would otherwise be
        orphaned."

        PRD §3.3: "When the guard passes, the batch's `packaged_bbl` falls by the
        run's `bbl_removed` and its `remaining_bbl` rises by the same amount, restoring
        the batch identity that `actual_yield_bbl` equals `packaged_bbl` plus
        `remaining_bbl`; the run's `bbl_removed` and `available_bbl` are reset to
        0.000, its `units_produced` is set back to null, and `voided_at_utc` is
        stamped."

        Design: Corner/errors/void_and_dump_guards_release_only_after_the_allocations_and_plans_are_cleared
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_distribution_ready_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "ID",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            franchise_state=False,
            **_license_window(),
        )
        tank, batch = _conditioning_batch(api, beer["id"])
        first_run = create_completed_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=10,
            run_code="R-1",
        )
        order = create_allocated_order(
            api,
            beer["id"],
            license_row["id"],
            bbl_requested=5.00,
            ship_to_state_code="ID",
            distance_miles=100,
            requested_ship_utc="2026-08-20T15:00:00Z",
            order_code="SO-8001",
        )
        second_run = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=4,
            run_code="R-2",
        )
        assert second_run["state"] == RUN_PLANNED

        validate_error(
            api.void_packaging_run(first_run["id"], CELLAR),
            ERR_RUN_HAS_ALLOCATIONS,
            409,
        )
        held = validate_success(api.get_packaging_run(first_run["id"], CELLAR))
        assert held["state"] == RUN_COMPLETED
        assert_bbl(held["allocated_bbl"], 5.000, "allocated_bbl")

        validate_error(
            api.dump_batch(batch["id"], dump_payload(DUMP_REASON), CELLAR),
            ERR_BATCH_HAS_PLANNED_RUNS,
            409,
        )
        assert (
            validate_success(api.get_batch(batch["id"], CELLAR))["state"]
            == BATCH_CONDITIONING
        )

        cancelled = validate_success(
            api.cancel_order(order["id"], cancel_order_payload(CANCEL_REASON), ADMIN)
        )
        released = validate_success(api.get_packaging_run(first_run["id"], CELLAR))
        assert cancelled["state"] == ORDER_CANCELLED
        assert_bbl(released["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(released["available_bbl"], 5.000, "available_bbl")

        voided_first = validate_success(api.void_packaging_run(first_run["id"], CELLAR))
        voided_second = validate_success(api.void_packaging_run(second_run["id"], CELLAR))
        dumped = validate_success(
            api.dump_batch(batch["id"], dump_payload(DUMP_REASON), CELLAR)
        )

        assert voided_first["state"] == RUN_VOIDED
        assert_bbl(voided_first["bbl_removed"], 0.000, "bbl_removed")
        assert_bbl(voided_first["available_bbl"], 0.000, "available_bbl")
        assert voided_first["loss_share_bbl"] is None
        assert voided_second["state"] == RUN_VOIDED
        assert dumped["state"] == BATCH_DUMPED
        assert dumped["dumped_reason"] == DUMP_REASON
        assert_bbl(dumped["packaged_bbl"], 0.000, "packaged_bbl")
        assert_bbl(dumped["total_loss_bbl"], 16.000, "total_loss_bbl")
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        assert stored_tank["status"] == TANK_DIRTY
        assert stored_tank["occupying_batch_id"] is None


class TestAutoClosedBatchRefusesALateCompletion:
    def test_the_second_run_becomes_uncompletable_one_request_later(self, api):
        """The closing run leaves exactly 1.000 barrels, and that closes the batch.

        PRD §3.3: "**When the resulting `remaining_bbl` is one barrel or less — at
        most 1.000, the comparison inclusive so exactly 1.000 closes the batch — the
        batch auto-transitions `CONDITIONING → PACKAGED` in the same request.**"

        PRD §3.3: "Closure sets the batch's `total_loss_bbl` to `actual_yield_bbl`
        minus `packaged_bbl`, moves the occupying vessel `OCCUPIED → DIRTY` with its
        `occupying_batch_id` cleared, and runs the loss allocation described next,
        writing a `loss_share_bbl` onto every completed run of the batch."

        PRD §3.3: "The run must be in `PLANNED` (otherwise
        `ERR_RUN_TRANSITION_INVALID`), the owning batch must still be in
        `CONDITIONING` (otherwise `ERR_BATCH_NOT_CONDITIONING`), and the brewery's
        `notice_status` must be `ACTIVE` (otherwise `ERR_NOTICE_NOT_ACTIVE`)."

        Design: Corner/errors/completing_a_run_after_the_batch_auto_closes_reports_batch_not_conditioning
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
        tank, batch = _conditioning_batch(api, beer["id"])
        run_a = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=30,
            run_code="R-A",
        )
        run_b = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_DISTRIBUTION,
            units_planned=2,
            run_code="R-B",
        )

        completed_a = validate_success(
            api.complete_packaging_run(run_a["id"], complete_run_payload(30), CELLAR)
        )
        closed_batch = validate_success(api.get_batch(batch["id"], CELLAR))
        stored_tank = validate_success(api.get_tank(tank["id"], CELLAR))
        stored_a = validate_success(api.get_packaging_run(run_a["id"], CELLAR))

        assert completed_a["state"] == RUN_COMPLETED
        assert_bbl(completed_a["bbl_removed"], 15.000, "bbl_removed")
        assert closed_batch["state"] == BATCH_PACKAGED
        assert_bbl(closed_batch["packaged_bbl"], 15.000, "packaged_bbl")
        assert_bbl(closed_batch["remaining_bbl"], 1.000, "remaining_bbl")
        assert_bbl(closed_batch["total_loss_bbl"], 1.000, "total_loss_bbl")
        assert stored_tank["status"] == TANK_DIRTY
        assert stored_tank["occupying_batch_id"] is None
        assert_bbl(stored_a["loss_share_bbl"], 1.000, "loss_share_bbl")

        validate_error(
            api.complete_packaging_run(run_b["id"], complete_run_payload(2), CELLAR),
            ERR_BATCH_NOT_CONDITIONING,
            409,
        )

        stored_b = validate_success(api.get_packaging_run(run_b["id"], CELLAR))
        assert stored_b["state"] == RUN_PLANNED
        assert_bbl(stored_b["bbl_removed"], 0.000, "bbl_removed")
        assert stored_b["loss_share_bbl"] is None
        assert_bbl(
            validate_success(api.get_batch(batch["id"], CELLAR))["packaged_bbl"],
            15.000,
            "packaged_bbl",
        )
