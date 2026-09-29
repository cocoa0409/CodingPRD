"""Boundaries that turn on one second of clock and on a tray count of zero.

Two unrelated inclusive comparisons are pinned here. A sweep observing a
credential whose expiry falls at exactly the sweep instant retires it, while the
attestation that lapses one second later is merely warned; and a tray set that
arrives late carrying no trays at all earns a positive per-tray charge and still
owes the hospital nothing.
"""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_SUSPENDED,
    COMPLEXITY_SIMPLE,
    COMPLIANCE_ADMIN,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    FEE_STATUS_ASSESSED,
    FEE_STATUS_WAIVED,
    LOANER_STATUS_DELIVERED_LATE,
    POSTURE_LAPSED,
    READINESS_NOT_APPLICABLE,
    STATUS_IN_GOOD_STANDING,
    SUSPENSION_REASON_CREDENTIAL_LAPSED,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    file_credential,
    find_by_id,
    list_rows,
    read_case,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    run_sweep,
    set_clock,
    shift_instant,
    verify_credential,
)

# The instant the compliance sweep observes, and the instant one second past it.
SWEEP_INSTANT_UTC = "2026-09-01T00:00:00Z"
ONE_SECOND_AFTER_SWEEP_UTC = shift_instant(SWEEP_INSTANT_UTC, seconds=1)

# Two attestations issued a year before each of those instants.
INFLUENZA_ISSUED_UTC = shift_instant(SWEEP_INSTANT_UTC, days=-365)
BLOODBORNE_ISSUED_UTC = shift_instant(ONE_SECOND_AFTER_SWEEP_UTC, days=-365)

# The background check and the gift attestation sit far outside the warning window.
FAR_ISSUED_UTC = "2026-07-01T00:00:00Z"
FAR_EXPIRY_UTC = "2027-07-01T00:00:00Z"

# The zero-tray arthroscopy case, its derived deadline and its late delivery.
CASE_START_UTC = "2026-09-18T12:00:00Z"
CASE_END_UTC = "2026-09-18T14:00:00Z"
DELIVERY_DEADLINE_UTC = shift_instant(CASE_START_UTC, hours=-10)
DELIVERED_AT_UTC = shift_instant(DELIVERY_DEADLINE_UTC, minutes=45)


