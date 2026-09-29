"""Access control: the five-role chain each running its own exclusive writes, the
refusals every neighbouring role earns on both halves of the API, the read surface
that is deliberately not uniform, the shipper ownership hops and list narrowing,
the segregation-of-duties pair, and the lookup, header and state-code catalogues
that no other module reaches."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_COMPRESSOR_RUN_NOT_FOUND,
    ERR_COMPRESSOR_UNIT_NOT_FOUND,
    ERR_CONTRACT_NOT_OWNED,
    ERR_EMERGENCY_EVENT_NOT_FOUND,
    ERR_INVALID_MIT_STATE,
    ERR_INVALID_REMEDIATION_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_MIT_NOT_FOUND,
    ERR_REMEDIATION_PROGRAM_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
    ERR_SOD_REMEDIATION_SELF_VERIFICATION,
    ERR_TICKET_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_created,
    assert_created_at_ascending,
    assert_error_envelope,
    assert_field_derived_block,
    assert_instant_equals,
    assert_ledger_entry,
    assert_money,
    assert_ok,
    assert_ticket_charges_unpriced,
    assert_variance_pct,
    assert_volume,
    assert_whole_dth,
)
from test_helpers.constants import (
    AGENCY_ACCEPTED,
    CLOCK_EPOCH,
    CONTRACT_ACTIVE,
    CONTRACT_DRAFT,
    DELIVERABILITY_CURVE_INTERPOLATED,
    EMERGENCY_DETECTED,
    EMERGENCY_RESPONDING,
    EVENT_TYPE_LEAK,
    EVENT_TYPE_OVERPRESSURE,
    INTEGRITY_MIT_CURRENT,
    INTEGRITY_REMEDIATED,
    LEDGER_DAILY_IMBALANCE,
    MIT_OUTCOME_FAIL,
    MIT_OUTCOME_PASS,
    MIT_SCHEDULED,
    NOMINATION_CONFIRMED,
    NOMINATION_DRAFT,
    NOMINATION_SUBMITTED,
    POSTURE_OPEN,
    REMEDIATION_COMPLETED,
    REMEDIATION_OPEN,
    REPORT_ACCEPTED,
    REPORT_DRAFT,
    REPORT_SUBMITTED,
    REPORT_TYPE_INTEGRITY,
    ROLE_FIELD_OPERATOR,
    ROLE_SHIPPER,
    SEASON_INJECTION,
    SEASON_WITHDRAWAL,
    SERVICE_CLASS_INTERRUPTIBLE,
    SEVERITY_MINOR,
    TICKET_CONFIRMED,
    TICKET_PENDING,
    UNIT_AVAILABLE,
    WELL_IN_SERVICE,
    WELL_SHUT_IN,
)
from test_helpers.fixtures import (
    book_run,
    complete_run,
    confirm_ticket,
    confirmed_nomination,
    contract_version,
    create_active_contract,
    create_contract,
    create_field,
    create_report,
    create_second_shipper,
    create_shipper,
    create_unit,
    create_well,
    fail_mit_on_well,
    field_version,
    file_nomination,
    open_ticket,
    read_contract,
    read_field,
    read_program,
    read_unit,
    read_well,
    record_mit,
    remediate_well,
    schedule_mit,
    set_clock,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_B,
    ENGINEER_A_ID,
    ENGINEER_B_ID,
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER,
    INTEGRITY_ENGINEER_B,
    NO_AUTH_HEADERS,
    OFFICER_A_ID,
    OFFICER_B_ID,
    SCHEDULING_COORDINATOR,
    headers_empty_user_id,
    headers_unknown_role,
    make_shipper_headers,
)

# A well-formed uuid that names nothing, so a refusal can never be blamed on
# PRD §2.11 rung 3's syntactic check.
SENTINEL_ID = "00000000-0000-4000-8000-000000000000"


def _field_reports(api, field_id, headers=None, **params):
    """Reports have no individual read channel, so they are re-read through the
    reservoir's own report listing."""
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(
        api.list_field_regulatory_reports(field_id, headers or COMPLIANCE_OFFICER, query)
    )


def _assert_all_refused(refusals, expected_error_id):
    """Assert a labelled batch of calls each carries the same refusal code."""
    for label, response in refusals:
        assert_error_envelope(response, expected_error_id)
        body = response.json()["data"]
        assert body["error_id"] == expected_error_id, (
            f"{label}: expected {expected_error_id}, got {body['error_id']}"
        )


def _read_report(api, field_id, report_id):
    rows, _ = _field_reports(api, field_id)
    matching = [row for row in rows if row["id"] == report_id]
    assert len(matching) == 1, f"Expected report {report_id} in the field listing"
    return matching[0]


