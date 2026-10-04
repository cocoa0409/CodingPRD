"""Boundary precision on the coverage extension band and the metering free window.

Difficulty queue A: boundary_precision_check.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_manual_order,
    dispatch_order,
    get_success_data,
    install_order,
    observe,
    set_clock,
    setup_system_with_units,
    validate_error,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: the 0.30 extension-band boundary, at and either side ────

def _ten_unit_system(code: str, failures: int, installs: int):
    """Commission ten units, fail the first `failures` of them, then install
    `installs` goodwill replacements inside the base window."""
    serials = [f"{code}-U{i}" for i in range(1, 11)]
    ctx = setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=serials, unit_models=["IQ8"] * 10,
        lot_code=f"LOT-{code}", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2025-09-15T00:00:00Z",
        site_address=f"11 {code} Way",
    )
    set_clock("2026-08-01T00:00:00Z")
    targets = []
    for index in range(failures):
        targets.append(observe(ctx["units"][index]["id"], 0.0, "2026-08-01T00:00:00Z"))
    installer_id = ctx["installer"]["id"]
    for index in range(installs):
        _consume_and_install(ctx, targets[index]["id"], installer_id,
                            f"{code}-R{index + 1}", f"2026-08-2{index}")
    set_clock("2026-09-01T00:00:00Z")
    return ctx


def _consume_and_install(ctx, unit_id, installer_id, serial, installed_day):
    unit = get_success_data(api_client.get_unit(unit_id, ADMIN))
    order = create_manual_order(unit["id"], unit["version"], model_code="IQ8")
    dispatch_order(order["id"])
    if serial is not None:
        install_order(order["id"], serial, f"{installed_day}T00:00:00Z", installer_id)
    return order


def test_three_installations_on_ten_units_select_the_partial_extension(api):
    """PRD §3.3: "Step two computes the system's `replacement_ratio`: the number of the
    system's replacement orders that reached `INSTALLED` at an instant at or before
    `base_warranty_end_at`, divided by the system's `unit_count`, carried to four
    decimal places with round-half-up." PRD §3.3: "a ratio of at least 0.30 but below
    0.50 earns sixty months".

    Design: Difficulty/boundary_precision_check/replacement_ratio_extension_band_at_zero_point_three
    """
    ctx = _ten_unit_system("BP1", failures=5, installs=3)
    coverage = get_success_data(api_client.get_system_coverage(ctx["system"]["id"], ADMIN))
    assert coverage["replacement_ratio"] == 0.3
    assert coverage["extension_months"] == 60, (
        "the comparison is inclusive at 0.30, so exactly a third earns the partial term"
    )
    assert coverage["base_warranty_end_at"] == "2050-09-15T00:00:00.000Z"
    assert coverage["extended_warranty_end_at"] == "2055-09-15T00:00:00.000Z"


def test_every_installed_replacement_consumes_one_of_the_five_positions(api):
    """PRD §3.3: "The `replacement_count` field counts the replacement orders in
    `INSTALLED` status that targeted the unit's position, and the
    `replacement_window_position` field tracks the unscheduled slots that remain on the
    unit's system — it starts at five and is decremented by one for every replacement
    installed anywhere on that system."

    Design: Difficulty/boundary_precision_check/replacement_ratio_extension_band_at_zero_point_three
    """
    ctx = _ten_unit_system("BP1B", failures=4, installs=3)
    for index in range(3):
        unit = get_success_data(api_client.get_unit(ctx["units"][index]["id"], ADMIN))
        assert unit["replacement_count"] == 1, "each install lands on its own position"
    untouched = get_success_data(api_client.get_unit(ctx["units"][9]["id"], ADMIN))
    assert untouched["replacement_window_position"] == 2, (
        "three installs anywhere on the system leave two of the five positions"
    )


# ─── Queue A: the inclusive age backstop at 144 months ────────────────

def _aged_system_at_forty_eight_months(code: str):
    """A system whose base term expired long ago and whose age band has decayed to the
    three-eighths band, so the extension is decided by the ratio band alone."""
    return setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=[f"{code}-U1"], unit_models=["IQ8"],
        lot_code=f"LOT-{code}", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2016-01-01T00:00:00Z",
        site_address=f"12 {code} Way",
    )


def test_system_with_no_replacements_earns_the_full_extension(api):
    """PRD §3.3: "Step three converts the ratio into an `extension_months` figure: a
    ratio of 0.50 or more earns no extension at all; a ratio of at least 0.30 but below
    0.50 earns sixty months; anything below 0.30 earns the full one hundred and twenty
    months."

    Design: Difficulty/boundary_precision_check/replacement_ratio_extension_band_at_zero_point_three
    """
    ctx = _aged_system_at_forty_eight_months("BP1C")
    set_clock("2026-09-01T00:00:00Z")
    coverage = get_success_data(api_client.get_system_coverage(ctx["system"]["id"], ADMIN))
    assert coverage["replacement_ratio"] == 0.0
    assert coverage["extension_months"] == 120
    assert coverage["base_warranty_end_at"] == "2041-01-01T00:00:00.000Z"
    assert coverage["extended_warranty_end_at"] == "2051-01-01T00:00:00.000Z"


# ─── Queue A: the metering free window closes at the sixtieth month ───

def test_fresh_system_inside_the_free_window_bills_nothing(api):
    """PRD §3.4: "The charge applies only to units whose `commissioning_state` is
    `COMMISSIONED`, and it is zero for a system whose `warranty_status` is not `ACTIVE`
    — an expired or transferred system bills nothing from the moment the status leaves
    `ACTIVE` — and zero for any system inside its first sixty months regardless of unit
    count."

    Design: Difficulty/boundary_precision_check/metering_free_months_empty_boundary_at_sixty
    """
    ctx = setup_system_with_units(
        installer_code="INST-BP2B", unit_serials=["BP2B-U1"], unit_models=["IQ8"],
        lot_code="LOT-BP2B", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-06-01T00:00:00Z",
        site_address="12b Oscar Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    summary = get_success_data(api_client.get_monitoring_summary(ctx["system"]["id"], ADMIN))
    assert summary["system_age_months"] == 3
    assert summary["active_units"] == 1
    assert summary["metering_fee_cents"] == 0, (
        "a system inside its free window bills zero even with a commissioned unit"
    )


def test_transferred_system_bills_nothing_for_metering(api):
    """PRD §3.4: "it is zero for a system whose `warranty_status` is not `ACTIVE` — an
    expired or transferred system bills nothing from the moment the status leaves
    `ACTIVE`".

    Design: Difficulty/boundary_precision_check/metering_free_months_empty_boundary_at_sixty
    """
    ctx = setup_system_with_units(
        installer_code="INST-BP2C", unit_serials=["BP2C-U1"], unit_models=["IQ8"],
        lot_code="LOT-BP2C", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2021-09-01T00:00:00Z",
        site_address="12c Oscar Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    billable = get_success_data(api_client.get_monitoring_summary(ctx["system"]["id"], ADMIN))
    assert billable["system_age_months"] == 60
    assert billable["metering_fee_cents"] == 0, (
        "the free-window test is inclusive at sixty months"
    )
    assert billable["active_units"] == 1, (
        "the zero comes from the threshold, not from an empty unit set"
    )
    from test_helpers import create_transfer, approve_transfer
    transfer = create_transfer(ctx["system"]["id"], effective_date="2026-08-15T00:00:00Z")
    approve_transfer(transfer["id"])
    transferred = get_success_data(api_client.get_monitoring_summary(ctx["system"]["id"], ADMIN))
    assert transferred["metering_fee_cents"] == 0
    assert transferred["warranty_status"] == "TRANSFERRED"


def test_system_one_month_past_the_free_window_bills_per_unit(api):
    """PRD §3.4: "The per-unit rate begins at two hundred and fifty cents per month and
    is multiplied by the same age factor table used for labor".

    Design: Difficulty/boundary_precision_check/metering_free_months_empty_boundary_at_sixty
    """
    ctx = setup_system_with_units(
        installer_code="INST-BP2D", unit_serials=["BP2D-U1"], unit_models=["IQ8"],
        lot_code="LOT-BP2D", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2021-08-01T00:00:00Z",
        site_address="12d Oscar Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    summary = get_success_data(api_client.get_monitoring_summary(ctx["system"]["id"], ADMIN))
    assert summary["system_age_months"] == 61
    assert summary["metering_fee_cents"] == 188, (
        "one unit at the three-quarters age factor costs 188 cents a month"
    )


# ─── Queue B: an unreached sentinel, kept as documentation only ───────

def test_unknown_claim_read_is_not_found(api):
    """PRD §2.5: "the first identifier in the path that resolves to nothing produces
    `ERR_RESOURCE_NOT_FOUND` for the whole request".

    Design: Corner/endpoints/unknown_claim_id_returns_not_found
    """
    set_clock()
    resp = api_client.get_claim("00000000-0000-0000-0000-000000000002", ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)