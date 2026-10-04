"""Catalog, lender and program lifecycle errors plus the lender-ban cascade."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.factories import create_lender_program_payload, create_targeting_criterion_payload
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    LENDER_OPS,
    PLATFORM_ADMIN,
    create_active_catalog_item,
    create_active_lender,
    create_active_program,
    create_active_score_tier,
    create_decision,
    read_decision,
    reset_clock,
    setup_catalog_scenario,
    setup_monitored,
)


def test_duplicate_program_code_is_rejected_at_activation(api):
    """PRD §3.5: "It starts in `DRAFT` and is activated by a `PlatformAdmin`, which
    requires the sponsoring lender to be `ACTIVE` — otherwise `ERR_LENDER_NOT_ACTIVE` —
    and the `program_code` to be unique — otherwise `ERR_PROGRAM_CODE_DUPLICATE`."

    Design: Corner/errors/duplicate_program_code_is_rejected
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    create_active_program(
        lender_id=lender["id"], item_id=item["id"], program_code="NS-LOAN-01", api=api
    )

    duplicate = validate_success(
        api.create_lender_program(
            create_lender_program_payload(
                lender["id"], item["id"], program_name="Duplicate Code Loan",
                program_code="NS-LOAN-01",
            ),
            PLATFORM_ADMIN,
        ),
        201,
    )
    validate_error(
        api.activate_lender_program(duplicate["id"], PLATFORM_ADMIN),
        ApiErrorId.ERR_PROGRAM_CODE_DUPLICATE, 409,
    )

    active = validate_success(
        api.list_lender_programs(PLATFORM_ADMIN, params={"status": "ACTIVE"}), 200
    )
    assert [p["program_code"] for p in active] == ["NS-LOAN-01"]


def test_lender_cannot_be_offboarded_while_sponsoring_an_active_program(api):
    """PRD §3.5: "Offboarding moves it to `OFFBOARDED` and is refused while any
    `ACTIVE` program is still sponsored by it, failing with
    `ERR_LENDER_HAS_ACTIVE_PROGRAM`."

    Design: Corner/errors/lender_cannot_be_offboarded_while_sponsoring_an_active_program
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    program = create_active_program(lender_id=lender["id"], item_id=item["id"], api=api)

    validate_error(
        api.offboard_lender(lender["id"], PLATFORM_ADMIN),
        ApiErrorId.ERR_LENDER_HAS_ACTIVE_PROGRAM, 409,
    )
    assert validate_success(
        api.get_lender(lender["id"], PLATFORM_ADMIN), 200
    )["status"] == "ACTIVE"

    validate_success(api.pause_lender_program(program["id"], COMPLIANCE_OFFICER), 200)
    validate_success(api.offboard_lender(lender["id"], PLATFORM_ADMIN), 200)
    assert validate_success(
        api.get_lender(lender["id"], PLATFORM_ADMIN), 200
    )["status"] == "OFFBOARDED"


def test_catalog_item_cannot_be_retired_while_a_program_references_it(api):
    """PRD §3.5: "Retiring an active item moves it to `RETIRED` and is refused while any
    `ACTIVE` `LenderProgram` still references it, failing with
    `ERR_ITEM_HAS_ACTIVE_PROGRAM`."

    Design: Corner/errors/catalog_item_cannot_be_retired_while_a_program_references_it
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    create_active_program(lender_id=lender["id"], item_id=item["id"], api=api)

    validate_error(
        api.retire_catalog_item(item["id"], PLATFORM_ADMIN),
        ApiErrorId.ERR_ITEM_HAS_ACTIVE_PROGRAM, 409,
    )
    assert validate_success(
        api.get_catalog_item(item["id"], PLATFORM_ADMIN), 200
    )["status"] == "ACTIVE"


