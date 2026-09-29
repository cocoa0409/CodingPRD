"""The refusal catalogue of the fair grandstand entertainment booking service.

Every test here drives one family of refusals end to end through the public API
and pins three things at once: the identifier the PRD names for the rule, the
HTTP status the error catalogue fixes for that identifier, and -- where two
rules would fire on the same request -- which of them the service is required to
report. Each test builds the whole world it needs, because the database is reset
between tests.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.factories import (
    build_activation_payload,
    build_announce_payload,
    build_contingency_action_payload,
    build_counter_payload,
    build_offer_payload,
    build_reschedule_payload,
    build_sales_batch_payload,
    build_settlement_payload,
)
from test_helpers.test_users import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SETTLEMENT_CONTROLLER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_HEADERS,
    make_talent_agent_headers,
)

# Identity headers built by hand rather than through the role helpers, because
# the point of the first test is that these are exactly the shapes the service
# must refuse before it looks at anything else.
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": "someone-01",
    "X-User-Role": "StageHand",
    "Content-Type": "application/json",
}
BLANK_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": "TalentBuyer",
    "Content-Type": "application/json",
}
WRONG_CASE_ROLE_HEADERS = {
    "X-User-ID": "buyer-01",
    "X-User-Role": "talentbuyer",
    "Content-Type": "application/json",
}


def test_undeclared_blank_or_wrong_case_identity_headers_are_unauthenticated():
    """The identity gate is the very first thing the service evaluates, so a
    role string outside the declared seven, an empty user identifier and a
    lower-case spelling of a real role are all authentication failures rather
    than authorization or lookup failures. The edition list is the probe
    because an empty list is a perfectly good answer, so any refusal is
    attributable to the headers alone.

    "If either header is absent or empty, or if `X-User-Role` is not one of the
    seven role names below, the request is refused with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/unknown_or_blank_identity_headers_are_unauthenticated
    """
    fixtures.set_clock()

    for headers in (
        UNDECLARED_ROLE_HEADERS,
        BLANK_USER_ID_HEADERS,
        WRONG_CASE_ROLE_HEADERS,
    ):
        response = api_client.list_fair_editions(headers)
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert response.json()["response_type"] == "error"
        assert set(error.keys()) == {"error_id", "message"}

    data, meta = validate_paginated(api_client.list_fair_editions(TALENT_BUYER_HEADERS))
    assert data == []
    assert meta["total_count"] == 0


def test_wrong_role_on_another_roles_exclusive_write_is_forbidden():
    """Once the headers are well formed the service checks whether the named
    role is admitted by the operation, and that check runs before any resource
    is looked up: a fictitious path identifier still yields the role refusal
    rather than a not-found. Reads the role does hold remain open throughout.

    "If the headers are well formed but the named role is not among the roles
    the target operation admits, the request is refused with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/errors/roles_cannot_reach_other_roles_exclusive_writes
    """
    world = fixtures.setup_base_world()
    absent_id = "00000000-0000-4000-8000-00000000dead"

    validate_error(
        api_client.create_fair_edition(
            {
                "year": 2027,
                "name": "State Fair 2027",
                "run_start_date": "2027-08-20",
                "run_end_date": "2027-08-30",
                "gate_admission_price_cents": 1500,
                "talent_budget_cap_cents": 40000000,
                "refund_reserve_cents": 15000000,
                "max_shows_per_day": 2,
                "curfew_utc_time": "23:30",
                "strategy_basis": "ATTENDANCE_WEIGHTED",
            },
            BOX_OFFICE_MANAGER_HEADERS,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    validate_error(
        api_client.create_offer(
            build_offer_payload(
                world["edition"]["id"], world["artist"]["id"], world["stage"]["id"]
            ),
            SETTLEMENT_CONTROLLER_HEADERS,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    validate_error(
        api_client.rule_rider_item(
            absent_id, {"decision": "APPROVED"}, TALENT_BUYER_HEADERS
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    validate_error(
        api_client.announce_show_booking(
            absent_id,
            {"doors_time_utc": TEST_DEFAULTS["DOORS_TIME_UTC"]},
            PRODUCTION_MANAGER_HEADERS,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
    )

    data, meta = validate_paginated(
        api_client.list_fair_editions(BOX_OFFICE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert len(data) == 1


def test_unknown_agent_identity_and_foreign_roster_are_both_forbidden():
    """The agent role is the one identity the service resolves against a stored
    record. An identifier matching no agent at all and an identifier matching a
    real agent who does not represent the act on the offer are two different
    refusals, and the roster rule guards every agent-side trigger rather than
    acceptance alone. The rightful agent then succeeds on the same request.

    "an identity that resolves to no agent record is refused with
    `ERR_UNKNOWN_ACTOR_IDENTITY` (HTTP 403)" -- while "a mismatch is refused
    with `ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST` (HTTP 403), because an agent may
    only counter, accept or decline for acts on its own roster."

    Design: Corner/errors/unknown_agent_identity_and_foreign_roster_are_both_forbidden
    """
    scenario = fixtures.setup_sent_offer()
    fixtures.create_agent(
        user_id="agent-mara",
        agency_name="Mara Artists",
        contact_email="deals@mara.example",
    )
    offer_id = scenario["offer"]["id"]

    validate_error(
        api_client.accept_offer(offer_id, make_talent_agent_headers("agent-ghost")),
        ApiErrorId.ERR_UNKNOWN_ACTOR_IDENTITY.value,
    )
    validate_error(
        api_client.accept_offer(offer_id, make_talent_agent_headers("agent-mara")),
        ApiErrorId.ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST.value,
    )
    validate_error(
        api_client.counter_offer(
            offer_id,
            build_counter_payload(13_000_000, note="Not my artist"),
            make_talent_agent_headers("agent-mara"),
        ),
        ApiErrorId.ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST.value,
    )

    accepted = validate_success(
        api_client.accept_offer(offer_id, scenario["agent_headers"]), 200
    )
    assert accepted["status"] == "ACCEPTED"
    assert fixtures.get_offer(offer_id)["round_count"] == 1


def test_each_absent_identifier_reports_its_own_not_found_code():
    """Twelve identifiers, twelve dedicated refusals: against an otherwise empty
    database each probe names a syntactically valid identifier that was never
    issued, and each comes back with the code belonging to that identifier
    rather than a shared generic one. The roles are chosen so that the role gate
    cannot pre-empt the lookup, and the refused artist create leaves no row.

    "Each identifier has a dedicated not-found error, and the identifier may
    arrive either in the path or in the body without changing which error is
    reported."

    Design: Corner/errors/every_absent_parent_id_yields_its_own_not_found_code
    """
    fixtures.set_clock()

    probes = (
        (
            ApiErrorId.ERR_FAIR_EDITION_NOT_FOUND.value,
            lambda: api_client.get_buying_strategy_report(
                "00000000-0000-4000-8000-000000000001", TALENT_BUYER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_STAGE_NOT_FOUND.value,
            lambda: api_client.get_stage(
                "00000000-0000-4000-8000-000000000002", TALENT_BUYER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_TALENT_AGENT_NOT_FOUND.value,
            lambda: api_client.create_artist(
                {
                    "agent_id": "00000000-0000-4000-8000-000000000003",
                    "name": "Ghost Roster",
                    "genre": "ROCK",
                    "audience_segment": "YOUNG_ADULT",
                    "base_draw_score": 50.00,
                },
                TALENT_BUYER_HEADERS,
            ),
        ),
        (
            ApiErrorId.ERR_ARTIST_NOT_FOUND.value,
            lambda: api_client.get_artist(
                "00000000-0000-4000-8000-000000000004", TALENT_BUYER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_OFFER_NOT_FOUND.value,
            lambda: api_client.get_offer(
                "00000000-0000-4000-8000-000000000005", TALENT_BUYER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_SHOW_BOOKING_NOT_FOUND.value,
            lambda: api_client.get_show_booking(
                "00000000-0000-4000-8000-000000000006", TALENT_BUYER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_TICKET_SCALE_NOT_FOUND.value,
            lambda: api_client.get_ticket_scale(
                "00000000-0000-4000-8000-000000000007", BOX_OFFICE_MANAGER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_PRODUCTION_ADVANCE_NOT_FOUND.value,
            lambda: api_client.get_production_advance(
                "00000000-0000-4000-8000-000000000008", PRODUCTION_MANAGER_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_RIDER_ITEM_NOT_FOUND.value,
            lambda: api_client.rule_rider_item(
                "00000000-0000-4000-8000-000000000009",
                {"decision": "APPROVED"},
                PRODUCTION_MANAGER_HEADERS,
            ),
        ),
        (
            ApiErrorId.ERR_SPONSOR_NOT_FOUND.value,
            lambda: api_client.get_sponsor(
                "00000000-0000-4000-8000-00000000000a", SPONSORSHIP_DIRECTOR_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_ACTIVATION_NOT_FOUND.value,
            lambda: api_client.get_sponsorship_activation(
                "00000000-0000-4000-8000-00000000000b", SPONSORSHIP_DIRECTOR_HEADERS
            ),
        ),
        (
            ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value,
            lambda: api_client.get_settlement(
                "00000000-0000-4000-8000-00000000000c", SETTLEMENT_CONTROLLER_HEADERS
            ),
        ),
    )

    reported = []
    for expected_error_id, probe in probes:
        error = validate_error(probe(), expected_error_id)
        reported.append(error["error_id"])

    assert len(set(reported)) == 12, f"codes are not pairwise distinct: {reported}"

    _, artists_meta = validate_paginated(api_client.list_artists(TALENT_BUYER_HEADERS))
    assert artists_meta["total_count"] == 0


def test_confirm_on_cancelled_activation_and_approve_on_draft_settlement_are_state_errors():
    """A cancelled activation is terminal, so both confirmation and a second
    cancellation are refused, and the record keeps the fee it was priced at. On
    the settlement side the approval arc starts at pending approval, so skipping
    submission is a state refusal and not a separation-of-duties refusal even
    though no submitter has been stamped yet.

    "confirmation is admitted only from `PROPOSED` while cancellation is
    admitted from `PROPOSED` or `CONFIRMED`; anything else is refused with
    `ERR_INVALID_ACTIVATION_STATE`"

    Design: Corner/errors/confirm_on_cancelled_activation_and_approve_on_draft_settlement_rejected
    """
    scenario = fixtures.setup_announced_booking(
        scale_overrides={"allotment_seats": 2000, "facility_fee_cents": 400}
    )
    booking_id = scenario["booking"]["id"]
    sponsor = fixtures.create_sponsor(
        name="Ridgeline Motors", category="AUTOMOTIVE", exclusivity_tier="SUPPORTING"
    )
    activation = fixtures.create_activation(
        sponsor["id"], booking_id, exclusivity_category="AUTOMOTIVE"
    )
    assert activation["net_fee_cents"] == 1100000
    fixtures.cancel_activation(activation["id"])

    # The booking still reads ANNOUNCED here, which is a state both the
    # confirmation and the cancellation admit, so the activation's own terminal
    # status is the only rejection either request can report (PRD 2.10 orders the
    # booking's contractual state check ahead of the activation's).
    validate_error(
        api_client.confirm_sponsorship_activation(
            activation["id"], SPONSORSHIP_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_INVALID_ACTIVATION_STATE.value,
    )
    validate_error(
        api_client.cancel_sponsorship_activation(
            activation["id"], SPONSORSHIP_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_INVALID_ACTIVATION_STATE.value,
    )

    fixtures.record_sales_batch(scenario["ticket_scale"]["id"], "SALE", 100, "ONLINE")
    fixtures.set_clock(scenario["booking"]["load_out_end_utc"])
    fixtures.mark_performed(booking_id)
    settlement = fixtures.open_settlement(
        booking_id, merch_gross_cents=0, merch_seller="ARTIST"
    )

    validate_error(
        api_client.approve_settlement(
            settlement["id"], SETTLEMENT_CONTROLLER_HEADERS
        ),
        ApiErrorId.ERR_INVALID_SETTLEMENT_STATE.value,
    )
    validate_error(
        api_client.reject_settlement(
            settlement["id"],
            {"rejection_reason_code": "GROSS_MISMATCH"},
            SETTLEMENT_CONTROLLER_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_SETTLEMENT_STATE.value,
    )

    final_activation = fixtures.get_activation(activation["id"])
    assert final_activation["status"] == "CANCELLED"
    assert final_activation["net_fee_cents"] == 1100000
    assert final_activation["make_good_credit_cents"] == 0

    final_settlement = fixtures.get_settlement(settlement["id"])
    assert final_settlement["status"] == "DRAFT"
    assert final_settlement["revision_count"] == 0
    assert final_settlement["submitted_by_user_id"] is None


def test_show_dates_outside_the_inclusive_fair_run_are_rejected():
    """The run window is inclusive at both ends, so the day after the close and
    the day before the open are both refused while the closing day itself is
    admitted. The same window is re-tested when a still-unannounced show is
    moved, so a booking that entered legally cannot be walked out of the run
    afterwards, and neither refused draft leaves an offer behind.

    "`target_show_date` must lie inside the edition's inclusive run window,
    failing which the draft is refused with `ERR_SHOW_DATE_OUTSIDE_FAIR_RUN`"

    Design: Corner/errors/show_dates_outside_the_inclusive_fair_run_rejected
    """
    world = fixtures.setup_base_world()

    for out_of_window_date in ("2026-08-31", "2026-08-19"):
        validate_error(
            api_client.create_offer(
                build_offer_payload(
                    world["edition"]["id"],
                    world["artist"]["id"],
                    world["stage"]["id"],
                    target_show_date=out_of_window_date,
                    load_in_start_utc=f"{out_of_window_date}T14:00:00.000Z",
                    load_out_end_utc=f"{out_of_window_date}T23:00:00.000Z",
                ),
                TALENT_BUYER_HEADERS,
            ),
            ApiErrorId.ERR_SHOW_DATE_OUTSIDE_FAIR_RUN.value,
        )

    scenario = fixtures.setup_accepted_booking(
        world,
        target_show_date="2026-08-30",
        load_in_start_utc="2026-08-30T14:00:00.000Z",
        load_out_end_utc="2026-08-30T23:00:00.000Z",
    )
    booking_id = scenario["booking"]["id"]

    validate_error(
        api_client.reschedule_show_booking(
            booking_id,
            build_reschedule_payload(
                "2026-08-19", "2026-08-19T14:00:00.000Z", "2026-08-19T23:00:00.000Z"
            ),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_SHOW_DATE_OUTSIDE_FAIR_RUN.value,
    )

    moved = validate_success(
        api_client.reschedule_show_booking(
            booking_id,
            build_reschedule_payload(
                "2026-08-20", "2026-08-20T14:00:00.000Z", "2026-08-20T23:00:00.000Z"
            ),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        ),
        200,
    )
    assert moved["show_date"] == "2026-08-20"
    assert fixtures.get_booking(booking_id)["show_date"] == "2026-08-20"

    _, offers_meta = validate_paginated(
        api_client.list_offers(
            TALENT_BUYER_HEADERS, {"artist_id": world["artist"]["id"]}
        )
    )
    assert offers_meta["total_count"] == 1


def test_postpone_without_a_strictly_later_replacement_date_is_rejected():
    """The replacement-date rule is one rule with four ways to break it, and all
    four report the same identifier: a postponement that names no replacement, a
    replacement equal to the show's own date, a replacement earlier than it even
    though that day is inside the run, and a cancellation carrying a replacement
    date it has no business carrying. The postponement that follows reuses the
    booking version read before the first attempt, so no refusal touched it.

    "a `POSTPONE` must supply `replacement_show_date`, that date must fall
    strictly after the booking's current `show_date`, and it must lie inside the
    edition's inclusive run window; a `CANCEL` must not supply a replacement
    date at all. Every one of those four failures is refused with
    `ERR_REPLACEMENT_DATE_INVALID`."

    Design: Corner/errors/postpone_without_a_strictly_later_replacement_date_rejected
    """
    scenario = fixtures.setup_accepted_booking()
    booking_id = scenario["booking"]["id"]
    held_version = fixtures.booking_version(booking_id)

    refused_payloads = (
        build_contingency_action_payload(
            held_version, action_type="POSTPONE", refund_policy="RAIN_CHECK"
        ),
        build_contingency_action_payload(
            held_version,
            action_type="POSTPONE",
            refund_policy="RAIN_CHECK",
            replacement_show_date="2026-08-22",
        ),
        build_contingency_action_payload(
            held_version,
            action_type="POSTPONE",
            refund_policy="RAIN_CHECK",
            replacement_show_date="2026-08-21",
        ),
        build_contingency_action_payload(
            held_version,
            action_type="CANCEL",
            refund_policy="RAIN_CHECK",
            replacement_show_date="2026-08-26",
        ),
    )
    for payload in refused_payloads:
        validate_error(
            api_client.create_contingency_action(
                booking_id, payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
            ),
            ApiErrorId.ERR_REPLACEMENT_DATE_INVALID.value,
        )

    assert fixtures.get_booking(booking_id)["booking_status"] == "DATE_HELD"

    action = validate_success(
        api_client.create_contingency_action(
            booking_id,
            build_contingency_action_payload(
                held_version,
                action_type="POSTPONE",
                refund_policy="RAIN_CHECK",
                replacement_show_date="2026-08-26",
            ),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        ),
        201,
    )
    assert action["action_type"] == "POSTPONE"
    assert action["replacement_show_date"] == "2026-08-26"

    _, replacements_meta = validate_paginated(
        api_client.list_show_bookings(
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
            {"postponed_from_booking_id": booking_id},
        )
    )
    assert replacements_meta["total_count"] == 1


def test_announce_reports_advance_not_complete_before_no_ticket_scales():
    """Announcement is guarded by both a completed production advance and a
    non-empty price structure, and while an unruled rider line remains the
    advance objection is the one reported even though the show also owns no
    price tier at all. Closing the advance is itself refused while any line
    sits unruled, including the seed staging line, and only once the advance is
    closed does the same announcement fall through to the pricing objection.

    "the booking must read `DATE_HELD`, the booking's production advance must
    read `ADVANCE_COMPLETE`" and "the booking must own at least one price tier,
    an empty price structure being refused with `ERR_NO_TICKET_SCALES`"

    Design: Corner/errors/announce_preconditions_fire_in_priority_order_31_then_44
    """
    scenario = fixtures.setup_accepted_booking()
    booking_id = scenario["booking"]["id"]
    advance_id = scenario["advance"]["id"]
    hospitality = fixtures.add_rider_item(
        advance_id,
        category="HOSPITALITY",
        description="Dressing room catering",
        requested_cost_cents=250000,
    )

    validate_error(
        api_client.complete_production_advance(advance_id, PRODUCTION_MANAGER_HEADERS),
        ApiErrorId.ERR_ADVANCE_HAS_OPEN_ITEMS.value,
    )
    validate_error(
        api_client.announce_show_booking(
            booking_id, build_announce_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_ADVANCE_NOT_COMPLETE.value,
    )

    fixtures.rule_rider_item(hospitality["id"], "DENIED")
    validate_error(
        api_client.complete_production_advance(advance_id, PRODUCTION_MANAGER_HEADERS),
        ApiErrorId.ERR_ADVANCE_HAS_OPEN_ITEMS.value,
    )

    fixtures.rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
    closed_advance = fixtures.complete_advance(advance_id)
    assert closed_advance["status"] == "ADVANCE_COMPLETE"
    assert closed_advance["approved_rider_cost_cents"] == 0

    validate_error(
        api_client.announce_show_booking(
            booking_id, build_announce_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_NO_TICKET_SCALES.value,
    )

    fixtures.add_ticket_scale(booking_id, allotment_seats=2000, facility_fee_cents=400)
    announced = validate_success(
        api_client.announce_show_booking(
            booking_id, build_announce_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
        ),
        200,
    )
    assert announced["booking_status"] == "ANNOUNCED"
    assert announced["ticketing_status"] == "ON_SALE"


def test_settlement_timing_uniqueness_and_negative_payout_are_rejected():
    """A deliberately underwater show exercises three refusals on the settlement
    arc. Opening the reconciliation while the clock sits behind load-out is
    refused even one millisecond short and even though the show already reads
    performed, because the clock rather than the status is the second half of
    that gate; the boundary instant itself is admitted. A second opening is
    refused while the first draft still occupies the booking, and the waterfall
    that comes out negative may be computed and previewed but never submitted.

    "The logical clock must have reached the booking's `load_out_end_utc`, since
    a show is not concluded until the stage is clear, and an early attempt is
    refused with `ERR_SHOW_NOT_YET_CONCLUDED`." Later, "the submission is
    refused with `ERR_SETTLEMENT_NEGATIVE_PAYOUT` and nothing is written".

    Design: Corner/errors/settlement_timing_uniqueness_and_negative_payout_rejected
    """
    scenario = fixtures.setup_accepted_booking(
        offered_guarantee_cents=500_000, backend_breakeven_cents=0
    )
    booking_id = scenario["booking"]["id"]
    advance_id = scenario["advance"]["id"]

    recoupable = fixtures.add_rider_item(
        advance_id,
        category="SOUND",
        description="Supplemental PA hang",
        requested_cost_cents=2000000,
        is_critical=True,
        artist_recoupable=True,
    )
    fixtures.rule_rider_item(scenario["seed_rider_item"]["id"], "APPROVED")
    fixtures.rule_rider_item(recoupable["id"], "APPROVED")
    closed_advance = fixtures.complete_advance(advance_id)
    assert closed_advance["approved_rider_cost_cents"] == 2000000

    ticket_scale = fixtures.add_ticket_scale(
        booking_id, tier_name="BLEACHER", face_price_cents=3770, allotment_seats=250
    )
    fixtures.announce_booking(booking_id)
    fixtures.record_sales_batch(ticket_scale["id"], "SALE", 100, "ONLINE")
    fixtures.set_clock("2026-08-22T23:00:00.000Z")
    fixtures.mark_performed(booking_id)

    for early_instant in ("2026-08-22T20:00:00.000Z", "2026-08-22T22:59:59.999Z"):
        fixtures.set_clock(early_instant)
        validate_error(
            api_client.create_settlement(
                booking_id,
                build_settlement_payload(merch_gross_cents=0, merch_seller="ARTIST"),
                TALENT_BUYER_HEADERS,
            ),
            ApiErrorId.ERR_SHOW_NOT_YET_CONCLUDED.value,
        )

    fixtures.set_clock("2026-08-22T23:00:00.000Z")
    settlement = validate_success(
        api_client.create_settlement(
            booking_id,
            build_settlement_payload(merch_gross_cents=0, merch_seller="ARTIST"),
            TALENT_BUYER_HEADERS,
        ),
        201,
    )
    assert settlement["status"] == "DRAFT"

    preview = fixtures.settlement_preview(booking_id)
    assert preview["artist_payout_cents"] == 500000
    assert preview["promoter_expense_cents"] == 4517500
    assert preview["net_pool_cents"] == -17500
    assert preview["merch_hall_fee_cents"] == 25000
    assert preview["merch_artist_share_cents"] == -25000
    assert preview["total_artist_settlement_cents"] == -1525000

    validate_error(
        api_client.create_settlement(
            booking_id,
            build_settlement_payload(
                basis="PROVISIONAL", merch_gross_cents=0, merch_seller="ARTIST"
            ),
            TALENT_BUYER_HEADERS,
        ),
        ApiErrorId.ERR_SETTLEMENT_ALREADY_EXISTS.value,
    )

    validate_error(
        api_client.submit_settlement(settlement["id"], TALENT_BUYER_HEADERS),
        ApiErrorId.ERR_SETTLEMENT_NEGATIVE_PAYOUT.value,
    )

    unsubmitted = fixtures.get_settlement(settlement["id"])
    assert unsubmitted["status"] == "DRAFT"
    assert unsubmitted["submitted_by_user_id"] is None

    _, settlements_meta = validate_paginated(
        api_client.list_settlements(
            SETTLEMENT_CONTROLLER_HEADERS, {"booking_id": booking_id}
        )
    )
    assert settlements_meta["total_count"] == 1


def test_sponsor_category_and_stage_naming_exclusivity_conflicts_are_rejected():
    """The two sponsorship uniqueness rules have different scopes and both bite.
    Trade-category exclusivity is per show and only against a live package of a
    different sponsor, so the incumbent may buy a second package in its own
    category. Stage-naming rights span every show on the stage for the whole
    edition and are blocked by a merely proposed incumbent, releasing only when
    that incumbent is cancelled. Only confirmed packages reach the show's pool.

    "On the same show, no two activations with different `sponsor_id` values may
    both be live in `CONFIRMED` or `FULFILLED` while carrying the same
    `exclusivity_category`; a clash is refused with
    `ERR_SPONSOR_CATEGORY_EXCLUSIVITY_CONFLICT`." Separately, "no second
    activation whose `rights` reads `STAGE_NAMING` may be created for bookings
    on the same stage within the same edition while an existing stage-naming
    activation is `PROPOSED`, `CONFIRMED` or `FULFILLED`, and a clash is refused
    with `ERR_STAGE_NAMING_ALREADY_GRANTED`."

    Design: Corner/errors/sponsor_category_and_stage_naming_exclusivity_conflicts_rejected
    """
    world = fixtures.setup_base_world()
    rock_act = fixtures.create_artist(
        world["agent"]["id"],
        name="Neon Skyline",
        genre="ROCK",
        audience_segment="YOUNG_ADULT",
        base_draw_score=41.00,
    )

    ridgeline = fixtures.create_sponsor(
        name="Ridgeline Motors", category="AUTOMOTIVE", exclusivity_tier="PRESENTING"
    )
    cascade = fixtures.create_sponsor(
        name="Cascade Cola", category="BEVERAGE", exclusivity_tier="SUPPORTING"
    )
    northline = fixtures.create_sponsor(
        name="Northline Wireless", category="TELECOM", exclusivity_tier="SUPPORTING"
    )

    country_show = fixtures.setup_accepted_booking(world)
    rock_show = fixtures.setup_accepted_booking(
        world,
        artist_id=rock_act["id"],
        deal_type="GUARANTEE_PLUS_BACKEND",
        offered_guarantee_cents=500_000,
        backend_breakeven_cents=0,
        target_show_date="2026-08-25",
        load_in_start_utc="2026-08-25T14:00:00.000Z",
        load_out_end_utc="2026-08-25T23:00:00.000Z",
    )
    country_booking = country_show["booking"]["id"]
    rock_booking = rock_show["booking"]["id"]

    incumbent = fixtures.create_activation(
        ridgeline["id"],
        country_booking,
        rights="SIGNAGE",
        base_fee_cents=1000000,
        exclusivity_category="AUTOMOTIVE",
    )
    confirmed_incumbent = fixtures.confirm_activation(incumbent["id"])
    assert confirmed_incumbent["net_fee_cents"] == 1050000

    locked_version = fixtures.booking_version(country_booking)
    validate_error(
        api_client.create_sponsorship_activation(
            build_activation_payload(
                cascade["id"],
                country_booking,
                locked_version,
                rights="SAMPLING",
                base_fee_cents=800000,
                exclusivity_category="AUTOMOTIVE",
            ),
            SPONSORSHIP_DIRECTOR_HEADERS,
        ),
        ApiErrorId.ERR_SPONSOR_CATEGORY_EXCLUSIVITY_CONFLICT.value,
    )

    beverage_package = validate_success(
        api_client.create_sponsorship_activation(
            build_activation_payload(
                cascade["id"],
                country_booking,
                locked_version,
                rights="SAMPLING",
                base_fee_cents=800000,
                exclusivity_category="BEVERAGE",
            ),
            SPONSORSHIP_DIRECTOR_HEADERS,
        ),
        201,
    )
    assert beverage_package["net_fee_cents"] == 800000

    second_package = validate_success(
        api_client.create_sponsorship_activation(
            build_activation_payload(
                ridgeline["id"],
                country_booking,
                fixtures.booking_version(country_booking),
                rights="PRESENTING",
                base_fee_cents=500000,
                exclusivity_category="AUTOMOTIVE",
            ),
            SPONSORSHIP_DIRECTOR_HEADERS,
        ),
        201,
    )
    assert second_package["net_fee_cents"] == 525000

    stage_name_elsewhere = validate_success(
        api_client.create_sponsorship_activation(
            build_activation_payload(
                cascade["id"],
                rock_booking,
                fixtures.booking_version(rock_booking),
                rights="STAGE_NAMING",
                base_fee_cents=600000,
                exclusivity_category="BEVERAGE",
            ),
            SPONSORSHIP_DIRECTOR_HEADERS,
        ),
        201,
    )
    assert stage_name_elsewhere["net_fee_cents"] == 750000
    assert stage_name_elsewhere["status"] == "PROPOSED"

    contested_version = fixtures.booking_version(country_booking)
    northline_request = build_activation_payload(
        northline["id"],
        country_booking,
        contested_version,
        rights="STAGE_NAMING",
        base_fee_cents=400000,
        exclusivity_category="TELECOM",
    )
    validate_error(
        api_client.create_sponsorship_activation(
            northline_request, SPONSORSHIP_DIRECTOR_HEADERS
        ),
        ApiErrorId.ERR_STAGE_NAMING_ALREADY_GRANTED.value,
    )

    fixtures.cancel_activation(stage_name_elsewhere["id"])
    released = validate_success(
        api_client.create_sponsorship_activation(
            northline_request, SPONSORSHIP_DIRECTOR_HEADERS
        ),
        201,
    )
    assert released["net_fee_cents"] == 500000

    assert fixtures.get_booking(country_booking)["sponsorship_revenue_cents"] == 1050000


def test_refund_batch_beyond_currently_sold_units_is_rejected():
    """The refund guard reads the tier's running net units rather than the gross
    units ever sold: one unit over the current holding is refused, exactly the
    current holding is admitted and drives the tier to zero, and a single unit
    against zero is then refused. A fresh sale moves the ceiling with it, and
    only the one admitted refund is ever persisted.

    "Applying the candidate `REFUND` batch, the tier's net unit count must
    remain at or above 0; a refund larger than what the tier currently holds is
    refused with `ERR_REFUND_EXCEEDS_SOLD_UNITS`."

    Design: Corner/errors/refund_batch_beyond_currently_sold_units_rejected
    """
    scenario = fixtures.setup_announced_booking(
        scale_overrides={"allotment_seats": 2000, "facility_fee_cents": 400}
    )
    scale_id = scenario["ticket_scale"]["id"]
    fixtures.record_sales_batch(scale_id, "SALE", 500, "ONLINE")

    validate_error(
        api_client.create_sales_batch(
            scale_id,
            build_sales_batch_payload("REFUND", 501, "ONLINE"),
            BOX_OFFICE_MANAGER_HEADERS,
        ),
        ApiErrorId.ERR_REFUND_EXCEEDS_SOLD_UNITS.value,
    )

    fixtures.record_sales_batch(scale_id, "REFUND", 500, "ONLINE")
    assert fixtures.get_ticket_scale(scale_id)["sold_seats"] == 0

    validate_error(
        api_client.create_sales_batch(
            scale_id,
            build_sales_batch_payload("REFUND", 1, "ONLINE"),
            BOX_OFFICE_MANAGER_HEADERS,
        ),
        ApiErrorId.ERR_REFUND_EXCEEDS_SOLD_UNITS.value,
    )

    fixtures.record_sales_batch(scale_id, "SALE", 300, "BOX_OFFICE")
    validate_error(
        api_client.create_sales_batch(
            scale_id,
            build_sales_batch_payload("REFUND", 301, "BOX_OFFICE"),
            BOX_OFFICE_MANAGER_HEADERS,
        ),
        ApiErrorId.ERR_REFUND_EXCEEDS_SOLD_UNITS.value,
    )

    final_scale = fixtures.get_ticket_scale(scale_id)
    assert final_scale["sold_seats"] == 300
    assert final_scale["available_seats"] == 1700
    assert final_scale["status"] == "ON_SALE_ELIGIBLE"
    assert (
        fixtures.get_booking(scenario["booking"]["id"])["ticketing_status"] == "ON_SALE"
    )

    _, refunds_meta = validate_paginated(
        api_client.list_sales_batches(
            scale_id, BOX_OFFICE_MANAGER_HEADERS, {"batch_kind": "REFUND"}
        )
    )
    assert refunds_meta["total_count"] == 1
