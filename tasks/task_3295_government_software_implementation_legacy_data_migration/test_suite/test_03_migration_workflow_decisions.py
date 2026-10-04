"""Migration, reconciliation, workflow-process, and decision tests."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_batch,
    create_contract_in_implementation, create_milestone, decision_payload,
    get_success_data, ingest_records, load_batch_through, make_headers,
    record_payload, reconcile_batch, reset_clock, submit_milestone,
    validate_error, validate_error_is_one_of, validate_paginated,
    validate_success, workflow_process_payload,
)


def test_reconciliation_forward_vs_chronological_sign_flip():
    """PRD §3.10: "The `CHRONOLOGICAL` variant replays the loaded records in
    ascending `legacy_primary_key` order with a running signed accumulator; any
    record whose inclusion would flip the running total's sign relative to the
    final total is flagged, and flagged records are excluded from
    `loaded_net_value_cents` in this variant." PRD §3.10: "When either variant
    is out of tolerance, the batch transitions to `RECONCILE_FAILED` rather
    than `RECONCILED`".

    Design: Difficulty/dual_variant_calc/reconciliation_forward_vs_chronological_sign_flip
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="ACCOUNTS_RECEIVABLE",
        source_system_label="LEGACY-AR",
        expected_record_count=3, expected_net_value_cents=500,
    )
    load_batch_through(batch["id"], [
        record_payload("K1", 400, field_payload={"acct": "a1"}),
        record_payload("K2", -700, field_payload={"acct": "a2"}),
        record_payload("K3", 800, field_payload={"acct": "a3"}),
    ])
    data = get_success_data(reconcile_batch(batch["id"]))
    assert data["status"] == "RECONCILE_FAILED"
    resp = api_client.list_reconciliation_reports(
        batch["id"], TEST_USERS["data_migration_lead"])
    rows, _meta = validate_paginated(resp)
    by_variant = {r["run_variant"]: r for r in rows}
    fwd = by_variant["FORWARD"]
    chrono = by_variant["CHRONOLOGICAL"]
    assert fwd["value_delta_cents"] == 0
    assert fwd["within_tolerance"] is True
    assert chrono["loaded_net_value_cents"] == 1200
    assert chrono["value_delta_cents"] == 700
    assert chrono["within_tolerance"] is False


def test_reconciliation_sign_flip_requires_both_variants_to_pass():
    """PRD §3.10: "Reconciliation of a loaded batch is computed twice over the
    same loaded records, and both variants must pass for the batch to
    reconcile." PRD §3.10: "Identical loaded data can therefore reconcile under
    `FORWARD` yet fail under `CHRONOLOGICAL`."

    Companion run: same K1/K2/K3 dataset confirms the FORWARD pass while the
    CHRONOLOGICAL failure alone forces RECONCILE_FAILED.

    Design: Difficulty/dual_variant_calc/reconciliation_forward_vs_chronological_sign_flip
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="ACCOUNTS_RECEIVABLE",
        source_system_label="LEGACY-AR",
        expected_record_count=3, expected_net_value_cents=500,
    )
    load_batch_through(batch["id"], [
        record_payload("K1", 400), record_payload("K2", -700),
        record_payload("K3", 800),
    ])
    resp = reconcile_batch(batch["id"])
    assert get_success_data(resp)["status"] == "RECONCILE_FAILED"
    rows, _meta = validate_paginated(api_client.list_reconciliation_reports(
        batch["id"], TEST_USERS["data_migration_lead"]))
    by_variant = {r["run_variant"]: r for r in rows}
    assert by_variant["FORWARD"]["within_tolerance"] is True
    assert by_variant["CHRONOLOGICAL"]["within_tolerance"] is False
    assert by_variant["CHRONOLOGICAL"]["loaded_net_value_cents"] == 1200


def test_reconciliation_nested_tolerance_rounding_order():
    """PRD §3.10: "A variant is `within_tolerance` only when the count delta is
    exactly zero and the absolute value of the value delta does not exceed the
    tolerance for the batch's domain: zero cents for `PROPERTY_TAX`,
    `COURT_CASES`, and `PAYROLL`; one hundred cents for `ACCOUNTS_RECEIVABLE`;
    and fifty cents for `LICENSES`."

    Design: Difficulty/combinatorial_formula/reconciliation_nested_tolerance_rounding_order
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="LICENSES", source_system_label="L2",
        expected_record_count=2, expected_net_value_cents=1000,
    )
    load_batch_through(batch["id"], [
        record_payload("L1", 500), record_payload("L2", 550),
    ])
    data = get_success_data(reconcile_batch(batch["id"]))
    assert data["status"] == "RECONCILED"
    rows, _meta = validate_paginated(api_client.list_reconciliation_reports(
        batch["id"], TEST_USERS["data_migration_lead"]))
    by_variant = {r["run_variant"]: r for r in rows}
    assert by_variant["FORWARD"]["value_delta_cents"] == 50
    assert by_variant["FORWARD"]["within_tolerance"] is True
    assert by_variant["CHRONOLOGICAL"]["within_tolerance"] is True


