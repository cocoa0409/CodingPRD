"""Seat-side ordering: money, the identification axis, and delivery priority."""
import pytest

from test_helpers import (
    api_client, ADMIN, LEAD,
    validate_success, validate_error, get_success_data,
    assert_order_slip, assert_order_slip_id_axis_consistency,
    make_menu_item, make_showtime, make_themed_menu_item, make_programming_event,
    set_clock, server_headers, read_slip, read_showtime, make_slip,
    approve_and_activate_event,
    setup_dining_open_showtime, setup_in_service_showtime,
    setup_alcohol_slip_in_service, setup_ready_entree_and_ready_alcohol_slips,
    setup_showtime_with_two_servers, place_scenario_slip,
)


def _themed_basket_scenario():
    """An activated themed event on one auditorium, a SPECIAL_EVENT showtime on
    it, and a plain showtime for the same basket off the theme."""
    set_clock("2026-09-01T19:40:00Z")
    auditorium = get_success_data(api_client.create_auditorium(
        {"name": "Theater 2", "seat_capacity": 60, "screen_lead_time_minutes": 20,
         "kitchen_point_rate": 1, "alcove_point_rate": 3}, ADMIN))
    entree = make_menu_item("ENTREE", price_cents=1200, prep_minutes=1, catalog_name="Quiche")
    water = make_menu_item("BEVERAGE", price_cents=1200, prep_minutes=1, catalog_name="Sparkling Water")
    cola = make_menu_item("BEVERAGE", price_cents=1200, prep_minutes=1, catalog_name="Cola")
    server = get_success_data(api_client.create_server(
        {"display_name": "Paz", "home_auditorium_id": auditorium["id"]}, ADMIN))

    event = make_programming_event(auditorium["id"], "Quote-Along: The Princess Bride", True)
    make_themed_menu_item(event["id"], entree["id"], 1011, is_signature=True)
    make_themed_menu_item(event["id"], water["id"], 1011)
    make_themed_menu_item(event["id"], cola["id"], 1011)

    # PRD §3.2 refuses activation with `ERR_NO_LINKED_SHOWTIME` unless the event
    # already "has at least one linked showtime of type `SPECIAL_EVENT`", and
    # §2.13 makes the linkage explicit: a showtime on the event's own auditorium
    # carrying `content_type` of `SPECIAL_EVENT`. The themed showtime therefore
    # has to be scheduled before the event can be activated.
    themed_showtime = make_showtime(auditorium["id"], "2026-09-01T20:00:00Z", 100,
                                    content_type="SPECIAL_EVENT", title="The Princess Bride")
    event = approve_and_activate_event(event)
    themed_showtime = get_success_data(api_client.open_dining(themed_showtime["id"], LEAD))
    themed_section = get_success_data(api_client.create_section_assignment(
        {"showtime_id": themed_showtime["id"], "server_id": server["id"],
         "section_label": "CENTER"}, LEAD))

    # §2.10's cluster is scoped to one auditorium, so the off-theme control lives
    # on a second room. PRD §3.2 is what makes it price from the catalogue: the
    # two showtimes on room 2 share that room with no programming event.
    set_clock("2026-09-01T19:45:00Z")
    plain_room = get_success_data(api_client.create_auditorium(
        {"name": "Theater 2B", "seat_capacity": 60, "screen_lead_time_minutes": 20,
         "kitchen_point_rate": 1, "alcove_point_rate": 3}, ADMIN))
    plain_showtime = make_showtime(plain_room["id"], "2026-09-01T20:05:00Z", 100,
                                   title="The Princess Bride (late)")
    plain_showtime = get_success_data(api_client.open_dining(plain_showtime["id"], LEAD))
    # PRD §2.11 rejects two of one server's active assignments whose on-floor
    # intervals come within fifteen minutes of each other, and both of these
    # windows are open at once — so the control room gets its own server.
    plain_server = get_success_data(api_client.create_server(
        {"display_name": "Quinn", "home_auditorium_id": plain_room["id"]}, ADMIN))
    plain_section = get_success_data(api_client.create_section_assignment(
        {"showtime_id": plain_showtime["id"], "server_id": plain_server["id"],
         "section_label": "RIGHT"}, LEAD))

    return {
        "auditorium": auditorium, "plain_room": plain_room,
        "item": entree, "water": water, "cola": cola,
        "server": server, "event": event,
        "themed_showtime": themed_showtime, "themed_section": themed_section,
        "plain_showtime": plain_showtime, "plain_section": plain_section,
        "plain_server": plain_server,
    }


