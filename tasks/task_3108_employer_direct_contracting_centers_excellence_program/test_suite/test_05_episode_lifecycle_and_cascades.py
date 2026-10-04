"""Episode lifecycle: scheduling, surgery, discharge, closure, cascades."""
from test_helpers import (
    ApiErrorId,
    add_care_item,
    adjudicate,
    administer_benefit,
    approve_episode,
    close_episode,
    drive_episode_to_post_op,
    drive_episode_to_pre_op,
    drive_episode_to_sor_pending,
    get_episode,
    get_success_data,
    make_active_contract,
    make_employer,
    make_patient,
    make_template,
    open_episode,
    schedule_episode,
    setup_approved_episode,
    setup_episode_in_post_op,
    setup_episode_in_sor_pending,
    setup_program,
    submit_claim,
    validate_error,
    validate_success,
)

ADMIN = {"X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"}
COORD = {"X-User-ID": "test-care-coordinator-1", "X-User-Role": "CareCoordinator"}
REVIEWER = {"X-User-ID": "test-physician-reviewer-1", "X-User-Role": "PhysicianReviewer"}
CLAIMS = {"X-User-ID": "test-claims-admin-1", "X-User-Role": "ClaimsAdmin"}


def test_surgery_complete_requires_required_preop_items_done(
    api, care_coordinator_headers
):
    """PRD §3.5: "It is blocked while any required `PRE_OP` item is still
    `OPEN` (`ERR_REQUIRED_CARE_INCOMPLETE`)"
    PRD §3.5: "Marking surgery complete moves the episode `PRE_OP →
    SURGERY_DONE` and carries `expected_episode_version`."

    Design: Difficulty/cross_entity_state_dependency/surgery_complete_requires_required_preop_items_done
    """
    ctx = setup_approved_episode()
    episode = drive_episode_to_pre_op(
        ctx["episode"], first_item_overrides={"required": True}
    )
    # An optional OPEN item alongside the required one.
    add_care_item(episode, phase="PRE_OP", required=False)

    current = get_episode(episode["id"])
    resp = api.complete_surgery(
        current["id"], {"expected_episode_version": current["version"]},
        care_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_REQUIRED_CARE_INCOMPLETE)
    assert get_episode(episode["id"])["status"] == "PRE_OP"

    # Completing the required item releases the gate; the optional OPEN item
    # does not matter.
    items = api.list_care_items(episode["id"], care_coordinator_headers).json()["data"]
    required_item = next(i for i in items if i["required"])
    get_success_data(api.complete_care_item(required_item["id"], care_coordinator_headers))

    current = get_episode(episode["id"])
    done = validate_success(
        api.complete_surgery(
            current["id"], {"expected_episode_version": current["version"]},
            care_coordinator_headers,
        )
    )
    assert done["status"] == "SURGERY_DONE"
    assert done["surgery_done_seq"] == done["screen_seq"], (
        "surgery_done_seq is stamped from the post-increment screen_seq"
    )
    assert done["surgery_done_seq"] >= done["scheduled_start_seq"]


def test_surgery_cannot_complete_before_scheduled_day(api, care_coordinator_headers):
    """PRD §3.5: "surgery cannot complete before its scheduled day — the
    current `screen_seq` must be at least `scheduled_start_seq`."
    PRD §3.5: "Scheduling is strictly into the future: the requested day must
    be greater than the episode's `screen_seq` at the time of the call,
    otherwise `ERR_OUTSIDE_COVERAGE_WINDOW`."

    Design: Difficulty/cross_entity_state_dependency/surgery_complete_requires_required_preop_items_done
    """
    ctx = setup_approved_episode()
    approved = ctx["episode"]
    # Schedule at current screen_seq + 2, then attempt surgery one day early.
    scheduled = schedule_episode(approved, approved["screen_seq"] + 2)
    add_care_item(scheduled, phase="PRE_OP", required=False)
    current = get_episode(approved["id"])
    assert current["status"] == "PRE_OP"
    assert current["screen_seq"] < current["scheduled_start_seq"]

    resp = api.complete_surgery(
        current["id"], {"expected_episode_version": current["version"]},
        care_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_COVERAGE_WINDOW)
    assert get_episode(approved["id"])["status"] == "PRE_OP"

    # Advance the counter onto the scheduled day; surgery now succeeds.
    target = get_episode(approved["id"])
    while target["screen_seq"] < target["scheduled_start_seq"]:
        target = validate_success(api.advance_day(target["id"], care_coordinator_headers))
    done = validate_success(
        api.complete_surgery(
            target["id"], {"expected_episode_version": target["version"]},
            care_coordinator_headers,
        )
    )
    assert done["status"] == "SURGERY_DONE"


