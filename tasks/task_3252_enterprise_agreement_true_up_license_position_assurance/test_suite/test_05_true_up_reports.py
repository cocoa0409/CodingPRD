"""True-up report workflow: pricing variants, rounding order, lifecycle, cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_true_up_line,
    create_entitlement,
    create_product,
    create_true_up_report,
    create_user_deployment,
    get_success_data,
    make_customer_admin_headers,
    setup_active_agreement_with_anniversary,
    setup_report_in_state,
    update_organization_devices,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_true_up_anniversary_proration_vs_full_year_retroactive(api):
    """PRD §3.5: "Under the `FULL_YEAR_RETROACTIVE` variant, the line total is the full base amount — the entire annual price regardless of when during the year the growth occurred, and therefore never less than the prorated amount for identical inputs. Under the `ANNIVERSARY_PRORATION` variant, the line total is the base multiplied by the fraction of the anniversary year remaining — twelve minus `months_growth` plus one, over twelve — rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/true_up_anniversary_proration_vs_full_year_retroactive
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="U1", name="User Cal", annual_unit_price_cents=100000)
    create_entitlement(agr["id"], prod["id"], 10)
    create_user_deployment(agr["id"], org["id"], prod["id"], 20)  # growth = 10
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    line_a = add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=3,
                              pricing_variant="ANNIVERSARY_PRORATION")
    assert line_a["total_amount_cents"] == 833333, "10 * 100000 * 10/12 rounded half-up"
    line_b = add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=3,
                              pricing_variant="FULL_YEAR_RETROACTIVE")
    assert line_b["total_amount_cents"] == 1000000, "full-year retroactive charges the full base"
    rep_after = get_success_data(api.get_true_up_report(rep["id"], LS))
    assert rep_after["total_amount_cents"] == 1833333, "report total is the sum of per-line rounded totals"
    assert line_b["total_amount_cents"] - line_a["total_amount_cents"] == 166667


def test_true_up_variants_diverge_on_months_growth(api):
    """PRD §3.5: "Under the `ANNIVERSARY_PRORATION` variant, the line total is the base multiplied by the fraction of the anniversary year remaining — twelve minus `months_growth` plus one, over twelve — rounded half-up to whole cents."
    PRD §3.5: "Under the `FULL_YEAR_RETROACTIVE` variant, the line total is the full base amount — the entire annual price regardless of when during the year the growth occurred, and therefore never less than the prorated amount for identical inputs."

    Design: Difficulty/dual_variant_calc/true_up_anniversary_proration_vs_full_year_retroactive
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="U2", name="User Cal 2", annual_unit_price_cents=120000)
    create_user_deployment(agr["id"], org["id"], prod["id"], 5)  # growth = 5
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    line_prorate = add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=12,
                                    pricing_variant="ANNIVERSARY_PRORATION")
    # growth 5 * 120000 * (12-12+1)/12 = 50000
    assert line_prorate["total_amount_cents"] == 50000
    line_full = add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=12,
                                 pricing_variant="FULL_YEAR_RETROACTIVE")
    assert line_full["total_amount_cents"] == 600000


def test_true_up_per_line_rounding_order(api):
    """PRD §3.5: "The report's `total_amount_cents` is the sum of the individually rounded line totals; lines are rounded first, summed second, never the reverse."

    Design: Difficulty/combinatorial_formula/true_up_per_line_rounding_order
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    p1 = create_product(sku="R1", name="Round One", annual_unit_price_cents=100001)
    p2 = create_product(sku="R2", name="Round Two", annual_unit_price_cents=100001)
    create_user_deployment(agr["id"], org["id"], p1["id"], 1)
    create_user_deployment(agr["id"], org["id"], p2["id"], 1)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    l1 = add_true_up_line(rep["id"], org["id"], p1["id"], months_growth=7,
                          pricing_variant="ANNIVERSARY_PRORATION")
    l2 = add_true_up_line(rep["id"], org["id"], p2["id"], months_growth=7,
                          pricing_variant="ANNIVERSARY_PRORATION")
    # round_half_up(100001 * 6/12) = round_half_up(50000.5) = 50001 per line
    assert l1["total_amount_cents"] == 50001
    assert l2["total_amount_cents"] == 50001
    rep_after = get_success_data(api.get_true_up_report(rep["id"], LS))
    assert rep_after["total_amount_cents"] == 100002, "round per line, then sum — never the reverse"


def test_true_up_report_rejection_revision_cycle(api):
    """PRD §3.5: "Rejection is not terminal: the customer may revise, moving the report `REJECTED → DRAFT` with `revision_count` incremented by 1 — the owning agreement must still be `ACTIVE` — and the cycle may repeat".

    Design: Difficulty/non_linear_state_machine/true_up_report_rejection_revision_cycle
    """
    ctx = setup_report_in_state("REJECTED", deployment_users=8, entitlement_qty=5,
                                months_growth=6, pricing_variant="ANNIVERSARY_PRORATION")
    rep, org = ctx["report"], ctx["org"]
    assert rep["status"] == "REJECTED"
    resp = api.revise_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "DRAFT"
    assert data["revision_count"] == 1
    resp = api.submit_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    data2 = validate_success(resp, 200)
    assert data2["status"] == "SUBMITTED", "REJECTED is not terminal — the cycle repeats"


