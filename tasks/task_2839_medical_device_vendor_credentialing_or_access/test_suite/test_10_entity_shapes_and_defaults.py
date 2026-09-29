"""The shape of every persisted row: declared fields, declared defaults, declared refusals."""

from __future__ import annotations

from test_helpers import (
    AUTH_STATUS_REQUESTED,
    COMPLEXITY_COMPLEX,
    COMPLIANCE_SWEEP_FIELDS,
    CREDENTIAL_TYPE_BACKGROUND,
    DEFAULT_BADGE_GRACE_MINUTES,
    DEFAULT_BADGE_LEAD_MINUTES,
    ERR_APPEAL_NOT_FOUND,
    ERR_APPROVED_PRODUCT_NOT_FOUND,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_CHECK_IN_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LOANER_SET_NOT_FOUND,
    ERR_PIR_NOT_FOUND,
    ERR_SURGICAL_CASE_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_VENDOR_REP_NOT_FOUND,
    FACILITY_FIELDS,
    FEE_STATUS_NONE,
    LOANER_STATUS_EXPECTED,
    LOANER_STATUS_RELEASED,
    LOGICAL_CLOCK_DEFAULT_UTC,
    REQUESTED_ROLE_OBSERVATION,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    SWEEP_COUNTER_FIELDS,
    VENDOR_REP_FIELDS,
    COMPLIANCE_ADMIN,
    CREDENTIALING_OFFICER,
    OR_COORDINATOR,
    STERILE_PROCESSING_TECH,
    approved_product,
    assert_common_fields,
    assert_event_common_fields,
    assert_fields_present,
    assert_ids_in_order,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    assert_money_cents,
    assert_rep_birth_values,
    assert_total_count,
    compliance_sweep_payload,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credential_decision_payload,
    credential_payload,
    facility_payload,
    get_success_data,
    is_valid_uuid,
    list_rows_and_meta,
    loaner_set_payload,
    make_vendor_admin_headers,
    read_case,
    read_vendor_rep,
    request_authorization,
    surgical_case_payload,
    validate_error,
    validate_success,
    vendor_rep_payload,
)


