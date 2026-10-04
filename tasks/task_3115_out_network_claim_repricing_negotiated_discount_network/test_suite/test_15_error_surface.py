"""Corner queue: errors — authentication, role authorization, IDR amount
matching, invoice fiscal guards, transparency gating."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_agreement, create_claim, add_line, reprice, setup_priced_claim,
    setup_finalized_claim, issue_invoice,
    create_payer_client_payload, create_claim_payload,
    create_idr_submission_payload,
    make_payer_admin_headers, make_payer_rep_headers,
    make_provider_rep_headers,
    TEST_USERS, NON_EXISTENT_UUID, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]
NET = TEST_USERS["network_admin_headers"]
IDR = TEST_USERS["idr_entity_headers"]


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "When either header is missing, or when the value of
    `X-User-Role` is not one of the declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then
    role authorization (`ERR_FORBIDDEN_ROLE`), then path-id existence checked
    left-to-right (`ERR_NOT_FOUND`)."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    res = api_client.get_payer_client(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_forbidden_role_returns_403():
    """PRD §2.1: "When the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/payer-clients` | Onboard a payer client with fee
    configuration | OpsAdmin |"

    Design: Corner/errors/forbidden_role_returns_403
    """
    provider = create_provider(npi="6000000001")
    res = api_client.create_payer_client(
        create_payer_client_payload(payer_name="X"),
        make_provider_rep_headers(provider["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def _setup_submitted_idr():
    """NSA claim priced; expired open negotiation; one QPA candidate; IDR filed."""
    get_success_data(api_client.set_clock("2026-09-10T10:00:00Z", OPS))
    env = setup_priced_claim(
        claim_overrides={"external_claim_ref": "E4", "nsa_flag": True,
                         "service_date": "2026-09-01T00:00:00Z",
                         "patient_responsibility_cents": 0},
        npi="6000000002")
    create_agreement(env["provider"], network_name="NQ", discount_percent=0.50)
    # PRD §3.7: QPA candidates are agreements whose determination snapshots
    # priced the claim's primary procedure_code under CONTRACTED_NETWORK.
    # Price a separate ANCILLARY claim under a CONTRACTED_NETWORK policy so a
    # qualifying snapshot (unit charge 30000, discount 0.50 -> rate 15000)
    # exists before submission.
    create_policy(env["payer"], env["ctx"], claim_type="ANCILLARY",
                  methodology="CONTRACTED_NETWORK", percent_of_medicare=None,
                  priority=1)
    qpa_claim = create_claim(env["payer"], env["provider"], env["ctx"],
                             external_claim_ref="E4-QPA", claim_type="ANCILLARY",
                             service_date="2026-09-01T00:00:00Z",
                             patient_responsibility_cents=0)
    add_line(qpa_claim["id"], env["ctx"], quantity_units=1,
             unit_charge_cents=30000)
    get_success_data(reprice(qpa_claim["id"], qpa_claim["version"] + 1,
                             env["ctx"]))
    on = get_success_data(api_client.create_open_negotiation(
        {"claim_id": env["claim"]["id"], "initiated_by": "PROVIDER"},
        env["ctx"]["provider_rep"]))
    get_success_data(api_client.set_clock("2026-10-23T00:00:00Z", OPS))
    idr = get_success_data(api_client.create_idr_submission(
        create_idr_submission_payload(env["claim"]["id"], on["id"]),
        env["ctx"]["provider_rep"]))
    env["idr"] = idr
    return env


def test_idr_decide_amount_mismatch_rejected():
    """PRD §3.7: "Deciding in the payer's favor requires `winner` indicating the
    payer and a `winning_amount_cents` exactly equal to the submission's
    `payer_offer_cents`; deciding in the provider's favor requires the
    `winning_amount_cents` to equal `provider_offer_cents`. A mismatch is
    rejected with `ERR_IDR_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/errors/idr_decide_amount_mismatch_rejected
    """
    env = _setup_submitted_idr()
    res = api_client.decide_idr_submission(
        env["idr"]["id"], {"winner": "PAYER", "winning_amount_cents": 31000}, IDR)
    validate_error(res, ApiErrorId.ERR_IDR_AMOUNT_MISMATCH)
    idr = validate_success(api_client.get_idr_submission(env["idr"]["id"], IDR), 200)
    assert idr["status"] == "SUBMITTED"


def test_fee_invoice_rejects_nonfinalized_and_double_invoicing():
    """PRD §3.9: "Issuing the invoice applies two fiscal guards, in order: every
    listed claim must be `FINALIZED` — otherwise `ERR_CLAIM_NOT_FINALIZED`
    (HTTP 409) — and no listed claim may already appear on another non-voided
    invoice — otherwise `ERR_CLAIM_ALREADY_INVOICED` (HTTP 409); these guards
    apply both at invoice creation and at issue time."

    Design: Corner/errors/fee_invoice_rejects_nonfinalized_and_double_invoicing
    """
    env_a = setup_finalized_claim(
        claim_overrides={"external_claim_ref": "E5A",
                         "patient_responsibility_cents": 0},
        npi="6000000003")
    payer, ctx = env_a["payer"], env_a["ctx"]
    claim_b = create_claim(payer, env_a["provider"], ctx,
                           external_claim_ref="E5B", patient_responsibility_cents=0)
    add_line(claim_b["id"], ctx)
    get_success_data(reprice(claim_b["id"], claim_b["version"] + 1, ctx))

    invoice_a = issue_invoice(payer["id"], [env_a["claim"]["id"]])
    assert invoice_a["status"] == "ISSUED"

    # PRD §3.9: the guards apply at invoice creation (and issue). Creating an
    # invoice over PRICED-but-not-FINALIZED claim B -> ERR_CLAIM_NOT_FINALIZED.
    res = api_client.create_fee_invoice(
        {"payer_client_id": payer["id"], "claim_ids": [claim_b["id"]]}, OPS)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_FINALIZED)

    # Second invoice over already-invoiced claim A -> ERR_CLAIM_ALREADY_INVOICED
    res2 = api_client.create_fee_invoice(
        {"payer_client_id": payer["id"], "claim_ids": [env_a["claim"]["id"]]}, OPS)
    validate_error(res2, ApiErrorId.ERR_CLAIM_ALREADY_INVOICED)


def test_transparency_report_requires_enabled_flag():
    """PRD §3.9: "Publishing against a payer without the flag, or against an
    invoice not yet `ISSUED`, is rejected with `ERR_TRANSPARENCY_NOT_ENABLED`
    (HTTP 422)."
    PRD §3.9: "Publishing also sets the invoice's `transparency_report_id`."

    Design: Corner/errors/transparency_report_requires_enabled_flag
    """
    env = setup_finalized_claim(
        payer_overrides={"transparency_reporting_enabled": False},
        claim_overrides={"external_claim_ref": "E6",
                         "patient_responsibility_cents": 0},
        npi="6000000004")
    invoice = issue_invoice(env["payer"]["id"], [env["claim"]["id"]])

    res = api_client.publish_transparency_report(invoice["id"], OPS)
    validate_error(res, ApiErrorId.ERR_TRANSPARENCY_NOT_ENABLED)
    invoice_after = validate_success(api_client.get_fee_invoice(invoice["id"], OPS), 200)
    assert invoice_after["transparency_report_id"] is None
