"""Derived arithmetic: rounding order, input sets, constants and thresholds.

Each test drives one calculation through the public endpoints with figures chosen so
that the intended order of operations is the only one that reproduces the answer, and
checks the neighbouring rollups that the same write is required to refresh.
"""

from test_helpers import (
    CompliancePosture,
    DecisionReason,
    FeePaymentStatus,
    FeeVariant,
    MembershipStatus,
    ObligatedPartyRole,
    ProducerStatus,
    ReportFeeStatus,
    SkuStatus,
    SubmissionStatus,
    assert_cents,
    assert_eco_mod_row,
    assert_exact_cents,
    assert_membership,
    assert_producer,
    assert_registration,
    assert_report,
    assert_report_line,
    assert_sku,
    assert_weight,
    factories as f,
    fixtures as fx,
    validate_success,
)


# ---------------------------------------------------------------------------
# Each unit is rounded before the sum, not after it
# ---------------------------------------------------------------------------
def test_the_producer_rollup_rounds_every_unit_before_adding_them_up(api):
    """Two half-gram units each round up to a full gram, so the total ends in 5.502.

    A unit of one item weighing 0.50 g contributes 0.0005 kg, which rounds half up to
    0.001 kg on its own; two such units therefore add 0.002 kg to the 5.500 kg of
    glass. Adding the raw contributions first and rounding once would give 5.501.

    Design: Corner/calculations/producer_weight_rollup_rounds_each_sku_before_summing
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email="compliance@northlake.example",
    )
    glass = fx.glass_mini_sku(api, producer, name="Sparkling Water 750ml")
    sachet_a = fx.make_sku_with_components(
        api,
        producer,
        components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=0.50,
                recyclability_class="LIMITED",
                pcr_content_pct=0,
            )
        ],
        name="Sample Sachet A",
        product_category="FOOD_DRY",
        units_sold_annual_estimate=1,
    )
    sachet_b = fx.make_sku_with_components(
        api,
        producer,
        components=[
            f.component_payload(material_type="PAPER", unit_weight_grams=0.50)
        ],
        name="Sample Sachet B",
        product_category="FOOD_DRY",
        units_sold_annual_estimate=1,
    )

    determined = fx.determine_obligation(api, producer)

    headers = fx.officer(producer)
    assert_sku(
        validate_success(api.get_sku(glass["id"], headers)),
        unit_packaging_weight_grams=50.00,
    )
    for sachet in (sachet_a, sachet_b):
        assert_sku(
            validate_success(api.get_sku(sachet["id"], headers)),
            unit_packaging_weight_grams=0.50,
        )
    assert_producer(
        determined,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.BRAND_OWNER,
        determination_stale=False,
    )
    assert_weight(
        determined["annual_packaging_weight_kg"], 5.502, "annual_packaging_weight_kg"
    )
    assert determined["annual_packaging_weight_kg"] != 5.501


# ---------------------------------------------------------------------------
# Only ACTIVE units and ACTIVE components enter the rollup
# ---------------------------------------------------------------------------
def test_the_rollup_ignores_draft_units_and_superseded_components(api):
    """A draft unit worth 100 kg never counts, and a revision retires what it replaces.

    The rollup sees only the activated glass unit, so it reads 5.500 kg even though a
    second unit holding 100.000 kg of plastic exists in draft. Replacing the glass
    with a lighter plastic component supersedes the old one rather than adding to it,
    so the figure falls to 2.200 kg and the determination is marked stale.

    Design: Corner/calculations/producer_weight_excludes_draft_skus_and_superseded_components
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email="compliance@northlake.example",
    )
    headers = fx.officer(producer)
    glass = fx.glass_mini_sku(api, producer, name="Sparkling Water 750ml")
    bulk = fx.make_sku_with_components(
        api,
        producer,
        components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=100.00,
                recyclability_class="NOT_RECYCLABLE",
                pcr_content_pct=0,
            )
        ],
        activate=False,
        name="Bulk Case Pack",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=1000,
    )
    determined = fx.determine_obligation(api, producer)

    assert_weight(
        determined["annual_packaging_weight_kg"], 5.500, "annual_packaging_weight_kg"
    )
    assert_sku(
        validate_success(api.get_sku(bulk["id"], headers)),
        status=SkuStatus.DRAFT,
        unit_packaging_weight_grams=100.00,
    )

    revised = validate_success(
        api.revise_packaging(
            glass["id"],
            f.revise_packaging_payload(
                [
                    f.component_payload(
                        material_type="PLASTIC",
                        unit_weight_grams=20.00,
                        pcr_content_pct=40,
                    )
                ],
                reason="Lightweighted from glass to rPET",
            ),
            headers,
        )
    )

    assert_sku(revised, unit_packaging_weight_grams=20.00, revision_count=1)
    assert len(revised["components"]) == 2
    assert [c["status"] for c in revised["components"]].count("ACTIVE") == 1
    after = validate_success(api.get_producer(producer["id"], headers))
    assert_producer(
        after, status=ProducerStatus.OBLIGATION_DETERMINED, determination_stale=True
    )
    assert_weight(after["annual_packaging_weight_kg"], 2.200, "annual_packaging_weight_kg")


