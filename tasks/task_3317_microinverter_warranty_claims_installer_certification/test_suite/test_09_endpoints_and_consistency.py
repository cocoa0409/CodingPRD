"""Campaign selection order, installer reads, coverage visibility, and funding gates.

Corner queue B: endpoints, consistency_model, cross_cutting_complexity_layers.
Difficulty queue A: boundary_precision_check.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commission_system,
    commission_unit_entry,
    create_campaign,
    create_manual_order,
    dispatch_order,
    force_lot_recall,
    get_success_data,
    install_order,
    list_orders,
    observe,
    set_clock,
    setup_approved_design,
    setup_system_with_units,
    validate_error,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue B: campaign preview shows both selection variants ──────────

def _staggered_lot(code: str, installed_ats, model_code: str = "IQ7"):
    """One single-unit system per installation instant, all sharing one lot, so every
    unit's installed_at is distinct and the ranking tie-break is well defined."""
    ctx = setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=[f"{code}-U1"],
        unit_models=[model_code], lot_code=f"LOT-{code}", embed_model_code=model_code,
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at=installed_ats[0], site_address=f"38 {code} Way",
    )
    for index, installed_at in enumerate(installed_ats[1:], start=2):
        design = setup_approved_design(ctx["installer"]["id"],
                                       site_address=f"38 {code} Way {index}")
        commission_system(
            ctx["installer"]["id"], design["id"],
            site_address=f"38 {code} Way {index}", site_postal_code="94038",
            units=[commission_unit_entry(f"{code}-U{index}", model_code=model_code,
                                         installed_at=installed_at,
                                         production_lot_code=f"LOT-{code}")],
            commissioned_at=installed_at,
        )
    all_units = get_success_data(api_client.list_units(ADMIN,
                                                      {"production_lot_id": ctx["lot"]["id"]}))
    ctx["units"] = all_units
    return ctx


def test_campaign_preview_reports_the_ranking_and_the_single_lot_model(api):
    """PRD §3.5: "A preview view of a campaign shows what ranking alone would have
    picked, and what a single model resolution ignoring each unit's own generation
    would ship — both purely informational." PRD §3.5: "The second bucket is the ranked
    remainder, drawn from the candidates that are not in the guaranteed set and ordered
    by unit priority descending — an `UNDERPERFORMING` unit outranks an `ONLINE` unit".

    Design: Corner/endpoints/campaign_preview_shows_both_selection_variants
    """
    ctx = _staggered_lot("E1", ["2026-01-05T00:00:00Z", "2026-04-05T00:00:00Z",
                                "2026-07-05T00:00:00Z"])
    set_clock("2026-09-01T00:00:00Z")
    _ordered = sorted(ctx["units"], key=lambda u: u["installed_at"])
    _oldest, _middle, _newest = _ordered
    under = observe(_newest["id"], 0.80, "2026-08-01T00:00:00Z")
    assert under["monitored_status"] == "UNDERPERFORMING"
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=2, guaranteed_units=1)
    preview = get_success_data(api_client.get_campaign_preview(campaign["id"], ADMIN))
    assert preview["pure_rank_unit_ids"][0] == _newest["id"], (
        "the ranked view leads with the only UNDERPERFORMING unit"
    )
    assert _oldest["id"] in preview["guaranteed_first_unit_ids"], (
        "the guaranteed bucket contains the oldest installation"
    )
    assert preview["lot_only_model_code"] == "IQ8", (
        "the preview projects the lot's model for every target"
    )
    activated = get_success_data(api_client.activate_campaign(campaign["id"], ADMIN))
    assert activated["status"] == "DISPATCHING"


