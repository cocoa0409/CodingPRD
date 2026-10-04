"""Composite setup helpers for multi-step test prerequisites.

Setup helpers use ``get_success_data()`` (the lenient validator) so a broken
precondition surfaces as a clear "setup step failed" error rather than a
confusing assertion failure inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_LOGICAL_CLOCK, TEST_DEFAULTS
from .factories import (
    create_allocation_commit_payload,
    create_audit_finalize_payload,
    create_capacity_profile_payload,
    create_distribution_payload,
    create_donation_product_payload,
    create_giving_partner_payload,
    create_impact_audit_payload,
    create_impact_season_payload,
    create_marketing_claim_payload,
    create_order_line_payload,
    create_product_line_payload,
    create_receipt_payload,
    create_return_request_payload,
    create_sales_order_payload,
    create_vetting_round_payload,
    create_waterfall_allocation_payload,
)
from .test_users import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]
DESIGN = TEST_USERS["designer_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
SERVICE = TEST_USERS["customer_service_headers"]
MARKETING = TEST_USERS["marketing_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ─── Tier 1: Logical clock and season progression ──────────────────────────

def set_clock(to_iso8601: str):
    """Set the logical clock and roll every dependent transition."""
    return get_success_data(api_client.set_clock(to_iso8601, AUDITOR))


def reset_clock():
    """Return the logical clock to its startup default."""
    return set_clock(DEFAULT_LOGICAL_CLOCK)


def create_season(
    season_code: str = TEST_DEFAULTS["SEASON_CODE"],
    starts_at: str = TEST_DEFAULTS["SEASON_STARTS_AT"],
    ends_at: str = TEST_DEFAULTS["SEASON_ENDS_AT"],
    freezes_at: str = TEST_DEFAULTS["SEASON_FREEZES_AT"],
):
    """Open an impact season calendar. Returns the created season."""
    res = api_client.create_impact_season(
        create_impact_season_payload(
            season_code=season_code, starts_at=starts_at, ends_at=ends_at, freezes_at=freezes_at
        ),
        AUDITOR,
    )
    return get_success_data(res)


def freeze_season(season_id: str):
    """Force a season to its frozen state through the explicit frozen-state write."""
    season = get_success_data(api_client.get_impact_season(season_id, AUDITOR))
    return get_success_data(
        api_client.set_season_frozen_state(
            season_id, {"is_final": True, "expected_season_version": season["version"]}, AUDITOR
        )
    )


def season_with_clock_inside(advance_to: str = TEST_DEFAULTS["SEASON_STARTS_AT"]):
    """A running (OPEN) season whose calendar contains the returned clock instant."""
    set_clock(advance_to)
    return create_season()


# ─── Tier 2: Product hierarchy ─────────────────────────────────────────────

def create_active_product(
    product_name: str = "Test Everyday Sock",
    product_kind: str = "ATHLETIC_SOCK",
    design_channel: str = "DUAL_CHANNEL",
    obligation_model: str = "AT_SALE",
    retail_price_cents: int = 1600,
    unit_cost_cents: int = 1150,
    is_reusable: bool = True,
    approved_donation_ratio_units: int = 1,
):
    """Create a donation product and walk it DRAFT → ACTIVE. Returns the product."""
    res = api_client.create_donation_product(
        create_donation_product_payload(
            product_name=product_name,
            product_kind=product_kind,
            design_channel=design_channel,
            obligation_model=obligation_model,
            retail_price_cents=retail_price_cents,
            unit_cost_cents=unit_cost_cents,
            is_reusable=is_reusable,
            approved_donation_ratio_units=approved_donation_ratio_units,
        ),
        DESIGN,
    )
    product = get_success_data(res)
    activated = api_client.activate_donation_product(product["id"], {}, DESIGN)
    return get_success_data(activated)


def add_product_line(
    product_id: str,
    gtin: str,
    unit_size_label: str = "M",
    is_essential_good: bool = False,
    donation_eligible: bool = True,
):
    """Add a sellable variant line under an active product. Returns the line."""
    res = api_client.create_product_line(
        product_id,
        create_product_line_payload(
            gtin=gtin,
            unit_size_label=unit_size_label,
            is_essential_good=is_essential_good,
            donation_eligible=donation_eligible,
        ),
        DESIGN,
    )
    return get_success_data(res)


def setup_product_with_two_lines(
    product_name: str = "Two Line Product",
    unit_cost_cents: int = 1150,
    retail_price_cents: int = 1600,
    design_channel: str = "DUAL_CHANNEL",
):
    """Active product carrying two eligible variant lines. Returns (product, line_a, line_b)."""
    product = create_active_product(
        product_name=product_name,
        unit_cost_cents=unit_cost_cents,
        retail_price_cents=retail_price_cents,
        design_channel=design_channel,
    )
    line_a = add_product_line(product["id"], "00000000000051", "M", True)
    line_b = add_product_line(product["id"], "00000000000052", "L", False)
    return product, line_a, line_b


# ─── Tier 2: Partner onboarding and vetting ────────────────────────────────

def onboard_partner(
    legal_name: str = "Test Harbor Shelter",
    partner_type: str = "HOMELESS_SHELTER",
    operating_region: str = "NORTHEAST",
    operating_state_code: str = "MA",
    registry_id: str = "MA-CHR-310031",
    ein: str = "400500600",
    founded_year: int = 1972,
    unduplicated_recipients_per_facility: int = 15000,
    need_tier: str = "MODERATE",
    service_radius_miles: int = 50,
):
    """Onboard a giving partner; the same request opens round 1. Returns the partner."""
    res = api_client.create_giving_partner(
        create_giving_partner_payload(
            legal_name=legal_name,
            partner_type=partner_type,
            operating_region=operating_region,
            operating_state_code=operating_state_code,
            registry_id=registry_id,
            ein=ein,
            founded_year=founded_year,
            unduplicated_recipients_per_facility=unduplicated_recipients_per_facility,
            need_tier=need_tier,
            service_radius_miles=service_radius_miles,
        ),
        COORD,
    )
    return get_success_data(res)


def record_round(
    vetting_id: str,
    outcome: str = None,
    registry_check_passed: bool = True,
    tax_check_passed: bool = True,
    on_site_check_passed: bool = True,
    capacity_check_passed: bool = True,
    need_verification_points: int = 1,
    valid_until: str = "2027-01-01T00:00:00Z",
    **extra,
):
    """Record evidence on an open vetting round.

    PRD §3.1: "A round begins at `REQUESTED` and may move to
    `DOCUMENTS_SUBMITTED` once `registry_check_passed` and `tax_check_passed`
    are both present; from there to `EVALUATING`." The helper therefore walks
    the declared path — REQUESTED -> DOCUMENTS_SUBMITTED -> (EVALUATING) —
    instead of jumping straight to an outcome the round's current state cannot
    reach. A caller-supplied ``outcome`` still rides the same walk so that a
    deliberately-invalid write remains the caller's to express.
    """
    current = get_vetting_round(vetting_id)["outcome"]
    started_at = current

    if current == "REQUESTED":
        res = api_client.update_vetting_round(
            vetting_id,
            create_vetting_round_payload(
                outcome="DOCUMENTS_SUBMITTED",
                registry_check_passed=registry_check_passed,
                tax_check_passed=tax_check_passed,
                on_site_check_passed=on_site_check_passed,
                capacity_check_passed=capacity_check_passed,
                need_verification_points=need_verification_points,
                valid_until=valid_until,
                **extra,
            ),
            COORD,
        )
        current = get_success_data(res)["outcome"]

    target = outcome
    if target is None:
        target = "EVALUATING" if current in ("DOCUMENTS_SUBMITTED", "EVALUATING") else None

    if target is None:
        return get_vetting_round(vetting_id)

    # The follow-up write always lands so that a caller who changes a flag after
    # the round has already advanced still records the change.  When this call
    # did NOT open the round (its first write above stayed put), the caller's
    # flags ride along verbatim; when it did, re-sending the factory's defaults
    # would silently overwrite a flag set to False (PRD §3.1 gates approval on
    # all four verification flags).
    advance = {
        "outcome": target,
        "need_verification_points": need_verification_points,
    }
    if started_at != "REQUESTED":
        advance.update({
            "registry_check_passed": registry_check_passed,
            "tax_check_passed": tax_check_passed,
            "on_site_check_passed": on_site_check_passed,
            "capacity_check_passed": capacity_check_passed,
        })
    if target == "REQUESTED":
        advance["outcome_message"] = extra.pop(
            "outcome_message", "More information requested.")
    advance.update(extra)
    res = api_client.update_vetting_round(vetting_id, advance, COORD)
    return get_success_data(res)


def evaluate_approved_round(vetting_id: str, need_verification_points: int = 1):
    """Re-record evidence on an already-APPROVED round.

    PRD §3.1: "`need_score` is recomputed ... on any vetting-round write that
    changes the verification points". Such a write lands on the round the
    partner already carries rather than opening a fresh one, so the round is
    re-addressed directly instead of through the REQUESTED path.
    """
    res = api_client.update_vetting_round(
        vetting_id,
        {"outcome": "EVALUATING", "need_verification_points": need_verification_points},
        COORD,
    )
    if res.status_code == 200:
        return get_success_data(res)
    # A round already holding a non-APPROVED outcome can be walked back to
    # DOCUMENTS_SUBMITTED first (PRD §3.1's completed-round reopening path).
    api_client.update_vetting_round(
        vetting_id, {"outcome": "DOCUMENTS_SUBMITTED"}, COORD
    )
    return get_success_data(
        api_client.update_vetting_round(
            vetting_id,
            {"outcome": "EVALUATING", "need_verification_points": need_verification_points},
            COORD,
        )
    )


def approve_round(vetting_id: str):
    """Approve a vetting round: partner moves to APPROVED."""
    return get_success_data(api_client.approve_vetting_round(vetting_id, {}, COORD))


def create_approved_partner(
    vetting_points: int = 1,
    legal_name: str = "Test Harbor Shelter",
    **partner_overrides,
):
    """Onboard a partner, run its round to EVALUATING and approve it.

    Returns the APPROVED partner. When the running season is still PLANNED the
    approval also mints a capacity profile for it.
    """
    partner = onboard_partner(legal_name=legal_name, **partner_overrides)
    record_round(
        partner["latest_vetting_round_id"], need_verification_points=vetting_points
    )
    approve_round(partner["latest_vetting_round_id"])
    return get_success_data(api_client.get_giving_partner(partner["id"], COORD))


def declare_capacity(
    partner_id: str,
    max_allocatable_units: int = 100000,
    season_code: str = TEST_DEFAULTS["SEASON_CODE"],
    effective_from: str = TEST_DEFAULTS["CAPACITY_EFFECTIVE_FROM"],
    effective_to: str = TEST_DEFAULTS["CAPACITY_EFFECTIVE_TO"],
):
    """Declare a partner's capacity ceiling for a season. Returns the profile."""
    res = api_client.create_capacity_profile(
        partner_id,
        create_capacity_profile_payload(
            season_code=season_code,
            max_allocatable_units=max_allocatable_units,
            effective_from=effective_from,
            effective_to=effective_to,
        ),
        COORD,
    )
    return get_success_data(res)


