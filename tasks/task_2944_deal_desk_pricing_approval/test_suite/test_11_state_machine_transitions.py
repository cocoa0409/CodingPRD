"""Declared initial states, refused replays, terminal lockdown and sweep cascades."""
from test_helpers import (
    ApiErrorId,
    EPOCH_STAMP,
    USER_IDS,
    assert_instant_equals,
    assert_paginated_list,
    assert_unset,
    create_desk_policy_with_matrix,
    create_grant,
    decide_step,
    generate_order_form,
    get_success_data,
    latest_approval_request,
    read_order_form,
    read_quote,
    read_step,
    revoke_grant,
    run_expiry_sweep,
    set_clock,
    setup_signed_order_form,
    setup_submitted_quote,
    setup_approved_quote,
    validate_error,
    validate_success,
)


def test_a_second_policy_is_born_draft_and_its_activation_supersedes_the_first(
    api, base, admin_headers
):
    """PRD §3.1: "A freshly created revision has `activated_at` and `superseded_at` both unset."
    PRD §3.1: "A revision only becomes law when a `PlatformAdmin` activates it, driving
    `status` from `DRAFT` to `ACTIVE`."
    PRD §3.1: "It then cascades downward: whichever revision currently holds `ACTIVE` — and at
    most one ever does — moves `ACTIVE` to `SUPERSEDED` and has its `superseded_at` stamped
    with the same instant."

    Design: Corner/state_machines/new_desk_policy_starts_draft_and_activation_supersedes_the_previous_one
    """
    second = create_desk_policy_with_matrix(api, activate=False, name="FY27 Deal Desk Policy")
    assert second["policy"]["status"] == "DRAFT"
    assert_unset(second["policy"], "activated_at", "superseded_at")

    activated = validate_success(api.activate_desk_policy(second["policy"]["id"], admin_headers))
    assert activated["status"] == "ACTIVE"
    assert_instant_equals(activated["activated_at"], EPOCH_STAMP, "activated_at")

    superseded = get_success_data(api.get_desk_policy(base["policy"]["id"], admin_headers))
    assert superseded["status"] == "SUPERSEDED"
    assert_instant_equals(superseded["superseded_at"], EPOCH_STAMP, "superseded_at")

    still_active = get_success_data(api.get_desk_policy(second["policy"]["id"], admin_headers))
    assert still_active["status"] == "ACTIVE"


def test_a_second_signature_on_a_signed_order_form_is_refused(api, base, analyst_headers):
    """PRD §3.9: "Both outcomes require the form to be in `OUT_FOR_SIGNATURE`, otherwise
    `ERR_ORDER_FORM_STATE_INVALID`, and both require the parent quote to be in `APPROVED`,
    otherwise `ERR_QUOTE_NOT_APPROVED`."
    PRD §2.11: "Checks are evaluated from the top of the list downwards, the first violated
    check decides the response, and no side effect of the request — not a state change, not a
    recomputation, not a ledger move — is applied when any check fails."

    Design: Corner/state_machines/second_signature_on_a_signed_order_form_is_state_invalid
    """
    scenario = setup_signed_order_form(
        api, base, [("support", 10, 0.00)], title="Northwind Signature Lockdown",
        payment_terms_days=30,
    )
    assert scenario["quote"]["status"] == "APPROVED"
    assert scenario["form"]["status"] == "SIGNED"
    assert_instant_equals(scenario["form"]["signed_at"], EPOCH_STAMP, "signed_at")
    assert scenario["form"]["signed_by_name"] == "Dana Signer"

    response = api.record_order_form_signature(
        scenario["form"]["id"], {"outcome": "DECLINED"}, analyst_headers
    )
    validate_error(response, ApiErrorId.ERR_ORDER_FORM_STATE_INVALID.value, 409)

    after = read_order_form(api, scenario["form"]["id"], analyst_headers)
    assert after["status"] == "SIGNED"
    assert_instant_equals(after["signed_at"], EPOCH_STAMP, "signed_at")
    assert after["signed_by_name"] == "Dana Signer"
    assert_unset(after, "declined_at")


