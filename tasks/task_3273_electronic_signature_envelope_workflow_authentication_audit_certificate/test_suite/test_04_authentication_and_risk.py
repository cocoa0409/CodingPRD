"""Authentication challenges, access codes and identity risk scoring."""

from test_helpers import (
    api_client,
    get_recipient,
    make_recipient_headers,
    setup_recipient_with_kba_failures,
    setup_risk_peer_envelope,
    setup_sent_single_signer,
    validate_error,
    validate_success,
)


class TestAuthenticationChallenge:
    """§3.4: the challenge outcome and its recorded side effects."""

    def test_mismatched_access_code_is_rejected_and_marks_failure(self, api):
        """PRD §3.4: "An `access_code` that does not match the recipient's
        stored `access_code` is refused with `ERR_INVALID_ACCESS_CODE` (HTTP 401)."
        PRD §3.4: "On success the recipient's `auth_status` becomes
        `AUTHENTICATED`; on failure it becomes `FAILED`."

        Design: Corner/errors/invalid_access_code_rejected
        """
        ctx = setup_sent_single_signer(auth_level="ACCESS_CODE", subject="Wrong code envelope")
        account, recipient = ctx["account"], ctx["recipient"]
        recipient = get_recipient(recipient["id"], account)

        res = api_client.authenticate_recipient(
            recipient["id"],
            {"method": "ACCESS_CODE", "access_code": "WRONG"},
            make_recipient_headers(recipient["id"]),
        )
        validate_error(res, "ERR_INVALID_ACCESS_CODE")
        assert res.status_code == 401

        after = get_recipient(recipient["id"], account)
        assert after["auth_status"] == "FAILED", (
            f"a failed challenge must mark the auth dimension FAILED, got {after['auth_status']}"
        )


class TestKbaAttemptCap:
    """§3.4: the knowledge-based-question cap is reached at three failures."""

    def test_third_failure_is_still_processed(self, api):
        """PRD §3.4: "the cap is reached at a count of three, so a recipient
        with two prior failures may still make one more attempt."

        Design: Difficulty/boundary_precision_check/kba_third_failure_rejected_at_boundary
        """
        ctx = setup_recipient_with_kba_failures(failures=2)
        recipient = ctx["recipient"]
        assert recipient["kba_fail_count"] == 2

        third = validate_success(
            api_client.authenticate_recipient(
                recipient["id"],
                {"method": "KBA", "kba_answers_correct": False},
                make_recipient_headers(recipient["id"]),
            ),
            200,
        )
        assert third["kba_fail_count"] == 3, (
            f"an attempt at fail_count 2 is still processed, so the count must "
            f"reach 3, got {third['kba_fail_count']}"
        )

    def test_attempt_at_three_failures_is_rejected(self, api):
        """PRD §3.4: "A knowledge-based challenge attempted after the recipient
        has already accumulated three failures is refused with
        `ERR_AUTH_MAX_ATTEMPTS` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/kba_third_failure_rejected_at_boundary
        """
        ctx = setup_recipient_with_kba_failures(failures=2)
        recipient = ctx["recipient"]
        third = validate_success(
            api_client.authenticate_recipient(
                recipient["id"],
                {"method": "KBA", "kba_answers_correct": False},
                make_recipient_headers(recipient["id"]),
            ),
            200,
        )
        assert third["kba_fail_count"] == 3

        res = api_client.authenticate_recipient(
            third["id"],
            {"method": "KBA", "kba_answers_correct": False},
            make_recipient_headers(third["id"]),
        )
        validate_error(res, "ERR_AUTH_MAX_ATTEMPTS")
        assert res.status_code == 422, "the cap is enforced at HTTP 422"

    def test_two_failures_leave_the_recipient_one_attempt_short(self, api):
        """PRD §3.4: "the cap is reached at a count of three".

        Design: Difficulty/boundary_precision_check/kba_third_failure_rejected_at_boundary
        """
        ctx = setup_recipient_with_kba_failures(failures=2)
        recipient = ctx["recipient"]
        assert recipient["kba_fail_count"] == 2, (
            "two prior failures must be recorded as exactly two, so the "
            f"threshold is < 3 rather than <= 3, got {recipient['kba_fail_count']}"
        )
        res = api_client.authenticate_recipient(
            recipient["id"],
            {"method": "KBA", "kba_answers_correct": True},
            make_recipient_headers(recipient["id"]),
        )
        authenticated = validate_success(res, 200)
        assert authenticated["auth_status"] == "AUTHENTICATED", (
            "a recipient below the cap may still authenticate successfully"
        )


