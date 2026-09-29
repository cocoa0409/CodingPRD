"""Dual-variant calculations: the settlement waterfall run as PROVISIONAL then
FINAL over the same appointment, and the continuing-education evaluation run as
CALENDAR_WINDOW then ROLLING_24M over the same records.
"""

from test_helpers import (
    assert_balance_equals_posting_sum,
    assert_canonical_final_row,
    assert_canonical_provisional_row,
    assert_ce_hours,
    assert_folio_contents,
    assert_list_count,
    assert_pool_conserved,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import (
    CANON_ACTUAL_DURATION_MINUTES,
    CANON_GRATUITY_CENTS,
    CANON_QUOTED_PRICE_CENTS,
    CANON_RETAIL_AMOUNT_CENTS,
    CANON_SETTLEMENT_ADJUSTMENT_CENTS,
    CANON_START_AT,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _settled_world():
    """Build the canonical appointment, check it in at 17:00, attach and purchase
    two 4595c retail lines, deliver 105 minutes with a 5000c gratuity, and return
    the world plus the appointment's current version."""
    world = fx.world_with_checked_in_appointment(
        arrival_clock=CANON_START_AT,
        treatment_type_overrides={
            "contraindication_codes": ["ACUTE_HYPERTENSION", "SHELLFISH_ALLERGY"]},
    )
    appointment_id = world.appointments["a"]["id"]
    therapist_headers = world.therapist_headers
    guest_headers = world.guest_headers
    for sku in ("MARINE-SERUM-30", "MARINE-BALM-50"):
        attachment = validate_success(api_client.create_retail_attachment(
            appointment_id,
            f.retail_attachment_payload(
                product_sku=sku, amount_cents=CANON_RETAIL_AMOUNT_CENTS),
            therapist_headers), 201)
        validate_success(api_client.resolve_retail_attachment(
            attachment["id"], f.resolve_payload("PURCHASED"), guest_headers))
    fx.start_service(appointment_id, world.therapist_id)
    world.appointments["a"] = fx.complete_service(
        appointment_id, world.therapist_id, CANON_ACTUAL_DURATION_MINUTES,
        CANON_GRATUITY_CENTS)
    appointment = validate_success(
        api_client.get_appointment(appointment_id, fx.DIRECTOR))
    return world, appointment


def test_settlement_provisional_and_final_variants_diverge_on_the_same_appointment():
    """The two variants of the waterfall disagree on every derived figure.

    PRD §3.9: "Under the provisional variant, `basis_duration_minutes` is the
    appointment's `scheduled_duration_minutes` and `realized_price_cents` is
    exactly the frozen `quoted_price_cents` — there is no overtime charge, no
    shortfall credit, and `gratuity_cents` on the row is 0 because a gratuity is
    only captured at completion."

    PRD §3.9: "When that tier basis is 50,000 cents or more, `service_charge_bp`
    is the reduced rate of 1,500 basis points; below that threshold it is the
    standard rate of 1,800 basis points."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
    """
    world, appointment = _settled_world()
    appointment_id = appointment["id"]

    final_row = validate_success(api_client.create_settlement(
        appointment_id, f.settlement_payload(appointment["version"]),
        fx.DIRECTOR), 201)
    assert_canonical_final_row(final_row)
    assert final_row["status"] == "FINALIZED", (
        f"a row cut at settlement time carries status FINALIZED, "
        f"got {final_row['status']}")
    assert_pool_conserved(final_row)

    rows = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 2,
        "settlement rows")
    assert [row["variant"] for row in rows] == ["PROVISIONAL", "FINAL"], (
        "an appointment's rows are returned with the provisional row first")
    assert_canonical_provisional_row(rows[0])
    assert_pool_conserved(rows[0])
    assert rows[0]["realized_price_cents"] == CANON_QUOTED_PRICE_CENTS
    assert rows[0]["retail_revenue_cents"] == 0, (
        "the provisional row was cut before either attachment was purchased")

    refreshed = validate_success(
        api_client.get_appointment(appointment_id, fx.DIRECTOR))
    assert refreshed["realized_price_cents"] == final_row["realized_price_cents"]


def test_final_settlement_supersedes_provisional_and_reconciles_the_folio():
    """Cutting the final row supersedes the provisional one and posts the
    difference between the final total and everything already charged.

    PRD §3.9: "It transitions the appointment's provisional row
    `PROVISIONAL → SUPERSEDED`."

    PRD §3.9: "It posts a folio charge of `kind` `SETTLEMENT_ADJUSTMENT` whose
    `amount_cents` is the final row's `folio_total_cents` less the sum of
    `amount_cents` over every folio posting already recorded against that
    appointment"

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
    """
    world, appointment = _settled_world()
    appointment_id = appointment["id"]

    final_row = validate_success(api_client.create_settlement(
        appointment_id, f.settlement_payload(appointment["version"]),
        fx.DIRECTOR), 201)

    rows = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 2,
        "settlement rows")
    provisional = rows[0]
    assert provisional["variant"] == "PROVISIONAL"
    assert provisional["status"] == "SUPERSEDED", (
        f"the provisional row becomes SUPERSEDED when a final row is cut, "
        f"got {provisional['status']}")
    assert provisional["folio_total_cents"] == 50504, (
        "its computed money fields freeze at the values they held")

    postings = assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR),
        4, "appointment folio postings")
    assert_folio_contents(postings, [
        ("TREATMENT", 50504),
        ("RETAIL", CANON_RETAIL_AMOUNT_CENTS),
        ("RETAIL", CANON_RETAIL_AMOUNT_CENTS),
        ("SETTLEMENT_ADJUSTMENT", CANON_SETTLEMENT_ADJUSTMENT_CENTS),
    ], "appointment folio")

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == final_row["folio_total_cents"], (
        f"the guest's folio balance must settle at the final row's folio total "
        f"{final_row['folio_total_cents']}, got {guest['folio_balance_cents']}")
    guest_postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR),
        4, "guest folio postings")
    assert_balance_equals_posting_sum(guest, guest_postings)


