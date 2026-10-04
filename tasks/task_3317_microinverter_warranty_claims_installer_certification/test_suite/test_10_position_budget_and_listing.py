"""The replacement-position budget, listing semantics, and the remaining design gates.

Difficulty queue A: combinatorial_formula.
Corner queue B: entities, validations.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commission_system,
    commission_unit_entry,
    create_entitlement,
    dispatch_order,
    get_success_data,
    install_order,
    list_orders,
    make_installer_headers,
    observe,
    set_clock,
    setup_submitted_design,
    setup_system_with_units,
    validate_error,
    validate_paginated,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: the claim gate is strict, so one spare position still admits ───

def _burn_positions(ctx, count: int, serial_prefix: str, start_month_iso: str):
    """Consume `count` of the system's five replacement positions with billed-
    replacement entitlements, installing each reservation before the next is taken."""
    unit = ctx["units"][0]
    months = ["2026-02-01", "2026-05-01", "2026-08-01", "2026-11-01", "2027-02-01"]
    for index in range(count):
        entitlement = create_entitlement(unit["id"], f"{months[index]}T00:00:00Z")
        assert entitlement["unit_id"] == unit["id"]
        order = list_orders(unit_id=unit["id"], status="PENDING_DISPATCH")[0]
        dispatch_order(order["id"])
        install_order(order["id"], f"{serial_prefix}-R{index + 1}",
                      f"2026-04-0{index + 2}T00:00:00Z", ctx["installer"]["id"])
    return get_success_data(api_client.get_unit(unit["id"], ADMIN))


def _single_unit_online_system(code: str):
    return setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=[f"{code}-U1"], unit_models=["IQ8"],
        lot_code=f"LOT-{code}", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-10T00:00:00Z",
        site_address=f"4 {code} Way",
    )


def test_a_claim_is_admitted_while_one_unscheduled_position_remains(api):
    """PRD §3.6: "Fourth, the unit's system must still have at least one unscheduled
    replacement position left, meaning a `replacement_window_position` strictly greater
    than zero; a system sitting at exactly one remaining position is admitted, and the
    eventual install takes it to zero". PRD §3.3: "it starts at five and is decremented
    by one for every replacement installed anywhere on that system."

    Design: Difficulty/combinatorial_formula/replacement_limit_strictly_greater_than_zero
    """
    ctx = _single_unit_online_system("CF2")
    set_clock("2026-09-01T00:00:00Z")
    unit = _burn_positions(ctx, 4, "CF2", "2026-02-01")
    assert unit["replacement_count"] == 4
    assert unit["replacement_window_position"] == 1

    failed = observe(unit["id"], 0.0, "2026-08-15T00:00:00Z")
    assert failed["monitored_status"] == "FAILED"
    claim = get_success_data(api_client.create_claim(
        {"unit_id": failed["id"], "installer_id": ctx["installer"]["id"],
         "claim_kind": "DEFECT", "remote_diagnostic_ref": "DIAG-CF2",
         "expected_unit_version": failed["version"]},
        make_installer_headers(ctx["installer"]["id"])), 201)
    assert claim["status"] == "DRAFT", (
        "a system sitting at exactly one position admits the filing"
    )


def test_a_claim_is_refused_once_the_replacement_budget_is_exhausted(api):
    """PRD §3.6: "while a system already at zero is refused with
    `ERR_REPLACEMENT_LIMIT_REACHED`." PRD §3.3: "Each unit's
    `replacement_window_position` is seeded at five, which is the number of unscheduled
    replacement slots the system will ever have."

    Design: Difficulty/combinatorial_formula/replacement_limit_strictly_greater_than_zero
    """
    ctx = _single_unit_online_system("CF2B")
    set_clock("2026-09-01T00:00:00Z")
    unit = _burn_positions(ctx, 5, "CF2B", "2026-02-01")
    assert unit["replacement_count"] == 5
    assert unit["replacement_window_position"] == 0

    failed = observe(unit["id"], 0.0, "2026-08-15T00:00:00Z")
    assert failed["monitored_status"] == "FAILED"
    resp = api_client.create_claim(
        {"unit_id": failed["id"], "installer_id": ctx["installer"]["id"],
         "claim_kind": "DEFECT", "remote_diagnostic_ref": "DIAG-CF2B",
         "expected_unit_version": failed["version"]},
        make_installer_headers(ctx["installer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REPLACEMENT_LIMIT_REACHED, 409)
    claims = get_success_data(api_client.list_claims(ADMIN, {"unit_id": failed["id"]}))
    assert claims == [], "the exhausted budget leaves the unit with no claim path"


# ─── Queue B: listing, filtering, and pagination ──────────────────────

def test_system_registration_list_filters_and_paginates_by_installer(api):
    """PRD §2.3: "Paginated responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object. `has_more` is true exactly when further items
    exist beyond the returned window." PRD §2.3: "`limit` caps how many items are
    returned, defaulting to 10 with a minimum of 1 and a maximum of 100".

    Design: Corner/entities/system_registrations_list_pagination_and_filter
    """
    ctx = setup_system_with_units(
        installer_code="INST-C4", unit_serials=["C4-U1"], unit_models=["IQ8"],
        lot_code="LOT-C4", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-02-01T00:00:00Z",
        site_address="21 Whiskey Way",
    )
    commission_system(
        ctx["installer"]["id"], ctx["design_project"]["id"],
        site_address="22 Whiskey Way", site_postal_code="94022",
        units=[commission_unit_entry("C4-U2", model_code="IQ8",
                                     installed_at="2026-03-01T00:00:00Z",
                                     production_lot_code="LOT-C4")],
        commissioned_at="2026-03-01T00:00:00Z",
    )
    other = setup_system_with_units(
        installer_code="INST-C4X", unit_serials=["C4X-U1"], unit_models=["IQ8"],
        lot_code="LOT-C4X", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-02-01T00:00:00Z",
        site_address="23 Whiskey Way",
    )
    first_page, meta = validate_paginated(
        api_client.list_system_registrations(ADMIN, {"installer_id": ctx["installer"]["id"],
                                                     "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    second_page, meta_two = validate_paginated(
        api_client.list_system_registrations(ADMIN, {"installer_id": ctx["installer"]["id"],
                                                     "limit": 1, "offset": 1}))
    assert meta_two["has_more"] is False
    ids = [first_page[0]["id"], second_page[0]["id"]]
    assert len(set(ids)) == 2, "the two pages must not repeat a row"
    assert ctx["system"]["id"] in ids
    assert other["system"]["id"] not in ids, "the filter excludes another installer's systems"


# ─── Queue B: the two sides of the DC/AC gate ─────────────────────────

def test_design_ratio_above_the_limit_is_rejected_at_the_design_gate(api, platform_admin_headers):
    """PRD §3.2: "a design whose `dc_ac_ratio` is greater than one and a half is refused
    with `ERR_DC_AC_RATIO_EXCEEDED`, because a DC array oversized beyond that ratio will
    clip in a way the manufacturer will not warrant."

    Design: Corner/validations/design_ratio_above_one_point_five_is_rejected
    """
    set_clock()
    from test_helpers import setup_certified_installer, set_installer_level
    installer = setup_certified_installer("INST-V1")
    installer = set_installer_level(installer["id"], "GOLD")
    project = setup_submitted_design(installer["id"], site_address="32 Golf Two Way",
                                     module_count=40, dc_capacity_watts=24600)
    assert project["dc_ac_ratio"] == 1.7571
    resp = api_client.approve_design_project(project["id"], platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_DC_AC_RATIO_EXCEEDED, 422)
    after = get_success_data(api_client.get_design_project(project["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_design_ratio_exactly_at_the_limit_is_accepted(api, platform_admin_headers):
    """PRD §3.2: "Ratios at or below one and a half pass." PRD §3.2: "An approved design
    is the only kind that can serve as the reference for a commissioning".

    Design: Corner/validations/design_ratio_exactly_one_point_five_is_accepted
    """
    set_clock()
    from test_helpers import setup_certified_installer, set_installer_level
    installer = setup_certified_installer("INST-V2")
    installer = set_installer_level(installer["id"], "GOLD")
    project = setup_submitted_design(installer["id"], site_address="33 Hotel Two Way",
                                     module_count=40, dc_capacity_watts=21000)
    assert project["dc_ac_ratio"] == 1.5
    approved = get_success_data(api_client.approve_design_project(project["id"],
                                                                 platform_admin_headers))
    assert approved["status"] == "APPROVED"


def test_a_payload_repeating_one_serial_registers_it_at_most_once(api):
    """PRD §3.3: "Every `serial_number` in the payload must then be globally unique
    across all `Unit` rows, because a serial number is the manufacturer's only handle on
    a physical device: a repeat is `ERR_SERIAL_ALREADY_REGISTERED`."

    Design: Corner/validations/duplicate_serial_within_one_payload_is_rejected
    """
    ctx = setup_system_with_units(
        installer_code="INST-V6", unit_serials=["V6-OTHER"], unit_models=["IQ8"],
        lot_code="LOT-V6", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-01-05T00:00:00Z",
        site_address="37 Lima Two Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import setup_approved_design
    design = setup_approved_design(ctx["installer"]["id"], site_address="37b Lima Two Way")
    payload = {
        "installer_id": ctx["installer"]["id"],
        "design_project_id": design["id"],
        "site_address": "37b Lima Two Way",
        "site_postal_code": "94037",
        "homeowner_name": "L. Lima",
        "homeowner_email": "l2@lima.example",
        "commissioned_at": "2026-06-01T00:00:00Z",
        "units": [
            {"serial_number": "V6-U1", "model_code": "IQ8",
             "installed_at": "2026-06-01T00:00:00Z", "production_lot_code": "LOT-V6"},
            {"serial_number": "V6-U1", "model_code": "IQ8",
             "installed_at": "2026-06-01T00:00:00Z", "production_lot_code": "LOT-V6"},
        ],
    }
    resp = api_client.create_system_registration(
        payload, make_installer_headers(ctx["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SERIAL_ALREADY_REGISTERED, 409)
    units = get_success_data(api_client.list_units(ADMIN, {"production_lot_id": ctx["lot"]["id"]}))
    matching = [unit for unit in units if unit["serial_number"] == "V6-U1"]
    assert matching == [], "a serial named twice in one payload is never registered"