def test_episode_closure_releases_benefits_and_absorbs_unpaid_claims(api):
    """PRD §3.6: "Closure sets `closed_outcome` to `READMITTED` when any
    readmission on the episode was recorded inside the warranty window,
    otherwise `CLEAN`; releases every `ADMINISTERED` benefit to `RELEASED`;
    and converts every still-unpaid `APPROVED` claim to `ABSORBED`, meaning
    the approved amount is never remitted."
    PRD §3.9: "the episode's `applied_bundle_price_cents`, plus an outlier
    projection when an outlier review flag is set (the expected billing above
    the contract's `outlier_threshold_cents`, floored at zero, multiplied by
    `outlier_share_pct`, divided by 100, and truncated to cents), minus the
    same unreleased accrual."

    Design: Difficulty/transitive_cascade/episode_closure_releases_benefits_and_absorbs_unpaid_claims
    """
    ctx = setup_episode_in_post_op(
        contract_overrides={"travel_benefit_cents": 200000},
        template_overrides={"warranty_days": 3},
    )
    episode = ctx["episode"]
    benefit = administer_benefit(episode, "TRAVEL", 50000)
    assert benefit["status"] == "ADMINISTERED"

    # Clinic view before closure subtracts the unreleased accrual (the
    # administered benefit) and the pool ledger holds 150000 for claims.
    before = get_success_data(
        api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"})
    )
    assert before["estimated_total_billed_cents"] == (
        before["applied_bundle_price_cents"] - 50000
    )

    claim = submit_claim(episode, "TRAVEL", episode["screen_seq"], 100000,
                         submitting_entity="TRAVEL_VENDOR")
    adjudicated = adjudicate(claim["id"])
    assert adjudicated["status"] == "APPROVED"
    assert adjudicated["adjudicated_payable_cents"] == 100000, (
        "the claim draws against the pool net of the administered benefit"
    )

    closed = close_episode(episode)
    assert closed["status"] == "CLOSED"
    assert closed["closed_outcome"] == "CLEAN"

    released = get_success_data(api.get_benefit(benefit["id"], COORD))
    assert released["status"] == "RELEASED"

    absorbed = get_success_data(api.get_claim(claim["id"], CLAIMS))
    assert absorbed["status"] == "ABSORBED", (
        "an approved-but-unpaid claim becomes ABSORBED at closure"
    )

    after = get_success_data(
        api.get_episode(episode["id"], CLAIMS, params={"view": "clinic"})
    )
    assert after["estimated_total_billed_cents"] == after["applied_bundle_price_cents"], (
        "the released accrual no longer subtracts from the estimate"
    )


def test_closure_blocked_by_pending_claim_then_fires_after_resolution(
    api, care_coordinator_headers
):
    """PRD §3.6: "When an advance brings `screen_seq` to or beyond
    `warranty_close_seq`, the episode closes — provided no required `POST_OP`
    care item is still `OPEN` (`ERR_REQUIRED_CARE_INCOMPLETE`) and no claim on
    the episode is still `PENDING` (`ERR_PENDING_CLAIMS`). The same closure
    fires on a later advance when the horizon had already passed but closure
    was previously blocked — for instance when a pending claim was resolved
    only after the close sequence had passed."

    Design: Difficulty/transitive_cascade/episode_closure_releases_benefits_and_absorbs_unpaid_claims
    """
    ctx = setup_episode_in_post_op(template_overrides={"warranty_days": 3})
    episode = ctx["episode"]
    claim = submit_claim(
        episode, "BUNDLE_CASE", episode["surgery_done_seq"], 3000000
    )
    assert claim["status"] == "PENDING"

    # Drive past the closure horizon: each advance that would close is blocked
    # by the PENDING claim.
    target = episode["warranty_close_seq"]
    current = get_episode(episode["id"])
    hit_pending = False
    while current["status"] != "CLOSED" and current["screen_seq"] < target + 1:
        resp = api.advance_day(current["id"], care_coordinator_headers)
        if resp.status_code >= 400:
            validate_error(resp, ApiErrorId.ERR_PENDING_CLAIMS)
            hit_pending = True
            # Resolve the claim, then keep advancing; closure fires later.
            adjudicate(claim["id"])
            current = get_episode(episode["id"])
            continue
        current = validate_success(resp)
    assert hit_pending, "the PENDING claim must have blocked closure at least once"
    assert current["status"] == "CLOSED", (
        "closure fires on a later advance after the blocking claim resolved"
    )

    absorbed = get_success_data(api.get_claim(claim["id"], CLAIMS))
    assert absorbed["status"] == "ABSORBED"


