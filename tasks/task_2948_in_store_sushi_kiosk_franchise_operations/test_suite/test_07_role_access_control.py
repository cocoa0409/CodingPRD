"""Which role may drive which operation, and where peer isolation bites instead."""

from test_helpers import (
    AUDITOR_VERIFIER_ID,
    AUDIT_CLOSED,
    AUDIT_REVERIFICATION,
    ApiErrorId,
    BATCH_APPROVED,
    CLOSURE_PASS_AFTER_CORRECTION,
    DISCARD_SHELF_LIFE_EXPIRED,
    FINDING_CORRECTED,
    FINDING_VERIFIED,
    KIOSK_OPERATING,
    KIOSK_SUSPENDED,
    MARKDOWN_POLICY_PRORATED,
    PACK_MARKED_DOWN,
    PACK_ON_SHELF,
    PLAN_RELEASED,
    PLAN_VOIDED,
    POSTURE_CLEAR,
    POSTURE_WATCH,
    SEVERITY_MAJOR,
    SPACE_UNVERIFIED,
    VOID_REASON_KIOSK_SUSPENDED,
    acidification_reading_payload,
    add_mixing_rice_batch,
    add_released_plan,
    add_reverification_request,
    add_submitted_audit,
    base_world,
    create_host_store,
    discard_payload,
    find_by_id,
    make_host_store_manager_headers,
    packed_world,
    production_plan_payload,
    space_attestation_payload,
    suspension_payload,
    validate_error,
    validate_list,
    validate_success,
    verification_payload,
)


def test_planning_production_is_closed_to_the_quality_auditor(api):
    """The auditor who may inspect and suspend a kiosk still may not plan its day.

    The plan create endpoint is open to "FranchiseChef, FranchisorOps", and "The
    role is one of the four declared names and is listed for the endpoint, or
    `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/quality_auditor_cannot_create_production_plan_forbidden_role
    """
    world = base_world()
    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    opening_version = kiosk["version"]

    validate_error(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], opening_version),
            world["auditor_headers"],
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    validate_list(
        api.list_production_plans(
            world["ops_headers"], {"kiosk_id": world["kiosk_id"]}
        ),
        expected_total=0,
    )
    untouched = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert untouched["version"] == opening_version

    by_chef = validate_success(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], opening_version),
            world["chef_headers"],
        ),
        201,
    )
    assert by_chef["planned_pack_count"] == 162

    refreshed = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    by_ops = validate_success(
        api.create_production_plan(
            production_plan_payload(world["kiosk_id"], refreshed["version"]),
            world["ops_headers"],
        ),
        201,
    )
    assert by_ops["planned_pack_count"] == 162
    assert by_ops["id"] != by_chef["id"]


def test_a_store_manager_may_only_attest_space_for_their_own_store(api):
    """The manager's identity is a store id, so a foreign store is an ownership failure.

    "An entity-backed actor that reaches outside its own scope is rejected with
    `ERR_OWNERSHIP_MISMATCH` (HTTP 403) … Ownership is a scoping check rather than
    a business rule, and it fires before any state or business validation on the
    target."

    Design: Corner/rbac/host_store_manager_cannot_attest_space_for_another_store
    """
    world = base_world()
    other_store = create_host_store(
        name="Northgate Market 419", store_number="419"
    )
    attestation = space_attestation_payload(
        attested_sushi_space_sqft=250,
        attested_case_linear_ft=22.0,
        attested_on="2026-08-03",
    )

    validate_error(
        api.attest_space(other_store["id"], attestation, world["manager_headers"]),
        ApiErrorId.ERR_OWNERSHIP_MISMATCH.value,
        403,
    )

    foreign = validate_success(
        api.get_host_store(other_store["id"], world["ops_headers"])
    )
    assert foreign["last_attested_on"] is None
    assert foreign["attested_sushi_space_sqft"] is None
    assert foreign["space_compliance_state"] == SPACE_UNVERIFIED

    own = validate_success(
        api.get_host_store(world["host_store_id"], world["ops_headers"])
    )
    assert own["attested_sushi_space_sqft"] == 240

    accepted = validate_success(
        api.attest_space(
            other_store["id"],
            attestation,
            make_host_store_manager_headers(other_store["id"]),
        )
    )
    assert accepted["attested_sushi_space_sqft"] == 250
    assert accepted["last_attested_on"] == "2026-08-03"


