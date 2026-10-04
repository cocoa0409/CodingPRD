"""Cross-cutting behaviour: one-hop cascades, clock-driven sweeps, pinned
derived fields, and immediate read-after-write visibility.
"""

from test_helpers import constants as C
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
    validate_paginated,
)
from test_helpers.fixtures import (
    active_contract,
    add_room_class,
    add_study,
    book_reservation,
    bookable_inventory,
    hire_employee,
    housing_scenario,
    reset_clock,
    set_clock,
    vouchers_for_hire,
)
from test_helpers.test_users import (
    FRONT_DESK,
    HR_MANAGER,
    OPS_MANAGER,
    RATE_ANALYST,
)


class TestArrivalConsumesTheVoucher:
    def test_mark_arrived_moves_the_linked_voucher_to_used(self, client):
        """PRD 3.7: "When the employee shows up, the HR manager marks the
        hire arrived, moving it from `HIRED` to `ARRIVED`; the linked booked
        voucher is consumed to `USED` in the same breath."

        Design: Corner/cross_cutting_complexity_layers/cascade_chain_hire_arrive_marks_voucher_used
        """
        scenario = housing_scenario(client, bed_count=2)
        contract_id = scenario["contract"]["id"]
        hire = hire_employee(
            client, contract_id,
            scenario["season"]["id"],
            scenario["lines"][C.LINE_LODGING]["id"],
            scenario["unit"]["id"],
            needs_transport=True, transport_origin="Salt Lake City",
        )
        assert vouchers_for_hire(client, contract_id, hire["id"])[0][
            "status"
        ] == C.VOUCHER_BOOKED
        arrived = get_success_data(client.mark_arrived(
            contract_id, hire["id"], headers=HR_MANAGER
        ))
        assert arrived["status"] == C.HIRE_ARRIVED
        vouchers = vouchers_for_hire(client, contract_id, hire["id"])
        assert vouchers[0]["status"] == C.VOUCHER_USED


class TestSeasonCloseSweep:
    def test_a_checked_in_reservation_is_swept_to_fulfilled_at_close(
        self, client
    ):
        """PRD 3.3: "When the season itself closes — the logical clock
        reaching its `close_date` — every still-`CONFIRMED` reservation is
        resolved by the close sweep: those whose `check_out_date` falls on or
        before the close date become `FULFILLED`, and those whose check-out
        falls after the close date become `NO_SHOW`."

        Design: Corner/cross_cutting_complexity_layers/season_close_sweeps_confirmed_reservations_to_fulfilled
        """
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        reservation = book_reservation(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            scenario["version"],
            guest_ref="g-sweep",
            check_in_date="2027-08-28T00:00:00Z",
            check_out_date="2027-08-31T00:00:00Z",
        )
        set_clock(client, "2027-01-01T00:00:00Z")  # close the lottery window
        set_clock(client, "2027-08-28T12:00:00Z")
        client.check_in_reservation(
            contract_id, reservation["id"], headers=FRONT_DESK
        )
        set_clock(client, "2027-09-01T00:00:01Z")  # past close_date
        season = get_success_data(client.get_season(
            contract_id, scenario["season"]["id"], headers=OPS_MANAGER
        ))
        assert season["status"] == C.SEASON_CLOSED
        reread = get_success_data(client.get_reservation(
            contract_id, reservation["id"], headers=FRONT_DESK
        ))
        assert reread["status"] == C.RESERVATION_FULFILLED


class TestApprovedMeanPinned:
    def test_a_newer_study_does_not_rewrite_an_approved_filing(self, client):
        """PRD 3.2: "its `approved_weighted_mean_cents` is pinned to the
        study's `weighted_mean_cents` as of the approval moment, so that a
        later change in study state cannot rewrite history."

        Design: Corner/cross_cutting_complexity_layers/approved_weighted_mean_pinned_against_later_study_change
        """
        scenario = bookable_inventory(client, clock=None)
        contract_id = scenario["contract"]["id"]
        filing = scenario["filing"]
        assert_cents(filing["approved_weighted_mean_cents"], 25000,
                     "approved_weighted_mean_cents at approval")
        add_study(
            client, contract_id, title="S2-newer",
            comparables=[dict(c) for c in C.STUDY_MEAN_20500_COMPARABLES],
            prepared_at="2026-08-01T00:00:00Z",
            valid_through="2028-06-01T00:00:00Z",
        )
        reread = get_success_data(client.get_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        ))
        assert_cents(reread["approved_weighted_mean_cents"], 25000,
                     "approved_weighted_mean_cents stays pinned")
        assert reread["status"] == C.FILING_APPROVED


class TestImmediateReadAfterWrite:
    def test_a_created_room_class_is_visible_in_the_next_read(self, client):
        """PRD 2.6 and 2.4 together fix a single logical clock and immediate
        visibility: "updated_at ... refreshed on every mutation" and the
        clock-advance rule "A single clock advance must apply every
        time-based transition whose precondition now holds."

        Design: Corner/consistency_model/writes_are_immediately_visible_in_subsequent_reads
        """
        reset_clock(client)
        contract, _season, _lines = active_contract(client)
        created = get_success_data(client.create_room_class(
            contract["id"],
            {"code": "IMM_1", "total_rooms": 3, "peak_season_months": [7]},
            headers=OPS_MANAGER,
        ))
        rows, _meta = validate_paginated(client.list_room_classes(
            contract["id"], headers=OPS_MANAGER
        ))
        match = [row for row in rows if row["id"] == created["id"]]
        assert len(match) == 1
        assert match[0]["code"] == "IMM_1"
        assert match[0]["total_rooms"] == 3
        assert match[0]["status"] == C.ROOM_CLASS_ACTIVE
