"""Access control and the read surface.

The two 401 gates that precede any permission check, the 403 that keeps each
role inside its own exclusive operations, the entity-backed donor identity whose
lists are filtered rather than refused, the two segregation-of-duties rules that
compare stored operator identifiers instead of roles, and the paginated read
surface over one fully processed batch.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_ID,
    INTAKE_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_ID,
    NO_HEADERS,
    PHARMACIST_HEADERS,
    PHARMACIST_ID,
    PRESCRIBER_HEADERS,
    PRESCRIBER_ID,
    QA_OFFICER_HEADERS,
    QA_OFFICER_ID,
    QA_RELEASER_HEADERS,
    QA_RELEASER_ID,
    TECHNICIAN_HEADERS,
    TECHNICIAN_ID,
    headers_for,
    headers_missing_role,
    headers_missing_user_id,
    make_donor_headers,
)
from test_helpers.types import (
    ClinicalAcuity,
    DonationStatus,
    DonorStatus,
    LotReleaseStatus,
    PatientType,
    PoolStatus,
    PrescriptionStatus,
    ProgramStatus,
    Role,
    ShipmentStatus,
)

INTAKE_CLOCK = C.CLOCK_INTAKE
INTAKE_DATE = C.CLOCK_INTAKE_DATE
RUN_CLOCK = C.CLOCK_RUN
RUN_DATE = C.CLOCK_RUN_DATE
UNKNOWN_ROLE = "MilkBankSuperuser"


def _uniform_chain(volume_each=1200, donor_count=3, expressed_on="2026-07-10", **chain):
    """`donor_count` donors, one 20.0 kcal/oz container each, so the pool's
    projected nutrition sits exactly in the middle of the accepted band."""
    donors = [fx.donor_spec(index + 1) for index in range(donor_count)]
    containers = [
        fx.container_spec(index + 1, index, volume_each, kcal_per_oz=20.0, expressed_on=expressed_on)
        for index in range(donor_count)
    ]
    return fx.build_chain(donors=donors, containers=containers, **chain)


def _lot_on_hold():
    """A 1200 ml lot bottled from a release-eligible run but not yet released."""
    return _uniform_chain(run={}, lots=[(12, 100)], release=False)


class TestTheAuthGatePrecedesEveryPermissionCheck:
    """Both 401 gates are decided before the endpoint's authorized-role list is
    ever consulted."""

    def test_absent_headers_an_empty_identifier_and_an_unknown_role_are_all_401(self):
        """An absent header pair, an empty X-User-ID and an empty X-User-Role all
        answer ERR_MISSING_AUTH_HEADERS, an X-User-Role of MilkBankSuperuser
        answers ERR_UNKNOWN_ROLE rather than the 403 ERR_ROLE_NOT_PERMITTED, and
        only the intact pair reaches the handler.

        PRD: "If either header is absent or present but empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request is examined."
        PRD: "If `X-User-Role` carries a value that is not one of the eight roles below, the rejection is `ERR_UNKNOWN_ROLE` (HTTP 401)."
        PRD: "If the named role is real but is not authorized for the endpoint being addressed — the authorized set for each endpoint is the one given in the §4 table — the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "Each list response reports `limit`, `offset`, `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current window) inside the `meta` object, and carries `response_type` of `"array"`."

        Design: Corner/rbac/auth_gate_rejects_absent_headers_and_an_unknown_role_before_any_permission_check
        """
        fx.set_clock(INTAKE_CLOCK)
        fx.enroll_donor(donor_code="DNR-0001", full_name="Ana Ruiz", zone_code="Z2")

        absent = validate_error(
            api_client.list_donors(NO_HEADERS), ApiErrorId.MISSING_AUTH_HEADERS, 401
        )
        empty_user = validate_error(
            api_client.list_donors(headers_missing_user_id(Role.MILK_BANK_ADMIN)),
            ApiErrorId.MISSING_AUTH_HEADERS,
            401,
        )
        empty_role = validate_error(
            api_client.list_donors(headers_missing_role(ADMIN_ID)),
            ApiErrorId.MISSING_AUTH_HEADERS,
            401,
        )
        unknown = validate_error(
            api_client.list_donors(headers_for(UNKNOWN_ROLE, ADMIN_ID)),
            ApiErrorId.UNKNOWN_ROLE,
            401,
        )
        assert (
            absent["error_id"]
            == empty_user["error_id"]
            == empty_role["error_id"]
            == ApiErrorId.MISSING_AUTH_HEADERS.value
        )
        assert unknown["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED.value, (
            "an unrecognised role never reaches the 403 permission check"
        )

        rows, meta = validate_paginated(api_client.list_donors(ADMIN_HEADERS))
        assert meta["total_count"] == 1 and meta["has_more"] is False
        assert rows[0]["donor_code"] == "DNR-0001"
        assert meta["limit"] == 10 and meta["offset"] == 0
        again, again_meta = validate_paginated(api_client.list_donors(ADMIN_HEADERS))
        assert again_meta["total_count"] == 1, "the three refusals wrote nothing"
        assert again[0]["id"] == rows[0]["id"]


class TestExclusiveOperationsCannotBeSwapped:
    """Each exclusive operation belongs to exactly one role, and borrowing it
    changes nothing."""

    def test_six_borrowed_operations_are_refused_and_the_rightful_owner_succeeds(self):
        """The intake coordinator cannot qualify a donor, file serology or open a
        pool; the pharmacist cannot write an order; the medical director cannot
        open a subsidy programme; the technician cannot move the clock. All six
        answer ERR_ROLE_NOT_PERMITTED at 403, nothing is written, the clock never
        moves, and the director's own qualification call then succeeds.

        PRD: "If the named role is real but is not authorized for the endpoint being addressed — the authorized set for each endpoint is the one given in the §4 table — the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD: "The Authorized Role(s) column lists exactly the values of `X-Role` the operation admits; every other recognized role is refused with `ERR_ROLE_NOT_PERMITTED`, and a `Donor` reading a collection or a resource is additionally confined to her own records per §2.1."
        PRD: "On success the recomputed surveillance score is stored, `qualified_at` is stamped with the clock instant, `qualified_by_user_id` is stamped with the acting director's `X-User-ID`, and the donor's `version` increases by 1."

        Design: Corner/rbac/exclusive_operations_cannot_be_swapped_between_roles
        """
        fx.set_clock(INTAKE_CLOCK)
        donor = fx.cleared_donor(donor_code="DNR-0001", full_name="Ana Ruiz", zone_code="Z2")
        A.assert_donor(donor, status=DonorStatus.SCREENING, screening_risk_score=50)

        refusals = [
            validate_error(
                api_client.qualify_donor(donor["id"], INTAKE_HEADERS),
                ApiErrorId.ROLE_NOT_PERMITTED,
                403,
            ),
            validate_error(
                api_client.record_serology_panel(
                    donor["id"], f.serology_panel(collected_on="2026-08-01"), INTAKE_HEADERS
                ),
                ApiErrorId.ROLE_NOT_PERMITTED,
                403,
            ),
            validate_error(
                api_client.create_pool(f.pool(pool_code="POOL-0001"), INTAKE_HEADERS),
                ApiErrorId.ROLE_NOT_PERMITTED,
                403,
            ),
            validate_error(
                api_client.create_prescription(
                    f.prescription(
                        prescription_code="RX-0001",
                        patient_reference="NICU-A",
                        patient_type=PatientType.NICU_INPATIENT,
                        clinical_acuity=ClinicalAcuity.CRITICAL,
                        requires_preterm_milk=False,
                        subsidy_required=False,
                        prescribed_ml=500,
                        needed_by_date="2026-09-01",
                    ),
                    PHARMACIST_HEADERS,
                ),
                ApiErrorId.ROLE_NOT_PERMITTED,
                403,
            ),
            validate_error(
                api_client.create_subsidy_program(
                    f.subsidy_program(program_code="SUB-0001", name="Community Milk Fund"),
                    MEDICAL_DIRECTOR_HEADERS,
                ),
                ApiErrorId.ROLE_NOT_PERMITTED,
                403,
            ),
            validate_error(
                api_client.set_clock("2026-08-06T08:00:00Z", TECHNICIAN_HEADERS),
                ApiErrorId.ROLE_NOT_PERMITTED,
                403,
            ),
        ]
        assert {refusal["error_id"] for refusal in refusals} == {
            ApiErrorId.ROLE_NOT_PERMITTED.value
        }

        assert validate_paginated(api_client.list_pools(TECHNICIAN_HEADERS))[1]["total_count"] == 0
        assert (
            validate_paginated(api_client.list_prescriptions(PRESCRIBER_HEADERS))[1]["total_count"]
            == 0
        )
        panels, panel_meta = validate_paginated(
            api_client.list_serology_panels(donor["id"], MEDICAL_DIRECTOR_HEADERS)
        )
        assert panel_meta["total_count"] == 1, "the borrowed panel was never filed"
        assert panels[0]["collected_on"] == "2026-07-20"

        qualified = fx.qualify(donor["id"])
        A.assert_donor(
            qualified,
            status=DonorStatus.QUALIFIED,
            qualified_by_user_id=MEDICAL_DIRECTOR_ID,
            surveillance_risk_score=30,
            screening_risk_score=50,
        )
        A.assert_instant_equals(qualified["qualified_at"], INTAKE_CLOCK, "qualified_at")


class TestTheDonorIdentityIsBackedByHerOwnRow:
    """For the Donor role the acting X-User-ID is the Donor row id, so single
    reads are scoped and list channels are filtered."""

    def test_she_reads_her_own_file_is_refused_another_and_her_list_is_filtered(self):
        """A donor reads her own record, is refused another donor's record and
        another donor's cooler with ERR_DONOR_SCOPE_VIOLATION, sees only her own
        cooler in the shipment list, cannot register a cooler under another
        donor_id, and can register one under her own.

        PRD: "When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor` row itself; ownership checks compare the addressed resource's donor reference to `X-User-ID`."
        PRD: "A `Donor` who addresses a resource belonging to another donor is rejected with `ERR_DONOR_SCOPE_VIOLATION` (HTTP 403); the one exception is the donor-scoped list channels, which are silently filtered down to the acting donor's own rows rather than rejected."
        PRD: "Registering a cooler is likewise scoped: a `Donor` may only submit a `donor_id` equal to her own `X-User-ID`."

        Design: Corner/rbac/donor_role_reads_only_her_own_file_and_her_lists_are_filtered_not_rejected
        """
        fx.set_clock(INTAKE_CLOCK)
        first = fx.qualified_donor(donor_code="DNR-0001", full_name="Ana Ruiz", zone_code="Z2")
        second = fx.qualified_donor(
            donor_code="DNR-0002",
            full_name="Bea Ortiz",
            zone_code="Z1",
            collected_on="2026-07-22",
            physician_npi="1234567802",
            approved_on="2026-07-16",
        )
        own_cooler = fx.register_shipment(
            first["id"], tracking_code="TRK-0001", declared_volume_ml=600
        )
        other_cooler = fx.register_shipment(
            second["id"], tracking_code="TRK-0002", declared_volume_ml=600
        )
        acting = make_donor_headers(first["id"])

        own_read = validate_success(api_client.get_donor(first["id"], acting), 200)
        assert own_read["donor_code"] == "DNR-0001"
        assert (
            validate_error(
                api_client.get_donor(second["id"], acting),
                ApiErrorId.DONOR_SCOPE_VIOLATION,
                403,
            )["error_id"]
            == ApiErrorId.DONOR_SCOPE_VIOLATION.value
        )
        validate_error(
            api_client.get_shipment(other_cooler["id"], acting),
            ApiErrorId.DONOR_SCOPE_VIOLATION,
            403,
        )

        scoped, scoped_meta = validate_paginated(api_client.list_shipments(acting))
        assert scoped_meta["total_count"] == 1 and scoped_meta["has_more"] is False
        assert scoped[0]["tracking_code"] == "TRK-0001", (
            "the other donor's cooler is filtered out, not refused"
        )

        validate_error(
            api_client.create_shipment(
                f.shipment(second["id"], tracking_code="TRK-0003", declared_volume_ml=600), acting
            ),
            ApiErrorId.DONOR_SCOPE_VIOLATION,
            403,
        )
        all_coolers, all_meta = validate_paginated(api_client.list_shipments(INTAKE_HEADERS))
        assert all_meta["total_count"] == 2
        assert "TRK-0003" not in {row["tracking_code"] for row in all_coolers}

        registered = validate_success(
            api_client.create_shipment(
                f.shipment(first["id"], tracking_code="TRK-0004", declared_volume_ml=600), acting
            ),
            201,
        )
        A.assert_shipment(
            registered,
            donor_id=first["id"],
            tracking_code="TRK-0004",
            status=ShipmentStatus.IN_TRANSIT,
        )
        assert validate_paginated(api_client.list_shipments(acting))[1]["total_count"] == 2
        assert (
            validate_paginated(api_client.list_shipments(INTAKE_HEADERS))[1]["total_count"] == 3
        )
        assert fx.get_shipment(registered["id"])["donor_id"] == first["id"]
        assert own_cooler["donor_id"] == first["id"]


class TestSegregationOfDutiesComparesIdentifiersNotRoles:
    """Holding the right role is not enough: the two accreditation rules compare
    the operator identifiers stored on the run and on the order."""

    def test_the_culture_recorder_the_completer_and_the_prescriber_are_all_refused(self):
        """Release is refused for the officer who recorded the culture and for the
        technician who completed the run even under the QA role, and the fill is
        refused for the prescriber's own identifier even under the pharmacist
        role; the lot stays on HOLD, no fill row appears, and the rightful actors
        then succeed.

        PRD: "At lot release, the releasing `QualityAssuranceOfficer`'s `X-User-ID` must differ from the run's `completed_by_user_id` **and** from the run's `culture_recorded_by_user_id`; a match with either one is refused with `ERR_SOD_RELEASE_CONFLICT` (HTTP 403)."
        PRD: "At fill time, the dispensing `DispensingPharmacist`'s `X-User-ID` must differ from the prescription's `prescriber_user_id`; a match is refused with `ERR_SOD_DISPENSE_CONFLICT` (HTTP 403)."
        PRD: "Both checks are unconditional: no override parameter exists, and no role bypasses them."
        PRD: "On success `released_at` is stamped with the clock instant, `released_by_user_id` with the acting officer's `X-User-ID`, and the lot's `version` increases by 1."
        PRD: "Then the OCC token is compared, per §2.7. Then segregation of duties: the acting pharmacist's `X-User-ID` must differ from the order's `prescriber_user_id`, else `ERR_SOD_DISPENSE_CONFLICT`."

        Design: Corner/rbac/segregation_of_duties_stops_the_culture_recorder_from_releasing_and_the_prescriber_from_dispensing
        """
        chain = _lot_on_hold()
        lot = chain.lots[0]
        A.assert_run(
            chain.run,
            completed_by_user_id=TECHNICIAN_ID,
            culture_recorded_by_user_id=QA_OFFICER_ID,
        )

        culturer = validate_error(
            api_client.release_milk_lot(lot["id"], QA_OFFICER_HEADERS),
            ApiErrorId.SOD_RELEASE_CONFLICT,
            403,
        )
        completer = validate_error(
            api_client.release_milk_lot(
                lot["id"], headers_for(Role.QUALITY_ASSURANCE_OFFICER, TECHNICIAN_ID)
            ),
            ApiErrorId.SOD_RELEASE_CONFLICT,
            403,
        )
        assert culturer["error_id"] == completer["error_id"] == ApiErrorId.SOD_RELEASE_CONFLICT.value
        assert completer["error_id"] != ApiErrorId.ROLE_NOT_PERMITTED.value, (
            "the QualityAssuranceOfficer role passed the permission check"
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            release_status=LotReleaseStatus.HOLD,
            released_by_user_id=None,
        )

        released = validate_success(
            api_client.release_milk_lot(lot["id"], QA_RELEASER_HEADERS), 200
        )
        A.assert_milk_lot(
            released,
            release_status=LotReleaseStatus.RELEASED,
            released_by_user_id=QA_RELEASER_ID,
        )

        order = fx.submit_prescription(
            prescription_code="RX-8101",
            patient_reference="NICU-B",
            patient_type=PatientType.NICU_INPATIENT,
            clinical_acuity=ClinicalAcuity.CRITICAL,
            requires_preterm_milk=False,
            subsidy_required=False,
            prescribed_ml=1200,
            needed_by_date="2026-09-01",
        )
        A.assert_prescription(order, prescriber_user_id=PRESCRIBER_ID)
        before = fx.lot_version(lot["id"])
        validate_error(
            api_client.create_dispense(
                order["id"],
                f.dispense(lot["id"], 600, before),
                headers_for(Role.DISPENSING_PHARMACIST, PRESCRIBER_ID),
            ),
            ApiErrorId.SOD_DISPENSE_CONFLICT,
            403,
        )
        assert fx.lot_version(lot["id"]) == before, "the refused fill wrote nothing"
        assert fx.list_prescription_dispenses(order["id"]) == []

        fill = validate_success(
            api_client.create_dispense(
                order["id"], f.dispense(lot["id"], 600, before), PHARMACIST_HEADERS
            ),
            201,
        )
        A.assert_dispense(
            fill,
            volume_ml=600,
            gross_fee_cents=2880,
            subsidy_cents=0,
            payer_due_cents=2880,
            dispensed_by_user_id=PHARMACIST_ID,
            allocation_cycle_sequence=None,
        )
        A.assert_milk_lot(
            fx.get_lot(lot["id"]),
            dispensed_ml=600,
            available_ml=600,
            release_status=LotReleaseStatus.RELEASED,
        )
        A.assert_prescription(
            fx.get_prescription(order["id"]),
            cumulative_dispensed_ml=600,
            remaining_ml=600,
            status=PrescriptionStatus.PARTIALLY_FILLED,
        )


class TestEveryReadPathAgreesWithEveryOther:
    """Ten read endpoints over one fully processed batch: each collection
    answers with the paginated envelope and each single read repeats exactly
    what the collection row said."""

    def test_the_single_reads_and_the_paginated_lists_report_the_same_batch(self):
        """One 300 ml subsidised fill against a released 1200 ml lot is visible
        identically through the panel, approval, donation, pool, run, lot, both
        dispense lists, the prescription list, the single order read and the
        programme ledger — and repeating every read changes no version.

        PRD: "Each list response reports `limit`, `offset`, `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current window) inside the `meta` object, and carries `response_type` of `"array"`."
        PRD: "Thereafter a lot's `dispensed_ml` is the sum of `volume_ml` across the fills against it whose `status` is `DISPENSED`, and its `available_ml` is its `total_volume_ml` less that figure."
        PRD: "These filters double as the reverse-reachability channels by which a client walks from a parent to its children, since the bank exposes no nested ownership URLs."
        PRD: "A donation's `remaining_ml` is thereafter always its `volume_ml` less the sum of `allocated_volume_ml` across its non-`VOIDED` components, and never goes below 0."

        Design: Corner/endpoints/read_surface_single_reads_and_paginated_lists_agree_across_the_whole_processing_chain
        """
        chain = _uniform_chain(run={}, lots=[(12, 100)])
        lot = chain.lots[0]
        program = fx.open_program(
            program_code="SUB-0001",
            name="County NICU Milk Fund",
            coverage_pct=0.50,
            annual_cap_cents=100000,
        )
        order = fx.submit_prescription(
            prescription_code="RX-8401",
            subsidy_program_id=program["id"],
            patient_reference="NICU-F",
            patient_type=PatientType.NICU_INPATIENT,
            clinical_acuity=ClinicalAcuity.CRITICAL,
            requires_preterm_milk=False,
            subsidy_required=True,
            prescribed_ml=300,
            needed_by_date="2026-09-01",
        )
        fill = fx.fill_prescription(order["id"], lot["id"], 300)
        A.assert_dispense(
            fill, volume_ml=300, gross_fee_cents=1440, subsidy_cents=720, payer_due_cents=720
        )

        panels, panel_meta = validate_paginated(
            api_client.list_serology_panels(chain.donors[0]["id"], MEDICAL_DIRECTOR_HEADERS)
        )
        assert panel_meta["total_count"] == 1 and panel_meta["has_more"] is False
        assert panels[0]["panel_status"] == "NON_REACTIVE"
        assert panels[0]["collected_on"] == "2026-07-20"

        approvals, approval_meta = validate_paginated(
            api_client.list_physician_approvals(chain.donors[0]["id"], MEDICAL_DIRECTOR_HEADERS)
        )
        assert approval_meta["total_count"] == 1 and approval_meta["has_more"] is False
        assert approvals[0]["physician_npi"] == "1234567893"
        assert approvals[0]["approved_on"] == "2026-07-15"

        donation = validate_success(
            api_client.get_donation(chain.donations[0]["id"], TECHNICIAN_HEADERS), 200
        )
        A.assert_donation(donation, status=DonationStatus.PASTEURIZED, remaining_ml=0)

        pools, pool_meta = validate_paginated(api_client.list_pools(TECHNICIAN_HEADERS))
        assert pool_meta["total_count"] == 1 and pool_meta["has_more"] is False
        A.assert_pool(
            pools[0],
            pool_code="POOL-0001",
            status=PoolStatus.PASTEURIZED,
            bottled_volume_ml=1200,
            total_volume_ml=3600,
        )

        runs, run_meta = validate_paginated(api_client.list_runs(QA_RELEASER_HEADERS))
        assert run_meta["total_count"] == 1 and run_meta["has_more"] is False
        A.assert_run(runs[0], pasteurizer_id="PAST-01", cycle_minutes=60)

        lots, lot_meta = validate_paginated(api_client.list_milk_lots(QA_RELEASER_HEADERS))
        assert lot_meta["total_count"] == 1 and lot_meta["has_more"] is False
        A.assert_milk_lot(
            lots[0],
            lot_code="20260810-001-01",
            release_status=LotReleaseStatus.RELEASED,
            total_volume_ml=1200,
            dispensed_ml=300,
            available_ml=900,
        )

        lot_side, lot_side_meta = validate_paginated(
            api_client.list_lot_dispenses(lot["id"], QA_RELEASER_HEADERS)
        )
        assert lot_side_meta["total_count"] == 1 and lot_side_meta["has_more"] is False
        A.assert_dispense(
            lot_side[0],
            id=fill["id"],
            prescription_id=order["id"],
            volume_ml=300,
            gross_fee_cents=1440,
            subsidy_cents=720,
            payer_due_cents=720,
        )
        order_side, order_side_meta = validate_paginated(
            api_client.list_prescription_dispenses(order["id"], PRESCRIBER_HEADERS)
        )
        assert order_side_meta["total_count"] == 1
        assert order_side[0] == lot_side[0], (
            "the lot-side and prescription-side lists reach the same row"
        )

        orders, order_meta = validate_paginated(api_client.list_prescriptions(PRESCRIBER_HEADERS))
        assert order_meta["total_count"] == 1 and order_meta["has_more"] is False
        A.assert_prescription(orders[0], prescription_code="RX-8401", priority_tier=1)
        single_order = validate_success(
            api_client.get_prescription(order["id"], PRESCRIBER_HEADERS), 200
        )
        A.assert_prescription(
            single_order,
            status=PrescriptionStatus.FILLED,
            cumulative_dispensed_ml=300,
            remaining_ml=0,
            waitlist_position=None,
        )

        ledger = validate_success(
            api_client.get_subsidy_program(program["id"], ADMIN_HEADERS), 200
        )
        A.assert_subsidy_program(ledger, consumed_cents=720, status=ProgramStatus.OPEN)

        # Repeating every read is a pure read: no version moves.
        versions = (
            fx.get_pool(chain.pool["id"])["version"],
            fx.get_lot(lot["id"])["version"],
            fx.get_prescription(order["id"])["version"],
        )
        for _ in range(2):
            validate_paginated(api_client.list_pools(TECHNICIAN_HEADERS))
            validate_paginated(api_client.list_milk_lots(QA_RELEASER_HEADERS))
            validate_paginated(api_client.list_prescriptions(PRESCRIBER_HEADERS))
            validate_success(api_client.get_subsidy_program(program["id"], ADMIN_HEADERS), 200)
        assert versions == (
            fx.get_pool(chain.pool["id"])["version"],
            fx.get_lot(lot["id"])["version"],
            fx.get_prescription(order["id"])["version"],
        )
