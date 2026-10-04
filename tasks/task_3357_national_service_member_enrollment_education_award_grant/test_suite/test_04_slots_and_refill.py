"""Position slot ledger: minting, deterministic selection, the refill cycle
with its fill_count termination, and half-open service-period overlap
(PRD §3.2, §3.3, §3.4)."""
from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    award_application_payload,
    award_version,
    certify_minutes,
    create_draft_application,
    create_enrollment_payload,
    enroll,
    exit_member,
    get_enrollment,
    make_grantee_staff_headers,
    match_line,
    register_cleared_member,
    setup_awarded_program,
    setup_org_competition,
    slot_request,
    submit_application,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ONE_FT_SLOT = {
    "federal_share_requested_cents": 2300000,
    "slot_requests": [slot_request("FULL_TIME", 1)],
    "match_lines": [match_line("CASH", 560000)],
}
TWO_FT_SLOT_AT_CAP = {
    "federal_share_requested_cents": 4600000,
    "slot_requests": [slot_request("FULL_TIME", 2)],
    "match_lines": [match_line("CASH", 1104000)],
}
MEMBER_B = {"full_name": "Blair Kim", "date_of_birth": "1999-05-20",
            "citizenship_status": "US_NATIONAL"}
MEMBER_C = {"full_name": "Casey Jo", "date_of_birth": "2001-03-03",
            "citizenship_status": "LAWFUL_PERMANENT_RESIDENT"}


def _slots_by_index(api, award_id, officer_headers):
    slots, _ = validate_paginated(api.list_slots(award_id, officer_headers))
    return {s["slot_index"]: s for s in slots}


