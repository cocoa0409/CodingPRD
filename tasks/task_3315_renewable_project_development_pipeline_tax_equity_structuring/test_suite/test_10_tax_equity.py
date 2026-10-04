"""Tax equity: waterfall rounding, the flip's pinned IRR evaluation order,
the credit-allocation invariant, and OCC on the partnership version."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_cod_project,
    create_partnership_payload,
    create_project,
    establish_tcq,
    get_success_data,
    post_distribution,
    safe_harbor_project,
    validate_error,
    validate_success,
)


def _cod_with_partnership(name, cluster_id, capacity, commitment=1000000.00,
                          target_irr_pct=8.0, **order_kwargs):
    """Project at COD with a fully funded partnership in PRE_FLIP_OPERATING."""
    overrides = {
        "order_amount_usd": 10000000,
        "safe_harbor_method": "FIVE_PERCENT_COST",
        "eligible_cost_basis_usd": 10000000,
        "deposit_usd": 500000.00,
        "supplier_domestic_content": True,
    }
    overrides.update(order_kwargs)
    return build_cod_project(
        name, cluster_id, capacity,
        project_overrides={"energy_community_eligible": True,
                           "domestic_content_certified": True},
        order_overrides=overrides,
        partnership={"investor_name": "Bank of America TE",
                     "commitment_usd": commitment,
                     "target_irr_pct": target_irr_pct},
    )


def _entries(api, partnership_id, headers, entry_type=None):
    params = {"limit": 100}
    if entry_type:
        params["entry_type"] = entry_type
    data = get_success_data(
        api.list_ledger_entries(partnership_id, headers, params=params)
    )
    return data if isinstance(data, list) else data.get("data", [])


def test_waterfall_per_tier_rounding_mode_b(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "The waterfall splits the cash between investor and developer
    at the investor share for the current stage — 99.00 percent before the
    flip, 5.00 percent after — with a pinned rounding order: the investor tier
    is rounded first, as the amount multiplied by the investor share percentage
    divided by 100, rounded half-up to 2 decimal places, and the developer tier
    takes the remainder of the amount. ... A distribution therefore creates
    four ledger entries on the first run — a `DISTRIBUTION_INVESTOR`, a
    `DISTRIBUTION_DEVELOPER`, a `CREDIT_ALLOCATION_INVESTOR`, and a
    `CREDIT_ALLOCATION_DEVELOPER` — and two entries thereafter once credits are
    fully allocated."

    Design: Difficulty/combinatorial_formula/waterfall_per_tier_rounding_mode_b
    """
    result = _cod_with_partnership("Waterfall Farm", "CL-B", 200)
    ps = result["partnership"]
    assert ps["status"] == "PRE_FLIP_OPERATING"
    entries = post_distribution(ps["id"], 100000.01, "2027-12-31T00:00:00Z")
    assert len(entries) == 4
    by_type = {e["entry_type"]: e["amount_usd"] for e in entries}
    # round_half_up(100000.01 * 0.99) = 99000.01; developer takes the remainder.
    assert by_type["DISTRIBUTION_INVESTOR"] == pytest.approx(99000.01, abs=0.001)
    assert by_type["DISTRIBUTION_DEVELOPER"] == pytest.approx(1000.00, abs=0.001)
    # Credit tier over the 5,000,000.00 credit pool at 99/1.
    assert by_type["CREDIT_ALLOCATION_INVESTOR"] == pytest.approx(4950000.00, abs=0.001)
    assert by_type["CREDIT_ALLOCATION_DEVELOPER"] == pytest.approx(50000.00, abs=0.001)
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    assert ps_now["retained_cash_usd"] == pytest.approx(899999.99, abs=0.001)


