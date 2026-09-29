"""Registration, retrieval, listing and the boundary rules on the way in.

What a freshly registered project and a freshly budgeted package look like, how the
list envelope reports a window over a larger set, and which identifier failure a
request is told about first.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CM_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_all_zero_money,
    assert_allowance_ledger_invariant,
    assert_equals,
    assert_fields,
    assert_money,
    assert_money_fields,
    assert_ordered_by_created_at,
    assert_page_meta,
    assert_project_axes,
    assert_ratio,
    assert_system_fields,
    factories,
    fixtures,
    ids_of,
)

#: A syntactically valid UUID that names no row anywhere in the system.
ABSENT_ID = "00000000-0000-4000-8000-000000000000"
#: A second absent UUID, used where a payload tries to dictate its own identity.
CLIENT_MINTED_ID = "11111111-1111-4111-8111-111111111111"

ZEROED_MONEY_FIELDS = (
    "gmp_amount",
    "proposed_gmp_amount",
    "cost_of_work_budget_total",
    "general_conditions_total",
    "insurance_amount",
    "cm_fee_amount",
    "owner_contingency_original",
    "owner_contingency_remaining",
    "construction_contingency_original",
    "construction_contingency_remaining",
    "contingency_drawn_to_cost_total",
    "buyout_savings_trade_level",
    "buyout_savings_project_net",
    "audit_adjustment_total",
    "provisional_savings_pool",
    "provisional_cm_savings_share",
    "provisional_owner_savings_share",
    "final_savings_pool",
    "final_cm_savings_share",
    "final_owner_savings_share",
)


def test_registration_zeroes_every_money_field_and_opens_all_four_axes(
    api: ApiClient,
) -> None:
    """A fresh project has no money in it at all, on any of its twenty money fields.

    PRD: "A freshly registered project arrives at `version` 1 with all four of its state axes at their initial values — `gmp_status` at `PRECONSTRUCTION`, `contingency_posture` at `OPEN`, `audit_status` at `NOT_REQUESTED`, `closeout_status` at `NOT_STARTED` — with `pending_amendment_count` at 0 and with every money field at 0.00."

    PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/project_creation_returns_zeroed_money_and_four_initial_states
    """
    response = api.create_project(
        factories.project_payload(
            name="Harborview Clinic",
            owner_org="Harborview Health",
            cm_fee_pct=Decimal("0.04"),
            insurance_rate=Decimal("0.01"),
            precon_fee_amount=Decimal("25000.00"),
        ),
        ADMIN_HEADERS,
    )
    project = validate_success(response, 201)

    envelope = response.json()
    assert envelope["response_type"] == "object", (
        "a single-resource response must declare response_type object"
    )
    assert envelope["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )
    assert "api_request_timestamp" in envelope["meta"], (
        "the meta object must carry api_request_timestamp"
    )

    assert_project_axes(
        project,
        gmp_status="PRECONSTRUCTION",
        contingency_posture="OPEN",
        audit_status="NOT_REQUESTED",
        closeout_status="NOT_STARTED",
    )
    assert_equals(project, "pending_amendment_count", 0)
    assert_system_fields(project, expected_version=1)
    assert project["created_at"] == project["updated_at"], (
        "updated_at moved on a row that has not yet been mutated"
    )
    assert_ratio(project["cm_fee_pct"], Decimal("0.0400"), "cm_fee_pct")
    assert_ratio(project["insurance_rate"], Decimal("0.0100"), "insurance_rate")
    assert_money(project["precon_fee_amount"], Decimal("25000.00"), "precon_fee_amount")
    assert_all_zero_money(project, ZEROED_MONEY_FIELDS)


def test_a_budgeted_package_reads_back_on_a_project_with_no_guaranteed_price_yet(
    api: ApiClient,
) -> None:
    """Buyout budgeting happens in preconstruction, so the read must not need a GMP.

    PRD: "A new package begins with `procurement_status` at `BUDGETED`, `transparency_status` at `SEALED`, `awarded_bid_id` null, `awarded_amount` at 0.00, `committed_amount` at 0.00, `replacement_reserve_amount` at 0.00, `bid_count` at 0, and both `solicitation_opens_at` and `solicitation_closes_at` null."

    PRD: "A `ConstructionManager` creates a package naming its `project_id`, its `trade_division` — a CSI trade division label such as `03-CONCRETE`, between 1 and 60 characters — and the `budget_amount` carried for that package inside the cost of work, greater than 0 at 2 decimal places."

    PRD: "A `self_perform_intent` flag may be supplied, defaulting to false, marking that the construction manager intends to bid the package with its own forces."

    Design: Corner/entities/work_package_retrieval_returns_the_stored_representation
    """
    project = fixtures.create_project(
        api, name="Harborview Clinic", owner_org="Harborview Health"
    )
    assert_project_axes(project, gmp_status="PRECONSTRUCTION")

    created = validate_success(
        api.create_work_package(
            factories.work_package_payload(
                project["id"],
                trade_division="07-ROOFING",
                budget_amount=Decimal("480000.00"),
                self_perform_intent=False,
            ),
            CM_HEADERS,
        ),
        201,
    )

    read = validate_success(api.get_work_package(created["id"], OWNER_HEADERS))
    assert_fields(
        read,
        {
            "project_id": project["id"],
            "trade_division": "07-ROOFING",
            "self_perform_intent": False,
            "procurement_status": "BUDGETED",
            "transparency_status": "SEALED",
            "solicitation_opens_at": None,
            "solicitation_closes_at": None,
            "awarded_bid_id": None,
            "bid_count": 0,
            "version": 1,
        },
    )
    assert_money_fields(
        read,
        {
            "budget_amount": Decimal("480000.00"),
            "awarded_amount": Decimal("0.00"),
            "committed_amount": Decimal("0.00"),
            "replacement_reserve_amount": Decimal("0.00"),
        },
    )


def test_the_list_window_reports_the_whole_filtered_set_not_the_page(
    api: ApiClient,
) -> None:
    """Two rows of three, then the last row, then a filter that matches nothing.

    PRD: "List responses carry four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    PRD: "The `offset` parameter is the number of records to skip before the page begins, and defaults to 0."

    PRD: "Unless a specific endpoint states otherwise, list results are ordered by the record's creation timestamp, ascending — oldest first."

    PRD: "Lists CMAR projects, filterable by `gmp_status`, `contingency_posture` and `closeout_status`."

    Design: Corner/entities/project_listing_paginates_with_total_count_and_has_more
    """
    first = fixtures.create_project(
        api, name="Harborview Clinic", owner_org="Harborview Health"
    )
    second = fixtures.create_project(
        api,
        name="Lakeshore Library Renovation",
        owner_org="Lakeshore Library District",
    )
    third = fixtures.create_project(
        api, name="Northgate Transit Center", owner_org="Northgate Transit Authority"
    )

    page_one, meta_one = validate_paginated(
        api.list_projects(ADMIN_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, "a limit of 2 returned a different number of rows"
    assert_page_meta(meta_one, total_count=3, has_more=True, limit=2, offset=0)
    assert_ordered_by_created_at(page_one)

    page_two, meta_two = validate_paginated(
        api.list_projects(ADMIN_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, "the tail window returned a different number of rows"
    assert_page_meta(meta_two, total_count=3, has_more=False, offset=2)

    combined = ids_of(page_one) + ids_of(page_two)
    assert sorted(combined) == sorted([first["id"], second["id"], third["id"]]), (
        "the two windows do not tile the whole set exactly once"
    )

    executed, meta_three = validate_paginated(
        api.list_projects(ADMIN_HEADERS, {"gmp_status": "EXECUTED"})
    )
    assert executed == [], "a project reached EXECUTED without any pricing being done"
    assert_page_meta(meta_three, total_count=0, has_more=False)


def test_the_four_way_not_found_split_answers_on_the_path_that_was_asked(
    api: ApiClient,
) -> None:
    """A valid UUID naming nothing gets the code of the collection it was asked of.

    PRD: "Identifiers that appear in a URL path are resolved left to right, and the first identifier that fails to resolve determines the error: a project identifier in a path that does not resolve yields `ERR_PROJECT_NOT_FOUND` (HTTP 404), a work-package identifier `ERR_WORK_PACKAGE_NOT_FOUND` (HTTP 404), a subcontract identifier `ERR_SUBCONTRACT_NOT_FOUND` (HTTP 404), a change-event identifier `ERR_CHANGE_EVENT_NOT_FOUND` (HTTP 404), and any other identifier — an estimate, a proposal, a qualification item, a self-perform bid, a contingency draw or a cost report — `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/project_read_with_unknown_id_returns_not_found
    """
    validate_error(
        api.get_project(ABSENT_ID, ADMIN_HEADERS), ApiErrorId.PROJECT_NOT_FOUND, 404
    )
    validate_error(
        api.get_work_package(ABSENT_ID, ADMIN_HEADERS),
        ApiErrorId.WORK_PACKAGE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_qualification_item(ABSENT_ID, CM_HEADERS),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )


def test_registration_without_a_fee_rate_is_refused_rather_than_defaulted(
    api: ApiClient,
) -> None:
    """cm_fee_pct has no default, so omitting it cannot silently price a zero fee.

    PRD: "4. Request-shape validation — `ERR_INVALID_REQUEST`. This covers required fields being present, enums taking declared values, money at no more than 2 decimal places and non-negative, unit rates and ratios at no more than 4 decimal places, datetimes parsing as ISO 8601 UTC instants, an interval's start being strictly before its end, and conditionally-required fields being present when their condition holds — `allowance_amount`, `allocated_units` and `unit_of_measure` when the item type is `ALLOWANCE`; `bond_amount` when `bond_required` is true; `void_reason` on a draw void; `recovered_amount` on a bond-claim settlement; and `adjustment_amount` on an audit adjustment."

    PRD: "A `ProgramAdmin` opens the engagement by registering the CMAR project itself, supplying a project `name` and the `owner_org` of the owner organization holding the CMAR contract (each between 1 and 200 characters), together with the two contractual rates that will later price the guaranteed maximum price: `cm_fee_pct`, the construction manager's fee rate, which must be greater than 0 and no greater than 0.1500 at 4 decimal places, and `insurance_rate`, the builder's-risk rate, which must be at least 0 and no greater than 0.0500 at 4 decimal places."

    Design: Corner/entities/project_creation_without_cm_fee_pct_is_rejected
    """
    payload = factories.project_payload(
        name="Harborview Clinic",
        owner_org="Harborview Health",
        insurance_rate=Decimal("0.01"),
    )
    del payload["cm_fee_pct"]

    validate_error(
        api.create_project(payload, ADMIN_HEADERS), ApiErrorId.INVALID_REQUEST, 400
    )

    rows, meta = validate_paginated(api.list_projects(ADMIN_HEADERS))
    assert rows == [], "the rejected registration wrote a project row anyway"
    assert_page_meta(meta, total_count=0)

    payload["cm_fee_pct"] = 0.04
    accepted = validate_success(api.create_project(payload, ADMIN_HEADERS), 201)
    assert_ratio(accepted["cm_fee_pct"], Decimal("0.0400"), "cm_fee_pct")


def test_omitting_the_preconstruction_fee_yields_the_declared_zero_not_null(
    api: ApiClient,
) -> None:
    """The one optional money input on registration still reads back as a decimal.

    PRD: "A lump-sum `precon_fee_amount` for preconstruction services may also be supplied; it must be at least 0.00, defaults to 0.00 when omitted, and is invoiced **outside** the guaranteed maximum price, so it never appears in any of the envelope identities."

    Design: Corner/entities/project_creation_omitting_precon_fee_applies_the_zero_default
    """
    payload = factories.project_payload(
        name="Lakeshore Library Renovation",
        owner_org="Lakeshore Library District",
    )
    assert "precon_fee_amount" not in payload, (
        "this test must send a payload with no precon_fee_amount at all"
    )

    project = validate_success(api.create_project(payload, ADMIN_HEADERS), 201)
    assert project["precon_fee_amount"] is not None, (
        "precon_fee_amount defaulted to null rather than to 0.00"
    )
    assert_money(project["precon_fee_amount"], Decimal("0.00"), "precon_fee_amount")
    assert_project_axes(project, gmp_status="PRECONSTRUCTION")
    assert_system_fields(project, expected_version=1)


def test_the_allowance_rate_is_derived_and_a_supplied_rate_is_discarded(
    api: ApiClient,
) -> None:
    """A client that dictates its own unit rate and booked units is simply overruled.

    PRD: "From those two numbers the server derives `allowance_unit_rate` as `allowance_amount` divided by `allocated_units`, rounded half-up to 4 decimal places, and opens the ledger with `remaining_units` equal to `allocated_units`, `reconciled_units` at 0.00, `reconciled_amount` at 0.00, `variance_amount` at 0.00, `reconciliation_seq` at 0, `last_action` at `NONE` and `status` at `OPEN`."

    PRD: "**The invariant, asserted after every action of either kind, is that `allocated_units` equals `remaining_units` plus `reconciled_units`.**"

    Design: Corner/entities/qualification_item_unit_rate_is_computed_and_supplied_value_input_ignored
    """
    priced = fixtures.draft_priced_project(
        api, project_kwargs={"name": "Harborview Clinic", "owner_org": "Harborview Health"}
    )

    item = validate_success(
        api.create_qualification_item(
            factories.allowance_item_payload(
                priced.proposal["id"],
                allowance_amount=Decimal("60000.00"),
                allocated_units=Decimal("1200.00"),
                unit_of_measure="SF",
                text="decorative terrazzo flooring at the lobby",
                allowance_unit_rate=99.9999,
                reconciled_units=400,
            ),
            CM_HEADERS,
        ),
        201,
    )

    assert_ratio(item["allowance_unit_rate"], Decimal("50.0000"), "allowance_unit_rate")
    assert_money(item["reconciled_units"], Decimal("0.00"), "reconciled_units")
    assert_money_fields(
        item,
        {
            "remaining_units": Decimal("1200.00"),
            "reconciled_amount": Decimal("0.00"),
            "variance_amount": Decimal("0.00"),
        },
    )
    assert_fields(
        item,
        {
            "reconciliation_seq": 0,
            "last_action": "NONE",
            "status": "OPEN",
            "gmp_proposal_id": priced.proposal["id"],
        },
    )
    assert_allowance_ledger_invariant(item)


def test_a_payload_cannot_mint_its_own_identity_version_or_state(
    api: ApiClient,
) -> None:
    """Every optimistic-concurrency check reads that version, so the client cannot set it.

    PRD: "`id` — a server-minted UUID. It carries no type prefix and no embedded meaning; clients must never construct one."

    PRD: "`version` — an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row. A cascade that mutates three rows increments three separate `version` counters."

    PRD: "A freshly registered project arrives at `version` 1 with all four of its state axes at their initial values — `gmp_status` at `PRECONSTRUCTION`, `contingency_posture` at `OPEN`, `audit_status` at `NOT_REQUESTED`, `closeout_status` at `NOT_STARTED` — with `pending_amendment_count` at 0 and with every money field at 0.00."

    Design: Corner/entities/project_creation_with_client_supplied_system_fields_input_ignored
    """
    project = validate_success(
        api.create_project(
            factories.project_payload(
                name="Harborview Clinic",
                owner_org="Harborview Health",
                id=CLIENT_MINTED_ID,
                version=77,
                created_at="2001-01-01T00:00:00.000Z",
                gmp_status="EXECUTED",
                gmp_amount=9999999.99,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert project["id"] != CLIENT_MINTED_ID, (
        "the server accepted a client-constructed identifier"
    )
    assert_system_fields(project, expected_version=1)
    assert_project_axes(project, gmp_status="PRECONSTRUCTION")
    assert_money(project["gmp_amount"], Decimal("0.00"), "gmp_amount")

    validate_error(
        api.get_project(CLIENT_MINTED_ID, ADMIN_HEADERS),
        ApiErrorId.PROJECT_NOT_FOUND,
        404,
    )


def test_an_unranked_milestone_code_is_refused_at_the_boundary(api: ApiClient) -> None:
    """A code with no rank would break every later variance-basis selection.

    PRD: "The milestone codes, in ascending design maturity, are `SD`, `DD`, `CD_50`, `CD_100` and `GMP_BASIS`; the server stamps a `milestone_rank` on the row from a fixed ranking in which `SD` ranks 1, `DD` ranks 2, `CD_50` ranks 3, `CD_100` ranks 4 and `GMP_BASIS` ranks 5."

    PRD: "Money supplied by a client is rejected with `ERR_INVALID_REQUEST` (HTTP 400) if it is negative or carries more than 2 decimal places."

    Design: Corner/entities/estimate_creation_with_unknown_milestone_code_is_rejected
    """
    project = fixtures.create_project(
        api, name="Harborview Clinic", owner_org="Harborview Health"
    )
    version = project["version"]

    validate_error(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                version,
                milestone_code="CD_75",
                submitted_cost_of_work=Decimal("1000000.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    empty, meta = validate_paginated(
        api.list_estimates(CM_HEADERS, {"project_id": project["id"]})
    )
    assert empty == [], "the rejected create wrote an estimate row anyway"
    assert_page_meta(meta, total_count=0)

    validate_error(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                version,
                milestone_code="CD_50",
                submitted_cost_of_work=Decimal("-1.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    accepted = validate_success(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                version,
                milestone_code="CD_50",
                submitted_cost_of_work=Decimal("1000000.00"),
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_fields(accepted, {"milestone_code": "CD_50", "milestone_rank": 3})


def test_an_unresolvable_body_project_outranks_the_concurrency_check(
    api: ApiClient,
) -> None:
    """The version field cannot possibly match, yet the parent lookup is reported first.

    PRD: "The same four-way split applies to identifiers supplied in a request body: an unresolvable `project_id` yields `ERR_PROJECT_NOT_FOUND`, an unresolvable `work_package_id` yields `ERR_WORK_PACKAGE_NOT_FOUND`, and every other unresolvable body identifier — `prior_estimate_id`, `based_on_estimate_id`, `gmp_proposal_id`, `awarded_bid_id`, `bid_id`, `qualification_item_id`, `source_subcontract_id`, or a cost line's `work_package_id` — yields `ERR_RESOURCE_NOT_FOUND`."

    PRD: "6. Existence of identifiers in the request body, per §2.9."

    PRD: "7. Stale-version rejection on the three creation operations listed in §2.10."

    Design: Corner/entities/estimate_creation_naming_an_unknown_project_returns_project_not_found
    """
    project = fixtures.create_project(
        api, name="Harborview Clinic", owner_org="Harborview Health"
    )
    version = project["version"]

    response = api.create_estimate(
        factories.estimate_payload(
            "22222222-2222-4222-8222-222222222222",
            version,
            milestone_code="SD",
            submitted_cost_of_work=Decimal("900000.00"),
        ),
        CM_HEADERS,
    )
    body = validate_error(response, ApiErrorId.PROJECT_NOT_FOUND, 404)
    assert body["error_id"] != ApiErrorId.STALE_PROJECT_VERSION.value, (
        "the stale-version check masked the unresolvable parent"
    )

    untouched = fixtures.read_project(api, project["id"])
    assert untouched["version"] == version, (
        "the refused create moved the real project's version counter"
    )
    rows, meta = validate_paginated(api.list_estimates(CM_HEADERS))
    assert rows == [], "the refused create wrote an estimate row anyway"
    assert_page_meta(meta, total_count=0)


def test_a_cost_line_may_not_borrow_another_projects_work_package(
    api: ApiClient,
) -> None:
    """Both ids resolve, both rows exist, and the write is still refused.

    PRD: "Beyond mere resolvability, **every referenced row must belong to the same CMAR project as the row being written.**"

    PRD: "Any `work_package_id` on a line must reference a work package of the same project, and a cross-project reference is rejected with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 422)."

    Design: Corner/entities/cost_report_line_naming_another_projects_work_package_is_rejected
    """
    priced = fixtures.executed_project(
        api,
        project_kwargs={"name": "Harborview Clinic", "owner_org": "Harborview Health"},
    )
    report = fixtures.cost_report(
        api,
        priced.id,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )

    other = fixtures.create_project(
        api, name="Northgate Transit Center", owner_org="Northgate Transit Authority"
    )
    foreign_package = fixtures.work_package(
        api,
        other["id"],
        trade_division="07-ROOFING",
        budget_amount=Decimal("480000.00"),
    )

    validate_error(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("1.0000"),
                unit_rate=Decimal("5000.0000"),
                markup_pct=Decimal("0.0000"),
                cost_code="07-100",
                work_package_id=foreign_package["id"],
                disputed=False,
            ),
            CM_HEADERS,
        ),
        ApiErrorId.CROSS_PROJECT_REFERENCE,
        422,
    )
    refused = fixtures.read_cost_report(api, report["id"])
    assert_fields(refused, {"line_count": 0})
    assert_money(refused["reported_cost_total"], Decimal("0.00"), "reported_cost_total")

    validate_success(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("1.0000"),
                unit_rate=Decimal("5000.0000"),
                markup_pct=Decimal("0.0000"),
                cost_code="07-100",
                disputed=False,
            ),
            CM_HEADERS,
        ),
        201,
    )
    accepted = fixtures.read_cost_report(api, report["id"])
    assert_fields(accepted, {"line_count": 1})
    assert_money(accepted["reported_cost_total"], Decimal("5000.00"), "reported_cost_total")