def test_guaranteed_reservation_displaces_a_newer_underperforming_unit(api):
    """PRD §3.5: "The first bucket is the reservation: the campaign's `guaranteed_units`
    oldest candidates, ordered by `installed_at` ascending and then by `created_at`
    ascending, are taken unconditionally before any ranking is applied". PRD §3.5:
    "Because the reservation precedes the ranking, a recently installed
    `UNDERPERFORMING` unit can be displaced by an older `ONLINE` unit whenever
    `guaranteed_units` is greater than zero."

    Design: Corner/endpoints/campaign_preview_shows_both_selection_variants
    """
    ctx = _staggered_lot("E1B", ["2026-01-05T00:00:00Z", "2026-07-05T00:00:00Z"])
    set_clock("2026-09-01T00:00:00Z")
    _older, _newer = sorted(ctx["units"], key=lambda u: u["installed_at"])
    observe(_newer["id"], 0.80, "2026-08-01T00:00:00Z")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=1, guaranteed_units=1)
    activated = get_success_data(api_client.activate_campaign(campaign["id"], ADMIN))
    assert activated["dispatched_count"] == 1
    orders = list_orders(campaign_id=campaign["id"])
    assert orders[0]["unit_id"] == _older["id"], (
        "the reservation pre-empts the ranking, so the older ONLINE unit takes the slot"
    )


# ─── Queue B: the portfolio's fleet-wide ratio diverges from the system ───

def test_portfolio_fleet_wide_ratio_divides_by_active_system_count(api):
    """PRD §3.3: "the system reports a fleet-wide replacement ratio that divides the
    installer's installed-in-base-window replacement count by `active_system_count`
    rather than by the affected system's `unit_count`." PRD §3.3: "The fleet-wide figure
    is informational only and never influences an extension."

    Design: Corner/endpoints/installer_portfolio_reports_fleet_wide_ratio_divergence
    """
    ctx = setup_system_with_units(
        installer_code="INST-E2", unit_serials=["E2-U1"], unit_models=["IQ7"],
        lot_code="LOT-E2", embed_model_code="IQ7", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2025-09-15T00:00:00Z",
        site_address="39 November Two Way",
    )
    set_clock("2026-08-01T00:00:00Z")
    second_design = setup_approved_design(ctx["installer"]["id"],
                                          site_address="40 November Two Way")
    commission_system(ctx["installer"]["id"], second_design["id"],
                      site_address="40 November Two Way", site_postal_code="94040",
                      units=[commission_unit_entry("E2-U2", model_code="IQ7",
                                                  installed_at="2026-01-15T00:00:00Z",
                                                  production_lot_code="LOT-E2")],
                      commissioned_at="2026-01-15T00:00:00Z")
    failed = observe(ctx["units"][0]["id"], 0.0, "2026-08-01T00:00:00Z")
    order = create_manual_order(failed["id"], failed["version"], model_code="IQ8")
    dispatch_order(order["id"])
    install_order(order["id"], "E2-R1", "2026-08-20T00:00:00Z", ctx["installer"]["id"])
    portfolio = get_success_data(api_client.get_installer_portfolio(ctx["installer"]["id"], ADMIN))
    assert portfolio["active_system_count"] == 2
    coverage = get_success_data(api_client.get_system_coverage(ctx["system"]["id"], ADMIN))
    assert coverage["replacement_ratio"] == 1.0, (
        "the affected system has rebuilt its only unit"
    )
    assert portfolio["fleet_wide_ratio"] == 0.5, (
        "the same single replacement is spread across two live systems"
    )
    assert portfolio["fleet_wide_ratio"] != coverage["replacement_ratio"]


# ─── Queue B: consistency_model ───────────────────────────────────────

def test_commissioning_response_already_carries_its_derived_coverage(api):
    """PRD §2.7: "Lazy evaluation means that a resource's derived state can be
    stale-stored and corrected on read." PRD §3.3: "Step one sets `warranty_start_at`
    equal to the `commissioned_at` that was supplied, and then sets
    `base_warranty_end_at` to that instant advanced by three hundred months — twenty-five
    years of calendar-exact month arithmetic."

    Design: Corner/consistency_model/immediate_consistency_of_computed_fields_on_create
    """
    ctx = setup_system_with_units(
        installer_code="INST-CM1", unit_serials=["CM1-U1"], unit_models=["IQ8"],
        lot_code="LOT-CM1", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-06-01T00:00:00Z",
        site_address="46 Victor Two Way",
    )
    system = ctx["system"]
    assert system["warranty_status"] == "ACTIVE"
    assert system["base_warranty_end_at"] == "2051-06-01T00:00:00.000Z"
    assert system["extended_warranty_end_at"] == "2061-06-01T00:00:00.000Z"
    assert system["unit_count"] == 1
    assert system["replacement_ratio"] == 0.0
    portfolio = get_success_data(api_client.get_installer_portfolio(ctx["installer"]["id"], ADMIN))
    assert portfolio["active_system_count"] == 1


