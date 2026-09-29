"""Version echoes, band boundaries, and side effects a client sees without re-reading."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_PENDING,
    AUTH_STATUS_APPROVED,
    COMPLEXITY_SIMPLE,
    COMPLIANCE_ADMIN,
    COMPLIANCE_ADMIN_2,
    COVERAGE_COVERED,
    COVERAGE_UNCOVERED,
    DEFAULT_BADGE_GRACE_MINUTES,
    DEFAULT_BADGE_LEAD_MINUTES,
    ERR_STALE_CASE_VERSION,
    ERR_STALE_VENDOR_VERSION,
    INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
    LOANER_STATUS_EXPECTED,
    LOGICAL_CLOCK_DEFAULT_UTC,
    OR_COORDINATOR,
    OUTCOME_SUBSTANTIATED,
    PIR_STATUS_DRAFT,
    READINESS_PENDING,
    REQUESTED_ROLE_IMPLANT_SUPPORT,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    STATUS_IN_GOOD_STANDING,
    STATUS_WATCH,
    STERILE_PROCESSING_TECH,
    TIER_STANDARD,
    USER_ORC_1,
    adjudicate_incident,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_total_count,
    assert_version_bumped,
    authorization_decision_payload,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credentialed_rep,
    get_success_data,
    ids_of,
    list_rows_and_meta,
    loaner_set_payload,
    make_vendor_admin_headers,
    pir_payload,
    read_case,
    read_scorecard,
    read_vendor,
    read_vendor_rep,
    report_incident,
    request_authorization,
    run_sweep,
    validate_error,
    validate_success,
)


class TestVendorVersionEchoOnASecondRequest:
    """A vendor company opening two product introduction requests back to back."""

    def test_replayed_vendor_version_is_refused_and_the_re_read_retry_succeeds(self, api):
        """The first create invalidates the reading it was authored against.

        "A successful create itself increments the vendor's `version` by one, so a
        caller submitting two requests in a row must re-read the vendor in
        between." Replaying the same `expected_vendor_version` is therefore a
        stale echo rather than a duplicate payload, and the plain read that
        recovers the fresh version is not itself a mutation, so it leaves the
        counter exactly where the first create left it.

        Design: Corner/cross-cutting complexity layers/stale_vendor_version_on_a_second_request_returns_412
        """
        facility = create_facility(
            api,
            "OV-66",
            name="Occ Vendor Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "OCCV", legal_name="Occ Vendor Devices")
        vendor_admin = make_vendor_admin_headers(vendor["id"])

        first = get_success_data(
            api.create_pir(
                pir_payload(
                    vendor["id"],
                    facility["id"],
                    "OF-1900",
                    33000,
                    vendor["version"],
                    product_name="Occ First Tray",
                    manufacturer="Occv",
                    is_implant=False,
                ),
                vendor_admin,
            ),
            201,
        )
        assert first["status"] == PIR_STATUS_DRAFT

        # The same reading of the vendor, replayed for the second tray.
        replay = api.create_pir(
            pir_payload(
                vendor["id"],
                facility["id"],
                "OS-1901",
                34000,
                vendor["version"],
                product_name="Occ Second Tray",
                manufacturer="Occv",
                is_implant=False,
            ),
            vendor_admin,
        )
        validate_error(replay, ERR_STALE_VENDOR_VERSION)

        refreshed = read_vendor(api, vendor["id"])
        assert_version_bumped(vendor, refreshed)
        assert_integer_field(
            read_vendor(api, vendor["id"]), "version", refreshed["version"]
        )

        second = get_success_data(
            api.create_pir(
                pir_payload(
                    vendor["id"],
                    facility["id"],
                    "OS-1901",
                    34000,
                    refreshed["version"],
                    product_name="Occ Second Tray",
                    manufacturer="Occv",
                    is_implant=False,
                ),
                vendor_admin,
            ),
            201,
        )
        assert second["id"] != first["id"], (
            "the accepted retry should mint a second request rather than return the first"
        )
        assert_version_bumped(refreshed, read_vendor(api, vendor["id"]))


class TestCaseVersionEchoOnASecondTraySet:
    """Two tray sets staged for one case, each pinned against the case schedule."""

    def test_replayed_case_version_is_refused_and_both_sets_pin_one_deadline(self, api):
        """The stale echo is turned away before any deadline is pinned.

        "A reschedule increments the case `version`, and so does a successful
        registration, which means registering a second tray set for the same case
        requires re-reading the case first." Reading the case back to recover the
        version is not a mutation, so the retry lands on the same six-hour lead
        the first set was given: four turnaround hours plus two for a `SIMPLE`
        reprocessing allowance, with no tray surcharge on two trays.

        Design: Corner/cross-cutting complexity layers/stale_case_version_on_a_second_loaner_set_returns_412
        """
        facility = create_facility(
            api,
            "OC-67",
            name="Occ Case Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "OCASV", legal_name="Occ Case Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "OB-2000",
            21000,
            product_name="Occ Case Basin",
            manufacturer="Ocasv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15200",
            "2026-10-09T08:00:00Z",
            "2026-10-09T10:00:00Z",
            procedure_name="Occ Case",
        )

        first = get_success_data(
            api.create_loaner_set(
                loaner_set_payload(
                    case["id"], product["id"], 2, case["version"], COMPLEXITY_SIMPLE
                ),
                STERILE_PROCESSING_TECH,
            ),
            201,
        )
        assert first["status"] == LOANER_STATUS_EXPECTED

        replay = api.create_loaner_set(
            loaner_set_payload(
                case["id"], product["id"], 2, case["version"], COMPLEXITY_SIMPLE
            ),
            STERILE_PROCESSING_TECH,
        )
        validate_error(replay, ERR_STALE_CASE_VERSION)

        refreshed = read_case(api, case["id"])
        assert_version_bumped(case, refreshed)
        assert_integer_field(
            read_case(api, case["id"]), "version", refreshed["version"]
        )

        second = get_success_data(
            api.create_loaner_set(
                loaner_set_payload(
                    case["id"], product["id"], 2, refreshed["version"], COMPLEXITY_SIMPLE
                ),
                STERILE_PROCESSING_TECH,
            ),
            201,
        )

        for tray_set in (first, second):
            assert_instant_equals(
                tray_set["required_delivery_deadline_utc"],
                "2026-10-09T02:00:00Z",
                "required_delivery_deadline_utc",
            )

        rows, meta = list_rows_and_meta(
            api.list_loaner_sets(COMPLIANCE_ADMIN, {"surgical_case_id": case["id"]})
        )
        assert_total_count(meta, 2)
        assert sorted(ids_of(rows)) == sorted([first["id"], second["id"]]), (
            "the refused registration should have left no tray set behind"
        )
        assert_version_bumped(refreshed, read_case(api, case["id"]))


class TestComplianceStatusBandBoundary:
    """Two vendors one point apart, on opposite sides of the good-standing band."""

    def test_eighty_four_reads_watch_while_eighty_five_reads_in_good_standing(self, api):
        """Sixteen points of MAJOR findings watch a vendor; fifteen of MINOR do not.

        "`BARRED` below 40, `PROBATION` below 70, `WATCH` below 85, and
        `IN_GOOD_STANDING` at 85 or above", read off an incident penalty of "three
        points for each `MINOR`, eight for each `MAJOR`". Two substantiated MAJOR
        gift-policy findings leave one vendor at 84 and therefore on watch, while
        five substantiated MINOR findings leave the other at exactly 85 and in good
        standing, and neither finding is of the one type and severity that touches
        a representative.

        Design: Corner/cross-cutting complexity layers/rate_threshold_bands_split_eighty_four_from_eighty_five
        """
        facility = create_facility(
            api,
            "RT-68",
            name="Rate Threshold Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        watch_vendor = create_vendor(api, "WATCHV", legal_name="Watch Band Devices")
        wade = create_vendor_rep(api, watch_vendor["id"], "Wade Watch")
        good_vendor = create_vendor(api, "GOODV", legal_name="Good Standing Devices")
        gil = create_vendor_rep(api, good_vendor["id"], "Gil Good")
        watch_case = create_case(
            api,
            facility["id"],
            "CASE-15210",
            "2026-09-30T08:00:00Z",
            "2026-09-30T10:00:00Z",
            procedure_name="Watch Band Case",
        )
        good_case = create_case(
            api,
            facility["id"],
            "CASE-15211",
            "2026-09-30T12:00:00Z",
            "2026-09-30T14:00:00Z",
            procedure_name="Good Standing Case",
        )

        # The compliance programme reports; a colleague adjudicates each finding.
        major_narratives = (
            "Implant log missing for the first construct",
            "Second construct also undocumented",
        )
        for narrative in major_narratives:
            finding = report_incident(
                api,
                watch_case["id"],
                wade["id"],
                INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
                SEVERITY_MAJOR,
                headers=COMPLIANCE_ADMIN,
                narrative=narrative,
            )
            adjudicate_incident(
                api, finding["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN_2
            )

        minor_narratives = (
            "Loaner manifest page one unsigned",
            "Loaner manifest page two unsigned",
            "Tray count sheet unsigned",
            "Return manifest unsigned",
            "Sterilization sticker sheet unsigned",
        )
        for narrative in minor_narratives:
            finding = report_incident(
                api,
                good_case["id"],
                gil["id"],
                INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
                SEVERITY_MINOR,
                headers=COMPLIANCE_ADMIN,
                narrative=narrative,
            )
            adjudicate_incident(
                api, finding["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN_2
            )

        sweep = run_sweep(api, COMPLIANCE_ADMIN_2)

        watched = read_vendor(api, watch_vendor["id"])
        assert_integer_field(watched, "provisional_compliance_score", 84)
        assert_integer_field(watched, "adjudicated_compliance_score", 84)
        assert watched["compliance_status"] == STATUS_WATCH
        assert watched["scorecard_tier"] == TIER_STANDARD
        assert_integer_field(watched, "access_quota_in_effect", 4)

        standing = read_vendor(api, good_vendor["id"])
        assert_integer_field(standing, "provisional_compliance_score", 85)
        assert_integer_field(standing, "adjudicated_compliance_score", 85)
        assert standing["compliance_status"] == STATUS_IN_GOOD_STANDING
        assert standing["scorecard_tier"] == TIER_STANDARD
        assert_integer_field(standing, "access_quota_in_effect", 4)

        assert (
            standing["adjudicated_compliance_score"]
            - watched["adjudicated_compliance_score"]
            == 1
        ), "the two vendors should sit one point apart across the band boundary"

        assert_integer_field(sweep, "vendors_rescored_count", 2)
        assert_integer_field(sweep, "reps_suspended_count", 0)

        assert read_vendor_rep(api, wade["id"])["access_status"] == ACCESS_STATUS_PENDING
        assert read_vendor_rep(api, gil["id"])["access_status"] == ACCESS_STATUS_PENDING

        scorecard = read_scorecard(api, watch_vendor["id"])
        assert_integer_field(scorecard, "substantiated_incident_count", 2)


class TestApprovalSideEffectsAreVisibleImmediately:
    """One approval, then a fresh look at everything it was supposed to move."""

    def test_the_decision_body_and_the_next_reads_already_agree(self, api):
        """The badge window, the case posture and both counters need no second pass.

        "Action endpoints return the resource they acted upon in `data`, after all
        side effects and all derived-field recomputations have been applied, so a
        caller never has to re-read to see the consequences of its own call", and
        "Every cascade named in §3 is immediate and observable on the very next
        read." No sweep is run, and the coordinator's own response already carries
        the window derived from the site's default hour of lead and half hour of
        grace.

        Design: Corner/consistency model/approval_side_effects_are_visible_immediately
        """
        facility = create_facility(
            api,
            "IM-69",
            name="Immediate Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        assert_integer_field(
            facility, "badge_lead_minutes", DEFAULT_BADGE_LEAD_MINUTES
        )
        assert_integer_field(
            facility, "badge_grace_minutes", DEFAULT_BADGE_GRACE_MINUTES
        )
        vendor = create_vendor(api, "IMMV", legal_name="Immediate Devices")
        approved_product(
            api,
            vendor["id"],
            facility["id"],
            "IC-2100",
            410000,
            is_implant=True,
            product_name="Immediate Cage",
            manufacturer="Immv",
        )
        iris = credentialed_rep(
            api,
            vendor["id"],
            "Iris Immediate",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-15220",
            "2026-10-16T08:00:00Z",
            "2026-10-16T10:00:00Z",
            procedure_name="Immediate Fusion",
            implant_required=True,
        )

        before = read_case(api, case["id"])
        assert before["vendor_coverage_status"] == COVERAGE_UNCOVERED
        assert before["implant_readiness_status"] == READINESS_PENDING

        requested = request_authorization(
            api,
            case["id"],
            iris["id"],
            REQUESTED_ROLE_IMPLANT_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )

        decided = validate_success(
            api.decide_authorization(
                requested["id"], authorization_decision_payload("APPROVE"), OR_COORDINATOR
            ),
            200,
        )

        # The coordinator's own response already carries the reconciled row.
        assert decided["status"] == AUTH_STATUS_APPROVED
        assert_instant_equals(
            decided["badge_window_start_utc"],
            "2026-10-16T07:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            decided["badge_window_end_utc"],
            "2026-10-16T10:30:00Z",
            "badge_window_end_utc",
        )
        assert_integer_field(decided, "epoch_number", 0)
        assert decided["decided_by_user_id"] == USER_ORC_1
        assert_instant_equals(
            decided["decided_at_utc"], LOGICAL_CLOCK_DEFAULT_UTC, "decided_at_utc"
        )

        # Fresh reads taken straight afterwards, with no sweep in between.
        after = read_case(api, case["id"])
        assert after["vendor_coverage_status"] == COVERAGE_COVERED
        assert_integer_field(after, "approved_rep_count", 1)
        assert after["implant_readiness_status"] == READINESS_PENDING

        assert_integer_field(
            read_vendor(api, vendor["id"]), "authorizations_used_epoch", 1
        )
        assert_integer_field(
            read_vendor_rep(api, iris["id"]), "open_authorization_count", 1
        )
