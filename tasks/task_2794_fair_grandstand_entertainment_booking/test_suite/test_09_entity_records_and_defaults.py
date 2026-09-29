"""Record shape, declared defaults, schema refusals and pagination discipline.

Covers what the service stores and returns for editions, stages, agents,
artists, offers, negotiation rounds and sponsorship activations: the echoed
inputs, the ledgers that start at 0, the defaults that apply when an optional
input is omitted, the dedicated not-found identifiers, and the append-only
negotiation log that carries no revision counter.
"""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_common_fields,
    assert_artist,
    assert_common_fields,
    assert_fair_edition,
    assert_offer,
    assert_sponsorship_activation,
    assert_stage,
    assert_talent_agent,
)
from test_helpers.constants import CANONICAL_CLOCK_UTC
from test_helpers.factories import (
    build_artist_payload,
    build_counter_payload,
    build_fair_edition_payload,
    build_offer_payload,
    build_revise_payload,
    build_talent_agent_payload,
)
from test_helpers.fixtures import (
    create_activation,
    create_edition,
    create_offer,
    create_sponsor,
    create_stage,
    get_booking,
    get_offer,
    offer_version,
    set_clock,
    setup_accepted_booking,
    setup_base_world,
)
from test_helpers.test_users import (
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    SPONSORSHIP_DIRECTOR_HEADERS,
    TALENT_BUYER_ALT_HEADERS,
    TALENT_BUYER_HEADERS,
)


def _window(show_date):
    """The canonical load-in and load-out instants for one performance date."""
    return {
        "target_show_date": show_date,
        "load_in_start_utc": f"{show_date}T14:00:00.000Z",
        "load_out_end_utc": f"{show_date}T23:00:00.000Z",
    }


def test_create_fair_edition_echoes_every_input_and_starts_ledgers_at_zero():
    """An edition opened with its full payload echoes every stored figure and
    reports its three derived ledgers at 0, alongside the four common fields.

    "A newly created edition returns HTTP 201 with its three derived ledgers"

    Design: Corner/entities/create_fair_edition_returns_all_declared_fields
    """
    set_clock(CANONICAL_CLOCK_UTC)

    edition = validate_success(
        api_client.create_fair_edition(
            build_fair_edition_payload(), FAIR_OPERATIONS_DIRECTOR_HEADERS
        ),
        expected_status=201,
    )

    assert_fair_edition(edition)
    assert edition["year"] == 2026
    assert edition["name"] == "State Fair 2026"
    assert edition["run_start_date"] == "2026-08-20"
    assert edition["run_end_date"] == "2026-08-30"
    assert edition["gate_admission_price_cents"] == 1500
    assert edition["talent_budget_cap_cents"] == 40000000
    assert edition["refund_reserve_cents"] == 15000000
    assert edition["max_shows_per_day"] == 2
    assert edition["curfew_utc_time"] == "23:30"
    assert edition["strategy_basis"] == "ATTENDANCE_WEIGHTED"
    assert edition["committed_guarantee_total_cents"] == 0
    assert edition["refund_liability_committed_cents"] == 0
    assert edition["open_stage_count"] == 0
    for field in ("id", "created_at", "updated_at", "version"):
        assert edition[field] is not None


def test_read_stage_returns_stored_capacities_and_an_empty_hold_ledger():
    """Reading a stage returns the row identified in the path: its four supplied
    figures echo the creation request and, with no offer ever sent against it,
    the stage still holds nothing and advertises itself as open.

    "A new stage returns HTTP 201 with `held_show_count` at 0 and `booking_posture` at `OPEN`"

    Design: Corner/entities/retrieve_stage_returns_stored_data_and_zero_hold_ledger
    """
    set_clock(CANONICAL_CLOCK_UTC)
    edition = create_edition()
    created = create_stage(edition["id"])

    stage = validate_success(
        api_client.get_stage(created["id"], PRODUCTION_MANAGER_HEADERS)
    )

    assert_stage(stage)
    assert stage["id"] == created["id"]
    assert stage["fair_edition_id"] == edition["id"]
    assert stage["name"] == "Grandstand"
    assert stage["reserved_seat_capacity"] == 4000
    assert stage["ga_capacity"] == 6000
    assert stage["changeover_buffer_minutes"] == 120
    assert stage["slot_soft_cap"] == 4
    assert stage["held_show_count"] == 0
    assert stage["booking_posture"] == "OPEN"


