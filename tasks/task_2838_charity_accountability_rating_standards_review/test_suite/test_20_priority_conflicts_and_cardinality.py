"""Segregation of duties against lower-ranked faults, panel composition, and the
two at-most-one constraints across a full appeal-and-correction lap."""
from test_helpers import (
    ALT_PANELIST_USER_IDS,
    REVIEWER_USER_ID,
    assert_instant,
    assign_panel,
    assign_panel_payload,
    claim_correction,
    create_appeal_payload,
    create_governance_profile_payload,
    decide_appeal,
    decide_correction,
    file_appeal,
    file_correction,
    make_admin_headers,
    make_reviewer_headers,
    open_org_review,
    publish_payload,
    read_appeal,
    read_cycle,
    score_cycle,
    set_clock,
    setup_cycle_in_org_review,
    setup_filed_appeal,
    setup_scored_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

PANEL_A, PANEL_B, PANEL_C = ALT_PANELIST_USER_IDS


def test_the_duties_check_answers_first_even_though_the_call_is_doubly_invalid(
    api, admin_headers
):
    """Each duties violation is paired with a lower-ranked fault, and the follow-up call
    proves that second fault was real and merely suppressed.

    PRD §2.8: "10. **Segregation of duties.** The acting `X-User-ID` differs from the user who performed the conflicting earlier step: a publishing reviewer may not be the cycle's `assigned_analyst_user_id`, and the `MethodologyAdmin` who seats an appeal panel may not be that same analyst either. Violations return `ERR_SEGREGATION_OF_DUTIES` (403) on the two endpoints this guards: `POST /rating-cycles/{rating_cycle_id}/publish` and `POST /appeals/{appeal_id}/assign-panel`."

    PRD §2.8: "32. **Publishability.** A cycle is published only when the logical clock is at or after `correction_deadline_at`, no correction of the cycle is `SUBMITTED` or `UNDER_ANALYST_REVIEW`, and no appeal of the cycle is `FILED` or `PANEL_ASSIGNED`. Otherwise `ERR_CYCLE_NOT_PUBLISHABLE` (409), on `POST /rating-cycles/{rating_cycle_id}/publish`."

    PRD §2.8: "27. **Panel composition.** `panel_member_user_ids` holds exactly three distinct identifiers, none of them equal to the cycle's `assigned_analyst_user_id` or its `publishing_reviewer_user_id`, else `ERR_PANEL_COMPOSITION_INVALID` (422), on `POST /appeals/{appeal_id}/assign-panel`."

    Design: Corner/validations/segregation_of_duties_outranks_both_the_publishability_and_the_panel_checks
    """
    scenario = setup_cycle_in_org_review()
    cycle = scenario["cycle"]
    analyst_user_id = scenario["analyst_user_id"]
    assert_instant(
        cycle["correction_deadline_at"], "2026-09-22T00:00:00Z", "correction_deadline_at"
    )

    validate_error(
        api.publish_rating_cycle(
            cycle["id"],
            publish_payload("self-clearing my own cycle"),
            make_reviewer_headers(analyst_user_id),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    validate_error(
        api.publish_rating_cycle(
            cycle["id"], publish_payload("clearing early"), scenario["reviewer_headers"]
        ),
        "ERR_CYCLE_NOT_PUBLISHABLE",
        409,
    )

    correction = file_correction(cycle["id"], scenario["org_rep_headers"])
    claim_correction(correction["id"], headers=scenario["analyst_headers"])
    decide_correction(correction["id"], "REJECT", headers=scenario["analyst_headers"])
    appeal = file_appeal(
        cycle["id"], correction["id"], scenario["org_rep_headers"]
    )

    validate_error(
        api.assign_appeal_panel(
            appeal["id"],
            assign_panel_payload([PANEL_A, PANEL_B]),
            make_admin_headers(analyst_user_id),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    validate_error(
        api.assign_appeal_panel(
            appeal["id"], assign_panel_payload([PANEL_A, PANEL_B]), admin_headers
        ),
        "ERR_PANEL_COMPOSITION_INVALID",
        422,
    )

    after_appeal = read_appeal(appeal["id"], admin_headers)
    assert after_appeal["status"] == "FILED"
    assert after_appeal["version"] == 1
    assert after_appeal["panel_member_user_ids"] == []

    after_cycle = read_cycle(cycle["id"], scenario["analyst_headers"])
    assert after_cycle["status"] == "APPEAL_OPEN"
    assert after_cycle["published_at"] is None
    assert after_cycle["publishing_reviewer_user_id"] is None


def test_a_seat_is_illegal_only_relative_to_the_cycles_own_stored_role_holders(
    api, admin_headers
):
    """Four malformed panels are refused, and then a panel containing reviewer-1 is
    seated, because the cycle's publishing_reviewer_user_id is still null.

    PRD §3.7: "The supplied `panel_member_user_ids` must hold exactly three distinct identifiers, none of them the cycle's `assigned_analyst_user_id` and none of them its `publishing_reviewer_user_id`, else `ERR_PANEL_COMPOSITION_INVALID`; and the seating admin may not themselves be that analyst, else `ERR_SEGREGATION_OF_DUTIES`."

    PRD §3.7: "The appeal moves `FILED` → `PANEL_ASSIGNED`, stores the panel and advances its `version` counter by one."

    Design: Corner/validations/panel_composition_is_validated_against_the_cycles_own_role_holders
    """
    scenario = setup_filed_appeal()
    appeal = scenario["appeal"]
    cycle = scenario["cycle"]
    analyst_user_id = scenario["analyst_user_id"]
    assert cycle["publishing_reviewer_user_id"] is None

    for panel in (
        [PANEL_A, PANEL_B],
        [PANEL_A, PANEL_B, PANEL_C, "panel-d"],
        [PANEL_A, PANEL_B, PANEL_A],
        [PANEL_A, analyst_user_id, PANEL_C],
    ):
        validate_error(
            api.assign_appeal_panel(
                appeal["id"], assign_panel_payload(panel), admin_headers
            ),
            "ERR_PANEL_COMPOSITION_INVALID",
            422,
        )

    seated = assign_panel(
        appeal["id"], [PANEL_A, REVIEWER_USER_ID, PANEL_C], headers=admin_headers
    )
    assert seated["status"] == "PANEL_ASSIGNED"
    assert seated["panel_member_user_ids"] == [PANEL_A, REVIEWER_USER_ID, PANEL_C]
    assert seated["version"] == 2

    after_cycle = read_cycle(cycle["id"], scenario["analyst_headers"])
    assert after_cycle["status"] == "APPEAL_OPEN"
    assert after_cycle["version"] == cycle["version"]


def test_the_two_at_most_one_rules_hold_across_a_granted_appeal_and_a_second_lap(
    api, admin_headers
):
    """A second governance disclosure is refused outright, and on the lap the grant opens
    the three refused appeal filings answer with three different codes by priority alone.

    PRD §2.8: "22. **One governance profile per cycle.** At most one `GovernanceProfile` exists per rating cycle, else `ERR_DUPLICATE_GOVERNANCE_PROFILE` (409), on `POST /governance-profiles`."

    PRD §3.7: "Four conditions gate the filing: the cycle must be in `ORG_REVIEW`, else `ERR_CYCLE_STATE_INVALID`; the referenced correction's `status` must be `REJECTED`, else `ERR_CORRECTION_NOT_REJECTED`; the logical clock must be strictly before the cycle's `appeal_deadline_at`, else `ERR_APPEAL_WINDOW_CLOSED`; and the cycle must not already hold an appeal in `FILED`, `PANEL_ASSIGNED`, `GRANTED` or `DENIED`, else `ERR_APPEAL_ALREADY_FILED`."

    PRD §3.7: "Only a `DISMISSED` appeal leaves room for another."

    PRD §3.7: "The new request lands with `status` `SUBMITTED`, its `submitted_by_org_user_id` taken from the caller's `X-User-ID`, its `round_number` set to the cycle's `correction_round` plus one, and `claimed_by_user_id`, `decided_by_user_id`, `decision_note` and `decided_at` all null."

    Design: Corner/validations/the_at_most_one_constraints_survive_a_full_appeal_and_correction_lap
    """
    scenario = setup_scored_cycle(score=False)
    cycle_id = scenario["cycle"]["id"]
    analyst_headers = scenario["analyst_headers"]
    org_rep_headers = scenario["org_rep_headers"]
    profile = scenario["governance_profile"]

    validate_error(
        api.create_governance_profile(
            create_governance_profile_payload(
                cycle_id,
                board_member_count=9,
                independent_board_member_count=6,
                board_meetings_last_year=6,
                ceo_compensation_reviewed=True,
                outcome_measures_count=4,
            ),
            analyst_headers,
        ),
        "ERR_DUPLICATE_GOVERNANCE_PROFILE",
        409,
    )
    profiles, profile_meta = validate_paginated(
        api.list_governance_profiles(analyst_headers, params={"rating_cycle_id": cycle_id})
    )
    assert profile_meta["total_count"] == 1
    assert profiles[0]["id"] == profile["id"]
    assert profiles[0]["board_member_count"] == 7

    score_cycle(cycle_id, headers=analyst_headers)
    open_org_review(cycle_id, headers=analyst_headers)
    first = file_correction(cycle_id, org_rep_headers)
    assert first["round_number"] == 1
    claim_correction(first["id"], headers=analyst_headers)
    decide_correction(first["id"], "REJECT", headers=analyst_headers)
    appeal = file_appeal(cycle_id, first["id"], org_rep_headers)
    assign_panel(appeal["id"], ALT_PANELIST_USER_IDS, headers=admin_headers)
    granted = decide_appeal(
        appeal["id"],
        "GRANT",
        panelist_user_id=PANEL_A,
        decision_note="the restated schedule is authoritative",
    )
    assert granted["status"] == "GRANTED"
    rewound = read_cycle(cycle_id, analyst_headers)
    assert rewound["status"] == "DATA_COLLECTION"
    assert rewound["correction_round"] == 1

    score_cycle(cycle_id, headers=analyst_headers)
    reopened = open_org_review(cycle_id, headers=analyst_headers)
    assert reopened["status"] == "ORG_REVIEW"
    assert reopened["correction_round"] == 1

    validate_error(
        api.create_appeal(
            create_appeal_payload(
                cycle_id, first["id"], grounds="the granted correction did not go far enough"
            ),
            org_rep_headers,
        ),
        "ERR_CORRECTION_NOT_REJECTED",
        409,
    )

    second = file_correction(
        cycle_id,
        org_rep_headers,
        target_field_name="fundraising_expense_cents",
        proposed_value="900000",
        narrative="Three hundred thousand of the appeal cost was a joint educational mailing",
    )
    assert second["round_number"] == 2
    claim_correction(second["id"], headers=analyst_headers)
    rejected = decide_correction(
        second["id"],
        "REJECT",
        headers=analyst_headers,
        decision_note="the mailing does not meet the joint cost criteria",
    )
    assert rejected["status"] == "REJECTED"

    validate_error(
        api.create_appeal(
            create_appeal_payload(
                cycle_id, second["id"], grounds="the joint cost criteria were misapplied"
            ),
            org_rep_headers,
        ),
        "ERR_APPEAL_ALREADY_FILED",
        409,
    )

    in_review = read_cycle(cycle_id, analyst_headers)
    assert in_review["status"] == "ORG_REVIEW"
    assert_instant(
        in_review["appeal_deadline_at"], "2026-09-15T00:00:00Z", "appeal_deadline_at"
    )
    set_clock(in_review["appeal_deadline_at"])
    validate_error(
        api.create_appeal(
            create_appeal_payload(
                cycle_id, second["id"], grounds="the joint cost criteria were misapplied"
            ),
            org_rep_headers,
        ),
        "ERR_APPEAL_WINDOW_CLOSED",
        409,
    )

    appeals, appeal_meta = validate_paginated(
        api.list_appeals(admin_headers, params={"rating_cycle_id": cycle_id})
    )
    assert appeal_meta["total_count"] == 1
    assert appeals[0]["id"] == appeal["id"]
    assert appeals[0]["status"] == "GRANTED"

    final = validate_success(api.get_rating_cycle(cycle_id, analyst_headers))
    assert final["status"] == "ORG_REVIEW"
    assert final["correction_round"] == 1
