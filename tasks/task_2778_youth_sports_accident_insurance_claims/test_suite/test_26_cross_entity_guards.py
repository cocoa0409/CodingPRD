"""Guards that read an entity the request never addresses.

Two of the program's forward-moving writes are gated by rows that sit outside the
resource being addressed. A verification decision on an injury report is gated by
the sanctioning state of the linked activity, one hop away, even though filing the
same report against that same unsanctioned activity was perfectly legal. An
adjudication is gated two hops away: it reads the governing policy's operating
posture, which is itself derived from the holding league's sanctioning standing,
so a governing body's discipline of the league stops a claims examiner's cheque.
"""
from test_helpers import (
    CLAIMS_EXAMINER_USER_ID,
    ApiErrorId,
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    assert_claim,
    assert_injury_report,
    assert_league_policy,
    assert_loss_position_invariants,
    claims_for_report,
    confirm_no_other_coverage,
    file_injury_report,
    make_claims_examiner_headers,
    make_league_official_headers,
    make_program_admin_headers,
    read_activity,
    read_claim,
    read_injury_report,
    read_policy,
    read_provider_bill,
    set_clock,
    setup_repriced_bill,
    setup_sanctioned_activity,
    validate_error,
    validate_success,
)

NORTHGATE_LEAGUE = {
    "name": "Northgate Youth Baseball",
    "league_code": "NYB-040",
    "state_code": "IL",
    "governing_body_code": "USYSA",
    "contact_email": "admin@nyb.example",
}
WESTBROOK_LEAGUE = {
    "name": "Westbrook Baseball Federation",
    "league_code": "WBF-041",
    "state_code": "PA",
    "governing_body_code": "USYSA",
    "contact_email": "admin@wbf.example",
}
FULL_EXCESS_TERM = {
    "coverage_basis_election": "FULL_EXCESS_PERMITTED",
    "cat_layer_elected": True,
}
SHOULDER_STRAIN_REPORT = {
    "body_part": "SHOULDER_ARM",
    "injury_description": "shoulder strain pitching the fourth inning",
    "severity_tier": "MODERATE",
}
ATTESTATION = "assistant coach witnessed the injury"


def _report_on_unsanctioned_game(api):
    """A pending-sanction game with one MODERATE report filed against it."""
    bundle = setup_sanctioned_activity(
        sanction=False,
        league_overrides=dict(NORTHGATE_LEAGUE),
        policy_overrides=dict(FULL_EXCESS_TERM),
        activity_overrides={"venue_name": "Northgate Field 3"},
    )
    assert bundle["activity"]["status"] == "PENDING_SANCTION", (
        "a newly scheduled activity waits in PENDING_SANCTION, got "
        f"{bundle['activity']['status']}"
    )
    set_clock("2026-07-12T00:00:00Z")
    bundle["injury_report"] = file_injury_report(
        bundle["enrollment"]["id"],
        bundle["activity"]["id"],
        bundle["league"]["id"],
        **SHOULDER_STRAIN_REPORT,
    )
    return bundle


