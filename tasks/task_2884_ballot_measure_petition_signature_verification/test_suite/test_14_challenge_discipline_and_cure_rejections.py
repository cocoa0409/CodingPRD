"""Rejection catalogue, part two: the litigation dimension, the discipline
cascade, and the two-period cure path.

These four walks all take their refusals from states that only a long setup can
reach, and each refusal is positioned so its neighbours are provably satisfied:
the escalation window is probed at exactly `review_deadline_at` and then five
days earlier, the reinstatement bars are taken while the state gate above them
passes, and the third cure period is refused with the clock standing exactly on
the second period's exclusive deadline so the overlap rule cannot be the
explanation.
"""
from test_helpers import (
    api_client,
    assert_instants_equal,
    make_challenger_headers,
    make_examiner_headers,
    make_proponent_headers,
    make_sos_admin_headers,
    read_batch,
    read_challenge,
    read_circulator,
    read_cure_period,
    read_line,
    read_petition,
    setup_circulation_ready,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    file_batch_with_lines,
    file_challenge,
    invalidate_batch,
    issue_determination,
    open_cure_period,
    open_followup_round,
    open_referral,
    read_assignment,
    refer_referral_to_ag,
    reinstate_batch,
    run_followup_round,
    run_verification_round,
    set_clock,
    tally_round,
    validate_line,
)

FILING_CLOCK = "2026-08-10T00:00:00Z"
FILING_STAMP = "2026-08-10T00:00:00.000Z"
REVIEW_DEADLINE_STAMP = "2026-08-25T00:00:00.000Z"

ONE_ACTIVE_VOTER = [{"voter_id_number": "VA1", "registration_status": "ACTIVE"}]


