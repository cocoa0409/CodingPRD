"""Declared lifecycle edges, their guards and the cascades they drive."""

from test_helpers import (
    AUDIT_CORRECTIVE_ACTION_PENDING,
    AUDIT_IN_PROGRESS,
    AUDIT_REVERIFICATION,
    ApiErrorId,
    BATCH_CONSUMED,
    BATCH_MIXING,
    BATCH_REJECTED,
    CAP_SOURCE_STAFFING,
    CERT_HACCP_RICE_ACIDIFICATION,
    CERT_REVOKED,
    CHEF_CERTIFIED,
    CHEF_SUSPENDED,
    DISCARD_AUDIT_LOCKDOWN,
    DISCARD_SHELF_LIFE_EXPIRED,
    FINDING_CORRECTED,
    KIOSK_DECOMMISSIONED,
    KIOSK_OPERATING,
    LICENSE_ACTIVE,
    LICENSE_DRAFT,
    PACK_DISCARDED,
    PLAN_VOIDED,
    REJECTION_PLAN_VOIDED,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    SETTLEMENT_DISPUTED,
    SETTLEMENT_DRAFT,
    SPACE_COMPLIANT,
    SPACE_UNVERIFIED,
    add_chef,
    add_draft_plan,
    add_mixing_rice_batch,
    add_pack_lot,
    add_released_plan,
    add_submitted_audit,
    assert_close,
    assert_discard_event,
    assert_rice_batch,
    base_world,
    correct_all_findings,
    correction_payload,
    decommission_payload,
    dispute_payload,
    discard_payload,
    find_by_id,
    packed_world,
    plan_void_payload,
    production_plan_payload,
    revision_payload,
    revocation_payload,
    settled_world,
    shelf_ready_world,
    validate_error,
    validate_list,
    validate_success,
)


def test_rice_batch_starts_in_mixing_with_its_yield_ceiling_fixed(api):
    """A started batch is MIXING and knows how many packs it can ever yield.

    "The batch starts in `MIXING` and immediately computes `max_pack_yield`, the
    ceiling on how many packs may ever be drawn from it, as `rice_kg` divided by
    0.12 kilograms of rice per pack, rounded down to a whole pack."

    Design: Corner/state_machines/rice_batch_starts_in_mixing
    """
    world = base_world()
    plan = add_released_plan(world)

    batch = add_mixing_rice_batch(world, plan["id"])
    assert_rice_batch(batch)

    assert batch["status"] == BATCH_MIXING
    assert batch["production_plan_id"] == plan["id"]
    assert batch["chef_id"] == world["chef_id"]
    assert batch["max_pack_yield"] == 180
    assert batch["measured_ph"] is None
    assert batch["exposure_minutes"] is None
    assert batch["rejection_reason"] is None
    assert batch["version"] == 1

    validate_list(
        api.list_rice_batches(world["ops_headers"], {"production_plan_id": plan["id"]}),
        expected_total=1,
    )