def test_reconciliation_tolerance_exclusive_above_boundary_fails():
    """PRD §3.10: "the absolute value of the value delta does not exceed the
    tolerance for the batch's domain". PRD §3.10: "When either variant is out
    of tolerance, the batch transitions to `RECONCILE_FAILED` rather than
    `RECONCILED`".

    Boundary companion: LICENSES delta 51 (> 50 tolerance) must fail.

    Design: Difficulty/combinatorial_formula/reconciliation_nested_tolerance_rounding_order
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="LICENSES", source_system_label="L2",
        expected_record_count=2, expected_net_value_cents=1000,
    )
    load_batch_through(batch["id"], [
        record_payload("L1", 500), record_payload("L2", 551),
    ])
    data = get_success_data(reconcile_batch(batch["id"]))
    assert data["status"] == "RECONCILE_FAILED"
    rows, _meta = validate_paginated(api_client.list_reconciliation_reports(
        batch["id"], TEST_USERS["data_migration_lead"]))
    by_variant = {r["run_variant"]: r for r in rows}
    assert by_variant["FORWARD"]["value_delta_cents"] == 51
    assert by_variant["FORWARD"]["within_tolerance"] is False


def test_migration_batch_accept_from_loaded_is_invalid():
    """PRD §3.5: "Final acceptance of a batch (`RECONCILED → ACCEPTED`) is
    performed by an `AgencyProjectManager` under segregation of duties". PRD
    §3.2: "An attempt to transition from a state other than the declared
    from-state is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/migration_batch_accept_from_loaded_is_invalid
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="PROPERTY_TAX", source_system_label="L1",
        expected_record_count=1, expected_net_value_cents=100,
    )
    load_batch_through(batch["id"], [record_payload("R1", 100)])
    resp = api_client.accept_batch(batch["id"], TEST_USERS["agency_pm"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api_client.get_migration_batch(
        batch["id"], TEST_USERS["data_migration_lead"]))
    assert current["status"] == "LOADED"


def test_unresolved_records_vs_duplicate_key_priority():
    """PRD §3.5: "each element carries a `legacy_primary_key` (the original
    system key, unique within the batch — a duplicate is rejected with
    `ERR_DUPLICATE_KEY`, HTTP 409 — and the anchor of historical fidelity)".

    Design: Difficulty/priority_pair_validation_conflict/unresolved_records_vs_duplicate_key_priority
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="PAYROLL", source_system_label="LP",
        expected_record_count=2, expected_net_value_cents=300,
    )
    resp = api_client.ingest_records(
        batch["id"],
        {"records": [record_payload("DUP", 100), record_payload("DUP", 200)]},
        TEST_USERS["data_migration_lead"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


def test_load_with_unresolved_records_rejected():
    """PRD §3.5: "Loading (`CLEANSED → LOADED`) is refused while any record has
    a non-null `issue_code` with a null `resolution` — the rejection is
    `ERR_UNRESOLVED_RECORDS` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/unresolved_records_vs_duplicate_key_priority
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="PAYROLL", source_system_label="LP",
        expected_record_count=1, expected_net_value_cents=100,
    )
    ingest_records(batch["id"], [record_payload("P1", 100)])
    get_success_data(api_client.extract_batch(batch["id"], TEST_USERS["data_migration_lead"]))
    get_success_data(api_client.cleanse_batch(
        batch["id"],
        {"resolutions": {"P1": {"issue_code": "ORPHAN_REFERENCE"}}},
        TEST_USERS["data_migration_lead"],
    ))
    resp = api_client.load_batch(batch["id"], TEST_USERS["data_migration_lead"])
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_RECORDS)