class TestFacilityRegistrationShape:
    """A hospital site reads back exactly what the credentialing office registered."""

    def test_creation_echoes_every_declared_facility_field(self, api):
        """Registering Corner General returns 201 with all seven inputs and the four common properties.

        "A `Facility` is described by its display `name` and its short `code` ...
        Alongside the identity fields, the facility carries the four operational
        parameters that later formulas read." The site is minted by a creation
        endpoint, and "Creation endpoints — those that mint a brand-new resource
        — return **201**".

        Design: Corner/entities/facility_creation_returns_every_declared_field
        """
        response = api.create_facility(
            facility_payload(
                "CG-20",
                name="Corner General Hospital",
                spd_turnaround_hours=7,
                spd_bay_count=4,
                badge_lead_minutes=45,
                badge_grace_minutes=20,
                restricted_escort_required=False,
            ),
            COMPLIANCE_ADMIN,
        )
        facility = validate_success(response, 201)

        envelope = response.json()
        assert envelope["response_type"] == "object", (
            "a single registered site is one resource, not a list"
        )
        assert envelope["meta"]["api_request_id"].startswith("req_"), (
            "the envelope should carry a server-generated request identifier"
        )
        assert isinstance(envelope["meta"]["api_request_timestamp"], str), (
            "the envelope should carry a server-generated request timestamp"
        )

        assert_fields_present(facility, FACILITY_FIELDS)
        assert facility["name"] == "Corner General Hospital"
        assert facility["code"] == "CG-20"
        assert_integer_field(facility, "spd_turnaround_hours", 7)
        assert_integer_field(facility, "spd_bay_count", 4)
        assert_integer_field(facility, "badge_lead_minutes", 45)
        assert_integer_field(facility, "badge_grace_minutes", 20)
        assert facility["restricted_escort_required"] is False, (
            "the site was registered without the restricted-case escort rule"
        )

        # The identifier is a bare UUID with no type prefix, and both instants are
        # well-formed ISO 8601 UTC, exactly as the common properties require.
        assert_common_fields(facility)

    def test_registration_without_a_site_code_is_refused(self, api):
        """Omitting the required short code refuses the registration rather than defaulting it.

        "Request well-formedness — every required body field is present, JSON
        types are correct, enum values fall inside their declared domain,
        integers fall inside their declared ranges ... otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/facility_creation_missing_required_code_rejected
        """
        response = api.create_facility(
            {
                "name": "Nameless Code Hospital",
                "spd_turnaround_hours": 6,
                "spd_bay_count": 2,
            },
            CREDENTIALING_OFFICER,
        )

        validate_error(response, ERR_INVALID_REQUEST)

    def test_omitted_badge_offsets_take_the_declared_site_defaults(self, api):
        """A site registered with only its identity and turnaround gets 60, 30 and true.

        "`badge_lead_minutes` is how many minutes before a case's scheduled start
        a kiosk badge becomes valid, defaulting to 60 when the caller omits it",
        "`badge_grace_minutes` is how many minutes after a case's scheduled end a
        badge stops being valid, defaulting to 30", and "the boolean
        `restricted_escort_required` defaults to true".

        Design: Corner/entities/facility_optional_inputs_take_declared_defaults
        """
        facility = get_success_data(
            api.create_facility(
                facility_payload(
                    "DF-21",
                    name="Defaults Memorial Hospital",
                    spd_turnaround_hours=5,
                    spd_bay_count=2,
                ),
                CREDENTIALING_OFFICER,
            ),
            201,
        )

        assert_integer_field(facility, "badge_lead_minutes", DEFAULT_BADGE_LEAD_MINUTES)
        assert_integer_field(
            facility, "badge_grace_minutes", DEFAULT_BADGE_GRACE_MINUTES
        )
        assert facility["restricted_escort_required"] is True, (
            "a site demands an escort on restricted cases until it says otherwise"
        )
        assert_integer_field(facility, "spd_turnaround_hours", 5)
        assert_integer_field(facility, "spd_bay_count", 2)


