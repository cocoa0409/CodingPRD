"""Composite setup helpers.

Most interesting rules of this API are only reachable behind multi-step
preconditions: an agency cannot transact until it holds a VERIFIED settlement
account and a CURRENT PCI_DSS_AOC attestation; a CONVENIENCE_FEE service
cannot activate without an in-effect APPROVED statutory authorization; a
payment cannot authorize without an OPEN unexpired quote and a usable
instrument; an ACH return is only defined once a transaction has SETTLED into
a batch. The helpers below encapsulate those chains so tests can focus on
assertions.

Clock discipline: every time-sensitive precondition is pinned against the
logical clock, whose startup default is exactly 2026-09-01T00:00:00Z. The
default windows used here (attestation issued 2026-08-01 expiring
2027-08-01, account effective_from 2026-01-01, authorization window
[2026-01-01, 2027-12-31]) all straddle that start instant, so every fixture
is reachable from a fresh server. Fixtures that need a later clock call
``set_clock`` themselves.

Identity threading: Payer-role calls always carry the real Payer.id via
``make_payer_headers`` — never the shared fallback constant. AgencyAdmin
calls carry opaque staff ids; ``AGENCY_ADMIN_LEAD`` initiates and
``AGENCY_ADMIN_PEER`` decides so segregation-of-duties gates pass.

Every helper uses the lenient success reader, so a broken preamble surfaces
as a clear "Setup step failed" error instead of a confusing assertion later.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    authorize_payment_payload,
    close_period_payload,
    confirm_deposit_payload,
    contest_chargeback_payload,
    create_agency_payload,
    create_attestation_payload,
    create_chargeback_payload,
    create_fee_quote_payload,
    create_instrument_payload,
    create_payer_payload,
    create_pricing_tier_payload,
    create_refund_payload,
    create_service_payload,
    create_settlement_account_payload,
    create_settlement_batch_payload,
    create_statutory_authorization_payload,
    decide_refund_payload,
    record_outcome_payload,
    resolve_exception_payload,
    update_service_payload,
    verify_account_payload,
    verify_ach_payload,
)
from .test_users import (
    AGENCY_ADMIN_COUNTY,
    AGENCY_ADMIN_LEAD,
    AGENCY_ADMIN_PEER,
    TEST_USERS,
    make_agency_admin_headers,
    make_payer_headers,
)

PA = TEST_USERS["platform_admin_headers"]
TO = TEST_USERS["treasury_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _aa(user_id=AGENCY_ADMIN_LEAD) -> dict:
    return make_agency_admin_headers(user_id)


def _payer(payer_id) -> dict:
    return make_payer_headers(payer_id)


def _tick(iso_utc: str, days: int) -> str:
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ") + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 0: the logical clock
# ---------------------------------------------------------------------------

def set_clock(current_utc=DEFAULT_CLOCK_UTC) -> dict:
    """Move the server's logical clock; a PlatformAdmin-only control mounted
    outside the business prefix."""
    return get_success_data(api_client.set_clock(current_utc, PA))


def reset_clock() -> dict:
    """Return the clock to its startup default."""
    return set_clock(DEFAULT_CLOCK_UTC)


# ---------------------------------------------------------------------------
# Tier 1: agency lifecycle
# ---------------------------------------------------------------------------

def create_agency(**overrides) -> dict:
    return get_success_data(api_client.create_agency(create_agency_payload(**overrides), PA))


def get_agency(agency_id) -> dict:
    return get_success_data(api_client.get_agency(agency_id, PA))


def create_settlement_account(agency_id, expected_agency_version, **overrides) -> dict:
    """Create a PENDING_VERIFICATION account. OCC: expected_agency_version must
    equal the agency's current version."""
    return get_success_data(
        api_client.create_settlement_account(
            create_settlement_account_payload(agency_id, expected_agency_version, **overrides),
            PA,
        )
    )


def verify_account(account_id, outcome="SUCCESS") -> dict:
    return get_success_data(
        api_client.verify_settlement_account(account_id, verify_account_payload(outcome), TO)
    )


