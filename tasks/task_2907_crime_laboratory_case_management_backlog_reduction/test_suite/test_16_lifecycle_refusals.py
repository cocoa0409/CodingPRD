"""Refusals that guard a lifecycle rather than a payload: one exhibit that can only be in one pair of
hands, a catalogue entry that admits each transition once, an outsourcing loop that will not settle
before the property has moved, a testimony block that must be served and elapsed, and a discovery
axis answered out of order.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_CASE_HAS_NO_RELEASED_REQUEST,
    ERR_COURT_EVENT_INVALID_STATE,
    ERR_COURT_EVENT_NOT_ELAPSED,
    ERR_DISCOVERY_ALREADY_RECEIVED,
    ERR_DISCOVERY_NOT_PENDING,
    ERR_EVIDENCE_CUSTODY_INVALID_STATE,
    ERR_INVALID_INTERVAL,
    ERR_METHOD_INVALID_STATE,
    ERR_METHOD_NOT_CONSUMPTIVE,
    ERR_VENDOR_ENGAGEMENT_INVALID_STATE,
)
from test_helpers.assertions import assert_absent, assert_fields, assert_list_meta
from test_helpers.factories import (
    complete_analysis_payload,
    court_event_payload,
    discovery_request_payload,
    discovery_response_payload,
    method_retirement_payload,
    method_validation_payload,
    record_return_payload,
    testimony_completion_payload as _completion_payload,
    vendor_engagement_payload,
)
from test_helpers.fixtures import (
    accept_case,
    assign_request,
    award_engagement,
    complete_analysis,
    create_method,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    register_vendor,
    release_request,
    set_clock,
    ship_engagement,
    start_analysis,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
    make_analyst_headers,
)


def test_one_exhibit_serves_two_examinations_but_only_one_at_a_time(api):
    """While the exhibit is out under the first examination the second cannot start, and the
    catalogue refuses both a second validation and the retirement of a method never validated; once
    the exhibit is checked back in the second examination starts and the item has been out twice.

    PRD §3.5: "Finally the property itself must be available: the item's `custody_status` must be
    `IN_VAULT`, else `ERR_EVIDENCE_CUSTODY_INVALID_STATE`, and its `seal_intact` must be true, else
    `ERR_EVIDENCE_SEAL_BROKEN`."

    PRD §3.5: "When it is true the item is destroyed by the examination, `IN_ANALYSIS` → `CONSUMED`,
    which is terminal — and that is admissible only if the method's `is_consumptive` is true, else the
    call is refused with `ERR_METHOD_NOT_CONSUMPTIVE`."

    PRD §3.2: "Validating a method that is not `DRAFT` is `ERR_METHOD_INVALID_STATE`."

    PRD §3.2: "Retiring anything that is not `VALIDATED` is `ERR_METHOD_INVALID_STATE`."

    PRD §3.5: "The item moves `IN_VAULT` → `IN_ANALYSIS` and its `checkout_count` increases by 1 —
    that counter records how many times the item has been checked out over its whole life, which is
    exactly once per revision round of the work performed on it."

    Design: Corner/errors/evidence_custody_and_method_lifecycle_violations_are_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Custody Cycle Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    screening = create_validated_method(
        api,
        name="Serology Screening",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        is_consumptive=False,
        accreditation_scope_code="BIO-SER-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    species = create_validated_method(
        api,
        name="Species Determination",
        discipline="BIOLOGY",
        standard_hours_per_item=2.00,
        min_competency_level=2,
        max_items_per_request=6,
        is_consumptive=True,
        accreditation_scope_code="BIO-SPC-01",
        validation_study_item_count=16,
        precision_cv_pct=3.00,
    )
    never_validated = create_method(
        api,
        name="Draft Presumptive Screen",
        discipline="BIOLOGY",
        standard_hours_per_item=3.00,
        min_competency_level=2,
        accreditation_scope_code="BIO-DRF-01",
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0501",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed stain cutting",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    first = raise_request(api, case["id"], item["id"], screening["id"], item_count=1)
    second = raise_request(api, case["id"], item["id"], species["id"], item_count=1)
    assign_request(api, first["id"], examiner["id"], expected_version=first["version"])
    assign_request(api, second["id"], examiner["id"], expected_version=second["version"])
    start_analysis(api, first["id"], examiner["id"])

    validate_error(
        api.start_analysis(second["id"], make_analyst_headers(examiner["id"])),
        ERR_EVIDENCE_CUSTODY_INVALID_STATE,
        409,
    )
    assert_fields(read_request(api, second["id"]), status="ASSIGNED")

    validate_error(
        api.complete_analysis(
            first["id"],
            complete_analysis_payload(actual_hours=4.00, evidence_consumed=True),
            make_analyst_headers(examiner["id"]),
        ),
        ERR_METHOD_NOT_CONSUMPTIVE,
        409,
    )
    still_open = read_request(api, first["id"])
    assert_fields(still_open, status="IN_ANALYSIS")
    assert_absent(still_open, "actual_hours_logged")

    validate_error(
        api.validate_method(
            screening["id"],
            method_validation_payload(
                validation_study_item_count=20,
                precision_cv_pct=1.50,
                expires_at_utc="2028-08-01T00:00:00Z",
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_METHOD_INVALID_STATE,
        409,
    )
    assert_fields(
        validate_success(api.get_method(screening["id"], QUALITY_MANAGER_HEADERS)),
        precision_cv_pct=2.00,
        validation_expires_at_utc="2027-08-01T00:00:00Z",
    )

    validate_error(
        api.retire_method(
            never_validated["id"],
            method_retirement_payload("Never validated"),
            QUALITY_MANAGER_HEADERS,
        ),
        ERR_METHOD_INVALID_STATE,
        409,
    )
    assert_fields(
        validate_success(api.get_method(never_validated["id"], QUALITY_MANAGER_HEADERS)),
        validation_status="DRAFT",
    )

    finished = complete_analysis(
        api, first["id"], examiner["id"], actual_hours=4.00, evidence_consumed=False
    )
    assert_fields(finished, status="TECH_REVIEW", actual_hours_logged=4.00)

    resumed = start_analysis(api, second["id"], examiner["id"])
    assert_fields(resumed, status="IN_ANALYSIS")
    assert_fields(
        validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS)),
        custody_status="IN_ANALYSIS",
        checkout_count=2,
    )


def test_a_degenerate_custody_window_and_an_unshipped_return_are_both_refused(api):
    """A window that ends where it starts is a payload-shape refusal before any vendor arithmetic
    runs, and the settled return is refused while the property has not left the building; once
    shipment is confirmed the identical invoice settles the ledger exactly.

    PRD §2.8: "An interval whose endpoints are not strictly increasing — a vendor custody window whose
    `window_end_utc` is at or before its `window_start_utc`, or a testimony block whose `end_utc` is
    at or before its `start_utc` — is refused with `ERR_INVALID_INTERVAL` (HTTP 422), and this is
    established before any capacity arithmetic that would consume the interval."

    PRD §3.7: "Recording the vendor's return closes the fiscal and custodial loops together and is
    admissible only from `AT_VENDOR`."

    PRD §3.7: "The vendor's ledger then settles: `encumbered_cents` decreases by `award_amount_cents`
    and `spent_cents` increases by `final_invoice_cents`."

    PRD §3.7: "The request rejoins the internal path, moving `OUTSOURCED` → `TECH_REVIEW`, and its own
    `vendor_custody_days` is refreshed to the sum of `custody_days` over that request's `RETURNED`
    engagements — 0.00 for a request that was never outsourced."

    Design: Corner/errors/vendor_engagement_interval_and_out_of_state_return_are_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vendor = register_vendor(
        api,
        name="Cascade Forensic Services",
        accredited_disciplines=["BIOLOGY"],
        accreditation_expires_at_utc="2027-01-01T00:00:00Z",
        concurrent_case_capacity=2,
        unit_price_cents=50000,
        rush_surcharge_pct=0.20,
        contract_ceiling_cents=1000000,
    )
    method = create_validated_method(
        api,
        name="Outsourced DNA Quant",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        accreditation_scope_code="BIO-QNT-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0502",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed reference sample",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)

    validate_error(
        api.create_vendor_engagement(
            request["id"],
            vendor_engagement_payload(
                vendor["id"],
                window_start_utc="2026-08-10T00:00:00Z",
                window_end_utc="2026-08-10T00:00:00Z",
            ),
            CASE_MANAGER_HEADERS,
        ),
        ERR_INVALID_INTERVAL,
        422,
    )
    assert_fields(read_request(api, request["id"]), status="QUEUED")
    assert_fields(
        validate_success(api.get_vendor(vendor["id"], CASE_MANAGER_HEADERS)),
        encumbered_cents=0,
    )

    engagement = award_engagement(
        api,
        request["id"],
        vendor["id"],
        window_start_utc="2026-08-10T00:00:00Z",
        window_end_utc="2026-08-20T00:00:00Z",
    )
    assert_fields(engagement, status="AWARDED", award_amount_cents=50000)
    assert_fields(read_request(api, request["id"]), status="OUTSOURCED")

    validate_error(
        api.record_return(
            engagement["id"], record_return_payload(50000), CASE_MANAGER_HEADERS
        ),
        ERR_VENDOR_ENGAGEMENT_INVALID_STATE,
        409,
    )
    unsettled = validate_success(
        api.get_vendor_engagement(engagement["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(unsettled, status="AWARDED")
    assert_absent(unsettled, "final_invoice_cents")

    shipped = ship_engagement(api, engagement["id"])
    assert_fields(shipped, status="AT_VENDOR")

    settled = validate_success(
        api.record_return(
            engagement["id"], record_return_payload(50000), CASE_MANAGER_HEADERS
        )
    )
    assert_fields(settled, status="RETURNED", variance_cents=0)
    assert_fields(read_request(api, request["id"]), status="TECH_REVIEW")
    assert_fields(
        validate_success(api.get_vendor(vendor["id"], CASE_MANAGER_HEADERS)),
        encumbered_cents=0,
        spent_cents=50000,
    )


def test_testimony_cannot_be_recorded_unconfirmed_or_before_the_hearing_ends(api):
    """The first completion attempt is refused because the block was never confirmed and the second
    because the hearing has not finished; the clock standing exactly on the end instant is late enough,
    and only that last call writes the note.

    PRD §3.9: "An event is then confirmed, completed or cancelled. Confirmation carries no body,
    requires `status` `SCHEDULED` else `ERR_COURT_EVENT_INVALID_STATE`, moves the event to `CONFIRMED`
    and sets `subpoena_received` to true, service being what confirmation records; the block's
    occupation of the calendar is unchanged, since both `SCHEDULED` and `CONFIRMED` occupy. Completion
    carries a `testimony_note`, is admissible only from `CONFIRMED` else `ERR_COURT_EVENT_INVALID_STATE`,
    and additionally requires the current logical instant to be at or after `end_utc`, else
    `ERR_COURT_EVENT_NOT_ELAPSED` — testimony cannot be recorded as given before the hearing has
    finished, though recording it at exactly `end_utc` is allowed."

    PRD §3.9: "A new event has `status` `SCHEDULED` and its `notice_days` computed once at creation as
    the whole number of complete days from the current logical instant to `start_utc` — the interval in
    seconds divided by 86400, discarding any fraction."

    Design: Corner/errors/court_event_completion_is_rejected_before_confirmation_and_before_the_end_instant
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Testimony Bench Examiner",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    peer = register_analyst(
        api,
        full_name="Testimony Peer Reviewer",
        disciplines=["BIOLOGY"],
        competency_level=5,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Court Ready STR",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        accreditation_scope_code="BIO-STR-02",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0503",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(api, request["id"], examiner["id"], expected_version=request["version"])
    released = release_request(
        api, request["id"], examiner["id"], peer["id"], actual_hours=4.00
    )
    assert_fields(released, status="RELEASED")

    hearing = validate_success(
        api.create_court_event(
            court_event_payload(
                request["id"],
                examiner["id"],
                start_utc="2026-08-20T14:00:00Z",
                end_utc="2026-08-20T16:00:00Z",
                court_name="Ninth District Court",
                docket_number="CR-2026-8891",
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(hearing, status="SCHEDULED", notice_days=19)

    validate_error(
        api.complete_court_event(
            hearing["id"],
            _completion_payload("Premature completion attempt"),
            CASE_MANAGER_HEADERS,
        ),
        ERR_COURT_EVENT_INVALID_STATE,
        409,
    )
    unconfirmed = validate_success(api.get_court_event(hearing["id"], CASE_MANAGER_HEADERS))
    assert_fields(unconfirmed, status="SCHEDULED")
    assert_absent(unconfirmed, "testimony_note")

    confirmed = validate_success(
        api.confirm_court_event(hearing["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(confirmed, status="CONFIRMED", subpoena_received=True)

    validate_error(
        api.complete_court_event(
            hearing["id"],
            _completion_payload("Still one instant early"),
            CASE_MANAGER_HEADERS,
        ),
        ERR_COURT_EVENT_NOT_ELAPSED,
        409,
    )
    assert_fields(
        validate_success(api.get_court_event(hearing["id"], CASE_MANAGER_HEADERS)),
        status="CONFIRMED",
    )

    set_clock(api, "2026-08-20T16:00:00Z")
    note = "Testified for two hours; defence cross-examined on the mixture interpretation"
    testified = validate_success(
        api.complete_court_event(
            hearing["id"], _completion_payload(note), CASE_MANAGER_HEADERS
        )
    )
    assert_fields(testified, status="TESTIFIED", testimony_note=note)


def test_the_discovery_axis_refuses_each_step_taken_out_of_turn(api):
    """Answering before a demand arrives, a second demand on the same case, and a fulfilment with no
    released findings each carry their own code; a denial with a reason is admissible on the very case
    that could not be fulfilled, and the casework axis never moves.

    PRD §3.9: "The case's `discovery_status` must be `NONE`, else `ERR_DISCOVERY_ALREADY_RECEIVED`,
    since a second demand on the same case is a duplicate rather than a new obligation, and the case's
    `workflow_status` must be one of `ACCEPTED`, `AWAITING_ASSIGNMENT`, `IN_PROGRESS` or `REPORTED`,
    else `ERR_CASE_INVALID_STATE`. On success `discovery_status` becomes `RECEIVED`,
    `discovery_requested_at_utc` is stamped from the logical clock, and `discovery_due_utc` is set to
    that instant advanced by 30 days."

    PRD §3.9: "Answering the demand is likewise the `CaseManager`'s act and requires
    `discovery_status` to be `RECEIVED`, else `ERR_DISCOVERY_NOT_PENDING`."

    PRD §3.9: "`FULFILL` moves `discovery_status` to `FULFILLED` and requires the case to have at least
    one `RELEASED` examination request, else `ERR_CASE_HAS_NO_RELEASED_REQUEST` — there is nothing to
    disclose from a case that has released no findings."

    PRD §3.9: "Answering exactly at `discovery_due_utc` is on time and raises no finding."

    Design: Corner/errors/discovery_axis_responses_are_rejected_out_of_order
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    case = submit_case(
        api,
        agency_case_number="O-2026-0504",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed envelope",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])

    validate_error(
        api.respond_to_discovery(
            case["id"], discovery_response_payload("FULFILL"), CASE_MANAGER_HEADERS
        ),
        ERR_DISCOVERY_NOT_PENDING,
        409,
    )
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        discovery_status="NONE",
    )

    received = validate_success(
        api.request_discovery(
            case["id"],
            discovery_request_payload("Office of the Public Defender"),
            CASE_MANAGER_HEADERS,
        )
    )
    assert_fields(
        received,
        discovery_status="RECEIVED",
        discovery_due_utc="2026-08-31T00:00:00Z",
    )

    validate_error(
        api.request_discovery(
            case["id"],
            discovery_request_payload("Private counsel for the co-defendant"),
            CASE_MANAGER_HEADERS,
        ),
        ERR_DISCOVERY_ALREADY_RECEIVED,
        409,
    )
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        discovery_requesting_party="Office of the Public Defender",
    )

    validate_error(
        api.respond_to_discovery(
            case["id"], discovery_response_payload("FULFILL"), CASE_MANAGER_HEADERS
        ),
        ERR_CASE_HAS_NO_RELEASED_REQUEST,
        409,
    )
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        released_examination_request_count=0,
    )

    denied = validate_success(
        api.respond_to_discovery(
            case["id"],
            discovery_response_payload(
                "DENY",
                response_note="No analytical report exists; nothing responsive to produce",
            ),
            CASE_MANAGER_HEADERS,
        )
    )
    assert_fields(denied, discovery_status="DENIED", workflow_status="ACCEPTED")

    _rows, meta = validate_paginated(
        api.list_nonconformances(QUALITY_MANAGER_HEADERS, {"source": "DEADLINE_MISS"})
    )
    assert_list_meta(meta, expected_total=0)
