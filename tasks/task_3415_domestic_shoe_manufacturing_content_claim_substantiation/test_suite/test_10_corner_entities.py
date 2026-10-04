"""Corner coverage: entity creation defaults, initial states, not-found,
pagination, required fields, and creation-time validation."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, assert_allocation, assert_claim,
    assert_factory, assert_lot, assert_model, assert_run, bom_line,
    create_model_payload, create_run_payload, enroll, get_allocation,
    is_valid_uuid, make_claim, make_component, make_contract,
    make_factory, make_model, make_worker, set_clock,
    standard_kit, validate_error, validate_paginated, validate_success,
)
from test_helpers import TEST_USERS, api_client

api = api_client
ADMIN = TEST_USERS["admin"]
SOURCING = TEST_USERS["sourcing"]
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]
TRAINING = TEST_USERS["training"]


def test_factory_create_applies_defaults_and_default_logical_clock():
    """PRD §3.1: "a `government_cleared` flag indicating whether the plant may
    produce government-contract footwear (defaulting to false when omitted)"
    PRD §3.1: "A new factory starts `ACTIVE` with `version` 1."
    PRD §3.2: "when no runs are in production the requirement is zero and that
    operation's coverage is defined as 100."
    PRD §2.5: "`id` (string): a unique, server-minted UUID with no type
    prefix."

    Design: Corner/entities/factory_create_applies_defaults_and_default_logical_clock
    """
    resp = api.create_factory({
        "factory_name": "Lawrence MA Plant", "location_type": "DOMESTIC",
        "weekly_capacity_units": 1000, "line_count": 3,
        "labor_rate_cents_per_minute": 50, "overhead_cents_per_pair": 600,
    }, ADMIN)
    factory = validate_success(resp, 201)
    assert_factory(factory)
    assert factory["status"] == "ACTIVE" and factory["version"] == 1
    assert factory["government_cleared"] is False  # omitted -> default
    assert factory["skill_coverage_certified_pct"] == pytest.approx(100.0)
    assert factory["skill_coverage_pipeline_pct"] == pytest.approx(100.0)
    assert is_valid_uuid(factory["id"])


def test_model_create_returns_bom_and_null_pricing():
    """PRD §3.3: "Every model carries its bill of materials in `bom_lines`,
    which must contain at least one line and is immutable after creation."
    PRD §3.3: "A new model starts `ACTIVE`, and its two read-only
    domestic-pricing fields, `domestic_unit_cost_cents` and
    `domestic_price_cents`, remain null until a certified content report lands
    on a domestic run of the model, as §3.6 describes."

    Design: Corner/entities/model_create_returns_bom_and_null_pricing
    """
    set_clock()
    make_factory()
    component = make_component()
    resp = api.create_model(create_model_payload(component["id"]), SOURCING)
    model = validate_success(resp, 201)
    assert_model(model)
    assert model["status"] == "ACTIVE" and model["version"] == 1
    assert len(model["bom_lines"]) == 1
    line = model["bom_lines"][0]
    assert line["quantity_per_pair"] == 1.0
    assert line["sourcing_requirement"] == "IMPORT_ALLOWED"
    assert line["planned_unit_cost_cents"] == 100
    assert line["planned_is_domestic"] is False
    assert model["domestic_unit_cost_cents"] is None
    assert model["domestic_price_cents"] is None


def test_lot_create_initializes_remaining_and_stamps_received_at():
    """PRD §3.3: "The server stamps each lot with `received_at` from the
    logical clock at creation, and that timestamp is the primary ordering key
    for the FIFO consumption rule."
    PRD §3.3: "A lot is initialized with `quantity_remaining` equal to
    `quantity_received` at receipt."
    PRD §2.4: "Before any client advances it, the logical clock stands at
    exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time on
    its own."

    Design: Corner/entities/lot_create_initializes_remaining_and_stamps_received_at
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    resp = api.create_lot({
        "component_id": kit["component"]["id"], "supplier_name": "Fall River Mills",
        "is_domestic": True, "quantity_received": 1000, "unit_cost_cents": 100,
    }, SOURCING)
    lot = validate_success(resp, 201)
    assert_lot(lot)
    assert lot["quantity_remaining"] == 1000 == lot["quantity_received"]
    assert lot["received_at"].startswith("2026-09-01T00:00:00")
    assert lot["version"] == 1


