"""Product carbon footprint reports (PRD §3.6): dual-variant computation with
pinned per-batch rounding, input-set filtering, half-open period semantics,
the verification fail/revise loop, empty-input rejection, nulls before submit,
and the collection-scoped optimistic concurrency check (PRD §2.7).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_to_batch,
    api_client,
    assign_report,
    create_batch,
    create_collection,
    create_installed_site,
    create_pcf_report_payload,
    create_qc_passed_lot,
    create_released_batch,
    create_report,
    create_verification_payload,
    fail_report,
    get_collection_version,
    lay_zone,
    make_manager_headers,
    make_verifier_headers,
    release_batch,
    revise_report,
    set_clock,
    setup_collection_with_batch,
    setup_credited_takeback,
    submit_report,
    validate_error,
    validate_success,
    DEFAULT_MANAGER_ID,
    DEFAULT_VERIFIER_ID,
)

MANAGER = make_manager_headers(DEFAULT_MANAGER_ID)

SECOND_MIX_300 = [
    (600, 0.40, "POST_CONSUMER_TILE", "NETCO"),
    (600, 2.10, "VIRGIN", "POLYCO"),
]


def _collection_with_two_batches_and_credit():
    """Collection CIR (CRADLE_TO_GRAVE, claim_intent NONE) with released
    batches DL-100 (100 m2, stored embodied 6.400) and DL-101 (300 m2, stored
    embodied 5.800) plus one CREDITED take-back (160 kg -> 40.00 m2 recovered)
    credited 2026-09-12, inside the reporting window [09-01, 10-01)."""
    set_clock()
    col = create_collection(claim_intent="NONE")
    b1 = create_released_batch(col["id"])
    create_released_batch(
        col["id"],
        mix=SECOND_MIX_300,
        dye_lot_code="DL-101",
        production_date="2026-09-10T00:00:00Z",
        produced_m2=300,
        mfg_intensity_kgco2e_per_m2=0.8,
        delta_e=0.9,
    )
    site = create_installed_site()
    lay_zone(site, b1["batch"]["id"], zone_code="Z-0", area_m2=10)
    setup_credited_takeback(site, col["id"])
    return col


def test_pcf_operational_variant_stores_weighted_mean(api):
    """PRD §3.6: "each input batch contributes its stored 3-decimal
    `embodied_carbon_kg_per_m2` multiplied by its `produced_m2`, the products
    are summed, the sum is divided by the total `produced_m2` of the input set,
    and the quotient is rounded half up to 3 decimal places."
    PRD §3.6: "A successful submission moves the report to `SUBMITTED`, records
    `submitted_by` as the acting `X-User-ID`, and computes and stores **both**
    footprint variants from identical inputs."

    Design: Difficulty/dual_variant_calc/pcf_operational_vs_lifecycle_diverge
    """
    col = _collection_with_two_batches_and_credit()
    rep = create_report(col["id"], boundary="CRADLE_TO_GRAVE")
    rep = submit_report(rep)
    assert rep["status"] == "SUBMITTED"
    # (6.400*100 + 5.800*300)/400 = 5.950 at the stored 3dp batch values.
    assert rep["operational_kgco2e_per_m2"] == pytest.approx(5.950, abs=1e-9)
    assert rep["submitted_by"] == DEFAULT_MANAGER_ID


def test_pcf_lifecycle_variant_adds_transport_minus_recovery_credit(api):
    """PRD §3.6: "The lifecycle value is then the operational value plus the
    transport constant of 0.35 kilograms of CO2e per square meter, minus the
    rounded end-of-life credit, with the final result rounded half up to 3
    decimal places."
    PRD §3.6: "Both variants are always computed and stored regardless of which
    `boundary` the report declares; the boundary governs which variant
    downstream consumers select, not which are computed."

    Design: Difficulty/dual_variant_calc/pcf_operational_vs_lifecycle_diverge
    """
    col = _collection_with_two_batches_and_credit()
    rep = create_report(col["id"], boundary="CRADLE_TO_GRAVE")
    rep = submit_report(rep)
    # Recovery share = 40.00 m2 / 400 m2 = 0.1; end-of-life credit
    # round(2.10 * 0.1, 4) = 0.2100; lifecycle = 5.950 + 0.350 - 0.2100.
    assert rep["lifecycle_kgco2e_per_m2"] == pytest.approx(6.090, abs=1e-9)
    assert rep["operational_kgco2e_per_m2"] == pytest.approx(5.950, abs=1e-9)
    # One submission over one identical input set stores both variants.
    assert rep["lifecycle_kgco2e_per_m2"] != rep["operational_kgco2e_per_m2"]


def _collection_with_precision_batches():
    """Collection RND (CRADLE_TO_GATE) with two 100 m2 batches whose mixes pin
    the nested rounding: DL-200 -> stored embodied 5.000, DL-201 -> 6.001."""
    set_clock()
    col = create_collection(
        name="Roundel", pattern_code="RND", lifecycle_boundary="CRADLE_TO_GATE",
        claim_intent="NONE",
    )
    b1 = create_released_batch(
        col["id"],
        mix=[(275.001, 0.50, "RECLAIMED_FISHING_NET", "NETCO"),
             (124.999, 2.10, "VIRGIN", "POLYCO")],
        dye_lot_code="DL-200",
        production_date="2026-09-06T00:00:00Z",
        produced_m2=100,
        mfg_intensity_kgco2e_per_m2=1.0,
        delta_e=0.2,
    )
    b2 = create_released_batch(
        col["id"],
        mix=[(212.438, 0.50, "RECLAIMED_FISHING_NET", "NETCO"),
             (187.562, 2.10, "VIRGIN", "POLYCO")],
        dye_lot_code="DL-201",
        production_date="2026-09-07T00:00:00Z",
        produced_m2=100,
        mfg_intensity_kgco2e_per_m2=1.0,
        delta_e=0.3,
    )
    return col, b1["batch"], b2["batch"]


def test_batch_embodied_values_round_component_at_4dp_first(api, admin_headers):
    """PRD §3.2: "first the feedstock component — each mix entry's
    `quantity_kg` multiplied by its lot's `carbon_factor_kgco2e_per_kg`, all
    summed, divided by the batch's `produced_m2`, and rounded half up to 4
    decimal places; then that rounded component is added to the batch's
    `mfg_intensity_kgco2e_per_m2` and the sum is rounded half up to 3 decimal
    places for storage."

    Design: Difficulty/combinatorial_formula/pcf_per_batch_rounding_order_pinned
    """
    _col, b1, b2 = _collection_with_precision_batches()
    d1 = validate_success(api.get_batch(b1["id"], admin_headers))
    d2 = validate_success(api.get_batch(b2["id"], admin_headers))
    # DL-200: (275.001*0.5 + 124.999*2.1)/100 = 3.999984 -> 4.0000 (4dp)
    #         -> 4.0000 + 1.0 = 5.000 stored.
    assert d1["embodied_carbon_kg_per_m2"] == pytest.approx(5.000, abs=1e-9)
    # DL-201: (212.438*0.5 + 187.562*2.1)/100 = 5.000992 -> 5.0010 (4dp)
    #         -> 5.0010 + 1.0 = 6.001 stored.
    assert d2["embodied_carbon_kg_per_m2"] == pytest.approx(6.001, abs=1e-9)


def test_pcf_weighted_mean_uses_stored_3dp_batch_values(api):
    """PRD §3.6: "Using each batch's stored 3-decimal value in this weighted
    sum is pinned; recomputing per-batch embodied carbon at full precision
    before weighting is the rejected variant and changes last digits."

    Design: Difficulty/combinatorial_formula/pcf_per_batch_rounding_order_pinned
    """
    col, _b1, _b2 = _collection_with_precision_batches()
    rep = create_report(col["id"], boundary="CRADLE_TO_GATE")
    rep = submit_report(rep)
    # Pinned: (5.000*100 + 6.001*100)/200 = 5.5005 -> 5.501 (3dp half-up).
    # The rejected full-precision order would produce 5.500.
    assert rep["operational_kgco2e_per_m2"] == pytest.approx(5.501, abs=1e-9)
    # No credited take-backs: 5.501 + 0.350 - 0.0000 = 5.851.
    assert rep["lifecycle_kgco2e_per_m2"] == pytest.approx(5.851, abs=1e-9)


def _reports_chain_through_submitted_rep_a():
    """Collection CIR with released DL-300 (50 m2, produced 2026-10-20,
    embodied 6.000). REP-0 [09-01, 10-01) DRAFT; REP-4 [09-15, 10-15) created
    (supersedes the overlapping DRAFT); REP-A [10-15, 11-15) created and
    submitted (input set: DL-300 only)."""
    set_clock()
    col = create_collection(claim_intent="NONE")
    create_released_batch(
        col["id"],
        mix=[(100, 0.40, "POST_CONSUMER_TILE", "NETCO"),
             (100, 2.10, "VIRGIN", "POLYCO")],
        dye_lot_code="DL-300",
        production_date="2026-10-20T00:00:00Z",
        produced_m2=50,
        mfg_intensity_kgco2e_per_m2=1.0,
        delta_e=0.7,
    )
    rep0 = create_report(col["id"], boundary="CRADLE_TO_GRAVE")
    rep4 = create_report(
        col["id"],
        period_start="2026-09-15T00:00:00Z",
        period_end="2026-10-15T00:00:00Z",
        boundary="CRADLE_TO_GRAVE",
    )
    rep_a = create_report(
        col["id"],
        period_start="2026-10-15T00:00:00Z",
        period_end="2026-11-15T00:00:00Z",
        boundary="CRADLE_TO_GRAVE",
    )
    rep_a = submit_report(rep_a)
    return col, rep0, rep4, rep_a


def test_draft_overlap_supersedes_and_half_open_adjacency_does_not(api, admin_headers):
    """PRD §3.6: "Overlapping reports in other states are handled by
    supersession instead: any same-collection `DRAFT` whose period overlaps the
    new report's is moved to `SUPERSEDED` as part of the create"
    PRD §2.5: "two periods whose endpoints merely touch — one period's
    `period_end` equal to the other's `period_start` — do not overlap."

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_overlap_semantics
    """
    col, rep0, rep4, rep_a = _reports_chain_through_submitted_rep_a()
    # REP-4 [09-15, 10-15) overlapped the DRAFT REP-0 [09-01, 10-01).
    assert validate_success(api.get_pcf_report(rep0["id"], admin_headers))[
        "status"
    ] == "SUPERSEDED"
    # REP-A starts exactly at REP-4's end: adjacency is not overlap, so REP-4
    # was created and survives unsubmitted.
    assert validate_success(api.get_pcf_report(rep4["id"], admin_headers))[
        "status"
    ] == "DRAFT"
    # REP-A's input set is only DL-300 (produced 2026-10-20).
    assert rep_a["status"] == "SUBMITTED"
    assert rep_a["operational_kgco2e_per_m2"] == pytest.approx(6.000, abs=1e-9)


def test_overlap_with_submitted_report_rejected(api, manager_headers):
    """PRD §3.6: "The period may not overlap — under the half-open rule of
    §2.5, where touching endpoints do not overlap — any report of the same
    collection sitting in `SUBMITTED`, `IN_VERIFICATION`, or `VERIFIED`, the
    in-verification pipeline; such an overlap is rejected with
    `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_overlap_semantics
    """
    col, _rep0, _rep4, _rep_a = _reports_chain_through_submitted_rep_a()
    # [11-01, 12-01) overlaps SUBMITTED REP-A [10-15, 11-15) on [11-01, 11-15).
    payload = create_pcf_report_payload(
        col["id"],
        get_collection_version(col["id"]),
        period_start="2026-11-01T00:00:00Z",
        period_end="2026-12-01T00:00:00Z",
        boundary="CRADLE_TO_GRAVE",
    )
    resp = api.create_pcf_report(payload, manager_headers)
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)


def test_report_computed_variants_stay_null_until_submit(api):
    """PRD §3.6: "The new report starts in `DRAFT`, and its creation increments
    the collection's `version` by 1."
    PRD §3.6: "A successful submission moves the report to `SUBMITTED`, records
    `submitted_by` as the acting `X-User-ID`, and computes and stores **both**
    footprint variants from identical inputs." — computation is a submission
    act, so a fresh report carries neither variant values nor verification
    metadata.

    Design: Corner/entities/report_computed_variants_stay_null_until_submit
    """
    set_clock()
    col = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    rep = create_report(col["id"])
    assert rep["status"] == "DRAFT"
    assert rep["operational_kgco2e_per_m2"] is None
    assert rep["lifecycle_kgco2e_per_m2"] is None
    assert rep["submitted_by"] is None
    assert rep["verifier_org"] is None
    assert rep["verified_by"] is None


def test_report_fail_revise_resubmit_cycle(api):
    """PRD §3.6: "Failing requires a `findings_count` of at least 1 — otherwise
    `ERR_INVALID_REQUEST` — and moves the report to `REJECTED`. Rejection is
    not the end: a `SustainabilityManager` may revise a `REJECTED` report back
    to `DRAFT`, which clears `submitted_by`, `verifier_org`, `verified_by`, and
    both computed variant values to null, readying the report for a corrected
    resubmission."

    Design: Corner/state_machines/report_fail_revise_resubmit_cycle
    """
    set_clock()
    built = setup_collection_with_batch()
    rep = create_report(built["collection"]["id"])
    rep = submit_report(rep)
    rep = assign_report(rep)
    rep = fail_report(rep, findings_count=1)
    assert rep["status"] == "REJECTED"
    rep = revise_report(rep)
    assert rep["status"] == "DRAFT"
    assert rep["submitted_by"] is None
    assert rep["verifier_org"] is None
    assert rep["verified_by"] is None
    assert rep["operational_kgco2e_per_m2"] is None
    assert rep["lifecycle_kgco2e_per_m2"] is None
    rep = submit_report(rep)
    assert rep["status"] == "SUBMITTED"
    # Canonical batch embodied 6.400 is the whole input set.
    assert rep["operational_kgco2e_per_m2"] == pytest.approx(6.400, abs=1e-9)


def test_verification_fail_requires_at_least_one_finding(api, admin_headers):
    """PRD §3.6: "Failing requires a `findings_count` of at least 1 — otherwise
    `ERR_INVALID_REQUEST`"

    Design: Corner/state_machines/report_fail_revise_resubmit_cycle
    """
    set_clock()
    built = setup_collection_with_batch()
    rep = create_report(built["collection"]["id"])
    rep = submit_report(rep)
    rep = assign_report(rep)
    resp = api.verify_pcf_report(
        rep["id"],
        create_verification_payload("FAIL", findings_count=0),
        make_verifier_headers(DEFAULT_VERIFIER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data = validate_success(api.get_pcf_report(rep["id"], admin_headers))
    assert data["status"] == "IN_VERIFICATION"


def test_pcf_input_set_filters_by_status_and_half_open_window(api):
    """PRD §3.6: "The input set is every batch of the report's collection whose
    `production_date` falls inside the half-open period and whose status is
    `RELEASED` or `EXHAUSTED`."

    Design: Corner/calculations/pcf_input_set_filters_by_status_and_half_open_window
    """
    set_clock()
    col = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    lot_a = create_qc_passed_lot(quantity_kg=100, carbon_factor_kgco2e_per_kg=0.50)
    lot_b = create_qc_passed_lot(
        supplier_name="POLYCO", source_type="VIRGIN",
        quantity_kg=200, carbon_factor_kgco2e_per_kg=2.10,
    )
    lot_c = create_qc_passed_lot(
        supplier_name="NETCO", source_type="POST_CONSUMER_TILE",
        quantity_kg=100, carbon_factor_kgco2e_per_kg=0.40,
    )
    # In-window but never released: excluded by the status filter.
    create_batch(
        col["id"], dye_lot_code="DL-Q", production_date="2026-09-05T00:00:00Z",
        produced_m2=50, mfg_intensity_kgco2e_per_m2=1.0, delta_e=0.1,
    )
    # Released but produced before the window: excluded by the half-open rule.
    b_out = create_batch(
        col["id"], dye_lot_code="DL-OUT", production_date="2026-08-20T00:00:00Z",
        produced_m2=50, mfg_intensity_kgco2e_per_m2=1.0, delta_e=0.2,
    )
    allocate_to_batch(lot_a["id"], b_out["id"], 100)
    allocate_to_batch(lot_b["id"], b_out["id"], 100)
    release_batch(b_out["id"])  # embodied 6.200
    # In-window and released: the only member of the input set.
    b_in = create_batch(
        col["id"], dye_lot_code="DL-IN", production_date="2026-09-20T00:00:00Z",
        produced_m2=50, mfg_intensity_kgco2e_per_m2=1.0, delta_e=0.3,
    )
    allocate_to_batch(lot_c["id"], b_in["id"], 100)
    allocate_to_batch(lot_b["id"], b_in["id"], 100)
    release_batch(b_in["id"])  # embodied 6.000

    rep = create_report(col["id"], boundary="CRADLE_TO_GATE")
    rep = submit_report(rep)
    assert rep["operational_kgco2e_per_m2"] == pytest.approx(6.000, abs=1e-9)
    assert rep["lifecycle_kgco2e_per_m2"] == pytest.approx(6.350, abs=1e-9)


def test_pcf_submit_with_empty_input_set_returns_422(api, admin_headers):
    """PRD §3.6: "requires a non-empty input set — a submission whose period
    and status filters select no batches at all is rejected with
    `ERR_EMPTY_REPORT_INPUT` (HTTP 422)."

    Design: Corner/calculations/pcf_submit_with_empty_input_set_returns_422
    """
    set_clock()
    col = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    rep = create_report(col["id"])
    resp = api.submit_pcf_report(rep["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_REPORT_INPUT)
    data = validate_success(api.get_pcf_report(rep["id"], admin_headers))
    assert data["status"] == "DRAFT"


def test_occ_report_create_stale_version_returns_412(api, admin_headers):
    """PRD §2.7: "Opening a footprint report and issuing a specification
    package each require the request body to carry
    `expected_collection_version`, holding the version of the target product
    collection the client last observed."
    PRD §2.7: "If the value presented does not match the parent's current
    `version` — because another writer's create has advanced that version
    since the client last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), protecting the client from, for example,
    superseding a package it has never seen or drafting a report over a draft
    it did not know had been replaced."

    Design: Corner/cross_cutting_layers/occ_report_create_stale_version_returns_412
    """
    set_clock()
    col = create_collection(
        name="Gatehouse", pattern_code="GAT",
        lifecycle_boundary="CRADLE_TO_GATE", claim_intent="NONE",
    )
    captured = col["version"]  # 1
    rep_a = create_report(col["id"])  # bumps the collection to version 2
    # Replaying the captured version is stale.
    payload = create_pcf_report_payload(
        col["id"],
        captured,
        period_start="2026-10-01T00:00:00Z",
        period_end="2026-11-01T00:00:00Z",
        boundary="CRADLE_TO_GATE",
    )
    validate_error(
        api.create_pcf_report(payload, MANAGER), ApiErrorId.ERR_STALE_VERSION
    )
    # Re-reading the version and resubmitting the identical payload succeeds.
    rep_b = create_report(
        col["id"],
        period_start="2026-10-01T00:00:00Z",
        period_end="2026-11-01T00:00:00Z",
        boundary="CRADLE_TO_GATE",
    )
    assert rep_b["status"] == "DRAFT"
    # Half-open adjacency: the two drafts coexist, neither superseded.
    assert validate_success(api.get_pcf_report(rep_a["id"], admin_headers))[
        "status"
    ] == "DRAFT"
    assert validate_success(api.get_pcf_report(rep_b["id"], admin_headers))[
        "status"
    ] == "DRAFT"
