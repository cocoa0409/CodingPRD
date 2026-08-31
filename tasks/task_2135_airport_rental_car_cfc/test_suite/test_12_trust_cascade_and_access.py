"""The five-hop receipt cascade, and the two gates every request passes first."""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    UNKNOWN_UUID,
    assert_bond_coverage_posture,
    assert_trust_conservation,
    build_user_headers,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _cascade_scenario(api):
    """A DEFICIENT trust holding 2,000,000 cents, one SCHEDULED 4,000,000 cent obligation and
    one project waiting in APPROVED, with a second 4,000,000 cent receipt still to come."""
    return fx.setup_two_receipt_trust(
        api,
        with_obligation=True,
        with_project=True,
        project_overrides={
            "project_name": "Ready-return deck resurfacing",
            "budget_cents": 2_000_000,
        },
        receive_second=False,
    )


def test_receipt_reconciles_and_flips_the_covenant(api):
    """PRD §3.6: "Every receipt drives the same five-hop cascade."
    PRD §3.6: "**Hop two** runs the trust waterfall over the newly arrived cents. **Hop
    three** recomputes the facility's `bond_coverage_status` from the moved buckets."
    PRD §2.8: "It is recomputed whenever any trust bucket moves: it reads `SATISFIED` when the
    sum of `trust_debt_service_reserve_cents` and `trust_debt_service_funded_cents` is greater
    than or equal to `ds_reserve_requirement_cents`, and `DEFICIENT` otherwise."

    Design: Difficulty/transitive_cascade/remittance_receipt_cascades_to_capital_project_release_depth_five
    """
    scenario = _cascade_scenario(api)

    received = fx.receive_cash(api, scenario["remittance_2"]["id"], 4_000_000)

    assert received["status"] == "RECONCILED"
    assert received["amount_received_cents"] == 4_000_000
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_om_reserve_cents"] == 250_000
    assert facility["trust_capital_fund_cents"] == 750_000
    assert facility["bond_coverage_status"] == "SATISFIED"
    assert facility["trust_lifetime_received_cents"] == 6_000_000
    assert_trust_conservation(facility)
    assert_bond_coverage_posture(facility)


def test_covenant_flip_funds_the_obligation_and_releases_the_project(api):
    """PRD §3.6: "**Hop four** offers the refreshed reserve to the debt-service auto-funding
    selector. **Hop five** releases capital projects that were waiting on the covenant."
    PRD §3.7: "If at least one does, the selector orders the passing candidates by `due_date`
    ascending and breaks ties by `created_at` ascending, and funds exactly the first one — at
    most one obligation is funded per receive call, however much cash arrived. The effects are
    the same as an explicit funding except that `auto_funded` is set to true."
    PRD §3.8: "A project left waiting in `APPROVED` is released later by whichever of three
    events clears its gate: the approval call itself, an obligation reaching `FUNDED`, or its
    predecessor reaching `CLOSED`. The release condition is the same in all three cases —
    status `APPROVED`, `funded_obligation_count` at least 1, `bond_coverage_status`
    `SATISFIED`, and the predecessor either absent or `CLOSED` — and the release sets
    `funding_hold` to false, moves the project `APPROVED → FUNDED`, and advances its `version`
    by 1."

    Design: Difficulty/transitive_cascade/remittance_receipt_cascades_to_capital_project_release_depth_five
    """
    scenario = _cascade_scenario(api)
    assert scenario["project"]["status"] == "APPROVED"
    assert scenario["project"]["funding_hold"] is True

    fx.receive_cash(api, scenario["remittance_2"]["id"], 4_000_000)

    obligation = validate_success(api.get_obligation(scenario["obligation"]["id"], ADMIN))
    assert obligation["status"] == "FUNDED"
    assert obligation["auto_funded"] is True, (
        "the receipt cascade funded it, not an explicit fund call"
    )
    assert obligation["funded_from_reserve_cents"] == 4_000_000
    assert obligation["coverage_ratio_at_funding"] == pytest.approx(1.25, abs=0.00005)
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_debt_service_reserve_cents"] == 1_000_000
    assert facility["trust_debt_service_funded_cents"] == 4_000_000
    assert facility["funded_obligation_count"] == 1
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["status"] == "FUNDED"
    assert project["funding_hold"] is False


def test_missing_auth_headers_are_rejected_before_body_validation(api):
    """PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the capacity in which the caller is
    acting."
    PRD §2.1: "If either header is absent, or if `X-User-Role` carries any string other than
    those four, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything
    else about the request is examined."

    Design: Corner/validations/create_facility_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_facility({"code": "DEN"}, {"Content-Type": "application/json"})

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_operator_cannot_register_a_facility(api):
    """PRD §2.1: "A caller whose role is recognised but who is not among the roles authorised
    for the endpoint being called receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "Register a consolidated rental car facility with its CFC rate, reserve
    requirements and overflow lot | FacilityAdmin"

    Design: Corner/validations/concessionaire_operator_cannot_create_a_facility
    """
    headers = build_user_headers(UNKNOWN_UUID, "ConcessionaireOperator")

    response = api.create_facility(f.facility_payload(), headers)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
