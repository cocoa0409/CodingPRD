"""Round trips through the endpoint surface: creates, computed reads and nested links."""

from __future__ import annotations

from test_helpers import (
    ACCESS_APPEAL_FIELDS,
    ACCESS_STATUS_REVOKED,
    APPEAL_STATUS_SUBMITTED,
    BADGE_STATUS_CHECKED_OUT,
    BADGE_STATUS_ISSUED,
    BASE_QUOTA,
    CASE_STATUS_SCHEDULED,
    COMPLEXITY_SIMPLE,
    COVERAGE_NOT_REQUIRED,
    CREDENTIALING_OFFICER,
    ESCORT_NOT_REQUIRED,
    FEE_STATUS_ASSESSED,
    FEE_STATUS_NONE,
    LOANER_STATUS_DELIVERED_ON_TIME,
    LOANER_STATUS_REJECTED_LATE,
    LOGICAL_CLOCK_DEFAULT_UTC,
    OR_COORDINATOR,
    READINESS_NOT_APPLICABLE,
    RESTRICTION_STANDARD,
    SCORECARD_FIELDS,
    STATUS_IN_GOOD_STANDING,
    SURGICAL_CASE_FIELDS,
    TIER_PLATINUM,
    approved_product,
    assert_common_fields,
    assert_created_at_ascending,
    assert_fields_present,
    assert_ids_in_order,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    assert_ratio_four_places,
    assert_total_count,
    badge_serial,
    canonicalize_instant,
    check_in,
    check_out,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credentialed_rep,
    decide_authorization,
    file_appeal,
    ids_of,
    list_rows_and_meta,
    make_vendor_admin_headers,
    read_appeal,
    read_case,
    read_check_in,
    read_loaner_set,
    read_scorecard,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    request_authorization,
    revoke_rep,
    set_clock,
)