class TestEveryRoleRunsItsOwnExclusiveOperations:
    """The five roles form a chain, not a hierarchy: one storage cycle can only be
    driven by handing control back and forth between them."""

    def test_one_storage_cycle_passes_through_all_five_roles_without_a_refusal(self, api):
        """The FieldOperator registers the reservoir, the wellbore and the station, the
        IntegrityEngineer books the integrity test, the SchedulingCoordinator onboards
        the customer and writes the contract, the Shipper files and submits, the
        coordinator confirms, the operator meters and the ComplianceOfficer prepares
        the filing -- and the two shared writes, opening an emergency event and moving
        the logical clock, answer to more than one role.

        PRD §2.1: "`IntegrityEngineer` — owns wellbore integrity. Schedules mechanical
        integrity tests, records their outcomes, and closes remediation programs. Cannot
        move gas and cannot schedule commerce."

        Design: Corner/rbac/all_five_roles_can_run_their_own_exclusive_operations_end_to_end
        """
        field = create_field(api)
        well = create_well(api, field["id"])
        unit = create_unit(api, field["id"])
        assert unit["status"] == UNIT_AVAILABLE

        booked = assert_created(
            api.create_mit(
                F.mit_payload(
                    well["id"],
                    scheduled_start_at="2026-08-20T00:00:00Z",
                    scheduled_end_at="2026-08-20T06:00:00Z",
                ),
                INTEGRITY_ENGINEER,
            )
        )
        assert booked["status"] == MIT_SCHEDULED, (
            f"Booking a window records no result, got {booked['status']}"
        )
        assert booked["recorded_by_user_id"] is None, (
            "Booking a test must not stamp recorded_by_user_id"
        )

        shipper = create_shipper(api)
        contract = create_active_contract(api, shipper["id"], field["id"])
        assert contract["status"] == CONTRACT_ACTIVE

        shipper_headers = make_shipper_headers(shipper["id"])
        as_customer = assert_ok(api.get_contract(contract["id"], shipper_headers))
        token = as_customer["version"]
        assert token == contract["version"], (
            "The customer's OCC token is the post-activation contract version, "
            f"expected {contract['version']}, got {token}"
        )

        nomination = assert_created(
            api.create_nomination(
                F.nomination_payload(
                    contract["id"], token, gas_day="2026-08-02", nominated_volume_dth=80000
                ),
                shipper_headers,
            )
        )
        assert nomination["status"] == NOMINATION_DRAFT
        submitted = assert_ok(
            api.submit_nomination(nomination["id"], shipper_headers, F.submit_nomination_payload())
        )
        assert submitted["status"] == NOMINATION_SUBMITTED
        confirmed = assert_ok(api.confirm_nomination(nomination["id"], SCHEDULING_COORDINATOR))
        assert confirmed["status"] == NOMINATION_CONFIRMED
        assert_whole_dth(confirmed["confirmed_volume_dth"], 80000, "confirmed_volume_dth")
        assert_whole_dth(confirmed["curtailed_volume_dth"], 0, "curtailed_volume_dth")

        ticket = assert_created(
            api.create_ticket(F.ticket_payload(nomination["id"], well["id"], 80000), FIELD_OPERATOR)
        )
        assert ticket["status"] == TICKET_PENDING
        assert_ticket_charges_unpriced(ticket)

        report = assert_created(
            api.create_regulatory_report(
                F.regulatory_report_payload(field["id"], 250000), COMPLIANCE_OFFICER
            )
        )
        assert report["status"] == REPORT_DRAFT
        assert report["prepared_by_user_id"] == OFFICER_A_ID
        assert_volume(report["book_inventory_dth"], 250000.000, "book_inventory_dth")
        assert_variance_pct(report["variance_pct"], 0.0000)

        by_officer = assert_created(
            api.create_emergency_event(
                F.emergency_event_payload(
                    field["id"], event_type=EVENT_TYPE_OVERPRESSURE, severity=SEVERITY_MINOR
                ),
                COMPLIANCE_OFFICER,
            )
        )
        by_operator = assert_created(
            api.create_emergency_event(
                F.emergency_event_payload(
                    field["id"],
                    event_type=EVENT_TYPE_LEAK,
                    severity=SEVERITY_MINOR,
                    well_id=well["id"],
                ),
                FIELD_OPERATOR,
            )
        )
        for event in (by_officer, by_operator):
            assert event["status"] == EMERGENCY_DETECTED, (
                f"A new event opens DETECTED, got {event['status']}"
            )

        moved = assert_ok(api.set_clock("2026-08-01T06:00:00Z", COMPLIANCE_OFFICER))
        assert_instant_equals(moved["current_utc"], "2026-08-01T06:00:00Z")

        # Metering moved no gas and neither MINOR event touched the posture.
        assert_field_derived_block(
            read_field(api, field["id"]),
            working_gas=250000.000,
            inventory_pct=50.00,
            wells_in_service=1,
            posture=POSTURE_OPEN,
        )