# ---------------------------------------------------------------------------
# The three eco-modulation constants, and the cap that sits between two of them
# ---------------------------------------------------------------------------
def test_the_eco_modulation_constants_price_one_reusable_recycled_component(api):
    """Malus twenty, recycled bonus twenty, reuse bonus fifteen, net minus fifteen.

    Limited recyclability attracts a twenty point surcharge; forty-seven percent
    recycled content buys four complete ten point steps and so twenty points of bonus,
    comfortably under the twenty-five point cap; reusability adds fifteen more. The
    ten kilograms of plastic therefore price at forty-two cents less fifteen percent.

    Design: Corner/calculations/eco_modulation_pcr_floor_step_cap_and_reuse_bonus_constants_applied
    """
    chain = fx.base_ca_chain(
        api,
        sku_components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=100.00,
                recyclability_class="LIMITED",
                pcr_content_pct=47,
                is_reusable=True,
            )
        ],
        sku_overrides=dict(
            name="Refill Pouch 1L",
            product_category="HOUSEHOLD_CHEM",
            units_sold_annual_estimate=100,
        ),
        schedule_overrides=dict(
            material_rates=[f.material_rate("PLASTIC", 0, None, 42)]
        ),
        line_units=100,
    )

    assessed = fx.assess_report(api, chain["pro"], chain["report"], FeeVariant.PROVISIONAL)

    assert_report(
        assessed,
        tier_basis_kg=0.000,
        fee_variant_applied=FeeVariant.PROVISIONAL,
        fee_status=ReportFeeStatus.PROVISIONAL,
        fee_subtotal_cents=357,
        fee_basis_weight_kg=10.000,
    )
    line = validate_success(
        api.get_report_line(chain["line"]["id"], chain["officer_headers"])
    )
    assert_report_line(line, line_weight_kg=10.000, fee_exempt=False, line_fee_cents=357)
    assert_exact_cents(line["line_fee_exact_cents"], 357.0000, "line_fee_exact_cents")
    assert len(line["eco_mod_detail"]) == 1
    row = line["eco_mod_detail"][0]
    assert_eco_mod_row(
        row,
        material_type="PLASTIC",
        comp_weight_kg=10.000,
        rate_cents_per_kg=42,
        net_pct=-15,
    )
    assert row["malus_pct"] == 20
    assert row["bonus_pct"] == 35
    assert_membership(
        validate_success(
            api.get_membership(chain["membership"]["id"], chain["admin_headers"])
        ),
        membership_fee_cents=250000,
    )


# ---------------------------------------------------------------------------
# The free tonnage allowance, and the thousandth of a kilogram beyond it
# ---------------------------------------------------------------------------
def _producer_at(api, program, kilograms_over, name, email_local):
    """A producer holding exactly 500.000 kg of glass plus an optional gram of paper."""
    components = [f.component_payload(material_type="GLASS", unit_weight_grams=50.00)]
    producer = fx.make_producer(
        api,
        legal_name=name,
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email=f"{email_local}@northlake.example",
    )
    fx.make_sku_with_components(
        api,
        producer,
        components=components,
        name="Sparkling Water 750ml",
        product_category="BEVERAGE",
        units_sold_annual_estimate=10000,
    )
    if kilograms_over:
        fx.make_sku_with_components(
            api,
            producer,
            components=[f.component_payload(material_type="PAPER", unit_weight_grams=1.00)],
            name="Neck Tag",
            product_category="BEVERAGE",
            units_sold_annual_estimate=1,
        )
    producer = fx.determine_obligation(api, producer)
    registration = fx.active_registration(api, producer, program["id"])
    return producer, registration