def test_verifying_a_report_whose_activity_is_still_pending_sanction_is_refused_and_opens_no_claim(api):
    """PRD §3.5: "The activity's own status must not be `REJECTED`, or the filing is refused with `ERR_ACTIVITY_NOT_SANCTIONED` — note that filing against an activity still merely `PENDING_SANCTION` is allowed, because in practice the paperwork often arrives before the official's sanction does; the sanction is required later, at verification."
    PRD §3.5: "A newly filed report enters `PENDING_VERIFICATION` with `correction_round_count` 0 and with `correction_note`, `verifying_official_id`, `verified_at`, `official_attestation` and `rejection_reason` all null."
    PRD §3.5: "The linked activity must actually be in `SANCTIONED` (not merely un-rejected), or the decision is refused with `ERR_ACTIVITY_NOT_SANCTIONED`."
    PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "Note that the new claim is **not** returned in the verification response body; it is discovered through the filtered claim list of §2.3."

    Design: Difficulty/cross_entity_state_dependency/injury_report_verification_guarded_by_sanctioned_activity_status
    """
    bundle = _report_on_unsanctioned_game(api)
    report = bundle["injury_report"]
    assert_injury_report(report)
    assert report["status"] == "PENDING_VERIFICATION", (
        "filing against a merely PENDING_SANCTION activity is legal and leaves the "
        f"report awaiting a decision, got {report['status']}"
    )

    refusal = api.record_verification_decision(
        report["id"],
        {"decision": "VERIFY", "official_attestation": ATTESTATION},
        make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
    )
    validate_error(refusal, ApiErrorId.ERR_ACTIVITY_NOT_SANCTIONED.value, 422)

    # The refused decision must leave the report exactly as it was: nothing was
    # stamped, so nothing downstream of the stamping happened either.
    unchanged = read_injury_report(report["id"])
    assert unchanged["status"] == "PENDING_VERIFICATION", (
        "a refused verification leaves the report in PENDING_VERIFICATION, got "
        f"{unchanged['status']}"
    )
    assert unchanged["verified_at"] is None, (
        f"verified_at must still be null, got {unchanged['verified_at']!r}"
    )
    assert unchanged["verifying_official_id"] is None, (
        "verifying_official_id must still be null, got "
        f"{unchanged['verifying_official_id']!r}"
    )
    assert unchanged["official_attestation"] is None, (
        "official_attestation must still be null, got "
        f"{unchanged['official_attestation']!r}"
    )
    assert claims_for_report(report["id"]) == [], (
        "no claim may exist for a report whose verification was refused"
    )

    # The activity itself is untouched by the refused decision.
    activity = read_activity(bundle["activity"]["id"])
    assert activity["status"] == "PENDING_SANCTION", (
        f"the activity is still awaiting its official, got {activity['status']}"
    )


def test_verifying_the_same_report_once_the_official_sanctions_the_activity_opens_one_claim(api):
    """PRD §3.5: "The linked activity must actually be in `SANCTIONED` (not merely un-rejected), or the decision is refused with `ERR_ACTIVITY_NOT_SANCTIONED`."
    PRD §3.4: "A `SANCTION` decision additionally requires the governing policy's `status` to be `BOUND` or `ACTIVE` and its posture not to be `FROZEN`; on success the activity moves `PENDING_SANCTION → SANCTIONED` and the deciding official's `X-User-ID` is written to `sanctioning_official_id`."
    PRD §3.5: "Both branches require the report to be in `PENDING_VERIFICATION` and both are subject to the program's central segregation rule: the deciding official's `X-User-ID` must differ from the `sanctioning_official_id` recorded on the linked activity."
    PRD §3.5: "The report moves `PENDING_VERIFICATION → VERIFIED`; `verified_at` is stamped with the logical clock, `verifying_official_id` with the deciding official's `X-User-ID`, and `official_attestation` with the supplied attestation text."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "It copies `league_policy_id` and `enrollment_id` off the report's enrollment onto itself — the latter so that lifetime catastrophic accumulation is addressable without traversing back through the report — records the originating report as `injury_report_id`, and is struck with a case reserve."
    PRD §3.5: "Note that the new claim is **not** returned in the verification response body; it is discovered through the filtered claim list of §2.3."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."

    Design: Difficulty/cross_entity_state_dependency/injury_report_verification_guarded_by_sanctioned_activity_status
    """
    bundle = _report_on_unsanctioned_game(api)
    report = bundle["injury_report"]

    # Nothing about the report itself changes; only the activity one hop away moves.
    sanctioned = validate_success(
        api.record_sanction_decision(
            bundle["activity"]["id"],
            {"decision": "SANCTION"},
            make_league_official_headers(SANCTIONING_OFFICIAL_USER_ID),
        ),
        200,
    )
    assert sanctioned["status"] == "SANCTIONED", (
        f"the sanction decision moves the activity to SANCTIONED, got {sanctioned['status']}"
    )
    assert sanctioned["sanctioning_official_id"] == SANCTIONING_OFFICIAL_USER_ID, (
        "the deciding official's id is recorded as sanctioning_official_id, got "
        f"{sanctioned['sanctioning_official_id']!r}"
    )

    verified = validate_success(
        api.record_verification_decision(
            report["id"],
            {"decision": "VERIFY", "official_attestation": ATTESTATION},
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        ),
        200,
    )
    assert_injury_report(verified)
    assert verified["status"] == "VERIFIED", (
        f"the identical decision now verifies the report, got {verified['status']}"
    )
    assert verified["verifying_official_id"] == VERIFYING_OFFICIAL_USER_ID, (
        "the deciding official's id is recorded as verifying_official_id, got "
        f"{verified['verifying_official_id']!r}"
    )
    assert verified["official_attestation"] == ATTESTATION, (
        f"the supplied attestation text is stored, got {verified['official_attestation']!r}"
    )

    claims = claims_for_report(report["id"])
    assert len(claims) == 1, (
        f"verification creates exactly one claim, found {len(claims)}"
    )
    claim = claims[0]
    assert_claim(claim)
    assert claim["adjudication_status"] == "PENDING_COORDINATION", (
        f"the new claim opens in PENDING_COORDINATION, got {claim['adjudication_status']}"
    )
    assert claim["coordination_status"] == "NOT_STARTED", (
        f"the new claim opens in NOT_STARTED, got {claim['coordination_status']}"
    )
    assert claim["injury_report_id"] == report["id"], (
        f"the originating report is recorded, got {claim['injury_report_id']!r}"
    )
    assert claim["enrollment_id"] == bundle["enrollment"]["id"], (
        f"the report's enrollment is copied onto the claim, got {claim['enrollment_id']!r}"
    )
    assert claim["league_policy_id"] == bundle["policy"]["id"], (
        f"the report's policy is copied onto the claim, got {claim['league_policy_id']!r}"
    )
    # MODERATE reserves 250000 cents, which is far below this term's exposure cap
    # of 2500000 + 100000000 cents, so the standard reserve is the smaller number.
    assert claim["reserve_amount_cents"] == 250000, (
        "a MODERATE injury is reserved at 250000 cents, got "
        f"{claim['reserve_amount_cents']}"
    )


