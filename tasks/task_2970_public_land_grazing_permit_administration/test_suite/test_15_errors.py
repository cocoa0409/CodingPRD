"""Envelope and rejection-code probes: the shape every response carries whatever its outcome, and
the two priority-1 and priority-2 codes that answer before the service looks anything up.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
)
from test_helpers import factories as f


def test_every_response_carries_the_declared_envelope_whatever_the_outcome():
    """A creation, a listing, a not-found and a shape failure all carry meta.api_request_id and
    meta.api_request_timestamp, and every one of the four ids is distinct — but response_type switches
    between "object", "array" and "error", the four pagination fields appear on the listing alone, and
    on a failure the payload moves into data.error_id and data.message with no resource fields beside
    them and a meta that carries nothing but the two request markers.

    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts
    with `req_`."
    PRD 2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three
    fractional digits."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of
    resources."
    PRD 2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are
    included for list endpoints."
    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD 2.3: "Listing responses carry `response_type` of `"array"` and place the array of resource
    objects directly in `data`."
    PRD 2.3: "Single-resource responses carry `response_type` of `"object"` and omit those four
    pagination fields from `meta`."
    PRD 2.3: "Every listing operation is paginated by the same two query parameters. `limit`
    controls page size: it defaults to `10` when omitted, may be no smaller than `1`, and may be no
    larger than `100`. `offset` controls the starting position: it defaults to `0` and may be no
    smaller than `0`."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."
    PRD 2.6: "Every field marked as required for the operation is present and non-null; every
    enumerated field holds one of its declared members; every field whose name ends in `_aums`,
    `_cents`, `_count`, `_days`, together with `acres`, is an integer that is not negative, with head
    counts (`planned_head_count`, `actual_head_count`, `head_count`) and `unauthorized_days` required
    to be at least 1; every field whose name ends in `_pct` is a number between 0.0 and 1.0
    inclusive; every field whose name ends in `_score` is an integer between 0 and 100 inclusive;
    `observed_utilization_pct` is an integer between 1 and 100 inclusive; date-valued fields are ISO
    8601 calendar dates in `YYYY-MM-DD` form; the allotment's `season_start` and `season_end` are
    `MM-DD` strings with no year; and instant-valued fields (`detected_at`, `current_utc`) are ISO
    8601 UTC instants with a trailing `Z`."

    Design: Corner/errors/corner_error_and_success_envelopes_have_the_declared_shape_on_invalid_payload
    """
    creation = api_client.create_allotment(
        f.allotment_payload(name="Envelope Probe Allotment", admin_unit_code="QB-170", acres=4000,
                            total_permitted_aums=120, required_pasture_rotation_count=1),
        make_officer_headers())
    assert creation.status_code == 201, creation.text
    created_body = creation.json()
    assert created_body["response_type"] == "object"
    assert is_valid_uuid(created_body["data"]["id"])
    created_meta = created_body["meta"]
    assert created_meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(created_meta["api_request_timestamp"])
    for absent in ("limit", "offset", "total_count", "has_more"):
        assert absent not in created_meta, "a single-resource meta omits the pagination fields"

    listing = api_client.list_allotments(make_specialist_headers())
    assert listing.status_code == 200, listing.text
    listed_body = listing.json()
    assert listed_body["response_type"] == "array"
    assert isinstance(listed_body["data"], list), "the array sits directly in data"
    listed_meta = listed_body["meta"]
    assert listed_meta["limit"] == 10, "the default page size"
    assert listed_meta["offset"] == 0, "the default starting position"
    assert listed_meta["total_count"] >= 1, "the allotment just created is in the collection"
    assert listed_meta["has_more"] is (
        listed_meta["offset"] + len(listed_body["data"]) < listed_meta["total_count"])

    missing = api_client.get_allotment(NON_EXISTENT_UUID, make_specialist_headers())
    assert missing.status_code == 404, missing.text
    missing_body = missing.json()
    assert missing_body["response_type"] == "error"
    assert missing_body["data"]["error_id"] == ApiErrorId.ERR_ALLOTMENT_NOT_FOUND
    assert isinstance(missing_body["data"]["message"], str)
    assert missing_body["data"]["message"] != ""
    assert "id" not in missing_body["data"], "an error payload carries no resource fields"
    assert set(missing_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}

    nameless = f.allotment_payload(admin_unit_code="QB-170", acres=4000, total_permitted_aums=120)
    del nameless["name"]
    malformed = api_client.create_allotment(nameless, make_officer_headers())
    assert malformed.status_code == 400, malformed.text
    malformed_body = malformed.json()
    assert malformed_body["response_type"] == "error"
    assert malformed_body["data"]["error_id"] == ApiErrorId.ERR_VALIDATION
    assert malformed_body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(malformed_body["meta"]["api_request_timestamp"])

    request_ids = [created_meta["api_request_id"], listed_meta["api_request_id"],
                   missing_body["meta"]["api_request_id"],
                   malformed_body["meta"]["api_request_id"]]
    assert len(set(request_ids)) == 4, "each request is identified uniquely: %r" % (request_ids,)


def test_one_validation_code_absorbs_every_shape_defect_before_any_lookup():
    """Eight bodies, eight different defects — a string where an integer belongs, a negative
    quantity, a full calendar date where a bare MM-DD season code belongs, an unknown enum member,
    a percentage above 1.0, a justification shorter than ten characters, a score above 100 and an
    email with no at-sign — and one single code answers all eight. Five of the eight carry foreign
    keys naming rows that were never minted, yet none of them reports a not-found code, because the
    shape check at priority 1 short-circuits the request before the existence checks at priorities 5
    and 6 ever run. No row survives any of the eight calls.

    PRD 2.6: "When a single request violates more than one rule, exactly one error is returned, and
    which one is fully determined."
    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 2.6: "Every field marked as required for the operation is present and non-null; every
    enumerated field holds one of its declared members; every field whose name ends in `_aums`,
    `_cents`, `_count`, `_days`, together with `acres`, is an integer that is not negative, with head
    counts (`planned_head_count`, `actual_head_count`, `head_count`) and `unauthorized_days` required
    to be at least 1; every field whose name ends in `_pct` is a number between 0.0 and 1.0
    inclusive; every field whose name ends in `_score` is an integer between 0 and 100 inclusive;
    `observed_utilization_pct` is an integer between 1 and 100 inclusive; date-valued fields are ISO
    8601 calendar dates in `YYYY-MM-DD` form; the allotment's `season_start` and `season_end` are
    `MM-DD` strings with no year; and instant-valued fields (`detected_at`, `current_utc`) are ISO
    8601 UTC instants with a trailing `Z`."
    PRD 2.6: "Three cross-field shape rules join this check: on a range improvement project
    proposal, `agency_share_pct` and `permittee_share_pct` must add up to exactly 1.0; on a
    stocking-adjustment decision, `adjustment_pct` must be greater than 0 and no greater than 0.9;
    and on a closure order, `reduction_pct` is required for a drought reduction and must be greater
    than 0.0 and no greater than 0.9, while a wildfire closure or a full closure must either omit
    `reduction_pct` altogether or send exactly 1.0 — the server records 1.0 in either case."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."
    PRD 2.6: "**Body foreign-key existence** — HTTP 404 with the entity-specific code, in the
    declared field order."
    PRD 3.1: "An `AuthorizedOfficer` registers one by supplying its `name` (between 1 and 120
    characters, and not blank), the administering field office's `admin_unit_code` (two uppercase
    letters, a hyphen, then three digits, as in `NV-042`), the `acres` of public land inside the
    boundary (at least 1), and the `total_permitted_aums` the inventory carries before any adjustment
    (also at least 1)."
    PRD 3.3: "An application is filed by an `AuthorizedOfficer` naming the `allotment_id` the
    preference attaches to, the `permittee_id` who will hold it, the `base_property_id` that
    qualifies it, the `requested_aums` of preference sought (at least 1), the `term_start_date` and
    `term_end_date` bounding the term, and the `livestock_kind`, which is `CATTLE`, `SHEEP` or
    `HORSES`."
    PRD 3.10: "The payload carries `allotment_id`, `order_type`, `effective_start_date`,
    `effective_end_date`, a `justification` of between 10 and 500 characters recording the drought
    indicators or fire perimeter relied on, and, conditionally, `reduction_pct`."
    PRD 3.2: "Registration takes only a `name` of 1 to 120 characters and a `contact_email`, which
    must contain an at-sign; the resulting record starts `IN_GOOD_STANDING` with an
    `outstanding_balance_cents` of 0 and a `billed_trespass_incident_count` of 0."

    Design: Corner/errors/corner_validation_error_covers_every_input_defect
    """
    officer = make_officer_headers()
    specialist = make_specialist_headers()
    # Priority 1 runs before priorities 5 and 6, so an id that names nothing is legal material here.
    unknown = NON_EXISTENT_UUID

    probes = [
        ("a string where acres wants an integer", api_client.create_allotment(
            f.allotment_payload(name="Bad Type Allotment", admin_unit_code="QB-171",
                                acres="twelve thousand", total_permitted_aums=400), officer)),
        ("a negative AUM quantity", api_client.create_allotment(
            f.allotment_payload(name="Negative Allotment", admin_unit_code="QB-172", acres=12000,
                                total_permitted_aums=-5), officer)),
        ("a full calendar date where a bare MM-DD season code belongs", api_client.create_allotment(
            f.allotment_payload(name="Bad Season Code Allotment", admin_unit_code="QB-173",
                                acres=12000, total_permitted_aums=400,
                                season_start="2026-01-01"), officer)),
        ("an enum member that was never declared", api_client.create_permit(
            f.permit_payload(unknown, unknown, unknown, requested_aums=100,
                             livestock_kind="GOATS"), officer)),
        ("a percentage above the 0.0-to-1.0 band", api_client.create_closure_order(
            f.closure_order_payload(unknown, reduction_pct=1.5,
                                    effective_end_date="2026-08-31"), officer)),
        ("a justification shorter than ten characters", api_client.create_closure_order(
            f.closure_order_payload(unknown, justification="dry",
                                    effective_end_date="2026-08-31"), officer)),
        ("a score above 100", api_client.create_assessment(
            f.assessment_payload(unknown, upland_score=101, riparian_score=60,
                                 water_quality_score=60), specialist)),
        ("an email with no at-sign", api_client.create_permittee(
            f.permittee_payload(name="No At Sign Ranch",
                                contact_email="billing.example.com"), officer)),
    ]

    for label, response in probes:
        body = validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
        assert body["error_id"] == ApiErrorId.ERR_VALIDATION, label

    for label, response in probes[3:7]:
        error_id = response.json()["data"]["error_id"]
        assert error_id not in (ApiErrorId.ERR_ALLOTMENT_NOT_FOUND,
                                ApiErrorId.ERR_PERMITTEE_NOT_FOUND,
                                ApiErrorId.ERR_BASE_PROPERTY_NOT_FOUND,
                                ApiErrorId.ERR_PERMIT_NOT_FOUND), (
            "the shape check answers before any lookup, so %s never reaches a 404" % label)

    for code in ("QB-171", "QB-172", "QB-173"):
        items, meta = validate_paginated(
            api_client.list_allotments(specialist, {"admin_unit_code": code, "limit": 100}))
        assert meta["total_count"] == 0, "a rejected creation leaves no row behind: %s" % code
        assert items == []

    validate_error(api_client.get_permittee(unknown, officer),
                   ApiErrorId.ERR_PERMITTEE_NOT_FOUND, 404)


def test_the_date_range_check_separates_closed_intervals_from_half_open_windows():
    """The permit term, the instruction season and the closure order are closed intervals: they fail
    only when the end precedes the start, so an instruction whose season begins and ends on the same
    day is coherent and falls through to the priority-5 lookup that reports the unknown permit. A use
    record's planned window and its reported window are half-open: there a single-day interval has
    zero length and is refused. The refusal is reported even when the acting X-User-ID names no
    permittee at all, because date-range coherence is checked at priority 2 and identity only at
    priority 3.

    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."
    PRD 2.6: "**Date-range coherence** — `ERR_INVALID_DATE_RANGE`, HTTP 400, checked before any
    record is looked up."
    PRD 2.6: "A permit's `term_start_date` must be strictly before its `term_end_date`; an operating
    instruction's `season_start_date` must be on or before its `season_end_date`; a use record's
    `planned_entry_date` must be strictly before its `planned_exit_date` and, when actual use is
    reported, its `actual_entry_date` must be strictly before its `actual_exit_date`, because a
    grazing window is half-open and a zero-length window is never valid; and a closure order's
    `effective_start_date` must be on or before its `effective_end_date`."
    PRD 2.6: "This check applies to permit application, permit renewal, permit transfer,
    operating-instruction creation, use-record scheduling, actual-use reporting and closure-order
    issuance."
    PRD 2.6: "**Identity and role** — `ERR_UNAUTHORIZED`, HTTP 403, on every operation without
    exception."
    PRD 2.6: "The rules are those of §2.1: `X-User-ID` present, non-empty and resolvable; the acting
    role listed for the operation; and a `Permittee` actor confined to rows belonging to its own
    permittee record, including the requirement that a filed appeal's `appellant_permittee_id` equal
    the acting `X-User-ID`."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left to
    right as described at the top of this subsection."

    Design: Corner/errors/corner_invalid_date_range_covers_every_dated_entity
    """
    officer = make_officer_headers()
    specialist = make_specialist_headers()
    unknown = NON_EXISTENT_UUID

    validate_error(api_client.create_permit(
        f.permit_payload(unknown, unknown, unknown, requested_aums=100,
                         term_start_date="2030-01-01", term_end_date="2026-12-31"), officer),
        ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    validate_error(api_client.create_aoi(
        f.aoi_payload(unknown, authorized_aums=100, season_start_date="2026-09-30",
                      season_end_date="2026-05-01"), specialist),
        ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    validate_error(api_client.create_use_record(unknown, f.use_record_payload(
        unknown, planned_entry_date="2026-06-01", planned_exit_date="2026-06-01",
        planned_head_count=30), specialist),
        ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    # The acting id resolves to no permittee, yet priority 2 has already decided the request.
    reported = api_client.report_actual_use(unknown, f.report_actual_use_payload(
        actual_entry_date="2026-06-10", actual_exit_date="2026-06-10", actual_head_count=30),
        make_permittee_headers(unknown))
    body = validate_error(reported, ApiErrorId.ERR_INVALID_DATE_RANGE, 400)
    assert body["error_id"] != ApiErrorId.ERR_UNAUTHORIZED, (
        "priority 2 outranks the identity check at priority 3")

    validate_error(api_client.create_closure_order(
        f.closure_order_payload(unknown, effective_start_date="2026-10-31",
                                effective_end_date="2026-08-05"), officer),
        ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    # A season that begins and ends on the same day is a coherent closed interval, so the request
    # survives priority 2 and the unknown permit_id is what finally answers.
    validate_error(api_client.create_aoi(
        f.aoi_payload(unknown, authorized_aums=100, season_start_date="2026-05-01",
                      season_end_date="2026-05-01"), specialist),
        ApiErrorId.ERR_PERMIT_NOT_FOUND, 404)
