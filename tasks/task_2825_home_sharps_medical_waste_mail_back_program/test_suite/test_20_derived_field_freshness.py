"""Derived-field freshness in the home-sharps mail-back program.

Every write in this API publishes its own computed fields in its own response and
leaves the denormalised counters on the aggregates it touched already correct for
the very next read — there is no refresh step and no second call to make. These
tests probe that from both directions: a kit issuance, which books money, and the
compensating void, which unwinds it.

Every test builds its own state from an empty database through the program's own
endpoints, and pins the logical clock so that every derived date is reproducible.
"""

from test_helpers import (
    assert_kit,
    assert_ledger_entry,
    assert_ledger_sequence,
    assert_program_balances,
    assert_total_count,
    kit_issuance_payload,
    kit_void_payload,
    read_enrollment,
    read_ledger_entries,
    read_program,
    setup_active_enrollment,
    validate_success,
)

CLOCK_AT_CREATION = "2026-08-01T00:00:00Z"

PATIENT_OVERRIDES = {
    "full_name": "Dana Reyes",
    "therapy_type": "INSULIN_PEN_NEEDLES",
    "weekly_sharps_count": 20,
    "contact_email": "dana@example.com",
}
ENROLLMENT_OVERRIDES = {"cadence_days": 30, "kits_authorized": 3}
PROGRAM_OVERRIDES = {
    "program_code": "NW-2026",
    "funding_ceiling_cents": 500000,
    "per_kit_allowance_cents": 5000,
}
STATE_RULE_OVERRIDES = {"household_sharps_classification": "HOUSEHOLD_EXEMPT"}


def _dana_with_nothing_issued(api):
    """Dana on an ACTIVE enrollment against a 500000-cent program, with three
    kits authorized and none issued yet."""
    return setup_active_enrollment(
        api,
        clock=CLOCK_AT_CREATION,
        state_rule_overrides=STATE_RULE_OVERRIDES,
        program_overrides=PROGRAM_OVERRIDES,
        patient_overrides=PATIENT_OVERRIDES,
        enrollment_overrides=ENROLLMENT_OVERRIDES,
    )


def _issue(api, ctx, headers):
    """Issue Dana's first kit, returning the enrollment version the request
    echoed alongside the issuance response body."""
    version_before = read_enrollment(api, ctx["enrollment"]["id"])["version"]
    kit = validate_success(
        api.issue_kit(
            ctx["enrollment"]["id"], kit_issuance_payload(version_before), headers
        ),
        201,
    )
    return version_before, kit


def test_01_the_issuance_response_already_carries_every_field_it_computed(
    api, program_admin_headers
):
    """The request body names only the version echo, yet the response that comes
    straight back already publishes the sizing, the price and the deadline.

    PRD 4: "Endpoints that mint a new resource return HTTP 201 with the created resource in `data`; endpoints that modify an existing resource return HTTP 200 with the updated resource in `data`, as do all read endpoints."
    PRD 3.4: "*Second*, the new kit is minted in status `ISSUED` with `enrollment_id` pointing at its enrollment, `required_units`, `container_size`, `capacity_units` and `volume_liters` from the sizing rule above, `provisional_cost_cents` from the costing rule above, `issued_at` set to the current logical-clock instant, `fill_units` at 0, `sealed_gross_weight_grams` null, `acknowledged_at` null, `void_reason` null, `auto_ship_run_id` null for an operator-driven issuance, and `supersedes_kit_id` set to the id of the kit that was just superseded — or null when there was none."
    PRD 3.4: "Its `seal_deadline_date` is the UTC calendar date of `issued_at` advanced by the enrollment's `cadence_days` plus a 14-day grace period; a kit still unsealed after that date is a late kit for audit purposes."
    Design: Corner/consistency_model/every_derived_field_is_current_in_the_very_next_read_with_no_lag
    """
    ctx = _dana_with_nothing_issued(api)

    _version_before, kit = _issue(api, ctx, program_admin_headers)

    assert_kit(
        kit,
        status="ISSUED",
        required_units=99,
        container_size="ONE_QUART",
        capacity_units=100,
        volume_liters=0.9,
        provisional_cost_cents=1465,
        seal_deadline_date="2026-09-14",
    )


