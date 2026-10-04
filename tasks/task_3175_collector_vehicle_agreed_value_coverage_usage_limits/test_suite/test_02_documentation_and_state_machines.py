"""Photographic dossier and state-machine corner tests."""
from test_helpers import (
    REQUIRED_PHOTO_TYPES,
    TEST_USERS,
    ApiErrorId,
    accept_photos,
    create_guide_tool_valuation,
    create_member,
    create_photo_payload,
    create_published_guide,
    create_vehicle,
    evaluate_vehicle,
    get_vehicle,
    make_member_headers,
    propose_and_approve,
    setup_documented_vehicle,
    submit_all_photos,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_photo_accept_side_effect_completes_documentation(api):
    """PRD §3.3: "After each review the vehicle's documentation dimension is
    recomputed: `accepted_photo_count` counts the vehicle's photos in
    `ACCEPTED` status, and `documentation_status` becomes `COMPLETE` exactly
    when all eight required types are accepted, remaining `INCOMPLETE`
    otherwise."

    Design: Corner/state_machines/photo_accept_side_effect_completes_documentation
    """
    member, m_headers = create_member(full_name="Wes", email="wes@x.com")
    vehicle = create_vehicle(member, vin="VIN104")
    photos = submit_all_photos(vehicle["id"], m_headers)
    # Accept only 7 of the 8 types first.
    accept_photos(vehicle["id"], photos, only_types=set(REQUIRED_PHOTO_TYPES) - {"VIN_PLATE"})
    before = get_vehicle(vehicle["id"])
    assert before["documentation_status"] == "INCOMPLETE"
    assert before["accepted_photo_count"] == 7

    validate_success(
        api.review_photo(
            vehicle["id"], photos["VIN_PLATE"]["id"], {"decision": "ACCEPT"}, UW
        )
    )
    after = get_vehicle(vehicle["id"])
    assert after["documentation_status"] == "COMPLETE", (
        "Accepting the 8th distinct photo type must flip documentation to COMPLETE"
    )
    assert after["accepted_photo_count"] == 8


def test_photo_type_duplicate_rejected(api):
    """PRD §3.3: "At most one photo per type may be live at a time — a second
    submission in `SUBMITTED` or `ACCEPTED` status for a type that already has
    one is rejected with `ERR_PHOTO_TYPE_DUPLICATE`."

    Design: Corner/validations/photo_type_duplicate_rejected
    """
    member, m_headers = create_member(full_name="Ida", email="ida@x.com")
    vehicle = create_vehicle(member, vin="VIN122")
    validate_success(
        api.submit_photo(
            vehicle["id"],
            create_photo_payload(photo_type="FRONT", image_ref="img://f1"),
            m_headers,
        ),
        expected_status=201,
    )
    resp = api.submit_photo(
        vehicle["id"],
        create_photo_payload(photo_type="FRONT", image_ref="img://f2",
                             captured_at="2026-09-02T00:00:00Z"),
        m_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PHOTO_TYPE_DUPLICATE)


def test_guide_publish_from_published_rejected(api):
    """PRD §3.4: "the guide begins in `DRAFT`."
    PRD §2.8: "State-transition legality is checked next
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/guide_publish_from_published_rejected
    """
    guide = create_published_guide()
    assert guide["status"] == "PUBLISHED"
    resp = api.publish_guide(guide["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_valuation_terminal_reject_lockdown(api):
    """PRD §3.5: "A proposed valuation can be sent back to `DRAFT` for
    revision, optionally carrying a new `proposed_agreed_value_cents` to be
    re-set on the next proposal, or rejected outright to `REJECTED`."
    PRD §2.8: "State-transition legality is checked next
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/valuation_terminal_reject_lockdown
    """
    member, m_headers = create_member(full_name="Val", email="val@x.com")
    vehicle = create_vehicle(member, vin="VIN103")
    create_published_guide()
    valuation = create_guide_tool_valuation(vehicle["id"], 3_000_000)
    validate_success(api.propose_valuation(valuation["id"], UW))
    rejected = validate_success(api.reject_valuation(valuation["id"], UW))
    assert rejected["status"] == "REJECTED"
    resp = api.approve_valuation(valuation["id"], {}, UW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_usage_event_reverse_idempotent_second_reverse_rejected(api):
    """PRD §3.7: "The member may reverse a recorded event, moving it to
    `REVERSED`".
    PRD §2.8: "State-transition legality is checked next
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/usage_event_reverse_idempotent_second_reverse_rejected
    """
    from test_helpers import record_usage_ok, setup_active_policy

    ctx = setup_active_policy()
    event = record_usage_ok(ctx, 100, "2026-10-01T00:00:00Z")
    reversed_event = validate_success(
        api.reverse_usage_event(event["id"], ctx["member_headers"])
    )
    assert reversed_event["status"] == "REVERSED"
    resp = api.reverse_usage_event(event["id"], ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
