"""Language, courthouse, interpreter and hearing record contracts.

Creation defaults, retrieval echoes, pagination metadata, request-shape
rejection, server-minted system fields, the frozen hearing priority figures,
append-only examination attempts, and the not-found catalogue for path segments
and body foreign keys (PRD §2.2-§2.6, §2.12, §3.1-§3.5).
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_append_only_fields,
    assert_courthouse_ledger_invariants,
    assert_envelope_meta,
    assert_three_fraction_digit_timestamp,
    create_assignment_payload,
    create_courthouse_payload,
    create_credential_payload,
    create_hearing_payload,
    create_interpreter_payload,
    create_language_payload,
    create_rare_language_payload,
    exam_attempt_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

# A syntactically well-formed UUID that no row in the program ever carries.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_language_registration_applies_declared_defaults_and_seeds_the_counter(
    api, program_admin_headers
):
    """PRD §3.1: "Registering a language records its ISO-639-3 `code` — three lowercase
    letters, unique across the whole program, with a second registration of the same code
    refused as `ERR_DUPLICATE_LANGUAGE_CODE` — together with a human-readable `name`, its
    coverage class in `tier_class`, and whether the program administers an oral performance
    examination in it via `oral_exam_available`."
    PRD §3.1: "An optional `telephonic_vendor_available` flag, false when omitted, records
    whether a telephonic language-service vendor covers the language; only a language with
    that flag set may be served telephonically."
    PRD §3.1: "Registration also initialises the derived `active_credentialed_count` to 0;
    thereafter it always equals the number of credentials in this language whose status is
    `ACTIVE`, and it is recomputed by every credential activation, lapse and revocation."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`,
    refreshed on every mutation of the row — and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 each time the row is mutated."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/Entities/language_creation_returns_every_declared_field_with_defaults_applied
    """
    payload = create_language_payload(
        code="spa", name="Spanish", tier_class="DESIGNATED", oral_exam_available=True
    )
    payload.pop("telephonic_vendor_available")

    response = api.create_language(payload, program_admin_headers)
    data = validate_success(response, 201)

    assert response.json()["response_type"] == "object", (
        f"expected response_type 'object', got {response.json()['response_type']!r}"
    )
    assert data["code"] == "spa", f"expected code 'spa', got {data['code']!r}"
    assert data["name"] == "Spanish", f"expected name 'Spanish', got {data['name']!r}"
    assert data["tier_class"] == "DESIGNATED", (
        f"expected tier_class 'DESIGNATED', got {data['tier_class']!r}"
    )
    assert data["oral_exam_available"] is True, (
        f"expected oral_exam_available True, got {data['oral_exam_available']!r}"
    )
    assert data["telephonic_vendor_available"] is False, (
        "telephonic_vendor_available is false when omitted, got "
        f"{data['telephonic_vendor_available']!r}"
    )
    assert data["active_credentialed_count"] == 0, (
        "a freshly registered language has 0 active credentials, got "
        f"{data['active_credentialed_count']!r}"
    )
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert data["version"] == 1, f"expected version 1 on creation, got {data['version']!r}"
    assert_three_fraction_digit_timestamp(data["created_at"])
    assert_three_fraction_digit_timestamp(data["updated_at"])


def test_courthouse_fetch_echoes_inputs_and_reports_an_empty_book_ledger(
    api, program_admin_headers, scheduling_coordinator_headers
):
    """PRD §3.1: "Registering a courthouse records its `name`, a three-uppercase-letter
    `county_code` used for geographic-availability ranking, a `courtroom_count` of at least
    1, and the fiscal-year interpreter pay authority `pay_budget_cents`, which may not be
    negative."
    PRD §3.1: "Two fields describe the facility's remote-interpreting technology:
    `remote_equipment_tier` is one of `NONE`, `BASIC`, or `CERTIFIED_VRI`, and
    `vri_concurrent_capacity` is the number of video-equipped courtrooms that can run a video
    remote interpreting session at the same time, which may be zero."
    PRD §3.1: "The facility's `status` is `OPEN` or `CLOSED` and defaults to `OPEN`."
    PRD §3.1: "Creation initialises `encumbered_pay_cents` and `obligated_pay_cents` to 0,
    which leaves `available_pay_cents` equal to `pay_budget_cents`."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less
    `obligated_pay_cents`."

    Design: Corner/Entities/courthouse_retrieval_returns_the_stored_row_including_computed_ledger
    """
    payload = create_courthouse_payload(
        name="Capitol Main Courthouse",
        county_code="CAS",
        courtroom_count=12,
        remote_equipment_tier="CERTIFIED_VRI",
        vri_concurrent_capacity=1,
        pay_budget_cents=5_000_000,
    )
    payload.pop("status")
    created = validate_success(
        api.create_courthouse(payload, program_admin_headers), 201
    )

    fetched = validate_success(
        api.get_courthouse(created["id"], scheduling_coordinator_headers)
    )

    assert fetched["id"] == created["id"], (
        f"expected id {created['id']}, got {fetched['id']}"
    )
    assert fetched["name"] == "Capitol Main Courthouse", (
        f"expected the stored name, got {fetched['name']!r}"
    )
    assert fetched["county_code"] == "CAS", (
        f"expected county_code 'CAS', got {fetched['county_code']!r}"
    )
    assert fetched["courtroom_count"] == 12, (
        f"expected courtroom_count 12, got {fetched['courtroom_count']!r}"
    )
    assert fetched["remote_equipment_tier"] == "CERTIFIED_VRI", (
        f"expected remote_equipment_tier 'CERTIFIED_VRI', got "
        f"{fetched['remote_equipment_tier']!r}"
    )
    assert fetched["vri_concurrent_capacity"] == 1, (
        f"expected vri_concurrent_capacity 1, got {fetched['vri_concurrent_capacity']!r}"
    )
    assert fetched["status"] == "OPEN", (
        f"status defaults to OPEN when omitted, got {fetched['status']!r}"
    )
    assert fetched["pay_budget_cents"] == 5_000_000, (
        f"expected pay_budget_cents 5000000, got {fetched['pay_budget_cents']!r}"
    )
    assert fetched["encumbered_pay_cents"] == 0, (
        f"an empty book encumbers nothing, got {fetched['encumbered_pay_cents']!r}"
    )
    assert fetched["obligated_pay_cents"] == 0, (
        f"an empty book obligates nothing, got {fetched['obligated_pay_cents']!r}"
    )
    assert fetched["available_pay_cents"] == 5_000_000, (
        "available_pay_cents equals the full budget on an empty book, got "
        f"{fetched['available_pay_cents']!r}"
    )
    assert_courthouse_ledger_invariants(fetched)


def test_interpreter_listing_reports_total_count_and_has_more_across_pages(
    api, program_admin_headers, credentialing_officer_headers
):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true exactly when rows remain beyond the current
    page."
    PRD §3.2: "The roster search itself accepts filters on `roster_status`,
    `credential_tier`, `language_id` (matching against the interpreter's credentialed
    languages) and `home_county_code`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/Entities/interpreter_listing_paginates_with_total_count_and_has_more
    """
    roster = (
        ("Ana Reyes", "ana.reyes@courts.example.gov", "CAS"),
        ("Bo Lim", "bo.lim@courts.example.gov", "CAS"),
        ("Dev Kaur", "dev.kaur@courts.example.gov", "NOR"),
    )
    for full_name, email, county_code in roster:
        validate_success(
            api.create_interpreter(
                create_interpreter_payload(
                    full_name=full_name, email=email, home_county_code=county_code
                ),
                credentialing_officer_headers,
            ),
            201,
        )

    first_response = api.list_interpreters(
        program_admin_headers, params={"limit": 2, "offset": 0}
    )
    first_page, first_meta = validate_paginated(first_response)

    assert first_response.json()["response_type"] == "array", (
        f"expected response_type 'array', got {first_response.json()['response_type']!r}"
    )
    assert first_meta["total_count"] == 3, (
        f"total_count counts the whole matching set, expected 3, got "
        f"{first_meta['total_count']!r}"
    )
    assert first_meta["limit"] == 2, f"expected limit 2, got {first_meta['limit']!r}"
    assert first_meta["offset"] == 0, f"expected offset 0, got {first_meta['offset']!r}"
    assert first_meta["has_more"] is True, (
        f"rows remain beyond page one, expected has_more True, got {first_meta['has_more']!r}"
    )
    assert len(first_page) == 2, f"expected exactly 2 rows on page one, got {len(first_page)}"

    second_page, second_meta = validate_paginated(
        api.list_interpreters(program_admin_headers, params={"limit": 2, "offset": 2})
    )
    assert second_meta["total_count"] == 3, (
        f"total_count is unaffected by paging, expected 3, got {second_meta['total_count']!r}"
    )
    assert second_meta["offset"] == 2, f"expected offset 2, got {second_meta['offset']!r}"
    assert second_meta["has_more"] is False, (
        f"no rows remain beyond page two, expected has_more False, got "
        f"{second_meta['has_more']!r}"
    )
    assert len(second_page) == 1, (
        f"expected exactly 1 row on page two, got {len(second_page)}"
    )

    first_ids = {row["id"] for row in first_page}
    second_ids = {row["id"] for row in second_page}
    assert not (first_ids & second_ids), (
        f"pages must not overlap, both carry {first_ids & second_ids}"
    )

    filtered, filtered_meta = validate_paginated(
        api.list_interpreters(program_admin_headers, params={"home_county_code": "NOR"})
    )
    assert filtered_meta["total_count"] == 1, (
        "the filter narrows total_count itself, expected 1, got "
        f"{filtered_meta['total_count']!r}"
    )
    assert len(filtered) == 1, f"expected 1 filtered row, got {len(filtered)}"
    assert filtered[0]["home_county_code"] == "NOR", (
        f"expected the NOR row, got home_county_code {filtered[0]['home_county_code']!r}"
    )
    assert filtered[0]["full_name"] == "Dev Kaur", (
        f"expected Dev Kaur as the only NOR interpreter, got {filtered[0]['full_name']!r}"
    )


