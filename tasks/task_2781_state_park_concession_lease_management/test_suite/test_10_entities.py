"""Entity-surface breadth: creation echoes, seeded defaults, computed
projections, system-field discipline, reference resolution and listing meta."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_append_only_record,
    assert_fields,
    assert_freshly_created,
    assert_null,
    assert_pct_equals,
    assert_status,
)

GORGE_PARK = {
    "name": "Whitewater Gorge State Park",
    "region_code": "SE",
    "annual_visitation": 315000,
    "comparable_lodging_rate_cents": 17500,
    "comparable_meal_rate_cents": 2800,
    "comparable_activity_rate_cents": 6400,
}


def test_park_registration_returns_201_with_its_benchmarks_and_seeded_counters(api):
    """PRD §3.1: "Everything begins with the park. A `ProgramAdministrator` registers each state park with its `name`, its administrative `region_code` — one of `NW`, `NE`, `SW` or `SE` — and its prior-year visitor count as `annual_visitation`, which must not be negative."
    PRD §3.1: "Three further figures are the reason the park register exists at all: `comparable_lodging_rate_cents`, `comparable_meal_rate_cents` and `comparable_activity_rate_cents` are the regional benchmark rates for a night's lodging, a meal and a guided activity, each of which must be strictly greater than zero."
    PRD §3.1: "A newly registered park has `status` `OPERATING` (the alternative value being `CLOSED`) and an `open_closure_window_count` of 0."
    PRD §4: "Requests that create a brand-new record return **201 Created** — that is, park registration, opportunity creation, prospectus drafting, offeror registration, proposal submission, score-sheet filing, the award (which mints both a lease and its performance bond), capital improvement proposal, operating plan submission, gross receipts report filing, fee reconciliation, audit engagement opening and compliance action issuance."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."

    Design: Corner/entities/park_creation_returns_201_with_benchmark_rates_and_zero_closure_count
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)

    response = api.create_park(dict(GORGE_PARK), X.admin_headers())
    validate_success(response, 201)
    park = get_success_data(response)

    assert_fields(park, GORGE_PARK)
    assert park["open_closure_window_count"] == 0, (
        f"open_closure_window_count: expected 0, got {park['open_closure_window_count']!r}"
    )
    assert_status(park, "OPERATING")
    assert_freshly_created(park)
    assert is_valid_uuid(park["id"]), f"id must be a server-minted UUID, got {park['id']!r}"


