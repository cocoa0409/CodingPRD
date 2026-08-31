"""Lead-disposal manifests: accumulation, the regulatory freeze and the unwind."""
import pytest

from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    create_warehouse, create_battery_model, receive_lot, create_disposal_manifest,
    scrap_lot, submit_disposal_manifest, reject_disposal_manifest, read_manifest,
    read_lot, read_core_return, read_account,
    setup_manifest_with_credited_return_and_scrapped_lot,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _submitted_manifest_and_a_second_expired_lot():
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-31-FLD")
    lot_seed = receive_lot(model["id"], warehouse["id"], manufactured_on="2024-01-01",
                           quantity_on_hand=4)
    lot_late = receive_lot(model["id"], warehouse["id"], manufactured_on="2024-01-01",
                           quantity_on_hand=4)
    manifest = create_disposal_manifest(warehouse["id"])
    scrap_lot(lot_seed["id"], manifest["id"])
    manifest = submit_disposal_manifest(manifest["id"])
    return {"warehouse": warehouse, "model": model, "lot_seed": lot_seed,
            "lot_late": lot_late, "manifest": manifest}


def test_scrapping_onto_a_submitted_manifest_is_refused(api):
    """PRD §3.9: "Once submitted, the manifest's attachments are frozen and any
    further attach or scrap against it is refused with `ERR_INVALID_STATE`."
    PRD §3.2: "Second: if the number of whole days from `manufactured_on` to the
    clock's current date is strictly greater than the model's `shelf_life_days`,
    the lot is `SHELF_EXPIRED` — the comparison is strict, so a lot whose age in
    days exactly equals its shelf life is still in service."

    Design: Difficulty/cross_entity_state_dependency/lot_scrap_requires_target_manifest_in_draft
    """
    ctx = _submitted_manifest_and_a_second_expired_lot()
    assert ctx["lot_seed"]["condition_state"] == "SHELF_EXPIRED"
    assert ctx["lot_late"]["condition_state"] == "SHELF_EXPIRED"
    assert ctx["manifest"]["status"] == "SUBMITTED"
    assert ctx["manifest"]["total_lead_kg"] == pytest.approx(50.000, abs=0.0005)

    resp = api.scrap_lot(ctx["lot_late"]["id"],
                         {"disposal_manifest_id": ctx["manifest"]["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_refused_scrap_leaves_both_the_lot_and_the_manifest_untouched(api):
    """PRD §3.2: "A successful scrap writes `scrap_manifest_id` onto the lot,
    which forces its `condition_state` to `SCRAPPED`, increments that manifest's
    `scrapped_lot_count` by 1, and re-derives the manifest's `lot_lead_kg` and
    `total_lead_kg`."
    PRD §3.2: "First: if `scrap_manifest_id` is non-null the lot is `SCRAPPED`,
    whatever else is true of it."

    Design: Difficulty/cross_entity_state_dependency/lot_scrap_requires_target_manifest_in_draft
    """
    ctx = _submitted_manifest_and_a_second_expired_lot()
    api.scrap_lot(ctx["lot_late"]["id"],
                  {"disposal_manifest_id": ctx["manifest"]["id"]}, COMPLIANCE)

    lot = read_lot(ctx["lot_late"]["id"])
    assert lot["scrap_manifest_id"] is None
    assert lot["condition_state"] == "SHELF_EXPIRED"

    manifest = read_manifest(ctx["manifest"]["id"])
    assert manifest["scrapped_lot_count"] == 1
    assert manifest["total_lead_kg"] == pytest.approx(50.000, abs=0.0005)


def test_manifest_accumulates_core_lead_and_lot_lead_before_the_freeze():
    """PRD §3.9: "The `core_lead_kg` is the sum of `lead_recovered_kg` over the
    core returns pointing at this manifest whose `status` is `CREDITED`, rounded
    half up to three decimals. The `lot_lead_kg` is the sum, over the inventory
    lots whose `scrap_manifest_id` is this manifest, of each lot's
    `quantity_on_hand` multiplied by its model's `lead_content_kg`, likewise
    rounded half up to three decimals. The `total_lead_kg` is the sum of those
    two already-rounded figures, rounded half up to three decimals again."

    Design: Difficulty/compensating_invariant/manifest_reject_conserves_global_recovered_lead_mass
    """
    env = setup_manifest_with_credited_return_and_scrapped_lot()
    assert env["core_return"]["lead_recovered_kg"] == pytest.approx(120.625, abs=0.0005)
    assert env["expired_lot"]["condition_state"] == "SHELF_EXPIRED"

    manifest = read_manifest(env["manifest"]["id"])
    assert manifest["core_lead_kg"] == pytest.approx(120.625, abs=0.0005)
    assert manifest["lot_lead_kg"] == pytest.approx(50.000, abs=0.0005)

    submitted = submit_disposal_manifest(manifest["id"])
    assert submitted["total_lead_kg"] == pytest.approx(170.625, abs=0.0005)


def test_rejecting_a_manifest_returns_every_kilogram_to_its_source():
    """PRD §3.9: "Rejecting it instead moves it `SUBMITTED → DRAFT`, records a
    free-text `rejection_reason`, and performs a full compensating unwind: every
    core return whose `disposal_manifest_id` is this manifest has that pointer
    cleared to null; every inventory lot whose `scrap_manifest_id` is this
    manifest has that pointer cleared to null, so each of those lots re-derives
    its `condition_state` out of `SCRAPPED` and back to whatever its age and
    charge now dictate; and the manifest's `attached_core_return_count`,
    `scrapped_lot_count`, `core_lead_kg`, `lot_lead_kg` and `total_lead_kg` are
    all reset to zero."

    Design: Difficulty/compensating_invariant/manifest_reject_conserves_global_recovered_lead_mass
    """
    env = setup_manifest_with_credited_return_and_scrapped_lot()
    submit_disposal_manifest(env["manifest"]["id"])

    rejected = reject_disposal_manifest(
        env["manifest"]["id"],
        "EPA generator identifier does not match the site permit on file.",
    )
    assert rejected["status"] == "DRAFT"
    assert rejected["total_lead_kg"] == pytest.approx(0.0, abs=0.0005)

    manifest = read_manifest(env["manifest"]["id"])
    assert manifest["core_lead_kg"] == pytest.approx(0.0, abs=0.0005)
    assert manifest["lot_lead_kg"] == pytest.approx(0.0, abs=0.0005)
    assert manifest["attached_core_return_count"] == 0
    assert manifest["scrapped_lot_count"] == 0

    core_return = read_core_return(env["core_return"]["id"])
    assert core_return["disposal_manifest_id"] is None
    assert core_return["lead_recovered_kg"] == pytest.approx(120.625, abs=0.0005), \
        "The assayed mass survives the detachment"

    lot = read_lot(env["expired_lot"]["id"])
    assert lot["scrap_manifest_id"] is None
    assert lot["condition_state"] == "SHELF_EXPIRED"
    assert read_account(env["account"]["id"])["lifetime_lead_recovered_kg"] == \
        pytest.approx(120.625, abs=0.0005)


def test_a_filed_manifest_refuses_any_further_transition(api):
    """PRD §3.9: "Filing it with the regulator moves it `SUBMITTED → FILED`,
    writes `filed_by_user_id` and `filed_at`, and renders the manifest immutable
    — `FILED` is terminal."
    PRD §3.9: "A compliance officer opens one by naming the generator
    `warehouse_id`, the `epa_id` printed on the paperwork and the
    `reporting_period` label such as a quarter designation. The opening
    officer's `X-User-ID` is recorded as `created_by_user_id`, every count and
    lead total starts at zero, and the manifest opens with `status` at
    `DRAFT`."

    Design: Corner/state_machines/filed_manifest_is_terminal_and_rejects_further_transitions
    """
    from test_helpers import file_disposal_manifest
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-31-FLD")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2024-01-01",
                      quantity_on_hand=4)
    manifest = create_disposal_manifest(warehouse["id"])
    assert manifest["created_by_user_id"] == "comp-1"
    assert manifest["status"] == "DRAFT"

    scrap_lot(lot["id"], manifest["id"])
    submit_disposal_manifest(manifest["id"])
    filed = file_disposal_manifest(manifest["id"])
    assert filed["status"] == "FILED"
    assert filed["filed_by_user_id"] == "comp-2"

    resp = api.reject_disposal_manifest(manifest["id"], {
        "rejection_reason": "Attempt to unwind an already filed manifest."
    }, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    stored = read_manifest(manifest["id"])
    assert stored["status"] == "FILED"
    assert stored["total_lead_kg"] == pytest.approx(50.000, abs=0.0005)

    scrapped = read_lot(lot["id"])
    assert scrapped["scrap_manifest_id"] == manifest["id"]
    assert scrapped["condition_state"] == "SCRAPPED"


def test_submitting_an_empty_manifest_is_refused(api):
    """PRD §3.9: "Submitting freezes a `DRAFT` manifest for regulatory review
    and moves it `DRAFT → SUBMITTED`. It requires substance: the sum of
    `attached_core_return_count` and `scrapped_lot_count` must be at least 1,
    and an empty manifest is refused with `ERR_MANIFEST_EMPTY` (HTTP 422)."

    Design: Corner/validations/manifest_submit_with_nothing_attached_returns_manifest_empty
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    manifest = create_disposal_manifest(warehouse["id"])

    resp = api.submit_disposal_manifest(manifest["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_MANIFEST_EMPTY.value)

    stored = read_manifest(manifest["id"])
    assert stored["status"] == "DRAFT"
    assert stored["attached_core_return_count"] == 0
    assert stored["scrapped_lot_count"] == 0
    assert stored["total_lead_kg"] == pytest.approx(0.0, abs=0.0005)


def test_a_scrap_breaching_the_regulatory_lead_cap_is_refused(api):
    """PRD §3.9: "One regulatory ceiling governs a manifest: its `total_lead_kg`
    may never exceed 1000.000 kilograms. That ceiling is enforced at three
    separate moments — when a core return is attached, when a lot is scrapped
    onto it, and when the manifest is submitted — and a breach at any of them is
    refused with `ERR_MANIFEST_LEAD_LIMIT_EXCEEDED` (HTTP 422)."
    PRD §3.9: "The `lot_lead_kg` is the sum, over the inventory lots whose
    `scrap_manifest_id` is this manifest, of each lot's `quantity_on_hand`
    multiplied by its model's `lead_content_kg`, likewise rounded half up to
    three decimals."

    Design: Corner/validations/scrap_pushing_manifest_over_the_epa_lead_cap_is_refused
    """
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    model = create_battery_model("IB-31-FLD")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2024-01-01",
                      quantity_on_hand=100)
    assert lot["condition_state"] == "SHELF_EXPIRED"
    manifest = create_disposal_manifest(warehouse["id"])

    resp = api.scrap_lot(lot["id"], {"disposal_manifest_id": manifest["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_MANIFEST_LEAD_LIMIT_EXCEEDED.value)

    stored_lot = read_lot(lot["id"])
    assert stored_lot["scrap_manifest_id"] is None
    assert stored_lot["condition_state"] == "SHELF_EXPIRED"
    stored = read_manifest(manifest["id"])
    assert stored["scrapped_lot_count"] == 0
    assert stored["total_lead_kg"] == pytest.approx(0.0, abs=0.0005)


def test_scrapping_a_reserved_lot_is_refused(api):
    """PRD §3.2: "Two further gates apply: the lot's `quantity_reserved` must be
    exactly 0, since units already committed to a customer cannot be destroyed,
    and a reserved lot is refused with `ERR_LOT_RESERVED` (HTTP 409); and the
    target manifest must itself be in `DRAFT`."
    PRD §3.2: "It is admissible only from `SHELF_EXPIRED` and from
    `REFRESH_REQUIRED`, and refused with `ERR_INVALID_STATE` (HTTP 409) from any
    other posture."

    Design: Corner/validations/scrap_of_a_reserved_lot_returns_lot_reserved
    """
    from test_helpers import (create_account, create_order, add_line, submit_order,
                              allocate_order, set_clock)
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-SLF-5")
    lot = receive_lot(model["id"], warehouse["id"], manufactured_on="2026-03-01",
                      quantity_on_hand=20)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    add_line(order["id"], model["id"], 5, core_expected_count=0)
    submit_order(order["id"])
    allocate_order(order["id"])
    manifest = create_disposal_manifest(warehouse["id"])

    set_clock("2027-09-01T00:00:00Z")
    aged = read_lot(lot["id"])
    assert aged["condition_state"] == "SHELF_EXPIRED"
    assert aged["quantity_reserved"] == 5

    resp = api.scrap_lot(lot["id"], {"disposal_manifest_id": manifest["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_LOT_RESERVED.value)

    assert read_lot(lot["id"])["scrap_manifest_id"] is None
    assert read_manifest(manifest["id"])["scrapped_lot_count"] == 0