def test_02_the_program_and_the_ledger_are_already_correct_on_the_next_read(
    api, program_admin_headers
):
    """With no intervening call of any kind, the program's balance triple and the
    ledger's own snapshot of it already agree with the kit that was just issued.

    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 3.4: "*Fourth*, the program's `available_cents`, `kits_issued_count` and `status` are recomputed, the program moving `ACTIVE → EXHAUSTED` if and only if `available_cents` lands on exactly 0."
    PRD 2.9: "Finally, each entry snapshots the three program balances as they stood immediately after the append, in `reserved_after_cents`, `committed_after_cents` and `available_after_cents`, and records a human-readable origin in `memo` — "kit issuance", "kit void", "certificate settlement" and the like."
    Design: Corner/consistency_model/every_derived_field_is_current_in_the_very_next_read_with_no_lag
    """
    ctx = _dana_with_nothing_issued(api)
    _version_before, kit = _issue(api, ctx, program_admin_headers)

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        status="ACTIVE",
    )
    assert program["kits_issued_count"] == 1

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert len(entries) == 1, f"expected exactly 1 ledger entry, got {len(entries)}"
    assert_ledger_entry(
        entries[0],
        entry_type="RESERVATION",
        amount_cents=1465,
        sequence_no=1,
        kit_id=kit["id"],
        reserved_after_cents=1465,
        committed_after_cents=0,
        available_after_cents=498535,
    )


def test_03_the_enrollment_read_already_reflects_the_issuance(
    api, program_admin_headers
):
    """The enrollment's own counters move inside the issuance request, so the
    immediately following read shows the bumped version and the new due date.

    PRD 3.4: "*Fifth*, the enrollment's `next_autoship_due_date` is set to the UTC calendar date of `issued_at` advanced by `cadence_days`, its `kits_issued` is recomputed, and its `version` is incremented by 1."
    Design: Corner/consistency_model/every_derived_field_is_current_in_the_very_next_read_with_no_lag
    """
    ctx = _dana_with_nothing_issued(api)
    version_before, _kit = _issue(api, ctx, program_admin_headers)

    enrollment = read_enrollment(api, ctx["enrollment"]["id"])
    assert enrollment["version"] == version_before + 1
    assert enrollment["kits_issued"] == 1
    assert enrollment["next_autoship_due_date"] == "2026-08-31"


def test_04_the_void_unwinds_the_accounting_inside_its_own_request(
    api, logistics_coordinator_headers, program_admin_headers
):
    """The void response already reads `VOIDED`, and the very next program and
    ledger reads already show the reservation released.

    PRD 3.5: "The kit moves to `VOIDED`, which is terminal, with the supplied reason stored in `void_reason`."
    PRD 3.5: "Accounting unwinds in the same request: a `RESERVATION_RELEASE` ledger entry for the negation of the kit's `provisional_cost_cents` is appended at the next `sequence_no`, the program's `reserved_cents` falls by that amount, and the program's `available_cents`, `kits_issued_count` and `status` are recomputed — the program moving `EXHAUSTED → ACTIVE` if the recomputed `available_cents` is above 0."
    Design: Corner/consistency_model/every_derived_field_is_current_in_the_very_next_read_with_no_lag
    """
    ctx = _dana_with_nothing_issued(api)
    _version_before, kit = _issue(api, ctx, program_admin_headers)

    voided = validate_success(
        api.void_kit(
            kit["id"],
            kit_void_payload("address correction"),
            logistics_coordinator_headers,
        ),
        200,
    )
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "address correction"

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program, reserved_cents=0, committed_cents=0, available_cents=500000
    )
    assert program["kits_issued_count"] == 0

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_sequence(
        entries, [(1, "RESERVATION", 1465), (2, "RESERVATION_RELEASE", -1465)]
    )
    assert_ledger_entry(
        entries[1],
        reserved_after_cents=0,
        available_after_cents=500000,
    )


def test_05_the_voided_kit_is_still_listed_under_its_enrollment(
    api, logistics_coordinator_headers, program_admin_headers
):
    """Voiding is an accounting unwind, not a deletion: the row remains readable
    under its enrollment even though it no longer counts toward the program.

    PRD 3.4: "Kits are readable individually and as a list, filterable by `enrollment_id`, by `supersedes_kit_id` to walk the replacement chain, by `auto_ship_run_id` to see what a checkpoint produced, or by `status`."
    PRD 3.2: "The new program starts with `reserved_cents` at 0, `committed_cents` at 0, `available_cents` equal to `funding_ceiling_cents`, and `status` `ACTIVE` — or `EXHAUSTED` in the degenerate case where the ceiling is zero, since the status is a pure function of `available_cents`."
    Design: Corner/consistency_model/every_derived_field_is_current_in_the_very_next_read_with_no_lag
    """
    ctx = _dana_with_nothing_issued(api)
    _version_before, kit = _issue(api, ctx, program_admin_headers)
    validate_success(
        api.void_kit(
            kit["id"],
            kit_void_payload("address correction"),
            logistics_coordinator_headers,
        ),
        200,
    )

    rows, _meta = assert_total_count(
        api.list_kits(
            program_admin_headers, {"enrollment_id": ctx["enrollment"]["id"]}
        ),
        1,
    )
    assert rows[0]["id"] == kit["id"]
    assert rows[0]["status"] == "VOIDED"