def test_themed_subtotal_rounds_the_discount_per_line(api):
    """PRD §3.3: "the platform computes a theme discount of one twentieth of the
    raw line amount — a five percent discount — and rounds that discount half up
    to a whole cent; when the unit price was a catalogue price, the discount is
    zero. The line's `line_total_cents` is the raw line amount minus its
    discount, so the discount is rounded *per line*. The slip's `subtotal_cents`
    is then the sum of those per-line totals across all lines."
    PRD §3.3: "Summing the raw amounts first and rounding a single discount at the
    end produces a different cent figure and is wrong".

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_rounding_not_sum_then_round
    """
    scenario = _themed_basket_scenario()
    lines = [
        {"menu_item_id": scenario["item"]["id"], "quantity": 1},
        {"menu_item_id": scenario["water"]["id"], "quantity": 1},
        {"menu_item_id": scenario["cola"]["id"], "quantity": 1},
    ]
    version = read_showtime(scenario["themed_showtime"]["id"], LEAD)["version"]
    slip = validate_success(api_client.create_order_slip(
        {"showtime_id": scenario["themed_showtime"]["id"],
         "section_assignment_id": scenario["themed_section"]["id"],
         "seat_number": 8, "lines": lines, "expected_showtime_version": version},
        server_headers(scenario["server"]),
    ), 201)
    assert_order_slip(slip)
    assert [line["unit_price_cents"] for line in slip["resolved_lines"]] == [1011, 1011, 1011], (
        "an activated event's themed menu supplies the unit prices"
    )
    assert slip["subtotal_cents"] == 2880, (
        "each 1011-cent line is rounded on its own: 1011 less round_half_up(50.55) "
        "is 960, and three of those make 2880"
    )
    assert slip["subtotal_cents"] != 2881, (
        "summing the raw amounts and rounding a single discount gives 3033 less "
        "round_half_up(151.65), which is 2881"
    )


def test_standard_subtotal_carries_no_discount(api):
    """PRD §3.3: "A slip that is not part of an activated programming event
    therefore carries a zero discount on every line and its subtotal is simply
    the sum of unit price times quantity."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_rounding_not_sum_then_round
    """
    scenario = _themed_basket_scenario()
    lines = [
        {"menu_item_id": scenario["item"]["id"], "quantity": 1},
        {"menu_item_id": scenario["water"]["id"], "quantity": 1},
        {"menu_item_id": scenario["cola"]["id"], "quantity": 1},
    ]
    version = read_showtime(scenario["plain_showtime"]["id"], LEAD)["version"]
    slip = validate_success(api_client.create_order_slip(
        {"showtime_id": scenario["plain_showtime"]["id"],
         "section_assignment_id": scenario["plain_section"]["id"],
         "seat_number": 8, "lines": lines, "expected_showtime_version": version},
        server_headers(scenario["plain_server"]),
    ), 201)
    assert [line["unit_price_cents"] for line in slip["resolved_lines"]] == [1200, 1200, 1200], (
        "off the theme the catalogue prices apply"
    )
    assert slip["subtotal_cents"] == 3600, "1200 * 3 with no theme discount at all"


