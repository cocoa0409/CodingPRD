"""Derived reads, refund tiers and the store/customer closure workflows."""
from test_helpers import E, get_success_data, validate_paginated, validate_success
from test_helpers.fixtures import (
    COMPLIANCE,
    READER,
    certify,
    create_jurisdiction,
    create_piercer,
    create_store,
    file_and_resolve_incident,
    get_appointment,
    get_piercer,
    get_store,
    open_explicit_session,
    set_clock,
    setup_customer_with_active_consent,
    setup_full_service,
    setup_ready_appointment,
    setup_store_with_certified_piercer,
)


def test_a_minor_severity_incident_finalizes_at_a_zero_refund(api):
    """PRD §3.7: "The refundable portion then depends on the incident's `severity`: `MINOR`
    yields 0; `MODERATE` yields the gross fee multiplied by 0.50 and floored to whole cents;
    `SEVERE` yields the gross fee multiplied by 0.75 and floored to whole cents".
    PRD §3.7: "The final variant runs at resolution, recomputes the gross fee from
    `base_fee_cents` plus the aftercare kit rule, applies the retention floor against the
    customer's lifetime `refunded_cents`, and overwrites `refund_amount_cents`."

    Design: Corner/calculations/incident_refund_minor_severity_yields_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    incident = file_and_resolve_incident(ctx["session"], severity="MINOR", reaction_codes=["REDNESS"])

    assert incident["escalation_status"] == "RESOLVED"
    assert incident["refund_amount_cents"] == 0


def test_a_severe_incident_refund_reflects_the_tier_rate_on_the_gross_fee(api):
    """PRD §3.7: "The gross fee is built from components in a pinned order: the session's
    `base_fee_cents` first, then an aftercare kit component of 1200 cents when
    `aftercare_kit_included` is true and 0 when it is false."
    PRD §3.7: "`SEVERE` yields the gross fee multiplied by 0.75 and floored to whole cents".

    Design: Corner/calculations/incident_refund_severe_tier_applies_the_retain_floor
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    session = ctx["session"]
    gross = session["base_fee_cents"] + 1200
    assert session["aftercare_kit_included"] is True

    incident = file_and_resolve_incident(session, severity="SEVERE", reaction_codes=["INFECTION"])

    # The tier rate gives the refundable portion, which is then capped so it can
    # never exceed the gross fee minus the non-refundable retention floor of
    # 500 cents (PRD 3.7).
    refundable = int(gross * 0.75)
    expected = min(refundable, gross - 500)
    assert incident["refund_amount_cents"] == expected
    assert incident["refund_amount_cents"] < gross


