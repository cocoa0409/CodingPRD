"""Lifecycle transitions on the policy term, the activity sanction and the roster.

A quoted term walks to bound and then on risk one step at a time; a step that is
not legal from the row's present state is refused and leaves the row untouched; a
cancelled term accepts nothing further; and withdrawing an athlete from a policy
roster lands every one of its declared side effects in a single call.
"""
from test_helpers import (
    SANCTIONING_OFFICIAL_USER_ID,
    THIRD_OFFICIAL_USER_ID,
    ApiErrorId,
    activate_policy,
    bind_policy,
    canonical_iso,
    create_league,
    create_sport_classification,
    make_league_admin_headers,
    make_league_official_headers,
    make_program_admin_headers,
    quote_policy,
    read_activity,
    read_enrollment,
    read_participant,
    read_policy,
    set_clock,
    setup_enrolled_athlete,
    setup_sanctioned_activity,
    validate_error,
    validate_success,
)

PROGRAM_ADMIN_HEADERS = make_program_admin_headers()


def _quoted_baseball_term():
    """One league, one moderate-hazard baseball classification and one QUOTED
    term declared on 404 participants with the catastrophic layer elected."""
    league = create_league()
    sport_classification = create_sport_classification("baseball")
    policy = quote_policy(league["id"], sport_classification["id"])
    return league, sport_classification, policy


def test_policy_term_walks_quoted_to_bound_to_active_one_version_step_at_a_time(api):
    """PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."
    PRD §3.2: "On success the whole premium build-up is recomputed from scratch, `status` moves `QUOTED → BOUND`, the holding league's `in_force_policy_count` increases by one, and posture is recomputed."
    PRD §3.2: "A bound term goes on risk as `BOUND → ACTIVE` once the logical clock has reached or passed its `term_effective_date`; attempting it earlier is refused, and posture is recomputed on success."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."

    Design: Corner/state_machines/policy_quoted_to_bound_to_active_happy_path_with_initial_states
    """
    _league, _sport_classification, policy = _quoted_baseball_term()

    assert policy["status"] == "QUOTED", (
        f"a freshly quoted term must start at QUOTED, got {policy['status']!r}"
    )
    assert policy["renewal_quote_status"] == "NONE"
    assert policy["version"] == 1, (
        f"version starts at 1 on the quote, got {policy['version']}"
    )

    bound = validate_success(
        api.bind_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS), expected_status=200
    )
    assert bound["status"] == "BOUND", (
        f"binding moves QUOTED -> BOUND, got {bound['status']!r}"
    )
    assert bound["version"] == 2, (
        f"binding is one mutation of the term, so version must read 2, got {bound['version']}"
    )

    activated = validate_success(
        api.activate_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS),
        expected_status=200,
    )
    assert activated["status"] == "ACTIVE", (
        f"activation moves BOUND -> ACTIVE, got {activated['status']!r}"
    )
    assert activated["version"] == 3, (
        f"activation is a second mutation, so version must read 3, got {activated['version']}"
    )

    reread = read_policy(policy["id"])
    assert reread["status"] == "ACTIVE"
    assert reread["version"] == 3