def create_verified_account(agency_id, agency_version, **overrides) -> dict:
    """Create + treasury-verify. Returns the VERIFIED account."""
    account = create_settlement_account(agency_id, agency_version, **overrides)
    return verify_account(account["id"], "SUCCESS")


def file_attestation(agency_id, **overrides) -> dict:
    """File a compliance attestation (ComplianceAuditor). Its CURRENT/EXPIRED
    standing is computed against the logical clock on every read."""
    return get_success_data(
        api_client.create_attestation(create_attestation_payload(agency_id, **overrides), CA)
    )


def activate_agency(agency_id) -> dict:
    return get_success_data(api_client.activate_agency(agency_id, PA))


def suspend_agency(agency_id) -> dict:
    return get_success_data(api_client.suspend_agency(agency_id, PA))


def offboard_agency(agency_id) -> dict:
    return get_success_data(api_client.offboard_agency(agency_id, PA))


def setup_agency_with_verified_account(agency_overrides=None, account_overrides=None) -> dict:
    """Agency + one VERIFIED settlement account. The returned agency is
    re-read after the create so its version reflects the account mutation."""
    agency = create_agency(**(agency_overrides or {}))
    account = create_verified_account(agency["id"], agency["version"], **(account_overrides or {}))
    return {"agency": get_agency(agency["id"]), "account": account}


def setup_active_agency(
    attestation_expires_at="2027-08-01T00:00:00Z",
    attestation_issued_at="2026-08-01T00:00:00Z",
    agency_overrides=None,
    account_overrides=None,
) -> dict:
    """Agency carried through both activation gates: a VERIFIED account and a
    CURRENT PCI_DSS_AOC attestation. Returns the ACTIVE agency, the account
    and the attestation."""
    built = setup_agency_with_verified_account(agency_overrides, account_overrides)
    attestation = file_attestation(
        built["agency"]["id"],
        issued_at=attestation_issued_at,
        expires_at=attestation_expires_at,
    )
    agency = activate_agency(built["agency"]["id"])
    return {"agency": agency, "account": built["account"], "attestation": attestation}


# ---------------------------------------------------------------------------
# Tier 2: catalog services, pricing bands, statutory authorizations
# ---------------------------------------------------------------------------

def create_service(agency_id, as_user_id=AGENCY_ADMIN_LEAD, **overrides) -> dict:
    return get_success_data(
        api_client.create_service(create_service_payload(agency_id, **overrides), _aa(as_user_id))
    )


def get_service(service_id) -> dict:
    return get_success_data(api_client.get_service(service_id, PA))


def update_service(service_id, expected_service_version, as_user_id=AGENCY_ADMIN_LEAD, **fields) -> dict:
    return get_success_data(
        api_client.update_service(
            service_id,
            update_service_payload(expected_service_version, **fields),
            _aa(as_user_id),
        )
    )


def activate_service(service_id) -> dict:
    return get_success_data(api_client.activate_service(service_id, PA))


def deactivate_service(service_id) -> dict:
    return get_success_data(api_client.deactivate_service(service_id, PA))


def create_authorization(service_id, as_user_id=AGENCY_ADMIN_LEAD, **overrides) -> dict:
    return get_success_data(
        api_client.create_statutory_authorization(
            create_statutory_authorization_payload(service_id, **overrides), _aa(as_user_id)
        )
    )


def approve_authorization(authorization_id) -> dict:
    return get_success_data(api_client.approve_statutory_authorization(authorization_id, PA))


def create_approved_authorization(service_id, as_user_id=AGENCY_ADMIN_LEAD, **overrides) -> dict:
    authorization = create_authorization(service_id, as_user_id, **overrides)
    return approve_authorization(authorization["id"])


def setup_active_cf_service(
    agency_id,
    as_user_id=AGENCY_ADMIN_LEAD,
    fee_cap_cents=5000,
    service_overrides=None,
    authz_overrides=None,
) -> dict:
    """DRAFT CONVENIENCE_FEE service + APPROVED in-effect authorization, then
    service activation. Returns the ACTIVE service (version 2) and the
    authorization."""
    svc_over = {"fee_model": "CONVENIENCE_FEE"}
    svc_over.update(service_overrides or {})
    service = create_service(agency_id, as_user_id, **svc_over)
    authz = {"fee_cap_cents": fee_cap_cents}
    authz.update(authz_overrides or {})
    authorization = create_approved_authorization(service["id"], as_user_id, **authz)
    service = activate_service(service["id"])
    return {"service": service, "authorization": authorization}