def test_the_stored_session_fee_reflects_the_upper_discount_tier(api):
    """PRD §3.5: "Third, the discount rate is selected from the pre-discount subtotal: 0.00 when
    the subtotal is below 4000 cents, 0.10 when it is at least 4000 cents and below 8000 cents,
    and 0.15 when it is at least 8000 cents."
    PRD §3.5: "Second, the pre-discount subtotal is `base_fee_cents` plus that aftercare
    component."

    Design: Corner/calculations/net_fee_second_tier_rate_observed_on_stored_session
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})

    _, response = open_explicit_session(
        ctx, base_fee_cents=10000, aftercare_kit_included=True, site_pierced="LOBE"
    )
    session = validate_success(response, 201)
    # pre-discount subtotal 11200 at the 0.15 tier leaves 9520, not the 0.10 result.
    assert session["net_fee_cents"] == 9520
    assert session["net_fee_cents"] != 10320

    stored = get_success_data(api.get_session(session["id"], READER))
    assert stored["net_fee_cents"] == 9520


def test_the_posture_read_reports_recomputed_derived_values(api):
    """PRD §2.7: "The store's posture read is itself a reconciliation point: reading a store's
    posture recomputes it before returning the store's `compliance_posture` and
    `open_incident_count`."

    Design: Corner/endpoints/posture_read_reports_derived_values_only
    """
    set_clock("2026-09-01T00:00:00Z")
    jurisdiction = create_jurisdiction(permitted_sites=["LOBE"])
    store = create_store(jurisdiction["id"], piercing_room_count=4)

    posture = validate_success(api.get_store_posture(store["id"], READER), 200)
    assert posture["compliance_posture"] == "OPEN"
    assert posture["open_incident_count"] == 0


def test_closing_a_store_cancels_open_appointments_and_suspends_piercers(api):
    """PRD §2.7: "closing cascades every `BOOKED` or `CONFIRMED` appointment at the store to
    `CANCELLED` and moves every `Piercer` whose `home_store_id` equals that store and whose
    `status` is `ACTIVE` to `SUSPENDED`."
    PRD §2.7: "Closing a store requires that no appointment at that store is in `CHECKED_IN`,
    `SCREENED` or `IN_SERVICE`".

    Design: Corner/endpoints/store_close_cancels_open_appointments_and_suspends_piercers
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service(store_overrides={"piercing_room_count": 2})
    assert get_piercer(ctx["piercer"]["id"])["status"] == "ACTIVE"

    open_appointment = setup_ready_appointment(
        ctx["store"]["id"], ctx["customer"]["id"], ctx["piercer"]["id"], ctx["jurisdiction"]["id"],
        slot_start="2026-09-01T11:00:00Z", slot_end="2026-09-01T11:30:00Z",
    )
    assert open_appointment["status"] == "CONFIRMED"

    closed = validate_success(api.close_store(ctx["store"]["id"], COMPLIANCE), 200)
    assert closed["status"] == "CLOSED"
    assert get_appointment(open_appointment["id"])["status"] == "CANCELLED"
    assert get_piercer(ctx["piercer"]["id"])["status"] == "SUSPENDED"


def test_a_higher_grade_certification_governs_the_piercer(api):
    """PRD §2.6: "Candidates are ranked by `certification_level_order` descending, where
    `INSTRUCTOR` ranks 4, `SENIOR` ranks 3, `STANDARD` ranks 2 and `APPRENTICE` ranks 1".

    Design: Corner/cross_cutting/piercer_selector_prefers_the_higher_certification_level
    """
    set_clock("2026-09-01T00:00:00Z")
    # A piercer holding a STANDARD certification added to an existing
    # APPRENTICE one: the selector must prefer the higher grade, and because a
    # STANDARD record is present the ACTIVE -> SUSPENDED fallback of §2.10 does
    # not fire.
    jurisdiction, store, piercer, _ = setup_store_with_certified_piercer(
        store_overrides={"piercing_room_count": 1}, certification_overrides={"certification_level": "STANDARD"}
    )
    standard = get_success_data(api.list_piercer_certifications(piercer["id"], READER))
    standard = standard if isinstance(standard, list) else standard.get("data", standard)
    standard_id = standard[0]["id"]

    apprentice = certify(piercer["id"], certification_level="APPRENTICE", issued_at="2026-08-02T00:00:00Z",
                         expires_at="2027-08-02T00:00:00Z")

    governed = get_piercer(piercer["id"])
    assert governed["active_certification_id"] == standard_id
    assert governed["active_certification_id"] != apprentice["id"]
    assert governed["status"] == "ACTIVE"


def test_session_listing_filters_by_cartridge_lot(api):
    """PRD §4: "| GET | `/piercing-services/sessions` | List sessions, optionally filtered by
    appointment, piercer or lot | `AnyAuthenticated` |"

    Design: Corner/cross_cutting/session_listing_filters_by_cartridge_lot
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_full_service()
    lot_id = ctx["lot"]["id"]

    data, meta = validate_paginated(
        api.list_sessions(READER, params={"cartridge_lot_id": lot_id})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    for session in data:
        assert session["cartridge_lot_id"] == lot_id