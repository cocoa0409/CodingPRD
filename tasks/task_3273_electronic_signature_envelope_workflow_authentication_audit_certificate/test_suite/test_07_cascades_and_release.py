"""Cascade propagation: declines, signatures and the routing release chain."""

from test_helpers import (
    api_client,
    get_recipient,
    make_account_headers,
    make_recipient_headers,
    setup_parallel_decline_envelope,
    setup_sequential_routing_pair,
    sign_recipient,
    validate_success,
)


class TestDeclineCascade:
    """§3.5: a decline is terminal for the envelope as a whole, and each hop is
    caused by the previous one."""

    def test_decline_bubbles_from_recipient_to_envelope(self, api):
        """PRD §3.5: "It moves the recipient to `DECLINED` and bubbles up: the
        owning envelope takes the `DECLINED` status with the supplied
        `decline_reason` captured on it".
        PRD §3.5: "Declining is therefore terminal for the envelope as a whole,
        not merely for the one recipient."

        Design: Difficulty/transitive_cascade/decline_recipient_cascades_to_envelope_to_peers_to_sessions
        """
        ctx = setup_parallel_decline_envelope(subject="Decline cascade envelope")
        account, envelope, decliner = ctx["account"], ctx["envelope"], ctx["decliner"]

        res = api_client.decline_recipient(
            decliner["id"],
            {"decline_reason": "Terms unacceptable"},
            make_recipient_headers(decliner["id"]),
        )
        declined = validate_success(res, 200)
        assert declined["status"] == "DECLINED", (
            f"the acting recipient becomes DECLINED, got {declined['status']}"
        )

        after = validate_success(
            api_client.get_envelope(envelope["id"], make_account_headers(account["id"])), 200
        )
        assert after["status"] == "DECLINED", (
            "the recipient's decline bubbles up to the owning envelope, "
            f"got {after['status']}"
        )
        assert after["decline_reason"] == "Terms unacceptable", (
            f"the decline_reason must be captured, got {after['decline_reason']!r}"
        )

    def test_decline_voids_the_in_flight_peer(self, api):
        """PRD §3.5: "every other recipient still in `WAITING`, `SENT`,
        `DELIVERED` or `SIGNING` is moved to `VOIDED`".
        PRD §2.6: "When a recipient declines and the decline bubbles up, the
        envelope takes the `DECLINED` status and every other recipient that was
        still in `WAITING`, `SENT`, `DELIVERED` or `SIGNING` moves to `VOIDED`".

        Design: Difficulty/transitive_cascade/decline_recipient_cascades_to_envelope_to_peers_to_sessions
        """
        ctx = setup_parallel_decline_envelope(subject="Decline cascade envelope two")
        account, decliner, peer = ctx["account"], ctx["decliner"], ctx["peer"]
        assert peer["status"] in ("SENT", "DELIVERED", "SIGNING")
        assert peer["id"] != decliner["id"]

        validate_success(
            api_client.decline_recipient(
                decliner["id"],
                {"decline_reason": "Terms unacceptable"},
                make_recipient_headers(decliner["id"]),
            ),
            200,
        )

        after = get_recipient(peer["id"], account)
        assert after["status"] == "VOIDED", (
            "the peer was in flight when the envelope declined, so it must be "
            f"VOIDED, got {after['status']}"
        )

    def test_decline_closes_the_peers_open_session(self, api):
        """PRD §3.5: "every open signing session belonging to a recipient of
        that envelope moves to `DECLINED`".
        PRD §2.6: "open sessions move to `DECLINED`".

        Design: Difficulty/transitive_cascade/decline_recipient_cascades_to_envelope_to_peers_to_sessions
        """
        ctx = setup_parallel_decline_envelope(subject="Decline cascade envelope three")
        account, decliner, peer_session = ctx["account"], ctx["decliner"], ctx["peer_session"]
        assert peer_session["status"] == "OPEN"

        validate_success(
            api_client.decline_recipient(
                decliner["id"],
                {"decline_reason": "Terms unacceptable"},
                make_recipient_headers(decliner["id"]),
            ),
            200,
        )

        after = validate_success(
            api_client.get_session(
                peer_session["id"], make_account_headers(account["id"])
            ),
            200,
        )
        assert after["status"] == "DECLINED", (
            "the peer's open session moves to DECLINED with the decline cascade, "
            f"got {after['status']}"
        )


