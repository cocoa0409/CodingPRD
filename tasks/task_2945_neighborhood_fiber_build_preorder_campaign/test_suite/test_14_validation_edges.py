"""Validation edges: admissibility gates, shape rules, ladder ordering and policy caps."""

from test_helpers import (
    CLOCK_EPOCH,
    PM,
    UNKNOWN_PREORDER_ID,
    ApiErrorId,
    api_client,
    assert_build_zone,
    assert_cents,
    assert_instant_equals,
    assert_instant_is_null,
    assert_mdu_agreement,
    assert_pct,
    assert_preorder,
    assert_service_address,
    assert_total_count,
    list_ledger_for_preorder,
    make_account,
    make_address,
    make_mdu_address,
    make_owner_account,
    make_preorder,
    make_subscriber_headers,
    mdu_agreement_payload,
    preorder_payload,
    read_account,
    read_address,
    read_preorder,
    read_zone,
    read_zone_version,
    service_address_payload,
    set_serviceability,
    setup_campaign_with_zone,
    setup_serviceable_address,
    threshold_payload,
    validate_error,
    validate_success,
)

PREREG_CLOSE = "2026-09-30T23:59:00Z"
EXTENDED_DEADLINE = "2026-10-30T23:59:00Z"


def test_an_unsurveyed_address_still_admits_a_sign_up_and_still_counts_toward_the_bar():
    """Nobody has been out to look at the property yet, and that is not a reason to refuse demand.

    PRD 2.10: "An `UNDETERMINED` address may still be preordered - that is the entire point of a
    fiberhood campaign - so only a definite negative determination blocks the operation."

    PRD 3.2: "It reads true when `serviceability` is `UNDETERMINED` or `SERVICEABLE`, and also when
    `serviceability` is `CONDITIONAL_MDU` and at least one MDU owner agreement for that address
    stands in status `SIGNED`."

    Design: Corner/validations/undetermined_address_may_still_be_preordered
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    address = make_address(zone_id, street_address="1 Elm St", distance_to_node_m=100)
    account = make_account(0)

    response = api_client.create_preorder(
        preorder_payload(
            zone_id, address["id"], account["id"], read_zone_version(zone_id)
        ),
        make_subscriber_headers(account["id"]),
    )

    preorder = validate_success(response, 201)
    assert_preorder(preorder)
    assert preorder["preorder_status"] == "PENDING", preorder["preorder_status"]
    assert preorder["deposit_status"] == "HELD", preorder["deposit_status"]
    assert preorder["counts_toward_threshold"] is True, preorder
    settled = read_address(address["id"])
    assert_service_address(settled)
    assert settled["serviceability"] == "UNDETERMINED", settled["serviceability"]
    assert_instant_is_null(
        settled["serviceability_determined_at"], "serviceability_determined_at"
    )
    assert settled["counts_toward_threshold"] is True, settled
    zone = read_zone(zone_id)
    assert_build_zone(zone)
    assert_pct(zone["prereg_rate_pct"], 10.00, "prereg_rate_pct")
    assert zone["provisional_qualifying_count"] == 1, zone
    assert zone["final_rate_pct"] is None, zone["final_rate_pct"]


def test_the_unit_count_rule_reads_the_dwelling_type_in_both_directions():
    """A one-unit tower and a four-unit house are both shape errors; only the real tower lands.

    PRD 3.2: "`unit_count` defaults to 1 and must be at least 1; beyond that it is constrained by
    the dwelling type, being exactly 1 for a `SINGLE_FAMILY` address and at least 2 for an `MDU`
    building."

    Design: Corner/validations/mdu_unit_count_rule_applies_only_to_mdu_addresses
    """
    base = setup_campaign_with_zone()
    zone_id = base["zone"]["id"]

    thin_tower = api_client.create_service_address(
        service_address_payload(
            zone_id,
            street_address="500 Birch Tower",
            dwelling_type="MDU",
            unit_count=1,
            distance_to_node_m=80,
        ),
        PM,
    )
    crowded_house = api_client.create_service_address(
        service_address_payload(zone_id, street_address="1 Elm St", unit_count=4), PM
    )

    validate_error(thin_tower, ApiErrorId.ERR_INVALID_REQUEST, 400)
    validate_error(crowded_house, ApiErrorId.ERR_INVALID_REQUEST, 400)

    accepted = validate_success(
        api_client.create_service_address(
            service_address_payload(
                zone_id,
                street_address="500 Birch Tower",
                dwelling_type="MDU",
                unit_count=24,
                distance_to_node_m=80,
            ),
            PM,
        ),
        201,
    )
    assert_service_address(accepted)
    assert accepted["unit_count"] == 24, accepted["unit_count"]
    assert accepted["dwelling_type"] == "MDU", accepted["dwelling_type"]
    assert_total_count(
        api_client.list_service_addresses(PM, params={"build_zone_id": zone_id}), 1
    )


def test_an_access_agreement_over_a_single_family_home_is_a_linkage_mismatch():
    """The negotiation only exists for buildings with an owner, so a house cannot host one.

    PRD 2.10: "Two references supplied in the same payload must agree with each other: on a
    preorder sign-up, the referenced address's `build_zone_id` equals the supplied
    `build_zone_id`; on an MDU agreement, the referenced address's `dwelling_type` is `MDU`; on a
    damage claim, the referenced appointment's preorder's `service_address_id` equals the supplied
    `service_address_id`; and on a restoration follow-up appointment, the referenced
    `parent_appointment_id` points at an appointment for the same `preorder_id`."

    Design: Corner/validations/mdu_agreement_against_a_single_family_address_returns_linkage_mismatch
    """
    base = setup_campaign_with_zone()
    zone_id = base["zone"]["id"]
    house = make_address(zone_id, street_address="1 Elm St", distance_to_node_m=100)
    tower = make_mdu_address(zone_id)
    owner = make_owner_account()

    response = api_client.create_mdu_agreement(
        mdu_agreement_payload(house["id"], owner["id"]), PM
    )

    validate_error(response, ApiErrorId.ERR_ADDRESS_LINKAGE_MISMATCH, 422)
    accepted = validate_success(
        api_client.create_mdu_agreement(
            mdu_agreement_payload(tower["id"], owner["id"]), PM
        ),
        201,
    )
    assert_mdu_agreement(accepted)
    assert accepted["status"] == "DRAFT", accepted["status"]
    assert_cents(accepted["access_fee_cents"], 250000, "access_fee_cents")
    assert_total_count(
        api_client.list_mdu_agreements(PM, params={"service_address_id": house["id"]}), 0
    )


def test_a_qualification_run_with_nothing_ripe_to_judge_is_refused_outright():
    """Every zone is still inside its window, so the run has no work and says so rather than passing.

    PRD 3.4: "Zones still inside their window are silently skipped rather than rejected; but when
    the campaign has no still-open zone whose deadline the clock has reached, the run itself is
    refused with `ERR_PREREG_DEADLINE_NOT_REACHED`."

    Design: Corner/validations/qualification_run_while_every_zone_is_inside_its_window_is_refused
    """
    base = setup_campaign_with_zone()
    zone_id = base["zone"]["id"]
    before = read_zone(zone_id)
    assert_instant_equals(
        before["prereg_deadline_at"], PREREG_CLOSE, "prereg_deadline_at"
    )

    response = api_client.qualification_run(base["campaign"]["id"], PM)

    validate_error(response, ApiErrorId.ERR_PREREG_DEADLINE_NOT_REACHED, 409)
    after = read_zone(zone_id)
    assert_build_zone(after)
    assert after["campaign_status"] == "PREREG_OPEN", after["campaign_status"]
    assert after["final_rate_pct"] is None, after["final_rate_pct"]
    assert after["final_qualifying_count"] is None, after["final_qualifying_count"]
    assert after["version"] == before["version"], after["version"]


def test_a_stranger_cancelling_a_row_that_does_not_exist_hears_about_the_row_first():
    """Existence sits above ownership on the ladder, so the same caller gets 404 then 403.

    PRD 2.10: "Because ownership is checked only after existence, a reference to a row that does
    not exist yields 404 rather than 403."

    Design: Corner/validations/existence_is_checked_before_ownership_on_preorder_cancel
    """
    base = setup_serviceable_address()
    owner_account = base["account"]
    stranger_account = make_account(1)
    preorder = make_preorder(
        base["zone"]["id"], base["address"]["id"], owner_account["id"]
    )
    stranger = make_subscriber_headers(stranger_account["id"])

    ghost = api_client.cancel_preorder(UNKNOWN_PREORDER_ID, stranger)
    trespass = api_client.cancel_preorder(preorder["id"], stranger)

    validate_error(ghost, ApiErrorId.ERR_PREORDER_NOT_FOUND, 404)
    validate_error(trespass, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
    reread = read_preorder(preorder["id"])
    assert_preorder(reread)
    assert reread["preorder_status"] == "PENDING", reread["preorder_status"]
    assert reread["deposit_status"] == "HELD", reread["deposit_status"]
    assert_cents(
        read_account(owner_account["id"])["deposit_held_cents"],
        1000,
        "owner.deposit_held_cents",
    )
    assert_cents(
        read_account(stranger_account["id"])["deposit_held_cents"],
        0,
        "stranger.deposit_held_cents",
    )


def test_an_overpaid_deposit_is_refused_without_disturbing_the_zone_version():
    """Paying too much is refused exactly like paying too little, and the retry reuses the version.

    PRD 3.3: "It tenders the deposit as `tendered_deposit_cents`, which must equal the campaign's
    `deposit_amount_cents` exactly - a partial payment and an overpayment are refused alike with
    `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    Design: Corner/validations/deposit_overpayment_is_the_last_complaint_a_preorder_hears
    """
    base = setup_serviceable_address()
    zone_id = base["zone"]["id"]
    account = base["account"]
    subscriber = make_subscriber_headers(account["id"])
    stale_version = read_zone_version(zone_id)

    overpaid = api_client.create_preorder(
        preorder_payload(
            zone_id,
            base["address"]["id"],
            account["id"],
            stale_version,
            tendered_deposit_cents=1500,
        ),
        subscriber,
    )

    validate_error(overpaid, ApiErrorId.ERR_DEPOSIT_AMOUNT_MISMATCH, 402)
    assert read_zone_version(zone_id) == stale_version, zone_id

    retry = validate_success(
        api_client.create_preorder(
            preorder_payload(
                zone_id, base["address"]["id"], account["id"], stale_version
            ),
            subscriber,
        ),
        201,
    )
    assert_preorder(retry)
    assert_cents(retry["deposit_amount_cents"], 1000, "deposit_amount_cents")
    assert retry["deposit_status"] == "HELD", retry["deposit_status"]
    entries, listing = list_ledger_for_preorder(retry["id"])
    assert_total_count(listing, 1)
    assert entries[0]["entry_type"] == "DEPOSIT_HELD", entries[0]


def test_the_bar_may_be_lowered_but_neither_raised_nor_left_where_it_stands():
    """Twelve is a raise and ten is a tie; only the genuine relief at eight is written.

    PRD 2.10: "A threshold adjustment may only lower the bar: the new `threshold_pct` is strictly
    less than the zone's current `threshold_pct` and is at least 0.01. Supplying a value greater
    than or equal to the current one is `ERR_THRESHOLD_INCREASE_FORBIDDEN`, on `PATCH
    /build-zones/{id}/threshold`."

    Design: Corner/validations/threshold_may_be_lowered_but_never_raised
    """
    base = setup_campaign_with_zone(
        zone_overrides={"household_count": 10, "threshold_pct": 10.0}
    )
    zone_id = base["zone"]["id"]
    version_before = read_zone_version(zone_id)

    raised = api_client.update_build_zone_threshold(zone_id, threshold_payload(12.0), PM)
    tied = api_client.update_build_zone_threshold(zone_id, threshold_payload(10.0), PM)

    validate_error(raised, ApiErrorId.ERR_THRESHOLD_INCREASE_FORBIDDEN, 409)
    validate_error(tied, ApiErrorId.ERR_THRESHOLD_INCREASE_FORBIDDEN, 409)

    lowered = validate_success(
        api_client.update_build_zone_threshold(zone_id, threshold_payload(8.0), PM), 200
    )
    assert_build_zone(lowered)
    assert_pct(lowered["threshold_pct"], 8.00, "threshold_pct")
    assert lowered["version"] == version_before + 1, lowered["version"]
    assert lowered["campaign_status"] == "PREREG_OPEN", lowered["campaign_status"]
    assert lowered["construction_status"] == "NOT_STARTED", lowered["construction_status"]


def test_a_sign_up_at_an_address_ruled_out_by_engineering_is_refused():
    """The determination is a definite negative, so no deposit is taken and no demand is recorded.

    PRD 3.3: "Sign-up is admissible only while the zone's preregistration window is open, only at
    an address whose `serviceability` is something other than `NOT_SERVICEABLE`, and only once per
    address-and-account pairing while an earlier preorder for that pairing is still `PENDING`,
    `QUALIFIED` or `CONVERTED`; a `CANCELLED` or `LAPSED` predecessor is no obstacle, and a second
    live sign-up is `ERR_DUPLICATE_PREORDER`."

    Design: Corner/validations/preorder_at_a_not_serviceable_address_is_refused
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    address = make_address(zone_id, street_address="7 Alley Ct", distance_to_node_m=140)
    ruled_out = set_serviceability(
        address["id"], "NOT_SERVICEABLE", not_serviceable_reason="NO_ROW_ACCESS"
    )
    account = make_account(0)

    response = api_client.create_preorder(
        preorder_payload(
            zone_id,
            address["id"],
            account["id"],
            read_zone_version(zone_id),
            plan_tier="GIGABIT_1000",
        ),
        make_subscriber_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ADDRESS_NOT_SERVICEABLE, 409)
    assert_service_address(ruled_out)
    assert ruled_out["not_serviceable_reason"] == "NO_ROW_ACCESS", ruled_out
    assert_instant_equals(
        ruled_out["serviceability_determined_at"],
        CLOCK_EPOCH,
        "serviceability_determined_at",
    )
    assert ruled_out["counts_toward_threshold"] is False, ruled_out
    zone = read_zone(zone_id)
    assert_build_zone(zone)
    assert zone["provisional_qualifying_count"] == 0, zone
    assert_pct(zone["prereg_rate_pct"], 0.00, "prereg_rate_pct")
    assert_cents(
        read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents"
    )


def test_the_one_permitted_extension_is_granted_by_policy_and_the_second_is_refused():
    """The client supplies no date at all, and the campaign's cap stops the second request dead.

    PRD 3.3: "An extension is admissible only while the zone's `extension_count` is strictly less
    than the campaign's `max_deadline_extensions`; the eleventh extension of a two-extension
    campaign is `ERR_EXTENSION_LIMIT_REACHED`."

    Design: Corner/validations/extension_beyond_the_campaign_limit_is_refused_and_the_grant_is_policy_driven
    """
    base = setup_campaign_with_zone(
        campaign_overrides={"max_deadline_extensions": 1, "extension_grant_days": 30},
        zone_overrides={"household_count": 10},
    )
    zone_id = base["zone"]["id"]

    granted = validate_success(api_client.extend_build_zone_deadline(zone_id, PM), 200)

    assert_build_zone(granted)
    assert_instant_equals(
        granted["prereg_deadline_at"], EXTENDED_DEADLINE, "prereg_deadline_at"
    )
    assert granted["extension_count"] == 1, granted["extension_count"]
    assert granted["cumulative_extension_days"] == 30, granted
    assert granted["campaign_status"] == "PREREG_EXTENDED", granted["campaign_status"]

    refused = api_client.extend_build_zone_deadline(zone_id, PM)

    validate_error(refused, ApiErrorId.ERR_EXTENSION_LIMIT_REACHED, 409)
    settled = read_zone(zone_id)
    assert_build_zone(settled)
    assert_instant_equals(
        settled["prereg_deadline_at"], EXTENDED_DEADLINE, "prereg_deadline_at"
    )
    assert settled["extension_count"] == 1, settled["extension_count"]
    assert settled["cumulative_extension_days"] == 30, settled
