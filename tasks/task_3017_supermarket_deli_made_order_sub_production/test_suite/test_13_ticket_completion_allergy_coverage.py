"""Ticket completion reads the acting associate's allergen coverage."""

from test_helpers import (
    ApiErrorId,
    api_client,
    clerk_headers,
    create_sub_ticket_payload,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def _setup_in_progress_ticket_and_two_clerks():
    """A ticket whose line carries SESAME, an ACTIVE price file, and two clerks —
    one cleared only for MILK and WHEAT, one cleared for SESAME as well."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                    slicer_count=2)
    sesame_item = validate_success(
        api_client.create_item(
            {"sku": "CC-SAL-01", "name": "Salami", "category": "COLD_CUT", "unit_cost_cents": 1000,
             "retail_price_per_lb_cents": 1499, "case_life_minutes": 120, "markdown_window_minutes": 30,
             "allergen_flags": ["MILK", "SESAME"], "slicer_required": True},
            platform_admin_headers(),
        ), expected_status=201)
    narrow_clerk = get_success_data(
        api_client.create_associate(
            {"store_id": master.s, "employee_number": "E-1006", "full_name": "Nina Narrow",
             "primary_role": "DELI_CLERK", "allergy_set": ["MILK", "WHEAT"]},
            platform_admin_headers(),
        )
    )
    broad_clerk = get_success_data(
        api_client.create_associate(
            {"store_id": master.s, "employee_number": "E-1007", "full_name": "Otto Broad",
             "primary_role": "DELI_CLERK", "allergy_set": ["MILK", "WHEAT", "SESAME"]},
            platform_admin_headers(),
        )
    )
    produce_batch(master.s, sesame_item["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])

    ticket = get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel="IN_STORE",
                lines=[{"deli_item_id": sesame_item["id"], "half_lb_units": 4,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    ticketed = get_success_data(
        api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"]))
    )
    return master, sesame_item, narrow_clerk, broad_clerk, ticketed


def test_completion_is_refused_for_a_clerk_who_does_not_cover_every_line_allergen():
    """PRD §3.4: "It is refused with `ERR_ALLERGY_HOLD_ACTIVE` when the completing
    associate's `allergy_set` is not a superset of every line's `allergen_flags`;
    this is the allergen-coverage rule, evaluated against the acting `Associate`
    rather than against any store-level set."

    Design: Difficulty/cross_entity_state_dependency/ticket_completion_gated_on_certification_coverage
    """
    master, _, narrow, _, ticket = _setup_in_progress_ticket_and_two_clerks()
    response = api_client.complete_sub_ticket(ticket["id"], 2, clerk_headers(narrow["id"]))
    validate_error(response, ApiErrorId.ERR_ALLERGY_HOLD_ACTIVE)

    unchanged = validate_success(api_client.get_sub_ticket(ticket["id"], platform_admin_headers()))
    assert unchanged["label_id"] is None, "the refused completion issued no label"
    assert unchanged["status"] in ("TICKETED", "IN_PROGRESS"), (
        "the refused completion writes no state; a read may advance the station leg"
    )


def test_completion_succeeds_for_a_clerk_whose_set_covers_the_line():
    """PRD §3.4: "A successful completion stamps `completed_at`, recomputes
    `lateness_minutes`, recomputes the ticket's `line_total_cents`, and
    synthesizes a `Label` with `subject_type` `SUB_TICKET` and status `ISSUED`,
    storing its identifier on the ticket as `label_id`."

    The same ticket row that the narrow clerk could not complete is completed
    once a clerk whose set covers the line's allergens acts.

    Design: Difficulty/cross_entity_state_dependency/ticket_completion_gated_on_certification_coverage
    """
    master, _, _, broad, ticket = _setup_in_progress_ticket_and_two_clerks()
    completed = validate_success(
        api_client.complete_sub_ticket(ticket["id"], 2, clerk_headers(broad["id"]))
    )
    assert completed["status"] == "COMPLETED"
    assert completed["label_id"] is not None, "completion issues the weight label"

    label = validate_success(api_client.get_label(completed["label_id"], platform_admin_headers()))
    assert label["subject_type"] == "SUB_TICKET"
    assert label["status"] == "ISSUED"