def test_run_create_starts_planned_with_empty_consumption():
    """PRD §3.5: "A new run starts `PLANNED`, with `actual_stitching_minutes`,
    `actual_lasting_minutes`, `actual_assembly_minutes`, and
    `certified_unit_cost_cents` all null until completion, and `consumed_lots`
    empty."
    PRD §3.4: "At creation the allocation is `OPEN` with
    `domestic_reserved_units` 0 and `import_reserved_units` equal to
    `total_reserved_units`, and while it remains `OPEN` no run may reserve
    materials against the week."

    Design: Corner/entities/run_create_starts_planned_with_empty_consumption
    """
    kit = standard_kit(with_run=False)
    resp = api.create_run(create_run_payload(kit["model"]["id"], kit["factory"]["id"]),
                          PLANNER)
    run = validate_success(resp, 201)
    assert_run(run)
    assert run["status"] == "PLANNED" and run["version"] == 1
    assert run["consumed_lots"] == []
    assert run["actual_stitching_minutes"] is None
    assert run["actual_lasting_minutes"] is None
    assert run["actual_assembly_minutes"] is None
    assert run["certified_unit_cost_cents"] is None
    allocation = get_allocation(kit["allocation"]["id"])
    assert allocation["status"] == "OPEN"
    assert allocation["domestic_reserved_units"] == 0
    assert allocation["import_reserved_units"] == 100


