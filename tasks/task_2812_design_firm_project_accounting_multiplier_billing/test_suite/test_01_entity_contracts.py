"""
Entity contracts for the architecture practice project accounting API.

The rows a firm sets up before it can bill anything: the billing client whose
configuration is fixed at registration, the project whose rollups all start at
zero, the work breakdown structure phase whose fee is derived rather than
supplied, and the append-only labour cost rate. Alongside those creations sit the
guards that keep the flat collection topology honest — the typed 404 each
collection returns for an identifier that resolves to nothing, the pagination and
filter contract of the project list, the shape validation that runs ahead of
every business rule, and the body foreign keys that must both resolve and agree.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_CHARGE_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
    ERR_MULTIPLIER_NOT_FOUND,
    ERR_PHASE_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_SUBCONTRACT_NOT_FOUND,
    ERR_WBS_CYCLE,
    ERR_WRITE_OFF_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_billing_posture,
    assert_created_at_ascending,
    assert_envelope_meta,
    assert_immutable_common_fields,
    assert_money,
    assert_mutable_common_fields,
    assert_null,
    assert_pagination_meta,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_ratio,
)
from test_helpers.constants import (
    CATEGORY_ENTERTAINMENT,
    DEFAULT_WIP_ALERT_THRESHOLD,
    PHASE_PLANNED,
    POSTURE_OPEN,
    PROJECT_ACTIVE,
    PROJECT_SETUP,
    ROLE_CODE_PROJECT_ARCHITECT,
    TIME_ENTRY_SUBMITTED,
)
from test_helpers.fixtures import (
    add_lump_sum_phase,
    build_active_project,
    create_project,
    read_phase,
    read_project,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    CONTROLLER,
    FIRM_ADMIN,
    PROJECT_MANAGER_ALT_USER_ID,
)

# The logical clock every test here pins, spelled as PRD §2.4 requires it: an
# ISO 8601 UTC instant with three fractional digits.
PINNED_CLOCK_STAMP = "2026-06-01T00:00:00.000Z"


def test_client_registration_returns_an_immutable_row_in_the_success_envelope(
    api, clock_june
):
    """
    Registering a billing client echoes all seven configuration inputs and mints
    an identity, but the row carries no mutation counter at all because a
    client's billing configuration is fixed once written.

    PRD §3.1: "A `FirmAdmin` or a `Controller` registers a client by supplying its legal `name`, a boolean `is_public_agency` flag marking it as a public agency subject to overhead rate certification and statutory unallowable-cost rules"
    PRD §2.4: "Two entities are deliberately immutable once written and therefore carry only `id` and `created_at` — they have **no** `updated_at` field and **no** `version` field at all. A `Client` is one: its billing configuration is fixed at registration."
    PRD §2.4: "Every resource also carries a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, recorded from the logical clock described in §2.6 at the moment the row was written."
    PRD §4: "Operations that create a new resource return HTTP 201 with the created resource in `data`; every other successful operation returns HTTP 200."

    Design: Corner/entities/client_creation_returns_immutable_row_in_envelope
    """
    payload = f.private_client_payload()

    response = api.create_client(payload, FIRM_ADMIN)
    created = validate_success(response, 201)

    assert_envelope_meta(response)
    assert response.json()["response_type"] == "object", (
        "a single registered client is one resource, so response_type must be object"
    )

    # No mutation counter and no updated_at: the configuration is fixed at
    # registration, so there is nothing for a counter to count.
    assert_immutable_common_fields(created)
    assert created["created_at"] == PINNED_CLOCK_STAMP, (
        f"created_at must be stamped from the logical clock, got {created['created_at']!r}"
    )

    assert created["name"] == payload["name"]
    assert created["is_public_agency"] is False
    assert_ratio(created["retainage_pct"], 0.0500, "client.retainage_pct")
    assert_ratio(created["expense_markup_pct"], 0.1000, "client.expense_markup_pct")
    assert created["disallowed_categories"] == [CATEGORY_ENTERTAINMENT]
    assert_money(created["receipt_required_above"], 75.00, "client.receipt_required_above")
    assert created["review_cycle_days"] == 30

    read_back = validate_success(api.get_client(created["id"], ACCOUNTANT), 200)
    assert read_back == created, (
        "the retrieval must return exactly the registered configuration: "
        f"{read_back} vs {created}"
    )


def test_project_creation_applies_the_omitted_work_in_progress_alert_default(
    api, private_client
):
    """
    A project created without the one optional input takes the declared alert
    threshold of 50000.00, lands in SETUP with an OPEN billing posture, and
    reports its not-yet-known figures as null rather than as zero.

    PRD §2.11: "`wip_alert_threshold` is supplied at project creation and, when omitted, defaults to 50000.00."
    PRD §3.1: "A project is then created in the `SETUP` state by a `FirmAdmin` or a `Controller`"
    PRD §3.1: "Its `locked_through_date` is `null`, its `overhead_adjustment_required` flag is false, and its `certified_multiplier_ceiling` is `null` unless a certification is already in force for a public-agency client."
    PRD §2.11: "4. Otherwise the posture is `OPEN`."

    Design: Corner/entities/project_creation_applies_defaults_and_zeroes_every_rollup
    """
    payload = f.project_payload(
        private_client["id"],
        name="Riverside Library",
        contract_amount=800000.00,
    )
    assert "wip_alert_threshold" not in payload, (
        "the alert threshold must be left out so the declared default is exercised"
    )

    created = validate_success(api.create_project(payload, CONTROLLER), 201)

    assert_money(
        created["wip_alert_threshold"],
        DEFAULT_WIP_ALERT_THRESHOLD,
        "project.wip_alert_threshold",
    )
    assert created["status"] == PROJECT_SETUP
    assert_billing_posture(created, POSTURE_OPEN)
    assert_null(created["locked_through_date"], "project.locked_through_date")
    assert_null(
        created["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling"
    )
    assert created["overhead_adjustment_required"] is False

    assert_mutable_common_fields(created, expected_version=1)
    assert created["created_at"] == PINNED_CLOCK_STAMP
    assert created["updated_at"] == PINNED_CLOCK_STAMP, (
        "a freshly written row has not changed since it was written, and the "
        "logical clock has not moved, so both stamps read the same instant"
    )

    assert created["client_id"] == private_client["id"]
    assert_money(created["contract_amount"], 800000.00, "project.contract_amount")
    assert_ratio(created["target_multiplier"], 3.0000, "project.target_multiplier")


def test_project_creation_zeroes_every_rollup_figure(api, private_client):
    """
    Every accounting rollup on a brand-new project starts at its identity
    element — 0.00 of money and a 0.0000 achieved multiplier — rather than null,
    and the conservation identity holds from the first instant.

    PRD §3.1: "On creation the project's `version` is initialised to 1, all of its rollup figures described in §2.10 are initialised to zero, and its `billing_posture` is computed for the first time."
    PRD §2.10: "When `raw_labor_cost_to_date` is exactly 0.00, `net_multiplier_achieved` reports 0.0000 rather than being undefined."
    PRD §2.10: "`total_charge_value` is the sum of those four buckets — `unbilled_wip` plus `billed_open` plus `paid_gross_to_date` plus `written_off_gross` — and it is a **conserved quantity**."

    Design: Corner/entities/project_creation_applies_defaults_and_zeroes_every_rollup
    """
    created = validate_success(
        api.create_project(f.project_payload(private_client["id"]), CONTROLLER), 201
    )

    assert_project_ledger(
        created,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=0.00,
        raw_labor_cost_to_date=0.00,
        earned_revenue_to_date=0.00,
        net_multiplier_achieved=0.0000,
    )

    # Every rollup is recomputed on a read of the project, so the retrieval must
    # report the same zeroes rather than drifting off them.
    read_back = read_project(api, created["id"], ACCOUNTANT)
    assert_project_ledger(
        read_back,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=0.00,
        raw_labor_cost_to_date=0.00,
        earned_revenue_to_date=0.00,
        net_multiplier_achieved=0.0000,
    )
    assert read_back["version"] == 1, (
        "a read recomputes the rollups but changes nothing, so the counter stays at 1"
    )


def test_percent_of_contract_phase_derives_its_fee_from_the_contract_amount(
    api, private_client
):
    """
    A phase priced as a fraction of the contract does not carry its own fee: on a
    contract of 800000.00 a fraction of 0.3333 prices the phase at 266640.00, and
    the node starts as a planned top-level leaf with nothing assessed and nothing
    spent.

    PRD §3.1: "When `fee_basis` is `PERCENT_OF_CONTRACT`, a `fee_percent` between 0.0001 and 1.0000 at 4 decimal places is required and `lump_sum_fee` must be omitted; the resulting `phase_fee` is the project's `contract_amount` multiplied by `fee_percent`, rounded half up to 2 decimal places."
    PRD §3.1: "Every phase begins with `status` `PLANNED` and `assessed_percent_complete` of 0.0000."
    PRD §3.1: "Each phase reports a computed `depth` — 0 for a top-level phase, and one more than its parent's `depth` otherwise — and a computed `is_leaf` flag, which is true exactly when no other phase declares this phase as its `parent_phase_id`."

    Design: Corner/entities/phase_fee_computed_from_contract_percentage
    """
    project = create_project(
        api, private_client["id"], name="Riverside Library", contract_amount=800000.00
    )

    phase = validate_success(
        api.create_phase(
            f.percent_phase_payload(
                project["id"],
                wbs_code="01-SD",
                fee_percent=0.3333,
                budget_labor_cost=50000.00,
                consultant_budget=0.00,
            ),
            CONTROLLER,
        ),
        201,
    )

    assert_money(phase["phase_fee"], 266640.00, "phase.phase_fee")
    assert_ratio(phase["fee_percent"], 0.3333, "phase.fee_percent")
    assert phase.get("lump_sum_fee") is None, (
        "a phase priced off the contract carries no lump sum fee of its own, got "
        f"{phase.get('lump_sum_fee')!r}"
    )

    assert phase["status"] == PHASE_PLANNED
    assert phase["is_leaf"] is True
    assert phase["depth"] == 0
    assert phase.get("parent_phase_id") is None
    assert_phase_earned_value(
        phase,
        actual_labor_cost_to_date=0.00,
        assessed_percent_complete=0.0000,
        recognized_earned_value=0.00,
        consultant_committed_open=0.00,
    )
    assert_mutable_common_fields(phase, expected_version=1)


def test_lump_sum_phase_copies_its_stated_fee_verbatim(api, private_client):
    """
    The other fee basis takes the money straight from the payload: a lump sum of
    120000.00 prices the phase at exactly 120000.00 on the same 800000.00
    contract, and the node is likewise a planned top-level leaf.

    PRD §3.1: "When `fee_basis` is `LUMP_SUM`, a `lump_sum_fee` strictly greater than 0.00 is required and `fee_percent` must be omitted; `phase_fee` is then simply that `lump_sum_fee`."
    PRD §3.1: "Every phase begins with `status` `PLANNED` and `assessed_percent_complete` of 0.0000."

    Design: Corner/entities/phase_fee_computed_from_contract_percentage
    """
    project = create_project(
        api, private_client["id"], name="Riverside Library", contract_amount=800000.00
    )

    phase = validate_success(
        api.create_phase(
            f.lump_sum_phase_payload(
                project["id"],
                wbs_code="02-DD",
                lump_sum_fee=120000.00,
                budget_labor_cost=60000.00,
                consultant_budget=0.00,
            ),
            CONTROLLER,
        ),
        201,
    )

    assert_money(phase["phase_fee"], 120000.00, "phase.phase_fee")
    assert_money(phase["lump_sum_fee"], 120000.00, "phase.lump_sum_fee")
    assert phase.get("fee_percent") is None, (
        "a lump sum phase carries no fraction of the contract, got "
        f"{phase.get('fee_percent')!r}"
    )

    assert phase["status"] == PHASE_PLANNED
    assert phase["is_leaf"] is True
    assert phase["depth"] == 0
    assert phase.get("parent_phase_id") is None
    assert_phase_earned_value(
        phase,
        actual_labor_cost_to_date=0.00,
        assessed_percent_complete=0.0000,
        recognized_earned_value=0.00,
        consultant_committed_open=0.00,
    )


def test_each_collection_reports_its_own_not_found_code_for_a_stranger_identifier(
    api, clock_june
):
    """
    Against an empty book of business, a well-formed identifier that resolves to
    nothing in each collection comes back as that collection's own 404 rather
    than as one generic miss, so the caller can tell which resource failed.

    PRD §2.9: "A `project_id` that does not resolve yields `ERR_PROJECT_NOT_FOUND`; a `phase_id`, `ERR_PHASE_NOT_FOUND`; a `client_id`, `ERR_CLIENT_NOT_FOUND`; a `subcontract_id`, `ERR_SUBCONTRACT_NOT_FOUND`; an `invoice_id`, `ERR_INVOICE_NOT_FOUND`; a `write_off_id`, `ERR_WRITE_OFF_NOT_FOUND`; a `certification_id`, `ERR_CERTIFICATION_NOT_FOUND`; and a `billing_multiplier_id`, `ERR_MULTIPLIER_NOT_FOUND`."
    PRD §2.9: "Identifiers embedded in a URL path are resolved strictly left to right, and the first identifier that fails to resolve determines the 404 returned."

    Design: Corner/entities/unknown_path_ids_return_typed_not_found_errors
    """
    probes = [
        (api.get_project(NON_EXISTENT_UUID, CONTROLLER), ERR_PROJECT_NOT_FOUND),
        (api.get_client(NON_EXISTENT_UUID, CONTROLLER), ERR_CLIENT_NOT_FOUND),
        (api.get_phase(NON_EXISTENT_UUID, CONTROLLER), ERR_PHASE_NOT_FOUND),
        (api.get_subcontract(NON_EXISTENT_UUID, CONTROLLER), ERR_SUBCONTRACT_NOT_FOUND),
        (api.get_invoice(NON_EXISTENT_UUID, CONTROLLER), ERR_INVOICE_NOT_FOUND),
        (api.get_write_off(NON_EXISTENT_UUID, CONTROLLER), ERR_WRITE_OFF_NOT_FOUND),
        (
            api.get_certification(NON_EXISTENT_UUID, CONTROLLER),
            ERR_CERTIFICATION_NOT_FOUND,
        ),
        (
            api.get_billing_multiplier(NON_EXISTENT_UUID, CONTROLLER),
            ERR_MULTIPLIER_NOT_FOUND,
        ),
    ]

    for response, expected_error_id in probes:
        # The identifier is well formed, so this is a resolution miss and never a
        # malformed request.
        assert response.status_code == 404, (
            f"expected {expected_error_id} at HTTP 404, got {response.status_code} "
            f"with body {response.json()}"
        )
        validate_error(response, expected_error_id, 404)


def test_the_three_charge_collections_share_one_not_found_code(api, clock_june):
    """
    Timesheet lines, reimbursable expenses and consultant payables are all
    charges, and the three of them deliberately answer with a single shared code
    rather than one code each.

    PRD §2.9: "The three charge identifiers — `time_entry_id`, `expense_id` and `consultant_invoice_id` — share a single code, `ERR_CHARGE_NOT_FOUND`. All eight are HTTP 404."

    Design: Corner/entities/unknown_path_ids_return_typed_not_found_errors
    """
    for response in (
        api.get_time_entry(NON_EXISTENT_UUID, CONTROLLER),
        api.get_expense(NON_EXISTENT_UUID, CONTROLLER),
        api.get_consultant_invoice(NON_EXISTENT_UUID, CONTROLLER),
    ):
        validate_error(response, ERR_CHARGE_NOT_FOUND, 404)


def test_project_list_pages_report_total_count_and_whether_more_remain(
    api, private_client
):
    """
    Three projects paged two at a time: the envelope reports the whole population
    in total_count on both pages while has_more is true only while rows are still
    unseen behind the page window.

    PRD §2.3: "List responses report pagination state in the envelope's `meta` object through four fields: `limit`, `offset`, `total_count` and `has_more`."
    PRD §2.3: "`offset` is the number of items to skip and defaults to 0; it may not be negative."
    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by their creation timestamp, `created_at`, in ascending order."

    Design: Corner/entities/project_listing_paginates_and_filters
    """
    alpha = create_project(api, private_client["id"], name="Project Alpha")
    beta = create_project(
        api,
        private_client["id"],
        name="Project Beta",
        contract_amount=400000.00,
        percent_complete_method="ASSESSED",
    )
    gamma = create_project(
        api,
        private_client["id"],
        name="Project Gamma",
        contract_type="FIXED_FEE",
        contract_amount=250000.00,
        project_manager_user_id=PROJECT_MANAGER_ALT_USER_ID,
        percent_complete_method="ASSESSED",
        target_multiplier=2.8000,
    )

    page_one, meta_one = validate_paginated(
        api.list_projects(ACCOUNTANT, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, f"a page limited to 2 must carry 2 rows, got {len(page_one)}"
    assert_pagination_meta(meta_one, limit=2, offset=0, total_count=3, has_more=True)
    assert_created_at_ascending(page_one)

    page_two, meta_two = validate_paginated(
        api.list_projects(ACCOUNTANT, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, (
        f"the third row is alone on the second page, got {len(page_two)}"
    )
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)

    paged_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert sorted(paged_ids) == sorted([alpha["id"], beta["id"], gamma["id"]]), (
        "the two pages together must cover every project exactly once, got "
        f"{paged_ids}"
    )


def test_project_list_filters_narrow_the_reported_population(api, private_client):
    """
    total_count follows the filter rather than the whole table: asking for one
    manager's work reports only that manager's project, and asking for projects
    already open for business reports none at all while all three are still in
    setup.

    PRD §2.9: "The other available filters are `is_public_agency` on clients; `client_id`, `project_manager_user_id` and `status` on projects"
    PRD §3.1: "A project is then created in the `SETUP` state by a `FirmAdmin` or a `Controller`"
    PRD §2.3: "List responses report pagination state in the envelope's `meta` object through four fields: `limit`, `offset`, `total_count` and `has_more`."

    Design: Corner/entities/project_listing_paginates_and_filters
    """
    create_project(api, private_client["id"], name="Project Alpha")
    create_project(api, private_client["id"], name="Project Beta", contract_amount=400000.00)
    gamma = create_project(
        api,
        private_client["id"],
        name="Project Gamma",
        contract_type="FIXED_FEE",
        contract_amount=250000.00,
        project_manager_user_id=PROJECT_MANAGER_ALT_USER_ID,
    )

    by_manager, manager_meta = validate_paginated(
        api.list_projects(ACCOUNTANT, {"project_manager_user_id": PROJECT_MANAGER_ALT_USER_ID})
    )
    assert [row["id"] for row in by_manager] == [gamma["id"]], (
        "only the project that manager owns may come back, got "
        f"{[row['name'] for row in by_manager]}"
    )
    assert_pagination_meta(manager_meta, total_count=1, has_more=False)

    by_status, status_meta = validate_paginated(
        api.list_projects(ACCOUNTANT, {"status": PROJECT_ACTIVE})
    )
    assert by_status == [], (
        f"no project has been opened for business yet, got {by_status}"
    )
    assert_pagination_meta(status_meta, total_count=0, has_more=False)


def test_project_creation_refuses_an_out_of_range_multiplier_or_unknown_contract_type(
    api, private_client
):
    """
    Shape validation runs ahead of every business rule, so a target multiplier
    above its declared ceiling, a contract type outside the three the firm sells
    and a payload missing a required figure are all malformed requests, and none
    of them leaves a project behind.

    PRD §3.1: "a `target_multiplier` between 1.0000 and 6.0000 at 4 decimal places, and optionally a `wip_alert_threshold`"
    PRD §2.5: "A request carrying money with more than 2 decimal places, a ratio outside its declared range, a negative amount where a non-negative one is required, a malformed calendar date, an unknown enumeration member, a missing required field or a value of the wrong JSON type is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/out_of_range_and_contradictory_inputs_rejected
    """
    over_range = f.project_payload(
        private_client["id"], name="Over-range multiplier", target_multiplier=6.5000
    )
    validate_error(api.create_project(over_range, CONTROLLER), ERR_INVALID_REQUEST, 400)

    unknown_type = f.project_payload(
        private_client["id"], name="Bad contract type", contract_type="RETAINER"
    )
    validate_error(api.create_project(unknown_type, CONTROLLER), ERR_INVALID_REQUEST, 400)

    missing_multiplier = f.project_payload(private_client["id"], name="No multiplier")
    missing_multiplier.pop("target_multiplier")
    validate_error(
        api.create_project(missing_multiplier, CONTROLLER), ERR_INVALID_REQUEST, 400
    )

    rows, meta = validate_paginated(api.list_projects(CONTROLLER))
    assert rows == [], f"a refused creation must store nothing, got {rows}"
    assert_pagination_meta(meta, total_count=0)


def test_phase_creation_refuses_a_fee_field_that_contradicts_the_declared_basis(
    api, private_client
):
    """
    The fee basis dictates exactly one fee field: a fraction of the contract above
    its declared ceiling, a lump sum node that also carries a fraction, and a lump
    sum node carrying no fee at all are all malformed, and no phase is stored.

    PRD §3.1: "When `fee_basis` is `PERCENT_OF_CONTRACT`, a `fee_percent` between 0.0001 and 1.0000 at 4 decimal places is required and `lump_sum_fee` must be omitted"
    PRD §3.1: "Supplying the fee field that contradicts the declared basis, or omitting the one it requires, is a malformed request and returns `ERR_INVALID_REQUEST`."
    PRD §2.5: "The same error covers a fee field that contradicts the phase's declared fee basis."

    Design: Corner/entities/out_of_range_and_contradictory_inputs_rejected
    """
    project = create_project(
        api, private_client["id"], name="Riverside Library", contract_amount=800000.00
    )

    over_range_fraction = f.percent_phase_payload(
        project["id"], wbs_code="03-CD", fee_percent=1.5000, budget_labor_cost=10000.00
    )
    validate_error(
        api.create_phase(over_range_fraction, CONTROLLER), ERR_INVALID_REQUEST, 400
    )

    both_fee_fields = f.lump_sum_phase_payload(
        project["id"],
        wbs_code="04-CA",
        lump_sum_fee=50000.00,
        budget_labor_cost=10000.00,
        fee_percent=0.1000,
    )
    validate_error(api.create_phase(both_fee_fields, CONTROLLER), ERR_INVALID_REQUEST, 400)

    no_fee_field = f.lump_sum_phase_payload(
        project["id"], wbs_code="05-CA", budget_labor_cost=10000.00
    )
    no_fee_field.pop("lump_sum_fee")
    validate_error(api.create_phase(no_fee_field, CONTROLLER), ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_phases(CONTROLLER, {"project_id": project["id"]})
    )
    assert rows == [], f"a refused phase creation must store nothing, got {rows}"
    assert_pagination_meta(meta, total_count=0)


def test_timesheet_hours_above_the_daily_cap_and_a_zero_page_limit_are_malformed(
    api, private_client
):
    """
    The same shape gate covers a charge payload and a query string: 30.00 hours in
    one day is above the declared cap, a timesheet line with no hours at all is
    missing a required figure, and a page limit of zero is outside the accepted
    pagination range. Shape is judged before the owning project's status, so none
    of the three reports a project state error.

    PRD §3.3: "and `hours` strictly greater than 0.00 and no more than 24.00 at 2 decimal places"
    PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.8: "7. Request and query shape — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/out_of_range_and_contradictory_inputs_rejected
    """
    project = create_project(
        api, private_client["id"], name="Riverside Library", contract_amount=800000.00
    )
    phase = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=200000.00,
        budget_labor_cost=60000.00,
    )

    over_cap = f.time_entry_payload(
        project["id"], phase["id"], work_date="2026-05-11", hours=30.00
    )
    validate_error(api.create_time_entry(over_cap, ACCOUNTANT), ERR_INVALID_REQUEST, 400)

    missing_hours = f.time_entry_payload(
        project["id"], phase["id"], work_date="2026-05-11"
    )
    missing_hours.pop("hours")
    validate_error(
        api.create_time_entry(missing_hours, ACCOUNTANT), ERR_INVALID_REQUEST, 400
    )

    validate_error(
        api.list_projects(CONTROLLER, {"limit": 0}), ERR_INVALID_REQUEST, 400
    )

    rows, meta = validate_paginated(
        api.list_time_entries(CONTROLLER, {"project_id": project["id"]})
    )
    assert rows == [], f"a refused timesheet line must store nothing, got {rows}"
    assert_pagination_meta(meta, total_count=0)


def test_a_published_labour_cost_rate_carries_no_mutation_counter(api, clock_june):
    """
    Published rate history is append-only, so the row the firm publishes carries
    an identity and a creation stamp and nothing else that could record an edit:
    no refreshed timestamp and no counter.

    PRD §2.4: "A `LaborRate` is the other: published rate history is append-only and is never edited in place; a change of rate is a new row over a new effective window."
    PRD §3.2: "a `raw_cost_rate` strictly greater than 0.00 at 2 decimal places giving the hourly raw cost of that labour grade, an inclusive `effective_from` calendar date, and optionally an `effective_to` calendar date which, when supplied, must be strictly later than `effective_from`."

    Design: Corner/entities/labor_rate_is_immutable_and_corrected_only_by_a_new_window
    """
    rate = validate_success(
        api.create_labor_rate(
            f.labor_rate_payload(
                ROLE_CODE_PROJECT_ARCHITECT, 62.50, "2026-01-01", "2026-07-01"
            ),
            CONTROLLER,
        ),
        201,
    )

    assert_immutable_common_fields(rate)
    assert rate["created_at"] == PINNED_CLOCK_STAMP
    assert rate["role_code"] == ROLE_CODE_PROJECT_ARCHITECT
    assert_money(rate["raw_cost_rate"], 62.50, "labor_rate.raw_cost_rate")
    assert rate["effective_from"] == "2026-01-01"
    assert rate["effective_to"] == "2026-07-01"


def test_a_rate_correction_is_a_second_adjacent_window_and_both_are_retained(
    api, clock_june
):
    """
    Because a published rate can never be edited in place, a raise is expressed as
    a second window starting exactly where the first one ends. The windows are
    half-open, so touching windows neither overlap nor leave a gap, and the
    listing keeps both as history.

    PRD §3.2: "Because of that, two windows for the same `role_code` that merely touch — where the earlier window's `effective_to` equals the later window's `effective_from` — are adjacent, leave neither gap nor overlap, and are entirely legal."
    PRD §3.2: "The firm's cost side is governed by a firm-wide, append-only table of labour cost rates that only a `Controller` may publish."

    Design: Corner/entities/labor_rate_is_immutable_and_corrected_only_by_a_new_window
    """
    first = validate_success(
        api.create_labor_rate(
            f.labor_rate_payload(
                ROLE_CODE_PROJECT_ARCHITECT, 62.50, "2026-01-01", "2026-07-01"
            ),
            CONTROLLER,
        ),
        201,
    )

    second = validate_success(
        api.create_labor_rate(
            f.labor_rate_payload(ROLE_CODE_PROJECT_ARCHITECT, 65.00, "2026-07-01"),
            CONTROLLER,
        ),
        201,
    )
    assert second["effective_from"] == "2026-07-01", (
        "the successor window starts exactly where the incumbent's ends"
    )
    assert second.get("effective_to") is None, (
        f"an omitted end date leaves the window open-ended, got {second.get('effective_to')!r}"
    )
    assert_money(second["raw_cost_rate"], 65.00, "labor_rate.raw_cost_rate")

    rows, meta = validate_paginated(
        api.list_labor_rates(CONTROLLER, {"role_code": ROLE_CODE_PROJECT_ARCHITECT})
    )
    assert_pagination_meta(meta, total_count=2)
    assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]]), (
        f"both windows must be retained as history, got {rows}"
    )
    superseded = next(row for row in rows if row["id"] == first["id"])
    assert_money(
        superseded["raw_cost_rate"], 62.50, "the earlier window's raw_cost_rate"
    )
    assert superseded["effective_to"] == "2026-07-01", (
        "the earlier window is untouched by the correction that followed it"
    )


def test_a_parent_phase_from_another_project_is_refused(api, private_client):
    """
    The self-referential link between phases is scoped to one project's work
    breakdown structure: a real phase identifier borrowed from a different project
    is refused, and the second project is left with no phase at all.

    PRD §3.1: "A supplied `parent_phase_id` must reference a phase of the same project and must not close a cycle in the tree; either fault is refused with `ERR_WBS_CYCLE` (HTTP 422)."
    PRD §3.1: "The project's shape is a **work breakdown structure**: a self-referential tree of phases."

    Design: Corner/entities/phase_parent_must_belong_to_the_same_project
    """
    project_alpha = create_project(
        api, private_client["id"], name="Project Alpha", contract_amount=800000.00
    )
    project_beta = create_project(
        api, private_client["id"], name="Project Beta", contract_amount=400000.00
    )
    parent = add_lump_sum_phase(
        api,
        project_alpha["id"],
        wbs_code="02-DD",
        lump_sum_fee=200000.00,
        budget_labor_cost=60000.00,
    )

    borrowed_parent = f.lump_sum_phase_payload(
        project_beta["id"],
        wbs_code="02-DD-1",
        lump_sum_fee=50000.00,
        budget_labor_cost=10000.00,
        parent_phase_id=parent["id"],
    )
    validate_error(api.create_phase(borrowed_parent, CONTROLLER), ERR_WBS_CYCLE, 422)

    rows, meta = validate_paginated(
        api.list_phases(CONTROLLER, {"project_id": project_beta["id"]})
    )
    assert rows == [], f"the refused request must create nothing, got {rows}"
    assert_pagination_meta(meta, total_count=0)


def test_a_child_phase_takes_depth_one_and_unseats_its_parent_as_a_leaf(
    api, private_client
):
    """
    The same request shape inside one project succeeds: the child sits one level
    down and is itself a leaf, while the phase it hangs under stops being a leaf
    from that moment on and is no longer chargeable.

    PRD §3.1: "Each phase reports a computed `depth` — 0 for a top-level phase, and one more than its parent's `depth` otherwise — and a computed `is_leaf` flag, which is true exactly when no other phase declares this phase as its `parent_phase_id`."
    PRD §3.1: "The corollary bites during setup: adding a child under a phase that was previously a leaf makes that parent non-leaf, and it is no longer chargeable from that moment on."

    Design: Corner/entities/phase_parent_must_belong_to_the_same_project
    """
    project = create_project(
        api, private_client["id"], name="Project Alpha", contract_amount=800000.00
    )
    parent = add_lump_sum_phase(
        api,
        project["id"],
        wbs_code="02-DD",
        lump_sum_fee=200000.00,
        budget_labor_cost=60000.00,
    )
    assert parent["is_leaf"] is True and parent["depth"] == 0

    child = validate_success(
        api.create_phase(
            f.lump_sum_phase_payload(
                project["id"],
                wbs_code="02-DD-1",
                lump_sum_fee=50000.00,
                budget_labor_cost=10000.00,
                parent_phase_id=parent["id"],
            ),
            CONTROLLER,
        ),
        201,
    )
    assert child["parent_phase_id"] == parent["id"]
    assert child["depth"] == 1, f"a child of a top-level node sits at depth 1, got {child['depth']}"
    assert child["is_leaf"] is True, "the new child declares no children of its own"
    assert_money(child["phase_fee"], 50000.00, "child phase.phase_fee")

    reread_parent = read_phase(api, parent["id"])
    assert reread_parent["is_leaf"] is False, (
        "a phase that now has a child phase is no longer a leaf"
    )
    assert reread_parent["depth"] == 0


def test_an_unresolvable_client_in_the_creation_payload_is_a_reference_fault(
    api, clock_june
):
    """
    Integrity lives in the body rather than in nested routes, so naming a billing
    client that does not exist fails as an unresolved reference and not as a
    missing path resource — and no project is stored.

    PRD §2.9: "When `client_id`, `project_id`, `phase_id`, `parent_phase_id`, `subcontract_id` or `invoice_id` appears in a creation payload and does not resolve — or when a referenced `phase_id` resolves but belongs to a project other than the referenced `project_id` — the request is rejected with `ERR_INVALID_REFERENCE` (HTTP 422)."
    PRD §2.9: "Foreign keys arriving in a request **body** are a separate check with a separate code."

    Design: Corner/entities/body_foreign_keys_must_resolve_and_agree
    """
    orphan = f.project_payload(
        NON_EXISTENT_UUID, name="Orphan project", contract_amount=100000.00
    )

    response = api.create_project(orphan, CONTROLLER)
    validate_error(response, ERR_INVALID_REFERENCE, 422)
    assert response.status_code == 422, (
        "an unresolved body key is a reference fault, never a path miss, got "
        f"{response.status_code}"
    )

    rows, meta = validate_paginated(api.list_projects(CONTROLLER))
    assert rows == [], f"the refused creation must store nothing, got {rows}"
    assert_pagination_meta(meta, total_count=0)


def test_a_timesheet_line_must_name_a_phase_of_the_project_it_charges(api):
    """
    A timesheet line carries both a project and a phase, and the two must agree:
    a phase that exists but belongs to another project is refused even though each
    identifier resolves on its own, while the consistent pair is accepted and
    lands as a submitted line.

    PRD §2.9: "When `client_id`, `project_id`, `phase_id`, `parent_phase_id`, `subcontract_id` or `invoice_id` appears in a creation payload and does not resolve — or when a referenced `phase_id` resolves but belongs to a project other than the referenced `project_id` — the request is rejected with `ERR_INVALID_REFERENCE` (HTTP 422)."
    PRD §3.3: "The line lands in `status` `SUBMITTED` and, crucially, carries no money yet: its `raw_cost` and `billable_amount` are both 0.00 and its `applied_multiplier` is `null`."

    Design: Corner/entities/body_foreign_keys_must_resolve_and_agree
    """
    alpha = build_active_project(api, project_overrides={"name": "Project Alpha"})
    beta = build_active_project(
        api,
        clock=None,
        publish_rate=False,
        project_overrides={"name": "Project Beta", "contract_amount": 400000.00},
        phase_overrides={"lump_sum_fee": 100000.00, "budget_labor_cost": 30000.00},
    )

    crossed = f.time_entry_payload(
        alpha.project_id, beta.phase_id, work_date="2026-05-11", hours=8.00
    )
    validate_error(api.create_time_entry(crossed, ACCOUNTANT), ERR_INVALID_REFERENCE, 422)

    consistent = f.time_entry_payload(
        alpha.project_id, alpha.phase_id, work_date="2026-05-11", hours=8.00
    )
    entry = validate_success(api.create_time_entry(consistent, ACCOUNTANT), 201)
    assert entry["status"] == TIME_ENTRY_SUBMITTED
    assert entry["project_id"] == alpha.project_id
    assert entry["phase_id"] == alpha.phase_id

    rows, meta = validate_paginated(
        api.list_time_entries(ACCOUNTANT, {"project_id": alpha.project_id})
    )
    assert [row["id"] for row in rows] == [entry["id"]], (
        f"only the consistent line may have been stored, got {rows}"
    )
    assert_pagination_meta(meta, total_count=1)