def setup_active_absorbed_service(
    agency_id, as_user_id=AGENCY_ADMIN_COUNTY, service_overrides=None
) -> dict:
    """ABSORBED services need no statutory authorization to activate."""
    svc_over = {
        "service_code": "PROP-TAX",
        "name": "Property Tax Payment",
        "fee_model": "ABSORBED",
        "allowed_methods": ["ECHECK"],
        "min_amount_cents": 1,
        "max_amount_cents": 100000000,
        "gl_code": "5200",
    }
    svc_over.update(service_overrides or {})
    service = create_service(agency_id, as_user_id, **svc_over)
    service = activate_service(service["id"])
    return {"service": service}


def create_pricing_band(agency_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_pricing_tier(create_pricing_tier_payload(agency_id, **overrides), PA)
    )


def setup_pricing_bands(agency_id, effective_month="2026-09", top_unbounded=True) -> list:
    """The standard three-band month config: [0,500000] @250bp +20,
    [500001,2000000] @190bp +15, and (optionally) the unbounded top band
    [2000001, null] @120bp +10. With top_unbounded=False only the first two
    bands exist — used by tier-coverage boundary tests."""
    bands = [
        create_pricing_band(
            agency_id,
            volume_min_cents=0,
            volume_max_cents=500000,
            rate_bp=250,
            per_txn_cents=20,
            effective_month=effective_month,
        ),
        create_pricing_band(
            agency_id,
            volume_min_cents=500001,
            volume_max_cents=2000000,
            rate_bp=190,
            per_txn_cents=15,
            effective_month=effective_month,
        ),
    ]
    if top_unbounded:
        bands.append(
            create_pricing_band(
                agency_id,
                volume_min_cents=2000001,
                volume_max_cents=None,
                rate_bp=120,
                per_txn_cents=10,
                effective_month=effective_month,
            )
        )
    return bands


# ---------------------------------------------------------------------------
# Tier 3: payers and instruments
# ---------------------------------------------------------------------------

def register_payer(**overrides) -> dict:
    """Registration is open to Anonymous callers."""
    return get_success_data(api_client.create_payer(create_payer_payload(**overrides), ANON))


def get_payer(payer_id) -> dict:
    return get_success_data(api_client.get_payer(payer_id, PA))


def add_instrument(payer_id, method, as_platform_admin=False, **overrides) -> dict:
    """Add an instrument under a payer. Payer-role calls carry the real
    Payer.id (ownership-gated); PlatformAdmin bypasses ownership."""
    headers = PA if as_platform_admin else _payer(payer_id)
    return get_success_data(
        api_client.create_instrument(
            payer_id, create_instrument_payload(method, **overrides), headers
        )
    )


def add_card_instrument(
    payer_id, card_cost_bucket="CONSUMER_DEBIT", card_brand="VISA", last4="4242"
) -> dict:
    """CARD instruments are created ACTIVE immediately."""
    return add_instrument(
        payer_id,
        "CARD",
        card_brand=card_brand,
        card_cost_bucket=card_cost_bucket,
        last4=last4,
    )


def add_wallet_instrument(payer_id, last4="5555") -> dict:
    """WALLET instruments are created ACTIVE immediately."""
    return add_instrument(payer_id, "WALLET", last4=last4)


def add_echeck_instrument(payer_id, last4="9876") -> dict:
    """ECHECK instruments start PENDING_VERIFICATION."""
    return add_instrument(payer_id, "ECHECK", last4=last4)


def verify_ach(instrument_id, payer_id=None, outcome="SUCCESS") -> dict:
    """Report a micro-deposit outcome. When payer_id is given the call runs as
    the owning Payer; otherwise as PlatformAdmin (which bypasses ownership)."""
    headers = _payer(payer_id) if payer_id is not None else PA
    return get_success_data(
        api_client.verify_ach_instrument(instrument_id, verify_ach_payload(outcome), headers)
    )