class TestVendorRepresentativeRoster:
    """A newly registered representative is inert, and the roster is browsable by vendor."""

    def test_a_fresh_representative_reads_back_with_every_birth_value(self, api):
        """Rita Alvarez reads back with her stored details and every declared starting value.

        "A freshly registered representative is inert: `access_status` is
        `PENDING_CREDENTIALING`, `credential_posture` is `INCOMPLETE`,
        `ever_credentialed` is false, `open_authorization_count` is 0,
        `suspension_reason` is `NONE`, and the three audit instants
        `revoked_by_user_id`, `revoked_at_utc` and `reinstated_at_utc` are all
        absent."

        Design: Corner/entities/vendor_rep_retrieval_returns_stored_row_with_defaults
        """
        vendor = create_vendor(api, "CORNV", legal_name="Cornerview Medical Inc")
        created = get_success_data(
            api.create_vendor_rep(
                vendor_rep_payload(
                    vendor["id"],
                    "Rita Alvarez",
                    email="rita.alvarez@cornerview.example",
                ),
                make_vendor_admin_headers(vendor["id"]),
            ),
            201,
        )

        stored = read_vendor_rep(api, created["id"])

        assert_fields_present(stored, VENDOR_REP_FIELDS)
        assert stored["vendor_id"] == vendor["id"], (
            "the employing vendor is written once and is immutable thereafter"
        )
        assert stored["full_name"] == "Rita Alvarez"
        assert stored["email"] == "rita.alvarez@cornerview.example"
        assert_rep_birth_values(stored)
        assert_common_fields(stored)

    def test_the_roster_narrows_by_employing_vendor_and_pages_one_row_at_a_time(self, api):
        """Two reps at Lista and one at Listb: the vendor filter and a limit of one both bite.

        "A representative listing may be narrowed by employing vendor through
        `vendor_id`", and "`limit` caps the number of rows returned; when the
        caller omits it the server uses 10 ... `offset` is the number of rows to
        skip before the page begins; when omitted it is 0."

        Design: Corner/entities/vendor_rep_listing_filters_by_vendor_and_paginates
        """
        lista = create_vendor(api, "LISTA", legal_name="Lista Devices SA")
        listb = create_vendor(api, "LISTB", legal_name="Listb Surgical SA")
        alpha = create_vendor_rep(api, lista["id"], "Rep Alpha", email="alpha@lista.example")
        beta = create_vendor_rep(api, lista["id"], "Rep Beta", email="beta@lista.example")
        gamma = create_vendor_rep(api, listb["id"], "Rep Gamma", email="gamma@listb.example")

        first_page, first_meta = list_rows_and_meta(
            api.list_vendor_reps(
                COMPLIANCE_ADMIN, {"vendor_id": lista["id"], "limit": 1, "offset": 0}
            )
        )
        assert_total_count(first_meta, 2)
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True, "a second Lista representative follows"
        assert_ids_in_order(first_page, [alpha["id"]])

        second_page, second_meta = list_rows_and_meta(
            api.list_vendor_reps(
                COMPLIANCE_ADMIN, {"vendor_id": lista["id"], "limit": 1, "offset": 1}
            )
        )
        assert_total_count(second_meta, 2)
        assert second_meta["offset"] == 1
        assert second_meta["has_more"] is False, "the Lista roster ends here"
        assert_ids_in_order(second_page, [beta["id"]])

        listed_ids = [row["id"] for row in first_page + second_page]
        assert gamma["id"] not in listed_ids, (
            "the Listb representative belongs to another company's roster"
        )

        everyone, everyone_meta = list_rows_and_meta(
            api.list_vendor_reps(COMPLIANCE_ADMIN)
        )
        assert_total_count(everyone_meta, 3)
        assert everyone_meta["limit"] == 10
        assert everyone_meta["offset"] == 0
        assert len(everyone) == 3, "all three representatives fit inside the default page"


