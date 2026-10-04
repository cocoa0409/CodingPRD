"""Exit verification: receipt codes, CV arch, mismatch handling, closeout."""
from test_helpers import (
    ADMIN,
    ASSOCIATE,
    LPO,
    MANAGER,
    ApiErrorId,
    create_item,
    create_member,
    create_session,
    get_session,
    make_associate_headers,
    member_headers,
    scan_unit_line,
    set_clock,
    setup_club_member,
    setup_exit_pending_session,
    setup_flagged_session_by_cv,
    setup_paid_session,
    validate_error,
    validate_success,
)


class TestExitScanGate:
    def test_exit_scan_requires_paid_session(self, api):
        """PRD §3.6: "Once a session is `PAID` — attempting exit verification
        earlier is rejected with `ERR_SESSION_NOT_PAID` — the member begins
        exit verification".

        Design: Difficulty/cross_entity_state_dependency/exit_scan_requires_paid_session
        """
        from test_helpers import setup_session_with_unit_item

        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=700, quantity=1,
        )
        resp = api.exit_scan(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_PAID)

    def test_exit_scan_after_pay_snapshots_expected_count(self, api):
        """PRD §3.6: "This creates an `ExitVerification` in `PENDING`,
        snapshots the session's `scanned_item_count` into the verification's
        `expected_item_count`, records the session's `club_id` on the
        verification, and moves the session `PAID → EXIT_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/exit_scan_requires_paid_session
        """
        club, item, member, session, pay_data = setup_paid_session(
            price_cents=700, quantity=1,
        )
        resp = api.exit_scan(session["id"], member_headers(member))
        verification = validate_success(resp, expected_status=201)
        assert verification["status"] == "PENDING"
        assert verification["expected_item_count"] == 1
        assert verification["club_id"] == club["id"]
        assert get_session(session["id"])["status"] == "EXIT_PENDING"


class TestReceiptCodeFlow:
    def test_receipt_verification_happy_path_exits_session(self, api):
        """PRD §3.6: "For a receipt-code verification, a door `Associate` scans
        the code the member presents: the submitted `receipt_code` is compared
        against the session's minted code, and a match moves the verification
        `PENDING → VERIFIED` and the session `EXIT_PENDING → EXITED`."

        Design: Corner/state_machines/receipt_verification_happy_path_exits_session
        """
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(price_cents=600, quantity=1)
        )
        resp = api.verify_receipt(
            verification["id"], pay_data["receipt_code"], ASSOCIATE,
        )
        verified = validate_success(resp)
        assert verified["status"] == "VERIFIED"
        assert get_session(session["id"])["status"] == "EXITED"

    def test_verify_receipt_wrong_code_flags_session(self, api):
        """PRD §3.6: "a receipt-code check with the wrong code does the same.
        Either way, the associate whose action produced the mismatch is
        recorded as the verification's `flagging_associate_id`, the session
        moves `EXIT_PENDING → FLAGGED`, and a `LossPreventionCase` opens in
        `OPEN` (§3.7)."; PRD §3.7: "Opening a case strikes the member:
        `unscanned_strikes` increases by one".

        Design: Corner/state_machines/verify_receipt_wrong_code_flags_session
        """
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(price_cents=600, quantity=1)
        )
        resp = api.verify_receipt(verification["id"], "WRONG-CODE", ASSOCIATE)
        mismatched = validate_success(resp)
        assert mismatched["status"] == "MISMATCH"
        assert get_session(session["id"])["status"] == "FLAGGED"
        resp = api.get_member(member["id"], LPO)
        assert resp.json()["data"]["unscanned_strikes"] == 1

    def test_void_exited_session_rejected(self, api):
        """PRD §3.4: "a `LossPreventionOfficer` may void a session in `PAID`,
        `EXIT_PENDING`, or `FLAGGED` — voiding from any other state is rejected
        with `ERR_SESSION_NOT_VOIDABLE`."

        Design: Corner/state_machines/void_exited_session_rejected
        """
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(price_cents=500, quantity=1)
        )
        resp = api.verify_receipt(
            verification["id"], pay_data["receipt_code"], ASSOCIATE,
        )
        validate_success(resp)
        assert get_session(session["id"])["status"] == "EXITED"

        resp = api.void_payment(session["id"], LPO)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_VOIDABLE)
        assert get_session(session["id"])["status"] == "EXITED"


