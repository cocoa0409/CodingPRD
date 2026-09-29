"""The four-hop signing cascade, the two clock sweeps and the two state axes."""

from test_helpers import (
    ACTIVATION_CLOCK_UTC,
    POST_TERM_CLOCK_UTC,
    assert_commitment,
    assert_subscription,
    canonical_instant,
    cast_vote,
    create_draft_trial,
    create_member,
    create_negotiation,
    create_product,
    create_vendor,
    decide,
    diagnose_and_resolve,
    endorse_trial,
    open_renewal_decision,
    open_vote,
    pledge,
    read_commitment,
    read_incident,
    read_member,
    read_subscription,
    read_trial,
    reopen,
    report_off_campus_incidents,
    set_clock,
    setup_agreed_negotiation,
    setup_configured_access,
    setup_multi_member_subscription,
    setup_signed_subscription,
    sign,
    sign_payload,
    submit_round,
    validate_error,
    validate_success,
    vendor_accepts,
    withdraw,
)


def test_moving_the_logical_clock_backwards_is_rejected(api, admin):
    """The clock accepts an equal instant but never an earlier one.

    PRD: "A `ConsortiumAdmin` moves it by supplying `to_iso8601`, an ISO 8601
    instant that must be greater than or equal to the clock's current value; an
    earlier instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` (422)."

    Design: Corner/validations/moving_the_logical_clock_backwards_is_rejected
    """
    advanced = set_clock("2026-09-01T00:00:00Z")
    assert canonical_instant(advanced["current_utc"]) == canonical_instant(
        "2026-09-01T00:00:00Z")

    response = api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, admin)
    validate_error(response, "ERR_CLOCK_NOT_MONOTONIC", 422)

    still_refused = api.set_clock({"to_iso8601": "2026-08-20T00:00:00Z"}, admin)
    validate_error(still_refused, "ERR_CLOCK_NOT_MONOTONIC", 422)

    unchanged = validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, admin))
    assert canonical_instant(unchanged["current_utc"]) == canonical_instant(
        "2026-09-01T00:00:00Z"), "the refusals left the clock exactly where it stood"
    assert unchanged["activated_subscription_ids"] == []
    assert unchanged["expired_subscription_ids"] == []


def test_clock_advance_past_the_term_end_expires_the_active_subscription(api, admin):
    """Both contract-axis sweeps are clock-driven, and expiry writes the access axis.

    PRD: "Any subscription in `PENDING_ACTIVATION` whose `activation_start_date`
    is less than or equal to the new clock date advances `PENDING_ACTIVATION →
    ACTIVE`."

    PRD: "Any subscription in `ACTIVE` whose `term_end` is strictly earlier than
    the new clock date advances `ACTIVE → EXPIRED`, and expiry writes the access
    axis according to the term locked at signing: `access_status` becomes
    `SUSPENDED` when `perpetual_access_mode` is `NONE`, and `POST_CANCELLATION`
    otherwise."

    Design: Corner/state_machines/clock_advance_past_the_term_end_expires_the_active_subscription
    """
    scenario = setup_signed_subscription()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["subscription"]["perpetual_access_mode"] == "FULL_ARCHIVE"

    activation = set_clock(ACTIVATION_CLOCK_UTC)
    assert subscription_id in activation["activated_subscription_ids"]
    assert read_subscription(subscription_id)["contract_status"] == "ACTIVE"

    response = api.set_clock({"to_iso8601": POST_TERM_CLOCK_UTC}, admin)
    data = validate_success(response)

    assert subscription_id in data["expired_subscription_ids"]
    assert data["activated_subscription_ids"] == [], "nothing was awaiting activation"

    stored = read_subscription(subscription_id)
    assert_subscription(stored)
    assert stored["contract_status"] == "EXPIRED", "2028-01-02 is past term_end 2027-12-31"
    assert stored["access_status"] == "POST_CANCELLATION", (
        "FULL_ARCHIVE parks the access axis in POST_CANCELLATION rather than SUSPENDED"
    )
    assert stored["term_end"] == "2027-12-31", "expiry does not move the term"
    assert stored["negotiated_price_cents"] == 9000000


