"""Depth tests: device valuation dual-variant (FIFO vs WEIGHTED_AVERAGE)."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_affiliate_with_tiers_abcd, create_catalog_entry, create_provider,
    create_license, create_stock_lot, create_patient, create_assessment,
    create_encounter, create_device_reservation, create_grant_report_payload,
    set_clock, get_patient,
)

CLINICIAN = None  # resolved via TEST_USERS inside helpers


def _setup_three_fulfilled_larc_units(api):
    """Two units fulfilled from a 20000-cent lot, one from a 30000-cent lot.

    Returns (affiliate, lot1, lot2) with all three encounters COMPLETED inside
    [2026-09-01, 2026-10-01) and the logical clock advanced past the period.
    """
    from test_helpers import TEST_USERS
    clinician = TEST_USERS["clinician_headers"]

    set_clock("2026-09-01T00:00:00Z")
    aff, _tiers = create_affiliate_with_tiers_abcd(quota=50)
    create_catalog_entry(aff["id"], service_code="LARC_INSERTION",
                         in_scope=True, telehealth_eligible=False,
                         full_fee_cents=50000)
    provider = create_provider(aff["id"], display_name="Dr. Reyes",
                               provider_type="PHYSICIAN")
    create_license(provider["id"], state_code="TX",
                   valid_from="2026-01-01T00:00:00Z",
                   valid_until="2027-01-01T00:00:00Z")
    lot1 = create_stock_lot(aff["id"], device_code="IUD_HORMONAL",
                            lot_number="LOT-1", unit_cost_cents=20000,
                            on_hand=5, expires_on="2027-01-01")
    lot2 = create_stock_lot(aff["id"], device_code="IUD_HORMONAL",
                            lot_number="LOT-2", unit_cost_cents=30000,
                            on_hand=5, expires_on="2027-01-01")

    plan = [
        ("D1", "2026-09-10T09:00:00Z", "2026-09-10T09:30:00Z", lot1),
        ("D2", "2026-09-10T10:00:00Z", "2026-09-10T10:30:00Z", lot1),
        ("D3", "2026-09-10T11:00:00Z", "2026-09-10T11:30:00Z", lot2),
    ]
    encounter_ids = []
    for ext_ref, start, end, lot in plan:
        patient = create_patient(aff["id"], external_ref=ext_ref,
                                 date_of_birth="1988-01-01")
        create_assessment(patient, household_size=1,
                          annual_income_cents=4000000,
                          income_basis="DOCUMENTED")
        enc = create_encounter(patient["id"], provider["id"],
                               service_code="LARC_INSERTION",
                               scheduled_start=start, scheduled_end=end)
        create_device_reservation(enc["id"], lot["id"])
        encounter_ids.append(enc["id"])

    set_clock("2026-09-10T12:00:00Z")
    for enc_id in encounter_ids:
        get_success_data(api_client.start_encounter(enc_id, clinician))
        get_success_data(api_client.complete_encounter(enc_id, clinician))
    set_clock("2026-10-02T00:00:00Z")
    return aff, lot1, lot2


def test_fifo_variant_values_units_at_own_lot_costs(api):
    """PRD §3.10: "Under `FIFO`, fulfilled units are valued in order of each
    unit's lot `created_at` ascending and then the reservation's `created_at`
    ascending, with each unit valued at its own lot's `unit_cost_cents`."

    Two units from a 20000-cent lot and one from a 30000-cent lot value to
    70000 cents under FIFO.

    Design: Difficulty/dual_variant_calc/device_valuation_fifo_vs_weighted_average
    """
    aff, _lot1, _lot2 = _setup_three_fulfilled_larc_units(api)
    payload = create_grant_report_payload(
        aff["version"], period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z", valuation_variant="FIFO",
    )
    report = validate_success(
        api_client.create_grant_report(aff["id"], payload,
                                       _admin_headers()), 201
    )
    assert report["device_value_cents"] == 70000, (
        f"FIFO values 20000 + 20000 + 30000 = 70000, got "
        f"{report['device_value_cents']}"
    )
    assert report["encounter_count"] == 3


def test_weighted_average_variant_floors_per_device_code_mean(api):
    """PRD §3.10: "Under `WEIGHTED_AVERAGE`, the server computes a
    per-`device_code` average cost as the floor of (sum of `unit_cost_cents`
    multiplied by units fulfilled from each lot) divided by (total units
    fulfilled of that device code), then multiplies that average by the units
    of that code and sums across codes."
    PRD §3.10: "The two variants produce different `device_value_cents`
    whenever lots of the same `device_code` carry different `unit_cost_cents`".

    floor(70000 / 3) = 23333 per unit x 3 units = 69999 — one cent below the
    FIFO value over the identical fulfilled-unit set.

    Design: Difficulty/dual_variant_calc/device_valuation_fifo_vs_weighted_average
    """
    aff, _lot1, _lot2 = _setup_three_fulfilled_larc_units(api)
    payload = create_grant_report_payload(
        aff["version"], period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z", valuation_variant="WEIGHTED_AVERAGE",
    )
    report = validate_success(
        api_client.create_grant_report(aff["id"], payload,
                                       _admin_headers()), 201
    )
    assert report["device_value_cents"] == 69999, (
        f"WEIGHTED_AVERAGE floors the mean: expected 69999, got "
        f"{report['device_value_cents']}"
    )
    assert report["device_value_cents"] != 70000, (
        "the two variants must diverge whenever lots of the same device_code "
        "carry different unit_cost_cents"
    )
    assert report["encounter_count"] == 3


def _admin_headers():
    from test_helpers import TEST_USERS
    return TEST_USERS["grant_admin_headers"]
