"""Government monitoring information: the four collection-method rules, the array
ceilings, amendment, and the archived-record lockdown."""

from test_helpers import (
    ApiErrorId,
    create_application,
    create_demographic_entry_payload,
    create_institution,
    make_loan_officer_headers,
    read_application,
    record_demographics,
    setup_filed_submission_over_locked_record,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_a_sex_code_outside_the_declared_set_is_malformed(api):
    """PRD §3.3: "`sex_code` takes `MALE`, `FEMALE`, `BOTH`, `INFO_NOT_PROVIDED`,
    or `NOT_APPLICABLE`."
    PRD §2.9: "Body shape: every required input named in §4 is present, every enum
    value is a member of its declared set, integers and numbers are of the declared
    type and within any stated range, arrays are arrays, ISO 8601 datetimes parse,
    and `limit` and `offset` lie inside the pagination bounds —
    `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/demographic_entry_invalid_enum_returns_invalid_request
    """
    institution = create_institution()
    record = create_application(institution["id"])

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(record["id"], sex_code="UNKNOWN"),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_a_second_applicant_row_for_the_same_role_is_rejected(api):
    """PRD §3.3: "At most one row may exist for a given pairing of
    `application_id` and `applicant_role`; a second attempt is refused with
    `ERR_DUPLICATE_DEMOGRAPHIC_ROLE`."

    Design: Corner/validations/duplicate_applicant_role_on_one_application_rejected
    """
    institution = create_institution()
    record = create_application(institution["id"])
    record_demographics(record["id"])

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], ethnicity_codes=["HISPANIC_OR_LATINO"],
                race_codes=["ASIAN"], sex_code="FEMALE",
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_DUPLICATE_DEMOGRAPHIC_ROLE.value,
    )

    validate_success(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], applicant_role="CO_APPLICANT",
                ethnicity_codes=["HISPANIC_OR_LATINO"], race_codes=["ASIAN"],
                sex_code="FEMALE",
            ),
            make_loan_officer_headers(),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_application_demographic_entries(record["id"], make_loan_officer_headers())
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_a_non_natural_applicant_may_carry_nothing_but_not_applicable(api):
    """PRD §3.3: "When `is_natural_person` is false — a trust, an estate, or
    another non-natural applicant — `collection_method` must be `NOT_APPLICABLE`,
    and `ethnicity_codes`, `race_codes`, and `sex_code` must all carry nothing but
    `NOT_APPLICABLE`. Anything else is refused with
    `ERR_NON_NATURAL_PERSON_MISMATCH`."

    Design: Corner/validations/non_natural_person_with_reported_codes_rejected
    """
    institution = create_institution()
    record = create_application(institution["id"], occupancy_type="INVESTMENT")

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(record["id"], is_natural_person=False),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_NON_NATURAL_PERSON_MISMATCH.value,
    )

    accepted = validate_success(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], collection_method="NOT_APPLICABLE",
                ethnicity_codes=["NOT_APPLICABLE"], race_codes=["NOT_APPLICABLE"],
                sex_code="NOT_APPLICABLE", is_natural_person=False,
            ),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert accepted["is_natural_person"] is False
    assert accepted["collection_method"] == "NOT_APPLICABLE"
    assert accepted["status"] == "RECORDED"


def test_observation_may_not_record_a_disaggregated_subcategory(api):
    """PRD §3.3: "When `collection_method` is `VISUAL_OBSERVATION_OR_SURNAME`,
    every supplied ethnicity code and every supplied race code must be one of the
    aggregate categories listed above; a disaggregated subcategory is forbidden,
    and so is `INFO_NOT_PROVIDED` in either array. In the same situation
    `sex_code` must be `MALE`, `FEMALE`, or `BOTH`. Any of these violations is
    refused with `ERR_DISAGGREGATED_CODE_NOT_PERMITTED`."

    Design: Corner/validations/disaggregated_codes_under_visual_observation_rejected
    """
    institution = create_institution()
    record = create_application(institution["id"], application_channel="FACE_TO_FACE")

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], collection_method="VISUAL_OBSERVATION_OR_SURNAME",
                race_codes=["KOREAN"], observation_basis="VISUAL",
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_DISAGGREGATED_CODE_NOT_PERMITTED.value,
    )

    accepted = validate_success(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], collection_method="VISUAL_OBSERVATION_OR_SURNAME",
                race_codes=["ASIAN"], observation_basis="VISUAL",
            ),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert accepted["race_codes"] == ["ASIAN"]
    assert accepted["observation_basis"] == "VISUAL"