def get_partner(partner_id: str):
    return get_success_data(api_client.get_giving_partner(partner_id, COORD))


def get_partner_version(partner_id: str) -> int:
    return get_partner(partner_id)["version"]


def get_profile(profile_id: str):
    return get_success_data(api_client.get_capacity_profile(profile_id, PLANNER))


# ─── Tier 2: Claims ────────────────────────────────────────────────────────

def register_claim(
    product_id: str,
    partner_id: str,
    stated_donation_units: int = 1000,
    winback_multiplier: int = 1,
    stated_reference_period: str = "SEASON",
    stated_ratio_text: str = "one purchased = one donated",
):
    """Register a public donation claim for a product and a named partner."""
    res = api_client.create_marketing_claim(
        create_marketing_claim_payload(
            product_id,
            partner_id,
            stated_donation_units=stated_donation_units,
            winback_multiplier=winback_multiplier,
            stated_reference_period=stated_reference_period,
            stated_ratio_text=stated_ratio_text,
        ),
        MARKETING,
    )
    return get_success_data(res)


def get_claim(claim_id: str):
    return get_success_data(api_client.get_marketing_claim(claim_id, MARKETING))


# ─── Tier 3: Allocation lifecycle shortcuts ────────────────────────────────

def commit_allocation(
    season_id: str,
    partner_id: str,
    claim_id: str,
    product_id: str,
    allocated_units: int = 10,
    priority_tier: str = "CRITICAL",
    liquidity_cap: int = 10,
    expected_partner_version=None,
):
    """Commit one benefit allocation to a single partner. Returns the APPROVED allocation."""
    if expected_partner_version is None:
        expected_partner_version = get_partner_version(partner_id)
    res = api_client.commit_allocation_plan(
        season_id,
        create_allocation_commit_payload(
            partner_id,
            claim_id,
            product_id,
            expected_partner_version,
            allocated_units=allocated_units,
            priority_tier=priority_tier,
            liquidity_cap=liquidity_cap,
        ),
        PLANNER,
    )
    return get_success_data(res)


