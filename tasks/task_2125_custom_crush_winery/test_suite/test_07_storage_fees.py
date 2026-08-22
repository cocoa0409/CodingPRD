"""Storage fees: the two readings of the projection and the posted accrual."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    house_lot,
    new_vessel,
    read_contract_version,
    setup_contract_with_lot,
    setup_housed_aging_lot,
    validate_success,
)


def _press_only_scenario():
    """A 3135.00-gallon lot committed into a 4000-gallon allocation and stopped
    at PRESSED, so its aging_start_at is still null."""
    scenario = setup_contract_with_lot(delivery_ticket="DT-F1")
    vessel = new_vessel()
    scenario["vessel"] = vessel
    scenario["allocation"] = house_lot(
        scenario["contract"]["id"], vessel["id"], scenario["lot"]["id"], 4000
    )
    validate_success(
        api_client.lot_transition(
            scenario["lot"]["id"],
            {"action": "START_FERMENTATION"},
            TEST_USERS["cellar_supervisor_headers"],
        )
    )
    scenario["lot"] = validate_success(
        api_client.lot_transition(
            scenario["lot"]["id"],
            {"action": "PRESS", "loss_gallons": 0},
            TEST_USERS["cellar_supervisor_headers"],
        )
    )
    return scenario


def test_the_two_readings_draw_on_different_subject_sets(api, facility_admin_headers):
    """PRD 3.6: "The **`OCCUPANCY`** reading bills the wine actually held: its
    subjects are the contract's lots whose `bond_status` is `IN_BOND` or
    `TAX_DETERMINED`, whose `production_status` is not `CONSUMED`, and whose
    `aging_start_at` is not null, and each such lot's clock starts at its own
    `aging_start_at`."
    PRD 3.6: "The **`VESSEL_FOOTPRINT`** reading bills the cooperage tied up
    instead: its subjects are the contract's allocations standing in
    `COMMITTED` or `RELEASED` with a non-null `committed_at`, each clocking from
    its own `committed_at`, and each charged its `allocated_gallons` multiplied
    by the same monthly rate multiplied by the day count and divided by thirty,
    again rounded half up per allocation and then summed."

    Design: Corner/calculations/corner_storage_accrual_input_set_excludes_lot_without_aging_start
    """
    scenario = _press_only_scenario()
    assert scenario["lot"]["production_status"] == "PRESSED"
    assert scenario["lot"]["alcohol_pct"] == pytest.approx(12.93, abs=0.01), (
        "pressing fixes alcohol_pct at brix_at_crush multiplied by 0.55"
    )
    assert scenario["lot"]["aging_start_at"] is None

    occupancy = validate_success(
        api.get_storage_accrual(
            scenario["contract"]["id"],
            facility_admin_headers,
            params={"through_at": "2026-12-01T00:00:00Z"},
        )
    )
    assert occupancy["subject_count"] == 0, (
        "a lot that never started aging is not an OCCUPANCY subject"
    )
    assert occupancy["charge_cents"] == 0

    footprint = validate_success(
        api.get_storage_accrual(
            scenario["contract"]["id"],
            facility_admin_headers,
            params={
                "through_at": "2026-12-01T00:00:00Z",
                "variant": "VESSEL_FOOTPRINT",
            },
        )
    )
    assert footprint["subject_count"] == 1, (
        "the COMMITTED allocation is still a VESSEL_FOOTPRINT subject"
    )
    assert footprint["charge_cents"] == 303333, (
        f"4000 gallons x 25 cents x 91 days / 30, got {footprint['charge_cents']}"
    )


def test_posting_an_accrual_advances_the_watermark_so_a_repost_bills_nothing(
    api, facility_admin_headers
):
    """PRD 3.6: "A successful posting adds that reading's `charge_cents` to the
    contract's `billed_total_cents`, advances `storage_billed_through` to the
    supplied `through_at` so the next accrual cannot double-bill the same days,
    and increments the contract's `version` by 1."
    PRD 3.6: "Every subject's billing window opens at the later of that
    subject's own clock start and the contract's `storage_billed_through`
    watermark when it is set, or the contract's `effective_from` when it is not;
    the window closes at `through_at`."

    Design: Corner/calculations/corner_storage_accrual_post_advances_watermark_and_reposts_zero
    """
    scenario = setup_housed_aging_lot(delivery_ticket="DT-G1")
    contract_id = scenario["contract"]["id"]

    posted = validate_success(
        api.post_storage_accrual(
            contract_id,
            {
                "through_at": "2026-12-01T00:00:00Z",
                "expected_contract_version": read_contract_version(contract_id),
            },
            facility_admin_headers,
        )
    )
    assert posted["billed_total_cents"] == 1187738, (
        f"950000 crush plus 237738 storage, got {posted['billed_total_cents']}"
    )
    assert posted["storage_billed_through"] == "2026-12-01T00:00:00.000Z"

    reprojected = validate_success(
        api.get_storage_accrual(
            contract_id,
            facility_admin_headers,
            params={"through_at": "2026-12-01T00:00:00Z"},
        )
    )
    assert reprojected["charge_cents"] == 0, (
        "the window now clips below at the watermark, giving zero whole days"
    )

    reposted = validate_success(
        api.post_storage_accrual(
            contract_id,
            {
                "through_at": "2026-12-01T00:00:00Z",
                "expected_contract_version": posted["version"],
            },
            facility_admin_headers,
        )
    )
    assert reposted["billed_total_cents"] == 1187738, (
        "re-posting the same window must double-bill nothing"
    )


# ── OCCUPANCY against VESSEL_FOOTPRINT on identical stored data ──────


def _setup_lot_aging_in_an_oversized_tank():
    """A 3135.00-gallon lot aging from 2026-09-01 inside a 4000-gallon
    allocation, so the two storage readings diverge."""
    return setup_housed_aging_lot(delivery_ticket="DT-1001")


def test_occupancy_is_the_default_reading_and_bills_the_wine_held(
    api, facility_admin_headers
):
    """PRD 3.6: "Each lot is charged its `volume_gallons` multiplied by the
    contract's `storage_rate_cents_per_gallon_month` multiplied by the day count
    and divided by the thirty days the rate is quoted against, rounded half up
    to whole cents per lot, and the per-lot charges are summed after rounding."
    PRD 3.6: "`OCCUPANCY` is the default reading: the projection uses it
    whenever the `variant` query parameter is absent or names it, and
    `VESSEL_FOOTPRINT` is only ever produced when explicitly requested."

    Design: Difficulty/dual_variant_calc/storage_accrual_occupancy_versus_vessel_footprint
    """
    scenario = _setup_lot_aging_in_an_oversized_tank()

    data = validate_success(
        api.get_storage_accrual(
            scenario["contract"]["id"],
            facility_admin_headers,
            params={"through_at": "2026-12-01T00:00:00Z"},
        )
    )

    assert data["variant"] == "OCCUPANCY", (
        f"an omitted variant must answer OCCUPANCY, got {data['variant']}"
    )
    assert data["contract_id"] == scenario["contract"]["id"]
    assert data["through_at"] == "2026-12-01T00:00:00.000Z"
    assert data["charge_cents"] == 237738, (
        f"3135.00 gallons x 25 cents x 91 days / 30 rounds 237737.5 half up to "
        f"237738; got {data['charge_cents']}"
    )


def test_vessel_footprint_bills_the_cooperage_and_returns_the_larger_figure(
    api, facility_admin_headers
):
    """PRD 3.6: "The **`VESSEL_FOOTPRINT`** reading bills the cooperage tied up
    instead: its subjects are the contract's allocations standing in
    `COMMITTED` or `RELEASED` with a non-null `committed_at`, each clocking from
    its own `committed_at`, and each charged its `allocated_gallons` multiplied
    by the same monthly rate multiplied by the day count and divided by thirty,
    again rounded half up per allocation and then summed."
    PRD 3.6: "Whenever a lot under-fills its vessel the two readings diverge,
    and `VESSEL_FOOTPRINT` returns the strictly larger figure."

    Design: Difficulty/dual_variant_calc/storage_accrual_occupancy_versus_vessel_footprint
    """
    scenario = _setup_lot_aging_in_an_oversized_tank()
    contract_id = scenario["contract"]["id"]

    occupancy = validate_success(
        api.get_storage_accrual(
            contract_id,
            facility_admin_headers,
            params={"through_at": "2026-12-01T00:00:00Z"},
        )
    )
    footprint = validate_success(
        api.get_storage_accrual(
            contract_id,
            facility_admin_headers,
            params={
                "through_at": "2026-12-01T00:00:00Z",
                "variant": "VESSEL_FOOTPRINT",
            },
        )
    )

    assert footprint["variant"] == "VESSEL_FOOTPRINT"
    assert footprint["charge_cents"] == 303333, (
        f"4000 allocated gallons x 25 cents x 91 days / 30, got "
        f"{footprint['charge_cents']}"
    )
    assert footprint["charge_cents"] - occupancy["charge_cents"] == 65595, (
        "the two readings differ by 65595 cents on byte-identical stored data"
    )
    assert footprint["charge_cents"] > occupancy["charge_cents"]


def test_the_storage_projection_posts_nothing_to_the_ledger(api, facility_admin_headers):
    """PRD 3.6: "A read-only projection answers, for a contract and a
    `through_at` instant, how much storage would be charged; it returns the
    `contract_id`, the `variant` used, the `through_at` echoed back, a
    `subject_count` naming how many subjects the reading found, and the
    `charge_cents` those subjects generate. The projection posts nothing."

    Design: Difficulty/dual_variant_calc/storage_accrual_occupancy_versus_vessel_footprint
    """
    scenario = _setup_lot_aging_in_an_oversized_tank()
    contract_id = scenario["contract"]["id"]

    validate_success(
        api.get_storage_accrual(
            contract_id, facility_admin_headers,
            params={"through_at": "2026-12-01T00:00:00Z"},
        )
    )
    validate_success(
        api.get_storage_accrual(
            contract_id, facility_admin_headers,
            params={"through_at": "2026-12-01T00:00:00Z", "variant": "VESSEL_FOOTPRINT"},
        )
    )

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["billed_total_cents"] == 950000, (
        f"only the crush fee has posted, got {contract['billed_total_cents']}"
    )
    assert contract["storage_billed_through"] is None, (
        "a projection must not advance the storage watermark"
    )
