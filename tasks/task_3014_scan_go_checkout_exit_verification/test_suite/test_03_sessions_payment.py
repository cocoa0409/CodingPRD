"""Session lifecycle: payment, repricing, voids, and shopping-hours gates."""
from test_helpers import (
    ADMIN,
    MANAGER,
    ApiErrorId,
    create_item,
    create_member,
    create_offer,
    create_session,
    get_member,
    get_session,
    member_headers,
    scan_unit_line,
    set_clock,
    setup_club_member,
    setup_paid_session,
    setup_session_with_unit_item,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalRepricing:
    def test_mid_shop_price_change_repriced_at_pay(self, api):
        """PRD §3.4: "the server computes `final_total_cents` by re-pricing
        every non-`REMOVED` line against the current catalog prices and offers
        evaluated at the pay-time clock (not the scan-time snapshots)"; PRD
        §3.1: "a `PlatformAdmin` may reprice an item or flip its `status` to
        `DELISTED` at any time".

        Design: Difficulty/dual_variant_calc/cart_provisional_vs_final_after_mid_shop_price_change
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1000, quantity=2,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        # The create-session response is a snapshot taken before any line
        # exists; the post-scan provisional total must be read back.
        assert get_session(session["id"])["provisional_total_cents"] == 2000

        resp = api.update_catalog_item(item["id"], {"unit_price_cents": 1200}, ADMIN)
        assert resp.status_code == 200, f"Setup failed: reprice -> {resp.text}"

        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        assert paid["final_total_cents"] == 2400

    def test_mid_shop_price_change_leaves_provisional_on_snapshots(self, api):
        """PRD §3.2: "The session's `provisional_total_cents` is the sum of
        `line_total_cents` over all non-`REMOVED` lines, recomputed on every
        line addition, removal, or intercept resolution, always from scan-time
        snapshots and scan-time offer evaluation."; PRD §3.4: "adds
        `final_total_cents` to the member's `lifetime_charged_cents`".

        Design: Difficulty/dual_variant_calc/cart_provisional_vs_final_after_mid_shop_price_change
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1000, quantity=2,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
        )
        resp = api.update_catalog_item(item["id"], {"unit_price_cents": 1200}, ADMIN)
        assert resp.status_code == 200, f"Setup failed: reprice -> {resp.text}"

        resp = api.pay_session(session["id"], member_headers(member))
        validate_success(resp)

        reread = get_session(session["id"])
        assert reread["provisional_total_cents"] == 2000
        assert reread["final_total_cents"] == 2400
        member_now = get_member(member["id"])
        assert member_now["lifetime_charged_cents"] == 2400


