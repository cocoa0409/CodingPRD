"""Refusals with a reason: the business cap that is not a schema range, the two inclusive study
gates, and the pairs of live rules whose declared order decides which reason is reported.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_ANALYST_DISCIPLINE_MISMATCH,
    ERR_INSUFFICIENT_TESTIMONY_NOTICE,
    ERR_INVALID_REQUEST,
    ERR_ITEM_COUNT_EXCEEDS_METHOD_LIMIT,
    ERR_METHOD_NOT_FOUND,
    ERR_METHOD_VALIDATION_INSUFFICIENT,
    ERR_REFERENTIAL_MISMATCH,
    ERR_STALE_EXAM_REQUEST_VERSION,
    ERR_VENDOR_CEILING_EXCEEDED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_vendor_ledger,
)
from test_helpers.factories import (
    assignment_payload,
    court_event_payload,
    examination_request_payload,
    method_validation_payload,
    vendor_engagement_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_request,
    award_engagement,
    create_method,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    register_vendor,
    release_request,
    set_clock,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
)

UNPERSISTED_METHOD_ID = "00000000-0000-4000-8000-0000000000ff"


def test_the_scope_cap_is_a_business_refusal_and_its_own_boundary_is_admitted(api):
    """Six items against a method capped at five is refused as an accreditation-scope breach rather
    than as a bad number, and a request for exactly five is raised and priced.

    PRD §3.3: "The `item_count` also faces the accreditation-scope cap: a count exceeding the
    method's `max_items_per_request` is refused with `ERR_ITEM_COUNT_EXCEEDS_METHOD_LIMIT` (HTTP
    422)."

    PRD §2.8: "**Body schema.** The body parses, carries every required field, carries no unknown
    field, and every value matches its declared type, enum domain and numeric range, else
    `ERR_INVALID_REQUEST` (400). A malformed ISO 8601 instant, a negative `item_count`, a
    `competency_level` outside 1 through 5, and a `score_pct` outside 0.00 through 100.00 all land
    here."

    Design: Corner/validations/item_count_above_the_method_limit_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=5,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0301",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    over_cap_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet one",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    at_cap_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed packet two",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])

    response = api.create_examination_request(
        examination_request_payload(
            case["id"], over_cap_item["id"], method["id"], item_count=6
        ),
        CASE_MANAGER_HEADERS,
    )
    validate_error(response, ERR_ITEM_COUNT_EXCEEDS_METHOD_LIMIT, 422)

    _rows, meta = validate_paginated(
        api.list_examination_requests(
            CASE_MANAGER_HEADERS, {"evidence_item_id": over_cap_item["id"]}
        )
    )
    assert_list_meta(meta, expected_total=0)

    admitted = validate_success(
        api.create_examination_request(
            examination_request_payload(
                case["id"], at_cap_item["id"], method["id"], item_count=5
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(admitted, item_count=5, status="QUEUED", estimated_hours=5.00)


def test_a_validation_study_at_both_boundary_figures_is_accepted(api):
    """Twelve items with a coefficient of variation of exactly 5.00 percent clears both study gates;
    eleven items alone and 5.01 percent alone each leave the method in draft.

    PRD §3.2: "The study is accepted only if it examined at least 12 items and its coefficient of
    variation is at most 5.00 percent; a study that examined fewer items or reported a higher
    coefficient is refused with `ERR_METHOD_VALIDATION_INSUFFICIENT`."

    PRD §3.2: "On success `validation_status` moves `DRAFT` → `VALIDATED`, `validated_at_utc` is
    stamped from the logical clock, and `validation_expires_at_utc` takes the supplied instant."

    Design: Corner/validations/method_validation_at_exactly_the_study_floor_and_cv_ceiling_is_admitted
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    at_boundary = create_method(
        api,
        name="FTIR Fibre Comparison Boundary",
        discipline="TRACE",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="TR-FTIR-02",
    )
    too_few_items = create_method(
        api,
        name="FTIR Fibre Comparison Understudied",
        discipline="TRACE",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="TR-FTIR-03",
    )
    too_imprecise = create_method(
        api,
        name="FTIR Fibre Comparison Imprecise",
        discipline="TRACE",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="TR-FTIR-04",
    )

    validated = validate_success(
        api.validate_method(
            at_boundary["id"],
            method_validation_payload(
                validation_study_item_count=12,
                precision_cv_pct=5.00,
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        )
    )
    assert_fields(
        validated,
        validation_status="VALIDATED",
        validation_study_item_count=12,
        precision_cv_pct=5.00,
    )
    assert_instant_equals(
        validated["validated_at_utc"], "2026-08-01T00:00:00Z", "validated_at_utc"
    )
    assert_instant_equals(
        validated["validation_expires_at_utc"],
        "2027-08-01T00:00:00Z",
        "validation_expires_at_utc",
    )

    validate_error(
        api.validate_method(
            too_few_items["id"],
            method_validation_payload(
                validation_study_item_count=11,
                precision_cv_pct=5.00,
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_METHOD_VALIDATION_INSUFFICIENT,
        422,
    )
    validate_error(
        api.validate_method(
            too_imprecise["id"],
            method_validation_payload(
                validation_study_item_count=12,
                precision_cv_pct=5.01,
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_METHOD_VALIDATION_INSUFFICIENT,
        422,
    )
    for refused in (too_few_items, too_imprecise):
        assert_fields(
            validate_success(api.get_method(refused["id"], QUALITY_MANAGER_HEADERS)),
            validation_status="DRAFT",
        )


def test_an_unknown_field_is_reported_before_an_unresolvable_method(api):
    """One body breaks the schema check and names a method that does not exist; the schema defect is
    reported, and the same body without the stray field then reports the missing method.

    PRD §2.8: "**Body schema.** The body parses, carries every required field, carries no unknown
    field, and every value matches its declared type, enum domain and numeric range, else
    `ERR_INVALID_REQUEST` (400). A malformed ISO 8601 instant, a negative `item_count`, a
    `competency_level` outside 1 through 5, and a `score_pct` outside 0.00 through 100.00 all land
    here."

    PRD §2.8: "**Body foreign keys.** Every identifier carried in the body resolves to an existing
    row of its declared entity, else that entity's not-found code (404). Body foreign keys are
    resolved after the schema check so that a syntactically invalid identifier yields 400 rather than
    404."

    Design: Corner/validations/unknown_field_outranks_the_unresolvable_method_and_returns_invalid_request
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0302",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])

    both_defects = api.create_examination_request(
        examination_request_payload(
            case["id"], item["id"], UNPERSISTED_METHOD_ID, item_count=1, rush_flag=True
        ),
        CASE_MANAGER_HEADERS,
    )
    validate_error(both_defects, ERR_INVALID_REQUEST, 400)

    only_the_missing_method = api.create_examination_request(
        examination_request_payload(
            case["id"], item["id"], UNPERSISTED_METHOD_ID, item_count=1
        ),
        CASE_MANAGER_HEADERS,
    )
    validate_error(only_the_missing_method, ERR_METHOD_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_examination_requests(CASE_MANAGER_HEADERS, {"case_id": case["id"]})
    )
    assert_list_meta(meta, expected_total=0)
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=0,
    )


def test_a_stale_version_is_reported_before_the_wrong_disciplines_examiner(api):
    """A reassignment body that is both out of date and names an out-of-discipline examiner reports
    the stale version; resupplied with the current version, the same body reports the discipline
    defect and the incumbent keeps the work.

    PRD §2.8: "**Stale-record check.** Where the endpoint declares an expected-version field, its
    value equals the parent row's current `version`, else that parent's stale-version code (412) —
    `ERR_STALE_EXAM_REQUEST_VERSION` when the parent is an examination request and
    `ERR_STALE_CASE_VERSION` when it is a case. Only the two operations named in §2.7 declare such a
    field; no other endpoint accepts one."

    PRD §2.8: "**Discipline match.** The subject analyst's `disciplines` contains the method's
    `discipline`, else `ERR_ANALYST_DISCIPLINE_MISMATCH` (409)."

    Design: Corner/validations/stale_request_version_outranks_the_discipline_mismatch
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    chemist = register_analyst(
        api,
        full_name="Conflict Chemist",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    biologist = register_analyst(
        api,
        full_name="Conflict Biologist",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0303",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed packet",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    version_at_creation = request["version"]
    incumbent_assignment = assign_request(
        api, request["id"], chemist["id"], expected_version=version_at_creation
    )
    version_after_assignment = read_request(api, request["id"])["version"]
    assert version_after_assignment != version_at_creation, (
        "Naming a holder is a mutation of the request"
    )

    validate_error(
        api.create_assignment(
            request["id"],
            assignment_payload(
                biologist["id"], version_at_creation, assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_STALE_EXAM_REQUEST_VERSION,
        412,
    )
    validate_error(
        api.create_assignment(
            request["id"],
            assignment_payload(
                biologist["id"], version_after_assignment, assignment_reason="MANUAL"
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_ANALYST_DISCIPLINE_MISMATCH,
        409,
    )

    after = read_request(api, request["id"])
    assert_fields(
        after, assigned_analyst_id=chemist["id"], version=version_after_assignment
    )
    assert_fields(
        validate_success(api.get_assignment(incumbent_assignment["id"], CASE_MANAGER_HEADERS)),
        status="ACTIVE",
    )
    assert_fields(
        validate_success(api.get_analyst(chemist["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=2.00,
    )
    assert_fields(
        validate_success(api.get_analyst(biologist["id"], QUALITY_MANAGER_HEADERS)),
        assigned_casework_hours=0.00,
    )


def test_a_request_may_not_name_another_cases_exhibit(api):
    """Both rows exist, so the refusal is a coherence failure rather than a missing exhibit, and the
    case's own exhibit is accepted immediately afterwards under the same method.

    PRD §3.3: "The named item must belong to the named case: an `evidence_item_id` whose own
    `case_id` is some other case is `ERR_REFERENTIAL_MISMATCH`."

    PRD §2.8: "**Body foreign keys.** Every identifier carried in the body resolves to an existing
    row of its declared entity, else that entity's not-found code (404). Body foreign keys are
    resolved after the schema check so that a syntactically invalid identifier yields 400 rather than
    404."

    Design: Corner/validations/examination_request_naming_another_cases_evidence_item_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
        validation_study_item_count=24,
        precision_cv_pct=2.50,
    )
    own_case = submit_case(
        api,
        agency_case_number="O-2026-0304",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    own_item = log_evidence(
        api,
        own_case["id"],
        item_number="1",
        item_description="Sealed packet C1",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, own_case["id"])
    other_case = submit_case(
        api,
        agency_case_number="O-2026-0305",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    other_item = log_evidence(
        api,
        other_case["id"],
        item_number="1",
        item_description="Sealed packet C2",
        item_type="CHEMICAL",
        seal_intact=True,
    )
    accept_case(api, other_case["id"])

    validate_error(
        api.create_examination_request(
            examination_request_payload(
                own_case["id"], other_item["id"], method["id"], item_count=1
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_REFERENTIAL_MISMATCH,
        409,
    )

    admitted = validate_success(
        api.create_examination_request(
            examination_request_payload(
                own_case["id"], own_item["id"], method["id"], item_count=1
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        admitted, evidence_item_id=own_item["id"], case_id=own_case["id"]
    )
    assert_fields(
        validate_success(api.get_case(own_case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=1,
    )
    assert_fields(
        validate_success(api.get_case(other_case["id"], CASE_MANAGER_HEADERS)),
        open_examination_request_count=0,
    )
    assert_fields(
        validate_success(api.get_evidence_item(other_item["id"], TECHNICIAN_HEADERS)),
        custody_status="IN_VAULT",
    )


def test_the_notice_floor_is_waived_by_a_subpoena_and_nothing_else(api):
    """A hearing three days out is refused on notice, and the identical hearing is admitted once the
    subpoena is declared — the block still records the three days, so the flag waives the floor
    rather than changing the count.

    PRD §3.9: "A new event has `status` `SCHEDULED` and its `notice_days` computed once at creation
    as the whole number of complete days from the current logical instant to `start_utc` — the
    interval in seconds divided by 86400, discarding any fraction."

    PRD §3.9: "The notice guard requires `notice_days` to be at least 7, else
    `ERR_INSUFFICIENT_TESTIMONY_NOTICE` — unless `subpoena_received` is true, in which case the
    notice floor is waived entirely, because a served subpoena compels attendance whatever the
    notice."

    Design: Corner/validations/testimony_notice_floor_applies_only_when_no_subpoena_was_received
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    author = register_analyst(
        api,
        full_name="Notice Author",
        disciplines=["LATENT_PRINTS"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Notice Reviewer",
        disciplines=["LATENT_PRINTS"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Cyanoacrylate Fuming and Comparison",
        discipline="LATENT_PRINTS",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="LP-CA-01",
        validation_study_item_count=20,
        precision_cv_pct=3.00,
    )
    case = submit_case(
        api,
        agency_case_number="B-2026-0306",
        submitting_agency="METRO PD",
        offense_category="BURGLARY",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed tape lift",
        item_type="LATENT_LIFT",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(api, request["id"], author["id"], expected_version=request["version"])
    release_request(api, request["id"], author["id"], reviewer["id"], actual_hours=1.00)
    assert_fields(
        read_request(api, request["id"]),
        status="RELEASED",
        assigned_analyst_id=author["id"],
    )

    short_notice = court_event_payload(
        request["id"],
        author["id"],
        start_utc="2026-08-04T09:00:00Z",
        end_utc="2026-08-04T11:00:00Z",
        court_name="County Criminal Court 3",
        docket_number="CR-2026-0306",
        subpoena_received=False,
    )
    validate_error(
        api.create_court_event(short_notice, CASE_MANAGER_HEADERS),
        ERR_INSUFFICIENT_TESTIMONY_NOTICE,
        422,
    )
    _rows, meta = validate_paginated(
        api.list_court_events(CASE_MANAGER_HEADERS, {"analyst_id": author["id"]})
    )
    assert_list_meta(meta, expected_total=0)

    under_subpoena = court_event_payload(
        request["id"],
        author["id"],
        start_utc="2026-08-04T09:00:00Z",
        end_utc="2026-08-04T11:00:00Z",
        court_name="County Criminal Court 3",
        docket_number="CR-2026-0306",
        subpoena_received=True,
    )
    admitted = validate_success(
        api.create_court_event(under_subpoena, CASE_MANAGER_HEADERS), 201
    )
    assert_fields(
        admitted,
        status="SCHEDULED",
        notice_days=3,
        subpoena_received=True,
        analyst_id=author["id"],
        examination_request_id=request["id"],
    )


def test_the_contract_ceiling_is_tested_against_the_discounted_award(api):
    """A ceiling of 96500 cents admits an award whose rush-inclusive basis is 100000 because the
    discount brings the committed figure to 96000; the next award of 25000 no longer fits and is
    refused without touching the ledger.

    PRD §3.7: "And last of all the money must fit: the vendor's `encumbered_cents` plus their
    `spent_cents` plus the newly computed `award_amount_cents` may not exceed their
    `contract_ceiling_cents`, else `ERR_VENDOR_CEILING_EXCEEDED` (HTTP 402)."

    PRD §2.8: "**Contract ceiling.** The vendor's committed and spent authority plus the newly priced
    award does not exceed the contract ceiling, else `ERR_VENDOR_CEILING_EXCEEDED` (402). This is the
    lowest-ranked gate of all: the award is priced in full, tier discount included, and every safety
    gate above it has already passed, before the money is tested."

    Design: Corner/validations/vendor_ceiling_is_tested_on_the_discounted_award_not_the_tier_basis
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vendor = register_vendor(
        api,
        name="Ceiling Order Digital Labs",
        accredited_disciplines=["DIGITAL"],
        accreditation_expires_at_utc="2027-08-01T00:00:00Z",
        concurrent_case_capacity=5,
        unit_price_cents=25000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=96500,
    )
    method = create_validated_method(
        api,
        name="Mobile Device Logical Extraction",
        discipline="DIGITAL",
        standard_hours_per_item=1.00,
        min_competency_level=2,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="DF-MOB-01",
        validation_study_item_count=12,
        precision_cv_pct=1.50,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0307",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    first_item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed handset bag one",
        item_type="DIGITAL_DEVICE",
        seal_intact=True,
    )
    second_item = log_evidence(
        api,
        case["id"],
        item_number="2",
        item_description="Sealed handset bag two",
        item_type="DIGITAL_DEVICE",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    large_request = raise_request(
        api, case["id"], first_item["id"], method["id"], item_count=4
    )
    small_request = raise_request(
        api, case["id"], second_item["id"], method["id"], item_count=1
    )

    awarded = award_engagement(
        api,
        large_request["id"],
        vendor["id"],
        window_start_utc="2026-08-02T00:00:00Z",
        window_end_utc="2026-08-12T00:00:00Z",
        rush_flag=False,
    )
    assert_fields(
        awarded,
        award_amount_cents=96000,
        tier_basis_cents=100000,
        discount_amount_cents=4000,
    )
    assert_vendor_ledger(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=96000,
        spent_cents=0,
    )

    validate_error(
        api.create_vendor_engagement(
            small_request["id"],
            vendor_engagement_payload(
                vendor["id"],
                window_start_utc="2026-08-03T00:00:00Z",
                window_end_utc="2026-08-13T00:00:00Z",
                rush_flag=False,
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_VENDOR_CEILING_EXCEEDED,
        402,
    )

    _rows, meta = validate_paginated(
        api.list_vendor_engagements(
            CASE_MANAGER_HEADERS, {"examination_request_id": small_request["id"]}
        )
    )
    assert_list_meta(meta, expected_total=0)
    assert_fields(read_request(api, large_request["id"]), status="OUTSOURCED")
    assert_fields(read_request(api, small_request["id"]), status="QUEUED")
    assert_vendor_ledger(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=96000,
        spent_cents=0,
    )