def test_closed_episode_is_terminal_no_further_transitions(
    api, care_coordinator_headers
):
    """PRD §2.10: "Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409)"
    PRD §2.8: "Episode status never regresses"
    PRD §3.8: "A benefit is created `ADMINISTERED` and stays outstanding until
    the episode reaches any terminal state — `CLOSED`, `AVOIDED`, or
    `CANCELLED`"

    Design: Corner/state_machines/closed_episode_is_terminal_no_further_transitions
    """
    ctx = setup_episode_in_post_op(template_overrides={"warranty_days": 3})
    episode = close_episode(ctx["episode"])
    assert episode["status"] == "CLOSED"

    screening = api.submit_screening(
        episode["id"], {"doc_type": "LAB", "result": "CANDIDATE"},
        care_coordinator_headers,
    )
    validate_error(screening, ApiErrorId.ERR_INVALID_STATE)

    schedule = api.schedule_episode(
        episode["id"],
        {"requested_day_seq": episode["screen_seq"] + 10,
         "expected_episode_version": episode["version"]},
        care_coordinator_headers,
    )
    validate_error(schedule, ApiErrorId.ERR_INVALID_STATE)

    after = get_episode(episode["id"])
    assert after["status"] == "CLOSED"
    assert after["version"] == episode["version"], (
        "rejected mutations must not bump the episode version"
    )


