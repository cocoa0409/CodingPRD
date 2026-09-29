"""Role exclusivity in both directions, and the three segregation-of-duties controls."""

from test_helpers import (
    ADMIN,
    APPT_ACTIVE,
    APPT_PROPOSED,
    BASIS_METERED_POUR,
    BASIS_WHOLE_KEG_REMOVAL,
    BATCH_BREWING,
    BATCH_CONDITIONING,
    CELLAR,
    CHANNEL_TAPROOM,
    COMPLIANCE,
    CONTAINER_PINT_16OZ,
    DECISION_APPROVED,
    DESTINATION_TAPROOM,
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    FILING_LABEL,
    KEG_CLEANED,
    KEG_FILLED,
    KEG_SIZE_HALF_BBL,
    KEG_TAPPED,
    LABEL_COLA_APPROVED,
    LABEL_COLA_PENDING,
    LICENSE_ACTIVE,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_WHOLESALER_ONLY,
    MOVEMENT_TAP,
    NOTICE_ACTION_ACTIVATE,
    NOTICE_ACTION_SUSPEND,
    NOTICE_ACTIVE,
    ORDER_SUBMITTED,
    PACKAGE_HALF_BBL_KEG,
    PERMIT_APPROVED,
    PERMIT_DECISION_APPROVED,
    PERMIT_FESTIVAL,
    PERMIT_SUBMITTED,
    REG_FORMULA_EXEMPT,
    REGULATOR,
    REPORT_DRAFT,
    REPORT_FILED,
    ROLE_COMPLIANCE_OFFICER,
    RUN_COMPLETED,
    SANITATION_NOT_REQUIRED,
    SANITATION_PASS,
    SCOPE_ALL_BRANDS,
    TANK_IDLE,
    TAPROOM,
    assert_bbl,
    assert_cents,
    assert_instant_equals,
    assert_oz,
    batch_payload,
    brewery_payload,
    complete_run_payload,
    condition_payload,
    event_permit_payload,
    excise_report_payload,
    exempt_beer_payload,
    filing_decision_payload,
    growler_payload,
    headers_for,
    keg_asset_payload,
    keg_clean_payload,
    keg_fill_payload,
    keg_movement_payload,
    label_filing_payload,
    notice_payload,
    order_payload,
    packaging_run_payload,
    permit_decision_payload,
    pour_payload,
    state_license_payload,
    tank_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_exempt_beer,
    create_license,
    create_tank,
    draft_report,
    propose_appointment,
    set_clock,
)
from test_helpers.test_users import (
    USER_ADMIN_1,
    USER_CELLAR_1,
    USER_COMPLIANCE_1,
    USER_TAPROOM_1,
    USER_TAPROOM_2,
)

AUGUST_START = "2026-08-01T00:00:00Z"
AUGUST_END = "2026-09-01T00:00:00Z"
LICENSE_WINDOW = {
    "effective_from_utc": "2026-01-01T00:00:00Z",
    "expires_at_utc": "2027-01-01T00:00:00Z",
}


