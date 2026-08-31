"""The OWBPA decisional-unit disclosure and the age-driven consideration window."""

from test_helpers import (
    ALICE,
    BEN,
    CARLA,
    TEST_USERS,
    ApiErrorId,
    assert_age_bands_sorted,
    assert_disclosure,
    clear_analysis,
    create_locked_plan,
    decide,
    deliver_notice,
    generate_disclosure,
    issue_offer,
    price_offer,
    propose_batch,
    read_disclosure,
    read_employee,
    read_plan,
    read_selection,
    render_legal_decision,
    run_analysis,
    setup_offer_ready_scenario,
    setup_site_with_roster,
    submit_for_review,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
BENEFITS = TEST_USERS["benefits_headers"]


def test_disclosure_covers_the_whole_decisional_unit_not_only_the_selected(api):
    """PRD 3.6: "The disclosure is about the unit, not about the selected group:
    selected and non-selected employees alike are counted, including people who
    hold no selection at all."
    PRD 3.6: "Each unit member's age is their completed whole years between
    `birth_date` and the anchor. From those ages the disclosure records
    `eligible_count` as the number of unit members aged 40 or over,
    `selected_count` as the number of unit members holding a selection of this
    plan in `SELECTED` or `SEPARATED` status, and `non_selected_count` as the
    size of the unit less that selected figure. It records `min_age` and
    `max_age` as the lowest and highest unit ages, and `age_bands` as one entry
    per distinct age actually held by a unit member, each entry carrying that
    `age` together with its own `selected_count` and `non_selected_count`,
    sorted by age ascending. No band is invented for an age nobody holds."
    PRD 3.6: "Three further values are snapshotted at generation.
    `decisional_unit_name` is copied verbatim from the plan, `consideration_days`
    captures the plan's `owbpa_consideration_days` as it stood at generation, and
    `snapshot_selected_count` and `snapshot_pool_count` capture the plan's
    `selected_count` and `pool_count`."

    Design: Corner/calculations/owbpa_disclosure_reports_decisional_unit_age_bands
    """
    _site, employees = setup_site_with_roster((ALICE, BEN, CARLA), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [employees[0]["id"]])
    decide(batch["selection_ids"][0], "SELECT")

    disclosure = validate_success(
        api.create_disclosure({"plan_id": plan["id"]}, COUNSEL), 201
    )
    assert_disclosure(disclosure)
    assert disclosure["decisional_unit_name"] == "Austin Operations"
    assert disclosure["eligible_count"] == 2, "Alice at 48 and Carla at 54"
    assert disclosure["selected_count"] == 1
    assert disclosure["non_selected_count"] == 2
    assert disclosure["min_age"] == 36
    assert disclosure["max_age"] == 54
    assert disclosure["consideration_days"] == 21
    assert disclosure["snapshot_selected_count"] == 1
    assert disclosure["snapshot_pool_count"] == 1
    assert disclosure["status"] == "ATTACHED"

    bands = disclosure["age_bands"]
    assert_age_bands_sorted(bands)
    assert len(bands) == 3
    assert bands[0]["age"] == 36
    assert bands[0]["selected_count"] == 0
    assert bands[0]["non_selected_count"] == 1
    assert bands[1]["age"] == 48
    assert bands[1]["selected_count"] == 1
    assert bands[1]["non_selected_count"] == 0
    assert bands[2]["age"] == 54
    assert bands[2]["selected_count"] == 0
    assert bands[2]["non_selected_count"] == 1

    assert read_plan(plan["id"])["owbpa_required"] is True


def test_consideration_window_is_group_length_for_the_protected_and_short_below_forty(
    api,
):
    """PRD 3.9: "When the employee's `age_at_separation` is 40 or more,
    `consideration_days_applied` is 45 if the owning plan's `selected_count` is
    at least 2 at that moment, and 21 otherwise. When the employee is under 40
    the OWBPA does not apply and `consideration_days_applied` is 14. The
    comparison against 40 is inclusive, so an employee who turns exactly 40 on
    their separation date is protected. `consideration_deadline_utc` is
    `issued_utc` advanced by `consideration_days_applied` whole days."
    PRD 3.6: "`owbpa_consideration_days` is 45 whenever the plan's
    `selected_count` is at least 2, and 21 otherwise — the statute's
    group-programme window versus its individual window — and it is applied only
    to offers made to employees aged 40 or over."

    Design: Corner/calculations/consideration_window_is_45_days_for_group_and_14_days_under_forty
    """
    scn = setup_offer_ready_scenario(
        people=(ALICE, BEN, CARLA),
        select_indexes=(0, 1, 2),
        propose_only_indexes=(),
        via_batch=True,
        notify_indexes=(0, 1),
        justification="Whole team eliminated.",
    )
    assert scn["plan"]["owbpa_consideration_days"] == 45

    alice_offer = price_offer(scn["selection_by_index"][0]["id"], "STANDARD")
    ben_offer = price_offer(scn["selection_by_index"][1]["id"], "STANDARD")

    issued_alice = issue_offer(alice_offer["id"])
    assert issued_alice["consideration_days_applied"] == 45
    assert issued_alice["consideration_deadline_utc"] == "2026-09-15T00:00:00.000Z"

    issued_ben = issue_offer(ben_offer["id"])
    assert issued_ben["consideration_days_applied"] == 14
    assert issued_ben["consideration_deadline_utc"] == "2026-08-15T00:00:00.000Z"

    assert read_employee(scn["employees"][0]["id"])["age_at_separation"] == 48
    assert read_employee(scn["employees"][1]["id"])["age_at_separation"] == 36
    assert issued_alice["total_separation_cost_cents"] == 3553428
    assert issued_ben["total_separation_cost_cents"] == 1255500

    plan = read_plan(scn["plan"]["id"])
    assert plan["severance_reserve_cents"] == 4808928
    assert plan["owbpa_required"] is True


def test_offer_against_a_stale_disclosure_is_refused_on_staleness(api):
    """PRD 3.6: "Whenever a decide or a rescind moves the plan's `selected_count`
    or `pool_count` away from what a disclosure recorded, that disclosure moves
    `ATTACHED → STALE` and its `version` increments by 1 — the paperwork no
    longer describes the population it claims to describe."
    PRD 3.8: "and that disclosure must actually be `ATTACHED`, its
    `snapshot_selected_count` and `snapshot_pool_count` still matching the plan's
    current `selected_count` and `pool_count`, failing which
    `ERR_OWBPA_DISCLOSURE_STALE`. The distinction matters: a plan with a merely
    stale disclosure fails on staleness, not on absence."

    Design: Corner/errors/error_owbpa_disclosure_stale_after_the_selection_set_moves
    """
    _site, employees = setup_site_with_roster((ALICE, CARLA), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [employees[0]["id"], employees[1]["id"]])
    s_alice, s_carla = batch["selection_ids"]

    decide(s_alice, "SELECT")
    first_analysis = run_analysis(plan["id"], "IMPACT_RATIO")
    clear_analysis(first_analysis["id"], "First pass.")
    disclosure = generate_disclosure(plan["id"])
    assert disclosure["snapshot_selected_count"] == 1

    decide(s_carla, "SELECT")
    second_analysis = run_analysis(plan["id"], "IMPACT_RATIO")
    clear_analysis(second_analysis["id"], "Second pass covering both selections.")
    submit_for_review(plan["id"])
    render_legal_decision(plan["id"], "APPROVE")
    deliver_notice(s_alice, "MANAGER_SCRIPT_STANDARD")

    selection_version = read_selection(s_alice)["version"]
    response = api.create_severance_offer(
        {
            "selection_id": s_alice,
            "variant": "STANDARD",
            "expected_selection_version": selection_version,
        },
        BENEFITS,
    )
    validate_error(response, ApiErrorId.ERR_OWBPA_DISCLOSURE_STALE.value)
    assert response.status_code == 422

    assert read_disclosure(disclosure["id"])["status"] == "STALE"
    from test_helpers import read_analysis

    assert read_analysis(second_analysis["id"])["status"] == "CLEARED"
    assert read_plan(plan["id"])["selected_count"] == 2

    from test_helpers import list_offers

    assert list_offers(plan_id=plan["id"]) == []