def test_license_activation_moves_draft_to_active_and_prices_the_space(api):
    """Activation takes the agreement live and recomputes the space shortfall.

    "Activation recomputes `space_shortfall_sqft` from the store's current
    attestation, re-derives the store's `space_compliance_state` against this
    agreement's obligations, and increments the agreement's `version` by 1."

    Design: Corner/state_machines/license_agreement_activate_moves_draft_to_active
    """
    world = base_world(activate=False, commission=False)
    drafted = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert drafted["status"] == LICENSE_DRAFT
    assert drafted["version"] == 1

    activated = validate_success(
        api.activate_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert activated["status"] == LICENSE_ACTIVE
    assert activated["version"] == 2
    assert activated["space_shortfall_sqft"] == 0
    assert activated["active_kiosk_count"] == 0
    assert activated["suspension_reason"] is None

    store = validate_success(
        api.get_host_store(world["host_store_id"], world["ops_headers"])
    )
    assert store["space_compliance_state"] == SPACE_COMPLIANT


def test_license_activation_without_any_space_attestation_is_refused(api):
    """An unverified store cannot have its agreement activated.

    "Moving an agreement `DRAFT → ACTIVE` requires the host store's
    `pos_integration_status` to be `CONNECTED`, and it requires the store to have
    attested at least once: an `UNVERIFIED` store is refused with
    `ERR_SPACE_OBLIGATION_DEFICIENT`."

    Design: Corner/state_machines/license_agreement_activate_without_space_attestation_rejected
    """
    world = base_world(attest=False, activate=False, place=False, commission=False)
    store = validate_success(
        api.get_host_store(world["host_store_id"], world["ops_headers"])
    )
    assert store["space_compliance_state"] == SPACE_UNVERIFIED

    validate_error(
        api.activate_license_agreement(world["agreement_id"], world["ops_headers"]),
        ApiErrorId.ERR_SPACE_OBLIGATION_DEFICIENT.value,
        422,
    )

    unchanged = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert unchanged["status"] == LICENSE_DRAFT
    assert unchanged["version"] == 1


def test_settlement_acknowledgement_from_draft_is_a_state_error(api):
    """Acknowledgement is reachable only from ISSUED.

    "From `ISSUED` the host store manager either acknowledges or disputes, and
    ownership is enforced on both: a manager may only act on statements of their
    own store."

    Design: Corner/state_machines/settlement_acknowledge_from_draft_rejected
    """
    world = settled_world()

    validate_error(
        api.acknowledge_settlement_statement(
            world["statement_id"], world["manager_headers"]
        ),
        ApiErrorId.ERR_SETTLEMENT_INVALID_STATE.value,
        409,
    )

    statement = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert statement["status"] == SETTLEMENT_DRAFT
    assert statement["version"] == 1


def test_second_discard_of_a_discarded_pack_lot_is_refused(api):
    """Exactly one discard event is ever appended to a lot.

    "Exactly one discard event is appended, never more: its `discarded_count` is
    the lot's `unsold_count` at that instant" and "`SOLD_OUT`, `DISCARDED` and
    `VOIDED` are all terminal."

    Design: Corner/state_machines/pack_lot_second_discard_from_discarded_rejected
    """
    world = packed_world()

    validate_success(
        api.discard_pack_lot(
            world["pack_lot_id"],
            discard_payload(DISCARD_SHELF_LIFE_EXPIRED),
            world["auditor_headers"],
        )
    )
    first = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )[0]
    assert_discard_event(first)
    assert first["discarded_count"] == 160
    assert first["settlement_credit_eligible"] is True

    validate_error(
        api.discard_pack_lot(
            world["pack_lot_id"],
            discard_payload(DISCARD_SHELF_LIFE_EXPIRED),
            world["auditor_headers"],
        ),
        ApiErrorId.ERR_PACK_LOT_INVALID_STATE.value,
        409,
    )

    lot = validate_success(api.get_pack_lot(world["pack_lot_id"], world["ops_headers"]))
    assert lot["status"] == PACK_DISCARDED
    assert lot["discarded_count"] == 160
    assert lot["unsold_count"] == 0
    validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )


def test_starting_an_already_open_audit_is_refused(api):
    """The start edge exists only out of SCHEDULED.

    "verifying an audit that is not in `REVERIFICATION`, or submitting one that
    was never started, is `ERR_AUDIT_INVALID_STATE`; and because state is checked
    before every business rule, a terminal-state target always reports the state
    error rather than a business complaint."

    Design: Corner/state_machines/audit_start_twice_rejected
    """
    world = base_world()
    audit = validate_success(
        api.create_audit(
            {"kiosk_id": world["kiosk_id"], "scheduled_for": "2026-08-03"},
            world["auditor_headers"],
        ),
        201,
    )
    opened = validate_success(api.start_audit(audit["id"], world["auditor_headers"]))
    assert opened["status"] == AUDIT_IN_PROGRESS
    assert opened["opened_by_user_id"] is not None

    validate_error(
        api.start_audit(audit["id"], world["auditor_headers"]),
        ApiErrorId.ERR_AUDIT_INVALID_STATE.value,
        409,
    )

    still_open = validate_success(api.get_audit(audit["id"], world["auditor_headers"]))
    assert still_open["status"] == AUDIT_IN_PROGRESS
    assert still_open["round_count"] == 0


def test_second_certified_chef_raises_the_staffing_ceiling(api):
    """Placing another certified chef lifts the staffing cap on the next plan.

    "The **staffing** ceiling is the kiosk's `certified_chef_count` multiplied by
    200 packs per certified chef; only chefs whose `status` is `CERTIFIED` count,
    which is why a revoked certification quietly lowers tomorrow's plan."

    Design: Corner/state_machines/second_chef_placement_raises_certified_chef_count_and_staffing_cap
    """
    world = base_world(
        store_overrides={
            "refrigerated_case_linear_ft": 100.0,
            "refrigerated_case_capacity_packs": 2000,
        }
    )
    first_plan = add_draft_plan(world, traffic_forecast=60000)
    assert first_plan["planned_pack_count"] == 200
    assert first_plan["binding_cap_source"] == CAP_SOURCE_STAFFING

    second_chef = add_chef(world, "Mika Sato", as_lead_chef=False)
    assert second_chef["status"] == CHEF_CERTIFIED
    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["certified_chef_count"] == 2

    second_plan = add_draft_plan(
        world, traffic_forecast=60000, production_date="2026-08-04"
    )
    assert second_plan["planned_pack_count"] == 400
    assert second_plan["binding_cap_source"] == CAP_SOURCE_STAFFING
    assert_close(second_plan["planned_rice_kg"], 48.00, places=2)