def test_claim_opened_once_the_activity_is_sanctioned_recomputes_the_policy_loss_position(api):
    """PRD §3.5: "The linked activity must actually be in `SANCTIONED` (not merely un-rejected), or the decision is refused with `ERR_ACTIVITY_NOT_SANCTIONED`."
    PRD §3.5: "Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed."
    PRD §3.5: "Caused by those recomputed figures alone, the policy's `coverage_posture` is re-derived and may move to `CLAIMS_REVIEW` or `FROZEN` — a third open claim is exactly what tips a policy into claims review."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.2: "`annual_premium_cents` is also the earned-premium denominator for every loss ratio in §3.9."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/injury_report_verification_guarded_by_sanctioned_activity_status
    """
    bundle = _report_on_unsanctioned_game(api)
    report = bundle["injury_report"]

    quoted = read_policy(bundle["policy"]["id"])
    assert quoted["open_claim_count"] == 0, (
        "no claim exists while the verification is still blocked by the activity, "
        f"got open_claim_count {quoted['open_claim_count']}"
    )

    validate_success(
        api.record_sanction_decision(
            bundle["activity"]["id"],
            {"decision": "SANCTION"},
            make_league_official_headers(SANCTIONING_OFFICIAL_USER_ID),
        ),
        200,
    )
    validate_success(
        api.record_verification_decision(
            report["id"],
            {"decision": "VERIFY", "official_attestation": ATTESTATION},
            make_league_official_headers(VERIFYING_OFFICIAL_USER_ID),
        ),
        200,
    )

    policy = read_policy(bundle["policy"]["id"])
    assert_league_policy(policy)
    assert_loss_position_invariants(policy)
    assert policy["open_claim_count"] == 1, (
        f"the newly opened claim joins the open set, got {policy['open_claim_count']}"
    )
    assert policy["reserve_cents"] == 250000, (
        f"the open set carries the claim's 250000-cent reserve, got {policy['reserve_cents']}"
    )
    assert policy["incurred_loss_cents"] == 250000, (
        "nothing has been paid, so incurred loss is the reserve alone, got "
        f"{policy['incurred_loss_cents']}"
    )
    # The term's earned premium is 822840 cents, and 250000 * 10000 / 822840 is
    # 3038.2577..., which rounds half up to 3038 basis points.
    assert policy["incurred_loss_ratio_bps"] == 3038, (
        "the incurred loss ratio is 3038 basis points against an earned premium of "
        f"{policy['annual_premium_cents']} cents, got {policy['incurred_loss_ratio_bps']}"
    )
    assert policy["experience_tier"] == "PREFERRED", (
        f"3038 basis points bands as PREFERRED, got {policy['experience_tier']}"
    )
    assert policy["coverage_posture"] == "OPEN", (
        "one open claim at 3038 basis points fails every freeze and claims-review "
        f"test, got {policy['coverage_posture']}"
    )


