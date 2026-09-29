"""What each shape of endpoint is actually obliged to do.

A collection endpoint creates, reads and filters. An action endpoint mutates a row that
already exists and mints nothing. A bulk action writes to every sibling it names. A link
field points at another row without spending it. And a pure read exposes the whole derived
picture without moving a single counter.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    AUDITOR_HEADERS,
    CM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_gmp_identity,
    assert_instant,
    assert_money,
    assert_money_fields,
    assert_null,
    assert_page_meta,
    assert_project_axes,
    assert_ratio,
    assert_system_fields,
    factories,
    fixtures,
    ids_of,
    line_by_seq,
)
from test_helpers.types import JsonObject

HARBORVIEW_CLINIC = {"name": "Harborview Clinic", "owner_org": "Harborview Health"}
CLINIC_KWARGS = {"project_kwargs": dict(HARBORVIEW_CLINIC)}
SOLICITATION_OPENS = "2026-08-01T00:00:00Z"
SOLICITATION_CLOSES = "2026-08-15T00:00:00Z"
ABSENT_PACKAGE_ID = "00000000-0000-0000-0000-000000000000"


def _clinic_with_two_milestones(api: ApiClient) -> Tuple[str, JsonObject, JsonObject]:
    """A reconciled schematic estimate and a fresh design-development draft above it."""
    project = fixtures.create_project(api, **HARBORVIEW_CLINIC)
    schematic = fixtures.reconciled_estimate(
        api,
        project["id"],
        milestone_code="SD",
        submitted_cost_of_work=Decimal("1000000.00"),
    )
    development = fixtures.create_estimate(
        api,
        project["id"],
        milestone_code="DD",
        submitted_cost_of_work=Decimal("1040000.00"),
    )
    return project["id"], schematic, development


def test_the_estimate_collection_creates_reads_and_filters_the_same_history(
    api: ApiClient,
) -> None:
    """One create, one read by id, and two filters that have to compose with paging.

    PRD: "The milestone codes, in ascending design maturity, are `SD`, `DD`, `CD_50`, `CD_100` and `GMP_BASIS`; the server stamps a `milestone_rank` on the row from a fixed ranking in which `SD` ranks 1, `DD` ranks 2, `CD_50` ranks 3, `CD_100` ranks 4 and `GMP_BASIS` ranks 5."

    PRD: "Otherwise the server gathers every other estimate of the same project whose status is `RECONCILED` and whose `milestone_rank` is strictly lower than the new estimate's rank; drafts, submissions, returns and superseded rows are never eligible as a basis even when their rank is lower."

    PRD: "Whenever a basis is selected, `variance_basis_estimate_id` records that basis row's identifier and `variance_pct` is the basis-relative signed ratio: the new estimate's `submitted_cost_of_work` less the basis estimate's `submitted_cost_of_work`, divided by the basis estimate's `submitted_cost_of_work`, rounded half-up to 4 decimal places."

    PRD: "Estimates already at `RECONCILED` are never superseded; they remain the reconciliation basis for everything downstream."

    PRD: "List responses carry four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    PRD: "Unless a specific endpoint states otherwise, list results are ordered by the record's creation timestamp, ascending — oldest first."

    Design: Corner/endpoints/estimate_collection_supports_create_read_and_filtered_list
    """
    project_id, schematic, development = _clinic_with_two_milestones(api)

    read_back = validate_success(
        api.get_estimate(development["id"], OWNER_HEADERS)
    )
    assert_system_fields(read_back)
    assert_fields(
        read_back,
        {
            "status": "DRAFT",
            "milestone_code": "DD",
            "milestone_rank": 2,
            "variance_basis": "HIGHEST_RECONCILED_MILESTONE",
            "variance_basis_estimate_id": schematic["id"],
        },
    )
    assert_ratio(read_back["variance_pct"], Decimal("0.0400"), "variance_pct")

    drafts, drafts_meta = validate_paginated(
        api.list_estimates(
            OWNER_HEADERS, {"project_id": project_id, "status": "DRAFT"}
        )
    )
    assert ids_of(drafts) == [development["id"]], (
        f"the DRAFT filter should isolate the design-development row, got {ids_of(drafts)}"
    )
    assert_page_meta(drafts_meta, total_count=1, has_more=False)

    reconciled, reconciled_meta = validate_paginated(
        api.list_estimates(
            AUDITOR_HEADERS, {"project_id": project_id, "status": "RECONCILED"}
        )
    )
    assert ids_of(reconciled) == [schematic["id"]], (
        f"the RECONCILED filter should isolate the schematic row, got {ids_of(reconciled)}"
    )
    assert_page_meta(reconciled_meta, total_count=1, has_more=False)
    assert_fields(reconciled[0], {"milestone_code": "SD", "status": "RECONCILED"})
    assert_null(reconciled[0], "superseded_by_estimate_id")

    first_page, page_meta = validate_paginated(
        api.list_estimates(
            AUDITOR_HEADERS, {"project_id": project_id, "limit": 1, "offset": 0}
        )
    )
    assert ids_of(first_page) == [schematic["id"]], (
        f"the oldest row belongs on the first page, got {ids_of(first_page)}"
    )
    assert_page_meta(page_meta, total_count=2, has_more=True, limit=1, offset=0)
    for row in first_page:
        assert_system_fields(row)


def test_solicit_mutates_the_package_it_names_and_mints_nothing(api: ApiClient) -> None:
    """A verb, not a collection: 200 with the same row, and only once the price is under way.

    PRD: "Creation endpoints return HTTP 201; every other successful operation, including all action endpoints and all reads, returns HTTP 200."

    PRD: "A new package begins with `procurement_status` at `BUDGETED`, `transparency_status` at `SEALED`, `awarded_bid_id` null, `awarded_amount` at 0.00, `committed_amount` at 0.00, `replacement_reserve_amount` at 0.00, `bid_count` at 0, and both `solicitation_opens_at` and `solicitation_closes_at` null."

    PRD: "Opening the bid market advances the package `BUDGETED → SOLICITING`, and the `ConstructionManager` supplies both `solicitation_opens_at` and `solicitation_closes_at` as ISO 8601 UTC instants, which are recorded on the package; the close must be strictly after the open, and a window that is not is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    PRD: "The project must have reached at least owner review of its base price — `gmp_status` must be `GMP_UNDER_REVIEW` or `EXECUTED` — and a project still in `PRECONSTRUCTION`, or already `CLOSED`, is rejected with `ERR_GMP_NOT_EXECUTED` (HTTP 409)."

    PRD: "`version` — an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/solicit_is_an_action_endpoint_that_mutates_without_creating_a_row
    """
    priced = fixtures.draft_priced_project(api, **CLINIC_KWARGS)
    assert_project_axes(fixtures.read_project(api, priced.id), gmp_status="PRECONSTRUCTION")
    package = fixtures.work_package(
        api, priced.id, budget_amount=Decimal("500000.00"), trade_division="03-CONCRETE"
    )
    minted_version = package["version"]
    assert_fields(package, {"procurement_status": "BUDGETED"})
    assert_null(package, "solicitation_opens_at", "solicitation_closes_at")
    window = factories.solicit_payload(SOLICITATION_OPENS, SOLICITATION_CLOSES)

    validate_error(
        api.solicit_work_package(package["id"], window, CM_HEADERS),
        ApiErrorId.GMP_NOT_EXECUTED,
        409,
    )
    refused = fixtures.read_work_package(api, package["id"])
    assert_fields(
        refused, {"procurement_status": "BUDGETED", "version": minted_version}
    )
    assert_null(refused, "solicitation_opens_at", "solicitation_closes_at")

    validate_success(api.submit_gmp_proposal(priced.proposal["id"], CM_HEADERS))
    validate_success(
        api.decide_gmp_proposal(
            priced.proposal["id"],
            factories.proposal_decision_payload("EXECUTE"),
            OWNER_HEADERS,
        )
    )

    solicited = validate_success(
        api.solicit_work_package(package["id"], window, CM_HEADERS), 200
    )
    assert_equals(solicited, "id", package["id"])
    assert_fields(
        solicited,
        {"procurement_status": "SOLICITING", "version": minted_version + 1},
    )
    assert_instant(
        solicited["solicitation_opens_at"], SOLICITATION_OPENS, "solicitation_opens_at"
    )
    assert_instant(
        solicited["solicitation_closes_at"],
        SOLICITATION_CLOSES,
        "solicitation_closes_at",
    )
    assert_equals(solicited, "bid_count", 0)


def test_one_award_settles_every_opened_sibling_and_leaves_the_sealed_one_alone(
    api: ApiClient,
) -> None:
    """Four envelopes, three unsealed, one award — and the price comes from the winner.

    PRD: "A bid is minted at `SEALED` with `prepared_by_user_id` taken from the submitting operator's `X-User-ID`, `opened_by_user_id` null and `opened_at` null; the parent package's `bid_count` increases by 1 and its `version` increments."

    PRD: "A successful open advances the bid `SEALED → OPENED`, records `opened_by_user_id` from the acting `X-User-ID` and `opened_at` from the logical clock, and increments the bid's `version`."

    PRD: "The award advances the package `SOLICITING → AWARDED`, writes `awarded_bid_id` from the supplied `bid_id` and `awarded_amount` from that bid's `base_bid_amount`, advances the winning bid `OPENED → AWARDED`, and moves **every other** bid on that package that is currently `OPENED` to `NOT_AWARDED`."

    PRD: "For each work package of the project, the per-package delta is its `budget_amount` minus its `awarded_amount`, so a positive delta is an underrun."

    PRD: "The **trade-level** figure (the `TRADE_LEVEL` variant) floors each package at zero before summing — it is the sum of the greater of the package delta and 0.00 across the included packages — and is written to the project's `buyout_savings_trade_level`."

    Design: Corner/endpoints/award_settles_every_open_bid_on_the_package_in_one_call
    """
    executed = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        solicitation_opens_at=SOLICITATION_OPENS,
        solicitation_closes_at=SOLICITATION_CLOSES,
    )
    cascade = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("455000.00"),
        bidder_name="Cascade Concrete",
    )
    ironbound = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("460000.00"),
        bidder_name="Ironbound Concrete",
    )
    kestrel = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("470000.00"),
        bidder_name="Kestrel Concrete",
    )
    northline = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("452000.00"),
        bidder_name="Northline Concrete",
    )
    for sealed in (cascade, ironbound, kestrel, northline):
        assert_fields(sealed, {"status": "SEALED"})
        assert_null(sealed, "opened_by_user_id", "opened_at")

    fixtures.set_clock(api, SOLICITATION_CLOSES)
    for unsealed in (cascade, ironbound, kestrel):
        opened = validate_success(api.open_bid(unsealed["id"], PO_HEADERS))
        assert_fields(opened, {"status": "OPENED"})

    awarded = validate_success(
        api.award_work_package(
            package["id"],
            factories.award_payload(
                ironbound["id"], "lowest responsive after scope levelling"
            ),
            PO_HEADERS,
        ),
        200,
    )
    assert_fields(
        awarded,
        {"procurement_status": "AWARDED", "awarded_bid_id": ironbound["id"]},
    )
    assert_money(awarded["awarded_amount"], Decimal("460000.00"), "awarded_amount")
    assert_equals(awarded, "bid_count", 4)

    assert_fields(fixtures.read_bid(api, ironbound["id"]), {"status": "AWARDED"})
    assert_fields(fixtures.read_bid(api, cascade["id"]), {"status": "NOT_AWARDED"})
    assert_fields(fixtures.read_bid(api, kestrel["id"]), {"status": "NOT_AWARDED"})
    assert_fields(fixtures.read_bid(api, northline["id"]), {"status": "SEALED"})

    project = fixtures.read_project(api, executed.id)
    assert_money_fields(
        project,
        {
            "buyout_savings_trade_level": Decimal("40000.00"),
            "buyout_savings_project_net": Decimal("40000.00"),
        },
    )


def test_a_cost_line_points_at_a_package_and_an_allowance_without_spending_either(
    api: ApiClient,
) -> None:
    """Two optional links on one line: both are echoed, neither moves the row it names.

    PRD: "Cost lines are appended one at a time by the `ConstructionManager`, each carrying a `cost_code` identifying the cost classification, a `quantity`, a `unit_rate`, a `markup_pct`, and optionally a `work_package_id` tying the line to a bought-out trade package, a `qualification_item_id` tying it to an allowance or assumption, and a `disputed` flag."

    PRD: "The appended line object exposes `line_seq` set to the report's `line_count` plus 1, together with `work_package_id`, `quantity`, `unit_rate`, `markup_pct`, the computed `line_amount` and `disputed`."

    PRD: "The report's `reported_cost_total` is then the sum of `line_amount` over every line, `undisputed_cost_total` is the sum of `line_amount` over lines whose `disputed` is false, `disputed_cost_total` is the sum over lines whose `disputed` is true, and `line_count` is the number of entries in `lines`."

    PRD: "From those two numbers the server derives `allowance_unit_rate` as `allowance_amount` divided by `allocated_units`, rounded half-up to 4 decimal places, and opens the ledger with `remaining_units` equal to `allocated_units`, `reconciled_units` at 0.00, `reconciled_amount` at 0.00, `variance_amount` at 0.00, `reconciliation_seq` at 0, `last_action` at `NONE` and `status` at `OPEN`."

    PRD: "That recount is defined once and used everywhere: a package's `committed_amount` is the sum of `contract_amount` over its subcontracts whose `contract_status` is `ACTIVE`, `DEFAULT_NOTICED` or `COMPLETED`, plus the sum of `paid_to_date` over its subcontracts whose `contract_status` is `TERMINATED_FOR_DEFAULT`."

    PRD: "The same four-way split applies to identifiers supplied in a request body: an unresolvable `project_id` yields `ERR_PROJECT_NOT_FOUND`, an unresolvable `work_package_id` yields `ERR_WORK_PACKAGE_NOT_FOUND`, and every other unresolvable body identifier — `prior_estimate_id`, `based_on_estimate_id`, `gmp_proposal_id`, `awarded_bid_id`, `bid_id`, `qualification_item_id`, `source_subcontract_id`, or a cost line's `work_package_id` — yields `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/endpoints/cost_report_line_links_to_a_work_package_and_an_allowance_of_the_same_project
    """
    priced = fixtures.draft_priced_project(api, **CLINIC_KWARGS)
    allowance = fixtures.allowance_item(
        api,
        priced.proposal["id"],
        allowance_amount=Decimal("90000.00"),
        allocated_units=Decimal("1500.00"),
        unit_of_measure="CY",
        text="hard rock excavation allowance",
    )
    validate_success(api.submit_gmp_proposal(priced.proposal["id"], CM_HEADERS))
    validate_success(
        api.decide_gmp_proposal(
            priced.proposal["id"],
            factories.proposal_decision_payload("EXECUTE"),
            OWNER_HEADERS,
        )
    )
    package = fixtures.work_package(
        api, priced.id, budget_amount=Decimal("500000.00"), trade_division="03-CONCRETE"
    )
    report = fixtures.cost_report(
        api, priced.id, period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z"
    )

    linked = validate_success(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("250.0000"),
                unit_rate=Decimal("62.5000"),
                markup_pct=Decimal("0.0000"),
                cost_code="03-100",
                work_package_id=package["id"],
                qualification_item_id=allowance["id"],
                disputed=False,
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_equals(linked, "line_count", 1)
    assert_money(
        linked["reported_cost_total"], Decimal("15625.00"), "reported_cost_total"
    )
    line = line_by_seq(linked, 1)
    # PRD enumerates what the appended line object exposes — "`line_seq` ...
    # together with `work_package_id`, `quantity`, `unit_rate`, `markup_pct`, the
    # computed `line_amount` and `disputed`" — and `qualification_item_id` is not
    # in that list, so its echo is not asserted here. The link is still proven
    # below by the allowance it names being left entirely unspent.
    assert_fields(
        line,
        {
            "work_package_id": package["id"],
            "disputed": False,
        },
    )
    assert_money(line["line_amount"], Decimal("15625.00"), "line_amount")

    untouched_allowance = fixtures.read_qualification_item(api, allowance["id"])
    assert_money_fields(
        untouched_allowance,
        {
            "reconciled_units": Decimal("0.00"),
            "remaining_units": Decimal("1500.00"),
        },
    )
    assert_fields(untouched_allowance, {"status": "OPEN", "last_action": "NONE"})
    assert_money(
        fixtures.read_work_package(api, package["id"])["committed_amount"],
        Decimal("0.00"),
        "committed_amount",
    )

    validate_error(
        api.append_cost_line(
            report["id"],
            factories.cost_line_payload(
                quantity=Decimal("1.0000"),
                unit_rate=Decimal("5000.0000"),
                markup_pct=Decimal("0.0000"),
                cost_code="03-200",
                work_package_id=ABSENT_PACKAGE_ID,
                disputed=False,
            ),
            CM_HEADERS,
        ),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )
    assert_equals(fixtures.read_cost_report(api, report["id"]), "line_count", 1)


def test_the_project_read_publishes_every_derived_figure_and_moves_nothing(
    api: ApiClient,
) -> None:
    """One read, seven envelope terms that still add up, and two savings figures outside them.

    PRD: "`gmp_amount` equals the sum of `cost_of_work_budget_total`, `general_conditions_total`, `insurance_amount`, `cm_fee_amount`, `owner_contingency_remaining`, `construction_contingency_remaining`, and `contingency_drawn_to_cost_total`."

    PRD: "Compute `insurance_amount` as the project's `insurance_rate` multiplied by the sum of the base and `provisional_fee_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the **binding** `cm_fee_amount` as the project's `cm_fee_pct` multiplied by the sum of the base and `insurance_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the proposal's `gmp_amount` as the exact sum of five already-rounded terms: the base, `insurance_amount`, `cm_fee_amount`, `owner_contingency_amount` and `construction_contingency_amount`."

    PRD: "Both contingency pots are funded at once: `owner_contingency_original` and `owner_contingency_remaining` are both set to the proposal's `owner_contingency_amount`, and `construction_contingency_original` and `construction_contingency_remaining` are both set to the proposal's `construction_contingency_amount`, while `contingency_drawn_to_cost_total` is set to 0.00."

    PRD: "The project's `proposed_gmp_amount` is then rolled up — with no pending amendments it equals the executed `gmp_amount` — the `contingency_posture` is re-derived (a fully funded construction pot yields `OPEN`), and the project's `version` increments by 1."

    PRD: "The **project-net** figure (the `PROJECT_NET` variant) sums every included package delta signed, so overruns offset underruns and the result may be negative; it is written to the project's `buyout_savings_project_net`."

    PRD: "A lump-sum `precon_fee_amount` for preconstruction services may also be supplied; it must be at least 0.00, defaults to 0.00 when omitted, and is invoiced **outside** the guaranteed maximum price, so it never appears in any of the envelope identities."

    PRD: "The provisional pass is therefore optional: an owner may go straight to the audited final figure, in which case the three provisional fields are simply never computed and stay at 0.00."

    PRD: "`version` — an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/project_read_exposes_derived_aggregates_that_reconcile_against_their_sources
    """
    executed = fixtures.executed_project(
        api,
        project_kwargs={
            "name": "Harborview Clinic",
            "owner_org": "Harborview Health",
            "precon_fee_amount": Decimal("25000.00"),
        },
    )
    fixtures.awarded_package(
        api,
        executed.id,
        budget_amount=Decimal("500000.00"),
        base_bid_amount=Decimal("460000.00"),
        trade_division="03-CONCRETE",
        solicitation_opens_at=SOLICITATION_OPENS,
        solicitation_closes_at=SOLICITATION_CLOSES,
    )
    settled_version = fixtures.project_version(api, executed.id)

    project = validate_success(api.get_project(executed.id, AUDITOR_HEADERS), 200)
    assert_system_fields(project, expected_version=settled_version)
    assert_money_fields(
        project,
        {
            "cost_of_work_budget_total": Decimal("1000000.00"),
            "general_conditions_total": Decimal("100000.00"),
            "insurance_amount": Decimal("11440.00"),
            "cm_fee_amount": Decimal("44457.60"),
            "owner_contingency_remaining": Decimal("50000.00"),
            "construction_contingency_remaining": Decimal("40000.00"),
            "contingency_drawn_to_cost_total": Decimal("0.00"),
            "gmp_amount": Decimal("1245897.60"),
            "proposed_gmp_amount": Decimal("1245897.60"),
            "precon_fee_amount": Decimal("25000.00"),
        },
    )
    assert_gmp_identity(project)
    assert_equals(project, "pending_amendment_count", 0)
    assert_money_fields(
        project,
        {
            "buyout_savings_trade_level": Decimal("40000.00"),
            "buyout_savings_project_net": Decimal("40000.00"),
        },
    )
    assert_project_axes(
        project,
        gmp_status="EXECUTED",
        contingency_posture="OPEN",
        audit_status="NOT_REQUESTED",
        closeout_status="NOT_STARTED",
    )
    assert_money_fields(
        project,
        {
            "provisional_savings_pool": Decimal("0.00"),
            "provisional_cm_savings_share": Decimal("0.00"),
            "provisional_owner_savings_share": Decimal("0.00"),
            "final_savings_pool": Decimal("0.00"),
            "final_cm_savings_share": Decimal("0.00"),
            "final_owner_savings_share": Decimal("0.00"),
        },
    )
    assert_equals(
        fixtures.read_project(api, executed.id), "version", settled_version
    )
