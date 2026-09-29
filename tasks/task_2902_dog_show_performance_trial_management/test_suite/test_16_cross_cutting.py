"""Cross-cutting layers: version pinning, rate thresholds and the venue flag that
arms the whole heat regime."""

from test_helpers import api_client, validate_error, validate_paginated, validate_success
from test_helpers.assertions import (
    assert_instant_equals,
    assert_one_decimal_place,
    assert_panel_slot,
    assert_ring_block,
)
from test_helpers.constants import MAX_DOGS_PER_JUDGE_PER_DAY, SETUP_CLOCK_INSTANT
from test_helpers.factories import (
    create_panel_slot_payload,
    create_ring_block_payload,
    temperature_reading_payload,
)
from test_helpers.fixtures import (
    apply_for_show,
    approve_show,
    publish_ring_block,
    read_class,
    read_entry,
    read_judge,
    read_ring_block,
    read_show,
    read_show_version,
    record_reading,
    register_club,
    register_judge,
    set_clock,
    setup_multi_dog_household,
    setup_show_with_class,
    submit_show,
)
from test_helpers.test_users import make_show_secretary_headers


def test_ring_block_create_rejects_the_show_version_a_temperature_reading_invalidated():
    """A reading on a wholly unrelated surface moves the counter the plan pins.

    PRD 3.7: "A reading may be taken while the show is `APPROVED` or while it is
    `IN_PROGRESS`; in both cases it increases the show's `temperature_reading_count`
    by one, rewrites `current_heat_index_c` and `current_advisory_level`, and
    increases the show's `version` by one."

    PRD 2.5: "If `expected_show_version` does not equal the show's stored
    `version`, the request is rejected with `ERR_STALE_SHOW_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/ring_block_create_rejects_the_show_version_a_temperature_reading_invalidated
    """
    context = setup_show_with_class(num_dogs=1, num_entries=1, confirm_entries=True)
    show, klass, slot = context["show"], context["klass"], context["slot"]
    headers = make_show_secretary_headers()

    # The setup already bumped the show's version several times: create, submit,
    # approve, and the confirmation whose money cascade rewrote the show ledger
    # (PRD 2.4 bumps a resource's version for a downstream consequence too).
    show_v0 = read_show_version(show)

    read = validate_success(
        api_client.record_temperature_reading(
            show["id"], temperature_reading_payload(22.0, 40), headers
        ),
        200,
    )
    assert read["current_advisory_level"] == "GREEN"
    assert_one_decimal_place(read["current_heat_index_c"], "current_heat_index_c")
    assert read["current_heat_index_c"] == 22.0, "40 percent humidity adds nothing"
    assert read["temperature_reading_count"] == 1
    assert read["version"] == show_v0 + 1, "the reading bumped the version the plan pins"

    stale = validate_error(
        api_client.create_ring_block(
            create_ring_block_payload(
                show["id"], klass["id"], slot["id"], show_v0,
                ring_number=1, block_start_at="2026-09-12T09:00:00Z",
            ),
            headers,
        ),
        "ERR_STALE_SHOW_VERSION",
        412,
    )
    assert stale["error_id"] == "ERR_STALE_SHOW_VERSION", (
        "a stale pin is neither ERR_INVALID_REQUEST, ERR_RING_BLOCK_OVERLAP "
        "nor ERR_INVALID_STATE"
    )
    rows, meta = validate_paginated(
        api_client.list_ring_blocks(headers, {"show_id": show["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], "the refused create wrote nothing"
    assert read_show_version(show) == show_v0 + 1, (
        "the refused create bumped nothing either"
    )

    show_v1 = read_show_version(show)
    assert show_v1 == show_v0 + 1

    block = validate_success(
        api_client.create_ring_block(
            create_ring_block_payload(
                show["id"], klass["id"], slot["id"], show_v1,
                ring_number=1, block_start_at="2026-09-12T09:00:00Z",
            ),
            headers,
        ),
        201,
    )
    assert_ring_block(block)
    assert block["block_status"] == "PLANNED"
    assert block["scheduled_dog_count"] == 1
    assert block["conflict_free_minutes"] == 3, "ceil(1 * 60 / 25) with no overhead"
    assert block["judging_minutes_estimate"] == 3
    assert block["deferred_dog_count"] == 0
    assert_instant_equals(
        block["block_end_at"], "2026-09-12T09:03:00Z", "block_end_at"
    )
    assert block["superseded_block_id"] is None
    assert read_show_version(show) == show_v1 + 1, (
        "the accepted create bumps the same counter the OCC check reads"
    )


def test_second_panel_proposal_rejects_the_judge_version_the_first_proposal_consumed():
    """Three slots are allowed, so only the version can refuse the second one.

    PRD 2.5: "A judge may legitimately hold up to three concurrent slots at one
    show, so a second proposal against the same judge is a valid operation rather
    than a state violation — but every proposal and every response changes that
    judge's confirmed-slot count and daily-load headroom."

    PRD 2.5: "If `expected_judge_version` does not equal the judge's stored
    `version`, the proposal is rejected with `ERR_STALE_JUDGE_VERSION` (HTTP 412),
    because the load picture the secretary chose the judge from is stale."

    Design: Corner/cross_cutting_complexity_layers/second_panel_proposal_rejects_the_judge_version_the_first_proposal_consumed
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    judge = register_judge()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)
    headers = make_show_secretary_headers()

    judge_v0 = judge["version"]
    assert judge_v0 == 1, "a freshly registered judge sits at version 1"

    first = validate_success(
        api_client.create_panel_slot(
            create_panel_slot_payload(
                show["id"], judge["id"], judge_v0, panel_role="BREED_JUDGE"
            ),
            headers,
        ),
        201,
    )
    assert_panel_slot(first)
    assert first["slot_status"] == "PROPOSED"
    assert first["assigned_class_count"] == 0

    stale = validate_error(
        api_client.create_panel_slot(
            create_panel_slot_payload(
                show["id"], judge["id"], judge_v0, panel_role="GROUP_JUDGE"
            ),
            headers,
        ),
        "ERR_STALE_JUDGE_VERSION",
        412,
    )
    assert stale["error_id"] == "ERR_STALE_JUDGE_VERSION", (
        "one slot against a limit of three is not ERR_JUDGE_ASSIGNMENT_LIMIT"
    )

    judge_row = read_judge(judge)
    assert judge_row["version"] == 2, "the first proposal consumed the judge version"
    assert judge_row["confirmed_slot_count"] == 0, (
        "the surviving slot is still PROPOSED, so the count never moved"
    )

    second = validate_success(
        api_client.create_panel_slot(
            create_panel_slot_payload(
                show["id"], judge["id"], judge_row["version"], panel_role="GROUP_JUDGE"
            ),
            headers,
        ),
        201,
    )
    assert second["panel_role"] == "GROUP_JUDGE"
    assert second["assigned_dog_capacity"] == MAX_DOGS_PER_JUDGE_PER_DAY
    assert read_judge(judge)["version"] == 3

    rows, meta = validate_paginated(
        api_client.list_panel_slots(headers, {"judge_id": judge["id"]})
    )
    assert meta["total_count"] == 2, "the refused proposal left no slot behind"
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_household_discount_appears_at_exactly_the_third_confirmation():
    """The ten percent band opens on the confirmation that makes the set three.

    PRD 3.5: "**Step six** builds a single discount percentage additively from two
    independent conditions: fifteen percent when the same-dog rank is 2 or higher,
    meaning this is not the dog's first counted entry at the show, plus ten percent
    when the handler-counted set holds at least three entries."

    PRD 3.5: "Entries still sitting in `RECEIVED` are invisible, so the household
    discount can only appear from a handler's third confirmation onward, and each
    earlier entry keeps the fee it was assessed at its own confirmation instant."

    Design: Corner/cross_cutting_complexity_layers/household_discount_appears_at_exactly_the_third_confirmation
    """
    context = setup_multi_dog_household(
        num_dogs=3,
        entry_clocks=[
            "2026-08-10T09:00:00Z",
            "2026-08-10T09:05:00Z",
            "2026-08-10T09:10:00Z",
        ],
        confirm=False,
    )
    entries = context["entries"]
    headers = make_show_secretary_headers()

    first = validate_success(api_client.confirm_entry(entries[0]["id"], headers), 200)
    assert first["entry_fee_cents"] == 4663, "3500 base + 900 surcharge + 263 levy"
    assert first["armband_number"] == 1

    second = validate_success(api_client.confirm_entry(entries[1]["id"], headers), 200)
    assert second["entry_fee_cents"] == 3763, (
        "handler rank 2 drops the surcharge; two counted entries is still under three"
    )
    assert second["armband_number"] == 2

    third = validate_success(api_client.confirm_entry(entries[2]["id"], headers), 200)
    assert third["entry_fee_cents"] == 3387, (
        "the third confirmation makes the counted set three, so 3763 * 0.90 rounds "
        "half-up to 3387"
    )
    assert third["armband_number"] == 3
    assert third["levy_cents"] == 263
    assert third["fee_basis"] == "PROVISIONAL"

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 11813, "4663 + 3763 + 3387"
    assert show["levy_total_cents"] == 789
    assert show["confirmed_entry_count"] == 3
    assert show["fee_collected_cents"] == 11813

    assert read_entry(entries[0])["entry_fee_cents"] == 4663, (
        "the provisional occasion never rewrites an already-assessed row"
    )


def test_red_advisory_on_an_indoor_show_holds_no_entry_and_blocks_no_publication():
    """The level alone is not the restriction: `outdoor_venue` arms it.

    PRD 3.7: "Conformation entries are never placed on a heat hold, and an indoor
    show never places any entry on one."

    PRD 3.7: "While the level stands at `RED` on an outdoor show, four operations
    are blocked with `ERR_HEAT_RESTRICTION_ACTIVE` — publishing a performance
    block, rescheduling a performance block, completing a performance class and
    recording a performance run — while conformation work continues untouched."

    Design: Corner/cross_cutting_complexity_layers/red_advisory_on_an_indoor_show_holds_no_entry_and_blocks_no_publication
    """
    context = setup_show_with_class(
        num_dogs=1,
        num_entries=1,
        confirm_entries=True,
        show_overrides={"show_type": "PERFORMANCE", "outdoor_venue": False},
        class_level="PERFORMANCE",
        discipline="OBEDIENCE",
        close_class=True,
        open_show=True,
        check_in_attendance="PRESENT",
    )
    show, klass, slot = context["show"], context["klass"], context["slot"]
    entry = context["entries"][0]
    headers = make_show_secretary_headers()

    read = record_reading(show, 29.0, 65)
    assert read["current_heat_index_c"] == 32.0, "29.0 plus 3.0 for 65 percent humidity"
    assert read["current_advisory_level"] == "RED", "32.0 is inclusive at the RED band"
    assert read["temperature_reading_count"] == 1

    held = read_entry(entry)
    assert held["welfare_status"] == "CLEAR", (
        "the heat-hold cascade is conditioned on outdoor_venue, false here"
    )
    assert held["entry_status"] == "CHECKED_IN", "the welfare axis moved no competition axis"

    block = validate_success(
        api_client.create_ring_block(
            create_ring_block_payload(
                show["id"], klass["id"], slot["id"], read_show_version(show),
                ring_number=1, block_start_at="2026-09-12T09:00:00Z",
            ),
            headers,
        ),
        201,
    )
    assert block["block_status"] == "PLANNED"
    assert block["judging_minutes_estimate"] == 4, (
        "ceil(1 * 60 / 15) for a PERFORMANCE class"
    )
    assert_instant_equals(
        block["block_end_at"], "2026-09-12T09:04:00Z", "block_end_at"
    )

    published = publish_ring_block(block)
    assert published["block_status"] == "PUBLISHED", (
        "priority 10 requires outdoor_venue true as well as a RED advisory"
    )
    assert read_ring_block(block)["block_status"] == "PUBLISHED"
    assert read_class(klass)["status"] == "SCHEDULED"