def test_park_read_returns_the_stored_row_without_bumping_its_version(api):
    """PRD §4: "| GET | `/parks/{id}` | Reads one park including its live `open_closure_window_count`. | All roles |"
    PRD §2.5: "Field visibility follows a simple rule: every field named in this document, whether the client supplied it, the system stamped it, or a formula computed it, is present in the resource object returned for that entity."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."

    Design: Corner/entities/park_retrieval_returns_the_stored_row_unchanged
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    created = get_success_data(api.create_park(dict(GORGE_PARK), X.admin_headers()), 201)

    response = api.get_park(created["id"], X.specialist_headers())
    validate_success(response, 200)
    park = get_success_data(response)

    assert park["id"] == created["id"], "the read must address the row that was created"
    assert_fields(park, GORGE_PARK)
    assert park["open_closure_window_count"] == 0, (
        f"open_closure_window_count: expected 0, got {park['open_closure_window_count']!r}"
    )
    assert park["version"] == 1, f"a read must not advance version, got {park['version']!r}"


def test_offeror_listing_reports_the_unpaginated_count_and_page_exhaustion(api):
    """PRD §2.3: "Every list endpoint is paginated by two optional query parameters."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` as the number of rows matching the filters before pagination, and `has_more` as true when rows remain beyond the current page."
    PRD §2.3: "Results are ordered by `created_at` ascending on every list endpoint; where two rows share a `created_at`, insertion order breaks the tie."
    PRD §3.3: "Offerors are created `ELIGIBLE`."

    Design: Corner/entities/offeror_listing_paginates_with_total_count_and_has_more
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    for legal_name, capacity in (
        ("Alder Ridge Outfitters LLC", 40000000),
        ("Basin Marina Group Inc", 60000000),
        ("Cedar Hollow Hospitality LLC", 50000000),
    ):
        X.register_offeror(api, legal_name=legal_name, bond_capacity_cents=capacity)

    first_page, first_meta = validate_paginated(
        api.list_offerors(X.award_officer_headers(), {"limit": 2, "offset": 0})
    )
    assert first_meta["limit"] == 2, f"meta.limit: expected 2, got {first_meta['limit']!r}"
    assert first_meta["offset"] == 0, f"meta.offset: expected 0, got {first_meta['offset']!r}"
    assert first_meta["total_count"] >= 3, (
        f"total_count must count every registered offeror, got {first_meta['total_count']}"
    )
    assert len(first_page) == 2, f"expected exactly 2 rows on the page, got {len(first_page)}"
    assert first_meta["has_more"] is True, "rows remain beyond a 2-row page of at least 3 rows"

    total = first_meta["total_count"]
    last_page, last_meta = validate_paginated(
        api.list_offerors(X.award_officer_headers(), {"limit": 2, "offset": total - 1})
    )
    assert last_meta["total_count"] == total, (
        "total_count is the count before pagination and must not change with offset"
    )
    assert len(last_page) == 1, f"expected the single trailing row, got {len(last_page)}"
    assert last_meta["has_more"] is False, "no rows remain beyond the final page"


def test_lease_read_with_an_unassigned_id_returns_lease_not_found(api):
    """PRD §2.9: "3. **Path resource existence** — the `{id}` path segment resolves to a row of the addressed collection, else the collection's own not-found code: `ERR_PARK_NOT_FOUND`, `ERR_OPPORTUNITY_NOT_FOUND`, `ERR_PROSPECTUS_NOT_FOUND`, `ERR_OFFEROR_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_IMPROVEMENT_NOT_FOUND`, `ERR_OPERATING_PLAN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND` or `ERR_COMPLIANCE_ACTION_NOT_FOUND`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/lease_get_with_unknown_id_returns_lease_not_found
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)

    response = api.get_lease(NON_EXISTENT_UUID, X.award_officer_headers())
    error = validate_error(response, "ERR_LEASE_NOT_FOUND", 404)
    assert error["message"].strip(), "the error envelope must carry a human-readable message"


def test_prospectus_draft_without_scoring_mode_is_an_invalid_request(api):
    """PRD §2.9: "6. **Request shape** — every required field present and non-null, every enum value a declared member, every `*_cents` field an integer inside its declared bound, every `*_pct` field carrying at most two decimals inside its declared bound, every date field in `YYYY-MM-DD` form and every instant field a valid ISO 8601 UTC timestamp, else `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "`scoring_mode` selects which of the two composite-score variants will be applied to every proposal on this solicitation and is either `PER_CRITERION_ROUNDING` or `FINAL_ROUNDING`; the choice is made once, at drafting time, and cannot be revisited."

    Design: Corner/entities/prospectus_create_missing_required_scoring_mode_returns_invalid_request
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    opportunity = X.create_opportunity(api, park["id"])
    X.record_market_analysis(api, opportunity["id"])

    payload = {
        "opportunity_id": opportunity["id"],
        "minimum_franchise_fee_pct": 4.00,
        "minimum_annual_guarantee_cents": 6000000,
        "term_years": 10,
        "submission_deadline": "2027-02-01T00:00:00Z",
        "weight_experience": 20,
        "weight_operating_plan": 25,
        "weight_capital_investment": 20,
        "weight_financial_capacity": 15,
        "weight_fee_offer": 20,
        "min_technical_score": 70.00,
    }
    validate_error(
        api.create_prospectus(payload, X.specialist_headers()), "ERR_INVALID_REQUEST", 400
    )

    _rows, meta = validate_paginated(
        api.list_prospectuses(X.specialist_headers(), {"opportunity_id": opportunity["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected draft must not have been persisted, found {meta['total_count']} rows"
    )


def test_new_opportunity_holds_null_market_fields_and_draft_status(api):
    """PRD §3.1: "The opportunity is born in `DRAFT` with no market figures at all: `comparable_gross_receipts_cents`, `market_capture_pct`, `estimated_annual_gross_receipts_cents` and `analyst_note` are all null."
    PRD §3.1: "A `ConcessionSpecialist` opens the commercial conversation by creating a **concession opportunity** against a park: the payload names the `park_id`, gives the opportunity a `title`, declares the `service_category` — `LODGING`, `FOOD_SERVICE`, `RETAIL`, `GUIDED_ACTIVITY` or `MARINA` — and states `required_capital_investment_cents`, the capital investment the agency intends to require of whoever wins, which may be zero but not negative."
    PRD §2.5: "Computed and system fields that have not yet been established are returned as null rather than omitted."

    Design: Corner/entities/opportunity_create_defaults_market_fields_to_null_and_status_to_draft
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)

    response = api.create_opportunity(
        {
            "park_id": park["id"],
            "title": "Cedar Hollow Marina Concession",
            "service_category": "MARINA",
            "required_capital_investment_cents": 12000000,
        },
        X.specialist_headers(),
    )
    validate_success(response, 201)
    opportunity = get_success_data(response)

    assert_status(opportunity, "DRAFT")
    assert_null(
        opportunity,
        "comparable_gross_receipts_cents",
        "market_capture_pct",
        "estimated_annual_gross_receipts_cents",
        "analyst_note",
    )
    assert_fields(
        opportunity,
        {"service_category": "MARINA", "required_capital_investment_cents": 12000000},
    )
    assert_freshly_created(opportunity)


def test_market_analysis_rounds_the_projection_half_up_to_whole_cents(api):
    """PRD §3.1: "The projection itself is deliberately simple: `estimated_annual_gross_receipts_cents` is the comparable's receipts multiplied by `market_capture_pct` and divided by one hundred, with the result rounded half up to whole cents."
    PRD §2.6: "Every money formula that divides — every percentage application, every proration, every amortization — rounds its result to a whole number of cents using round-half-up (a value exactly at the midpoint rounds away from zero, so 1,250.5 cents becomes 1,251 cents)."
    PRD §3.1: "Recording the analysis moves a `DRAFT` opportunity to `ANALYSIS_COMPLETE`, and on an opportunity already at `ANALYSIS_COMPLETE` it is a self-loop that leaves the status where it is while recomputing the projection from the new comparables — the analysis may be redone any number of times until an officer clears the opportunity."

    Design: Corner/entities/market_analysis_projection_computes_estimated_annual_gross_receipts
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    opportunity = X.create_opportunity(
        api,
        park["id"],
        title="Cedar Hollow Trading Post",
        service_category="RETAIL",
        required_capital_investment_cents=8000000,
    )

    response = api.record_market_analysis(
        opportunity["id"],
        {
            "comparable_gross_receipts_cents": 123456789,
            "market_capture_pct": 37.50,
            "analyst_note": "Regional gift-shop comparables, shoulder-season adjusted.",
        },
        X.specialist_headers(),
    )
    validate_success(response, 200)
    analysed = get_success_data(response)

    assert analysed["estimated_annual_gross_receipts_cents"] == 46296296, (
        "123,456,789 at 37.50 percent is 46,296,295.875 cents, which rounds half up to "
        f"46,296,296; got {analysed['estimated_annual_gross_receipts_cents']!r}"
    )
    assert analysed["comparable_gross_receipts_cents"] == 123456789
    assert_pct_equals(analysed["market_capture_pct"], "37.50", "market_capture_pct")
    assert analysed["analyst_note"] == (
        "Regional gift-shop comparables, shoulder-season adjusted."
    )
    assert_status(analysed, "ANALYSIS_COMPLETE")


def test_offeror_registration_discards_client_supplied_system_fields(api):
    """PRD §2.5: "Every persisted record carries an `id` that is a server-minted UUID with no type prefix — clients never supply it — and a `created_at` timestamp in ISO 8601 UTC form with exactly three fractional-second digits."
    PRD §2.9: "Unknown fields are ignored rather than rejected."
    PRD §3.3: "An **offeror** record carries its `legal_name`, a `contact_email` for correspondence, and `bond_capacity_cents` — the maximum penal sum its surety has attested it can post, which must be strictly positive."
    PRD §3.3: "Offerors are created `ELIGIBLE`."

    Design: Corner/entities/offeror_create_with_client_supplied_status_and_id_input_ignored
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)

    response = api.create_offeror(
        {
            "legal_name": "Basin Marina Group Inc",
            "contact_email": "bids@basinmarina.example",
            "bond_capacity_cents": 60000000,
            "status": "DEBARRED",
            "id": "client-chosen-id",
            "version": 99,
        },
        X.admin_headers(),
    )
    validate_success(response, 201)
    offeror = get_success_data(response)

    assert_status(offeror, "ELIGIBLE")
    assert offeror["id"] != "client-chosen-id", "the id must be minted by the server"
    assert is_valid_uuid(offeror["id"]), f"id must be a UUID, got {offeror['id']!r}"
    assert_freshly_created(offeror)
    assert_fields(
        offeror,
        {"legal_name": "Basin Marina Group Inc", "bond_capacity_cents": 60000000},
    )


def test_park_registration_with_an_undeclared_region_code_is_rejected(api):
    """PRD §3.1: "Everything begins with the park. A `ProgramAdministrator` registers each state park with its `name`, its administrative `region_code` — one of `NW`, `NE`, `SW` or `SE` — and its prior-year visitor count as `annual_visitation`, which must not be negative."
    PRD §2.9: "6. **Request shape** — every required field present and non-null, every enum value a declared member, every `*_cents` field an integer inside its declared bound, every `*_pct` field carrying at most two decimals inside its declared bound, every date field in `YYYY-MM-DD` form and every instant field a valid ISO 8601 UTC timestamp, else `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/park_create_with_unknown_region_code_returns_invalid_request
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)

    response = api.create_park(
        {
            "name": "Prairie Bend State Park",
            "region_code": "CENTRAL",
            "annual_visitation": 210000,
            "comparable_lodging_rate_cents": 15000,
            "comparable_meal_rate_cents": 2500,
            "comparable_activity_rate_cents": 5000,
        },
        X.admin_headers(),
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)


def test_filed_score_sheet_carries_no_version_and_no_updated_at(api):
    """PRD §2.5: "The single exception is the panel score sheet. A `ProposalEvaluation` is append-only and immutable, so it carries only `id` and `created_at`; it has no `updated_at` field and no `version` field at all. Nothing in the system ever rewrites a filed score sheet."
    PRD §2.1: "It is nevertheless recorded where a transition says so: the officer who awards a lease is stored as `awarded_by_user_id`, the officer who executes it as `executed_by_user_id`, and the panelist who files a score sheet as `panelist_user_id`."

    Design: Corner/entities/proposal_evaluation_row_carries_no_version_and_has_no_update_endpoint
    """
    ctx = X.setup_issued_prospectus(api)
    proposal = X.submit_proposal(api, ctx["prospectus_id"], ctx["offeror_id"])
    X.begin_review(api, proposal["id"])
    sheet = X.file_evaluation(api, proposal["id"], "panelist-01", **X.PANEL_SCORES_ONE)

    response = api.get_proposal_evaluation(sheet["id"], X.auditor_headers())
    validate_success(response, 200)
    evaluation = get_success_data(response)

    assert evaluation["proposal_id"] == proposal["id"]
    assert evaluation["panelist_user_id"] == "panelist-01", (
        f"panelist_user_id: expected panelist-01, got {evaluation['panelist_user_id']!r}"
    )
    assert evaluation["score_experience"] == 81
    assert evaluation["score_fee_offer"] == 71
    assert_append_only_record(evaluation)


def test_opportunity_creation_resolves_its_park_reference_first(api):
    """PRD §2.9: "4. **Body foreign-key existence** — every reference carried in the request body resolves, and references are resolved left to right in the order the fields are listed for that endpoint."
    PRD §2.9: "A `park_id` that does not resolve on opportunity creation yields `ERR_PARK_NOT_FOUND`; an `opportunity_id` on prospectus creation yields `ERR_OPPORTUNITY_NOT_FOUND`; on proposal creation `prospectus_id` is resolved first and yields `ERR_PROSPECTUS_NOT_FOUND`, and only then is `offeror_id` resolved, yielding `ERR_OFFEROR_NOT_FOUND`; a `lease_id` on capital-improvement, operating-plan, gross-receipts-report, fee-reconciliation, audit-engagement or compliance-action creation yields `ERR_LEASE_NOT_FOUND`; a supplied `reconciliation_id` on compliance-action creation must resolve to a reconciliation whose `lease_id` equals the body's `lease_id`, else `ERR_RECONCILIATION_NOT_FOUND`; a supplied `successor_lease_id` at close-out must resolve to a lease other than the one in the path, else `ERR_LEASE_NOT_FOUND`."

    Design: Corner/entities/opportunity_create_with_unknown_park_id_returns_park_not_found
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)

    response = api.create_opportunity(
        {
            "park_id": NON_EXISTENT_UUID,
            "title": "Phantom Park Lodge",
            "service_category": "LODGING",
            "required_capital_investment_cents": 30000000,
        },
        X.specialist_headers(),
    )
    validate_error(response, "ERR_PARK_NOT_FOUND", 404)

    _rows, meta = validate_paginated(
        api.list_opportunities(X.specialist_headers(), {"park_id": NON_EXISTENT_UUID})
    )
    assert meta["total_count"] == 0, (
        f"no opportunity may hang off an unresolvable park, found {meta['total_count']}"
    )


def test_improvement_creation_resolves_the_lease_before_ownership_or_state(api):
    """PRD §2.9: "4. **Body foreign-key existence** — every reference carried in the request body resolves, and references are resolved left to right in the order the fields are listed for that endpoint."
    PRD §2.9: "Checks are grouped into ordered bands, evaluated strictly from the lowest band upward, and **the lowest-numbered failing check is the one reported**."
    PRD §2.9: "5. **Resource ownership** — when the acting role is `Concessionaire`, `X-User-ID` must equal the owning offeror's `id`, else `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/entities/capital_improvement_create_with_unknown_lease_id_returns_lease_not_found
    """
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    offeror = X.register_offeror(api)

    response = api.create_improvement(
        {
            "lease_id": NON_EXISTENT_UUID,
            "description": "Phantom boathouse",
            "funding_source": "CONCESSIONAIRE_CAPITAL",
            "proposed_cost_cents": 5000000,
            "useful_life_years": 20,
            "construction_window_start": "2027-04-01",
            "construction_window_end": "2027-07-01",
            "ownership_at_expiration": "AGENCY",
        },
        X.concessionaire_headers(offeror["id"]),
    )
    validate_error(response, "ERR_LEASE_NOT_FOUND", 404)

    _rows, meta = validate_paginated(
        api.list_improvements(X.award_officer_headers(), {"lease_id": NON_EXISTENT_UUID})
    )
    assert meta["total_count"] == 0, (
        f"no improvement may hang off an unresolvable lease, found {meta['total_count']}"
    )