def test_revision_preserves_pinned_snapshot(api):
    """PRD §3.5: "note that re-snapshotting happens only when an entirely new report is created, not on revision, so the pinned snapshot survives revision loops."

    Design: Difficulty/non_linear_state_machine/true_up_report_rejection_revision_cycle
    """
    ctx = setup_report_in_state("REJECTED", deployment_users=8, entitlement_qty=5)
    rep, org = ctx["report"], ctx["org"]
    pinned = rep["snapshot_id"]
    resp = api.revise_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    data = validate_success(resp, 200)
    assert data["snapshot_id"] == pinned, "revision must not re-snapshot"


def test_submit_empty_report_rejected(api):
    """PRD §3.5: "a report with zero lines is rejected with `ERR_REPORT_EMPTY` (HTTP 422)".

    Design: Corner/endpoints/submit_empty_report_rejected
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    resp = api.submit_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_REPORT_EMPTY, 422)


def test_months_growth_out_of_range_rejected(api):
    """PRD §3.5: "declares `months_growth` — the number of whole months the growth was in use before the anniversary date, which must lie within 1 through 12 inclusive or the line is rejected with `ERR_MONTHS_OUT_OF_RANGE` (HTTP 422)".

    Design: Corner/validations/months_growth_out_of_range_rejected
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="MO1")
    create_user_deployment(agr["id"], org["id"], prod["id"], 2)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    resp = api.add_true_up_line(
        rep["id"], {"product_id": prod["id"], "months_growth": 13,
                    "pricing_variant": "ANNIVERSARY_PRORATION"},
        make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_MONTHS_OUT_OF_RANGE, 422)


