"""Cut specifications and supply agreements: panel gating, the implicit spec
lock at first activation, the revision/re-ack cycle, the term-end clock
sweep, and the plant weekly pool boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_cut_specification_payload,
    create_supply_agreement_payload,
    make_active_agreement,
    make_agreement,
    make_chain,
    make_chain_customer_headers,
    make_spec,
    make_validated_spec,
    set_clock,
    setup_chain_with_validated_spec,
    validate_error,
    validate_paginated,
    validate_success,
    validate_spec,
)

ACCOUNT = TEST_USERS["account_manager_headers"]
QA = TEST_USERS["qa_lead_headers"]


def test_spec_create_omitting_sensory_panel_required_defaults_true(api):
    """PRD §3.4: "a `max_cook_time_sec` greater than zero, and an optional
    `sensory_panel_required` flag that defaults to true. A new specification
    starts in `SUBMITTED` status, with `ever_locked` false and `panel_score`
    null."
    PRD §3.4: "When `sensory_panel_required` is true, the score must be at
    least 7.0 or the validation is rejected with
    `ERR_PANEL_SCORE_BELOW_STANDARD` (HTTP 422)".

    Design: Corner/entities/spec_create_omitting_sensory_panel_required_defaults_true
    """
    set_clock(api=api)
    chain = make_chain(api=api)
    resp = api.create_cut_specification(
        create_cut_specification_payload(chain["id"]),  # sensory_panel_required omitted
        make_chain_customer_headers(chain["id"]),
    )
    spec = validate_success(resp, 201)
    assert spec["sensory_panel_required"] is True, "the documented default is true, not null"
    assert spec["status"] == "SUBMITTED"
    assert spec["ever_locked"] is False and spec["panel_score"] is None

    resp_v = api.validate_cut_specification(spec["id"], {"panel_score": 6.9}, QA)
    validate_error(resp_v, ApiErrorId.ERR_PANEL_SCORE_BELOW_STANDARD)
    assert resp_v.status_code == 422, "the defaulted flag still demands >= 7.0"


def test_spec_validate_panel_score_boundary_7_passes_6_9_fails(api):
    """PRD §3.4: "When `sensory_panel_required` is true, the score must be at
    least 7.0 or the validation is rejected with
    `ERR_PANEL_SCORE_BELOW_STANDARD` (HTTP 422)".
    PRD §3.4: "The specification must be `SUBMITTED` or `REVISION_REQUESTED`
    (`ERR_SPEC_NOT_AWAITING_VALIDATION` otherwise)."

    Design: Corner/calculations/spec_validate_panel_score_boundary_7_passes_6_9_fails
    """
    set_clock(api=api)
    chain = make_chain(api=api)
    spec_ok = make_spec(chain["id"], api=api)
    spec_low = make_spec(chain["id"], api=api, spec_code="SP-A-2", cut_family="WEDGE",
                         cut_size_mm=12.0, coating_type="NONE", target_color_units=3.0,
                         max_cook_time_sec=240)

    validated = validate_success(
        api.validate_cut_specification(spec_ok["id"], {"panel_score": 7.0}, QA)
    )
    assert validated["status"] == "VALIDATED", "the boundary is inclusive at 7.0"

    resp_low = api.validate_cut_specification(spec_low["id"], {"panel_score": 6.9}, QA)
    validate_error(resp_low, ApiErrorId.ERR_PANEL_SCORE_BELOW_STANDARD)
    assert resp_low.status_code == 422
    reread = validate_success(api.get_cut_specification(spec_low["id"], QA))
    assert reread["status"] == "SUBMITTED", "a failed validation leaves the spec SUBMITTED"


def test_spec_revision_before_first_lock_returns_to_validated_not_locked(api):
    """PRD §3.4: "The destination state depends on history: from `SUBMITTED`
    the spec moves to `VALIDATED`; from `REVISION_REQUESTED` it moves to
    `VALIDATED` if it has never been locked, but directly back to `LOCKED` if
    `ever_locked` is true."
    PRD §3.4: "A revision from `VALIDATED` has no such cascade, because no
    agreement could yet have pinned the spec."

    Design: Corner/state_machines/spec_revision_before_first_lock_returns_to_validated_not_locked
    """
    cs = setup_chain_with_validated_spec(api=api)  # spec VALIDATED at version 2
    spec = cs["spec"]

    revised = validate_success(
        api.request_spec_revision(spec["id"], make_chain_customer_headers(cs["chain"]["id"]))
    )
    assert revised["status"] == "REVISION_REQUESTED"

    revalidated = validate_spec(spec["id"], panel_score=8.5, api=api)
    assert revalidated["status"] == "VALIDATED", (
        f"never-locked specs return to VALIDATED, got {revalidated['status']}"
    )
    assert revalidated["ever_locked"] is False
    assert revalidated["panel_score"] == 8.5


def test_agreement_activate_locks_spec_and_pins_its_version(api):
    """PRD §3.4: "Locking happens implicitly: the first time a supply
    agreement referencing a `VALIDATED` specification is activated, the
    specification transitions to `LOCKED`, sets `ever_locked` to true, and
    increments its `version`."
    PRD §3.5: "On a first activation the agreement becomes `ACTIVE`;
    `pinned_spec_version` captures the specification's current `version`;
    `spec_stale` is cleared; `current_week_allocation_cases` is initialized to
    `weekly_contracted_cases`; and the weekly cases are reserved from the
    plant pool."

    Design: Corner/endpoints/agreement_activate_locks_spec_and_pins_its_version
    """
    cs = setup_chain_with_validated_spec(api=api)
    agreement = make_agreement(cs["chain"]["id"], cs["spec"]["id"], api=api)
    assert agreement["pinned_spec_version"] is None, "DRAFT agreements carry a null pin"

    activated = validate_success(api.activate_supply_agreement(agreement["id"], ACCOUNT))
    assert activated["status"] == "ACTIVE"
    # spec version: create 1 -> validate 2 -> lock on activation 3.
    assert activated["pinned_spec_version"] == 3
    assert activated["current_week_allocation_cases"] == 10000
    assert activated["spec_stale"] is False

    rows, _ = validate_paginated(
        api.list_cut_specifications(ACCOUNT, params={"customer_id": cs["chain"]["id"]})
    )
    spec = rows[0]
    assert spec["status"] == "LOCKED"
    assert spec["ever_locked"] is True
    assert spec["version"] == 3


def test_agreement_completes_via_clock_sweep_at_term_end_inclusive(api):
    """PRD §2.5: "Setting the clock performs a term-end sweep in the same
    operation: every supply agreement in `ACTIVE` status whose `term_end` is
    at or before the supplied `current_utc` transitions to `COMPLETED`, its
    reserved weekly cases are released back to the plant pool, and its
    `version` increments."
    PRD §3.5: "the term-end sweep of §2.5 moves an `ACTIVE` agreement to
    `COMPLETED` once the logical clock reaches its `term_end`, releasing its
    weekly cases permanently."

    Design: Corner/state_machines/agreement_completes_via_clock_sweep_at_term_end_inclusive
    """
    set_clock(api=api)
    cs_a = setup_chain_with_validated_spec(api=api)
    agr_a = make_active_agreement(
        cs_a["chain"]["id"], cs_a["spec"]["id"], api=api,
        weekly_contracted_cases=60000, term_end="2026-10-01T00:00:00Z",
    )
    chain_b = make_chain(api=api, chain_code="CH-BETA", legal_name="Beta Diner Group",
                         priority_tier="TIER_2_PREFERRED")
    spec_b = make_validated_spec(chain_b["id"], api=api, spec_code="SP-B-1",
                                 cut_family="CRINKLE", cut_size_mm=10.0,
                                 coating_type="SEASONED", target_color_units=2.0,
                                 max_cook_time_sec=210)
    agr_b = make_agreement(chain_b["id"], spec_b["id"], api=api,
                           weekly_contracted_cases=100000, price_per_case_cents=310)

    # The sweep is inclusive: term_end exactly equals the new clock reading.
    set_clock("2026-10-01T00:00:00Z", api=api)

    completed = validate_success(api.get_supply_agreement(agr_a["id"], ACCOUNT))
    assert completed["status"] == "COMPLETED"

    activated_b = validate_success(api.activate_supply_agreement(agr_b["id"], ACCOUNT))
    assert activated_b["status"] == "ACTIVE", (
        "A's released 60000-case reservation lets the 100000-case agreement activate"
    )

    rows, _ = validate_paginated(api.list_supply_agreements(ACCOUNT, params={"status": "COMPLETED"}))
    assert len(rows) == 1 and rows[0]["id"] == agr_a["id"]


def test_spec_revision_cycle_flags_and_reacks_agreement(api):
    """PRD §3.4: "When the revised spec was `LOCKED`, the revision also flags
    downstream staleness: every `ACTIVE` supply agreement whose
    `pinned_spec_version` equals the specification's pre-revision `version`
    has its `spec_stale` set to true."
    PRD §3.4: "from `REVISION_REQUESTED` it moves to `VALIDATED` if it has
    never been locked, but directly back to `LOCKED` if `ever_locked` is
    true."
    PRD §3.5: "re-activating it re-pins `pinned_spec_version` to the
    specification's current `version` and clears `spec_stale`."

    Design: Difficulty/non_linear_state_machine/cut_spec_revision_cycle_flags_and_reacks_agreement
    """
    cs = setup_chain_with_validated_spec(api=api)  # spec v2 VALIDATED
    agreement = make_active_agreement(cs["chain"]["id"], cs["spec"]["id"], api=api)
    assert agreement["pinned_spec_version"] == 3, "spec v3 after the implicit lock"

    revised = validate_success(
        api.request_spec_revision(cs["spec"]["id"], make_chain_customer_headers(cs["chain"]["id"]))
    )
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["version"] == 4, "spec cycles SUBMITTED(1) VALIDATED(2) LOCKED(3) REVISION_REQUESTED(4)"

    rows, _ = validate_paginated(
        api.list_supply_agreements(ACCOUNT, params={"customer_id": cs["chain"]["id"]})
    )
    mid = rows[0]
    assert mid["spec_stale"] is True, "the revision flags the pinned ACTIVE agreement"
    assert mid["pinned_spec_version"] == 3, "the pin is not rewritten by the revision"
    assert mid["status"] == "ACTIVE"

    relocked = validate_spec(cs["spec"]["id"], panel_score=8.5, api=api)
    assert relocked["status"] == "LOCKED", "ever_locked steers the re-validation back to LOCKED"
    assert relocked["version"] == 5

    reacked = validate_success(api.activate_supply_agreement(agreement["id"], ACCOUNT))
    assert reacked["status"] == "ACTIVE", "the cycle never leaves ACTIVE"
    assert reacked["spec_stale"] is False
    assert reacked["pinned_spec_version"] == 5, "re-ack re-pins to the post-revision version"


def test_reack_while_spec_still_under_revision_is_rejected(api):
    """PRD §3.5: "This branch requires the specification to be `LOCKED` again
    (`ERR_SPEC_NOT_LOCKED` otherwise); an `ACTIVE` agreement without a stale
    pin is not activatable at all (`ERR_AGREEMENT_NOT_ACTIVABLE`)."

    Design: Difficulty/non_linear_state_machine/cut_spec_revision_cycle_flags_and_reacks_agreement
    """
    cs = setup_chain_with_validated_spec(api=api)
    agreement = make_active_agreement(cs["chain"]["id"], cs["spec"]["id"], api=api)
    validate_success(
        api.request_spec_revision(cs["spec"]["id"], make_chain_customer_headers(cs["chain"]["id"]))
    )

    resp = api.activate_supply_agreement(agreement["id"], ACCOUNT)
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_LOCKED)
    assert resp.status_code == 409, "the spec is REVISION_REQUESTED, not yet LOCKED again"

    stale = validate_success(api.get_supply_agreement(agreement["id"], ACCOUNT))
    assert stale["spec_stale"] is True and stale["status"] == "ACTIVE", (
        "a rejected re-ack leaves the stale pin in place"
    )
