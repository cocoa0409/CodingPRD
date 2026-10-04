"""Regulatory licensing: filing shape coherence, composite-score threshold,
and the revocation cascade."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    file_customer_license,
    get_assignment,
    get_contract,
    get_mission,
    set_clock,
    setup_provisional_assignments,
    transition_license,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.test_users import TEST_USERS, make_customer_headers

MOPS = TEST_USERS["mission_ops_headers"]
REG = TEST_USERS["regulator_headers"]
RO = TEST_USERS["range_officer_headers"]


def test_revoke_cascades_to_assignment_removal(api):
    """PRD §3.4: "When a `Regulator` moves a `GRANTED` license to `REVOKED`, a
    license covering a `CUSTOMER` subject of kind `PAYLOAD_OPERATOR` takes the
    manifest down with it: every live assignment — status `PROVISIONAL`,
    `CONFIRMED`, or `INTEGRATED` — of any payload belonging to that customer's
    contracts, on any mission in `MANIFEST_OPEN`, `MANIFEST_LOCKED`, or
    `RANGE_SCHEDULED`, is moved to `REMOVED`, each removal running the full
    release and bubble-up side effects of §3.3."

    Design: Difficulty/transitive_cascade/license_revoke_cascades_assignment_removal_and_contract_revert
    """
    ctx = setup_provisional_assignments()
    lic = ctx["customer_license"]
    a1 = ctx["assignments"][0]
    resp = api_client.transition_license(lic["id"], "REVOKED", REG)
    revoked = validate_success(resp, 200)
    assert revoked["status"] == "REVOKED"
    assert get_assignment(a1["id"])["status"] == "REMOVED", (
        "cascade hop 2: the customer's live assignment is removed"
    )


def test_revoke_cascade_bubbles_payload_contract_and_capacity(api):
    """PRD §3.4: "every live assignment — status `PROVISIONAL`, `CONFIRMED`, or
    `INTEGRATED` — of any payload belonging to that customer's contracts, on any
    mission in `MANIFEST_OPEN`, `MANIFEST_LOCKED`, or `RANGE_SCHEDULED`, is moved
    to `REMOVED`, each removal running the full release and bubble-up side
    effects of §3.3."
    PRD §3.3: "Removal releases capacity: the mission's commitment fields are
    recomputed, the payload returns from `MANIFESTED` to `REGISTERED` with a
    version increment, and — when the removed assignment was the contract's last
    live one — the contract falls back from `MANIFESTED` to `SIGNED` with its
    own increment."

    Design: Difficulty/transitive_cascade/license_revoke_cascades_assignment_removal_and_contract_revert
    """
    ctx = setup_provisional_assignments()
    lic = ctx["customer_license"]
    resp = api_client.transition_license(lic["id"], "REVOKED", REG)
    validate_success(resp, 200)
    payloads = validate_success(
        api_client.list_contract_payloads(ctx["contract"]["id"], MOPS), 200
    )
    assert payloads[0]["status"] == "REGISTERED", "cascade hop 3: payload reverts"
    assert get_contract(ctx["contract"]["id"])["status"] == "SIGNED", (
        "cascade hop 3: contract falls back"
    )
    mission = get_mission(ctx["mission"]["id"])
    assert mission["committed_mass_kg"] == 0
    assert mission["committed_volume_m3"] == 0


def test_license_and_exclusion_window_shape_incoherence_rejected(api):
    """PRD §3.4: "Incoherent pairings — a `MISSION` subject with
    `PAYLOAD_OPERATOR` kind, a `CUSTOMER` subject with `LAUNCH_AUTHORIZATION`
    kind, or a filing missing the foreign key its `subject_type` requires — fail
    request-shape validation with `ERR_INVALID_REQUEST`."
    PRD §3.5: "`WEATHER` windows must be range-scoped and `COLA`
    (collision-avoidance) windows must be orbit-scoped, a mismatched pairing
    being rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/license_and_exclusion_window_shape_incoherence_rejected
    """
    set_clock()
    customer = create_customer()

    r1 = api_client.create_license(
        {
            "subject_type": "MISSION",
            "kind": "PAYLOAD_OPERATOR",
            "mission_id": "00000000-0000-4000-8000-000000000010",
            "valid_until": "2027-01-01T00:00:00Z",
            "debris_score": 80,
            "spectrum_score": 80,
            "operator_history_score": 80,
        },
        MOPS,
    )
    validate_error(r1, ApiErrorId.ERR_INVALID_REQUEST)

    r2 = api_client.create_license(
        {
            "subject_type": "CUSTOMER",
            "kind": "LAUNCH_AUTHORIZATION",
            "customer_id": customer["id"],
            "valid_until": "2027-01-01T00:00:00Z",
            "debris_score": 80,
            "spectrum_score": 80,
            "operator_history_score": 80,
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(r2, ApiErrorId.ERR_INVALID_REQUEST)

    r3 = api_client.create_exclusion_window(
        {
            "scope_type": "ORBIT",
            "scope_value": "SSO",
            "kind": "WEATHER",
            "start_utc": "2026-10-15T00:00:00Z",
            "end_utc": "2026-10-16T00:00:00Z",
        },
        RO,
    )
    validate_error(r3, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api_client.list_licenses(REG))
    assert rows == [] and meta["total_count"] == 0


def test_license_composite_weighted_score_threshold_69_vs_70(api):
    """PRD §3.4: "The system immediately computes `composite_score` as one-half
    of `debris_score` plus three-tenths of `spectrum_score` plus one-fifth of
    `operator_history_score`, rounded half up to a whole integer, and the
    application enters `SUBMITTED`."
    PRD §3.4: "Granting requires a `composite_score` of at least 70: a score of
    exactly 70 grants, while 69 or below is rejected with
    `ERR_LICENSE_SCORE_TOO_LOW` (HTTP 422). Denial from `SUBMITTED` is
    unconditional."
    PRD §3.4: "`DENIED`, `REVOKED`, and `EXPIRED` are terminal."

    Design: Corner/calculations/license_composite_weighted_score_threshold_69_vs_70
    """
    set_clock()
    customer = create_customer()

    l1 = file_customer_license(
        customer["id"], debris_score=50, spectrum_score=90, operator_history_score=80
    )
    assert l1["composite_score"] == 68, "0.5x50 + 0.3x90 + 0.2x80 = 68"
    r1 = api_client.transition_license(l1["id"], "GRANTED", REG)
    validate_error(r1, ApiErrorId.ERR_LICENSE_SCORE_TOO_LOW)

    denied = transition_license(l1["id"], "DENIED")
    assert denied["status"] == "DENIED"
    r2 = api_client.transition_license(l1["id"], "GRANTED", REG)
    validate_error(r2, ApiErrorId.ERR_INVALID_STATE)

    l2 = file_customer_license(
        customer["id"], debris_score=60, spectrum_score=80, operator_history_score=80
    )
    assert l2["composite_score"] == 70, "0.5x60 + 0.3x80 + 0.2x80 = 70"
    granted = transition_license(l2["id"], "GRANTED")
    assert granted["status"] == "GRANTED", "boundary >= 70 grants"