class TestCvBoundary:
    def test_cv_unscanned_at_threshold_mismatches(self, api):
        """PRD §3.6: "A mismatch is the boundary case, inclusive: an unscanned
        count greater than or equal to `lp_unscanned_threshold` flips the
        verification to `MISMATCH`".

        Design: Difficulty/boundary_precision_check/cv_unscanned_at_threshold_mismatches_one_below_verifies
        """
        # unscanned == threshold (2): 5 observed - 3 expected.
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(
                price_cents=200, quantity=3,
                club_overrides={"exit_verification_mode": "CV_ARCH"},
            )
        )
        resp = api.cv_report(verification["id"], 5, ASSOCIATE)
        result = validate_success(resp)
        assert result["status"] == "MISMATCH"
        assert get_session(session["id"])["status"] == "FLAGGED"

    def test_cv_unscanned_one_below_threshold_verifies(self, api):
        """PRD §3.6: "the unscanned count is the observed count minus the
        verification's `expected_item_count`, and if that difference is below
        the club's `lp_unscanned_threshold` — including when the arch observes
        no more than was scanned — the verification moves `PENDING → VERIFIED`
        and the session to `EXITED`."

        Design: Difficulty/boundary_precision_check/cv_unscanned_at_threshold_mismatches_one_below_verifies
        """
        # unscanned == threshold - 1 (1): 4 observed - 3 expected.
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(
                price_cents=200, quantity=3,
                club_overrides={"exit_verification_mode": "CV_ARCH"},
            )
        )
        resp = api.cv_report(verification["id"], 4, ASSOCIATE)
        result = validate_success(resp)
        assert result["status"] == "VERIFIED"
        assert get_session(session["id"])["status"] == "EXITED"


class TestCvMismatchCascade:
    def test_cv_mismatch_flags_session_opens_case_suspends_member(self, api):
        """PRD §3.7: "Opening a case strikes the member: `unscanned_strikes`
        increases by one, and the moment a member's strikes reach the club's
        `lp_suspend_strikes` — the boundary is inclusive — the member's
        `status` flips from `ACTIVE` to `SUSPENDED`"; PRD §3.6: "the session
        moves `EXIT_PENDING → FLAGGED`, and a `LossPreventionCase` opens in
        `OPEN` (§3.7)."

        Design: Difficulty/transitive_cascade/cv_mismatch_flags_session_opens_case_suspends_member
        """
        from test_helpers import create_club, patch_club

        set_clock()
        club = create_club(
            name="Club TC2", exit_verification_mode="CV_ARCH",
        )
        club = patch_club(club["id"], club["version"], lp_suspend_strikes=1)
        item = create_item(club["id"], sku="SODA-12", unit_price_cents=300)
        member = create_member(club["id"], tier="PLUS", birth_year=1995)
        session = create_session(club, member)
        scan_unit_line(session, member, item, quantity=3)
        resp = api.pay_session(session["id"], member_headers(member))
        validate_success(resp)
        resp = api.exit_scan(session["id"], member_headers(member))
        verification = validate_success(resp, expected_status=201)

        resp = api.cv_report(
            verification["id"], 5, make_associate_headers("assoc-flagger-1"),
        )
        result = validate_success(resp)
        assert result["status"] == "MISMATCH"
        assert get_session(session["id"])["status"] == "FLAGGED"

        resp = api.get_member(member["id"], LPO)
        member_now = resp.json()["data"]
        assert member_now["unscanned_strikes"] == 1
        assert member_now["status"] == "SUSPENDED"

    def test_cv_mismatch_opens_review_case_with_unscanned_count(self, api):
        """PRD §3.7: "For a computer-vision mismatch the case records the
        `unscanned_count` — the observed count minus the expected count";
        "The case's `tier` is `SEVERE` when the unscanned count is at least
        twice the club's `lp_unscanned_threshold`, and `REVIEW` otherwise".

        Design: Difficulty/transitive_cascade/cv_mismatch_flags_session_opens_case_suspends_member
        """
        from test_helpers import create_club, patch_club

        set_clock()
        club = create_club(name="Club TC2b", exit_verification_mode="CV_ARCH")
        club = patch_club(club["id"], club["version"], lp_suspend_strikes=1)
        item = create_item(club["id"], sku="SODA-12", unit_price_cents=300)
        member = create_member(club["id"], tier="PLUS", birth_year=1995)
        session = create_session(club, member)
        scan_unit_line(session, member, item, quantity=3)
        resp = api.pay_session(session["id"], member_headers(member))
        validate_success(resp)
        resp = api.exit_scan(session["id"], member_headers(member))
        verification = validate_success(resp, expected_status=201)

        resp = api.cv_report(
            verification["id"], 5, make_associate_headers("assoc-flagger-1"),
        )
        validate_success(resp)

        resp = api.list_lp_cases(LPO)
        cases = resp.json()["data"]
        case = next(c for c in cases if c["session_id"] == session["id"])
        assert case["status"] == "OPEN"
        assert case["source"] == "CV_MISMATCH"
        assert case["unscanned_count"] == 2
        # 2 < 2 * 2 -> REVIEW tier.
        assert case["tier"] == "REVIEW"


