"""Appointment slot lifecycle: capacity oscillation, release, and booking conservation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_active_contract,
    create_terminal_with_labor_day,
    create_return_location,
    create_slot,
    create_available_container,
    set_clock,
    validate_error,
    validate_success,
)

CM = {"X-User-ID": "cm-1", "X-User-Role": "ContractManager"}
TO = {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"}


def _stack_with_slot(account_code, contract_ref, slot_date, capacity):
    """Terminal + holiday + slot + account/contract + DRY40 return location."""
    terminal = create_terminal_with_labor_day(terminal_code="OAK")
    slot = create_slot(
        terminal["id"], slot_date=f"{slot_date}T00:00:00Z", slot_seq=1, capacity=capacity
    )
    account = create_account(account_code=account_code, legal_name=f"{account_code} Co")
    contract = create_active_contract(
        account["id"], contract_ref=contract_ref,
        demurrage_free_days=2, detention_free_days=5, saturday_counts_as_free_day=False,
    )
    create_return_location(terminal["id"], location_code="LOC-1")
    return terminal, slot, account, contract


def _available_container(account, contract, terminal, number):
    return create_available_container(
        account, contract, terminal,
        container_number=number,
        discharge_ts="2026-09-08T12:00:00Z",
        available_ts="2026-09-09T12:00:00Z",
    )


class TestSlotOscillation:
    def test_open_full_open_then_released_terminal(self):
        """PRD §3.2: "when a booking pushes `booked_count` to equal `capacity`,
        the slot flips from `OPEN` to `FULL`; when a cancellation brings
        `booked_count` back below `capacity`, a `FULL` slot reopens to `OPEN`.
        A `TerminalOperator` may also administratively release a slot, moving
        it from `OPEN` to `RELEASED`; subsequent booking attempts against a
        `RELEASED` slot are rejected with `ERR_SLOT_RELEASED`".

        Design: Difficulty/non_linear_state_machine/slot_open_full_open_oscillation_on_terminal_appointment_slot
        """
        terminal, slot, account, contract = _stack_with_slot(
            "ACCT-F", "CTR-F", "2026-09-10", capacity=1
        )
        container = _available_container(account, contract, terminal, "MATU0000078")

        booking = validate_success(
            api_client.book_appointment(container["id"], {"slot_id": slot["id"]}, TO), 201
        )
        mid = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert mid["status"] == "FULL" and mid["booked_count"] == 1

        validate_success(
            api_client.cancel_appointment(container["id"], booking["booking_id"], TO)
        )
        after = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert after["status"] == "OPEN" and after["booked_count"] == 0

        validate_success(api_client.release_appointment_slot(slot["id"], TO))
        resp = api_client.book_appointment(container["id"], {"slot_id": slot["id"]}, TO)
        validate_error(resp, ApiErrorId.ERR_SLOT_RELEASED)

    def test_released_slot_preserves_booked_count_as_evidence(self):
        """PRD §3.2: "A `TerminalOperator` may also administratively release a
        slot, moving it from `OPEN` to `RELEASED`; subsequent booking attempts
        against a `RELEASED` slot are rejected with `ERR_SLOT_RELEASED`, while
        the slot's `booked_count` is preserved so that released-but-congested
        days remain visible as dispute evidence."

        Design: Difficulty/non_linear_state_machine/slot_open_full_open_oscillation_on_terminal_appointment_slot
        """
        terminal, slot, account, contract = _stack_with_slot(
            "ACCT-F2", "CTR-F2", "2026-09-10", capacity=2
        )
        container = _available_container(account, contract, terminal, "MATU0000400")
        validate_success(
            api_client.book_appointment(container["id"], {"slot_id": slot["id"]}, TO), 201
        )
        validate_success(api_client.release_appointment_slot(slot["id"], TO))
        released = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert released["status"] == "RELEASED"
        assert released["booked_count"] == 1, "booked_count must be preserved on release"

    def test_capacity_two_admits_exactly_two_bookings(self):
        """PRD §3.2: "The system maintains the invariant that `booked_count`
        never falls below zero and never exceeds `capacity`: when a booking
        pushes `booked_count` to equal `capacity`, the slot flips from `OPEN`
        to `FULL`".
        PRD §3.4: "booked in advance by a `TerminalOperator` or the customer's
        own `CustomerRep` against a specific slot via `slot_id`, which
        increments the slot's `booked_count` and is refused with
        `ERR_CAPACITY_OR_CONFLICT` when the slot is `FULL` or
        `ERR_SLOT_RELEASED` when it is `RELEASED`."

        Design: Difficulty/resource_temporal_overlap/appointment_slot_capacity_exhaustion_per_day
        """
        terminal, slot, account, contract = _stack_with_slot(
            "ACCT-O", "CTR-O", "2026-09-10", capacity=2
        )
        c1 = _available_container(account, contract, terminal, "MATU0000185")
        c2 = _available_container(account, contract, terminal, "MATU0000193")
        c3 = _available_container(account, contract, terminal, "MATU0000201")

        validate_success(api_client.book_appointment(c1["id"], {"slot_id": slot["id"]}, TO), 201)
        validate_success(api_client.book_appointment(c2["id"], {"slot_id": slot["id"]}, TO), 201)
        third = api_client.book_appointment(c3["id"], {"slot_id": slot["id"]}, TO)
        validate_error(third, ApiErrorId.ERR_CAPACITY_OR_CONFLICT)

        final = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert final["status"] == "FULL"
        assert final["booked_count"] == 2


class TestSlotCapacityBoundary:
    def test_booking_at_exact_capacity_boundary(self):
        """PRD §3.2: "The system maintains the invariant that `booked_count`
        never falls below zero and never exceeds `capacity`: when a booking
        pushes `booked_count` to equal `capacity`, the slot flips from `OPEN`
        to `FULL`".

        Design: Difficulty/resource_temporal_overlap/appointment_slot_capacity_exhaustion_per_day
        """
        terminal, slot, account, contract = _stack_with_slot(
            "ACCT-O2", "CTR-O2", "2026-09-10", capacity=1
        )
        c1 = _available_container(account, contract, terminal, "MATU0000500")
        validate_success(api_client.book_appointment(c1["id"], {"slot_id": slot["id"]}, TO), 201)
        full = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert full["status"] == "FULL"
        assert full["booked_count"] == 1 == full["capacity"]


class TestSlotBookedCountConservation:
    def test_book_then_cancel_restores_occupancy_exactly(self):
        """PRD §3.2: "when a booking pushes `booked_count` to equal `capacity`,
        the slot flips from `OPEN` to `FULL`; when a cancellation brings
        `booked_count` back below `capacity`, a `FULL` slot reopens to `OPEN`."

        Design: Difficulty/compensating_invariant/slot_booked_count_conserved_under_book_and_cancel
        """
        terminal, slot, account, contract = _stack_with_slot(
            "ACCT-R", "CTR-R", "2026-09-11", capacity=1
        )
        container = _available_container(account, contract, terminal, "MATU0000227")

        booking = validate_success(
            api_client.book_appointment(container["id"], {"slot_id": slot["id"]}, TO), 201
        )
        mid = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert mid["status"] == "FULL" and mid["booked_count"] == 1

        validate_success(
            api_client.cancel_appointment(container["id"], booking["booking_id"], TO)
        )
        end = validate_success(api_client.get_appointment_slot(slot["id"], TO))
        assert end["status"] == "OPEN"
        assert end["booked_count"] == 0

    def test_slot_accepts_fresh_booking_after_cancel(self):
        """PRD §3.4: "A booking may also be cancelled, which decrements the
        slot's `booked_count` and reopens a `FULL` slot to `OPEN`; the booking
        record carries a `booking_id`, the `slot_id`, the `container_id`, and
        the `booked_date`."

        Design: Difficulty/compensating_invariant/slot_booked_count_conserved_under_book_and_cancel
        """
        terminal, slot, account, contract = _stack_with_slot(
            "ACCT-R2", "CTR-R2", "2026-09-11", capacity=1
        )
        container = _available_container(account, contract, terminal, "MATU0000300")

        booking = validate_success(
            api_client.book_appointment(container["id"], {"slot_id": slot["id"]}, TO), 201
        )
        validate_success(
            api_client.cancel_appointment(container["id"], booking["booking_id"], TO)
        )
        fresh = validate_success(
            api_client.book_appointment(container["id"], {"slot_id": slot["id"]}, TO), 201
        )
        assert fresh["booking_id"], "a fresh booking id must be returned after the cancel"
