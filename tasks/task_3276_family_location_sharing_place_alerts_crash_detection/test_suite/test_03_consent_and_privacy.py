"""Consent lifecycle, privacy modes, OCC on privacy, and parallel dimensions."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    create_fix_payload,
    get_member_state,
    invite_and_grant_member,
    invite_and_grant_minor,
    invite_member,
    make_admin_headers,
    make_member_headers,
    make_minor_headers,
    make_owner_headers,
    privacy_payload,
    invite_grant_promote_admin,
    post_fix,
    reset_clock,
    start_trip,
    report_crash_for_member,
    set_clock,
    run_sweeps,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client


class TestMinorConsentLock:
    def test_minor_consent_revoke_by_admin_locked(self, api, system_headers):
        """PRD §3.2: "For a `MINOR` target, only the `OWNER` may revoke; an
        attempt by an `ADMIN`, by another member, or by the minor themselves is
        rejected with `ERR_MINOR_CONSENT_LOCKED` (HTTP 403)."

        Design: Corner/errors/err_minor_consent_locked_for_admin_revoke
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="LockFam")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="K2", email="k2@example.com")
        admin, admin_headers = _ = None, None
        admin, admin_headers = invite_grant_promote_admin(
            circle, owner_headers, display_name="Adm", email="adm@example.com",
        )
        resp = api.revoke_consent(circle["id"], kid["id"], admin_headers)
        validate_error(resp, "ERR_MINOR_CONSENT_LOCKED")

    def test_minor_consent_revoke_by_minor_self_locked(self, api, system_headers):
        """PRD §3.2: "For a `MINOR` target, only the `OWNER` may revoke; an
        attempt by an `ADMIN`, by another member, or by the minor themselves is
        rejected with `ERR_MINOR_CONSENT_LOCKED` (HTTP 403)."

        Design: Corner/errors/err_minor_consent_locked_for_admin_revoke
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="LockFam2")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="K3", email="k3@example.com")
        resp = api.revoke_consent(circle["id"], kid["id"], make_minor_headers(kid["id"]))
        validate_error(resp, "ERR_MINOR_CONSENT_LOCKED")


class TestPrivacyAntiCoercion:
    def test_privacy_self_only_for_hidden_lift(self, api, system_headers):
        """PRD §3.3: "Moving from `HIDDEN` back to `PRECISE` is the strictest
        transition: only the member themselves may perform it, by presenting an
        `X-User-ID` that equals the target `member_id`. Any other actor
        attempting to lift `HIDDEN` to `PRECISE` is rejected with
        `ERR_PRIVACY_SELF_ONLY` (HTTP 403)."

        Design: Corner/errors/err_privacy_self_only_for_hidden_lift
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="PrivFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="H", email="h@example.com")
        member_headers = make_member_headers(member["id"])
        v1 = get_member_state(circle["id"], member["id"], member_headers)["version"]
        validate_success(api.patch_privacy(
            circle["id"], member["id"], privacy_payload("HIDDEN", v1), member_headers,
        ))
        v2 = get_member_state(circle["id"], member["id"], member_headers)["version"]
        resp = api.patch_privacy(
            circle["id"], member["id"], privacy_payload("PRECISE", v2), owner_headers,
        )
        validate_error(resp, "ERR_PRIVACY_SELF_ONLY")
        after = get_member_state(circle["id"], member["id"], member_headers)
        assert after["privacy_mode"] == "HIDDEN"

    def test_privacy_hidden_lift_by_self_succeeds_and_clears_tension(self, api, system_headers):
        """PRD §3.3: "A successful lift to `PRECISE` also clears the
        `tension_flag`."

        Design: Corner/errors/err_privacy_self_only_for_hidden_lift
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="PrivFam3")
        member = invite_and_grant_member(circle, owner_headers, display_name="H2", email="h2@example.com")
        member_headers = make_member_headers(member["id"])
        v1 = get_member_state(circle["id"], member["id"], member_headers)["version"]
        validate_success(api.patch_privacy(
            circle["id"], member["id"], privacy_payload("HIDDEN", v1), member_headers,
        ))
        v2 = get_member_state(circle["id"], member["id"], member_headers)["version"]
        lifted = validate_success(api.patch_privacy(
            circle["id"], member["id"], privacy_payload("PRECISE", v2), member_headers,
        ))
        assert lifted["privacy_mode"] == "PRECISE"
        assert lifted["tension_flag"] is False


class TestPrivacyOcc:
    def test_stale_version_on_privacy_patch_rejected(self, api, system_headers):
        """PRD §2.7: "a request to patch a member's `privacy_mode` must carry
        `expected_member_version` matching the member's current `version`. In
        both cases the field is non-optional. If the supplied value does not
        match the parent's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_on_privacy_patch_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="StaleFam")
        member = invite_member(circle, owner_headers, display_name="Stale", email="stale@example.com")
        stale_version = member["version"]
        # Consent grant advances the member's version beyond the stale read.
        validate_success(api.grant_consent(
            circle["id"], member["id"],
            {"scope": "FULL", "monetization_opt_in": False},
            make_member_headers(member["id"]),
        ))
        resp = api.patch_privacy(
            circle["id"], member["id"],
            privacy_payload("HIDDEN", stale_version),
            make_member_headers(member["id"]),
        )
        validate_error(resp, "ERR_STALE_VERSION")

    def test_occ_version_increments_on_privacy_flip(self, api, system_headers):
        """PRD §3.3: "Every successful `privacy_mode` mutation increments the
        member's `version`."
        PRD §2.7: "If the supplied value does not match the parent's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_privacy_flip
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="OccFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="OCC", email="occ@example.com")
        member_headers = make_member_headers(member["id"])
        v1 = get_member_state(circle["id"], member["id"], member_headers)["version"]
        flipped = validate_success(api.patch_privacy(
            circle["id"], member["id"], privacy_payload("BLURRED", v1), member_headers,
        ))
        assert flipped["version"] == v1 + 1
        resp = api.patch_privacy(
            circle["id"], member["id"], privacy_payload("PRECISE", v1), member_headers,
        )
        validate_error(resp, "ERR_STALE_VERSION")


class TestParallelDimensions:
    def test_privacy_flip_leaves_consent_and_promotion_unaffected(self, api, system_headers):
        """PRD §3.3: "Moving from either `PRECISE` or `BLURRED` to `HIDDEN` may
        also be performed by the owner, an admin, or the member themselves, but
        it requires the target's `consent_state` to be `GRANTED` — attempting to
        apply `HIDDEN` while the target is `REVOKED` or `EXPIRED` is rejected
        with `ERR_CONSENT_NOT_GRANTED`."
        PRD §3.3: "Every successful `privacy_mode` mutation increments the
        member's `version`."
        PRD §3.2: "Promoting a `MEMBER` to `ADMIN` requires that the target's
        `consent_state` is `GRANTED` and that the circle's posture is not
        `FROZEN`."

        Design: Difficulty/non_linear_state_machine/member_parallel_dimensions_consent_x_privacy
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="ParFam")
        mia = invite_and_grant_member(circle, owner_headers, display_name="Mia", email="mia@example.com")
        mia_headers = make_member_headers(mia["id"])
        v1 = get_member_state(circle["id"], mia["id"], mia_headers)["version"]
        hidden = validate_success(api.patch_privacy(
            circle["id"], mia["id"], privacy_payload("HIDDEN", v1), mia_headers,
        ))
        assert hidden["privacy_mode"] == "HIDDEN"
        assert hidden["consent_state"] == "GRANTED"
        promoted = validate_success(api.promote_member(circle["id"], mia["id"], owner_headers))
        assert promoted["role"] == "ADMIN"
        assert promoted["privacy_mode"] == "HIDDEN"
        assert promoted["consent_state"] == "GRANTED"
        assert promoted["version"] == v1 + 2

    def test_consent_revoke_leaves_role_unchanged(self, api, system_headers):
        """PRD §3.2: "A successful revocation appends a `ConsentRecord` with
        `consent_action` `REVOKE`, flips the member's `consent_state` to
        `REVOKED`, increments the member's `version`, and triggers three
        compensations across the rest of the system: every location fix the
        member's device subsequently submits is recorded as `REJECTED_CONSENT`
        rather than accepted; every `OPEN` crash event on that member
        transitions to `FALSE_ALARM`; and every wellness check still `SENT` for
        that member is `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/member_parallel_dimensions_consent_x_privacy
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="ParFam2")
        member = invite_and_grant_member(circle, owner_headers, display_name="Rey", email="rey@example.com")
        promote = validate_success(api.promote_member(circle["id"], member["id"], owner_headers))
        assert promote["role"] == "ADMIN"
        validate_success(api.revoke_consent(
            circle["id"], member["id"], make_admin_headers(member["id"]),
        ))
        after = get_member_state(circle["id"], member["id"], owner_headers)
        assert after["consent_state"] == "REVOKED"
        assert after["role"] == "ADMIN"