SUSPENSION = {
    "sanctioning_status": "SUSPENDED",
    "reason": "governing body suspended the league pending a background-check audit",
}
REINSTATEMENT = {
    "sanctioning_status": "SANCTIONED",
    "reason": "audit cleared, league reinstated",
}
EXAMINER_NOTE = {"examiner_note": "full-excess determination ready"}


def _adjudication_ready_full_excess_claim(api):
    """A SEVERE claim on a full-excess footing with one repriced emergency-room bill."""
    bundle = setup_repriced_bill(
        league_overrides=dict(WESTBROOK_LEAGUE),
        policy_overrides=dict(FULL_EXCESS_TERM),
        participant_overrides={
            "first_name": "Omar",
            "last_name": "Haddad",
            "date_of_birth": "2014-01-09",
            "guardian_email": "g16@wbf.example",
        },
        activity_overrides={
            "venue_name": "Westbrook Memorial Park",
            "ends_at": "2026-07-11T20:30:00Z",
        },
        report_overrides={
            "injury_datetime": "2026-07-11T19:30:00Z",
            "body_part": "KNEE",
            "injury_description": "home-plate collision, suspected ligament rupture",
            "severity_tier": "SEVERE",
        },
        bill_overrides={
            "provider_npi": "1558820174",
            "provider_name": "Westbrook General Emergency",
        },
    )
    confirm_no_other_coverage(bundle["claim"]["id"])
    bundle["claim"] = read_claim(bundle["claim"]["id"])
    return bundle