def get_allocation(allocation_id: str):
    return get_success_data(api_client.get_allocation(allocation_id, PLANNER))


def ship_allocation(
    allocation_id: str,
    shipped_units: int,
    shipment_reference: str = "TRK-SHIP-1",
    carrier_code: str = "UPS",
):
    """Ship units against an approved allocation. Returns the created distribution."""
    res = api_client.create_distribution(
        allocation_id,
        create_distribution_payload(
            shipped_units=shipped_units,
            shipment_reference=shipment_reference,
            carrier_code=carrier_code,
        ),
        FULFILL,
    )
    return get_success_data(res)


def confirm_receipt(
    distribution_id: str,
    received_units: int,
    receipt_reference: str = "RCV-1",
):
    """Confirm partner receipt against a distribution; the confirmation accumulates."""
    res = api_client.create_receipt(
        distribution_id,
        create_receipt_payload(
            received_units=received_units, receipt_reference=receipt_reference
        ),
        COORD,
    )
    return get_success_data(res)


def get_liability_for(product_id: str, season_id: str):
    """The single liability row for a product-and-season bucket."""
    res = api_client.list_liabilities(
        AUDITOR, {"donation_product_id": product_id, "impact_season_id": season_id}
    )
    data = get_success_data(res)
    rows = data if isinstance(data, list) else data.get("data", data)
    assert rows, "expected a liability row for this product and season"
    return rows[0]