def test_the_membership_surcharge_starts_one_thousandth_past_the_free_tonnage(api):
    """Five hundred kilograms exactly is free; a gram more costs a whole unit.

    The surcharge count is the excess over the five hundred kilogram allowance divided
    by a thousand and rounded up, so a producer sitting exactly on the allowance owes
    the flat fee while one carrying a single extra gram owes one full five hundred
    dollar unit on top.

    Design: Corner/calculations/membership_fee_surcharge_ceil_boundary_at_exactly_the_free_tonnage
    """
    program = fx.make_breadth_program(api, state_code="CA")
    pro = fx.make_pro(api, name="Circular Stewardship Alliance", contact_email="ops@csa.example")
    schedule = fx.published_fee_schedule(api, pro, program["id"], membership_fee_cents=250000)
    assert schedule["version"] == 2

    on_the_line, reg_a = _producer_at(api, program, False, "Exactly Five Hundred LLC", "a")
    over_the_line, reg_b = _producer_at(api, program, True, "One Gram Over LLC", "b")
    assert_weight(
        on_the_line["annual_packaging_weight_kg"], 500.000, "annual_packaging_weight_kg"
    )
    assert_weight(
        over_the_line["annual_packaging_weight_kg"], 500.001, "annual_packaging_weight_kg"
    )
    application_a = fx.apply_for_membership(api, on_the_line, reg_a, pro, schedule)
    application_b = fx.apply_for_membership(api, over_the_line, reg_b, pro, schedule)

    approved_a = fx.approve_membership(api, pro, application_a)
    approved_b = fx.approve_membership(api, pro, application_b)

    assert_membership(
        approved_a,
        status=MembershipStatus.ACTIVE,
        membership_fee_cents=250000,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=2,
    )
    assert_membership(
        approved_b,
        status=MembershipStatus.ACTIVE,
        membership_fee_cents=300000,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=2,
    )
    for producer, registration in ((on_the_line, reg_a), (over_the_line, reg_b)):
        assert_registration(
            validate_success(
                api.get_registration(registration["id"], fx.officer(producer))
            ),
            compliance_posture=CompliancePosture.COMPLIANT,
        )


# ---------------------------------------------------------------------------
# The projection is priced twice and persists nothing either time
# ---------------------------------------------------------------------------
def test_the_redesign_projection_isolates_the_delta_and_writes_nothing(api):
    """A lighter recyclable candidate saves 458 cents and leaves the unit untouched.

    The baseline is a hundred units of unrecyclable plastic, ten kilograms priced at
    forty-two cents with a sixty percent surcharge; the candidate weighs six kilograms
    and earns a fifteen percent discount. The rate bands are read from a draft
    schedule, which the projection is free to model, and a second identical call that
    also names a unit count is answered field for field the same because the baseline
    basis ignores that count.

    Design: Corner/calculations/redesign_projection_writes_nothing_and_isolates_the_fee_delta
    """
    program = fx.make_breadth_program(api, state_code="CA")
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email="compliance@northlake.example",
    )
    headers = fx.officer(producer)
    sku = fx.make_sku_with_components(
        api,
        producer,
        components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=100.00,
                recyclability_class="NOT_RECYCLABLE",
                pcr_content_pct=0,
            )
        ],
        name="Cleaner Bottle 1L",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=100,
    )
    pro = fx.make_pro(api, name="Circular Stewardship Alliance", contact_email="ops@csa.example")
    draft_schedule = fx.make_fee_schedule(
        api,
        pro,
        program["id"],
        material_rates=[f.material_rate("PLASTIC", 0, None, 42)],
    )
    before = validate_success(api.get_sku(sku["id"], headers))
    candidate = [
        f.component_payload(
            material_type="PLASTIC",
            unit_weight_grams=60.00,
            recyclability_class="READILY_RECYCLABLE",
            pcr_content_pct=30,
        )
    ]

    first = validate_success(
        api.redesign_projection(
            sku["id"],
            f.redesign_projection_payload(
                program["id"], draft_schedule["id"], 0, "BASELINE_UNITS", candidate
            ),
            headers,
        )
    )
    second = validate_success(
        api.redesign_projection(
            sku["id"],
            f.redesign_projection_payload(
                program["id"],
                draft_schedule["id"],
                0,
                "BASELINE_UNITS",
                candidate,
                projected_units=999999,
            ),
            headers,
        )
    )

    assert first["projected_units"] == 100
    assert_weight(
        first["projected_unit_weight_grams"], 60.00, "projected_unit_weight_grams"
    )
    assert_weight(
        first["projected_line_weight_kg"], 6.000, "projected_line_weight_kg"
    )
    assert_cents(first["baseline_line_fee_cents"], 672, "baseline_line_fee_cents")
    assert_cents(first["projected_line_fee_cents"], 214, "projected_line_fee_cents")
    assert_cents(first["fee_delta_cents"], -458, "fee_delta_cents")
    assert second == first

    after = validate_success(api.get_sku(sku["id"], headers))
    assert_sku(
        after,
        version=before["version"],
        unit_packaging_weight_grams=100.00,
        revision_count=0,
    )
    assert [c["status"] for c in after["components"]].count("ACTIVE") == 1
    assert_weight(
        validate_success(api.get_producer(producer["id"], headers))[
            "annual_packaging_weight_kg"
        ],
        10.000,
        "annual_packaging_weight_kg",
    )