def test_adjudication_is_refused_while_the_suspended_league_freezes_the_governing_policy(api):
    """PRD §3.7: "A successful reprice moves the bill `SUBMITTED → REPRICED`, stamps `repriced_at` with the logical clock and `repriced_by_user_id` with the examiner's `X-User-ID`, recomputes the parent claim's totals and its benefit determination, and — if the parent claim is still in `PENDING_COORDINATION` — drives the claim's adjudication axis `PENDING_COORDINATION → UNDER_ADJUDICATION`."
    PRD §3.6: "The mirror-image move is the examiner confirming that no other coverage exists, supplied with an `attestation_note`, which drives `NOT_STARTED → NO_OTHER_COVERAGE_CONFIRMED`."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Posture is recomputed at the end of every write that changes the policy itself, changes its league's sanctioning standing, or changes any claim or benefit payment beneath it."
    PRD §2.8: "Otherwise, if the holding league's `sanctioning_status` is `SUSPENDED`, the posture is `FROZEN`."
    PRD §2.8: "Posture is what actually gates whether new exposure and new claim activity may be written; `status` records where the term is in its life, posture records whether the program is presently willing to let anything happen under it."
    PRD §3.1: "Suspension is the hard signal, and it drives the three-link cascade of §2.9: every policy of the league recomputes its posture and lands on `FROZEN` because its holding league is suspended; because those policies just became frozen, each of their activities still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` set to `POLICY_FROZEN`; and because those activities just became rejected, every injury report pointing at one of them whose own status is `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION` moves to `REJECTED` with `rejection_reason` set to `ACTIVITY_NOT_SANCTIONED`."
    PRD §3.8: "Four requirements are common to both outcomes: the claim's `adjudication_status` must be `UNDER_ADJUDICATION` (otherwise `ERR_INVALID_CLAIM_STATE`); its `coordination_status` must have reached a settled value — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — which is the **single declared join** between the two axes, and a claim still `NOT_STARTED`, or still `EOB_REQUESTED` with the forty-five-day waiver window not yet elapsed, is refused with `ERR_COORDINATION_INCOMPLETE`; the governing policy's `status` must be `ACTIVE` or `RUN_OFF`; and the policy's posture must not be `FROZEN`."
    PRD §2.8: "So `ERR_POLICY_FROZEN` can arise from enrolling an athlete, scheduling an activity, taking a sanction decision, filing an injury report, resubmitting one, taking a verification decision, recording a provider bill, repricing one, filing a coordination record, requesting an explanation of benefits, confirming no other coverage, adjudicating a claim, issuing a benefit payment or quoting a renewal."
    PRD §3.8: "Approval also moves every bill of the claim still in `REPRICED` to `ADJUDICATED`."

    Design: Difficulty/cross_entity_state_dependency/claim_adjudication_guarded_two_hops_through_policy_to_league_sanctioning
    """
    bundle = _adjudication_ready_full_excess_claim(api)
    claim = bundle["claim"]
    assert claim["adjudication_status"] == "UNDER_ADJUDICATION", (
        "the first reprice advanced the claim's adjudication axis, got "
        f"{claim['adjudication_status']}"
    )
    assert claim["coordination_status"] == "NO_OTHER_COVERAGE_CONFIRMED", (
        "ruling out other coverage settles the coordination axis, got "
        f"{claim['coordination_status']}"
    )

    # A SEVERE claim reserves 1500000 cents against 822840 cents of earned premium,
    # which is 18230 basis points of incurred loss - already past claims review, but
    # claims review never blocks the settlement of a claim already in flight.
    before = read_policy(bundle["policy"]["id"])
    assert before["coverage_posture"] == "CLAIMS_REVIEW", (
        f"the deteriorated loss position reads CLAIMS_REVIEW, got {before['coverage_posture']}"
    )

    suspended = validate_success(
        api.set_league_sanctioning_status(
            bundle["league"]["id"], dict(SUSPENSION), make_program_admin_headers()
        ),
        200,
    )
    assert suspended["sanctioning_status"] == "SUSPENDED", (
        f"the governing body's decision is recorded, got {suspended['sanctioning_status']}"
    )

    frozen = read_policy(bundle["policy"]["id"])
    assert frozen["coverage_posture"] == "FROZEN", (
        "a suspended holding league freezes the policy's posture, got "
        f"{frozen['coverage_posture']}"
    )
    assert frozen["status"] == "ACTIVE", (
        f"the term's own lifecycle status is untouched, got {frozen['status']}"
    )

    refusal = api.adjudicate_claim(
        claim["id"], dict(EXAMINER_NOTE), make_claims_examiner_headers()
    )
    validate_error(refusal, ApiErrorId.ERR_POLICY_FROZEN.value, 409)

    still_open = read_claim(claim["id"])
    assert still_open["adjudication_status"] == "UNDER_ADJUDICATION", (
        "the refused adjudication leaves the claim under adjudication, got "
        f"{still_open['adjudication_status']}"
    )
    assert still_open["adjudicated_at"] is None, (
        f"adjudicated_at must still be null, got {still_open['adjudicated_at']!r}"
    )
    assert still_open["adjudicated_by_user_id"] is None, (
        "adjudicated_by_user_id must still be null, got "
        f"{still_open['adjudicated_by_user_id']!r}"
    )
    bill = read_provider_bill(bundle["provider_bill"]["id"])
    assert bill["status"] == "REPRICED", (
        f"no approval happened, so the charge stays repriced, got {bill['status']}"
    )

    # The suspension cascade only reaches activities still awaiting sanction and
    # reports still awaiting a decision; this pair is past both points.
    assert read_activity(bundle["activity"]["id"])["status"] == "SANCTIONED", (
        "an already sanctioned activity is not swept up by the freeze"
    )
    assert read_injury_report(bundle["injury_report"]["id"])["status"] == "VERIFIED", (
        "an already verified report is not swept up by the freeze"
    )