def get_season(season_id: str):
    return get_success_data(api_client.get_impact_season(season_id, AUDITOR))


def get_product(product_id: str):
    return get_success_data(api_client.get_donation_product(product_id, AUDITOR))

# ─── Tier 2: Multi-partner pool (shared seven-call prefix) ─────────────────

def provision_approved_partner(
    legal_name: str,
    partner_type: str,
    operating_region: str,
    operating_state_code: str,
    registry_id: str,
    ein: str,
    unduplicated_recipients_per_facility: int,
    need_tier: str,
    founded_year: int = 1990,
    service_radius_miles: int = 50,
    cap_units: int = 100000,
    season_code: str = TEST_DEFAULTS["SEASON_CODE"],
):
    """Onboard → vet → approve → declare capacity in one call.

    Returns (partner, vetting_round, capacity_profile).
    """
    partner = onboard_partner(
        legal_name=legal_name,
        partner_type=partner_type,
        operating_region=operating_region,
        operating_state_code=operating_state_code,
        registry_id=registry_id,
        ein=ein,
        founded_year=founded_year,
        unduplicated_recipients_per_facility=unduplicated_recipients_per_facility,
        need_tier=need_tier,
        service_radius_miles=service_radius_miles,
    )
    vetting_id = partner["latest_vetting_round_id"]
    record_round(vetting_id, need_verification_points=1)
    approve_round(vetting_id)
    profile = declare_capacity(partner["id"], max_allocatable_units=cap_units,
                               season_code=season_code)
    return get_partner(partner["id"]), vetting_id, profile