def test_activated_term_declared_on_404_athletes_reads_its_banded_annual_premium(api):
    """PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
    PRD §3.2: "The gross premium slices the declared head count into three cumulative volume bands and prices each band separately."
    PRD §3.2: "The first band covers participants 1 through 75 at full rate — a factor of exactly 1.0000."
    PRD §3.2: "The second band covers participants 76 through 400 at a factor of 0.9250, a seven-and-a-half percent volume discount."
    PRD §3.2: "The third band covers every participant beyond 400 at a factor of 0.8500."
    PRD §3.2: "Concretely, the first band's head count is the declared count capped at 75; the second band's head count is the declared count capped at 400 with 75 subtracted, and is zero if that subtraction would go negative; the third band's head count is the declared count with 400 subtracted, and is likewise zero if that would go negative."
    PRD §3.2: "Each band produces one line item: multiply that band's head count by the sport's `base_rate_per_participant_cents`, multiply by that band's factor, then apply the sport's `hazard_load_bps` by multiplying by ten thousand plus the load and dividing by ten thousand — and **round the line item half up to whole cents at that point**."
    PRD §3.2: "`gross_premium_cents` is then the plain sum of the three already-rounded band lines."
    PRD §3.2: "If `cat_layer_elected` is true, `cat_layer_charge_cents` is the gross premium multiplied by 850 basis points — eight and a half percent — divided by ten thousand and rounded half up to whole cents."
    PRD §3.2: "`premium_subtotal_cents` is the gross premium plus the catastrophic layer charge."
    PRD §3.2: "A subtotal below 500,000 cents (five thousand dollars) earns no credit at all; a subtotal from 500,000 through 1,499,999 cents earns 300 basis points; a subtotal from 1,500,000 through 4,999,999 cents earns 550 basis points; a subtotal of 5,000,000 cents (fifty thousand dollars) or more earns 800 basis points."
    PRD §3.2: "`volume_credit_cents` is the subtotal multiplied by `volume_credit_bps`, divided by ten thousand, and rounded half up to whole cents."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."

    Design: Corner/state_machines/policy_quoted_to_bound_to_active_happy_path_with_initial_states
    """
    _league, _sport_classification, policy = _quoted_baseball_term()
    bind_policy(policy["id"])
    activate_policy(policy["id"])

    on_risk = read_policy(policy["id"])
    assert on_risk["status"] == "ACTIVE"
    # 75 x 1850 x 1.0000 x 1.1150 -> 154706; 325 x 1850 x 0.9250 x 1.1150 -> 620114;
    # 4 x 1850 x 0.8500 x 1.1150 -> 7013; gross 781833; cat layer charge 66456;
    # subtotal 848289 earns 300 bps -> credit 25449.
    assert on_risk["annual_premium_cents"] == 822840, (
        "the 404-athlete moderate-hazard term with the catastrophic layer elected "
        f"rates at 822840 cents, got {on_risk['annual_premium_cents']}"
    )


def test_activated_term_with_no_claims_and_a_sanctioned_league_reads_an_open_posture(api):
    """PRD §2.8: "The posture is selected by walking six tests strictly from the top and stopping at the first that matches:"
    PRD §2.8: "If the policy's `status` is `CLOSED` or `CANCELLED`, the posture is `FROZEN`."
    PRD §2.8: "Otherwise, if the holding league's `sanctioning_status` is `SUSPENDED`, the posture is `FROZEN`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "The test is inclusive: an incurred loss exactly equal to the aggregate limit freezes the term."
    PRD §2.8: "Otherwise, if the policy's `open_claim_count` is three or more, the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."
    PRD §3.1: "A newly registered league starts with `sanctioning_status` set to `SANCTIONED` and `in_force_policy_count` set to 0."

    Design: Corner/state_machines/policy_quoted_to_bound_to_active_happy_path_with_initial_states
    """
    league, _sport_classification, policy = _quoted_baseball_term()
    assert league["sanctioning_status"] == "SANCTIONED"
    bind_policy(policy["id"])
    activate_policy(policy["id"])

    on_risk = read_policy(policy["id"])
    assert on_risk["status"] == "ACTIVE"
    assert on_risk["coverage_posture"] == "OPEN", (
        "an active term on a sanctioned league with no incurred loss and no open "
        f"claim matches none of the six posture tests, got {on_risk['coverage_posture']!r}"
    )


