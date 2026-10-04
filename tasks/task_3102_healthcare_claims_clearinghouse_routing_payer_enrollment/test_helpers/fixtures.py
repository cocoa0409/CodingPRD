"""Composite setup helpers for the clearinghouse API.

Every helper builds its world from scratch through the public API — the test
harness restarts the server before each test, so nothing is shared between
tests. Setup calls use the lenient ``get_success_data`` so a failed setup step
reports as a clear "Setup failed" message instead of a confusing assertion.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    DEFAULT_CLOCK,
    PERIOD_2026_09,
)
from .factories import (
    create_claim_payload,
    create_credential_payload,
    create_edit_rule_payload,
    create_eligibility_payload,
    create_enrollment_payload,
    create_outage_payload,
    create_payer_payload,
    create_pricing_tier_payload,
    create_provider_payload,
    create_remittance_payload,
    create_usage_invoice_payload,
)
from .test_users import (
    CLEARINGHOUSE_OPS_HEADERS,
    make_payer_operator_headers,
    make_provider_admin_headers,
)


class World:
    """A bundle of the entities most scenarios need, with their headers."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.ops_headers = CLEARINGHOUSE_OPS_HEADERS
        self.provider: Optional[Dict[str, Any]] = None
        self.credential: Optional[Dict[str, Any]] = None
        self.payer: Optional[Dict[str, Any]] = None
        self.enrollments: Dict[str, Dict[str, Any]] = {}

    @property
    def provider_id(self) -> str:
        assert self.provider is not None, "world has no provider"
        return self.provider["id"]

    @property
    def payer_id(self) -> str:
        assert self.payer is not None, "world has no payer"
        return self.payer["id"]

    @property
    def payer_code(self) -> str:
        assert self.payer is not None, "world has no payer"
        return self.payer["payer_id_code"]

    @property
    def credential_id(self) -> str:
        assert self.credential is not None, "world has no credential"
        return self.credential["id"]

    def admin_headers(self) -> Dict[str, str]:
        return make_provider_admin_headers(self.provider_id)

    def payer_headers(self) -> Dict[str, str]:
        return make_payer_operator_headers(self.payer_id, self.payer_code)


def set_clock(api: ApiClient, current_utc: str) -> None:
    resp = api.set_clock(current_utc, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.status_code} {resp.text}"