def setup_three_partner_pool(
    cap_units: int = 5000,
    product_name: str = "Pool Test Sock",
    unit_cost_cents: int = 1150,
    retail_price_cents: int = 1900,
    stated_units: int = 3000,
    season_code: str = TEST_DEFAULTS["SEASON_CODE"],
):
    """A running OPEN season, one active dual-channel product with one line, three
    APPROVED partners with declared ceilings created one second apart, and one claim.

    Returns a dict with season, product, line, partners (list, in creation order),
    profiles (list) and claim.
    """
    season = create_season(season_code=season_code)
    product = create_active_product(
        product_name=product_name,
        unit_cost_cents=unit_cost_cents,
        retail_price_cents=retail_price_cents,
        design_channel="DUAL_CHANNEL",
    )
    line = add_product_line(product["id"], "00000000000054", "M", True)

    partner_specs = [
        # The last tuple member is the declared `need_tier`, whose vocabulary in
        # PRD §3.1 is `CRITICAL`, `HIGH`, `MODERATE` or `LOW` — the partner_type
        # token drives the band's *base* for need_score, not this field.
        ("Alpha Housing Bridge", "HOMELESS_SHELTER", "NORTHEAST", "NY",
         "NY-CHR-100001", "111222333", 5000, "MODERATE"),
        ("Beta Outreach Collective", "YOUTH_OUTREACH", "SOUTHWEST", "TX",
         "TX-CHR-200002", "222333444", 3000, "MODERATE"),
        ("Gamma Relief Network", "DISASTER_RELIEF", "MIDWEST", "OH",
         "OH-CHR-300003", "333444555", 2000, "CRITICAL"),
    ]
    # Distinct created_at values make the pinned tie-break sequences total.
    partner_clocks = [
        "2026-09-01T00:00:00Z",
        "2026-09-02T00:00:00Z",
        "2026-09-03T00:00:00Z",
    ]
    partners, profiles = [], []
    for spec, clock_instant in zip(partner_specs, partner_clocks):
        name, ptype, region, state, reg, ein, recipients, tier = spec
        set_clock(clock_instant)
        partner, _, profile = provision_approved_partner(
            legal_name=name, partner_type=ptype, operating_region=region,
            operating_state_code=state, registry_id=reg, ein=ein,
            unduplicated_recipients_per_facility=recipients, need_tier=tier,
            cap_units=cap_units, season_code=season_code,
        )
        partners.append(partner)
        profiles.append(profile)

    claim = register_claim(
        product["id"], partners[0]["id"], stated_donation_units=stated_units
    )
    return {
        "season": season,
        "product": product,
        "line": line,
        "partners": partners,
        "profiles": profiles,
        "claim": claim,
    }


def allocate_waterfall(
    season_id: str,
    claim_id: str,
    product_id: str,
    liquidity_cap: int = 10,
    baseline_units: int = 2400,
    demand_units: int = 15000,
    pool_units: int = 4000,
):
    """Spread a finite pool across every eligible partner at once."""
    res = api_client.allocate_allocation_plan(
        season_id,
        create_waterfall_allocation_payload(
            claim_id, product_id,
            liquidity_cap=liquidity_cap, baseline_units=baseline_units,
            demand_units=demand_units, pool_units=pool_units,
        ),
        PLANNER,
    )
    return get_success_data(res)


# ─── Tier 3: Order and commercial shortcuts ────────────────────────────────

def create_order(order_number: str = "SO-FACTORY-1", channel: str = "RETAIL_ECOM"):
    """Create a retail sales order; it opens CREATED / PLACED."""
    res = api_client.create_sales_order(
        create_sales_order_payload(order_number=order_number, channel=channel), SERVICE
    )
    return get_success_data(res)


def add_line(order_id: str, product_line_id: str, quantity: int = 2,
             unit_price_cents: int = 1600, line_discount_cents: int = 0, **extra):
    """Add a purchased variant to an order; the donation obligation accrues immediately."""
    res = api_client.add_order_line(
        order_id,
        create_order_line_payload(
            product_line_id,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
            line_discount_cents=line_discount_cents,
            **extra,
        ),
        SERVICE,
    )
    return get_success_data(res)


def pay_order(order_id: str):
    return get_success_data(api_client.pay_order(order_id, {}, SERVICE))


def create_paid_order(order_number: str, product_line_id: str, quantity: int = 2,
                      unit_price_cents: int = 1600, line_discount_cents: int = 0,
                      channel: str = "RETAIL_ECOM"):
    """Create an order, add one line and pay it. Returns (order, line)."""
    order = create_order(order_number=order_number, channel=channel)
    line = add_line(order["id"], product_line_id, quantity=quantity,
                    unit_price_cents=unit_price_cents,
                    line_discount_cents=line_discount_cents)
    paid = pay_order(order["id"])
    return paid, line


def create_created_order_with_line(order_number: str, product_line_id: str,
                                   quantity: int = 4, unit_price_cents: int = 1600):
    """An order that has a line but has not been paid. Returns (order, line)."""
    order = create_order(order_number=order_number, channel="RETAIL_POS")
    line = add_line(order["id"], product_line_id, quantity=quantity,
                    unit_price_cents=unit_price_cents)
    return order, line


def open_return(line_id: str, expected_line_version: int, requested_units: int = 1,
                request_reason: str = "SIZE", order_id: str = None, **extra):
    """Open a return request against a line, nested when an order id is supplied."""
    payload = create_return_request_payload(
        line_id, request_reason=request_reason, requested_units=requested_units,
        expected_line_version=expected_line_version, **extra,
    )
    if order_id:
        res = api_client.open_line_return_request(order_id, line_id, payload, SERVICE)
    else:
        res = api_client.create_return_request(payload, SERVICE)
    return get_success_data(res)


