"""Pinned arithmetic: delivery leads, the fee ceiling, posture input sets and projections."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    APPROVAL_VALIDITY_DAYS,
    AUTH_STATUS_APPROVED,
    BASE_SCORE,
    COMPLEXITY_HOURS,
    COMPLEXITY_IMPLANT_SPECIALTY,
    COVERAGE_AT_RISK,
    COVERAGE_COVERED,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    CREDENTIALING_OFFICER,
    FEE_STATUS_ASSESSED,
    FEE_STATUS_NONE,
    LATE_FEE_CAP_CENTS,
    LOANER_STATUS_EXPECTED,
    LOANER_STATUS_REJECTED_LATE,
    LOGICAL_CLOCK_DEFAULT_UTC,
    OR_COORDINATOR,
    PIR_STATUS_APPROVED,
    POSTURE_COMPLIANT,
    POSTURE_EXPIRING_SOON,
    POSTURE_INCOMPLETE,
    PRODUCT_STATUS_ACTIVE,
    READINESS_BLOCKED,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    SUSPENDED_REASON_NONE,
    USER_VAC_1,
    VALUE_ANALYSIS_APPROVER,
    W_LATE_DELIVERY,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    assert_total_count,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credential_decision_payload,
    decide_authorization,
    decide_value_analysis,
    endorse_pir,
    file_credential,
    late_fee_cents,
    list_rows_and_meta,
    loaner_lead_hours,
    make_vendor_admin_headers,
    open_pir,
    per_tray_late_charge_cents,
    read_authorization,
    read_case,
    read_loaner_set,
    read_pir,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    request_authorization,
    run_sweep,
    shift_instant,
    submit_pir,
    tray_surcharge_hours,
    validate_success,
    verify_credential,
)


class TestDeadlineConstants:
    """Three additive terms and no implant floor on a thirteen-tray specialty set."""

    def test_thirteen_tray_specialty_set_leads_the_case_by_seventeen_hours(self, api):
        """A 13-tray IMPLANT_SPECIALTY set at a five-hour site is due 17 hours ahead.

        "Add three terms to get the turnaround: the facility's
        `spd_turnaround_hours`, plus the reprocessing allowance for the set's
        complexity — two hours for `SIMPLE`, six hours for `COMPLEX`, ten hours
        for `IMPLANT_SPECIALTY` — plus the tray surcharge just derived." The
        procedure needs no implant, so the 24-hour floor stays out of the
        comparison and the lead is the bare turnaround of 5 + 10 + 2 hours.

        Design: Corner/calculations/deadline_applies_tray_surcharge_and_complexity_constants
        """
        facility = create_facility(
            api,
            "CA-40",
            name="Calculation Constants Hospital",
            spd_turnaround_hours=5,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "CALCV", legal_name="Calculation Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "SP-800",
            90000,
            is_implant=False,
            product_name="Specialty Power Tray",
            manufacturer="Calcv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-14001",
            "2026-10-20T12:00:00Z",
            "2026-10-20T14:00:00Z",
            procedure_name="Specialty Instrument Case",
        )

        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 13, COMPLEXITY_IMPLANT_SPECIALTY
        )

        # Thirteen trays take the top surcharge band and the specialty allowance.
        assert tray_surcharge_hours(13) == 2
        assert COMPLEXITY_HOURS[COMPLEXITY_IMPLANT_SPECIALTY] == 10
        assert (
            loaner_lead_hours(5, COMPLEXITY_IMPLANT_SPECIALTY, 13, False) == 17
        ), "a case with no implant requirement never reaches the 24-hour floor"

        stored = read_loaner_set(api, loaner["id"])
        assert_instant_equals(
            stored["required_delivery_deadline_utc"],
            "2026-10-19T19:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            stored["pinned_deadline_utc"], "2026-10-19T19:00:00Z", "pinned_deadline_utc"
        )
        assert_instant_equals(
            stored["spd_occupation_start_utc"],
            "2026-10-19T19:00:00Z",
            "spd_occupation_start_utc",
        )
        assert_instant_equals(
            stored["spd_occupation_end_utc"],
            "2026-10-20T12:00:00Z",
            "spd_occupation_end_utc",
        )
        assert stored["status"] == LOANER_STATUS_EXPECTED
        assert stored["fee_status"] == FEE_STATUS_NONE
        assert_money_cents(stored, "assessed_late_fee_cents", 0)


class TestLateFeeCeiling:
    """A twenty-tray specialty set fifty hours late runs into the fee ceiling."""

    def test_raw_fee_of_two_hundred_sixty_two_thousand_five_hundred_is_clamped(self, api):
        """3000 late minutes on twenty specialty trays are billed at the 250,000-cent ceiling.

        "Second, multiply the rounded per-tray charge by `tray_count` to get the
        raw fee. Third, take the lesser of the raw fee and the cap of 250,000
        cents, and store the result in `assessed_late_fee_cents`." The clamp
        therefore bites after the multiplication, so the raw 262,500 cents is
        stored as exactly the ceiling.

        Design: Corner/calculations/late_fee_cap_clamps_raw_fee_at_the_declared_ceiling
        """
        facility = create_facility(
            api,
            "CP-41",
            name="Capped Fee Hospital",
            spd_turnaround_hours=8,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "CAPV", legal_name="Capped Fee Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CH-900",
            800000,
            is_implant=True,
            product_name="Capped Hip Stem",
            manufacturer="Capv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-14101",
            "2026-10-25T08:00:00Z",
            "2026-10-25T11:00:00Z",
            procedure_name="Capped Arthroplasty",
            implant_required=True,
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 20, COMPLEXITY_IMPLANT_SPECIALTY
        )

        # The implant floor of 24 hours beats the 20-hour turnaround on this case.
        assert loaner_lead_hours(8, COMPLEXITY_IMPLANT_SPECIALTY, 20, True) == 24
        registered = read_loaner_set(api, loaner["id"])
        assert_instant_equals(
            registered["required_delivery_deadline_utc"],
            "2026-10-24T08:00:00Z",
            "required_delivery_deadline_utc",
        )

        received = receive_loaner_set(api, loaner["id"], "2026-10-26T10:00:00Z")

        # Fifty hours past the deadline, and the tray charge rounds before scaling.
        assert per_tray_late_charge_cents(3000, COMPLEXITY_IMPLANT_SPECIALTY) == 13125
        assert 13125 * 20 == 262500, "the uncapped raw fee overshoots the ceiling"
        assert late_fee_cents(3000, 20, COMPLEXITY_IMPLANT_SPECIALTY) == LATE_FEE_CAP_CENTS

        assert received["status"] == LOANER_STATUS_REJECTED_LATE
        stored = read_loaner_set(api, loaner["id"])
        assert_integer_field(stored, "late_minutes_current_basis", 3000)
        assert_integer_field(stored, "late_minutes_pinned_basis", 3000)
        assert_money_cents(stored, "assessed_late_fee_cents", 250000)
        assert stored["fee_status"] == FEE_STATUS_ASSESSED

        billed = read_vendor(api, vendor["id"])
        assert_money_cents(billed, "late_fee_balance_cents", 250000)
        assert_integer_field(
            billed, "provisional_compliance_score", BASE_SCORE - W_LATE_DELIVERY
        )
        assert_integer_field(
            billed, "adjudicated_compliance_score", BASE_SCORE - W_LATE_DELIVERY
        )

        blocked = read_case(api, case["id"])
        assert blocked["implant_readiness_status"] == READINESS_BLOCKED


class TestPostureInputSet:
    """Only verified and expiring cover a gating type; rejected and pending cover nothing."""

    def test_replacement_background_check_only_covers_its_type_once_verified(self, api):
        """A rejected and a pending background check leave the posture INCOMPLETE.

        "Collect the set of credential types held by credentials of that
        representative whose `status` is either `VERIFIED` or `EXPIRING_SOON`;
        these are the *covered* types. Credentials in `PENDING_VERIFICATION`,
        `REJECTED` or `EXPIRED` never contribute to that set." Fay holds three
        gating types outright, so the fourth is what decides her posture, and it
        only counts from the moment the replacement attestation is verified.

        Design: Corner/calculations/posture_input_set_ignores_rejected_and_pending_credentials
        """
        vendor = create_vendor(api, "FILTV", legal_name="Filtered Input Devices")
        rep = create_vendor_rep(api, vendor["id"], "Fay Filter", email="fay@filtv.example")

        for credential_type, reference in (
            (CREDENTIAL_TYPE_INFLUENZA, "FLU-FI-01"),
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-FI-01"),
            (CREDENTIAL_TYPE_COI, "COI-FI-01"),
        ):
            filed = file_credential(
                api,
                rep["id"],
                credential_type,
                issued_at_utc="2026-07-01T00:00:00Z",
                expires_at_utc="2027-07-01T00:00:00Z",
                document_reference=reference,
            )
            verify_credential(api, filed["id"])

        first_check = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="BGC-FI-01",
        )
        validate_success(
            api.decide_credential(
                first_check["id"],
                credential_decision_payload(
                    "REJECT",
                    "Screening vendor could not confirm the identity documents",
                ),
                CREDENTIALING_OFFICER,
            ),
            200,
        )

        # The rejected slot is free again, so a replacement may be filed.
        second_check = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc="2026-07-15T00:00:00Z",
            expires_at_utc="2027-07-15T00:00:00Z",
            document_reference="BGC-FI-02",
        )
        before = read_vendor_rep(api, rep["id"])
        assert before["credential_posture"] == POSTURE_INCOMPLETE, (
            "neither the rejected nor the pending background check covers the type"
        )

        verify_credential(api, second_check["id"])

        cleared = read_vendor_rep(api, rep["id"])
        assert cleared["credential_posture"] == POSTURE_COMPLIANT
        assert cleared["access_status"] == ACCESS_STATUS_CREDENTIALED

        rows, meta = list_rows_and_meta(
            api.list_rep_credentials(
                rep["id"],
                CREDENTIALING_OFFICER,
                {"credential_type": CREDENTIAL_TYPE_BACKGROUND},
            )
        )
        assert_total_count(meta, 2)
        by_id = {row["id"]: row for row in rows}
        assert by_id[first_check["id"]]["status"] == "REJECTED"
        assert (
            by_id[first_check["id"]]["rejection_reason"]
            == "Screening vendor could not confirm the identity documents"
        )
        assert by_id[second_check["id"]]["status"] == "VERIFIED"


class TestApprovalValidityWindow:
    """The minted product carries a 365-day approval, not a calendar year."""

    def test_approval_at_the_default_instant_expires_three_hundred_sixty_five_days_later(
        self, api
    ):
        """Approving at the startup instant mints a product valid to 2027-08-01T00:00:00Z.

        "It records `product_introduction_request_id` pointing back at the
        request, `pinned_pir_version` capturing the request's `version` observed
        at the moment of approval, `approved_at_utc` from the logical clock, and
        `approval_expires_at_utc` exactly 365 days after `approved_at_utc`."
        Every descriptive field is copied from the request as it stood at the
        vote.

        Design: Corner/calculations/approved_product_expiry_lands_three_hundred_sixty_five_days_out
        """
        facility = create_facility(
            api,
            "AE-42",
            name="Approval Expiry Hospital",
            spd_turnaround_hours=5,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "APEXV", legal_name="Apex Expiry Devices")
        pir = open_pir(
            api,
            vendor["id"],
            facility["id"],
            "AL-1000",
            320000,
            is_implant=True,
            product_name="Apex Locking Plate",
            manufacturer="Apexv Ortho",
        )
        submit_pir(api, vendor["id"], pir["id"])
        endorse_pir(api, pir["id"])

        decide_value_analysis(api, pir["id"], "APPROVE")

        approved = read_pir(api, pir["id"])
        assert approved["status"] == PIR_STATUS_APPROVED
        assert approved["value_analysis_user_id"] == USER_VAC_1
        assert_instant_equals(
            approved["decided_at_utc"], LOGICAL_CLOCK_DEFAULT_UTC, "decided_at_utc"
        )

        rows, meta = list_rows_and_meta(
            api.list_approved_products(
                VALUE_ANALYSIS_APPROVER, {"product_introduction_request_id": pir["id"]}
            )
        )
        assert_total_count(meta, 1)
        product = rows[0]

        assert_instant_equals(
            product["approved_at_utc"], "2026-08-01T00:00:00Z", "approved_at_utc"
        )
        assert_instant_equals(
            product["approval_expires_at_utc"],
            "2027-08-01T00:00:00Z",
            "approval_expires_at_utc",
        )
        # Exactly 365 days of shelf life, counted in days rather than calendars.
        assert_instant_equals(
            product["approval_expires_at_utc"],
            shift_instant("2026-08-01T00:00:00Z", days=APPROVAL_VALIDITY_DAYS),
            "approval_expires_at_utc",
        )

        assert product["status"] == PRODUCT_STATUS_ACTIVE
        assert product["suspended_reason"] == SUSPENDED_REASON_NONE
        assert product["product_introduction_request_id"] == pir["id"]
        assert product["product_name"] == "Apex Locking Plate"
        assert product["product_catalog_number"] == "AL-1000"
        assert product["manufacturer"] == "Apexv Ortho"
        assert product["is_implant"] is True
        assert_money_cents(product, "unit_cost_cents", 320000)

        settled = read_vendor(api, vendor["id"])
        assert_integer_field(settled, "open_pir_count", 0)


class TestCoverageProjection:
    """Coverage re-derives from the covering rep's posture, not from the authorization."""

    def test_warning_a_covering_reps_influenza_shot_moves_coverage_to_at_risk(self, api):
        """The sweep's expiry warning alone drags a fully approved case to AT_RISK.

        "Otherwise, if any approved authorization belongs to a representative
        whose `credential_posture` is `EXPIRING_SOON`, or if the case's
        `revoked_authorization_count` is at least one, the posture is `AT_RISK`."
        Pia's influenza shot lapses inside the fortnight the sweep warns on, so
        her posture slips while her authorization stays exactly as approved.

        Design: Corner/calculations/coverage_projection_turns_at_risk_when_a_covering_rep_is_expiring_soon
        """
        facility = create_facility(
            api,
            "PJ-43",
            name="Projection Hospital",
            spd_turnaround_hours=5,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "PROJV", legal_name="Projection Devices")
        approved_product(
            api,
            vendor["id"],
            facility["id"],
            "PN-1100",
            280000,
            is_implant=True,
            product_name="Projection Nail",
            manufacturer="Projv",
        )
        rep = create_vendor_rep(api, vendor["id"], "Pia Project", email="pia@projv.example")

        # The influenza shot lapses on 2026-08-10, nine days after the clock.
        flu = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2025-08-10T00:00:00Z",
            expires_at_utc="2026-08-10T00:00:00Z",
            document_reference="FLU-PJ-01",
        )
        verify_credential(api, flu["id"])
        for credential_type, reference in (
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-PJ-01"),
            (CREDENTIAL_TYPE_BACKGROUND, "BGC-PJ-01"),
            (CREDENTIAL_TYPE_COI, "COI-PJ-01"),
        ):
            filed = file_credential(
                api,
                rep["id"],
                credential_type,
                issued_at_utc="2026-07-01T00:00:00Z",
                expires_at_utc="2027-07-01T00:00:00Z",
                document_reference=reference,
            )
            verify_credential(api, filed["id"])

        case = create_case(
            api,
            facility["id"],
            "CASE-14301",
            "2026-08-20T08:00:00Z",
            "2026-08-20T10:00:00Z",
            procedure_name="Projection Nailing",
            implant_required=True,
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_TECHNICAL_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        authorization = decide_authorization(
            api, requested["id"], "APPROVE", headers=OR_COORDINATOR
        )
        assert authorization["status"] == AUTH_STATUS_APPROVED

        covered = read_case(api, case["id"])
        assert covered["vendor_coverage_status"] == COVERAGE_COVERED

        sweep = run_sweep(api)

        assert_integer_field(sweep, "credentials_warned_count", 1)
        assert_integer_field(sweep, "credentials_expired_count", 0)
        assert_integer_field(sweep, "reps_suspended_count", 0)
        assert_integer_field(sweep, "authorizations_revoked_count", 0)

        warned = read_vendor_rep(api, rep["id"])
        assert warned["credential_posture"] == POSTURE_EXPIRING_SOON
        assert warned["access_status"] == ACCESS_STATUS_CREDENTIALED, (
            "a warning is not a suspension"
        )

        held = read_authorization(api, authorization["id"])
        assert held["status"] == AUTH_STATUS_APPROVED
        assert_instant_equals(
            held["badge_window_start_utc"],
            "2026-08-20T07:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            held["badge_window_end_utc"], "2026-08-20T10:30:00Z", "badge_window_end_utc"
        )

        at_risk = read_case(api, case["id"])
        assert_integer_field(at_risk, "approved_rep_count", 1)
        assert_integer_field(at_risk, "revoked_authorization_count", 0)
        assert at_risk["vendor_coverage_status"] == COVERAGE_AT_RISK

        rescored = read_vendor(api, vendor["id"])
        assert_integer_field(rescored, "adjudicated_compliance_score", BASE_SCORE)
        assert_integer_field(rescored, "access_quota_in_effect", 6)
        assert_integer_field(rescored, "authorizations_used_epoch", 0)