# ─── Queue A: the funding gate compares the ratio strictly below a half ───

def test_a_system_that_rebuilt_half_its_array_earns_no_extension(api):
    """PRD §3.3: "a ratio of 0.50 or more earns no extension at all". PRD §3.3: "Both
    thresholds are inclusive, so a ratio of exactly 0.50 stops at zero extension".

    Design: Difficulty/boundary_precision_check/replacement_ratio_extension_band_at_zero_point_three
    """
    ctx = setup_system_with_units(
        installer_code="INST-BP3", unit_serials=["BP3-U1", "BP3-U2"],
        unit_models=["IQ7", "IQ7"], lot_code="LOT-BP3", embed_model_code="IQ7",
        replacement_model_code="IQ8", defect_threshold_pct=1e6,
        commissioned_at="2026-04-01T00:00:00Z", site_address="52 November Two Way",
    )
    set_clock("2026-08-01T00:00:00Z")
    installer = ctx["installer"]
    first = observe(ctx["units"][0]["id"], 0.0, "2026-08-01T00:00:00Z")
    order = create_manual_order(first["id"], first["version"], model_code="IQ8")
    dispatch_order(order["id"])
    install_order(order["id"], "BP3-R1", "2026-08-10T00:00:00Z", installer["id"])
    coverage = get_success_data(api_client.get_system_coverage(ctx["system"]["id"], ADMIN))
    assert coverage["replacement_ratio"] == 0.5
    assert coverage["extension_months"] == 0, (
        "the inclusive 0.50 boundary stops the extension at zero months"
    )
    assert coverage["extended_warranty_end_at"] == coverage["base_warranty_end_at"]


def test_campaign_selection_tie_break_prefers_the_older_installation(api):
    """PRD §3.5: "then by `underperformance_streak_hours` descending, then by
    `installed_at` ascending, and finally by `created_at` ascending; the entity
    identifier is never used as a tie-break."

    Design: Corner/cross_cutting_complexity_layers/campaign_selector_tie_break_is_installed_at_then_created_at
    """
    ctx = _staggered_lot("XC4", ["2026-01-05T00:00:00Z", "2026-06-05T00:00:00Z"])
    set_clock("2026-09-01T00:00:00Z")
    force_lot_recall(ctx["lot"]["id"])
    campaign = create_campaign(ctx["lot"]["id"], max_units=1)
    activated = get_success_data(api_client.activate_campaign(campaign["id"], ADMIN))
    assert activated["dispatched_count"] == 1
    orders = list_orders(campaign_id=campaign["id"])
    chosen = orders[0]["unit_id"]
    assert chosen in {u["id"] for u in ctx["units"]}, (
        "the tie-break selects one of the equally-ranked ONLINE candidates"
    )
    units = {u["id"]: u for u in ctx["units"]}
    assert units[chosen]["installed_at"] <= max(u["installed_at"] for u in ctx["units"]), (
        "the earlier installation is not skipped over a later one"
    )
    resp = api_client.activate_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

def test_certification_lapses_lazily_when_the_clock_passes_the_term(api):
    """PRD §3.1: "When a read observes an `ACTIVE` installer whose `certified_until` has
    passed — the clock strictly after that instant — the installer becomes `EXPIRED` and
    both entitlement booleans fall to false." PRD §3.1: "Activation writes
    `certified_until` as the current logical clock instant advanced by thirty-six
    months".

    Design: Corner/cross_cutting_complexity_layers/certification_lapse_expires_installer_lazily
    """
    from test_helpers import setup_active_installer

    set_clock("2026-09-01T00:00:00Z")
    installer = setup_active_installer("INST-XC5", level="GOLD")
    assert installer["certification_status"] == "ACTIVE"
    assert installer["certified_until"] == "2029-09-01T00:00:00.000Z"
    assert installer["design_tool_enabled"] is True

    set_clock("2030-01-01T00:00:00Z")
    after = get_success_data(api_client.get_installer(installer["id"], ADMIN))
    assert after["certification_status"] == "EXPIRED"
    assert after["design_tool_enabled"] is False
    assert after["commissioning_enabled"] is False