class TestExclusiveWritesAreRefusedToNeighbouringRoles:
    """Every refusal below is a 403 that fires ahead of the path lookup, the body
    shape and the ownership narrowing that the same request would also have failed."""

    def test_the_operational_and_integrity_writes_refuse_their_closest_neighbours(self, api):
        """A well-formed sentinel id that resolves to nothing, and bodies missing
        required fields, still earn 403: the IntegrityEngineer who owns wellbore
        integrity may not change a wellbore's service state, and the FieldOperator who
        owns the wellbore may not book or record its integrity test.

        PRD §2.11 rung 2: "**Authorization.** The acting role appears among the
        endpoint's authorized roles in §4 — otherwise `ERR_UNAUTHORIZED` (403). Applies
        to every endpoint."

        Design: Corner/rbac/operational_and_integrity_exclusives_are_rejected_for_every_other_role
        """
        field = create_field(api)
        well = create_well(api, field["id"])
        fv1 = field_version(api, field["id"])

        rogue_field = {
            "name": "Rogue Cavern",
            "field_code": "F-ROGUE",
            "total_capacity_dth": 1000000,
            "cushion_gas_dth": 500000,
            "base_pressure_psig": 800,
            "pressure_span_psig": 1400,
            "max_pressure_psig": 3000,
            "deliverability_method": DELIVERABILITY_CURVE_INTERPOLATED,
            "deliverability_curve": F.two_point_curve(300000, 300000),
        }
        refusals = [
            ("field create as the coordinator",
             api.create_storage_field(rogue_field, SCHEDULING_COORDINATOR)),
            ("season flip as the officer",
             api.set_season(field["id"], F.season_payload(SEASON_WITHDRAWAL), COMPLIANCE_OFFICER)),
            ("well create as the engineer",
             api.create_well(
                 F.well_payload(field["id"], well_name="MINI-2"), INTEGRITY_ENGINEER)),
            ("service change as the engineer",
             api.change_well_service(
                 well["id"], F.service_change_payload(WELL_SHUT_IN, "Integrity concern"),
                 INTEGRITY_ENGINEER)),
            ("unit create as the coordinator",
             api.create_compressor_unit(
                 {"storage_field_id": field["id"], "unit_code": "U-9", "rated_horsepower": 6000},
                 SCHEDULING_COORDINATOR)),
            ("run booking on a missing unit as the coordinator",
             api.create_compressor_run(
                 F.compressor_run_payload(
                     SENTINEL_ID,
                     window_start_at="2026-08-10T00:00:00Z",
                     window_end_at="2026-08-10T08:00:00Z"),
                 SCHEDULING_COORDINATOR)),
            ("run completion on a missing run as the engineer",
             api.complete_compressor_run(SENTINEL_ID, INTEGRITY_ENGINEER)),
            ("ticket create as the coordinator",
             api.create_ticket(
                 F.ticket_payload(SENTINEL_ID, well["id"], 1000), SCHEDULING_COORDINATOR)),
            ("ticket confirm as a shipper",
             api.confirm_ticket(
                 SENTINEL_ID, F.ticket_confirm_payload(fv1), make_shipper_headers(SENTINEL_ID))),
            ("ticket reversal as the officer",
             api.reverse_ticket(
                 SENTINEL_ID, F.ticket_reversal_payload("Rogue reversal"), COMPLIANCE_OFFICER)),
            ("test booking as the operator",
             api.create_mit(F.mit_payload(well["id"]), FIELD_OPERATOR)),
            ("result recording as the officer",
             api.record_mit_result(
                 SENTINEL_ID, F.mit_result_payload(MIT_OUTCOME_PASS, 1200), COMPLIANCE_OFFICER)),
            ("remediation completion as the operator",
             api.complete_remediation_program(
                 SENTINEL_ID, F.remediation_completion_payload("Signed off"), FIELD_OPERATOR)),
        ]
        _assert_all_refused(refusals, ERR_UNAUTHORIZED)

        # Nothing moved: the reservoir kept its season and its version, the wellbore
        # kept its service state, and neither the station nor the test table was written.
        unchanged = read_field(api, field["id"])
        assert unchanged["season"] == SEASON_INJECTION
        assert unchanged["version"] == fv1, (
            f"Refused writes must not bump the field version, expected {fv1}, "
            f"got {unchanged['version']}"
        )
        assert read_well(api, well["id"])["operational_state"] == WELL_IN_SERVICE
        _, unit_meta = validate_paginated(api.list_compressor_units(FIELD_OPERATOR, {"limit": 100}))
        assert unit_meta["total_count"] == 0, (
            f"No compressor unit was created, got {unit_meta['total_count']}"
        )
        _, mit_meta = validate_paginated(api.list_mits(INTEGRITY_ENGINEER, {"limit": 100}))
        assert mit_meta["total_count"] == 0, (
            f"No integrity test was booked, got {mit_meta['total_count']}"
        )

    def test_the_commercial_and_compliance_writes_refuse_their_closest_neighbours(self, api):
        """The Shipper may neither activate its own contract nor confirm its own
        nomination, the coordinator may not file one on its customer's behalf, and the
        officer who reads every contract may not write one or settle a cash-out. The
        engineer's refused submission never reaches the duty-split comparison.

        PRD §2.11 rung 2: "**Authorization.** The acting role appears among the
        endpoint's authorized roles in §4 — otherwise `ERR_UNAUTHORIZED` (403). Applies
        to every endpoint."

        Design: Corner/rbac/commercial_and_compliance_exclusives_are_rejected_for_every_other_role
        """
        field = create_field(api)
        well = create_well(api, field["id"])
        shipper = create_shipper(api)
        contract = create_active_contract(api, shipper["id"], field["id"])
        cv1 = contract["version"]
        nomination = file_nomination(
            api, contract["id"], shipper["id"], gas_day="2026-08-02", nominated_volume_dth=80000
        )
        report = create_report(api, field["id"], 250000)
        # PRD §3.5: "Every filing increments the contract's `version` by one", so
        # the successful filing above has already moved the token past cv1. The
        # baseline the refusals must not disturb is the version as of here.
        cv_before_refusals = contract_version(api, contract["id"])
        assert cv_before_refusals == cv1 + 1, (
            f"One accepted filing bumps the contract once, got {cv_before_refusals}"
        )

        refusals = [
            ("shipper onboarding as the operator",
             api.create_shipper(
                 F.shipper_payload(legal_name="Rogue Marketing", duns_number="555555555",
                                   penalty_threshold_usd=100000.00),
                 FIELD_OPERATOR)),
            ("contract draft as the officer",
             api.create_contract(
                 F.contract_payload(shipper["id"], field["id"], contract_code="CN-9"),
                 COMPLIANCE_OFFICER)),
            ("contract activation as the customer",
             api.activate_contract(contract["id"], make_shipper_headers(shipper["id"]))),
            ("cash-out as the officer",
             api.cash_out(
                 contract["id"], F.cash_out_payload("2026-08-01", "2026-08-31"),
                 COMPLIANCE_OFFICER)),
            ("cash-out reversal as the operator",
             api.cash_out_reversal(
                 contract["id"], F.cash_out_reversal_payload("Rogue reversal"), FIELD_OPERATOR)),
            ("nomination filing as the coordinator",
             api.create_nomination(
                 F.nomination_payload(
                     contract["id"], cv1, gas_day="2026-08-03", nominated_volume_dth=80000),
                 SCHEDULING_COORDINATOR)),
            ("nomination submission as the coordinator",
             api.submit_nomination(nomination["id"], SCHEDULING_COORDINATOR)),
            ("nomination confirmation as the customer",
             api.confirm_nomination(nomination["id"], make_shipper_headers(shipper["id"]))),
            ("report preparation as the operator",
             api.create_regulatory_report(
                 F.regulatory_report_payload(
                     field["id"], 250000, report_type=REPORT_TYPE_INTEGRITY),
                 FIELD_OPERATOR)),
            ("report submission as the engineer",
             api.submit_regulatory_report(report["id"], INTEGRITY_ENGINEER)),
            ("agency response as the coordinator",
             api.record_agency_response(
                 report["id"], F.agency_response_payload(AGENCY_ACCEPTED), SCHEDULING_COORDINATOR)),
        ]
        _assert_all_refused(refusals, ERR_UNAUTHORIZED)

        # The engineer's refusal is the role gate, not the duty split, so the report
        # never reached its prepared_by comparison and is still a draft.
        assert _read_report(api, field["id"], report["id"])["status"] == REPORT_DRAFT
        _, shipper_book = validate_paginated(
            api.list_contracts(SCHEDULING_COORDINATOR, {"limit": 100})
        )
        assert shipper_book["total_count"] == 1, (
            f"No second contract was drafted, got {shipper_book['total_count']}"
        )
        still_draft = api.get_nomination(nomination["id"], make_shipper_headers(shipper["id"]))
        current = assert_ok(still_draft)
        assert current["status"] == NOMINATION_DRAFT
        assert current["revision_round"] == 0, (
            f"A refused submission runs no allocation round, got {current['revision_round']}"
        )
        assert read_contract(api, contract["id"])["version"] == cv_before_refusals, (
            "Every refused write left the contract's OCC token intact"
        )
        assert read_well(api, well["id"])["operational_state"] == WELL_IN_SERVICE