class TestCredentialExpiryEqualityBoundary:
    """One second decides whether Yuki Tanaka's attestation retires or is warned."""

    @staticmethod
    def _swept_at_the_influenza_expiry(api):
        """Credential four attestations, then sweep at exactly the influenza expiry."""
        create_facility(
            api,
            "SB-11",
            name="Southbank Dermatology Surgery",
            spd_turnaround_hours=4,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "DERMA", legal_name="Dermatech Surgical Ltd")
        rep = create_vendor_rep(
            api,
            vendor["id"],
            "Yuki Tanaka",
            email="yuki.tanaka@dermatech.example",
        )

        influenza = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc=INFLUENZA_ISSUED_UTC,
            expires_at_utc=SWEEP_INSTANT_UTC,
            document_reference="IMM-YUKI-01",
        )
        verify_credential(api, influenza["id"])

        bloodborne = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BLOODBORNE,
            issued_at_utc=BLOODBORNE_ISSUED_UTC,
            expires_at_utc=ONE_SECOND_AFTER_SWEEP_UTC,
            document_reference="BBP-YUKI-01",
        )
        verify_credential(api, bloodborne["id"])

        background = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_BACKGROUND,
            issued_at_utc=FAR_ISSUED_UTC,
            expires_at_utc=FAR_EXPIRY_UTC,
            document_reference="BGC-YUKI-01",
        )
        verify_credential(api, background["id"])

        gift = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_COI,
            issued_at_utc=FAR_ISSUED_UTC,
            expires_at_utc=FAR_EXPIRY_UTC,
            document_reference="COI-YUKI-01",
        )
        verify_credential(api, gift["id"])

        set_clock(api, SWEEP_INSTANT_UTC)
        sweep = run_sweep(api)
        held = list_rows(api.list_rep_credentials(rep["id"], COMPLIANCE_ADMIN))
        return vendor, rep, sweep, held, {
            "influenza": influenza["id"],
            "bloodborne": bloodborne["id"],
            "background": background["id"],
            "gift": gift["id"],
        }

    def test_influenza_expiring_at_exactly_the_sweep_instant_retires(self, api):
        """An expiry equal to the sweep instant retires the influenza attestation.

        "Every `VERIFIED` credential whose `expires_at_utc` is at or before
        `swept_at_utc` moves to `EXPIRED` — equality expires, the boundary is
        inclusive ... each such move increments `credentials_expired_count`."

        Design: Difficulty/boundary_precision_check/credential_expiry_equality_expires_one_second_later_only_warns
        """
        _vendor, _rep, sweep, held, ids = self._swept_at_the_influenza_expiry(api)

        assert_instant_equals(sweep["swept_at_utc"], SWEEP_INSTANT_UTC, "swept_at_utc")

        influenza = find_by_id(held, ids["influenza"])
        assert_instant_equals(
            influenza["expires_at_utc"], SWEEP_INSTANT_UTC, "expires_at_utc"
        )
        assert influenza["status"] == "EXPIRED", (
            "an expiry landing exactly on the sweep instant should retire the attestation"
        )
        assert_integer_field(sweep, "credentials_expired_count", 1)

    def test_bloodborne_expiring_one_second_later_is_only_warned(self, api):
        """One second past the sweep instant the training is warned, not retired.

        "Every `VERIFIED` credential that has not yet expired but whose
        `expires_at_utc` falls at or before `swept_at_utc` plus fourteen days
        moves `VERIFIED → EXPIRING_SOON` and increments
        `credentials_warned_count`."

        Design: Difficulty/boundary_precision_check/credential_expiry_equality_expires_one_second_later_only_warns
        """
        _vendor, _rep, sweep, held, ids = self._swept_at_the_influenza_expiry(api)

        bloodborne = find_by_id(held, ids["bloodborne"])
        assert_instant_equals(
            bloodborne["expires_at_utc"], ONE_SECOND_AFTER_SWEEP_UTC, "expires_at_utc"
        )
        assert bloodborne["status"] == "EXPIRING_SOON", (
            "an attestation lapsing one second after the sweep should only be warned"
        )
        assert_integer_field(sweep, "credentials_warned_count", 1)

        for key in ("background", "gift"):
            far = find_by_id(held, ids[key])
            assert far["status"] == "VERIFIED", (
                "an attestation expiring in ten months is outside the warning window"
            )

    def test_the_retired_type_alone_lapses_the_posture_and_suspends_the_rep(self, api):
        """The single uncovered type lapses Yuki Tanaka while the warned type still covers.

        "If even one of the four gating types is not covered, the posture is
        `LAPSED` when the representative's `ever_credentialed` flag is true", and
        "a `CREDENTIALED` representative whose posture is now `LAPSED` moves
        `CREDENTIALED → SUSPENDED` with `suspension_reason` set to
        `CREDENTIAL_LAPSED`, incrementing `reps_suspended_count`".

        Design: Difficulty/boundary_precision_check/credential_expiry_equality_expires_one_second_later_only_warns
        """
        vendor, rep, sweep, _held, _ids = self._swept_at_the_influenza_expiry(api)

        assert_integer_field(sweep, "reps_suspended_count", 1)

        suspended = read_vendor_rep(api, rep["id"])
        assert suspended["credential_posture"] == POSTURE_LAPSED, (
            "the retired influenza type is uncovered, while the warned training "
            "attestation still covers its own type"
        )
        assert suspended["access_status"] == ACCESS_STATUS_SUSPENDED
        assert suspended["suspension_reason"] == SUSPENSION_REASON_CREDENTIAL_LAPSED
        assert suspended["ever_credentialed"] is True

        # "The lapsed-representative penalty is six points for each of the
        # vendor's representatives counted as lapsed at the last sweep."
        rescored = read_vendor(api, vendor["id"])
        assert_integer_field(rescored, "adjudicated_compliance_score", 94)
        assert rescored["compliance_status"] == STATUS_IN_GOOD_STANDING


