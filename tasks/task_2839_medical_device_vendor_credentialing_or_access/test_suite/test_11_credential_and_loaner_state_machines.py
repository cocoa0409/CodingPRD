"""Lifecycles of an attestation, a tray set and a badge, walked one hop at a time."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_PENDING,
    AUTH_STATUS_REQUESTED,
    COMPLEXITY_SIMPLE,
    COMPLIANCE_ADMIN,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    CREDENTIALING_OFFICER,
    ERR_AUTHORIZATION_NOT_APPROVED,
    ERR_CREDENTIAL_NOT_PENDING,
    ERR_LOANER_SET_INVALID_STATE,
    FEE_STATUS_NONE,
    LOANER_STATUS_EXPECTED,
    LOANER_STATUS_RELEASED,
    POSTURE_COMPLIANT,
    POSTURE_INCOMPLETE,
    READINESS_NOT_APPLICABLE,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    STERILE_PROCESSING_TECH,
    SUSPENSION_REASON_NONE,
    USER_CREDENTIALING_1,
    approved_product,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    assert_money_cents,
    assert_total_count,
    check_in_payload,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credential_decision_payload,
    credential_rep,
    file_credential,
    find_by_id,
    list_rows_and_meta,
    make_vendor_admin_headers,
    make_vendor_rep_headers,
    read_authorization,
    read_case,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    receive_payload,
    register_loaner_set,
    release_loaner_set,
    request_authorization,
    set_clock,
    validate_error,
    verify_credential,
)


class TestCredentialLifecycle:
    """An attestation from the moment the vendor files it to the officer's ruling."""

    def test_freshly_filed_credential_is_pending_and_leaves_the_rep_inert(self, api):
        """Filing a background check leaves the attestation unverified and the rep untouched.

        "A newly filed credential lands in `PENDING_VERIFICATION`, and filing it
        changes nothing about the representative: a pending attestation covers
        nothing, so `credential_posture` is left exactly as it was."

        Design: Corner/state_machines/credential_created_starts_in_pending_verification
        """
        vendor = create_vendor(api, "INITV", legal_name="Initial State Devices")
        rep = create_vendor_rep(api, vendor["id"], "Ivan Init")

        filed = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="BGC-INIT-01",
        )

        assert filed["status"] == "PENDING_VERIFICATION"
        assert filed["verified_by_user_id"] is None, (
            "nobody has ruled on the attestation yet"
        )
        assert_instant_is_none(filed, "verified_at_utc")
        assert filed["rejection_reason"] is None

        untouched = read_vendor_rep(api, rep["id"])
        assert untouched["credential_posture"] == POSTURE_INCOMPLETE
        assert untouched["access_status"] == ACCESS_STATUS_PENDING

    def test_one_verification_stamps_the_officer_but_not_the_rep(self, api):
        """Verifying the first of four gating attestations moves only the credential.

        "A verification moves the credential `PENDING_VERIFICATION → VERIFIED`
        and stamps `verified_by_user_id` with the officer's `X-User-ID` and
        `verified_at_utc` with the logical clock's current instant." Influenza,
        bloodborne-pathogens training and the gift attestation are all still
        uncovered, and "If even one of the four gating types is not covered, the
        posture is ... `INCOMPLETE` when it is false."

        Design: Corner/state_machines/single_credential_verification_transitions_to_verified
        """
        vendor = create_vendor(api, "ONEV", legal_name="One Step Devices")
        rep = create_vendor_rep(api, vendor["id"], "Olive One")
        filed = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="BGC-ONE-01",
        )

        verified = verify_credential(api, filed["id"])

        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_CREDENTIALING_1
        assert_instant_equals(
            verified["verified_at_utc"], "2026-08-01T00:00:00Z", "verified_at_utc"
        )

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["credential_posture"] == POSTURE_INCOMPLETE, (
            "three gating attestations are still missing from the roster file"
        )
        assert stored_rep["access_status"] == ACCESS_STATUS_PENDING
        assert stored_rep["ever_credentialed"] is False

    def test_fourth_verification_carries_the_rep_to_credentialed(self, api):
        """The fourth gating attestation fires every access side effect at once.

        "When a verification leaves the representative with a posture of
        `COMPLIANT` or `EXPIRING_SOON`, `access_status` advances
        `PENDING_CREDENTIALING → CREDENTIALED`, `ever_credentialed` is set true,
        and `suspension_reason` is set to `NONE`."

        Design: Corner/state_machines/fourth_credential_verification_credentials_the_rep
        """
        vendor = create_vendor(api, "FOURV", legal_name="Fourth Step Devices")
        rep = create_vendor_rep(api, vendor["id"], "Frank Fourth")
        for credential_type, reference in (
            (CREDENTIAL_TYPE_INFLUENZA, "FLU-FOUR-01"),
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-FOUR-01"),
            (CREDENTIAL_TYPE_BACKGROUND, "BGC-FOUR-01"),
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
        gift_attestation = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_COI,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="COI-FOUR-01",
        )

        before = read_vendor_rep(api, rep["id"])
        assert before["credential_posture"] == POSTURE_INCOMPLETE, (
            "three verifications on their own clear nobody for the theatre"
        )
        assert before["access_status"] == ACCESS_STATUS_PENDING

        fourth = verify_credential(api, gift_attestation["id"])
        assert fourth["status"] == "VERIFIED"

        cleared = read_vendor_rep(api, rep["id"])
        assert cleared["credential_posture"] == POSTURE_COMPLIANT
        assert cleared["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert cleared["ever_credentialed"] is True
        assert cleared["suspension_reason"] == SUSPENSION_REASON_NONE

        rows, meta = list_rows_and_meta(
            api.list_rep_credentials(rep["id"], COMPLIANCE_ADMIN)
        )
        assert_total_count(meta, 4)
        assert [row["status"] for row in rows] == ["VERIFIED"] * 4, (
            "the whole attestation file should read as verified"
        )

    def test_second_verification_is_refused_and_keeps_the_first_stamp(self, api):
        """A re-ruling on a verified attestation is refused rather than re-stamped.

        "**Credential pending** — the target credential is in
        `PENDING_VERIFICATION`, else `ERR_CREDENTIAL_NOT_PENDING` (409). Applies
        to the credential verify/reject decision."

        Design: Corner/state_machines/credential_verify_twice_rejects_second_decision
        """
        vendor = create_vendor(api, "TWICV", legal_name="Twice Verified Devices")
        rep = create_vendor_rep(api, vendor["id"], "Tess Twice")
        filed = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
            document_reference="BGC-TWICE-01",
        )
        verified = verify_credential(api, filed["id"])
        set_clock(api, "2026-08-03T00:00:00Z")

        validate_error(
            api.decide_credential(
                filed["id"], credential_decision_payload("VERIFY"), CREDENTIALING_OFFICER
            ),
            ERR_CREDENTIAL_NOT_PENDING,
        )

        rows, _meta = list_rows_and_meta(
            api.list_rep_credentials(rep["id"], COMPLIANCE_ADMIN)
        )
        stored = find_by_id(rows, filed["id"])
        assert stored["status"] == "VERIFIED"
        assert_instant_equals(
            stored["verified_at_utc"], "2026-08-01T00:00:00Z", "verified_at_utc"
        )
        assert_integer_field(stored, "version", verified["version"])


