"""Filing-time and schema validation corners (PRD §2.11, §3.3, §3.4, §3.6,
§3.9).
"""
from test_helpers import (
    APPEALS,
    ApiErrorId,
    PANEL,
    accord,
    api_client,
    create_discovery_payload,
    create_litigation_matter,
    create_petition_payload,
    file_petition,
    get_petition,
    get_proceeding,
    get_success_data,
    new_world,
    setup_decided_with_appeal,
    setup_instituted_proceeding,
    validate_error,
)


def test_time_barred_and_underpaid_returns_temporal_error_before_fiscal():
    """PRD §2.11: "(8) statutory clocks (`ERR_PETITION_TIME_BARRED`,
    `ERR_INSTITUTION_WINDOW_LAPSED`, `ERR_BRIEF_WINDOW_CLOSED`,
    `ERR_FWD_DEADLINE_PASSED`, `ERR_HEARING_PAST_FWD_DATE`)" precedes "(10)
    filing-fee sufficiency (`ERR_FEE_INSUFFICIENT`)", and "A request that
    violates both an earlier and a later category always reports the earlier
    one."

    Design: Corner/validations/time_barred_and_underpaid_returns_temporal_error_before_fiscal
    """
    world = new_world(petitioner_name="PU Corp", owner_name="OU Corp")
    create_litigation_matter(
        world["patent"]["id"], world["petitioner"]["id"],
        "2025-08-20T00:00:00Z", court_name="D. Del.",
        docket_number="1:25-cv-01400",
    )
    # 377 days since service AND fee 0: the temporal error reports first.
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=[1],
        fee_paid_cents=0,
        expected_patent_version=world["patent"]["version"],
    )
    resp = api_client.create_petition(payload, world["petitioner_headers"])
    err = validate_error(resp, ApiErrorId.ERR_PETITION_TIME_BARRED, 422)
    assert err["error_id"] != ApiErrorId.ERR_FEE_INSUFFICIENT


def test_petition_with_unknown_review_type_rejected_as_schema_error():
    """PRD §3.3: "The `review_type` selects the statutory track: `IPR` or
    `PGR`." and "any structural defect in these arrays is `ERR_VALIDATION`"
    (PRD §2.11 category (5): "required fields present, enums in range").

    Design: Corner/validations/petition_with_unknown_review_type_rejected_as_schema_error
    """
    world = new_world(petitioner_name="PAM Corp", owner_name="OAM Corp")
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        review_type="CBM",
        challenged_claims=[1],
        expected_patent_version=world["patent"]["version"],
    )
    resp = api_client.create_petition(payload, world["petitioner_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_ground_referencing_unchallenged_claim_rejected_as_schema_error():
    """PRD §3.3: "`grounds`, a non-empty array whose entries pair a
    `claim_number` with a `basis`, where every `claim_number` appears among
    the `challenged_claims`" — and "any structural defect in these arrays is
    `ERR_VALIDATION`."

    Design: Corner/validations/ground_referencing_unchallenged_claim_rejected_as_schema_error
    """
    world = new_world(petitioner_name="PAP Corp", owner_name="OAP Corp",
                      total_claims=5)
    payload = create_petition_payload(
        patent_id=world["patent"]["id"],
        petitioner_id=world["petitioner"]["id"],
        challenged_claims=[1, 2],
        grounds=[{"claim_number": 4, "basis": "ANTICIPATION_102"}],
        expected_patent_version=world["patent"]["version"],
    )
    resp = api_client.create_petition(payload, world["petitioner_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_ipr_ground_outside_statutory_basis_rejected_at_accord():
    """PRD §3.4: "Every asserted ground `basis` on an `IPR` petition must be
    `ANTICIPATION_102` or `OBVIOUSNESS_103`, or accordance is rejected with
    `ERR_GROUND_NOT_PERMITTED`".

    Design: Corner/validations/ipr_ground_outside_statutory_basis_rejected_at_accord
    """
    world = new_world(petitioner_name="PV Corp", owner_name="OV Corp")
    petition = file_petition(
        world["petitioner"]["id"], world["patent"]["id"],
        challenged_claims=[1],
        grounds=[{"claim_number": 1, "basis": "PUBLIC_USE"}],
    )
    resp = api_client.accord_filing_date(petition["id"], PANEL)
    validate_error(resp, ApiErrorId.ERR_GROUND_NOT_PERMITTED, 422)
    # No partial mutation: the petition remains FILED.
    assert get_petition(petition["id"])["status"] == "FILED"


def test_ipr_prior_art_product_reference_rejected_at_accord():
    """PRD §3.4: "every `prior_art` entry on an `IPR` petition must have a
    `reference_type` of `PATENT` or `PRINTED_PUBLICATION`, or accordance is
    rejected with `ERR_PRIOR_ART_TYPE_NOT_PERMITTED`."

    Design: Corner/validations/ipr_prior_art_product_reference_rejected_at_accord
    """
    world = new_world(petitioner_name="PW Corp", owner_name="OW Corp")
    petition = file_petition(
        world["petitioner"]["id"], world["patent"]["id"],
        challenged_claims=[1],
        prior_art=[{"reference_type": "PRODUCT",
                    "citation": "Widget 3000 sold 2015"}],
    )
    resp = api_client.accord_filing_date(petition["id"], PANEL)
    validate_error(resp, ApiErrorId.ERR_PRIOR_ART_TYPE_NOT_PERMITTED, 422)
    assert get_petition(petition["id"])["status"] == "FILED"


def test_additional_discovery_with_wrong_factor_count_rejected():
    """PRD §3.6: "An `ADDITIONAL` request requires `factor_scores` of exactly
    five integers, each from 0 to 2 — any other shape is `ERR_VALIDATION`".

    Design: Corner/validations/additional_discovery_with_wrong_factor_count_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-quinn2",
    )
    resp = api_client.create_discovery_request(
        world["proceeding"]["id"],
        create_discovery_payload(discovery_type="ADDITIONAL",
                                 factor_scores=[2, 2, 1, 1]),
        world["petitioner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_vacated_remand_decision_without_instructions_rejected():
    """PRD §3.9: "`VACATED_AND_REMANDED` is the inverse: it requires
    `remand_instructions` of `REOPEN_RECORD` or `RECONSIDER`, and their
    absence is likewise `ERR_VALIDATION`."

    Design: Corner/validations/vacated_remand_decision_without_instructions_rejected
    """
    world = setup_decided_with_appeal(
        institute_kw=dict(
            total_claims=2, challenged_claims=(1,),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102",
                     "score": 80}],
            lead_judge="judge-rae",
        ),
        outcomes=[{"claim_number": 1, "outcome": "UNPATENTABLE"}],
    )
    resp = api_client.decide_appeal(
        world["appeal"]["id"], {"outcome": "VACATED_AND_REMANDED"}, APPEALS,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
    # No partial mutation: the appeal remains FILED, proceeding DECIDED.
    appeals = get_success_data(
        api_client.list_appeals(world["proceeding"]["id"], APPEALS)
    )
    assert appeals[0]["status"] == "FILED"
    assert get_proceeding(world["proceeding"]["id"])["phase"] == "DECIDED"
