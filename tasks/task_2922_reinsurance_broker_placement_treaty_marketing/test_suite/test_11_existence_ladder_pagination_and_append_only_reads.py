"""Reads across the flat registry: existence, pagination and append-only evidence (PRD §2.3, §2.5, §2.8, §3.7).

Queue B — section ``entities``: an unused but well-formed UUID is answered by the
entity-specific 404 of the surface it was probed against, a body-borne foreign key
is checked exactly as a path segment is, list reads carry the four pagination
fields, and the two evidence records grow by appending rather than by mutation.
"""
from test_helpers import (
    ACTUARY,
    ADMIN,
    CLOCK,
    LEAD,
    OMIT,
    UNUSED_UUID,
    UNUSED_UUID_ALT,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_capacity_invariants,
    assert_instant_equals,
    assert_money_equals,
    assert_status,
    create_cedent,
    create_program,
    create_program_payload,
    create_market_submission_payload,
    create_reinsurer_payload,
    file_document,
    list_rows,
    read_layer,
    read_program,
    set_clock,
    set_market_security,
    setup_bound_program,
    setup_program_in_market,
    validate_error,
    validate_paginated,
    validate_success,
)

# The instant the corner design files the slip on: four whole days after the
# 2026-01-01 inception, so days_from_inception floors to 4.
SLIP_FILING_INSTANT = "2026-01-05T00:00:00.000Z"
SLIP_DAYS_FROM_INCEPTION = 4

# Well-formed UUIDs that are never the id of any row in these chains.
GHOST_CEDENT_ID = "33333333-3333-4333-8333-333333333333"
GHOST_REINSURER_ID = "44444444-4444-4444-8444-444444444444"

# One cedent, three non-overlapping programs: different lines of business, so the
# overlapping-treaty-period rule at priority 50 never fires.
THREE_PROGRAM_SPECS = [
    {
        "program_name": "Northwind Property 2026",
        "line_of_business": "PROPERTY",
        "estimated_premium_income_minor": 2_000_000_000,
    },
    {
        "program_name": "Northwind Marine 2026",
        "line_of_business": "MARINE",
        "estimated_premium_income_minor": 500_000_000,
    },
    {
        "program_name": "Northwind Casualty 2026",
        "line_of_business": "CASUALTY",
        "estimated_premium_income_minor": 800_000_000,
    },
]


def _empty_registry():
    """Park the clock on an otherwise empty database."""
    set_clock(CLOCK["PLACEMENT_START"])