def test_hearing_fetch_with_unknown_uuid_returns_hearing_not_found(
    api, scheduling_coordinator_headers
):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first segment
    that fails to resolve determines the error."
    PRD §2.6: "An unresolvable interpreter segment yields `ERR_INTERPRETER_NOT_FOUND`; a
    credential segment, `ERR_CREDENTIAL_NOT_FOUND`; a hearing segment,
    `ERR_HEARING_NOT_FOUND`; an assignment segment, `ERR_ASSIGNMENT_NOT_FOUND`; a pay-claim
    segment, `ERR_PAY_CLAIM_NOT_FOUND`; a complaint segment, `ERR_COMPLAINT_NOT_FOUND`; a
    disciplinary-action segment, `ERR_DISCIPLINARY_ACTION_NOT_FOUND`; and a courthouse
    segment, `ERR_CONFIG_RESOURCE_NOT_FOUND`."
    PRD §2.12: "Path existence: every `id` path segment resolves, left to right, mapped to the
    not-found codes listed in §2.6."

    Design: Corner/Entities/hearing_get_with_unknown_uuid_returns_not_found
    """
    response = api.get_hearing(UNKNOWN_UUID, scheduling_coordinator_headers)

    validate_error(response, ApiErrorId.ERR_HEARING_NOT_FOUND)
    assert response.json()["response_type"] == "error", (
        f"expected response_type 'error', got {response.json()['response_type']!r}"
    )


def test_hearing_create_without_scheduled_end_is_rejected(
    api, scheduling_coordinator_headers
):
    """PRD §3.5: "A `SchedulingCoordinator` or `ProgramAdmin` places one on a courthouse
    calendar by supplying `courthouse_id`, the `language_id` the hearing needs, the court's
    `case_number`, the `hearing_type`, an `in_custody` flag that is true when the
    limited-English party is held in custody, the `scheduled_start` and `scheduled_end`
    instants as ISO 8601 UTC timestamps with three fractional digits, and the
    `requested_delivery_mode` the calendar is asking for — `IN_PERSON`, `VRI`, or
    `TELEPHONIC`."
    PRD §2.12: "Request shape: unknown value types, malformed dates or datetimes, enum values
    outside the declared set, negative money or mileage, non-positive counts, a `limit`
    outside 1 through 100, a negative `offset`, a `scheduled_end` at or before
    `scheduled_start`, a `period_end` at or before `period_start`, and any missing required
    input field — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/Entities/hearing_create_without_scheduled_end_is_rejected
    """
    language = fixtures.bootstrap_language()
    courthouse = fixtures.bootstrap_courthouse()

    payload = create_hearing_payload(
        courthouse["id"],
        language["id"],
        case_number="CR-2026-0900",
        hearing_type="TRIAL",
        in_custody=True,
        scheduled_start="2026-09-10T09:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    payload.pop("scheduled_end")

    response = api.create_hearing(payload, scheduling_coordinator_headers)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_hearings(scheduling_coordinator_headers))
    assert meta["total_count"] == 0, (
        f"a rejected placement must create no Hearing row, got total_count "
        f"{meta['total_count']!r}"
    )


def test_interpreter_enrolment_applies_declared_optional_defaults(
    api, credentialing_officer_headers
):
    """PRD §3.2: "Enrolment, performed by a `CredentialingOfficer` or a `ProgramAdmin`,
    records `full_name`, a contact `email` that must be unique across the roster — a second
    enrolment with the same address is refused with `ERR_DUPLICATE_INTERPRETER_EMAIL` — an
    optional `phone` that is null when omitted, and a `home_county_code` of three uppercase
    letters that the program later compares against a courthouse's `county_code` when it ranks
    candidates by geographic availability."
    PRD §3.2: "Two willingness flags, `accepts_in_person` and `accepts_remote`, both default
    to true when omitted; the first governs eligibility for in-person work and the second
    governs both video and telephonic work."
    PRD §3.2: "Enrolment sets `roster_status` to `APPLICANT` and `ethics_training_status` to
    `NOT_STARTED`, and it initialises `complaint_points` to 0 with `rolling_12_month_score`
    and `lifetime_score` both at 100."
    PRD §3.2: "`credential_tier` is the highest tier among the interpreter's credentials whose
    status is `ACTIVE`, ranked `MASTER` above `CERTIFIED` above `REGISTERED` above
    `PROVISIONAL`, and reads `NONE` when no credential of theirs is active."
    PRD §3.2: "`credentialed_language_ids` lists the language of each of those active
    credentials, ordered by the credential's own `created_at` ascending."
    PRD §3.2: "`pending_pay_cents` is the sum of `final_total_cents` over this interpreter's
    pay claims whose status is `FINALIZED`, `SUBMITTED`, or `APPROVED`, and `paid_pay_cents`
    is the same sum restricted to claims in `PAID`."
    PRD §3.2: "The field `suspension_through` holds the date through which an in-effect
    suspension keeps `roster_status` at `SUSPENDED`, and is null whenever the interpreter is
    not suspended."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`,
    refreshed on every mutation of the row — and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 each time the row is mutated."

    Design: Corner/Entities/interpreter_create_omitting_optional_flags_applies_declared_defaults
    """
    payload = create_interpreter_payload(
        full_name="Ana Reyes",
        email="ana.reyes@courts.example.gov",
        home_county_code="CAS",
    )
    payload.pop("accepts_in_person")
    payload.pop("accepts_remote")

    data = validate_success(
        api.create_interpreter(payload, credentialing_officer_headers), 201
    )

    assert data["accepts_in_person"] is True, (
        f"accepts_in_person defaults to true, got {data['accepts_in_person']!r}"
    )
    assert data["accepts_remote"] is True, (
        f"accepts_remote defaults to true, got {data['accepts_remote']!r}"
    )
    assert data["phone"] is None, f"phone is null when omitted, got {data['phone']!r}"
    assert data["suspension_through"] is None, (
        f"an unsuspended interpreter carries a null suspension_through, got "
        f"{data['suspension_through']!r}"
    )
    assert data["roster_status"] == "APPLICANT", (
        f"enrolment sets roster_status APPLICANT, got {data['roster_status']!r}"
    )
    assert data["ethics_training_status"] == "NOT_STARTED", (
        f"enrolment sets ethics_training_status NOT_STARTED, got "
        f"{data['ethics_training_status']!r}"
    )
    assert data["credential_tier"] == "NONE", (
        f"credential_tier reads NONE with no active credential, got "
        f"{data['credential_tier']!r}"
    )
    assert data["credentialed_language_ids"] == [], (
        f"no active credential means no credentialed languages, got "
        f"{data['credentialed_language_ids']!r}"
    )
    assert data["complaint_points"] == 0, (
        f"enrolment initialises complaint_points to 0, got {data['complaint_points']!r}"
    )
    assert data["rolling_12_month_score"] == 100, (
        f"enrolment initialises rolling_12_month_score to 100, got "
        f"{data['rolling_12_month_score']!r}"
    )
    assert data["lifetime_score"] == 100, (
        f"enrolment initialises lifetime_score to 100, got {data['lifetime_score']!r}"
    )
    assert data["pending_pay_cents"] == 0, (
        f"an interpreter with no claims has 0 pending pay, got {data['pending_pay_cents']!r}"
    )
    assert data["paid_pay_cents"] == 0, (
        f"an interpreter with no claims has 0 paid pay, got {data['paid_pay_cents']!r}"
    )
    assert data["version"] == 1, f"expected version 1 on creation, got {data['version']!r}"


def test_hearing_priority_score_and_lead_time_are_computed_at_placement(
    api, scheduling_coordinator_headers
):
    """PRD §2.5: "Before any client sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; the server never falls back to real time."
    PRD §3.5: "First, a **type weight** taken from the event type: an arraignment scores 50, a
    detention review 45, a trial 40, a plea 30, a sentencing 30, a motion 20, and a civil
    motion 10."
    PRD §3.5: "Second, a **custody bonus** of 25 points added when `in_custody` is true and
    nothing added when it is false."
    PRD §3.5: "Third, a **rarity bonus** taken from the needed language's `tier_class`: 15
    points for a `RARE` language, 5 points for a `NON_DESIGNATED` one, and 0 for a
    `DESIGNATED` one."
    PRD §3.5: "Fourth, a **lead-time figure** stored on the row as `lead_time_days`: take the
    difference between `scheduled_start` and the logical clock at the moment of creation,
    express it in whole days by discarding any remaining fraction of a day, and then treat any
    negative result as 0."
    PRD §3.5: "Fifth, an **urgency term**: start from 20 points, subtract 2 points for each
    whole day of `lead_time_days`, and treat any negative result as 0 — so a hearing 10 or
    more days out contributes no urgency at all while one starting the same day contributes the
    full 20."
    PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency term,
    then cap the sum at 100; the result is `priority_score`."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is 80 or
    more, `B` when it is 55 or more but below 80, and `C` otherwise."
    PRD §3.5: "Creation sets `status` to `SCHEDULED` and `continuance_count` to 0, and leaves
    `continuance_reason_code` null."

    Design: Corner/Entities/hearing_priority_and_lead_time_are_computed_and_client_input_ignored
    """
    language = fixtures.bootstrap_language(
        code="kor", name="Korean", tier_class="NON_DESIGNATED", oral_exam_available=True
    )
    courthouse = fixtures.bootstrap_courthouse()

    payload = create_hearing_payload(
        courthouse["id"],
        language["id"],
        case_number="CR-2026-0901",
        hearing_type="PLEA",
        in_custody=False,
        scheduled_start="2026-09-14T09:00:00.000Z",
        scheduled_end="2026-09-14T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )

    data = validate_success(
        api.create_hearing(payload, scheduling_coordinator_headers), 201
    )

    assert data["lead_time_days"] == 44, (
        f"2026-08-01T00:00:00Z to 2026-09-14T09:00:00.000Z is 44 whole days, got "
        f"{data['lead_time_days']!r}"
    )
    assert data["priority_score"] == 35, (
        "expected 35 (PLEA 30 + custody 0 + NON_DESIGNATED 5 + urgency 0), got "
        f"{data['priority_score']!r}"
    )
    assert data["priority_class"] == "C", (
        f"a score of 35 is below the class B floor of 55, got {data['priority_class']!r}"
    )
    assert data["status"] == "SCHEDULED", (
        f"creation sets status SCHEDULED, got {data['status']!r}"
    )
    assert data["continuance_count"] == 0, (
        f"creation sets continuance_count 0, got {data['continuance_count']!r}"
    )
    assert data["continuance_reason_code"] is None, (
        f"creation leaves continuance_reason_code null, got "
        f"{data['continuance_reason_code']!r}"
    )


def test_hearing_placement_ignores_client_supplied_priority_and_status(
    api, scheduling_coordinator_headers
):
    """PRD §3.5: "Placement is also the only moment at which the program judges how urgently
    the hearing needs an interpreter, and that judgement is frozen onto the row so that
    priority never drifts as the calendar approaches."
    PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency term,
    then cap the sum at 100; the result is `priority_score`."
    PRD §3.5: "Fourth, a **lead-time figure** stored on the row as `lead_time_days`: take the
    difference between `scheduled_start` and the logical clock at the moment of creation,
    express it in whole days by discarding any remaining fraction of a day, and then treat any
    negative result as 0."
    PRD §3.5: "Creation sets `status` to `SCHEDULED` and `continuance_count` to 0, and leaves
    `continuance_reason_code` null."
    PRD §3.5: "Coverage is tracked separately in the hearing's `status`, which is never
    written by a client after creation."

    Design: Corner/Entities/hearing_priority_and_lead_time_are_computed_and_client_input_ignored
    """
    language = fixtures.bootstrap_language(
        code="kor", name="Korean", tier_class="NON_DESIGNATED", oral_exam_available=True
    )
    courthouse = fixtures.bootstrap_courthouse()

    payload = create_hearing_payload(
        courthouse["id"],
        language["id"],
        case_number="CR-2026-0901",
        hearing_type="PLEA",
        in_custody=False,
        scheduled_start="2026-09-14T09:00:00.000Z",
        scheduled_end="2026-09-14T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
        priority_score=5,
        priority_class="C",
        lead_time_days=999,
        status="SERVED",
    )

    data = validate_success(
        api.create_hearing(payload, scheduling_coordinator_headers), 201
    )

    assert data["lead_time_days"] == 44, (
        f"lead_time_days is computed from the clock, not the supplied 999, got "
        f"{data['lead_time_days']!r}"
    )
    assert data["priority_score"] == 35, (
        f"priority_score is computed from the formula, not the supplied 5, got "
        f"{data['priority_score']!r}"
    )
    assert data["priority_class"] == "C", (
        f"a score of 35 derives class C, got {data['priority_class']!r}"
    )
    assert data["status"] == "SCHEDULED", (
        f"creation sets status SCHEDULED and the supplied SERVED is ignored, got "
        f"{data['status']!r}"
    )


def test_language_creation_mints_its_own_identity_and_revision_counter(
    api, program_admin_headers
):
    """PRD §2.4: "Every resource the service creates is identified by `id`, a server-minted
    UUID carrying no type prefix and no embedded semantics; clients never supply an `id`."
    PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with exactly
    three fractional-second digits recording when the row was inserted."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`,
    refreshed on every mutation of the row — and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 each time the row is mutated."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/Entities/language_system_fields_are_server_minted_and_client_input_ignored
    """
    payload = create_rare_language_payload(
        code="mix",
        name="Mixteco Bajo",
        tier_class="RARE",
        oral_exam_available=False,
        telephonic_vendor_available=True,
    )

    response = api.create_language(payload, program_admin_headers)
    data = validate_success(response, 201)

    assert is_valid_uuid(data["id"]), (
        f"id must be a server-minted UUID with no type prefix, got {data['id']!r}"
    )
    assert data["version"] == 1, f"version starts at 1 on creation, got {data['version']!r}"
    assert_three_fraction_digit_timestamp(data["created_at"])
    assert_three_fraction_digit_timestamp(data["updated_at"])
    assert_envelope_meta(response.json())


def test_language_creation_discards_client_supplied_system_fields(
    api, program_admin_headers
):
    """PRD §2.4: "Every resource the service creates is identified by `id`, a server-minted
    UUID carrying no type prefix and no embedded semantics; clients never supply an `id`."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`,
    refreshed on every mutation of the row — and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 each time the row is mutated."
    PRD §3.1: "Registration also initialises the derived `active_credentialed_count` to 0;
    thereafter it always equals the number of credentials in this language whose status is
    `ACTIVE`, and it is recomputed by every credential activation, lapse and revocation."

    Design: Corner/Entities/language_system_fields_are_server_minted_and_client_input_ignored
    """
    client_id = "11111111-1111-4111-8111-111111111111"
    client_timestamp = "2000-01-01T00:00:00.000Z"
    payload = create_rare_language_payload(
        code="mix",
        name="Mixteco Bajo",
        tier_class="RARE",
        oral_exam_available=False,
        telephonic_vendor_available=True,
        id=client_id,
        version=77,
        created_at=client_timestamp,
        updated_at=client_timestamp,
        active_credentialed_count=42,
    )

    response = api.create_language(payload, program_admin_headers)
    data = validate_success(response, 201)

    assert data["id"] != client_id, (
        f"the server mints its own id; the client-supplied {client_id} must be discarded"
    )
    assert is_valid_uuid(data["id"]), f"id must be a UUID, got {data['id']!r}"
    assert data["version"] == 1, (
        f"version starts at 1 on creation, not the supplied 77, got {data['version']!r}"
    )
    assert data["active_credentialed_count"] == 0, (
        "active_credentialed_count is derived and starts at 0, not the supplied 42, got "
        f"{data['active_credentialed_count']!r}"
    )
    assert data["created_at"] != client_timestamp, (
        f"created_at records when the row was inserted, not the supplied {client_timestamp}"
    )
    assert data["tier_class"] == "RARE", (
        f"expected tier_class 'RARE', got {data['tier_class']!r}"
    )
    assert data["oral_exam_available"] is False, (
        f"expected oral_exam_available False, got {data['oral_exam_available']!r}"
    )
    assert data["telephonic_vendor_available"] is True, (
        f"expected telephonic_vendor_available True, got "
        f"{data['telephonic_vendor_available']!r}"
    )
    assert_envelope_meta(response.json())


def test_exam_attempt_carries_no_version_and_preserves_the_failed_attempt(
    api, credentialing_officer_headers
):
    """PRD §2.4: "Two resource types are immutable ledger entries and therefore behave
    differently: an examination attempt and an unmet-need report each carry only `id` and
    `created_at`."
    PRD §2.4: "For those two, `updated_at` and `version` are absent from the response entirely
    — not null, absent — because neither row is ever updated after insertion and neither
    exposes an update endpoint."
    PRD §3.3: "Recording an attempt writes `credential_id` from the credential the attempt is
    filed under, derives `attempt_ordinal` as the 1-based index of this attempt among the
    credential's attempts of the *same* `exam_type` ordered by `taken_on` ascending and then
    `created_at` ascending, and derives `result` as `PASS` when the score reaches the passing
    floor for the credential's target tier and this exam type and `FAIL` otherwise."
    PRD §3.3: "The written floor is 90 for a `MASTER` target and 80 for every other target."
    PRD §3.3: "Each recorded attempt refreshes the credential's best score for that exam type
    — `written_best_score` and `oral_best_score` each hold the highest `score` seen across that
    type's attempts, remaining null while no attempt of that type exists — increments the
    matching `written_attempt_count` or `oral_attempt_count`, and increments the credential's
    `version` by 1."
    PRD §3.3: "And a candidate who has failed must wait: the supplied `taken_on` must be at
    least 90 days after the `taken_on` of the most recent failed attempt of the same exam type
    on this credential, with a gap of exactly 90 days accepted and anything shorter refused as
    `ERR_EXAM_RETAKE_TOO_SOON`."

    Design: Corner/Entities/exam_attempt_is_immutable_and_carries_no_version_field
    """
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter()
    credential = fixtures.open_credential(
        interpreter["id"], language["id"], "CERTIFIED", interpreter["version"]
    )

    failed = fixtures.record_exam_attempt(
        credential["id"], "WRITTEN", 62, "2026-08-01"
    )
    assert failed["result"] == "FAIL", (
        f"62 is below the CERTIFIED written floor of 80, expected FAIL, got "
        f"{failed['result']!r}"
    )
    assert failed["attempt_ordinal"] == 1, (
        f"the first written attempt is ordinal 1, got {failed['attempt_ordinal']!r}"
    )

    response = api.create_exam_attempt(
        credential["id"],
        exam_attempt_payload("WRITTEN", 86, "2026-11-01"),
        credentialing_officer_headers,
    )
    passed = validate_success(response, 201)

    assert passed["result"] == "PASS", (
        f"86 reaches the CERTIFIED written floor of 80, expected PASS, got "
        f"{passed['result']!r}"
    )
    assert passed["attempt_ordinal"] == 2, (
        f"the second written attempt is ordinal 2, got {passed['attempt_ordinal']!r}"
    )
    assert passed["credential_id"] == credential["id"], (
        f"expected credential_id {credential['id']}, got {passed['credential_id']!r}"
    )
    assert_append_only_fields(passed)

    rows, meta = validate_paginated(
        api.list_exam_attempts(
            credential["id"], credentialing_officer_headers,
            params={"exam_type": "WRITTEN"},
        )
    )
    assert meta["total_count"] == 2, (
        f"both attempts are preserved, expected total_count 2, got {meta['total_count']!r}"
    )
    by_id = {row["id"]: row for row in rows}
    assert failed["id"] in by_id, (
        f"the failed attempt {failed['id']} must still be readable, got {sorted(by_id)}"
    )
    preserved = by_id[failed["id"]]
    assert preserved["score"] == 62, (
        f"the failed attempt keeps its score of 62, got {preserved['score']!r}"
    )
    assert preserved["result"] == "FAIL", (
        f"the failed attempt keeps its FAIL result, got {preserved['result']!r}"
    )
    assert preserved["attempt_ordinal"] == 1, (
        f"the failed attempt keeps ordinal 1, got {preserved['attempt_ordinal']!r}"
    )
    assert_append_only_fields(preserved)

    after = fixtures.read_credential(credential["id"])
    assert after["written_attempt_count"] == 2, (
        f"expected written_attempt_count 2, got {after['written_attempt_count']!r}"
    )
    assert after["written_best_score"] == 86, (
        f"written_best_score holds the highest score, not the last, got "
        f"{after['written_best_score']!r}"
    )


def test_credential_create_with_unknown_target_tier_is_rejected(
    api, credentialing_officer_headers
):
    """PRD §3.3: "A `CredentialingOfficer` opens one by naming the holder in
    `interpreter_id`, the language in `language_id`, and the tier being pursued in
    `target_tier` — one of `MASTER`, `CERTIFIED`, `REGISTERED`, or `PROVISIONAL` — together
    with the `expected_interpreter_version` pin described in §2.7."
    PRD §2.12: "Request shape: unknown value types, malformed dates or datetimes, enum values
    outside the declared set, negative money or mileage, non-positive counts, a `limit` outside
    1 through 100, a negative `offset`, a `scheduled_end` at or before `scheduled_start`, a
    `period_end` at or before `period_start`, and any missing required input field — otherwise
    `ERR_INVALID_REQUEST` (400)."
    PRD §3.2: "The first credential application opened in their name promotes `APPLICANT →
    CANDIDATE`, and that promotion increments the interpreter's `version` by 1."

    Design: Corner/Entities/credential_create_with_unknown_target_tier_is_rejected
    """
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter()

    response = api.create_credential(
        create_credential_payload(
            interpreter["id"],
            language["id"],
            interpreter["version"],
            target_tier="JOURNEYMAN",
        ),
        credentialing_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.list_credentials(
            credentialing_officer_headers,
            params={"interpreter_id": interpreter["id"]},
        )
    )
    assert meta["total_count"] == 0, (
        f"a rejected application must not persist a credential, expected total_count 0, "
        f"got {meta['total_count']!r}"
    )

    after = fixtures.read_interpreter(interpreter["id"])
    assert after["roster_status"] == "APPLICANT", (
        f"no application was opened, so the holder stays APPLICANT, got "
        f"{after['roster_status']!r}"
    )
    assert after["version"] == interpreter["version"], (
        f"no promotion happened, so version stays {interpreter['version']}, got "
        f"{after['version']!r}"
    )


def test_exam_attempt_under_unknown_credential_returns_credential_not_found(
    api, credentialing_officer_headers
):
    """PRD §2.6: "Path parameters are resolved strictly left to right, and the first segment
    that fails to resolve determines the error. An unresolvable interpreter segment yields
    `ERR_INTERPRETER_NOT_FOUND`; a credential segment, `ERR_CREDENTIAL_NOT_FOUND`; a hearing
    segment, `ERR_HEARING_NOT_FOUND`; an assignment segment, `ERR_ASSIGNMENT_NOT_FOUND`; a
    pay-claim segment, `ERR_PAY_CLAIM_NOT_FOUND`; a complaint segment,
    `ERR_COMPLAINT_NOT_FOUND`; a disciplinary-action segment,
    `ERR_DISCIPLINARY_ACTION_NOT_FOUND`; and a courthouse segment,
    `ERR_CONFIG_RESOURCE_NOT_FOUND`. All eight are HTTP 404."
    PRD §2.12: "Path existence: every `id` path segment resolves, left to right, mapped to the
    not-found codes listed in §2.6. Applies to every endpoint carrying a path parameter."

    Design: Corner/Entities/exam_attempt_under_unknown_credential_parent_returns_not_found
    """
    response = api.create_exam_attempt(
        UNKNOWN_UUID,
        exam_attempt_payload("WRITTEN", 86, "2026-08-01"),
        credentialing_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_CREDENTIAL_NOT_FOUND)


def test_assignment_create_with_unknown_hearing_id_returns_hearing_not_found(
    api, scheduling_coordinator_headers
):
    """PRD §2.6: "The same catalogue governs foreign keys arriving in a request body, and the
    mapping is by *referent type*, not by field name. A `language_id`, `courthouse_id`, or
    `rate_schedule_id` that does not resolve yields `ERR_CONFIG_RESOURCE_NOT_FOUND`; an
    `interpreter_id`, `ERR_INTERPRETER_NOT_FOUND`; a `hearing_id`, `ERR_HEARING_NOT_FOUND`; an
    `assignment_id`, `ERR_ASSIGNMENT_NOT_FOUND`; a `complaint_id`,
    `ERR_COMPLAINT_NOT_FOUND`. Body-level foreign-key resolution is checked on exactly five
    write endpoints: `POST /credentials`, `POST /hearings`, `POST /assignments`, `POST
    /complaints`, and `POST /unmet-need-reports`."
    PRD §2.12: "Body referential integrity: every foreign key in the request body resolves,
    mapped as in §2.6. Applies to `POST /credentials`, `POST /hearings`, `POST /assignments`,
    `POST /complaints`, and `POST /unmet-need-reports`."
    PRD §2.12: "Optimistic concurrency: `expected_hearing_version` equals the hearing's
    `version` on `POST /assignments`, and `expected_interpreter_version` equals the
    interpreter's `version` on `POST /credentials` — otherwise `ERR_STALE_HEARING_VERSION` or
    `ERR_STALE_INTERPRETER_VERSION` (both 412)."

    Design: Corner/Entities/assignment_create_with_unresolvable_body_foreign_key_returns_not_found
    """
    fixtures.setup_program_config()
    interpreter = fixtures.enrol_interpreter()

    response = api.create_assignment(
        create_assignment_payload(
            UNKNOWN_UUID, 1, interpreter_id=interpreter["id"]
        ),
        scheduling_coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_HEARING_NOT_FOUND)

    _rows, meta = validate_paginated(
        api.list_assignments(scheduling_coordinator_headers)
    )
    assert meta["total_count"] == 0, (
        f"an unresolvable hearing_id must not create an assignment, expected total_count 0, "
        f"got {meta['total_count']!r}"
    )
