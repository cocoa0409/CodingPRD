"""Operations whose admissibility is decided by a *different* row's state.

A pick reads the owning section's renovation posture, and publishing an
event's slots reads the parent recalculation's certification status.  In both
cases the operand itself is perfectly well formed.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_RECALCULATION_NOT_CERTIFIED,
    ERR_SECTION_UNDER_RENOVATION,
)
from test_helpers.assertions import (
    assert_donor_points,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    ACTION_ABANDON,
    EVENT_DRAFT,
    EVENT_SLOTS_PUBLISHED,
    NON_ALUMNUS,
    OCCUPANCY_HELD,
    RENOVATION_ABANDONED,
    RENOVATION_SURVEYED,
    SEAT_AVAILABLE,
    SEAT_HELD,
    SECTION_OPEN,
    SECTION_UNDER_RENOVATION,
    SLOT_CONSUMED,
    SLOT_SCHEDULED,
)
from test_helpers.fixtures import (
    add_received_gift,
    certified_cycle,
    certify_cycle,
    communicated_cycle,
    create_event,
    create_section_with_seats,
    list_event_slots,
    publish_and_open,
    publish_slots,
    read_donor,
    read_event,
    read_seat,
    read_section,
    read_slot,
    register_donor,
    renovation_action,
    set_clock,
    slot_for_donor,
    survey_section,
)
from test_helpers.test_users import ADMIN, OFFICER, make_donor_headers


def _open_slot_over_a_surveyed_section(client):
    """A pickable slot on a one-seat section whose renovation has begun.

    Returns the section, its single seat, the donor's slot and the seat's
    ``version`` captured *before* the survey ran, so the same pick body can be
    replayed after the renovation is abandoned.
    """
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    cycle = certified_cycle(client, 2026)

    section, seats = create_section_with_seats(
        client, [("K", 1)], seat_capacity=1, per_seat_requirement_cents=100000
    )
    event = publish_and_open(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    slot = slot_for_donor(client, event["id"], donor["id"])
    set_clock(client, f.instant(2026, 9, 1, 12))

    seat_version = read_seat(client, seats[0]["id"])["version"]
    surveyed = survey_section(client, section["id"])
    assert surveyed["renovation_status"] == RENOVATION_SURVEYED
    assert surveyed["status"] == SECTION_UNDER_RENOVATION

    return donor, section, seats[0], slot, seat_version


def _replay_pick(client, slot, seat, donor, seat_version):
    """The identical pick body, with the pre-survey seat version stamp."""
    return client.pick_seat(
        slot["id"],
        f.pick_payload(seat["id"], seat_version),
        headers=make_donor_headers(donor["id"]),
    )


class TestPickBlockedBySectionRenovation:
    """The seat is free and the slot is live; only the section objects."""

    def test_a_pick_into_a_surveyed_section_is_refused(self, client):
        """Surveying blocks picks even though the seat itself is AVAILABLE.

        PRD 3.6: "Its side effect is to set `status` to `UNDER_RENOVATION`,
        which blocks every pick into this section for the duration."

        Design: Difficulty/cross_entity_state_dependency/pick_blocked_when_section_under_renovation
        """
        donor, _section, seat, slot, seat_version = _open_slot_over_a_surveyed_section(
            client
        )

        refused = _replay_pick(client, slot, seat, donor, seat_version)
        validate_error(refused, ERR_SECTION_UNDER_RENOVATION, 409)

    def test_the_refusal_consumes_neither_the_slot_nor_the_seat(self, client):
        """A blocked pick is inert on both rows it would otherwise move.

        PRD 2.9: "The section holding the target seat is `OPEN` rather than
        `UNDER_RENOVATION` or `CLOSED`. This applies to a seat pick, a
        relocation decision, and adding a seat to a section. Violation:
        `ERR_SECTION_UNDER_RENOVATION` (409)."

        Design: Difficulty/cross_entity_state_dependency/pick_blocked_when_section_under_renovation
        """
        donor, _section, seat, slot, seat_version = _open_slot_over_a_surveyed_section(
            client
        )

        _replay_pick(client, slot, seat, donor, seat_version)

        assert read_slot(client, slot["id"])["slot_status"] == SLOT_SCHEDULED
        assert read_seat(client, seat["id"])["seat_status"] == SEAT_AVAILABLE

    def test_abandoning_the_renovation_admits_the_identical_pick(self, client):
        """Only the neighbouring row changed, so the same body now succeeds.

        PRD 3.6: "Both paths set `status` back to `OPEN` and clear
        `post_renovation_capacity` and `post_renovation_requirement_cents` back
        to null."

        Design: Difficulty/cross_entity_state_dependency/pick_blocked_when_section_under_renovation
        """
        donor, section, seat, slot, seat_version = _open_slot_over_a_surveyed_section(
            client
        )
        _replay_pick(client, slot, seat, donor, seat_version)

        renovation_action(client, section["id"], ACTION_ABANDON, headers=ADMIN)

        accepted = _replay_pick(client, slot, seat, donor, seat_version)
        assignment = validate_success(accepted, 201)
        assert assignment["occupancy_status"] == OCCUPANCY_HELD
        assert assignment["requirement_cents"] == 100000

    def test_the_pick_leaves_the_renovation_dimension_terminal(self, client):
        """The two section axes are independent: ABANDONED alongside OPEN.

        PRD 3.6: "The two axes really are independent: the renovation dimension
        rests in the terminal `ABANDONED` while the section's own `status` is a
        perfectly ordinary `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/pick_blocked_when_section_under_renovation
        """
        donor, section, seat, slot, seat_version = _open_slot_over_a_surveyed_section(
            client
        )
        renovation_action(client, section["id"], ACTION_ABANDON, headers=ADMIN)
        validate_success(_replay_pick(client, slot, seat, donor, seat_version), 201)

        after = read_section(client, section["id"])
        assert after["renovation_status"] == RENOVATION_ABANDONED
        assert after["status"] == SECTION_OPEN
        assert after["post_renovation_capacity"] is None
        assert after["post_renovation_requirement_cents"] is None

        assert read_seat(client, seat["id"])["seat_status"] == SEAT_HELD
        assert read_slot(client, slot["id"])["slot_status"] == SLOT_CONSUMED


def _draft_event_over_an_uncertified_cycle(client):
    """A DRAFT event hanging off a cycle that has only reached COMMUNICATED."""
    set_clock(client, f.instant(2026, 4, 1))
    donor = register_donor(client, alumni_status=NON_ALUMNUS)
    add_received_gift(client, donor["id"], 5000000, f.instant(2026, 3, 1))

    cycle = communicated_cycle(client, 2026)
    event = create_event(
        client, cycle["id"], f.instant(2026, 9, 1), f.instant(2026, 9, 5), 2880
    )
    assert event["status"] == EVENT_DRAFT
    return donor, cycle, event


class TestPublishBlockedByUncertifiedRecalculation:
    """Slots may only be published off a cycle that has been certified."""

    def test_publishing_before_certification_is_refused(self, client):
        """A COMMUNICATED cycle is not yet a publishable ranking.

        PRD 2.9: "The recalculation the operation depends on is in `CERTIFIED`.
        This applies to publishing slots for a selection event, starting a
        section's reseating, and reading a recalculation's retention analysis.
        Violation: `ERR_RECALCULATION_NOT_CERTIFIED` (409)."

        Design: Difficulty/cross_entity_state_dependency/publish_slots_blocked_when_recalculation_not_certified
        """
        _donor, _cycle, event = _draft_event_over_an_uncertified_cycle(client)

        refused = client.publish_slots(event["id"], headers=OFFICER)
        validate_error(refused, ERR_RECALCULATION_NOT_CERTIFIED, 409)

    def test_the_refusal_leaves_the_event_in_draft_with_no_slots(self, client):
        """The event's own counters are untouched by the blocked publication.

        PRD 3.6: "It starts in `DRAFT` with `published_slot_count` and
        `scheduled_slot_count` both zero."

        Design: Difficulty/cross_entity_state_dependency/publish_slots_blocked_when_recalculation_not_certified
        """
        _donor, _cycle, event = _draft_event_over_an_uncertified_cycle(client)

        client.publish_slots(event["id"], headers=OFFICER)

        after = read_event(client, event["id"])
        assert after["status"] == EVENT_DRAFT
        assert after["published_slot_count"] == 0
        assert list_event_slots(client, event["id"]) == []

    def test_certifying_the_parent_admits_the_identical_publication(self, client):
        """Only the parent row moved, and the same call now ranks the donor.

        PRD 3.6: "A selection event hangs off a certified cycle and runs one
        allocation."

        Design: Difficulty/cross_entity_state_dependency/publish_slots_blocked_when_recalculation_not_certified
        """
        donor, cycle, event = _draft_event_over_an_uncertified_cycle(client)
        client.publish_slots(event["id"], headers=OFFICER)

        certify_cycle(client, cycle["id"])

        published = publish_slots(client, event["id"])
        assert published["status"] == EVENT_SLOTS_PUBLISHED
        assert published["published_slot_count"] == 1

        scored = read_donor(client, donor["id"])
        assert_donor_points(scored, certified_points="67.50")
        assert scored["rank_position"] == 1

        slots = list_event_slots(client, event["id"])
        assert len(slots) == 1
        assert slots[0]["rank_at_publish"] == 1
        assert slots[0]["slot_status"] == SLOT_SCHEDULED