def test_workflow_rework_loop_increments_map_revision():
    """PRD §3.4: "the cyclic loop `MAPPED → IN_REVIEW → REWORK → MAPPED`
    increments `map_revision` on each return to `MAPPED`." PRD §3.4: "the
    process is born in `DRAFT` with `map_revision` 1."

    Design: Corner/state_machines/workflow_rework_loop_increments_map_revision
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    wp = get_success_data(api_client.create_workflow_process(
        ctx["contract"]["id"], workflow_process_payload(name="P1"),
        TEST_USERS["business_analyst"]))
    assert wp["map_revision"] == 1
    # each loop iteration must first return the process to MAPPED: the first
    # via map (DRAFT → MAPPED), later iterations via remap (REWORK → MAPPED)
    mapped = False
    for note in ("fix", "fix2"):
        if mapped:
            get_success_data(api_client.remap_process(wp["id"], TEST_USERS["business_analyst"]))
        else:
            get_success_data(api_client.map_process(wp["id"], TEST_USERS["business_analyst"]))
            mapped = True
        get_success_data(api_client.submit_process_review(wp["id"], TEST_USERS["business_analyst"]))
        get_success_data(api_client.send_process_rework(
            wp["id"], {"rework_note": note}, TEST_USERS["agency_pm"]))
    final = get_success_data(api_client.remap_process(wp["id"], TEST_USERS["business_analyst"]))
    assert final["map_revision"] == 3


def test_decision_on_unmapped_process_rejected():
    """PRD §3.4: "The referenced workflow process must be in `MAPPED` or
    `APPROVED` status, else creation is rejected with `ERR_PROCESS_NOT_MAPPED`
    (HTTP 422)".

    Design: Corner/validations/decision_on_unmapped_process_rejected
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    wp = get_success_data(api_client.create_workflow_process(
        ctx["contract"]["id"], workflow_process_payload(name="P1"),
        TEST_USERS["business_analyst"]))
    resp = api_client.create_decision(
        wp["id"],
        {"decision_key": "GL-DELIM", "chosen_value": "-", "rationale": "r"},
        TEST_USERS["business_analyst"],
    )
    validate_error(resp, ApiErrorId.ERR_PROCESS_NOT_MAPPED)