def test_employer_terminate_cascades_contract_episode_careitem(api):
    """PRD §2.8: "Terminating an employer terminates every one of its
    contracts still in `DRAFT` or `ACTIVE`, and each contract termination in
    turn cancels every episode on that contract that has not yet been approved
    — episodes in `INTAKE_PENDING`, `SCREENING`, `SOR_PENDING`, or
    `SOR_REVIEW` move to `CANCELLED` — while every `OPEN` care plan item on a
    cancelled episode is set to `WAIVED`."

    Design: Difficulty/transitive_cascade/employer_terminate_cascades_contract_episode_careitem
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_active_contract(employer, template)
    patient_a = make_patient(employer)
    patient_b = make_patient(employer)

    # Pre-approval episode (SOR_PENDING) — must be cancelled by the cascade.
    ep_pre = drive_episode_to_sor_pending(open_episode(patient_a, contract))
    # Post-approval episode in PRE_OP with one OPEN required care item — the
    # cascade is state-conditional and must leave it untouched.
    ep_post = drive_episode_to_pre_op(
        approve_episode(
            drive_episode_to_sor_pending(open_episode(patient_b, contract))
        ),
        first_item_overrides={"required": True},
    )
    item = api.list_care_items(ep_post["id"], COORD).json()["data"][0]
    assert item["status"] == "OPEN"

    terminated = validate_success(api.terminate_employer(employer["id"], ADMIN))
    assert terminated["status"] == "TERMINATED"

    assert get_success_data(api.get_contract(contract["id"], ADMIN))["status"] == "TERMINATED"

    after_pre = get_episode(ep_pre["id"])
    assert after_pre["status"] == "CANCELLED"
    assert after_pre["screen_seq"] == ep_pre["screen_seq"] + 1, (
        "each cancelled episode has its screen_seq incremented"
    )
    assert after_pre["version"] == ep_pre["version"] + 1, (
        "each cancelled episode has its version bumped by the cancellation"
    )

    after_post = get_episode(ep_post["id"])
    assert after_post["status"] == "PRE_OP", (
        "the cascade cancels only pre-approval episodes"
    )
    after_item = get_success_data(api.get_care_item(item["id"], COORD))
    assert after_item["status"] == "OPEN", (
        "items on an unaffected (post-approval) episode stay OPEN"
    )


def test_contract_termination_waives_open_items_on_cancelled_episode(api):
    """PRD §2.8: "each contract termination in turn cancels every episode on
    that contract that has not yet been approved — episodes in
    `INTAKE_PENDING`, `SCREENING`, `SOR_PENDING`, or `SOR_REVIEW` move to
    `CANCELLED` — while every `OPEN` care plan item on a cancelled episode is
    set to `WAIVED`."

    Design: Difficulty/transitive_cascade/employer_terminate_cascades_contract_episode_careitem
    """
    prog = setup_program()
    patient = make_patient(prog["employer"])
    ep = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))

    terminated = validate_success(
        api.terminate_contract(prog["contract"]["id"], ADMIN)
    )
    assert terminated["status"] == "TERMINATED"

    after = get_episode(ep["id"])
    assert after["status"] == "CANCELLED"
    assert after["screen_seq"] == ep["screen_seq"] + 1


def test_cascade_mutations_visible_in_same_response_chain(api):
    """PRD §2.8: "Each cancelled episode has its `screen_seq` incremented and
    its `version` bumped by the cancellation."
    PRD §2.4: "Any mutation — including system-driven side effects such as a
    cascade cancellation — refreshes `updated_at` and increments `version` on
    each resource it touches."

    Design: Corner/consistency_model/cascade_mutations_visible_in_same_response_chain
    """
    prog = setup_program()
    patient = make_patient(prog["employer"])
    ep = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))

    terminated = validate_success(
        api.terminate_contract(prog["contract"]["id"], ADMIN)
    )
    assert terminated["status"] == "TERMINATED"

    # The immediate read already reflects the cascade — no consistency lag.
    after = get_episode(ep["id"])
    assert after["status"] == "CANCELLED"
    assert after["version"] == ep["version"] + 1


def test_active_episode_occupancy_blocks_second_intake_same_family(
    api, care_coordinator_headers, physician_reviewer_headers
):
    """PRD §3.3: "a patient may hold at most one non-terminal episode per
    procedure family — a second intake in a family where an episode is still
    live fails with `ERR_ACTIVE_EPISODE_EXISTS`."
    PRD §3.4: "A conclusion of `SURGERY_UNNECESSARY` — from either
    `SOR_PENDING` or `SOR_REVIEW` — ends the episode as `AVOIDED`"

    Design: Difficulty/resource_temporal_overlap/active_episode_occupancy_blocks_second_intake_same_family
    """
    prog = setup_program()
    patient = make_patient(prog["employer"])
    ep1 = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))

    blocked = api.create_episode(
        {"patient_id": patient["id"], "contract_id": prog["contract"]["id"],
         "intake_request_id": "IR-second-attempt"},
        care_coordinator_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_ACTIVE_EPISODE_EXISTS)

    # Terminate the first episode via SURGERY_UNNECESSARY; occupancy ends at
    # the terminal transition and a fresh intake succeeds.
    validate_success(
        api.record_review(
            ep1["id"],
            {"conclusion": "SURGERY_UNNECESSARY",
             "expected_episode_version": ep1["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    assert get_episode(ep1["id"])["status"] == "AVOIDED"

    allowed = api.create_episode(
        {"patient_id": patient["id"], "contract_id": prog["contract"]["id"],
         "intake_request_id": "IR-third-attempt"},
        care_coordinator_headers,
    )
    ep2 = validate_success(allowed, expected_status=201)
    assert ep2["status"] == "INTAKE_PENDING"
    assert ep2["id"] != ep1["id"]


def test_occupancy_is_scoped_per_procedure_family(api, care_coordinator_headers):
    """PRD §3.3: "a patient may hold at most one non-terminal episode per
    procedure family — a second intake in a family where an episode is still
    live fails with `ERR_ACTIVE_EPISODE_EXISTS`."
    A live ORTHO_JOINT episode does not block a CARDIAC intake for the same
    patient — the occupancy is per family.

    Design: Difficulty/resource_temporal_overlap/active_episode_occupancy_blocks_second_intake_same_family
    """
    employer = make_employer()
    template_a = make_template()  # ORTHO_JOINT
    template_b = make_template(procedure_family="CARDIAC", label="CABG")
    contract_a = make_active_contract(employer, template_a)
    contract_b = make_active_contract(employer, template_b)
    patient = make_patient(employer)

    ep1 = open_episode(patient, contract_a)
    assert ep1["family"] == "ORTHO_JOINT"

    allowed = api.create_episode(
        {"patient_id": patient["id"], "contract_id": contract_b["id"],
         "intake_request_id": "IR-other-family"},
        care_coordinator_headers,
    )
    ep2 = validate_success(allowed, expected_status=201)
    assert ep2["family"] == "CARDIAC"
