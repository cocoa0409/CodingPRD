"""The two status dimensions of one membership, and the arrears share that escapes it.

A single agreement row carries a contract dimension and a collections dimension that move
on disjoint triggers: freezing suspends the contract, not the ledger. A second scenario
puts one of two live memberships into arrears and follows the share upward.
"""

from test_helpers import (
    create_member,
    freeze_agreement,
    post_dues,
    post_payment_failure,
    read_agreement,
    read_club,
    read_franchisee,
    set_clock_date,
    setup_single_club_franchise,
    sign_active_agreement,
    unfreeze_agreement,
)


def _frozen_membership_aged_to_twenty_nine_days() -> dict:
    """One live membership, frozen while CURRENT, whose September charge is 29 days
    overdue at a clock of 2026-10-04."""
    scenario = setup_single_club_franchise(
        legal_name="Ridgeway Fitness LLC",
        contact_email="ops@ridgewayfit.example",
        club_name="Ridgeway Club",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Cara Devlin", email="cara.devlin@example.com"
    )
    agreement = sign_active_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        signed_on="2026-08-01",
        due_on="2026-08-05",
        paid_on="2026-08-02",
        multi_club_access=False,
    )
    freeze_agreement(agreement["id"], scenario["club"]["id"])
    set_clock_date("2026-09-01")
    post_dues(agreement["id"], 4500, "2026-09-01", "2026-09-05")
    set_clock_date("2026-10-04")
    post_payment_failure(agreement["id"], "2026-10-04")
    scenario["member"] = member
    scenario["agreement"] = agreement
    return scenario


def _frozen_membership_aged_to_thirty_days() -> dict:
    """The same membership one day later, re-projected across the delinquency boundary."""
    scenario = _frozen_membership_aged_to_twenty_nine_days()
    set_clock_date("2026-10-05")
    post_payment_failure(scenario["agreement"]["id"], "2026-10-05")
    return scenario