class TestTheReadSurfaceIsNotUniform:
    """An internal operator is locked out of the commercial reads and the external
    customer out of the operational ones, yet both may read wellbores and the field."""

    def test_each_role_is_refused_the_reads_outside_its_own_list_and_keeps_its_own(self, api):
        """The IntegrityEngineer cannot see shippers, contracts, the ledger, nominations
        or tickets; the Shipper cannot see integrity tests, remediation programs,
        compressor runs, emergency events, the field's filings or the logical clock --
        and an implementation that grants every GET to every authenticated role passes
        nothing here.

        PRD §4: "| GET | `/storage-fields/{id}/regulatory-reports` | List the regulatory
        reports filed for this storage field | FieldOperator, IntegrityEngineer,
        SchedulingCoordinator, ComplianceOfficer |"

        PRD §2.11 rung 2: "**Authorization.** The acting role appears among the
        endpoint's authorized roles in §4 — otherwise `ERR_UNAUTHORIZED` (403). Applies
        to every endpoint."

        Design: Corner/rbac/read_endpoints_outside_a_roles_shared_list_are_rejected_while_its_own_reads_pass
        """
        field = create_field(api)
        well = create_well(api, field["id"])
        unit = create_unit(api, field["id"])
        shipper = create_shipper(api)
        contract = create_contract(api, shipper["id"], field["id"])
        assert contract["status"] == CONTRACT_DRAFT
        report = create_report(api, field["id"], 250000)
        customer = make_shipper_headers(shipper["id"])
        fv1 = field_version(api, field["id"])

        page = {"limit": 100}
        _assert_all_refused(
            [
                ("shipper read as the engineer", api.get_shipper(shipper["id"], INTEGRITY_ENGINEER)),
                ("contract list as the engineer", api.list_contracts(INTEGRITY_ENGINEER, page)),
                ("ledger as the engineer",
                 api.list_ledger_entries(contract["id"], INTEGRITY_ENGINEER, page)),
                ("nomination list as the engineer", api.list_nominations(INTEGRITY_ENGINEER, page)),
                ("ticket list as the engineer", api.list_tickets(INTEGRITY_ENGINEER, page)),
                ("integrity test list as the customer", api.list_mits(customer, page)),
                ("remediation list as the customer",
                 api.list_remediation_programs(customer, page)),
                ("unit runs as the customer", api.list_unit_runs(unit["id"], customer, page)),
                ("emergency list as the customer", api.list_emergency_events(customer, page)),
                ("field filings as the customer",
                 api.list_field_regulatory_reports(field["id"], customer, page)),
                ("clock write as the customer", api.set_clock("2026-08-05T00:00:00Z", customer)),
            ],
            ERR_UNAUTHORIZED,
        )

        # The customer's read surface is narrow, not empty.
        wells, well_meta = validate_paginated(
            api.list_wells(customer, {"storage_field_id": field["id"], "limit": 100})
        )
        assert well_meta["total_count"] == 1, (
            f"The customer may list wellbores, got {well_meta['total_count']}"
        )
        assert wells[0]["id"] == well["id"]
        assert wells[0]["operational_state"] == WELL_IN_SERVICE

        # And the engineer's lockout is commercial only: the reservoir read is shared.
        as_engineer = assert_ok(api.get_storage_field(field["id"], INTEGRITY_ENGINEER))
        assert_field_derived_block(
            as_engineer,
            working_gas=250000.000,
            inventory_pct=50.00,
            pressure=1500,
            injection_rate=150000,
            withdrawal_rate=150000,
            wells_in_service=1,
            posture=POSTURE_OPEN,
        )
        assert as_engineer["version"] == fv1, (
            f"A read mutates nothing, expected version {fv1}, got {as_engineer['version']}"
        )
        assert _read_report(api, field["id"], report["id"])["status"] == REPORT_DRAFT

        # The refused clock write left the logical clock where it was, which the next
        # record's server-stamped created_at reports.
        probe = create_well(api, field["id"], well_name="MINI-2")
        assert_instant_equals(probe["created_at"], CLOCK_EPOCH)