def add_verified_echeck_instrument(payer_id, last4="9876") -> dict:
    instrument = add_echeck_instrument(payer_id, last4)
    return verify_ach(instrument["id"], payer_id, "SUCCESS")


# ---------------------------------------------------------------------------
# Tier 4: checkout — quotes, authorization, capture
# ---------------------------------------------------------------------------

def create_quote(service_id, payer_id, amount_cents, method) -> dict:
    """The quote's payer_id comes from X-User-ID, so the Payer-role header must
    carry the real payer id."""
    return get_success_data(
        api_client.create_fee_quote(
            create_fee_quote_payload(service_id, amount_cents, method), _payer(payer_id)
        )
    )


def get_quote(quote_id, payer_id=None) -> dict:
    headers = _payer(payer_id) if payer_id is not None else PA
    return get_success_data(api_client.get_fee_quote(quote_id, headers))


def authorize(quote_id, instrument_id, payer_id) -> dict:
    return get_success_data(
        api_client.authorize_payment(
            authorize_payment_payload(quote_id, instrument_id), _payer(payer_id)
        )
    )


def get_transaction(transaction_id) -> dict:
    return get_success_data(api_client.get_transaction(transaction_id, PA))


def pay(service_id, payer_id, instrument_id, amount_cents, method) -> dict:
    """Quote + authorize. Returns {"quote": ..., "transaction": ...}; the
    transaction is AUTHORIZED and the quote CONSUMED."""
    quote = create_quote(service_id, payer_id, amount_cents, method)
    transaction = authorize(quote["id"], instrument_id, payer_id)
    return {"quote": quote, "transaction": transaction}


def capture(transaction_id, as_user_id=AGENCY_ADMIN_LEAD) -> dict:
    return get_success_data(api_client.capture_transaction(transaction_id, _aa(as_user_id)))


def void_transaction(transaction_id, as_user_id=AGENCY_ADMIN_LEAD) -> dict:
    return get_success_data(api_client.void_transaction(transaction_id, _aa(as_user_id)))


def pay_and_capture(
    service_id, payer_id, instrument_id, amount_cents, method, as_user_id=AGENCY_ADMIN_LEAD
) -> dict:
    paid = pay(service_id, payer_id, instrument_id, amount_cents, method)
    paid["transaction"] = capture(paid["transaction"]["id"], as_user_id)
    return paid


# ---------------------------------------------------------------------------
# Tier 5: composite checkout contexts
# ---------------------------------------------------------------------------

def setup_cf_checkout(
    clock=DEFAULT_CLOCK_UTC,
    fee_cap_cents=5000,
    attestation_expires_at="2027-08-01T00:00:00Z",
    attestation_issued_at="2026-08-01T00:00:00Z",
    agency_overrides=None,
    account_overrides=None,
    service_overrides=None,
    authz_overrides=None,
    payer_overrides=None,
    with_payer=True,
    with_card=False,
    card_cost_bucket="CONSUMER_DEBIT",
    with_echeck=False,
    echeck_verified=True,
    with_wallet=False,
) -> dict:
    """The canonical CONVENIENCE_FEE base chain:

    clock -> agency -> settlement account -> treasury verify -> PCI
    attestation -> agency ACTIVE -> CF service -> APPROVED authorization ->
    service ACTIVE -> payer (+ instruments on demand).

    Returns a context dict with keys agency, account, attestation, service,
    authorization and, when requested, payer / card / echeck / wallet.
    """
    set_clock(clock)
    built = setup_active_agency(
        attestation_expires_at=attestation_expires_at,
        attestation_issued_at=attestation_issued_at,
        agency_overrides=agency_overrides,
        account_overrides=account_overrides,
    )
    svc = setup_active_cf_service(
        built["agency"]["id"],
        fee_cap_cents=fee_cap_cents,
        service_overrides=service_overrides,
        authz_overrides=authz_overrides,
    )
    ctx = {
        "agency": built["agency"],
        "account": built["account"],
        "attestation": built["attestation"],
        "service": svc["service"],
        "authorization": svc["authorization"],
    }
    if with_payer:
        payer = register_payer(**(payer_overrides or {}))
        ctx["payer"] = payer
        if with_card:
            ctx["card"] = add_card_instrument(payer["id"], card_cost_bucket=card_cost_bucket)
        if with_echeck:
            if echeck_verified:
                ctx["echeck"] = add_verified_echeck_instrument(payer["id"])
            else:
                ctx["echeck"] = add_echeck_instrument(payer["id"])
        if with_wallet:
            ctx["wallet"] = add_wallet_instrument(payer["id"])
    return ctx


