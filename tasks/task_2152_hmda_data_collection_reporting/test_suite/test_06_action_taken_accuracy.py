"""Recording the action taken and its date: the three referential rules, the three
date-accuracy rules and their pinned precedence."""

from test_helpers import (
    ApiErrorId,
    action_taken_payload,
    create_institution,
    make_loan_officer_headers,
    read_application,
    setup_decisioned_application,
    validate_error,
    validate_success,
)


def test_an_action_dated_after_the_logical_clock_is_rejected(api):
    """PRD §3.5: "It may not be later than the current logical clock, since an
    institution cannot act in the future; a violation is refused with
    `ERR_ACTION_DATE_IN_FUTURE`."
    PRD §2.5: "It maintains a single logical clock which, before any caller sets
    it, reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time."

    Design: Corner/validations/action_taken_date_in_the_future_rejected
    """
    institution = create_institution()
    record = setup_decisioned_application(institution["id"])

    validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(action_taken_date="2026-09-01T00:00:00Z"),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_ACTION_DATE_IN_FUTURE.value,
    )
    assert read_application(record["id"])["action_taken"] is None


def test_an_action_dated_outside_the_activity_year_is_rejected(api):
    """PRD §3.5: "And its calendar year must equal the owning institution's
    `activity_year`, because a register covers exactly one year; a violation is
    refused with `ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR`."

    Design: Corner/validations/action_taken_date_outside_activity_year_rejected
    """
    institution = create_institution()
    record = setup_decisioned_application(
        institution["id"], application_date="2025-11-01T00:00:00Z"
    )

    validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(action_taken_date="2025-12-20T00:00:00Z"),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR.value,
    )
    assert read_application(record["id"])["action_taken_date"] is None


def test_denial_reasons_on_an_origination_are_not_permitted(api):
    """PRD §3.5: "Conversely, any action that is neither `DENIED` nor
    `PREAPPROVAL_DENIED` forbids a non-empty `denial_reason_codes` array, and
    supplying one is refused with `ERR_DENIAL_REASON_NOT_PERMITTED`."

    Design: Corner/validations/denial_reasons_on_an_origination_rejected
    """
    institution = create_institution()
    record = setup_decisioned_application(institution["id"])

    validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(denial_reason_codes=["CREDIT_HISTORY"]),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_DENIAL_REASON_NOT_PERMITTED.value,
    )
    assert read_application(record["id"])["action_taken"] is None


def test_a_purchased_loan_must_name_a_real_purchaser(api):
    """PRD §3.5: "And an action of `PURCHASED_LOAN` requires `purchaser_type` to
    be present and to be something other than `NOT_APPLICABLE`, since a purchased
    loan by definition has a purchaser; a missing or `NOT_APPLICABLE` value is
    refused with `ERR_PURCHASER_TYPE_REQUIRED`."
    PRD §3.2: "If the owning institution is **not** partially exempt,
    `income_thousands` joins the applicable set, and three further conditional
    additions apply on top of it: when `action_taken` reads `ORIGINATED`, both
    `rate_spread` and `purchaser_type` become applicable; when `action_taken` reads
    `PURCHASED_LOAN`, `purchaser_type` becomes applicable; and when `action_taken`
    reads `DENIED`, `denial_reason_codes` becomes applicable."

    Design: Corner/validations/purchased_loan_without_purchaser_type_rejected
    """
    institution = create_institution()
    record = setup_decisioned_application(institution["id"])

    validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(action_taken="PURCHASED_LOAN", rate_spread=None,
                                 purchaser_type="NOT_APPLICABLE"),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_PURCHASER_TYPE_REQUIRED.value,
    )

    data = validate_success(
        api.record_action_taken(
            record["id"],
            action_taken_payload(action_taken="PURCHASED_LOAN", rate_spread=None,
                                 purchaser_type="FANNIE_MAE"),
            make_loan_officer_headers(),
        )
    )
    assert data["action_taken"] == "PURCHASED_LOAN"
    assert data["purchaser_type"] == "FANNIE_MAE"
    assert data["applicable_field_count"] == 12
    assert data["lar_status"] == "COMPLETE"


