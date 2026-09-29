"""Gates that read the state of a neighbouring entity before letting a transition through."""

from test_helpers import (
    PERMIT_OFFICE,
    PM,
    ApiErrorId,
    CLOCK_AFTER_DEADLINE,
    api_client,
    assert_cents,
    conversion_payload,
    make_account,
    make_address,
    make_campaign,
    make_mdu_address,
    make_mdu_agreement,
    make_owner_account,
    make_permit,
    make_pole_request,
    make_preorder,
    make_subscriber_headers,
    make_zone,
    permit_decision_payload,
    read_account,
    read_preorder,
    read_zone,
    set_clock,
    set_serviceability,
    validate_error,
    validate_success,
)

BOTH_PERMIT_TYPES = ["ROW", "TRAFFIC_CONTROL"]
POLE_QUOTE_FOR_ONE_RECIPIENT = 12000
POLE_QUOTE_FOR_TWO_RECIPIENTS = 24000


def _sequenced_zone_missing_one_permit_approval():
    """A sequenced zone holding an approved ROW permit and a merely submitted traffic permit."""
    set_clock()
    campaign = make_campaign(default_threshold_pct=10.0, deposit_amount_cents=1000)
    zone = make_zone(
        campaign["id"],
        household_count=10,
        threshold_pct=10.0,
        required_permit_types=list(BOTH_PERMIT_TYPES),
    )
    address = make_address(zone["id"], street_address="1 Elm St")
    address = set_serviceability(address["id"], "SERVICEABLE")
    account = make_account(0)
    preorder = make_preorder(zone["id"], address["id"], account["id"])
    approved = make_permit(
        zone["id"], permit_type="ROW", target_status="APPROVED", valid_days=200
    )
    pending = make_permit(
        zone["id"], permit_type="TRAFFIC_CONTROL", target_status="SUBMITTED"
    )
    make_pole_request(
        zone["id"],
        target_status="ATTACHED",
        make_ready_cost_cents=POLE_QUOTE_FOR_ONE_RECIPIENT,
    )
    set_clock(CLOCK_AFTER_DEADLINE)
    validate_success(api_client.qualification_run(campaign["id"], PM))
    validate_success(api_client.sequencing_run(campaign["id"], PM))
    return {
        "campaign": campaign,
        "zone": zone,
        "preorder": preorder,
        "account": account,
        "approved_permit": approved,
        "pending_permit": pending,
    }


def test_ground_break_is_refused_while_any_required_permit_type_lacks_approval():
    """One of two required permit types still sits at SUBMITTED, so the zone cannot break ground.

    PRD 3.6: "Two readiness gates then apply, in this order: first every permit type in
    `required_permit_types` must have an application in status `APPROVED` whose `expires_at` is
    strictly after the logical clock, failing which the attempt is `ERR_PERMIT_READINESS_UNMET`"

    Design: Difficulty/cross_entity_state_dependency/construction_start_blocked_until_every_required_permit_is_approved
    """
    world = _sequenced_zone_missing_one_permit_approval()

    response = api_client.start_construction(world["zone"]["id"], PM)

    validate_error(response, ApiErrorId.ERR_PERMIT_READINESS_UNMET)
    zone = read_zone(world["zone"]["id"])
    assert zone["construction_status"] == "SEQUENCED", zone["construction_status"]
    assert zone["readiness_posture"] == "PERMIT_PENDING", zone["readiness_posture"]
    assert read_preorder(world["preorder"]["id"])["make_ready_share_cents"] is None


def test_approving_the_outstanding_permit_unblocks_the_identical_ground_break_call():
    """Nothing about the request changes; approving the second permit is what lets it through.

    PRD 2.10: "**Permit readiness.** Every permit type in the zone's `required_permit_types`
    has a permit application in status `APPROVED` whose `expires_at` is strictly after the
    logical clock."

    Design: Difficulty/cross_entity_state_dependency/construction_start_blocked_until_every_required_permit_is_approved
    """
    world = _sequenced_zone_missing_one_permit_approval()
    validate_error(
        api_client.start_construction(world["zone"]["id"], PM),
        ApiErrorId.ERR_PERMIT_READINESS_UNMET,
    )
    validate_success(
        api_client.decide_permit_application(
            world["pending_permit"]["id"],
            permit_decision_payload("APPROVE"),
            PERMIT_OFFICE,
        )
    )

    validate_success(api_client.start_construction(world["zone"]["id"], PM))

    zone = read_zone(world["zone"]["id"])
    assert zone["construction_status"] == "IN_CONSTRUCTION", zone["construction_status"]
    assert zone["readiness_posture"] == "READY", zone["readiness_posture"]
    assert_cents(
        read_preorder(world["preorder"]["id"])["make_ready_share_cents"],
        POLE_QUOTE_FOR_ONE_RECIPIENT,
        "make_ready_share_cents",
    )