def test_offer_list_pages_the_filtered_set_and_counts_it_in_full():
    """The offer list windows the filtered set while reporting the whole size of
    that set, so two pages of two exhaust three drafted offers and a status
    filter that matches nothing reports no records at all.

    "`total_count` (the number of records matching the filters before the page window is applied) and `has_more` (true when records remain beyond the current window, false otherwise)"

    Design: Corner/entities/list_offers_is_paginated_with_total_count_and_has_more
    """
    world = setup_base_world()
    edition_id = world["edition"]["id"]
    created_ids = set()
    for show_date in ("2026-08-22", "2026-08-25", "2026-08-28"):
        offer = create_offer(
            edition_id,
            world["artist"]["id"],
            world["stage"]["id"],
            **_window(show_date),
        )
        created_ids.add(offer["id"])

    first_page, first_meta = validate_paginated(
        api_client.list_offers(
            TALENT_BUYER_HEADERS,
            {"fair_edition_id": edition_id, "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api_client.list_offers(
            TALENT_BUYER_HEADERS,
            {"fair_edition_id": edition_id, "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2

    paged_ids = [record["id"] for record in first_page + second_page]
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == created_ids

    sent_page, sent_meta = validate_paginated(
        api_client.list_offers(
            TALENT_BUYER_HEADERS, {"fair_edition_id": edition_id, "status": "SENT"}
        )
    )
    assert sent_page == []
    assert sent_meta["total_count"] == 0
    assert sent_meta["has_more"] is False


def test_read_artist_with_unknown_identifier_reports_the_artist_not_found_error():
    """Each identifier carries its own not-found identifier, so a well-formed
    UUID that matches no act on any roster is refused with the artist-specific
    404 rather than answered with an empty body.

    "an `artist_id` that identifies no artist yields `ERR_ARTIST_NOT_FOUND`; an `offer_id` that identifies no offer yields `ERR_OFFER_NOT_FOUND`"

    Design: Corner/entities/get_artist_with_unknown_uuid_returns_artist_not_found
    """
    set_clock(CANONICAL_CLOCK_UTC)

    error = validate_error(
        api_client.get_artist(NON_EXISTENT_UUID, TALENT_BUYER_HEADERS),
        ApiErrorId.ERR_ARTIST_NOT_FOUND.value,
    )

    assert error["error_id"] == ApiErrorId.ERR_ARTIST_NOT_FOUND.value
    assert isinstance(error["message"], str)
    assert error["message"].strip() != ""


@pytest.mark.parametrize("omitted_field", ["backend_split_pct", "target_show_date"])
def test_draft_offer_missing_a_required_field_is_refused_and_persists_nothing(
    omitted_field,
):
    """Both the artist's backend share and the requested performance date are
    offer inputs without a declared default, so a draft that omits either fails
    the payload schema check and leaves the edition with no offer row at all.

    "Every required field must be present; every enum field must carry a declared member"

    Design: Corner/entities/create_offer_missing_required_fields_returns_invalid_request
    """
    world = setup_base_world()
    edition_id = world["edition"]["id"]
    payload = build_offer_payload(
        edition_id, world["artist"]["id"], world["stage"]["id"]
    )
    payload.pop(omitted_field)

    validate_error(
        api_client.create_offer(payload, TALENT_BUYER_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    records, meta = validate_paginated(
        api_client.list_offers(TALENT_BUYER_HEADERS, {"fair_edition_id": edition_id})
    )
    assert records == []
    assert meta["total_count"] == 0


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults():
    """An edition, a stage, an act and an offer created with only their required
    inputs come back carrying the defaults the fair declares: two shows a day, a
    23:30 curfew, attendance-weighted rescoring, a two-hour changeover, a soft
    cap of three, a draw score of 50.00, a 150/30/30 radius clause and a
    forty-eight-hour response window.

    "Three further edition inputs are optional and each has a default that applies when it is omitted."

    Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(CANONICAL_CLOCK_UTC)

    edition = validate_success(
        api_client.create_fair_edition(
            {
                "year": 2026,
                "name": "State Fair 2026",
                "run_start_date": "2026-08-20",
                "run_end_date": "2026-08-30",
                "gate_admission_price_cents": 1500,
                "talent_budget_cap_cents": 40000000,
                "refund_reserve_cents": 15000000,
            },
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert edition["max_shows_per_day"] == 2
    assert edition["curfew_utc_time"] == "23:30"
    assert edition["strategy_basis"] == "ATTENDANCE_WEIGHTED"

    stage = validate_success(
        api_client.create_stage(
            {
                "fair_edition_id": edition["id"],
                "name": "Grandstand",
                "reserved_seat_capacity": 4000,
                "ga_capacity": 6000,
            },
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert stage["changeover_buffer_minutes"] == 120
    assert stage["slot_soft_cap"] == 3

    agent = validate_success(
        api_client.create_talent_agent(
            {
                "user_id": "agent-hollis",
                "agency_name": "Hollis Talent",
                "contact_email": "book@hollis.example",
            },
            TALENT_BUYER_HEADERS,
        ),
        expected_status=201,
    )

    artist = validate_success(
        api_client.create_artist(
            {
                "agent_id": agent["id"],
                "name": "Dust Road Revival",
                "genre": "COUNTRY",
                "audience_segment": "FAMILY",
            },
            TALENT_BUYER_HEADERS,
        ),
        expected_status=201,
    )
    assert artist["base_draw_score"] == pytest.approx(50.0, abs=0.01)
    assert artist["prior_year_paid_attendance"] == 0
    assert artist["prior_year_net_revenue_cents"] == 0

    offer = validate_success(
        api_client.create_offer(
            {
                "fair_edition_id": edition["id"],
                "artist_id": artist["id"],
                "target_stage_id": stage["id"],
                "deal_type": "VERSUS",
                "offered_guarantee_cents": 12500000,
                "backend_split_pct": 0.85,
                "target_show_date": "2026-08-22",
                "load_in_start_utc": "2026-08-22T14:00:00.000Z",
                "load_out_end_utc": "2026-08-22T23:00:00.000Z",
            },
            TALENT_BUYER_HEADERS,
        ),
        expected_status=201,
    )
    assert offer["backend_breakeven_cents"] == 0
    assert offer["radius_miles"] == 150
    assert offer["radius_days_before"] == 30
    assert offer["radius_days_after"] == 30
    assert offer["response_window_hours"] == 48


def test_drafted_offer_ignores_client_supplied_negotiation_state():
    """A draft is inert whatever the client puts in the body: the negotiation
    status, the round tally, the radius waiver and the send timestamps are the
    service's to write, so a create that ships its own values still returns a
    plain draft holding nothing.

    "It returns HTTP 201 with `status` at `DRAFT`, `round_count` at 0 and `radius_waiver_granted` at false"

    Design: Corner/entities/offer_computed_and_system_fields_input_ignored
    """
    world = setup_base_world()
    payload = build_offer_payload(
        world["edition"]["id"],
        world["artist"]["id"],
        world["stage"]["id"],
        status="ACCEPTED",
        round_count=5,
        radius_waiver_granted=True,
        sent_at_utc="2026-07-01T00:00:00.000Z",
        agreed_guarantee_cents=999,
    )

    offer = validate_success(
        api_client.create_offer(payload, TALENT_BUYER_HEADERS), expected_status=201
    )

    assert_offer(offer)
    assert offer["status"] == "DRAFT"
    assert offer["round_count"] == 0
    assert offer["radius_waiver_granted"] is False
    assert offer["sent_at_utc"] is None
    assert offer["expires_at_utc"] is None
    assert offer["countered_guarantee_cents"] is None
    assert offer["agreed_guarantee_cents"] is None


def test_offer_records_the_buying_identity_that_drafted_it():
    """The buyer's identifier is the offer's audit stamp and comes from the
    request headers alone, so two otherwise identical drafts sent by two buyers
    differ exactly in that stamp while each mints its own identity and version.

    "The server does record it in three places where the workflow demands an audit trail"

    Design: Corner/entities/system_fields_are_server_generated_on_offer_create
    """
    world = setup_base_world()
    edition_id = world["edition"]["id"]
    artist_id = world["artist"]["id"]
    stage_id = world["stage"]["id"]

    first = validate_success(
        api_client.create_offer(
            build_offer_payload(
                edition_id, artist_id, stage_id, **_window("2026-08-22")
            ),
            TALENT_BUYER_HEADERS,
        ),
        expected_status=201,
    )
    second = validate_success(
        api_client.create_offer(
            build_offer_payload(
                edition_id, artist_id, stage_id, **_window("2026-08-25")
            ),
            TALENT_BUYER_ALT_HEADERS,
        ),
        expected_status=201,
    )

    assert first["created_by_user_id"] == "buyer-01"
    assert second["created_by_user_id"] == "buyer-02"
    assert first["id"] != second["id"]
    for offer in (first, second):
        assert_common_fields(offer)
        assert offer["created_at"] is not None
        assert offer["updated_at"] is not None
        assert offer["version"] is not None


@pytest.mark.parametrize(
    "violation",
    [
        "undeclared_genre",
        "undeclared_deal_type",
        "negative_guarantee",
        "backend_split_above_one",
    ],
)
def test_roster_and_offer_payloads_outside_their_declared_domains_are_refused(
    violation,
):
    """A programming genre outside the fair's taxonomy, a deal type outside the
    two the service admits, a negative money amount and a backend share above
    one are each a payload schema failure, and none of them writes a row.

    "every enum field must carry a declared member, which covers `genre`, `audience_segment`, `exclusivity_tier`"

    Design: Corner/entities/artist_and_offer_type_constraints_rejected
    """
    world = setup_base_world()
    edition_id = world["edition"]["id"]
    agent_id = world["agent"]["id"]
    artist_id = world["artist"]["id"]
    stage_id = world["stage"]["id"]

    if violation == "undeclared_genre":
        response = api_client.create_artist(
            build_artist_payload(agent_id, name="Polka Kings", genre="POLKA"),
            TALENT_BUYER_HEADERS,
        )
    elif violation == "undeclared_deal_type":
        response = api_client.create_offer(
            build_offer_payload(
                edition_id, artist_id, stage_id, deal_type="FLAT_GUARANTEE"
            ),
            TALENT_BUYER_HEADERS,
        )
    elif violation == "negative_guarantee":
        response = api_client.create_offer(
            build_offer_payload(
                edition_id, artist_id, stage_id, offered_guarantee_cents=-1
            ),
            TALENT_BUYER_HEADERS,
        )
    else:
        response = api_client.create_offer(
            build_offer_payload(edition_id, artist_id, stage_id, backend_split_pct=1.5),
            TALENT_BUYER_HEADERS,
        )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    artists, artist_meta = validate_paginated(
        api_client.list_artists(TALENT_BUYER_HEADERS, {"agent_id": agent_id})
    )
    assert artist_meta["total_count"] == 1
    assert len(artists) == 1
    offers, offer_meta = validate_paginated(
        api_client.list_offers(TALENT_BUYER_HEADERS, {"fair_edition_id": edition_id})
    )
    assert offer_meta["total_count"] == 0
    assert offers == []


def test_negotiation_rounds_are_append_only_and_keep_their_original_terms():
    """A send, an agent counter and a buyer revision leave three rows in the
    negotiation log, the first still reporting the guarantee it was written with,
    and none of the rows carries a revision counter to echo back.

    "For those three, `updated_at` is absent and `version` is absent"

    Design: Corner/entities/offer_round_rows_are_immutable_and_carry_no_version
    """
    world = setup_base_world()
    offer = create_offer(
        world["edition"]["id"], world["artist"]["id"], world["stage"]["id"]
    )
    validate_success(api_client.send_offer(offer["id"], TALENT_BUYER_HEADERS))
    validate_success(
        api_client.counter_offer(
            offer["id"],
            build_counter_payload(
                13500000,
                proposed_backend_split_pct=0.80,
                proposed_breakeven_cents=6000000,
                grant_radius_waiver=False,
                note="Needs a bump.",
            ),
            world["agent_headers"],
        )
    )
    validate_success(
        api_client.revise_offer(
            offer["id"],
            build_revise_payload(
                offer_version(offer["id"]),
                13000000,
                backend_split_pct=0.85,
                backend_breakeven_cents=6000000,
                note="Final number.",
            ),
            TALENT_BUYER_HEADERS,
        )
    )

    rounds, meta = validate_paginated(
        api_client.list_offer_rounds(offer["id"], TALENT_BUYER_HEADERS)
    )
    assert meta["total_count"] == 3
    assert len(rounds) == 3
    assert [row["round_number"] for row in rounds] == [1, 2, 3]
    for row in rounds:
        assert_append_only_common_fields(row)
        assert "version" not in row

    assert rounds[0]["proposed_by"] == "BUYER"
    assert rounds[0]["proposed_guarantee_cents"] == 12500000
    assert rounds[0]["proposed_backend_split_pct"] == pytest.approx(0.85, abs=0.01)
    assert rounds[1]["proposed_by"] == "AGENT"
    assert rounds[1]["proposed_guarantee_cents"] == 13500000
    assert rounds[1]["proposed_backend_split_pct"] == pytest.approx(0.80, abs=0.01)
    assert rounds[2]["proposed_by"] == "BUYER"
    assert rounds[2]["proposed_guarantee_cents"] == 13000000

    final = get_offer(offer["id"])
    assert final["round_count"] == 3
    assert final["offered_guarantee_cents"] == 13000000
    assert final["countered_guarantee_cents"] is None
    assert final["status"] == "SENT"


def test_adding_an_act_to_an_unknown_agent_is_refused_before_the_roster_moves():
    """An act names the one agency authorised to negotiate for it, so an agency
    identifier that resolves to nothing is refused with the agent-specific 404;
    registering the agency first admits the same act and lifts its roster count.

    "an `agent_id` that identifies no agent yields `ERR_TALENT_AGENT_NOT_FOUND`; an `artist_id` that identifies no artist yields `ERR_ARTIST_NOT_FOUND`"

    Design: Corner/entities/create_artist_with_unknown_agent_returns_talent_agent_not_found
    """
    set_clock(CANONICAL_CLOCK_UTC)

    validate_error(
        api_client.create_artist(
            build_artist_payload(NON_EXISTENT_UUID), TALENT_BUYER_HEADERS
        ),
        ApiErrorId.ERR_TALENT_AGENT_NOT_FOUND.value,
    )

    agent = validate_success(
        api_client.create_talent_agent(
            build_talent_agent_payload(), TALENT_BUYER_HEADERS
        ),
        expected_status=201,
    )
    assert_talent_agent(agent)
    assert agent["roster_artist_count"] == 0

    artist = validate_success(
        api_client.create_artist(
            build_artist_payload(agent["id"]), TALENT_BUYER_HEADERS
        ),
        expected_status=201,
    )
    assert_artist(artist)
    assert artist["agent_id"] == agent["id"]

    reread = validate_success(
        api_client.get_talent_agent(agent["id"], TALENT_BUYER_HEADERS)
    )
    assert reread["roster_artist_count"] == 1


def test_two_sponsors_hold_separate_activations_on_one_show():
    """Two sponsors of different trade categories can each hold a rights package
    on the same show; the activation list answers on either side of that link,
    and while both packages are only proposed the show's sponsorship revenue
    stays empty.

    "A new activation returns HTTP 201 in status `PROPOSED` with `make_good_credit_cents` at 0, and it deliberately does not move the booking's `sponsorship_revenue_cents`"

    Design: Corner/entities/activation_junction_links_two_sponsors_to_one_booking
    """
    scenario = setup_accepted_booking()
    booking_id = scenario["booking"]["id"]

    cola = create_sponsor(
        name="Prairie Cola", category="BEVERAGE", exclusivity_tier="SUPPORTING"
    )
    trucks = create_sponsor(
        name="Ridgeline Trucks", category="AUTOMOTIVE", exclusivity_tier="SUPPORTING"
    )

    first = create_activation(
        cola["id"],
        booking_id,
        rights="SIGNAGE",
        base_fee_cents=1000000,
        exclusivity_category="BEVERAGE",
    )
    second = create_activation(
        trucks["id"],
        booking_id,
        rights="SIGNAGE",
        base_fee_cents=1000000,
        exclusivity_category="AUTOMOTIVE",
    )

    by_booking, booking_meta = validate_paginated(
        api_client.list_sponsorship_activations(
            SPONSORSHIP_DIRECTOR_HEADERS, {"booking_id": booking_id}
        )
    )
    assert booking_meta["total_count"] == 2
    assert {row["id"] for row in by_booking} == {first["id"], second["id"]}

    by_sponsor, sponsor_meta = validate_paginated(
        api_client.list_sponsorship_activations(
            SPONSORSHIP_DIRECTOR_HEADERS, {"sponsor_id": cola["id"]}
        )
    )
    assert sponsor_meta["total_count"] == 1
    assert [row["id"] for row in by_sponsor] == [first["id"]]

    activation = validate_success(
        api_client.get_sponsorship_activation(second["id"], TALENT_BUYER_HEADERS)
    )
    assert_sponsorship_activation(activation)
    assert activation["sponsor_id"] == trucks["id"]
    assert activation["booking_id"] == booking_id
    assert activation["status"] == "PROPOSED"
    assert activation["net_fee_cents"] == 1000000
    assert activation["make_good_credit_cents"] == 0

    booking = get_booking(booking_id)
    assert booking["gross_potential_cents"] == 0
    assert booking["sponsorship_revenue_cents"] == 0
