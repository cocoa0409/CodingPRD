"""Composite setup helpers.

Conventions:
- Every primitive performs exactly one API call and returns the parsed `data`
  payload (via the lenient get_success_data with the PRD-exact status), so a
  setup failure surfaces as "Setup failed" rather than a confusing assertion.
- DealerRep calls are ALWAYS identity-threaded: pass the owning dealer's id
  as `dealer_id` and the helper builds make_dealer_headers(dealer_id).
  EndUserRep calls likewise take `end_user_id`.
- Composite setup_* helpers return a context dict, e.g.
  {"dealer": ..., "end_user": ..., "agreement": ..., "families": {...},
   "configuration": ..., "order": ..., "phase": ...}.
- Date defaults come from factories.py and assume the logical clock is still
  at its 2026-09-01T00:00:00Z startup default (PRD §2.4). If your test moved
  the clock before calling a composite, pass explicit dates.
"""
from prd_bench_local_runner.testing import get_success_data

from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    DEFAULT_PRODUCTION_DATE,
    DEFAULT_REQUESTED_INSTALL_DATE,
    make_cancel_payload,
    make_configuration_payload,
    make_dealer_payload,
    make_end_user_payload,
    make_install_window_payload,
    make_lock_payload,
    make_module_entry,
    make_phase_payload,
    make_product_family_payload,
    make_project_order_payload,
    make_punch_ticket_payload,
    make_reserve_slot_payload,
    make_resolve_payload,
    make_review_payload,
    make_submit_payload,
    make_verify_payload,
    make_volume_agreement_payload,
    make_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_dealer_headers, make_end_user_headers

ADMIN = TEST_USERS["admin_headers"]


# ==========================================================================
# Clock
# ==========================================================================

def set_logical_clock(api, to_iso8601=DEFAULT_CLOCK_UTC) -> dict:
    """POST /_clock/set_current_utc as ManufacturerAdmin. Returns
    {"current_utc": ...}."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN), 200)


# ==========================================================================
# Dealer / end user / family / agreement primitives (ManufacturerAdmin)
# ==========================================================================

def create_dealer(api, **overrides) -> dict:
    """Create a Dealer (201). Initial status ACTIVE, showroom_compliant true
    unless overridden."""
    resp = api.create_dealer(make_dealer_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def update_dealer(api, dealer_id, **fields) -> dict:
    """PATCH /dealers/{id} (200). Pass any of service_capability_level,
    territory_codes, showroom_compliant, status."""
    resp = api.update_dealer(dealer_id, fields, ADMIN)
    return get_success_data(resp, 200)


def suspend_dealer(api, dealer_id) -> dict:
    """Showroom violation route: showroom_compliant true->false auto-suspends
    and cascades the dealer's SUBMITTED orders to ON_HOLD (PRD §3.1)."""
    return update_dealer(api, dealer_id, showroom_compliant=False)


def reinstate_dealer(api, dealer_id) -> dict:
    """SUSPENDED -> ACTIVE; cascades ON_HOLD orders back to SUBMITTED."""
    return update_dealer(api, dealer_id, showroom_compliant=True, status="ACTIVE")