def test_replaying_a_decision_on_a_decided_step_raises_no_second_successor(
    api, base, analyst_headers
):
    """PRD §3.7: "The step's `decision` must still be `PENDING`, otherwise
    `ERR_STEP_ALREADY_DECIDED`."
    PRD §3.7: "An `APPROVE` on a step whose `level` is below the request's `required_level`
    moves the step `PENDING` to `APPROVED` and creates the next step at `level` one higher,
    with `assigned_role` taken from the matrix band at that next `tier_level` and fresh
    turnaround fields, and advances the request's `current_level` to that new level."

    Design: Corner/state_machines/deciding_an_already_decided_approval_step_returns_step_already_decided
    """
    scenario = setup_submitted_quote(
        api, base, [("support", 10, 0.20)], title="Northwind Replay Check", payment_terms_days=30,
    )
    assert scenario["quote"]["required_approval_level"] == 2
    first = scenario["step"]

    decided = decide_step(api, first["id"], "APPROVE", analyst_headers, "Level 1 cleared")
    assert decided["decision"] == "APPROVED"
    assert_instant_equals(decided["decided_at"], EPOCH_STAMP, "decided_at")
    assert decided["decision_note"] == "Level 1 cleared"

    response = api.decide_approval_step(
        first["id"], {"decision": "APPROVE", "decision_note": "Replayed approval"}, analyst_headers
    )
    validate_error(response, ApiErrorId.ERR_STEP_ALREADY_DECIDED.value, 409)

    assert read_step(api, first["id"], analyst_headers)["decision_note"] == "Level 1 cleared"
    pending, _ = assert_paginated_list(
        api.list_approval_steps(
            analyst_headers,
            params={"approval_request_id": scenario["request"]["id"], "decision": "PENDING"},
        ),
        expected_total=1, expected_page_size=1,
    )
    assert pending[0]["level"] == 2
    assert latest_approval_request(api, scenario["quote"]["id"])["current_level"] == 2


def test_revoking_an_already_revoked_grant_is_refused_and_keeps_the_first_stamp(
    api, base, director_headers
):
    """PRD §2.10: "A grant is created in `ACTIVE` status and leaves that status in exactly two
    ways: the grantor revokes it, moving it to `REVOKED` and stamping `revoked_at`; or the
    expiry sweep observes that the logical clock has reached `ends_at` and moves it to
    `EXPIRED`."
    PRD §2.11: "The target record is in a status from which the requested transition is
    declared."

    Design: Corner/state_machines/revoking_an_already_revoked_delegation_grant_is_state_invalid
    """
    grant = create_grant(
        api, USER_IDS["grantee_a"], 2, 0.20, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
        headers=director_headers,
    )
    assert grant["status"] == "ACTIVE"

    revoked = revoke_grant(api, grant["id"], director_headers)
    assert revoked["status"] == "REVOKED"
    assert_instant_equals(revoked["revoked_at"], EPOCH_STAMP, "revoked_at")

    response = api.revoke_delegation_grant(grant["id"], director_headers)
    validate_error(response, ApiErrorId.ERR_DELEGATION_STATE_INVALID.value, 409)

    grants, _ = assert_paginated_list(
        api.list_delegation_grants(director_headers, params={"tier_level": 2}),
        expected_total=1, expected_page_size=1,
    )
    assert grants[0]["status"] == "REVOKED"
    assert_instant_equals(grants[0]["revoked_at"], EPOCH_STAMP, "revoked_at")


def test_the_expiry_sweep_expires_the_quote_and_voids_its_generated_order_form(
    api, base, rep_headers, analyst_headers
):
    """PRD §3.8: "Expiry, like breach, is strict: a quote expires only when the logical clock
    is strictly past its `expires_at`."
    PRD §3.8: "When it does expire from `APPROVED`, every order form on the quote whose
    `status` is `GENERATED` or `OUT_FOR_SIGNATURE` moves to `VOID` with `voided_at` stamped and
    `void_reason` set to the fixed string `QUOTE_EXPIRED`, and every `ACCEPTED` exception is
    released with the same allowance return."
    PRD §3.8: "The sweep answers with `swept_at`, `expired_quote_ids`,
    `expired_delegation_grant_ids`, `voided_order_form_ids` and `released_exception_ids`."

    Design: Corner/state_machines/expiry_sweep_expires_the_approved_quote_and_voids_its_generated_order_form
    """
    scenario = setup_approved_quote(
        api, base, [("support", 10, 0.00)], title="Northwind Expiry Cascade",
        payment_terms_days=30,
    )
    quote = scenario["quote"]
    assert quote["status"] == "APPROVED"
    assert_instant_equals(quote["expires_at"], "2026-08-31T00:00:00.000Z", "expires_at")

    form = generate_order_form(api, quote["id"], headers=rep_headers)
    assert form["status"] == "GENERATED"

    set_clock(api, "2026-08-31T00:00:01Z")
    swept = run_expiry_sweep(api)
    assert_instant_equals(swept["swept_at"], "2026-08-31T00:00:01.000Z", "swept_at")
    assert swept["expired_quote_ids"] == [quote["id"]]
    assert swept["voided_order_form_ids"] == [form["id"]]
    assert swept["expired_delegation_grant_ids"] == []
    assert swept["released_exception_ids"] == []

    assert read_quote(api, quote["id"], rep_headers)["status"] == "EXPIRED"
    voided = read_order_form(api, form["id"], analyst_headers)
    assert voided["status"] == "VOID"
    assert voided["void_reason"] == "QUOTE_EXPIRED"
    assert_instant_equals(voided["voided_at"], "2026-08-31T00:00:01.000Z", "voided_at")