def setup_absorbed_checkout(
    clock=DEFAULT_CLOCK_UTC,
    effective_month="2026-09",
    top_unbounded=True,
    payer=None,
    echeck=None,
    agency_overrides=None,
    service_overrides=None,
) -> dict:
    """The canonical ABSORBED base chain: LOCAL ABSORBED-default agency through
    both activation gates, the standard pricing bands for effective_month, and
    an ACTIVE ECHECK-only absorbed service. Pass an existing payer (and its
    verified ECHECK instrument) to share one payer across agencies; otherwise a
    fresh payer with a verified ECHECK instrument is registered."""
    set_clock(clock)
    agency_over = {
        "legal_name": "County Treasurer",
        "agency_type": "LOCAL",
        "default_fee_model": "ABSORBED",
    }
    agency_over.update(agency_overrides or {})
    built = setup_active_agency(
        agency_overrides=agency_over,
        account_overrides={"routing_number": "103000648", "account_number_last4": "7700"},
    )
    tiers = setup_pricing_bands(
        built["agency"]["id"], effective_month=effective_month, top_unbounded=top_unbounded
    )
    svc = setup_active_absorbed_service(built["agency"]["id"], service_overrides=service_overrides)
    if payer is None:
        payer = register_payer()
    if echeck is None:
        echeck = add_verified_echeck_instrument(payer["id"])
    return {
        "agency": built["agency"],
        "account": built["account"],
        "attestation": built["attestation"],
        "tiers": tiers,
        "service": svc["service"],
        "payer": payer,
        "echeck": echeck,
    }


def setup_open_card_quote(amount_cents=100000, method="CARD", **cf_kwargs) -> dict:
    """CF base chain + card instrument + one OPEN quote."""
    cf_kwargs.setdefault("with_card", True)
    ctx = setup_cf_checkout(**cf_kwargs)
    ctx["quote"] = create_quote(
        ctx["service"]["id"], ctx["payer"]["id"], amount_cents, method
    )
    return ctx


def setup_captured_card(
    amount_cents=100000,
    capture_clock=None,
    capture_as=AGENCY_ADMIN_LEAD,
    with_open_batch=False,
    business_date="2026-09-02",
    **cf_kwargs,
) -> dict:
    """CF base chain + AUTHORIZED-then-CAPTURED card transaction. When
    capture_clock is given the clock moves there before the quote is created,
    so captured_at and value_date derive from it. Optionally leaves an OPEN
    batch for the agency (refund-approval precondition)."""
    # build explicitly: quote creation must happen after any clock move
    cf_kwargs.setdefault("with_card", True)
    ctx = setup_cf_checkout(**cf_kwargs)
    if capture_clock is not None:
        set_clock(capture_clock)
    paid = pay_and_capture(
        ctx["service"]["id"],
        ctx["payer"]["id"],
        ctx["card"]["id"],
        amount_cents,
        "CARD",
        capture_as,
    )
    ctx.update(paid)
    if with_open_batch:
        ctx["batch"] = open_batch(ctx["agency"]["id"], business_date)
    return ctx


def setup_captured_echeck(
    amount_cents=50000, capture_clock=None, capture_as=AGENCY_ADMIN_LEAD, **cf_kwargs
) -> dict:
    """CF base chain + verified ECHECK instrument + CAPTURED echeck
    transaction."""
    cf_kwargs.setdefault("with_echeck", True)
    ctx = setup_cf_checkout(**cf_kwargs)
    if capture_clock is not None:
        set_clock(capture_clock)
    paid = pay_and_capture(
        ctx["service"]["id"],
        ctx["payer"]["id"],
        ctx["echeck"]["id"],
        amount_cents,
        "ECHECK",
        capture_as,
    )
    ctx.update(paid)
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: settlement batches
# ---------------------------------------------------------------------------