def create_end_user(api, **overrides) -> dict:
    """Create an EndUser (201)."""
    resp = api.create_end_user(make_end_user_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_product_family(api, **overrides) -> dict:
    """Create a ProductFamily (201). At most one family per category exists,
    so create each category at most once per test."""
    resp = api.create_product_family(make_product_family_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def advance_family(api, family_id, **fields) -> dict:
    """PATCH /product-families/{id} (200): lifecycle_status plus
    last_order_date / parts_support_until as the transition requires."""
    resp = api.update_product_family(family_id, fields, ADMIN)
    return get_success_data(resp, 200)


def create_volume_agreement(api, end_user_id, **overrides) -> dict:
    """Create a VolumeAgreement (201); lands DRAFT, cumulative 0, tier 1."""
    resp = api.create_volume_agreement(
        make_volume_agreement_payload(end_user_id, **overrides), ADMIN
    )
    return get_success_data(resp, 201)


def activate_agreement(api, agreement_id) -> dict:
    """POST /volume-agreements/{id}/activate (200): DRAFT -> ACTIVE."""
    resp = api.activate_volume_agreement(agreement_id, ADMIN)
    return get_success_data(resp, 200)


def create_and_activate_agreement(api, end_user_id=None, **overrides) -> tuple:
    """Agreement in ACTIVE. Creates an EndUser when end_user_id is None.
    Returns (agreement_dict, end_user_dict)."""
    end_user = (
        create_end_user(api) if end_user_id is None
        else {"id": end_user_id}
    )
    agreement = create_volume_agreement(api, end_user["id"], **overrides)
    return activate_agreement(api, agreement["id"]), end_user


# ==========================================================================
# Configuration primitives (DealerRep, owner)
# ==========================================================================

def create_configuration(api, dealer_id, modules=None, **overrides) -> dict:
    """Create a ConfigurationSpec (201) owned by dealer_id; DRAFT, rev 1.
    modules: list of module entries (default one 4x TASK_CHAIR_SET A)."""
    if modules is not None:
        overrides["modules"] = modules
    resp = api.create_configuration(
        make_configuration_payload(**overrides), make_dealer_headers(dealer_id)
    )
    return get_success_data(resp, 201)


def lock_configuration(api, spec, dealer_id) -> dict:
    """POST /configurations/{id}/lock (200) with OCC: sends the spec dict's
    current version as expected_configuration_version. Pass the freshest spec
    dict you hold."""
    resp = api.lock_configuration(
        spec["id"],
        make_lock_payload(spec["version"]),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 200)


def revise_configuration(api, spec, dealer_id) -> dict:
    """POST /configurations/{id}/revise (200): LOCKED -> DRAFT, rev +1."""
    resp = api.revise_configuration(spec["id"], make_dealer_headers(dealer_id))
    return get_success_data(resp, 200)


def create_and_lock_configuration(api, dealer_id, modules=None, **overrides) -> dict:
    """Create then lock a configuration. Returns the LOCKED spec dict."""
    spec = create_configuration(api, dealer_id, modules=modules, **overrides)
    return lock_configuration(api, spec, dealer_id)


# ==========================================================================
# Project order primitives
# ==========================================================================

def create_order(api, agreement_id, configuration_id, dealer_id, **overrides) -> dict:
    """Create a ProjectOrder (201) as the owning DealerRep; DRAFT."""
    resp = api.create_project_order(
        make_project_order_payload(agreement_id, configuration_id, **overrides),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 201)


def submit_order(api, order, dealer_id) -> dict:
    """POST /project-orders/{id}/submit (200) with OCC: sends the order
    dict's current version as expected_order_version."""
    resp = api.submit_project_order(
        order["id"],
        make_submit_payload(order["version"]),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 200)


def acknowledge_order(api, order_id) -> dict:
    """POST /project-orders/{id}/acknowledge (200) as ManufacturerAdmin."""
    resp = api.acknowledge_project_order(order_id, ADMIN)
    return get_success_data(resp, 200)


def cancel_order(api, order_id, headers, reason=None) -> dict:
    """POST /project-orders/{id}/cancel (200). Pass make_dealer_headers for
    the owning dealer or ADMIN for the manufacturer."""
    resp = api.cancel_project_order(order_id, make_cancel_payload(reason), headers)
    return get_success_data(resp, 200)


def get_order(api, order_id, headers) -> dict:
    """GET /project-orders/{id} (200)."""
    return get_success_data(api.get_project_order(order_id, headers), 200)


def get_agreement(api, agreement_id, headers=None) -> dict:
    """GET /volume-agreements/{id} (200); lazy expiry applied server-side."""
    return get_success_data(
        api.get_volume_agreement(agreement_id, headers or ADMIN), 200
    )


# ==========================================================================
# Installation phase primitives (DealerRep, owner of the phase's order)
# ==========================================================================

def create_phase(api, order_id, dealer_id, **overrides) -> dict:
    """POST /project-orders/{id}/phases (201); PLANNED + NOT_STARTED."""
    resp = api.create_phase(
        order_id, make_phase_payload(**overrides), make_dealer_headers(dealer_id)
    )
    return get_success_data(resp, 201)


def reserve_slot(api, phase_id, dealer_id, plant_code="PLANT_GR",
                 production_date=DEFAULT_PRODUCTION_DATE) -> dict:
    """POST /phases/{id}/reserve-slot (200): PLANNED -> SCHEDULED; consumes
    plant capacity. Default date is clock-safe at the 2026-09-01 default."""
    resp = api.reserve_slot(
        phase_id,
        make_reserve_slot_payload(
            plant_code=plant_code, production_date=production_date
        ),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 200)


def start_install(api, phase_id, dealer_id) -> dict:
    """POST /phases/{id}/start-install (200): SCHEDULED -> DELIVERED and
    NOT_STARTED -> IN_PROGRESS in one action. Requires clock date >= the
    phase's production_date — advance the clock first if needed."""
    resp = api.start_install(phase_id, make_dealer_headers(dealer_id))
    return get_success_data(resp, 200)


def complete_phase(api, phase_id, dealer_id) -> dict:
    """POST /phases/{id}/complete (200): IN_PROGRESS -> COMPLETE; stamps
    actual_install_complete_date with the current clock date and may bubble
    the order ACKNOWLEDGED -> CLOSED."""
    resp = api.complete_phase(phase_id, make_dealer_headers(dealer_id))
    return get_success_data(resp, 200)


def schedule_and_start_install(api, phase_id, dealer_id,
                               plant_code="PLANT_GR",
                               production_date=DEFAULT_PRODUCTION_DATE) -> dict:
    """reserve_slot, advance the clock to production_date, then start_install.
    Returns the DELIVERED / IN_PROGRESS phase dict."""
    reserve_slot(api, phase_id, dealer_id, plant_code, production_date)
    set_logical_clock(api, f"{production_date}T00:00:00Z")
    return start_install(api, phase_id, dealer_id)


# ==========================================================================
# Install window / punch ticket / warranty claim primitives
# ==========================================================================

def create_window(api, phase_id, dealer_id, **overrides) -> dict:
    """POST /install-windows (201) as the owning DealerRep; RESERVED.
    Defaults: 2026-12-01 09:00-12:00Z, non-union, elevator, crew 4."""
    resp = api.create_install_window(
        make_install_window_payload(phase_id, **overrides),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 201)


def cancel_window(api, window_id, dealer_id) -> dict:
    """POST /install-windows/{id}/cancel (200): RESERVED -> CANCELLED."""
    resp = api.cancel_install_window(window_id, make_dealer_headers(dealer_id))
    return get_success_data(resp, 200)


def file_punch(api, phase_id, headers, **overrides) -> dict:
    """POST /punch-tickets (201); OPEN. headers choose the filer:
    make_dealer_headers(order's dealer) or make_end_user_headers(order's
    agreement's end user)."""
    resp = api.create_punch_ticket(
        make_punch_ticket_payload(phase_id, **overrides), headers
    )
    return get_success_data(resp, 201)


def resolve_punch(api, ticket_id, dealer_id, resolution_note="Resolved") -> dict:
    """POST /punch-tickets/{id}/resolve (200): OPEN -> RESOLVED; a
    requires_part ticket auto-creates a SUBMITTED PARTS WarrantyClaim."""
    resp = api.resolve_punch_ticket(
        ticket_id, make_resolve_payload(resolution_note),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 200)


def verify_punch(api, ticket_id, end_user_id, outcome="CONFIRMED") -> dict:
    """POST /punch-tickets/{id}/verify (200) as the owning EndUserRep:
    CONFIRMED -> VERIFIED; REJECTED -> back to OPEN."""
    resp = api.verify_punch_ticket(
        ticket_id, make_verify_payload(outcome),
        make_end_user_headers(end_user_id),
    )
    return get_success_data(resp, 200)


def file_claim(api, order_id, phase_id, dealer_id, **overrides) -> dict:
    """POST /warranty-claims (201) as the owning DealerRep; SUBMITTED with
    filed_date = clock date. Phase must be COMPLETE."""
    resp = api.create_warranty_claim(
        make_warranty_claim_payload(order_id, phase_id, **overrides),
        make_dealer_headers(dealer_id),
    )
    return get_success_data(resp, 201)


def review_claim(api, claim_id, decision="APPROVE", review_note=None) -> dict:
    """POST /warranty-claims/{id}/review (200) as ManufacturerAdmin;
    APPROVE/DENY are both terminal."""
    resp = api.review_warranty_claim(
        claim_id, make_review_payload(decision, review_note), ADMIN
    )
    return get_success_data(resp, 200)


# ==========================================================================
# Composite worlds (tiers 1-5)
# ==========================================================================

def setup_dealer_world(api, *, territories=("MI", "OH"), capability=4,
                       family_specs=(("SEAT-2200", "SEATING", 28),),
                       agreement_start="2026-01-01",
                       agreement_end="2027-12-31",
                       discounts=(0.10, 0.15, 0.20),
                       activate=True) -> dict:
    """Dealer + end user + agreement + product families.

    family_specs: (family_code, category, base_lead_time_days) triples; at
    most one per category (PRD §3.3 uniqueness). The default builds the
    SEATING base-28 family used across the design recipes.
    Returns {"dealer", "end_user", "agreement", "families": {category: fam}}.
    """
    dealer = create_dealer(
        api, territory_codes=list(territories), service_capability_level=capability
    )
    end_user = create_end_user(api)
    t1, t2, t3 = discounts
    agreement = create_volume_agreement(
        api, end_user["id"],
        effective_start=agreement_start, effective_end=agreement_end,
        tier1_discount_pct=t1, tier2_discount_pct=t2, tier3_discount_pct=t3,
    )
    if activate:
        agreement = activate_agreement(api, agreement["id"])
    families = {}
    for code, category, base in family_specs:
        families[category] = create_product_family(
            api, family_code=code, name=f"{category.title()} {code}",
            category=category, base_lead_time_days=base,
        )
    return {
        "dealer": dealer,
        "end_user": end_user,
        "agreement": agreement,
        "families": families,
    }


def setup_locked_world(api, modules=None, **world_kwargs) -> dict:
    """setup_dealer_world + one LOCKED configuration owned by the dealer.
    Adds ctx["configuration"]. Default modules: 4 x TASK_CHAIR_SET grade A
    (pre-discount 500000c, lead 31d at the SEATING-28 default family)."""
    ctx = setup_dealer_world(api, **world_kwargs)
    ctx["configuration"] = create_and_lock_configuration(
        api, ctx["dealer"]["id"], modules=modules
    )
    return ctx


def setup_submitted_order(api, modules=None, **order_kwargs) -> dict:
    """setup_locked_world + one order in SUBMITTED. Adds ctx["order"].
    order_kwargs: territory_code, requested_install_date, plus world kwargs."""
    world_keys = {"territories", "capability", "family_specs",
                  "agreement_start", "agreement_end", "discounts", "activate"}
    ctx = setup_locked_world(
        api, modules=modules,
        **{k: v for k, v in order_kwargs.items() if k in world_keys},
    )
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"],
        territory_code=order_kwargs.get("territory_code", "MI"),
        requested_install_date=order_kwargs.get(
            "requested_install_date", DEFAULT_REQUESTED_INSTALL_DATE
        ),
    )
    ctx["order"] = submit_order(api, order, ctx["dealer"]["id"])
    return ctx


def setup_acknowledged_order(api, modules=None, **order_kwargs) -> dict:
    """setup_submitted_order + manufacturer acknowledgment. ctx["order"] is
    ACKNOWLEDGED with final pricing cached; ctx["agreement"] is re-read so its
    cumulative_volume_cents includes the order."""
    ctx = setup_submitted_order(api, modules=modules, **order_kwargs)
    ctx["order"] = acknowledge_order(api, ctx["order"]["id"])
    ctx["agreement"] = get_agreement(api, ctx["agreement"]["id"])
    return ctx


def setup_scheduled_phase(api, *, planned_units=10, plant_code="PLANT_GR",
                          production_date=DEFAULT_PRODUCTION_DATE,
                          floor_number=1, phase_sequence=1,
                          building_zone_id="Z1", **order_kwargs) -> dict:
    """setup_acknowledged_order + one phase reserved (logistics SCHEDULED).
    Adds ctx["phase"]."""
    ctx = setup_acknowledged_order(api, **order_kwargs)
    phase = create_phase(
        api, ctx["order"]["id"], ctx["dealer"]["id"],
        floor_number=floor_number, phase_sequence=phase_sequence,
        building_zone_id=building_zone_id, planned_units=planned_units,
    )
    ctx["phase"] = reserve_slot(
        api, phase["id"], ctx["dealer"]["id"], plant_code, production_date
    )
    return ctx


def setup_phase_in_progress(api, *, production_date=DEFAULT_PRODUCTION_DATE,
                            **kwargs) -> dict:
    """setup_scheduled_phase + clock advanced to production_date +
    start-install. ctx["phase"] is DELIVERED / IN_PROGRESS."""
    ctx = setup_scheduled_phase(api, production_date=production_date, **kwargs)
    set_logical_clock(api, f"{production_date}T00:00:00Z")
    ctx["phase"] = start_install(api, ctx["phase"]["id"], ctx["dealer"]["id"])
    return ctx


def setup_completed_phase(api, *, complete_on=None,
                          production_date=DEFAULT_PRODUCTION_DATE,
                          **kwargs) -> dict:
    """setup_phase_in_progress + complete. If complete_on is given the clock
    advances to that date first, so actual_install_complete_date ==
    complete_on; otherwise completion happens on production_date.
    ctx["order"] is re-read (single-phase orders bubble to CLOSED)."""
    ctx = setup_phase_in_progress(api, production_date=production_date, **kwargs)
    if complete_on is not None:
        set_logical_clock(api, f"{complete_on}T00:00:00Z")
    ctx["phase"] = complete_phase(api, ctx["phase"]["id"], ctx["dealer"]["id"])
    ctx["order"] = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    return ctx


def acknowledge_chair_order(api, ctx, qty) -> dict:
    """Accumulate agreement volume: create + lock a qty x TASK_CHAIR_SET A
    configuration under ctx, then create + submit + acknowledge an order for
    it. Each chair contributes exactly 125000c pre-discount (PRD §2.7), so
    qty chairs move cumulative_volume_cents by qty * 125000. Returns the
    ACKNOWLEDGED order dict. Callers re-read the agreement afterwards."""
    spec = create_and_lock_configuration(
        api, ctx["dealer"]["id"],
        modules=[make_module_entry("TASK_CHAIR_SET", "A", qty)],
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    return acknowledge_order(api, submitted["id"])