class TestRoutingRelease:
    """§3.5: signing releases the next routing group, which then recomputes its
    provisional risk score."""

    def test_signing_releases_the_next_routing_group(self, api):
        """PRD §3.5: "the next routing group is released: every recipient of the
        envelope at the next-higher `routing_order` whose status is still
        `WAITING` moves to `SENT` with `auth_status` `PENDING`."
        PRD §3.2: "Every recipient at routing order 1 moves to `SENT` with
        `auth_status` `PENDING`".

        Design: Difficulty/transitive_cascade/sign_releases_next_routing_group_and_recomputes_peer_scores
        """
        ctx = setup_sequential_routing_pair(subject="Routing release envelope")
        account = ctx["account"]
        second = ctx["second"]
        assert second["status"] == "WAITING", (
            "the routing_order-2 recipient is WAITING before the first signs, "
            f"got {second['status']}"
        )

        signed = sign_recipient(ctx["first"])
        assert signed["status"] == "SIGNED", f"the sign must commit, got {signed['status']}"

        released = get_recipient(second["id"], account)
        assert released["status"] == "SENT", (
            f"signing releases the next routing order, so the peer becomes SENT, got {released['status']}"
        )
        assert released["auth_status"] == "PENDING", (
            f"a released recipient starts PENDING, got {released['auth_status']}"
        )

    def test_released_recipient_carries_its_recomputed_risk_score(self, api):
        """PRD §2.10: "The provisional score, written to a recipient's
        `auth_risk_score`, is recomputed for every recipient of an envelope
        whenever any authentication event occurs".
        PRD §2.10: "The score begins from a base that depends on the level: ten
        for `EMAIL_ACCESS`, thirty for `ACCESS_CODE`, fifty-five for `KBA` and
        eighty for `ID_DOCUMENT`."

        Design: Difficulty/transitive_cascade/sign_releases_next_routing_group_and_recomputes_peer_scores
        """
        ctx = setup_sequential_routing_pair(
            first_auth_level="KBA",
            second_auth_level="ID_DOCUMENT",
            subject="Routing release envelope two",
        )
        account = ctx["account"]
        second = ctx["second"]

        sign_recipient(ctx["first"])

        released = get_recipient(second["id"], account)
        assert released["auth_level"] == "ID_DOCUMENT"
        assert released["auth_risk_score"] == 80, (
            "the released ID_DOCUMENT recipient's provisional score is its raw "
            f"base of 80, got {released['auth_risk_score']}"
        )

def test_only_the_lowest_routing_order_is_released_at_send(api):
    """PRD §3.2: "Every recipient at routing order 1 moves to `SENT` with
    `auth_status` `PENDING`".
    PRD §3.3: "In a `SEQUENTIAL` envelope a recipient is released only when
    every recipient of the envelope whose role is `SIGNER` or `APPROVER` and
    whose `routing_order` is lower has already reached a terminal-attempted
    recipient status — `SIGNED`, `APPROVED`, `DECLINED` or `VOIDED`."

    The send releases only the lowest group, so the higher group is still
    waiting until the first recipient completes.

    Design: Difficulty/transitive_cascade/sign_releases_next_routing_group_and_recomputes_peer_scores
    """
    ctx = setup_sequential_routing_pair(subject="Routing release envelope three")
    account = ctx["account"]
    first = ctx["first"]
    second = ctx["second"]

    assert first["routing_order"] == 1
    assert second["routing_order"] == 2
    assert first["status"] in ("SENT", "DELIVERED", "SIGNING"), (
        f"the routing_order-1 recipient is released by the send, got {first['status']}"
    )
    assert second["status"] == "WAITING", (
        "the routing_order-2 recipient is held back until the first is "
        f"terminal-attempted, got {second['status']}"
    )
    assert second["auth_status"] == "PENDING", (
        f"a recipient that has not been released is still PENDING, got {second['auth_status']}"
    )
