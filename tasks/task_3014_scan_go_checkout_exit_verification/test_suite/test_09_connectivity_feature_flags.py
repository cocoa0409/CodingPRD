"""Connectivity failover and club-level feature flags."""
from test_helpers import (
    ADMIN,
    MANAGER,
    ApiErrorId,
    create_club,
    create_item,
    create_member,
    create_session,
    get_session,
    member_headers,
    scan_unit_line,
    setup_club_member,
    setup_paid_session,
    setup_session_with_unit_item,
    validate_error,
    validate_success,
)


class TestOfflinePauseAndRestore:
    def test_offline_pause_and_restore_cycle(self, api):
        """PRD §3.5: "When a `ClubManager` sets a club's posture to
        `OFFLINE_FALLBACK`, every session at that club in `OPEN` or
        `REVIEW_HOLD` moves to `OFFLINE_PAUSED`"; "When the posture is set
        back to `ONLINE` or `DEGRADED`, every `OFFLINE_PAUSED` session at the
        club returns to `OPEN` — sessions always resume to `OPEN`, never back
        to `REVIEW_HOLD`, because the intercepts that expired during the
        outage stay `EXPIRED` and their lines stay `REMOVED`."

        Design: Corner/state_machines/offline_pause_and_restore_cycle
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=500, quantity=1,
        )
        resp = api.set_connectivity(club["id"], "OFFLINE_FALLBACK", MANAGER)
        validate_success(resp)
        assert get_session(session["id"])["status"] == "OFFLINE_PAUSED"

        resp = api.set_connectivity(club["id"], "ONLINE", MANAGER)
        validate_success(resp)
        reread = get_session(session["id"])
        assert reread["status"] == "OPEN"
        # The cart survives the outage.
        assert reread["provisional_total_cents"] == 500


class TestFeatureFlags:
    def test_scan_go_disabled_blocks_new_sessions(self, api):
        """PRD §2.9: "Separately, the `scan_go_enabled` flag on a club —
        defaulting to enabled — is a static kill switch: while it is off, no
        new scan sessions may be started at that club regardless of posture."

        Design: Corner/cross_cutting_layers/scan_go_disabled_blocks_new_sessions
        """
        club, member = setup_club_member()
        item = create_item(club["id"], sku="MILK", unit_price_cents=500)
        session = create_session(club, member)

        club_now = patch_club_flip(api, club["id"])

        # Existing session keeps scanning after the flag flip.
        line = scan_unit_line(session, member, item, quantity=1)
        assert line["id"]

        member_b = create_member(club["id"], tier="CLUB", birth_year=1991)
        resp = api.create_scan_session(club["id"], member_headers(member_b))
        validate_error(resp, ApiErrorId.ERR_CLUB_SCAN_GO_DISABLED)

    def test_offline_fallback_blocks_new_sessions(self, api):
        """PRD §2.9: "new scan sessions cannot be created while
        `OFFLINE_FALLBACK`"; PRD §3.5: "only `OFFLINE_FALLBACK` pauses
        sessions, blocks new sessions with `ERR_CLUB_OFFLINE`".

        Design: Corner/cross_cutting_layers/offline_fallback_blocks_new_sessions
        """
        club, member = setup_club_member()
        resp = api.set_connectivity(club["id"], "OFFLINE_FALLBACK", MANAGER)
        validate_success(resp)

        resp = api.create_scan_session(club["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_CLUB_OFFLINE)

        resp = api.set_connectivity(club["id"], "ONLINE", MANAGER)
        validate_success(resp)
        resp = api.create_scan_session(club["id"], member_headers(member))
        session = validate_success(resp, expected_status=201)
        assert session["id"]

    def test_offline_payment_requires_fallback_flag_and_uses_provisional(self, api):
        """PRD §3.4: "a session in `OFFLINE_PAUSED` may be paid only when the
        club has `allow_offline_payment` enabled (otherwise the attempt is
        rejected with `ERR_SESSION_NOT_OPEN`), and in that case
        `final_total_cents` is taken as the `provisional_total_cents` with no
        re-pricing at all".

        Design: Corner/cross_cutting_layers/offline_payment_requires_fallback_flag_and_uses_provisional
        """
        club, item, member, session, _line = setup_session_with_unit_item(
            price_cents=1000, quantity=1,
        )
        resp = api.set_connectivity(club["id"], "OFFLINE_FALLBACK", MANAGER)
        validate_success(resp)
        # Reprice mid-outage: an offline pay must not see the new price.
        resp = api.update_catalog_item(item["id"], {"unit_price_cents": 1300}, ADMIN)
        assert resp.status_code == 200, f"Setup failed: {resp.text}"

        resp = api.pay_session(session["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_OPEN)

        # Enable offline payment (OCC: read fresh club version).
        resp = api.get_club(club["id"], MANAGER)
        current_version = resp.json()["data"]["version"]
        resp = api.update_club(
            club["id"],
            {
                "expected_club_version": current_version,
                "allow_offline_payment": True,
            },
            MANAGER,
        )
        assert resp.status_code == 200, f"Setup failed: {resp.text}"

        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        # Provisional total used; the 1300c reprice is skipped offline.
        assert paid["final_total_cents"] == 1000

    def test_verification_method_not_enabled_by_club_mode(self, api):
        """PRD §2.10: "A club declares which exit-verification methods it
        operates through `exit_verification_mode`: `RECEIPT_CODE`, `CV_ARCH`,
        or `BOTH`. Requesting a method the club has not enabled is rejected
        with `ERR_VERIFICATION_METHOD_NOT_ENABLED`."; PRD §3.6: "when the
        method is omitted it is taken from the club's
        `exit_verification_mode`."

        Design: Corner/cross_cutting_layers/verification_method_not_enabled_by_club_mode
        """
        club, item, member, session, pay_data = setup_paid_session(
            price_cents=500, quantity=1,
        )
        resp = api.exit_scan(session["id"], member_headers(member), method="CV_ARCH")
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_METHOD_NOT_ENABLED)

        resp = api.exit_scan(session["id"], member_headers(member))
        verification = validate_success(resp, expected_status=201)
        assert verification["method"] == "RECEIPT_CODE"
        assert verification["status"] == "PENDING"


def patch_club_flip(api, club_id):
    """Flip scan_go_enabled off using the club's current version (OCC)."""
    resp = api.get_club(club_id, MANAGER)
    current_version = resp.json()["data"]["version"]
    resp = api.update_club(
        club_id,
        {"expected_club_version": current_version, "scan_go_enabled": False},
        MANAGER,
    )
    assert resp.status_code == 200, f"Setup failed: {resp.text}"
    return resp.json()["data"]
