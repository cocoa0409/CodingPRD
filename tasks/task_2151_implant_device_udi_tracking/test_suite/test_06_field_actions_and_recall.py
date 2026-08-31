"""Field actions: the exposure cohort, the quarantine cascade and outreach."""

from test_helpers import (
    ApiErrorId,
    CC,
    CO,
    IL,
    agreement_version,
    assert_lot_conservation,
    assert_recall_notification,
    assert_same_instant,
    close_field_action,
    create_active_agreement,
    create_case,
    create_catalog_item,
    create_field_action,
    create_lot,
    create_patient,
    create_vendor,
    document_implant,
    get_case,
    get_catalog_item,
    get_exposure,
    get_field_action,
    get_lot,
    get_notification,
    get_unit,
    get_vendor,
    add_unit,
    make_vendor_rep_headers,
    notifications_for,
    ops_run,
    publish_field_action,
    release_lot,
    reserve_unit,
    resolve_notification,
    set_clock,
    setup_published_field_action,
    setup_stock,
    start_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def _lot_scoped_recall_world():
    """One released lot of two owned units: SN-0002 implanted into an
    IN_PROGRESS case, SN-0001 reserved to a second, still SCHEDULED case."""
    world = setup_stock((400_000, 400_000), lot_overrides={"lot_number": "L-4401"})
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
    record = document_implant(case_one["id"], world["units"][1])
    action = create_field_action(
        world["vendor"]["id"],
        world["catalog_item"]["id"],
        action_code="FA-2026-001",
        action_class="CLASS_II",
        scope_type="LOT",
        lot_numbers=["L-4401"],
    )
    world.update(
        {
            "patient_one": patient_one,
            "case_one": case_one,
            "case_two": case_two,
            "record": record,
            "action": action,
        }
    )
    return world


class TestPublishCascade:
    def test_publish_recalls_the_matched_lot_and_freezes_its_on_hand_stock(self, api):
        """PRD §3.8: "Publishing runs that cohort for real and is legal only from
        `DRAFT`. It stamps `published_at_utc` from the logical clock, writes both
        cohort sizes, and then executes a four-hop cascade. Every matched lot whose
        `status` is `QUARANTINE` or `AVAILABLE` moves to the terminal `RECALLED`."
        PRD §3.8: "From the qualifying set, the on-hand cohort is those units whose
        `custody_state` is `QUARANTINED`, `AVAILABLE` or `RESERVED`, and its size is
        `on_hand_cohort_size`."
        PRD §3.8: "Under `LOT` scope, the unit additionally qualifies only when its
        lot's `lot_number` is one of the values listed in `lot_numbers`."

        Design: Difficulty/transitive_cascade/field_action_publish_four_hop_recall_cascade
        """
        world = _lot_scoped_recall_world()

        published = validate_success(
            api.publish_field_action(world["action"]["id"], CO), 200
        )
        assert published["status"] == "PUBLISHED"
        assert published["published_at_utc"] is not None
        assert published["on_hand_cohort_size"] == 1
        assert published["implanted_cohort_size"] == 1
        assert published["notification_open_count"] == 1

        assert get_lot(world["lot"]["id"])["status"] == "RECALLED"
        assert get_unit(world["units"][0]["id"])["custody_state"] == "RECALL_HOLD"
        assert get_unit(world["units"][1]["id"])["custody_state"] == "IMPLANTED"

    def test_publish_detaches_the_reserved_unit_and_blocks_its_case(self, api):
        """PRD §3.8: "Each `RESERVED` unit moving to `RECALL_HOLD` in turn has its
        `reserved_case_id` cleared and increments the detached case's
        `blocked_reservation_count` by one, which in turn flips that case's
        `readiness_status` to `BLOCKED_RESERVATION` — that is the serialization
        point between the recall and any case still trying to close."
        PRD §3.8: "Separately, one recall notification is created in `PENDING` for
        each distinct implant record in the implanted cohort, in ascending
        `created_at` order of those records, each carrying the originating
        `field_action_id`, its `implant_record_id`, the `patient_id` denormalized
        from the record so that recall lookup never needs a join, an
        `escalation_level` of 0 and a null `outcome_note`."
        PRD §3.8: "Finally, an `action_class` of `CLASS_I` sets the vendor's
        `standing` to `HOLD`, freezing that vendor's invoicing; `CLASS_II` and
        `CLASS_III` leave `standing` alone. In every case the vendor's
        `recall_open_count` is re-derived."

        Design: Difficulty/transitive_cascade/field_action_publish_four_hop_recall_cascade
        """
        world = _lot_scoped_recall_world()
        publish_field_action(world["action"]["id"])

        detached = get_unit(world["units"][0]["id"])
        assert detached["custody_state"] == "RECALL_HOLD"
        assert detached["reserved_case_id"] is None

        case_two = get_case(world["case_two"]["id"])
        assert case_two["blocked_reservation_count"] == 1
        assert case_two["readiness_status"] == "BLOCKED_RESERVATION"

        rows, meta = validate_paginated(
            api.list_recall_notifications(CO, {"field_action_id": world["action"]["id"]})
        )
        assert meta["total_count"] == 1
        notification = rows[0]
        assert_recall_notification(notification)
        assert notification["status"] == "PENDING"
        assert notification["implant_record_id"] == world["record"]["id"]
        assert notification["patient_id"] == world["patient_one"]["id"]
        assert notification["escalation_level"] == 0
        assert notification["outcome_note"] is None

        vendor = get_vendor(world["vendor"]["id"])
        assert vendor["standing"] == "ACTIVE"
        assert vendor["recall_open_count"] == 1


class TestEmptyImplantedCohort:
    def test_publish_with_no_implanted_stock_creates_no_notifications(self, api):
        """PRD §3.8: "The implanted side takes the qualifying units whose
        `custody_state` is `IMPLANTED` or `EXPLANTED`, then collects the distinct
        implant records pointing at those units whose own `status` is `DOCUMENTED`,
        `VERIFIED`, `AMENDED` or `EXPLANTED`; the count of those distinct records is
        `implanted_cohort_size`, and a `VOIDED` record never enters it."
        PRD §3.8: "Separately, one recall notification is created in `PENDING` for
        each distinct implant record in the implanted cohort, in ascending
        `created_at` order of those records, each carrying the originating
        `field_action_id`, its `implant_record_id`, the `patient_id` denormalized
        from the record so that recall lookup never needs a join, an
        `escalation_level` of 0 and a null `outcome_note`."

        Design: Difficulty/boundary_precision_check/field_action_publish_with_empty_implanted_cohort_closes_from_published
        """
        world = setup_stock(
            (60_000,),
            catalog_overrides={
                "device_identifier": "00812345678974",
                "description": "Suture Anchor",
                "category": "STANDARD_IMPLANT",
                "list_charge_cents": 90_000,
                "charge_code": "CDM-77210",
                "shelf_life_days": 900,
            },
            lot_overrides={"lot_number": "L-9901", "expiration_date": "2027-06-30"},
        )
        action = create_field_action(
            world["vendor"]["id"],
            world["catalog_item"]["id"],
            action_code="FA-2026-010",
            action_class="CLASS_III",
            scope_type="CATALOG",
        )

        published = validate_success(api.publish_field_action(action["id"], CO), 200)
        assert published["implanted_cohort_size"] == 0
        assert published["on_hand_cohort_size"] == 1
        assert published["notification_open_count"] == 0

        _, meta = validate_paginated(
            api.list_recall_notifications(CO, {"field_action_id": action["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_action_with_no_notifications_closes_straight_from_published(self, api):
        """PRD §3.8: "Closing is legal from `IN_REMEDIATION` and also directly from
        `PUBLISHED` — the latter is reachable precisely when the implanted cohort
        was empty, so that zero notifications were ever created and the open count
        never left 0."
        PRD §3.8: "Closing moves every notification of this action sitting in
        `NOTIFIED`, `ACKNOWLEDGED` or `UNREACHABLE` to `CLOSED`; moves every device
        unit in `RECALL_HOLD` attributable to this action to the terminal
        `RETURNED_TO_VENDOR` under a `RETURN_TO_VENDOR` disposition or to the
        terminal `DISPOSED` under a `DISPOSE` disposition, re-deriving each affected
        lot's `on_hand_qty` and `consumed_qty` either way; and re-derives the
        vendor's `recall_open_count`, restoring that vendor's `standing` to `ACTIVE`
        at the moment the count reaches 0."

        Design: Difficulty/boundary_precision_check/field_action_publish_with_empty_implanted_cohort_closes_from_published
        """
        world = setup_stock(
            (60_000,),
            catalog_overrides={
                "device_identifier": "00812345678974",
                "description": "Suture Anchor",
                "category": "STANDARD_IMPLANT",
                "list_charge_cents": 90_000,
                "charge_code": "CDM-77210",
                "shelf_life_days": 900,
            },
            lot_overrides={"lot_number": "L-9901", "expiration_date": "2027-06-30"},
        )
        action = create_field_action(
            world["vendor"]["id"],
            world["catalog_item"]["id"],
            action_code="FA-2026-010",
            action_class="CLASS_III",
            scope_type="CATALOG",
        )
        publish_field_action(action["id"])

        closed = validate_success(
            api.close_field_action(
                action["id"], {"on_hand_disposition": "RETURN_TO_VENDOR"}, CO
            ),
            200,
        )
        assert closed["status"] == "CLOSED"

        assert get_unit(world["units"][0]["id"])["custody_state"] == "RETURNED_TO_VENDOR"

        lot = get_lot(world["lot"]["id"])
        assert lot["received_qty"] == 1
        assert lot["on_hand_qty"] == 0
        assert lot["consumed_qty"] == 1
        assert_lot_conservation(lot)
        assert get_vendor(world["vendor"]["id"])["recall_open_count"] == 0


class TestRemediationGate:
    def test_close_is_refused_while_a_notification_is_still_pending(self, api):
        """PRD §3.8: "Closing an action requires `notification_open_count` to be
        exactly 0; while any notification is still `PENDING` the attempt is rejected
        with `ERR_RECALL_REMEDIATION_INCOMPLETE`."
        PRD §2.12: "`notification_open_count` on a field action counts that action's
        recall notifications whose `status` is `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/field_action_close_blocked_by_pending_recall_notification
        """
        world = setup_published_field_action(
            field_action_overrides={"action_code": "FA-2026-020"}
        )
        action = world["field_action"]
        assert action["notification_open_count"] == 1

        validate_error(
            api.close_field_action(action["id"], {"on_hand_disposition": "DISPOSE"}, CO),
            ApiErrorId.ERR_RECALL_REMEDIATION_INCOMPLETE,
            409,
        )
        assert get_field_action(action["id"])["status"] == "PUBLISHED"

    def test_resolving_the_last_notification_unlocks_the_close(self, api):
        """PRD §3.8: "All three branches carry an identical side-effect set: the
        outcome and the note are stored, the action's `notification_open_count` is
        re-derived, and — on the first resolution against a still-`PUBLISHED` action
        — the action itself bubbles up `PUBLISHED → IN_REMEDIATION`."
        PRD §3.8: "Closing moves every notification of this action sitting in
        `NOTIFIED`, `ACKNOWLEDGED` or `UNREACHABLE` to `CLOSED`; moves every device
        unit in `RECALL_HOLD` attributable to this action to the terminal
        `RETURNED_TO_VENDOR` under a `RETURN_TO_VENDOR` disposition or to the
        terminal `DISPOSED` under a `DISPOSE` disposition, re-deriving each affected
        lot's `on_hand_qty` and `consumed_qty` either way; and re-derives the
        vendor's `recall_open_count`, restoring that vendor's `standing` to `ACTIVE`
        at the moment the count reaches 0."

        Design: Difficulty/cross_entity_state_dependency/field_action_close_blocked_by_pending_recall_notification
        """
        world = setup_published_field_action(
            field_action_overrides={"action_code": "FA-2026-020"}
        )
        action = world["field_action"]
        notification = world["notifications"][0]

        validate_error(
            api.close_field_action(action["id"], {"on_hand_disposition": "DISPOSE"}, CO),
            ApiErrorId.ERR_RECALL_REMEDIATION_INCOMPLETE,
            409,
        )

        resolved = validate_success(
            api.resolve_recall_notification(
                notification["id"],
                {"outcome": "ACKNOWLEDGED", "outcome_note": "patient contacted by phone"},
                CO,
            ),
            200,
        )
        assert resolved["status"] == "ACKNOWLEDGED"

        in_remediation = get_field_action(action["id"])
        assert in_remediation["status"] == "IN_REMEDIATION"
        assert in_remediation["notification_open_count"] == 0

        closed = validate_success(
            api.close_field_action(action["id"], {"on_hand_disposition": "DISPOSE"}, CO),
            200,
        )
        assert closed["status"] == "CLOSED"
        assert get_notification(notification["id"])["status"] == "CLOSED"


class TestSeverityAndScope:
    def test_class_one_publication_holds_the_vendor_and_blocks_invoicing(self, api):
        """PRD §3.8: "Finally, an `action_class` of `CLASS_I` sets the vendor's
        `standing` to `HOLD`, freezing that vendor's invoicing; `CLASS_II` and
        `CLASS_III` leave `standing` alone. In every case the vendor's
        `recall_open_count` is re-derived."
        PRD §3.10: "The agreement must be `ACTIVE`, failing which the answer is
        `ERR_AGREEMENT_NOT_ACTIVE`, and the vendor's `standing` must be `ACTIVE`,
        failing which the answer is `ERR_VENDOR_ON_HOLD` — a vendor with an open
        `CLASS_I` field action cannot invoice at all."

        Design: Corner/state_machines/class_i_field_action_publish_places_vendor_on_hold_and_blocks_invoicing
        """
        set_clock("2026-09-01T00:00:00Z")
        vendor = create_vendor()
        agreement = create_active_agreement(vendor["id"])
        catalog_item = create_catalog_item(vendor["id"])
        lot = create_lot(catalog_item["id"])
        unit = add_unit(
            lot["id"], "SN-0001", 462_500, consignment_agreement_id=agreement["id"]
        )
        release_lot(lot["id"])

        patient = create_patient()
        case = create_case(patient["id"])
        start_case(case["id"])
        document_implant(case["id"], unit)
        assert get_unit(unit["id"])["billing_state"] == "BILLABLE"

        action = create_field_action(
            vendor["id"],
            catalog_item["id"],
            action_code="FA-2026-100",
            action_class="CLASS_I",
            scope_type="CATALOG",
        )
        stale_free_version = agreement_version(agreement["id"])
        published = validate_success(api.publish_field_action(action["id"], CO), 200)
        assert published["implanted_cohort_size"] == 1

        held = get_vendor(vendor["id"])
        assert held["standing"] == "HOLD"
        assert held["recall_open_count"] == 1

        validate_error(
            api.create_vendor_invoice(
                {
                    "vendor_id": vendor["id"],
                    "consignment_agreement_id": agreement["id"],
                    "invoice_number": "INV-1",
                    "submitted_total_cents": 462_500,
                    "device_unit_ids": [unit["id"]],
                    "expected_agreement_version": stale_free_version,
                },
                make_vendor_rep_headers(vendor["id"]),
            ),
            ApiErrorId.ERR_VENDOR_ON_HOLD,
            409,
        )

        after = get_unit(unit["id"])
        assert after["billing_state"] == "BILLABLE"
        assert after["vendor_invoice_id"] is None

    def test_serial_range_scope_captures_both_endpoint_serials(self, api):
        """PRD §3.8: "Under `SERIAL_RANGE` scope, the unit additionally qualifies
        only when its `udi_serial` compares as at or after `serial_low` and at or
        before `serial_high` under a plain lexicographic byte comparison — **both
        ends of the range are inclusive**."
        PRD §3.8: "From the qualifying set, the on-hand cohort is those units whose
        `custody_state` is `QUARANTINED`, `AVAILABLE` or `RESERVED`, and its size is
        `on_hand_cohort_size`."

        Design: Corner/calculations/recall_serial_range_scope_is_inclusive_on_both_ends
        """
        world = setup_stock((400_000, 400_000, 400_000))
        action = create_field_action(
            world["vendor"]["id"],
            world["catalog_item"]["id"],
            action_code="FA-2026-200",
            action_class="CLASS_III",
            scope_type="SERIAL_RANGE",
            serial_low="SN-0001",
            serial_high="SN-0002",
        )

        published = validate_success(api.publish_field_action(action["id"], CO), 200)
        assert published["on_hand_cohort_size"] == 2, (
            "Both endpoint serials must qualify: an exclusive reading would give 0 "
            "or 1"
        )
        assert published["implanted_cohort_size"] == 0

        assert get_unit(world["units"][0]["id"])["custody_state"] == "RECALL_HOLD"
        assert get_unit(world["units"][1]["id"])["custody_state"] == "RECALL_HOLD"

        # The exposure read recomputes from scratch (PRD §3.8), and the on-hand
        # cohort is exhaustively "QUARANTINED, AVAILABLE or RESERVED" — the two
        # in-scope serials are now RECALL_HOLD, so the recount is 0.  An
        # implementation that echoed the stored cohort size would answer 2 here.
        exposure = get_exposure(action["id"])
        assert exposure["on_hand_cohort_size"] == 0
        assert exposure["implanted_cohort_size"] == 0
        assert exposure["patient_ids"] == []

        lot = get_lot(world["lot"]["id"])
        assert lot["status"] == "RECALLED"
        assert lot["on_hand_qty"] == 3
        assert_lot_conservation(lot)


class TestExposureRead:
    def test_exposure_read_recomputes_the_cohort_and_names_the_patients(self, api):
        """PRD §3.8: "Alongside all of that sits a pure read used for recall lookup
        across implanted patients: it recomputes the exposure cohort from scratch and
        answers with `implanted_cohort_size`, `on_hand_cohort_size`, the list of
        affected `patient_ids`, the list of affected `implant_record_ids`, and the
        current `notification_open_count`."
        PRD §3.8: "Each notification's `due_utc` is measured from the action's
        `effective_from_utc`, not from publication, and the window depends on
        severity: a `CLASS_I` action allows 7 days, a `CLASS_II` action 30 days, and
        a `CLASS_III` action 90 days."

        Design: Corner/endpoints/field_action_exposure_computed_read_lists_implanted_patients
        """
        world = setup_published_field_action(
            field_action_overrides={
                "action_code": "FA-2026-300",
                "effective_from_utc": "2026-09-01T00:00:00Z",
            }
        )

        # Recomputed from scratch after publication: the single on-hand serial
        # was frozen into RECALL_HOLD by the publish cascade, and RECALL_HOLD is
        # not one of the three custody states PRD §3.8 lists for the on-hand
        # cohort, so the live recount is 0 while the implanted side is unchanged.
        exposure = get_exposure(world["field_action"]["id"])
        assert exposure["implanted_cohort_size"] == 1
        assert exposure["on_hand_cohort_size"] == 0
        assert exposure["notification_open_count"] == 1
        assert exposure["patient_ids"] == [world["patient"]["id"]]
        assert exposure["implant_record_ids"] == [world["records"][0]["id"]]

        rows, meta = validate_paginated(
            api.list_recall_notifications(CO, {"patient_id": world["patient"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["field_action_id"] == world["field_action"]["id"]
        assert rows[0]["status"] == "PENDING"
        assert_same_instant(
            rows[0]["due_utc"], "2026-10-01T00:00:00Z", "CLASS_II due_utc"
        )

        assert get_unit(world["units"][0]["id"])["custody_state"] == "RECALL_HOLD"
        assert get_unit(world["units"][1]["id"])["custody_state"] == "IMPLANTED"


class TestOutreachEscalation:
    def test_two_overdue_checkpoints_close_a_patient_out_as_unreachable(self, api):
        """PRD §3.11: "Every recall notification whose `status` is `PENDING` and
        whose `due_utc` is strictly before the logical clock has its
        `escalation_level` incremented by one and is counted in
        `escalated_notification_count`. When a notification's `escalation_level`
        reaches 2 or more, it moves to `UNREACHABLE`, which re-derives its field
        action's `notification_open_count` and, when that action is still
        `PUBLISHED`, bubbles it up to `IN_REMEDIATION` — exactly as a manual
        resolution would."
        PRD §3.8: "Each notification's `due_utc` is measured from the action's
        `effective_from_utc`, not from publication, and the window depends on
        severity: a `CLASS_I` action allows 7 days, a `CLASS_II` action 30 days, and
        a `CLASS_III` action 90 days."

        Design: Corner/state_machines/ops_run_escalates_overdue_notification_to_unreachable
        """
        world = setup_published_field_action(
            action_class="CLASS_I",
            field_action_overrides={
                "action_code": "FA-2026-110",
                "effective_from_utc": "2026-09-01T00:00:00Z",
            },
        )
        notification = world["notifications"][0]
        assert_same_instant(
            notification["due_utc"], "2026-09-08T00:00:00Z", "CLASS_I due_utc"
        )

        set_clock("2026-09-09T00:00:00Z")

        first = ops_run()
        assert first["escalated_notification_count"] == 1
        after_first = get_notification(notification["id"])
        assert after_first["escalation_level"] == 1
        assert after_first["status"] == "PENDING"

        second = ops_run()
        assert second["escalated_notification_count"] == 1
        after_second = get_notification(notification["id"])
        assert after_second["escalation_level"] == 2
        assert after_second["status"] == "UNREACHABLE"

        action = get_field_action(world["field_action"]["id"])
        assert action["status"] == "IN_REMEDIATION"
        assert action["notification_open_count"] == 0
