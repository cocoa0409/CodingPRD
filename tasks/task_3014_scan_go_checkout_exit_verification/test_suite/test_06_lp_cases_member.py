"""Loss-prevention case lifecycle, segregation of duties, member suspension."""
from test_helpers import (
    ADMIN,
    ASSOCIATE,
    LPO,
    MANAGER,
    ApiErrorId,
    create_item,
    create_member,
    create_session,
    make_lpo_headers,
    member_headers,
    scan_unit_line,
    setup_flagged_session_by_cv,
    validate_error,
    validate_success,
)


def _setup_flagged_with_case(api, lp_suspend_strikes=None):
    """CV_MISMATCH-flagged session flagged by opaque associate id assoc-1."""
    from test_helpers import create_club, patch_club, set_clock

    set_clock()
    club = create_club(exit_verification_mode="CV_ARCH")
    if lp_suspend_strikes is not None:
        club = patch_club(
            club["id"], club["version"], lp_suspend_strikes=lp_suspend_strikes,
        )
    item = create_item(club["id"], sku="MILK", unit_price_cents=300)
    member = create_member(club["id"], tier="CLUB", birth_year=1990)
    session = create_session(club, member)
    scan_unit_line(session, member, item, quantity=1)
    resp = api.pay_session(session["id"], member_headers(member))
    validate_success(resp)
    resp = api.exit_scan(session["id"], member_headers(member))
    verification = validate_success(resp, expected_status=201)

    from test_helpers import make_associate_headers

    resp = api.cv_report(
        verification["id"], 4, make_associate_headers("assoc-1"),
    )
    result = validate_success(resp)
    assert result["status"] == "MISMATCH", f"Setup failed: {resp.text}"
    resp = api.list_lp_cases(LPO)
    case = next(c for c in resp.json()["data"] if c["session_id"] == session["id"])
    return club, item, member, session, verification, case


class TestLpCaseLifecycle:
    def test_lp_case_escalation_path_open_ack_escalate_resolve(self, api):
        """PRD §3.7: "A case in `OPEN` may be acknowledged (`OPEN →
        ACKNOWLEDGED`) or escalated directly (`OPEN → ESCALATED`), and an
        `ACKNOWLEDGED` case may likewise be escalated (`ACKNOWLEDGED →
        ESCALATED`). Resolution — from `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`
        — records an `outcome` of `DISMISSED` or `CONFIRMED` and moves the
        case to its terminal `RESOLVED` state".

        Design: Corner/state_machines/lp_case_escalation_path_open_ack_escalate_resolve
        """
        _club, _item, _member, _session, _ev, case = _setup_flagged_with_case(api)
        lpo9 = make_lpo_headers("lpo-9")

        resp = api.acknowledge_lp_case(case["id"], lpo9)
        assert validate_success(resp)["status"] == "ACKNOWLEDGED"
        resp = api.escalate_lp_case(case["id"], lpo9)
        assert validate_success(resp)["status"] == "ESCALATED"
        resp = api.resolve_lp_case(case["id"], "CONFIRMED", lpo9)
        resolved = validate_success(resp)
        assert resolved["status"] == "RESOLVED"
        assert resolved["outcome"] == "CONFIRMED"

    def test_error_lp_case_not_open_on_double_resolve(self, api):
        """PRD §3.7: "any of these operations against a `RESOLVED` case is
        rejected with `ERR_LP_CASE_NOT_OPEN`. A dismissal gives the member
        their strike back: `unscanned_strikes` decreases by one, never below
        zero."

        Design: Corner/errors/error_lp_case_not_open_on_double_resolve
        """
        _club, _item, member, _session, _ev, case = _setup_flagged_with_case(api)
        lpo9 = make_lpo_headers("lpo-9")

        resp = api.resolve_lp_case(case["id"], "DISMISSED", lpo9)
        validate_success(resp)
        resp = api.get_member(member["id"], LPO)
        assert resp.json()["data"]["unscanned_strikes"] == 0

        resp = api.resolve_lp_case(case["id"], "CONFIRMED", lpo9)
        validate_error(resp, ApiErrorId.ERR_LP_CASE_NOT_OPEN)
        # No double decrement.
        resp = api.get_member(member["id"], LPO)
        assert resp.json()["data"]["unscanned_strikes"] == 0

    def test_sod_flagging_associate_cannot_resolve_own_case(self, api):
        """PRD §3.7: "Segregation of duties is enforced at resolution: the
        resolving officer's `X-User-ID` must differ from the case's
        `flagging_associate_id`, and a violation is rejected with
        `ERR_SO_DUTY_VIOLATION` (HTTP 403) — the associate who flagged a
        mismatch can never close their own case."

        Design: Corner/cross_cutting_layers/sod_flagging_associate_cannot_resolve_own_case
        """
        _club, _item, _member, _session, _ev, case = _setup_flagged_with_case(api)
        assert case["flagging_associate_id"] == "assoc-1"

        resp = api.resolve_lp_case(
            case["id"], "CONFIRMED", make_lpo_headers("assoc-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SO_DUTY_VIOLATION)

        resp = api.resolve_lp_case(case["id"], "CONFIRMED", make_lpo_headers("lpo-9"))
        assert validate_success(resp)["status"] == "RESOLVED"


class TestSuspensionAndReinstate:
    def test_suspended_member_cannot_create_session(self, api):
        """PRD §3.2: "Session creation is refused with ... `ERR_MEMBER_INACTIVE`
        when the member is `SUSPENDED`"; PRD §3.7: "the moment a member's
        strikes reach the club's `lp_suspend_strikes` — the boundary is
        inclusive — the member's `status` flips from `ACTIVE` to `SUSPENDED`,
        after which they can no longer create scan sessions or pay."

        Design: Corner/state_machines/suspended_member_cannot_create_session_and_reinstate_restores
        """
        club, _item, member, _session, _ev, _case = _setup_flagged_with_case(
            api, lp_suspend_strikes=1,
        )
        resp = api.get_member(member["id"], LPO)
        assert resp.json()["data"]["status"] == "SUSPENDED"

        resp = api.create_scan_session(club["id"], member_headers(member))
        validate_error(resp, ApiErrorId.ERR_MEMBER_INACTIVE)

    def test_reinstate_restores_active_and_zeroes_strikes(self, api):
        """PRD §3.7: "A suspended member is restored by a
        `LossPreventionOfficer` through reinstatement, which returns the
        member to `ACTIVE` and zeroes their `unscanned_strikes`."

        Design: Corner/state_machines/suspended_member_cannot_create_session_and_reinstate_restores
        """
        club, _item, member, _session, _ev, _case = _setup_flagged_with_case(
            api, lp_suspend_strikes=1,
        )
        resp = api.reinstate_member(member["id"], LPO)
        reinstated = validate_success(resp)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["unscanned_strikes"] == 0

        resp = api.create_scan_session(club["id"], member_headers(member))
        new_session = validate_success(resp, expected_status=201)
        assert new_session["id"]