class TestMismatchResolution:
    def test_resolve_mismatch_rescan_cycles_back_to_exit_pending(self, api):
        """PRD §3.6: "`RESCAN` abandons the current verification (it stays
        `MISMATCH`, superseded), creates a fresh `PENDING` verification, and
        returns the session `FLAGGED → EXIT_PENDING` for another pass."

        Design: Corner/state_machines/resolve_mismatch_rescan_cycles_back_to_exit_pending
        """
        club, item, member, session, pay_data, verification, case = (
            setup_flagged_session_by_cv(
                price_cents=300, quantity=1, observed_item_count=5,
            )
        )
        resp = api.resolve_mismatch(verification["id"], "RESCAN", ASSOCIATE)
        validate_success(resp)

        assert get_session(session["id"])["status"] == "EXIT_PENDING"
        resp = api.list_session_exit_verifications(session["id"], ASSOCIATE)
        body = resp.json()
        verifications = body["data"]
        assert body["meta"]["total_count"] == 2
        statuses = sorted(v["status"] for v in verifications)
        assert statuses == ["MISMATCH", "PENDING"]

    def test_error_verification_not_mismatched_on_resolve_of_pending(self, api):
        """PRD §3.6: "An associate handles a `MISMATCH` verification — acting
        on a verification in any other state is rejected with
        `ERR_VERIFICATION_NOT_MISMATCHED`".

        Design: Corner/errors/error_verification_not_mismatched_on_resolve_of_pending
        """
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(
                price_cents=300, quantity=1,
                club_overrides={"exit_verification_mode": "CV_ARCH"},
            )
        )
        resp = api.resolve_mismatch(verification["id"], "CLEAR", ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_MISMATCHED)

    def test_error_verification_not_pending_on_second_cv_report(self, api):
        """PRD §3.6: "Both flows require the verification to still be
        `PENDING` (else `ERR_VERIFICATION_NOT_PENDING`)".

        Design: Corner/errors/error_verification_not_pending_on_second_cv_report
        """
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(
                price_cents=300, quantity=2,
                club_overrides={"exit_verification_mode": "CV_ARCH"},
            )
        )
        resp = api.cv_report(verification["id"], 2, ASSOCIATE)
        first = validate_success(resp)
        assert first["status"] == "VERIFIED"

        resp = api.cv_report(verification["id"], 2, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_PENDING)


class TestReceiptCodeExpiry:
    def test_receipt_code_expiry_flags_session_at_closeout(self, api):
        """PRD §3.10: "Second, every session still `EXIT_PENDING` whose receipt
        code has outlived `receipt_code_ttl_minutes` is flagged: its pending
        verifications expire, the session moves to `FLAGGED`, a
        `RECEIPT_EXPIRY` loss-prevention case opens, and the
        strike-and-suspension cascade of §3.7 applies (§3.6)."

        Design: Corner/calculations/receipt_code_expiry_flags_session_at_closeout
        """
        club, item, member, session, pay_data, verification = (
            setup_exit_pending_session(price_cents=500, quantity=1)
        )
        set_clock("2026-09-01T12:31:00Z")  # past the default 30-minute TTL
        resp = api.run_closeout(club["id"], MANAGER)
        validate_success(resp)

        assert get_session(session["id"])["status"] == "FLAGGED"
        resp = api.list_lp_cases(LPO)
        cases = resp.json()["data"]
        case = next(c for c in cases if c["session_id"] == session["id"])
        assert case["source"] == "RECEIPT_EXPIRY"
        assert case["unscanned_count"] == 0
        assert case["tier"] == "REVIEW"
