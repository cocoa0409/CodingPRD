"""Cross-cutting corners: the two concurrency tokens and the channel airtime ledger."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import FINANCE_HEADERS, SCHEDULER_HEADERS


def test_the_hold_plan_guard_consumes_one_version_per_accepted_plan(client):
    """Activation already spent the creation version, and a replay spends nothing.

    PRD 2.7: "Replacing a series' hold plan requires `expected_series_version` as a
    non-optional input field, carrying the client's last observed `version` of the
    target `Series`."

    PRD 2.7: "If `expected_series_version` differs from the series' current stored
    `version` — because the series has since been activated, lapsed, re-planned, or had
    hold slots consumed by scheduling — the request is rejected with
    `ERR_STALE_SERIES_VERSION` (HTTP 412), and the client is expected to re-read the
    series and try again."

    PRD 3.2: "The request supplies `expected_series_version` and
    `hold_plan_slots_granted`; on success both `hold_plan_slots_granted` and
    `remaining_hold_slots` are set to the granted figure — a new plan replaces the old
    one outright rather than adding to it — and the series' `version` increments by 1."

    PRD 3.2: "Activation is the `SchedulingCoordinator`'s act and serves both the
    `PROPOSED → ACTIVE` and the `LAPSED → ACTIVE` edges."

    PRD 2.4: "Most resources also carry `updated_at`, refreshed on every mutation, and
    `version`, an integer that starts at 1 on creation and increments by exactly 1 on
    every mutation of that row"

    Design: Corner/cross_cutting_complexity_layers/corner_occ_series_hold_plan_rejects_superseded_version
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    proposed = fx.propose_series(client, producer["id"], title="Riverside Weekly")
    a.assert_common_fields(proposed, expected_version=1)
    assert proposed["status"] == "PROPOSED"
    assert proposed["hold_plan_slots_granted"] == 0
    assert proposed["remaining_hold_slots"] == 0
    creation_version = proposed["version"]

    activated = fx.activate_series(client, proposed["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == creation_version + 1
    activated_version = activated["version"]

    stale = client.replace_hold_plan(
        proposed["id"], f.hold_plan_payload(creation_version, 4), SCHEDULER_HEADERS
    )

    a.error_of(stale, e.ERR_STALE_SERIES_VERSION, 412)
    midway = fx.read_series(client, proposed["id"])
    assert midway["hold_plan_slots_granted"] == 0
    assert midway["remaining_hold_slots"] == 0
    assert midway["version"] == activated_version

    granted = a.data_of(
        client.replace_hold_plan(
            proposed["id"], f.hold_plan_payload(activated_version, 4), SCHEDULER_HEADERS
        )
    )

    assert granted["hold_plan_slots_granted"] == 4
    assert granted["remaining_hold_slots"] == 4
    assert granted["version"] == activated_version + 1
    granted_version = granted["version"]

    replayed = client.replace_hold_plan(
        proposed["id"], f.hold_plan_payload(activated_version, 9), SCHEDULER_HEADERS
    )

    a.error_of(replayed, e.ERR_STALE_SERIES_VERSION, 412)
    after_replay = fx.read_series(client, proposed["id"])
    assert after_replay["hold_plan_slots_granted"] == 4
    assert after_replay["remaining_hold_slots"] == 4
    assert after_replay["version"] == granted_version

    replaced = a.data_of(
        client.replace_hold_plan(
            proposed["id"], f.hold_plan_payload(granted_version, 6), SCHEDULER_HEADERS
        )
    )

    assert replaced["hold_plan_slots_granted"] == 6
    assert replaced["remaining_hold_slots"] == 6
    assert replaced["version"] == granted_version + 1
    assert replaced["status"] == "ACTIVE"


def test_the_funding_guard_answers_with_its_own_code_and_reruns_the_allocation(client):
    """Two restatements, one refusal, and the basis switch re-rates the whole period.

    PRD 2.7: "Restating a funding period's franchise-fee figures requires
    `expected_funding_period_version` as a non-optional input field, carrying the
    client's last observed `version` of the target `FundingPeriod`."

    PRD 2.7: "If `expected_funding_period_version` differs from the period's current
    stored `version`, the request is rejected with `ERR_STALE_FUNDING_PERIOD_VERSION`
    (HTTP 412)."

    PRD 3.8: "A `FinanceOfficer` restates a period by supplying
    `expected_funding_period_version` together with any subset of `basis`,
    `service_period_earned_cents`, `remittance_received_cents` and
    `capital_grant_cents`; whatever is supplied replaces the stored figure and whatever
    is omitted is left alone."

    PRD 3.8: "Both forms raise `revision_round` by 1, re-run the whole allocation under
    the effective basis — which may itself have changed with this request — and
    increment the period's `version` by 1."

    PRD 3.8: "Step one selects the recognised amount: `allocable_base_cents` becomes
    `service_period_earned_cents` when the `basis` is `ACCRUAL`, and
    `remittance_received_cents` when the `basis` is `CASH`."

    PRD 3.8: "the rate is 500 basis points — 5 percent — when `allocable_base_cents` is
    at or above 5000000 cents, and 800 basis points — 8 percent — below that threshold"

    Design: Corner/cross_cutting_complexity_layers/corner_occ_funding_revision_rejects_superseded_version
    """
    period = fx.open_funding_period(
        client,
        fiscal_year=2026,
        quarter=3,
        basis="ACCRUAL",
        gross_franchise_fee_cents=5200000,
        service_period_earned_cents=5000000,
        remittance_received_cents=4800000,
        capital_grant_cents=100000,
    )
    assert period["report_status"] == "DRAFT"
    assert period["revision_round"] == 0
    opening_version = period["version"]

    first = a.data_of(
        client.revise_funding_period(
            period["id"],
            f.revise_funding_payload(opening_version, remittance_received_cents=4900000),
            FINANCE_HEADERS,
        )
    )

    a.assert_cents(first["remittance_received_cents"], 4900000, "remittance_received_cents")
    assert first["basis"] == "ACCRUAL"
    assert first["revision_round"] == 1
    assert first["version"] == opening_version + 1
    a.assert_cents(first["allocable_base_cents"], 5000000, "allocable_base_cents")
    a.assert_cents(first["admin_reserve_cents"], 250000, "admin_reserve_cents")
    a.assert_cents(first["capital_allocation_cents"], 1762500, "capital_allocation_cents")
    a.assert_cents(first["operating_allocation_cents"], 3087500, "operating_allocation_cents")
    a.assert_cents(first["total_program_funds_cents"], 5100000, "total_program_funds_cents")
    first_version = first["version"]

    stale = client.revise_funding_period(
        period["id"], f.revise_funding_payload(opening_version, basis="CASH"), FINANCE_HEADERS
    )

    a.error_of(stale, e.ERR_STALE_FUNDING_PERIOD_VERSION, 412)
    midway = fx.read_funding_period(client, period["id"])
    assert midway["basis"] == "ACCRUAL"
    assert midway["revision_round"] == 1
    assert midway["version"] == first_version
    a.assert_cents(midway["allocable_base_cents"], 5000000, "allocable_base_cents")

    second = a.data_of(
        client.revise_funding_period(
            period["id"], f.revise_funding_payload(first_version, basis="CASH"), FINANCE_HEADERS
        )
    )

    assert second["basis"] == "CASH"
    assert second["revision_round"] == 2
    assert second["version"] == first_version + 1
    assert second["report_status"] == "DRAFT"
    a.assert_cents(second["allocable_base_cents"], 4900000, "allocable_base_cents")
    a.assert_cents(second["admin_reserve_cents"], 392000, "admin_reserve_cents")
    a.assert_cents(second["capital_allocation_cents"], 1677800, "capital_allocation_cents")
    a.assert_cents(second["operating_allocation_cents"], 2930200, "operating_allocation_cents")
    a.assert_cents(second["total_program_funds_cents"], 5000000, "total_program_funds_cents")
    assert (
        second["admin_reserve_cents"]
        + second["capital_allocation_cents"]
        + second["operating_allocation_cents"]
        == second["total_program_funds_cents"]
    )
    a.assert_cents(second["service_period_earned_cents"], 5000000, "service_period_earned_cents")


def test_the_two_airtime_counters_account_for_every_booked_second_once(client):
    """Booking adds, cancelling subtracts only its own share, airing moves the footprint.

    PRD 3.4: "A new channel opens with `scheduled_seconds` at 0, `aired_seconds` at 0
    and `slot_sequence_high` at 0."

    PRD 3.4: "`occupied_seconds` is the program's `runtime_seconds` plus the channel's
    `inter_program_buffer_seconds`, and it is frozen on the slot at creation so that a
    later change to either input cannot retroactively move the schedule. The slot's
    `end_at` is its `start_at` advanced by `occupied_seconds`"

    PRD 3.4: "its `sequence_number` is set to the channel's `slot_sequence_high` plus 1,
    with `slot_sequence_high` advancing to match."

    PRD 3.4: "The channel's `scheduled_seconds` rises by the slot's `occupied_seconds`,
    and the channel's `version` increments by 1."

    PRD 3.4: "The channel's `scheduled_seconds` falls by the slot's `occupied_seconds`
    and the reason is recorded."

    PRD 3.5: "On the channel's airtime ledger, `scheduled_seconds` falls by the slot's
    `occupied_seconds` and `aired_seconds` rises by the same figure, so the two counters
    together always account for every booked second exactly once."

    PRD 2.9: "A channel's `scheduled_seconds` is the sum of `occupied_seconds` over its
    `SCHEDULED` slots and its `aired_seconds` is the same sum over its `AIRED` slots."

    Design: Corner/cross_cutting_complexity_layers/corner_channel_airtime_ledger_reconciles_across_create_cancel_air
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(
        client,
        call_sign="PATV1",
        tier="PUBLIC",
        daily_window_start_minute=1080,
        daily_window_end_minute=1380,
        inter_program_buffer_seconds=120,
    )
    first_program = fx.setup_approved_program(
        client, producer["id"], title="Neighborhood Notes", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    second_program = fx.setup_approved_program(
        client, producer["id"], title="Harbor Nightly Recap", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    a.assert_channel_ledger(channel, 0, 0)
    assert channel["slot_sequence_high"] == 0

    first_slot = fx.book_slot(
        client, channel["id"], first_program["id"], "2026-08-20T18:00:00Z"
    )

    assert first_slot["occupied_seconds"] == 1920
    a.assert_instant_equals(first_slot["end_at"], "2026-08-20T18:32:00Z", "end_at")
    assert first_slot["sequence_number"] == 1
    after_first = fx.read_channel(client, channel["id"])
    a.assert_channel_ledger(after_first, 1920, 0)
    assert after_first["slot_sequence_high"] == 1

    second_slot = fx.book_slot(
        client, channel["id"], second_program["id"], "2026-08-20T19:00:00Z"
    )

    assert second_slot["occupied_seconds"] == 1920
    assert second_slot["sequence_number"] == 2
    after_second = fx.read_channel(client, channel["id"])
    a.assert_channel_ledger(after_second, 3840, 0)
    assert after_second["slot_sequence_high"] == 2

    cancelled = fx.cancel_slot(
        client, second_slot["id"], cancellation_reason="Tape not delivered"
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "Tape not delivered"
    after_cancel = fx.read_channel(client, channel["id"])
    a.assert_channel_ledger(after_cancel, 1920, 0)
    assert after_cancel["slot_sequence_high"] == 2

    fx.set_clock(client, "2026-08-20T18:00:00Z")
    aired = fx.air_slot(client, first_slot["id"], 500)

    assert aired["status"] == "AIRED"
    assert aired["measured_households"] == 500
    after_air = fx.read_channel(client, channel["id"])
    a.assert_channel_ledger(after_air, 0, 1920)
    assert after_air["slot_sequence_high"] == 2
    assert after_air["scheduled_seconds"] + after_air["aired_seconds"] == 1920
