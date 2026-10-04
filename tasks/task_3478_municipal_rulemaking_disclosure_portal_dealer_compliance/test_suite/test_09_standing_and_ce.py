"""Professional standing x qualification dimensions, the employer
headcount invariant, and the continuing-education cycle with its epoch
transitions (PRD sections 2.4, 3.5, 3.6)."""
from test_helpers import (
    assert_instant,
    create_ce_due_professional,
    create_dealer_org,
    create_org_with_professional,
    create_professional,
    create_qualified_professional,
    read_organization,
    read_professional,
    record_ce_credits,
    set_clock,
    set_standing,
    suspend_organization,
)


def test_standing_cycle_leaves_qualification_untouched(api):
    """PRD section 3.6: "A professional's state has two parallel dimensions
    that evolve independently: `qualification_status`, born `UNQUALIFIED`,
    and `standing`, born `ACTIVE`", and "The two dimensions meet in exactly
    one derived boolean: `may_transact` is true precisely when
    `qualification_status` is `QUALIFIED` and `standing` is `ACTIVE`, and
    it is recomputed on every qualification or standing change."

    Design: Difficulty/non_linear_state_machine/professional_parallel_dimension_independence
    """
    org, prof = create_qualified_professional(api)  # QUALIFIED x ACTIVE
    assert prof["may_transact"] is True

    suspended = set_standing(api, prof["id"], "SUSPENDED", reason="investigation")
    assert suspended["standing"] == "SUSPENDED"
    assert suspended["qualification_status"] == "QUALIFIED", (
        "a standing transition must not touch the qualification dimension"
    )
    assert suspended["may_transact"] is False

    reinstated = set_standing(api, prof["id"], "ACTIVE")
    assert reinstated["standing"] == "ACTIVE"
    assert reinstated["qualification_status"] == "QUALIFIED"
    assert reinstated["may_transact"] is True


def test_standing_cycle_while_ce_due_keeps_may_transact_false(api):
    """PRD section 3.6: "`may_transact` is true precisely when
    `qualification_status` is `QUALIFIED` and `standing` is `ACTIVE`" —
    for a `CE_DUE` professional, neither suspension nor reinstatement can
    raise the flag, and the qualification dimension stays `CE_DUE`
    throughout ("two parallel dimensions that evolve independently").

    Design: Difficulty/non_linear_state_machine/professional_parallel_dimension_independence
    """
    org, prof = create_ce_due_professional(api)
    assert prof["qualification_status"] == "CE_DUE"
    assert prof["may_transact"] is False

    suspended = set_standing(api, prof["id"], "SUSPENDED", reason="audit hold")
    assert suspended["standing"] == "SUSPENDED"
    assert suspended["qualification_status"] == "CE_DUE"
    assert suspended["may_transact"] is False

    reinstated = set_standing(api, prof["id"], "ACTIVE")
    assert reinstated["standing"] == "ACTIVE"
    assert reinstated["qualification_status"] == "CE_DUE"
    assert reinstated["may_transact"] is False, (
        "CE_DUE x ACTIVE is not transactable: qualification is not QUALIFIED"
    )


def test_suspend_then_reinstate_conserves_active_headcount(api):
    """PRD section 3.6: "Registration increments the employer
    organization's `active_professional_count` by one" and "Moving a
    professional to `SUSPENDED` decrements the employer organization's
    `active_professional_count` by one; reinstatement to `ACTIVE`
    increments it back." A suspend/reinstate pair returns the count to
    exactly its prior value.

    Design: Difficulty/compensating_invariant/standing_cycle_conserves_active_professional_count
    """
    org = create_dealer_org(api, org_code="BD-1000", name="Dealer Ten")
    pro = create_professional(api, org["id"], full_name="Pro One")
    create_professional(
        api, org["id"], professional_class="MUNICIPAL_ADVISOR_REP", full_name="Pro Two"
    )
    assert read_organization(api, org["id"])["active_professional_count"] == 2

    set_standing(api, pro["id"], "SUSPENDED", reason="audit hold")
    assert read_organization(api, org["id"])["active_professional_count"] == 1

    set_standing(api, pro["id"], "ACTIVE")
    assert read_organization(api, org["id"])["active_professional_count"] == 2, (
        "suspend + reinstate must conserve the active headcount with no drift"
    )