def test_six_race_codes_exceed_the_array_ceiling(api):
    """PRD §3.3: "Independently of the four rules, an array size limit applies to
    both recording and amendment: `race_codes` may carry at most 5 entries and
    `ethnicity_codes` at most 2. Exceeding either limit is refused with
    `ERR_TOO_MANY_RACE_CODES`."

    Design: Corner/errors/too_many_race_codes_rejected
    """
    institution = create_institution()
    record = create_application(institution["id"])

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"],
                race_codes=["WHITE", "ASIAN", "BLACK", "AMERICAN_INDIAN",
                            "PACIFIC_ISLANDER", "CHINESE"],
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_TOO_MANY_RACE_CODES.value,
    )

    rows, meta = validate_paginated(
        api.list_application_demographic_entries(record["id"], make_loan_officer_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_amending_an_applicant_row_moves_it_to_amended(api):
    """PRD §3.3: "A successful amendment moves the row `RECORDED → AMENDED` and
    increments its `version` by 1."
    PRD §3.3: "Amendment merges the supplied values — any of `collection_method`,
    `ethnicity_codes`, `race_codes`, `sex_code`, `age_years`, `observation_basis`,
    and `is_natural_person` — into the existing row, then re-evaluates all four
    collection rules and the array limits against the *merged* result rather than
    against the submitted fragment."

    Design: Corner/state_machines/demographic_patch_moves_status_recorded_to_amended
    """
    institution = create_institution()
    record = create_application(institution["id"])
    entry = record_demographics(record["id"], age_years=41)

    data = validate_success(
        api.patch_demographic_entry(
            entry["id"], {"race_codes": ["ASIAN", "CHINESE"], "age_years": 42},
            make_loan_officer_headers(),
        )
    )
    assert data["status"] == "AMENDED"
    assert data["race_codes"] == ["ASIAN", "CHINESE"]
    assert data["age_years"] == 42
    assert data["applicant_role"] == "APPLICANT"
    assert data["version"] == 2


def test_amending_an_unknown_applicant_row_is_a_not_found(api):
    """PRD §2.6: "A request naming an institution that does not exist yields
    `ERR_INSTITUTION_NOT_FOUND`; an unknown register record yields
    `ERR_APPLICATION_NOT_FOUND`; and the same pattern holds for
    `ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND`, `ERR_GEOCODE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CENSUS_TRACT_NOT_FOUND`, `ERR_EDIT_RUN_NOT_FOUND`,
    `ERR_EDIT_EXCEPTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, and
    `ERR_AUDIT_SAMPLE_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/errors/patch_unknown_demographic_entry_returns_not_found
    """
    validate_error(
        api.patch_demographic_entry(UNKNOWN_ID, {"age_years": 44},
                                    make_loan_officer_headers()),
        ApiErrorId.ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND.value,
    )


def test_an_archived_record_refuses_demographic_amendment(api):
    """PRD §3.2: "While a record is `ARCHIVED`, no mutation may touch it: an
    attempt to amend its applicant demographics, or to verify an edit exception
    that names it, is refused with `ERR_APPLICATION_ARCHIVED`."
    PRD §3.3: "Amendment is refused with `ERR_APPLICATION_ARCHIVED` when the
    parent register record's stage reads `ARCHIVED`."

    Design: Corner/errors/demographic_patch_on_archived_application_rejected
    """
    scenario = setup_filed_submission_over_locked_record()
    record = scenario["application"]
    assert record["stage"] == "ARCHIVED"

    rows, _meta = validate_paginated(
        api.list_application_demographic_entries(record["id"], make_loan_officer_headers())
    )
    entry = rows[0]

    validate_error(
        api.patch_demographic_entry(entry["id"], {"age_years": 44},
                                    make_loan_officer_headers()),
        ApiErrorId.ERR_APPLICATION_ARCHIVED.value,
    )

    after, _ = validate_paginated(
        api.list_application_demographic_entries(record["id"], make_loan_officer_headers())
    )
    assert after[0]["status"] == "RECORDED"
    assert after[0]["version"] == 1


def test_visual_observation_on_an_internet_application_outranks_the_code_ceiling(api):
    """PRD §3.3: "`VISUAL_OBSERVATION_OR_SURNAME` may be used as the
    `collection_method` only when the parent register record's
    `application_channel` reads `FACE_TO_FACE`. On a mail, internet, or telephone
    application it is refused with `ERR_VISUAL_OBSERVATION_NOT_PERMITTED`."
    PRD §2.9: "The four demographic collection rules, in the order given in §3.3 —
    `ERR_VISUAL_OBSERVATION_NOT_PERMITTED`, then
    `ERR_DISAGGREGATED_CODE_NOT_PERMITTED`, then
    `ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON`, then
    `ERR_NON_NATURAL_PERSON_MISMATCH`, all 422."
    PRD §2.9: "Structural constraints, in this order — `ERR_EDIT_RUN_WINDOW_OVERLAP`
    (409), `ERR_REMEDIATION_WINDOW_OVERLAP` (409), `ERR_DUPLICATE_ULI` (409),
    `ERR_DUPLICATE_LEI` (409), `ERR_DUPLICATE_DEMOGRAPHIC_ROLE` (409),
    `ERR_TOO_MANY_RACE_CODES` (422), `ERR_SEVERITY_NOT_VERIFIABLE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/visual_observation_safety_error_outranks_too_many_race_codes
    """
    institution = create_institution()
    record = create_application(institution["id"], application_channel="INTERNET")

    error = validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], collection_method="VISUAL_OBSERVATION_OR_SURNAME",
                race_codes=["WHITE", "ASIAN", "BLACK", "AMERICAN_INDIAN",
                            "PACIFIC_ISLANDER", "OTHER_ASIAN"],
                observation_basis="VISUAL",
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_VISUAL_OBSERVATION_NOT_PERMITTED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_TOO_MANY_RACE_CODES.value
    assert error["error_id"] != ApiErrorId.ERR_DISAGGREGATED_CODE_NOT_PERMITTED.value


def test_no_applicant_row_is_written_when_the_observation_rule_fires(api):
    """PRD §3.3: "`VISUAL_OBSERVATION_OR_SURNAME` may be used as the
    `collection_method` only when the parent register record's
    `application_channel` reads `FACE_TO_FACE`. On a mail, internet, or telephone
    application it is refused with `ERR_VISUAL_OBSERVATION_NOT_PERMITTED`."
    PRD §3.3: "Independently of the four rules, an array size limit applies to both
    recording and amendment: `race_codes` may carry at most 5 entries and
    `ethnicity_codes` at most 2. Exceeding either limit is refused with
    `ERR_TOO_MANY_RACE_CODES`."

    Design: Difficulty/priority_pair_validation_conflict/visual_observation_safety_error_outranks_too_many_race_codes
    """
    institution = create_institution()
    record = create_application(institution["id"], application_channel="INTERNET")

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], collection_method="VISUAL_OBSERVATION_OR_SURNAME",
                race_codes=["WHITE", "ASIAN", "BLACK", "AMERICAN_INDIAN",
                            "PACIFIC_ISLANDER", "OTHER_ASIAN"],
                observation_basis="VISUAL",
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_VISUAL_OBSERVATION_NOT_PERMITTED.value,
    )

    rows, meta = validate_paginated(
        api.list_application_demographic_entries(record["id"], make_loan_officer_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_application(record["id"])["stage"] == "INTAKE"


def test_declining_to_state_is_refused_on_an_in_person_application(api):
    """PRD §3.3: "When the parent register record's `application_channel` reads
    `FACE_TO_FACE` and `is_natural_person` is true, `collection_method` may not be
    `NOT_PROVIDED_BY_APPLICANT`; the officer is required to record ethnicity,
    race, and sex by visual observation or surname when the applicant declines to
    state them. Violation is refused with
    `ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON`."

    Design: Difficulty/cross_entity_state_dependency/not_provided_demographics_rejected_for_face_to_face_application
    """
    institution = create_institution()
    record = create_application(institution["id"], application_channel="FACE_TO_FACE")

    validate_error(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                record["id"], collection_method="NOT_PROVIDED_BY_APPLICANT",
                ethnicity_codes=["INFO_NOT_PROVIDED"], race_codes=["INFO_NOT_PROVIDED"],
                sex_code="INFO_NOT_PROVIDED", is_natural_person=True,
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON.value,
    )

    rows, meta = validate_paginated(
        api.list_application_demographic_entries(record["id"], make_loan_officer_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_application(record["id"])["stage"] == "INTAKE"


def test_the_same_declined_row_is_accepted_on_a_mail_application(api):
    """PRD §3.3: "When the parent register record's `application_channel` reads
    `FACE_TO_FACE` and `is_natural_person` is true, `collection_method` may not be
    `NOT_PROVIDED_BY_APPLICANT`; the officer is required to record ethnicity,
    race, and sex by visual observation or surname when the applicant declines to
    state them. Violation is refused with
    `ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON`."
    PRD §3.3: "A newly recorded row has a status of `RECORDED`."

    Design: Difficulty/cross_entity_state_dependency/not_provided_demographics_rejected_for_face_to_face_application
    """
    institution = create_institution()
    by_mail = create_application(institution["id"], application_channel="MAIL")

    accepted = validate_success(
        api.create_demographic_entry(
            create_demographic_entry_payload(
                by_mail["id"], collection_method="NOT_PROVIDED_BY_APPLICANT",
                ethnicity_codes=["INFO_NOT_PROVIDED"], race_codes=["INFO_NOT_PROVIDED"],
                sex_code="INFO_NOT_PROVIDED", is_natural_person=True,
            ),
            make_loan_officer_headers(),
        ),
        201,
    )
    assert accepted["collection_method"] == "NOT_PROVIDED_BY_APPLICANT"
    assert accepted["status"] == "RECORDED"