# ---------------------------------------------------------------------------
# Continuing-education dual variant
# ---------------------------------------------------------------------------

def _ce_license():
    """A PENDING_REVIEW licence carrying four CE records, with the logical clock
    parked at 2026-08-01 so the ROLLING_24M `as_of` default is that date."""
    fx.set_clock("2026-08-01T00:00:00.000Z",
                 fx.make_compliance_headers(fx.CO_SUBMIT))
    therapist = fx.create_therapist(
        full_name="Kai Mahelona", commission_tier="MASTER",
        base_hourly_cost_cents=6000)
    license_row = fx.submit_license(
        therapist["id"], submit_user=fx.CO_SUBMIT,
        license_number="HI-LMT-9002", issued_on="2022-01-01",
        expires_on="2026-09-30", current_period_start_on="2024-01-01",
        ce_hours_required=12)
    for course_code, category, hours, completed_on in (
            ("ETH-201", "ETHICS", 3.0, "2024-03-15"),
            ("CLI-310", "CLINICAL", 8.0, "2025-06-01"),
            ("CLI-410", "CLINICAL", 4.0, "2026-02-10"),
            ("SAF-120", "SAFETY", 2.0, "2026-07-20")):
        fx.add_ce_record(license_row["id"], course_code=course_code,
                         category=category, ce_hours=hours,
                         completed_on=completed_on)
    return license_row