def test_rice_verification_is_shared_by_the_chef_and_the_auditor(api):
    """Both food-safety roles drive the same disposition; the commercial role cannot.

    The verify endpoint is open to "FranchiseChef, QualityAuditor", and "When all
    three pass, the batch moves `ACIDIFYING → APPROVED`. `exposure_minutes` is
    recorded and no risk points at all are added to the kiosk on this branch."

    Design: Corner/rbac/chef_and_auditor_share_rice_ttc_verification
    """
    world = base_world()
    plan = add_released_plan(world)

    morning = add_mixing_rice_batch(
        world,
        plan["id"],
        hold_start_at="2026-08-03T05:00:00Z",
        hold_end_at="2026-08-03T07:00:00Z",
    )
    validate_success(
        api.record_acidification_reading(
            morning["id"], acidification_reading_payload(), world["chef_headers"]
        )
    )

    validate_error(
        api.verify_ttc(morning["id"], world["ops_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    by_auditor = validate_success(
        api.verify_ttc(morning["id"], world["auditor_headers"])
    )
    assert by_auditor["status"] == BATCH_APPROVED
    assert by_auditor["exposure_minutes"] == 120
    assert by_auditor["max_pack_yield"] == 180
    assert by_auditor["variance_submitted_by_chef_id"] is None

    quiet = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert quiet["risk_points"] == 0
    assert quiet["sanitation_posture"] == POSTURE_CLEAR

    midday = add_mixing_rice_batch(
        world,
        plan["id"],
        hold_start_at="2026-08-03T07:00:00Z",
        hold_end_at="2026-08-03T09:00:00Z",
    )
    validate_success(
        api.record_acidification_reading(
            midday["id"], acidification_reading_payload(), world["chef_headers"]
        )
    )
    by_chef = validate_success(api.verify_ttc(midday["id"], world["chef_headers"]))
    assert by_chef["status"] == BATCH_APPROVED
    assert by_chef["exposure_minutes"] == 120


def test_the_auditor_who_opened_an_audit_may_not_sign_off_its_remediation(api):
    """Segregation of duties is keyed on the user id, not on the role.

    "the verifying `X-User-ID` must differ from `opened_by_user_id` — the auditor
    who opened an audit may never be the one who signs off its remediation, and a
    self-verification is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/audit_verification_by_the_opening_auditor_rejected
    """
    world = base_world()
    submitted = add_submitted_audit(
        world,
        severities=(SEVERITY_MAJOR, SEVERITY_MAJOR),
        codes=["FS-CASE-TEMP-LOG", "FS-SANITISER-CONCENTRATION"],
    )
    audit_id = submitted["audit_id"]
    requested = add_reverification_request(world, audit_id, submitted["findings"])
    assert requested["status"] == AUDIT_REVERIFICATION

    validate_error(
        api.verify_audit(audit_id, verification_payload(), world["auditor_headers"]),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        422,
    )

    stalled = validate_success(api.get_audit(audit_id, world["auditor_headers"]))
    assert stalled["status"] == AUDIT_REVERIFICATION
    assert stalled["verified_by_user_id"] is None
    assert stalled["closure_outcome"] is None

    pending = validate_list(
        api.list_findings(audit_id, world["auditor_headers"]), expected_total=2
    )
    assert find_by_id(pending, submitted["findings"][0]["id"])["status"] == (
        FINDING_CORRECTED
    )

    carried = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert carried["risk_points"] == 8
    assert carried["sanitation_posture"] == POSTURE_WATCH

    closed = validate_success(
        api.verify_audit(
            audit_id, verification_payload(), world["auditor_verifier_headers"]
        )
    )
    assert closed["status"] == AUDIT_CLOSED
    assert closed["closure_outcome"] == CLOSURE_PASS_AFTER_CORRECTION
    assert closed["verified_by_user_id"] == AUDITOR_VERIFIER_ID

    cleared = validate_list(
        api.list_findings(audit_id, world["auditor_headers"]), expected_total=2
    )
    assert all(finding["status"] == FINDING_VERIFIED for finding in cleared)

    lifted = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert lifted["risk_points"] == 0
    assert lifted["sanitation_posture"] == POSTURE_CLEAR


def test_shelf_pricing_belongs_to_the_chef_alone(api):
    """Neither the franchisor nor the auditor may reprice a shelf, though both read it.

    The markdown endpoint is open to "FranchiseChef" alone, while discarding is open
    to "FranchiseChef, QualityAuditor", so the exclusivity is per operation:
    "`markdown_variant_applied` records which policy was binding."

    Design: Corner/rbac/franchisor_ops_cannot_mark_down_a_pack_lot
    """
    world = packed_world()

    validate_error(
        api.markdown_pack_lot(world["pack_lot_id"], world["ops_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api.markdown_pack_lot(world["pack_lot_id"], world["auditor_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    listed = validate_success(
        api.get_pack_lot(world["pack_lot_id"], world["ops_headers"])
    )
    assert listed["status"] == PACK_ON_SHELF
    assert listed["markdown_price_cents"] is None
    assert listed["advisory_markdown_price_cents"] is None
    assert listed["markdown_variant_applied"] is None
    assert listed["list_price_cents"] == 900
    assert listed["unsold_count"] == 160

    marked = validate_success(
        api.markdown_pack_lot(world["pack_lot_id"], world["chef_headers"])
    )
    assert marked["status"] == PACK_MARKED_DOWN
    assert marked["markdown_price_cents"] == 675
    assert marked["advisory_markdown_price_cents"] == 450
    assert marked["markdown_variant_applied"] == MARKDOWN_POLICY_PRORATED

    validate_success(
        api.discard_pack_lot(
            world["pack_lot_id"],
            discard_payload(DISCARD_SHELF_LIFE_EXPIRED),
            world["auditor_headers"],
        )
    )
    # The discard is a state transition of the pack lot, so the call answers with
    # the updated lot; the appended event surfaces through its nested list, which
    # "is the only place cascade-created events ever surface".
    event = validate_list(
        api.list_discard_events(world["pack_lot_id"], world["ops_headers"]),
        expected_total=1,
    )[0]
    assert event["unit_value_cents"] == 675
    assert event["discard_value_cents"] == 108000


def test_kiosk_suspension_is_shared_by_franchisor_operations_and_the_auditor(api):
    """Either role drives the same cascade; the chef who runs the kiosk drives none.

    Suspension "is available to franchisor operations and to the quality auditor,
    and drives the four-link cascade of §2.10 in full: the kiosk's plans in
    `DRAFT`, `RELEASED` or `LOCKED` move to `VOIDED` with `void_reason`
    `KIOSK_SUSPENDED` … The agreement's `active_kiosk_count` is decremented by 1."

    Design: Corner/rbac/auditor_and_ops_share_kiosk_suspension
    """
    world = base_world()
    first_plan = add_released_plan(world)
    assert first_plan["status"] == PLAN_RELEASED

    validate_error(
        api.suspend_kiosk(
            world["kiosk_id"],
            suspension_payload(suspension_reason="PEST_SIGHTING_IN_BACKROOM"),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    by_auditor = validate_success(
        api.suspend_kiosk(
            world["kiosk_id"],
            suspension_payload(suspension_reason="PEST_SIGHTING_IN_BACKROOM"),
            world["auditor_headers"],
        )
    )
    assert by_auditor["operational_state"] == KIOSK_SUSPENDED
    assert by_auditor["suspension_reason"] == "PEST_SIGHTING_IN_BACKROOM"
    assert by_auditor["sanitation_posture"] == POSTURE_CLEAR

    voided = validate_success(
        api.get_production_plan(first_plan["id"], world["ops_headers"])
    )
    assert voided["status"] == PLAN_VOIDED
    assert voided["void_reason"] == VOID_REASON_KIOSK_SUSPENDED

    emptied = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert emptied["active_kiosk_count"] == 0

    back_up = validate_success(
        api.reinstate_kiosk(world["kiosk_id"], world["ops_headers"])
    )
    assert back_up["operational_state"] == KIOSK_OPERATING
    second_plan = add_released_plan(world, production_date="2026-08-04")

    by_ops = validate_success(
        api.suspend_kiosk(
            world["kiosk_id"],
            suspension_payload(suspension_reason="PEST_SIGHTING_IN_BACKROOM"),
            world["ops_headers"],
        )
    )
    assert by_ops["operational_state"] == KIOSK_SUSPENDED
    assert by_ops["suspension_reason"] == "PEST_SIGHTING_IN_BACKROOM"
    assert by_ops["sanitation_posture"] == POSTURE_CLEAR

    voided_again = validate_success(
        api.get_production_plan(second_plan["id"], world["ops_headers"])
    )
    assert voided_again["status"] == PLAN_VOIDED
    assert voided_again["void_reason"] == VOID_REASON_KIOSK_SUSPENDED

    emptied_again = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert emptied_again["active_kiosk_count"] == 0