def test_activation_of_a_term_that_was_never_bound_is_refused_and_leaves_it_quoted(api):
    """PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."
    PRD §3.2: "A bound term goes on risk as `BOUND → ACTIVE` once the logical clock has reached or passed its `term_effective_date`; attempting it earlier is refused, and posture is recomputed on success."
    PRD §2.7: "**The addressed resource's own state** — the row is in a state from which the requested transition is legal."
    PRD §2.7: "The rejection names the entity whose state blocked it: `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_FAMILY_PLAN_STATE`, `ERR_INVALID_ACTIVITY_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COORDINATION_STATE`, `ERR_INVALID_BILL_STATE` or `ERR_INVALID_PAYMENT_STATE`, each HTTP 409."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."

    Design: Corner/state_machines/activate_on_a_quoted_policy_that_was_never_bound_rejected
    """
    _league, _sport_classification, policy = _quoted_baseball_term()
    assert policy["status"] == "QUOTED"
    assert policy["version"] == 1

    validate_error(
        api.activate_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_POLICY_STATE,
        expected_status=409,
    )

    unchanged = read_policy(policy["id"])
    assert unchanged["status"] == "QUOTED", (
        "going on risk is only legal from BOUND, so the refused call must leave the "
        f"term at QUOTED, got {unchanged['status']!r}"
    )
    assert unchanged["version"] == 1, (
        f"a refused action mutates nothing, so version stays 1, got {unchanged['version']}"
    )


def test_second_bind_on_an_already_bound_term_is_refused_on_the_terms_own_state(api):
    """PRD §3.2: "Binding requires the policy to be in `QUOTED`, the holding league to be `SANCTIONED` (otherwise `ERR_LEAGUE_NOT_SANCTIONED`), the declared `enrolled_participant_count` to be at least the sport's `minimum_participants` (otherwise `ERR_MINIMUM_PARTICIPANTS_NOT_MET`), and no other policy for the same league-and-sport pairing whose `status` is `BOUND`, `ACTIVE` or `RUN_OFF` to hold a term intersecting this one (otherwise `ERR_POLICY_TERM_OVERLAP`)."
    PRD §3.2: "On success the whole premium build-up is recomputed from scratch, `status` moves `QUOTED → BOUND`, the holding league's `in_force_policy_count` increases by one, and posture is recomputed."
    PRD §2.7: "Checks are evaluated strictly in the sequence below, and the **first** violated check determines the response; no later check is evaluated once one has failed."
    PRD §2.7: "**The addressed resource's own state** — the row is in a state from which the requested transition is legal."
    PRD §2.7: "The rejection names the entity whose state blocked it: `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_FAMILY_PLAN_STATE`, `ERR_INVALID_ACTIVITY_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COORDINATION_STATE`, `ERR_INVALID_BILL_STATE` or `ERR_INVALID_PAYMENT_STATE`, each HTTP 409."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."

    Design: Corner/state_machines/second_bind_on_an_already_bound_policy_rejected_as_invalid_from_state
    """
    _league, _sport_classification, policy = _quoted_baseball_term()
    bound = bind_policy(policy["id"])
    assert bound["status"] == "BOUND"
    assert bound["version"] == 2

    validate_error(
        api.bind_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_POLICY_STATE,
        expected_status=409,
    )

    unchanged = read_policy(policy["id"])
    assert unchanged["status"] == "BOUND", (
        "the term's own state blocks the replay before the overlap rule is reached, "
        f"and the term stays BOUND, got {unchanged['status']!r}"
    )
    assert unchanged["version"] == 2, (
        f"the refused replay is not a mutation, so version stays 2, got {unchanged['version']}"
    )


def test_second_sanction_decision_on_a_sanctioned_activity_keeps_the_first_officials_id(api):
    """PRD §3.4: "Every new activity starts in `PENDING_SANCTION`, with `sanctioning_official_id` and `rejection_reason` both null."
    PRD §3.4: "Both branches require the activity to be in `PENDING_SANCTION`; a decision on an activity that has already been decided is refused with `ERR_INVALID_ACTIVITY_STATE`."
    PRD §3.4: "A `SANCTION` decision additionally requires the governing policy's `status` to be `BOUND` or `ACTIVE` and its posture not to be `FROZEN`; on success the activity moves `PENDING_SANCTION → SANCTIONED` and the deciding official's `X-User-ID` is written to `sanctioning_official_id`."

    Design: Corner/state_machines/second_sanction_decision_on_a_sanctioned_activity_rejected
    """
    bundle = setup_sanctioned_activity(
        sanctioning_official_id=SANCTIONING_OFFICIAL_USER_ID
    )
    activity = bundle["activity"]
    assert activity["status"] == "SANCTIONED"
    assert activity["sanctioning_official_id"] == SANCTIONING_OFFICIAL_USER_ID

    validate_error(
        api.record_sanction_decision(
            activity["id"],
            {"decision": "SANCTION"},
            make_league_official_headers(THIRD_OFFICIAL_USER_ID),
        ),
        ApiErrorId.ERR_INVALID_ACTIVITY_STATE,
        expected_status=409,
    )

    unchanged = read_activity(activity["id"])
    assert unchanged["status"] == "SANCTIONED", (
        f"the already-decided activity stays SANCTIONED, got {unchanged['status']!r}"
    )
    assert unchanged["sanctioning_official_id"] == SANCTIONING_OFFICIAL_USER_ID, (
        "the refused second decision must not overwrite the recorded sanctioning "
        f"official, got {unchanged['sanctioning_official_id']!r}"
    )