def test_banning_a_lender_cascades_three_hops(api):
    """PRD §3.5: "The `BANNED` determination is the one with a blast radius: every
    `ACTIVE` program sponsored by that lender is paused, and each paused program in turn
    cascades its own eligible decisions to `INELIGIBLE`."
    PRD §3.5: "pausing cascades every decision pinned to that program whose status is
    `ELIGIBLE` or `PREQUALIFIED` to `INELIGIBLE`, stamping the reason `PROGRAM_PAUSED`
    and nulling the modeled odds."

    Design: Difficulty/transitive_cascade/lender_ban_cascade_depth_three
    """
    reset_clock(api=api)
    create_active_score_tier(api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    program = create_active_program(lender_id=lender["id"], item_id=item["id"], api=api)
    validate_success(
        api.create_targeting_criterion(
            program["id"],
            create_targeting_criterion_payload(
                criterion_field="UTILIZATION_PCT", operator="LTE", criterion_value="50",
                is_hard_requirement=True,
            ),
            LENDER_OPS,
        ),
        201,
    )
    consumer = setup_monitored(api=api, email="cascade@example.com", bureau_pin="5001")["consumer"]
    decision = create_decision(consumer["id"], program["id"], api=api)
    assert decision["decision_status"] == "ELIGIBLE"

    validate_success(
        api.set_lender_compliance_status(
            lender["id"], {"compliance_status": "BANNED"}, COMPLIANCE_OFFICER
        ),
        200,
    )

    lender_after = validate_success(api.get_lender(lender["id"], PLATFORM_ADMIN), 200)
    assert lender_after["compliance_status"] == "BANNED"
    assert lender_after["status"] == "ACTIVE", "hop 1 does not touch lender status"

    assert validate_success(
        api.get_lender_program(program["id"], PLATFORM_ADMIN), 200
    )["status"] == "PAUSED"

    decision_after = read_decision(decision["id"], api=api)
    assert decision_after["decision_status"] == "INELIGIBLE"
    assert decision_after["reason"] == "PROGRAM_PAUSED"
    assert decision_after["modeled_odds_pct"] is None

    assert validate_success(
        api.list_referrals(PLATFORM_ADMIN, params={"consumer_id": consumer["id"]}), 200
    ) == []


def test_pausing_a_program_cascades_its_open_decisions(api):
    """PRD §3.5: "pausing cascades every decision pinned to that program whose status is
    `ELIGIBLE` or `PREQUALIFIED` to `INELIGIBLE`, stamping the reason `PROGRAM_PAUSED`
    and nulling the modeled odds."

    Design: Difficulty/transitive_cascade/lender_ban_cascade_depth_three
    """
    ctx = setup_catalog_scenario(api=api)
    consumer = setup_monitored(api=api, email="pause@example.com", bureau_pin="5002")["consumer"]
    decision = create_decision(consumer["id"], ctx["program"]["id"], api=api)
    assert decision["decision_status"] == "ELIGIBLE"

    validate_success(
        api.pause_lender_program(ctx["program"]["id"], COMPLIANCE_OFFICER), 200
    )
    assert validate_success(
        api.get_lender_program(ctx["program"]["id"], PLATFORM_ADMIN), 200
    )["status"] == "PAUSED"

    decision_after = read_decision(decision["id"], api=api)
    assert decision_after["decision_status"] == "INELIGIBLE"
    assert decision_after["reason"] == "PROGRAM_PAUSED"
    assert decision_after["modeled_odds_pct"] is None


def test_resuming_a_paused_program_does_not_restore_the_decision(api):
    """PRD §3.5: "Resuming a paused program returns it to `ACTIVE` but again requires
    the sponsoring lender to still be `ACTIVE`."

    Design: Difficulty/transitive_cascade/lender_ban_cascade_depth_three
    """
    ctx = setup_catalog_scenario(api=api)
    consumer = setup_monitored(api=api, email="resume@example.com", bureau_pin="5003")["consumer"]
    decision = create_decision(consumer["id"], ctx["program"]["id"], api=api)
    validate_success(api.pause_lender_program(ctx["program"]["id"], COMPLIANCE_OFFICER), 200)
    validate_success(api.resume_lender_program(ctx["program"]["id"], COMPLIANCE_OFFICER), 200)
    assert validate_success(
        api.get_lender_program(ctx["program"]["id"], PLATFORM_ADMIN), 200
    )["status"] == "ACTIVE"

    # The cascade that already fired is not undone by the resume.
    assert read_decision(decision["id"], api=api)["decision_status"] == "INELIGIBLE"