# ---------------------------------------------------------------------------
# Only four submission positions are inside the counted set
# ---------------------------------------------------------------------------
def test_a_draft_report_stays_outside_the_year_to_date_tonnage(api):
    """A second report holding the same tonnage in draft does not raise the total.

    The running total sums only reports that have been filed, so appending another
    5.500 kg line to a draft report for the following half leaves the registration at
    the 5.500 kg of the one submitted report while the draft report itself carries the
    full weight of its own line.

    Design: Corner/calculations/reported_weight_ytd_counts_only_the_declared_submission_statuses
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
    draft_report = fx.make_report(api, chain["producer"], chain["registration"], second_period)

    line = fx.add_line(api, chain["producer"], draft_report, chain["sku"], 110)

    assert_report_line(line, line_weight_kg=5.500)
    reread = validate_success(api.get_report(draft_report["id"], headers))
    assert_report(
        reread,
        submission_status=SubmissionStatus.DRAFT,
        fee_status=ReportFeeStatus.UNASSESSED,
        total_weight_kg=5.500,
        line_count=1,
    )
    filed = validate_success(api.get_report(chain["report"]["id"], headers))
    assert_report(
        filed, submission_status=SubmissionStatus.SUBMITTED, total_weight_kg=5.500
    )
    registration = validate_success(api.get_registration(chain["registration"]["id"], headers))
    assert_registration(registration, compliance_posture=CompliancePosture.COMPLIANT)
    assert_weight(
        registration["reported_weight_kg_ytd"], 5.500, "reported_weight_kg_ytd"
    )


# ---------------------------------------------------------------------------
# An overdue draft report bites at the next recompute, not before
# ---------------------------------------------------------------------------
def test_an_overdue_draft_report_turns_the_posture_delinquent_on_the_next_recompute(api):
    """Opening the overdue report changes nothing; the next membership rewrites it.

    A draft report for a period whose deadline has already passed is enough to make
    the posture delinquent, but only a write that recomputes the posture will say so —
    opening the report is not one. Electing fresh coverage is, and the same call
    supersedes the coverage the registration already had.

    Design: Corner/calculations/compliance_posture_becomes_delinquent_when_a_draft_report_is_past_deadline
    """
    chain = fx.base_ca_chain(api)
    headers, admin_headers = chain["officer_headers"], chain["admin_headers"]
    closed_period = fx.make_reporting_period(
        api,
        chain["program"]["id"],
        period_label="CA-2025-H2",
        data_start="2025-07-01",
        data_end="2026-01-01",
        submission_open="2025-07-01T00:00:00Z",
        submission_deadline="2026-01-31T23:59:59Z",
        correction_window_days=30,
    )
    overdue = fx.make_report(api, chain["producer"], chain["registration"], closed_period)
    assert_registration(
        validate_success(api.get_registration(chain["registration"]["id"], headers)),
        compliance_posture=CompliancePosture.COMPLIANT,
    )

    replacement = fx.apply_for_membership(
        api, chain["producer"], chain["registration"], chain["pro"], chain["schedule"]
    )

    assert_registration(
        validate_success(api.get_registration(chain["registration"]["id"], headers)),
        compliance_posture=CompliancePosture.DELINQUENT,
    )
    assert_report(
        validate_success(api.get_report(overdue["id"], headers)),
        submission_status=SubmissionStatus.DRAFT,
        line_count=0,
    )
    assert_membership(
        validate_success(api.get_membership(chain["membership"]["id"], admin_headers)),
        status=MembershipStatus.TERMINATED,
        decision_reason=DecisionReason.SUPERSEDED_BY_NEW_MEMBERSHIP,
    )
    assert_membership(
        replacement,
        status=MembershipStatus.PENDING,
        membership_fee_cents=0,
        fee_payment_status=FeePaymentStatus.OUTSTANDING,
        fee_schedule_version_pinned=None,
    )