def test_cancelled_term_refuses_bind_activate_and_run_off_and_keeps_its_cancel_reason(api):
    """PRD §3.2: "Cancelling a term is available from three states and always requires a `cancel_reason`, which is stored on the policy."
    PRD §3.2: "From `QUOTED` the cancellation is unconditional: `status` becomes `CANCELLED`, the reason is stored, and posture becomes `FROZEN`; nothing else changes, because a quoted term was never counted as in force."
    PRD §3.2: "Binding requires the policy to be in `QUOTED`, the holding league to be `SANCTIONED` (otherwise `ERR_LEAGUE_NOT_SANCTIONED`), the declared `enrolled_participant_count` to be at least the sport's `minimum_participants` (otherwise `ERR_MINIMUM_PARTICIPANTS_NOT_MET`), and no other policy for the same league-and-sport pairing whose `status` is `BOUND`, `ACTIVE` or `RUN_OFF` to hold a term intersecting this one (otherwise `ERR_POLICY_TERM_OVERLAP`)."
    PRD §3.2: "A bound term goes on risk as `BOUND → ACTIVE` once the logical clock has reached or passed its `term_effective_date`; attempting it earlier is refused, and posture is recomputed on success."
    PRD §3.2: "When the clock has reached or passed `term_expiration_date`, the underwriting desk moves the term `ACTIVE → RUN_OFF`, which stops all new exposure — no further enrollment, activity or injury report may be created under the term — while letting the claims already open continue to be adjudicated and paid."
    PRD §2.7: "**The addressed resource's own state** — the row is in a state from which the requested transition is legal."
    PRD §2.7: "The rejection names the entity whose state blocked it: `ERR_INVALID_POLICY_STATE`, `ERR_INVALID_ENROLLMENT_STATE`, `ERR_INVALID_FAMILY_PLAN_STATE`, `ERR_INVALID_ACTIVITY_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_COORDINATION_STATE`, `ERR_INVALID_BILL_STATE` or `ERR_INVALID_PAYMENT_STATE`, each HTTP 409."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."

    Design: Corner/state_machines/cancelled_policy_is_terminal_and_rejects_every_further_action
    """
    _league, _sport_classification, policy = _quoted_baseball_term()
    cancel_reason = "league withdrew the application before the season opened"

    cancelled = validate_success(
        api.cancel_league_policy(
            policy["id"], PROGRAM_ADMIN_HEADERS, {"cancel_reason": cancel_reason}
        ),
        expected_status=200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == cancel_reason
    assert cancelled["coverage_posture"] == "FROZEN"
    assert cancelled["version"] == 2

    for refused in (
        api.bind_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS),
        api.activate_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS),
        api.run_off_league_policy(policy["id"], PROGRAM_ADMIN_HEADERS),
    ):
        validate_error(
            refused, ApiErrorId.ERR_INVALID_POLICY_STATE, expected_status=409
        )

    unchanged = read_policy(policy["id"])
    assert unchanged["status"] == "CANCELLED", (
        "a cancelled term is terminal on the lifecycle axis, got "
        f"{unchanged['status']!r}"
    )
    assert unchanged["cancel_reason"] == cancel_reason
    assert unchanged["coverage_posture"] == "FROZEN"
    assert unchanged["version"] == 2, (
        "none of the three refused calls is a mutation, so version stays 2, got "
        f"{unchanged['version']}"
    )