class TestLoanerSetStateMachine:
    """A tray set may only be released from the dock it was actually received at."""

    def test_release_before_the_dock_is_refused_and_the_set_stays_expected(self, api):
        """Sterile processing cannot walk an undelivered tray set into the theatre.

        "receiving requires `EXPECTED`, and releasing requires
        `DELIVERED_ON_TIME` or `DELIVERED_LATE`, else
        `ERR_LOANER_SET_INVALID_STATE` (409)", and on a case without an implant
        "If the case's `implant_required` is false, the posture is
        `NOT_APPLICABLE`."

        Design: Corner/state_machines/loaner_set_release_before_receive_rejected
        """
        facility = create_facility(
            api,
            "RB-31",
            name="Release Before Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "RELBV", legal_name="Release Before Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "RT-200",
            30000,
            is_implant=False,
            product_name="Retractor Tray",
            manufacturer="Relbv",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-13101",
            "2026-10-08T08:00:00Z",
            "2026-10-08T10:00:00Z",
            procedure_name="Retractor Case",
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 2, COMPLEXITY_SIMPLE
        )
        assert loaner["status"] == LOANER_STATUS_EXPECTED

        validate_error(
            api.release_loaner_set(loaner["id"], {}, STERILE_PROCESSING_TECH),
            ERR_LOANER_SET_INVALID_STATE,
        )

        stored = read_loaner_set(api, loaner["id"])
        assert stored["status"] == LOANER_STATUS_EXPECTED
        assert_instant_is_none(stored, "delivered_at_utc")
        assert_instant_equals(
            stored["required_delivery_deadline_utc"],
            "2026-10-08T02:00:00Z",
            "required_delivery_deadline_utc",
        )

        stored_case = read_case(api, case["id"])
        assert stored_case["implant_readiness_status"] == READINESS_NOT_APPLICABLE

    def test_released_set_refuses_both_of_its_own_action_endpoints(self, api):
        """Once the trays are in the theatre neither dock action reopens the set.

        "Release to the operating room is the join point of the delivery fork" and
        "`RELEASED_TO_OR` is terminal", so both dock actions fall foul of the rule
        that "receiving requires `EXPECTED`, and releasing requires
        `DELIVERED_ON_TIME` or `DELIVERED_LATE`, else
        `ERR_LOANER_SET_INVALID_STATE` (409)".

        Design: Corner/state_machines/released_loaner_set_terminal_lockdown_rejects_receive_and_release
        """
        facility = create_facility(
            api,
            "TL-32",
            name="Terminal Lock Hospital",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "TLOCK", legal_name="Terminal Lock Devices")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "CT-300",
            20000,
            is_implant=False,
            product_name="Clamp Tray",
            manufacturer="Tlock",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-13201",
            "2026-10-10T08:00:00Z",
            "2026-10-10T10:00:00Z",
            procedure_name="Clamp Case",
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 2, COMPLEXITY_SIMPLE
        )
        receive_loaner_set(api, loaner["id"])
        released = release_loaner_set(api, loaner["id"])
        assert released["status"] == LOANER_STATUS_RELEASED
        set_clock(api, "2026-08-02T00:00:00Z")

        validate_error(
            api.receive_loaner_set(loaner["id"], receive_payload(), STERILE_PROCESSING_TECH),
            ERR_LOANER_SET_INVALID_STATE,
        )
        validate_error(
            api.release_loaner_set(loaner["id"], {}, STERILE_PROCESSING_TECH),
            ERR_LOANER_SET_INVALID_STATE,
        )

        stored = read_loaner_set(api, loaner["id"])
        assert stored["status"] == LOANER_STATUS_RELEASED
        assert_instant_equals(
            stored["delivered_at_utc"], "2026-08-01T00:00:00Z", "delivered_at_utc"
        )
        assert_integer_field(stored, "late_minutes_current_basis", 0)
        assert_money_cents(stored, "assessed_late_fee_cents", 0)
        assert stored["fee_status"] == FEE_STATUS_NONE

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 0)


