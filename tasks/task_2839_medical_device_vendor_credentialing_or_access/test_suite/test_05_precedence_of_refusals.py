"""Two rungs of the validation ladder tripped at once, and which one answers."""

from __future__ import annotations

from test_helpers import (
    ACCESS_STATUS_CREDENTIALED,
    ACCESS_STATUS_REVOKED,
    AUTH_STATUS_APPROVED,
    COMPLEXITY_IMPLANT_SPECIALTY,
    COMPLEXITY_SIMPLE,
    COMPLIANCE_ADMIN,
    CREDENTIALING_OFFICER,
    ERR_BADGE_WINDOW_NOT_OPEN,
    ERR_PRODUCT_NOT_APPROVED,
    ERR_REP_ACCESS_REVOKED,
    ERR_VENDOR_FEE_HOLD,
    FEE_HOLD_THRESHOLD_CENTS,
    FEE_STATUS_ASSESSED,
    FEE_STATUS_NONE,
    LOANER_STATUS_DELIVERED_ON_TIME,
    LOANER_STATUS_REJECTED_LATE,
    POSTURE_COMPLIANT,
    PRODUCT_STATUS_ACTIVE,
    PRODUCT_STATUS_EXPIRED,
    READINESS_BLOCKED,
    READINESS_PENDING,
    STERILE_PROCESSING_TECH,
    approved_authorization,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    check_in_payload,
    create_case,
    create_facility,
    create_vendor,
    credentialed_rep,
    list_rows,
    make_vendor_rep_headers,
    read_approved_product,
    read_authorization,
    read_case,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    revoke_rep,
    run_sweep,
    set_clock,
    validate_error,
)