def test_claim_create_starts_draft():
    """PRD §3.8: "A new claim starts `DRAFT` with `report_id` null and both
    `substantiated_at` and `published_at` null."

    Design: Corner/entities/claim_create_starts_draft
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    resp = api.create_label_claim(
        {"model_id": kit["model"]["id"], "claim_type": "MADE_IN_USA"}, COMPLIANCE)
    claim = validate_success(resp, 201)
    assert_claim(claim)
    assert claim["status"] == "DRAFT" and claim["version"] == 1
    assert claim["report_id"] is None
    assert claim["substantiated_at"] is None
    assert claim["published_at"] is None


def test_allocation_create_starts_open_with_zero_domestic():
    """PRD §3.4: "At creation the allocation is `OPEN` with
    `domestic_reserved_units` 0 and `import_reserved_units` equal to
    `total_reserved_units`, and while it remains `OPEN` no run may reserve
    materials against the week."

    Design: Corner/entities/allocation_create_starts_open_with_zero_domestic
    """
    set_clock()
    factory = make_factory()
    resp = api.create_allocation(
        {"factory_id": factory["id"], "iso_week": "2026-W37",
         "total_reserved_units": 250}, ADMIN)
    allocation = validate_success(resp, 201)
    assert_allocation(allocation)
    assert allocation["status"] == "OPEN"
    assert allocation["domestic_reserved_units"] == 0
    assert allocation["import_reserved_units"] == 250
    assert allocation["version"] == 1


def test_get_factory_with_unknown_id_returns_not_found():
    """PRD §2.9: "The not-found family is resource-specific:
    `ERR_FACTORY_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DOC_NOT_FOUND`,
    `ERR_WORKER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, and
    `ERR_CERTIFICATION_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/get_factory_with_unknown_id_returns_not_found
    """
    resp = api.get_factory(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FACTORY_NOT_FOUND)


def test_models_list_paginates_with_envelope():
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; when omitted it defaults to 10, and it is bounded below by 1 and
    above by 100. The `offset` parameter sets the number of items to skip and
    defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the four pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/models_list_paginates_with_envelope
    """
    set_clock()
    make_factory()
    component = make_component()
    for style, policy, base, basis, sourcing, planned_dom in (
            ("P1", "DUAL_SOURCE", 5000, 2000, "IMPORT_ALLOWED", False),
            ("P2", "IMPORT_ONLY", 6000, 2500, "IMPORT_ALLOWED", False),
            ("P3", "DOMESTIC_ONLY", 7000, 3000, "DOMESTIC_REQUIRED", True)):
        make_model(component["id"], style_code=style, production_policy=policy,
                   base_price_cents=base, import_cost_basis_cents=basis,
                   bom_lines=[bom_line(component["id"],
                                       sourcing_requirement=sourcing,
                                       planned_is_domestic=planned_dom)])

    page1, meta1 = validate_paginated(api.list_models(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_models(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    page_default, meta_default = validate_paginated(api.list_models(ADMIN))
    assert len(page_default) == 3
    assert meta_default["limit"] == 10 and meta_default["offset"] == 0

    imports, _ = validate_paginated(
        api.list_models(ADMIN, params={"production_policy": "IMPORT_ONLY"}))
    assert [m["style_code"] for m in imports] == ["P2"]
    actives, _ = validate_paginated(api.list_models(ADMIN, params={"status": "ACTIVE"}))
    assert len(actives) == 3


def test_run_create_missing_planned_units_returns_invalid_request():
    """PRD §2.8 (family 5): "Required fields must be present, enum values must
    be valid, and numeric and date ranges must be honored: `planned_units` at
    least 1, `quantity_units` between 1 and 12 inclusive, `score` between 0 and
    100 inclusive, `units` at least 1, `target_level` between 1 and 3
    inclusive, `end_day` strictly after `start_day`, `valid_until` strictly
    after `valid_from`, and `fulfillment_end` strictly after
    `fulfillment_start`. Violations are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/run_create_missing_planned_units_returns_invalid_request
    """
    kit = standard_kit(with_run=False)
    payload = create_run_payload(kit["model"]["id"], kit["factory"]["id"])
    del payload["planned_units"]
    resp = api.create_run(payload, PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    runs, meta = validate_paginated(
        api.list_runs(PLANNER, params={"factory_id": kit["factory"]["id"]}))
    assert runs == [] and meta["total_count"] == 0


def test_evidence_create_with_two_links_is_rejected():
    """PRD §3.8: "Setting zero of the three, or more than one, is rejected with
    `ERR_DOC_LINK_AMBIGUOUS` (HTTP 400)."

    Design: Corner/entities/evidence_create_with_two_links_is_rejected
    """
    kit = standard_kit(with_allocation=False, with_run=False)
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")
    sm1 = {"X-User-ID": "sm-1", "X-User-Role": "SourcingManager"}

    two_links = api.create_evidence_document({
        "doc_type": "SUPPLIER_ORIGIN_CERT", "issuer": "Fall River Mills",
        "valid_from": "2026-08-01", "valid_until": "2027-08-31",
        "claim_id": claim["id"], "material_lot_id": kit["lot"]["id"],
    }, sm1)
    validate_error(two_links, ApiErrorId.ERR_DOC_LINK_AMBIGUOUS)

    zero_links = api.create_evidence_document({
        "doc_type": "COST_BREAKDOWN", "issuer": "Fall River Mills",
        "valid_from": "2026-08-01", "valid_until": "2027-08-31",
    }, sm1)
    validate_error(zero_links, ApiErrorId.ERR_DOC_LINK_AMBIGUOUS)

    docs, meta = validate_paginated(
        api.list_evidence_documents(COMPLIANCE, params={"claim_id": claim["id"]}))
    assert docs == [] and meta["total_count"] == 0


def test_run_create_domestic_only_model_on_overseas_factory_is_rejected():
    """PRD §3.5: "The model's `production_policy` sets a direction: a
    `DOMESTIC_ONLY` model may not be produced at an `OVERSEAS` factory
    (`ERR_POLICY_FORBIDS_IMPORT`, HTTP 422), and an `IMPORT_ONLY` model may not
    be produced at a `DOMESTIC` factory (`ERR_POLICY_FORBIDS_DOMESTIC`, HTTP
    422); a `DUAL_SOURCE` model accepts either."

    Design: Corner/entities/run_create_domestic_only_model_on_overseas_factory_is_rejected
    """
    set_clock()
    make_factory()
    f_os = make_factory(factory_name="Hanoi Partner Plant", location_type="OVERSEAS",
                        weekly_capacity_units=2000, line_count=2,
                        labor_rate_cents_per_minute=10, overhead_cents_per_pair=100)
    component = make_component()
    m_dom = make_model(component["id"], style_code="MDOM",
                       production_policy="DOMESTIC_ONLY",
                       bom_lines=[bom_line(component["id"],
                                           sourcing_requirement="DOMESTIC_REQUIRED",
                                           planned_is_domestic=True)])
    m_std = make_model(component["id"], style_code="MSTD")

    bad = api.create_run(create_run_payload(m_dom["id"], f_os["id"]), PLANNER)
    validate_error(bad, ApiErrorId.ERR_POLICY_FORBIDS_IMPORT)
    ok = api.create_run(create_run_payload(m_std["id"], f_os["id"]), PLANNER)
    run = validate_success(ok, 201)
    assert run["status"] == "PLANNED"


def test_government_run_on_uncleared_factory_is_rejected():
    """PRD §3.5: "And a `GOVERNMENT` run may be created only on a factory that
    is both `DOMESTIC` and `government_cleared` — otherwise
    `ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY` (HTTP 422)."

    Design: Corner/entities/government_run_on_uncleared_factory_is_rejected
    """
    set_clock()
    factory = make_factory()  # DOMESTIC, not government_cleared
    component = make_component()
    m_dom = make_model(component["id"], style_code="MDOM",
                       production_policy="DOMESTIC_ONLY",
                       bom_lines=[bom_line(component["id"],
                                           sourcing_requirement="DOMESTIC_REQUIRED",
                                           planned_is_domestic=True)])

    bad = api.create_run(create_run_payload(m_dom["id"], factory["id"],
                                            run_type="GOVERNMENT"), PLANNER)
    validate_error(bad, ApiErrorId.ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY)
    ok = api.create_run(create_run_payload(m_dom["id"], factory["id"],
                                           run_type="STOCK"), PLANNER)
    assert validate_success(ok, 201)["status"] == "PLANNED"


def test_unique_key_collisions_are_rejected():
    """PRD §3.3: "a public `style_code` that must be unique across all models
    (a duplicate is rejected with `ERR_STYLE_CODE_EXISTS`, HTTP 409)"
    PRD §3.4: "Only one allocation may exist per factory and week: a duplicate
    pair is rejected with `ERR_ALLOCATION_ALREADY_EXISTS` (HTTP 409)."
    PRD §3.8: "At most one non-`REVOKED` claim may exist per model and claim
    type — a duplicate is rejected with `ERR_CLAIM_ALREADY_EXISTS` (HTTP 409)."
    PRD §3.9: "a `contract_number` that must be unique across all contracts (a
    duplicate is rejected with `ERR_CONTRACT_NUMBER_EXISTS`, HTTP 409)"

    Design: Corner/entities/unique_key_collisions_are_rejected
    """
    kit = standard_kit(with_run=False)
    make_claim(kit["model"]["id"], "MADE_IN_USA")
    make_contract(kit["model"]["id"], kit["factory"]["id"], contract_number="G-200",
                  awarded_units=5, fulfillment_start="2026-12-01",
                  fulfillment_end="2026-12-31")

    dup_model = api.create_model(
        create_model_payload(kit["component"]["id"], style_code="MSTD"), SOURCING)
    validate_error(dup_model, ApiErrorId.ERR_STYLE_CODE_EXISTS)

    dup_alloc = api.create_allocation(
        {"factory_id": kit["factory"]["id"], "iso_week": "2026-W36",
         "total_reserved_units": 50}, ADMIN)
    validate_error(dup_alloc, ApiErrorId.ERR_ALLOCATION_ALREADY_EXISTS)

    dup_claim = api.create_label_claim(
        {"model_id": kit["model"]["id"], "claim_type": "MADE_IN_USA"}, COMPLIANCE)
    validate_error(dup_claim, ApiErrorId.ERR_CLAIM_ALREADY_EXISTS)

    # Uniqueness scopes on (model_id, claim_type): a different type is fine.
    other_claim = api.create_label_claim(
        {"model_id": kit["model"]["id"], "claim_type": "IMPORTED"}, COMPLIANCE)
    assert validate_success(other_claim, 201)["status"] == "DRAFT"

    dup_contract = api.create_gov_contract({
        "contract_number": "G-200", "model_id": kit["model"]["id"],
        "factory_id": kit["factory"]["id"], "awarded_units": 5,
        "fulfillment_start": "2027-01-01", "fulfillment_end": "2027-01-31",
    }, ADMIN)
    validate_error(dup_contract, ApiErrorId.ERR_CONTRACT_NUMBER_EXISTS)


def test_allocation_total_above_weekly_capacity_is_rejected():
    """PRD §3.4: "A `PlatformAdmin` opens a **CapacityAllocation** by naming
    the `factory_id`, the `iso_week` in `YYYY-Www` form, and a
    `total_reserved_units` budget that must be at least zero and no more than
    the factory's `weekly_capacity_units` (a larger total is rejected with
    `ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY`, HTTP 422)."

    Design: Corner/entities/allocation_total_above_weekly_capacity_is_rejected
    """
    set_clock()
    factory = make_factory()  # weekly_capacity_units 1000
    ok = api.create_allocation(
        {"factory_id": factory["id"], "iso_week": "2026-W38",
         "total_reserved_units": 1000}, ADMIN)
    assert validate_success(ok, 201)["total_reserved_units"] == 1000

    over = api.create_allocation(
        {"factory_id": factory["id"], "iso_week": "2026-W39",
         "total_reserved_units": 1001}, ADMIN)
    validate_error(over, ApiErrorId.ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY)


def test_enrollment_for_suspended_worker_is_rejected():
    """PRD §3.2: "A `TrainingCoordinator` enrolls an `ACTIVE` worker —
    enrolling a `SUSPENDED` worker is rejected with `ERR_WORKER_NOT_ACTIVE`
    (HTTP 409)"
    PRD §3.2: "A fresh enrollment starts `ENROLLED` with `attempt_count` 0 and
    `last_score` null."

    Design: Corner/entities/enrollment_for_suspended_worker_is_rejected
    """
    set_clock()
    factory = make_factory()
    worker = make_worker(factory["id"], "Ada Lovelace")
    validate_success(api.suspend_worker(worker["id"], TRAINING))

    blocked = api.create_enrollment(
        {"worker_id": worker["id"], "operation": "STITCHING", "target_level": 1},
        TRAINING)
    validate_error(blocked, ApiErrorId.ERR_WORKER_NOT_ACTIVE)

    validate_success(api.reinstate_worker(worker["id"], TRAINING))
    enrollment = enroll(worker["id"], "STITCHING", target_level=1)
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["attempt_count"] == 0
    assert enrollment["last_score"] is None
