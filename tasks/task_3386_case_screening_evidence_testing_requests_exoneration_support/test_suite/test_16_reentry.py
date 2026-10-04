"""Reentry referrals: the clock-gated activation, aggregate overlapping-window
capacity (not strict pairwise exclusion), and slot-pool conservation across
create / activate / complete / cancel."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_reentry_referral,
    assert_slots_in_use_consistent,
    create_reentry_provider,
    create_reentry_referral,
    create_reentry_referral_payload,
    get_reentry_provider,
    list_rows,
    referral_advance_payload,
    set_clock,
    setup_exonerated_case,
    setup_reentry_referral_pending,
    validate_created,
    validate_error,
    validate_ok,
)

ADVOCATE = TEST_USERS["client_services_advocate_headers"]


def test_referral_activate_before_window_start_rejected(api):
    """PRD section 3.9: "Activation moves a `PENDING` referral to `ACTIVE`
    once the logical clock has reached `service_start` — earlier activation is
    `ERR_SERVICE_WINDOW_NOT_STARTED` (HTTP 409) — and changes no slot
    accounting, since a pending referral already occupies a slot."

    Design: Corner/validations/referral_activate_before_window_start_rejected
    """
    ctx = setup_reentry_referral_pending(
        jurisdiction_overrides={"state_code": "NH", "name": "New Hampshire"},
        provider_overrides={
            "name": "Beacon Counseling", "service_type": "COUNSELING",
            "total_capacity": 3,
        },
        referral_overrides={
            "service_start": "2027-03-01T00:00:00Z",
            "service_end": "2027-03-10T00:00:00Z",
        },
    )
    referral_id = ctx["referral"]["id"]
    assert ctx["referral"]["status"] == "PENDING"

    set_clock("2027-02-28T12:00:00Z")
    resp = api.advance_reentry_referral(
        referral_id, referral_advance_payload("ACTIVATE"), ADVOCATE
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_WINDOW_NOT_STARTED)

    # At exactly service_start the activation succeeds.
    set_clock("2027-03-01T00:00:00Z")
    data = validate_ok(
        api.advance_reentry_referral(referral_id, referral_advance_payload("ACTIVATE"), ADVOCATE)
    )
    assert data["status"] == "ACTIVE"


def _exonerated_case_with_provider(state_code, name, capacity):
    ctx = setup_exonerated_case(
        jurisdiction_overrides={"state_code": state_code, "name": name}
    )
    provider = create_reentry_provider(
        name="FreshStart Housing", service_type="HOUSING", total_capacity=capacity
    )
    ctx["provider"] = provider
    return ctx


def test_provider_overlapping_windows_allowed_up_to_capacity(api):
    """PRD section 3.9: "Capacity is enforced as an overlapping-window
    aggregate: counting the provider's live referrals — those in `PENDING` or
    `ACTIVE` — whose windows strictly overlap the new one (the existing window
    starts before the new window ends and ends after the new window starts; a
    window that merely touches the new one at an endpoint does not overlap),
    the create is allowed only when that count is below `total_capacity`; a
    count already equal to capacity means the provider is full for that window
    and the create is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/provider_windows_aggregate_capacity_not_strict_overlap
    """
    ctx = _exonerated_case_with_provider("MD", "Maryland", 2)
    case_id, provider_id = ctx["case"]["id"], ctx["provider"]["id"]

    # R1 and R2 overlap and BOTH succeed: the aggregate rule allows overlap
    # up to total_capacity, unlike the strict lab-window rule.
    r1 = validate_created(api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-01T00:00:00Z", service_end="2027-03-10T00:00:00Z",
        ), ADVOCATE))
    r2 = validate_created(api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-05T00:00:00Z", service_end="2027-03-15T00:00:00Z",
        ), ADVOCATE))
    assert r1["status"] == "PENDING"
    assert r2["status"] == "PENDING"

    # R3 would be the third concurrent referral: capacity 2 already reached.
    resp = api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-06T00:00:00Z", service_end="2027-03-08T00:00:00Z",
        ), ADVOCATE)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED)


def test_provider_window_adjacency_and_slot_count(api):
    """PRD section 3.9: "a window that merely touches the new one at an
    endpoint does not overlap".
    PRD section 3.9: "The provider's `slots_in_use` is a computed count of its
    referrals in `PENDING` or `ACTIVE` status, written on referral creation,
    completion, and cancellation; it starts at 0."

    Design: Difficulty/resource_temporal_overlap/provider_windows_aggregate_capacity_not_strict_overlap
    """
    ctx = _exonerated_case_with_provider("MD", "Maryland", 2)
    case_id, provider_id = ctx["case"]["id"], ctx["provider"]["id"]

    validate_created(api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-01T00:00:00Z", service_end="2027-03-10T00:00:00Z",
        ), ADVOCATE))
    validate_created(api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-05T00:00:00Z", service_end="2027-03-15T00:00:00Z",
        ), ADVOCATE))
    resp = api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-06T00:00:00Z", service_end="2027-03-08T00:00:00Z",
        ), ADVOCATE)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_CAPACITY_EXCEEDED)

    # R4 starts exactly at R1's end: it counts only against R2, so it fits.
    validate_created(api.create_reentry_referral(
        create_reentry_referral_payload(
            case_id, provider_id,
            service_start="2027-03-10T00:00:00Z", service_end="2027-03-20T00:00:00Z",
        ), ADVOCATE))

    # Three live referrals (R1, R2, R4); the rejected R3 occupies nothing.
    assert get_reentry_provider(provider_id)["slots_in_use"] == 3


def test_provider_slots_conserved_across_create_activate_complete(api):
    """PRD section 3.9: "A successful create lands the referral in `PENDING`
    and increments the provider's `slots_in_use` (bumping the provider's
    `version`)."
    PRD section 3.9: "Completion from `ACTIVE`, or cancellation from `PENDING`
    or `ACTIVE`, releases the slot: `slots_in_use` decrements and the
    provider's `version` increments."

    Design: Difficulty/compensating_invariant/provider_slots_conserved_across_create_complete_cancel
    """
    ctx = _exonerated_case_with_provider("CT", "Connecticut", 1)
    provider_id = ctx["provider"]["id"]
    assert ctx["provider"]["slots_in_use"] == 0
    set_clock("2027-03-02T00:00:00Z")

    referral = create_reentry_referral(
        ctx["case"]["id"], provider_id,
        service_start="2027-03-01T00:00:00Z", service_end="2027-03-10T00:00:00Z",
    )
    assert get_reentry_provider(provider_id)["slots_in_use"] == 1, (
        "the forward action occupies the slot"
    )

    advance_reentry_referral(referral["id"], "ACTIVATE")
    assert get_reentry_provider(provider_id)["slots_in_use"] == 1, (
        "PENDING already occupied the slot; activation changes no accounting"
    )

    advance_reentry_referral(referral["id"], "COMPLETE")
    assert get_reentry_provider(provider_id)["slots_in_use"] == 0, (
        "create + complete conserve the pool"
    )


def test_provider_slots_conserved_across_create_and_cancel(api):
    """PRD section 3.9: "Completion from `ACTIVE`, or cancellation from
    `PENDING` or `ACTIVE`, releases the slot: `slots_in_use` decrements and
    the provider's `version` increments."
    PRD section 3.9: "The provider's `slots_in_use` is a computed count of its
    referrals in `PENDING` or `ACTIVE` status, written on referral creation,
    completion, and cancellation; it starts at 0."

    Design: Difficulty/compensating_invariant/provider_slots_conserved_across_create_complete_cancel
    """
    ctx = _exonerated_case_with_provider("CT", "Connecticut", 1)
    provider_id = ctx["provider"]["id"]

    referral = create_reentry_referral(
        ctx["case"]["id"], provider_id,
        service_start="2027-03-05T00:00:00Z", service_end="2027-03-15T00:00:00Z",
    )
    assert get_reentry_provider(provider_id)["slots_in_use"] == 1

    advance_reentry_referral(referral["id"], "CANCEL")
    provider = get_reentry_provider(provider_id)
    assert provider["slots_in_use"] == 0, "create + cancel conserve the pool"
    assert provider["total_capacity"] == 1, "pool size is invariant; only occupancy moves"

    rows, _ = list_rows(api.list_reentry_provider_referrals(provider_id, ADVOCATE))
    assert_slots_in_use_consistent(provider, rows)