def test_signing_response_already_reflects_every_cascade_hop(api, admin):
    """A read issued straight after the 201 already shows all four hops applied.

    PRD: "Every commitment row on the signed negotiation's product whose `status`
    is `PLEDGED` has its `subscription_id` set to the new subscription's `id`, has
    `tier_price_cents` stamped by the settled variant of the member tier price,
    has `applied_discount_pct` and `participant_count_at_pricing` refreshed, and
    advances `PLEDGED → CONFIRMED`."

    PRD: "**Hop three** is caused by each of those confirmations: the confirmed
    commitment's `tier_price_cents` is added to `annual_committed_cents` on the
    `Member` identified by that commitment's `member_id`."

    Design: Corner/consistency_model/signing_response_already_reflects_every_cascade_hop
    """
    scenario = setup_agreed_negotiation()
    member_id = scenario["member"]["id"]
    commitment = pledge(scenario["product"]["id"], member_id)
    assert commitment["projected_price_cents"] == 4500000
    assert commitment["tier_price_cents"] is None
    assert read_member(member_id)["annual_committed_cents"] == 0

    signed = validate_success(
        api.sign_negotiation(scenario["negotiation"]["id"], sign_payload(), admin),
        expected_status=201)
    assert signed["contract_status"] == "PENDING_ACTIVATION", (
        "the 201 body itself already carries the new subscription's state"
    )
    assert signed["negotiated_price_cents"] == 9000000

    response = api.get_commitment(commitment["id"], admin)
    data = validate_success(response)

    assert_commitment(data)
    assert data["status"] == "CONFIRMED", "no second write was needed to see the cascade"
    assert data["tier_price_cents"] == 4500000
    assert data["subscription_id"] == signed["id"]
    assert read_member(member_id)["annual_committed_cents"] == 4500000
    assert read_subscription(signed["id"])["contract_status"] == "PENDING_ACTIVATION"


def _three_members_settling_below_their_projections():
    """Alpha, Bravo and Charlie pledge in order, then one signature settles all three."""
    return setup_multi_member_subscription([
        {"name": "Alpha College", "fte_count": 4000},
        {"name": "Bravo University", "fte_count": 4600},
        {"name": "Charlie Institute", "fte_count": 4900},
    ])


def test_the_settled_price_diverges_from_the_projection_it_was_quoted(api):
    """Early pledgers are quoted 4,500,000 and settle at 4,050,000.

    PRD: "Early pledgers therefore see a small participant count, land in a lower
    band of `tier_bands`, and are quoted a higher price than they will eventually
    pay."

    PRD: "Because the settled variant counts `CONFIRMED` rows after the entire
    pass has run, all the newly confirmed members count each other, and the price
    each of them settles at is generally lower than the projection they were
    quoted at pledge time."

    Design: Difficulty/dual_variant_calc/commitment_projected_price_diverges_from_settled_price_at_signing
    """
    scenario = _three_members_settling_below_their_projections()
    alpha, bravo, charlie = scenario["commitments"]

    assert alpha["projected_price_cents"] == 4500000, "quoted alone, in the no-discount band"
    assert bravo["projected_price_cents"] == 4500000, "two participants is still that band"
    assert charlie["projected_price_cents"] == 4050000, "the third pledge earns ten percent"

    for row in (alpha, bravo, charlie):
        settled = read_commitment(row["id"])
        assert settled["status"] == "CONFIRMED"
        assert settled["tier_price_cents"] == 4050000, (
            "the settled pass counts all three confirmed rows for everybody"
        )
        assert settled["subscription_id"] == scenario["subscription"]["id"]

    assert read_commitment(alpha["id"])["projected_price_cents"] == 4500000, (
        "the projection is kept alongside the settled price, not overwritten"
    )
    assert read_subscription(scenario["subscription"]["id"])["negotiated_price_cents"] == 9000000


