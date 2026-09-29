"""Two-dimensional build-zone state, and the MDU offer/counter negotiation loop."""

from test_helpers import (
    PM,
    ApiErrorId,
    CLOCK_EPOCH,
    api_client,
    assert_cents,
    assert_instant_equals,
    assert_pct,
    get_success_data,
    make_mdu_address,
    make_owner_account,
    make_permit,
    make_pole_request,
    make_mdu_owner_headers,
    mdu_agreement_payload,
    mdu_offer_payload,
    owner_response_payload,
    read_zone,
    set_clock,
    setup_campaign_with_zone,
    setup_zone_with_preorders,
    suspension_payload,
    validate_error,
    validate_success,
)

EXTENDED_DEADLINE = "2026-10-30T23:59:00Z"
CLOCK_AFTER_EXTENDED_DEADLINE = "2026-11-01T00:00:00Z"
NEGOTIATION_EXPIRY = "2026-09-15T00:00:00Z"


def _zone_extended_then_built():
    """One zone granted a deadline extension and then carried through to IN_CONSTRUCTION."""
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )
    zone_id = base["zone"]["id"]
    validate_success(api_client.extend_build_zone_deadline(zone_id, PM))
    make_permit(zone_id, permit_type="ROW", target_status="APPROVED", valid_days=200)
    make_pole_request(zone_id, target_status="ATTACHED", make_ready_cost_cents=12000)
    set_clock(CLOCK_AFTER_EXTENDED_DEADLINE)
    validate_success(api_client.qualification_run(base["campaign"]["id"], PM))
    validate_success(api_client.sequencing_run(base["campaign"]["id"], PM))
    validate_success(api_client.start_construction(zone_id, PM))
    return base


def test_deadline_extension_moves_only_the_campaign_dimension():
    """The grant flips PREREG_OPEN to PREREG_EXTENDED and leaves NOT_STARTED untouched.

    PRD 2.5: "Granting a deadline extension moves `campaign_status` and leaves
    `construction_status` exactly as it was; suspending construction moves
    `construction_status` and leaves `campaign_status` exactly as it was."

    Design: Difficulty/non_linear_state_machine/build_zone_parallel_campaign_and_construction_dimensions
    """
    base = setup_zone_with_preorders(
        preorder_count=1, household_count=10, threshold_pct=10.0
    )

    validate_success(api_client.extend_build_zone_deadline(base["zone"]["id"], PM))

    zone = read_zone(base["zone"]["id"])
    assert zone["campaign_status"] == "PREREG_EXTENDED", zone["campaign_status"]
    assert zone["construction_status"] == "NOT_STARTED", zone["construction_status"]
    assert zone["extension_count"] == 1, zone["extension_count"]
    assert zone["cumulative_extension_days"] == 30, zone["cumulative_extension_days"]
    assert_instant_equals(zone["prereg_deadline_at"], EXTENDED_DEADLINE, "prereg_deadline_at")


def test_suspension_moves_only_the_construction_dimension():
    """A manual suspension leaves the zone QUALIFIED while construction reads SUSPENDED.

    PRD 3.6: "Suspending moves `construction_status` `IN_CONSTRUCTION → SUSPENDED` and
    records the reason, defaulting to `MANUAL` when the caller supplies none"

    Design: Difficulty/non_linear_state_machine/build_zone_parallel_campaign_and_construction_dimensions
    """
    base = _zone_extended_then_built()

    validate_success(
        api_client.set_build_zone_suspension(
            base["zone"]["id"], suspension_payload("SUSPEND"), PM
        )
    )

    zone = read_zone(base["zone"]["id"])
    assert zone["construction_status"] == "SUSPENDED", zone["construction_status"]
    assert zone["suspension_reason"] == "MANUAL", zone["suspension_reason"]
    assert zone["readiness_posture"] == "SUSPENDED", zone["readiness_posture"]
    assert zone["campaign_status"] == "QUALIFIED", zone["campaign_status"]


def test_resume_clears_the_reason_and_restores_the_derived_posture():
    """Resuming returns the zone to IN_CONSTRUCTION with a null reason and READY posture.

    PRD 3.6: "It clears `suspension_reason` back to null, recomputes `readiness_posture` and
    increments the zone's `version` by 1."

    Design: Difficulty/non_linear_state_machine/build_zone_parallel_campaign_and_construction_dimensions
    """
    base = _zone_extended_then_built()
    zone_id = base["zone"]["id"]
    validate_success(
        api_client.set_build_zone_suspension(zone_id, suspension_payload("SUSPEND"), PM)
    )

    validate_success(
        api_client.set_build_zone_suspension(zone_id, suspension_payload("RESUME"), PM)
    )

    zone = read_zone(zone_id)
    assert zone["construction_status"] == "IN_CONSTRUCTION", zone["construction_status"]
    assert zone["suspension_reason"] is None, zone["suspension_reason"]
    assert zone["readiness_posture"] == "READY", zone["readiness_posture"]
    assert zone["campaign_status"] == "QUALIFIED", zone["campaign_status"]
    assert zone["extension_count"] == 1, zone["extension_count"]
    assert zone["cumulative_extension_days"] == 30, zone["cumulative_extension_days"]
    assert_pct(zone["final_rate_pct"], 10.00, "final_rate_pct")
    assert zone["build_sequence_index"] == 1, zone["build_sequence_index"]


