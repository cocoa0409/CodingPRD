"""Warranty-window and parts-support-horizon boundaries (PRD §3.8, §3.3,
§2.9). Both windows are inclusive on the last eligible day; the parts-support
horizon gates PARTS claims of DISCONTINUED families independently.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    acknowledge_order,
    complete_phase,
    create_and_lock_configuration,
    create_order,
    create_phase,
    file_claim,
    make_dealer_headers,
    make_module_entry,
    make_warranty_claim_payload,
    set_logical_clock,
    setup_completed_phase,
    setup_dealer_world,
    start_install,
    submit_order,
    advance_family,
    reserve_slot,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def test_warranty_window_boundaries_ok_then_rejected(api):
    """PRD §3.8: "A `PARTS` claim is eligible only while its `filed_date` is
    on or before `actual_install_complete_date` plus 1826 days; a `LABOR`
    claim only while its `filed_date` is on or before
    `actual_install_complete_date` plus 366 days; a claim past its window is
    rejected with `ERR_WARRANTY_EXPIRED`." §2.9 step 5: "(`part_number` is
    required exactly when `requires_part` is true on a punch ticket, or when
    `claim_type` is `PARTS` on a warranty claim)" else ERR_VALIDATION.

    Design: Corner/validations/val_warranty_window_boundaries_ok_then_rejected
    """
    ctx = setup_completed_phase(api, complete_on="2026-12-01")
    order_id = ctx["order"]["id"]
    phase_id = ctx["phase"]["id"]
    dealer_id = ctx["dealer"]["id"]
    assert ctx["phase"]["actual_install_complete_date"] == "2026-12-01"

    # LABOR last eligible day: 2026-12-01 + 366 = 2027-12-02 (inclusive).
    set_logical_clock(api, "2027-12-02T00:00:00Z")
    claim = file_claim(
        api, order_id, phase_id, dealer_id,
        claim_type="LABOR", description="Re-level at last labor day",
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["filed_date"] == "2027-12-02"

    set_logical_clock(api, "2027-12-03T00:00:00Z")
    resp = api.create_warranty_claim(
        make_warranty_claim_payload(
            order_id, phase_id, claim_type="LABOR",
            description="One day too late",
        ),
        make_dealer_headers(dealer_id),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)

    # PARTS last eligible day: 2026-12-01 + 1826 = 2031-12-01 (inclusive).
    set_logical_clock(api, "2031-12-01T00:00:00Z")
    claim = file_claim(
        api, order_id, phase_id, dealer_id,
        claim_type="PARTS", part_number="PN-CHR-TASK",
        description="Last parts day",
    )
    assert claim["status"] == "SUBMITTED"

    set_logical_clock(api, "2031-12-02T00:00:00Z")
    resp = api.create_warranty_claim(
        make_warranty_claim_payload(
            order_id, phase_id, claim_type="PARTS",
            part_number="PN-CHR-TASK", description="One day past parts",
        ),
        make_dealer_headers(dealer_id),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)

    # A PARTS claim without part_number fails body-shape validation.
    resp = api.create_warranty_claim(
        make_warranty_claim_payload(
            order_id, phase_id, claim_type="PARTS",
            description="Missing part number",
        ),
        make_dealer_headers(dealer_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_parts_support_boundary_ok_then_rejected(api):
    """PRD §3.8: "a `PARTS` claim whose part belongs to a `DISCONTINUED`
    family must be filed on or before that family's `parts_support_until`;
    after the parts-support horizon the claim is rejected with
    `ERR_PARTS_SUPPORT_EXPIRED`." §3.3: moving to DISCONTINUED "requires the
    payload to carry a `parts_support_until` date at least 2557 days after
    the current clock date".

    Design: Corner/validations/val_parts_support_boundary_ok_then_rejected
    """
    ctx = setup_dealer_world(
        api,
        family_specs=(("SYS-7500", "SYSTEMS", 42),),
        agreement_end="2040-12-31",
    )
    family = ctx["families"]["SYSTEMS"]
    dealer_id = ctx["dealer"]["id"]

    spec = create_and_lock_configuration(
        api, dealer_id, modules=[make_module_entry("WORKSTATION_6X6", "A", 1)]
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], dealer_id,
        requested_install_date="2026-12-15",
    )
    order = submit_order(api, order, dealer_id)
    acknowledge_order(api, order["id"])
    phase = create_phase(api, order["id"], dealer_id, planned_units=10)
    # Reserve while the family is still CURRENT.
    reserve_slot(api, phase["id"], dealer_id, production_date="2026-11-02")

    # Drive the family CURRENT -> SUNSETTING -> DISCONTINUED; the horizon is
    # exactly clock(2026-10-05) + 2557 days = 2033-10-05 (leap days 2028,
    # 2032 inside the span).
    set_logical_clock(api, "2026-10-01T00:00:00Z")
    advance_family(api, family["id"], lifecycle_status="SUNSETTING",
                   last_order_date="2026-12-31")
    set_logical_clock(api, "2026-10-05T00:00:00Z")
    advance_family(api, family["id"], lifecycle_status="DISCONTINUED",
                   parts_support_until="2033-10-05")

    set_logical_clock(api, "2026-11-02T00:00:00Z")
    start_install(api, phase["id"], dealer_id)
    set_logical_clock(api, "2031-10-06T00:00:00Z")
    done = complete_phase(api, phase["id"], dealer_id)
    assert done["actual_install_complete_date"] == "2031-10-06"

    # The parts warranty window itself stays open well past these dates
    # (complete + 1826 days), so only the parts-support horizon decides here.
    set_logical_clock(api, "2033-10-05T00:00:00Z")
    claim = file_claim(
        api, order["id"], phase["id"], dealer_id,
        claim_type="PARTS", part_number="PN-FRM-66",
        description="Frame weld crack on last supported day",
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["filed_date"] == "2033-10-05"

    set_logical_clock(api, "2033-10-06T00:00:00Z")
    resp = api.create_warranty_claim(
        make_warranty_claim_payload(
            order["id"], phase["id"], claim_type="PARTS",
            part_number="PN-FRM-66",
            description="One day past support horizon",
        ),
        make_dealer_headers(dealer_id),
    )
    validate_error(resp, ApiErrorId.ERR_PARTS_SUPPORT_EXPIRED)
