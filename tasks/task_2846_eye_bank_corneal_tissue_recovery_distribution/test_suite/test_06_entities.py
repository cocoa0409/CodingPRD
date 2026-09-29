"""
The donor referral row and the append-only screening observation: shapes, defaults,
computed fields, reference integrity and the listing envelope.

These cases exercise the entity surface directly — one write or one read at a time —
rather than the long workflows of the other modules.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_DONOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TECHNICIAN_NOT_FOUND,
    LAB_TECHNICIAN_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    T_NOW,
    UNKNOWN_DONOR_ID,
    UNKNOWN_DONOR_ID_ALT,
    UNKNOWN_TECHNICIAN_ID,
    assert_common_fields,
    assert_instant_equals,
    assert_observation_fields,
    assert_response_type,
    assert_total_count,
    factories,
    fixtures,
    get_success_data,
    page_of,
    validate_error,
    validate_success,
)


def test_donor_creation_returns_the_computed_window_and_every_default(pinned_api):
    """
    A promptly cooled asystole referral is registered with a 960 minute window, an 18:00
    deadline and the full set of creation defaults.

    PRD 3.1: "The base window is **twelve hours — 720 minutes — when `death_time_basis` is
    `ASYSTOLE`, and eleven hours (660 minutes) when it is `PRONOUNCED`**, reflecting the
    greater confidence attached to an observed asystole."

    PRD 3.1: "Otherwise the cooling delay is the number of whole minutes from `death_at` to
    `body_cooled_at`, floored; a delay of at most four hours (240 minutes) earns a credit of
    four hours, a delay of more than four hours but at most eight hours (480 minutes) earns a
    credit of two hours (120 minutes), and a delay beyond eight hours earns nothing."

    PRD 3.1: "A newly registered donor is created with `status` `REFERRED`, `consent_type`
    and `consent_scope` both `NONE`, `authorizing_party_name` and `consent_obtained_at` both
    null, `serology_status` `PENDING`, `screening_risk_score` 0, `screening_risk_variant`
    `INTERVIEW_ONLY`, `deferral_reason` null, `lookback_flag` false,
    `tissues_recovered_count` 0 and `version` 1."

    Design: Corner/entities/donor_referral_creation_returns_the_computed_recovery_window_and_every_default
    """
    response = pinned_api.create_donor(
        factories.donor_payload(
            donor_code="D-2846-C01",
            referral_source="HOSPITAL",
            death_at="2026-08-03T02:00:00.000Z",
            death_time_basis="ASYSTOLE",
            body_cooled_at="2026-08-03T03:00:00.000Z",
            age_years=52,
            cause_of_death_category="CARDIAC",
        ),
        COORDINATOR_HEADERS,
    )

    donor = validate_success(response, 201)
    assert donor["donor_code"] == "D-2846-C01"
    assert donor["referral_source"] == "HOSPITAL"
    assert donor["death_time_basis"] == "ASYSTOLE"
    assert donor["age_years"] == 52
    assert donor["cause_of_death_category"] == "CARDIAC"
    assert donor["recovery_window_minutes"] == 960
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T18:00:00.000Z", "recovery_deadline_at"
    )
    assert donor["status"] == "REFERRED"
    assert donor["consent_type"] == "NONE"
    assert donor["consent_scope"] == "NONE"
    assert donor["authorizing_party_name"] is None
    assert donor["consent_obtained_at"] is None
    assert donor["serology_status"] == "PENDING"
    assert donor["screening_risk_score"] == 0
    assert donor["screening_risk_variant"] == "INTERVIEW_ONLY"
    assert donor["deferral_reason"] is None
    assert donor["lookback_flag"] is False
    assert donor["tissues_recovered_count"] == 0
    assert_common_fields(donor, expected_version=1, label="donor")
    assert_instant_equals(donor["created_at"], T_NOW, "created_at")
    assert_instant_equals(donor["updated_at"], T_NOW, "updated_at")


def test_donor_read_by_id_returns_the_stored_referral_row(pinned_api):
    """
    A pronounced-death referral of an elderly donor stores a 840 minute window, and reading
    it back as a lab technician returns the identical row without mutating it.

    PRD 3.1: "Otherwise the cooling delay is the number of whole minutes from `death_at` to
    `body_cooled_at`, floored; a delay of at most four hours (240 minutes) earns a credit of
    four hours, a delay of more than four hours but at most eight hours (480 minutes) earns a
    credit of two hours (120 minutes), and a delay beyond eight hours earns nothing."

    PRD 3.1: "Advanced age costs time: a donor aged 71 years or more incurs a penalty of one
    hour (60 minutes), and every younger donor incurs none."

    PRD 3.1: "Finally `recovery_deadline_at` is `death_at` advanced by
    `recovery_window_minutes`, and it is the hard cut-off past which the cornea may not be
    preserved."

    Design: Corner/entities/donor_read_by_id_returns_the_stored_referral_row
    """
    created = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-C02",
        referral_source="HOSPICE",
        death_at="2026-08-03T02:00:00.000Z",
        death_time_basis="PRONOUNCED",
        body_cooled_at="2026-08-03T04:00:00.000Z",
        age_years=75,
        cause_of_death_category="NEUROLOGIC",
    )
    assert created["recovery_window_minutes"] == 840

    donor = get_success_data(pinned_api.get_donor(created["id"], LAB_TECHNICIAN_HEADERS))

    assert donor["id"] == created["id"]
    assert donor["donor_code"] == "D-2846-C02"
    assert donor["referral_source"] == "HOSPICE"
    assert donor["death_time_basis"] == "PRONOUNCED"
    assert donor["age_years"] == 75
    assert donor["cause_of_death_category"] == "NEUROLOGIC"
    assert_instant_equals(donor["death_at"], "2026-08-03T02:00:00.000Z", "death_at")
    assert_instant_equals(
        donor["body_cooled_at"], "2026-08-03T04:00:00.000Z", "body_cooled_at"
    )
    assert donor["recovery_window_minutes"] == 840
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T16:00:00.000Z", "recovery_deadline_at"
    )
    assert donor["status"] == "REFERRED"
    assert_common_fields(donor, expected_version=1, label="donor")
    assert donor == created


def test_donor_list_is_newest_first_with_total_count_and_has_more(pinned_api):
    """
    Three referrals registered ten minutes apart page two at a time, newest first, with the
    unwindowed total and the has_more flag reported in the meta envelope.

    PRD 2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count` (the number of records matching the filter before the window is applied)
    and `has_more` (true when records remain beyond the current window)."

    PRD 2.3: "Unless a specific listing states otherwise, records are returned in ascending
    `created_at` order. The following listings override that default, and their ordering is
    part of the contract: the donor list, the shipment list and the
    tissue-evaluation-by-technician list are returned newest first; the tissue list is ordered
    by descending `preserved_at`; the recovery list by descending `dispatched_at`; the
    serology-panel list by descending `drawn_at` (invalidated panels included); the
    tissue-evaluation list for one tissue and the evaluation list for one technician by
    descending `performed_at`; the allocation list by descending `allocated_at`; the
    adverse-reaction-report list by descending `reported_at`; the lookback-investigation list
    by descending `opened_at`; the temperature-reading list by ascending `recorded_at`; and
    both surgeon-request listings by descending `priority_score` with ascending `created_at`
    as the tie-break."

    Design: Corner/entities/donor_list_is_paginated_newest_created_at_first_with_total_count_and_has_more
    """
    first = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-C03",
        referral_source="HOSPITAL",
        body_cooled_at=None,
        age_years=52,
        cause_of_death_category="CARDIAC",
    )
    fixtures.set_clock(pinned_api, "2026-08-03T06:10:00.000Z")
    second = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-C04",
        referral_source="HOSPICE",
        body_cooled_at=None,
        age_years=60,
        cause_of_death_category="TRAUMA",
    )
    fixtures.set_clock(pinned_api, "2026-08-03T06:20:00.000Z")
    third = fixtures.create_donor(
        pinned_api,
        donor_code="D-2846-C05",
        referral_source="MEDICAL_EXAMINER",
        death_time_basis="PRONOUNCED",
        body_cooled_at=None,
        age_years=44,
        cause_of_death_category="OTHER",
    )

    page_one, meta_one = page_of(pinned_api.list_donors(COORDINATOR_HEADERS, limit=2, offset=0))

    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [third["id"], second["id"]]
    assert [row["donor_code"] for row in page_one] == ["D-2846-C05", "D-2846-C04"]

    page_two, meta_two = page_of(pinned_api.list_donors(COORDINATOR_HEADERS, limit=2, offset=2))

    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(page_two) == 1
    assert page_two[0]["id"] == first["id"]
    assert page_two[0]["donor_code"] == "D-2846-C03"


def test_donor_read_with_an_unknown_uuid_yields_err_donor_not_found(pinned_api):
    """
    A syntactically valid identifier that matches no row answers 404 in the standard error
    envelope.

    PRD 2.8: "Every not-found condition carries HTTP 404 and the code named for the missing
    entity: `ERR_DONOR_NOT_FOUND`, `ERR_SEROLOGY_PANEL_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
    `ERR_RECOVERY_NOT_FOUND`, `ERR_TISSUE_NOT_FOUND`, `ERR_SURGEON_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND`."

    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/donor_read_with_an_unknown_uuid_yields_err_donor_not_found
    """
    response = pinned_api.get_donor(UNKNOWN_DONOR_ID, COORDINATOR_HEADERS)

    validate_error(response, ERR_DONOR_NOT_FOUND, 404)
    assert_response_type(response, "error")
    body = response.json()
    assert body["data"]["error_id"] == ERR_DONOR_NOT_FOUND
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""


def test_donor_create_without_death_at_is_a_400_invalid_request(pinned_api):
    """
    The clinical anchor of the record is required, and a referral omitting it is rejected
    before any row is written.

    PRD 2.10: "The body conforms to the endpoint's input schema: required fields present,
    enum values in range, numerics inside their declared bounds, datetimes in the exact
    ISO-8601 UTC form of section 2.4, and a tissue evaluation's grade fields present or absent
    exactly as its `method` demands — otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."

    Design: Corner/entities/donor_create_without_death_at_is_a_400_invalid_request
    """
    payload = factories.donor_payload(donor_code="D-2846-C06", death_at=None)
    assert "death_at" not in payload

    response = pinned_api.create_donor(payload, COORDINATOR_HEADERS)

    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert_total_count(pinned_api.list_donors(COORDINATOR_HEADERS), 0, "donors after refusal")


def test_donor_create_omitting_body_cooled_at_applies_the_null_default(pinned_api):
    """
    A body that was never refrigerated stores a null cooling instant, earns no credit and
    keeps the bare twelve-hour asystole window.

    PRD 3.1: "Alongside it the coordinator records `death_time_basis`, either `ASYSTOLE` or
    `PRONOUNCED`, describing how the instant of death was established; `body_cooled_at`, the
    instant refrigeration began, which defaults to null when the body was never cooled and
    which — when supplied — must not be earlier than `death_at`, an inversion being an invalid
    request; `age_years`, the donor's whole-year age at death, between 0 and 110 inclusive;
    and `cause_of_death_category`, one of `CARDIAC`, `TRAUMA`, `MALIGNANCY`, `NEUROLOGIC`,
    `INFECTIOUS` or `OTHER`."

    PRD 3.1: "When `body_cooled_at` is null there is no cooling delay to measure and the
    cooling credit is zero."

    Design: Corner/entities/donor_create_omitting_body_cooled_at_applies_the_null_default
    """
    payload = factories.donor_payload(
        donor_code="D-2846-C07",
        referral_source="FUNERAL_HOME",
        death_at="2026-08-03T02:00:00.000Z",
        body_cooled_at=None,
        age_years=52,
    )
    assert "body_cooled_at" not in payload

    donor = validate_success(pinned_api.create_donor(payload, COORDINATOR_HEADERS), 201)

    assert donor["body_cooled_at"] is None
    assert donor["recovery_window_minutes"] == 720
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T14:00:00.000Z", "recovery_deadline_at"
    )
    assert donor["status"] == "REFERRED"
    assert_common_fields(donor, expected_version=1, label="donor")


def test_screening_record_weight_applied_is_computed_from_the_answer(pinned_api):
    """
    A YES answer to intravenous drug use stores the question's full 40 point weight on the
    row, publishes it as the donor's interview-only risk score and moves the donor to
    SCREENING.

    PRD 3.1: "Each stored row also carries `recorded_by_user_id`, copied from the acting
    coordinator's `X-User-ID`, and `weight_applied`, which starts at 0 and is rewritten on
    every recomputation described below."

    PRD 3.1: "The weights encode the bank's clinical priorities: a family history of
    Creutzfeldt–Jakob disease (`CJD_FAMILY`) is worth 60 points, unexplained neurological
    death (`UNEXPLAINED_NEURO`) 50, intravenous drug use (`IV_DRUG_USE`) 40, HIV risk
    behaviour (`HIV_RISK`) 35, a hepatitis B or C history (`HEP_B_C_HISTORY`) 30, sepsis
    (`SEPSIS`) 25, incarceration within the last twelve months (`INCARCERATION_12M`) 15 and a
    tattoo within the last twelve months (`TATTOO_12M`) 10."

    PRD 3.1: "The **first** screening record for a donor advances that donor from `REFERRED`
    to `SCREENING`; second and later records leave `status` untouched but still trigger a full
    recomputation of the risk score."

    Design: Corner/entities/screening_record_weight_applied_is_computed_from_the_answer
    """
    donor = fixtures.create_donor(pinned_api, donor_code="D-2846-C08")

    response = pinned_api.create_screening_record(
        donor["id"],
        factories.screening_payload("IV_DRUG_USE", "YES", "SIBLING"),
        COORDINATOR_HEADERS,
    )

    record = validate_success(response, 201)
    assert record["question_code"] == "IV_DRUG_USE"
    assert record["response"] == "YES"
    assert record["historian_relationship"] == "SIBLING"
    assert record["weight_applied"] == 40
    assert record["recorded_by_user_id"] == COORDINATOR_HEADERS["X-User-ID"]
    assert_observation_fields(record, label="screening record")

    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["screening_risk_score"] == 40
    assert reread["screening_risk_variant"] == "INTERVIEW_ONLY"
    assert reread["status"] == "SCREENING"
    assert reread["version"] == 2


def test_donor_create_with_age_years_above_the_declared_bound_is_a_400(pinned_api):
    """
    An age of 130 years is outside the inclusive 0 to 110 bound, so the referral is refused
    and no donor row exists afterwards.

    PRD 3.1: "Alongside it the coordinator records `death_time_basis`, either `ASYSTOLE` or
    `PRONOUNCED`, describing how the instant of death was established; `body_cooled_at`, the
    instant refrigeration began, which defaults to null when the body was never cooled and
    which — when supplied — must not be earlier than `death_at`, an inversion being an invalid
    request; `age_years`, the donor's whole-year age at death, between 0 and 110 inclusive;
    and `cause_of_death_category`, one of `CARDIAC`, `TRAUMA`, `MALIGNANCY`, `NEUROLOGIC`,
    `INFECTIOUS` or `OTHER`."

    PRD 2.10: "The body conforms to the endpoint's input schema: required fields present,
    enum values in range, numerics inside their declared bounds, datetimes in the exact
    ISO-8601 UTC form of section 2.4, and a tissue evaluation's grade fields present or absent
    exactly as its `method` demands — otherwise `ERR_INVALID_REQUEST` (400). Applies to every
    endpoint."

    Design: Corner/entities/donor_create_with_age_years_above_the_declared_bound_is_a_400
    """
    response = pinned_api.create_donor(
        factories.donor_payload(donor_code="D-2846-C10", age_years=130), COORDINATOR_HEADERS
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert_total_count(
        pinned_api.list_donors(COORDINATOR_HEADERS), 0, "donors after out-of-bounds age"
    )


def test_screening_record_rows_are_append_only_with_no_version_field(pinned_api):
    """
    Two answers to different questions coexist as observations carrying only an id and a
    creation instant, and only the YES row contributes weight.

    PRD 2.5: "Two resources are exceptions. A `ScreeningRecord` and a `TemperatureReading`
    are append-only observations rather than mutable records: each carries only `id` and
    `created_at`. Neither has an `updated_at` and neither has a `version`, and neither field
    appears in their response payloads."

    PRD 3.1: "Whichever variant applies, `weight_applied` on every one of the donor's rows is
    rewritten to the weight that row actually contributed — the question's weight for a `YES`
    row, zero for a `NO` row, and zero for an `UNKNOWN` row whenever the predicate fails."

    Design: Corner/entities/screening_record_rows_are_append_only_with_no_version_field
    """
    donor = fixtures.create_donor(pinned_api, donor_code="D-2846-C11")
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.add_screening(pinned_api, donor["id"], "SEPSIS", "YES", "MEDICAL_RECORD")

    rows = get_success_data(
        pinned_api.list_screening_records(donor["id"], MEDICAL_DIRECTOR_HEADERS)
    )

    assert len(rows) == 2
    by_question = {row["question_code"]: row for row in rows}
    assert set(by_question) == {"TATTOO_12M", "SEPSIS"}
    assert by_question["SEPSIS"]["weight_applied"] == 25
    assert by_question["TATTOO_12M"]["weight_applied"] == 0
    for question_code, row in by_question.items():
        assert_observation_fields(row, label=f"screening record {question_code}")

    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["screening_risk_score"] == 25
    assert reread["screening_risk_variant"] == "INTERVIEW_ONLY"
    assert reread["status"] == "SCREENING"


def test_screening_record_under_an_unknown_donor_yields_err_donor_not_found(pinned_api):
    """
    The path identifier is resolved before the body is considered, so answering a history
    question for a donor that does not exist is a 404.

    PRD 2.8: "Path identifiers are resolved strictly left to right, and the first one that
    fails to resolve determines the response."

    PRD 2.10: "Every identifier in the request path resolves, left to right — otherwise the
    matching 404 code from section 2.8. Applies to every endpoint with a path identifier."

    Design: Corner/entities/screening_record_under_an_unknown_donor_yields_err_donor_not_found
    """
    response = pinned_api.create_screening_record(
        UNKNOWN_DONOR_ID_ALT,
        factories.screening_payload("HIV_RISK", "NO", "CHILD"),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_DONOR_NOT_FOUND, 404)
    assert_response_type(response, "error")


def test_recovery_dispatch_with_an_unregistered_technician_yields_err_technician_not_found(
    pinned_api,
):
    """
    A dispatch naming a technician that was never registered fails on body reference
    integrity, which sits above the donor's state gate on the refusal ladder.

    PRD 2.10: "Every foreign key in the request body resolves — otherwise the matching 404
    code. Applies to recovery dispatch, tissue evaluation, surgeon-request creation, manual
    allocation, shipment preparation and adverse-reaction reporting."

    PRD 2.8: "Every not-found condition carries HTTP 404 and the code named for the missing
    entity: `ERR_DONOR_NOT_FOUND`, `ERR_SEROLOGY_PANEL_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
    `ERR_RECOVERY_NOT_FOUND`, `ERR_TISSUE_NOT_FOUND`, `ERR_SURGEON_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND` and `ERR_INVESTIGATION_NOT_FOUND`."

    Design: Corner/entities/recovery_dispatch_with_an_unregistered_technician_yields_err_technician_not_found
    """
    donor = fixtures.create_donor(pinned_api, donor_code="D-2846-C12")
    assert donor["status"] == "REFERRED"

    response = pinned_api.create_recovery(
        factories.recovery_payload(
            donor["id"],
            UNKNOWN_TECHNICIAN_ID,
            "2026-08-03T06:30:00.000Z",
            "2026-08-03T10:00:00.000Z",
        ),
        COORDINATOR_HEADERS,
    )

    validate_error(response, ERR_TECHNICIAN_NOT_FOUND, 404)
    assert fixtures.count_recoveries(pinned_api, donor_id=donor["id"]) == 0
    assert fixtures.read_donor(pinned_api, donor["id"])["status"] == "REFERRED"