def test_the_settled_pass_refreshes_the_discount_and_participant_observability(api):
    """Both audit fields follow the variant that priced the row last.

    PRD: "Whichever variant produced the latest price on a commitment row also
    refreshes two observability fields: `applied_discount_pct` records the
    `discount_pct` of the band that variant selected, and
    `participant_count_at_pricing` records the participant count that variant
    counted."

    PRD: "The **settled** variant runs when a signature confirms the pledges, and
    again on renewal execution, restructure execution and restructure reversal;
    its result is stamped as `tier_price_cents`."

    Design: Difficulty/dual_variant_calc/commitment_projected_price_diverges_from_settled_price_at_signing
    """
    scenario = _three_members_settling_below_their_projections()
    alpha_commitment = scenario["commitments"][0]
    assert float(alpha_commitment["applied_discount_pct"]) == 0, (
        "at pledge time Alpha was alone in the schedule"
    )
    assert alpha_commitment["participant_count_at_pricing"] == 1

    stored = read_commitment(alpha_commitment["id"])
    assert float(stored["applied_discount_pct"]) == 10, (
        "the settled pass selected the three-participant band"
    )
    assert stored["participant_count_at_pricing"] == 3

    for member in scenario["members"]:
        ledger = read_member(member["id"])
        assert ledger["annual_committed_cents"] == 4050000, (
            "hop three adds the settled price, never the projection"
        )
        assert ledger["standing"] == "IN_GOOD_STANDING"


def _cascade_that_overshoots_the_ceiling():
    """A signature that confirms one pledge, overcommits the member, and withdraws a trial.

    Xavier pledges third and is quoted 4,050,000, comfortably inside its
    4,100,000 ceiling.  Its two co-pledgers then withdraw, so the settled pass
    counts Xavier alone and lands on 4,500,000 — past the ceiling, which flips
    standing and reaches back out into Xavier's DRAFT trial on the other package.
    """
    vendor = create_vendor()
    first = create_product(vendor["id"], name="Atlas Humanities Collection")
    second = create_product(vendor["id"], name="Atlas Sciences Collection")
    xavier = create_member(name="Xavier College", budget_ceiling_cents=4100000)
    yankee = create_member(name="Yankee University")
    zulu = create_member(name="Zulu Institute")

    endorsed = endorse_trial(create_draft_trial(first["id"], xavier["id"])["id"],
                             xavier["id"])
    draft = create_draft_trial(second["id"], xavier["id"], "2026-10-01", "2026-10-31")

    negotiation = create_negotiation(first["id"], endorsed["id"])
    submit_round(negotiation["id"])
    vendor_accepts(negotiation["id"], vendor["id"], 9000000)

    yankee_commitment = pledge(first["id"], yankee["id"])
    zulu_commitment = pledge(first["id"], zulu["id"])
    xavier_commitment = pledge(first["id"], xavier["id"])
    assert xavier_commitment["projected_price_cents"] == 4050000
    withdraw(yankee_commitment["id"], yankee["id"])
    withdraw(zulu_commitment["id"], zulu["id"])

    return {
        "vendor": vendor,
        "first": first,
        "second": second,
        "xavier": xavier,
        "yankee": yankee,
        "zulu": zulu,
        "endorsed_trial": endorsed,
        "draft_trial": draft,
        "commitment": xavier_commitment,
        "yankee_commitment": yankee_commitment,
        "zulu_commitment": zulu_commitment,
        "negotiation_id": negotiation["id"],
    }


