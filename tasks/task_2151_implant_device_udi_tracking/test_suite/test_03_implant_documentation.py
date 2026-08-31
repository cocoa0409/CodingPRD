"""Documenting the implant: the validation ladder, transcription and linkage."""

from test_helpers import (
    ApiErrorId,
    CC,
    CO,
    IL,
    MISSING_UUID,
    RT,
    add_unit,
    case_version,
    create_case,
    create_catalog_item,
    create_charge,
    create_field_action,
    create_lot,
    create_patient,
    create_vendor,
    document_implant,
    get_case,
    get_charge,
    get_lot,
    get_patient,
    get_record,
    get_unit,
    publish_field_action,
    release_lot,
    reserve_unit,
    set_clock,
    setup_documented_implant,
    setup_in_progress_case,
    setup_scheduled_case,
    setup_stock,
    start_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def _implant_payload(unit, case_id, **overrides):
    payload = {
        "device_unit_id": unit["id"],
        "udi_di": unit["udi_di_snapshot"],
        "udi_pi_serial": unit["udi_serial"],
        "anatomic_site": "FEMUR_PROXIMAL",
        "laterality": "LEFT",
        "expected_case_version": case_version(case_id),
    }
    payload.update(overrides)
    return payload


class TestLadderPrecedenceOnDocumentation:
    def test_cancelled_case_outranks_a_recalled_unit(self, api):
        """PRD §2.6: "Every request runs through one ordered ladder of checks.
        **The first check that fails determines the entire response; no later check
        runs, and no side effect belonging to a later stage is applied.**"
        PRD §2.6: "Path-target state — the resource named by the path is in a state
        from which the requested transition is declared. Cross-referenced entities
        named in the *body* are not judged here; they are judged at steps 15
        through 18. Failure: `ERR_INVALID_CASE_STATE`, `ERR_INVALID_UNIT_STATE`,
        `ERR_INVALID_RECORD_STATE`, `ERR_INVALID_INVOICE_STATE` or
        `ERR_INVALID_LIFECYCLE_STATE` (409)."
        PRD §2.6: "Recall safety — the referenced device unit is not in
        `RECALL_HOLD` and its lot is not `RECALLED`. Applies to reservation and to
        implant documentation. Failure: `ERR_UNIT_RECALLED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/case_state_precedes_unit_recall_on_implant_documentation
        """
        world = setup_stock((400_000,))
        action = create_field_action(
            world["vendor"]["id"],
            world["catalog_item"]["id"],
            action_code="FA-2026-002",
            action_class="CLASS_II",
            scope_type="CATALOG",
        )
        publish_field_action(action["id"])
        assert get_unit(world["units"][0]["id"])["custody_state"] == "RECALL_HOLD"

        case = setup_scheduled_case()["case"]
        cancelled = validate_success(api.cancel_case(case["id"], CC), 200)
        assert cancelled["status"] == "CANCELLED"

        unit = get_unit(world["units"][0]["id"])
        response = api.create_implant_record(
            case["id"],
            _implant_payload(unit, case["id"], expected_case_version=cancelled["version"]),
            CC,
        )
        error = validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE, 409)
        assert error["error_id"] != ApiErrorId.ERR_UNIT_RECALLED.value

    def test_no_side_effect_of_a_later_ladder_stage_survives_the_case_state_rejection(
        self, api
    ):
        """PRD §2.6: "Every request runs through one ordered ladder of checks.
        **The first check that fails determines the entire response; no later check
        runs, and no side effect belonging to a later stage is applied.**"
        PRD §3.5: "Documentation requires the case to be `IN_PROGRESS`; a case still
        `SCHEDULED`, or already closed, is rejected with `ERR_INVALID_CASE_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/case_state_precedes_unit_recall_on_implant_documentation
        """
        world = setup_stock((400_000,))
        action = create_field_action(
            world["vendor"]["id"],
            world["catalog_item"]["id"],
            action_code="FA-2026-002",
            action_class="CLASS_II",
            scope_type="CATALOG",
        )
        publish_field_action(action["id"])
        case = setup_scheduled_case()["case"]
        cancelled = validate_success(api.cancel_case(case["id"], CC), 200)

        unit = get_unit(world["units"][0]["id"])
        validate_error(
            api.create_implant_record(
                case["id"],
                _implant_payload(
                    unit, case["id"], expected_case_version=cancelled["version"]
                ),
                CC,
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE,
            409,
        )

        assert get_case(case["id"])["status"] == "CANCELLED"
        assert get_unit(world["units"][0]["id"])["custody_state"] == "RECALL_HOLD"
        _, meta = validate_paginated(
            api.list_implant_records(CC, {"surgical_case_id": case["id"]})
        )
        assert meta["total_count"] == 0

    def test_recall_safety_outranks_the_referenced_unit_custody_check(self, api):
        """PRD §2.6: "Recall safety — the referenced device unit is not in
        `RECALL_HOLD` and its lot is not `RECALLED`. Applies to reservation and to
        implant documentation. Failure: `ERR_UNIT_RECALLED` (422)."
        PRD §2.6: "Referenced unit custody — the device unit named in the body is in
        an allowed custody state: `AVAILABLE` for a reservation, `AVAILABLE` or
        `RESERVED` for implant documentation, `IMPLANTED` for an explant. Failure:
        `ERR_INVALID_UNIT_STATE` (409)."
        PRD §3.5: "Both branches additionally require the lot to be `AVAILABLE` — a
        still-quarantined lot reports `ERR_LOT_NOT_RELEASED` first — and the lot's
        expiry instant to be strictly after the logical clock, failing which the
        answer is `ERR_UNIT_EXPIRED`; a unit under a field action reports
        `ERR_UNIT_RECALLED` ahead of both."

        Design: Difficulty/priority_pair_validation_conflict/unit_recall_safety_precedes_referential_unit_state_on_implant
        """
        world = setup_stock((400_000,))
        case = setup_in_progress_case()["case"]
        action = create_field_action(
            world["vendor"]["id"],
            world["catalog_item"]["id"],
            action_code="FA-2026-003",
            action_class="CLASS_II",
            scope_type="CATALOG",
        )
        publish_field_action(action["id"])

        unit = get_unit(world["units"][0]["id"])
        assert unit["custody_state"] == "RECALL_HOLD"

        error = validate_error(
            api.create_implant_record(case["id"], _implant_payload(unit, case["id"]), CC),
            ApiErrorId.ERR_UNIT_RECALLED,
            422,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_UNIT_STATE.value

        refreshed_case = get_case(case["id"])
        assert refreshed_case["status"] == "IN_PROGRESS"
        assert refreshed_case["implant_record_count"] == 0
        assert get_unit(unit["id"])["custody_state"] == "RECALL_HOLD"

    def test_a_unit_reserved_to_another_case_fails_the_custody_check(self, api):
        """PRD §3.5: "The ordinary path is `RESERVED → IMPLANTED`, and it requires
        that the unit's `reserved_case_id` is exactly this case. The emergency path
        is `AVAILABLE → IMPLANTED`, covering unreserved stock grabbed off the shelf
        mid-procedure, and it requires that `reserved_case_id` is null. A unit that
        is `RESERVED` to some *other* case satisfies neither branch and is rejected
        with `ERR_INVALID_UNIT_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/unit_recall_safety_precedes_referential_unit_state_on_implant
        """
        world = setup_stock((400_000,))
        patient_one = create_patient(mrn="MRN-1001", display_name="Pat One")
        patient_two = create_patient(mrn="MRN-1002", display_name="Pat Two")
        case_one = create_case(
            patient_one["id"],
            case_number="CASE-1",
            or_room_code="OR-3",
            scheduled_start_utc="2026-09-10T08:00:00Z",
            scheduled_end_utc="2026-09-10T10:00:00Z",
        )
        case_two = create_case(
            patient_two["id"],
            case_number="CASE-2",
            or_room_code="OR-4",
            scheduled_start_utc="2026-09-12T08:00:00Z",
            scheduled_end_utc="2026-09-12T10:00:00Z",
        )
        reserve_unit(case_two["id"], world["units"][0]["id"])
        start_case(case_one["id"])

        unit = get_unit(world["units"][0]["id"])
        assert unit["reserved_case_id"] == case_two["id"]

        validate_error(
            api.create_implant_record(
                case_one["id"], _implant_payload(unit, case_one["id"]), CC
            ),
            ApiErrorId.ERR_INVALID_UNIT_STATE,
            409,
        )
        assert get_unit(unit["id"])["custody_state"] == "RESERVED"
        assert get_case(case_one["id"])["implant_record_count"] == 0


class TestDocumentationGuards:
    def test_udi_transcription_and_patient_link_are_both_enforced(self, api):
        """PRD §3.5: "The transcription is checked against the physical unit:
        `udi_di` must equal the unit's frozen `udi_di_snapshot` and `udi_pi_serial`
        must equal its `udi_serial`, and any mismatch is rejected with
        `ERR_UDI_INCOMPLETE` — this is the guard against a nurse reading the wrong
        package."
        PRD §3.5: "An optional `patient_id` may be supplied for belt-and-braces
        confirmation; when it is omitted the patient is copied from the case, and
        when it is supplied it must equal the case's `patient_id` or the request is
        rejected with `ERR_PATIENT_LINK_MISMATCH`."

        Design: Corner/validations/udi_transcription_and_patient_link_guards_on_implant_documentation
        """
        world = setup_stock((400_000,))
        patient_one = create_patient(mrn="MRN-1001", display_name="Pat One")
        patient_two = create_patient(mrn="MRN-1002", display_name="Pat Two")
        case = create_case(patient_one["id"])
        start_case(case["id"])
        unit = world["units"][0]

        validate_error(
            api.create_implant_record(
                case["id"],
                _implant_payload(unit, case["id"], udi_pi_serial="SN-9999"),
                CC,
            ),
            ApiErrorId.ERR_UDI_INCOMPLETE,
            422,
        )
        validate_error(
            api.create_implant_record(
                case["id"],
                _implant_payload(unit, case["id"], patient_id=patient_two["id"]),
                CC,
            ),
            ApiErrorId.ERR_PATIENT_LINK_MISMATCH,
            422,
        )

        assert get_case(case["id"])["implant_record_count"] == 0
        assert get_unit(unit["id"])["custody_state"] == "AVAILABLE"

    def test_quarantined_lot_and_expired_lot_each_report_their_own_reason(self, api):
        """PRD §3.5: "Both branches additionally require the lot to be `AVAILABLE`
        — a still-quarantined lot reports `ERR_LOT_NOT_RELEASED` first — and the
        lot's expiry instant to be strictly after the logical clock, failing which
        the answer is `ERR_UNIT_EXPIRED`; a unit under a field action reports
        `ERR_UNIT_RECALLED` ahead of both."
        PRD §3.2: "That calendar date is not itself an instant, and the distinction
        matters for every expiry comparison in this document: **the expiry instant
        of a lot is its `expiration_date` at 23:59:59.999Z**, so a lot dated for
        today is still good for the whole of today."

        Design: Corner/validations/quarantined_lot_and_expired_lot_guards_on_implant_documentation
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        catalog_item = create_catalog_item(vendor["id"])

        quarantined_lot = create_lot(
            catalog_item["id"], lot_number="L-QUAR", expiration_date="2027-06-30"
        )
        quarantined_unit = add_unit(quarantined_lot["id"], "SN-Q1", 400_000)

        short_lot = create_lot(
            catalog_item["id"], lot_number="L-SHORT", expiration_date="2026-09-15"
        )
        short_unit = add_unit(short_lot["id"], "SN-S1", 400_000)
        release_lot(short_lot["id"])

        patient = create_patient()
        case = create_case(
            patient["id"],
            scheduled_start_utc="2026-09-16T08:00:00Z",
            scheduled_end_utc="2026-09-16T10:00:00Z",
        )
        start_case(case["id"])

        # Advance past the short lot's expiry instant without running a checkpoint.
        set_clock("2026-09-16T00:00:00Z")

        validate_error(
            api.create_implant_record(
                case["id"], _implant_payload(quarantined_unit, case["id"]), CC
            ),
            ApiErrorId.ERR_LOT_NOT_RELEASED,
            409,
        )
        validate_error(
            api.create_implant_record(
                case["id"], _implant_payload(get_unit(short_unit["id"]), case["id"]), CC
            ),
            ApiErrorId.ERR_UNIT_EXPIRED,
            422,
        )

        assert get_lot(short_lot["id"])["status"] == "AVAILABLE"
        assert get_unit(short_unit["id"])["custody_state"] == "AVAILABLE"
        assert get_case(case["id"])["implant_record_count"] == 0

    def test_a_missing_body_foreign_key_outranks_the_case_state_check(self, api):
        """PRD §2.6: "Body foreign-key existence, checked in the order the fields
        are declared in the endpoint's input list, and for the `device_unit_ids`
        array in array order. Failure: the matching not-found code (404)."
        PRD §2.6: "Path-target state — the resource named by the path is in a state
        from which the requested transition is declared."

        Design: Corner/validations/body_foreign_key_existence_is_checked_before_target_state
        """
        set_clock("2026-09-01T00:00:00Z")
        patient = create_patient()
        case = create_case(patient["id"])
        cancelled = validate_success(api.cancel_case(case["id"], CC), 200)

        error = validate_error(
            api.create_implant_record(
                case["id"],
                {
                    "device_unit_id": MISSING_UUID,
                    "udi_di": "00812345678905",
                    "udi_pi_serial": "SN-0001",
                    "anatomic_site": "FEMUR_PROXIMAL",
                    "laterality": "LEFT",
                    "expected_case_version": cancelled["version"],
                },
                CC,
            ),
            ApiErrorId.ERR_DEVICE_UNIT_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_CASE_STATE.value


class TestOptimisticConcurrencyOnTheCase:
    def test_second_documentation_with_a_stale_case_version_is_rejected(self, api):
        """PRD §2.7: "A request to `POST /udi/surgical-cases/{case_id}/implant-records`
        must carry `expected_case_version` holding the client's last observed
        `version` of that surgical case."
        PRD §2.7: "If the value differs from the case's current `version`, the
        request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."
        PRD §3.5: "Finally the lot's `on_hand_qty` and `consumed_qty`, the catalog
        item's `on_hand_available_qty`, the patient's `implant_count`, the case's
        `implant_record_count` and the case's `readiness_status` are all
        re-derived, and the case's `version` is advanced by one — which means a
        client documenting a second implant on the same case must first re-read the
        case to obtain a fresh `expected_case_version`."

        Design: Corner/cross_cutting_layers/occ_stale_case_version_rejects_second_implant_documentation
        """
        world = setup_stock((400_000, 400_000))
        patient = create_patient()
        case = create_case(patient["id"], scheduled_end_utc="2026-09-10T12:00:00Z")
        started = start_case(case["id"])
        stale_version = started["version"]

        document_implant(case["id"], world["units"][0])

        validate_error(
            api.create_implant_record(
                case["id"],
                _implant_payload(
                    world["units"][1], case["id"], expected_case_version=stale_version
                ),
                CC,
            ),
            ApiErrorId.ERR_STALE_CASE_VERSION,
            412,
        )
        assert get_case(case["id"])["implant_record_count"] == 1
        assert get_unit(world["units"][1]["id"])["custody_state"] == "AVAILABLE"

        second = document_implant(case["id"], world["units"][1], laterality="RIGHT")
        assert second["status"] == "DOCUMENTED"
        assert get_case(case["id"])["implant_record_count"] == 2
        assert get_unit(world["units"][1]["id"])["custody_state"] == "IMPLANTED"


class TestRecallLookupSurface:
    def test_implant_records_filter_by_patient_and_by_device_unit(self, api):
        """PRD §2.3: "Implant records accept `surgical_case_id`, `device_unit_id`,
        `patient_id` and `status`; this is the recall lookup surface across
        implanted patients, where filtering by patient answers "what is in this
        patient" and filtering by device unit answers "where did this serial go"."
        PRD §2.12: "`implant_count` on a patient counts that patient's implant
        records whose `status` is `DOCUMENTED`, `VERIFIED`, `AMENDED` or
        `EXPLANTED`."
        PRD §3.5: "A new implant record is created in `DOCUMENTED` carrying
        `surgical_case_id`, `device_unit_id` and `patient_id`, with
        `documented_by_user_id` set to the acting `X-User-ID`, `documented_at_utc`
        stamped from the logical clock, `amendment_count` at 0, and
        `verified_by_user_id` and `verified_at_utc` null."

        Design: Corner/entities/implant_record_list_by_patient_id_is_the_recall_lookup_surface
        """
        world = setup_documented_implant()
        record = world["record"]

        rows, meta = validate_paginated(
            api.list_implant_records(CO, {"patient_id": world["patient"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == record["id"]

        rows, meta = validate_paginated(
            api.list_implant_records(CO, {"device_unit_id": world["unit"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == record["id"]

        assert get_patient(world["patient"]["id"])["implant_count"] == 1
        assert record["patient_id"] == world["patient"]["id"]
        assert record["documented_by_user_id"] == "cc-01"
        assert record["verified_by_user_id"] is None
        assert record["verified_at_utc"] is None
        assert record["amendment_count"] == 0
        assert get_case(world["case"]["id"])["implant_record_count"] == 1


class TestAbortCascade:
    def test_aborting_an_in_progress_case_voids_records_then_charges(self, api):
        """PRD §3.3: "From `IN_PROGRESS` the case moves to `ABORTED`, which does all
        of that *and* runs a three-hop void cascade — every implant record of the
        case still in `DOCUMENTED` moves to `VOIDED`; each record moving to
        `VOIDED` in turn moves every charge line of that record in `DRAFT`,
        `POSTED` or `CORRECTION_REQUIRED` to `VOIDED`; each charge moving to
        `VOIDED` in turn re-derives the case's `total_posted_charge_cents`; and each
        record moving to `VOIDED` in turn re-derives that patient's
        `implant_count`."
        PRD §2.12: "`implant_record_count` on a case counts that case's implant
        records whose `status` is anything other than `VOIDED`."

        Design: Corner/state_machines/case_abort_from_in_progress_voids_records_and_charges
        """
        world = setup_documented_implant()
        charge = create_charge(world["record"]["id"])

        aborted = validate_success(api.cancel_case(world["case"]["id"], CC), 200)
        assert aborted["status"] == "ABORTED"

        assert get_record(world["record"]["id"])["status"] == "VOIDED"
        assert get_charge(charge["id"])["status"] == "VOIDED"
        assert get_patient(world["patient"]["id"])["implant_count"] == 0

        case = get_case(world["case"]["id"])
        assert case["implant_record_count"] == 0
        assert case["total_posted_charge_cents"] == 0
        assert get_unit(world["unit"]["id"])["custody_state"] == "IMPLANTED"