def _agreement_with_one_counter_allowed():
    """A DRAFT agreement on an MDU address whose owner may counter exactly once."""
    set_clock()
    base = setup_campaign_with_zone()
    address = make_mdu_address(base["zone"]["id"], unit_count=24)
    owner = make_owner_account()
    agreement = get_success_data(
        api_client.create_mdu_agreement(
            mdu_agreement_payload(
                address["id"],
                owner["id"],
                access_fee_cents=250000,
                expires_at=NEGOTIATION_EXPIRY,
                max_counter_rounds=1,
            ),
            PM,
        )
    )
    return {
        "address": address,
        "owner": owner,
        "agreement": agreement,
        "owner_headers": make_mdu_owner_headers(owner["id"]),
    }


def _read_agreement(agreement_id):
    return validate_success(api_client.get_mdu_agreement(agreement_id, PM))


def test_offer_and_counter_alternate_between_sent_and_countered():
    """A counter returns the agreement to COUNTERED and the next offer drives it back to SENT.

    PRD 3.2: "Offer and counter therefore alternate, `SENT → COUNTERED → SENT`, for as
    many rounds as the cap allows, until the owner signs, declines, the clock passes
    `expires_at`, or `counter_round` reaches `max_counter_rounds`."

    Design: Difficulty/non_linear_state_machine/mdu_agreement_counter_offer_cycle_returns_to_sent
    """
    world = _agreement_with_one_counter_allowed()
    agreement_id = world["agreement"]["id"]
    assert world["agreement"]["status"] == "DRAFT", world["agreement"]["status"]
    assert world["agreement"]["offer_round"] == 0, world["agreement"]["offer_round"]
    assert world["agreement"]["counter_round"] == 0, world["agreement"]["counter_round"]
    assert world["agreement"]["countered_fee_cents"] is None

    first_offer = validate_success(
        api_client.create_mdu_offer(agreement_id, mdu_offer_payload(250000), PM)
    )
    assert first_offer["status"] == "SENT", first_offer["status"]
    assert first_offer["offer_round"] == 1, first_offer["offer_round"]

    countered = validate_success(
        api_client.mdu_owner_response(
            agreement_id,
            owner_response_payload("COUNTER", countered_fee_cents=200000),
            world["owner_headers"],
        )
    )
    assert countered["status"] == "COUNTERED", countered["status"]
    assert countered["counter_round"] == 1, countered["counter_round"]
    assert_cents(countered["countered_fee_cents"], 200000, "countered_fee_cents")

    second_offer = validate_success(
        api_client.create_mdu_offer(agreement_id, mdu_offer_payload(220000), PM)
    )
    assert second_offer["status"] == "SENT", second_offer["status"]
    assert second_offer["offer_round"] == 2, second_offer["offer_round"]
    assert_cents(second_offer["access_fee_cents"], 220000, "access_fee_cents")


def test_second_counter_past_the_cap_is_refused_and_leaves_the_agreement_in_sent():
    """With max_counter_rounds at 1 the owner's second counter is rejected, not absorbed.

    PRD 2.10: "**Counter cap.** The agreement's `counter_round` is strictly less than its
    `max_counter_rounds` before a counter is accepted; otherwise `ERR_COUNTER_LIMIT_REACHED`,
    on `POST /mdu-agreements/{id}/owner-response`."

    Design: Difficulty/non_linear_state_machine/mdu_agreement_counter_offer_cycle_returns_to_sent
    """
    world = _agreement_with_one_counter_allowed()
    agreement_id = world["agreement"]["id"]
    validate_success(
        api_client.create_mdu_offer(agreement_id, mdu_offer_payload(250000), PM)
    )
    validate_success(
        api_client.mdu_owner_response(
            agreement_id,
            owner_response_payload("COUNTER", countered_fee_cents=200000),
            world["owner_headers"],
        )
    )
    validate_success(
        api_client.create_mdu_offer(agreement_id, mdu_offer_payload(220000), PM)
    )

    response = api_client.mdu_owner_response(
        agreement_id,
        owner_response_payload("COUNTER", countered_fee_cents=210000),
        world["owner_headers"],
    )

    validate_error(response, ApiErrorId.ERR_COUNTER_LIMIT_REACHED)
    agreement = _read_agreement(agreement_id)
    assert agreement["status"] == "SENT", agreement["status"]
    assert agreement["counter_round"] == 1, agreement["counter_round"]
    assert agreement["offer_round"] == 2, agreement["offer_round"]
    assert_cents(agreement["countered_fee_cents"], 200000, "countered_fee_cents")


def test_signing_accepts_the_standing_offer_fee_and_not_the_countered_one():
    """The owner signs the 220,000-cent offer that is on the table, not their 200,000 counter.

    PRD 3.2: "What is signed is the standing `access_fee_cents`, not `countered_fee_cents` -
    a counter is a request, not an agreement, so an owner who signs while the row sits in
    `COUNTERED` accepts the operator's last offered fee."

    Design: Difficulty/non_linear_state_machine/mdu_agreement_counter_offer_cycle_returns_to_sent
    """
    world = _agreement_with_one_counter_allowed()
    agreement_id = world["agreement"]["id"]
    validate_success(
        api_client.create_mdu_offer(agreement_id, mdu_offer_payload(250000), PM)
    )
    validate_success(
        api_client.mdu_owner_response(
            agreement_id,
            owner_response_payload("COUNTER", countered_fee_cents=200000),
            world["owner_headers"],
        )
    )
    validate_success(
        api_client.create_mdu_offer(agreement_id, mdu_offer_payload(220000), PM)
    )

    signed = validate_success(
        api_client.mdu_owner_response(
            agreement_id, owner_response_payload("SIGN"), world["owner_headers"]
        )
    )

    assert signed["status"] == "SIGNED", signed["status"]
    assert_cents(signed["access_fee_cents"], 220000, "access_fee_cents")
    assert_instant_equals(signed["signed_at"], CLOCK_EPOCH, "signed_at")