def test_the_signing_cascade_overcommits_the_member_and_withdraws_its_draft_trial(api):
    """Four hops fire from one signature, the last one reaching into a sibling trial.

    PRD: "Any member whose `annual_committed_cents` now exceeds its
    `budget_ceiling_cents` has `standing` flipped to `OVER_COMMITTED`, and that
    flip in turn transitions every trial belonging to that member whose `status`
    is `DRAFT` to `WITHDRAWN`."

    PRD: "It opens on both state axes at their initial values — `contract_status`
    of `PENDING_ACTIVATION` and `access_status` of `UNCONFIGURED`."

    Design: Difficulty/transitive_cascade/signing_cascade_confirms_pledge_then_overcommits_member_then_withdraws_draft_trial
    """
    scenario = _cascade_that_overshoots_the_ceiling()

    subscription = sign(scenario["negotiation_id"])

    assert_subscription(subscription)
    assert subscription["contract_status"] == "PENDING_ACTIVATION"
    assert subscription["access_status"] == "UNCONFIGURED"
    assert subscription["negotiated_price_cents"] == 9000000
    assert subscription["entitled_title_count"] == 400
    assert subscription["notice_deadline_date"] == "2027-10-02"

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["status"] == "CONFIRMED"
    assert commitment["tier_price_cents"] == 4500000, (
        "the settled pass counted Xavier alone, so the discount band is lost"
    )
    assert commitment["projected_price_cents"] == 4050000
    assert commitment["participant_count_at_pricing"] == 1

    member = read_member(scenario["xavier"]["id"])
    assert member["annual_committed_cents"] == 4500000
    assert member["standing"] == "OVER_COMMITTED", "4,500,000 exceeds the 4,100,000 ceiling"

    assert read_trial(scenario["draft_trial"]["id"])["status"] == "WITHDRAWN", (
        "the standing flip withdrew the member's DRAFT trial"
    )


def test_the_cascade_spares_the_endorsed_trial_and_the_withdrawn_pledges(api):
    """A hop propagates only where its precondition holds when the hop runs.

    PRD: "A cascade propagates **only where its precondition holds at the moment
    the hop runs**. When a signature drives a member over its budget ceiling and
    that member's `standing` flips to `OVER_COMMITTED`, the flip withdraws that
    member's trials that are in `DRAFT` and leaves every other trial of that
    member untouched — `ACTIVE`, `CLOSED` and terminal trials are not affected."

    PRD: "A pledge that is still `PLEDGED` simply moves `PLEDGED → WITHDRAWN` with
    no financial consequence, since it never entered the ledger."

    Design: Difficulty/transitive_cascade/signing_cascade_confirms_pledge_then_overcommits_member_then_withdraws_draft_trial
    """
    scenario = _cascade_that_overshoots_the_ceiling()

    sign(scenario["negotiation_id"])

    assert read_trial(scenario["endorsed_trial"]["id"])["status"] == "ENDORSED", (
        "the trial that unlocked the signature is terminal and untouched"
    )

    for name, member in (("yankee", scenario["yankee"]), ("zulu", scenario["zulu"])):
        row = read_commitment(scenario[f"{name}_commitment"]["id"])
        assert row["status"] == "WITHDRAWN", "hop two only confirms PLEDGED rows"
        assert row["tier_price_cents"] is None
        assert row["subscription_id"] is None
        ledger = read_member(member["id"])
        assert ledger["annual_committed_cents"] == 0
        assert ledger["standing"] == "IN_GOOD_STANDING", (
            "a withdrawn pledge never entered the ledger, so nothing flipped"
        )


def _axes_split_by_a_reopen_then_a_cancel_decision():
    """One subscription driven to DEGRADED on access and DECIDED_CANCEL on contract."""
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]

    incidents = report_off_campus_incidents(subscription_id, member_id, 5)
    diagnose_and_resolve(incidents[0]["id"])
    reopen(incidents[0]["id"], member_id)

    decision = open_renewal_decision(subscription_id, "CANCEL", 0.00)
    decision = open_vote(decision["id"])
    cast_vote(decision["id"], member_id, "YES")

    scenario["incidents"] = incidents
    scenario["decision"] = decision
    return scenario