class TestUnknownIdentifiersAndBodyForeignKeys:
    """Every addressable row answers an unknown identifier with its own named refusal."""

    def test_each_addressable_entity_reports_its_own_not_found(self, api):
        """Twelve reads against an empty estate return twelve distinct 404 identifiers.

        "Path existence — every resource named in the path exists, validated left
        to right, else the corresponding 404: `ERR_FACILITY_NOT_FOUND`,
        `ERR_VENDOR_NOT_FOUND`, `ERR_VENDOR_REP_NOT_FOUND`,
        `ERR_CREDENTIAL_NOT_FOUND`, `ERR_SURGICAL_CASE_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_PIR_NOT_FOUND`,
        `ERR_APPROVED_PRODUCT_NOT_FOUND`, `ERR_LOANER_SET_NOT_FOUND`,
        `ERR_CHECK_IN_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` or
        `ERR_APPEAL_NOT_FOUND`."

        Design: Corner/entities/unknown_uuid_not_found_for_every_addressable_entity
        """
        probes = [
            (
                api.get_facility("00000000-0000-4000-8000-000000000001", COMPLIANCE_ADMIN),
                ERR_FACILITY_NOT_FOUND,
            ),
            (
                api.get_vendor("00000000-0000-4000-8000-000000000002", COMPLIANCE_ADMIN),
                ERR_VENDOR_NOT_FOUND,
            ),
            (
                api.get_vendor_rep("00000000-0000-4000-8000-000000000003", COMPLIANCE_ADMIN),
                ERR_VENDOR_REP_NOT_FOUND,
            ),
            (
                api.decide_credential(
                    "00000000-0000-4000-8000-000000000004",
                    credential_decision_payload("VERIFY"),
                    CREDENTIALING_OFFICER,
                ),
                ERR_CREDENTIAL_NOT_FOUND,
            ),
            (
                api.get_surgical_case(
                    "00000000-0000-4000-8000-000000000005", COMPLIANCE_ADMIN
                ),
                ERR_SURGICAL_CASE_NOT_FOUND,
            ),
            (
                api.get_authorization(
                    "00000000-0000-4000-8000-000000000006", COMPLIANCE_ADMIN
                ),
                ERR_AUTHORIZATION_NOT_FOUND,
            ),
            (
                api.get_pir("00000000-0000-4000-8000-000000000007", COMPLIANCE_ADMIN),
                ERR_PIR_NOT_FOUND,
            ),
            (
                api.get_approved_product(
                    "00000000-0000-4000-8000-000000000008", COMPLIANCE_ADMIN
                ),
                ERR_APPROVED_PRODUCT_NOT_FOUND,
            ),
            (
                api.get_loaner_set("00000000-0000-4000-8000-000000000009", COMPLIANCE_ADMIN),
                ERR_LOANER_SET_NOT_FOUND,
            ),
            (
                api.get_check_in("00000000-0000-4000-8000-00000000000a", COMPLIANCE_ADMIN),
                ERR_CHECK_IN_NOT_FOUND,
            ),
            (
                api.get_incident("00000000-0000-4000-8000-00000000000b", COMPLIANCE_ADMIN),
                ERR_INCIDENT_NOT_FOUND,
            ),
            (
                api.get_access_appeal(
                    "00000000-0000-4000-8000-00000000000c", COMPLIANCE_ADMIN
                ),
                ERR_APPEAL_NOT_FOUND,
            ),
        ]

        reported = []
        for response, expected_error_id in probes:
            refusal = validate_error(response, expected_error_id)
            assert sorted(refusal.keys()) == ["error_id", "message"], (
                "a refusal carries only the machine-readable identifier and its message"
            )
            reported.append(refusal["error_id"])

        assert len(set(reported)) == 12, (
            "each entity names itself in its own refusal rather than sharing a generic one"
        )

    def test_a_credential_naming_an_unknown_representative_is_not_found(self, api):
        """An attestation for a representative that does not exist is a 404, not a 400.

        "Body foreign-key existence — every foreign key in the request body
        references an existing row, validated in the endpoint's declared field
        order, else `ERR_FACILITY_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
        `ERR_VENDOR_REP_NOT_FOUND` ... as appropriate."

        Design: Corner/entities/credential_body_fk_unknown_rep_returns_not_found
        """
        response = api.create_credential(
            credential_payload(
                "00000000-0000-4000-8000-0000000000d1",
                CREDENTIAL_TYPE_BACKGROUND,
                issued_at_utc="2026-07-01T00:00:00Z",
                expires_at_utc="2027-07-01T00:00:00Z",
                document_reference="BGC-GHOST-01",
            ),
            CREDENTIALING_OFFICER,
        )

        validate_error(response, ERR_VENDOR_REP_NOT_FOUND)


