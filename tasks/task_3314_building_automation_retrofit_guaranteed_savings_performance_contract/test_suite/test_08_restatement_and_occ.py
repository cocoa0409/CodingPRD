"""Baseline restatement cascade, adjustment chain, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    attested_report,
    create_adjustment_payload,
    create_and_submit_report,
    eng_headers,
    make_actor_ids,
    own_headers,
    performance_contract,
    reset_clock,
    validate_error,
    validate_success,
)


def test_baseline_restatement_cascades_to_reports_and_contract_ledger(api):
    """PRD §3.6: "every savings report of the contract currently in
    `SUBMITTED` or `ATTESTED` state has its `verified_savings_cents` and
    `shortfall_cents` recomputed against the restated baseline, while
    `RECONCILED` reports are not reopened and `DISPUTED` reports are not
    reopened; and the contract's `cumulative_verified_savings_cents` is
    re-derived over the `RECONCILED` reports only."
    PRD §3.6: "The baseline moves from `LOCKED` or `RESTATED` to `RESTATED`;
    its `version_tag` — a restatement counter that starts at 1 — increments
    by 1; its `annual_energy_kwh` absorbs the `kwh_delta`"

    Design: Difficulty/transitive_cascade/baseline_restatement_cascades_to_reports_and_contract_ledger
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, baseline, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id, facility_name="Flat Rate School"
    )
    cid, bid = contract["id"], baseline["id"]
    assert baseline["adjusted_annual_cost_cents"] == 1200000
    report = create_and_submit_report(cid, eng_id)
    assert report["verified_savings_cents"] == 240000
    assert report["shortfall_cents"] == 10000
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    assert baseline["status"] == "LOCKED"
    adjustment = validate_success(
        api.create_adjustment(cid, create_adjustment_payload(
            baseline_id=bid, supersedes_adjustment_id=None,
            reason="FACILITY_REDUCTION", kwh_delta=-20000),
                              eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.approve_adjustment(cid, adjustment["id"],
                               {"expected_baseline_version": baseline["version"]},
                               own_headers(owner_id))
    )
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    assert baseline["status"] == "RESTATED"
    assert baseline["version_tag"] == 2
    assert baseline["annual_energy_kwh"] == 80000
    assert baseline["adjusted_annual_cost_cents"] == 960000
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["status"] == "SUBMITTED"
    assert report["verified_savings_cents"] == 0
    assert report["shortfall_cents"] == 250000


def test_baseline_restatement_recomputes_adjusted_cost(api):
    """PRD §3.6: "The restated `adjusted_annual_cost_cents` is then
    recomputed with the same tiered procedure as at submission"
    PRD §2.9: "Approving a baseline adjustment restates the baseline,
    recomputes every in-flight savings report's verified savings and
    shortfall, and re-derives the contract's cumulative verified savings —
    all in one atomic step."

    Design: Difficulty/transitive_cascade/baseline_restatement_cascades_to_reports_and_contract_ledger
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, baseline, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id, facility_name="Flat Rate School"
    )
    cid, bid = contract["id"], baseline["id"]
    report = attested_report(cid, eng_id, owner_id)
    assert report["status"] == "ATTESTED"
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    adjustment = validate_success(
        api.create_adjustment(cid, create_adjustment_payload(
            baseline_id=bid, supersedes_adjustment_id=None,
            reason="FACILITY_REDUCTION", kwh_delta=-20000),
                              eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.approve_adjustment(cid, adjustment["id"],
                               {"expected_baseline_version": baseline["version"]},
                               own_headers(owner_id))
    )
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    assert baseline["adjusted_annual_cost_cents"] == 960000
    # ATTESTED (in-flight) reports are also recomputed.
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["verified_savings_cents"] == 0
    assert report["shortfall_cents"] == 250000
    assert report["status"] == "ATTESTED"


def test_stale_adjustment_chain_rejected(api):
    """PRD §3.6: "the `supersedes_adjustment_id` must be `null` or equal the
    latest approved adjustment on that baseline — a chain break is rejected
    with `ERR_STALE_ADJUSTMENT_CHAIN`"

    Design: Corner/validations/stale_adjustment_chain_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, baseline, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id
    )
    cid, bid = contract["id"], baseline["id"]
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    a1 = validate_success(
        api.create_adjustment(cid, create_adjustment_payload(
            baseline_id=bid, supersedes_adjustment_id=None,
            reason="FACILITY_EXPANSION", kwh_delta=10000),
                              eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.approve_adjustment(cid, a1["id"],
                               {"expected_baseline_version": baseline["version"]},
                               own_headers(owner_id))
    )
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    a2 = validate_success(
        api.create_adjustment(cid, create_adjustment_payload(
            baseline_id=bid, supersedes_adjustment_id=None,
            reason="RATE_CHANGE", kwh_delta=5000),
                              eng_headers(eng_id)),
        201,
    )
    response = api.approve_adjustment(
        cid, a2["id"], {"expected_baseline_version": baseline["version"]},
        own_headers(owner_id),
    )
    validate_error(response, ApiErrorId.ERR_STALE_ADJUSTMENT_CHAIN.value, 409)
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    assert baseline["annual_energy_kwh"] == 110000


def test_occ_reconcile_with_stale_contract_version_rejected(api):
    """PRD §2.7: "If the contract's current `version` does not match —
    because, for example, another report has been reconciled in the meantime,
    advancing `cumulative_verified_savings_cents` and
    `guarantee_shortfall_reserve_cents` — the reconcile is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "A successful reconcile moves the report to `RECONCILED` — a
    terminal state — and posts to the contract ledger atomically:
    `cumulative_verified_savings_cents` increases by the report's
    `verified_savings_cents`, `guarantee_shortfall_reserve_cents` increases by
    the report's `shortfall_cents`, and the contract's `version` increments by
    exactly 1."

    Design: Corner/endpoints/occ_reconcile_with_stale_contract_version_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, _p = performance_contract(eng_id, owner_id)
    cid = contract["id"]
    report = attested_report(cid, eng_id, owner_id)
    contract = validate_success(api.get_contract(cid, own_headers(owner_id)))
    response = api.reconcile_report(
        cid, report["id"],
        {"expected_contract_version": contract["version"] - 1},
        own_headers(owner_id),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    report = validate_success(api.get_report(cid, report["id"], eng_headers(eng_id)))
    assert report["status"] == "ATTESTED"
    reconciled = validate_success(
        api.reconcile_report(cid, report["id"],
                             {"expected_contract_version": contract["version"]},
                             own_headers(owner_id))
    )
    assert reconciled["status"] == "RECONCILED"
    after = validate_success(api.get_contract(cid, own_headers(owner_id)))
    assert after["version"] == contract["version"] + 1


def test_occ_baseline_adjustment_with_stale_baseline_version_rejected(api):
    """PRD §2.7: "If the baseline's current `version` does not match —
    because another adjustment has just been approved against it, restating
    the baseline and bumping its `version_tag` — the approval is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "if the adjustment carried an `occupancy_factor_override`, that
    value replaces the baseline's `occupancy_factor`"

    Design: Corner/endpoints/occ_baseline_adjustment_with_stale_baseline_version_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, baseline, _bd, _m, _f, _p = performance_contract(
        eng_id, owner_id
    )
    cid, bid = contract["id"], baseline["id"]
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    adjustment = validate_success(
        api.create_adjustment(cid, create_adjustment_payload(
            baseline_id=bid, supersedes_adjustment_id=None,
            reason="OCCUPANCY_CHANGE", kwh_delta=5000,
            occupancy_factor_override=0.6),
                              eng_headers(eng_id)),
        201,
    )
    response = api.approve_adjustment(
        cid, adjustment["id"],
        {"expected_baseline_version": baseline["version"] - 1},
        own_headers(owner_id),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    adjustment = validate_success(
        api.get_adjustment(cid, adjustment["id"], eng_headers(eng_id))
    )
    assert adjustment["status"] == "PROPOSED"
    approved = validate_success(
        api.approve_adjustment(cid, adjustment["id"],
                               {"expected_baseline_version": baseline["version"]},
                               own_headers(owner_id))
    )
    assert approved["status"] == "APPROVED"
    baseline = validate_success(api.get_baseline(cid, bid, eng_headers(eng_id)))
    assert baseline["status"] == "RESTATED"
    assert baseline["occupancy_factor"] == 0.6