def get_order_line(order_id: str, line_id: str):
    return get_success_data(api_client.get_order_line(order_id, line_id, SERVICE))


def get_line_version(order_id: str, line_id: str) -> int:
    return get_order_line(order_id, line_id)["version"]


# ─── Tier 3: Distribution lifecycle shortcuts ──────────────────────────────

def ship_and_receive(allocation_id: str, units: int, received: int = None,
                     reference_prefix: str = "LIFE"):
    """Ship an allocation and confirm receipt in full (or partially).

    Returns (distribution, received_units).
    """
    dist = ship_allocation(allocation_id, units, f"TRK-{reference_prefix}-1")
    received_units = units if received is None else received
    confirm_receipt(dist["id"], received_units, f"RCV-{reference_prefix}-1")
    return get_success_data(api_client.get_distribution(dist["id"], FULFILL)), received_units


def setup_pending_allocation(
    cap_units: int = 100000,
    allocated_units: int = 40,
    priority_tier: str = "CRITICAL",
    product_name: str = "Pending Alloc Sock",
    partner_overrides=None,
):
    """Season + active product + one line + APPROVED partner + ceiling + claim +
    one committed allocation.

    Returns a dict with season, product, line, partner, profile, claim, allocation.
    """
    season = create_season()
    product = create_active_product(product_name=product_name, design_channel="DUAL_CHANNEL")
    line = add_product_line(product["id"], "00000000000601", "M", True)
    partner = create_approved_partner(**(partner_overrides or {}))
    profile = declare_capacity(partner["id"], max_allocatable_units=cap_units)
    claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
    allocation = commit_allocation(
        season["id"], partner["id"], claim["id"], product["id"],
        allocated_units=allocated_units, priority_tier=priority_tier,
    )
    return {
        "season": get_season(season["id"]),
        "product": product,
        "line": line,
        "partner": get_partner(partner["id"]),
        "profile": get_profile(profile["id"]),
        "claim": claim,
        "allocation": allocation,
    }


# ─── Tier 3: Remaining lifecycle shortcuts ─────────────────────────────────

def settle_line(order_id: str, line_id: str, shipped_units: int):
    """Settle a line's donation obligation out of the warehouse."""
    return get_success_data(
        api_client.settle_line(order_id, line_id, {"shipped_units": shipped_units}, FULFILL)
    )


def cancel_allocation(allocation_id: str, expected_allocation_version=None):
    """Cancel an approved allocation before any unit ships."""
    if expected_allocation_version is None:
        expected_allocation_version = get_allocation(allocation_id)["version"]
    return get_success_data(
        api_client.cancel_allocation(
            allocation_id, {"expected_allocation_version": expected_allocation_version}, PLANNER
        )
    )


def substantiate_claim(claim_id: str):
    """Substantiate a claim, or refuse it and overstate it."""
    return get_success_data(api_client.substantiate_claim(claim_id, {}, MARKETING))


def derive_build_claim(claim_id: str, expected_liability_version=None, product_id=None,
                       season_id=None):
    """Run the derive-build carry-forward, guarded by the liability's version."""
    if expected_liability_version is None:
        expected_liability_version = get_liability_for(product_id, season_id)["version"]
    return get_success_data(
        api_client.derive_build_claim(
            claim_id, {"expected_liability_version": expected_liability_version}, MARKETING
        )
    )


def revoke_claim(claim_id: str, reason: str = "Public statement withdrawn"):
    return get_success_data(api_client.revoke_claim(claim_id, {"reason": reason}, MARKETING))


def get_impact_audit(audit_id: str):
    return get_success_data(api_client.get_impact_audit(audit_id, AUDITOR))


def get_distribution(distribution_id: str):
    return get_success_data(api_client.get_distribution(distribution_id, FULFILL))


def get_order(order_id: str):
    return get_success_data(api_client.get_sales_order(order_id, SERVICE))


def get_product_line(line_id: str):
    return get_success_data(api_client.get_donation_product_line(line_id, DESIGN))


def get_vetting_round(vetting_id: str):
    return get_success_data(api_client.get_vetting_round(vetting_id, COORD))