def test_flip_irr_evaluation_order_mode_c(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "first, cumulative contributions are summed from the
    `CONTRIBUTION` entries; second, the cumulative investor return is summed
    from the `DISTRIBUTION_INVESTOR` and `CREDIT_ALLOCATION_INVESTOR` entries;
    third, the `investor_irr_pct` snapshot is computed from those two sums
    exactly as defined above — 0.00 when contributions are zero — and this
    snapshot never includes hypothetical post-flip distributions; fourth, the
    flip is permitted if and only if that snapshot is at least the
    `target_irr_pct`, failing with `ERR_TARGET_IRR_NOT_ACHIEVED` (HTTP 409)
    below target. Only after a successful flip do subsequent distribution runs
    switch to the post-flip shares. A successful flip stamps `flip_date` from
    the logical clock."

    Design: Difficulty/combinatorial_formula/flip_irr_evaluation_order_mode_c
    """
    result = _cod_with_partnership("Flip Farm", "CL-C", 200)
    ps = result["partnership"]
    post_distribution(ps["id"], 100000.01, "2027-12-31T00:00:00Z")
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    # Pre-flip snapshot: (99000.01 + 4950000.00) / 1000000.00 - 1 = 4.04900001 -> 404.90.
    assert ps_now["investor_irr_pct"] == pytest.approx(404.90, abs=0.001)
    flipped = get_success_data(
        api.transition_partnership(
            ps["id"],
            {"to": "FLIPPED", "expected_partnership_version": ps_now["version"]},
            tax_counsel_headers,
        )
    )
    assert flipped["status"] == "FLIPPED"
    assert flipped["flip_date"] is not None
    # Post-flip distribution at 5/95; credits fully allocated, so only 2 entries.
    entries = post_distribution(ps["id"], 200000.00, "2028-03-31T00:00:00Z")
    assert len(entries) == 2
    by_type = {e["entry_type"]: e["amount_usd"] for e in entries}
    assert by_type["DISTRIBUTION_INVESTOR"] == pytest.approx(10000.00, abs=0.001)
    assert by_type["DISTRIBUTION_DEVELOPER"] == pytest.approx(190000.00, abs=0.001)


def test_flip_below_target_irr_rejected(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "fourth, the flip is permitted if and only if that snapshot is
    at least the `target_irr_pct`, failing with `ERR_TARGET_IRR_NOT_ACHIEVED`
    (HTTP 409) below target."

    Design: Difficulty/combinatorial_formula/flip_irr_evaluation_order_mode_c
    """
    # No distribution run: investor return 0, contributions 1,000,000.00, so
    # the IRR snapshot is -100.00 — far below the 8.0 target.
    result = _cod_with_partnership("Flip Gate Farm", "CL-FG", 200)
    ps = result["partnership"]
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    resp = api.transition_partnership(
        ps["id"],
        {"to": "FLIPPED", "expected_partnership_version": ps_now["version"]},
        tax_counsel_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TARGET_IRR_NOT_ACHIEVED)
    current = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    assert current["status"] == "PRE_FLIP_OPERATING"


def test_credit_allocation_sum_invariant(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "Across every run, the cumulative sum of investor credit
    allocations plus the cumulative sum of developer credit allocations always
    equals the project's `total_itc_credits_usd`."
    PRD §3.7: "A credit tier runs alongside the cash tier only while
    unallocated credits remain".

    Design: Difficulty/compensating_invariant/credit_allocation_sum_invariant
    """
    result = _cod_with_partnership("Invariant Farm", "CL-IV", 200)
    project = result["project"]
    ps = result["partnership"]
    post_distribution(ps["id"], 100000.01, "2027-12-31T00:00:00Z")
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    get_success_data(
        api.transition_partnership(
            ps["id"],
            {"to": "FLIPPED", "expected_partnership_version": ps_now["version"]},
            tax_counsel_headers,
        )
    )
    post_distribution(ps["id"], 200000.00, "2028-03-31T00:00:00Z")
    entries = _entries(api, ps["id"], tax_counsel_headers)
    # 1 contribution + 4 first-run entries + 2 second-run entries.
    assert len(entries) == 7
    credit_inv = sum(
        e["amount_usd"] for e in entries if e["entry_type"] == "CREDIT_ALLOCATION_INVESTOR"
    )
    credit_dev = sum(
        e["amount_usd"] for e in entries if e["entry_type"] == "CREDIT_ALLOCATION_DEVELOPER"
    )
    assert credit_inv + credit_dev == pytest.approx(
        project["total_itc_credits_usd"], abs=0.001
    )
    assert project["total_itc_credits_usd"] == pytest.approx(5000000.00, abs=0.001)


def test_credit_allocation_invariant_entry_type_filter(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "Every ledger entry records its `entry_type`, its computed
    `amount_usd` ... and its `period_end_date`; entries are immutable, and the
    entry list may be filtered by `entry_type`."

    Design: Difficulty/compensating_invariant/credit_allocation_sum_invariant
    """
    result = _cod_with_partnership("Invariant Farm 2", "CL-IV2", 200)
    ps = result["partnership"]
    post_distribution(ps["id"], 50000.00, "2027-12-31T00:00:00Z")
    filtered = _entries(api, ps["id"], tax_counsel_headers,
                        entry_type="CREDIT_ALLOCATION_INVESTOR")
    assert len(filtered) == 1
    assert all(e["entry_type"] == "CREDIT_ALLOCATION_INVESTOR" for e in filtered)
    unfiltered = _entries(api, ps["id"], tax_counsel_headers)
    # 1 contribution + 4 distribution-run entries.
    assert len(unfiltered) == 5


def test_waterfall_second_run_no_credit_tier(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "A credit tier runs alongside the cash tier only while
    unallocated credits remain: the unallocated credit is the project's
    `total_itc_credits_usd` minus the sum of all existing credit allocation
    entries, and when that remainder is positive, it is split at the same stage
    share with the same rounding order — investor tier rounded first, developer
    tier taking the remainder. A distribution therefore creates four ledger
    entries on the first run — a `DISTRIBUTION_INVESTOR`, a
    `DISTRIBUTION_DEVELOPER`, a `CREDIT_ALLOCATION_INVESTOR`, and a
    `CREDIT_ALLOCATION_DEVELOPER` — and two entries thereafter once credits are
    fully allocated."

    Design: Difficulty/combinatorial_formula/waterfall_per_tier_rounding_mode_b
    """
    result = _cod_with_partnership("Waterfall Farm 2", "CL-B2", 200)
    ps = result["partnership"]
    # First run fully allocates the credit pool.
    first = post_distribution(ps["id"], 100000.01, "2027-12-31T00:00:00Z")
    assert len(first) == 4
    # Second pre-flip run: cash tier only, investor rounded first at 99%.
    second = post_distribution(ps["id"], 200000.00, "2028-03-31T00:00:00Z")
    assert len(second) == 2
    by_type = {e["entry_type"]: e["amount_usd"] for e in second}
    assert by_type["DISTRIBUTION_INVESTOR"] == pytest.approx(198000.00, abs=0.001)
    assert by_type["DISTRIBUTION_DEVELOPER"] == pytest.approx(2000.00, abs=0.001)


def test_flip_election_stale_partnership_version(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §2.7: "When electing the flip on a tax equity partnership, the
    request must carry `expected_partnership_version`, the client-side last
    observed `version` of the partnership. Contributions and distributions each
    advance the partnership `version`, so a stale version means the IRR basis
    the client relied on is no longer current; the flip election is then
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/flip_election_stale_partnership_version
    """
    result = _cod_with_partnership("Flip OCC Farm", "CL-FO", 200)
    ps = result["partnership"]
    post_distribution(ps["id"], 100000.01, "2027-12-31T00:00:00Z")
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    stale_version = ps_now["version"]
    # Another distribution advances the partnership version past the capture.
    post_distribution(ps["id"], 50000.00, "2028-03-31T00:00:00Z")
    resp = api.transition_partnership(
        ps["id"],
        {"to": "FLIPPED", "expected_partnership_version": stale_version},
        tax_counsel_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    assert current["status"] == "PRE_FLIP_OPERATING"


def test_contribution_cap_enforced_on_cumulative_sum(
    api, developer_admin_headers, tax_counsel_headers, investor_manager_headers
):
    """PRD §3.7: "it may not push `contributed_usd` above the `commitment_usd`
    cap (otherwise `ERR_CONTRIBUTION_EXCEEDS_COMMITMENT`, HTTP 422). ...
    `contributed_usd`, the sum of all `CONTRIBUTION` entries".
    PRD §3.7: "The first contribution auto-advances the partnership from
    `COMMITMENT_EXECUTED` to `FUNDING`".

    Design: Corner/calculations/contribution_cap_enforced_on_cumulative_sum
    """
    project = create_project(name="Cap Farm", technology="SOLAR",
                             target_capacity_mw=70)
    pid = project["id"]
    safe_harbor_project(pid, order_amount_usd=1000000,
                        safe_harbor_method="FIVE_PERCENT_COST",
                        eligible_cost_basis_usd=1000000, deposit_usd=60000.00)
    establish_tcq(pid)
    ps = validate_success(
        api.create_partnership(
            pid,
            create_partnership_payload(
                investor_name="Cap Investors", commitment_usd=1000000.00,
                target_irr_pct=7.5,
            ),
            tax_counsel_headers,
        ),
        expected_status=201,
    )
    get_success_data(
        api.transition_partnership(ps["id"], {"to": "COMMITMENT_EXECUTED"},
                                   tax_counsel_headers)
    )
    get_success_data(
        api.post_contribution(
            ps["id"], {"amount_usd": 600000.00,
                       "period_end_date": "2026-12-31T00:00:00Z"},
            investor_manager_headers,
        )
    )
    # 600,000 + 500,000 > 1,000,000 commitment: refused without partial credit.
    resp = api.post_contribution(
        ps["id"], {"amount_usd": 500000.00,
                   "period_end_date": "2027-03-31T00:00:00Z"},
        investor_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_EXCEEDS_COMMITMENT)
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    assert ps_now["contributed_usd"] == pytest.approx(600000.00, abs=0.001)
    assert ps_now["status"] == "FUNDING"


def test_partnership_commitment_requires_anchored_credit(
    api, developer_admin_headers, tax_counsel_headers
):
    """PRD §3.7: "Executing the commitment — moving the partnership from
    `STRUCTURING` to `COMMITMENT_EXECUTED` — requires the project's tax credit
    qualification to be anchored in `SAFE_HARBOR_ESTABLISHED`,
    `CONTINUITY_MAINTAINED`, `CURED`, or `QUALIFIED` (otherwise
    `ERR_SAFE_HARBOR_NOT_QUALIFIED`, HTTP 409)."

    Design: Corner/validations/partnership_commitment_requires_anchored_credit
    """
    project = create_project(name="Anchor Farm", technology="SOLAR",
                             target_capacity_mw=45, resource_class="B")
    ps = validate_success(
        api.create_partnership(
            project["id"],
            create_partnership_payload(
                investor_name="Anchor TE", commitment_usd=750000.00,
                target_irr_pct=8.5,
            ),
            tax_counsel_headers,
        ),
        expected_status=201,
    )
    resp = api.transition_partnership(
        ps["id"], {"to": "COMMITMENT_EXECUTED"}, tax_counsel_headers
    )
    validate_error(resp, ApiErrorId.ERR_SAFE_HARBOR_NOT_QUALIFIED)
    ps_now = get_success_data(api.get_partnership(ps["id"], tax_counsel_headers))
    assert ps_now["status"] == "STRUCTURING"