def _challenged_world(jurisdiction_code):
    """A petition tallied SUFFICIENT by exam-1 at 2026-08-10, sitting in
    PENDING_CERTIFICATION with challenge_status NONE."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": jurisdiction_code,
            "signature_pct_bps": 100,
            "sufficiency_upper_bps": 10000,
        },
        counties=[("ALPHA", 20)],
        voters=ONE_ACTIVE_VOTER,
    )
    assert world["petition"]["required_valid_signatures"] == 1
    set_clock(FILING_CLOCK)
    file_batch_with_lines(world, ["VA1"])
    closed = run_verification_round(world)
    assert closed["determination"] == "SUFFICIENT"
    assert closed["tallied_by_examiner_id"] == "exam-1"
    pending = read_petition(world["petition"]["id"])
    assert pending["status"] == "PENDING_CERTIFICATION"
    assert pending["challenge_status"] == "NONE"
    world["petition"] = pending
    return world


class TestChallengeLifecycleAndReviewWindowRejections:
    """One live challenge at a time; it freezes the determination without
    freezing the petition's status."""

    def test_a_filed_challenge_locks_out_rivals_and_blocks_the_determination(self):
        """The filing stamps its own clock and a fifteen-day review deadline, a
        second challenger is refused, and `CERTIFY` is refused while the
        petition's own status stands still.

        PRD §3.8: "The server stores `challenger_user_id` from the `X-User-ID`
        header, stamps `filed_at` from the logical clock, and sets
        `review_deadline_at` to `filed_at` advanced by the fifteen-day statutory
        review window."

        PRD §3.8: "The petition's `challenge_status` must be `NONE`, else the
        filing is refused with `ERR_CHALLENGE_ALREADY_FILED` — one live challenge
        at a time."

        Design: Corner/validations/challenge_lifecycle_and_review_window_rejections
        """
        world = _challenged_world("SOS-X")
        petition_id = world["petition"]["id"]

        challenge = file_challenge(
            petition_id,
            challenger_user_id="chal-1",
            challenger_name="Vera Vigilant",
            grounds="COUNT_ERROR",
            statement="The projection overstates validity.",
        )
        assert challenge["status"] == "FILED"
        assert challenge["challenger_user_id"] == "chal-1"
        assert challenge["grounds"] == "COUNT_ERROR"
        assert challenge["ruling"] is None
        assert challenge["court_docket_number"] is None
        assert_instants_equal(challenge["filed_at"], FILING_STAMP)
        assert_instants_equal(challenge["review_deadline_at"], REVIEW_DEADLINE_STAMP)
        assert read_petition(petition_id)["challenge_status"] == "CHALLENGE_FILED"

        validate_error(
            api_client.create_challenge(
                petition_id,
                {
                    "challenger_name": "Rival Rick",
                    "grounds": "FORGERY",
                    "statement": "Second challenger.",
                },
                make_challenger_headers("chal-2"),
            ),
            "ERR_CHALLENGE_ALREADY_FILED",
            409,
        )

        validate_error(
            api_client.issue_determination(
                petition_id, {"determination": "CERTIFY"}, make_sos_admin_headers()
            ),
            "ERR_CHALLENGE_PENDING",
            409,
        )
        blocked = read_petition(petition_id)
        assert blocked["status"] == "PENDING_CERTIFICATION", (
            "PRD §3.8: filing does not change the petition's status"
        )
        assert blocked["challenge_status"] == "CHALLENGE_FILED"

    def test_escalation_separates_wrong_state_wrong_owner_and_a_closed_window(self):
        """Ruling before escalation, escalating as the wrong challenger, and
        escalating exactly on the deadline are three different refusals; five
        days earlier the same call goes through.

        PRD §3.8: "The challenge must be `FILED` and the logical clock must be
        strictly before `review_deadline_at`; a clock at or past that instant
        refuses the escalation with `ERR_CHALLENGE_REVIEW_WINDOW_EXPIRED`.
        Escalation is owner-restricted: the acting `X-User-ID` must equal the
        challenge's `challenger_user_id`, else the request is refused with
        `ERR_NOT_CHALLENGE_OWNER`."

        PRD §3.8: "Attempting to escalate, dismiss or rule on a challenge whose
        `status` does not match the transition's requirement is refused with
        `ERR_INVALID_CHALLENGE_STATE`."

        Design: Corner/validations/challenge_lifecycle_and_review_window_rejections
        """
        world = _challenged_world("SOS-X2")
        petition_id = world["petition"]["id"]
        challenge = file_challenge(petition_id, challenger_user_id="chal-1")
        challenge_id = challenge["id"]

        validate_error(
            api_client.rule_on_challenge(
                challenge_id, {"ruling": "AFFIRM"}, make_sos_admin_headers()
            ),
            "ERR_INVALID_CHALLENGE_STATE",
            409,
        )

        validate_error(
            api_client.escalate_challenge(
                challenge_id,
                {"court_docket_number": "CV-2026-9999"},
                make_challenger_headers("chal-2"),
            ),
            "ERR_NOT_CHALLENGE_OWNER",
            403,
        )
        assert read_challenge(challenge_id)["status"] == "FILED"

        set_clock("2026-08-25T00:00:00Z")
        validate_error(
            api_client.escalate_challenge(
                challenge_id,
                {"court_docket_number": "CV-2026-0001"},
                make_challenger_headers("chal-1"),
            ),
            "ERR_CHALLENGE_REVIEW_WINDOW_EXPIRED",
            409,
        )
        assert read_challenge(challenge_id)["court_docket_number"] is None

        set_clock("2026-08-20T00:00:00Z")
        escalated = validate_success(
            api_client.escalate_challenge(
                challenge_id,
                {"court_docket_number": "CV-2026-0001"},
                make_challenger_headers("chal-1"),
            )
        )
        assert escalated["status"] == "COURT_REVIEW", (
            "the identical call five days earlier proves the window was the only bar"
        )
        assert escalated["court_docket_number"] == "CV-2026-0001"
        assert read_petition(petition_id)["challenge_status"] == "COURT_REVIEW"

    def test_an_affirmed_challenge_is_terminal_and_releases_the_determination(self):
        """An `AFFIRM` ruling dismisses the challenge, leaves the petition
        pending, refuses a later dismissal, and lets the once-blocked `CERTIFY`
        through unchanged.

        PRD §3.8: "A `challenge_status` of `NONE`, `COURT_AFFIRMED` or
        `COURT_REVERSED` all pass, because in each of those states the litigation
        is either absent or concluded."

        Design: Corner/validations/challenge_lifecycle_and_review_window_rejections
        """
        world = _challenged_world("SOS-X3")
        petition_id = world["petition"]["id"]
        challenge_id = file_challenge(petition_id, challenger_user_id="chal-1")["id"]

        set_clock("2026-08-20T00:00:00Z")
        validate_success(
            api_client.escalate_challenge(
                challenge_id,
                {"court_docket_number": "CV-2026-0001"},
                make_challenger_headers("chal-1"),
            )
        )

        ruled = validate_success(
            api_client.rule_on_challenge(
                challenge_id, {"ruling": "AFFIRM"}, make_sos_admin_headers()
            )
        )
        assert ruled["status"] == "DISMISSED"
        assert ruled["ruling"] == "AFFIRM"
        affirmed = read_petition(petition_id)
        assert affirmed["challenge_status"] == "COURT_AFFIRMED"
        assert affirmed["status"] == "PENDING_CERTIFICATION", (
            "an AFFIRM does not itself decide the petition"
        )

        validate_error(
            api_client.dismiss_challenge(
                challenge_id, make_sos_admin_headers(), {"reason": "already ruled"}
            ),
            "ERR_INVALID_CHALLENGE_STATE",
            409,
        )
        assert read_challenge(challenge_id)["status"] == "DISMISSED"

        certified = issue_determination(petition_id, determination="CERTIFY")
        assert certified["status"] == "CERTIFIED"
        assert certified["challenge_status"] == "COURT_AFFIRMED"


