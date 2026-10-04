"""Originator lifecycle, exposure accounting, entry admission gates, and the
exposure-limit OCC rule — PRD §2.5, §2.7, §2.8, §3.2, §3.5.
"""

from test_helpers import (
    ApiErrorId,
    assert_immutable_record_fields,
    assert_originator,
    cancel_entry,
    create_active_participant,
    create_approved_originator,
    create_originator,
    create_originator_payload,
    create_participant,
    create_payment_entry,
    create_payment_entry_payload,
    create_settlement_window,
    create_settlement_window_payload,
    create_transaction_code,
    exposure_limit_payload,
    get_originator,
    make_participant_officer_headers,
    run_settlement,
    set_clock,
    setup_origination_stack,
    transition_originator,
    validate_create_success,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_settlement_window_has_no_version_or_updated_at(api, admin_headers):
    """PRD §2.5: "Three resources are immutable record types and carry only `id`
    and `created_at`: the `SettlementWindow`, the `ReturnRecord`, and the
    `AccountValidation`. On those three, both `updated_at` and `version` are
    absent entirely."

    Design: Corner/entities/settlement_window_has_no_version_or_updated_at
    """
    resp = api.create_settlement_window(
        create_settlement_window_payload(
            window_code="W1",
            cutoff_time_utc="17:00",
            per_entry_limit_cents=100000000,
            odfi_window_cap_cents=2500000000,
        ),
        admin_headers,
    )
    window = validate_create_success(resp)
    assert_immutable_record_fields(window, "SettlementWindow")
    assert window["window_code"] == "W1"


def test_originator_create_defaults_pending_with_zero_exposure(api, admin_headers):
    """PRD §3.2: "The new originator's `participant_id` is set from the acting
    officer's `X-User-ID`, binding the originator to that officer's
    institution, and its lifecycle begins in `PENDING_DUE_DILIGENCE`."
    PRD §3.2: "`committed_exposure_cents` is the sum of `amount_cents` over the
    originator's entries currently in `ORIGINATED` status — money originated
    but not yet settled."

    Design: Corner/entities/originator_create_defaults_pending_with_zero_exposure
    """
    participant = create_participant(
        legal_name="Bank One", participant_type="ODFI", routing_number="111000025"
    )
    originator = create_originator(
        participant, legal_name="Alpha Payroll Corp", risk_tier="STANDARD",
        exposure_limit_cents=1000000000,
    )
    assert_originator(originator)
    assert originator["status"] == "PENDING_DUE_DILIGENCE"
    assert originator["committed_exposure_cents"] == 0
    assert originator["contingent_exposure_cents"] == 0
    assert originator["version"] == 1
    assert originator["participant_id"] == participant["id"]


def test_entry_admission_gated_on_originator_due_diligence_state(api, admin_headers):
    """PRD §3.5: "Second, the originator itself must be `APPROVED`, otherwise
    `ERR_ORIGINATOR_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/entry_admission_gated_on_originator_due_diligence_state
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="ODFI")
    code = create_transaction_code()
    create_settlement_window()
    originator = create_originator(participant, legal_name="Alpha Payroll Corp")
    assert originator["status"] == "PENDING_DUE_DILIGENCE"

    resp = api.create_payment_entry(
        create_payment_entry_payload(originator["id"], code["id"], amount_cents=1000),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORIGINATOR_NOT_APPROVED)

    list_resp = api.list_payment_entries(
        admin_headers, params={"originator_id": originator["id"]}
    )
    entries, meta = validate_paginated(list_resp)
    assert entries == [] and meta["total_count"] == 0


def test_originator_suspend_reinstate_cycle_toggles_admission(api, admin_headers):
    """PRD §3.2: "An approved originator can be placed in `SUSPENDED` and later
    reinstated to `APPROVED`; reinstatement likewise requires the owning
    participant to be `ACTIVE`."
    PRD §3.5: "Second, the originator itself must be `APPROVED`, otherwise
    `ERR_ORIGINATOR_NOT_APPROVED`."

    Design: Difficulty/non_linear_state_machine/originator_suspend_reinstate_cycle_toggles_admission
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    code = stack["transaction_code"]
    originator = stack["originator"]

    entry1 = create_payment_entry(originator, code, amount_cents=1000)
    assert entry1["status"] == "ORIGINATED"

    suspended = transition_originator(originator, "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"

    blocked = api.create_payment_entry(
        create_payment_entry_payload(originator["id"], code["id"], amount_cents=1000),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_ORIGINATOR_NOT_APPROVED)

    reinstated = transition_originator(originator, "APPROVED")
    assert reinstated["status"] == "APPROVED"

    resp = api.create_payment_entry(
        create_payment_entry_payload(originator["id"], code["id"], amount_cents=1000),
        make_participant_officer_headers(participant["id"]),
    )
    entry3 = validate_create_success(resp)
    assert entry3["status"] == "ORIGINATED"


def test_originate_then_cancel_restores_exposure_exactly(api, admin_headers):
    """PRD §3.6: "cancellation is the compensating invariant of origination,
    subtracting the entry's `amount_cents` from both `committed_exposure_cents`
    and `contingent_exposure_cents` and advancing the originator's `version`."
    PRD §3.5: "An admitted entry is born in `ORIGINATED` status; its
    `amount_cents` is added to both the originator's `committed_exposure_cents`
    and `contingent_exposure_cents`, and the originator's `version` increments
    by one."

    Design: Difficulty/compensating_invariant/originate_then_cancel_restores_exposure_exactly
    """
    stack = setup_origination_stack(with_receiver=False)
    code = stack["transaction_code"]
    originator = stack["originator"]

    before = get_originator(originator["id"])
    assert before["committed_exposure_cents"] == 0
    assert before["contingent_exposure_cents"] == 0

    entry = create_payment_entry(originator, code, amount_cents=250000)
    cancelled = cancel_entry(entry)
    assert cancelled["status"] == "CANCELLED"

    after = get_originator(originator["id"])
    assert after["committed_exposure_cents"] == 0
    assert after["contingent_exposure_cents"] == 0


def test_exposure_committed_vs_contingent_admission(api, admin_headers):
    """PRD §3.5: "The originator's `contingent_exposure_cents` is computed
    **before** the candidate entry is added — this pinned evaluation order is
    what resolves the otherwise circular dependency between the exposure figure
    and the entry that would change it — and the entry is admitted only when
    that pre-computed contingent figure plus the candidate's `amount_cents` is
    less than or equal to `exposure_limit_cents`; a total exactly equal to the
    limit is admitted, and anything larger is rejected with
    `ERR_EXPOSURE_LIMIT_EXCEEDED`."
    PRD §3.2: "`contingent_exposure_cents` adds to that committed figure the
    sum of `amount_cents` over entries in `SETTLED` status whose return window
    has not yet expired as of the logical clock"

    Design: Difficulty/dual_variant_calc/exposure_committed_vs_contingent_admission
    """
    stack = setup_origination_stack(
        with_receiver=False,
        originator_overrides={"exposure_limit_cents": 100000000},
    )
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]

    create_payment_entry(originator, code, amount_cents=60000000)
    run_settlement(window["id"], at_iso="2026-09-01T18:00:00Z")

    set_clock("2026-09-02T09:00:00Z")
    create_payment_entry(originator, code, amount_cents=30000000)

    rejected = api.create_payment_entry(
        create_payment_entry_payload(originator["id"], code["id"], amount_cents=20000000),
        make_participant_officer_headers(stack["participant"]["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_EXPOSURE_LIMIT_EXCEEDED)

    fresh = get_originator(originator["id"])
    assert fresh["committed_exposure_cents"] == 30000000
    assert fresh["contingent_exposure_cents"] == 90000000


def test_state_gate_beats_fiscal_gate_on_suspended_originator_over_limit(api, admin_headers):
    """PRD §2.8: "When a request violates several rules at once, the server does
    not choose an error arbitrarily: it reports the error belonging to the
    earliest check in a fixed evaluation order, and later failures never mask
    earlier ones."
    PRD §2.8: "The participant-active, originator-approved, and entry-settled
    gates, in that relative order (`ERR_PARTICIPANT_NOT_ACTIVE`,
    `ERR_ORIGINATOR_NOT_APPROVED`, `ERR_ENTRY_NOT_SETTLED`)."
    PRD §2.8: "Fiscal limits (`ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED`,
    `ERR_WINDOW_CAPACITY_EXCEEDED`, `ERR_EXPOSURE_LIMIT_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_gate_on_suspended_originator_over_limit
    """
    stack = setup_origination_stack(
        with_receiver=False,
        originator_overrides={"exposure_limit_cents": 100000},
    )
    participant = stack["participant"]
    code = stack["transaction_code"]
    originator = transition_originator(stack["originator"], "SUSPENDED")

    resp = api.create_payment_entry(
        create_payment_entry_payload(originator["id"], code["id"], amount_cents=500000),
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORIGINATOR_NOT_APPROVED)


def test_occ_exposure_limit_stale_version_rejected(api, admin_headers):
    """PRD §2.7: "Updating an originator's exposure limit requires a
    non-optional `expected_originator_version` field carrying the client's last
    observed `version` of that `Originator`. If it does not equal the
    originator's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "a successful update increments the originator's `version` by
    one."

    Design: Corner/complexity_layers/occ_exposure_limit_stale_version_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="ODFI")
    originator = create_approved_originator(participant, legal_name="Alpha Payroll Corp")
    observed = get_originator(originator["id"])
    observed_version = observed["version"]

    headers = make_participant_officer_headers(participant["id"])
    first = api.update_exposure_limit(
        originator["id"],
        exposure_limit_payload(5000000, observed_version),
        headers,
    )
    updated = validate_success(first)
    assert updated["exposure_limit_cents"] == 5000000
    assert updated["version"] == observed_version + 1

    replay = api.update_exposure_limit(
        originator["id"],
        exposure_limit_payload(6000000, observed_version),
        headers,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

    after = get_originator(originator["id"])
    assert after["exposure_limit_cents"] == 5000000


def test_originator_create_by_platform_admin_forbidden(api, admin_headers):
    """PRD §2.1: "Access to specific operations is restricted by role per §4; a
    request whose role is not listed for the endpoint it targets is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    PRD §4 lists POST /network/originators under ParticipantOfficer only, so
    the PlatformAdmin credential is not authorized for it.

    Design: Corner/rbac/originator_create_by_platform_admin_forbidden
    """
    create_participant(legal_name="Bank One", participant_type="ODFI", routing_number="111000025")
    resp = api.create_originator(
        create_originator_payload(
            legal_name="Alpha Payroll Corp", risk_tier="STANDARD",
            exposure_limit_cents=1000000000,
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_entry_create_for_foreign_originator_forbidden(api, admin_headers):
    """PRD §2.1: "On those operations, `X-User-ID` must equal the `id` of the
    owning participant — for example the originator's `participant_id`, the
    entry's `originating_participant_id`, or the inquiry case's
    `participant_id` — and a mismatch is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/entry_create_for_foreign_originator_forbidden
    """
    stack = setup_origination_stack()
    code = stack["transaction_code"]
    originator = stack["originator"]
    foreign = stack["receiver"]

    resp = api.create_payment_entry(
        create_payment_entry_payload(originator["id"], code["id"], amount_cents=1000),
        make_participant_officer_headers(foreign["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_reads_observe_writes_immediately(api, auditor_headers):
    """PRD §3.5: "An admitted entry is born in `ORIGINATED` status"
    PRD §3.5: "when `same_day` is false the server assigns the window itself."
    PRD §3.5: "the server assigns the entry to the earliest-cutoff window,
    ranking all settlement windows by `cutoff_time_utc` ascending and breaking
    ties by the window's `created_at` ascending."

    Design: Corner/consistency_model/reads_observe_writes_immediately
    """
    stack = setup_origination_stack(with_receiver=False)
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]

    entry = create_payment_entry(originator, code, amount_cents=3000)
    read_back = validate_success(api.get_payment_entry(entry["id"], auditor_headers))
    assert read_back["status"] == "ORIGINATED"
    assert read_back["settlement_window_id"] == window["id"]
    assert read_back.get("entry_fee_cents") is None
