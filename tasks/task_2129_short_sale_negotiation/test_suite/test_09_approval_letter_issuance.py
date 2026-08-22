"""Issuing the approval letter: the readiness gates, the fiscal ceilings, and the
side effects a successful issuance carries."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_approval_letter,
    case_version,
    issue_approval_letter_payload,
    setup_full_approval_chain,
    setup_ready_for_issuance,
    validate_error,
    validate_paginated,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
AGENT = TEST_USERS["listing_agent_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]


def test_a_case_with_no_liens_and_no_mi_claim_may_be_approved(api):
    """PRD §3.9: "Every junior lien on the case must be `APPROVED` — a case with no junior
    liens at all satisfies this vacuously — or `ERR_JUNIOR_LIEN_UNRESOLVED`."
    PRD §3.9: "The case's MI claim, if one exists, must be `APPROVED` or `NOT_REQUIRED`;
    a `PENDING` or `DECLINED` claim yields `ERR_MI_APPROVAL_PENDING`, while a case with no
    MI claim at all passes."
    PRD §3.9: "A successful issuance stamps `issued_by_user_id`, stamps `issued_at` with
    the current logical-clock instant, leaves `supersedes_approval_id` null because this
    is an original rather than a successor, starts `cumulative_extension_days_used` at 0,
    and computes `closing_deadline` as `issued_at` plus **45 calendar days**, preserving
    the time of day exactly."

    Design: Difficulty/boundary_precision_check/zero_junior_liens_and_absent_mi_claim_permit_issuance
    """
    scenario = setup_ready_for_issuance(lien_stage=None, mi_outcome=None)
    assert scenario["case"]["minimum_acceptable_net_cents"] == 22_176_000

    letter = validate_success(
        api.issue_approval_letter(
            scenario["case"]["id"],
            issue_approval_letter_payload(
                scenario["offer"]["id"],
                case_version(scenario["case"]["id"]),
                approved_net_proceeds_cents=22_176_000,
            ),
            ANALYST,
        ),
        201,
    )

    assert letter["status"] == "ACTIVE"
    assert letter["approved_net_proceeds_cents"] == 22_176_000
    assert letter["supersedes_approval_id"] is None
    assert letter["cumulative_extension_days_used"] == 0
    # Issued 2026-08-24, plus 45 calendar days with the time of day preserved.
    assert letter["closing_deadline"].startswith("2026-10-08T00:00:00")
    assert_approval_letter(letter)


def test_vacuous_readiness_leaves_the_ledger_and_credit_at_zero(api):
    """PRD §3.9: "The letter is born `ACTIVE`. Its issuance moves the approved offer to
    the terminal `ACCEPTED`, carries the case's negotiation dimension from
    `OFFER_UNDER_REVIEW` to `APPROVAL_ACTIVE`, and increments the case's `version`."
    PRD §3.8: "A final sheet carries the carrier's `required_contribution_cents` when the
    case has an MI claim in `APPROVED` status, and 0 in every other situation — no claim
    at all, a pending one, a declined one, or one declared not required."

    Design: Difficulty/boundary_precision_check/zero_junior_liens_and_absent_mi_claim_permit_issuance
    """
    scenario = setup_ready_for_issuance(lien_stage=None, mi_outcome=None)

    assert scenario["case"]["junior_lien_count"] == 0
    assert scenario["case"]["junior_contribution_total_cents"] == 0
    assert scenario["net_sheet"]["mi_contribution_credit_cents"] == 0
    assert scenario["net_sheet"]["net_proceeds_cents"] == 21_972_539

    validate_success(
        api.issue_approval_letter(
            scenario["case"]["id"],
            issue_approval_letter_payload(
                scenario["offer"]["id"],
                case_version(scenario["case"]["id"]),
                approved_net_proceeds_cents=22_176_000,
            ),
            ANALYST,
        ),
        201,
    )

    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer_after["status"] == "ACCEPTED"

    case_after = validate_success(api.get_case(scenario["case"]["id"], ANALYST), 200)
    assert case_after["negotiation_status"] == "APPROVAL_ACTIVE"
    assert case_after["minimum_acceptable_net_cents"] == 22_176_000


def test_a_pending_mi_claim_blocks_issuance(api):
    """PRD §3.9: "The case's MI claim, if one exists, must be `APPROVED` or
    `NOT_REQUIRED`; a `PENDING` or `DECLINED` claim yields `ERR_MI_APPROVAL_PENDING`,
    while a case with no MI claim at all passes."
    PRD §3.7: "The claim starts `PENDING` with `required_contribution_cents` at 0,
    `contribution_form` at `NONE` and `decided_by_user_id` null — and a pending claim
    blocks approval-letter issuance outright."

    Design: Difficulty/cross_entity_state_dependency/approval_issuance_gated_on_mi_claim_decision_state
    """
    scenario = setup_ready_for_issuance(mi_outcome="PENDING")
    assert scenario["mi_claim"]["status"] == "PENDING"

    validate_error(
        api.issue_approval_letter(
            scenario["case"]["id"],
            issue_approval_letter_payload(
                scenario["offer"]["id"],
                case_version(scenario["case"]["id"]),
                approved_net_proceeds_cents=22_176_000,
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_MI_APPROVAL_PENDING.value,
    )

    claims = validate_success(api.list_case_mi_claims(scenario["case"]["id"], NEG), 200)
    assert claims[0]["status"] == "PENDING"
    assert claims[0]["required_contribution_cents"] == 0


def test_the_blocked_issuance_leaves_the_file_where_it_stood(api):
    """PRD §3.9: "The case's MI claim, if one exists, must be `APPROVED` or
    `NOT_REQUIRED`; a `PENDING` or `DECLINED` claim yields `ERR_MI_APPROVAL_PENDING`,
    while a case with no MI claim at all passes."
    PRD §3.8: "A final sheet carries the carrier's `required_contribution_cents` when the
    case has an MI claim in `APPROVED` status, and 0 in every other situation — no claim
    at all, a pending one, a declined one, or one declared not required."

    Design: Difficulty/cross_entity_state_dependency/approval_issuance_gated_on_mi_claim_decision_state
    """
    scenario = setup_ready_for_issuance(mi_outcome="PENDING")
    case_id = scenario["case"]["id"]

    assert scenario["case"]["minimum_acceptable_net_cents"] == 22_176_000
    assert scenario["net_sheet"]["mi_contribution_credit_cents"] == 0
    assert scenario["net_sheet"]["net_proceeds_cents"] == 21_372_539

    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=22_176_000,
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_MI_APPROVAL_PENDING.value,
    )

    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0

    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer_after["status"] == "SUBMITTED"
    case_after = validate_success(api.get_case(case_id, ANALYST), 200)
    assert case_after["negotiation_status"] == "OFFER_UNDER_REVIEW"


def test_unresolved_junior_lien_is_reported_ahead_of_the_net_floor(api):
    """PRD §2.6: "Read that ladder with approval-letter issuance in mind, since it is the
    operation most heavily guarded: eleven distinct rungs can refuse it, and they are
    evaluated in exactly the order listed — concurrency before state, state before
    deficiency eligibility, deficiency eligibility before the readiness of the valuation,
    the package, the net sheet, the liens and the MI claim, and all of those before the
    commission cap and the net floor."
    PRD §3.9: "Every junior lien on the case must be `APPROVED` — a case with no junior
    liens at all satisfies this vacuously — or `ERR_JUNIOR_LIEN_UNRESOLVED`."

    Design: Difficulty/priority_pair_validation_conflict/junior_lien_unresolved_beats_net_below_minimum_on_issuance
    """
    scenario = setup_ready_for_issuance(lien_stage="NEGOTIATING")
    case_id = scenario["case"]["id"]
    assert scenario["case"]["minimum_acceptable_net_cents"] == 21_426_000
    assert scenario["net_sheet"]["net_proceeds_cents"] == 22_722_539
    assert scenario["net_sheet"]["status"] == "CURRENT"

    # 20_000_000 also sits below the 21_426_000 floor, but the lien rung is higher.
    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=20_000_000, conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_JUNIOR_LIEN_UNRESOLVED.value,
    )

    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0
    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer_after["status"] == "SUBMITTED"


def test_the_net_floor_fires_once_every_lien_is_approved(api):
    """PRD §3.9: "And finally the `approved_net_proceeds_cents`, which may be 0 or more,
    must be **at least** the case's `minimum_acceptable_net_cents`; a letter below the
    floor is refused with `ERR_NET_BELOW_MINIMUM`, and a letter exactly at the floor is
    fine."
    PRD §3.9: "Every junior lien on the case must be `APPROVED` — a case with no junior
    liens at all satisfies this vacuously — or `ERR_JUNIOR_LIEN_UNRESOLVED`."

    Design: Difficulty/priority_pair_validation_conflict/junior_lien_unresolved_beats_net_below_minimum_on_issuance
    """
    scenario = setup_ready_for_issuance(lien_stage="APPROVED")
    case_id = scenario["case"]["id"]
    assert scenario["case"]["minimum_acceptable_net_cents"] == 21_426_000

    # Identical below-floor net, but now the lien rung passes and the floor bites.
    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=20_000_000, conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_NET_BELOW_MINIMUM.value,
    )

    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0
    case_after = validate_success(api.get_case(case_id, ANALYST), 200)
    assert case_after["negotiation_status"] == "OFFER_UNDER_REVIEW"


def test_commission_cap_above_the_servicer_ceiling_is_refused(api):
    """PRD §3.9: "The `commission_cap_pct` must be strictly above 0 and no greater than
    the servicer's own cap of `0.055`, on pain of `ERR_COMMISSION_CAP_EXCEEDED`."

    Design: Corner/validations/commission_cap_above_servicer_cap_rejected
    """
    scenario = setup_ready_for_issuance()
    case_id = scenario["case"]["id"]

    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                commission_cap_pct=0.06, conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_COMMISSION_CAP_EXCEEDED.value,
    )

    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0
    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer_after["status"] == "SUBMITTED"
    case_after = validate_success(api.get_case(case_id, ANALYST), 200)
    assert case_after["negotiation_status"] == "OFFER_UNDER_REVIEW"


def test_waived_deficiency_on_a_portfolio_case_is_refused_first(api):
    """PRD §3.9: "The `deficiency_waiver` may read `WAIVED` only on a case whose
    `deficiency_waiver_permitted` is true — that is, a `GSE` or `FHA` file — and a
    `WAIVED` letter on a `PORTFOLIO` case is refused with
    `ERR_DEFICIENCY_WAIVER_NOT_PERMITTED`; `RESERVED` and `PROMISSORY_NOTE` are always
    available."
    PRD §2.6: "Read that ladder with approval-letter issuance in mind, since it is the
    operation most heavily guarded: eleven distinct rungs can refuse it, and they are
    evaluated in exactly the order listed — concurrency before state, state before
    deficiency eligibility, deficiency eligibility before the readiness of the valuation,
    the package, the net sheet, the liens and the MI claim, and all of those before the
    commission cap and the net floor."

    Design: Corner/validations/deficiency_waiver_not_permitted_for_portfolio_case
    """
    scenario = setup_ready_for_issuance(
        case_overrides={
            "property_address": "33 Ivyhill Ct, Reno NV",
            "investor_type": "PORTFOLIO",
            "unpaid_principal_balance_cents": 42_000_000,
        },
        with_valuation=False,
        lien_stage=None,
        mi_outcome=None,
        net_sheet_variant=None,
    )
    case_id = scenario["case"]["id"]
    assert scenario["case"]["deficiency_waiver_permitted"] is False

    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=20_000_000,
                deficiency_waiver="WAIVED", conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_DEFICIENCY_WAIVER_NOT_PERMITTED.value,
    )

    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0


def test_a_case_without_a_controlling_valuation_cannot_be_approved(api):
    """PRD §3.9: "The case must have a controlling valuation, so that its
    `final_value_cents` and `minimum_acceptable_net_cents` are not null, or the issuance
    fails with `ERR_CONTROLLING_VALUATION_MISSING`."

    Design: Corner/validations/controlling_valuation_missing_blocks_issuance
    """
    scenario = setup_ready_for_issuance(
        with_valuation=False, lien_stage=None, mi_outcome=None, net_sheet_variant=None
    )
    case_id = scenario["case"]["id"]

    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=22_000_000, conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_CONTROLLING_VALUATION_MISSING.value,
    )

    case_after = validate_success(api.get_case(case_id, ANALYST), 200)
    assert case_after["final_value_cents"] is None
    assert case_after["minimum_acceptable_net_cents"] is None
    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0


def test_a_staled_final_sheet_cannot_support_a_letter(api):
    """PRD §3.9: "The named offer must have a settlement sheet of the final variant whose
    status is `CURRENT`, or `ERR_STALE_NET_SHEET`."
    PRD §3.8: "Neither a `SUPERSEDED` nor a `STALE` final sheet can support an approval
    letter."

    Design: Corner/validations/stale_final_net_sheet_blocks_issuance
    """
    scenario = setup_ready_for_issuance(
        lien_stage="APPROVED", lien_response_after_net_sheet=True
    )
    case_id = scenario["case"]["id"]
    assert scenario["net_sheet"]["status"] == "STALE"

    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=22_000_000, conditions=[],
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_STALE_NET_SHEET.value,
    )

    assert scenario["lien"]["status"] == "APPROVED"
    case_after = validate_success(api.get_case(case_id, ANALYST), 200)
    assert case_after["junior_contribution_total_cents"] == 600_000
    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0


def test_approval_letters_can_be_narrowed_by_their_foreign_keys(api):
    """PRD §2.3: "The system-wide approval-letter list may be narrowed by `case_id`, by
    `offer_id`, by `supersedes_approval_id`, and by `status`."
    PRD §3.9: "A successful issuance stamps `issued_by_user_id`, stamps `issued_at` with
    the current logical-clock instant, leaves `supersedes_approval_id` null because this
    is an original rather than a successor, starts `cumulative_extension_days_used` at 0,
    and computes `closing_deadline` as `issued_at` plus **45 calendar days**, preserving
    the time of day exactly."

    Design: Corner/endpoints/approval_letters_filtered_list_by_case_id
    """
    scenario = setup_full_approval_chain()
    letter = scenario["letter"]

    rows, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": scenario["case"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == letter["id"]

    _, by_offer = validate_paginated(
        api.list_approval_letters(ANALYST, params={"offer_id": scenario["offer"]["id"]})
    )
    assert by_offer["total_count"] == 1

    _, by_successor = validate_paginated(
        api.list_approval_letters(
            ANALYST, params={"supersedes_approval_id": letter["id"]}
        )
    )
    assert by_successor["total_count"] == 0, "an original letter has no successor yet"


def test_a_listing_agent_may_not_issue_an_approval_letter(api):
    """PRD §2.1: "Once the headers are accepted, the role is checked against the set of
    roles the addressed endpoint admits; a role outside that set yields `ERR_UNAUTHORIZED`
    and HTTP 403."
    PRD §3.9: "A `ServicerAnalyst` issues one against a case, naming in the body the
    `offer_id` of the offer being approved, the `approved_net_proceeds_cents` the servicer
    commits to accept, the `commission_cap_pct` ceiling the letter allows, the
    `seller_relocation_incentive_cents` the letter grants the seller at closing, the
    `deficiency_waiver` treatment, an optional array of free-text `conditions` attached to
    closing, and the `expected_case_version` §2.8 requires."

    Design: Corner/rbac/listing_agent_cannot_issue_approval_letter
    """
    scenario = setup_ready_for_issuance(
        with_valuation=False, lien_stage=None, mi_outcome=None, net_sheet_variant=None
    )
    case_id = scenario["case"]["id"]

    validate_error(
        api.issue_approval_letter(
            case_id,
            issue_approval_letter_payload(
                scenario["offer"]["id"], case_version(case_id),
                approved_net_proceeds_cents=22_000_000, conditions=[],
            ),
            AGENT,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    _, meta = validate_paginated(
        api.list_approval_letters(ANALYST, params={"case_id": case_id})
    )
    assert meta["total_count"] == 0
