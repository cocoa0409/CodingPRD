"""Member invite, role transitions, ownership transfer, and the age sweep."""
from test_helpers import (
    TEST_USERS,
    create_circle,
    create_member_payload,
    get_member_state,
    grant_consent_as_owner,
    invite_and_grant_member,
    invite_and_grant_minor,
    invite_member,
    make_member_headers,
    make_minor_headers,
    make_owner_headers,
    privacy_payload,
    reset_clock,
    run_sweeps,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


class TestMemberInvite:
    def test_member_invite_defaults_to_pending_consent_and_minor_role_for_under16(self, api, system_headers):
        """PRD §3.2: "If that age is less than 16 the new member is assigned the
        `MINOR` role; otherwise they are assigned `MEMBER`. Newly invited members
        always start with `consent_state` `PENDING`, and the invite increments the
        circle's `version`."
        PRD §3.3: "Each member's `privacy_mode` is one of `PRECISE`, `BLURRED`, or
        `HIDDEN`, defaulting to `PRECISE` at join."
        PRD §3.4: "the member's `sampling_profile` (`HIGH`, `BALANCED`, or
        `SAVER`, defaulting to `BALANCED`)"

        Design: Corner/entities/member_invite_defaults_to_pending_consent_and_minor_role_for_under16
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="InviteFam")
        kid = get_member_state(
            circle["id"],
            validate_success(api.invite_member(
                circle["id"],
                create_member_payload(
                    display_name="Young", birthdate="2014-06-06T00:00:00Z",
                    email="young@example.com",
                ),
                owner_headers,
            ), 201)["id"],
            owner_headers,
        )
        assert kid["role"] == "MINOR"
        assert kid["consent_state"] == "PENDING"
        assert kid["privacy_mode"] == "PRECISE"
        assert kid["sampling_profile"] == "BALANCED"
        assert kid["tension_flag"] is False
        adult = validate_success(api.invite_member(
            circle["id"],
            create_member_payload(
                display_name="Old", birthdate="2000-06-06T00:00:00Z",
                email="old@example.com",
            ),
            owner_headers,
        ), 201)
        assert adult["role"] == "MEMBER"
        assert adult["consent_state"] == "PENDING"

    def test_member_invite_boundary_at_exactly_sixteen_is_member_role(self, api, system_headers):
        """PRD §3.2: "If that age is less than 16 the new member is assigned the
        `MINOR` role; otherwise they are assigned `MEMBER`."

        Design: Corner/entities/member_invite_defaults_to_pending_consent_and_minor_role_for_under16
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="BoundaryFam")
        sixteen = validate_success(api.invite_member(
            circle["id"],
            create_member_payload(
                display_name="Sixteen", birthdate="2010-08-31T00:00:00Z",
                email="sixteen@example.com",
            ),
            owner_headers,
        ), 201)
        assert sixteen["role"] == "MEMBER"
        assert sixteen["consent_state"] == "PENDING"

    def test_member_age_years_computed_ignores_client_supplied_value(self, api, system_headers):
        """PRD §3.2: "The server computes the invitee's `age_years` as the floor
        of the difference between the current logical-clock date and the
        `birthdate`, expressed in units of 365.25 days."

        Design: Corner/entities/member_age_years_computed_ignores_client_supplied_value
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AgeFam")
        resp = api.invite_member(
            circle["id"],
            create_member_payload(
                display_name="Forged", birthdate="2010-01-01T00:00:00Z",
                email="forged@example.com", age_years=99,
            ),
            owner_headers,
        )
        if resp.status_code in (400, 422):
            validate_error(resp, "ERR_INVALID_REQUEST")
            return
        member = validate_success(resp, 201)
        assert member["age_years"] != 99, (
            "client-supplied age_years must not override the computed value"
        )


class TestRoleTransitions:
    def test_member_promote_minor_rejected(self, api, system_headers):
        """PRD §3.2: "Promoting a `MINOR` to `ADMIN` is rejected with
        `ERR_ROLE_INCOMPATIBLE`."

        Design: Corner/state_machines/member_promote_minor_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="PromoFam")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="Y", email="y@example.com")
        resp = api.promote_member(circle["id"], kid["id"], owner_headers)
        validate_error(resp, "ERR_ROLE_INCOMPATIBLE")
        after = get_member_state(circle["id"], kid["id"], owner_headers)
        assert after["role"] == "MINOR"

    def test_member_promote_granted_member_to_admin_succeeds(self, api, system_headers):
        """PRD §3.2: "Promoting a `MEMBER` to `ADMIN` requires that the target's
        `consent_state` is `GRANTED` and that the circle's posture is not
        `FROZEN`; a successful promotion sets the target's `role` to `ADMIN` and
        increments the member's `version`."

        Design: Corner/state_machines/member_promote_minor_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="PromoOkFam")
        member = invite_and_grant_member(circle, owner_headers, display_name="Pm", email="pm@example.com")
        before = member["version"]
        promoted = validate_success(
            api.promote_member(circle["id"], member["id"], owner_headers)
        )
        assert promoted["role"] == "ADMIN"
        assert promoted["version"] == before + 1

    def test_transfer_ownership_to_minor_rejected(self, api, system_headers):
        """PRD §3.2: "the target's `consent_state` must be `GRANTED`, and the
        target's role must not be `MINOR` — violations are rejected with
        `ERR_ROLE_INCOMPATIBLE`."

        Design: Corner/state_machines/transfer_ownership_to_minor_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="XferFam")
        kid = invite_and_grant_minor(circle, owner_headers, display_name="Y2", email="y2@example.com")
        resp = api.transfer_ownership(
            circle["id"], {"target_member_id": kid["id"]}, owner_headers,
        )
        validate_error(resp, "ERR_ROLE_INCOMPATIBLE")
        after = api.get_circle(circle["id"], owner_headers).json()["data"]
        assert after["owner_member_id"] == circle["owner_member_id"]

    def test_transfer_ownership_to_non_granted_target_rejected(self, api, system_headers):
        """PRD §3.2: "the target's `consent_state` must be `GRANTED`, and the
        target's role must not be `MINOR` — violations are rejected with
        `ERR_ROLE_INCOMPATIBLE`."

        Design: Corner/state_machines/transfer_ownership_to_minor_rejected
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="XferPendingFam")
        pending = invite_member(circle, owner_headers, display_name="Pend", email="pend@example.com")
        resp = api.transfer_ownership(
            circle["id"], {"target_member_id": pending["id"]}, owner_headers,
        )
        validate_error(resp, "ERR_ROLE_INCOMPATIBLE")


class TestAgeSweep:
    def test_age_sweep_promotes_minor_to_member_at_16(self, api, system_headers):
        """PRD §3.9: "When a `MINOR` member's recomputed age reaches 16, the
        member's `role` is promoted to `MEMBER`, the parent-imposed privacy
        override lock is released, the `tension_flag` is cleared, and the
        `privacy_mode` itself is preserved unchanged."

        Design: Corner/state_machines/age_sweep_promotes_minor_to_member_at_16
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="AgeFam2")
        # Birthdate one day after the boot-clock date 16 years earlier, so the
        # invitee is 15 at join and turns 16 when the clock crosses 2026-09-02.
        kid = invite_member(
            circle, owner_headers, display_name="Ag",
            birthdate="2010-09-02T00:00:00Z", email="ag@example.com",
        )
        grant_consent_as_owner(circle, owner_headers, kid["id"])
        kid_state = get_member_state(circle["id"], kid["id"], owner_headers)
        assert kid_state["role"] == "MINOR"
        # Owner flips the minor to HIDDEN, raising the tension flag.
        resp = api.patch_privacy(
            circle["id"], kid["id"],
            privacy_payload("HIDDEN", kid_state["version"]),
            owner_headers,
        )
        flipped = validate_success(resp)
        assert flipped["tension_flag"] is True
        # Cross the 16th birthday and run the sweep.
        set_clock("2026-09-02T00:00:01Z")
        run_sweeps()
        after = get_member_state(circle["id"], kid["id"], owner_headers)
        assert after["role"] == "MEMBER"
        assert after["tension_flag"] is False
        assert after["privacy_mode"] == "HIDDEN"

    def test_age_sweep_leaves_under_16_minor_unchanged(self, api, system_headers):
        """PRD §3.9: "When a `MINOR` member's recomputed age reaches 16, the
        member's `role` is promoted to `MEMBER`, the parent-imposed privacy
        override lock is released, the `tension_flag` is cleared, and the
        `privacy_mode` itself is preserved unchanged."

        Design: Corner/state_machines/age_sweep_promotes_minor_to_member_at_16
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="YoungFam")
        kid = invite_member(
            circle, owner_headers, display_name="Yg",
            birthdate="2010-09-02T00:00:00Z", email="yg@example.com",
        )
        grant_consent_as_owner(circle, owner_headers, kid["id"])
        # One second before the 16th birthday: no promotion.
        set_clock("2026-09-01T23:59:59Z")
        run_sweeps()
        after = get_member_state(circle["id"], kid["id"], owner_headers)
        assert after["role"] == "MINOR"


class TestMemberListFilters:
    def test_list_members_filters_by_role(self, api, system_headers):
        """PRD §4: "GET /api/circles/{id}/members | List members of a circle"
        (the member list accepts `role` and `consent_state` filters).

        Design: Corner/endpoints/list_members_filters_by_role
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FilterFam")
        invite_member(circle, owner_headers, display_name="K", birthdate="2012-01-01T00:00:00Z", email="k@example.com")
        invite_member(circle, owner_headers, display_name="A", birthdate="1990-01-01T00:00:00Z", email="a@example.com")
        data, meta = validate_paginated(
            api.list_members(circle["id"], owner_headers, params={"role": "MINOR"})
        )
        assert meta["total_count"] == 1
        assert all(m["role"] == "MINOR" for m in data)
        data2, meta2 = validate_paginated(
            api.list_members(
                circle["id"], owner_headers,
                params={"role": "MINOR", "consent_state": "GRANTED"},
            )
        )
        assert meta2["total_count"] == 0

    def test_list_members_filters_by_role_member(self, api, system_headers):
        """PRD §4: "GET /api/circles/{id}/members | List members of a circle"
        (the member list accepts `role` and `consent_state` filters).

        Design: Corner/endpoints/list_members_filters_by_role
        """
        reset_clock()
        circle, owner_headers = create_circle(tier="FREE", name="FilterFam2")
        invite_member(circle, owner_headers, display_name="K2", birthdate="2012-01-01T00:00:00Z", email="k2f@example.com")
        invite_member(circle, owner_headers, display_name="A2", birthdate="1990-01-01T00:00:00Z", email="a2f@example.com")
        data, meta = validate_paginated(
            api.list_members(circle["id"], owner_headers, params={"role": "MEMBER"})
        )
        assert meta["total_count"] == 1
        assert data[0]["role"] == "MEMBER"