def create_provider(api: ApiClient, **overrides) -> Dict[str, Any]:
    resp = api.create_provider(create_provider_payload(**overrides), CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 201, f"Setup failed: create_provider -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_credential(api: ApiClient, provider_id: str, **overrides) -> Dict[str, Any]:
    headers = make_provider_admin_headers(provider_id)
    resp = api.create_credential(provider_id, create_credential_payload(**overrides), headers)
    assert resp.status_code == 201, f"Setup failed: create_credential -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def submit_credential(api: ApiClient, provider_id: str, credential_id: str) -> Dict[str, Any]:
    headers = make_provider_admin_headers(provider_id)
    resp = api.submit_credential(provider_id, credential_id, headers)
    assert resp.status_code == 200, f"Setup failed: submit_credential -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def activate_provider(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    resp = api.activate_provider(provider_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: activate_provider -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_payer(api: ApiClient, **overrides) -> Dict[str, Any]:
    resp = api.create_payer(create_payer_payload(**overrides), CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 201, f"Setup failed: create_payer -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_pricing_tier(api: ApiClient, payer_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_pricing_tier(payer_id, create_pricing_tier_payload(**overrides), CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 201, f"Setup failed: create_pricing_tier -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_edit_rule(api: ApiClient, payer_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_edit_rule(payer_id, create_edit_rule_payload(**overrides), CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 201, f"Setup failed: create_edit_rule -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def setup_active_provider_with_credential(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK,
    provider_overrides: Optional[Dict[str, Any]] = None,
    credential_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Provider ONBOARDING -> ACTIVE with one credential submitted.

    The credential's default window starts at the boot clock, so once the
    provider is activated at that same logical instant the credential has
    already reached its activation moment.
    """
    set_clock(api, clock)
    provider = create_provider(api, **(provider_overrides or {}))
    credential = create_credential(api, provider["id"], **(credential_overrides or {}))
    submit_credential(api, provider["id"], credential["id"])
    provider = activate_provider(api, provider["id"])
    return provider, credential


def setup_world(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK,
    provider_overrides: Optional[Dict[str, Any]] = None,
    credential_overrides: Optional[Dict[str, Any]] = None,
    payer_overrides: Optional[Dict[str, Any]] = None,
    payer_code: str = "PAYAA",
) -> World:
    """Active provider with credential plus a registered payer."""
    world = World(api)
    provider, credential = setup_active_provider_with_credential(
        api, clock, provider_overrides, credential_overrides
    )
    world.provider = provider
    world.credential = credential
    payer_defaults: Dict[str, Any] = {"payer_id_code": payer_code}
    payer_defaults.update(payer_overrides or {})
    world.payer = create_payer(api, **payer_defaults)
    return world


def enroll_and_approve(api: ApiClient, world: World, transaction_type: str) -> Dict[str, Any]:
    """Create -> submit -> advance -> APPROVE an enrollment for the world's pair."""
    admin = world.admin_headers()
    resp = api.create_enrollment(
        world.provider_id,
        create_enrollment_payload(payer_id=world.payer_id, transaction_type=transaction_type),
        admin,
    )
    assert resp.status_code == 201, f"Setup failed: create_enrollment -> {resp.status_code} {resp.text}"
    enrollment = get_success_data(resp)

    resp = api.submit_enrollment(world.provider_id, enrollment["id"], admin)
    assert resp.status_code == 200, f"Setup failed: submit_enrollment -> {resp.status_code} {resp.text}"

    resp = api.advance_enrollment_to_review(enrollment["id"], CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: advance_enrollment_to_review -> {resp.status_code} {resp.text}"

    resp = api.get_enrollment(world.provider_id, enrollment["id"], admin)
    assert resp.status_code == 200, f"Setup failed: get_enrollment -> {resp.status_code} {resp.text}"
    current = get_success_data(resp)

    resp = api.record_payer_decision(
        enrollment["id"],
        {"decision": "APPROVE", "expected_enrollment_version": current["version"]},
        world.payer_headers(),
    )
    assert resp.status_code == 200, f"Setup failed: payer decision APPROVE -> {resp.status_code} {resp.text}"
    approved = get_success_data(resp)
    world.enrollments[transaction_type] = approved
    return approved


def submit_claim(api: ApiClient, world: World, **overrides) -> Dict[str, Any]:
    """Submit one claim; returns the settled claim body from the 201 response.

    When ``total_charge_cents`` is overridden without overriding ``lines``, the
    lines array is rebuilt as a single line matching the new total so the
    intake arithmetic check balances.
    """
    defaults: Dict[str, Any] = {
        "payer_id": world.payer_id,
        "submitter_credential_id": world.credential_id,
        "rendering_npi": world.provider["national_provider_identifier"],
    }
    defaults.update(overrides)
    if "total_charge_cents" in overrides and "lines" not in overrides:
        defaults["lines"] = [
            {"cpt_code": "99213", "units": 1, "unit_charge_cents": overrides["total_charge_cents"]}
        ]
    resp = api.create_claim(world.provider_id, create_claim_payload(**defaults), world.admin_headers())
    assert resp.status_code == 201, f"Setup failed: create_claim -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def forward_claim(api: ApiClient, claim: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.forward_claim(
        claim["id"], {"expected_claim_version": claim["version"]}, CLEARINGHOUSE_OPS_HEADERS
    )
    assert resp.status_code == 200, f"Setup failed: forward_claim -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def ack_claim(api: ApiClient, world: World, claim_id: str) -> Dict[str, Any]:
    resp = api.ack_claim(claim_id, world.payer_headers())
    assert resp.status_code == 200, f"Setup failed: ack_claim -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_remittance(api: ApiClient, world: World, claim_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_remittance(claim_id, create_remittance_payload(**overrides), world.payer_headers())
    assert resp.status_code == 201, f"Setup failed: create_remittance -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def post_remittance(api: ApiClient, remittance_id: str) -> Dict[str, Any]:
    resp = api.post_remittance(remittance_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: post_remittance -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def setup_claims_pipeline(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK,
    provider_overrides: Optional[Dict[str, Any]] = None,
    credential_overrides: Optional[Dict[str, Any]] = None,
    payer_overrides: Optional[Dict[str, Any]] = None,
    payer_code: str = "PAYAA",
    transaction_types: Tuple[str, ...] = ("CLAIMS_837",),
) -> World:
    """World with APPROVED enrollments for the given transaction types."""
    world = setup_world(
        api,
        clock=clock,
        provider_overrides=provider_overrides,
        credential_overrides=credential_overrides,
        payer_overrides=payer_overrides,
        payer_code=payer_code,
    )
    for transaction_type in transaction_types:
        enroll_and_approve(api, world, transaction_type)
    return world


def setup_forwarded_claim(
    api: ApiClient,
    world: World,
    claim_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit one claim and forward it. Returns the FORWARDED claim."""
    claim = submit_claim(api, world, **(claim_overrides or {}))
    return forward_claim(api, claim)


def setup_acknowledged_claim(
    api: ApiClient,
    world: World,
    claim_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit, forward and acknowledge one claim."""
    claim = setup_forwarded_claim(api, world, claim_overrides)
    return ack_claim(api, world, claim["id"])


def submit_inquiry(api: ApiClient, world: World, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"payer_id": world.payer_id}
    defaults.update(overrides)
    resp = api.create_eligibility_inquiry(
        world.provider_id, create_eligibility_payload(**defaults), world.admin_headers()
    )
    assert resp.status_code == 201, f"Setup failed: create_eligibility_inquiry -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def respond_inquiry(api: ApiClient, world: World, inquiry_id: str, benefit_summary: Optional[Dict] = None) -> Dict[str, Any]:
    payload = {"benefit_summary": benefit_summary if benefit_summary is not None else {"coverage": "ACTIVE"}}
    resp = api.respond_to_inquiry(inquiry_id, payload, world.payer_headers())
    assert resp.status_code == 200, f"Setup failed: respond_to_inquiry -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_outage(api: ApiClient, payer_id: str, **overrides) -> Dict[str, Any]:
    resp = api.create_outage(payer_id, create_outage_payload(**overrides), CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 201, f"Setup failed: create_outage -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_usage_invoice(api: ApiClient, provider_id: str, period: str = PERIOD_2026_09) -> Dict[str, Any]:
    resp = api.create_usage_invoice(
        provider_id, create_usage_invoice_payload(period_yyyy_mm=period), CLEARINGHOUSE_OPS_HEADERS
    )
    assert resp.status_code == 201, f"Setup failed: create_usage_invoice -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def finalize_invoice(api: ApiClient, invoice: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.finalize_usage_invoice(
        invoice["id"], {"expected_invoice_version": invoice["version"]}, CLEARINGHOUSE_OPS_HEADERS
    )
    assert resp.status_code == 200, f"Setup failed: finalize_invoice -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_invoice(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    resp = api.get_usage_invoice(invoice_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: get_invoice -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_provider(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    resp = api.get_provider(provider_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: get_provider -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    resp = api.get_claim(claim_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: get_claim -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_payer(api: ApiClient, payer_id: str) -> Dict[str, Any]:
    resp = api.get_payer(payer_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: get_payer -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_enrollment(api: ApiClient, world: World, enrollment_id: str) -> Dict[str, Any]:
    resp = api.get_enrollment(world.provider_id, enrollment_id, world.admin_headers())
    assert resp.status_code == 200, f"Setup failed: get_enrollment -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_inquiry(api: ApiClient, inquiry_id: str) -> Dict[str, Any]:
    resp = api.get_eligibility_inquiry(inquiry_id, CLEARINGHOUSE_OPS_HEADERS)
    assert resp.status_code == 200, f"Setup failed: get_inquiry -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def list_claims(api: ApiClient, provider_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    resp = api.list_claims(provider_id, CLEARINGHOUSE_OPS_HEADERS, params=params)
    assert resp.status_code == 200, f"Setup failed: list_claims -> {resp.status_code} {resp.text}"
    body = resp.json()
    return body["data"]


def setup_remittance_world(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK,
    claim_total_cents: int = 20000,
    payer_overrides: Optional[Dict[str, Any]] = None,
    payer_code: str = "PAYAA",
) -> Tuple[World, Dict[str, Any]]:
    """World with CLAIMS_837 + REMITTANCE_835 approved and one claim ACKNOWLEDGED."""
    world = setup_claims_pipeline(
        api,
        clock=clock,
        payer_overrides=payer_overrides,
        payer_code=payer_code,
        transaction_types=("CLAIMS_837", "REMITTANCE_835"),
    )
    claim = setup_acknowledged_claim(
        api, world, claim_overrides={"total_charge_cents": claim_total_cents}
    )
    return world, claim
