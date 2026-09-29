"""Entity-shape probes: what each create call persists, what the server stamps on top of it, and
what a read or a listing gives back."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_common_fields,
    assert_pct,
    make_adjudicator_headers,
    make_officer_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    create_aoi,
    create_base_property,
    create_pasture,
    create_permit,
    create_permittee,
    get_allotment,
    get_aoi,
    get_pasture,
    get_permittee,
    get_use_record,
    issue_permit,
    list_bills,
)

# A well-formed identifier that no call in this suite ever mints.
NEVER_MINTED_ID = "00000000-0000-4000-8000-000000000001"


def _create_allotment(payload, headers=None):
    """POST /allotments with a hand-built body, so a field can be genuinely absent."""
    return api_client.create_allotment(payload, headers or make_officer_headers())


def _allotment(**overrides):
    return get_success_data(_create_allotment(f.allotment_payload(**overrides)), 201)


def _all_allotment_codes():
    """Every admin_unit_code in the register, walked page by page (PRD 2.3)."""
    codes = []
    offset = 0
    while True:
        items, meta = validate_paginated(
            api_client.list_allotments(make_officer_headers(), {"limit": 100, "offset": offset}))
        codes.extend(row["admin_unit_code"] for row in items)
        if not meta["has_more"]:
            return codes
        offset += 100


def test_registering_an_allotment_stamps_the_full_ledger_and_a_permissive_posture():
    """A create that supplies only the seven input fields comes back with the whole derived
    surface: capacity 1500 / allocated 0 / open 1500, adjustment 0.0, OPEN, NOT_ASSESSED and a
    current_grazing_year of 2026 read off the logical clock — and the allotment created just before
    it keeps its own 400 open AUMs.

    PRD 3.1: "A freshly registered allotment starts in a fully permissive posture. Its
    `allotment_status` is `OPEN`, its `health_determination` is `NOT_ASSESSED`, its
    `stocking_adjustment_pct` is 0, and its capacity ledger reads `effective_capacity_aums` equal
    to `total_permitted_aums`, `allocated_aums` of 0 and `open_aums` equal to
    `total_permitted_aums`."
    PRD 3.1: "Its `current_grazing_year` is set to the calendar year of the logical clock."
    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created and increases
    by exactly 1 on every mutation of that resource, whether the mutation was requested directly by
    a client or applied as a side effect of an operation on some other resource."

    Design: Corner/entities/corner_allotment_creation_populates_ledger_and_posture_fields
    """
    neighbour = _allotment(name="Baseline Allotment", admin_unit_code="QA-101", acres=12000,
                           total_permitted_aums=400, season_start="03-01", season_end="10-31")

    created = _allotment(name="Creation Probe Allotment", admin_unit_code="QA-102", acres=48000,
                         total_permitted_aums=1500, season_start="01-01", season_end="12-31",
                         required_pasture_rotation_count=3)

    assert created["name"] == "Creation Probe Allotment"
    assert created["admin_unit_code"] == "QA-102"
    assert created["acres"] == 48000
    assert created["total_permitted_aums"] == 1500
    assert created["season_start"] == "01-01"
    assert created["season_end"] == "12-31"
    assert created["required_pasture_rotation_count"] == 3

    assert_pct(created["stocking_adjustment_pct"], 0.0)
    assert created["effective_capacity_aums"] == 1500
    assert created["allocated_aums"] == 0
    assert created["open_aums"] == 1500
    assert created["allotment_status"] == "OPEN"
    assert created["health_determination"] == "NOT_ASSESSED"
    assert created["current_grazing_year"] == 2026
    assert_common_fields(created)

    assert get_allotment(neighbour["id"])["open_aums"] == 400, (
        "a second registration does not touch the first allotment's ledger")


def test_reading_an_allotment_back_returns_the_persisted_row_without_drift():
    """The row a specialist reads is the row the officer's create returned, field for field: 900
    permitted AUMs still read 900 of capacity and 900 open, and the recurring season is still
    04-01 to 09-30.

    PRD 3.1: "Officers and specialists can therefore browse the inventory filtered by
    `allotment_status`, by `health_determination` or by `admin_unit_code`, and read a single
    allotment to see its live ledger and its current `version`."
    PRD 2.4: "`updated_at` is the ISO 8601 UTC instant of the most recent mutation of that
    resource, in the same format, and equals `created_at` on a resource that has never been mutated
    since creation."

    Design: Corner/entities/corner_allotment_retrieval_returns_stored_row
    """
    created = _allotment(name="Retrieval Probe", admin_unit_code="QA-103", acres=21000,
                         total_permitted_aums=900, season_start="04-01", season_end="09-30",
                         required_pasture_rotation_count=2)

    read = get_success_data(api_client.get_allotment(created["id"], make_specialist_headers()))
    assert read["id"] == created["id"]
    assert read["total_permitted_aums"] == 900
    assert read["effective_capacity_aums"] == 900
    assert read["open_aums"] == 900
    assert read["allocated_aums"] == 0
    assert read["season_start"] == "04-01"
    assert read["season_end"] == "09-30"
    assert read["allotment_status"] == "OPEN"
    assert read["health_determination"] == "NOT_ASSESSED"
    assert read["version"] == created["version"]
    assert read["updated_at"] == read["created_at"], "nothing has mutated the row since creation"


def test_the_allotment_listing_paginates_and_narrows_by_status():
    """A limit of 2 over a register that holds at least the three allotments just created returns
    exactly 2 rows with has_more true and the effective limit and offset echoed in meta; the
    allotment_status=CLOSED filter then answers with closed allotments only, holding the one
    carrying the FULL_CLOSURE order and neither of its two open neighbours.

    PRD 2.3: "Listing responses carry `response_type` of `"array"` and place the array of resource
    objects directly in `data`. The `meta` object of a listing response additionally carries `limit`
    (the effective page size), `offset` (the effective starting position), `total_count` (the number
    of records matching the filters before pagination is applied) and `has_more` (true exactly when
    records matching the filters remain beyond the current page)."
    PRD 2.3: "All other filter parameters named in §4 narrow the result set by exact equality on the
    named field, and combining several filters narrows by conjunction."
    PRD 3.10: "It is exactly 1.0 when any closure order on the allotment in `order_status` `ACTIVE`
    has `order_type` `WILDFIRE_CLOSURE` or `FULL_CLOSURE`."

    Design: Corner/entities/corner_allotment_listing_paginates_and_filters_by_status
    """
    one = _allotment(name="List Probe One", admin_unit_code="QA-104", acres=10000,
                     total_permitted_aums=300, season_start="01-01", season_end="12-31")
    two = _allotment(name="List Probe Two", admin_unit_code="QA-105", acres=11000,
                     total_permitted_aums=320, season_start="01-01", season_end="12-31")
    three = _allotment(name="List Probe Three", admin_unit_code="QA-106", acres=12500,
                       total_permitted_aums=340, season_start="01-01", season_end="12-31")
    get_success_data(api_client.create_closure_order(
        {"allotment_id": three["id"], "order_type": "FULL_CLOSURE",
         "effective_start_date": "2026-08-05", "effective_end_date": "2026-11-30",
         "justification": "Administrative full closure pending allotment boundary resurvey."},
        make_officer_headers()), 201)

    page, meta = validate_paginated(api_client.list_allotments(
        make_adjudicator_headers(), {"limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True

    closed, closed_meta = validate_paginated(api_client.list_allotments(
        make_adjudicator_headers(), {"allotment_status": "CLOSED", "limit": 100}))
    assert closed_meta["total_count"] >= 1
    ids = [row["id"] for row in closed]
    assert three["id"] in ids
    assert one["id"] not in ids
    assert two["id"] not in ids
    for row in closed:
        assert row["allotment_status"] == "CLOSED", "the filter is exact equality on the field"

    shut = get_allotment(three["id"])
    assert shut["allotment_status"] == "CLOSED"
    assert_pct(shut["stocking_adjustment_pct"], 1.0)
    assert shut["effective_capacity_aums"] == 0
    assert get_allotment(one["id"])["allotment_status"] == "OPEN", (
        "the closure order is scoped to its own allotment")
    assert get_allotment(two["id"])["allotment_status"] == "OPEN"


def test_getting_an_allotment_by_an_id_that_was_never_minted_is_a_404():
    """A well-formed identifier that no create ever returned answers with HTTP 404 and
    ERR_ALLOTMENT_NOT_FOUND rather than an empty 200, and the real allotment beside it is
    untouched.

    PRD 2.6: "Nested paths are resolved strictly left to right, so the outermost missing identifier
    wins: a request naming an allotment that does not exist and, beneath it, a pasture that also
    does not exist, reports the allotment failure. Each entity has its own not-found code: an
    allotment yields `ERR_ALLOTMENT_NOT_FOUND`, a pasture `ERR_PASTURE_NOT_FOUND`, a permittee
    `ERR_PERMITTEE_NOT_FOUND`, a base property `ERR_BASE_PROPERTY_NOT_FOUND`, a grazing permit
    `ERR_PERMIT_NOT_FOUND`, an annual operating instruction `ERR_AOI_NOT_FOUND`, a pasture use
    record `ERR_USE_RECORD_NOT_FOUND`, a grazing bill `ERR_BILL_NOT_FOUND`, a rangeland health
    assessment `ERR_ASSESSMENT_NOT_FOUND`, a permit decision `ERR_DECISION_NOT_FOUND`, an appeal
    case `ERR_APPEAL_NOT_FOUND`, a closure order `ERR_CLOSURE_ORDER_NOT_FOUND`, a trespass incident
    `ERR_TRESPASS_NOT_FOUND` and a range improvement project `ERR_PROJECT_NOT_FOUND`. All fourteen
    carry HTTP 404."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left
    to right as described at the top of this subsection. Applies to every operation that carries a
    path parameter."

    Design: Corner/entities/corner_allotment_get_unknown_id_returns_allotment_not_found
    """
    existing = _allotment(name="NotFound Probe", admin_unit_code="QA-107", acres=9000,
                          total_permitted_aums=260, season_start="01-01", season_end="12-31")

    validate_error(api_client.get_allotment(NEVER_MINTED_ID, make_officer_headers()),
                   ApiErrorId.ERR_ALLOTMENT_NOT_FOUND, 404)

    still_there = get_allotment(existing["id"])
    assert still_there["id"] == existing["id"]
    assert still_there["open_aums"] == 260


def test_omitting_a_required_field_rejects_the_create_and_writes_nothing():
    """total_permitted_aums carries no default, so a body without it is a request-shape failure —
    HTTP 400 ERR_VALIDATION — and the register never gains a row bearing the rejected code.

    PRD 2.6: "**Request shape** — `ERR_VALIDATION`, HTTP 400. Every field marked as required for
    the operation is present and non-null; every enumerated field holds one of its declared
    members; every field whose name ends in `_aums`, `_cents`, `_count`, `_days`, together with
    `acres`, is an integer that is not negative, with head counts (`planned_head_count`,
    `actual_head_count`, `head_count`) and `unauthorized_days` required to be at least 1; every
    field whose name ends in `_pct` is a number between 0.0 and 1.0 inclusive; every field whose
    name ends in `_score` is an integer between 0 and 100 inclusive; `observed_utilization_pct` is
    an integer between 1 and 100 inclusive; date-valued fields are ISO 8601 calendar dates in
    `YYYY-MM-DD` form; the allotment's `season_start` and `season_end` are `MM-DD` strings with no
    year; and instant-valued fields (`detected_at`, `current_utc`) are ISO 8601 UTC instants with a
    trailing `Z`."
    PRD 3.1: "An `AuthorizedOfficer` registers one by supplying its `name` (between 1 and 120
    characters, and not blank), the administering field office's `admin_unit_code` (two uppercase
    letters, a hyphen, then three digits, as in `NV-042`), the `acres` of public land inside the
    boundary (at least 1), and the `total_permitted_aums` the inventory carries before any
    adjustment (also at least 1)."

    Design: Corner/entities/corner_allotment_create_missing_required_field_rejected
    """
    baseline = _allotment(name="Required Field Baseline", admin_unit_code="QA-108", acres=8000,
                          total_permitted_aums=240, season_start="01-01", season_end="12-31")

    validate_error(
        _create_allotment({"name": "Incomplete Allotment", "admin_unit_code": "QA-109",
                           "acres": 8000, "season_start": "01-01", "season_end": "12-31"}),
        ApiErrorId.ERR_VALIDATION, 400)

    codes = _all_allotment_codes()
    assert "QA-109" not in codes, "the rejected request persisted nothing"
    assert "QA-108" in codes
    assert get_allotment(baseline["id"])["total_permitted_aums"] == 240


def _rotation_setup():
    """An allotment registered WITHOUT required_pasture_rotation_count, two pastures on it, and a
    DRAFT 2026 instruction of 200 AUMs scheduling only the first pasture."""
    allotment = get_success_data(_create_allotment(
        {"name": "Default Rotation Allotment", "admin_unit_code": "QA-110", "acres": 15000,
         "total_permitted_aums": 600, "season_start": "01-01", "season_end": "12-31"}), 201)
    first = create_pasture(allotment["id"], name="Rotation Pasture One",
                           pasture_aum_capacity=300, sequence_order=1)
    second = create_pasture(allotment["id"], name="Rotation Pasture Two",
                            pasture_aum_capacity=300, sequence_order=2)
    permittee = create_permittee(name="Default Rotation Ranch",
                                 contact_email="rotation@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                        legal_description="T41N R63E Sec 04 SW",
                                        carrying_capacity_aums=200,
                                        controlled_since_date="2014-03-01")
    permit = issue_permit(create_permit(
        allotment["id"], permittee["id"], base_property["id"], requested_aums=200,
        term_start_date="2026-01-01", term_end_date="2031-12-31",
        livestock_kind="CATTLE")["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=200,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    record = add_use_record(aoi["id"], first["id"], planned_head_count=60,
                            livestock_kind="CATTLE", planned_entry_date="2026-05-01",
                            planned_exit_date="2026-06-01")
    return {"allotment": allotment, "first": first, "second": second, "aoi": aoi,
            "record": record}


def test_the_rotation_requirement_defaults_to_two_and_the_issue_gate_enforces_it():
    """The create omitted required_pasture_rotation_count, so the allotment reads 2 — and that
    default is what refuses issuance of an instruction whose distinct_pasture_count is 1, with
    ERR_ROTATION_REQUIREMENT_NOT_MET and no preliminary bill; scheduling a second leg on the second
    pasture takes the count to 2 and the identical issue call then succeeds.

    PRD 3.1: "The officer may also supply `required_pasture_rotation_count`, the minimum number of
    distinct pastures an operating instruction must schedule before it may be issued; when omitted
    it defaults to 2, and it must be at least 1."
    PRD 2.6: "**Rotation requirement** — `ERR_ROTATION_REQUIREMENT_NOT_MET`, HTTP 422, on
    operating-instruction issuance. The instruction's `distinct_pasture_count` must be at least the
    allotment's `required_pasture_rotation_count`, and every pasture of that allotment whose
    `rest_required` is true must be absent from the instruction's use records."
    PRD 3.4: "Once the leg is stored, the instruction's `planned_aums_total` is recomputed as the
    sum of `planned_aums` over **all** of its use records regardless of `record_status`, its
    `distinct_pasture_count` as the number of distinct `pasture_id` values across all of those
    records, and the named pasture's `scheduled_aums` roll-up is refreshed."

    Design: Corner/entities/corner_allotment_rotation_count_defaults_to_two
    """
    setup = _rotation_setup()
    assert setup["allotment"]["required_pasture_rotation_count"] == 2, (
        "the omitted field takes its declared default")
    assert_aums(setup["record"]["planned_aums"], 62.00)  # 60 head x CATTLE 1.0 x 31 days / 30
    drafted = get_aoi(setup["aoi"]["id"])
    assert drafted["distinct_pasture_count"] == 1

    validate_error(api_client.issue_aoi(setup["aoi"]["id"], make_officer_headers()),
                   ApiErrorId.ERR_ROTATION_REQUIREMENT_NOT_MET, 422)
    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "DRAFT"
    assert list_bills(aoi_id=setup["aoi"]["id"], bill_type="PRELIMINARY_USE") == []

    add_use_record(setup["aoi"]["id"], setup["second"]["id"], planned_head_count=60,
                   livestock_kind="CATTLE", planned_entry_date="2026-06-05",
                   planned_exit_date="2026-07-06")
    two_pastures = get_aoi(setup["aoi"]["id"])
    assert two_pastures["distinct_pasture_count"] == 2
    assert_aums(two_pastures["planned_aums_total"], 124.00)

    issued = get_success_data(api_client.issue_aoi(setup["aoi"]["id"], make_officer_headers()))
    assert issued["aoi_status"] == "ISSUED"


def test_qualified_aums_follows_the_base_property_type_not_the_carrying_capacity():
    """Two properties of the same permittee with an identical 400 AUMs of carrying capacity qualify
    differently: the LAND property qualifies all 400 and the LIVESTOCK property only 300, while both
    rows keep their 400 of carrying capacity untouched.

    PRD 3.2: "Deeded land qualifies at full strength: the qualification factor for a `LAND` property
    is 1.0."
    PRD 3.2: "Controlled livestock qualifies at three-quarters strength: the factor for a
    `LIVESTOCK` property is 0.75."
    PRD 3.2: "The property's `qualified_aums` is its `carrying_capacity_aums` multiplied by that
    factor, floored to a whole AUM."
    PRD 3.2: "A `LAND` property producing 400 AUMs therefore qualifies 400; a `LIVESTOCK` property
    producing the same 400 qualifies 300, and one producing 401 qualifies 300 as well, because the
    product 300.75 is floored rather than rounded."
    PRD 3.2: "Base properties are listed beneath their permittee or across the register, narrowed by
    `permittee_id` or by `base_property_type`."

    Design: Corner/entities/corner_base_property_qualified_aums_computed_by_type_factor
    """
    permittee = create_permittee(name="Qualification Ranch", contact_email="qual@example.com")

    land = create_base_property(permittee["id"], base_property_type="LAND",
                                legal_description="T44N R61E Sec 22 all",
                                carrying_capacity_aums=400,
                                controlled_since_date="2010-06-15")
    livestock = create_base_property(permittee["id"], base_property_type="LIVESTOCK",
                                     legal_description="Brand-inspected herd of 400 head, Elko",
                                     carrying_capacity_aums=400,
                                     controlled_since_date="2010-06-15")

    assert land["qualified_aums"] == 400
    assert livestock["qualified_aums"] == 300
    assert land["carrying_capacity_aums"] == 400
    assert livestock["carrying_capacity_aums"] == 400, (
        "the factor lands on the derived field only")

    items, meta = validate_paginated(api_client.list_base_properties(
        make_officer_headers(), {"permittee_id": permittee["id"],
                                 "base_property_type": "LIVESTOCK", "limit": 100}))
    assert meta["total_count"] == 1, "the two filters narrow by conjunction"
    assert [row["id"] for row in items] == [livestock["id"]]


def test_a_filed_permit_carries_the_servers_lifecycle_fields_not_the_clients():
    """The application body names none of the lifecycle fields, yet the created row reads
    PENDING_REVIEW / CURRENT with a null predecessor, zero non-use years, the default preference of
    2 and a null suspension reason — and the 300 AUMs it seeks are stored as permitted_aums without
    moving the allotment's allocated total.

    PRD 3.3: "The request-body figure is named `requested_aums`, and the value it carries is stored
    on the permit as `permitted_aums`; the two names refer to the same quantity seen from the client
    side and the server side respectively."
    PRD 3.3: "The application lands in `permit_status` `PENDING_REVIEW` and `account_status`
    `CURRENT`, with `suspension_reason` null, `consecutive_nonuse_years` 0, `predecessor_permit_id`
    null — that self-reference is populated only on a permit born of a renewal or a transfer — and
    `preference_priority` at its default of 2."
    PRD 3.3: "A `PENDING_REVIEW` application consumes no capacity whatsoever; the ledger of §2.9
    does not see it."
    PRD 3.2: "This field is never client-supplied and, importantly, is not computed when the
    application is filed: it is stamped on the transition that moves the permit from
    `PENDING_REVIEW` to `ISSUED`."

    Design: Corner/entities/corner_grazing_permit_system_fields_stamped_by_server
    """
    allotment = _allotment(name="System Fields Allotment", admin_unit_code="QA-111", acres=14000,
                           total_permitted_aums=500, season_start="01-01", season_end="12-31",
                           required_pasture_rotation_count=1)
    permittee = create_permittee(name="System Fields Ranch",
                                 contact_email="sysfields@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         legal_description="T38N R59E Sec 31 NW",
                                         carrying_capacity_aums=300,
                                         controlled_since_date="2016-02-20")

    permit = create_permit(allotment["id"], permittee["id"], base_property["id"],
                           requested_aums=300, term_start_date="2026-03-01",
                           term_end_date="2032-02-28", livestock_kind="SHEEP")

    assert permit["permit_status"] == "PENDING_REVIEW"
    assert permit["account_status"] == "CURRENT"
    assert permit["predecessor_permit_id"] is None
    assert permit["consecutive_nonuse_years"] == 0
    assert permit["preference_priority"] == 2, "LAND is only honoured at issuance"
    assert permit["suspension_reason"] is None
    assert permit["livestock_kind"] == "SHEEP"
    assert permit["permitted_aums"] == 300
    assert_common_fields(permit)

    ledger = get_allotment(allotment["id"])
    assert ledger["allocated_aums"] == 0, "an application reserves nothing"
    assert ledger["open_aums"] == 500


def test_a_scheduled_leg_reports_no_actual_figures_until_use_is_reported():
    """A freshly scheduled leg is SCHEDULED with all four actual columns null and 62.00 planned
    AUMs; its instruction shows 62.00 planned against 0 actual, and because that instruction is
    still DRAFT the pasture's own roll-up stays at 0.

    PRD 3.5: "The instruction's `actual_aums_total` is then recomputed as the sum of `actual_aums`
    over its records whose `record_status` is `ACTUAL_REPORTED` or `ACCEPTED`; records still
    `SCHEDULED` contribute nothing, and `actual_aums` is null until the leg is reported."
    PRD 3.4: "Round the result half-up to 2 decimal places, exactly once. That value is the record's
    `planned_aums`."
    PRD 3.1: "Its `scheduled_aums` is the sum of `planned_aums` over every use record naming that
    pasture whose owning operating instruction has a `grazing_year` equal to the allotment's
    `current_grazing_year` and an `aoi_status` of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`;
    the figure is carried to 2 decimal places and starts at 0."
    PRD 3.1: "Records belonging to draft or voided instructions, and records for any other grazing
    year, contribute nothing."

    Design: Corner/entities/corner_use_record_actual_fields_null_until_reported
    """
    allotment = _allotment(name="Actuals Allotment", admin_unit_code="QA-112", acres=9000,
                           total_permitted_aums=400, season_start="01-01", season_end="12-31",
                           required_pasture_rotation_count=1)
    pasture = create_pasture(allotment["id"], name="Actuals Pasture",
                             pasture_aum_capacity=300, sequence_order=1)
    permittee = create_permittee(name="Actuals Ranch", contact_email="actuals@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         legal_description="T37N R58E Sec 09 SE",
                                         carrying_capacity_aums=200,
                                         controlled_since_date="2013-08-08")
    permit = issue_permit(create_permit(
        allotment["id"], permittee["id"], base_property["id"], requested_aums=200,
        term_start_date="2026-01-01", term_end_date="2030-12-31",
        livestock_kind="CATTLE")["id"])
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=120,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")

    record = add_use_record(aoi["id"], pasture["id"], planned_head_count=60,
                            livestock_kind="CATTLE", planned_entry_date="2026-05-01",
                            planned_exit_date="2026-06-01")

    assert record["record_status"] == "SCHEDULED"
    for column in ("actual_entry_date", "actual_exit_date", "actual_head_count", "actual_aums"):
        assert record[column] is None, "%s is written only by the report call" % column
    assert_aums(record["planned_aums"], 62.00)
    assert get_use_record(record["id"])["record_status"] == "SCHEDULED"

    drafted = get_aoi(aoi["id"])
    assert_aums(drafted["planned_aums_total"], 62.00)
    assert_aums(drafted["actual_aums_total"], 0.00)
    assert drafted["aoi_status"] == "DRAFT"

    assert_aums(get_pasture(pasture["id"])["scheduled_aums"], 0.00)


def test_a_new_permittee_starts_with_an_empty_debt_aggregate():
    """A ranch registered a moment ago owes 0 cents, has been billed for 0 trespass incidents and
    stands IN_GOOD_STANDING — the aggregates are zero rather than null.

    PRD 3.2: "Registration takes only a `name` of 1 to 120 characters and a `contact_email`, which
    must contain an at-sign; the resulting record starts `IN_GOOD_STANDING` with an
    `outstanding_balance_cents` of 0 and a `billed_trespass_incident_count` of 0."
    PRD 3.2: "the trespass counter is itself derived: it is the number of trespass incidents
    attributed to this permittee whose `incident_status` is `BILLED` or `RESOLVED`."
    PRD 2.9: "A permittee's `outstanding_balance_cents` always equals the sum, over that permittee's
    bills whose `bill_status` is `ISSUED` or `DELINQUENT`, of each bill's `total_amount_cents` less
    its `amount_paid_cents`; bills in `PAID` or `VOIDED` contribute nothing, and an
    `ADJUSTMENT_CREDIT` bill contributes its negative total and so reduces the balance."

    Design: Corner/entities/corner_permittee_aggregates_initialised_to_zero
    """
    created = create_permittee(name="Zero Aggregate Ranch", contact_email="zero@example.com")

    read = get_permittee(created["id"])
    assert read["outstanding_balance_cents"] == 0
    assert read["billed_trespass_incident_count"] == 0
    assert read["permittee_status"] == "IN_GOOD_STANDING"
    assert read["name"] == "Zero Aggregate Ranch"
    assert read["contact_email"] == "zero@example.com"
    assert_common_fields(read)


def test_the_code_pattern_the_season_format_and_the_livestock_enum_are_all_shape_failures():
    """Three different type constraints answer with the same code: a three-letter admin unit prefix,
    a month of 13 in an MM-DD season and a livestock kind outside the three declared members each
    return HTTP 400 ERR_VALIDATION, and none of the three writes a row.

    PRD 3.1: "An `AuthorizedOfficer` registers one by supplying its `name` (between 1 and 120
    characters, and not blank), the administering field office's `admin_unit_code` (two uppercase
    letters, a hyphen, then three digits, as in `NV-042`), the `acres` of public land inside the
    boundary (at least 1), and the `total_permitted_aums` the inventory carries before any
    adjustment (also at least 1)."
    PRD 3.1: "The season of use is recurring rather than dated: `season_start` and `season_end` are
    month-and-day strings with no year, and `season_end` must fall strictly after `season_start`
    inside the same calendar year, so a season that wraps around New Year's Day cannot be
    expressed."
    PRD 3.3: "An application is filed by an `AuthorizedOfficer` naming the `allotment_id` the
    preference attaches to, the `permittee_id` who will hold it, the `base_property_id` that
    qualifies it, the `requested_aums` of preference sought (at least 1), the `term_start_date` and
    `term_end_date` bounding the term, and the `livestock_kind`, which is `CATTLE`, `SHEEP` or
    `HORSES`."
    PRD 2.6: "This check applies to every write operation."

    Design: Corner/entities/corner_allotment_type_constraints_on_code_and_season
    """
    allotment = _allotment(name="Constraint Probe", admin_unit_code="QA-113", acres=7000,
                           total_permitted_aums=250, season_start="01-01", season_end="12-31",
                           required_pasture_rotation_count=1)
    permittee = create_permittee(name="Constraint Ranch", contact_email="constraint@example.com")
    base_property = create_base_property(permittee["id"], base_property_type="LAND",
                                         legal_description="T36N R57E Sec 15 NE",
                                         carrying_capacity_aums=150,
                                         controlled_since_date="2018-01-01")

    validate_error(
        _create_allotment({"name": "Bad Code Allotment", "admin_unit_code": "BLM-NV-047",
                           "acres": 7000, "total_permitted_aums": 250,
                           "season_start": "01-01", "season_end": "12-31"}),
        ApiErrorId.ERR_VALIDATION, 400)
    validate_error(
        _create_allotment({"name": "Bad Season Allotment", "admin_unit_code": "QA-114",
                           "acres": 7000, "total_permitted_aums": 250,
                           "season_start": "13-01", "season_end": "12-31"}),
        ApiErrorId.ERR_VALIDATION, 400)
    validate_error(
        api_client.create_permit(
            f.permit_payload(allotment["id"], permittee["id"], base_property["id"],
                             requested_aums=150, term_start_date="2026-01-01",
                             term_end_date="2030-12-31", livestock_kind="GOATS"),
            make_officer_headers()),
        ApiErrorId.ERR_VALIDATION, 400)

    codes = _all_allotment_codes()
    assert "BLM-NV-047" not in codes
    assert "QA-114" not in codes
    assert "QA-113" in codes

    _items, meta = validate_paginated(api_client.list_permits(
        make_officer_headers(), {"permittee_id": permittee["id"], "limit": 100}))
    assert meta["total_count"] == 0, "the rejected application never became a permit"


def test_a_pasture_create_under_an_unknown_allotment_resolves_the_parent_first():
    """The body is impeccable, but the path parent does not exist, so the nested create answers with
    HTTP 404 ERR_ALLOTMENT_NOT_FOUND rather than a validation error — and the real allotment beside
    it gains no orphan pasture.

    PRD 2.6: "Nested paths are resolved strictly left to right, so the outermost missing identifier
    wins: a request naming an allotment that does not exist and, beneath it, a pasture that also
    does not exist, reports the allotment failure."
    PRD 2.6: "**Path-parameter existence** — HTTP 404 with the entity-specific code, resolved left
    to right as described at the top of this subsection. Applies to every operation that carries a
    path parameter."
    PRD 3.1: "A pasture may be flagged `rest_required`, which defaults to false; a rested pasture
    may not be scheduled in any operating instruction at all, and the `allotment_id` the pasture
    belongs to is taken from the path rather than the body."

    Design: Corner/entities/corner_pasture_create_under_unknown_allotment_returns_not_found
    """
    real = _allotment(name="Parent Probe", admin_unit_code="QA-115", acres=6000,
                      total_permitted_aums=210, season_start="01-01", season_end="12-31",
                      required_pasture_rotation_count=1)

    validate_error(
        api_client.create_pasture(
            NEVER_MINTED_ID,
            f.pasture_payload(name="Orphan Pasture", pasture_aum_capacity=100, sequence_order=1),
            make_officer_headers()),
        ApiErrorId.ERR_ALLOTMENT_NOT_FOUND, 404)

    items, meta = validate_paginated(api_client.list_allotment_pastures(
        real["id"], make_officer_headers(), {"limit": 100}))
    assert meta["total_count"] == 0, "no orphan pasture landed anywhere"
    assert items == []