class TestServerOwnedFieldsAndImmutableRecords:
    """What the server computes, the client cannot dictate; what it logs, nobody can edit."""

    def test_registration_ignores_client_supplied_deadline_status_and_fee(self, api):
        """A tray set sent with its own deadline, status, fee and id gets the server's values instead.

        "`pinned_deadline_utc` is computed once, at registration, from the case's
        `original_scheduled_start_utc`" and "The set lands in `EXPECTED` with
        `fee_status` at `NONE` and `assessed_late_fee_cents` at 0", while the
        identifier is "a server-minted UUID ... Clients never supply it."

        Design: Corner/entities/loaner_set_computed_and_system_fields_input_ignored
        """
        facility = create_facility(
            api,
            "CI-22",
            name="Computed Inputs Hospital",
            spd_turnaround_hours=6,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "COMPI", legal_name="Computa Instruments Ltd")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "BS-100",
            50000,
            is_implant=False,
            product_name="Basic Scope Tray",
            manufacturer="Computa",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-12001",
            "2026-10-01T08:00:00Z",
            "2026-10-01T10:00:00Z",
            procedure_name="Diagnostic Scope",
        )

        payload = loaner_set_payload(
            case["id"],
            product["id"],
            5,
            read_case(api, case["id"])["version"],
            COMPLEXITY_COMPLEX,
        )
        payload.update(
            {
                "pinned_deadline_utc": "2020-01-01T00:00:00Z",
                "status": LOANER_STATUS_RELEASED,
                "assessed_late_fee_cents": 999999,
                "id": "00000000-0000-4000-8000-0000000000ff",
            }
        )
        loaner = get_success_data(
            api.create_loaner_set(payload, STERILE_PROCESSING_TECH), 201
        )

        # Six turnaround hours plus six for a COMPLEX reprocessing plus one tray
        # surcharge for a five-tray set is a thirteen-hour lead off an 08:00 start.
        assert_instant_equals(
            loaner["pinned_deadline_utc"],
            "2026-09-30T19:00:00Z",
            "pinned_deadline_utc",
        )
        assert_instant_equals(
            loaner["required_delivery_deadline_utc"],
            "2026-09-30T19:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert loaner["status"] == LOANER_STATUS_EXPECTED, (
            "a tray set that nobody has received yet is still expected at the dock"
        )
        assert_money_cents(loaner, "assessed_late_fee_cents", 0)
        assert loaner["fee_status"] == FEE_STATUS_NONE
        assert_instant_is_none(loaner, "delivered_at_utc")
        assert loaner["id"] != "00000000-0000-4000-8000-0000000000ff", (
            "the tray set takes a server-minted identifier"
        )
        assert is_valid_uuid(loaner["id"])
        assert_instant_equals(
            loaner["spd_occupation_start_utc"],
            "2026-09-30T19:00:00Z",
            "spd_occupation_start_utc",
        )
        assert_instant_equals(
            loaner["spd_occupation_end_utc"],
            "2026-10-01T08:00:00Z",
            "spd_occupation_end_utc",
        )

    def test_a_sweep_record_carries_no_version_and_no_updated_at(self, api):
        """The first sweep over an empty estate opens epoch 1 and logs only id and created_at.

        "The `ComplianceSweep` record is the single exception: it is an immutable
        event log entry, so it carries only `id` and `created_at`. Both
        `updated_at` and `version` are absent from a sweep record entirely — a
        client must not expect either field there."

        Design: Corner/entities/compliance_sweep_is_immutable_and_carries_no_version
        """
        sweep = validate_success(
            api.create_compliance_sweep(compliance_sweep_payload(), COMPLIANCE_ADMIN), 201
        )

        assert_event_common_fields(sweep)
        assert_fields_present(sweep, COMPLIANCE_SWEEP_FIELDS)
        assert_integer_field(sweep, "epoch_number", 1)
        assert_integer_field(sweep, "previous_epoch_number", 0)
        assert_instant_equals(
            sweep["swept_at_utc"], LOGICAL_CLOCK_DEFAULT_UTC, "swept_at_utc"
        )
        for counter in SWEEP_COUNTER_FIELDS:
            assert_integer_field(sweep, counter, 0)