class TestIdentityRiskScoring:
    """§2.10: provisional and final variants of the identity risk score."""

    def test_provisional_and_final_diverge_by_the_peer_term(self, api):
        """PRD §2.10: "The peer-consensus term is ten points for each other
        recipient of the same envelope whose `auth_status` is `AUTHENTICATED`
        and whose `auth_level` is `ACCESS_CODE`, `KBA` or `ID_DOCUMENT` — that
        is, any level at or above `ACCESS_CODE`."
        PRD §2.10: "The provisional variant never includes that peer term, which
        is why the same recipient can read a lower provisional score than final
        score."
        PRD §2.10: "The final score, written to a recipient's
        `auth_risk_score_final` at the moment that recipient signs and never
        recomputed afterwards, is the raw total plus a peer-consensus term".

        Design: Difficulty/dual_variant_calc/auth_risk_score_provisional_vs_final
        """
        ctx = setup_risk_peer_envelope(
            peer_auth_level="ACCESS_CODE",
            target_auth_level="EMAIL_ACCESS",
            authenticate_peer=True,
        )
        account, target = ctx["account"], ctx["target"]

        assert target["auth_risk_score"] == 10, (
            "an EMAIL_ACCESS signer with no failures and no identity "
            f"verification has a provisional score of 10, got {target['auth_risk_score']}"
        )
        assert ctx["peer"]["auth_risk_score"] == 30, (
            f"the ACCESS_CODE peer's provisional score is 30, got {ctx['peer']['auth_risk_score']}"
        )

        signed = validate_success(
            api_client.sign_recipient(
                target["id"], make_recipient_headers(target["id"])
            ),
            200,
        )

        assert signed["auth_risk_score_final"] == 20, (
            "the final score adds ten points for the one authenticated "
            f"ACCESS_CODE peer, so it reads 20, got {signed['auth_risk_score_final']}"
        )
        assert signed["auth_risk_score_final"] != signed["auth_risk_score"], (
            "the two variants must diverge once a peer term exists"
        )

    def test_provisional_excludes_the_peer_term_after_authentication(self, api):
        """PRD §2.10: "The provisional score, written to a recipient's
        `auth_risk_score`, is recomputed for every recipient of an envelope
        whenever any authentication event occurs; it is the raw total clamped
        into the range from zero to one hundred, and it takes no account of the
        envelope's other recipients."

        Design: Difficulty/dual_variant_calc/auth_risk_score_provisional_vs_final
        """
        ctx = setup_risk_peer_envelope(
            peer_auth_level="ACCESS_CODE",
            target_auth_level="EMAIL_ACCESS",
            authenticate_peer=True,
        )
        account = ctx["account"]
        peer = ctx["peer"]
        target = ctx["target"]

        # The peer's authentication event recomputed the provisional score for
        # every recipient, and the target's provisional value ignores the peer.
        assert target["auth_risk_score"] == 10, (
            "the provisional variant is reject-transparent to peers: the "
            f"target's provisional score stays 10, got {target['auth_risk_score']}"
        )
        assert peer["auth_risk_score"] == 30, (
            f"the peer's own provisional score is its raw base, got {peer['auth_risk_score']}"
        )

    def test_final_score_is_not_computed_for_a_recipient_that_never_signed(self, api):
        """PRD §2.10: "The final score, written to a recipient's
        `auth_risk_score_final` at the moment that recipient signs and never
        recomputed afterwards".
        PRD §3.5: "The signing recipient's `auth_risk_score_final` is sealed at
        this moment by the final variant of §2.10 and is never recomputed."

        Design: Difficulty/dual_variant_calc/auth_risk_score_provisional_vs_final
        """
        ctx = setup_risk_peer_envelope(
            peer_auth_level="ACCESS_CODE",
            target_auth_level="EMAIL_ACCESS",
            authenticate_peer=True,
        )
        account = ctx["account"]

        peer = get_recipient(ctx["peer"]["id"], account)
        assert peer["auth_status"] == "AUTHENTICATED"
        assert peer["auth_risk_score_final"] == 0, (
            "the peer never signed, so its final score was never computed and "
            f"remains 0, got {peer['auth_risk_score_final']}"
        )

    def test_final_score_is_sealed_by_the_signature(self, api):
        """PRD §3.5: "The signing recipient's `auth_risk_score_final` is sealed
        at this moment by the final variant of §2.10 and is never recomputed."
        PRD §3.4: "On success the recipient's `auth_status` becomes
        `AUTHENTICATED`".

        Design: Difficulty/dual_variant_calc/auth_risk_score_provisional_vs_final
        """
        ctx = setup_risk_peer_envelope(
            peer_auth_level="ACCESS_CODE",
            target_auth_level="EMAIL_ACCESS",
            authenticate_peer=True,
        )
        target = ctx["target"]
        signed = validate_success(
            api_client.sign_recipient(target["id"], make_recipient_headers(target["id"])),
            200,
        )
        assert signed["status"] == "SIGNED", (
            f"the sign must commit for the final score to seal, got {signed['status']}"
        )
        assert signed["auth_risk_score_final"] == 20
        assert signed["auth_risk_score_final"] > signed["auth_risk_score"]