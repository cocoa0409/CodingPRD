"""Effectiveness-delay variants, epoch effectuation ordering, and the
supersession cascade into enforcement referrals (PRD sections 2.4, 3.2, 3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_days,
    advance_referral,
    assert_instant,
    create_dealer_org,
    create_effective_proposal,
    create_referral,
    create_rule_proposal,
    create_superseded_pair,
    decide_proposal,
    make_compliance_officer_headers,
    open_comment_period,
    read_proposal,
    read_referral,
    set_clock,
    submit_proposal,
    validate_error,
)

OFFICER = TEST_USERS["rulemaking_officer_headers"]


def _two_proposals_approved_at_one_instant(api):
    """Two proposals opened together (21-day windows at the fresh-deployment
    clock) and approved in the same logical instant; one carries the
    expedited flag. Returns (standard decide data, expedited decide data)."""
    standard = create_rule_proposal(
        api, rule_code="G-900", title="Standard rule", body="body-std", category="DEALER_CONDUCT"
    )
    expedited = create_rule_proposal(
        api, rule_code="G-901", title="Expedited rule", body="body-exp", category="DEALER_CONDUCT"
    )
    open_comment_period(api, standard["id"], days=21, expedited=False)
    open_comment_period(api, expedited["id"], days=21, expedited=True)
    set_clock(api, "2026-09-22T00:00:00Z")
    submit_proposal(api, standard["id"])
    submit_proposal(api, expedited["id"])
    standard_decided = decide_proposal(api, standard["id"], "APPROVE")
    expedited_decided = decide_proposal(api, expedited["id"], "APPROVE")
    return standard_decided, expedited_decided


def test_standard_and_expedited_delays_diverge_twenty_days(api):
    """PRD section 3.2: "The system computes `effective_at` as
    `approval_at` plus thirty days for a standard rulemaking, or
    `approval_at` plus ten days when the proposal's `expedited` flag is
    true — for two proposals approved at the same instant, the expedited
    one becomes effective twenty days earlier."

    Design: Difficulty/dual_variant_calc/rule_effectiveness_standard_vs_expedited
    """
    standard, expedited = _two_proposals_approved_at_one_instant(api)
    assert_instant(standard["approval_at"], "2026-09-22T00:00:00Z", "standard approval_at")
    assert_instant(expedited["approval_at"], "2026-09-22T00:00:00Z", "expedited approval_at")
    assert standard["expedited"] is False
    assert expedited["expedited"] is True
    assert_instant(standard["effective_at"], "2026-10-22T00:00:00Z", "standard effective_at")
    assert_instant(expedited["effective_at"], "2026-10-02T00:00:00Z", "expedited effective_at")

    # At the expedited instant only the expedited proposal effectuates.
    set_clock(api, "2026-10-02T00:00:00Z")
    expedited_now = read_proposal(api, expedited["id"])
    standard_now = read_proposal(api, standard["id"])
    assert expedited_now["status"] == "EFFECTIVE", (
        f"expedited proposal must be EFFECTIVE at approval+10d, got {expedited_now['status']!r}"
    )
    assert standard_now["status"] == "APPROVED", (
        f"standard proposal must still be APPROVED at approval+10d, got {standard_now['status']!r}"
    )


def test_both_variants_effectuate_at_their_own_computed_instant(api):
    """PRD section 3.2: "when the logical clock reaches or passes a
    proposal's `effective_at`, the proposal transitions from `APPROVED` to
    `EFFECTIVE`". For two proposals approved at the same instant, "the
    expedited one becomes effective twenty days earlier" (section 3.2).

    Design: Difficulty/dual_variant_calc/rule_effectiveness_standard_vs_expedited
    """
    standard, expedited = _two_proposals_approved_at_one_instant(api)
    # The two effectiveness dates stand exactly twenty days apart.
    assert_instant(
        standard["effective_at"], add_days(expedited["effective_at"], 20), "twenty-day divergence"
    )

    # Inclusive boundary: at exactly the expedited effective_at, it flips.
    set_clock(api, "2026-10-02T00:00:00Z")
    assert read_proposal(api, expedited["id"])["status"] == "EFFECTIVE"

    # At the standard effective_at the second proposal follows.
    set_clock(api, "2026-10-22T00:00:00Z")
    assert read_proposal(api, standard["id"])["status"] == "EFFECTIVE"


def test_effectuation_supersedes_target_and_flags_open_referral(api):
    """PRD section 3.2: "If the newly effective proposal declared a
    `supersedes_proposal_id` and the referenced proposal is currently
    `EFFECTIVE`, that referenced proposal transitions from `EFFECTIVE` to
    `SUPERSEDED` in the same pass". PRD section 3.2: "Every enforcement
    referral that cites the superseded proposal's `rule_code` and is still
    in `OPEN` or `REFERRED` status has its `needs_rule_review` flag set to
    true".

    Design: Difficulty/transitive_cascade/rule_effectuation_supersession_referral_cascade
    """
    bundle = create_superseded_pair(api, rule_code_a="G-100", rule_code_b="G-101", with_referral=True)
    assert bundle["rule_b"]["status"] == "EFFECTIVE", (
        f"superseding proposal must reach EFFECTIVE, got {bundle['rule_b']['status']!r}"
    )
    assert bundle["rule_a"]["status"] == "SUPERSEDED", (
        f"referenced proposal must be SUPERSEDED, got {bundle['rule_a']['status']!r}"
    )
    referral = bundle["referral"]
    assert referral is not None
    assert referral["needs_rule_review"] is True, (
        "the open referral citing the superseded rule must be flagged needs_rule_review"
    )


def test_supersession_cascade_leaves_closed_referrals_untouched(api):
    """PRD section 3.2: "The flag stays true until the referral closes;
    referrals already closed are untouched."

    Design: Difficulty/transitive_cascade/rule_effectuation_supersession_referral_cascade
    """
    rule_a = create_effective_proposal(api, rule_code="G-110", category="TRADE_REPORTING")
    subject = create_dealer_org(api)
    referral = create_referral(api, rule_a["rule_code"], subject_org_id=subject["id"])
    referral = advance_referral(api, referral["id"], "REFERRED")
    closed = advance_referral(
        api,
        referral["id"],
        "CLOSED_NO_ACTION",
        officer_headers=make_compliance_officer_headers("co-2"),
        closure_notes="unsubstantiated",
    )
    assert closed["status"] == "CLOSED_NO_ACTION"
    assert closed["needs_rule_review"] is False

    create_effective_proposal(
        api,
        days=21,
        expedited=True,
        anchor="2026-10-22T00:00:00Z",
        rule_code="G-111",
        category="TRADE_REPORTING",
        supersedes_proposal_id=rule_a["id"],
    )
    assert read_proposal(api, rule_a["id"])["status"] == "SUPERSEDED"
    after = read_referral(api, referral["id"])
    assert after["needs_rule_review"] is False, (
        "a referral closed before the supersession must keep needs_rule_review false"
    )


def test_superseded_proposal_rejects_further_transitions(api):
    """PRD section 3.2: "the only way a proposal reaches the terminal
    `SUPERSEDED` state is through this cascade" and "A proposal that is
    superseded never returns". PRD section 2.5 step 7: "The target
    resource's state machine must permit the attempted transition"
    (`ERR_INVALID_STATE`, HTTP 409).

    Design: Corner/state_machines/superseded_proposal_rejects_further_transitions
    """
    bundle = create_superseded_pair(api, rule_code_a="G-100", rule_code_b="G-101")
    rule_a = bundle["rule_a"]
    assert rule_a["status"] == "SUPERSEDED"
    resp = api.open_comment_period(rule_a["id"], {"comment_period_days": 21}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_proposal(api, rule_a["id"])["status"] == "SUPERSEDED"


def test_epoch_effectuates_tied_proposals_and_supersedes_target_once(api):
    """PRD section 2.4: "every `APPROVED` proposal whose `effective_at` is
    at or before the new current time transitions to `EFFECTIVE`, processed
    in order of `effective_at` ascending with ties broken by `created_at`
    ascending, and each effectuation runs the supersession cascade
    described in §3.2." PRD section 3.2 conditions the cascade on
    the referenced proposal being "currently `EFFECTIVE`" and increments
    the superseded proposal's `version` exactly once ("Both the newly
    effective proposal's and the superseded proposal's `version` increment
    by one").

    Design: Corner/calculations/epoch_effectuates_multiple_proposals_in_pinned_order
    """
    rule_a = create_rule_proposal(api, rule_code="G-200", title="Rule A", body="a", category="MARKET_DATA")
    rule_b = create_rule_proposal(
        api, rule_code="G-201", title="Rule B", body="b", category="MARKET_DATA",
        supersedes_proposal_id=rule_a["id"],
    )
    rule_c = create_rule_proposal(
        api, rule_code="G-202", title="Rule C", body="c", category="MARKET_DATA",
        supersedes_proposal_id=rule_a["id"],
    )
    open_comment_period(api, rule_a["id"], days=21)
    open_comment_period(api, rule_b["id"], days=21, expedited=True)
    open_comment_period(api, rule_c["id"], days=21, expedited=True)

    set_clock(api, "2026-09-22T00:00:00Z")
    submit_proposal(api, rule_a["id"])
    decide_proposal(api, rule_a["id"], "APPROVE")

    set_clock(api, "2026-10-22T00:00:00Z")  # A effectuates (standard +30d)
    assert read_proposal(api, rule_a["id"])["status"] == "EFFECTIVE"

    set_clock(api, "2026-11-12T00:00:00Z")
    submit_proposal(api, rule_b["id"])
    submit_proposal(api, rule_c["id"])
    decide_proposal(api, rule_b["id"], "APPROVE")  # expedited: effective 2026-11-22
    decide_proposal(api, rule_c["id"], "APPROVE")  # expedited: effective 2026-11-22

    version_before = read_proposal(api, rule_a["id"])["version"]
    set_clock(api, "2026-11-22T00:00:00Z")

    after_a = read_proposal(api, rule_a["id"])
    assert after_a["status"] == "SUPERSEDED"
    assert after_a["version"] == version_before + 1, (
        "the supersession cascade must strike A exactly once even though two "
        f"effectuating proposals both cite it: {version_before} -> {after_a['version']}"
    )
    assert read_proposal(api, rule_b["id"])["status"] == "EFFECTIVE"
    assert read_proposal(api, rule_c["id"])["status"] == "EFFECTIVE"