def _three_programs_of_one_cedent():
    """One cedent with PROPERTY, MARINE and CASUALTY 2026 files, created in that order."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    programs = [create_program(cedent["id"], **spec) for spec in THREE_PROGRAM_SPECS]
    return cedent, programs


def _bound_program_with_a_filed_slip():
    """The BOUND prologue, then a SLIP filed four days after inception."""
    ctx = setup_bound_program()
    set_clock(SLIP_FILING_INSTANT)
    ctx["slip"] = file_document(ctx["program"]["id"], "SLIP", "NW-CAT-2026-SLIP")
    return ctx


def test_unknown_registry_and_program_path_ids_return_their_own_not_found_codes():
    """Probing a cedent, market, program or exposure package that does not exist.

    PRD: "A `{cedent_id}` path segment or a body `cedent_id` must resolve to an
    existing cedent, else `ERR_CEDENT_NOT_FOUND` — this guards `GET
    /cedents/{cedent_id}`, `POST /cedents/{cedent_id}/suspension`, `GET
    /cedents/{cedent_id}/programs` and `POST /programs` (priority 8)."

    Design: Corner/entities/unknown_path_ids_on_read_endpoints_return_entity_specific_not_found
    """
    _empty_registry()

    validate_error(
        api_client.get_cedent(UNUSED_UUID, ADMIN), ApiErrorId.ERR_CEDENT_NOT_FOUND.value
    )
    validate_error(
        api_client.get_reinsurer(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_REINSURER_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_program(UNUSED_UUID, ADMIN), ApiErrorId.ERR_PROGRAM_NOT_FOUND.value
    )
    validate_error(
        api_client.get_exposure_submission(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_EXPOSURE_SUBMISSION_NOT_FOUND.value,
    )


def test_unknown_placement_path_ids_return_their_own_not_found_codes():
    """Probing a layer, market submission, quote or signing line that does not exist.

    PRD: "A `{layer_id}` segment must resolve on every `/layers/{layer_id}...`
    endpoint, else `ERR_LAYER_NOT_FOUND` (priority 13)."

    Design: Corner/entities/unknown_path_ids_on_read_endpoints_return_entity_specific_not_found
    """
    _empty_registry()

    validate_error(
        api_client.get_layer(UNUSED_UUID, ADMIN), ApiErrorId.ERR_LAYER_NOT_FOUND.value
    )
    validate_error(
        api_client.get_market_submission(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_MARKET_SUBMISSION_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_quote(UNUSED_UUID, ADMIN), ApiErrorId.ERR_QUOTE_NOT_FOUND.value
    )
    validate_error(
        api_client.get_signing_line(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_SIGNING_LINE_NOT_FOUND.value,
    )


def test_unknown_money_and_claim_path_ids_return_their_own_not_found_codes():
    """Probing a disclosure, fiduciary movement, advocacy or dispute that does not exist.

    PRD: "A `{claim_advocacy_id}` segment must resolve on every
    `/claim-advocacies/{claim_advocacy_id}...` endpoint, else
    `ERR_CLAIM_ADVOCACY_NOT_FOUND` (priority 19)."

    Design: Corner/entities/unknown_path_ids_on_read_endpoints_return_entity_specific_not_found
    """
    _empty_registry()

    validate_error(
        api_client.get_brokerage_disclosure(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_DISCLOSURE_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_fiduciary_transaction(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_TRANSACTION_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_claim_advocacy(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_CLAIM_ADVOCACY_NOT_FOUND.value,
    )
    validate_error(
        api_client.get_cession_dispute(UNUSED_UUID, ADMIN),
        ApiErrorId.ERR_CESSION_DISPUTE_NOT_FOUND.value,
    )


def test_program_create_naming_an_unknown_prior_program_is_a_not_found():
    """A renewal pointed at a prior file that does not exist is refused at priority 11.

    PRD: "A non-null `prior_program_id` in the body of `POST /programs` must resolve,
    else `ERR_PRIOR_PROGRAM_NOT_FOUND` (priority 11)."

    Design: Corner/entities/program_create_with_an_unknown_prior_program_id_is_rejected
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()

    response = api_client.create_program(
        create_program_payload(
            cedent["id"], prior_program_id=UNUSED_UUID_ALT, brokerage_pct=OMIT
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_PRIOR_PROGRAM_NOT_FOUND.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 0, f"the rejected renewal created no program, got {len(rows)} rows"


def test_program_create_naming_a_real_but_mismatched_prior_program_is_a_renewal_mismatch():
    """A 2024 predecessor cannot be the prior file of a 2026 renewal.

    PRD: "When `prior_program_id` is supplied it must reference a program of the same
    `cedent_id` and the same `line_of_business` whose `underwriting_year` is exactly
    one less than this program's; any deviation is `ERR_RENEWAL_PRIOR_MISMATCH`."

    Design: Corner/entities/program_create_with_an_unknown_prior_program_id_is_rejected
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    stale_prior = create_program(
        cedent["id"],
        program_name="Northwind Property 2024",
        underwriting_year=2024,
        inception_date="2024-01-01T00:00:00.000Z",
        expiry_date="2025-01-01T00:00:00.000Z",
    )

    response = api_client.create_program(
        create_program_payload(cedent["id"], prior_program_id=stale_prior["id"]), LEAD
    )
    validate_error(response, ApiErrorId.ERR_RENEWAL_PRIOR_MISMATCH.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"only the 2024 predecessor exists, got {len(rows)} rows"
    assert rows[0]["id"] == stale_prior["id"], "the mismatched renewal created no row"


def test_filing_a_second_document_appends_a_row_and_leaves_the_first_untouched():
    """A wording draft filed after the slip grows the trail from one row to two.

    PRD: "The placing broker files documents against a program, and each filing is
    append-only: a filed document is never mutated or deleted."

    Design: Corner/entities/contract_documents_and_renewal_reports_are_immutable_append_only_rows
    """
    ctx = _bound_program_with_a_filed_slip()
    program_id = ctx["program"]["id"]

    draft = file_document(program_id, "WORDING_DRAFT", "NW-CAT-2026-WD1")

    rows = list_rows(api_client.list_program_contract_documents(program_id, LEAD))
    assert len(rows) == 2, f"the trail holds both filings, got {len(rows)} rows"
    assert rows[0]["id"] == ctx["slip"]["id"], "the oldest filing is returned first"
    assert_status(rows[0], "document_type", "SLIP")
    assert rows[0]["wording_reference"] == "NW-CAT-2026-SLIP", (
        "the first row is unchanged by the second filing"
    )
    assert rows[1]["id"] == draft["id"], "the second filing is appended after the slip"
    assert_status(rows[1], "document_type", "WORDING_DRAFT")
    assert_instant_equals(rows[1]["issued_at"], SLIP_FILING_INSTANT, "issued_at")
    assert_status(read_program(program_id), "documentation_status", "WORDING_DRAFTED")


def test_a_slip_filed_four_days_after_inception_floors_days_from_inception_at_four():
    """Filing on 2026-01-05 against a 2026-01-01 inception records four whole days.

    PRD: "The system records the document's `program_id`, stamps `issued_at` with the
    current logical clock, records `filed_by_user_id` as the filing broker's identity,
    and computes `days_from_inception` as the whole number of days between the
    program's `inception_date` and `issued_at`: the elapsed seconds divided by eighty-six
    thousand four hundred, floored, which is negative when the document was filed
    before inception."

    Design: Corner/entities/contract_documents_and_renewal_reports_are_immutable_append_only_rows
    """
    ctx = _bound_program_with_a_filed_slip()

    assert ctx["slip"]["days_from_inception"] == SLIP_DAYS_FROM_INCEPTION, (
        "four whole days elapsed between inception and the filing, got "
        f"{ctx['slip']['days_from_inception']!r}"
    )
    assert_instant_equals(ctx["slip"]["issued_at"], SLIP_FILING_INSTANT, "issued_at")
    assert ctx["slip"]["program_id"] == ctx["program"]["id"], (
        "the document belongs to the program it was filed under"
    )


def test_a_filed_contract_document_exposes_neither_version_nor_updated_at():
    """The slip carries an id and a created_at and nothing else from the common properties.

    PRD: "A contract document carries only `id` and `created_at` from the common
    properties; it has no `updated_at` and no `version`, because there is nothing about
    it that can ever change."

    Design: Corner/entities/contract_documents_and_renewal_reports_are_immutable_append_only_rows
    """
    ctx = _bound_program_with_a_filed_slip()

    assert_append_only_fields(ctx["slip"])
    assert_instant_equals(ctx["slip"]["created_at"], SLIP_FILING_INSTANT, "created_at")

    stored = validate_success(api_client.get_contract_document(ctx["slip"]["id"], LEAD))
    assert_append_only_fields(stored)
    rows = list_rows(
        api_client.list_program_contract_documents(ctx["program"]["id"], LEAD)
    )
    assert_append_only_fields(rows[0])


def test_a_generated_renewal_report_exposes_neither_version_nor_updated_at():
    """The renewal report is written once and carries only an id and a created_at.

    PRD: "The report is append-only, carries only `id` and `created_at` from the common
    properties — no `updated_at` and no `version` — records its `program_id`, the
    generating actuary's identity as `generated_by_user_id` and the current logical
    clock as `as_of`, and answers 201."

    Design: Corner/entities/contract_documents_and_renewal_reports_are_immutable_append_only_rows
    """
    ctx = _bound_program_with_a_filed_slip()

    response = api_client.create_renewal_report(ctx["program"]["id"], ACTUARY)
    report = validate_success(response, 201)

    assert_append_only_fields(report)
    assert report["program_id"] == ctx["program"]["id"], (
        "the report belongs to the program it was generated against"
    )
    assert_instant_equals(report["as_of"], SLIP_FILING_INSTANT, "as_of")
    assert_append_only_fields(
        validate_success(api_client.get_renewal_report(report["id"], LEAD))
    )


def test_program_listing_pages_through_three_files_with_total_count_and_has_more():
    """Two pages of limit 2 over three programs report total_count 3 throughout.

    PRD: "Four pagination fields appear in the `meta` object of every list response:
    `limit` and `offset` echo the effective values used, `total_count` is the number of
    rows matching the request's filters **before** `limit` and `offset` are applied, and
    `has_more` is true exactly when the sum of `offset` and the number of rows returned
    in this page is less than `total_count`."

    Design: Corner/entities/program_listing_paginates_with_total_count_and_has_more
    """
    cedent, programs = _three_programs_of_one_cedent()

    first_response = api_client.list_programs(
        LEAD, params={"cedent_id": cedent["id"], "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)

    assert first_response.json()["response_type"] == "array", (
        "a collection is returned with response_type array"
    )
    assert len(first_rows) == 2, f"the first page holds 2 rows, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, (
        f"total_count counts the whole filtered population, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "0 + 2 is less than 3, so has_more is true"
    assert first_meta["limit"] == 2, f"limit echoes 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"offset echoes 0, got {first_meta['offset']}"
    assert first_rows[0]["id"] == programs[0]["id"], (
        "the earliest created program leads the ascending created_at order"
    )

    second_rows, second_meta = validate_paginated(
        api_client.list_programs(
            LEAD, params={"cedent_id": cedent["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_rows) == 1, f"the second page holds 1 row, got {len(second_rows)}"
    assert second_meta["total_count"] == 3, (
        f"total_count is unchanged by paging, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, "2 + 1 is not less than 3, so has_more is false"
    assert second_rows[0]["id"] == programs[2]["id"], (
        "the last page returns the most recently created program"
    )


def test_the_cedent_filter_narrows_total_count_to_the_filtered_population():
    """A second cedent's file is counted by the unfiltered read and by neither filtered one.

    PRD: "Four pagination fields appear in the `meta` object of every list response:
    `limit` and `offset` echo the effective values used, `total_count` is the number of
    rows matching the request's filters **before** `limit` and `offset` are applied, and
    `has_more` is true exactly when the sum of `offset` and the number of rows returned
    in this page is less than `total_count`."

    Design: Corner/entities/program_listing_paginates_with_total_count_and_has_more
    """
    cedent, programs = _three_programs_of_one_cedent()
    other_cedent = create_cedent(name="Southwind Mutual")
    create_program(other_cedent["id"], program_name="Southwind Property 2026")

    _all_rows, all_meta = validate_paginated(
        api_client.list_programs(LEAD, params={"limit": 10, "offset": 0})
    )
    assert all_meta["total_count"] == 4, (
        f"the unfiltered read counts every program, got {all_meta['total_count']}"
    )

    filtered_rows, filtered_meta = validate_paginated(
        api_client.list_programs(
            LEAD, params={"cedent_id": cedent["id"], "limit": 10, "offset": 0}
        )
    )
    assert filtered_meta["total_count"] == 3, (
        f"the filter narrows total_count to 3, got {filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False, "0 + 3 is not less than 3"
    assert [row["id"] for row in filtered_rows] == [
        program["id"] for program in programs
    ], "the cedent's own three files are returned in creation order"

    scoped_rows, scoped_meta = validate_paginated(
        api_client.list_cedent_programs(
            cedent["id"], LEAD, params={"limit": 10, "offset": 0}
        )
    )
    assert scoped_meta["total_count"] == 3, (
        f"the cedent-scoped read counts the same 3 rows, got {scoped_meta['total_count']}"
    )
    assert [row["id"] for row in scoped_rows] == [
        program["id"] for program in programs
    ], "the cedent-scoped read returns the same three files in the same order"


def test_a_limit_above_one_hundred_or_a_negative_offset_is_rejected():
    """limit 101 and offset -1 are both refused by the priority-7 pagination guard.

    PRD: "A `limit` that is not an integer, is below 1 or is above 100, and an `offset`
    that is not an integer or is negative, are rejected with `ERR_VALIDATION` (HTTP
    400)."

    Design: Corner/entities/pagination_limit_outside_one_to_one_hundred_is_rejected
    """
    set_clock(CLOCK["PLACEMENT_START"])
    create_cedent()

    validate_error(
        api_client.list_cedents(ADMIN, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_VALIDATION.value,
        expected_status=400,
    )
    validate_error(
        api_client.list_cedents(ADMIN, params={"limit": 10, "offset": -1}),
        ApiErrorId.ERR_VALIDATION.value,
        expected_status=400,
    )


def test_a_limit_of_exactly_one_hundred_is_accepted_and_echoed_back():
    """The declared maximum is inclusive, so limit 100 is a legal page size.

    PRD: "`limit` is an integer with a default of 10, a minimum of 1 and a maximum of
    100."

    Design: Corner/entities/pagination_limit_outside_one_to_one_hundred_is_rejected
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()

    rows, meta = validate_paginated(
        api_client.list_cedents(ADMIN, params={"limit": 100, "offset": 0})
    )

    assert len(rows) == 1, f"the only cedent is returned, got {len(rows)} rows"
    assert rows[0]["id"] == cedent["id"], "the registered cedent is the row returned"
    assert meta["total_count"] == 1, f"total_count is 1, got {meta['total_count']}"
    assert meta["limit"] == 100, f"limit echoes 100, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset echoes 0, got {meta['offset']}"


def test_a_market_read_after_a_security_change_returns_the_restricted_posture():
    """A market moved to RESTRICTED reads back RESTRICTED, with its capacity untouched.

    PRD: "The same authority sets a market's `security_status` to `APPROVED`,
    `RESTRICTED` or `SUSPENDED`, supplying a `reason` for the change."

    Design: Corner/entities/reinsurer_retrieval_reflects_the_security_status_change
    """
    set_clock(CLOCK["PLACEMENT_START"])
    market = validate_success(
        api_client.create_reinsurer(create_reinsurer_payload(), ADMIN), 201
    )
    assert_status(market, "security_status", "APPROVED")

    restricted = set_market_security(market["id"], "RESTRICTED", "Watchlist downgrade")
    assert_status(restricted, "security_status", "RESTRICTED")

    stored = validate_success(api_client.get_reinsurer(market["id"], LEAD))
    assert_status(stored, "security_status", "RESTRICTED")
    assert_money_equals(stored["capacity_limit_minor"], 1_000_000_000, "capacity_limit_minor")
    assert_money_equals(
        stored["available_capacity_minor"], 1_000_000_000, "available_capacity_minor"
    )
    assert_capacity_invariants(stored)


def test_a_security_change_increments_the_market_version_exactly_once():
    """The posture change is one mutation, so the market goes from version 1 to version 2.

    PRD: "Most resources additionally carry an `updated_at` timestamp, refreshed on
    every mutation, and a `version` integer that starts at 1 when the resource is
    created and increments by exactly one on every mutation of that resource —
    including mutations that arrive as a side effect of an operation on a different
    resource."

    Design: Corner/entities/reinsurer_retrieval_reflects_the_security_status_change
    """
    set_clock(CLOCK["PLACEMENT_START"])
    market = validate_success(
        api_client.create_reinsurer(create_reinsurer_payload(), ADMIN), 201
    )
    assert market["version"] == 1, f"a created market starts at version 1, got {market['version']}"

    restricted = set_market_security(market["id"], "RESTRICTED", "Watchlist downgrade")
    assert restricted["version"] == 2, (
        f"one mutation takes the version to 2, got {restricted['version']}"
    )

    stored = validate_success(api_client.get_reinsurer(market["id"], LEAD))
    assert stored["version"] == 2, (
        f"the read-back carries the same version 2, got {stored['version']}"
    )


def test_an_unknown_cedent_id_in_the_program_body_is_a_cedent_not_found():
    """A body-borne cedent_id is resolved exactly as a path segment would be.

    PRD: "A `{cedent_id}` path segment or a body `cedent_id` must resolve to an existing
    cedent, else `ERR_CEDENT_NOT_FOUND` — this guards `GET /cedents/{cedent_id}`, `POST
    /cedents/{cedent_id}/suspension`, `GET /cedents/{cedent_id}/programs` and `POST
    /programs` (priority 8)."

    Design: Corner/entities/foreign_keys_supplied_in_a_body_are_validated_against_the_flat_registry
    """
    ctx = setup_program_in_market(market_specs=[])

    response = api_client.create_program(
        create_program_payload(
            GHOST_CEDENT_ID,
            program_name="Ghost Property 2026",
            estimated_premium_income_minor=1_000_000_000,
            brokerage_pct=OMIT,
        ),
        LEAD,
    )
    validate_error(response, ApiErrorId.ERR_CEDENT_NOT_FOUND.value)

    rows = list_rows(api_client.list_programs(LEAD))
    assert len(rows) == 1, f"the ghost program was not created, got {len(rows)} rows"
    assert rows[0]["id"] == ctx["program"]["id"], "only the real placement file exists"


def test_an_unknown_reinsurer_id_in_the_market_submission_body_is_a_reinsurer_not_found():
    """Approaching a market that was never registered leaves the layer untouched.

    PRD: "A `{reinsurer_id}` path segment or a body `reinsurer_id` must resolve to an
    existing market, else `ERR_REINSURER_NOT_FOUND` — guarding `GET
    /reinsurers/{reinsurer_id}`, `POST /reinsurers/{reinsurer_id}/security-status`, `GET
    /reinsurers/{reinsurer_id}/signing-lines`, `GET
    /reinsurers/{reinsurer_id}/market-submissions` and `POST
    /layers/{layer_id}/market-submissions` (priority 9)."

    Design: Corner/entities/foreign_keys_supplied_in_a_body_are_validated_against_the_flat_registry
    """
    ctx = setup_program_in_market(market_specs=[])
    layer_id = ctx["layer"]["id"]

    response = api_client.create_market_submission(
        layer_id, create_market_submission_payload(GHOST_REINSURER_ID), LEAD
    )
    validate_error(response, ApiErrorId.ERR_REINSURER_NOT_FOUND.value)

    rows = list_rows(api_client.list_layer_market_submissions(layer_id, LEAD))
    assert len(rows) == 0, f"no market submission was stored, got {len(rows)} rows"
    assert_status(read_layer(layer_id), "status", "OPEN")
