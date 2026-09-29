"""Optimistic concurrency, the per-write version counter and inclusive thresholds.

Both stale-version guards sit near the top of the ladder, so each case also shows
that the refused write left no trace at all — no row, no balance movement, no
version bump — and that replaying an accepted expected value is stale in turn.
"""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    SPECIALIST,
    WORKER,
    ApiErrorId,
    assert_reunification_case,
    assert_safety_screening,
    assert_tlp_placement,
    assert_youth,
    fetch_placement,
    fetch_youth,
    intake_youth,
    log_outreach_contact,
    reunification_case_payload,
    safety_screening_payload,
    savings_entry_payload,
    setup_tlp_placement,
    validate_error,
    validate_paginated,
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
MONTHLY_INCOME_CENTS = 90000


# ─── Instance: the youth OCC guard on opening a case ───

YAEL = {
    "legal_first_name": "Yael",
    "legal_last_name": "Duarte",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
DUARTE_HOUSEHOLD = "Duarte household"


def test_one_version_behind_refuses_the_case_open_and_the_accepted_value_goes_stale(api):
    """PRD §2.9: "Opening a reunification case — `POST /ryhs/reunification-cases` —
    requires `expected_youth_version`, carrying the client's last observed `version` of
    the target `Youth`."
    PRD §2.9: "If that value does not equal the youth's current `version`, the request is
    rejected with `ERR_STALE_YOUTH_VERSION` (HTTP 412)."
    PRD §2.10: "7. `expected_youth_version` equals the youth's current `version` —
    `ERR_STALE_YOUTH_VERSION`, 412, on opening a reunification case."
    PRD §3.6: "Opening a case always increments the youth's `version` by one."
    PRD §3.6: "A new case opens in `status` `OPENED` with `opened_at` stamped from the
    clock, `mediation_round` at 0, `max_mediation_rounds` fixed by the server at 3,
    `safety_assessment_result` null, `aftercare_plan_due_at` null,
    `aftercare_contacts_completed` at 0 and `closed_at` null."

    Design: Corner/complexity_layers/stale_youth_version_on_case_open_is_rejected
    """
    youth = intake_youth(**dict(YAEL))
    observed_version = youth["version"]
    assert observed_version == 1, (
        f"a freshly intaken youth stands at version 1, got {observed_version}"
    )

    stale = api.create_reunification_case(
        reunification_case_payload(
            youth["id"], observed_version - 1, guardian_household_label=DUARTE_HOUSEHOLD
        ),
        SPECIALIST,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_YOUTH_VERSION.value, 412)
    _rows, meta = validate_paginated(
        api.list_youth_reunification_cases(youth["id"], ADMIN)
    )
    assert meta["total_count"] == 0, (
        f"the refused open created no case, got {meta['total_count']}"
    )
    untouched = fetch_youth(youth["id"])
    assert_youth(untouched)
    assert untouched["version"] == observed_version, (
        f"the refusal moved no version, got {untouched['version']}"
    )

    case = validate_success(
        api.create_reunification_case(
            reunification_case_payload(
                youth["id"], observed_version, guardian_household_label=DUARTE_HOUSEHOLD
            ),
            SPECIALIST,
        ),
        201,
    )
    assert_reunification_case(case)
    assert case["status"] == "OPENED", (
        f"the observed version is accepted, got {case['status']}"
    )
    assert case["mediation_round"] == 0, (
        f"a fresh case has run no round yet, got {case['mediation_round']}"
    )
    bumped = fetch_youth(youth["id"])
    assert bumped["version"] == observed_version + 1, (
        "opening a case moves the youth's version by exactly one, got "
        f"{bumped['version']}"
    )

    replayed = api.create_reunification_case(
        reunification_case_payload(
            youth["id"], observed_version, guardian_household_label=DUARTE_HOUSEHOLD
        ),
        SPECIALIST,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_YOUTH_VERSION.value, 412)
    _rows, after = validate_paginated(
        api.list_youth_reunification_cases(youth["id"], ADMIN)
    )
    assert after["total_count"] == 1, (
        f"the replay superseded nothing, got {after['total_count']}"
    )


# ─── Instance: the placement OCC guard on the savings ledger ───

ZENO = {
    "legal_first_name": "Zeno",
    "legal_last_name": "Abarca",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
DEPOSIT_CENTS = 1000


def test_one_version_behind_refuses_an_affordable_deposit_and_the_replay_is_stale(api):
    """PRD §2.9: "Posting a savings entry — `POST /ryhs/tlp-placements/{id}/savings-entries`
    — requires `expected_placement_version`, carrying the client's last observed `version`
    of the target `TlpPlacement`."
    PRD §2.9: "If that value does not equal the placement's current `version`, the request
    is rejected with `ERR_STALE_PLACEMENT_VERSION` (HTTP 412)."
    PRD §2.10: "8. `expected_placement_version` equals the placement's current `version` —
    `ERR_STALE_PLACEMENT_VERSION`, 412, on posting a savings entry."

    Design: Corner/complexity_layers/stale_placement_version_on_a_savings_entry_is_rejected
    """
    setup = setup_tlp_placement(
        MONTHLY_INCOME_CENTS,
        shelter_program_overrides=dict(RIVERSIDE),
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(ZENO),
    )
    placement = setup["placement"]
    observed_version = placement["version"]
    assert_tlp_placement(placement)
    assert placement["savings_balance_cents"] == 0, (
        f"the ledger opens empty, got {placement['savings_balance_cents']}"
    )

    stale = api.create_savings_entry(
        placement["id"],
        savings_entry_payload("DEPOSIT", DEPOSIT_CENTS, observed_version - 1, "stale write"),
        COORDINATOR,
    )

    validate_error(stale, ApiErrorId.ERR_STALE_PLACEMENT_VERSION.value, 412)
    unmoved = fetch_placement(placement["id"])
    assert unmoved["savings_balance_cents"] == 0, (
        f"an affordable deposit still moves no balance, got {unmoved['savings_balance_cents']}"
    )
    assert unmoved["version"] == observed_version, (
        f"the refusal moved no version, got {unmoved['version']}"
    )
    _rows, meta = validate_paginated(api.list_savings_entries(placement["id"], COORDINATOR))
    assert meta["total_count"] == 0, (
        f"the refused entry was never written, got {meta['total_count']}"
    )

    entry = validate_success(
        api.create_savings_entry(
            placement["id"],
            savings_entry_payload("DEPOSIT", DEPOSIT_CENTS, observed_version, "fresh write"),
            COORDINATOR,
        ),
        201,
    )
    assert entry["match_component_cents"] == 250, (
        "a 1000-cent deposit matched at 2500 basis points earns 250, got "
        f"{entry['match_component_cents']}"
    )
    assert entry["balance_after_cents"] == 1250, (
        f"the deposit and its match make 1250, got {entry['balance_after_cents']}"
    )

    replayed = api.create_savings_entry(
        placement["id"],
        savings_entry_payload("DEPOSIT", DEPOSIT_CENTS, observed_version, "replayed write"),
        COORDINATOR,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_PLACEMENT_VERSION.value, 412)
    _rows, after = validate_paginated(api.list_savings_entries(placement["id"], COORDINATOR))
    assert after["total_count"] == 1, (
        f"the repeatable deposit was not written twice, got {after['total_count']}"
    )
    settled = fetch_placement(placement["id"])
    assert settled["savings_balance_cents"] == 1250, (
        f"the balance reflects exactly one accepted entry, got {settled['savings_balance_cents']}"
    )


# ─── Instance: version is a per-write counter, not a per-field one ───

INES = {
    "legal_first_name": "Ines",
    "legal_last_name": "Vargas",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}


def test_one_contact_that_changes_four_fields_moves_the_version_by_one(api):
    """PRD §3.1: "Either way the same set of consequences fires:
    `engagement_contact_count` rises by one, `basic_needs_provision_count` rises by the
    number of items in the `basic_needs_provided` list of this encounter, the youth's
    standing trafficking risk is recomputed and re-tiered against the current clock, the
    youth's `risk_posture` is recomputed, `governance_vote_eligible` is recomputed, and the
    youth's `version` increments by one."
    PRD §3.1: "A first encounter moves the youth `PROSPECT → ENGAGED`; every later
    encounter is a legitimate self-loop `ENGAGED → ENGAGED`, since street engagement is by
    nature repeated."
    PRD §3.1: "The server stamps `contacted_at` with the logical-clock instant of the
    encounter and `worker_user_id` with the acting worker's identifier; an outreach contact
    is an immutable event record and carries no version."

    Design: Corner/complexity_layers/youth_version_increments_once_per_mutating_write
    """
    youth = intake_youth(**dict(INES))
    assert youth["version"] == 1, (
        f"a created youth opens at version 1, got {youth['version']}"
    )
    assert youth["status"] == "PROSPECT", (
        f"a youth with no encounter is a prospect, got {youth['status']}"
    )

    read_twice = validate_success(api.get_youth(youth["id"], WORKER))
    assert read_twice["version"] == 1, (
        f"reading the row moves nothing, got {read_twice['version']}"
    )

    log_outreach_contact(
        youth["id"],
        engagement_stage="FIRST_CONTACT",
        basic_needs_provided=["FOOD", "HYGIENE_KIT"],
        indicator_flags=[],
    )
    engaged = fetch_youth(youth["id"])
    assert engaged["version"] == 2, (
        "one encounter that recomputes four derived fields still moves the version by "
        f"one, got {engaged['version']}"
    )
    assert engaged["status"] == "ENGAGED", (
        f"the first encounter engages the youth, got {engaged['status']}"
    )
    assert engaged["engagement_contact_count"] == 1, (
        f"one encounter is counted, got {engaged['engagement_contact_count']}"
    )
    assert engaged["basic_needs_provision_count"] == 2, (
        f"two items were handed over, got {engaged['basic_needs_provision_count']}"
    )

    log_outreach_contact(
        youth["id"],
        engagement_stage="RAPPORT_BUILDING",
        basic_needs_provided=["CLOTHING"],
        indicator_flags=[],
    )
    again = fetch_youth(youth["id"])
    assert again["version"] == 3, (
        f"the second encounter moves the version by one more, got {again['version']}"
    )
    assert again["status"] == "ENGAGED", (
        f"a later encounter is a self-loop rather than a new status, got {again['status']}"
    )
    assert again["engagement_contact_count"] == 2, (
        f"both encounters are counted, got {again['engagement_contact_count']}"
    )
    assert again["basic_needs_provision_count"] == 3, (
        "the provision count accumulates across encounters, got "
        f"{again['basic_needs_provision_count']}"
    )


# ─── Instance: both tier thresholds are inclusive ───

BEA = {
    "legal_first_name": "Bea",
    "legal_last_name": "Torres",
    "date_of_birth": DOB_AGE_16,
    "unaccompanied": True,
}
CATO = {
    "legal_first_name": "Cato",
    "legal_last_name": "Torres",
    "date_of_birth": "2010-04-15",
    "unaccompanied": True,
}
DELIA = {
    "legal_first_name": "Delia",
    "legal_last_name": "Torres",
    "date_of_birth": "2010-05-15",
    "unaccompanied": True,
}


def test_a_screening_score_of_exactly_thirty_and_exactly_sixty_tiers_upward(api):
    """PRD §3.2: "The screening's own `score` is the **undecayed snapshot** of exactly one
    indicator set: the sum of the weights of the distinct codes supplied on this screening,
    capped at 100, with no decay of any kind applied and no other screening or contact
    participating."
    PRD §3.2: "The screening's `tier` is read off the same two thresholds as the youth's
    tier — `CRITICAL` at 60 or more, `ELEVATED` at 30 or more, `LOW` below 30 — but it is
    read off the screening's own `score` rather than off the youth's history figure."
    PRD §3.1: "Each indicator code carries a weight: `THIRD_PARTY_CONTROL` is worth 30
    points, `QUOTA_DEBT` 25, `COMMERCIAL_SEX` 40, `DOCUMENT_WITHHELD` 20,
    `RECRUITER_PRESENT` 15 and `CURFEW_ENFORCED` 10."
    PRD §3.1: "`trafficking_risk_tier` follows from that score by two thresholds: the tier
    is `CRITICAL` at a score of 60 or more, `ELEVATED` at a score of 30 or more, and `LOW`
    below 30."
    PRD §3.2: "A screening in `SUBMITTED` never freezes a youth on its own; the youth's
    `risk_posture` is recomputed on submission, but only a disposition can drive it to
    `FROZEN`."

    Design: Corner/complexity_layers/trafficking_tier_boundaries_sit_at_exactly_thirty_and_sixty
    """
    below = intake_youth(**dict(BEA))
    at_thirty = intake_youth(**dict(CATO))
    at_sixty = intake_youth(**dict(DELIA))

    low = validate_success(
        api.create_safety_screening(
            below["id"], safety_screening_payload(indicator_codes=["QUOTA_DEBT"]), WORKER
        ),
        201,
    )
    elevated = validate_success(
        api.create_safety_screening(
            at_thirty["id"],
            safety_screening_payload(indicator_codes=["DOCUMENT_WITHHELD", "CURFEW_ENFORCED"]),
            WORKER,
        ),
        201,
    )
    critical = validate_success(
        api.create_safety_screening(
            at_sixty["id"],
            safety_screening_payload(indicator_codes=["COMMERCIAL_SEX", "DOCUMENT_WITHHELD"]),
            WORKER,
        ),
        201,
    )

    for screening in (low, elevated, critical):
        assert_safety_screening(screening)
        assert screening["status"] == "SUBMITTED", (
            f"an undispositioned screening stands SUBMITTED, got {screening['status']}"
        )
    assert low["score"] == 25, (
        f"QUOTA_DEBT alone is 25 points, got {low['score']}"
    )
    assert low["tier"] == "LOW", (
        f"25 sits below the elevated threshold, got {low['tier']}"
    )
    assert elevated["score"] == 30, (
        "DOCUMENT_WITHHELD and CURFEW_ENFORCED sum to precisely 30, got "
        f"{elevated['score']}"
    )
    assert elevated["tier"] == "ELEVATED", (
        f"exactly 30 is already ELEVATED, got {elevated['tier']}"
    )
    assert critical["score"] == 60, (
        f"COMMERCIAL_SEX and DOCUMENT_WITHHELD sum to precisely 60, got {critical['score']}"
    )
    assert critical["tier"] == "CRITICAL", (
        f"exactly 60 is already CRITICAL, got {critical['tier']}"
    )

    for youth in (below, at_thirty, at_sixty):
        standing = fetch_youth(youth["id"])
        assert standing["trafficking_risk_score"] == 0, (
            "the youth figure is fed by outreach history alone, and none of these youths "
            f"has a contact, got {standing['trafficking_risk_score']}"
        )
        assert standing["trafficking_risk_tier"] == "LOW", (
            f"a score of zero tiers as LOW, got {standing['trafficking_risk_tier']}"
        )
        assert standing["risk_posture"] != "FROZEN", (
            "only a disposition can freeze a youth, got "
            f"{standing['risk_posture']}"
        )
