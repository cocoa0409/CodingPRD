"""Authorization corners: shared writes, the two refinements and segregation of duties."""

from test_helpers import (
    BOARD,
    COMPLIANCE,
    OFFICER,
    PUBLIC,
    STEWARD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    CycleStatus,
    DataSourceType,
    EvalStatus,
    EvalType,
    FundingState,
    IndicatorDomain,
    PostingStatus,
    Posture,
    ReportStatus,
    SignatorySide,
    SignatureState,
    Subgroup,
    ValuationBasis,
    add_agreement,
    add_evaluation,
    add_indicator,
    add_partner_party,
    advance_to,
    assert_close,
    build_scenario,
    create_cycle,
    make_compliance_headers,
    make_partner_representative_headers,
    open_report,
    post_charge_based,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_indicator_registration_is_shared_while_its_observations_are_not(api):
    """PRD §4: "| POST | `/health-indicators` | Registers a health indicator on a cycle
    in `DATA_COLLECTION`, with the benchmark rate its community rate is measured against.
    | `CommunityBenefitOfficer`, `DataSteward` |"

    PRD §3.2: "Separately, `evidence_count` is the total number of active observations on
    the indicator, counting the `OVERALL` rows as well as the subgroup rows."

    Design: Corner/rbac/shared_operations_open_to_both_owners_while_exclusive_ones_stay_closed
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    officers_own = add_indicator(api, cycle["id"], name=C.INDICATOR_NAME)

    # The steward registers an indicator exactly as the officer did.
    stewards_own = validate_success(
        api.create_indicator(
            F.indicator_payload(
                cycle["id"],
                domain=IndicatorDomain.ACCESS_TO_CARE,
                name="Uninsured adult rate",
                benchmark_value=8.0,
            ),
            headers=STEWARD,
        ),
        201,
    )

    validate_success(
        api.create_data_point(
            stewards_own["id"],
            F.data_point_payload(
                population_subgroup=Subgroup.OVERALL,
                source_type=DataSourceType.PUBLIC_DATASET,
                value=14.0,
                collected_on=C.COLLECTED_ON,
            ),
            headers=STEWARD,
        ),
        201,
    )
    evidenced = validate_success(api.get_indicator(stewards_own["id"], headers=STEWARD))
    assert evidenced["evidence_count"] == 1
    assert evidenced["subgroup_count"] == 0
    assert_close(evidenced["latest_overall_value"], 14.0, "latest_overall_value")

    # The steward's read surface covers indicators the officer registered.
    read_back = validate_success(api.get_indicator(officers_own["id"], headers=STEWARD))
    assert read_back["id"] == officers_own["id"]

    rows, meta = validate_paginated(api.list_indicators(cycle_id=cycle["id"]))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {officers_own["id"], stewards_own["id"]}


def test_the_exclusive_writes_refuse_every_role_outside_their_own_list(api):
    """PRD §4: "Authentication and authorization for every row are as described in §2.1:
    a missing or unparseable `X-User-ID` or `X-User-Role` is `ERR_UNAUTHENTICATED` with
    HTTP 401, and a role outside the row's authorized set is `ERR_UNAUTHORIZED` with HTTP
    403."

    PRD §2.1: "`CommunityBenefitOfficer` — runs the assessment cycle end to end:
    registering indicators, gathering community input, prioritizing needs, drafting
    strategies and objectives, negotiating partnerships, committing resources, opening the
    expense report, posting expenses, and drafting and publishing progress evaluations.
    This role cannot certify indicator observations, cannot adopt the assessment, and
    cannot lock or file the community benefit report."

    Design: Corner/rbac/shared_operations_open_to_both_owners_while_exclusive_ones_stay_closed
    """
    sc = build_scenario(api, stage="INDICATOR")
    partner = add_partner_party(api, name="Northside Housing Trust")

    # Opening a cycle belongs to the officer alone.
    for headers in (STEWARD, BOARD, COMPLIANCE, PUBLIC):
        validate_error(
            api.create_cycle(F.cycle_payload(fiscal_year=2028), headers=headers),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
    validate_error(
        api.create_cycle(
            F.cycle_payload(fiscal_year=2028),
            headers=make_partner_representative_headers(partner["id"]),
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    # Observations, and their retraction, belong to the steward alone.
    validate_error(
        api.create_data_point(sc.indicator_id, F.data_point_payload(), headers=OFFICER),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.void_data_point(sc.data_point_ids[0], "Corrected extract", headers=OFFICER),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    # The board decision belongs to the chair, filing to the compliance officer.
    for headers in (OFFICER, COMPLIANCE):
        validate_error(
            api.board_action(sc.cycle_id, F.board_action_payload(), headers=headers),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
    validate_error(
        api.file_return(sc.cycle_id, "F990SCH-H-2026-0001", headers=OFFICER),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # Registering a party is not a partner's to perform.
    validate_error(
        api.create_party(
            F.partner_party_payload(name="Riverbend Food Bank"),
            headers=make_partner_representative_headers(partner["id"]),
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    # None of the denials left a row behind.
    _rows, meta = validate_paginated(api.list_indicators(cycle_id=sc.cycle_id))
    assert meta["total_count"] == 1
    _points, point_meta = validate_paginated(api.list_data_points(indicator_id=sc.indicator_id))
    assert point_meta["total_count"] == 3


def test_a_near_miss_role_name_is_rejected_as_unauthenticated_not_unauthorized(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six
    role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP
    401."

    Design: Corner/rbac/missing_or_unknown_role_header_precedes_every_authorization_check
    """
    cycle = create_cycle(api)
    path = f"/assessment-cycles/{cycle['id']}"
    assert validate_success(api.raw("GET", path, headers=dict(OFFICER)))["id"] == cycle["id"]

    # One character short of a declared role name is not a role at all.
    near_miss = dict(OFFICER)
    near_miss["X-User-Role"] = "CommunityBenefitOffice"
    validate_error(api.raw("GET", path, headers=near_miss), ApiErrorId.UNAUTHENTICATED, 401)

    # The same on a write, where an unknown role could otherwise look unauthorized.
    validate_error(
        api.raw("POST", "/assessment-cycles", payload=F.cycle_payload(fiscal_year=2028), headers=near_miss),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    no_role = {k: v for k, v in OFFICER.items() if k != "X-User-Role"}
    validate_error(
        api.raw("POST", "/assessment-cycles", payload=F.cycle_payload(fiscal_year=2028), headers=no_role),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )


def test_authentication_answers_before_the_path_lookup_on_a_write(api):
    """PRD §2.1: "This check runs before anything else, including before the server
    attempts to resolve any identifier in the path."

    PRD §2.11: "Endpoint authorization, including the transition-actor refinement on a
    phase advance and the signatory-side refinement on a signature — `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/missing_or_unknown_role_header_precedes_every_authorization_check
    """
    advance_path = f"/assessment-cycles/{NON_EXISTENT_UUID}/advance"
    payload = {"to_status": CycleStatus.DATA_COLLECTION}

    validate_error(
        api.raw("POST", advance_path, payload=payload, headers={}),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )

    # Properly identified, the very same call gets as far as the path lookup.
    validate_error(
        api.advance_cycle(NON_EXISTENT_UUID, CycleStatus.DATA_COLLECTION),
        ApiErrorId.CYCLE_NOT_FOUND,
        404,
    )


def test_the_advance_actor_is_decided_per_requested_transition(api):
    """PRD §2.1: "On a cycle phase advance the acting role must equal the declared actor
    of the *requested* transition: a `to_status` of `CLOSED` requires `ComplianceOfficer`,
    and every other `to_status` requires `CommunityBenefitOfficer`; a mismatch is
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/advance_actor_refinement_splits_the_close_from_every_other_transition
    """
    cycle = create_cycle(api)

    # Rung 2 answers before the rung-11 legality check on DRAFT -> CLOSED.
    wrong_actor_for_close = api.advance_cycle(cycle["id"], CycleStatus.CLOSED, headers=OFFICER)
    validate_error(wrong_actor_for_close, ApiErrorId.UNAUTHORIZED, 403)

    # And the compliance officer is refused a transition that is otherwise legal here.
    wrong_actor_for_opening = api.advance_cycle(
        cycle["id"], CycleStatus.DATA_COLLECTION, headers=COMPLIANCE
    )
    validate_error(wrong_actor_for_opening, ApiErrorId.UNAUTHORIZED, 403)
    assert validate_success(api.get_cycle(cycle["id"]))["status"] == CycleStatus.DRAFT

    advanced = validate_success(
        api.advance_cycle(cycle["id"], CycleStatus.DATA_COLLECTION, headers=OFFICER)
    )
    assert advanced["status"] == CycleStatus.DATA_COLLECTION
    assert advanced["posture"] == Posture.OPEN


def test_the_side_refinement_refuses_each_role_on_the_other_sides_signature(api):
    """PRD §2.1: "On a partnership signature the acting role must match the
    `signatory_side` being recorded: a `HOSPITAL` signature requires
    `CommunityBenefitOfficer` and a `PARTNER` signature requires `PartnerRepresentative`;
    again the rejection is `ERR_UNAUTHORIZED`."

    PRD §4: "Records one side's signature. A `signatory_side` of `HOSPITAL` is restricted
    to `CommunityBenefitOfficer`; `PARTNER` is restricted to the `PartnerRepresentative`
    whose `X-User-ID` equals the agreement's own party id."

    Design: Corner/rbac/partner_signature_is_bound_to_both_the_side_and_the_counterparty
    """
    cycle = create_cycle(api)
    holder = add_partner_party(api, name="Northside Housing Trust", fte_capacity_bp=5000)
    agreement = add_agreement(api, cycle["id"], holder["id"])
    assert agreement["signature_state"] == SignatureState.NEGOTIATING

    holder_headers = make_partner_representative_headers(holder["id"])
    # The right party on the wrong side is still refused at rung 2.
    validate_error(
        api.sign_agreement(agreement["id"], SignatorySide.HOSPITAL, headers=holder_headers),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    # And the mirror image: the officer may not sign the partner's side.
    validate_error(
        api.sign_agreement(agreement["id"], SignatorySide.PARTNER, headers=OFFICER),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    untouched = validate_success(api.get_agreement(agreement["id"]))
    assert untouched["signature_state"] == SignatureState.NEGOTIATING
    assert untouched["hospital_signed_at"] is None
    assert untouched["partner_signed_at"] is None
    assert untouched["funding_state"] == FundingState.UNFUNDED


def test_the_partner_side_is_bound_to_the_agreements_own_counterparty(api):
    """PRD §2.1: "Concretely, a `PartnerRepresentative` may only sign a
    `PartnershipAgreement` whose `party_id` equals the caller's `X-User-ID`, and a mismatch
    is rejected with `ERR_NOT_AGREEMENT_PARTY` and HTTP 403."

    PRD §3.6: "Recording a `PARTNER` signature on an agreement in `NEGOTIATING` moves
    `signature_state` to `PARTNER_SIGNED`, stamps `partner_signed_at` from the logical
    clock, and stores the acting `X-User-ID` as `partner_signatory_user_id` — a value that,
    by the identity rule in §2.1, necessarily equals the agreement's `party_id`;
    `hospital_signed_at` and `hospital_signatory_user_id` stay null and `funding_state`
    stays `UNFUNDED`."

    Design: Corner/rbac/partner_signature_is_bound_to_both_the_side_and_the_counterparty
    """
    cycle = create_cycle(api)
    holder = add_partner_party(api, name="Northside Housing Trust", fte_capacity_bp=5000)
    stranger = add_partner_party(api, name="Riverbend Food Bank", fte_capacity_bp=5000)
    agreement = add_agreement(api, cycle["id"], holder["id"])

    # Right side, wrong counterparty: rung 6, after the side refinement has passed.
    validate_error(
        api.sign_agreement(
            agreement["id"],
            SignatorySide.PARTNER,
            headers=make_partner_representative_headers(stranger["id"]),
        ),
        ApiErrorId.NOT_AGREEMENT_PARTY,
        403,
    )

    signed = validate_success(
        api.sign_agreement(
            agreement["id"],
            SignatorySide.PARTNER,
            headers=make_partner_representative_headers(holder["id"]),
        )
    )
    assert signed["signature_state"] == SignatureState.PARTNER_SIGNED
    assert signed["partner_signatory_user_id"] == holder["id"]
    assert signed["partner_signed_at"] is not None
    assert signed["hospital_signed_at"] is None
    assert signed["hospital_signatory_user_id"] is None
    assert signed["funding_state"] == FundingState.UNFUNDED


def test_the_officer_who_posted_an_expense_may_not_void_it(api):
    """PRD §2.8: "Voiding an expense posting requires that the acting `X-User-ID` differ
    from the `posted_by_user_id` recorded when that posting was created."

    PRD §3.9: "On success the supplied reason is stored in `void_reason`,
    `voided_by_user_id` records the actor, `status` moves `POSTED` to `VOID`, and every one
    of the report's totals — the five categories, `total_valued_cents`, `overhead_rate`,
    `indirect_allocation_cents`, `grand_total_cents` and `benefit_pct_of_expense` — is
    recomputed so that the report returns to exactly the values it held before that posting
    was ever entered."

    Design: Corner/rbac/paired_report_steps_refuse_the_user_who_performed_the_first_half
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    assert report["created_by_user_id"] == OFFICER["X-User-ID"]
    posting = post_charge_based(api, report["id"], 1005)
    assert posting["posted_by_user_id"] == OFFICER["X-User-ID"]
    assert posting["valued_cents"] == 322

    self_void = api.void_posting(posting["id"], "Duplicate charge extract", headers=OFFICER)
    validate_error(self_void, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
    assert validate_success(api.get_posting(posting["id"]))["status"] == PostingStatus.POSTED

    voided = validate_success(
        api.void_posting(posting["id"], "Duplicate charge extract", headers=COMPLIANCE)
    )
    assert voided["status"] == PostingStatus.VOID
    assert voided["voided_by_user_id"] == COMPLIANCE["X-User-ID"]

    restored = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert restored["financial_assistance_cents"] == 0
    assert restored["total_valued_cents"] == 0
    assert restored["indirect_allocation_cents"] == 0
    assert restored["grand_total_cents"] == 0


def test_the_officer_who_opened_the_report_may_not_lock_it(api):
    """PRD §2.8: "Locking a community benefit report requires that the acting `X-User-ID`
    differ from the `created_by_user_id` recorded when that report was opened."

    PRD §2.8: "Both rejections carry `ERR_SEGREGATION_OF_DUTIES` with HTTP 403, and both
    apply irrespective of role — the posting-void rule bites even when both users hold the
    same role, because voiding a posting is available to both `CommunityBenefitOfficer` and
    `ComplianceOfficer`."

    PRD §3.9: "Finally `locked_at` is stamped from the logical clock,
    `finalized_by_user_id` records the actor, and `status` moves `OPEN` to `LOCKED`."

    Design: Corner/rbac/paired_report_steps_refuse_the_user_who_performed_the_first_half
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    post_charge_based(api, report["id"], 1005)

    # The right role presenting the report creator's user id is still refused.
    impostor = make_compliance_headers(OFFICER["X-User-ID"])
    validate_error(
        api.finalize_report(report["id"], C.AUDITED_RATIO, headers=impostor),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert validate_success(api.get_report(report["id"], headers=COMPLIANCE))["status"] == (
        ReportStatus.OPEN
    )

    locked = validate_success(
        api.finalize_report(report["id"], C.AUDITED_RATIO, headers=COMPLIANCE)
    )
    assert locked["status"] == ReportStatus.LOCKED
    assert locked["valuation_basis"] == ValuationBasis.FINAL
    assert locked["finalized_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert locked["locked_at"] is not None


def test_the_public_viewer_reaches_the_four_availability_reads(api):
    """PRD §2.1: "Read-only access to the cycle collection, a single cycle, the
    cycle-scoped progress-evaluation list and a single progress evaluation; every other read
    and every write is denied."

    Design: Corner/rbac/public_viewer_reaches_the_availability_surface_and_nothing_else
    """
    cycle = create_cycle(api)
    evaluation = add_evaluation(
        api,
        cycle["id"],
        eval_type=EvalType.MID_CYCLE,
        period_year=2027,
        findings_summary="Interim scan of implementation progress",
    )

    cycles, cycle_meta = validate_paginated(api.list_cycles(headers=PUBLIC))
    assert cycle_meta["total_count"] == 1
    assert [row["id"] for row in cycles] == [cycle["id"]]

    single = validate_success(api.get_cycle(cycle["id"], headers=PUBLIC))
    assert single["id"] == cycle["id"]
    assert single["status"] == CycleStatus.DRAFT
    assert single["public_availability_met"] is False

    # No rule filters unpublished evaluations out of the public list.
    rows, meta = validate_paginated(api.list_cycle_evaluations(cycle["id"], headers=PUBLIC))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [evaluation["id"]]
    assert validate_success(api.get_evaluation(evaluation["id"], headers=PUBLIC))["status"] == (
        EvalStatus.DRAFT
    )


def test_every_other_read_and_every_write_is_closed_to_the_public_viewer(api):
    """PRD §2.1: "If the headers are well-formed but the acting role does not appear in
    the called endpoint's authorized-role list in §4, the request is rejected with
    `ERR_UNAUTHORIZED` and HTTP 403."

    Design: Corner/rbac/public_viewer_reaches_the_availability_surface_and_nothing_else
    """
    cycle = create_cycle(api)

    denied_reads = (
        api.list_indicators(headers=PUBLIC),
        api.list_interviews(headers=PUBLIC),
        api.list_candidates(headers=PUBLIC),
        api.list_strategies(headers=PUBLIC),
        api.list_agreements(headers=PUBLIC),
        api.list_reports(headers=PUBLIC),
        api.list_postings(headers=PUBLIC),
        api.list_parties(headers=PUBLIC),
        api.list_evaluations(headers=PUBLIC),
    )
    for response in denied_reads:
        validate_error(response, ApiErrorId.UNAUTHORIZED, 403)

    validate_error(
        api.create_cycle(F.cycle_payload(fiscal_year=2028), headers=PUBLIC),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_evaluation(
            F.evaluation_payload(cycle["id"], eval_type=EvalType.MID_CYCLE, period_year=2027),
            headers=PUBLIC,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    # The denials wrote nothing: the public surface still shows the one cycle.
    _rows, meta = validate_paginated(api.list_cycles(headers=PUBLIC))
    assert meta["total_count"] == 1