class TestPayPreconditions:
    def test_empty_cart_pay_rejected_then_single_line_accepted(self, api):
        """PRD §3.4: "at least one non-`REMOVED` line (else `ERR_EMPTY_CART`)".

        Design: Difficulty/boundary_precision_check/empty_cart_pay_rejected_single_line_accepted
        """
        club, member = setup_club_member()
        item = create_item(club["id"], sku="BREAD", unit_price_cents=450)
        session = create_session(club, member)

        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_EMPTY_CART)

        scan_unit_line(session, member, item, quantity=1)
        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        assert paid["final_total_cents"] == 450

    def test_empty_cart_pay_rejected_and_session_stays_open(self, api):
        """PRD §3.4: "at least one non-`REMOVED` line (else `ERR_EMPTY_CART`)";
        PRD §3.2: "A new session starts `OPEN` with a
        `provisional_total_cents` of zero."

        Design: Difficulty/boundary_precision_check/empty_cart_pay_rejected_single_line_accepted
        """
        club, member = setup_club_member()
        session = create_session(club, member)

        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_EMPTY_CART)
        # The rejected pay leaves the session OPEN and uncharged.
        reread = get_session(session["id"])
        assert reread["status"] == "OPEN"
        assert reread["provisional_total_cents"] == 0
        assert get_member(member["id"])["lifetime_charged_cents"] == 0

    def test_tender_declined_blocks_pay_with_402(self, api):
        """PRD §3.4: "a `tender_status` of `OK` on the member's
        membership-linked tender — a tender in the `DECLINED` state blocks
        payment with `ERR_TENDER_DECLINED` (HTTP 402)."

        Design: Corner/errors/error_tender_declined_on_pay
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=500, quantity=1,
            member_overrides={"tier": "CLUB", "tender_status": "DECLINED"},
        )
        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_TENDER_DECLINED)
        assert get_session(session["id"])["status"] == "OPEN"

    def test_pending_intercept_safety_beats_declined_tender_fiscal(self, api):
        """PRD §2.8: "payment on a session that both has a pending intercept
        and an empty cart fails with the intercept error, because safety
        outranks fiscal checks"; PRD §3.4: "no `PENDING` intercept on the
        session (else `ERR_INTERCEPT_PENDING` — which is also why paying from
        `REVIEW_HOLD` is unreachable in practice until its intercepts
        resolve)".

        Design: Difficulty/priority_pair_validation_conflict/pending_intercept_safety_beats_declined_tender_fiscal
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=2000, quantity=1,
            member_overrides={
                "tier": "PLUS", "birth_year": 1990, "tender_status": "DECLINED",
            },
            restricted_class="ALCOHOL",
        )
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"

        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_INTERCEPT_PENDING)
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"

    def test_intercept_gate_holds_even_when_tender_is_ok(self, api):
        """PRD §3.4: "Paying requires the member to be `ACTIVE` (else
        `ERR_MEMBER_INACTIVE`), no `PENDING` intercept on the session (else
        `ERR_INTERCEPT_PENDING` — which is also why paying from `REVIEW_HOLD`
        is unreachable in practice until its intercepts resolve), at least one
        non-`REMOVED` line (else `ERR_EMPTY_CART`), and a `tender_status` of
        `OK` on the member's membership-linked tender".

        Design: Difficulty/priority_pair_validation_conflict/pending_intercept_safety_beats_declined_tender_fiscal
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=2000, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="ALCOHOL",
        )
        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_INTERCEPT_PENDING)
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"

    def test_intercept_gate_holds_even_when_tender_is_ok(self, api):
        """PRD §3.4: "Paying requires the member to be `ACTIVE` (else
        `ERR_MEMBER_INACTIVE`), no `PENDING` intercept on the session (else
        `ERR_INTERCEPT_PENDING` — which is also why paying from `REVIEW_HOLD`
        is unreachable in practice until its intercepts resolve), at least one
        non-`REMOVED` line (else `ERR_EMPTY_CART`), and a `tender_status` of
        `OK` on the member's membership-linked tender".

        Design: Difficulty/priority_pair_validation_conflict/pending_intercept_safety_beats_declined_tender_fiscal
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=2000, quantity=1,
            member_overrides={"tier": "PLUS", "birth_year": 1990},
            restricted_class="ALCOHOL",
        )
        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_INTERCEPT_PENDING)
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"

    def test_pay_blocked_until_restricted_intercept_resolved(self, api):
        """PRD §3.4: "Paying requires the member to be `ACTIVE` (else
        `ERR_MEMBER_INACTIVE`), no `PENDING` intercept on the session (else
        `ERR_INTERCEPT_PENDING` — which is also why paying from `REVIEW_HOLD`
        is unreachable in practice until its intercepts resolve)"; "In both
        cases, once no `PENDING` intercepts remain for the session, the
        session reopens from `REVIEW_HOLD` to `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/pay_blocked_until_restricted_intercept_resolved
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1200, quantity=1, restricted_class="PHARMACY",
        )
        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_INTERCEPT_PENDING)

        _resolve_pharmacy_intercept(api, session["id"])

        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        assert paid["final_total_cents"] == 1200

    def test_after_intercept_approval_session_reopens_for_pay(self, api):
        """PRD §3.4: "On approval, the intercept becomes `APPROVED`, the line
        moves `INTERCEPTED → CLEARED`, the resolving associate's identity is
        recorded as the intercept's `associate_id`, and the line's savings and
        total are finalized."; "once no `PENDING` intercepts remain for the
        session, the session reopens from `REVIEW_HOLD` to `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/pay_blocked_until_restricted_intercept_resolved
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1200, quantity=1, restricted_class="PHARMACY",
        )
        assert get_session(session["id"])["status"] == "REVIEW_HOLD"
        _resolve_pharmacy_intercept(api, session["id"])
        assert get_session(session["id"])["status"] == "OPEN"


def _resolve_pharmacy_intercept(api, session_id):
    from test_helpers import ASSOCIATE

    resp = api.list_session_intercepts(session_id, ASSOCIATE)
    intercepts = resp.json()["data"]
    pending = [i for i in intercepts if i["status"] == "PENDING"]
    assert pending, "Setup failed: no PENDING intercept"
    resp = api.resolve_intercept(
        pending[0]["id"],
        {"decision": "APPROVE", "pharmacist_note": "verified at counter"},
        ASSOCIATE,
    )
    assert resp.status_code == 200, f"Setup failed: resolve -> {resp.text}"


class TestVoidAndTerminalLockdown:
    def test_pay_then_void_restores_member_charged_cents(self, api):
        """PRD §3.4: "A void moves the session to `VOIDED`, sets
        `refunded_cents` equal to `final_total_cents` as a full compensating
        refund, subtracts `final_total_cents` from the member's
        `lifetime_charged_cents`, claws the session's
        `rewards_contribution_cents` back out of the member's
        `cash_rewards_pending_cents` (never letting it drop below zero),
        invalidates the receipt code, and expires any `PENDING` exit
        verifications."

        Design: Difficulty/compensating_invariant/pay_then_void_restores_member_charged_cents
        """
        from test_helpers import LPO

        club, item, member, session, pay_data = setup_paid_session(
            price_cents=750, quantity=2,
            member_overrides={"tier": "PLUS", "birth_year": 1979},
        )
        after_pay = get_member(member["id"])
        assert after_pay["lifetime_charged_cents"] == 1500
        # PLUS rewards: floor(1500 * 2 / 100) = 30 pending.
        assert after_pay["cash_rewards_pending_cents"] == 30

        resp = api.void_payment(session["id"], LPO)
        voided = validate_success(resp)
        assert voided["status"] == "VOIDED"
        assert voided["refunded_cents"] == 1500

        after_void = get_member(member["id"])
        assert after_void["lifetime_charged_cents"] == 0
        assert after_void["cash_rewards_pending_cents"] == 0

    def test_void_full_refund_equals_final_total(self, api):
        """PRD §3.4: "A void moves the session to `VOIDED`, sets
        `refunded_cents` equal to `final_total_cents` as a full compensating
        refund, subtracts `final_total_cents` from the member's
        `lifetime_charged_cents`".

        Design: Difficulty/compensating_invariant/pay_then_void_restores_member_charged_cents
        """
        from test_helpers import LPO

        club, item, member, session, pay_data = setup_paid_session(
            price_cents=750, quantity=2,
            member_overrides={"tier": "PLUS", "birth_year": 1979},
        )
        resp = api.void_payment(session["id"], LPO)
        voided = validate_success(resp)
        assert voided["refunded_cents"] == voided["final_total_cents"] == 1500
        resp = api.get_scan_session(session["id"], LPO)
        reread = resp.json()["data"]
        assert reread["status"] == "VOIDED"
        assert reread["refunded_cents"] == 1500

    def test_void_full_refund_equals_final_total(self, api):
        """PRD §3.4: "A void moves the session to `VOIDED`, sets
        `refunded_cents` equal to `final_total_cents` as a full compensating
        refund, subtracts `final_total_cents` from the member's
        `lifetime_charged_cents`".

        Design: Difficulty/compensating_invariant/pay_then_void_restores_member_charged_cents
        """
        from test_helpers import LPO

        club, item, member, session, pay_data = setup_paid_session(
            price_cents=750, quantity=2,
            member_overrides={"tier": "PLUS", "birth_year": 1979},
        )
        resp = api.void_payment(session["id"], LPO)
        voided = validate_success(resp)
        assert voided["refunded_cents"] == voided["final_total_cents"] == 1500
        resp = api.get_scan_session(session["id"], LPO)
        reread = resp.json()["data"]
        assert reread["status"] == "VOIDED"
        assert reread["refunded_cents"] == 1500

    def test_pay_voided_session_rejected_terminal_lockdown(self, api):
        """PRD §3.4: "a `LossPreventionOfficer` may void a session in `PAID`,
        `EXIT_PENDING`, or `FLAGGED` — voiding from any other state is rejected
        with `ERR_SESSION_NOT_VOIDABLE`."; PRD §3.4: "A void moves the session
        to `VOIDED` ... subtracts `final_total_cents` from the member's
        `lifetime_charged_cents`".

        Design: Corner/state_machines/pay_voided_session_rejected_terminal_lockdown
        """
        from test_helpers import LPO

        club, item, member, session, pay_data = setup_paid_session(
            price_cents=500, quantity=1,
        )
        resp = api.void_payment(session["id"], LPO)
        validate_success(resp)

        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)
        # No double charge: the void fully compensated the payment.
        assert get_member(member["id"])["lifetime_charged_cents"] == 0

    def test_abandon_paid_session_rejected(self, api):
        """PRD §3.4: "an unpaid session in `OPEN`, `REVIEW_HOLD`, or
        `OFFLINE_PAUSED` may instead be abandoned by its member, which moves
        the session to its terminal `ABANDONED` state, removes every
        non-`REMOVED` line, and expires any `PENDING` intercepts."

        Design: Corner/state_machines/abandon_paid_session_rejected
        """
        club, item, member, session, pay_data = setup_paid_session(
            price_cents=500, quantity=1,
        )
        resp = api.abandon_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)
        assert get_session(session["id"])["status"] == "PAID"


class TestEarlyHoursGate:
    def test_early_hours_plus_admitted_club_denied(self, api):
        """PRD §3.3: "In between — the early-shopping window, open at exactly
        `early_shopping_start_minute` and closed the moment `open_minute`
        arrives — session creation is reserved for members whose `tier` is
        `PLUS`; a `CLUB` member attempting to start a session inside the window
        is likewise rejected with `ERR_EARLY_HOURS_NOT_ELIGIBLE`."

        Design: Corner/calculations/early_hours_plus_admitted_club_denied
        """
        set_clock("2026-09-01T09:00:00Z")
        from test_helpers import create_club

        club = create_club(name="Club EH")
        plus_member = create_member(club["id"], tier="PLUS", birth_year=1990)
        club_member = create_member(club["id"], tier="CLUB", birth_year=1990)

        resp = api.create_scan_session(club["id"], member_headers(plus_member))
        plus_session = validate_success(resp, expected_status=201)
        assert plus_session["status"] == "OPEN"

        resp = api.create_scan_session(club["id"], member_headers(club_member))
        validate_error(resp, ApiErrorId.ERR_EARLY_HOURS_NOT_ELIGIBLE)

    def test_before_early_window_no_member_may_start(self, api):
        """PRD §3.3: "Before `early_shopping_start_minute`, no member may start
        a session at all, and the attempt is rejected with
        `ERR_EARLY_HOURS_NOT_ELIGIBLE` regardless of tier."

        Design: Corner/calculations/early_hours_plus_admitted_club_denied
        """
        set_clock("2026-09-01T06:00:00Z")  # 360 < early start 480
        from test_helpers import create_club

        club = create_club(name="Club EH2")
        plus_member = create_member(club["id"], tier="PLUS", birth_year=1990)
        resp = api.create_scan_session(club["id"], member_headers(plus_member))
        validate_error(resp, ApiErrorId.ERR_EARLY_HOURS_NOT_ELIGIBLE)