def test_reinstating_the_league_thaws_the_policy_and_the_same_adjudication_approves(api):
    """PRD §3.1: "Suspension is the hard signal, and it drives the three-link cascade of §2.9: every policy of the league recomputes its posture and lands on `FROZEN` because its holding league is suspended; because those policies just became frozen, each of their activities still in `PENDING_SANCTION` moves to `REJECTED` with `rejection_reason` set to `POLICY_FROZEN`; and because those activities just became rejected, every injury report pointing at one of them whose own status is `PENDING_VERIFICATION` or `RETURNED_FOR_CORRECTION` moves to `REJECTED` with `rejection_reason` set to `ACTIVITY_NOT_SANCTIONED`."
    PRD §3.1: "Restoring a suspended league to `SANCTIONED` recomputes posture on all its policies, and a policy leaves `FROZEN` unless its own `incurred_loss_cents` has reached its `aggregate_limit_cents` — but as §2.9 says, the activities and reports already rejected are never revived."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "Take the category's cap from `service_category_caps`, multiply by the severity factor for the originating report's `severity_tier`, divide by ten thousand and round half up to whole cents."
    PRD §3.7: "The severity factors are 10000 basis points for a `MINOR` injury and 10000 for a `MODERATE` one — both leaving the cap untouched — 11500 basis points for a `SEVERE` injury, lifting the cap by fifteen percent, and 12500 basis points for a `CATASTROPHIC` one, lifting it by a quarter."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "The **catastrophic-eligible amount** is `benefit_before_limit_cents` less the policy's `cat_attachment_point_cents`, floored at zero."
    PRD §3.7: "`cat_layer_benefit_cents` is the smaller of the catastrophic-eligible amount and that remaining lifetime benefit — but **only** when the policy's `cat_layer_elected` is true *and* the claim's `cat_certification_status` is `CERTIFIED`."
    PRD §3.7: "If either condition fails, `cat_layer_benefit_cents` is exactly zero."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "Four requirements are common to both outcomes: the claim's `adjudication_status` must be `UNDER_ADJUDICATION` (otherwise `ERR_INVALID_CLAIM_STATE`); its `coordination_status` must have reached a settled value — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — which is the **single declared join** between the two axes, and a claim still `NOT_STARTED`, or still `EOB_REQUESTED` with the forty-five-day waiver window not yet elapsed, is refused with `ERR_COORDINATION_INCOMPLETE`; the governing policy's `status` must be `ACTIVE` or `RUN_OFF`; and the policy's posture must not be `FROZEN`."
    PRD §3.8: "It reaches `UNDER_ADJUDICATION → APPROVED` when the athlete's enrollment `status` is `ENROLLED` and `benefit_payable_cents` is at least one cent, and when the determination does not reach into the catastrophic layer without certification: where the policy's `cat_layer_elected` is true and `benefit_before_limit_cents` exceeds the policy's `cat_attachment_point_cents`, the claim's `cat_certification_status` must be `CERTIFIED`, and otherwise the adjudication is refused with `ERR_CAT_CERTIFICATION_REQUIRED` rather than quietly paying the base layer alone."
    PRD §3.8: "Approval stamps `adjudicated_at` and `adjudicated_by_user_id` and **freezes** five determination figures — `deductible_applied_cents`, `benefit_before_limit_cents`, `base_layer_benefit_cents`, `cat_layer_benefit_cents` and `benefit_payable_cents` — which are never recomputed again on that claim."
    PRD §2.1: "The server does, however, record it wherever an audit trail or a segregation rule needs it: as `sanctioning_official_id` on a sanctioned activity, as `verifying_official_id` on an injury report, as `verified_by_user_id` on a family health plan, as `repriced_by_user_id` on a provider bill, as `adjudicated_by_user_id` and `cat_certified_by_user_id` on a claim, and as `issued_by_user_id` on a benefit payment."
    PRD §3.8: "Approval also moves every bill of the claim still in `REPRICED` to `ADJUDICATED`."

    Design: Difficulty/cross_entity_state_dependency/claim_adjudication_guarded_two_hops_through_policy_to_league_sanctioning
    """
    bundle = _adjudication_ready_full_excess_claim(api)
    claim = bundle["claim"]

    # The in-network charge of 620000 against a fee schedule of 385000 negotiates to
    # 385000, well under the SEVERE-adjusted emergency-room cap of 575000; the
    # full-excess footing doubles the 25000-cent deductible, leaving 335000 payable.
    assert claim["coordination_basis"] == "FULL_EXCESS", (
        f"ruling out other coverage puts the claim on FULL_EXCESS, got {claim['coordination_basis']!r}"
    )
    assert claim["allowed_amount_total_cents"] == 385000, (
        f"the single repriced charge allows 385000 cents, got {claim['allowed_amount_total_cents']}"
    )
    assert claim["deductible_applied_cents"] == 50000, (
        "the full-excess deductible basis is twice 25000 cents, got "
        f"{claim['deductible_applied_cents']}"
    )
    assert claim["benefit_payable_cents"] == 335000, (
        f"385000 less the doubled deductible is 335000 cents, got {claim['benefit_payable_cents']}"
    )

    validate_success(
        api.set_league_sanctioning_status(
            bundle["league"]["id"], dict(SUSPENSION), make_program_admin_headers()
        ),
        200,
    )
    assert read_policy(bundle["policy"]["id"])["coverage_posture"] == "FROZEN", (
        "the suspension must freeze the term before the reinstatement is tested"
    )

    reinstated = validate_success(
        api.set_league_sanctioning_status(
            bundle["league"]["id"], dict(REINSTATEMENT), make_program_admin_headers()
        ),
        200,
    )
    assert reinstated["sanctioning_status"] == "SANCTIONED", (
        f"the league is restored to good standing, got {reinstated['sanctioning_status']}"
    )

    thawed = read_policy(bundle["policy"]["id"])
    assert thawed["incurred_loss_cents"] == 1500000, (
        "the SEVERE case reserve is the whole incurred loss, got "
        f"{thawed['incurred_loss_cents']}"
    )
    assert thawed["incurred_loss_cents"] < thawed["aggregate_limit_cents"], (
        "the term is nowhere near its aggregate limit, so the freeze must lift"
    )
    assert thawed["coverage_posture"] == "CLAIMS_REVIEW", (
        "the thawed term falls back to its own loss-driven posture, got "
        f"{thawed['coverage_posture']}"
    )

    approved = validate_success(
        api.adjudicate_claim(
            claim["id"], dict(EXAMINER_NOTE), make_claims_examiner_headers()
        ),
        200,
    )
    assert_claim(approved)
    assert approved["adjudication_status"] == "APPROVED", (
        f"the identical adjudication now approves, got {approved['adjudication_status']}"
    )
    assert approved["adjudicated_at"] is not None, "adjudicated_at must be stamped"
    assert approved["adjudicated_by_user_id"] == CLAIMS_EXAMINER_USER_ID, (
        "the adjudicating examiner's id is recorded, got "
        f"{approved['adjudicated_by_user_id']!r}"
    )
    assert approved["deductible_applied_cents"] == 50000, (
        f"the frozen deductible is 50000 cents, got {approved['deductible_applied_cents']}"
    )
    assert approved["benefit_before_limit_cents"] == 335000, (
        f"the frozen benefit before limits is 335000 cents, got {approved['benefit_before_limit_cents']}"
    )
    assert approved["base_layer_benefit_cents"] == 335000, (
        "the whole benefit sits inside the 2500000-cent per-injury limit, got "
        f"{approved['base_layer_benefit_cents']}"
    )
    assert approved["cat_layer_benefit_cents"] == 0, (
        "nothing reaches the catastrophic layer and no certification exists, got "
        f"{approved['cat_layer_benefit_cents']}"
    )
    assert approved["benefit_payable_cents"] == 335000, (
        f"the frozen payable benefit is 335000 cents, got {approved['benefit_payable_cents']}"
    )

    bill = read_provider_bill(bundle["provider_bill"]["id"])
    assert bill["status"] == "ADJUDICATED", (
        f"approval makes the repriced charge payable, got {bill['status']}"
    )
