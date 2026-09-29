"""Endpoint contracts on the four reads and writes that have no create call.

A claim exists only because an official verified an injury report, so the
filtered claim list is the only way a client ever finds it — and what that list
projects must be the same claim the by-id read projects. The policy's loss
position is published twice, once as a computed read and once inside the policy
itself, and the two must agree. Renewal acceptance is the league's own signature
on a price the underwriting desk already froze, so it must move one field and
re-rate nothing. And the explanation-of-benefits record is the junction of a
claim, a provider charge and a family plan, so it must refuse a charge or a plan
belonging to somebody else before any coordination state moves.
"""
from test_helpers import (
    ApiErrorId,
    BASEBALL_404_ANNUAL_PREMIUM_CENTS,
    RESERVE_BY_SEVERITY_CENTS,
    SANCTIONING_OFFICIAL_USER_ID,
    VERIFYING_OFFICIAL_USER_ID,
    add_family_health_plan,
    add_participant,
    assert_claim,
    canonical_iso,
    create_coordination_record_payload,
    discover_claim,
    enroll_participant,
    file_injury_report,
    make_claims_examiner_headers,
    make_program_admin_headers,
    read_claim,
    read_policy,
    record_provider_bill,
    renewal_quote_payload,
    reprice_bill,
    request_eob,
    sanction_activity,
    schedule_activity,
    set_clock,
    setup_active_policy,
    setup_verified_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_injury_report,
)

MODERATE_RESERVE_CENTS = RESERVE_BY_SEVERITY_CENTS["MODERATE"]


def _fields_agree(field: str, left, right) -> bool:
    """Compare one projected field, canonicalising instants before comparing."""
    if field.endswith("_at") and isinstance(left, str) and isinstance(right, str):
        return canonical_iso(left) == canonical_iso(right)
    return left == right


