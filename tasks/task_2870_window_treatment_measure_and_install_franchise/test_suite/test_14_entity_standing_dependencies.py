"""Booking reads the standing of the one designer it names, row by row."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_DESIGNER_NOT_ACTIVE
from test_helpers.assertions import assert_page_meta
from test_helpers.fixtures import (
    book_consultation,
    charter_territory,
    hire_designer,
    intake_lead,
    read_designer,
    read_territory,
    set_clock,
)
from test_helpers.test_users import designer_headers, franchisee_headers

FUTURE_START = "2026-09-15T14:00:00.000Z"
FUTURE_END = "2026-09-15T15:00:00.000Z"


def _one_retired_and_one_active_designer(api):
    """Two colleagues in one franchise, each with a future appointment; one retires.

    Both appointments sit on 2026-09-10 in the same hour but on different designers,
    so no calendar rule can interfere. A third lead is kept spare so an identical
    booking can be attempted against each designer after the retirement.
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    retiring = hire_designer(api, territory, full_name="Dana Reed")
    staying = hire_designer(api, territory, full_name="Milo Vance")
    first = intake_lead(api, territory, customer_name="Ana Ruiz",
                        source="WEB_FORM",
                        requested_at="2026-08-01T08:00:00.000Z")
    second = intake_lead(api, territory, customer_name="Bo Chen",
                         source="REFERRAL",
                         requested_at="2026-08-01T09:00:00.000Z")
    spare = intake_lead(api, territory, customer_name="Cy Doyle",
                        source="WALK_IN",
                        requested_at="2026-08-01T10:00:00.000Z")
    retiring_appointment = book_consultation(
        api, retiring, first,
        scheduled_start_at="2026-09-10T14:00:00.000Z",
        scheduled_end_at="2026-09-10T15:00:00.000Z")
    staying_appointment = book_consultation(
        api, staying, second,
        scheduled_start_at="2026-09-10T14:00:00.000Z",
        scheduled_end_at="2026-09-10T15:00:00.000Z")
    set_clock(api, "2026-08-05T09:00:00.000Z")
    validate_success(api.patch_designer(retiring["id"],
                                        f.designer_patch(status="INACTIVE"),
                                        franchisee_headers(territory["id"])))
    return {"territory": territory, "retiring": retiring, "staying": staying,
            "spare": spare, "retiring_appointment": retiring_appointment,
            "staying_appointment": staying_appointment}


def test_retirement_cancels_only_its_own_designers_future_appointment(api):
    """`ACTIVE → INACTIVE` sweeps one calendar and leaves the colleague's alone.

    "The same operation drives `ACTIVE → INACTIVE`, which is terminal, and retiring a
    designer this way cancels that designer's future scheduled consultations and install
    jobs in precisely the same way a suspension does."

    "Every consultation of that designer that is still `SCHEDULED` and whose
    `scheduled_start_at` is at or after the logical clock moves `SCHEDULED →
    CANCELLED`, and every install job of that designer that is still `SCHEDULED` and
    whose `scheduled_start_at` is at or after the logical clock moves `install_status`
    `SCHEDULED → CANCELLED`."

    Design: Difficulty/cross_entity_state_dependency/consultation_creation_is_refused_by_the_referenced_designers_own_state
    """
    world = _one_retired_and_one_active_designer(api)
    territory = world["territory"]
    owner = franchisee_headers(territory["id"])

    assert read_designer(api, territory,
                         world["retiring"]["id"])["status"] == "INACTIVE"
    assert read_designer(api, territory,
                         world["staying"]["id"])["status"] == "ACTIVE"

    cancelled = validate_success(api.get_consultation(
        world["retiring_appointment"]["id"], owner))
    assert cancelled["status"] == "CANCELLED"

    survivor = validate_success(api.get_consultation(
        world["staying_appointment"]["id"], owner))
    assert survivor["status"] == "SCHEDULED"

    # Retirement is an administrative act, not an incident: nobody is re-scored.
    assert read_designer(api, territory,
                         world["retiring"]["id"])["remeasure_liability_score"] == 100


def test_the_booking_gate_reads_the_named_designer_not_the_territory(api):
    """The identical body is refused for the retired designer and accepted for the other.

    "A designer's `status` is `ACTIVE`, `SUSPENDED` or `INACTIVE`, and only `ACTIVE`
    designers may be booked onto consultations or install jobs."

    "**Designer standing** — `ERR_DESIGNER_NOT_ACTIVE` on `POST /blinds/consultations`
    and `POST /blinds/install-jobs` when the named designer is `SUSPENDED` or
    `INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/consultation_creation_is_refused_by_the_referenced_designers_own_state
    """
    world = _one_retired_and_one_active_designer(api)
    territory, spare = world["territory"], world["spare"]
    retiring, staying = world["retiring"], world["staying"]
    owner = franchisee_headers(territory["id"])

    validate_error(
        api.create_consultation(
            f.consultation_payload(spare["id"], retiring["id"],
                                   scheduled_start_at=FUTURE_START,
                                   scheduled_end_at=FUTURE_END),
            designer_headers(retiring["id"])),
        ERR_DESIGNER_NOT_ACTIVE, 409)

    booked = validate_success(
        api.create_consultation(
            f.consultation_payload(spare["id"], staying["id"],
                                   scheduled_start_at=FUTURE_START,
                                   scheduled_end_at=FUTURE_END),
            designer_headers(staying["id"])), 201)
    assert booked["status"] == "SCHEDULED"
    assert booked["designer_id"] == staying["id"]

    # The refusal wrote nothing: the retired designer keeps only the cancelled row.
    _rows, meta = validate_paginated(
        api.list_consultations(owner, designer_id=retiring["id"]))
    assert_page_meta(meta, total_count=1, has_more=False)

    assert validate_success(
        api.get_lead(spare["id"], owner))["status"] == "ROUTED"
    assert read_territory(api, territory)["open_leads_count"] == 3