class TestZeroTrayLateDeliveryFeeFloor:
    """A late tray set carrying no trays owes a positive rate on nothing at all."""

    @staticmethod
    def _late_delivery_with(api, tray_count):
        """Stage the Zenith arthroscopy case and deliver its tray set 45 minutes late."""
        facility = create_facility(
            api,
            "ZT-12",
            name="Zenith Day Surgery",
            spd_turnaround_hours=8,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "ZEROT", legal_name="Zerotech Instruments Ltd")
        _request, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "AS-220",
            90000,
            is_implant=False,
            product_name="Arthroscopy Shaver Handpiece",
            manufacturer="Zerotech",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-9901",
            CASE_START_UTC,
            CASE_END_UTC,
            procedure_name="Knee Arthroscopy",
            implant_required=False,
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], tray_count, COMPLEXITY_SIMPLE
        )
        received = receive_loaner_set(api, loaner["id"], DELIVERED_AT_UTC)
        return vendor, case, loaner, received

    def test_zero_tray_set_lands_late_on_a_real_deadline_with_no_fee_owed(self, api):
        """Forty-five minutes late with no trays waives the charge and spares the ledger.

        "Second, multiply the rounded per-tray charge by `tray_count` to get the
        raw fee ... The accompanying `fee_status` is decided in this order:
        `NONE` when `late_minutes_current_basis` is zero, otherwise `WAIVED`
        when `tray_count` is zero, otherwise `ASSESSED`."

        Design: Difficulty/boundary_precision_check/zero_tray_late_set_computes_positive_per_tray_rate_but_zero_fee
        """
        vendor, _case, loaner, received = self._late_delivery_with(api, 0)

        assert_instant_equals(
            received["required_delivery_deadline_utc"],
            DELIVERY_DEADLINE_UTC,
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            received["pinned_deadline_utc"], DELIVERY_DEADLINE_UTC, "pinned_deadline_utc"
        )
        assert_integer_field(received, "late_minutes_current_basis", 45)
        assert_integer_field(received, "late_minutes_pinned_basis", 45)
        assert received["status"] == LOANER_STATUS_DELIVERED_LATE, (
            "forty-five minutes sits inside the two-hour hard-reject grace"
        )

        stored = read_loaner_set(api, loaner["id"])
        assert_money_cents(stored, "assessed_late_fee_cents", 0)
        assert stored["fee_status"] == FEE_STATUS_WAIVED

        # "only sets whose `fee_status` is `ASSESSED` contribute to the vendor's
        # `late_fee_balance_cents`"
        billed = read_vendor(api, vendor["id"])
        assert_money_cents(billed, "late_fee_balance_cents", 0)

    def test_one_tray_at_the_same_lateness_bills_the_positive_per_tray_rate(self, api):
        """A single tray at the identical lateness bills 113 cents, so the rate is positive.

        "multiply `late_minutes_current_basis` by the base rate of 2.5 cents per
        tray per minute, then by the complexity multiplier — one for `SIMPLE` ...
        and **round that per-tray figure half up to a whole number of cents
        before going any further**."

        Design: Difficulty/boundary_precision_check/zero_tray_late_set_computes_positive_per_tray_rate_but_zero_fee
        """
        vendor, _case, loaner, received = self._late_delivery_with(api, 1)

        assert_integer_field(received, "late_minutes_current_basis", 45)
        assert received["status"] == LOANER_STATUS_DELIVERED_LATE

        stored = read_loaner_set(api, loaner["id"])
        # Forty-five minutes at 2.5 cents a tray a minute is 112.5, which rounds up.
        assert_money_cents(stored, "assessed_late_fee_cents", 113)
        assert stored["fee_status"] == FEE_STATUS_ASSESSED, (
            "one tray is not zero trays, so the charge is assessed rather than waived"
        )

        billed = read_vendor(api, vendor["id"])
        assert_money_cents(billed, "late_fee_balance_cents", 113)

    def test_waiving_the_fee_does_not_waive_the_late_delivery_penalty(self, api):
        """The zero-tray set costs nothing yet still docks the vendor five points.

        "The late-delivery penalty is five points for each of that vendor's
        loaner sets whose `status` is `DELIVERED_LATE` or `REJECTED_LATE` **and**
        whose `fee_status` is not `REVERSED`."

        Design: Difficulty/boundary_precision_check/zero_tray_late_set_computes_positive_per_tray_rate_but_zero_fee
        """
        vendor, case, loaner, _received = self._late_delivery_with(api, 0)

        stored = read_loaner_set(api, loaner["id"])
        assert stored["fee_status"] == FEE_STATUS_WAIVED

        rescored = read_vendor(api, vendor["id"])
        assert_integer_field(rescored, "adjudicated_compliance_score", 95)
        assert rescored["compliance_status"] == STATUS_IN_GOOD_STANDING

        # The case never needed an implant, so no tray state can move its readiness.
        staged = read_case(api, case["id"])
        assert staged["implant_readiness_status"] == READINESS_NOT_APPLICABLE
