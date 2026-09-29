"""Endpoint behaviour: the collection verbs, the guarded creations and the computed read.

These tests exercise the report-line collection through its whole cycle, the two
creations that link one resource to another, and the read-only breakdown, checking in
each case what the endpoint returns and what it leaves alone.
"""

from test_helpers import (
    ApiErrorId,
    FeePaymentStatus,
    FeeRoundingOrder,
    FeeScheduleStatus,
    FeeVariant,
    MembershipStatus,
    ReportFeeStatus,
    VERIFIER_HEADERS,
    assert_cents,
    assert_exact_cents,
    assert_fee_schedule,
    assert_invoice,
    assert_membership,
    assert_no_version_movement,
    assert_report,
    assert_report_line,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The line collection: append, read, list, delete — all visible on the parent
# ---------------------------------------------------------------------------
def test_the_line_collection_cycle_is_visible_on_the_parent_report(api):
    """Two lines lift the draft report to 7.500 kg and the removal puts it back.

    Each append and each removal is a write on the report as well as on the line, so
    the report's rollups and version move four times over the cycle; the removal
    answers with no content at all, the removed line stops being readable, and the
    surviving line is untouched. None of it reaches the year-to-date total, because a
    draft report is outside the counted set.

    Design: Corner/endpoints/report_line_create_read_list_and_delete_recompute_the_report_rollup
    """
    chain = fx.base_ca_chain(api)
    headers = chain["officer_headers"]
    second_period = fx.make_reporting_period(
        api,
        chain["program"]["id"],
        period_label="CA-2026-H2",
        data_start="2027-01-01",
        data_end="2027-07-01",
        submission_open="2027-01-01T00:00:00Z",
        submission_deadline="2027-06-30T23:59:59Z",
        correction_window_days=30,
    )
    paper_sku = fx.make_sku_with_components(
        api,
        chain["producer"],
        components=[f.component_payload(material_type="PAPER", unit_weight_grams=20.00)],
        name="Case Wrap",
        product_category="FOOD_DRY",
        units_sold_annual_estimate=100,
    )
    report = fx.make_report(api, chain["producer"], chain["registration"], second_period)
    glass_line = fx.add_line(api, chain["producer"], report, chain["sku"], 110)
    paper_line = fx.add_line(api, chain["producer"], report, paper_sku, 100)

    assert_report_line(
        validate_success(api.get_report_line(paper_line["id"], headers)),
        sku_id=paper_sku["id"],
        units_sold=100,
        line_weight_kg=2.000,
        fee_exempt=False,
    )
    rows, meta = validate_paginated(
        api.list_report_lines(headers, {"packaging_report_id": report["id"], "limit": 5, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 5 and meta["offset"] == 0
    assert {row["id"] for row in rows} == {glass_line["id"], paper_line["id"]}
    assert_report(
        validate_success(api.get_report(report["id"], headers)),
        total_weight_kg=7.500,
        fee_basis_weight_kg=7.500,
        line_count=2,
        version=3,
    )

    removal = api.delete_report_line(paper_line["id"], headers)

    assert removal.status_code == 204, removal.text
    assert removal.text == ""
    assert_report(
        validate_success(api.get_report(report["id"], headers)),
        total_weight_kg=5.500,
        fee_basis_weight_kg=5.500,
        line_count=1,
        version=4,
    )
    validate_error(
        api.get_report_line(paper_line["id"], headers), ApiErrorId.REPORT_LINE_NOT_FOUND, 404
    )
    assert_report_line(
        validate_success(api.get_report_line(glass_line["id"], headers)),
        line_weight_kg=5.500,
    )
    assert_weight(
        validate_success(api.get_registration(chain["registration"]["id"], headers))[
            "reported_weight_kg_ytd"
        ],
        5.500,
        "reported_weight_kg_ytd",
    )


# ---------------------------------------------------------------------------
# Billing is admitted from one fee position only
# ---------------------------------------------------------------------------
def test_an_invoice_is_refused_until_the_assessment_is_final(api):
    """The same body fails against a provisional price and succeeds against a final one.

    The provisional price excludes the report's own tonnage from the tier basis and the
    final one includes it, and although the glass band is flat enough that both come to
    fifty cents, only the final position admits the bill. The failed attempt leaves the
    producer owing nothing.

    Design: Corner/endpoints/invoice_creation_is_allowed_only_from_a_final_fee_status
    """
    chain = fx.base_ca_chain(api)
    officer_headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    body = f.invoice_payload(chain["report"]["id"], chain["membership"]["id"])

    provisional = fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.PROVISIONAL)
    validate_error(api.create_invoice(body, admin_headers), ApiErrorId.INVALID_STATE, 409)

    assert_report(
        provisional,
        fee_status=ReportFeeStatus.PROVISIONAL,
        tier_basis_kg=0.000,
        fee_variant_applied=FeeVariant.PROVISIONAL,
        fee_subtotal_cents=50,
    )
    rows, meta = validate_paginated(
        api.list_invoices(admin_headers, {"packaging_report_id": chain["report"]["id"]})
    )
    assert meta["total_count"] == 0 and rows == []
    assert_cents(
        validate_success(api.get_producer(chain["producer"]["id"], officer_headers))[
            "assessed_fee_balance_cents"
        ],
        0,
        "assessed_fee_balance_cents",
    )

    final = fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    invoice = validate_success(api.create_invoice(body, admin_headers), 201)

    assert_report(
        final,
        fee_status=ReportFeeStatus.FINAL,
        tier_basis_kg=5.500,
        fee_subtotal_cents=50,
    )
    assert_invoice(invoice, total_cents=53, status="ISSUED")
    assert_report(
        validate_success(api.get_report(chain["report"]["id"], officer_headers)),
        fee_status=ReportFeeStatus.INVOICED,
    )
    assert_cents(
        validate_success(api.get_producer(chain["producer"]["id"], officer_headers))[
            "assessed_fee_balance_cents"
        ],
        53,
        "assessed_fee_balance_cents",
    )


# ---------------------------------------------------------------------------
# The membership link checks both of the schedule's owners before it pins anything
# ---------------------------------------------------------------------------
def test_the_membership_link_checks_the_schedule_owner_and_its_program(api):
    """A schedule for another state, then one from another organisation, then the right one.

    Both refusals name what is wrong with the elected schedule rather than its status,
    since all three schedules are published, and neither attempt moves the
    registration. The accepted link is created with nothing assessed and nothing
    pinned; approval is what prices it and pins the schedule version.

    Design: Corner/endpoints/membership_link_validates_both_referenced_owners_before_pinning_the_schedule
    """
    chain = fx.base_ca_chain(api)
    headers = chain["officer_headers"]
    other_state = fx.make_breadth_program(api, state_code="WA")
    wrong_program = fx.published_fee_schedule(api, chain["pro"], other_state["id"])
    other_pro = fx.make_pro(api, name="Pacific Stewardship Co", contact_email="ops@pacific.example")
    wrong_pro = fx.published_fee_schedule(api, other_pro, chain["program"]["id"])
    version_before = fx.read_registration_version(
        api, chain["producer"], chain["registration"]["id"]
    )

    validate_error(
        api.create_membership(
            f.membership_payload(
                chain["registration"]["id"],
                chain["pro"]["id"],
                wrong_program["id"],
                version_before,
            ),
            headers,
        ),
        ApiErrorId.FEE_SCHEDULE_PROGRAM_MISMATCH,
        422,
    )
    validate_error(
        api.create_membership(
            f.membership_payload(
                chain["registration"]["id"],
                chain["pro"]["id"],
                wrong_pro["id"],
                version_before,
            ),
            headers,
        ),
        ApiErrorId.FEE_SCHEDULE_PRO_MISMATCH,
        422,
    )
    assert (
        fx.read_registration_version(api, chain["producer"], chain["registration"]["id"])
        == version_before
    )

    application = validate_success(
        api.create_membership(
            f.membership_payload(
                chain["registration"]["id"],
                chain["pro"]["id"],
                chain["schedule"]["id"],
                version_before,
            ),
            headers,
        ),
        201,
    )

    assert_membership(
        application,
        status=MembershipStatus.PENDING,
        fee_schedule_id=chain["schedule"]["id"],
        membership_fee_cents=0,
        fee_schedule_version_pinned=None,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], chain["admin_headers"])),
        status=MembershipStatus.TERMINATED,
        decision_reason="SUPERSEDED_BY_NEW_MEMBERSHIP",
    )

    approved = fx.approve_membership(api, chain["pro"], application)

    assert_membership(
        approved,
        status=MembershipStatus.ACTIVE,
        membership_fee_cents=250000,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=2,
    )
    assert_fee_schedule(
        validate_success(api.get_fee_schedule(chain["schedule"]["id"], headers)),
        status=FeeScheduleStatus.PUBLISHED,
    )
    assert_fee_schedule(
        validate_success(api.get_fee_schedule(wrong_program["id"], headers)),
        status=FeeScheduleStatus.PUBLISHED,
    )