def _one_of_two_live_memberships_in_arrears() -> dict:
    """Two ACTIVE agreements at one club; only the first is left unpaid into a second
    month, making the arrears share exactly one half."""
    scenario = setup_single_club_franchise()
    first_member = create_member(
        scenario["club"]["id"],
        full_name="Ivo Marchetti",
        email="ivo.marchetti@example.com",
    )
    second_member = create_member(
        scenario["club"]["id"], full_name="Pia Lindgren", email="pia.lindgren@example.com"
    )
    first = sign_active_agreement(
        first_member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    second = sign_active_agreement(
        second_member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    set_clock_date("2026-09-01")
    post_dues(first["id"], 4500, "2026-09-01", "2026-09-05")
    set_clock_date("2026-10-05")
    scenario["first_agreement"] = first
    scenario["second_agreement"] = second
    scenario["trigger"] = post_payment_failure(first["id"], "2026-10-05")
    return scenario


def test_freezing_a_current_membership_leaves_it_in_the_watch_denominator():
    """The freeze pauses the contract dimension only; the club still counts the membership
    among its live ones.

    PRD 3.5: "It deliberately leaves the club's `active_agreement_count` alone: a frozen
    membership still counts as active in the collections-watch denominator, so freezing
    cannot be used to flatter a club's arrears share."

    Design: Difficulty/non_linear_state_machine/agreement_status_and_dues_status_dimensions_advance_independently
    """
    scenario = setup_single_club_franchise(
        legal_name="Ridgeway Fitness LLC",
        contact_email="ops@ridgewayfit.example",
        club_name="Ridgeway Club",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Cara Devlin", email="cara.devlin@example.com"
    )
    agreement = sign_active_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )
    assert agreement["agreement_status"] == "ACTIVE"
    assert agreement["dues_status"] == "CURRENT"
    assert agreement["effective_monthly_dues_cents"] == 4500

    frozen = freeze_agreement(agreement["id"], scenario["club"]["id"])
    assert frozen["agreement_status"] == "FROZEN"
    assert frozen["dues_status"] == "CURRENT"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 1


def test_ledger_reaches_past_due_at_twenty_nine_days_while_the_contract_is_frozen():
    """The September charge ages to 29 days under a frozen contract, which is one day
    short of delinquency.

    PRD 3.4: "The boundary is exact and inclusive on the delinquency side: an age of 29
    days is `PAST_DUE`, and an age of 30 days is `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/agreement_status_and_dues_status_dimensions_advance_independently
    """
    scenario = _frozen_membership_aged_to_twenty_nine_days()

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["agreement_status"] == "FROZEN"
    assert agreement["dues_status"] == "PAST_DUE"
    assert agreement["delinquency_days"] == 29
    assert agreement["outstanding_balance_cents"] == 4500


def test_one_more_day_takes_the_collections_dimension_to_delinquent_under_the_freeze():
    """At 30 days the collections cascade fires even though the contract dimension has not
    moved off FROZEN.

    PRD 3.4: "Otherwise, if `delinquency_days` is at least 30, `dues_status` becomes
    `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/agreement_status_and_dues_status_dimensions_advance_independently
    """
    scenario = _frozen_membership_aged_to_thirty_days()

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["agreement_status"] == "FROZEN"
    assert agreement["dues_status"] == "DELINQUENT"
    assert agreement["delinquency_days"] == 30


def test_unfreezing_restores_the_contract_without_curing_the_arrears():
    """The membership comes back ACTIVE and comes back regardless, still carrying the
    delinquency it accumulated while paused.

    PRD 3.5: "In particular, the collections dimension is irrelevant here — the `ACTIVE ↔
    FROZEN` cycle runs entirely independently of `dues_status`, which keeps advancing from
    billing events all the way through a freeze, so a membership frozen while `CURRENT` may
    well come back as `DELINQUENT`, and it comes back regardless."

    Design: Difficulty/non_linear_state_machine/agreement_status_and_dues_status_dimensions_advance_independently
    """
    scenario = _frozen_membership_aged_to_thirty_days()

    unfrozen = unfreeze_agreement(scenario["agreement"]["id"], scenario["club"]["id"])
    assert unfrozen["agreement_status"] == "ACTIVE"
    assert unfrozen["dues_status"] == "DELINQUENT"
    assert unfrozen["delinquency_days"] == 30
    assert unfrozen["outstanding_balance_cents"] == 4500
    assert unfrozen["dues_paid_cents"] == 4500


def test_sole_delinquent_membership_raises_the_watch_flag_and_docks_the_franchisee():
    """One delinquent membership out of one live one is a share of 1.0, far above the
    threshold, so the club goes on watch and the franchisee loses the flat 20 points.

    PRD 3.4: "`collections_watch` is true when the denominator is greater than 0 and the
    numerator divided by the denominator is strictly greater than 0.15 — more than fifteen
    percent of live memberships in arrears."

    Design: Difficulty/non_linear_state_machine/agreement_status_and_dues_status_dimensions_advance_independently
    """
    scenario = _frozen_membership_aged_to_thirty_days()
    unfreeze_agreement(scenario["agreement"]["id"], scenario["club"]["id"])

    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 1
    assert club["delinquent_member_count"] == 1
    assert club["collections_watch"] is True
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["collections_watch_club_count"] == 1
    assert franchisee["compliance_score"] == 80
    assert franchisee["status"] == "ACTIVE"


def test_appended_entry_snapshots_the_balance_it_left_behind():
    """The zero-amount failure marker moves no money, so the snapshot it stores is the
    4500 cents still outstanding after it was folded in.

    PRD 3.4: "Every appended entry also stores `resulting_outstanding_balance_cents`, a
    snapshot of the agreement's outstanding balance immediately after that entry was folded
    into the projection, so the ledger can be replayed for audit."

    Design: Difficulty/transitive_cascade/single_delinquent_agreement_cascades_club_watch_to_franchisee_score
    """
    scenario = _one_of_two_live_memberships_in_arrears()

    assert scenario["trigger"]["event_type"] == "PAYMENT_FAILED"
    assert scenario["trigger"]["amount_cents"] == 0
    assert scenario["trigger"]["resulting_outstanding_balance_cents"] == 4500


def test_only_the_unpaid_membership_ages_and_its_sibling_stays_current():
    """Ageing is decided per agreement from its own ledger, so the second membership is
    untouched at zero balance and zero days.

    PRD 3.4: "Otherwise `delinquency_days` is the number of whole days from that earliest
    unsatisfied charge's `due_on` to the logical clock date, floored at 0 so that a charge
    not yet due never produces a negative age."

    Design: Difficulty/transitive_cascade/single_delinquent_agreement_cascades_club_watch_to_franchisee_score
    """
    scenario = _one_of_two_live_memberships_in_arrears()

    first = read_agreement(scenario["first_agreement"]["id"])
    assert first["dues_status"] == "DELINQUENT"
    assert first["delinquency_days"] == 30
    assert first["outstanding_balance_cents"] == 4500
    second = read_agreement(scenario["second_agreement"]["id"])
    assert second["dues_status"] == "CURRENT"
    assert second["outstanding_balance_cents"] == 0
    assert second["delinquency_days"] == 0


def test_arrears_share_of_one_half_flips_the_club_onto_collections_watch():
    """Two live memberships and one in arrears give a share of 0.5, which clears the
    fifteen percent threshold, while the count of live memberships stays at two.

    PRD 3.4: "The denominator is the number of agreements whose `home_club_id` is that club
    and whose `agreement_status` is `ACTIVE`, `FROZEN` or `CANCELLATION_PENDING`; that
    figure is stored as `active_agreement_count`."

    Design: Difficulty/transitive_cascade/single_delinquent_agreement_cascades_club_watch_to_franchisee_score
    """
    scenario = _one_of_two_live_memberships_in_arrears()

    club = read_club(scenario["club"]["id"])
    assert club["active_agreement_count"] == 2
    assert club["delinquent_member_count"] == 1
    assert club["collections_watch"] is True


def test_flat_collections_penalty_lands_once_and_leaves_the_franchisee_active():
    """With no inspection failures and no disputed royalties, the only deduction is the
    single flat 20 for having a club on watch, so 80 keeps the franchisee ACTIVE.

    PRD 3.9: "`compliance_score` then starts at 100 and subtracts 20 for each step of
    `inspection_fail_streak`, a flat 20 if `collections_watch_club_count` is greater than
    zero — one flat penalty no matter how many clubs are on watch, not 20 per club — and 10
    for each disputed royalty report, with the result clamped into 0 through 100."

    Design: Difficulty/transitive_cascade/single_delinquent_agreement_cascades_club_watch_to_franchisee_score
    """
    scenario = _one_of_two_live_memberships_in_arrears()

    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["collections_watch_club_count"] == 1
    assert franchisee["inspection_fail_streak"] == 0
    assert franchisee["disputed_royalty_count"] == 0
    assert franchisee["compliance_score"] == 80
    assert franchisee["status"] == "ACTIVE"
