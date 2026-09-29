"""Entity shape, declared defaults and the identity of a freshly written row.

Every case here keeps a second, already-stored row of the same kind in the
database, so the assertion is about the row under test rather than about an
empty collection.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    COORDINATOR,
    USER_IDS,
    WORKER,
    ApiErrorId,
    assert_immutable_event_fields,
    assert_instant_equals,
    assert_outreach_contact,
    assert_program_counters,
    assert_savings_ledger_entry,
    assert_shelter_program,
    assert_youth,
    clear_screening,
    fetch_placement,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    log_outreach_contact,
    post_savings_entry,
    request_admission,
    savings_entries_of,
    setup_placement_with_deposits,
    submit_screening,
    transitional_living_payload,
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
    "max_stay_nights": 21,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
UNKNOWN_ADMISSION_ID = "11111111-1111-1111-1111-111111111111"
UNKNOWN_YOUTH_ID = "22222222-2222-2222-2222-222222222222"
UNKNOWN_PROGRAM_ID = "33333333-3333-3333-3333-333333333333"


def test_program_creation_stamps_its_own_derived_defaults(api):
    """PRD §3.3: "It declares `licensed_bed_capacity`, the federally licensed bed
    count, which must be at least 1 and which is a hard ceiling on occupancy."
    PRD §3.3: "A newly licensed program starts with `occupied_beds`,
    `waitlisted_count` and `overdue_notification_count` all at 0, `utilization_bp`
    at 0, and `posture` computed as `OPEN`."
    PRD §2.4: "`version` is an integer that starts at 1 when the record is created
    and increments by exactly 1 on every mutation of that record; a mutation of a
    derived field — an occupied-bed counter, a recomputed posture, a re-decayed risk
    score — is a mutation like any other and increments `version` accordingly."

    Design: Corner/entities/shelter_program_creation_stamps_derived_defaults
    """
    first = license_emergency_shelter(**dict(RIVERSIDE))

    response = api.create_shelter_program(
        transitional_living_payload(**dict(NORTHSIDE)), ADMIN
    )
    program = validate_success(response, 201)

    assert_shelter_program(program)
    assert program["name"] == "Northside Transitional Living", (
        f"the supplied name is echoed back, got {program['name']}"
    )
    assert program["program_type"] == "TRANSITIONAL_LIVING", (
        f"the declared program type is fixed for all time, got {program['program_type']}"
    )
    assert program["licensed_bed_capacity"] == 3, (
        f"the licensed bed count is stored as supplied, got {program['licensed_bed_capacity']}"
    )
    assert program["max_placement_days"] == 540, (
        f"the transitional-living duration ceiling is stored, got {program['max_placement_days']}"
    )
    assert program["savings_match_rate_bp"] == 2500, (
        f"the match rate is stored in basis points, got {program['savings_match_rate_bp']}"
    )
    assert program["occupied_beds"] == 0, (
        f"a fresh licence occupies no beds, got {program['occupied_beds']}"
    )
    assert program["waitlisted_count"] == 0, (
        f"a fresh licence has nobody waiting, got {program['waitlisted_count']}"
    )
    assert program["overdue_notification_count"] == 0, (
        f"a fresh licence owes no obligation, got {program['overdue_notification_count']}"
    )
    assert program["utilization_bp"] == 0, (
        f"zero of three beds is zero basis points, got {program['utilization_bp']}"
    )
    assert program["posture"] == "OPEN", (
        f"a fresh licence computes to OPEN, got {program['posture']}"
    )
    assert program["version"] == 1, (
        f"a freshly created record stands at version 1, got {program['version']}"
    )
    assert program["id"] != first["id"], (
        "each licence is addressed by its own server-minted id, got the same id twice"
    )


def test_youth_retrieval_returns_the_stored_row_with_derived_age(api):
    """PRD §3.1: "The freshly created youth starts in `status` `PROSPECT`, with
    `risk_posture` `OPEN`, `trafficking_risk_score` 0, `trafficking_risk_tier` `LOW`,
    `engagement_contact_count` 0, `basic_needs_provision_count` 0,
    `cumulative_shelter_nights` 0, `lifetime_savings_deposited_cents` 0,
    `governance_vote_eligible` false, and `version` 1."
    PRD §2.5: "Because the comparison is inclusive, a youth turns the new age on the
    birthday itself rather than the day after, and the result is always floored to
    whole years."

    Design: Corner/entities/youth_retrieval_returns_the_stored_row
    """
    created = intake_youth(
        legal_first_name="Mara", legal_last_name="Cole",
        date_of_birth="2010-03-15", unaccompanied=True,
    )

    youth = validate_success(api.get_youth(created["id"], CASE_MANAGER))

    assert_youth(youth)
    assert youth["legal_first_name"] == "Mara", (
        f"the stored given name is returned, got {youth['legal_first_name']}"
    )
    assert youth["date_of_birth"] == "2010-03-15", (
        f"the birth date is a bare calendar date, got {youth['date_of_birth']}"
    )
    assert youth["age_years"] == 16, (
        "a youth born 2010-03-15 has already had a birthday by the 2026-08-01 clock, "
        f"so the age is 16, got {youth['age_years']}"
    )
    assert youth["status"] == "PROSPECT", (
        f"a youth met on the street starts as a PROSPECT, got {youth['status']}"
    )
    assert youth["risk_posture"] == "OPEN", (
        f"no screening and no obligation is an OPEN posture, got {youth['risk_posture']}"
    )
    assert youth["trafficking_risk_score"] == 0, (
        f"no encounter has been logged, got {youth['trafficking_risk_score']}"
    )
    assert youth["trafficking_risk_tier"] == "LOW", (
        f"a zero score tiers as LOW, got {youth['trafficking_risk_tier']}"
    )
    assert youth["engagement_contact_count"] == 0, (
        f"no encounter has been logged, got {youth['engagement_contact_count']}"
    )
    assert youth["cumulative_shelter_nights"] == 0, (
        f"the youth has never been sheltered, got {youth['cumulative_shelter_nights']}"
    )
    assert youth["governance_vote_eligible"] is False, (
        f"a prospect holds no residency, got {youth['governance_vote_eligible']}"
    )
    assert youth["version"] == 1, (
        f"the row has not been mutated since intake, got {youth['version']}"
    )


def test_youth_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "Both list-based and paginated responses populate `limit`, `offset`,
    `total_count` and `has_more` inside the `meta` object of the envelope, where
    `total_count` is the number of records matching the filter before the limit and
    offset window is applied, and `has_more` is true exactly when records matching
    the filter remain beyond the returned window."
    PRD §2.3: "Unless a specific endpoint states otherwise, list results are ordered
    by the record's creation timestamp, `created_at`, in ascending order."

    Design: Corner/entities/youth_listing_paginates_with_total_count_and_has_more
    """
    intake_youth(legal_first_name="Uno", legal_last_name="Reyes",
                 date_of_birth="2010-03-15", unaccompanied=True)
    intake_youth(legal_first_name="Dos", legal_last_name="Reyes",
                 date_of_birth="2011-03-15", unaccompanied=True)
    intake_youth(legal_first_name="Tres", legal_last_name="Reyes",
                 date_of_birth="2012-03-15", unaccompanied=False)

    first_rows, first_meta = validate_paginated(
        api.list_youths(CASE_MANAGER, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2, (
        f"a limit of two caps the window at two rows, got {len(first_rows)}"
    )
    assert first_meta["total_count"] == 3, (
        "the total counts every matching row before the window is applied, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        f"a third row remains beyond the window, got {first_meta['has_more']}"
    )

    second_rows, second_meta = validate_paginated(
        api.list_youths(CASE_MANAGER, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, (
        f"only the third row is left to return, got {len(second_rows)}"
    )
    assert second_meta["total_count"] == 3, (
        "the total is independent of the offset window, got "
        f"{second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        f"nothing remains beyond the second window, got {second_meta['has_more']}"
    )

    filtered_rows, filtered_meta = validate_paginated(
        api.list_youths(CASE_MANAGER, {"status": "PROSPECT", "limit": 50, "offset": 0})
    )
    assert filtered_meta["total_count"] == 3, (
        f"all three youths are prospects, got {filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False, (
        f"a window of fifty holds all three rows, got {filtered_meta['has_more']}"
    )
    assert len(filtered_rows) == 3, (
        f"the unpaged window returns all three rows, got {len(filtered_rows)}"
    )

    first_ids = {row["id"] for row in first_rows}
    second_ids = {row["id"] for row in second_rows}
    assert not (first_ids & second_ids), (
        "the two windows are disjoint, got an id on both pages"
    )


def test_admission_get_with_unknown_id_returns_not_found(api):
    """PRD §2.10: "Each resource kind has its own not-found code, so a request
    naming an unknown youth fails with `ERR_YOUTH_NOT_FOUND` before the server ever
    looks at the nested segment."
    PRD §2.10: "Every identifier in the path resolves, left to right — the matching
    not-found code, 404, on every path-templated endpoint."

    Design: Corner/entities/admission_get_with_unknown_id_returns_not_found
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(legal_first_name="Nia", legal_last_name="Okafor",
                         date_of_birth="2010-03-15", unaccompanied=True)
    clear_screening(youth["id"])
    admission = request_admission(youth["id"], program["id"], instant("2026-08-15"))

    response = api.get_admission(UNKNOWN_ADMISSION_ID, CASE_MANAGER)

    error = validate_error(response, ApiErrorId.ERR_ADMISSION_NOT_FOUND.value, 404)
    assert error["message"].strip(), (
        "the error envelope carries a non-empty message, got "
        f"{error['message']!r}"
    )
    stored = validate_success(api.get_admission(admission["id"], CASE_MANAGER))
    assert stored["status"] == "ACTIVE", (
        f"the real admission is untouched by the failed read, got {stored['status']}"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(CASE_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the collection still holds exactly one admission, got {meta['total_count']}"
    )


def test_youth_creation_without_a_birth_date_is_rejected(api):
    """PRD §2.10: "Request-body shape: required fields present, enum members legal,
    integers inside their declared bounds, arrays free of duplicates and drawn from
    their declared code sets, instants parseable as ISO 8601 UTC, and `limit` and
    `offset` inside the pagination bounds — `ERR_INVALID_REQUEST`, 400, on every
    endpoint."
    PRD §3.1: "An `OutreachWorker` who meets a young person creates a **Youth**
    record by supplying `legal_first_name`, `legal_last_name` and `date_of_birth`,
    plus an optional `unaccompanied` flag that declares whether the youth presented
    with no accompanying adult."

    Design: Corner/entities/youth_creation_missing_date_of_birth_returns_invalid_request
    """
    existing = intake_youth(legal_first_name="Existing", legal_last_name="Youth",
                            date_of_birth="2010-03-15", unaccompanied=True)

    response = api.create_youth(
        {"legal_first_name": "NoBirthdate", "legal_last_name": "Case"}, WORKER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(api.list_youths(CASE_MANAGER))
    assert meta["total_count"] == 1, (
        f"the rejected intake wrote no youth row, got {meta['total_count']}"
    )
    stored = fetch_youth(existing["id"])
    assert stored["version"] == 1, (
        f"the existing youth was not mutated, got version {stored['version']}"
    )


def test_unaccompanied_defaults_to_true_only_when_omitted(api):
    """PRD §3.1: "When `unaccompanied` is omitted it defaults to true, on the
    operating assumption that a youth met through street outreach is unaccompanied
    unless the worker says otherwise."

    Design: Corner/entities/youth_unaccompanied_defaults_to_true_when_omitted
    """
    explicit_false = intake_youth(
        legal_first_name="Accompanied", legal_last_name="Youth",
        date_of_birth="2010-03-15", unaccompanied=False,
    )

    response = api.create_youth(
        {"legal_first_name": "Default", "legal_last_name": "Youth",
         "date_of_birth": "2010-03-15"},
        WORKER,
    )
    defaulted = validate_success(response, 201)

    assert defaulted["unaccompanied"] is True, (
        f"an omitted flag defaults to true, got {defaulted['unaccompanied']}"
    )
    assert explicit_false["unaccompanied"] is False, (
        "an explicit false is preserved rather than defaulted, got "
        f"{explicit_false['unaccompanied']}"
    )
    assert defaulted["status"] == "PROSPECT", (
        f"the defaulted youth still starts as a PROSPECT, got {defaulted['status']}"
    )


def test_one_outreach_contact_counts_items_not_contacts(api):
    """PRD §3.1: "`engagement_contact_count` rises by one,
    `basic_needs_provision_count` rises by the number of items in the
    `basic_needs_provided` list of this encounter, the youth's standing trafficking
    risk is recomputed and re-tiered against the current clock, the youth's
    `risk_posture` is recomputed, `governance_vote_eligible` is recomputed, and the
    youth's `version` increments by one."
    PRD §3.1: "The server stamps `contacted_at` with the logical-clock instant of
    the encounter and `worker_user_id` with the acting worker's identifier; an
    outreach contact is an immutable event record and carries no version."

    Design: Corner/entities/outreach_contact_recomputes_youth_engagement_counters
    """
    youth = intake_youth(legal_first_name="Piet", legal_last_name="Nkomo",
                         date_of_birth="2011-01-05", unaccompanied=True)

    response = api.create_outreach_contact(
        youth["id"],
        {"engagement_stage": "FIRST_CONTACT",
         "basic_needs_provided": ["FOOD", "HYGIENE_KIT", "TRANSIT_PASS"],
         "indicator_flags": []},
        WORKER,
    )
    contact = validate_success(response, 201)

    assert_outreach_contact(contact)
    assert_instant_equals(contact["contacted_at"], instant("2026-08-01"),
                          "the encounter's contacted_at")
    assert contact["worker_user_id"] == USER_IDS["OUTREACH_WORKER"], (
        f"the acting worker is stamped onto the encounter, got {contact['worker_user_id']}"
    )

    current = fetch_youth(youth["id"])
    assert current["engagement_contact_count"] == 1, (
        f"one encounter has been logged, got {current['engagement_contact_count']}"
    )
    assert current["basic_needs_provision_count"] == 3, (
        "the needs counter counts handed-over items rather than encounters, got "
        f"{current['basic_needs_provision_count']}"
    )
    assert current["status"] == "ENGAGED", (
        f"the first encounter engages the youth, got {current['status']}"
    )
    assert current["trafficking_risk_score"] == 0, (
        f"the encounter observed no indicator, got {current['trafficking_risk_score']}"
    )
    assert current["governance_vote_eligible"] is False, (
        f"an engaged youth holds no residency yet, got {current['governance_vote_eligible']}"
    )
    assert current["version"] == 2, (
        f"the encounter mutates the youth exactly once, got {current['version']}"
    )


def test_zero_licensed_bed_capacity_is_refused(api):
    """PRD §3.3: "A capacity below 1, or a rate outside the basis-point range, is
    refused as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/shelter_program_creation_with_zero_bed_capacity_returns_invalid_request
    """
    existing = license_emergency_shelter(**dict(RIVERSIDE))

    response = api.create_shelter_program(
        {"name": "Zero Bed Shelter", "program_type": "EMERGENCY_SHELTER",
         "licensed_bed_capacity": 0, "min_age_years": 12, "max_age_years": 17,
         "max_stay_nights": 21, "max_placement_days": 540,
         "savings_match_rate_bp": 2500, "required_savings_rate_bp": 2000},
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(api.list_shelter_programs(ADMIN))
    assert meta["total_count"] == 1, (
        f"the rejected licence wrote no program row, got {meta['total_count']}"
    )
    stored = fetch_program(existing["id"])
    assert stored["licensed_bed_capacity"] == 2, (
        "the valid licence keeps its own capacity, got "
        f"{stored['licensed_bed_capacity']}"
    )


def test_duplicate_indicator_codes_on_a_screening_are_refused(api):
    """PRD §3.2: "Either an `OutreachWorker` or a `ShelterCaseManager` submits a
    **SafetyScreening** against a youth, supplying `indicator_codes` — the same
    six-code vocabulary and the same no-duplicates, may-be-empty rules as the
    outreach indicator list."
    PRD §3.2: "The screening's own `score` is the **undecayed snapshot** of exactly
    one indicator set: the sum of the weights of the distinct codes supplied on this
    screening, capped at 100, with no decay of any kind applied and no other
    screening or contact participating."

    Design: Corner/entities/safety_screening_with_duplicate_indicator_codes_returns_invalid_request
    """
    youth = intake_youth(legal_first_name="Dana", legal_last_name="Iqbal",
                         date_of_birth="2010-03-15", unaccompanied=True)
    accepted = submit_screening(youth["id"], ["CURFEW_ENFORCED"])

    response = api.create_safety_screening(
        youth["id"], {"indicator_codes": ["CURFEW_ENFORCED", "CURFEW_ENFORCED"]}, WORKER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert accepted["score"] == 10, (
        f"one CURFEW_ENFORCED code is worth ten points, got {accepted['score']}"
    )
    assert accepted["tier"] == "LOW", (
        f"a score of ten sits below the elevated threshold, got {accepted['tier']}"
    )
    _rows, meta = validate_paginated(api.list_safety_screenings(youth["id"], WORKER))
    assert meta["total_count"] == 1, (
        "the duplicate payload wrote no second screening, got "
        f"{meta['total_count']}"
    )


OLA = {
    "legal_first_name": "Ola",
    "legal_last_name": "Sanchez",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}


def test_savings_ledger_entries_are_immutable_event_records(api):
    """PRD §2.4: "Three record types are immutable event records: an
    `OutreachContact`, a `SavingsLedgerEntry` and a `LifeSkillsCompletion` are
    written once and never changed. These three carry only `id` and `created_at`;
    they have no `updated_at` field and no `version` field at all, and neither field
    appears in their responses."
    PRD §3.8: "`balance_after_cents` is the placement's `savings_balance_cents` as it
    stands immediately after this entry posted."

    Design: Corner/entities/savings_ledger_entry_is_immutable_and_exposes_no_version
    """
    setup = setup_placement_with_deposits(
        [1010],
        documented_monthly_income_cents=90000,
        tlp_program_overrides=dict(NORTHSIDE),
        youth_overrides=dict(OLA),
    )
    first_entry = setup["entries"][0]

    second_entry = post_savings_entry(
        setup["placement"]["id"], "DEPOSIT", 2000, source_note="second deposit"
    )

    for entry in (first_entry, second_entry):
        assert_savings_ledger_entry(entry)
        assert_immutable_event_fields(entry, "savings ledger entry")
        assert "version" not in entry, (
            f"a savings entry exposes no version field, got {entry.get('version')}"
        )
    assert first_entry["match_component_cents"] == 253, (
        "1010 cents at 2500 basis points rounds half up to 253, got "
        f"{first_entry['match_component_cents']}"
    )
    assert second_entry["balance_after_cents"] == 3763, (
        "3010 deposited cents plus 753 matched cents is 3763, got "
        f"{second_entry['balance_after_cents']}"
    )

    reread = savings_entries_of(setup["placement"]["id"])
    frozen = next(entry for entry in reread if entry["id"] == first_entry["id"])
    assert frozen["balance_after_cents"] == 1263, (
        "the first entry's balance snapshot is written once and never changed, got "
        f"{frozen['balance_after_cents']}"
    )
    assert "version" not in frozen, (
        f"the listed row exposes no version either, got {frozen.get('version')}"
    )
    placement = fetch_placement(setup["placement"]["id"])
    assert placement["savings_balance_cents"] == 3763, (
        "the placement carries the live balance while the entries stay frozen, got "
        f"{placement['savings_balance_cents']}"
    )
    _rows, meta = validate_paginated(
        api.list_savings_entries(setup["placement"]["id"], COORDINATOR)
    )
    assert meta["total_count"] == 2, (
        f"both postings are listed, got {meta['total_count']}"
    )


def test_outreach_contact_under_an_unknown_youth_is_not_found(api):
    """PRD §2.10: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the first identifier that fails to resolve determines the error."
    PRD §2.10: "Each resource kind has its own not-found code, so a request naming
    an unknown youth fails with `ERR_YOUTH_NOT_FOUND` before the server ever looks
    at the nested segment."

    Design: Corner/entities/outreach_contact_under_unknown_youth_returns_not_found
    """
    youth = intake_youth(legal_first_name="Rune", legal_last_name="Halstead",
                         date_of_birth="2010-03-15", unaccompanied=True)
    log_outreach_contact(youth["id"], engagement_stage="FIRST_CONTACT",
                         basic_needs_provided=["FOOD"], indicator_flags=[])

    response = api.create_outreach_contact(
        UNKNOWN_YOUTH_ID,
        {"engagement_stage": "FIRST_CONTACT", "basic_needs_provided": ["FOOD"],
         "indicator_flags": []},
        WORKER,
    )

    validate_error(response, ApiErrorId.ERR_YOUTH_NOT_FOUND.value, 404)
    _rows, meta = validate_paginated(api.list_outreach_contacts(youth["id"], WORKER))
    assert meta["total_count"] == 1, (
        f"the real youth still holds exactly one encounter, got {meta['total_count']}"
    )
    current = fetch_youth(youth["id"])
    assert current["engagement_contact_count"] == 1, (
        "the failed write never touched the real youth's counters, got "
        f"{current['engagement_contact_count']}"
    )


def test_admission_with_an_unknown_program_reports_the_program_code(api):
    """PRD §2.10: "Foreign keys supplied in a request body are resolved in the order
    the endpoint declares them: an admission request resolves `youth_id` and then
    `program_id`; a transitional-living placement resolves `youth_id` and then
    `program_id`; a reunification case resolves `youth_id`."
    PRD §2.10: "Every foreign key in the request body resolves, in declaration order
    — the matching not-found code, 404, on the admission-request,
    transitional-living-placement and reunification-case-open operations."

    Design: Corner/entities/admission_creation_with_unknown_program_id_returns_not_found
    """
    program = license_emergency_shelter(**dict(RIVERSIDE))
    youth = intake_youth(legal_first_name="Cato", legal_last_name="Mensah",
                         date_of_birth="2010-03-15", unaccompanied=True)
    clear_screening(youth["id"])

    response = api.create_admission(
        {"youth_id": youth["id"], "program_id": UNKNOWN_PROGRAM_ID,
         "planned_discharge_at": instant("2026-08-15")},
        CASE_MANAGER,
    )

    error = validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_YOUTH_NOT_FOUND.value, (
        "the resolvable youth id is not the failing key, got "
        f"{error['error_id']}"
    )
    _rows, meta = validate_paginated(
        api.list_admissions(CASE_MANAGER, {"youth_id": youth["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected request wrote no admission, got {meta['total_count']}"
    )
    stored = fetch_program(program["id"])
    assert_program_counters(stored)
    assert stored["occupied_beds"] == 0, (
        f"the real program took nobody in, got {stored['occupied_beds']}"
    )
    current = fetch_youth(youth["id"])
    assert current["status"] == "PROSPECT", (
        f"the youth was never sheltered, got {current['status']}"
    )