class TestKioskBadgePrecondition:
    """A badge is minted from an approved authorization and from nothing else."""

    def test_kiosk_refuses_a_badge_on_an_undecided_authorization(self, api):
        """A fully credentialed rep inside the badge window still gets no badge.

        "Before a badge prints, the server insists that the referenced
        authorization is `APPROVED`", because "the target authorization is in
        `APPROVED`, else `ERR_AUTHORIZATION_NOT_APPROVED` (409)".

        Design: Corner/state_machines/kiosk_check_in_on_requested_authorization_rejected
        """
        facility = create_facility(
            api,
            "PC-33",
            name="Precondition Hospital",
            spd_turnaround_hours=5,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "PRECV", legal_name="Precondition Devices")
        rep = create_vendor_rep(api, vendor["id"], "Pia Precon")
        credential_rep(
            api,
            rep["id"],
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-13301",
            "2026-08-06T08:00:00Z",
            "2026-08-06T10:00:00Z",
            procedure_name="Precondition Case",
        )
        authorization = request_authorization(
            api,
            case["id"],
            rep["id"],
            REQUESTED_ROLE_TECHNICAL_SUPPORT,
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        # Half an hour before the knife, well inside the window an approval would
        # have opened, so only the undecided request can explain the refusal.
        set_clock(api, "2026-08-06T07:30:00Z")

        validate_error(
            api.create_check_in(
                check_in_payload(authorization["id"]),
                make_vendor_rep_headers(rep["id"]),
            ),
            ERR_AUTHORIZATION_NOT_APPROVED,
        )

        stored_auth = read_authorization(api, authorization["id"])
        assert stored_auth["status"] == AUTH_STATUS_REQUESTED
        assert_instant_is_none(stored_auth, "badge_window_start_utc")
        assert_instant_is_none(stored_auth, "badge_window_end_utc")

        _rows, meta = list_rows_and_meta(
            api.list_authorization_check_ins(authorization["id"], COMPLIANCE_ADMIN)
        )
        assert_total_count(meta, 0)

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["credential_posture"] == POSTURE_COMPLIANT
        assert_integer_field(stored_rep, "open_authorization_count", 0)

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "authorizations_used_epoch", 0)