def test_decision_supersede_cascade_on_ratify():
    """PRD §2.11: "Ratifying a configuration decision that names a
    `supersedes_decision_id` moves the referenced decision to `SUPERSEDED`."

    Design: Corner/cross_cutting_layers/decision_supersede_cascade_on_ratify
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    wp = get_success_data(api_client.create_workflow_process(
        ctx["contract"]["id"], workflow_process_payload(name="P1"),
        TEST_USERS["business_analyst"]))
    get_success_data(api_client.map_process(wp["id"], TEST_USERS["business_analyst"]))
    d1 = get_success_data(api_client.create_decision(
        wp["id"], decision_payload(decision_key="GL-DELIM", chosen_value="-"),
        TEST_USERS["business_analyst"]))
    get_success_data(api_client.ratify_decision(d1["id"], TEST_USERS["agency_pm"]))
    d2 = get_success_data(api_client.create_decision(
        wp["id"],
        decision_payload(decision_key="GL-DELIM2", chosen_value="|",
                         rationale="r2", supersedes_decision_id=d1["id"]),
        TEST_USERS["business_analyst"]))
    ratified = get_success_data(api_client.ratify_decision(
        d2["id"], TEST_USERS["agency_pm"]))
    assert ratified["status"] == "RATIFIED"
    superseded = get_success_data(api_client.get_decision(
        d1["id"], TEST_USERS["agency_pm"]))
    assert superseded["status"] == "SUPERSEDED"


def test_segregation_of_duties_batch_self_accept():
    """PRD §3.5: "Final acceptance of a batch (`RECONCILED → ACCEPTED`) is
    performed by an `AgencyProjectManager` under segregation of duties: the
    accepting `X-User-ID` must differ from the recorded last reconciler, else
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/segregation_of_duties_batch_self_accept
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="PROPERTY_TAX", source_system_label="L1",
        expected_record_count=1, expected_net_value_cents=100,
    )
    load_batch_through(batch["id"], [record_payload("R1", 100)])
    reconciled = get_success_data(reconcile_batch(batch["id"], user_id="shared-user-1"))
    assert reconciled["status"] == "RECONCILED"
    resp = api_client.accept_batch(
        batch["id"], make_headers("shared-user-1", "AgencyProjectManager"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_data_migration_lead_cannot_accept_batch():
    """PRD §4: the batch accept endpoint `POST
    /programs/migration-batches/{id}/accept` lists only `AgencyProjectManager`
    as authorized. PRD §2.1: "A request whose role is not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/data_migration_lead_cannot_accept_batch
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    batch = create_batch(
        ctx["contract"]["id"], domain="PROPERTY_TAX", source_system_label="L1",
        expected_record_count=1, expected_net_value_cents=100,
    )
    load_batch_through(batch["id"], [record_payload("R1", 100)])
    reconciled = get_success_data(reconcile_batch(batch["id"], user_id="dml-1"))
    assert reconciled["status"] == "RECONCILED"
    resp = api_client.accept_batch(
        batch["id"], make_headers("dml-2", "DataMigrationLead"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_contract_not_settled_blocks_close():
    """PRD §3.2: "every milestone of the contract must be in `PAID`, the
    contract's support transition must exist and be in `STEADY_STATE`, and the
    contract's maintenance agreement must be `ACTIVE`; closing with an unpaid
    milestone or a non-steady support state is rejected with
    `ERR_CONTRACT_NOT_SETTLED` (HTTP 422)."

    Design: Corner/errors/contract_not_settled_blocks_close
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    ms = create_milestone(phase1["id"], code="M1", amount=100)
    submit_milestone(ms["id"])
    get_success_data(api_client.accept_milestone(ms["id"], TEST_USERS["agency_pm"]))
    resp = api_client.close_contract(ctx["contract"]["id"], TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_SETTLED)


def test_implementation_manager_cannot_award_contract():
    """PRD §4: the award endpoint `POST /programs/contracts/{id}/award` lists
    only `ProcurementOfficer` as authorized. PRD §2.1: "A request whose role is
    not permitted for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/implementation_manager_cannot_award_contract
    """
    from test_helpers import (create_agency, create_draft_contract,
                              walk_contract_to_award_pending)
    reset_clock()
    agency = create_agency()
    contract = create_draft_contract(agency["id"])
    walk_contract_to_award_pending(contract["id"])
    current = get_success_data(api_client.get_contract(
        contract["id"], TEST_USERS["procurement_officer"]))
    resp = api_client.award_contract(
        contract["id"], {"expected_contract_version": current["version"]},
        TEST_USERS["implementation_manager"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_occ_stale_contract_version_rejected():
    """PRD §2.7: "Awarding a contract requires the request to carry
    `expected_contract_version`, the version of the `ProcurementContract` the
    client last observed; if another writer has advanced the contract's
    `version` since — for instance by recording a protest resolution — the
    award is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_stale_contract_version_rejected

    PRD §3.2 declares no transition out of AWARD_PENDING other than award
    itself, so a same-contract version bump cannot be driven from
    AWARD_PENDING through PRD-declared transitions. The stale observation is
    therefore produced by observing an earlier version: awarding with the
    version the contract held before the walk to AWARD_PENDING completed is
    stale under §2.7 (the request's version is not the current one).
    """
    from test_helpers import (create_agency, create_draft_contract,
                              walk_contract_to_award_pending)
    reset_clock()
    agency = create_agency()
    contract = create_draft_contract(agency["id"])
    walk_contract_to_award_pending(contract["id"])
    observed = get_success_data(api_client.get_contract(
        contract["id"], TEST_USERS["procurement_officer"]))["version"]
    # stale = the version observed before the final transition of the walk
    stale = observed - 1
    resp = api_client.award_contract(
        contract["id"], {"expected_contract_version": stale},
        TEST_USERS["procurement_officer"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api_client.get_contract(
        contract["id"], TEST_USERS["procurement_officer"]))
    assert current["status"] == "AWARD_PENDING"


def test_pagination_filter_interaction_on_milestones():
    """PRD §2.3: "All list endpoints accept the query parameters `limit` and
    `offset`." PRD §2.3: "Many list endpoints additionally accept
    resource-specific filter parameters — for example `status` ... — which
    narrow the returned collection without changing sort order".

    Design: Corner/cross_cutting_layers/pagination_filter_interaction_on_milestones
    """
    reset_clock()
    ctx = create_contract_in_implementation()
    phase1 = ctx["phases"][0]
    m1 = create_milestone(phase1["id"], code="M1", amount=100)
    create_milestone(phase1["id"], code="M2", amount=100)
    create_milestone(phase1["id"], code="M3", amount=100)
    submit_milestone(m1["id"])
    page1, meta1 = validate_paginated(api_client.list_phase_milestones(
        phase1["id"], TEST_USERS["implementation_manager"],
        params={"status": "PLANNED", "limit": 1, "offset": 0}))
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert len(page1) == 1
    assert page1[0]["status"] == "PLANNED"
    page2, meta2 = validate_paginated(api_client.list_phase_milestones(
        phase1["id"], TEST_USERS["implementation_manager"],
        params={"status": "PLANNED", "limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert page2[0]["id"] != page1[0]["id"]