def test_kiosk_decommission_unassigns_every_chef(api):
    """Decommissioning clears the placements and the agreement's live count.

    "Decommissioning also unassigns every chef whose `assigned_kiosk_id` is this
    kiosk and clears `lead_chef_id`, and it sets the agreement's
    `active_kiosk_count` to a fresh recount of that agreement's kiosks that are
    still `OPERATING`."

    Design: Corner/state_machines/kiosk_decommission_cascades_to_chef_unassignment
    """
    world = base_world()
    add_chef(world, "Mika Sato", as_lead_chef=False)

    retired = validate_success(
        api.decommission_kiosk(
            world["kiosk_id"], decommission_payload(), world["ops_headers"]
        )
    )
    assert retired["operational_state"] == KIOSK_DECOMMISSIONED
    assert retired["lead_chef_id"] is None

    for chef in validate_list(api.list_chefs(world["ops_headers"]), expected_total=2):
        assert chef["assigned_kiosk_id"] is None

    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["active_kiosk_count"] == 0

    validate_error(
        api.decommission_kiosk(
            world["kiosk_id"], decommission_payload(), world["ops_headers"]
        ),
        ApiErrorId.ERR_KIOSK_INVALID_STATE.value,
        409,
    )


def test_revoking_a_mandatory_certification_suspends_the_chef(api):
    """Losing HACCP suspends the chef and lowers tomorrow's staffing ceiling.

    "if the lost certification was a `FOOD_HANDLER` or
    `HACCP_RICE_ACIDIFICATION` and the chef was `CERTIFIED`, the chef moves
    `CERTIFIED → SUSPENDED` and the assigned kiosk's `certified_chef_count` is
    decremented and that kiosk's risk inputs recomputed. … In neither case is the
    kiosk itself suspended."

    Design: Corner/state_machines/certification_revoke_suspends_chef_and_lowers_staffing
    """
    world = base_world()
    haccp_id = world["certifications"]["haccp"]["id"]

    validate_success(
        api.revoke_certification(
            world["chef_id"], haccp_id, revocation_payload(), world["auditor_headers"]
        )
    )
    revoked = find_by_id(
        validate_list(
            api.list_certifications(world["chef_id"], world["auditor_headers"])
        ),
        haccp_id,
    )
    assert revoked["status"] == CERT_REVOKED
    assert revoked["cert_type"] == CERT_HACCP_RICE_ACIDIFICATION
    assert revoked["revocation_reason"] == "FALSIFIED_EXAM_RECORD"

    chef = validate_success(api.get_chef(world["chef_id"], world["ops_headers"]))
    assert chef["status"] == CHEF_SUSPENDED
    assert chef["valid_cert_count"] == 1
    assert chef["haccp_cert_expires_at"] is None

    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert kiosk["certified_chef_count"] == 0
    assert kiosk["operational_state"] == KIOSK_OPERATING

    plan = validate_success(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], kiosk["version"]),
            world["ops_headers"],
        ),
        201,
    )
    assert plan["planned_pack_count"] == 0
    assert plan["binding_cap_source"] == CAP_SOURCE_STAFFING

    validate_error(
        api.revoke_certification(
            world["chef_id"], haccp_id, revocation_payload(), world["auditor_headers"]
        ),
        ApiErrorId.ERR_CERTIFICATION_INVALID_STATE.value,
        409,
    )