class TestSlotRefillCycleTerminates:
    def _setup_single_slot_with_a_active(self, api):
        program = setup_awarded_program(**ONE_FT_SLOT)
        member_a = register_cleared_member(program["org_id"])
        enrollment_a = enroll(program["award_id"], program["org_id"], member_a)
        certify_minutes(enrollment_a["id"], program["org_id"], [15300])
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        return program, member_a, enrollment_a, member_b

    def test_vacated_slot_reopens_and_refills_same_slot(self, api, officer_headers):
        """After member A's exit the same slot is OPEN again with fill_count 1,
        and the refill selector assigns member B to that same slot, which fills
        it a second time (fill_count 2).

        PRD §3.3: "Vacancy triggers immediate refill evaluation: if the award is `ACTIVE` and the slot's `fill_count` is still below 2, the slot reopens (`VACATED` → `OPEN`)"
        PRD §3.4: "among the award's slots that are `OPEN` and match the requested `term_category`, it picks the one with the lowest `slot_index`"

        Design: Difficulty/non_linear_state_machine/slot_refill_cycle_terminates
        """
        program, member_a, enrollment_a, member_b = self._setup_single_slot_with_a_active(api)
        slot_id = enrollment_a["slot_id"]
        exit_member(enrollment_a["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        slot = validate_success(api.get_slot(slot_id, officer_headers))
        assert slot["status"] == "OPEN" and slot["fill_count"] == 1, "refill, not replacement"
        enrollment_b = enroll(
            program["award_id"], program["org_id"], member_b,
            service_start_date="2026-11-01", service_end_date="2027-09-01",
        )
        assert enrollment_b["slot_id"] == slot_id, "member B refills the SAME slot"
        refilled = validate_success(api.get_slot(slot_id, officer_headers))
        assert refilled["status"] == "FILLED" and refilled["fill_count"] == 2

    def test_second_vacancy_retires_slot(self, api, officer_headers):
        """Once fill_count reaches 2 the next vacancy retires the slot — the
        OPEN -> RESERVED -> FILLED -> VACATED -> OPEN cycle terminates.

        PRD §3.3: "if the award is anything other than `ACTIVE`, or the slot has already been filled twice, the slot is `RETIRED`. A slot already filled twice is never offered again"

        Design: Difficulty/non_linear_state_machine/slot_refill_cycle_terminates
        """
        program, member_a, enrollment_a, member_b = self._setup_single_slot_with_a_active(api)
        slot_id = enrollment_a["slot_id"]
        exit_member(enrollment_a["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        enrollment_b = enroll(
            program["award_id"], program["org_id"], member_b,
            service_start_date="2026-11-01", service_end_date="2027-09-01",
        )
        certify_minutes(enrollment_b["id"], program["org_id"], [15300],
                        first_service_date=date(2026, 11, 2))
        exit_member(enrollment_b["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        slot = validate_success(api.get_slot(slot_id, officer_headers))
        assert slot["status"] == "RETIRED" and slot["fill_count"] == 2
        slots, meta = validate_paginated(api.list_slots(program["award_id"], officer_headers))
        assert meta["total_count"] == 1 and slots[0]["status"] == "RETIRED"


class TestSlotConservation:
    def _setup_two_slots(self, api):
        program = setup_awarded_program(**TWO_FT_SLOT_AT_CAP)
        member_a = register_cleared_member(program["org_id"])
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        member_c = register_cleared_member(program["org_id"], **MEMBER_C)
        enrollment_a = enroll(program["award_id"], program["org_id"], member_a)
        enrollment_b = enroll(program["award_id"], program["org_id"], member_b)
        return program, member_a, member_b, member_c, enrollment_a, enrollment_b

    def test_fill_and_vacate_preserve_slot_population(self, api, officer_headers):
        """Enrolling two members fills both slots (FILLED 2, OPEN 0, RETIRED 0
        == awarded_slot_count 2); member A's exit reopens only A's slot with
        fill_count 1 (FILLED 1, OPEN 1, RETIRED 0).

        PRD §3.3: "Slots move on system events, never on direct request: enrollment creation reserves one (`OPEN` → `RESERVED`); a cleared criminal history check fills it (`RESERVED` → `FILLED`, `fill_count` incremented); a flagged check releases it back (`RESERVED` → `OPEN`); a member exit vacates it (`FILLED` → `VACATED`)."
        PRD §3.2: "one PositionSlot is minted per requested slot unit — `awarded_slot_count` in total, the sum of the `slot_requests` counts"

        Design: Difficulty/compensating_invariant/slot_conservation_across_fill_vacate_refill_retire
        """
        program, m_a, m_b, m_c, enr_a, enr_b = self._setup_two_slots(api)
        slot_a = enr_a["slot_id"]
        slots, meta = validate_paginated(api.list_slots(program["award_id"], officer_headers))
        assert meta["total_count"] == 2
        statuses = sorted(s["status"] for s in slots)
        assert statuses == ["FILLED", "FILLED"]
        certify_minutes(enr_a["id"], program["org_id"], [15300])
        exit_member(enr_a["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        slot = validate_success(api.get_slot(slot_a, officer_headers))
        assert slot["status"] == "OPEN" and slot["fill_count"] == 1
        slots2, _ = validate_paginated(api.list_slots(program["award_id"], officer_headers))
        counts = {}
        for s in slots2:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        assert counts.get("FILLED") == 1 and counts.get("OPEN") == 1
        assert counts.get("RETIRED", 0) == 0
        assert len(slots2) == 2, "slots are never created or destroyed"

    def test_refill_then_for_cause_exit_retires_slot_and_debars_member(self, api, officer_headers):
        """Member C refills A's vacated slot (lowest OPEN slot_index); C's
        FOR_CAUSE exit retires that slot (fill_count 2), debars C, and creates
        no education award — final ledger: FILLED 1 (B) + RETIRED 1 == 2.

        PRD §3.3: "if the award is anything other than `ACTIVE`, or the slot has already been filled twice, the slot is `RETIRED`."
        PRD §3.7: "No education award is created (`education_award_id` stays null), the member is `DEBARRED` from further service, and the member's `for_cause_release_count` increments"

        Design: Difficulty/compensating_invariant/slot_conservation_across_fill_vacate_refill_retire
        """
        program, m_a, m_b, m_c, enr_a, enr_b = self._setup_two_slots(api)
        slot_a = enr_a["slot_id"]
        certify_minutes(enr_a["id"], program["org_id"], [15300])
        exit_member(enr_a["id"], program["org_id"], "COMPELLING_CIRCUMSTANCE")
        enr_c = enroll(
            program["award_id"], program["org_id"], m_c,
            service_start_date="2026-11-01", service_end_date="2027-09-01",
        )
        assert enr_c["slot_id"] == slot_a, "refill takes the lowest-index OPEN slot"
        exited_c = exit_member(enr_c["id"], program["org_id"], "FOR_CAUSE")
        assert exited_c["status"] == "RELEASED_FOR_CAUSE"
        assert exited_c["education_award_id"] is None
        slot = validate_success(api.get_slot(slot_a, officer_headers))
        assert slot["status"] == "RETIRED" and slot["fill_count"] == 2
        slots, _ = validate_paginated(api.list_slots(program["award_id"], officer_headers))
        counts = {}
        for s in slots:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        assert counts.get("FILLED") == 1 and counts.get("RETIRED") == 1
        assert len(slots) == 2
        member_c = validate_success(api.get_member(m_c, officer_headers))
        assert member_c["status"] == "DEBARRED"
        awards, meta = validate_paginated(
            api.list_education_awards(officer_headers, params={"enrollment_id": enr_c["id"]})
        )
        assert awards == [] and meta["total_count"] == 0


class TestMemberServicePeriodOverlap:
    def _setup_member_active(self, api):
        program = setup_awarded_program()
        member_a = register_cleared_member(program["org_id"])
        enrollment_a = enroll(program["award_id"], program["org_id"], member_a)
        return program, member_a, enrollment_a

    def test_adjacent_period_starting_on_end_date_allowed(self, api, officer_headers):
        """Back-to-back service: a second enrollment whose start equals the
        first enrollment's exclusive end date does not intersect it.

        PRD §3.4: "any other enrollment of the same member in `PENDING_CHECKS`, `ACTIVE`, or `SUSPENDED` whose half-open service period — inclusive of its start date, exclusive of its end date — intersects the requested period blocks the create with `ERR_SERVICE_PERIOD_OVERLAP`; back-to-back service, where the new start date equals an existing end date, is allowed."

        Design: Difficulty/resource_temporal_overlap/member_service_period_half_open_overlap
        """
        program, member_a, enrollment_a = self._setup_member_active(api)
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_a,
                service_start_date="2027-08-15",
                service_end_date="2028-04-15",
                expected_award_version=award_version(program["award_id"]),
            ),
            make_grantee_staff_headers(program["org_id"]),
        )
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "ACTIVE", "member's latest check is CLEARED"
        rows, meta = validate_paginated(
            api.list_enrollments(officer_headers, params={"member_id": member_a})
        )
        assert meta["total_count"] == 2

    def test_one_day_earlier_start_intersects_and_is_rejected(self, api, officer_headers):
        """Starting one day before the first enrollment's end date intersects
        the half-open period and is rejected.

        PRD §3.4: "intersects the requested period blocks the create with `ERR_SERVICE_PERIOD_OVERLAP`; back-to-back service, where the new start date equals an existing end date, is allowed."

        Design: Difficulty/resource_temporal_overlap/member_service_period_half_open_overlap
        """
        program, member_a, enrollment_a = self._setup_member_active(api)
        staff = make_grantee_staff_headers(program["org_id"])
        validate_success(
            api.create_enrollment(
                program["award_id"],
                create_enrollment_payload(
                    member_a,
                    service_start_date="2027-08-15",
                    service_end_date="2028-04-15",
                    expected_award_version=award_version(program["award_id"]),
                ),
                staff,
            ),
            201,
        )
        resp = api.create_enrollment(
            program["award_id"],
            create_enrollment_payload(
                member_a,
                service_start_date="2027-08-14",
                service_end_date="2028-04-14",
                expected_award_version=award_version(program["award_id"]),
            ),
            staff,
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_PERIOD_OVERLAP)
        assert resp.status_code == 409
        rows, meta = validate_paginated(
            api.list_enrollments(officer_headers, params={"member_id": member_a})
        )
        assert meta["total_count"] == 2


class TestSlotSelectorDeterminism:
    def test_lowest_slot_index_wins_in_order(self, api, officer_headers):
        """With two OPEN FULL_TIME slots, the first enrollment takes slot_index
        1 and the second takes slot_index 2.

        PRD §3.4: "among the award's slots that are `OPEN` and match the requested `term_category`, it picks the one with the lowest `slot_index` — unique per award, so no tie is possible"

        Design: Corner/cross-cutting complexity layers/slot_selector_picks_lowest_slot_index_deterministically
        """
        program = setup_awarded_program()
        by_index = _slots_by_index(api, program["award_id"], officer_headers)
        member_a = register_cleared_member(program["org_id"])
        member_b = register_cleared_member(program["org_id"], **MEMBER_B)
        enr_a = enroll(program["award_id"], program["org_id"], member_a)
        enr_b = enroll(program["award_id"], program["org_id"], member_b)
        assert sorted(by_index) == [1, 2]
        assert enr_a["slot_id"] == by_index[1]["id"], "lowest slot_index wins"
        assert enr_b["slot_id"] == by_index[2]["id"]


class TestMixedCategorySlotMinting:
    def test_award_mints_slots_in_slot_requests_order(self, api, officer_headers):
        """slot_requests [FULL_TIME x1, HALF_TIME x2] mint exactly 3 slots in
        array order — slot_index 1 FULL_TIME, 2 and 3 HALF_TIME — and the award
        stores total_term_minutes 210000 and cost_per_msy_awarded 1942857.14.

        PRD §3.2: "one PositionSlot is minted per requested slot unit — `awarded_slot_count` in total, the sum of the `slot_requests` counts — numbered by `slot_index` from 1 upward in `slot_requests` array order, each `OPEN` with `fill_count` 0"

        Design: Corner/endpoints/award_action_creates_mixed_category_slots
        """
        base = setup_org_competition()
        app = create_draft_application(
            base["comp_id"], base["org_id"],
            federal_share_requested_cents=4000000,
            slot_requests=[slot_request("FULL_TIME", 1), slot_request("HALF_TIME", 2)],
            match_lines=[match_line("CASH", 960000)],
        )
        submit_application(app["id"], base["org_id"])
        set_clock("2026-10-02T00:00:00Z")
        validate_success(api.close_competition(base["comp_id"], officer_headers))
        award = validate_success(
            api.award_application(app["id"], award_application_payload(4000000), officer_headers),
            201,
        )
        assert award["awarded_slot_count"] == 3
        assert award["total_term_minutes"] == 210000
        assert award["cost_per_msy_awarded_cents"] == pytest.approx(1942857.14, abs=0.005)
        by_index = _slots_by_index(api, award["id"], officer_headers)
        assert sorted(by_index) == [1, 2, 3]
        assert by_index[1]["term_category"] == "FULL_TIME"
        assert by_index[2]["term_category"] == "HALF_TIME"
        assert by_index[3]["term_category"] == "HALF_TIME"
        for slot in by_index.values():
            assert slot["status"] == "OPEN" and slot["fill_count"] == 0