def test_headcount_adjustment_is_scoped_to_the_employer_org(api):
    """PRD section 3.6: "Moving a professional to `SUSPENDED` decrements
    the employer organization's `active_professional_count` by one" — only
    the employer's counter moves; a sibling organization is untouched.

    Design: Difficulty/compensating_invariant/standing_cycle_conserves_active_professional_count
    """
    org_a = create_dealer_org(api, org_code="BD-1010", name="Dealer Scope A")
    org_b = create_dealer_org(api, org_code="BD-1011", name="Dealer Scope B")
    pro_a = create_professional(api, org_a["id"], full_name="Pro A")
    create_professional(api, org_b["id"], full_name="Pro B")

    set_standing(api, pro_a["id"], "SUSPENDED", reason="hold")

    assert read_organization(api, org_a["id"])["active_professional_count"] == 0
    assert read_organization(api, org_b["id"])["active_professional_count"] == 1


def test_org_suspension_does_not_cascade_to_professionals(api):
    """PRD section 3.5: "Suspension does not cascade to the organization's
    professionals or subscriptions, but it gates the future" — the
    professional's own standing and qualification are unchanged by the
    employer's suspension.

    Design: Corner/state_machines/org_suspend_does_not_cascade_to_professional
    """
    org, prof = create_org_with_professional(api, org_code="BD-1005", name="Dealer Nocascade")
    suspend_organization(api, org["id"], reason="net capital deficiency")

    after = read_professional(api, prof["id"])
    assert after["standing"] == "ACTIVE", (
        f"org suspension must not move professional standing, got {after['standing']!r}"
    )
    assert after["qualification_status"] == "UNQUALIFIED"


def test_ce_cure_requires_the_ethics_subbucket_independently(api):
    """PRD section 3.6: "When, after applying a recording, the open cycle
    holds at least 12 credits in total **and** at least 2 ethics credits,
    the professional returns from `CE_DUE` to `QUALIFIED`; the ethics
    minimum binds independently, so a large general total without the
    ethics sub-bucket does not cure." Recorded credits "are added into the
    open cycle's `ce_credits_total` and `ce_ethics_credits` respectively."

    Design: Corner/calculations/ce_cure_requires_ethics_subbucket_minimum
    """
    org, prof = create_ce_due_professional(api)  # CE_DUE at 2027-09-01T00:00:00Z

    first = record_ce_credits(api, prof["id"], credits_total=12, ethics_credits=1)
    assert first["qualification_status"] == "CE_DUE", (
        "12 total with only 1 ethics credit must not cure the cycle"
    )
    assert first["ce_credits_total"] == 12
    assert first["ce_ethics_credits"] == 1

    second = record_ce_credits(api, prof["id"], credits_total=0, ethics_credits=1)
    assert second["ce_credits_total"] == 12, "credits accumulate: 12 + 0"
    assert second["ce_ethics_credits"] == 2, "credits accumulate: 1 + 1"
    assert second["qualification_status"] == "QUALIFIED", (
        "12 total with 2 ethics credits satisfies the cure"
    )


def test_ce_epoch_transitions_due_then_lapsed_at_pinned_anchors(api):
    """PRD section 3.6: "`ce_cycle_end` is derived as exactly 365 days
    after qualification, `ce_grace_end` as 60 days beyond the cycle end";
    "When the epoch pass of §2.4 finds the current time at or beyond
    a `QUALIFIED` professional's `ce_cycle_end`, the professional moves to
    `CE_DUE`; when it finds a `CE_DUE` professional at or beyond
    `ce_grace_end`, the professional moves to `LAPSED`." Qualification was
    earned at the fresh-deployment clock 2026-09-01T00:00:00Z.

    Design: Corner/cross_cutting_layers/ce_epoch_due_then_lapse_transitions
    """
    org, prof = create_qualified_professional(api)  # QUALIFIED at 2026-09-01T00:00:00Z
    assert prof["may_transact"] is True

    set_clock(api, "2027-09-01T00:00:00Z")
    due = read_professional(api, prof["id"])
    assert due["qualification_status"] == "CE_DUE"
    assert_instant(due["ce_cycle_end"], "2027-09-01T00:00:00Z", "ce_cycle_end")
    assert_instant(due["ce_grace_end"], "2027-10-31T00:00:00Z", "ce_grace_end")
    assert due["may_transact"] is False

    set_clock(api, "2027-10-31T00:00:00Z")
    lapsed = read_professional(api, prof["id"])
    assert lapsed["qualification_status"] == "LAPSED"
    assert lapsed["may_transact"] is False