def _mdu_preorder_ready_to_convert():
    """A zone mid-build holding one MDU preorder whose building has no signed agreement yet."""
    set_clock()
    campaign = make_campaign(default_threshold_pct=10.0, deposit_amount_cents=1000)
    zone = make_zone(campaign["id"], household_count=10, threshold_pct=10.0)
    mdu_address = make_mdu_address(zone["id"], unit_count=24)
    single_address = make_address(zone["id"], street_address="1 Elm St")
    single_address = set_serviceability(single_address["id"], "SERVICEABLE")
    mdu_account = make_account(0)
    single_account = make_account(1)
    mdu_preorder = make_preorder(
        zone["id"], mdu_address["id"], mdu_account["id"], unit_designator="12B"
    )
    make_preorder(zone["id"], single_address["id"], single_account["id"])
    make_permit(zone["id"], permit_type="ROW", target_status="APPROVED", valid_days=200)
    make_pole_request(
        zone["id"],
        target_status="ATTACHED",
        make_ready_cost_cents=POLE_QUOTE_FOR_TWO_RECIPIENTS,
    )
    set_clock(CLOCK_AFTER_DEADLINE)
    validate_success(api_client.qualification_run(campaign["id"], PM))
    validate_success(api_client.sequencing_run(campaign["id"], PM))
    validate_success(api_client.start_construction(zone["id"], PM))
    return {
        "campaign": campaign,
        "zone": zone,
        "mdu_address": mdu_address,
        "mdu_account": mdu_account,
        "mdu_preorder": mdu_preorder,
        "owner": make_owner_account(),
        "subscriber_headers": make_subscriber_headers(mdu_account["id"]),
    }


def test_conversion_at_an_mdu_address_is_refused_without_an_owner_signature():
    """The building may collect preorders, but it cannot be built into unsigned.

    PRD 3.7: "And where the address's `dwelling_type` is `MDU`, some MDU owner agreement for
    that address must stand in status `SIGNED`; a `CONDITIONAL_MDU` address may collect
    preorders all campaign long but cannot be built into without the owner's signature, and the
    attempt is `ERR_MDU_AGREEMENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/mdu_conversion_blocked_until_owner_agreement_is_signed
    """
    world = _mdu_preorder_ready_to_convert()

    response = api_client.convert_preorder(
        world["mdu_preorder"]["id"],
        conversion_payload("BURY"),
        world["subscriber_headers"],
    )

    validate_error(response, ApiErrorId.ERR_MDU_AGREEMENT_REQUIRED)
    preorder = read_preorder(world["mdu_preorder"]["id"])
    assert preorder["preorder_status"] == "QUALIFIED", preorder["preorder_status"]
    assert preorder["deposit_status"] == "HELD", preorder["deposit_status"]
    assert preorder["drop_method"] is None, preorder["drop_method"]
    assert preorder["conversion_total_due_cents"] is None


def test_signing_the_agreement_lets_the_same_conversion_settle_in_full():
    """With the signature in hand the settlement runs to 36,900 less 1,845 less the deposit.

    PRD 2.10: "**MDU signature at conversion.** For an address whose `dwelling_type` is `MDU`,
    conversion requires an MDU owner agreement for that address in status `SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/mdu_conversion_blocked_until_owner_agreement_is_signed
    """
    world = _mdu_preorder_ready_to_convert()
    validate_error(
        api_client.convert_preorder(
            world["mdu_preorder"]["id"],
            conversion_payload("BURY"),
            world["subscriber_headers"],
        ),
        ApiErrorId.ERR_MDU_AGREEMENT_REQUIRED,
    )
    agreement = make_mdu_agreement(
        world["mdu_address"]["id"], world["owner"]["id"], target_status="SIGNED"
    )
    assert agreement["status"] == "SIGNED", agreement["status"]

    converted = validate_success(
        api_client.convert_preorder(
            world["mdu_preorder"]["id"],
            conversion_payload("BURY"),
            world["subscriber_headers"],
        )
    )

    assert converted["preorder_status"] == "CONVERTED", converted["preorder_status"]
    assert converted["deposit_status"] == "APPLIED", converted["deposit_status"]
    assert_cents(
        converted["make_ready_share_cents"],
        POLE_QUOTE_FOR_ONE_RECIPIENT,
        "make_ready_share_cents",
    )
    assert_cents(
        converted["conversion_pre_discount_total_cents"],
        36900,
        "conversion_pre_discount_total_cents",
    )
    assert_cents(converted["conversion_discount_cents"], 1845, "conversion_discount_cents")
    assert_cents(converted["conversion_total_due_cents"], 34055, "conversion_total_due_cents")
    assert_cents(
        read_account(world["mdu_account"]["id"])["deposit_held_cents"], 0, "deposit_held_cents"
    )