def _substantiated_world():
    """One circulator, two affidavit-verified batches — the second struck for a
    clerical reason — and a substantiated fraud referral naming the first."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={"jurisdiction_code": "SOS-R"},
        counties=[("ALPHA", 20)],
        voters=ONE_ACTIVE_VOTER,
    )
    set_clock(FILING_CLOCK)
    b1 = file_batch_with_lines(
        world, [{"claimed_voter_id_number": "VA1", "signed_on": "2026-08-05T00:00:00Z"}]
    )
    b2 = file_batch_with_lines(
        world, [{"claimed_voter_id_number": "VA1", "signed_on": "2026-08-06T00:00:00Z"}]
    )
    struck = invalidate_batch(b2["batch"]["id"], invalidation_reason="clerical duplication")
    assert struck["status"] == "INVALIDATED"

    referral = open_referral(
        world["petition"]["id"],
        world["circulator"]["id"],
        batch_id=b1["batch"]["id"],
        referral_type="FORGED_SIGNATURES",
        opened_by="exam-1",
    )
    return world, b1, b2, referral


class TestPostSubstantiationDisciplineRejections:
    """Three refusals that all follow one substantiated referral, ordered so the
    priority between the statutory bar and the linkage bar is observable."""

    def test_a_substantiated_finding_cascades_four_levels_and_seals_its_batch(self):
        """Opening prices the circulator provisionally; substantiation voids the
        named batch, suspends the circulator and its assignment, and makes that
        batch permanently irreinstatable.

        PRD §3.9: "When the referral named a `batch_id`, that batch is set to
        `INVALIDATED` and every one of its lines not already `VOIDED` is set to
        `VOIDED` with a `void_reason` of `FRAUD_SUBSTANTIATED`, with the number
        of lines so voided recorded on the referral as
        `voided_signature_count`."

        PRD §3.9: "no `FraudReferral` naming this batch may have a `status` of
        `SUBSTANTIATED`, else it is refused with
        `ERR_FRAUD_SUBSTANTIATED_BATCH`."

        Design: Corner/validations/post_substantiation_discipline_rejections
        """
        world, b1, _b2, referral = _substantiated_world()
        circulator_id = world["circulator"]["id"]

        assert referral["status"] == "OPENED"
        assert referral["opened_by_examiner_id"] == "exam-1"
        assert referral["referred_to_ag"] is False
        assert referral["finding"] is None
        assert referral["adjudicated_by_examiner_id"] is None
        assert referral["voided_signature_count"] == 0
        assert read_circulator(circulator_id)["credibility_score_bps"] == 9500, (
            "provisional variant: 10000 with an empty checked base less one open referral"
        )

        forwarded = refer_referral_to_ag(referral["id"], examiner_id="exam-1")
        assert forwarded["status"] == "REFERRED_TO_AG"
        assert forwarded["referred_to_ag"] is True

        adjudicated = validate_success(
            api_client.adjudicate_referral(
                referral["id"],
                {"finding": "SUBSTANTIATED"},
                make_examiner_headers("exam-2"),
            )
        )
        assert adjudicated["status"] == "SUBSTANTIATED"
        assert adjudicated["finding"] == "SUBSTANTIATED"
        assert adjudicated["adjudicated_by_examiner_id"] == "exam-2"
        assert adjudicated["voided_signature_count"] == 1

        struck = read_batch(b1["batch"]["id"])
        assert struck["status"] == "INVALIDATED"
        voided = read_line(b1["lines"][0]["id"])
        assert voided["validation_status"] == "VOIDED"
        assert voided["void_reason"] == "FRAUD_SUBSTANTIATED"
        assert voided["status_before_void"] == "PENDING"

        disciplined = read_circulator(circulator_id)
        assert disciplined["misconduct_strike_count"] == 1
        assert disciplined["registration_status"] == "SUSPENDED"
        assert disciplined["credibility_score_bps"] == 8000, (
            "adjudicated variant: 10000 less one 2000-point strike, the open-referral "
            "penalty having dropped away"
        )
        assert read_assignment(world["assignment"]["id"])["status"] == "SUSPENDED"

        validate_error(
            api_client.reinstate_batch(b1["batch"]["id"], make_sos_admin_headers(), {}),
            "ERR_FRAUD_SUBSTANTIATED_BATCH",
            409,
        )
        assert read_batch(b1["batch"]["id"])["status"] == "INVALIDATED"

    def test_the_strike_bar_then_the_revoked_bar_outrank_the_batch_level_checks(self):
        """Reinstating the circulator is refused as a statutory 422 rather than a
        state error, and after revocation an unrelated struck batch is refused
        with the revoked bar rather than any linkage code.

        PRD §3.9: "it is barred when the suspension came from proven misconduct,
        so a `misconduct_strike_count` at or above the threshold of one refuses
        the request with `ERR_CIRCULATOR_REINSTATEMENT_BARRED`."

        PRD §3.9: "the batch circulator's `registration_status` must not be
        `REVOKED`, else the request is refused with `ERR_CIRCULATOR_REVOKED`."

        Design: Corner/validations/post_substantiation_discipline_rejections
        """
        world, _b1, b2, referral = _substantiated_world()
        circulator_id = world["circulator"]["id"]
        refer_referral_to_ag(referral["id"], examiner_id="exam-1")
        validate_success(
            api_client.adjudicate_referral(
                referral["id"],
                {"finding": "SUBSTANTIATED"},
                make_examiner_headers("exam-2"),
            )
        )
        assert read_circulator(circulator_id)["registration_status"] == "SUSPENDED"

        validate_error(
            api_client.reinstate_circulator(circulator_id, make_sos_admin_headers()),
            "ERR_CIRCULATOR_REINSTATEMENT_BARRED",
            422,
        )
        assert read_circulator(circulator_id)["registration_status"] == "SUSPENDED", (
            "the state gate above the strike bar passed, so this is not a state error"
        )

        revoked = validate_success(
            api_client.revoke_circulator(
                circulator_id, make_sos_admin_headers(), {"reason": "substantiated forgery"}
            )
        )
        assert revoked["registration_status"] == "REVOKED"
        assert revoked["credibility_score_bps"] == 8000
        assert read_assignment(world["assignment"]["id"])["status"] == "TERMINATED"

        assert read_batch(b2["batch"]["id"])["status"] == "INVALIDATED"
        validate_error(
            api_client.reinstate_batch(
                b2["batch"]["id"],
                make_sos_admin_headers(),
                {"invalidation_reason": "clerical duplication reversed"},
            ),
            "ERR_CIRCULATOR_REVOKED",
            422,
        )
        assert read_batch(b2["batch"]["id"])["status"] == "INVALIDATED", (
            "the revoked bar fires on a batch no referral ever named"
        )


CURE_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
]

CURE_LINES = [
    {"claimed_voter_id_number": "VA1", "signed_on": "2026-08-15T00:00:00Z"},
    {
        "claimed_voter_id_number": "VZ9",
        "signed_on": "2026-08-16T00:00:00Z",
        "signer_name": "Zoe Zephyr",
    },
]


def _cure_world():
    """Required 3, one VALID and one unregistered line, tallied INSUFFICIENT at
    2026-09-01 but above the eligibility floor, so the petition lands in
    CURE_PERIOD with no cure period yet opened."""
    set_clock(CLOCK_EPOCH)
    world = setup_circulation_ready(
        standard_overrides={
            "jurisdiction_code": "SOS-C",
            "signature_pct_bps": 300,
            "sufficiency_upper_bps": 10000,
            "sufficiency_lower_bps": 9000,
            "cure_allowed": True,
            "cure_window_days": 10,
            "cure_eligibility_floor_bps": 3000,
        },
        counties=[("ALPHA", 20)],
        voters=CURE_VOTERS,
        effective_to="2027-02-28T00:00:00Z",
    )
    assert world["petition"]["required_valid_signatures"] == 3
    file_batch_with_lines(world, CURE_LINES)

    set_clock("2026-09-01T00:00:00Z")
    closed = run_verification_round(world)
    assert closed["validity_rate_bps"] == 5000, "floor(1 * 10000 / 2)"
    assert closed["projected_valid_count"] == 1, "floor(2 * 5000 / 10000)"
    assert closed["determination"] == "INSUFFICIENT", "1 is at or below lower_gate 2"
    assert read_petition(world["petition"]["id"])["status"] == "CURE_PERIOD"
    return world


def _supplemental_batch_payload(world, **extra):
    payload = {
        "petition_id": world["petition"]["id"],
        "circulator_id": world["circulator"]["id"],
        "county_id": world["counties"]["ALPHA"]["id"],
        "affidavit_signed": True,
    }
    payload.update(extra)
    return payload


class TestCurePeriodLifecycleAndSupplementalLinkageRejections:
    """Both arms of the supplemental coherence rule, and a petition walked
    through both cure periods the statute permits."""

    def test_both_arms_of_the_coherence_rule_and_the_first_cure_target(self):
        """`is_supplemental` without a cure period and a cure period without
        `is_supplemental` are the same refusal; between them the first period
        opens with a target of four raw signatures and cannot yet be expired.

        PRD §3.7: "The pairing is strict in both directions — a batch declaring
        `is_supplemental` as `true` with no `cure_period_id`, and a batch
        supplying a `cure_period_id` while `is_supplemental` is `false`, are both
        refused with `ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD`."

        PRD §3.7: "And `cure_target_raw_signatures`, the number of raw
        supplemental lines the proponent must file, is `shortfall_at_open`
        multiplied by 10000, divided by `assumed_validity_rate_bps`, with any
        remainder rounded **up**; the clamp is applied before the division, not
        after."

        PRD §3.7: "Expiring one is a `SosAdmin` act taking no body, permitted
        only while the period is `OPEN` and only once the logical clock has
        reached or passed its `deadline_at`; expiring it while the clock is still
        strictly before that instant is refused with
        `ERR_CURE_PERIOD_NOT_EXPIRED`."

        Design: Corner/validations/cure_period_lifecycle_and_supplemental_linkage_rejections
        """
        world = _cure_world()
        petition_id = world["petition"]["id"]

        validate_error(
            api_client.create_signature_batch(
                _supplemental_batch_payload(world, is_supplemental=True),
                make_proponent_headers(),
            ),
            "ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD",
            409,
        )

        cure = open_cure_period(petition_id)
        assert cure["status"] == "OPEN"
        assert cure["shortfall_at_open"] == 2, "max(0, 3 - 1)"
        assert cure["assumed_validity_rate_bps"] == 5000, "min(10000, max(2500, 5000))"
        assert cure["cure_target_raw_signatures"] == 4, "ceil(2 * 10000 / 5000)"
        assert cure["supplemental_raw_count"] == 0
        assert_instants_equal(cure["opened_at"], "2026-09-01T00:00:00.000Z")
        assert_instants_equal(cure["deadline_at"], "2026-09-11T00:00:00.000Z")
        assert read_petition(petition_id)["cure_period_count"] == 1

        validate_error(
            api_client.expire_cure_period(cure["id"], make_sos_admin_headers()),
            "ERR_CURE_PERIOD_NOT_EXPIRED",
            409,
        )
        assert read_cure_period(cure["id"])["status"] == "OPEN"

        validate_error(
            api_client.create_signature_batch(
                _supplemental_batch_payload(world, cure_period_id=cure["id"]),
                make_proponent_headers(),
            ),
            "ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD",
            409,
        )

        supplemental = file_batch_with_lines(
            world,
            [{"claimed_voter_id_number": "VA2", "signed_on": "2026-09-02T00:00:00Z"}],
            is_supplemental=True,
            cure_period_id=cure["id"],
        )
        assert supplemental["batch"]["is_supplemental"] is True
        assert supplemental["batch"]["cure_period_id"] == cure["id"]
        assert supplemental["batch"]["accepted_raw_count"] == 1
        assert read_cure_period(cure["id"])["supplemental_raw_count"] == 1

    def test_the_second_period_opens_on_the_first_deadline_and_a_third_is_refused(self):
        """A cure recheck closes the first period insufficient, the second opens
        exactly on the first's exclusive deadline with a re-read assumed rate,
        and a third is refused on the count alone.

        PRD §3.7: "the petition's `cure_period_count` must be strictly below the
        statutory ceiling of two, refused with `ERR_CURE_LIMIT_REACHED`; and the
        new period must not overlap any existing cure period of the same
        petition, refused with `ERR_CURE_PERIOD_OVERLAP`."

        PRD §3.7: "The named period must belong to the same petition and must
        still be `OPEN`; a supplemental batch naming a period in any other status
        is refused with `ERR_CURE_PERIOD_NOT_OPEN`."

        PRD §3.7: "Expiry moves the period from `OPEN` to `EXPIRED`, advances the
        petition to `PENDING_FAILURE`, and causes any later supplemental batch
        naming that period to be rejected."

        Design: Corner/validations/cure_period_lifecycle_and_supplemental_linkage_rejections
        """
        world = _cure_world()
        petition_id = world["petition"]["id"]
        first = open_cure_period(petition_id)
        supplemental = file_batch_with_lines(
            world,
            [{"claimed_voter_id_number": "VA2", "signed_on": "2026-09-02T00:00:00Z"}],
            is_supplemental=True,
            cure_period_id=first["id"],
        )

        recheck = open_followup_round(
            world, round_type="CURE_RECHECK", cure_period_id=first["id"]
        )
        assert recheck["sample_size"] == 1, (
            "a CURE_RECHECK takes every still-unexamined eligible line, and only the "
            "supplemental line is left"
        )
        adjudicated = validate_line(
            supplemental["lines"][0]["id"], world["counties"]["ALPHA"]["id"]
        )
        assert adjudicated["validation_status"] == "VALID"
        closed = tally_round(recheck["id"])
        assert closed["validity_rate_bps"] == 10000, "floor(1 * 10000 / 1)"
        assert closed["determination"] == "INSUFFICIENT", "face value 2 is below required 3"
        assert read_cure_period(first["id"])["status"] == "CLOSED_INSUFFICIENT"
        assert read_petition(petition_id)["status"] == "CURE_PERIOD", (
            "one cure period remains permitted, so the petition does not fail yet"
        )

        set_clock("2026-09-11T00:00:00Z")
        second = open_cure_period(petition_id)
        assert second["shortfall_at_open"] == 1, "max(0, 3 - 2) read from verified_valid_count"
        assert second["assumed_validity_rate_bps"] == 10000, "the CURE_RECHECK round's rate"
        assert second["cure_target_raw_signatures"] == 1, "ceil(1 * 10000 / 10000)"
        assert_instants_equal(second["opened_at"], "2026-09-11T00:00:00.000Z")
        assert_instants_equal(second["deadline_at"], "2026-09-21T00:00:00.000Z")
        assert read_petition(petition_id)["cure_period_count"] == 2, (
            "opening exactly at the first period's exclusive deadline is not an overlap"
        )

        validate_error(
            api_client.create_signature_batch(
                _supplemental_batch_payload(
                    world, is_supplemental=True, cure_period_id=first["id"]
                ),
                make_proponent_headers(),
            ),
            "ERR_CURE_PERIOD_NOT_OPEN",
            409,
        )

        set_clock("2026-09-21T00:00:00Z")
        validate_error(
            api_client.create_cure_period(petition_id, make_sos_admin_headers()),
            "ERR_CURE_LIMIT_REACHED",
            409,
        )

        expired = validate_success(
            api_client.expire_cure_period(second["id"], make_sos_admin_headers())
        )
        assert expired["status"] == "EXPIRED"
        assert read_petition(petition_id)["status"] == "PENDING_FAILURE"


FLOOR_VOTERS = [
    {"voter_id_number": "VA1", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA2", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA3", "registration_status": "ACTIVE"},
    {"voter_id_number": "VA4", "registration_status": "ACTIVE"},
]


class TestCureEligibilityFloorBlocksReopenAfterLedgerDrop:
    """The eligibility floor is re-read at cure-period creation, so a ledger that
    drops between two identical calls changes the answer."""

    def test_invalidating_a_batch_drops_the_ledger_under_the_floor_and_back(self):
        """A petition sitting exactly on the floor is cure-eligible; striking one
        batch refuses the same call with the floor code while the petition stays
        in `CURE_PERIOD`; reinstating it lets the call through.

        PRD §3.7: "The standard's `cure_allowed` must be `true` and the
        petition's best available valid count must clear the cure eligibility
        floor, both refused with `ERR_CURE_NOT_ELIGIBLE`."

        PRD §3.9: "it restores each line's `validation_status` from its
        `status_before_void` verbatim and clears `status_before_void` and
        `void_reason`, so a line that was `VALID` returns to `VALID`."

        Design: Corner/validations/cure_eligibility_floor_blocks_reopen_after_ledger_drop
        """
        set_clock(CLOCK_EPOCH)
        world = setup_circulation_ready(
            standard_overrides={
                "jurisdiction_code": "SOS-F",
                "signature_pct_bps": 500,
                "sample_pct_bps": 5000,
                "sufficiency_upper_bps": 10000,
                "sufficiency_lower_bps": 4000,
                "cure_allowed": True,
                "cure_window_days": 10,
                "cure_eligibility_floor_bps": 8000,
            },
            counties=[("ALPHA", 40)],
            voters=FLOOR_VOTERS,
            measure_subject_codes=("ENVIRONMENT",),
            effective_to="2027-02-28T00:00:00Z",
        )
        petition_id = world["petition"]["id"]
        assert world["petition"]["required_valid_signatures"] == 5

        first = file_batch_with_lines(
            world,
            [
                {"claimed_voter_id_number": "VA1", "signed_on": "2026-08-05T00:00:00Z"},
                {"claimed_voter_id_number": "VA2", "signed_on": "2026-08-06T00:00:00Z"},
            ],
        )
        file_batch_with_lines(
            world,
            [
                {"claimed_voter_id_number": "VA3", "signed_on": "2026-08-07T00:00:00Z"},
                {"claimed_voter_id_number": "VA4", "signed_on": "2026-08-08T00:00:00Z"},
            ],
        )

        set_clock("2026-09-01T00:00:00Z")
        sampled = run_verification_round(world)
        assert sampled["sample_size"] == 2, "max(1, ceil(4 * 5000 / 10000))"
        assert sampled["projected_valid_count"] == 4
        assert sampled["determination"] == "FULL_CHECK_REQUIRED", (
            "4 lies strictly between lower_gate 2 and upper_gate 5"
        )
        assert read_petition(petition_id)["status"] == "FULL_CHECK"

        full = run_followup_round(world, round_type="FULL_CHECK", examiner_id="exam-2")
        assert full["validity_rate_bps"] == 10000
        assert full["determination"] == "INSUFFICIENT", "face value 4 is below required 5"

        eligible = read_petition(petition_id)
        assert eligible["verified_valid_count"] == 4, "exactly 5 * 8000 / 10000"
        assert eligible["status"] == "CURE_PERIOD"
        assert eligible["cure_period_count"] == 0

        struck = invalidate_batch(
            first["batch"]["id"], invalidation_reason="notary jurat defective"
        )
        assert struck["status"] == "INVALIDATED"
        dropped = read_petition(petition_id)
        assert dropped["verified_valid_count"] == 2
        assert dropped["voided_signature_count"] == 2
        assert dropped["status"] == "CURE_PERIOD", (
            "the drop does not move the petition, so the refusal below is not a state error"
        )

        validate_error(
            api_client.create_cure_period(petition_id, make_sos_admin_headers()),
            "ERR_CURE_NOT_ELIGIBLE",
            409,
        )
        assert read_petition(petition_id)["cure_period_count"] == 0, (
            "cure_period_count is still 0, so the refusal is not the limit code"
        )

        restored = reinstate_batch(
            first["batch"]["id"], invalidation_reason="jurat cured on the record"
        )
        assert restored["status"] == "FULLY_CHECKED", (
            "the RANDOM_SAMPLE round moved the batch to SAMPLED and the FULL_CHECK "
            "round to FULLY_CHECKED, so status_before_invalidation is FULLY_CHECKED "
            "and reinstatement restores it verbatim"
        )
        recovered = read_petition(petition_id)
        assert recovered["verified_valid_count"] == 4
        assert recovered["voided_signature_count"] == 0
        assert [read_line(line["id"])["validation_status"] for line in first["lines"]] == [
            "VALID",
            "VALID",
        ]

        cure = open_cure_period(petition_id)
        assert cure["shortfall_at_open"] == 1, "max(0, 5 - 4)"
        assert cure["assumed_validity_rate_bps"] == 10000, "the FULL_CHECK round's rate"
        assert cure["cure_target_raw_signatures"] == 1, "ceil(1 * 10000 / 10000)"
        assert read_petition(petition_id)["cure_period_count"] == 1, (
            "the identical call now succeeds, so the floor was the only obstacle"
        )
