"""Three gates that read a neighbouring row rather than their own payload: intake reading
the patron, acceptance reading the lender, and escalation reading the work."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.factories import escalate_payload, request_payload
from test_helpers.fixtures import (
    add_rota_entry,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    decline_offer,
    escalate_request,
    intake_request,
    list_pod_orders,
    read_partner,
    read_patron,
    read_request,
    run_rota_round,
    set_clock,
    update_bib_item,
    update_partner,
    update_patron,
)
from test_helpers.test_users import (
    make_ill_staff_headers,
    make_partner_agent_headers,
)
from test_helpers.types import (
    DeclineReason,
    ItemType,
    LicensedAccessStatus,
    LocalHoldingStatus,
    MaterialType,
    OfferStatus,
    PartnerStatus,
    PatronStatus,
    PodOrderStatus,
    RequestStatus,
)


def _patron_with_one_live_request_and_a_second_work_to_ask_for(client):
    """One accepted intake on file, plus a second work whose payload differs from the first
    only in the identifier of the work."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8012",
        full_name="Lena Undergrad",
        email="lena@u.edu",
        patron_type="UNDERGRAD",
        department="BIOL",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    assert patron["status"] == PatronStatus.ACTIVE
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    first_work = create_bib_item(
        client,
        title="Marine Invertebrates of the Pacific",
        item_type=ItemType.BOOK,
        publication_year=2015,
        isbn="978-0-000-00006-6",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    second_work = create_bib_item(
        client,
        title="Coral Reef Ecology",
        item_type=ItemType.BOOK,
        publication_year=2016,
        isbn="978-0-000-00007-3",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    accepted = intake_request(
        client,
        patron["id"],
        first_work["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert accepted["status"] == RequestStatus.SOURCING
    return {
        "patron": patron,
        "rota": rota,
        "first_request": accepted,
        "second_work": second_work,
    }


def _second_intake_attempt(client, world):
    return client.create_request(
        request_payload(
            world["patron"]["id"],
            world["second_work"]["id"],
            world["rota"]["id"],
            needed_by="2026-08-09T00:00:00.000Z",
            max_supply_fee_cents=5000,
        ),
        headers=make_ill_staff_headers(),
    )


def test_an_intake_payload_that_worked_a_moment_ago_is_refused_after_the_patron_is_blocked(
    client,
):
    """Nothing on the request side of the payload changed between the two calls; only the
    patron row moved, and the gate reads that row rather than remembering the earlier verdict.

    PRD: "The third, fourth and fifth gates concern the patron: an account whose `status` is
    `BLOCKED` or `WITHDRAWN` is refused with `ERR_PATRON_BLOCKED`; an account whose
    `open_request_count` has already reached `max_open_requests` is refused with
    `ERR_PATRON_REQUEST_CAP_REACHED`; and an account whose provisional standing score reaches
    the block threshold of 40 is refused with `ERR_PATRON_STANDING_BLOCKED`." And: "That
    amendment accepts any of `status`, `email`, `max_open_requests`, `max_concurrent_loans`
    and `unpaid_balance_cap_cents`, increments the patron's `version` by 1, and re-derives
    both `provisional_risk_score` and `final_risk_score` afterwards."

    Design: Difficulty/cross_entity_state_dependency/intake_gate_reads_patron_status_blocked_written_after_an_earlier_success
    """
    world = _patron_with_one_live_request_and_a_second_work_to_ask_for(client)

    blocked = update_patron(
        client, world["patron"]["id"], status=PatronStatus.BLOCKED
    )
    assert blocked["status"] == PatronStatus.BLOCKED
    assert blocked["open_request_count"] == 1

    validate_error(
        _second_intake_attempt(client, world),
        ApiErrorId.PATRON_BLOCKED,
        expected_status=403,
    )


def test_blocking_the_patron_leaves_the_request_already_in_flight_exactly_where_it_was(
    client,
):
    """The block is a gate on new intake and not a cancellation, so the earlier request is
    still the patron's single live one and the refused call added nothing beside it.

    PRD: "And `open_request_count` counts that patron's requests whose `status` is none of
    `CLOSED`, `CLOSED_WITH_DAMAGE`, `CLOSED_LOST`, `CANCELLED`, `UNFILLED`,
    `FILLED_BY_PURCHASE` or `UNCLAIMED` — in other words, the requests still consuming desk
    attention." And: "`pending_charge_cents` is the sum of `net_patron_charge_cents` over that
    patron's requests whose `status` is anything other than `CANCELLED` or `UNFILLED`."

    Design: Difficulty/cross_entity_state_dependency/intake_gate_reads_patron_status_blocked_written_after_an_earlier_success
    """
    world = _patron_with_one_live_request_and_a_second_work_to_ask_for(client)
    patron_id = world["patron"]["id"]
    update_patron(client, patron_id, status=PatronStatus.BLOCKED)
    validate_error(
        _second_intake_attempt(client, world), ApiErrorId.PATRON_BLOCKED
    )

    rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(), params={"patron_id": patron_id}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [world["first_request"]["id"]]
    assert rows[0]["status"] == RequestStatus.SOURCING

    untouched_work = validate_success(
        client.get_bib_item(world["second_work"]["id"], headers=make_ill_staff_headers())
    )
    assert untouched_work["local_holding_status"] == LocalHoldingStatus.NONE

    patron = read_patron(client, patron_id)
    assert patron["open_request_count"] == 1
    assert patron["pending_charge_cents"] == 0
    assert patron["status"] == PatronStatus.BLOCKED


def _open_offer_from_a_partner_we_can_suspend(client):
    """One offer standing open inside its response window against a lender whose master-data
    row we can move underneath it."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8013",
        full_name="Mo Grad",
        email="mo@u.edu",
        patron_type="GRAD",
        department="CHEM",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    assert partner["status"] == PartnerStatus.ACTIVE
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Organometallic Synthesis",
        item_type=ItemType.BOOK,
        publication_year=2017,
        isbn="978-0-000-00008-0",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    assert offer["status"] == OfferStatus.OFFERED
    return {"partner": partner, "request": request, "offer": offer}


def test_an_open_offer_cannot_be_accepted_once_its_own_lender_has_been_suspended(client):
    """The offer row is untouched and still inside its window, yet the acceptance reads the
    partner's master-data status and refuses on that ground rather than on the offer's own.

    PRD: "Beyond the offer being open, the accepting partner must still be `ACTIVE` and must
    still support the request's `service_type`, otherwise the acceptance is refused with
    `ERR_PARTNER_NOT_ELIGIBLE` — a partner suspended between the offer and the answer cannot
    commit." And: "An administrator may amend a partner's `status`,
    `base_lending_fee_cents`, `avg_turnaround_days`, `ships_physical`, `supplies_electronic`,
    `allows_renewals`, `loan_period_days` or `max_renewals`."

    Design: Difficulty/cross_entity_state_dependency/offer_acceptance_gate_reads_partner_status_suspended_after_the_offer_opened
    """
    world = _open_offer_from_a_partner_we_can_suspend(client)
    partner_id = world["partner"]["id"]
    offer_id = world["offer"]["id"]

    suspended = update_partner(client, partner_id, status=PartnerStatus.SUSPENDED)
    assert suspended["status"] == PartnerStatus.SUSPENDED

    validate_error(
        client.accept_offer(offer_id, headers=make_partner_agent_headers(partner_id)),
        ApiErrorId.PARTNER_NOT_ELIGIBLE,
        expected_status=422,
    )

    still_open = validate_success(
        client.get_supply_offer(offer_id, headers=make_ill_staff_headers())
    )
    assert still_open["status"] == OfferStatus.OFFERED

    waiting = read_request(client, world["request"]["id"])
    assert waiting["status"] == RequestStatus.OFFER_PENDING
    assert waiting["committed_partner_id"] is None


def test_restoring_the_lender_lets_the_very_same_acceptance_through_and_commits_the_supply(
    client,
):
    """Nothing about the offer or the payload is rewritten between the refusal and the
    success, so the reinstated partner row is the only thing that changed the outcome.

    PRD: "Acceptance drives `OFFERED → ACCEPTED` and the request `OFFER_PENDING →
    SUPPLY_COMMITTED`." And: "On success the request takes its commitment snapshot:
    `committed_partner_id` is set to the accepting partner, `committed_fee_cents` is set to
    the offer's `effective_fee_cents`, and `committed_loan_period_days` is set from that
    partner's current `loan_period_days`."

    Design: Difficulty/cross_entity_state_dependency/offer_acceptance_gate_reads_partner_status_suspended_after_the_offer_opened
    """
    world = _open_offer_from_a_partner_we_can_suspend(client)
    partner_id = world["partner"]["id"]
    offer_id = world["offer"]["id"]

    update_partner(client, partner_id, status=PartnerStatus.SUSPENDED)
    validate_error(
        client.accept_offer(offer_id, headers=make_partner_agent_headers(partner_id)),
        ApiErrorId.PARTNER_NOT_ELIGIBLE,
    )

    restored = update_partner(client, partner_id, status=PartnerStatus.ACTIVE)
    assert restored["status"] == PartnerStatus.ACTIVE

    accepted = validate_success(
        client.accept_offer(offer_id, headers=make_partner_agent_headers(partner_id))
    )
    assert accepted["status"] == OfferStatus.ACCEPTED

    committed = read_request(client, world["request"]["id"])
    assert committed["status"] == RequestStatus.SUPPLY_COMMITTED
    assert committed["committed_partner_id"] == partner_id
    assert committed["committed_fee_cents"] == 2000
    assert committed["committed_loan_period_days"] == 28
    assert read_partner(client, partner_id)["status"] == PartnerStatus.ACTIVE


def _dead_end_request_whose_work_can_be_moved_onto_our_shelf(client):
    """A request whose single rota round has been declined, so purchase escalation is the
    only path left, alongside a work whose holdings row we can edit."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8014",
        full_name="Nia Faculty",
        email="nia@u.edu",
        patron_type="FACULTY",
        department="ECON",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Single attempt rota",
        material_type=MaterialType.LOAN,
        max_attempts=1,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Regional Input-Output Tables 2024",
        item_type=ItemType.BOOK,
        publication_year=2024,
        isbn="978-0-000-00009-7",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    declined = decline_offer(
        client, offer["id"], partner["id"], decline_reason=DeclineReason.NOT_HELD
    )
    assert declined["status"] == OfferStatus.DECLINED
    dead_end = read_request(client, request["id"])
    assert dead_end["status"] == RequestStatus.SOURCING
    assert dead_end["attempt_count"] == 1
    return {"request": request, "bib_item": bib_item}


def test_escalation_re_reads_the_work_and_refuses_once_it_has_landed_on_our_own_shelf(
    client,
):
    """Intake cleared this work when nothing was held locally, but the escalation consults the
    record again rather than trusting that verdict, and the acquisitions edit now closes it.

    PRD: "Escalation is refused with `ERR_ALREADY_HELD_LOCALLY` when the work's
    `local_holding_status` is `HELD_AVAILABLE` or `ON_ORDER` — there is no point buying a book
    that is already on the shelf or already on order." And: "Holdings facts change, so a
    `LibraryAdmin` or `AcquisitionsLibrarian` may amend a record's `local_holding_status`,
    `licensed_access_status`, `embargo_months` or `list_price_cents`; each amendment increments
    that record's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/escalation_gate_reads_bib_item_local_holding_written_after_intake
    """
    world = _dead_end_request_whose_work_can_be_moved_onto_our_shelf(client)
    request_id = world["request"]["id"]

    now_held = update_bib_item(
        client,
        world["bib_item"]["id"],
        local_holding_status=LocalHoldingStatus.HELD_AVAILABLE,
    )
    assert now_held["local_holding_status"] == LocalHoldingStatus.HELD_AVAILABLE
    assert now_held["version"] == world["bib_item"]["version"] + 1

    validate_error(
        client.escalate_request(
            request_id,
            escalate_payload(vendor="AcmeBooks"),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.ALREADY_HELD_LOCALLY,
        expected_status=422,
    )

    rows, meta = validate_paginated(
        client.list_pod_orders(request_id, headers=make_ill_staff_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_request(client, request_id)["status"] == RequestStatus.SOURCING


def test_returning_the_work_to_unheld_lets_the_identical_escalation_open_a_proposal(client):
    """Moving the neighbouring record back is the only difference between the refusal and the
    success, and the proposal that opens snapshots the price off that same record.

    PRD: "The order records the request, a `vendor` supplied by the caller, a
    `list_price_cents` snapshotted from the work's `list_price_cents` at escalation, and an
    `escalated_by_user_id` holding the escalating `X-User-ID`, or the literal string `system`
    when the operational sweep escalated automatically." And: "It opens at `status` `PROPOSED`
    with `decided_by_user_id`, `decision_note`, `decided_at` and `received_at` all null."

    Design: Difficulty/cross_entity_state_dependency/escalation_gate_reads_bib_item_local_holding_written_after_intake
    """
    world = _dead_end_request_whose_work_can_be_moved_onto_our_shelf(client)
    request_id = world["request"]["id"]
    update_bib_item(
        client,
        world["bib_item"]["id"],
        local_holding_status=LocalHoldingStatus.HELD_AVAILABLE,
    )
    validate_error(
        client.escalate_request(
            request_id,
            escalate_payload(vendor="AcmeBooks"),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.ALREADY_HELD_LOCALLY,
    )

    unheld_again = update_bib_item(
        client, world["bib_item"]["id"], local_holding_status=LocalHoldingStatus.NONE
    )
    assert unheld_again["local_holding_status"] == LocalHoldingStatus.NONE

    order = escalate_request(client, request_id, vendor="AcmeBooks")
    assert order["status"] == PodOrderStatus.PROPOSED
    assert order["list_price_cents"] == 9000
    assert order["decided_by_user_id"] is None
    assert order["decision_note"] is None
    assert order["decided_at"] is None
    assert order["received_at"] is None

    assert read_request(client, request_id)["status"] == RequestStatus.ESCALATED_POD
    orders = list_pod_orders(client, request_id)
    assert [row["id"] for row in orders] == [order["id"]]