def test_verified_claim_reads_the_same_by_id_as_through_the_filtered_claim_list(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
    PRD §2.3: "Claims may be filtered by `injury_report_id`, `league_policy_id`, `enrollment_id`, `adjudication_status` and `coordination_status` — and because a claim is born as a side effect of verification rather than by a direct create call, this filtered list is the only channel through which a client discovers a newly created claim."
    PRD §2.5: "All monetary amounts in this system are integers denominated in whole cents."
    PRD §3.5: "Caused by that stamping alone, exactly one **Claim** is created, in `adjudication_status` `PENDING_COORDINATION` and `coordination_status` `NOT_STARTED`."
    PRD §3.5: "It copies `league_policy_id` and `enrollment_id` off the report's enrollment onto itself — the latter so that lifetime catastrophic accumulation is addressable without traversing back through the report — records the originating report as `injury_report_id`, and is struck with a case reserve."
    PRD §3.5: "Note that the new claim is **not** returned in the verification response body; it is discovered through the filtered claim list of §2.3."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §3.8: "A reviewer certifies by supplying a `certification_note`, which moves the claim's `cat_certification_status` from `NONE` to `CERTIFIED`, stamps `cat_certified_at` with the logical clock and `cat_certified_by_user_id` with the reviewer's `X-User-ID`, stores the note as `cat_certification_note`, and recomputes the benefit determination — which is what can lift `cat_layer_benefit_cents` above zero for the first time."
    PRD §3.8: "The claim's `paid_base_cents` (the sum of `ISSUED` `BASE`-layer amounts on the claim), `paid_cat_cents` (the same for the `CATASTROPHIC` layer) and `paid_to_date_cents` (their sum) are recomputed, and once `paid_to_date_cents` has reached or passed `benefit_payable_cents` the claim moves `APPROVED → PAID`, taking it out of the open set."

    Design: Corner/endpoints/claim_read_by_id_agrees_with_the_list_projection
    """
    examiner = make_claims_examiner_headers()
    bundle = setup_verified_claim(
        activity_overrides={
            "activity_type": "PRACTICE",
            "venue_name": "Zephyr Practice Field",
        },
        report_overrides={
            "body_part": "KNEE",
            "injury_description": "knee sprain during fielding drills",
            "severity_tier": "MODERATE",
        },
    )
    enrollment_id = bundle["enrollment"]["id"]
    report_id = bundle["injury_report"]["id"]
    policy_id = bundle["policy"]["id"]

    rows, meta = validate_paginated(
        api.list_claims(examiner, {"enrollment_id": enrollment_id})
    )
    assert meta["total_count"] == 1, (
        "verifying the single injury report opens exactly one claim, so the list "
        f"filtered on the enrollment carries total_count 1, got {meta['total_count']}"
    )
    assert len(rows) == 1, f"expected one claim row, got {len(rows)}"
    listed = rows[0]

    claim = validate_success(api.get_claim(listed["id"], examiner), 200)
    assert_claim(claim)

    assert claim["id"] == listed["id"], "the by-id read addresses the listed claim"
    assert claim["injury_report_id"] == report_id, (
        "the claim records the originating report as injury_report_id, got "
        f"{claim['injury_report_id']!r} against report {report_id!r}"
    )
    assert claim["enrollment_id"] == enrollment_id, (
        "the claim copies enrollment_id off the report's enrollment, got "
        f"{claim['enrollment_id']!r}"
    )
    assert claim["league_policy_id"] == policy_id, (
        "the claim copies league_policy_id off the report's enrollment, got "
        f"{claim['league_policy_id']!r}"
    )

    assert claim["adjudication_status"] == "PENDING_COORDINATION", (
        "a claim minted by verification is born in PENDING_COORDINATION, got "
        f"{claim['adjudication_status']!r}"
    )
    assert claim["coordination_status"] == "NOT_STARTED", (
        f"coordination begins at NOT_STARTED, got {claim['coordination_status']!r}"
    )
    assert claim["coordination_basis"] is None, (
        "coordination_basis reads null while the coordination status is still "
        f"NOT_STARTED, got {claim['coordination_basis']!r}"
    )
    assert claim["cat_certification_status"] == "NONE", (
        "certification has not been issued, so cat_certification_status is NONE, "
        f"got {claim['cat_certification_status']!r}"
    )
    assert claim["reserve_amount_cents"] == MODERATE_RESERVE_CENTS, (
        "the MODERATE standard reserve of 250000 cents is smaller than the "
        "per-injury limit plus the elected catastrophic lifetime maximum, so it is "
        f"the case reserve, got {claim['reserve_amount_cents']}"
    )
    assert claim["allowed_amount_total_cents"] == 0, (
        "no provider bill has been repriced, so the allowed-amount total is 0, got "
        f"{claim['allowed_amount_total_cents']}"
    )
    assert claim["benefit_payable_cents"] == 0, (
        "with nothing allowed, both layers pay nothing and benefit_payable_cents "
        f"is 0, got {claim['benefit_payable_cents']}"
    )
    assert claim["paid_base_cents"] == 0, (
        f"no ISSUED BASE-layer payment exists, got {claim['paid_base_cents']}"
    )
    assert claim["paid_cat_cents"] == 0, (
        f"no ISSUED CATASTROPHIC-layer payment exists, got {claim['paid_cat_cents']}"
    )

    divergent = [
        field
        for field, value in claim.items()
        if field not in listed or not _fields_agree(field, value, listed[field])
    ]
    assert not divergent, (
        "the listed claim row must project the same resource object as the by-id "
        f"read; these fields diverge or are missing from the list row: {divergent}"
    )

    _approved_rows, approved_meta = validate_paginated(
        api.list_claims(examiner, {"adjudication_status": "APPROVED"})
    )
    assert approved_meta["total_count"] == 0, (
        "the only claim is PENDING_COORDINATION, so filtering the list on "
        "adjudication_status APPROVED must return no rows rather than ignoring the "
        f"filter, got total_count {approved_meta['total_count']}"
    )


def _term_carrying_a_quoted_renewal(api):
    """An ACTIVE loss-free 404-athlete term with a renewal quoted for 410."""
    bundle = setup_active_policy()
    policy_id = bundle["policy"]["id"]
    current = read_policy(policy_id)
    quoted = validate_success(
        api.create_renewal_quote(
            policy_id,
            renewal_quote_payload("INCURRED", "2027-03-01", 410, current["version"]),
            make_program_admin_headers(),
        ),
        200,
    )
    return bundle, quoted


def test_renewal_acceptance_moves_the_quote_to_accepted_and_re_rates_nothing(api):
    """PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §3.1: "The hazard class immediately determines the echoed `hazard_load_bps` field: a low-hazard sport carries no load at all, a moderate-hazard sport carries 1150 basis points, a high-hazard sport 2625 basis points, and a contact sport 4075 basis points — so writing a contact sport costs a little over forty percent more per athlete than writing the same rate at low hazard."
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
    PRD §3.9: "`renewal_loss_ratio_bps` is set to `incurred_loss_ratio_bps` when `loss_experience_basis` is `INCURRED`, and to `paid_loss_ratio_bps` when it is `PAID_ONLY`."
    PRD §3.9: "The elected basis is recorded as `renewal_loss_experience_basis`."
    PRD §3.9: "`renewal_experience_tier` is banded from `renewal_loss_ratio_bps` using the same four bands as `experience_tier`, and `renewal_experience_modifier_bps` is read from that tier: `PREFERRED` is −1500 basis points (a credit), `STANDARD` is 0, `ADVERSE` is +2750 and `DECLINE` is +6000."
    PRD §3.9: "The banded gross premium of §3.2 and the six-step annual assembly that follows it are both run again with the participant count set to `renewal_enrolled_participant_count`, keeping the **same** `SportClassification` and the same `cat_layer_elected` election as the expiring term."
    PRD §3.9: "The result is `renewal_base_premium_cents`."
    PRD §3.9: "`renewal_quoted_premium_cents` is the larger of 25,000 cents (the same minimum annual premium as a new term) and `renewal_base_premium_cents` multiplied by the quantity 10000 plus `renewal_experience_modifier_bps`, divided by 10000, rounded half up."
    PRD §3.9: "The league accepts the quoted terms, moving `renewal_quote_status` `QUOTED → ACCEPTED` and incrementing the policy's `version`."
    PRD §3.9: "Acceptance records the league's agreement to the price and nothing more — it does not create the renewal term, does not alter the expiring term's own `annual_premium_cents`, and does not change the expiring term's `status`."

    Design: Corner/endpoints/renewal_acceptance_moves_the_quote_from_quoted_to_accepted
    """
    bundle, quoted = _term_carrying_a_quoted_renewal(api)
    policy_id = bundle["policy"]["id"]

    assert quoted["annual_premium_cents"] == BASEBALL_404_ANNUAL_PREMIUM_CENTS, (
        "the expiring term is rated on 404 declared athletes at the moderate hazard "
        f"load, so its annual premium is 822840 cents, got {quoted['annual_premium_cents']}"
    )
    assert quoted["renewal_quote_status"] == "QUOTED", (
        f"quoting publishes the renewal as QUOTED, got {quoted['renewal_quote_status']!r}"
    )
    assert quoted["renewal_loss_experience_basis"] == "INCURRED", (
        "the elected basis is recorded on the policy, got "
        f"{quoted['renewal_loss_experience_basis']!r}"
    )
    assert quoted["renewal_loss_ratio_bps"] == 0, (
        "a loss-free term carries an incurred loss ratio of 0 basis points, which "
        f"the INCURRED basis freezes onto the quote, got {quoted['renewal_loss_ratio_bps']}"
    )
    assert quoted["renewal_experience_tier"] == "PREFERRED", (
        "0 basis points is below 3500, so the renewal bands as PREFERRED, got "
        f"{quoted['renewal_experience_tier']!r}"
    )
    assert quoted["renewal_experience_modifier_bps"] == -1500, (
        "a PREFERRED renewal tier reads a credit of -1500 basis points, got "
        f"{quoted['renewal_experience_modifier_bps']}"
    )
    # 410 athletes re-rated from scratch: band lines 154706 + 620114 + 17533 give a
    # gross of 792353, the 850 bps catastrophic charge adds 67350 for a subtotal of
    # 859703, whose 300 bps volume credit is 25791, leaving 833912.
    assert quoted["renewal_base_premium_cents"] == 833912, (
        "the renewal is a full re-rate on 410 athletes with per-band rounding, the "
        "catastrophic layer charge and the subtotal-keyed volume credit all applied "
        f"again, got {quoted['renewal_base_premium_cents']}"
    )
    # 833912 * (10000 - 1500) / 10000 = 708825.2, rounded half up to 708825.
    assert quoted["renewal_quoted_premium_cents"] == 708825, (
        "the PREFERRED credit of 1500 basis points applies to the re-rated base and "
        f"the 25000-cent floor does not bite, got {quoted['renewal_quoted_premium_cents']}"
    )

    accepted = validate_success(
        api.accept_renewal_quote(policy_id, bundle["league_headers"]), 200
    )
    assert accepted["renewal_quote_status"] == "ACCEPTED", (
        "the league's acceptance moves renewal_quote_status QUOTED to ACCEPTED, got "
        f"{accepted['renewal_quote_status']!r}"
    )
    assert accepted["version"] == quoted["version"] + 1, (
        "acceptance is a mutation of the policy row, so its version increments by "
        f"exactly one from {quoted['version']}, got {accepted['version']}"
    )

    assert accepted["status"] == "ACTIVE", (
        "acceptance does not change the expiring term's lifecycle status, got "
        f"{accepted['status']!r}"
    )
    assert accepted["annual_premium_cents"] == BASEBALL_404_ANNUAL_PREMIUM_CENTS, (
        "acceptance does not alter the expiring term's own annual premium, got "
        f"{accepted['annual_premium_cents']}"
    )
    assert accepted["renewal_base_premium_cents"] == 833912, (
        "acceptance re-rates nothing, so the frozen renewal base premium stands, got "
        f"{accepted['renewal_base_premium_cents']}"
    )
    assert accepted["renewal_quoted_premium_cents"] == 708825, (
        "acceptance re-rates nothing, so the quoted renewal premium stands, got "
        f"{accepted['renewal_quoted_premium_cents']}"
    )
    assert accepted["renewal_experience_modifier_bps"] == -1500, (
        "the experience modifier the price was struck from is untouched, got "
        f"{accepted['renewal_experience_modifier_bps']}"
    )

    persisted = read_policy(policy_id)
    assert persisted["renewal_quote_status"] == "ACCEPTED", (
        "the acceptance is persisted on the policy row, got "
        f"{persisted['renewal_quote_status']!r}"
    )
    assert persisted["version"] == accepted["version"], (
        "reading the policy is not a mutation, so its version stays where the "
        f"acceptance left it, got {persisted['version']}"
    )


def test_second_renewal_acceptance_on_an_already_accepted_quote_is_refused(api):
    """PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §3.9: "The league accepts the quoted terms, moving `renewal_quote_status` `QUOTED → ACCEPTED` and incrementing the policy's `version`."
    PRD §3.9: "Acceptance requires `renewal_quote_status` to be exactly `QUOTED`; accepting when it reads `NONE` or `ACCEPTED` is refused with `ERR_INVALID_POLICY_STATE`."

    Design: Corner/endpoints/renewal_acceptance_moves_the_quote_from_quoted_to_accepted
    """
    bundle, quoted = _term_carrying_a_quoted_renewal(api)
    policy_id = bundle["policy"]["id"]

    accepted = validate_success(
        api.accept_renewal_quote(policy_id, bundle["league_headers"]), 200
    )
    assert accepted["renewal_quote_status"] == "ACCEPTED", (
        "the first acceptance moves the outstanding quote to ACCEPTED, got "
        f"{accepted['renewal_quote_status']!r}"
    )
    assert accepted["version"] == quoted["version"] + 1, (
        f"the first acceptance increments the policy version once, got {accepted['version']}"
    )

    validate_error(
        api.accept_renewal_quote(policy_id, bundle["league_headers"]),
        ApiErrorId.ERR_INVALID_POLICY_STATE.value,
        409,
    )

    unchanged = read_policy(policy_id)
    assert unchanged["renewal_quote_status"] == "ACCEPTED", (
        "the refused second acceptance leaves the quote exactly where the first one "
        f"left it, got {unchanged['renewal_quote_status']!r}"
    )
    assert unchanged["version"] == accepted["version"], (
        "a refused acceptance mutates nothing, so the policy version does not "
        f"advance again from {accepted['version']}, got {unchanged['version']}"
    )


LOSS_POSITION_FIELDS = (
    "paid_loss_cents",
    "reserve_cents",
    "incurred_loss_cents",
    "incurred_loss_ratio_bps",
    "paid_loss_ratio_bps",
    "open_claim_count",
    "experience_tier",
    "coverage_posture",
)


def _term_with_one_open_moderate_claim():
    """An ACTIVE 404-athlete term carrying exactly one open MODERATE claim."""
    return setup_verified_claim(
        report_overrides={
            "body_part": "ANKLE_FOOT",
            "injury_description": "ankle sprain sliding into third",
            "severity_tier": "MODERATE",
        },
        official_attestation="third-base official witnessed the slide",
    )


def test_loss_experience_read_reports_the_single_open_claims_reserve_as_incurred_loss(api):
    """PRD §2.8: "The posture is selected by walking six tests strictly from the top and stopping at the first that matches:"
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_cents` has reached or passed its `aggregate_limit_cents`, the posture is `FROZEN`."
    PRD §2.8: "Otherwise, if the policy's `open_claim_count` is three or more, the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Otherwise, if the policy's `incurred_loss_ratio_bps` has reached or passed 6500 basis points — that is, incurred losses of sixty-five percent or more of the term's earned premium — the posture is `CLAIMS_REVIEW`."
    PRD §2.8: "Failing all of them, the posture is `OPEN`."
    PRD §3.2: "`annual_premium_cents` is the subtotal less the volume credit, but never less than the program's minimum annual premium of 25,000 cents — two hundred and fifty dollars."
    PRD §3.2: "`annual_premium_cents` is also the earned-premium denominator for every loss ratio in §3.9."
    PRD §3.2: "A newly quoted policy takes `status` `QUOTED` and `renewal_quote_status` `NONE`, and immediately mirrors five figures from its sport classification onto itself — `deductible_cents`, `per_injury_limit_cents`, `cat_attachment_point_cents`, `aggregate_limit_cents` and `cat_lifetime_max_cents` — so that a claim can be determined without traversing back to master data."
    PRD §3.5: "The reserve struck at claim creation is `reserve_amount_cents`, and it is the smaller of two numbers."
    PRD §3.5: "The first is the program's standard reserve for the report's `severity_tier`: 50,000 cents for a `MINOR` injury, 250,000 cents for a `MODERATE` one, 1,500,000 cents for a `SEVERE` one, and 7,500,000 cents — seventy-five thousand dollars — for a `CATASTROPHIC` one."
    PRD §3.5: "The second is the policy's total exposure cap for one injury, which is its `per_injury_limit_cents` plus, only when `cat_layer_elected` is true, its `cat_lifetime_max_cents`; where the catastrophic layer was not purchased, the exposure cap is the per-injury limit alone."
    PRD §3.9: "There is no batch job and no nightly close: the figures are always current as of the last write, and they are exposed as a computed read that returns `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `open_claim_count`, `experience_tier` and the current `coverage_posture` together."
    PRD §3.9: "The central definition is the **open set**: the claims of the policy whose `adjudication_status` is `PENDING_COORDINATION`, `UNDER_ADJUDICATION` or `APPROVED`."
    PRD §3.9: "`paid_loss_cents` is the sum of `amount_cents` over payments whose `status` is `ISSUED`, taken across **every** claim of the policy, in the open set or not."
    PRD §3.9: "`reserve_cents` is the sum of `reserve_amount_cents` over the claims **in the open set only**."
    PRD §3.9: "`incurred_loss_cents` is `paid_loss_cents` plus `reserve_cents`."
    PRD §3.9: "`open_claim_count` is the number of claims in the open set."
    PRD §3.9: "`incurred_loss_ratio_bps` is `incurred_loss_cents` multiplied by 10000, divided by `annual_premium_cents`, rounded half up."
    PRD §3.9: "`paid_loss_ratio_bps` is the same computation over `paid_loss_cents`."
    PRD §3.9: "`experience_tier` is banded from `incurred_loss_ratio_bps`: below 3500 basis points is `PREFERRED`, from 3500 through 6499 is `STANDARD`, from 6500 through 9999 is `ADVERSE`, and 10000 or above is `DECLINE`."

    Design: Corner/endpoints/loss_experience_read_matches_the_policy_derived_fields
    """
    bundle = _term_with_one_open_moderate_claim()
    policy_id = bundle["policy"]["id"]

    policy = read_policy(policy_id)
    assert policy["annual_premium_cents"] == BASEBALL_404_ANNUAL_PREMIUM_CENTS, (
        "the earned-premium denominator for both loss ratios is this term's annual "
        f"premium of 822840 cents, got {policy['annual_premium_cents']}"
    )
    assert policy["aggregate_limit_cents"] == 25000000, (
        "the term aggregate ceiling mirrored from the sport classification is "
        f"25000000 cents, got {policy['aggregate_limit_cents']}"
    )

    position = validate_success(
        api.get_loss_experience(policy_id, bundle["league_headers"]), 200
    )

    assert position["paid_loss_cents"] == 0, (
        "no benefit payment has been issued under the term, so paid loss is 0, got "
        f"{position['paid_loss_cents']}"
    )
    assert position["reserve_cents"] == MODERATE_RESERVE_CENTS, (
        "the single open claim's MODERATE case reserve of 250000 cents is the whole "
        f"of the term's reserve, got {position['reserve_cents']}"
    )
    assert position["incurred_loss_cents"] == MODERATE_RESERVE_CENTS, (
        "incurred loss is paid loss plus reserve, so 0 + 250000, got "
        f"{position['incurred_loss_cents']}"
    )
    assert (
        position["incurred_loss_cents"]
        == position["paid_loss_cents"] + position["reserve_cents"]
    ), "incurred_loss_cents must always equal paid_loss_cents plus reserve_cents"
    assert position["open_claim_count"] == 1, (
        "the one claim minted by verification sits in PENDING_COORDINATION and is "
        f"therefore the only member of the open set, got {position['open_claim_count']}"
    )
    # 250000 * 10000 / 822840 = 3038.2577..., rounded half up to 3038.
    assert position["incurred_loss_ratio_bps"] == 3038, (
        "the incurred loss ratio is 250000 * 10000 / 822840 rounded half up, got "
        f"{position['incurred_loss_ratio_bps']}"
    )
    assert position["paid_loss_ratio_bps"] == 0, (
        "the same computation over a paid loss of 0 gives 0 basis points, got "
        f"{position['paid_loss_ratio_bps']}"
    )
    assert position["experience_tier"] == "PREFERRED", (
        "3038 basis points is below 3500, so the term bands as PREFERRED, got "
        f"{position['experience_tier']!r}"
    )
    assert position["coverage_posture"] == "OPEN", (
        "incurred loss of 250000 is far below the 25000000 aggregate limit, the open "
        "claim count of 1 is below three and 3038 basis points is below 6500, so "
        f"every posture test fails through to OPEN, got {position['coverage_posture']!r}"
    )


def test_loss_experience_read_projects_the_same_aggregates_the_policy_row_carries(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §2.4: "A change to a *derived* field counts as a mutation for these purposes."
    PRD §2.8: "Alongside its lifecycle `status`, every policy carries a derived operating posture, `coverage_posture`, taking one of three values: `OPEN`, `CLAIMS_REVIEW` or `FROZEN`."
    PRD §3.5: "Caused by the claim's creation alone, the claim joins its policy's open set, so the policy's `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `open_claim_count` and `experience_tier` are all recomputed."
    PRD §3.8: "And in the same request the policy's `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, both loss ratios, `open_claim_count`, `experience_tier` and `coverage_posture` are recomputed."
    PRD §3.9: "Everything the program knows about how a policy term is performing is recomputed at the end of every write that changes one of its claims, changes a benefit payment beneath one of those claims, or changes the policy's own `annual_premium_cents`."
    PRD §3.9: "There is no batch job and no nightly close: the figures are always current as of the last write, and they are exposed as a computed read that returns `paid_loss_cents`, `reserve_cents`, `incurred_loss_cents`, `incurred_loss_ratio_bps`, `paid_loss_ratio_bps`, `open_claim_count`, `experience_tier` and the current `coverage_posture` together."

    Design: Corner/endpoints/loss_experience_read_matches_the_policy_derived_fields
    """
    bundle = _term_with_one_open_moderate_claim()
    policy_id = bundle["policy"]["id"]

    before = read_policy(policy_id)
    version_after_the_verification_cascade = before["version"]

    position = validate_success(
        api.get_loss_experience(policy_id, bundle["league_headers"]), 200
    )
    after = validate_success(
        api.get_league_policy(policy_id, make_program_admin_headers()), 200
    )

    for field in LOSS_POSITION_FIELDS:
        assert field in position, (
            f"the computed loss-experience read must return {field}, got keys "
            f"{sorted(position)}"
        )
        assert field in after, (
            f"the policy row itself carries the recomputed {field}, got keys "
            f"{sorted(after)}"
        )
        assert position[field] == after[field], (
            f"the loss-experience read is a projection of the policy's stored "
            f"derived state, not a second computation: {field} reads "
            f"{position[field]!r} there and {after[field]!r} on the policy"
        )

    assert after["version"] == version_after_the_verification_cascade, (
        "neither read mutates the policy, so its version stays at the value the "
        f"verification cascade left, expected {version_after_the_verification_cascade}, "
        f"got {after['version']}"
    )
    assert canonical_iso(after["updated_at"]) == canonical_iso(before["updated_at"]), (
        "a read refreshes nothing, so the policy's updated_at is unchanged by the "
        f"two reads, got {after['updated_at']!r} against {before['updated_at']!r}"
    )


def _cedarcrest_two_claims_each_awaiting_a_family_carrier():
    """Two athletes hurt in the same ball game, each with their own claim, their
    own repriced emergency-room charge and their own family plan.

    Athlete A's file has already gone out to the family carrier, so claim A sits
    at EOB_REQUESTED and is the only claim ready to receive an explanation of
    benefits. Both charges are billed 400000 against a 360000 fee schedule, which
    an in-network provider reprices to an allowed 360000.
    """
    bundle = setup_active_policy(
        league_overrides={
            "name": "Cedarcrest Baseball",
            "league_code": "CCB-135",
            "state_code": "MN",
            "contact_email": "admin@ccb.example",
        }
    )
    league_id = bundle["league"]["id"]
    policy_id = bundle["policy"]["id"]

    athlete_a = add_participant(
        league_id,
        first_name="Tomas",
        last_name="Nyberg",
        date_of_birth="2015-04-30",
        guardian_email="g37@ccb.example",
    )
    athlete_b = add_participant(
        league_id,
        first_name="Ursula",
        last_name="Mkhize",
        date_of_birth="2015-05-31",
        guardian_email="g38@ccb.example",
    )
    enrollment_a = enroll_participant(athlete_a["id"], policy_id, league_id)
    enrollment_b = enroll_participant(athlete_b["id"], policy_id, league_id)

    plan_a = add_family_health_plan(
        athlete_a["id"],
        carrier_name="Northstar Health",
        policy_number="NS-88120",
        plan_type="PPO",
        individual_deductible_cents=150000,
        coinsurance_bps=2000,
        effective_date="2026-01-01",
    )
    plan_b = add_family_health_plan(
        athlete_b["id"],
        carrier_name="Northstar Health",
        policy_number="NS-88121",
        plan_type="PPO",
        individual_deductible_cents=150000,
        coinsurance_bps=2000,
        effective_date="2026-01-01",
    )

    game = schedule_activity(policy_id, league_id, venue_name="Cedarcrest Field 2")
    sanction_activity(game["id"], SANCTIONING_OFFICIAL_USER_ID)

    set_clock("2026-07-12T00:00:00Z")

    report_a = file_injury_report(
        enrollment_a["id"],
        game["id"],
        league_id,
        body_part="TORSO",
        injury_description="rib contusion from a foul ball",
        severity_tier="MODERATE",
    )
    verify_injury_report(
        report_a["id"],
        VERIFYING_OFFICIAL_USER_ID,
        "home-plate official witnessed the foul ball",
    )
    report_b = file_injury_report(
        enrollment_b["id"],
        game["id"],
        league_id,
        injury_datetime="2026-07-11T19:20:00Z",
        body_part="HAND_WRIST",
        injury_description="jammed wrist diving for a grounder",
        severity_tier="MODERATE",
    )
    verify_injury_report(
        report_b["id"],
        VERIFYING_OFFICIAL_USER_ID,
        "field official witnessed the dive",
    )

    claim_a = discover_claim(report_a["id"])
    claim_b = discover_claim(report_b["id"])

    charge = {
        "provider_npi": "1166778899",
        "provider_name": "Cedarcrest Regional ER",
        "network_status": "IN_NETWORK",
        "service_category": "EMERGENCY_ROOM",
        "service_date": "2026-07-11",
        "billed_charge_cents": 400000,
        "fee_schedule_amount_cents": 360000,
    }
    bill_a = reprice_bill(record_provider_bill(claim_a["id"], **charge)["id"])
    bill_b = reprice_bill(record_provider_bill(claim_b["id"], **charge)["id"])

    request_eob(claim_a["id"], "requesting the family carrier explanation of benefits")

    return {
        "policy": bundle["policy"],
        "plan_a": plan_a,
        "plan_b": plan_b,
        "bill_a": bill_a,
        "bill_b": bill_b,
        "claim_a": read_claim(claim_a["id"]),
        "claim_b": read_claim(claim_b["id"]),
    }


def test_coordination_record_naming_another_claims_charge_or_another_athletes_plan_is_refused(api):
    """PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §2.3: "Coordination records may be filtered by `claim_id`, `provider_bill_id`, `family_health_plan_id`, `superseded_by_record_id` and `status`."
    PRD §2.6: "Only once every referenced row exists does the server check that those rows are *mutually in scope* — that they actually belong together in the same aggregate."
    PRD §2.6: "A scope failure is `ERR_SCOPE_MISMATCH` (HTTP 422) and is described where each affected workflow appears in §3."
    PRD §3.6: "A `ClaimsExaminer` requesting the explanation of benefits, optionally with a `note`, drives `NOT_STARTED → EOB_REQUESTED` and stamps `eob_requested_at` with the logical clock."
    PRD §3.6: "A `ClaimsExaminer` files a **CoordinationRecord** naming the `claim_id` whose coordination file it belongs to, the `provider_bill_id` of the specific charge the family plan adjudicated, and the `family_health_plan_id` of the plan that issued it."
    PRD §3.6: "The three references must be mutually in scope: the named provider bill must belong to the named claim, and the named family health plan must belong to the claim's own athlete — the plan's `participant_id` must equal the participant behind the claim's enrollment."
    PRD §3.6: "Either mismatch is refused with `ERR_SCOPE_MISMATCH`."
    PRD §3.6: "Coordination begins at `NOT_STARTED` and settles at one of three values — `EOB_RECEIVED`, `EOB_WAIVED` or `NO_OTHER_COVERAGE_CONFIRMED` — and both moves out of `NOT_STARTED` require the claim's `adjudication_status` to be `PENDING_COORDINATION` or `UNDER_ADJUDICATION`."
    PRD §3.6: "A newly filed record takes `status` `ACTIVE` with `superseded_by_record_id` null, and increments the parent claim's `version` by one."
    PRD §3.6: "Only `ACTIVE` records contribute to any total."
    PRD §3.6: "Filing the first record on a claim also drives the coordination axis `EOB_REQUESTED → EOB_RECEIVED`, after which `coordination_basis` reads `EXCESS_OF_OTHER`, and the claim's `other_insurance_paid_cents` and its whole benefit determination are recomputed."
    PRD §3.6: "At the claim level, `other_insurance_paid_cents` is the sum of `other_plan_paid_cents` across this claim's `ACTIVE` coordination records whose `provider_bill_id` names one of the claim's bills in `REPRICED` or `ADJUDICATED` status."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."

    Design: Corner/endpoints/coordination_record_must_link_a_bill_and_a_plan_of_its_own_claim
    """
    world = _cedarcrest_two_claims_each_awaiting_a_family_carrier()
    examiner = make_claims_examiner_headers()
    claim_a = world["claim_a"]

    assert claim_a["coordination_status"] == "EOB_REQUESTED", (
        "the explanation of benefits has gone out on athlete A's file, so claim A "
        f"awaits the carrier in EOB_REQUESTED, got {claim_a['coordination_status']}"
    )
    assert claim_a["coordination_basis"] is None, (
        "a claim still waiting on the carrier has no coordination basis yet, got "
        f"{claim_a['coordination_basis']!r}"
    )
    version_awaiting_the_carrier = claim_a["version"]

    # The charge belongs to athlete B's claim, not to claim A.
    validate_error(
        api.create_coordination_record(
            create_coordination_record_payload(
                claim_a["id"],
                world["bill_b"]["id"],
                world["plan_a"]["id"],
                version_awaiting_the_carrier,
                eob_received_date="2026-07-18",
                other_plan_allowed_cents=300000,
                other_plan_paid_cents=210000,
                patient_responsibility_cents=90000,
            ),
            examiner,
        ),
        ApiErrorId.ERR_SCOPE_MISMATCH.value,
        422,
    )

    # The plan belongs to athlete B, not to the athlete behind claim A.
    validate_error(
        api.create_coordination_record(
            create_coordination_record_payload(
                claim_a["id"],
                world["bill_a"]["id"],
                world["plan_b"]["id"],
                version_awaiting_the_carrier,
                eob_received_date="2026-07-18",
                other_plan_allowed_cents=300000,
                other_plan_paid_cents=210000,
                patient_responsibility_cents=90000,
            ),
            examiner,
        ),
        ApiErrorId.ERR_SCOPE_MISMATCH.value,
        422,
    )

    after = read_claim(claim_a["id"])
    assert after["coordination_status"] == "EOB_REQUESTED", (
        "neither mismatched reference may move the coordination axis, so claim A is "
        f"still waiting on the carrier, got {after['coordination_status']}"
    )
    assert after["coordination_basis"] is None, (
        "coordination basis stays null while the status is EOB_REQUESTED, got "
        f"{after['coordination_basis']!r}"
    )
    assert after["other_insurance_paid_cents"] == 0, (
        "no explanation of benefits was accepted, so no other-plan payment is on "
        f"the claim, got {after['other_insurance_paid_cents']}"
    )
    assert after["version"] == version_awaiting_the_carrier, (
        "only a record that is actually filed increments the parent claim's "
        f"version, expected {version_awaiting_the_carrier}, got {after['version']}"
    )

    for label, claim_id in (("A", world["claim_a"]["id"]), ("B", world["claim_b"]["id"])):
        _rows, meta = validate_paginated(
            api.list_coordination_records(examiner, {"claim_id": claim_id})
        )
        assert meta["total_count"] == 0, (
            f"the refused filings wrote nothing, so claim {label} carries no "
            f"coordination record, got total_count {meta['total_count']}"
        )

    assert read_claim(world["claim_b"]["id"])["coordination_status"] == "NOT_STARTED", (
        "athlete B's claim was only ever named as the owner of the borrowed charge "
        "and must be left untouched at NOT_STARTED, got "
        f"{read_claim(world['claim_b']['id'])['coordination_status']}"
    )


def test_coordination_record_on_its_own_charge_and_plan_receives_the_eob_and_redetermines_the_benefit(api):
    """PRD §2.4: "`version` — an integer that starts at 1 and increments by one on every mutation of the row."
    PRD §2.5: "All monetary amounts in this system are integers denominated in whole cents."
    PRD §3.6: "A `ClaimsExaminer` files a **CoordinationRecord** naming the `claim_id` whose coordination file it belongs to, the `provider_bill_id` of the specific charge the family plan adjudicated, and the `family_health_plan_id` of the plan that issued it."
    PRD §3.6: "The record carries the `eob_received_date` on which the program received it, plus the three figures off the explanation of benefits itself: `other_plan_allowed_cents` (zero or more), `other_plan_paid_cents` (zero or more and never greater than the allowed amount) and `patient_responsibility_cents` (zero or more)."
    PRD §3.6: "The three references must be mutually in scope: the named provider bill must belong to the named claim, and the named family health plan must belong to the claim's own athlete — the plan's `participant_id` must equal the participant behind the claim's enrollment."
    PRD §3.6: "A newly filed record takes `status` `ACTIVE` with `superseded_by_record_id` null, and increments the parent claim's `version` by one."
    PRD §3.6: "Filing the first record on a claim also drives the coordination axis `EOB_REQUESTED → EOB_RECEIVED`, after which `coordination_basis` reads `EXCESS_OF_OTHER`, and the claim's `other_insurance_paid_cents` and its whole benefit determination are recomputed."
    PRD §3.6: "At the claim level, `other_insurance_paid_cents` is the sum of `other_plan_paid_cents` across this claim's `ACTIVE` coordination records whose `provider_bill_id` names one of the claim's bills in `REPRICED` or `ADJUDICATED` status."
    PRD §3.6: "It is `FULL_EXCESS` when the coordination status is `NO_OTHER_COVERAGE_CONFIRMED`, `EXCESS_OF_OTHER` when the coordination status is `EOB_RECEIVED` or `EOB_WAIVED`, and null while the coordination status is still `NOT_STARTED` or `EOB_REQUESTED`."
    PRD §3.7: "For an in-network provider it is the smaller of the billed charge and the fee-schedule amount."
    PRD §3.7: "`allowed_amount_cents` is the smaller of the negotiated amount and the severity-adjusted scheduled cap, and never below zero."
    PRD §3.7: "`allowed_amount_total_cents` is the sum of `allowed_amount_cents` across this claim's bills whose `status` is `REPRICED` or `ADJUDICATED`."
    PRD §3.7: "The **other-insurance offset** is the claim's `other_insurance_paid_cents` when `coordination_basis` is `EXCESS_OF_OTHER`, and zero in every other case."
    PRD §3.7: "The **deductible basis** is the policy's `deductible_cents` at face value when `coordination_basis` is `EXCESS_OF_OTHER`; otherwise it is that deductible multiplied by 20000 basis points and divided by ten thousand — that is, exactly doubled — with the result rounded half up to whole cents."
    PRD §3.7: "The **net after other insurance** is the allowed-amount total less the offset, floored at zero."
    PRD §3.7: "`deductible_applied_cents` is the smaller of that net figure and the deductible basis — so a claim smaller than the deductible absorbs only what there is to absorb."
    PRD §3.7: "`benefit_before_limit_cents` is the net figure less the applied deductible, floored at zero."
    PRD §3.7: "`base_layer_benefit_cents` is the smaller of `benefit_before_limit_cents` and the policy's `per_injury_limit_cents`."
    PRD §3.7: "If either condition fails, `cat_layer_benefit_cents` is exactly zero."
    PRD §3.7: "`benefit_payable_cents` is `base_layer_benefit_cents` plus `cat_layer_benefit_cents`."
    PRD §4: "Endpoints that create a new resource return HTTP 201; every other successful call returns HTTP 200."

    Design: Corner/endpoints/coordination_record_must_link_a_bill_and_a_plan_of_its_own_claim
    """
    world = _cedarcrest_two_claims_each_awaiting_a_family_carrier()
    examiner = make_claims_examiner_headers()
    claim_a = world["claim_a"]
    policy = read_policy(world["policy"]["id"])

    assert world["bill_a"]["allowed_amount_cents"] == 360000, (
        "the in-network charge is negotiated down to the 360000 fee schedule, which "
        "is under the 500000 emergency-room cap left untouched by a MODERATE "
        f"injury, got {world['bill_a']['allowed_amount_cents']}"
    )
    assert policy["deductible_cents"] == 25000, (
        f"the term carries a 25000-cent deductible, got {policy['deductible_cents']}"
    )
    assert policy["per_injury_limit_cents"] == 2500000, (
        "the term carries a 2500000-cent per-injury limit, got "
        f"{policy['per_injury_limit_cents']}"
    )
    version_awaiting_the_carrier = claim_a["version"]

    record = validate_success(
        api.create_coordination_record(
            create_coordination_record_payload(
                claim_a["id"],
                world["bill_a"]["id"],
                world["plan_a"]["id"],
                version_awaiting_the_carrier,
                eob_received_date="2026-07-18",
                other_plan_allowed_cents=300000,
                other_plan_paid_cents=210000,
                patient_responsibility_cents=90000,
            ),
            examiner,
        ),
        201,
    )

    assert record["status"] == "ACTIVE", (
        f"a newly filed explanation of benefits is ACTIVE, got {record['status']}"
    )
    assert record["superseded_by_record_id"] is None, (
        "nothing has corrected this explanation of benefits, so "
        f"superseded_by_record_id is null, got {record['superseded_by_record_id']!r}"
    )
    assert record["other_plan_paid_cents"] == 210000, (
        "the record carries the figure off the carrier's explanation of benefits "
        f"unchanged, got {record['other_plan_paid_cents']}"
    )
    assert record["other_plan_allowed_cents"] == 300000, (
        f"the carrier allowed 300000, got {record['other_plan_allowed_cents']}"
    )
    assert record["patient_responsibility_cents"] == 90000, (
        "the carrier left 90000 with the family, got "
        f"{record['patient_responsibility_cents']}"
    )
    assert record["claim_id"] == claim_a["id"]
    assert record["provider_bill_id"] == world["bill_a"]["id"]
    assert record["family_health_plan_id"] == world["plan_a"]["id"]

    after = read_claim(claim_a["id"])
    assert after["coordination_status"] == "EOB_RECEIVED", (
        "the first record filed on the claim drives the coordination axis to "
        f"EOB_RECEIVED, got {after['coordination_status']}"
    )
    assert after["coordination_basis"] == "EXCESS_OF_OTHER", (
        "a claim whose coordination status is EOB_RECEIVED reads EXCESS_OF_OTHER, "
        f"got {after['coordination_basis']!r}"
    )
    assert after["other_insurance_paid_cents"] == 210000, (
        "the single ACTIVE record against a REPRICED charge of this claim sums to "
        f"210000, got {after['other_insurance_paid_cents']}"
    )
    assert after["allowed_amount_total_cents"] == 360000, (
        "the one repriced charge contributes its whole allowed amount, got "
        f"{after['allowed_amount_total_cents']}"
    )
    assert after["deductible_applied_cents"] == 25000, (
        "an excess-of-other claim absorbs the deductible at face value, and the "
        "150000 net left after the other plan paid is larger than it, got "
        f"{after['deductible_applied_cents']}"
    )
    assert after["benefit_before_limit_cents"] == 125000, (
        "360000 allowed less the 210000 the family plan paid less the 25000 "
        f"deductible leaves 125000, got {after['benefit_before_limit_cents']}"
    )
    assert after["base_layer_benefit_cents"] == 125000, (
        "125000 is far under the 2500000 per-injury limit, so the base layer takes "
        f"all of it, got {after['base_layer_benefit_cents']}"
    )
    assert after["cat_layer_benefit_cents"] == 0, (
        "no catastrophic certification has been issued on this MODERATE injury, so "
        f"the catastrophic layer is exactly zero, got {after['cat_layer_benefit_cents']}"
    )
    assert after["benefit_payable_cents"] == 125000, (
        "125000 from the base layer plus nothing from the catastrophic layer, got "
        f"{after['benefit_payable_cents']}"
    )
    assert after["version"] == version_awaiting_the_carrier + 1, (
        "filing the record increments the parent claim's version by exactly one, "
        f"expected {version_awaiting_the_carrier + 1}, got {after['version']}"
    )

    rows, meta = validate_paginated(
        api.list_coordination_records(examiner, {"claim_id": claim_a["id"]})
    )
    assert meta["total_count"] == 1, (
        f"claim A carries exactly one explanation of benefits, got {meta['total_count']}"
    )
    assert rows[0]["id"] == record["id"]

    _rows_b, meta_b = validate_paginated(
        api.list_coordination_records(examiner, {"claim_id": world["claim_b"]["id"]})
    )
    assert meta_b["total_count"] == 0, (
        "athlete B's claim was never coordinated, got total_count "
        f"{meta_b['total_count']}"
    )