class TestShipperOwnershipHops:
    """Ownership is a comparison of X-User-ID against the contract's shipper_id
    reached through up to two hops, and it gates the by-id reads exactly like the
    writes."""

    def test_a_second_good_standing_customer_is_refused_every_hop_into_the_first(self, api):
        """SOUTHLINE is a legitimate customer with its own ACTIVE contract on the SAME
        reservoir, so nothing but the ownership hop separates its refusals from
        NORTHLINE's successes -- and the refusals are 403, never 404 and never a 200
        with fields blanked out.

        PRD §2.1: "A shipper may only touch a storage service contract whose
        `shipper_id` equals `X-User-ID`, whether that contract is named directly in the
        path, reached through the nomination named in the path, or reached through the
        nomination behind the gas movement ticket named in the path. A violation is
        reported as `ERR_CONTRACT_NOT_OWNED` (HTTP 403). Single-resource reads are gated
        identically to writes."

        Design: Corner/rbac/a_shipper_cannot_read_or_write_another_shippers_contract_nomination_or_ticket
        """
        field = create_field(api)
        well = create_well(api, field["id"])
        northline = create_shipper(api)
        southgate = create_second_shipper(api)
        c1 = create_active_contract(api, northline["id"], field["id"], contract_code="CN-1")
        c2 = create_active_contract(api, southgate["id"], field["id"], contract_code="CS-1")
        cv1 = contract_version(api, c1["id"])

        nomination = confirmed_nomination(
            api, c1["id"], northline["id"], gas_day="2026-08-02", nominated_volume_dth=80000
        )
        ticket = confirm_ticket(
            api, open_ticket(api, nomination["id"], well["id"], 80000)["id"], field["id"]
        )
        owner = make_shipper_headers(northline["id"])
        peer = make_shipper_headers(southgate["id"])

        _assert_all_refused(
            [
                ("peer reads the contract", api.get_contract(c1["id"], peer)),
                ("peer reads the ledger",
                 api.list_ledger_entries(c1["id"], peer, {"limit": 100})),
                ("peer reads the nomination one hop away",
                 api.get_nomination(nomination["id"], peer)),
                ("peer reads the ticket two hops away", api.get_ticket(ticket["id"], peer)),
                ("peer files against the contract with a stale token",
                 api.create_nomination(
                     F.nomination_payload(
                         c1["id"], cv1, gas_day="2026-08-03", nominated_volume_dth=50000),
                     peer)),
                ("peer resubmits a confirmed nomination",
                 api.submit_nomination(nomination["id"], peer, F.submit_nomination_payload(10000))),
            ],
            ERR_CONTRACT_NOT_OWNED,
        )

        # The peer's own book is readable and in good standing.
        own = assert_ok(api.get_contract(c2["id"], peer))
        assert_volume(own["inventory_balance_dth"], 0.000, "inventory_balance_dth")
        assert own["status"] == CONTRACT_ACTIVE

        # The owner sees everything the peer was refused.
        as_owner = assert_ok(api.get_nomination(nomination["id"], owner))
        assert_whole_dth(as_owner["confirmed_volume_dth"], 80000, "confirmed_volume_dth")
        assert assert_ok(api.get_ticket(ticket["id"], owner))["status"] == TICKET_CONFIRMED
        rows, meta = validate_paginated(api.list_ledger_entries(c1["id"], owner, {"limit": 100}))
        assert meta["total_count"] == 1, (
            f"The refusal hid a real ledger row, got {meta['total_count']}"
        )
        assert_ledger_entry(rows[0], entry_type=LEDGER_DAILY_IMBALANCE, gas_day="2026-08-02")

    def test_a_shippers_list_reads_are_narrowed_and_a_filter_cannot_widen_them(self, api):
        """The narrowing is silent rather than a 403, it is applied before total_count
        and before limit/offset, and an explicit shipper_id filter naming a competitor
        intersects the narrowing instead of replacing it -- so it yields an empty page,
        not the competitor's book.

        PRD §2.1: "The list endpoints are the deliberate exception: when a `Shipper`
        lists storage contracts, nominations or gas movement tickets, the endpoint never
        raises `ERR_CONTRACT_NOT_OWNED` and instead returns only the rows whose owning
        contract's `shipper_id` equals `X-User-ID`, with `total_count` counting only
        those rows."

        PRD §2.3: "The `total_count` reported in `meta` counts every row matching the
        endpoint's filters — including the ownership narrowing applied to a `Shipper` —
        as measured *before* `limit` and `offset` are applied, so a client can page to
        the end of a filtered set."

        Design: Corner/rbac/shipper_list_reads_are_narrowed_to_the_owner_and_a_filter_cannot_widen_them
        """
        field = create_field(api)
        create_well(api, field["id"])
        northline = create_shipper(api)
        southgate = create_second_shipper(api)
        # The clock advances between the drafts so `created_at ascending` is a strict
        # order rather than a tie the PRD leaves unresolved.
        c1 = create_active_contract(api, northline["id"], field["id"], contract_code="CN-1")
        set_clock(api, "2026-08-01T01:00:00Z")
        c2 = create_active_contract(
            api, northline["id"], field["id"], contract_code="CN-2",
            service_class=SERVICE_CLASS_INTERRUPTIBLE,
        )
        set_clock(api, "2026-08-01T02:00:00Z")
        c3 = create_active_contract(api, northline["id"], field["id"], contract_code="CN-3")
        set_clock(api, "2026-08-01T03:00:00Z")
        c4 = create_active_contract(api, southgate["id"], field["id"], contract_code="CS-1")
        file_nomination(
            api, c1["id"], northline["id"], gas_day="2026-08-02", nominated_volume_dth=50000
        )

        owner = make_shipper_headers(northline["id"])
        peer = make_shipper_headers(southgate["id"])
        page = {"limit": 100}

        mine, mine_meta = validate_paginated(api.list_contracts(owner, page))
        assert mine_meta["total_count"] == 3, (
            f"NORTHLINE holds three contracts, got {mine_meta['total_count']}"
        )
        assert [row["id"] for row in mine] == [c1["id"], c2["id"], c3["id"]], (
            "CS-1 is absent and the three rows arrive in created_at ascending order"
        )
        assert_created_at_ascending(mine)

        theirs, theirs_meta = validate_paginated(api.list_contracts(peer, page))
        assert theirs_meta["total_count"] == 1
        assert [row["id"] for row in theirs] == [c4["id"]]

        widened, widened_meta = validate_paginated(
            api.list_contracts(peer, {"shipper_id": northline["id"], "limit": 100})
        )
        assert widened_meta["total_count"] == 0, (
            "The filter intersects the narrowing instead of replacing it, got "
            f"{widened_meta['total_count']}"
        )
        assert widened == [], f"Expected an empty data array, got {len(widened)} rows"

        first_page, page_meta = validate_paginated(
            api.list_contracts(owner, {"limit": 2, "offset": 0})
        )
        assert [row["id"] for row in first_page] == [c1["id"], c2["id"]]
        assert page_meta["total_count"] == 3, (
            f"total_count is the narrowed 3, never the global 4, got {page_meta['total_count']}"
        )
        assert page_meta["has_more"] is True

        _, peer_nominations = validate_paginated(api.list_nominations(peer, page))
        assert peer_nominations["total_count"] == 0, (
            "NORTHLINE's draft nomination is invisible to SOUTHGATE, got "
            f"{peer_nominations['total_count']}"
        )
        _, owner_tickets = validate_paginated(api.list_tickets(owner, page))
        assert owner_tickets["total_count"] == 0, (
            f"No ticket has been metered yet, got {owner_tickets['total_count']}"
        )
        assert owner_tickets["has_more"] is False

        everything, all_meta = validate_paginated(api.list_contracts(SCHEDULING_COORDINATOR, page))
        assert all_meta["total_count"] == 4, (
            f"The narrowing is Shipper-specific, got {all_meta['total_count']}"
        )
        assert [row["id"] for row in everything] == [
            c1["id"], c2["id"], c3["id"], c4["id"]
        ]


