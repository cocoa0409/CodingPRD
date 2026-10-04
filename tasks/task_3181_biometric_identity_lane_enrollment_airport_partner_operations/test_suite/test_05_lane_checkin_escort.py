"""Lane check-in and escort: escort window boundary, member-status gating,
OCC on member version, wrong-ambassador denial, and federal-trusted upgrade."""
from test_helpers import (
    ApiErrorId,
    check_in_member,
    create_active_member_with_subscription,
    escort_member,
    make_ambassador_headers,
    make_member_headers,
    create_ambassador,
    set_clock,
    setup_lane_environment,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS, PM, CO


def _env_with_member(federal=False):
    env = setup_lane_environment(federal_integration=federal)
    member, sub = create_active_member_with_subscription(env["center"], plan="INDIVIDUAL")
    env["member"] = member
    env["subscription"] = sub
    return env


class TestEscortWindowBoundary:
    def test_escort_exactly_at_expires_at_allowed(self, api):
        """PRD §3.5: "The escort window check permits completion while the logical clock is
        at or before `expires_at`; exactly at the deadline is allowed, and one minute
        later is refused with `ERR_ESCORT_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/escort_at_exactly_expires_at_allowed_one_minute_later_rejected
        """
        env = _env_with_member(federal=True)
        set_clock("2026-09-01T09:00:00Z")
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        set_clock("2026-09-01T09:15:00Z")  # exactly verified_at + 15 minutes
        escorted = escort_member(verification, env["ambassador"])
        assert escorted["escort_status"] == "ESCORTED", (
            "escort exactly at expires_at is allowed (closed boundary)"
        )

    def test_escort_one_minute_later_rejected(self, api):
        """PRD §3.5: "The escort window check permits completion while the logical clock is
        at or before `expires_at`; exactly at the deadline is allowed, and one minute
        later is refused with `ERR_ESCORT_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/escort_at_exactly_expires_at_allowed_one_minute_later_rejected
        """
        env = _env_with_member(federal=True)
        set_clock("2026-09-01T09:00:00Z")
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        set_clock("2026-09-01T09:16:00Z")
        resp = api.escort(
            verification["id"], verification["version_confirmed"],
            make_ambassador_headers(env["ambassador"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ESCORT_WINDOW_EXPIRED)
        verification_after = validate_success(
            api.get_lane_verification(verification["id"], OPS)
        )
        assert verification_after["escort_status"] == "PENDING"


class TestCheckInMemberGate:
    def test_check_in_succeeds_while_member_active(self, api):
        """PRD §3.5: "Check-in requires the lane to be `OPEN` (`ERR_LANE_NOT_OPEN`), the
        member to be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the member's subscription to
        be `ACTIVE` or `PAST_DUE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), the lane's
        agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), and the ambassador to
        be `ACTIVE` and homed at the same airport as the lane (`ERR_WRONG_AMBASSADOR`)."

        Design: Difficulty/cross_entity_state_dependency/lane_checkin_blocked_by_member_suspension_and_lane_not_open
        """
        env = _env_with_member()
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        assert verification["escort_status"] == "PENDING"

    def test_check_in_blocked_after_member_suspension(self, api):
        """PRD §3.5: "Check-in requires the lane to be `OPEN` (`ERR_LANE_NOT_OPEN`), the
        member to be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`)" — after an admin suspension
        the same check-in on the still-OPEN lane fails on the member gate.

        Design: Difficulty/cross_entity_state_dependency/lane_checkin_blocked_by_member_suspension_and_lane_not_open
        """
        env = _env_with_member()
        check_in_member(env["member"], env["lane"], env["ambassador"])
        validate_success(api.admin_suspend_member(env["member"]["id"], OPS))
        resp = api.check_in(
            {"member_id": env["member"]["id"], "lane_id": env["lane"]["id"],
             "ambassador_id": env["ambassador"]["id"]},
            make_member_headers(env["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        lane_after = validate_success(api.get_lane(env["lane"]["id"], OPS))
        assert lane_after["status"] == "OPEN", "lane state unchanged"


class TestEscortOccStaleVersion:
    def test_escort_with_stale_member_version_rejected_412(self, api):
        """PRD §2.6: "If the member's version has advanced since check-in — for instance
        because a dispute suspension or a family-slot change landed in between — the
        escort is rejected with `ERR_STALE_VERSION`, forcing the caller to re-read the
        member before proceeding."

        Design: Corner/errors/escort_stale_member_version_returns_412
        """
        env = _env_with_member(federal=True)
        set_clock("2026-09-01T09:00:00Z")
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        validate_success(api.admin_suspend_member(env["member"]["id"], OPS))
        resp = api.escort(
            verification["id"], verification["version_confirmed"],
            make_ambassador_headers(env["ambassador"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        verification_after = validate_success(
            api.get_lane_verification(verification["id"], OPS)
        )
        assert verification_after["escort_status"] == "PENDING"

    def test_escort_with_current_member_version_succeeds(self, api):
        """PRD §2.6: "completing an escort — the ambassador action that moves a lane
        verification from `PENDING` to `ESCORTED` — requires the non-optional input
        `expected_member_version`, carrying the member `version` the client observed
        at check-in (which the check-in response itself pinned as `version_confirmed`)."

        Design: Corner/errors/escort_stale_member_version_returns_412
        """
        env = _env_with_member(federal=True)
        set_clock("2026-09-01T09:00:00Z")
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        escorted = escort_member(verification, env["ambassador"])
        assert escorted["escort_status"] == "ESCORTED"


class TestWrongAmbassador:
    def test_escort_by_other_ambassador_rejected(self, api):
        """PRD §2.1: "completing an escort requires that the lane verification's named
        ambassador match `X-User-ID`."
        PRD §3.5: "the ambassador to be `ACTIVE` and homed at the same airport as the
        lane (`ERR_WRONG_AMBASSADOR`)"

        Design: Corner/roles/ambassador_escort_requires_named_ambassador
        """
        env = _env_with_member()
        wrong_ambassador = create_ambassador(env["airport"]["id"], employee_ref="E601")
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        resp = api.escort(
            verification["id"], verification["version_confirmed"],
            make_ambassador_headers(wrong_ambassador["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WRONG_AMBASSADOR)
        verification_after = validate_success(
            api.get_lane_verification(verification["id"], OPS)
        )
        assert verification_after["escort_status"] == "PENDING"

    def test_named_ambassador_escorts_successfully(self, api):
        """PRD §2.1: "completing an escort requires that the lane verification's named
        ambassador match `X-User-ID`." — the named ambassador's escort succeeds.

        Design: Corner/roles/ambassador_escort_requires_named_ambassador
        """
        env = _env_with_member()
        verification = check_in_member(env["member"], env["lane"], env["ambassador"])
        escorted = escort_member(verification, env["ambassador"])
        assert escorted["escort_status"] == "ESCORTED"


class TestFederalTrustedUpgrade:
    def _setup_two_airports(self):
        fed = setup_lane_environment(federal_integration=True)
        fed["member"], fed["subscription"] = create_active_member_with_subscription(
            fed["center"], email="fed@x.com", document_number="PF000100",
        )
        reg = setup_lane_environment(federal_integration=False)
        reg["member"], reg["subscription"] = create_active_member_with_subscription(
            reg["center"], email="reg@x.com", document_number="PF000101",
        )
        return fed, reg

    def test_federal_lane_escort_upgrades_to_federal_trusted(self, api):
        """PRD §3.5: "The `federal_program` flag is computed at check-in: it is true when the
        lane's agreement has `federal_integration` enabled and the member's enrolled
        `document_type` is `PASSPORT` or `DRIVERS_LICENSE`" and "when `federal_program`
        is true and the member's `verification_level` is not yet `FEDERAL_TRUSTED`,
        completing the escort upgrades the member to `FEDERAL_TRUSTED`"

        Design: Corner/endpoints/federal_trusted_upgrade_only_on_federal_integration_lane
        """
        fed, _ = self._setup_two_airports()
        verification = check_in_member(fed["member"], fed["lane"], fed["ambassador"])
        assert verification["federal_program"] is True
        escort_member(verification, fed["ambassador"])
        member_after = validate_success(api.get_member(fed["member"]["id"], OPS))
        assert member_after["verification_level"] == "FEDERAL_TRUSTED"

    def test_non_federal_lane_escort_confers_no_upgrade(self, api):
        """PRD §3.5: "The `federal_program` flag is computed at check-in: it is true when the
        lane's agreement has `federal_integration` enabled and the member's enrolled
        `document_type` is `PASSPORT` or `DRIVERS_LICENSE`" — with the flag disabled
        the flag is false and no upgrade follows.

        Design: Corner/endpoints/federal_trusted_upgrade_only_on_federal_integration_lane
        """
        _, reg = self._setup_two_airports()
        verification = check_in_member(reg["member"], reg["lane"], reg["ambassador"])
        assert verification["federal_program"] is False
        escort_member(verification, reg["ambassador"])
        member_after = validate_success(api.get_member(reg["member"]["id"], OPS))
        assert member_after["verification_level"] != "FEDERAL_TRUSTED"