def open_batch(agency_id, business_date) -> dict:
    return get_success_data(
        api_client.create_settlement_batch(
            create_settlement_batch_payload(agency_id, business_date), PA
        )
    )


def get_batch(batch_id) -> dict:
    return get_success_data(api_client.get_settlement_batch(batch_id, PA))


def list_batches(agency_id, params=None) -> list:
    return get_success_data(api_client.list_settlement_batches(agency_id, PA, params=params))


def close_batch(batch_id) -> dict:
    """Sweeps every eligible transaction (CAPTURED or RE_PRESENTED, no batch,
    value_date on or before business_date) to SETTLED and finalizes totals."""
    return get_success_data(api_client.close_settlement_batch(batch_id, PA))


def submit_batch(batch_id) -> dict:
    return get_success_data(api_client.submit_settlement_batch(batch_id, PA))


def confirm_batch(batch_id, actual_deposit_cents) -> dict:
    """TreasuryOfficer-only, segregated from the PlatformAdmin that submitted."""
    return get_success_data(
        api_client.confirm_batch_deposit(
            batch_id, confirm_deposit_payload(actual_deposit_cents), TO
        )
    )


def reconcile_batch(batch_id) -> dict:
    return get_success_data(api_client.reconcile_settlement_batch(batch_id, PA))


def open_and_close_batch(agency_id, business_date) -> dict:
    batch = open_batch(agency_id, business_date)
    return close_batch(batch["id"])


def setup_settled_echeck(
    amount_cents=50000,
    capture_clock="2026-09-10T00:00:00Z",
    business_date="2026-09-12",
    **cf_kwargs,
) -> dict:
    """ECHECK transaction captured at capture_clock (value_date = capture date
    + 2 days) and swept to SETTLED by a batch with the given business_date.
    Returns ctx + transaction + batch. The clock is left at capture_clock."""
    ctx = setup_captured_echeck(amount_cents, capture_clock, **cf_kwargs)
    ctx["batch"] = open_and_close_batch(ctx["agency"]["id"], business_date)
    ctx["transaction"] = get_transaction(ctx["transaction"]["id"])
    return ctx


def ach_return(transaction_id) -> dict:
    """PlatformAdmin records an ACH return against a SETTLED or RE_PRESENTED
    ECHECK transaction; when no OPEN batch exists the system auto-creates one
    stamped with the current clock date."""
    return get_success_data(api_client.ach_return_transaction(transaction_id, PA))


def re_present(transaction_id, as_user_id=AGENCY_ADMIN_LEAD) -> dict:
    return get_success_data(api_client.re_present_transaction(transaction_id, _aa(as_user_id)))


def setup_returned_echeck(
    return_clock="2026-09-15T00:00:00Z", amount_cents=50000, **kwargs
) -> dict:
    """Settled ECHECK transaction then ACH-returned at return_clock. The return
    clears current_batch_id and auto-creates an OPEN batch carrying the return
    debit (the settling batch is already CLOSED). Returns ctx + transaction
    (RETURNED) + batch + batches (all agency batches, created_at ASC, so the
    auto-created one is batches[1])."""
    ctx = setup_settled_echeck(amount_cents, **kwargs)
    set_clock(return_clock)
    ctx["transaction"] = ach_return(ctx["transaction"]["id"])
    ctx["batches"] = list_batches(ctx["agency"]["id"])
    return ctx


def setup_submitted_batch(
    amount_cents=100000,
    capture_clock="2026-09-10T00:00:00Z",
    business_date="2026-09-11",
    **cf_kwargs,
) -> dict:
    """Captured card transaction swept into a batch taken OPEN -> CLOSED ->
    SUBMITTED. Confirm is deliberately left to the caller (it is the
    TreasuryOfficer-segregated step under test)."""
    ctx = setup_captured_card(amount_cents, capture_clock, **cf_kwargs)
    batch = open_batch(ctx["agency"]["id"], business_date)
    batch = close_batch(batch["id"])
    ctx["batch"] = submit_batch(batch["id"])
    ctx["transaction"] = get_transaction(ctx["transaction"]["id"])
    return ctx