def test_submit_reprices_lines_at_current_price_level(api):
    """PRD §3.5: "Submission reprices every line: each line's `unit_price_cents` is recomputed from the organization's current price level (resolving any tier movement since drafting), each line total is recomputed under its chosen variant, and the report total is re-summed."

    Design: Corner/calculations/submit_reprices_lines_at_current_price_level
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="RP1", name="Reprice Cal", annual_unit_price_cents=100000)
    create_user_deployment(agr["id"], org["id"], prod["id"], 4)  # growth 4, no entitlement
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    line = add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=6,
                            pricing_variant="ANNIVERSARY_PRORATION")
    assert line["unit_price_cents"] == 100000  # level A at drafting
    update_organization_devices(org["id"], 300)  # move org to level B
    submit = api.submit_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    rep_after = validate_success(submit, 200)
    assert rep_after["total_amount_cents"] == 221667, "round_half_up(4*95000*7/12)"
    lines, _ = validate_paginated(api.list_lines_of_report(rep["id"], LS))
    assert lines[0]["unit_price_cents"] == 95000, "repriced at level B multiplier 0.95"
    assert lines[0]["total_amount_cents"] == 221667


def test_submit_requires_agreement_active(api):
    """PRD §3.5: "Submitting the report moves it `DRAFT → SUBMITTED` and is performed by the `CustomerAdmin`; a report with zero lines is rejected with `ERR_REPORT_EMPTY` (HTTP 422), and the owning agreement must be `ACTIVE`."
    PRD §3.1: "Nearly every commercial mutation in the system — purchasing entitlements, reporting deployments, registering anniversaries, computing snapshots, opening true-up reports, granting benefits, creating commitments, requesting hosting authorizations, initiating step-ups, adjusting entitlement quantities — is gated on the agreement being `ACTIVE`; attempting any of them against an agreement in another status is rejected with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_agreement_active
    """
    ctx = setup_active_agreement_with_anniversary(
        agreement_overrides={"enrollment_number": "E-XD1-1",
                             "start_date": "2026-09-01", "end_date": "2026-09-30"})
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="W1", name="W Cal")
    create_entitlement(agr["id"], prod["id"], 1)
    create_user_deployment(agr["id"], org["id"], prod["id"], 2)
    rep = create_true_up_report(agr["id"], org["id"], ann["id"])
    add_true_up_line(rep["id"], org["id"], prod["id"], months_growth=1,
                     pricing_variant="ANNIVERSARY_PRORATION")
    from test_helpers import set_clock
    set_clock("2026-10-01T00:00:00Z")
    resp = api.expire_agreement(agr["id"], PA)
    assert resp.status_code == 200, get_success_data(resp)
    resp = api.submit_true_up_report(rep["id"], make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)


def test_true_up_duplicate_window_per_anniversary(api):
    """PRD §3.5: "At most one report in a non-`REJECTED` status may exist per agreement-and-anniversary pair; a second open report for the same anniversary is rejected with `ERR_DUPLICATE_TRUE_UP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/true_up_duplicate_window_per_anniversary
    """
    ctx = setup_active_agreement_with_anniversary()
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    prod = create_product(sku="D1", name="Dup Cal")
    create_user_deployment(agr["id"], org["id"], prod["id"], 3)
    rep1 = create_true_up_report(agr["id"], org["id"], ann["id"])
    resp = api.create_true_up_report(agr["id"], {"anniversary_id": ann["id"]},
                                     make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRUE_UP, 409)
    # Rejection frees the slot.
    add_true_up_line(rep1["id"], org["id"], prod["id"], months_growth=1)
    submit = api.submit_true_up_report(rep1["id"], make_customer_admin_headers(org["id"]))
    assert submit.status_code == 200, get_success_data(submit)
    rej = api.reject_true_up_report(rep1["id"], LS)
    assert rej.status_code == 200, get_success_data(rej)
    resp2 = api.create_true_up_report(agr["id"], {"anniversary_id": ann["id"]},
                                      make_customer_admin_headers(org["id"]))
    rep2 = validate_success(resp2, 201)
    assert rep2["status"] == "DRAFT"


def test_duplicate_true_up_blocked_while_accepted(api):
    """PRD §3.5: "At most one report in a non-`REJECTED` status may exist per agreement-and-anniversary pair; a second open report for the same anniversary is rejected with `ERR_DUPLICATE_TRUE_UP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/true_up_duplicate_window_per_anniversary
    """
    ctx = setup_report_in_state("ACCEPTED", deployment_users=3)
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    resp = api.create_true_up_report(agr["id"], {"anniversary_id": ann["id"]},
                                     make_customer_admin_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRUE_UP, 409)


def test_settle_cascade_entitlement_baseline_anniversary_closure_benefit_accrual(api):
    """PRD §3.5: "For each line, the matching entitlement — the one sharing the report's agreement and the line's product — has its `quantity` increased by the line's `growth_quantity`, and its `locked_baseline_quantity` is ratified up to the new quantity; each touched entitlement's `version` increments. The anniversary referenced by the report has its `true_up_closed` set true and its `version` incremented, sealing the anniversary against further snapshots or reports. And the settled report accrues software-assurance benefits per §3.7."
    PRD §3.7: "At five hundred thousand dollars or more but below two million dollars, the agreement accrues 5 training-voucher units and 1 support incident."

    Design: Difficulty/transitive_cascade/settle_cascade_entitlement_baseline_anniversary_closure_benefit_accrual
    """
    ctx = setup_report_in_state("INVOICED", deployment_users=505, entitlement_qty=5,
                                months_growth=2, pricing_variant="FULL_YEAR_RETROACTIVE")
    org, agr, ann = ctx["org"], ctx["agreement"], ctx["anniversary"]
    ent = ctx["entitlement"]
    resp = api.settle_true_up_report(ctx["report"]["id"], LS)
    rep = validate_success(resp, 200)
    assert rep["status"] == "SETTLED"
    assert rep["total_amount_cents"] == 50000000  # 500 * 100000 full-year: exactly the $500K tier boundary
    ent_after = get_success_data(api.get_entitlement(ent["id"], LS))
    assert ent_after["quantity"] == 505
    assert ent_after["locked_baseline_quantity"] == 505, "baseline ratified to the new quantity"
    ann_after = get_success_data(api.get_anniversary(ann["id"], LS))
    assert ann_after["true_up_closed"] is True
    grants, _ = validate_paginated(api.list_benefit_grants_of_agreement(agr["id"], LS))
    by_type = {}
    for g in grants:
        by_type.setdefault(g["benefit_type"], []).append(g)
    assert len(by_type.get("TRAINING_VOUCHER", [])) == 1
    assert by_type["TRAINING_VOUCHER"][0]["quantity_granted"] == 5
    assert len(by_type.get("SUPPORT_INCIDENT", [])) == 1
    assert by_type["SUPPORT_INCIDENT"][0]["quantity_granted"] == 1


def test_settle_immediately_visible_across_entities(api):
    """PRD §3.5: "Settlement is the ratification moment, and it cascades. For each line, the matching entitlement — the one sharing the report's agreement and the line's product — has its `quantity` increased by the line's `growth_quantity`, and its `locked_baseline_quantity` is ratified up to the new quantity; each touched entitlement's `version` increments. The anniversary referenced by the report has its `true_up_closed` set true and its `version` incremented, sealing the anniversary against further snapshots or reports."

    Design: Corner/consistency_model/settle_immediately_visible_across_entities
    """
    ctx = setup_report_in_state("INVOICED", deployment_users=7, entitlement_qty=5,
                                months_growth=1, pricing_variant="FULL_YEAR_RETROACTIVE")
    ann, ent = ctx["anniversary"], ctx["entitlement"]
    resp = api.settle_true_up_report(ctx["report"]["id"], LS)
    rep = validate_success(resp, 200)
    assert rep["status"] == "SETTLED"
    ent_after = get_success_data(api.get_entitlement(ent["id"], AUD))
    assert ent_after["quantity"] == 7
    ann_after = get_success_data(api.get_anniversary(ann["id"], AUD))
    assert ann_after["true_up_closed"] is True