class TestEveryRoleDrivesItsOwnOperations:
    def test_the_chain_from_an_empty_database_to_a_filed_return_needs_all_five(self, api):
        """No single role could have made the next call anywhere along the chain.

        PRD §2.1: "`BreweryAdmin` — the owner-operator. Stands up the premises record,
        the keg float, and the commercial surface: distribution orders, appointment
        proposals, and excise return drafts. Never approves its own paperwork."

        PRD §2.1: "`ComplianceOfficer` — holder of the regulatory file. Makes TTB
        submissions, registers state licences, approves the appointments a
        `BreweryAdmin` proposed, files the returns a `BreweryAdmin` prepared, and
        drives the event-permit application."

        PRD §2.1: "`CellarOperator` — runs the brewhouse, the packaging line and the
        keg float. Owns every production transition from scheduling a brew through
        filling, deploying and returning kegs."

        PRD §2.1: "`TaproomStaff` — works the bar. Records pours, growler and crowler
        fills with their sanitation attestation, and taps or returns kegs at the bar."

        PRD §2.1: "`StateRegulator` — the external authority. Decides the brewer's
        notice, TTB formula and label filings, and off-site event permits."

        PRD §2.1: "All five roles may read every list and single-resource retrieval
        endpoint, and all five may drive the logical clock."

        Design: Corner/rbac/every_role_can_drive_its_own_exclusive_operations_end_to_end
        """
        brewery = validate_success(
            api.create_brewery(
                brewery_payload(
                    legal_name="Cascade Ridge Brewing", home_state_code="OR"
                ),
                ADMIN,
            ),
            201,
        )
        activated = validate_success(
            api.drive_notice(notice_payload(NOTICE_ACTION_ACTIVATE), REGULATOR)
        )
        beer = validate_success(
            api.create_beer(
                exempt_beer_payload(
                    name="Ridgeline IPA",
                    style="West Coast IPA",
                    abv_pct=6.8,
                    price_per_bbl_cents=42000,
                ),
                COMPLIANCE,
            ),
            201,
        )
        pending_label = validate_success(
            api.create_beer_filing(beer["id"], label_filing_payload(), COMPLIANCE)
        )
        approved_label = validate_success(
            api.decide_beer_filing(
                beer["id"],
                FILING_LABEL,
                filing_decision_payload(DECISION_APPROVED, cola_id="COLA-24-0917"),
                REGULATOR,
            )
        )
        license_row = validate_success(
            api.create_state_license(
                state_license_payload(
                    state_code="ID",
                    license_type=LICENSE_SELF_DISTRIBUTION,
                    annual_barrel_cap=1000.00,
                    franchise_state=False,
                    **LICENSE_WINDOW,
                ),
                COMPLIANCE,
            ),
            201,
        )

        tank = validate_success(
            api.create_tank(tank_payload(code="FV-01", capacity_bbl=30.00), CELLAR), 201
        )
        batch = validate_success(
            api.create_batch(
                batch_payload(
                    beer["id"],
                    tank["id"],
                    batch_code="B-1001",
                    planned_volume_bbl=16.00,
                    brew_start_utc="2026-08-01T06:00:00Z",
                    brew_end_utc="2026-08-08T06:00:00Z",
                ),
                CELLAR,
            ),
            201,
        )
        started = validate_success(api.start_batch(batch["id"], CELLAR))
        conditioned = validate_success(
            api.condition_batch(batch["id"], condition_payload(16.000), CELLAR)
        )
        run = validate_success(
            api.create_packaging_run(
                packaging_run_payload(
                    batch["id"],
                    conditioned["version"],
                    package_type=PACKAGE_HALF_BBL_KEG,
                    destination=DESTINATION_TAPROOM,
                    units_planned=2,
                    run_code="R-TAP-1",
                ),
                CELLAR,
            ),
            201,
        )
        completed = validate_success(
            api.complete_packaging_run(run["id"], complete_run_payload(2), CELLAR)
        )
        keg = validate_success(
            api.create_keg_asset(
                keg_asset_payload(KEG_SIZE_HALF_BBL, keg_serial="KEG-0001"), CELLAR
            ),
            201,
        )
        cleaned = validate_success(
            api.clean_keg_asset(keg["id"], keg_clean_payload(), CELLAR)
        )
        filled = validate_success(
            api.fill_keg_asset(keg["id"], keg_fill_payload(run["id"]), CELLAR)
        )

        tapped = validate_success(
            api.move_keg_asset(keg["id"], keg_movement_payload(MOVEMENT_TAP), TAPROOM)
        )
        pour = validate_success(
            api.create_taproom_pour(
                pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )

        order = validate_success(
            api.create_distribution_order(
                order_payload(
                    beer["id"],
                    license_row["id"],
                    bbl_requested=2.00,
                    ship_to_state_code="ID",
                    distance_miles=100,
                    requested_ship_utc="2026-08-20T15:00:00Z",
                    order_code="SO-1",
                ),
                ADMIN,
            ),
            201,
        )
        permit = validate_success(
            api.create_event_permit(
                event_permit_payload(
                    beer["id"],
                    venue_state_code="ID",
                    requested_bbl=2.00,
                    event_start_utc="2026-09-12T16:00:00Z",
                    event_end_utc="2026-09-14T22:00:00Z",
                    permit_type=PERMIT_FESTIVAL,
                    event_name="Cascade Hop Fest",
                ),
                COMPLIANCE,
            ),
            201,
        )
        submitted_permit = validate_success(
            api.submit_event_permit(permit["id"], COMPLIANCE)
        )
        decided_permit = validate_success(
            api.decide_event_permit(
                permit["id"],
                permit_decision_payload(PERMIT_DECISION_APPROVED, note="site plan accepted"),
                REGULATOR,
            )
        )

        report = validate_success(
            api.create_excise_report(
                excise_report_payload(
                    period_start_utc=AUGUST_START,
                    period_end_utc=AUGUST_END,
                    taproom_basis=BASIS_METERED_POUR,
                ),
                ADMIN,
            ),
            201,
        )
        validate_success(api.set_clock(AUGUST_END, COMPLIANCE))
        filed_report = validate_success(api.file_excise_report(report["id"], COMPLIANCE))

        assert brewery["legal_name"] == "Cascade Ridge Brewing"
        assert activated["notice_status"] == NOTICE_ACTIVE
        assert beer["registration_state"] == REG_FORMULA_EXEMPT
        assert pending_label["label_state"] == LABEL_COLA_PENDING
        assert approved_label["label_state"] == LABEL_COLA_APPROVED
        assert approved_label["distribution_sellable"] is True
        assert license_row["status"] == LICENSE_ACTIVE
        assert tank["status"] == TANK_IDLE
        assert started["state"] == BATCH_BREWING
        assert conditioned["state"] == BATCH_CONDITIONING
        assert completed["state"] == RUN_COMPLETED
        assert completed["certified_by_user_id"] == USER_CELLAR_1
        assert_bbl(completed["bbl_removed"], 1.000, "bbl_removed")
        assert cleaned["state"] == KEG_CLEANED
        assert filled["state"] == KEG_FILLED
        assert tapped["state"] == KEG_TAPPED
        assert tapped["deployment_channel"] == CHANNEL_TAPROOM
        assert pour["poured_by_user_id"] == USER_TAPROOM_1
        assert_oz(pour["volume_oz"], 16.00, "volume_oz")
        assert pour["sanitation_verdict"] == SANITATION_NOT_REQUIRED
        assert order["state"] == ORDER_SUBMITTED
        assert submitted_permit["state"] == PERMIT_SUBMITTED
        assert decided_permit["state"] == PERMIT_APPROVED
        assert report["state"] == REPORT_DRAFT
        assert report["prepared_by_user_id"] == USER_ADMIN_1
        assert filed_report["state"] == REPORT_FILED
        assert filed_report["filed_by_user_id"] == USER_COMPLIANCE_1
        assert_instant_equals(filed_report["filed_at_utc"], AUGUST_END, "filed_at_utc")
        assert_bbl(filed_report["taproom_bbl"], 0.004, "taproom_bbl")
        assert_bbl(filed_report["distribution_bbl"], 0.000, "distribution_bbl")
        assert_cents(filed_report["federal_tax_cents"], 1, "federal_tax_cents")
        assert_cents(filed_report["state_tax_cents"], 2, "state_tax_cents")
        assert_cents(filed_report["total_tax_due_cents"], 3, "total_tax_due_cents")


class TestEachExclusiveOperationIsDeniedToEveryOtherRole:
    def test_six_role_boundaries_each_refuse_a_body_that_would_have_been_accepted(
        self, api
    ):
        """Every denied call is well-formed, so only the role can be the reason.

        PRD §2.1: "Once the headers are accepted, the role named by `X-User-Role` must
        appear in the acting endpoint's authorised-role list, which §4 tabulates. A
        role that is not listed is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD §2.1: "`CellarOperator` — runs the brewhouse, the packaging line and the
        keg float. Owns every production transition from scheduling a brew through
        filling, deploying and returning kegs. Holds no commercial or regulatory
        authority whatsoever."

        PRD §2.1: "`TaproomStaff` — works the bar. Records pours, growler and crowler
        fills with their sanitation attestation, and taps or returns kegs at the bar.
        Cannot brew, package, or touch a licence."

        PRD §2.1: "`StateRegulator` — the external authority. Decides the brewer's
        notice, TTB formula and label filings, and off-site event permits.
        Deliberately holds no operational write on production, inventory, orders or
        excise returns; it only ever answers applications."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/rbac/each_roles_exclusive_operation_is_denied_to_every_other_role
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        validate_success(
            api.create_beer_filing(beer["id"], label_filing_payload(), COMPLIANCE)
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)

        refusals = [
            validate_error(
                api.drive_notice(
                    notice_payload(
                        NOTICE_ACTION_SUSPEND, reason="cellar operator overreach"
                    ),
                    CELLAR,
                ),
                ERR_FORBIDDEN_ROLE,
                403,
            ),
            validate_error(
                api.create_batch(
                    batch_payload(
                        beer["id"],
                        tank["id"],
                        batch_code="B-9001",
                        planned_volume_bbl=16.00,
                        brew_start_utc="2026-08-01T06:00:00Z",
                        brew_end_utc="2026-08-08T06:00:00Z",
                    ),
                    REGULATOR,
                ),
                ERR_FORBIDDEN_ROLE,
                403,
            ),
            validate_error(
                api.create_state_license(
                    state_license_payload(
                        state_code="ID",
                        license_type=LICENSE_SELF_DISTRIBUTION,
                        annual_barrel_cap=1000.00,
                        franchise_state=False,
                        **LICENSE_WINDOW,
                    ),
                    TAPROOM,
                ),
                ERR_FORBIDDEN_ROLE,
                403,
            ),
            validate_error(
                api.decide_beer_filing(
                    beer["id"],
                    FILING_LABEL,
                    filing_decision_payload(DECISION_APPROVED, cola_id="COLA-24-0917"),
                    ADMIN,
                ),
                ERR_FORBIDDEN_ROLE,
                403,
            ),
            validate_error(
                api.create_excise_report(
                    excise_report_payload(
                        period_start_utc=AUGUST_START,
                        period_end_utc=AUGUST_END,
                        taproom_basis=BASIS_METERED_POUR,
                    ),
                    REGULATOR,
                ),
                ERR_FORBIDDEN_ROLE,
                403,
            ),
            validate_error(
                api.create_event_permit(
                    event_permit_payload(
                        beer["id"],
                        venue_state_code="OR",
                        requested_bbl=2.00,
                        event_start_utc="2026-09-12T16:00:00Z",
                        event_end_utc="2026-09-14T22:00:00Z",
                        permit_type=PERMIT_FESTIVAL,
                        event_name="Cascade Hop Fest",
                    ),
                    ADMIN,
                ),
                ERR_FORBIDDEN_ROLE,
                403,
            ),
        ]

        assert len(refusals) == 6
        for body in refusals:
            assert body["error_id"] == ERR_FORBIDDEN_ROLE
            assert body["message"].strip() != ""

        assert validate_success(api.get_brewery(ADMIN))["notice_status"] == NOTICE_ACTIVE
        stored_beer = validate_success(api.get_beer(beer["id"], COMPLIANCE))
        assert stored_beer["label_state"] == LABEL_COLA_PENDING
        assert stored_beer["cola_id"] is None
        for lister, params in (
            (api.list_batches, None),
            (api.list_state_licenses, None),
            (api.list_excise_reports, None),
            (api.list_event_permits, None),
        ):
            _, meta = validate_paginated(lister(ADMIN, params))
            assert meta["total_count"] == 0


class TestSegregationOfDuties:
    def test_the_same_identity_cannot_stand_on_both_sides_of_three_controls(self, api):
        """Approval, filing and attestation each need a second identity, not a second role.

        PRD §3.6: "The appointment must be in `PROPOSED`; the acting `X-User-ID` must
        differ from `proposed_by_user_id`, or the approval is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.5: "Separately, the attestation must be genuinely second-person:
        `attested_by_user_id` may not equal the acting `X-User-ID` recorded as
        `poured_by_user_id`, and a bartender attesting their own reading is refused
        with `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.8: "The acting `X-User-ID` must differ from `prepared_by_user_id`, or
        the filing is refused with `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.8: "`taproom_bbl` is the sum of `size_bbl` over every keg asset whose
        `deployment_channel` is `TAPROOM`, whose `tapped_at_utc` is not null, and whose
        `tapped_at_utc` falls inside the window, rounded half up to three decimal
        places."

        Design: Corner/rbac/segregation_of_duties_blocks_self_approval_self_filing_and_self_attestation
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_exempt_beer(
            api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
        )
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            termination_notice_days=90,
            **LICENSE_WINDOW,
        )
        appointment = propose_appointment(
            api, license_row["id"], brand_scope=SCOPE_ALL_BRANDS
        )
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch = validate_success(
            api.create_batch(
                batch_payload(
                    beer["id"],
                    tank["id"],
                    batch_code="B-1001",
                    planned_volume_bbl=16.00,
                    brew_start_utc="2026-08-01T06:00:00Z",
                    brew_end_utc="2026-08-08T06:00:00Z",
                ),
                CELLAR,
            ),
            201,
        )
        validate_success(api.start_batch(batch["id"], CELLAR))
        conditioned = validate_success(
            api.condition_batch(batch["id"], condition_payload(16.000), CELLAR)
        )
        run = validate_success(
            api.create_packaging_run(
                packaging_run_payload(
                    batch["id"],
                    conditioned["version"],
                    package_type=PACKAGE_HALF_BBL_KEG,
                    destination=DESTINATION_TAPROOM,
                    units_planned=2,
                    run_code="R-TAP-1",
                ),
                CELLAR,
            ),
            201,
        )
        validate_success(
            api.complete_packaging_run(run["id"], complete_run_payload(2), CELLAR)
        )
        keg = validate_success(
            api.create_keg_asset(
                keg_asset_payload(KEG_SIZE_HALF_BBL, keg_serial="KEG-0001"), CELLAR
            ),
            201,
        )
        validate_success(api.clean_keg_asset(keg["id"], keg_clean_payload(), CELLAR))
        validate_success(api.fill_keg_asset(keg["id"], keg_fill_payload(run["id"]), CELLAR))
        validate_success(
            api.move_keg_asset(keg["id"], keg_movement_payload(MOVEMENT_TAP), TAPROOM)
        )
        report = draft_report(
            api,
            period_start_utc=AUGUST_START,
            period_end_utc=AUGUST_END,
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
        )

        validate_error(
            api.approve_appointment(
                appointment["id"], headers_for(ROLE_COMPLIANCE_OFFICER, USER_ADMIN_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        held_appointment = validate_success(
            api.get_distributor_appointment(appointment["id"], COMPLIANCE)
        )
        assert held_appointment["state"] == APPT_PROPOSED
        assert held_appointment["proposed_by_user_id"] == USER_ADMIN_1
        assert held_appointment["approved_by_user_id"] is None

        approved = validate_success(
            api.approve_appointment(appointment["id"], COMPLIANCE)
        )
        assert approved["state"] == APPT_ACTIVE
        assert approved["approved_by_user_id"] == USER_COMPLIANCE_1

        validate_error(
            api.create_taproom_pour(
                growler_payload(keg["id"], USER_TAPROOM_1, price_cents=2200), TAPROOM
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        _, empty_meta = validate_paginated(
            api.list_taproom_pours(TAPROOM, {"keg_asset_id": keg["id"]})
        )
        assert empty_meta["total_count"] == 0
        assert_oz(
            validate_success(api.get_keg_asset(keg["id"], CELLAR))["poured_volume_oz"],
            0.00,
            "poured_volume_oz",
        )

        witnessed = validate_success(
            api.create_taproom_pour(
                growler_payload(keg["id"], USER_TAPROOM_2, price_cents=2200), TAPROOM
            ),
            201,
        )
        assert witnessed["poured_by_user_id"] == USER_TAPROOM_1
        assert witnessed["attested_by_user_id"] == USER_TAPROOM_2
        assert_oz(witnessed["volume_oz"], 64.00, "volume_oz")
        assert witnessed["sanitation_verdict"] == SANITATION_PASS

        set_clock(api, AUGUST_END)
        validate_error(
            api.file_excise_report(
                report["id"], headers_for(ROLE_COMPLIANCE_OFFICER, USER_ADMIN_1)
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )
        held_report = validate_success(api.get_excise_report(report["id"], ADMIN))
        assert held_report["state"] == REPORT_DRAFT
        assert held_report["filed_by_user_id"] is None

        filed = validate_success(api.file_excise_report(report["id"], COMPLIANCE))
        assert filed["state"] == REPORT_FILED
        assert filed["filed_by_user_id"] == USER_COMPLIANCE_1
        assert_bbl(filed["taproom_bbl"], 0.500, "taproom_bbl")