def test_enrollment_withdrawal_stamps_the_clock_and_recomputes_the_roster_counters(api):
    """PRD §3.3: "A new enrollment starts with `status` `ENROLLED`, `lifetime_cat_benefit_used_cents` 0 and `coverage_status` `COVERED`, and its creation immediately recomputes the athlete's `enrolled_policy_count` and `roster_status`."
    PRD §3.3: "The `withdrawn_on_date` field stays null while the enrollment is live."
    PRD §3.3: "Withdrawing an athlete from a policy roster is the league administrator's own act, carried out with a `withdrawal_note`, and it drives the enrollment `ENROLLED → WITHDRAWN`."
    PRD §3.3: "On success the enrollment's `withdrawn_on_date` is stamped with the logical clock, its `coverage_status` becomes `WITHDRAWN_NO_COVERAGE`, and the athlete's `enrolled_policy_count` and `roster_status` are recomputed — which is how an athlete's last withdrawal flips them to `INACTIVE`."
    PRD §3.3: "`enrolled_policy_count` is the number of this athlete's enrollments whose `status` is `ENROLLED`."
    PRD §3.3: "`roster_status` is `ROSTERED` while at least one enrollment of the athlete is `ENROLLED`, becomes `INACTIVE` once every enrollment of the athlete has been withdrawn, and — importantly for the moment just after an athlete is added — reads `ROSTERED` when the athlete has no enrollment rows at all."
    PRD §3.2: "That declared count is a rating input and is deliberately independent of how many enrollment rows the league later actually creates."

    Design: Corner/state_machines/enrollment_withdrawal_applies_every_declared_side_effect
    """
    bundle = setup_enrolled_athlete()
    league_headers = make_league_admin_headers(bundle["league"]["id"])
    enrollment_id = bundle["enrollment"]["id"]
    participant_id = bundle["participant"]["id"]
    premium_before = read_policy(bundle["policy"]["id"])["annual_premium_cents"]

    live = read_enrollment(enrollment_id)
    assert live["status"] == "ENROLLED"
    assert live["coverage_status"] == "COVERED"
    assert live["withdrawn_on_date"] is None
    rostered = read_participant(participant_id)
    assert rostered["enrolled_policy_count"] == 1
    assert rostered["roster_status"] == "ROSTERED"

    withdrawal_clock = "2026-06-01T00:00:00Z"
    set_clock(withdrawal_clock)

    withdrawn = validate_success(
        api.withdraw_enrollment(
            enrollment_id,
            {"withdrawal_note": "family relocated out of the district mid-season"},
            league_headers,
        ),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN", (
        f"withdrawal drives ENROLLED -> WITHDRAWN, got {withdrawn['status']!r}"
    )
    assert withdrawn["coverage_status"] == "WITHDRAWN_NO_COVERAGE", (
        "the derived coverage status must follow the withdrawal in the same call, got "
        f"{withdrawn['coverage_status']!r}"
    )
    assert canonical_iso(withdrawn["withdrawn_on_date"]) == canonical_iso(
        withdrawal_clock
    ), (
        "withdrawn_on_date is stamped from the logical clock, not from the request "
        f"body, got {withdrawn['withdrawn_on_date']!r}"
    )

    off_roster = read_participant(participant_id)
    assert off_roster["enrolled_policy_count"] == 0, (
        "the athlete's only ENROLLED enrollment is gone, so the count must fall to 0, "
        f"got {off_roster['enrolled_policy_count']}"
    )
    assert off_roster["roster_status"] == "INACTIVE", (
        "every enrollment of the athlete has now been withdrawn, so the roster status "
        f"must read INACTIVE, got {off_roster['roster_status']!r}"
    )
    assert read_policy(bundle["policy"]["id"])["annual_premium_cents"] == premium_before, (
        "the premium is rated off the declared head count, so a withdrawal must not "
        "re-rate the term mid-term"
    )
