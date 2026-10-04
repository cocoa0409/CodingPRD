"""Cross-entity state dependencies: install gating, labor payment, and transfers.

Difficulty queue A: cross_entity_state_dependency.
Corner queue B: cross_cutting_complexity_layers.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_transfer,
    create_transfer,
    get_success_data,
    install_order,
    make_installer_headers,
    observe,
    reinstate_installer,
    set_clock,
    setup_failed_unit_claim,
    setup_system_with_units,
    suspend_installer,
    validate_error,
)

from test_helpers import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Queue A: an install needs a commissioned installer, not just a shipped order ───

def test_dispatched_order_cannot_be_installed_while_the_installer_is_suspended(api):
    """PRD §3.7: "The acting installer must hold `commissioning_enabled`, so an
    installer whose certification lapsed cannot install even an already-shipped unit —
    the refusal is `ERR_COMMISSIONING_NOT_ENABLED`."

    Design: Difficulty/cross_entity_state_dependency/replacement_install_requires_commissioning_enabled_active_installer
    """
    ctx = setup_failed_unit_claim(installer_code="INST-XE1", claim_target="DISPATCHED")
    installer, claim = ctx["installer"], ctx["claim"]
    order = get_success_data(api_client.list_replacement_orders(
        ADMIN, {"claim_id": claim["id"]}))[0]
    suspended = suspend_installer(installer["id"], reason="insurance lapse")
    assert suspended["commissioning_enabled"] is False
    resp = api_client.install_replacement_order(
        order["id"],
        {"replacement_serial_number": "XE1-R1", "installed_at": "2026-08-10T00:00:00Z"},
        make_installer_headers(installer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMMISSIONING_NOT_ENABLED, 403)
    still = get_success_data(api_client.get_replacement_order(order["id"], ADMIN))
    assert still["status"] == "DISPATCHED", "a refused install must not move the order"


def test_reinstating_the_installer_lets_the_same_order_be_installed(api):
    """PRD §3.7: "If the order carries a `claim_id`, the source claim moves from
    `DISPATCHED` to `CLOSED` and that claim's `APPROVED` reimbursements move to `PAID`
    with a `paid_at` instant stamped". PRD §3.1: "Reinstatement re-issues
    `certified_until` from the current clock instant and recomputes both entitlement
    booleans."

    Design: Difficulty/cross_entity_state_dependency/replacement_install_requires_commissioning_enabled_active_installer
    """
    ctx = setup_failed_unit_claim(installer_code="INST-XE1B", claim_target="DISPATCHED")
    installer, claim = ctx["installer"], ctx["claim"]
    order = get_success_data(api_client.list_replacement_orders(
        ADMIN, {"claim_id": claim["id"]}))[0]
    suspend_installer(installer["id"])
    reinstated = reinstate_installer(installer["id"])
    assert reinstated["commissioning_enabled"] is True, (
        "the installer still holds an approved design project"
    )
    installed = install_order(order["id"], "XE1B-R1", "2026-08-15T00:00:00Z", installer["id"])
    assert installed["status"] == "INSTALLED"
    closed = get_success_data(api_client.get_claim(claim["id"], ADMIN))
    assert closed["status"] == "CLOSED"


# ─── Queue A: labor is paid only when the claim closes behind the install ───

def _dispatched_claim_with_labor(code: str):
    return setup_failed_unit_claim(
        installer_code=code, claim_target="DISPATCHED", claimed_hours=4.0,
        unit_serials=[f"{code}-U1"], unit_models=["IQ7"], lot_code=f"LOT-{code}",
        embed_model_code="IQ7", replacement_model_code="IQ8",
        commissioned_at="2019-03-01T00:00:00Z", site_address=f"14 {code} Way",
    )


def test_approved_labor_stays_pending_until_the_claim_is_dispatched(api):
    """PRD §3.8: "While the claim is only `APPROVED`, the reimbursement sits
    `PENDING`." PRD §3.8: "The hours cap is likewise drawn from the level table:
    `PLATINUM` allows six hours, `GOLD` four, and `CERTIFIED` two."

    Design: Difficulty/cross_entity_state_dependency/labor_payment_requires_claim_closed_after_order_install
    """
    ctx = setup_failed_unit_claim(
        installer_code="INST-XE2A", claim_target="APPROVED", claimed_hours=4.0,
        unit_serials=["XE2A-U1"], unit_models=["IQ7"], lot_code="LOT-XE2A",
        embed_model_code="IQ7", replacement_model_code="IQ8",
        commissioned_at="2019-03-01T00:00:00Z", site_address="14a Quebec Way",
    )
    reimbursement = ctx["reimbursement"]
    assert reimbursement["status"] == "PENDING"
    assert reimbursement["allowed_hours"] == 4.0
    assert reimbursement["cap_applied"] is False
    assert ctx["claim"]["status"] == "APPROVED"


def test_dispatching_the_claim_approves_the_pending_labor(api):
    """PRD §3.8: "When the claim is dispatched, the reimbursement becomes `APPROVED`,
    and the installer's approved total grows."

    Design: Difficulty/cross_entity_state_dependency/labor_payment_requires_claim_closed_after_order_install
    """
    ctx = _dispatched_claim_with_labor("XE2B")
    reimbursement, claim = ctx["reimbursement"], ctx["claim"]
    assert claim["status"] == "DISPATCHED"
    after = get_success_data(api_client.get_labor_reimbursement(reimbursement["id"], ADMIN))
    assert after["status"] == "APPROVED"
    assert after["net_amount_cents"] == 34425
    portfolio = get_success_data(api_client.get_installer_portfolio(ctx["installer"]["id"], ADMIN))
    assert portfolio["labor_approved_cents_total"] == 34425
    assert portfolio["labor_paid_cents_total"] == 0


def test_installing_the_replacement_pays_the_labor_and_closes_the_claim(api):
    """PRD §3.8: "When the claim closes after the replacement is installed, the
    reimbursement becomes `PAID` and its `paid_at` is stamped, moving the amount from
    the approved total into the paid total." PRD §3.1: "`labor_paid_cents_total` sums
    only reimbursements in `PAID`."

    Design: Difficulty/cross_entity_state_dependency/labor_payment_requires_claim_closed_after_order_install
    """
    ctx = _dispatched_claim_with_labor("XE2C")
    reimbursement, claim = ctx["reimbursement"], ctx["claim"]
    order = get_success_data(api_client.list_replacement_orders(
        ADMIN, {"claim_id": claim["id"]}))[0]
    install_order(order["id"], "XE2C-R1", "2026-08-20T00:00:00Z", ctx["installer"]["id"])
    after = get_success_data(api_client.get_labor_reimbursement(reimbursement["id"], ADMIN))
    assert after["status"] == "PAID"
    assert after["paid_at"] is not None
    closed = get_success_data(api_client.get_claim(claim["id"], ADMIN))
    assert closed["status"] == "CLOSED"
    portfolio = get_success_data(api_client.get_installer_portfolio(ctx["installer"]["id"], ADMIN))
    assert portfolio["labor_paid_cents_total"] == 34425
    assert portfolio["labor_reversed_cents_total"] == 0


# ─── Queue B: cross-cutting complexity layers ─────────────────────────

def _register_online_unit(code: str):
    ctx = setup_system_with_units(
        installer_code=f"INST-{code}", unit_serials=[f"{code}-U1"], unit_models=["IQ8"],
        lot_code=f"LOT-{code}", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2026-04-01T00:00:00Z",
        site_address=f"42 {code} Way",
    )
    return ctx


def test_claim_creation_with_a_stale_unit_version_is_refused(api):
    """PRD §2.8: "Filing a `WarrantyClaim` and creating a `ReplacementOrder` against a
    unit both require the client to supply `expected_unit_version`: the caller's last
    observed `version` of the target `Unit`. If the supplied value does not equal the
    unit's current `version`, the request is rejected with `ERR_STALE_UNIT_VERSION` at
    HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_claim_create
    """
    ctx = _register_online_unit("XC1")
    unit = ctx["units"][0]
    stale_version = unit["version"]
    moved = observe(unit["id"], 0.80, "2026-08-01T00:00:00Z")
    assert moved["version"] > stale_version
    resp = api_client.create_claim(
        {"unit_id": unit["id"], "installer_id": ctx["installer"]["id"],
         "claim_kind": "DEFECT", "remote_diagnostic_ref": "DIAG-XC1",
         "expected_unit_version": stale_version},
        make_installer_headers(ctx["installer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_UNIT_VERSION, 412)
    created = get_success_data(api_client.create_claim(
        {"unit_id": unit["id"], "installer_id": ctx["installer"]["id"],
         "claim_kind": "DEFECT", "remote_diagnostic_ref": "DIAG-XC1",
         "expected_unit_version": moved["version"]},
        make_installer_headers(ctx["installer"]["id"]),
    ), 201)
    assert created["status"] == "DRAFT"


def test_replacement_order_creation_with_a_stale_unit_version_is_refused(api):
    """PRD §2.8: "A successful unit-scoped write bumps the unit's `version` by one, so
    the next caller must re-read before writing."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_replacement_order_create
    """
    ctx = _register_online_unit("XC2")
    unit = ctx["units"][0]
    stale_version = unit["version"]
    moved = observe(unit["id"], 0.80, "2026-08-01T00:00:00Z")
    resp = api_client.create_replacement_order(
        {"unit_id": unit["id"], "replacement_model_code": "IQ8",
         "expected_unit_version": stale_version}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_UNIT_VERSION, 412)
    created = get_success_data(api_client.create_replacement_order(
        {"unit_id": unit["id"], "replacement_model_code": "IQ8",
         "expected_unit_version": moved["version"]}, ADMIN), 201)
    assert created["status"] == "PENDING_DISPATCH"


def test_approving_a_transfer_keeps_the_system_in_the_installer_book(api):
    """PRD §3.1: "`active_system_count` counts the installer's `SystemRegistration`
    rows whose `warranty_status` is `ACTIVE` or `TRANSFERRED`." PRD §3.9: "on approval
    the transfer becomes `APPROVED`, the system's `warranty_status` becomes
    `TRANSFERRED`, the system's `homeowner_name` and `homeowner_email` are replaced with
    the transfer's new owner values, the system's `owner_change_count` — the number of
    approved transfers the system has ever had — is incremented".

    Design: Corner/cross_cutting_complexity_layers/derived_installer_active_system_count_tracks_transfer
    """
    ctx = setup_system_with_units(
        installer_code="INST-XC3", unit_serials=["XC3-U1"], unit_models=["IQ8"],
        lot_code="LOT-XC3", embed_model_code="IQ8", replacement_model_code="IQ8",
        defect_threshold_pct=1e6, commissioned_at="2020-01-01T00:00:00Z",
        site_address="44 Sierra Two Way",
    )
    set_clock("2026-09-01T00:00:00Z")
    before = get_success_data(api_client.get_installer_portfolio(ctx["installer"]["id"], ADMIN))
    assert before["active_system_count"] == 1
    transfer = create_transfer(ctx["system"]["id"], effective_date="2026-08-15T00:00:00Z",
                               new_owner_name="T. Tango", new_owner_email="t2@tango.example")
    approved = approve_transfer(transfer["id"])
    assert approved["status"] == "APPROVED"
    after = get_success_data(api_client.get_installer_portfolio(ctx["installer"]["id"], ADMIN))
    assert after["active_system_count"] == 1, "a transferred system still counts in the book"
    system = get_success_data(api_client.get_system_registration(ctx["system"]["id"], ADMIN))
    assert system["warranty_status"] == "TRANSFERRED"
    assert system["homeowner_name"] == "T. Tango"
    assert system["owner_change_count"] == 1