def test_the_cancel_decision_moves_the_contract_axis_and_leaves_access_degraded(api):
    """One axis is at NOTICE_GIVEN while the other independently sits at DEGRADED.

    PRD: "Once the subscription exists it lives on two independent axes. The
    **contract axis** is driven by time and by renewal decisions; the **access
    axis** is driven by authentication verification and incident volume."

    PRD: "It sets `resolved_action` to `CANCEL`, advances `VOTING →
    DECIDED_CANCEL`, and reaches into the subscription to advance its contract
    axis `ACTIVE → NOTICE_GIVEN`."

    Design: Difficulty/non_linear_state_machine/subscription_contract_and_access_axes_advance_independently
    """
    scenario = _axes_split_by_a_reopen_then_a_cancel_decision()

    decided = decide(scenario["decision"]["id"], "CANCEL")
    assert decided["status"] == "DECIDED_CANCEL"
    assert decided["resolved_action"] == "CANCEL"

    stored = read_subscription(scenario["subscription"]["id"])
    assert_subscription(stored)
    assert stored["contract_status"] == "NOTICE_GIVEN"
    assert stored["access_status"] == "DEGRADED", (
        "the cancel decision does not touch the access axis"
    )
    assert stored["access_health_score"] == 45
    assert stored["degrade_count"] == 1
    assert stored["sla_credit_cents"] == 180000

    assert read_incident(scenario["incidents"][0]["id"])["status"] == "REOPENED"
    assert read_commitment(scenario["commitment"]["id"])["status"] == "CONFIRMED", (
        "notice being given releases nothing yet"
    )


def test_the_access_axis_degrades_while_the_contract_axis_stays_active(api):
    """The access axis walks 100 to 60 to 65 to 45 with the contract axis at ACTIVE.

    PRD: "Each incident contributes a base penalty of 8 points when its
    `off_campus` flag is true, and 4 points when it is false."

    PRD: "When a recomputation triggered by an incident report or a reopen leaves
    the score **strictly below** 60 while the subscription's `access_status` is
    `CONFIGURED`, the axis advances `CONFIGURED → DEGRADED`."

    PRD: "Each entry into `DEGRADED` adds to `sla_credit_cents` an amount equal to
    two percent of the subscription's current `negotiated_price_cents`, rounded
    half up to whole cents — but only while the newly incremented `degrade_count`
    is less than or equal to 3 events."

    Design: Difficulty/non_linear_state_machine/subscription_contract_and_access_axes_advance_independently
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]
    assert scenario["subscription"]["access_health_score"] == 100

    incidents = report_off_campus_incidents(subscription_id, member_id, 5)
    after_reports = read_subscription(subscription_id)
    assert after_reports["access_health_score"] == 60, "five off-campus denials cost 40"
    assert after_reports["access_status"] == "CONFIGURED", "60 is not strictly below 60"
    assert after_reports["contract_status"] == "ACTIVE"

    diagnose_and_resolve(incidents[0]["id"])
    after_resolve = read_subscription(subscription_id)
    assert after_resolve["access_health_score"] == 65, "a RESOLVED incident gives back 5"
    assert after_resolve["access_status"] == "CONFIGURED"

    reopen(incidents[0]["id"], member_id)
    after_reopen = read_subscription(subscription_id)
    assert after_reopen["access_health_score"] == 45, (
        "the reopen costs 15 and forfeits the 5 points of recovery"
    )
    assert after_reopen["access_status"] == "DEGRADED"
    assert after_reopen["degrade_count"] == 1
    assert after_reopen["sla_credit_cents"] == 180000, "two percent of 9,000,000"
    assert after_reopen["contract_status"] == "ACTIVE", (
        "nothing about the access axis moved the contract axis"
    )
