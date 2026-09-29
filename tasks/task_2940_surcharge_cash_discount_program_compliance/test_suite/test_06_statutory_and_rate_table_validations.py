"""The refusals that guard a jurisdiction's cap coherence, the two prohibition flags,
the debit-exclusion precondition, and the rate table's pinning and scope rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_terminal_census,
    attest_disclosures,
    create_jurisdiction,
    decide_registration,
    effectuate_registration,
    file_cost_documentation,
    jurisdiction_payload,
    law_change_payload,
    list_items,
    list_total,
    program_payload,
    rate_rule_payload,
    read_merchant,
    read_program,
    read_terminal,
    set_clock,
    setup_active_surcharge_program,
    setup_configured_terminal,
    setup_draft_program,
    setup_merchant_with_documentation,
    setup_program_pending_registration,
    submit_registration,
    terminal_action_payload,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_AUG_31,
    CLOCK_DEC_31,
    OFFICER_TWO_USER_ID,
)
from test_helpers.fixtures import ADMIN, OFFICER_ONE, REGULATOR
from test_helpers.test_users import make_merchant_operator_headers


def test_permitting_surcharging_without_a_cap_is_refused(api):
    """PRD §3.1: "`surcharge_cap_pct` carries the statutory ceiling as a percentage: it must be greater than 0 and at most 100 with up to four decimal places, it must be supplied and non-null whenever `surcharge_permitted` is true, and it must be null whenever `surcharge_permitted` is false."
    PRD §3.1: "Either half of that coherence rule being broken is rejected with `ERR_JURISDICTION_CAP_REQUIRED`."

    Design: Corner/validations/jurisdiction_permitting_surcharge_without_a_cap_rejected
    """
    response = api_client.create_jurisdiction(
        jurisdiction_payload("AZ", state_code="NV", surcharge_cap_pct=None), ADMIN
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_CAP_REQUIRED)

    assert list_total(api_client.list_jurisdictions(ADMIN)) == 0
    assert list_total(api_client.list_jurisdictions(ADMIN, params={"state_code": "NV"})) == 0


def test_prohibiting_surcharging_while_keeping_a_cap_is_refused(api):
    """PRD §3.1: "The cap-coherence rule is re-evaluated against the post-change picture, so a change that turns surcharging on without supplying a cap, or turns it off while leaving a cap in place, is rejected with `ERR_JURISDICTION_CAP_REQUIRED` and nothing is applied."
    PRD §3.1: "Applying a law change increments `law_change_count` by exactly 1, sets `last_law_change_at` to the current logical clock, and bumps the jurisdiction's `version`."
    PRD §3.1: "A freshly registered jurisdiction begins with `law_change_count` at 0 and `last_law_change_at` null."

    Design: Corner/validations/law_change_prohibiting_surcharging_with_a_nonnull_cap_rejected
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    assert jurisdiction["law_change_count"] == 0
    assert jurisdiction["last_law_change_at"] is None

    response = api_client.apply_law_change(
        jurisdiction["id"], law_change_payload(False, surcharge_cap_pct=2.0), REGULATOR
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_CAP_REQUIRED)

    after = validate_success(api_client.get_jurisdiction(jurisdiction["id"], ADMIN))
    assert after["surcharge_permitted"] is True
    assert after["surcharge_cap_pct"] == pytest.approx(4.0, abs=0.00001)
    assert after["law_change_count"] == 0
    assert after["last_law_change_at"] is None
    assert after["version"] == jurisdiction["version"]