def test_plan_void_rejects_only_the_non_terminal_rice_batches(api):
    """A void spares batches already consumed and rejects the rest.

    "the void rejects every rice batch of the plan that is not already `REJECTED`
    or `CONSUMED` with `rejection_reason` `PLAN_VOIDED`, discards every pack lot
    of the plan's batches that is still `ON_SHELF` or `MARKED_DOWN` with a discard
    event whose `reason` is `AUDIT_LOCKDOWN`."

    Design: Corner/state_machines/plan_void_rejects_only_non_terminal_rice_batches
    """
    world = shelf_ready_world()
    pack_lot = add_pack_lot(world, world["rice_batch_id"], world["fish_lot_id"])
    untouched = add_mixing_rice_batch(
        world,
        world["plan_id"],
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T08:00:00Z",
    )

    voided = validate_success(
        api.void_production_plan(
            world["plan_id"], plan_void_payload(), world["ops_headers"]
        )
    )
    assert voided["status"] == PLAN_VOIDED
    assert voided["void_reason"] == "HOST_STORE_POWER_OUTAGE"
    assert voided["actual_pack_count"] == 0

    consumed = validate_success(
        api.get_rice_batch(world["rice_batch_id"], world["ops_headers"])
    )
    assert consumed["status"] == BATCH_CONSUMED
    assert consumed["rejection_reason"] is None

    rejected = validate_success(api.get_rice_batch(untouched["id"], world["ops_headers"]))
    assert rejected["status"] == BATCH_REJECTED
    assert rejected["rejection_reason"] == REJECTION_PLAN_VOIDED

    lot = validate_success(api.get_pack_lot(pack_lot["id"], world["ops_headers"]))
    assert lot["status"] == PACK_DISCARDED
    events = validate_list(
        api.list_discard_events(pack_lot["id"], world["ops_headers"]), expected_total=1
    )
    assert events[0]["reason"] == DISCARD_AUDIT_LOCKDOWN
    assert events[0]["settlement_credit_eligible"] is False


def test_disputing_then_revising_returns_the_statement_to_draft(api):
    """A revision reopens the statement, bumps the round and clears the issuer.

    "The franchisor answers a dispute by revising, which returns the statement to
    `DRAFT`, increments `revision_round` by one, records `revision_note`, clears
    `issued_by_user_id` and recomputes every money field from the currently
    reconciled feeds and discard events."

    Design: Corner/state_machines/settlement_dispute_then_revise_returns_statement_to_draft
    """
    world = settled_world()
    issued = validate_success(
        api.issue_settlement_statement(world["statement_id"], world["ops_issuer_headers"])
    )
    assert issued["issued_by_user_id"] is not None
    assert issued["binding_share_cents"] == 296000

    disputed = validate_success(
        api.dispute_settlement_statement(
            world["statement_id"], dispute_payload(), world["manager_headers"]
        )
    )
    assert disputed["status"] == SETTLEMENT_DISPUTED
    agreement = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert agreement["lifetime_share_accrued_cents"] == 0

    revised = validate_success(
        api.revise_settlement_statement(
            world["statement_id"], revision_payload(), world["ops_headers"]
        )
    )
    assert revised["status"] == SETTLEMENT_DRAFT
    assert revised["revision_round"] == 2
    assert revised["issued_by_user_id"] is None
    assert revised["revision_note"] == "Recomputed after markdown reconciliation"
    assert revised["binding_share_cents"] == 296000


def test_correcting_every_finding_unblocks_the_reverification_request(api):
    """Reverification is requestable once nothing is left OPEN.

    "Every finding of the audit must be `CORRECTED` or `WAIVED`; a single
    still-`OPEN` finding blocks the request with
    `ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION`. The request moves the audit
    `CORRECTIVE_ACTION_PENDING → REVERIFICATION` and increments `round_count` by
    one, so the first request makes it 1."

    Design: Corner/state_machines/audit_all_findings_corrected_allows_reverification_request
    """
    world = base_world()
    submitted = add_submitted_audit(world, severities=(SEVERITY_MINOR, SEVERITY_MAJOR))
    audit_id = submitted["audit_id"]
    assert submitted["audit"]["status"] == AUDIT_CORRECTIVE_ACTION_PENDING
    assert submitted["audit"]["score"] == 90
    assert submitted["audit"]["open_finding_count"] == 2

    validate_success(
        api.correct_finding(
            audit_id,
            submitted["findings"][0]["id"],
            correction_payload(),
            world["manager_headers"],
        )
    )
    corrected = find_by_id(
        validate_list(api.list_findings(audit_id, world["auditor_headers"])),
        submitted["findings"][0]["id"],
    )
    assert corrected["status"] == FINDING_CORRECTED

    validate_error(
        api.request_reverification(audit_id, world["manager_headers"]),
        ApiErrorId.ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION.value,
        422,
    )

    correct_all_findings(world, audit_id, submitted["findings"][1:])
    requested = validate_success(
        api.request_reverification(audit_id, world["manager_headers"])
    )
    assert requested["status"] == AUDIT_REVERIFICATION
    assert requested["round_count"] == 1
    assert requested["open_finding_count"] == 0
