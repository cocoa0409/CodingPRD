"""Lifecycles that revisit a state, and one kiosk row whose two dimensions diverge."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_SUSPENDED,
    AUTH_STATUS_APPROVED,
    BADGE_STATUS_EXPIRED,
    BADGE_STATUS_ISSUED,
    COMPLIANCE_ADMIN,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_COI,
    CREDENTIAL_TYPE_INFLUENZA,
    ESCORT_ATTACHED,
    ESCORT_PENDING,
    ESCORT_RELEASED,
    POSTURE_COMPLIANT,
    POSTURE_LAPSED,
    RESTRICTION_RESTRICTED,
    SUSPENSION_REASON_CREDENTIAL_LAPSED,
    SUSPENSION_REASON_NONE,
    USER_ESCORT_NURSE_1,
    USER_ESCORT_NURSE_2,
    assert_instant_equals,
    assert_instant_is_none,
    assert_integer_field,
    attach_escort,
    check_in,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credentialed_rep,
    decide_authorization,
    file_credential,
    find_by_id,
    list_rows,
    make_vendor_admin_headers,
    read_authorization,
    read_check_in,
    read_vendor_rep,
    request_authorization,
    run_sweep,
    set_clock,
    verify_credential,
)


class TestRepAccessStatusCycle:
    """A representative walks out of site access on a lapsed shot and back in on a fresh one."""

    @staticmethod
    def _setup(api):
        """Credential Priya Nandi with an influenza shot that runs out on 1 September."""
        create_facility(
            api,
            "LK-05",
            name="Lakeside Neuro Institute",
            spd_turnaround_hours=6,
            spd_bay_count=3,
        )
        vendor = create_vendor(api, "NEUROV", legal_name="Neurovance Medical Ltd")
        rep = create_vendor_rep(api, vendor["id"], "Priya Nandi")
        influenza = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2025-09-01T00:00:00Z",
            expires_at_utc="2026-09-01T00:00:00Z",
            document_reference="IMM-PRIYA-01",
        )
        verify_credential(api, influenza["id"])
        long_lived = {}
        for credential_type, reference in (
            (CREDENTIAL_TYPE_BLOODBORNE, "BBP-PRIYA-01"),
            (CREDENTIAL_TYPE_BACKGROUND, "BGC-PRIYA-01"),
            (CREDENTIAL_TYPE_COI, "COI-PRIYA-01"),
        ):
            filed = file_credential(
                api,
                rep["id"],
                credential_type,
                issued_at_utc="2026-07-01T00:00:00Z",
                expires_at_utc="2027-07-01T00:00:00Z",
                document_reference=reference,
            )
            long_lived[credential_type] = verify_credential(api, filed["id"])
        return rep, influenza, long_lived

    def test_lapsed_influenza_shot_carries_a_credentialed_rep_into_suspension(self, api):
        """The shot expires on its own instant and the sweep suspends its holder.

        "Every `VERIFIED` credential whose `expires_at_utc` is at or before
        `swept_at_utc` moves to `EXPIRED` — equality expires, the boundary is
        inclusive", after which "a `CREDENTIALED` representative whose posture is
        now `LAPSED` moves `CREDENTIALED → SUSPENDED` with `suspension_reason`
        set to `CREDENTIAL_LAPSED`" — and that recorded reason is what later
        admits credential work as the remedy.

        Design: Difficulty/non_linear_state_machine/rep_access_status_cycles_credentialed_suspended_credentialed
        """
        rep, influenza, long_lived = self._setup(api)

        cleared = read_vendor_rep(api, rep["id"])
        assert cleared["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert cleared["credential_posture"] == POSTURE_COMPLIANT
        assert cleared["ever_credentialed"] is True

        set_clock(api, "2026-09-01T00:00:00Z")
        sweep = run_sweep(api)

        assert_integer_field(sweep, "credentials_expired_count", 1)
        assert_integer_field(sweep, "credentials_warned_count", 0)
        assert_integer_field(sweep, "reps_suspended_count", 1)

        on_file = list_rows(api.list_rep_credentials(rep["id"], COMPLIANCE_ADMIN))
        assert find_by_id(on_file, influenza["id"])["status"] == "EXPIRED", (
            "the influenza shot expires at exactly its own expiry instant"
        )
        bloodborne = long_lived[CREDENTIAL_TYPE_BLOODBORNE]
        assert find_by_id(on_file, bloodborne["id"])["status"] == "VERIFIED", (
            "a shot good until 2027 is not even warned from a 2026 observation point"
        )

        lapsed = read_vendor_rep(api, rep["id"])
        assert lapsed["access_status"] == ACCESS_STATUS_SUSPENDED
        assert lapsed["credential_posture"] == POSTURE_LAPSED
        assert lapsed["suspension_reason"] == SUSPENSION_REASON_CREDENTIAL_LAPSED
        assert lapsed["ever_credentialed"] is True

    def test_replacement_shot_opens_a_second_and_different_credentialed_spell(self, api):
        """Returning to site access clears the reason, keeps the flag and stamps the return.

        "The same verification, applied to a representative already sitting in
        `SUSPENDED`, moves it `SUSPENDED → CREDENTIALED` and stamps
        `reinstated_at_utc` with the logical clock's current instant — but
        **only** when the existing `suspension_reason` is `CREDENTIAL_LAPSED`."
        The replacement attestation is admissible because "once an old credential
        has gone `EXPIRED` or `REJECTED`, a replacement of the same type is
        accepted", and `ever_credentialed`, "once true ... never returns to
        false", so the second spell is not a copy of the first.

        Design: Difficulty/non_linear_state_machine/rep_access_status_cycles_credentialed_suspended_credentialed
        """
        rep, _influenza, _long_lived = self._setup(api)
        set_clock(api, "2026-09-01T00:00:00Z")
        run_sweep(api)

        replacement = file_credential(
            api,
            rep["id"],
            CREDENTIAL_TYPE_INFLUENZA,
            issued_at_utc="2026-09-01T00:00:00Z",
            expires_at_utc="2027-09-01T00:00:00Z",
            document_reference="IMM-PRIYA-02",
        )
        verified = verify_credential(api, replacement["id"])
        assert verified["status"] == "VERIFIED"

        reinstated = read_vendor_rep(api, rep["id"])
        assert reinstated["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert reinstated["credential_posture"] == POSTURE_COMPLIANT
        assert reinstated["suspension_reason"] == SUSPENSION_REASON_NONE
        assert reinstated["ever_credentialed"] is True
        assert_instant_equals(
            reinstated["reinstated_at_utc"],
            "2026-09-01T00:00:00Z",
            "reinstated_at_utc",
        )


class TestBadgeAndEscortDimensionsMoveApart:
    """One badge whose physical lifecycle and escort custody advance on separate calls."""

    @staticmethod
    def _setup(api):
        """Put Omar Haddad through the kiosk on a restricted valve case at 07:30."""
        facility = create_facility(
            api,
            "RV-06",
            name="Riverview Cardiac Tower",
            spd_turnaround_hours=6,
            spd_bay_count=3,
            restricted_escort_required=True,
        )
        vendor = create_vendor(api, "CARDX", legal_name="Cardex Structural Heart Inc")
        rep = credentialed_rep(
            api,
            vendor["id"],
            "Omar Haddad",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-9401",
            "2026-09-15T08:00:00Z",
            "2026-09-15T10:00:00Z",
            restriction_level=RESTRICTION_RESTRICTED,
            procedure_name="Transcatheter Valve Repair",
        )
        requested = request_authorization(
            api,
            case["id"],
            rep["id"],
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        authorization = decide_authorization(
            api, requested["id"], "APPROVE", escort_user_id=USER_ESCORT_NURSE_1
        )
        set_clock(api, "2026-09-15T07:30:00Z")
        badge = check_in(api, authorization["id"], rep["id"])
        return authorization, badge

    def test_approval_derives_the_badge_window_and_the_escort_requirement(self, api):
        """The badge the kiosk prints inherits the window the approval computed.

        "`badge_window_start_utc` is the case's live `scheduled_start_utc`
        shifted earlier by the facility's `badge_lead_minutes` minutes, and
        `badge_window_end_utc` is the case's live `scheduled_end_utc` shifted
        later by the facility's `badge_grace_minutes` minutes", while
        `escort_required` "is written as the conjunction of two facts observed at
        this moment: the case's `restriction_level` equals `RESTRICTED` **and**
        the facility's `restricted_escort_required` is true". The escort dimension
        therefore opens at `ESCORT_PENDING` beside a badge at `ISSUED`.

        Design: Difficulty/non_linear_state_machine/kiosk_badge_and_escort_dimensions_advance_independently
        """
        authorization, badge = self._setup(api)

        assert authorization["escort_required"] is True
        assert_instant_equals(
            authorization["badge_window_start_utc"],
            "2026-09-15T07:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            authorization["badge_window_end_utc"],
            "2026-09-15T10:30:00Z",
            "badge_window_end_utc",
        )

        assert_instant_equals(
            badge["valid_from_utc"], "2026-09-15T07:00:00Z", "valid_from_utc"
        )
        assert_instant_equals(
            badge["valid_until_utc"], "2026-09-15T10:30:00Z", "valid_until_utc"
        )
        assert_instant_equals(
            badge["issued_at_utc"], "2026-09-15T07:30:00Z", "issued_at_utc"
        )
        assert badge["badge_status"] == BADGE_STATUS_ISSUED
        assert badge["escort_status"] == ESCORT_PENDING

    def test_attaching_the_escort_leaves_the_badge_dimension_at_issued(self, api):
        """Logging the nurse who actually turned up moves nothing but the escort dimension.

        "This moves the escort dimension `ESCORT_PENDING → ESCORT_ATTACHED`,
        writes `escort_user_id` from the body and `escort_attached_at_utc` from
        the logical clock, and — critically — leaves `badge_status` exactly where
        it was at `ISSUED`. The escort recorded here is the one who actually
        showed up and may legitimately differ from the `escort_user_id` the
        coordinator named on the authorization back at approval time."

        Design: Difficulty/non_linear_state_machine/kiosk_badge_and_escort_dimensions_advance_independently
        """
        authorization, badge = self._setup(api)
        assert authorization["escort_user_id"] == USER_ESCORT_NURSE_1

        attached = attach_escort(api, badge["id"], USER_ESCORT_NURSE_2)

        assert attached["escort_status"] == ESCORT_ATTACHED
        assert attached["escort_user_id"] == USER_ESCORT_NURSE_2, (
            "the nurse logged at the kiosk overrides the one named at approval"
        )
        assert_instant_equals(
            attached["escort_attached_at_utc"],
            "2026-09-15T07:30:00Z",
            "escort_attached_at_utc",
        )
        assert attached["badge_status"] == BADGE_STATUS_ISSUED
        assert_instant_is_none(attached, "checked_out_at_utc")

    def test_sweep_expires_the_badge_while_the_escort_stands_attached(self, api):
        """The badge runs out at the closing instant and the escort dimension does not move.

        "The sweep's badge phase moves an `ISSUED` badge to `EXPIRED` once its
        `valid_until_utc` is at or before the sweep's observation instant,
        leaving `escort_status` exactly as it stood." Only a check-out may reach
        `ESCORT_RELEASED`, and the authorization behind the dead badge is
        untouched.

        Design: Difficulty/non_linear_state_machine/kiosk_badge_and_escort_dimensions_advance_independently
        """
        authorization, badge = self._setup(api)
        attach_escort(api, badge["id"], USER_ESCORT_NURSE_2)

        set_clock(api, "2026-09-15T10:30:00Z")
        sweep = run_sweep(api)

        assert_integer_field(sweep, "badges_expired_count", 1)
        assert_integer_field(sweep, "badges_voided_count", 0)

        stored = read_check_in(api, badge["id"])
        assert stored["badge_status"] == BADGE_STATUS_EXPIRED
        assert stored["escort_status"] == ESCORT_ATTACHED
        assert stored["escort_status"] != ESCORT_RELEASED, (
            "only a check-out releases the escort, never a badge expiry"
        )
        assert_instant_is_none(stored, "checked_out_at_utc")

        assert read_authorization(api, authorization["id"])["status"] == AUTH_STATUS_APPROVED