def setup_exception_batch(
    actual_deposit_cents=99000,
    confirm_clock="2026-09-13T00:00:00Z",
    amount_cents=100000,
    **kwargs,
) -> dict:
    """A batch walked all the way to EXCEPTION: captured card transaction,
    close, submit, then a treasury confirmation of a DIFFERENT amount at
    confirm_clock, then reconcile. With the default clock (two days after the
    due date of 2026-09-11, i.e. past the one-day grace) reconcile raises both
    AMOUNT_MISMATCH and DEPOSIT_LATE; pass confirm_clock="2026-09-12T00:00:00Z"
    to land exactly on the grace boundary so only AMOUNT_MISMATCH is raised.
    Returns ctx + batch (EXCEPTION) + exceptions (created_at ASC, then
    exception_type ASC)."""
    ctx = setup_submitted_batch(amount_cents, **kwargs)
    set_clock(confirm_clock)
    confirm_batch(ctx["batch"]["id"], actual_deposit_cents)
    ctx["batch"] = reconcile_batch(ctx["batch"]["id"])
    ctx["exceptions"] = list_exceptions(ctx["batch"]["id"])
    return ctx


def list_exceptions(batch_id) -> list:
    return get_success_data(api_client.list_batch_exceptions(batch_id, PA))


def resolve_exception(exception_id, resolution_note=None) -> dict:
    return get_success_data(
        api_client.resolve_reconciliation_exception(
            exception_id, resolve_exception_payload(resolution_note), PA
        )
    )


# ---------------------------------------------------------------------------
# Tier 7: refunds and chargebacks
# ---------------------------------------------------------------------------

def request_refund(
    transaction_id, amount_cents, reason="overpayment", initiated_by=AGENCY_ADMIN_LEAD
) -> dict:
    """Born REQUESTED with initiated_by_user_id = the caller's X-User-ID."""
    return get_success_data(
        api_client.create_refund(
            create_refund_payload(transaction_id, amount_cents, reason=reason),
            _aa(initiated_by),
        )
    )


def decide_refund(refund_id, decision="APPROVE", decided_by=AGENCY_ADMIN_PEER) -> dict:
    """The decider must differ from the initiator (segregation of duties);
    APPROVE additionally needs an OPEN batch for the agency."""
    return get_success_data(
        api_client.decide_refund(refund_id, decide_refund_payload(decision), _aa(decided_by))
    )


def approve_refund(
    transaction_id,
    amount_cents,
    reason="overpayment",
    initiated_by=AGENCY_ADMIN_LEAD,
    decided_by=AGENCY_ADMIN_PEER,
) -> dict:
    """Request + approve. The caller must ensure an OPEN batch exists first."""
    refund = request_refund(transaction_id, amount_cents, reason, initiated_by)
    return decide_refund(refund["id"], "APPROVE", decided_by)


def open_chargeback(transaction_id, reason_code="FRAUD") -> dict:
    """Ops-side intake of a card-network chargeback; the case opens OPENED with
    evidence_due_at = opened_at + 10 days."""
    return get_success_data(
        api_client.create_chargeback(create_chargeback_payload(transaction_id, reason_code), PA)
    )


def get_chargeback_via_transaction(transaction_id) -> list:
    return get_success_data(api_client.list_transaction_chargebacks(transaction_id, PA))


def contest_chargeback(case_id, evidence_note=None, as_user_id=AGENCY_ADMIN_LEAD) -> dict:
    return get_success_data(
        api_client.contest_chargeback(
            case_id, contest_chargeback_payload(evidence_note), _aa(as_user_id)
        )
    )


def accept_chargeback(case_id, as_user_id=AGENCY_ADMIN_LEAD) -> dict:
    return get_success_data(api_client.accept_chargeback(case_id, _aa(as_user_id)))