# ---------------------------------------------------------------------------
# The computed read mirrors the stored assessment and touches nothing
# ---------------------------------------------------------------------------
def _line_rows_of(breakdown, line_id):
    """The breakdown's per-line rows, found by the line identifier they carry."""
    for value in breakdown.values():
        if isinstance(value, list) and any(
            isinstance(row, dict) and line_id in row.values() for row in value
        ):
            return value
    raise AssertionError(f"No per-line rows naming {line_id} in {sorted(breakdown)}")


def _reconciliation_deltas(breakdown):
    """Whatever the breakdown calls the sum-of-lines reconciliation delta."""
    deltas = {k: v for k, v in breakdown.items() if "delta" in k}
    assert deltas, f"No reconciliation delta in {sorted(breakdown)}"
    return deltas


def test_the_fee_breakdown_mirrors_the_assessment_for_every_reader(api):
    """Both readers get the same figures and neither read moves a version.

    The breakdown repeats the tier basis and the variant of the last assessment, names
    the state's rounding order, and carries the line's exact and rounded values; under
    the per-line order the rounded line value already equals the stored subtotal, so
    the reconciliation delta is nothing. The verifier's read is identical to the
    producer's, and the report and its line are exactly as they were.

    Design: Corner/endpoints/fee_breakdown_read_mirrors_the_stored_assessment_and_writes_nothing
    """
    chain = fx.base_ca_chain(api)
    headers = chain["officer_headers"]
    assessed = fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.FINAL)
    line_before = validate_success(api.get_report_line(chain["line"]["id"], headers))

    producer_view = validate_success(api.get_fee_breakdown(chain["report"]["id"], headers))
    verifier_view = validate_success(
        api.get_fee_breakdown(chain["report"]["id"], VERIFIER_HEADERS)
    )

    assert_weight(producer_view["tier_basis_kg"], 5.500, "tier_basis_kg")
    assert producer_view["fee_variant_applied"] == FeeVariant.FINAL
    assert producer_view["fee_rounding_order_applied"] == FeeRoundingOrder.PER_LINE_THEN_SUM
    rows = _line_rows_of(producer_view, chain["line"]["id"])
    assert len(rows) == 1
    assert_exact_cents(rows[0]["line_fee_exact_cents"], 49.5000, "line_fee_exact_cents")
    assert_cents(rows[0]["line_fee_cents"], 50, "line_fee_cents")
    for name, value in _reconciliation_deltas(producer_view).items():
        assert_cents(value, 0, name)
    assert verifier_view == producer_view

    assert_no_version_movement(
        assessed, validate_success(api.get_report(chain["report"]["id"], headers)), "report"
    )
    assert_no_version_movement(
        line_before,
        validate_success(api.get_report_line(chain["line"]["id"], headers)),
        "report line",
    )