def test_alcohol_slip_fulfilment_advances_while_its_id_axis_stalls(api):
    """PRD §3.3: "The `id_check_required` flag is true exactly when at least one
    resolved line is an alcoholic beverage, and the corresponding
    `id_check_status` is then set to `PENDING`".
    PRD §3.4: "That act moves `status` from `ACCEPTED` to `PREPARING` and stamps
    `in_kitchen_at_utc` with the logical clock."
    PRD §3.4: "A slip whose `id_check_required` flag is true cannot reach its seat
    unless its `id_check_status` is `VERIFIED`; an attempt to deliver it
    otherwise is refused with `ERR_ID_CHECK_REQUIRED` (HTTP 403)."

    Design: Difficulty/non_linear_state_machine/order_slip_alcohol_axis_voids_while_fulfilment_axis_advances
    """
    scenario = setup_alcohol_slip_in_service(to_ready=False)
    slip, server = scenario["slip"], scenario["server"]
    assert slip["status"] == "PREPARING", "the server's own action moved the fulfilment axis"
    assert slip["id_check_status"] == "PENDING", (
        "the identification axis has not been asked anything yet"
    )
    assert slip["id_check_required"] is True
    assert_order_slip_id_axis_consistency(slip)

    get_success_data(api_client.mark_order_slip_ready(slip["id"], server_headers(server)))
    ready = read_slip(slip["id"], ADMIN)
    assert ready["status"] == "READY", "the fulfilment axis reached READY"
    assert ready["id_check_status"] == "PENDING", "and the identification axis still has not moved"

    refused = api_client.deliver_order_slip(slip["id"], server_headers(server))
    validate_error(refused, "ERR_ID_CHECK_REQUIRED")


def test_verifying_the_check_moves_only_the_id_axis(api):
    """PRD §3.4: "a passing result sets that slip's `id_check_status` to
    `VERIFIED`, while a failing result sets it to `REFUSED` and releases the slip
    without charge".

    Design: Difficulty/non_linear_state_machine/order_slip_alcohol_axis_voids_while_fulfilment_axis_advances
    """
    scenario = setup_alcohol_slip_in_service(to_ready=True)
    slip, server, ticket = scenario["slip"], scenario["server"], scenario["hot_ticket"]
    assert slip["status"] == "READY"
    assert slip["id_check_status"] == "PENDING"

    validate_success(api_client.verify_ticket_id(ticket["id"], "PASS", server_headers(server)), 200)
    after = read_slip(slip["id"], ADMIN)
    assert after["id_check_status"] == "VERIFIED", "the identification axis advanced"
    assert after["status"] == "READY", (
        "the fulfilment axis is unchanged by an identification result"
    )

    delivered = validate_success(
        api_client.deliver_order_slip(slip["id"], server_headers(server)), 200
    )
    assert delivered["status"] == "DELIVERED", "the same row then completes on the fulfilment axis"


def test_unverified_alcohol_is_refused_until_the_check_passes(api):
    """PRD §3.4: "an attempt to deliver it otherwise is refused with
    `ERR_ID_CHECK_REQUIRED` (HTTP 403)."
    PRD §3.4: "a passing result sets that slip's `id_check_status` to `VERIFIED`".

    Design: Corner/errors/unverified_alcohol_requires_a_completed_identification_check
    """
    scenario = setup_alcohol_slip_in_service(to_ready=True)
    slip, server, ticket = scenario["slip"], scenario["server"], scenario["hot_ticket"]

    first = api_client.deliver_order_slip(slip["id"], server_headers(server))
    validate_error(first, "ERR_ID_CHECK_REQUIRED")

    validate_success(api_client.verify_ticket_id(ticket["id"], "PASS", server_headers(server)), 200)
    second = validate_success(
        api_client.deliver_order_slip(slip["id"], server_headers(server)), 200
    )
    assert second["status"] == "DELIVERED"
    assert second["id_check_status"] == "VERIFIED"


