"""Write responses and later reads agree, with no settling period in between.

Each case reads the same derived figure twice — once out of the mutating response
itself and once out of a follow-up read of every aggregate the write touched — and
insists the two agree exactly.
"""

from test_helpers import (
    CASE_MANAGER,
    COORDINATOR,
    assert_admission,
    assert_instant_equals,
    assert_program_counters,
    discharge_payload,
    fetch_placement,
    fetch_program,
    fetch_youth,
    instant,
    move_clock,
    savings_entry_payload,
    setup_sheltered_youth_open_posture,
    setup_tlp_placement,
    validate_success,
)

RIVERSIDE = {
    "name": "Riverside Emergency Shelter",
    "licensed_bed_capacity": 2,
    "min_age_years": 12,
    "max_age_years": 17,
    "max_stay_nights": 21,
}
NORTHSIDE = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
}
DOB_AGE_16 = "2010-03-15"
PLANNED_DISCHARGE = instant("2026-08-15")
MONTHLY_INCOME_CENTS = 90000


# ─── Instance: the discharge response is already the settled truth ───

FABIO = {
    "legal_first_name": "Fabio",
    "legal_last_name": "Renzi",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
DISCHARGE_CLOCK = instant("2026-08-05")


def test_the_discharge_response_and_the_follow_up_reads_agree_exactly(api):
    """PRD §3.5: "At discharge it is the number of whole calendar days from the calendar
    date of `admitted_at` to the calendar date of `discharged_at`, plus one further night
    when the hour of the discharge instant is at or after twelve — a youth still in the bed
    at or after 12:00:00Z on the discharge date has occupied that night's bed for federal
    reporting purposes."
    PRD §3.5: "First, `discharged_at` is stamped with the clock instant, the supplied
    `exit_destination` is stored, `final_billable_nights` is computed by the
    chronological-actual rule, and `outcome_positive` is derived as true exactly when the
    destination is `FAMILY_REUNIFIED`, `TRANSITIONAL_LIVING` or `INDEPENDENT_HOUSING` and
    false otherwise — the field is null until discharge; the youth's
    `cumulative_shelter_nights` rises by the final billable nights, and the youth's `status`
    moves to `REUNIFIED` if the youth was in `REUNIFIED_PENDING` and the destination is
    `FAMILY_REUNIFIED`, and otherwise to `EXITED`, with the youth's `version` incremented by
    one and `governance_vote_eligible` recomputed to false either way."
    PRD §3.5: "Second, because the admission has left the set of bed-holding statuses, the
    program's `occupied_beds` falls by one."
    PRD §3.5: "Third, because occupied beds changed, the program's `utilization_bp` and
    `posture` are recomputed."

    Design: Corner/consistency_model/discharge_response_already_carries_every_derived_field
    """
    setup = setup_sheltered_youth_open_posture(
        program_overrides=dict(RIVERSIDE),
        youth_overrides=dict(FABIO),
        planned_discharge_at=PLANNED_DISCHARGE,
    )
    move_clock(DISCHARGE_CLOCK)

    discharged = validate_success(
        api.discharge_admission(
            setup["admission"]["id"], discharge_payload("FAMILY_REUNIFIED"), CASE_MANAGER
        )
    )

    assert_admission(discharged)
    assert discharged["status"] == "DISCHARGED", (
        f"the mutating response already reports the terminal status, got {discharged['status']}"
    )
    assert_instant_equals(discharged["discharged_at"], DISCHARGE_CLOCK,
                          "the discharge response's discharged_at")
    assert discharged["final_billable_nights"] == 4, (
        "2026-08-01 to 2026-08-05 is four whole calendar days and a midnight discharge "
        f"earns no cutoff night, got {discharged['final_billable_nights']}"
    )
    assert discharged["outcome_positive"] is True, (
        f"a FAMILY_REUNIFIED destination is a positive outcome, got {discharged['outcome_positive']}"
    )

    read_back = validate_success(api.get_admission(setup["admission"]["id"], CASE_MANAGER))
    for field in ("status", "discharged_at", "final_billable_nights", "outcome_positive",
                  "exit_destination"):
        assert read_back[field] == discharged[field], (
            f"the follow-up read of {field} disagrees with the discharge response: "
            f"{read_back[field]} against {discharged[field]}"
        )

    program = fetch_program(setup["program"]["id"])
    assert_program_counters(program)
    assert program["occupied_beds"] == 0, (
        f"the released bed is already free on the next read, got {program['occupied_beds']}"
    )
    assert program["utilization_bp"] == 0, (
        f"an empty program is at zero basis points, got {program['utilization_bp']}"
    )
    assert program["posture"] == "OPEN", (
        f"an empty program with no overdue obligation is OPEN, got {program['posture']}"
    )
    youth = fetch_youth(setup["youth"]["id"])
    assert youth["cumulative_shelter_nights"] == 4, (
        "the four final nights are already on the youth, got "
        f"{youth['cumulative_shelter_nights']}"
    )
    assert youth["status"] == "EXITED", (
        "this youth never stood in REUNIFIED_PENDING, so the destination alone does not "
        f"reunify, got {youth['status']}"
    )
    assert youth["governance_vote_eligible"] is False, (
        f"a departed youth votes no longer, got {youth['governance_vote_eligible']}"
    )


# ─── Instance: the ledger entry and the aggregates it moves ───

GALA = {
    "legal_first_name": "Gala",
    "legal_last_name": "Ibarra",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
DEPOSIT_CENTS = 3011


def test_the_stamped_balance_reconciles_against_the_placement_and_the_youth(api):
    """PRD §3.7: "`signed_amount_cents` gives the posting its direction: it is the positive
    `amount_cents` for a `DEPOSIT`, and the negation of `amount_cents` for both a
    `WITHDRAWAL` and a `REVERSAL`."
    PRD §3.7: "`match_component_cents` is the per-entry program match: for a `DEPOSIT` it is
    the entry's `amount_cents` multiplied by the program's `savings_match_rate_bp`, divided
    by 10000 and rounded **half up** to whole cents; for a `REVERSAL` it is the exact
    negation of that same quantity; and for a `WITHDRAWAL` it is 0."
    PRD §3.7: "`balance_after_cents` is the placement's `savings_balance_cents` as it stands
    immediately after this entry posted."
    PRD §3.7: "The placement's `savings_balance_cents` is the sum of `signed_amount_cents`
    over every entry plus the capped `match_awarded_cents` — that identity is the conserved
    quantity of the account and must hold after every posting."
    PRD §3.7: "Posting an entry also recomputes the youth's
    `lifetime_savings_deposited_cents`, which is the sum of `amount_cents` over the youth's
    `DEPOSIT` entries minus the sum of `amount_cents` over the youth's `REVERSAL` entries,
    taken across every placement that youth has ever held; and it increments the placement's
    `version` by one."

    Design: Corner/consistency_model/a_savings_entry_and_a_later_read_agree_on_the_balance
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(GALA),
    )
    placement = setup["placement"]
    observed_version = placement["version"]

    entry = validate_success(
        api.create_savings_entry(
            placement["id"],
            savings_entry_payload("DEPOSIT", DEPOSIT_CENTS, observed_version, "first paycheque"),
            COORDINATOR,
        ),
        201,
    )

    assert entry["signed_amount_cents"] == 3011, (
        f"a deposit posts positively, got {entry['signed_amount_cents']}"
    )
    assert entry["match_component_cents"] == 753, (
        "3011 cents matched at 2500 basis points is 752.75, rounded half up to 753, got "
        f"{entry['match_component_cents']}"
    )
    assert entry["balance_after_cents"] == 3764, (
        f"3011 plus its 753-cent match is 3764, got {entry['balance_after_cents']}"
    )

    reconciled = fetch_placement(placement["id"])
    assert reconciled["savings_balance_cents"] == entry["balance_after_cents"], (
        "the placement read disagrees with the balance the entry stamped: "
        f"{reconciled['savings_balance_cents']} against {entry['balance_after_cents']}"
    )
    assert reconciled["match_awarded_cents"] == 753, (
        "the single entry's match is the whole awarded total, got "
        f"{reconciled['match_awarded_cents']}"
    )
    assert reconciled["version"] == observed_version + 1, (
        f"posting an entry moves the placement version by one, got {reconciled['version']}"
    )
    saver = fetch_youth(setup["youth"]["id"])
    assert saver["lifetime_savings_deposited_cents"] == 3011, (
        "the youth's lifetime figure counts the deposit magnitude without the match, got "
        f"{saver['lifetime_savings_deposited_cents']}"
    )