def test_ce_calendar_window_credits_capped_category_totals():
    """The default variant spans the whole renewal period and caps each category.

    PRD §3.3: "`CALENDAR_WINDOW` is the default, and it is always the variant the
    review gate uses: its window runs from the licence's
    `current_period_start_on` to the licence's `expires_on` with **both** bounds
    inclusive, and it ignores the `as_of` input entirely."

    PRD §3.3: "the credited category figure is the smaller of that raw total and
    the per-category cap of 8 hours"

    Design: Difficulty/dual_variant_calc/ce_calendar_window_vs_rolling_24m_divergence
    """
    license_row = _ce_license()
    compliance = validate_success(api_client.get_ce_compliance(
        license_row["id"], fx.make_compliance_headers(fx.CO_REVIEW)))

    assert compliance["variant"] == "CALENDAR_WINDOW", (
        f"CALENDAR_WINDOW is the default variant, got {compliance['variant']}")
    assert compliance["window_start_on"] == "2024-01-01"
    assert compliance["window_end_on"] == "2026-09-30"
    assert_ce_hours(compliance["credited_hours"], "credited_hours")
    assert float(compliance["credited_hours"]) == 13.0, (
        "3.0 ETHICS + min(8.0 + 4.0, 8) CLINICAL + 2.0 SAFETY = 13.0, not 15.0")
    assert float(compliance["ethics_hours_credited"]) == 3.0
    assert float(compliance["ce_hours_required"]) == 12
    assert float(compliance["shortfall_hours"]) == 0
    assert compliance["ethics_requirement_met"] is True
    assert compliance["compliant"] is True


def test_ce_rolling_24m_drops_the_record_on_its_exclusive_lower_bound():
    """The rolling variant excludes the oldest ethics course and flips compliance.

    PRD §3.3: "`ROLLING_24M` is requested explicitly through the `variant` query
    parameter: its window opens strictly after the date 24 months before `as_of`
    — the lower bound is exclusive — and closes on `as_of` inclusive, where
    `as_of` defaults to the logical clock's UTC date."

    PRD §3.3: "Because the rolling window can exclude older courses that the
    calendar window credits, the same records can credit fewer hours under
    `ROLLING_24M`, drop a whole category below the ethics minimum, and flip
    `compliant` to false."

    Design: Difficulty/dual_variant_calc/ce_calendar_window_vs_rolling_24m_divergence
    """
    license_row = _ce_license()
    compliance = validate_success(api_client.get_ce_compliance(
        license_row["id"], fx.make_compliance_headers(fx.CO_REVIEW),
        params={"variant": "ROLLING_24M"}))

    assert compliance["variant"] == "ROLLING_24M"
    assert float(compliance["credited_hours"]) == 10.0, (
        "the ETHICS 3.0 record completed on 2024-03-15 sits on the exclusive "
        "lower bound 2024-08-01 and is dropped")
    assert float(compliance["ethics_hours_credited"]) == 0.0
    assert float(compliance["shortfall_hours"]) == 2.0
    assert compliance["ethics_requirement_met"] is False
    assert compliance["compliant"] is False


def test_review_gate_reads_calendar_window_even_when_rolling_24m_is_not_compliant():
    """The review gate is pinned to one variant, so the licence still verifies.

    PRD §3.3: "A licence that clears all three moves
    `PENDING_REVIEW → VERIFIED`, stamps `verified_at` with the logical clock,
    records `reviewed_by_user_id` and `review_note`, and writes
    `credited_ce_hours` with the credited hours figure that the calendar-window
    evaluation produced at that moment."

    PRD §2.7 rung 17: "**Continuing-education shortfall** — the calendar-window
    continuing-education evaluation reports a shortfall of zero hours for the
    licence under review."

    Design: Difficulty/dual_variant_calc/ce_calendar_window_vs_rolling_24m_divergence
    """
    license_row = _ce_license()
    reviewed = validate_success(api_client.review_license(
        license_row["id"], f.review_payload("VERIFIED"),
        fx.make_compliance_headers(fx.CO_REVIEW)))

    assert reviewed["verification_status"] == "VERIFIED", (
        f"the calendar-window evaluation reports no shortfall, so the review "
        f"succeeds; got {reviewed['verification_status']}")
    assert float(reviewed["credited_ce_hours"]) == 13.0, (
        "credited_ce_hours is written with the calendar-window figure")
    assert reviewed["reviewed_by_user_id"] == fx.CO_REVIEW
    assert reviewed["verified_at"] is not None