def test_unverified_alcohol_outranks_the_late_entree_error(api):
    """PRD §2.9: "Compliance holds and safety rules outrank mere capacity: an
    alcohol gate fires before any capacity band is computed."
    PRD §3.4: "a delivery attempted after `entree_ready_deadline_utc` is refused
    with `ERR_ENTREE_DEADLINE_PASSED`".

    Design: Difficulty/priority_pair_validation_conflict/identity_check_priority_5_beats_window_priority_8
    """
    scenario = setup_ready_entree_and_ready_alcohol_slips()
    server = scenario["server"]
    wine_refused = api_client.deliver_order_slip(
        scenario["wine_slip"]["id"], server_headers(server)
    )
    validate_error(wine_refused, "ERR_ID_CHECK_REQUIRED")
    assert wine_refused.status_code == 403

    entree_refused = api_client.deliver_order_slip(
        scenario["entree_slip"]["id"], server_headers(server)
    )
    validate_error(entree_refused, "ERR_ENTREE_DEADLINE_PASSED")


def test_the_safety_refusal_differs_from_the_temporal_refusal(api):
    """PRD §3.4: "A slip whose `id_check_required` flag is true cannot reach its
    seat unless its `id_check_status` is `VERIFIED`; an attempt to deliver it
    otherwise is refused with `ERR_ID_CHECK_REQUIRED` (HTTP 403)."
    PRD §3.4: "an entrée slip must still be within its deadline, so a delivery
    attempted after `entree_ready_deadline_utc` is refused with
    `ERR_ENTREE_DEADLINE_PASSED`".

    Design: Difficulty/priority_pair_validation_conflict/identity_check_priority_5_beats_window_priority_8
    """
    scenario = setup_ready_entree_and_ready_alcohol_slips()
    server = scenario["server"]

    wine_body = api_client.deliver_order_slip(
        scenario["wine_slip"]["id"], server_headers(server)
    ).json()["data"]["error_id"]
    entree_body = api_client.deliver_order_slip(
        scenario["entree_slip"]["id"], server_headers(server)
    ).json()["data"]["error_id"]
    assert wine_body == "ERR_ID_CHECK_REQUIRED"
    assert entree_body == "ERR_ENTREE_DEADLINE_PASSED"
    assert wine_body != entree_body, (
        "the safety check did not simply fall through to the temporal one"
    )


def test_server_may_not_advance_another_servers_slip(api):
    """PRD §3.4: "only for the server named on the slip's own section, since a
    server cannot advance another server's plate (otherwise
    `ERR_NOT_ASSIGNED_SERVER`, HTTP 403)."

    Design: Corner/validations/cross_entity_actor_check_rejects_a_slip_from_another_section
    """
    scenario = setup_showtime_with_two_servers()
    first, second = scenario["first_server"], scenario["second_server"]
    item = make_menu_item("ENTREE", price_cents=700, prep_minutes=1, catalog_name="Fries")
    version = read_showtime(scenario["showtime"]["id"], LEAD)["version"]
    slip = make_slip(scenario["showtime"]["id"], scenario["first_section"]["id"], first, 7,
                     [{"menu_item_id": item["id"], "quantity": 1}],
                     expected_showtime_version=version)

    refused = api_client.prepare_order_slip(slip["id"], server_headers(second))
    validate_error(refused, "ERR_NOT_ASSIGNED_SERVER")
    assert refused.status_code == 403
    assert read_slip(slip["id"], ADMIN)["status"] == "ACCEPTED", (
        "the rejected call applied no side effect"
    )