class TestCaseEnumsAndTheAuthorizationJunction:
    """The schedule refuses an unknown restriction level, and the junction reads both ways."""

    def test_an_unknown_restriction_level_is_refused_and_schedules_nothing(self, api):
        """A case asking for a third restriction level is refused and leaves the schedule empty.

        "`restriction_level` is either `STANDARD` or `RESTRICTED` and defaults to
        `STANDARD`", and a request is well-formed only when "enum values fall
        inside their declared domain ... otherwise `ERR_INVALID_REQUEST` (400)".

        Design: Corner/entities/surgical_case_invalid_restriction_level_enum_rejected
        """
        facility = create_facility(
            api,
            "EN-23",
            name="Enumville Surgical",
            spd_turnaround_hours=6,
            spd_bay_count=2,
        )

        response = api.create_surgical_case(
            surgical_case_payload(
                facility["id"],
                "CASE-12101",
                "2026-10-02T08:00:00Z",
                "2026-10-02T10:00:00Z",
                procedure_name="Enum Probe",
                restriction_level="TOP_SECRET",
            ),
            OR_COORDINATOR,
        )

        validate_error(response, ERR_INVALID_REQUEST)

        scheduled, meta = list_rows_and_meta(
            api.list_surgical_cases(COMPLIANCE_ADMIN, {"facility_id": facility["id"]})
        )
        assert_total_count(meta, 0)
        assert scheduled == [], (
            "the refused request stored no case on the Enumville schedule"
        )

    def test_authorizations_are_reachable_from_the_case_and_from_the_representative(self, api):
        """Two reps on one case and one of them on a second case read back from either side.

        "A representative reaches an operating room only through a
        `CaseRepAuthorization`, the junction that resolves the many-to-many
        relationship between cases and representatives", and "Authorization
        listings may be narrowed by `surgical_case_id`, by `vendor_rep_id` and by
        `status`."

        Design: Corner/entities/authorization_junction_links_case_and_rep_both_ways
        """
        facility = create_facility(
            api,
            "JN-24",
            name="Junction Point Hospital",
            spd_turnaround_hours=6,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "JUNCT", legal_name="Junction Surgical Group")
        rep_one = create_vendor_rep(
            api, vendor["id"], "Junction Rep One", email="one@junction.example"
        )
        rep_two = create_vendor_rep(
            api, vendor["id"], "Junction Rep Two", email="two@junction.example"
        )
        case_one = create_case(
            api,
            facility["id"],
            "CASE-12201",
            "2026-10-03T08:00:00Z",
            "2026-10-03T10:00:00Z",
            procedure_name="Junction Case One",
        )
        case_two = create_case(
            api,
            facility["id"],
            "CASE-12202",
            "2026-10-04T08:00:00Z",
            "2026-10-04T10:00:00Z",
            procedure_name="Junction Case Two",
        )

        first_on_first = request_authorization(
            api, case_one["id"], rep_one["id"], REQUESTED_ROLE_TECHNICAL_SUPPORT
        )
        second_on_first = request_authorization(
            api, case_one["id"], rep_two["id"], REQUESTED_ROLE_OBSERVATION
        )
        first_on_second = request_authorization(
            api, case_two["id"], rep_one["id"], REQUESTED_ROLE_TECHNICAL_SUPPORT
        )

        case_side, case_meta = list_rows_and_meta(
            api.list_authorizations(COMPLIANCE_ADMIN, {"surgical_case_id": case_one["id"]})
        )
        assert_total_count(case_meta, 2)
        assert_ids_in_order(case_side, [first_on_first["id"], second_on_first["id"]])

        rep_side, rep_meta = list_rows_and_meta(
            api.list_authorizations(COMPLIANCE_ADMIN, {"vendor_rep_id": rep_one["id"]})
        )
        assert_total_count(rep_meta, 2)
        assert_ids_in_order(rep_side, [first_on_first["id"], first_on_second["id"]])

        for row in case_side + rep_side:
            assert row["status"] == AUTH_STATUS_REQUESTED, (
                "nobody has decided any of these requests yet"
            )
            assert row["epoch_number"] is None, (
                "the quota epoch is stamped only when an approval consumes a slot"
            )

        assert_integer_field(read_case(api, case_one["id"]), "approved_rep_count", 0)