class TestSegregationOfDuties:
    """One code guards two unrelated endpoints, and in both cases the identity
    compared is a user id stored on a different row rather than the caller's role."""

    def test_the_report_duty_split_is_per_report_and_covers_only_the_submit_step(self, api):
        """officer-a is barred from submitting the filing it prepared but not from
        recording the agency's disposition on that same filing, and the two officers swap
        roles freely on a second filing -- so the rule is keyed on the report's
        prepared_by_user_id, not on a fixed privileged id.

        PRD §3.9: "Submission requires a second officer. The acting `X-User-ID` is
        compared against the report's `prepared_by_user_id`, and a match is refused with
        `ERR_SOD_REMEDIATION_SELF_VERIFICATION` — the officer who prepared a filing may
        never be the one who files it."

        Design: Corner/rbac/segregation_of_duties_binds_only_the_prepare_to_submit_pair_on_a_report
        """
        f1 = create_field(api)
        create_well(api, f1["id"])
        f2 = create_field(api, name="Cavern Two", field_code="F-TWO")
        create_well(api, f2["id"], well_name="TWO-1")
        r1 = create_report(api, f1["id"], 250000)
        r2 = assert_created(
            api.create_regulatory_report(
                F.regulatory_report_payload(f2["id"], 250000), COMPLIANCE_OFFICER_B
            )
        )
        for prepared, officer in ((r1, OFFICER_A_ID), (r2, OFFICER_B_ID)):
            assert prepared["status"] == REPORT_DRAFT
            assert prepared["prepared_by_user_id"] == officer
            assert_volume(prepared["book_inventory_dth"], 250000.000, "book_inventory_dth")
            assert_volume(prepared["variance_dth"], 0.000, "variance_dth")
            assert_variance_pct(prepared["variance_pct"], 0.0000)
            assert prepared["open_finding_count"] == 0, (
                f"No remediation program exists, got {prepared['open_finding_count']}"
            )

        # The preparer may not file its own report, on either field.
        assert_error_envelope(
            api.submit_regulatory_report(r1["id"], COMPLIANCE_OFFICER),
            ERR_SOD_REMEDIATION_SELF_VERIFICATION,
        )
        refused = _read_report(api, f1["id"], r1["id"])
        assert refused["status"] == REPORT_DRAFT
        assert refused["submitted_by_user_id"] is None

        filed = assert_ok(api.submit_regulatory_report(r1["id"], COMPLIANCE_OFFICER_B))
        assert filed["status"] == REPORT_SUBMITTED
        assert filed["submitted_by_user_id"] == OFFICER_B_ID
        assert filed["prepared_by_user_id"] == OFFICER_A_ID, (
            "Filing does not rewrite the preparer"
        )

        assert_error_envelope(
            api.submit_regulatory_report(r2["id"], COMPLIANCE_OFFICER_B),
            ERR_SOD_REMEDIATION_SELF_VERIFICATION,
        )
        second_refusal = _read_report(api, f2["id"], r2["id"])
        assert second_refusal["status"] == REPORT_DRAFT
        assert second_refusal["submitted_by_user_id"] is None

        swapped = assert_ok(api.submit_regulatory_report(r2["id"], COMPLIANCE_OFFICER))
        assert swapped["status"] == REPORT_SUBMITTED
        assert swapped["submitted_by_user_id"] == OFFICER_A_ID, (
            "The duty split is per report, so officer-a may file what officer-b prepared"
        )

        # No third rule exists, so the preparer records the agency's disposition.
        disposed = assert_ok(
            api.record_agency_response(
                r1["id"],
                F.agency_response_payload(AGENCY_ACCEPTED, "Filed without exception"),
                COMPLIANCE_OFFICER,
            )
        )
        assert disposed["status"] == REPORT_ACCEPTED
        _, second_field = _field_reports(api, f2["id"], COMPLIANCE_OFFICER_B)
        assert second_field["total_count"] == 1, (
            f"F-TWO carries exactly one filing, got {second_field['total_count']}"
        )

    def test_the_same_code_refuses_the_self_verifier_on_a_program_and_on_a_report(self, api):
        """The remediation completion is measured against the triggering test's
        recorded_by_user_id and the report submission against prepared_by_user_id; both
        refusals leave the target row untouched, so the identical call from a second
        holder of the same role then succeeds.

        PRD §3.2: "Closing a remediation program is an act of independent verification,
        and the engineer who recorded the failing result may not perform it. The
        completing request carries `verification_notes`, and the acting `X-User-ID` is
        compared against the `recorded_by_user_id` of the triggering test; a match is
        refused with `ERR_SOD_REMEDIATION_SELF_VERIFICATION`."

        Design: Corner/validations/segregation_of_duties_refuses_the_self_verifier_on_both_endpoints
        """
        field = create_field(api)
        w1 = create_well(api, field["id"])
        create_well(api, field["id"], well_name="MINI-2")
        failure = fail_mit_on_well(api, w1["id"], record_at="2026-08-02T07:00:00Z")
        assert failure.test["recorded_by_user_id"] == ENGINEER_A_ID
        program = failure.program
        assert program["status"] == REMEDIATION_OPEN
        report = create_report(api, field["id"], 250000)
        assert report["prepared_by_user_id"] == OFFICER_A_ID

        assert_error_envelope(
            api.complete_remediation_program(
                program["id"],
                F.remediation_completion_payload(
                    "Casing repaired and re-tested by the same engineer"
                ),
                INTEGRITY_ENGINEER,
            ),
            ERR_SOD_REMEDIATION_SELF_VERIFICATION,
        )
        held = read_program(api, program["id"])
        assert held["status"] == REMEDIATION_OPEN
        assert held["completed_by_user_id"] is None

        assert_error_envelope(
            api.submit_regulatory_report(report["id"], COMPLIANCE_OFFICER),
            ERR_SOD_REMEDIATION_SELF_VERIFICATION,
        )
        still_draft = _read_report(api, field["id"], report["id"])
        assert still_draft["status"] == REPORT_DRAFT
        assert still_draft["submitted_by_user_id"] is None

        closed = assert_ok(
            api.complete_remediation_program(
                program["id"],
                F.remediation_completion_payload("Casing repair verified independently"),
                INTEGRITY_ENGINEER_B,
            )
        )
        assert closed["status"] == REMEDIATION_COMPLETED
        assert closed["completed_by_user_id"] == ENGINEER_B_ID
        assert_instant_equals(closed["completed_at"], "2026-08-02T07:00:00Z")

        filed = assert_ok(api.submit_regulatory_report(report["id"], COMPLIANCE_OFFICER_B))
        assert filed["status"] == REPORT_SUBMITTED
        assert filed["submitted_by_user_id"] == OFFICER_B_ID
        assert filed["prepared_by_user_id"] == OFFICER_A_ID

        cleared = read_well(api, w1["id"])
        assert cleared["integrity_state"] == INTEGRITY_REMEDIATED
        assert cleared["operational_state"] == WELL_SHUT_IN, (
            "Remediation proves the wellbore sound without returning it to service"
        )
        assert cleared["shut_in_reason"] is None