def test_a_real_server_id_that_is_not_the_owner_is_still_refused(api):
    """PRD §2.1: "When `X-User-Role` is `Server`, `X-User-ID` is the `id` of the
    acting `Server` entity; ownership checks on any resource that references a
    `Server` compare the resource's foreign-key field to `X-User-ID`."
    PRD §3.4: "only for the server named on the slip's own section, since a server
    cannot advance another server's plate (otherwise `ERR_NOT_ASSIGNED_SERVER`,
    HTTP 403)."

    Design: Corner/rbac/entity_backed_server_must_act_as_itself_on_its_own_section
    """
    scenario = setup_showtime_with_two_servers()
    first, second = scenario["first_server"], scenario["second_server"]
    item = make_menu_item("ENTREE", price_cents=900, prep_minutes=1, catalog_name="Kebab")
    version = read_showtime(scenario["showtime"]["id"], LEAD)["version"]
    slip = make_slip(scenario["showtime"]["id"], scenario["first_section"]["id"], first, 4,
                     [{"menu_item_id": item["id"], "quantity": 1}],
                     expected_showtime_version=version)

    refused = api_client.prepare_order_slip(slip["id"], server_headers(second))
    validate_error(refused, "ERR_NOT_ASSIGNED_SERVER")
    assert second["id"] != first["id"], "S2 is a real server entity, so this is an identity mismatch"
    assert read_slip(slip["id"], ADMIN)["status"] == "ACCEPTED"


def test_the_platform_operator_cannot_deliver_a_slip(api):
    """PRD §2.1: "Each role owns a distinct slice of the operation and no role can
    override another's: an administrator cannot place an order on a server's
    behalf, and a server cannot open a room's seating window."
    PRD §2.1: "If the declared role is real but is not on the permitted roster for
    the addressed operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/platform_admin_cannot_deliver_a_slip
    """
    scenario = setup_in_service_showtime(
        clock="2026-09-01T19:40:00Z", service_clock="2026-09-01T19:50:00Z",
        before_service=lambda s: place_scenario_slip(
            s, seat=3, price_cents=800, catalog_name="Bratwurst"),
    )
    server, slip = scenario["server"], scenario["slip"]
    set_clock("2026-09-01T20:10:00Z")
    get_success_data(api_client.prepare_order_slip(slip["id"], server_headers(server)))
    get_success_data(api_client.mark_order_slip_ready(slip["id"], server_headers(server)))

    refused = api_client.deliver_order_slip(slip["id"], ADMIN)
    validate_error(refused, "ERR_UNAUTHORIZED_ROLE")
    assert refused.status_code == 403
    assert read_slip(slip["id"], ADMIN)["status"] == "READY", "the slip is still awaiting its runner"


def test_delivering_an_entree_after_the_deadline_is_refused(api):
    """PRD §3.3: "a slip whose channel is `ENTREE` is admissible only while the
    clock is at or before `entree_ready_deadline_utc` (otherwise
    `ERR_ENTREE_DEADLINE_PASSED`)."
    PRD §3.4: "a delivery attempted after `entree_ready_deadline_utc` is refused
    with `ERR_ENTREE_DEADLINE_PASSED`".

    Design: Corner/validations/temporal_validation_rejects_an_entree_after_the_deadline
    """
    scenario = setup_dining_open_showtime(
        start_at_utc="2026-09-01T20:00:00Z", runtime_minutes=100,
        clock="2026-09-01T19:50:00Z",
    )
    showtime, server, section = scenario["showtime"], scenario["server"], scenario["section"]
    item = make_menu_item("ENTREE", price_cents=1300, prep_minutes=1, catalog_name="Ramen")
    # The 100-minute feature's entree deadline is 21:15 and its seating window
    # closes at 20:45, so 21:00 is past the deadline while the showtime's `mode`
    # is still `DINING_OPEN`: the pure temporal refusal, not the silent-order one.
    set_clock("2026-09-01T21:20:00Z")

    version = read_showtime(showtime["id"], LEAD)["version"]
    refused = api_client.create_order_slip(
        {"showtime_id": showtime["id"], "section_assignment_id": section["id"],
         "seat_number": 9, "lines": [{"menu_item_id": item["id"], "quantity": 1}],
         "expected_showtime_version": version},
        server_headers(server),
    )
    validate_error(refused, "ERR_ENTREE_DEADLINE_PASSED")
    assert refused.status_code == 409
    unchanged = read_showtime(showtime["id"], LEAD)
    assert unchanged["entree_ready_deadline_utc"] == "2026-09-01T21:15:00Z", (
        "only the clock moved, not the derived deadline"
    )