def test_an_action_dated_before_the_application_is_rejected(api):
    """PRD §3.5: "The `action_taken_date` may not precede the record's
    `application_date` — an institution cannot act on an application before
    receiving it — and a violation is refused with
    `ERR_ACTION_DATE_BEFORE_APPLICATION`."

    Design: Corner/errors/action_date_before_application_date_rejected
    """
    institution = create_institution()
    record = setup_decisioned_application(
        institution["id"], application_date="2026-03-20T00:00:00Z"
    )

    validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(action_taken_date="2026-03-01T00:00:00Z"),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_ACTION_DATE_BEFORE_APPLICATION.value,
    )
    assert read_application(record["id"])["action_taken"] is None


def test_missing_denial_reasons_outrank_an_action_date_before_the_application(api):
    """PRD §3.5: "A denial — `action_taken` of `DENIED` or `PREAPPROVAL_DENIED` —
    requires a non-empty `denial_reason_codes` array, and its absence is refused
    with `ERR_DENIAL_REASON_REQUIRED`."
    PRD §2.9: "Cross-field referential accuracy, in this order —
    `ERR_DENIAL_REASON_REQUIRED`, `ERR_DENIAL_REASON_NOT_PERMITTED`,
    `ERR_PURCHASER_TYPE_REQUIRED`, `ERR_GEOCODE_TRACT_MISMATCH`,
    `ERR_EDIT_RUN_INSTITUTION_MISMATCH`, `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE`,
    all 422."
    PRD §2.9: "Action-date accuracy, in this order —
    `ERR_ACTION_DATE_BEFORE_APPLICATION`, `ERR_ACTION_DATE_IN_FUTURE`,
    `ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR`, all 422."

    Design: Difficulty/priority_pair_validation_conflict/denial_reason_referential_error_outranks_action_date_temporal_error
    """
    institution = create_institution()
    record = setup_decisioned_application(
        institution["id"], application_channel="TELEPHONE",
        application_date="2026-03-20T00:00:00Z",
        demographic_overrides={
            "collection_method": "NOT_PROVIDED_BY_APPLICANT",
            "ethnicity_codes": ["INFO_NOT_PROVIDED"],
            "race_codes": ["INFO_NOT_PROVIDED"],
            "sex_code": "INFO_NOT_PROVIDED",
        },
    )

    error = validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(
                action_taken="DENIED", action_taken_date="2026-03-01T00:00:00Z",
                denial_reason_codes=[], rate_spread=None, purchaser_type=None,
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_DENIAL_REASON_REQUIRED.value,
    )
    assert error["error_id"] != ApiErrorId.ERR_ACTION_DATE_BEFORE_APPLICATION.value


def test_the_record_is_untouched_when_the_referential_rule_wins(api):
    """PRD §3.5: "A denial — `action_taken` of `DENIED` or `PREAPPROVAL_DENIED` —
    requires a non-empty `denial_reason_codes` array, and its absence is refused
    with `ERR_DENIAL_REASON_REQUIRED`."
    PRD §3.5: "Once all six rules pass, `action_taken` and `action_taken_date` are
    stored, the completeness calculation of §3.2 re-runs — commonly moving the
    record `PENDING_FIELDS → COMPLETE`, because the action and its date are two of
    the ten always-applicable fields and because the action may add the conditional
    ones — the institution's record counters are recomputed, and both the record's
    `version` and the institution's `version` increment by 1."

    Design: Difficulty/priority_pair_validation_conflict/denial_reason_referential_error_outranks_action_date_temporal_error
    """
    institution = create_institution()
    record = setup_decisioned_application(
        institution["id"], application_channel="TELEPHONE",
        application_date="2026-03-20T00:00:00Z",
        demographic_overrides={
            "collection_method": "NOT_PROVIDED_BY_APPLICANT",
            "ethnicity_codes": ["INFO_NOT_PROVIDED"],
            "race_codes": ["INFO_NOT_PROVIDED"],
            "sex_code": "INFO_NOT_PROVIDED",
        },
    )

    validate_error(
        api.record_action_taken(
            record["id"],
            action_taken_payload(
                action_taken="DENIED", action_taken_date="2026-03-01T00:00:00Z",
                denial_reason_codes=[], rate_spread=None, purchaser_type=None,
            ),
            make_loan_officer_headers(),
        ),
        ApiErrorId.ERR_DENIAL_REASON_REQUIRED.value,
    )

    after = read_application(record["id"])
    assert after["action_taken"] is None
    assert after["action_taken_date"] is None
    assert after["stage"] == "DECISIONED"