class TestTheLookupCatalogueIsPerResourceType:
    """Priority 4 maps the path resource type to its own code, and priority 5 reuses
    the same mapping for a body foreign key."""

    def test_the_eight_remaining_not_found_codes_are_each_reachable_on_a_populated_database(self, api):
        """Every table below holds at least one row, so each 404 is a genuine per-id
        miss rather than an empty-table artefact -- and a single shared ERR_NOT_FOUND, or
        ERR_STORAGE_FIELD_NOT_FOUND reused everywhere, satisfies none of them.

        PRD §2.11 rung 4: "The code follows the resource type: a storage field gives
        `ERR_STORAGE_FIELD_NOT_FOUND`, a wellbore `ERR_WELL_NOT_FOUND`, a mechanical
        integrity test `ERR_MIT_NOT_FOUND`, a remediation program
        `ERR_REMEDIATION_PROGRAM_NOT_FOUND`, a compressor unit
        `ERR_COMPRESSOR_UNIT_NOT_FOUND`, a compressor run `ERR_COMPRESSOR_RUN_NOT_FOUND`,
        a shipper `ERR_SHIPPER_NOT_FOUND`, a storage contract `ERR_CONTRACT_NOT_FOUND`, a
        nomination `ERR_NOMINATION_NOT_FOUND`, a gas movement ticket
        `ERR_TICKET_NOT_FOUND`, an emergency event `ERR_EMERGENCY_EVENT_NOT_FOUND`, and a
        regulatory report `ERR_REPORT_NOT_FOUND`. All are HTTP 404."

        Design: Corner/errors/eight_remaining_lookup_codes_are_each_reachable_and_not_found_is_never_generic
        """
        field = create_field(api)
        create_well(api, field["id"])
        create_unit(api, field["id"])
        create_shipper(api)

        expectations = [
            ("integrity test read", api.get_mit(SENTINEL_ID, INTEGRITY_ENGINEER),
             ERR_MIT_NOT_FOUND),
            ("remediation completion ahead of the duty split",
             api.complete_remediation_program(
                 SENTINEL_ID, F.remediation_completion_payload("n/a"), INTEGRITY_ENGINEER_B),
             ERR_REMEDIATION_PROGRAM_NOT_FOUND),
            ("run listing on an absent parent",
             api.list_unit_runs(SENTINEL_ID, FIELD_OPERATOR, {"limit": 100}),
             ERR_COMPRESSOR_UNIT_NOT_FOUND),
            ("run completion", api.complete_compressor_run(SENTINEL_ID, FIELD_OPERATOR),
             ERR_COMPRESSOR_RUN_NOT_FOUND),
            ("shipper read", api.get_shipper(SENTINEL_ID, SCHEDULING_COORDINATOR),
             ERR_SHIPPER_NOT_FOUND),
            ("ticket read", api.get_ticket(SENTINEL_ID, FIELD_OPERATOR), ERR_TICKET_NOT_FOUND),
            ("emergency advance ahead of the radius check",
             api.advance_emergency_event(
                 SENTINEL_ID, F.advance_payload(EMERGENCY_RESPONDING, "n/a"), FIELD_OPERATOR),
             ERR_EMERGENCY_EVENT_NOT_FOUND),
            ("report submission", api.submit_regulatory_report(SENTINEL_ID, COMPLIANCE_OFFICER_B),
             ERR_REPORT_NOT_FOUND),
            ("contract create on a body foreign key",
             api.create_contract(
                 F.contract_payload(SENTINEL_ID, field["id"]), SCHEDULING_COORDINATOR),
             ERR_SHIPPER_NOT_FOUND),
        ]
        for label, response, expected in expectations:
            body = assert_error_envelope(response, expected)
            assert response.json()["response_type"] == "error", (
                f"{label}: expected response_type error"
            )
            assert body["message"], f"{label}: a human-readable message is required"

        _, meta = validate_paginated(api.list_contracts(SCHEDULING_COORDINATOR, {"limit": 100}))
        assert meta["total_count"] == 0, (
            f"The refused create wrote no contract, got {meta['total_count']}"
        )

    def test_a_missing_or_unknown_identity_header_is_unauthenticated_before_everything_else(self, api):
        """All three triggers of the header gate answer 401 rather than 403, and each
        wins against a request that would also have failed on role, on body shape or on
        path lookup.

        PRD §2.1: "Each request must carry two headers: `X-User-ID`, naming the acting
        user, and `X-User-Role`, naming the capacity in which that user acts. If either
        header is absent, present but empty, or if `X-User-Role` names anything other
        than one of the five roles below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

        Design: Corner/errors/missing_x_user_headers_or_an_unknown_role_is_unauthenticated_before_any_other_check
        """
        field = create_field(api)
        fv1 = field_version(api, field["id"])

        _assert_all_refused(
            [
                ("no headers at all on the widest read in the API",
                 api.get_storage_field(field["id"], NO_AUTH_HEADERS)),
                ("a present role with an empty X-User-ID",
                 api.get_storage_field(field["id"], headers_empty_user_id(ROLE_FIELD_OPERATOR))),
                ("a role string that names no declared role",
                 api.get_storage_field(field["id"], headers_unknown_role())),
                ("no headers on a create whose body is missing four required fields",
                 api.create_well({"well_name": "GHOST-1"}, NO_AUTH_HEADERS)),
                ("no headers on a path id that resolves to nothing",
                 api.get_mit(SENTINEL_ID, NO_AUTH_HEADERS)),
                ("an empty id on an endpoint the named role may not call anyway",
                 api.set_season(
                     field["id"], F.season_payload(SEASON_WITHDRAWAL),
                     headers_empty_user_id(ROLE_SHIPPER))),
            ],
            ERR_UNAUTHENTICATED,
        )

        unchanged = read_field(api, field["id"])
        assert unchanged["season"] == SEASON_INJECTION
        assert unchanged["version"] == fv1, (
            f"No refusal mutated the reservoir, expected version {fv1}, "
            f"got {unchanged['version']}"
        )