class TestRevokedAccessOutranksTheClosedBadgeWindow:
    """A revoked representative presenting at the kiosk after the badge has lapsed."""

    @staticmethod
    def _setup(api):
        """A credentialed representative holding one approved authorization."""
        facility = create_facility(
            api, "BR-09", name="Bayridge Vascular Center",
            spd_turnaround_hours=6, spd_bay_count=2,
        )
        vendor = create_vendor(api, "VASCU", legal_name="Vasculine Access Corp")
        rep = credentialed_rep(
            api,
            vendor["id"],
            "Nia Brooks",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        assert rep["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert rep["credential_posture"] == POSTURE_COMPLIANT
        case = create_case(
            api,
            facility["id"],
            "CASE-9701",
            "2026-09-10T14:00:00Z",
            "2026-09-10T18:00:00Z",
            procedure_name="AV Fistula Creation",
        )
        authorization = approved_authorization(api, case["id"], rep["id"])
        assert authorization["status"] == AUTH_STATUS_APPROVED
        # An hour of lead before the knife and half an hour of grace after it.
        assert_instant_equals(
            authorization["badge_window_start_utc"],
            "2026-09-10T13:00:00Z",
            "badge_window_start_utc",
        )
        assert_instant_equals(
            authorization["badge_window_end_utc"],
            "2026-09-10T18:30:00Z",
            "badge_window_end_utc",
        )
        return rep, authorization

    @staticmethod
    def _attempt_check_in(api, rep_id, auth_id):
        """The representative badging itself in at the vendor kiosk."""
        return api.create_check_in(
            check_in_payload(auth_id), make_vendor_rep_headers(rep_id)
        )

    @staticmethod
    def _assert_no_badge_printed(api, auth_id):
        """A refused kiosk arrival leaves the authorization with no check-in at all."""
        badges = list_rows(api.list_authorization_check_ins(auth_id, COMPLIANCE_ADMIN))
        assert badges == [], "a refused kiosk arrival should print no badge"

    def test_revoked_access_answers_before_the_shut_badge_window(self, api):
        """Both the revocation and the shut window hold, and the revocation is reported.

        "**Representative not revoked** — the acting or referenced
        representative's `access_status` is not `REVOKED`, else
        `ERR_REP_ACCESS_REVOKED` (409). Applies to four operations: requesting a
        case authorization, kiosk check-in, kiosk check-out, and attesting a
        credential." That rung sits above the badge-window rung, and "the first
        failing rung produces the response", so the kiosk reports the revoked
        access with 409 rather than the shut window with 422.

        Design: Difficulty/priority_pair_validation_conflict/revoked_rep_state_check_precedes_badge_window_and_returns_409
        """
        rep, authorization = self._setup(api)

        # Half an hour past the badge window's close, and after the case started.
        set_clock(api, "2026-09-10T19:00:00Z")
        revoke_rep(
            api,
            rep["id"],
            CREDENTIALING_OFFICER,
            "Background attestation withdrawn by the vendor.",
        )

        refused = self._attempt_check_in(api, rep["id"], authorization["id"])
        validate_error(refused, ERR_REP_ACCESS_REVOKED)

        self._assert_no_badge_printed(api, authorization["id"])

        # The revocation reached the representative but not this authorization,
        # because the theatre time it covers is already history.
        standing = read_authorization(api, authorization["id"])
        assert standing["status"] == AUTH_STATUS_APPROVED
        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_REVOKED
        assert_instant_equals(
            stored_rep["revoked_at_utc"], "2026-09-10T19:00:00Z", "revoked_at_utc"
        )
        assert_integer_field(stored_rep, "open_authorization_count", 1)

    def test_shut_badge_window_surfaces_once_the_revocation_is_removed(self, api):
        """With site access intact, the very same late arrival reports the window instead.

        "check-in is admissible when the current instant is at or after
        `badge_window_start_utc` and at or before `badge_window_end_utc`, so
        arriving at exactly the opening instant or exactly the closing instant
        both succeed, and anything outside is refused with
        `ERR_BADGE_WINDOW_NOT_OPEN`." The window is just as shut here as it was
        for the revoked representative, which is what shows the earlier refusal
        was the ladder's ordering rather than an accident of the clock.

        Design: Difficulty/priority_pair_validation_conflict/revoked_rep_state_check_precedes_badge_window_and_returns_409
        """
        rep, authorization = self._setup(api)

        set_clock(api, "2026-09-10T19:00:00Z")

        refused = self._attempt_check_in(api, rep["id"], authorization["id"])
        validate_error(refused, ERR_BADGE_WINDOW_NOT_OPEN)

        self._assert_no_badge_printed(api, authorization["id"])

        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert stored_rep.get("revoked_at_utc") is None
        assert_integer_field(stored_rep, "open_authorization_count", 1)

    def test_revoked_access_still_answers_inside_an_open_badge_window(self, api):
        """With the window wide open, the revocation alone still shuts the kiosk.

        "**Representative not revoked** — the acting or referenced
        representative's `access_status` is not `REVOKED`, else
        `ERR_REP_ACCESS_REVOKED` (409)." The revocation lands after the knife
        went in, and "authorizations for cases that have already started are
        deliberately left `APPROVED`, because historical access is a matter of
        record and is not rewritten", so the authorization is still approved and
        only the representative's own state bars the badge.

        Design: Difficulty/priority_pair_validation_conflict/revoked_rep_state_check_precedes_badge_window_and_returns_409
        """
        rep, authorization = self._setup(api)

        # An hour into the procedure, comfortably inside the 13:00-18:30 window.
        set_clock(api, "2026-09-10T15:00:00Z")
        revoke_rep(
            api,
            rep["id"],
            CREDENTIALING_OFFICER,
            "Background attestation withdrawn by the vendor.",
        )

        refused = self._attempt_check_in(api, rep["id"], authorization["id"])
        validate_error(refused, ERR_REP_ACCESS_REVOKED)

        self._assert_no_badge_printed(api, authorization["id"])

        standing = read_authorization(api, authorization["id"])
        assert standing["status"] == AUTH_STATUS_APPROVED
        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_REVOKED
        assert_instant_equals(
            stored_rep["revoked_at_utc"], "2026-09-10T15:00:00Z", "revoked_at_utc"
        )


class TestExpiredApprovalOutranksTheFeeHold:
    """A vendor over the fee hold whose product approval has also lapsed."""

    @staticmethod
    def _setup(api):
        """One rejected-late tray set past the fee hold, one on-time set fit to release."""
        facility = create_facility(
            api, "FX-10", name="Fairfax Spine Institute",
            spd_turnaround_hours=8, spd_bay_count=2,
        )
        vendor = create_vendor(api, "MEGAI", legal_name="Megaimplant Holdings AG")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "LI-L9-905",
            610000,
            is_implant=True,
            product_name="Lumbar Interbody Cage L9",
            manufacturer="Megaimplant",
        )
        # Approved at the startup instant, so the approval runs to 2027-08-01.
        assert product["status"] == PRODUCT_STATUS_ACTIVE
        assert_instant_equals(
            product["approval_expires_at_utc"],
            "2027-08-01T00:00:00Z",
            "approval_expires_at_utc",
        )

        # An implant case: the 24-hour floor beats the 20-hour turnaround.
        long_case = create_case(
            api,
            facility["id"],
            "CASE-9801",
            "2026-09-25T10:00:00Z",
            "2026-09-25T14:00:00Z",
            procedure_name="Lumbar Fusion Long Construct",
            implant_required=True,
        )
        late_set = register_loaner_set(
            api,
            vendor["id"],
            long_case["id"],
            product["id"],
            20,
            COMPLEXITY_IMPLANT_SPECIALTY,
        )
        assert_instant_equals(
            late_set["required_delivery_deadline_utc"],
            "2026-09-24T10:00:00Z",
            "required_delivery_deadline_utc",
        )

        short_case = create_case(
            api,
            facility["id"],
            "CASE-9802",
            "2026-09-26T10:00:00Z",
            "2026-09-26T14:00:00Z",
            procedure_name="Single Level Interbody Fusion",
            implant_required=True,
        )
        ready_set = register_loaner_set(
            api, vendor["id"], short_case["id"], product["id"], 4, COMPLEXITY_SIMPLE
        )
        assert_instant_equals(
            ready_set["required_delivery_deadline_utc"],
            "2026-09-25T10:00:00Z",
            "required_delivery_deadline_utc",
        )

        # Twenty hours past its deadline: well beyond the two-hour hard reject.
        rejected = receive_loaner_set(api, late_set["id"], "2026-09-25T06:00:00Z")
        assert rejected["status"] == LOANER_STATUS_REJECTED_LATE
        assert_integer_field(rejected, "late_minutes_current_basis", 1200)
        assert_money_cents(rejected, "assessed_late_fee_cents", 105000)
        assert rejected["fee_status"] == FEE_STATUS_ASSESSED

        # An hour early, so this one is on time and releasable on state grounds.
        on_time = receive_loaner_set(api, ready_set["id"], "2026-09-25T09:00:00Z")
        assert on_time["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert on_time["fee_status"] == FEE_STATUS_NONE

        # A thousand and fifty dollars of late fees, over the hold threshold.
        billed = read_vendor(api, vendor["id"])
        assert_money_cents(billed, "late_fee_balance_cents", 105000)
        assert billed["late_fee_balance_cents"] >= FEE_HOLD_THRESHOLD_CENTS
        return vendor, product, late_set, ready_set, long_case, short_case

    @staticmethod
    def _expire_the_approval(api):
        """Let the clock reach the approval expiry exactly and sweep the estate."""
        set_clock(api, "2027-08-01T00:00:00Z")
        return run_sweep(api)

    def test_expired_approval_answers_before_the_fee_hold(self, api):
        """Both refusals apply to the release, and the lapsed approval is reported.

        "**Product still approved** — the referenced approved product is
        `ACTIVE`, and is neither `SUSPENDED` nor `EXPIRED`, else
        `ERR_PRODUCT_NOT_APPROVED` (422). Applies to two operations: registering
        a loaner set and releasing one." The ladder puts "uniqueness before
        referential product checks, and money and quota last of all", so the
        lapsed approval answers with 422 and the fee hold's 402 never appears.

        Design: Difficulty/priority_pair_validation_conflict/expired_product_referential_check_precedes_fee_hold_and_returns_422
        """
        _vendor, product, _late_set, ready_set, _long_case, short_case = self._setup(api)

        self._expire_the_approval(api)
        assert read_approved_product(api, product["id"])["status"] == PRODUCT_STATUS_EXPIRED

        refused = api.release_loaner_set(ready_set["id"], {}, STERILE_PROCESSING_TECH)
        validate_error(refused, ERR_PRODUCT_NOT_APPROVED)

        # The trays never reached the theatre, so nothing about them moved.
        held_back = read_loaner_set(api, ready_set["id"])
        assert held_back["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert held_back["fee_status"] == FEE_STATUS_NONE
        assert read_case(api, short_case["id"])["implant_readiness_status"] == READINESS_PENDING

    def test_fee_hold_surfaces_while_the_approval_is_still_active(self, api):
        """With the approval still live, the same release reports the fiscal hold.

        "the vendor's `late_fee_balance_cents` must be strictly below the fee
        hold threshold of 100,000 cents, else it is refused with
        `ERR_VENDOR_FEE_HOLD`." The balance is the same 105,000 cents that stood
        behind the earlier refusal, which is what shows that refusal came from
        the ladder's ordering rather than from an absent fee hold.

        Design: Difficulty/priority_pair_validation_conflict/expired_product_referential_check_precedes_fee_hold_and_returns_422
        """
        vendor, product, _late_set, ready_set, _long_case, short_case = self._setup(api)

        assert read_approved_product(api, product["id"])["status"] == PRODUCT_STATUS_ACTIVE

        refused = api.release_loaner_set(ready_set["id"], {}, STERILE_PROCESSING_TECH)
        validate_error(refused, ERR_VENDOR_FEE_HOLD)

        held_back = read_loaner_set(api, ready_set["id"])
        assert held_back["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert read_case(api, short_case["id"])["implant_readiness_status"] == READINESS_PENDING
        assert_money_cents(read_vendor(api, vendor["id"]), "late_fee_balance_cents", 105000)

    def test_the_lapsing_approval_leaves_both_tray_sets_exactly_where_they_stood(self, api):
        """The approval lapses on its own terms without disturbing a single tray set.

        "Expiry places **no hold** on any loaner set, exactly as in §3.7: a set
        already registered against a product whose approval lapses stays where it
        is, while a *new* release attempt against that product is refused." That
        is what keeps the tray-set state rung from masking the pair of refusals
        the release attempt has to choose between.

        Design: Difficulty/priority_pair_validation_conflict/expired_product_referential_check_precedes_fee_hold_and_returns_422
        """
        vendor, _product, late_set, ready_set, long_case, short_case = self._setup(api)

        sweep = self._expire_the_approval(api)
        assert_integer_field(sweep, "approvals_expired_count", 1)

        rejected = read_loaner_set(api, late_set["id"])
        assert rejected["status"] == LOANER_STATUS_REJECTED_LATE
        assert rejected["fee_status"] == FEE_STATUS_ASSESSED
        assert_money_cents(rejected, "assessed_late_fee_cents", 105000)
        assert_integer_field(rejected, "late_minutes_current_basis", 1200)

        on_time = read_loaner_set(api, ready_set["id"])
        assert on_time["status"] == LOANER_STATUS_DELIVERED_ON_TIME

        assert read_case(api, long_case["id"])["implant_readiness_status"] == READINESS_BLOCKED
        assert read_case(api, short_case["id"])["implant_readiness_status"] == READINESS_PENDING

        # One late delivery costs the vendor five points on both variants.
        rescored = read_vendor(api, vendor["id"])
        assert_integer_field(rescored, "adjudicated_compliance_score", 95)
        assert_money_cents(rescored, "late_fee_balance_cents", 105000)