class TestSurgicalCaseRoundTrip:
    """One scheduled case read back three ways: the create, the read and the list."""

    def test_create_read_and_facility_filtered_list_report_the_same_case(self, api):
        """A case scheduled at one hospital reads identically from all three channels.

        "The two derived postures start according to the implant flag:
        `vendor_coverage_status` is `UNCOVERED` on an implant case and
        `NOT_REQUIRED` otherwise, while `implant_readiness_status` is `PENDING`
        on an implant case and `NOT_APPLICABLE` otherwise." Case listings "may be
        narrowed by `facility_id`", so the theatre booked at the sister hospital
        stays off this page.

        Design: Corner/endpoints/surgical_case_crud_round_trip_create_read_list
        """
        hospital_a = create_facility(
            api, "CR-51A", name="Crud Hospital A",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        hospital_b = create_facility(
            api, "CR-51B", name="Crud Hospital B",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        elsewhere = create_case(
            api,
            hospital_b["id"],
            "CASE-15079",
            "2026-10-02T08:00:00Z",
            "2026-10-02T09:00:00Z",
            procedure_name="Other Facility Case",
        )

        created = create_case(
            api,
            hospital_a["id"],
            "CASE-15078",
            "2026-10-03T07:30:00Z",
            "2026-10-03T09:45:00Z",
            procedure_name="Crud Round Trip Case",
        )
        assert_common_fields(created)
        assert_fields_present(created, SURGICAL_CASE_FIELDS)

        stored = read_case(api, created["id"])
        assert stored["id"] == created["id"], "the read should return the row just created"
        assert_common_fields(stored)
        assert stored["version"] == created["version"], (
            "a plain read is not a mutation, so it leaves version where the create left it"
        )
        assert stored["facility_id"] == hospital_a["id"]
        assert stored["case_number"] == "CASE-15078"
        assert_instant_equals(
            stored["scheduled_start_utc"], "2026-10-03T07:30:00Z", "scheduled_start_utc"
        )
        assert_instant_equals(
            stored["scheduled_end_utc"], "2026-10-03T09:45:00Z", "scheduled_end_utc"
        )
        assert_instant_equals(
            stored["original_scheduled_start_utc"],
            "2026-10-03T07:30:00Z",
            "original_scheduled_start_utc",
        )
        assert stored["status"] == CASE_STATUS_SCHEDULED
        assert stored["restriction_level"] == RESTRICTION_STANDARD
        assert stored["implant_required"] is False
        assert stored["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED
        assert stored["implant_readiness_status"] == READINESS_NOT_APPLICABLE
        assert_integer_field(stored, "approved_rep_count", 0)
        assert_integer_field(stored, "revoked_authorization_count", 0)
        assert_integer_field(stored, "reschedule_count", 0)

        rows, meta = list_rows_and_meta(
            api.list_surgical_cases(OR_COORDINATOR, {"facility_id": hospital_a["id"]})
        )
        assert_total_count(meta, 1)
        assert_ids_in_order(rows, [created["id"]])
        assert elsewhere["id"] not in ids_of(rows), (
            "the sister hospital's theatre list has no business on this page"
        )
        listed = rows[0]
        assert_integer_field(listed, "version", created["version"])
        assert listed["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED
        assert listed["implant_readiness_status"] == READINESS_NOT_APPLICABLE


class TestVendorScorecardComputedRead:
    """The scorecard is a live projection over the vendor's trays, not a snapshot."""

    def test_scorecard_aggregates_the_rejected_late_delivery_before_any_sweep(self, api):
        """One tray set three hours past its deadline drives every scorecard number.

        "The late-delivery penalty is five points for each of that vendor's loaner
        sets whose `status` is `DELIVERED_LATE` or `REJECTED_LATE` **and** whose
        `fee_status` is not `REVERSED`." The read "is entirely read-only, and
        `utilization_ratio` together with `lapsed_rep_count` are derived live from
        the current counters and representative postures", so the numbers stand
        even though no compliance sweep has ever observed this vendor.

        Design: Corner/endpoints/vendor_scorecard_computed_read_aggregates_live_counters
        """
        facility = create_facility(
            api, "SC-51", name="Scorecard Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "SCORV", legal_name="Scorecard Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "SD-1300",
            55000,
            product_name="Scorecard Driver Set",
            manufacturer="Scorv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15080",
            "2026-10-02T08:00:00Z",
            "2026-10-02T10:00:00Z",
            procedure_name="Scorecard Case",
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 2, COMPLEXITY_SIMPLE
        )
        assert_instant_equals(
            loaner["required_delivery_deadline_utc"],
            "2026-10-02T02:00:00Z",
            "required_delivery_deadline_utc",
        )

        receive_loaner_set(api, loaner["id"], "2026-10-02T05:00:00Z")

        scorecard = read_scorecard(api, vendor["id"])
        assert_fields_present(scorecard, SCORECARD_FIELDS)
        assert scorecard["vendor_id"] == vendor["id"]
        assert_integer_field(scorecard, "provisional_compliance_score", 95)
        assert_integer_field(scorecard, "adjudicated_compliance_score", 95)
        assert scorecard["scorecard_tier"] == TIER_PLATINUM
        assert scorecard["compliance_status"] == STATUS_IN_GOOD_STANDING
        assert_integer_field(scorecard, "access_quota_in_effect", BASE_QUOTA)
        assert_integer_field(scorecard, "authorizations_used_epoch", 0)
        assert_ratio_four_places(scorecard["utilization_ratio"], 0.0)
        assert_money_cents(scorecard, "late_fee_balance_cents", 900)
        assert_integer_field(scorecard, "late_delivery_count", 1)
        assert_integer_field(scorecard, "lapsed_rep_count", 0)
        assert_integer_field(scorecard, "substantiated_incident_count", 0)
        assert_integer_field(scorecard, "open_incident_count", 0)
        assert_integer_field(scorecard, "last_sweep_epoch", 0)

        stored = read_loaner_set(api, loaner["id"])
        assert stored["status"] == LOANER_STATUS_REJECTED_LATE
        assert stored["fee_status"] == FEE_STATUS_ASSESSED
        assert_integer_field(stored, "late_minutes_current_basis", 180)
        assert_money_cents(stored, "assessed_late_fee_cents", 900)

        again = read_scorecard(api, vendor["id"])
        assert again == scorecard, (
            "reading the scorecard a second time must not move a single number"
        )


class TestLogicalClockDrivesEveryStamp:
    """The clock endpoint is the only writable time source in the whole system."""

    def test_revocation_and_appeal_inherit_their_instants_from_the_clock(self, api):
        """A revocation at 13:45:30 hands the appeal a deadline of the same second.

        "Any of the eight roles may advance or rewind the clock through an
        operator capability that accepts a single `current_utc` instant and echoes
        it back", and "Filing stamps `status` at `SUBMITTED`, `filed_at_utc` from
        the logical clock, and `appeal_deadline_utc` at the representative's
        `revoked_at_utc` plus fourteen days", so the deadline is carried from the
        revocation second rather than from the filing instant.

        Design: Corner/endpoints/clock_action_endpoint_drives_every_system_timestamp
        """
        vendor = create_vendor(api, "CLKV", legal_name="Clock Devices")
        rep = create_vendor_rep(api, vendor["id"], "Cleo Clock")

        echoed = set_clock(api, "2026-09-20T13:45:30Z")
        assert_instant_equals(echoed["current_utc"], "2026-09-20T13:45:30Z", "current_utc")

        revoked = revoke_rep(
            api, rep["id"], CREDENTIALING_OFFICER, "Gift policy attestation withdrawn"
        )
        assert revoked["access_status"] == ACCESS_STATUS_REVOKED
        assert_instant_equals(
            revoked["revoked_at_utc"], "2026-09-20T13:45:30Z", "revoked_at_utc"
        )
        assert canonicalize_instant(revoked["revoked_at_utc"]) != canonicalize_instant(
            LOGICAL_CLOCK_DEFAULT_UTC
        ), "the revocation should be stamped from the moved clock, not the startup default"

        set_clock(api, "2026-09-25T00:00:00Z")
        appeal = file_appeal(
            api,
            vendor["id"],
            rep["id"],
            grounds="The attestation was re-signed the same afternoon",
        )
        assert_fields_present(appeal, ACCESS_APPEAL_FIELDS)
        assert appeal["status"] == APPEAL_STATUS_SUBMITTED
        assert_instant_equals(
            appeal["filed_at_utc"], "2026-09-25T00:00:00Z", "filed_at_utc"
        )
        assert_instant_equals(
            appeal["filed_for_revoked_at_utc"],
            "2026-09-20T13:45:30Z",
            "filed_for_revoked_at_utc",
        )
        assert_instant_equals(
            appeal["appeal_deadline_utc"], "2026-10-04T13:45:30Z", "appeal_deadline_utc"
        )

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_REVOKED
        assert_instant_equals(
            stored_rep["revoked_at_utc"], "2026-09-20T13:45:30Z", "revoked_at_utc"
        )

        stored_appeal = read_appeal(api, appeal["id"])
        assert_instant_equals(
            stored_appeal["appeal_deadline_utc"],
            "2026-10-04T13:45:30Z",
            "appeal_deadline_utc",
        )


class TestAuthorizationCheckInLink:
    """The nested badge collection is scoped to one authorization and filterable."""

    def test_the_link_lists_both_badges_and_narrows_to_the_live_one(self, api):
        """Two kiosk visits on one authorization surface as XR-53-0001 and XR-53-0002.

        "`badge_serial` is the hosting facility's `code`, then a hyphen, then a
        four-digit zero-padded counter that is scoped per facility, starts at
        `0001`, and is handed out in check-in order", and "each authorization
        exposes a sub-resource listing of its kiosk check-ins narrowable by
        `badge_status`", so the filtered link returns only the badge still in the
        representative's hand.

        Design: Corner/endpoints/authorization_check_ins_cross_reference_link_lists_both_badges
        """
        facility = create_facility(
            api, "XR-53", name="Cross Reference Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "XREFV", legal_name="Cross Reference Devices")
        rep = credentialed_rep(
            api,
            vendor["id"],
            "Xena Xref",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15100",
            "2026-08-28T09:00:00Z",
            "2026-08-28T11:00:00Z",
            procedure_name="Cross Reference Case",
        )
        requested = request_authorization(
            api, case["id"], rep["id"], headers=make_vendor_admin_headers(vendor["id"])
        )
        authorization = decide_authorization(
            api, requested["id"], "APPROVE", OR_COORDINATOR
        )
        assert_instant_equals(
            authorization["badge_window_start_utc"],
            "2026-08-28T08:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            authorization["badge_window_end_utc"],
            "2026-08-28T11:30:00Z",
            "badge_window_end_utc",
        )

        set_clock(api, "2026-08-28T09:15:00Z")
        first = check_in(api, authorization["id"], rep["id"])
        assert first["badge_serial"] == badge_serial("XR-53", 1)
        assert first["escort_status"] == ESCORT_NOT_REQUIRED

        set_clock(api, "2026-08-28T09:45:00Z")
        check_out(api, first["id"], rep["id"])

        set_clock(api, "2026-08-28T10:15:00Z")
        second = check_in(api, authorization["id"], rep["id"])
        assert second["badge_serial"] == badge_serial("XR-53", 2)

        rows, meta = list_rows_and_meta(
            api.list_authorization_check_ins(authorization["id"], OR_COORDINATOR)
        )
        assert_total_count(meta, 2)
        assert_created_at_ascending(rows)
        assert_ids_in_order(rows, [first["id"], second["id"]])

        live_rows, live_meta = list_rows_and_meta(
            api.list_authorization_check_ins(
                authorization["id"], OR_COORDINATOR, {"badge_status": BADGE_STATUS_ISSUED}
            )
        )
        assert_total_count(live_meta, 1)
        assert_ids_in_order(live_rows, [second["id"]])

        surrendered = read_check_in(api, first["id"])
        assert surrendered["badge_status"] == BADGE_STATUS_CHECKED_OUT
        assert_instant_equals(
            surrendered["checked_out_at_utc"],
            "2026-08-28T09:45:00Z",
            "checked_out_at_utc",
        )

        in_hand = read_check_in(api, second["id"])
        assert in_hand["badge_status"] == BADGE_STATUS_ISSUED
        assert_instant_equals(
            in_hand["issued_at_utc"], "2026-08-28T10:15:00Z", "issued_at_utc"
        )
        assert_instant_equals(
            in_hand["valid_until_utc"], "2026-08-28T11:30:00Z", "valid_until_utc"
        )


class TestReceiveDefaultsToTheLogicalClock:
    """An omitted delivery instant is filled from the clock, not left null."""

    def test_receiving_with_an_empty_body_lands_the_tray_set_exactly_on_time(self, api):
        """The dock takes the clock's instant, which sits precisely on the deadline.

        "Receipt at the dock is a `SterileProcessingTech`'s call and takes an
        optional `delivered_at_utc`; when the field is omitted the server uses the
        logical clock's current instant." "A delivery at exactly the deadline is
        zero minutes late", so the set forks to the on-time branch and no fee is
        owed.

        Design: Corner/endpoints/receive_without_delivered_at_defaults_to_the_logical_clock
        """
        facility = create_facility(
            api, "CN-52", name="Conditional Action Hospital",
            spd_turnaround_hours=4, spd_bay_count=2,
        )
        vendor = create_vendor(api, "CONDV", legal_name="Conditional Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CB-1400",
            30000,
            product_name="Conditional Basin Set",
            manufacturer="Condv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15090",
            "2026-10-06T08:00:00Z",
            "2026-10-06T10:00:00Z",
            procedure_name="Conditional Action Case",
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 2, COMPLEXITY_SIMPLE
        )
        assert_instant_equals(
            loaner["required_delivery_deadline_utc"],
            "2026-10-06T02:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            loaner["pinned_deadline_utc"], "2026-10-06T02:00:00Z", "pinned_deadline_utc"
        )

        set_clock(api, "2026-10-06T02:00:00Z")
        received = receive_loaner_set(api, loaner["id"])

        assert_instant_equals(
            received["delivered_at_utc"], "2026-10-06T02:00:00Z", "delivered_at_utc"
        )
        assert received["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert_integer_field(received, "late_minutes_current_basis", 0)
        assert_integer_field(received, "late_minutes_pinned_basis", 0)
        assert_money_cents(received, "assessed_late_fee_cents", 0)
        assert received["fee_status"] == FEE_STATUS_NONE

        stored = read_loaner_set(api, loaner["id"])
        assert stored["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert_instant_equals(
            stored["delivered_at_utc"], "2026-10-06T02:00:00Z", "delivered_at_utc"
        )

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 0)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 100)

        stored_case = read_case(api, case["id"])
        assert stored_case["implant_readiness_status"] == READINESS_NOT_APPLICABLE