class TestTerminalRowsAnswerTheirOwnInvalidStateCode:
    """Priority 7 is one rule with a per-entity code table, and a replayed transition
    on a terminal row is refused for state reasons with no side effect applied twice."""

    def test_replaying_three_completed_transitions_yields_three_distinct_state_codes(self, api):
        """The passed test, the completed program and the completed run each refuse the
        replay with their own code, even though every temporal precondition the same call
        also carries -- the clock past scheduled_end_at and past window_end_at -- is
        satisfied.

        PRD §2.11 rung 7: "**Transition legality.** The target record is in a state from
        which the requested transition is declared. Per-entity codes, all HTTP 409: a
        nomination gives `ERR_INVALID_NOMINATION_STATE`, a ticket
        `ERR_INVALID_TICKET_STATE`, a contract `ERR_INVALID_CONTRACT_STATE`, a mechanical
        integrity test `ERR_INVALID_MIT_STATE`, a remediation program
        `ERR_INVALID_REMEDIATION_STATE`, a compressor run `ERR_INVALID_RUN_STATE`, an
        emergency event `ERR_INVALID_EMERGENCY_STATE`, a regulatory report
        `ERR_INVALID_REPORT_STATE`, and a wellbore `ERR_INVALID_WELL_STATE`."

        Design: Corner/errors/three_action_endpoints_report_their_own_invalid_state_code_on_a_terminal_row
        """
        field = create_field(api)
        w1 = create_well(api, field["id"])
        w2 = create_well(api, field["id"], well_name="MINI-2")
        unit = create_unit(api, field["id"])
        run = book_run(
            api,
            unit["id"],
            window_start_at="2026-08-02T00:00:00Z",
            window_end_at="2026-08-02T04:00:00Z",
            allocated_horsepower=3000,
        )
        t1 = schedule_mit(api, w1["id"])
        set_clock(api, "2026-08-02T06:00:00Z")
        passed = record_mit(api, t1["id"], MIT_OUTCOME_PASS, 1200)
        failure = fail_mit_on_well(
            api, w2["id"],
            scheduled_start_at="2026-08-02T08:00:00Z",
            scheduled_end_at="2026-08-02T14:00:00Z",
            record_at="2026-08-02T14:00:00Z",
        )
        program = remediate_well(api, failure.program["id"], notes="Casing sleeve verified")
        assert program["status"] == REMEDIATION_COMPLETED
        completed = complete_run(api, run["id"])
        assert_money(completed["fuel_consumed_dth"], 110.40, "fuel_consumed_dth")

        assert_error_envelope(
            api.record_mit_result(
                t1["id"], F.mit_result_payload(MIT_OUTCOME_FAIL, 2900), INTEGRITY_ENGINEER
            ),
            ERR_INVALID_MIT_STATE,
        )
        assert_error_envelope(
            api.complete_remediation_program(
                program["id"], F.remediation_completion_payload("Second sign-off"),
                INTEGRITY_ENGINEER_B,
            ),
            ERR_INVALID_REMEDIATION_STATE,
        )
        assert_error_envelope(
            api.complete_compressor_run(run["id"], FIELD_OPERATOR), ERR_INVALID_RUN_STATE
        )

        # The replayed FAIL never ran: the passed wellbore is untouched and opened no
        # remediation program of its own.
        intact = read_well(api, w1["id"])
        assert intact["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert intact["shut_in_reason"] is None
        assert intact["operational_state"] == WELL_IN_SERVICE
        assert_instant_equals(intact["last_mit_passed_at"], passed["recorded_at"])
        _, program_meta = validate_paginated(
            api.list_remediation_programs(
                INTEGRITY_ENGINEER, {"well_id": w1["id"], "limit": 100}
            )
        )
        assert program_meta["total_count"] == 0, (
            f"No program was opened on the passed wellbore, got {program_meta['total_count']}"
        )
        reread = read_program(api, program["id"])
        assert reread["completed_by_user_id"] == ENGINEER_B_ID
        assert_instant_equals(reread["completed_at"], program["completed_at"])

        # The fuel was drawn exactly once.
        station = read_unit(api, unit["id"])
        assert_money(station["lifetime_fuel_dth"], 110.40, "lifetime_fuel_dth")
        assert station["scheduled_run_count"] == 0
        assert station["status"] == UNIT_AVAILABLE
        drawn = read_field(api, field["id"])
        assert_money(drawn["fuel_gas_used_dth"], 110.40, "fuel_gas_used_dth")
        assert_field_derived_block(drawn, working_gas=249889.600)
