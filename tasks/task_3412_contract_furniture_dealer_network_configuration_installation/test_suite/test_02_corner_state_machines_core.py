"""State-machine core: initial states on create, invalid transitions, and
terminal-state lockdown for orders and product families (PRD §3.1-§3.7)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_configuration,
    activate_agreement,
    create_configuration,
    create_dealer,
    create_end_user,
    create_order,
    create_phase,
    create_product_family,
    create_volume_agreement,
    get_order,
    make_dealer_headers,
    make_install_window_payload,
    make_submit_payload,
    setup_acknowledged_order,
    setup_dealer_world,
    setup_locked_world,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_initial_states_on_create(api):
    """PRD §3.1: "A new dealer starts in `ACTIVE` status". PRD §3.2: "A new
    agreement is `DRAFT`, with `cumulative_volume_cents` at 0 and
    `current_tier` at 1." PRD §3.3: "A new family's `lifecycle_status` is
    `CURRENT`." PRD §3.4: "the spec starts in `DRAFT` with `revision_number`
    1." PRD §3.5: "the order starts in `DRAFT`."

    Design: Corner/state_machines/sm_initial_states_on_create
    """
    family = create_product_family(
        api, family_code="SEAT-2200", name="Seating 2200",
        category="SEATING", base_lead_time_days=28,
    )
    assert family["lifecycle_status"] == "CURRENT"

    dealer = create_dealer(api, name="Dealer Alpha", service_capability_level=4)
    assert dealer["status"] == "ACTIVE"

    end_user = create_end_user(api, name="MegaCorp")
    agreement = create_volume_agreement(api, end_user["id"])
    assert agreement["status"] == "DRAFT"
    assert agreement["cumulative_volume_cents"] == 0
    assert agreement["current_tier"] == 1

    spec = create_configuration(api, dealer["id"], name="Chairs")
    assert_configuration(spec)
    assert spec["status"] == "DRAFT"
    assert spec["revision_number"] == 1

    activate_agreement(api, agreement["id"])
    order = create_order(api, agreement["id"], spec["id"], dealer["id"])
    assert order["status"] == "DRAFT"


def test_revise_from_draft_rejected(api):
    """PRD §3.4: "Attempting to revise a spec that is still `DRAFT` is an
    invalid transition rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_revise_from_draft_rejected
    """
    dealer = create_dealer(api)
    create_product_family(api, category="SEATING", base_lead_time_days=28)
    spec = create_configuration(api, dealer["id"], name="Chairs")
    assert spec["status"] == "DRAFT"

    resp = api.revise_configuration(spec["id"], make_dealer_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = validate_success(
        api.get_configuration(spec["id"], make_dealer_headers(dealer["id"])), 200
    )
    assert reread["status"] == "DRAFT"
    assert reread["revision_number"] == 1


def test_cancelled_order_terminal_rejects_submit(api):
    """PRD §3.5: "Cancelling a `CLOSED` order — or any other state outside
    those four — is rejected with `ERR_INVALID_STATE`." Submission requires
    the order be `DRAFT` (else `ERR_INVALID_STATE`), so a `CANCELLED` order
    stays terminal.

    Design: Corner/state_machines/sm_cancelled_order_terminal_rejects_submit
    """
    ctx = setup_locked_world(api)
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"],
    )
    cancelled = validate_success(
        api.cancel_project_order(
            order["id"], {"reason": "no budget"},
            make_dealer_headers(ctx["dealer"]["id"]),
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"

    resp = api.submit_project_order(
        order["id"], make_submit_payload(cancelled["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_order(
        api, order["id"], make_dealer_headers(ctx["dealer"]["id"])
    )["status"] == "CANCELLED"


def test_family_lifecycle_reverse_rejected(api):
    """PRD §3.3: "Lifecycle is forward-only: `CURRENT → SUNSETTING →
    DISCONTINUED`, with no skipping and no reverse. Any other step —
    `CURRENT` straight to `DISCONTINUED`, or `SUNSETTING` back to `CURRENT` —
    is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION`."

    Design: Corner/state_machines/sm_family_lifecycle_reverse_rejected
    """
    fam_sys = create_product_family(
        api, family_code="SYS-7500", name="Systems 7500",
        category="SYSTEMS", base_lead_time_days=42,
    )
    fam_seat = create_product_family(
        api, family_code="SEAT-2200", name="Seating 2200",
        category="SEATING", base_lead_time_days=28,
    )

    # CURRENT -> DISCONTINUED skips SUNSETTING (valid parts horizon supplied so
    # only the forward-only rule can fail).
    resp = api.update_product_family(
        fam_seat["id"],
        {"lifecycle_status": "DISCONTINUED", "parts_support_until": "2033-09-01"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_TRANSITION)

    # Drive SYS-7500 to SUNSETTING, then attempt the reverse step.
    sunset = validate_success(
        api.update_product_family(
            fam_sys["id"],
            {"lifecycle_status": "SUNSETTING", "last_order_date": "2026-12-31"},
            ADMIN,
        ),
        200,
    )
    assert sunset["lifecycle_status"] == "SUNSETTING"
    resp = api.update_product_family(
        fam_sys["id"], {"lifecycle_status": "CURRENT"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_LIFECYCLE_TRANSITION)


def test_window_on_planned_phase_rejected(api):
    """PRD §3.7: "The owning `DealerRep` creates an `InstallWindow` against a
    phase whose `logistics_status` is `SCHEDULED` or `DELIVERED` — booking a
    window against a `PLANNED` phase is rejected with `ERR_INVALID_STATE`"
    (the sentence then continues with the window's input fields).

    Design: Corner/state_machines/sm_window_on_planned_phase_rejected
    """
    ctx = setup_acknowledged_order(api)
    phase = create_phase(api, ctx["order"]["id"], ctx["dealer"]["id"])
    assert phase["logistics_status"] == "PLANNED"

    resp = api.create_install_window(
        make_install_window_payload(phase["id"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