def test_a_surcharge_program_cannot_be_created_in_a_prohibiting_state(api):
    """PRD §3.3: "Creating a `SURCHARGE` program in a jurisdiction whose `surcharge_permitted` is false is rejected with `ERR_SURCHARGE_PROHIBITED_JURISDICTION`; creating a `CASH_DISCOUNT` program in a jurisdiction whose `cash_discount_permitted` is false is rejected with `ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION`."
    PRD §3.1: "`surcharge_permitted` says whether credit-card surcharging is lawful at all."

    Design: Corner/validations/surcharge_program_creation_in_a_prohibiting_state_rejected
    """
    ctx = setup_merchant_with_documentation("CT")
    assert ctx["jurisdiction"]["surcharge_permitted"] is False
    assert ctx["jurisdiction"]["surcharge_cap_pct"] is None

    response = api_client.create_program(
        program_payload(
            ctx["merchant"]["id"],
            ctx["jurisdiction"]["id"],
            ctx["cost_documentation"]["id"],
            "SURCHARGE",
            "BRAND_LEVEL",
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_SURCHARGE_PROHIBITED_JURISDICTION)

    assert (
        list_total(
            api_client.list_programs(ADMIN, params={"merchant_id": ctx["merchant"]["id"]})
        )
        == 0
    )


def test_a_cash_discount_program_cannot_be_created_where_the_structure_is_banned(api):
    """PRD §3.3: "Creating a `SURCHARGE` program in a jurisdiction whose `surcharge_permitted` is false is rejected with `ERR_SURCHARGE_PROHIBITED_JURISDICTION`; creating a `CASH_DISCOUNT` program in a jurisdiction whose `cash_discount_permitted` is false is rejected with `ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION`."
    PRD §3.1: "`cash_discount_permitted` says whether a cash-discount program structure is lawful."

    Design: Corner/validations/cash_discount_program_creation_in_a_prohibiting_state_rejected
    """
    ctx = setup_merchant_with_documentation("MA")
    assert ctx["jurisdiction"]["surcharge_permitted"] is True
    assert ctx["jurisdiction"]["surcharge_cap_pct"] == pytest.approx(3.5, abs=0.00001)
    assert ctx["jurisdiction"]["cash_discount_permitted"] is False

    response = api_client.create_program(
        program_payload(
            ctx["merchant"]["id"],
            ctx["jurisdiction"]["id"],
            ctx["cost_documentation"]["id"],
            "CASH_DISCOUNT",
            "BRAND_LEVEL",
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION)

    assert (
        list_total(
            api_client.list_programs(ADMIN, params={"merchant_id": ctx["merchant"]["id"]})
        )
        == 0
    )


def test_a_terminal_without_debit_exclusion_cannot_enforce_a_surcharge_program(api):
    """PRD §3.8: "Three cross-entity conditions are checked against the bound program: its `status` must be `ACTIVE`, else `ERR_INVALID_PROGRAM_STATE`; its `disclosure_ready` must be true, else `ERR_DISCLOSURE_INCOMPLETE`; and if its `program_type` is `SURCHARGE`, the terminal's `debit_exclusion_enabled` must be true, else `ERR_DEBIT_EXCLUSION_NOT_ENABLED`."
    PRD §3.8: "A cash-discount terminal is exempt from the debit-exclusion requirement, because a cash discount is never applied as a card fee in the first place."

    Design: Corner/validations/terminal_enforcement_without_debit_exclusion_rejected
    """
    ctx = setup_active_surcharge_program(jurisdiction_profile="AZ")
    merchant_id = ctx["merchant"]["id"]
    terminal = setup_configured_terminal(
        merchant_id, ctx["program"]["id"], "TRM-AZ-0001", debit_exclusion_enabled=False
    )
    assert terminal["state"] == "CONFIGURED"

    response = api_client.terminal_state_action(
        terminal["id"],
        terminal_action_payload("ENFORCE"),
        make_merchant_operator_headers(merchant_id),
    )
    validate_error(response, ApiErrorId.ERR_DEBIT_EXCLUSION_NOT_ENABLED)

    after = read_terminal(terminal["id"])
    assert after["state"] == "CONFIGURED"
    assert after["debit_exclusion_enabled"] is False
    assert_terminal_census(read_merchant(merchant_id), 0)


def test_a_rate_rule_on_superseded_documentation_is_refused(api):
    """PRD §3.2: "The merchant's existing document in state `ACTIVE`, if there is one, moves to `SUPERSEDED` with `superseded_at` stamped from the logical clock and its own `version` bumped; the merchant's `active_cost_documentation_id` is repointed at the new document; and the merchant's `version` is bumped by 1."
    PRD §3.2: "The consequence for programs is sharp: any `SurchargeProgram` still pinned to the document that just became `SUPERSEDED` can no longer file rate rules or activate, failing with `ERR_COST_DOCUMENTATION_STALE`, until an officer re-pins it."
    PRD §3.4: "Filing carries the `expected_program_version` guard of §2.7 and is refused on a program whose pinned documentation has been superseded, with `ERR_COST_DOCUMENTATION_STALE`, or on a program that has been withdrawn, with `ERR_INVALID_PROGRAM_STATE`."

    Design: Corner/validations/rate_rule_on_a_superseded_cost_documentation_rejected
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]
    doc_a_id = ctx["cost_documentation"]["id"]
    newer = file_cost_documentation(ctx["merchant"]["id"], profile="docB")
    assert newer["state"] == "ACTIVE"

    response = api_client.create_rate_rule(
        program_id,
        rate_rule_payload(ctx["program"]["version"], rate_pct=2.19),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_COST_DOCUMENTATION_STALE)

    assert (
        validate_success(api_client.get_cost_documentation(doc_a_id, ADMIN))["state"]
        == "SUPERSEDED"
    )
    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id}))
        == 0
    )
    program = read_program(program_id)
    assert program["cost_documentation_id"] == doc_a_id
    assert program["status"] == "DRAFT"


def test_a_product_level_program_cannot_file_the_catch_all_tier(api):
    """PRD §3.4: "`product_tier` is one of `ALL`, `CONSUMER_CREDIT`, `COMMERCIAL_CREDIT`, or `REWARDS_CREDIT`, and it must agree with the program's `consistency_scope` in both directions: a rule filed under a `BRAND_LEVEL` program must carry `ALL`, and a rule filed under a `PRODUCT_LEVEL` program must carry something other than `ALL`."
    PRD §3.4: "Either direction being violated is rejected with `ERR_PRODUCT_TIER_SCOPE_VIOLATION`."
    PRD §3.3: "`PRODUCT_LEVEL` means the merchant prices named credit product tiers separately and every rate rule must name a specific tier rather than `ALL`."

    Design: Corner/validations/product_tier_all_on_a_product_level_program_rejected
    """
    ctx = setup_draft_program(consistency_scope="PRODUCT_LEVEL", with_rate_rule=False)
    program_id = ctx["program"]["id"]
    version_before = ctx["program"]["version"]

    response = api_client.create_rate_rule(
        program_id,
        rate_rule_payload(version_before, product_tier="ALL", rate_pct=2.19),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_PRODUCT_TIER_SCOPE_VIOLATION)

    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id}))
        == 0
    )
    assert read_program(program_id)["version"] == version_before


def test_a_brand_level_program_cannot_file_a_specific_tier(api):
    """PRD §3.4: "Either direction being violated is rejected with `ERR_PRODUCT_TIER_SCOPE_VIOLATION`."
    PRD §3.3: "`BRAND_LEVEL` means the merchant prices a whole card brand identically and every rate rule must carry `product_tier` of `ALL`."

    Design: Corner/validations/specific_product_tier_on_a_brand_level_program_rejected
    """
    ctx = setup_draft_program(consistency_scope="BRAND_LEVEL", with_rate_rule=False)
    program_id = ctx["program"]["id"]
    assert ctx["program"]["consistency_scope"] == "BRAND_LEVEL"

    response = api_client.create_rate_rule(
        program_id,
        rate_rule_payload(
            ctx["program"]["version"], product_tier="CONSUMER_CREDIT", rate_pct=1.5
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_PRODUCT_TIER_SCOPE_VIOLATION)

    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id}))
        == 0
    )


def test_activation_needs_a_rate_rule_for_every_effective_network(api):
    """PRD §3.7: "Its preconditions are: the jurisdiction's `surcharge_permitted` is true, else `ERR_SURCHARGE_PROHIBITED_JURISDICTION`; the activating officer's `X-User-ID` differs from `attested_by_user_id` of every disclosure artifact of the program, else `ERR_SEGREGATION_OF_DUTIES`; the pinned `CostDocumentation` is still in state `ACTIVE`, else `ERR_COST_DOCUMENTATION_STALE`; at least one registration of the program is in state `EFFECTIVE`, else `ERR_REGISTRATION_NOT_EFFECTIVE`; every network that holds an `EFFECTIVE` registration has a rate rule for that same brand whose closed interval contains the logical clock, else `ERR_BRAND_CONSISTENCY_VIOLATION`; readiness holds for the surcharge required set, else `ERR_DISCLOSURE_INCOMPLETE`; and at least one rate rule of the program is in effect at the clock, else `ERR_NO_RATE_RULE_IN_EFFECT`."
    PRD §3.7: "Registration effectiveness and brand coverage are both required here and both absent from the cash-discount arm."

    Design: Corner/validations/activation_without_a_rate_rule_for_every_effective_network_rejected
    """
    # The program's only rate rule prices MASTERCARD, while the registration that
    # becomes EFFECTIVE was submitted to VISA. PRD §3.5 admits a registration
    # submission only from a program in DRAFT, so the program holds exactly one
    # registration and the uncovered network is reached through the brand mismatch.
    ctx = setup_program_pending_registration(
        jurisdiction_profile="AZ", network="VISA", brand="MASTERCARD"
    )
    program_id = ctx["program"]["id"]
    decide_registration(ctx["registration"]["id"], "ACKNOWLEDGE")
    set_clock(CLOCK_AUG_31)
    effectuate_registration(ctx["registration"]["id"])

    response = api_client.activate_program(program_id, OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_BRAND_CONSISTENCY_VIOLATION)

    program = read_program(program_id)
    assert program["status"] == "PENDING_REGISTRATION"
    assert program["activated_at"] is None
    effective = list_items(
        api_client.list_network_registrations(
            ADMIN, params={"program_id": program_id, "state": "EFFECTIVE"}
        )
    )
    assert len(effective) == 1
    assert effective[0]["network"] == "VISA"
    rules = list_items(
        api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id})
    )
    assert len(rules) == 1
    assert rules[0]["brand"] == "MASTERCARD"


def test_a_cash_discount_activation_needs_the_posted_price_list(api):
    """PRD §3.7: "Its preconditions are: the jurisdiction's `cash_discount_permitted` is true, else `ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION`; the activating officer's `X-User-ID` differs from `attested_by_user_id` of every disclosure artifact of the program, else `ERR_SEGREGATION_OF_DUTIES`; the pinned `CostDocumentation` is still in state `ACTIVE`, else `ERR_COST_DOCUMENTATION_STALE`; readiness holds for the cash-discount required set, else `ERR_DISCLOSURE_INCOMPLETE`; when the jurisdiction's `price_posting_required` is true, a `PRICE_LIST_POSTING` artifact is `ATTESTED` with the clock inside its window, else `ERR_PRICE_POSTING_REQUIRED`; and at least one rate rule of the program has a closed effectivity interval containing the logical clock, else `ERR_NO_RATE_RULE_IN_EFFECT`."
    PRD §3.6: "`PRICE_LIST_POSTING` is deliberately never a member of the required set, because the posted dual-price list is policed by its own independent rule at step 33 of §2.9; a program that has attested its signage but not its price list must fail with `ERR_PRICE_POSTING_REQUIRED` rather than be masked by `ERR_DISCLOSURE_INCOMPLETE`."
    PRD §3.6: "For a `CASH_DISCOUNT` program: if `disclosure_signage_required` is true, only `POS_SIGNAGE` is required."

    Design: Corner/validations/cash_discount_activation_without_the_price_list_posting_rejected
    """
    ctx = setup_draft_program(jurisdiction_profile="NY", program_type="CASH_DISCOUNT")
    program_id = ctx["program"]["id"]
    attest_disclosures(
        program_id,
        ctx["merchant"]["id"],
        ["POS_SIGNAGE"],
        CLOCK_AUG_01,
        CLOCK_DEC_31,
        OFFICER_TWO_USER_ID,
    )
    set_clock(CLOCK_AUG_31)
    assert read_program(program_id)["disclosure_ready"] is True

    response = api_client.activate_program(program_id, OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_PRICE_POSTING_REQUIRED)

    program = read_program(program_id)
    assert program["status"] == "DRAFT"
    assert program["disclosure_ready"] is True
    assert program["activated_at"] is None

    attested = list_items(
        api_client.list_disclosure_artifacts(
            ADMIN, params={"program_id": program_id, "state": "ATTESTED"}
        )
    )
    assert len(attested) == 1
    assert attested[0]["artifact_type"] == "POS_SIGNAGE"