def record_chargeback_outcome(case_id, outcome) -> dict:
    return get_success_data(
        api_client.record_chargeback_outcome(case_id, record_outcome_payload(outcome), PA)
    )


def setup_captured_card_pair(
    amount_a=100000,
    amount_b=100000,
    at_clock=None,
    capture_as=AGENCY_ADMIN_LEAD,
    **cf_kwargs,
) -> dict:
    """Two CAPTURED card transactions for one payer (quotes are consumed
    per-transaction, so each payment creates its own). Used by chargeback
    fork and evidence-deadline tests."""
    cf_kwargs.setdefault("with_card", True)
    ctx = setup_cf_checkout(**cf_kwargs)
    if at_clock is not None:
        set_clock(at_clock)
    first = pay_and_capture(
        ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], amount_a, "CARD", capture_as
    )
    second = pay_and_capture(
        ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], amount_b, "CARD", capture_as
    )
    ctx["quote_a"] = first["quote"]
    ctx["transaction_a"] = first["transaction"]
    ctx["quote_b"] = second["quote"]
    ctx["transaction_b"] = second["transaction"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 8: self-funding period close
# ---------------------------------------------------------------------------

def close_period(period="2026-09") -> dict:
    """TreasuryOfficer closes a YYYY-MM period exactly once."""
    return get_success_data(api_client.close_period(close_period_payload(period), TO))


def list_ledger_entries(period=None) -> list:
    params = {"period": period} if period else None
    return get_success_data(api_client.list_ledger_entries(TO, params=params))


def capture_series(
    service_id,
    payer_id,
    instrument_id,
    amounts,
    method="ECHECK",
    start_clock="2026-09-10T00:00:00Z",
    step_days=1,
    as_user_id=AGENCY_ADMIN_COUNTY,
) -> list:
    """Authorize+capture one transaction per amount, advancing the logical
    clock by step_days between captures so each lands in its own chronological
    slot. Returns the CAPTURED transactions in order."""
    set_clock(start_clock)
    transactions = []
    for i, amount in enumerate(amounts):
        if i > 0 and step_days:
            set_clock(_tick(start_clock, step_days * i))
        paid = pay_and_capture(service_id, payer_id, instrument_id, amount, method, as_user_id)
        transactions.append(paid["transaction"])
    return transactions


def setup_september_pool_scenario() -> dict:
    """The full two-agency September fixture.

    CF agency: CARD 100000 (CONSUMER_DEBIT instrument), ECHECK 50000 and
    WALLET 20000, all captured at clock 2026-09-10. Absorbed agency with the
    standard three bands for 2026-09: three ECHECK captures of 300000 at
    2026-09-10, 2026-09-11 and 2026-09-12, sharing the same payer. Returns
    both contexts plus the captured transaction lists; the clock is left at
    2026-09-12, and no period has been closed yet."""
    cf = setup_cf_checkout(with_card=True, with_echeck=True, with_wallet=True)
    absorbed = setup_absorbed_checkout(payer=cf["payer"], echeck=cf["echeck"])
    set_clock("2026-09-10T00:00:00Z")
    card = pay_and_capture(
        cf["service"]["id"], cf["payer"]["id"], cf["card"]["id"], 100000, "CARD"
    )["transaction"]
    echeck = pay_and_capture(
        cf["service"]["id"], cf["payer"]["id"], cf["echeck"]["id"], 50000, "ECHECK"
    )["transaction"]
    wallet = pay_and_capture(
        cf["service"]["id"], cf["payer"]["id"], cf["wallet"]["id"], 20000, "WALLET"
    )["transaction"]
    absorbed_txns = capture_series(
        absorbed["service"]["id"],
        absorbed["payer"]["id"],
        absorbed["echeck"]["id"],
        [300000, 300000, 300000],
        start_clock="2026-09-10T00:00:00Z",
    )
    return {
        "cf": cf,
        "absorbed": absorbed,
        "card_transaction": card,
        "echeck_transaction": echeck,
        "wallet_transaction": wallet,
        "absorbed_transactions": absorbed_txns,
    }
