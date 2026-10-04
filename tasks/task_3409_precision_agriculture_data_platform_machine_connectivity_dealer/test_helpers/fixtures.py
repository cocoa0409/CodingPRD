"""Composite setup builders for the Precision Ag Connectivity API.

Every builder drives the public API only and returns the ``data`` payload of
a successful response (via ``get_success_data``), so a setup failure surfaces
as a clear assertion error naming the failing call rather than a confusing
downstream test failure.

Layering: ``setup_org_dealer`` -> ``add_machine`` -> ``connect_machine`` ->
``activate_machine_in`` -> ``ingest_batch`` compose into the named scenario
builders (``setup_connected_machine``, ``setup_activated_machine``,
``setup_in_service_machine``, ``setup_machine_with_coverage``,
``setup_delivery_*``, ``setup_open_session``, ``setup_submitted_claim``).
Multi-machine instances call ``add_machine`` / ``connect_machine`` again on
the same context.

Identity threading: after an Organization or Dealer row exists, every
ownership-gated call uses ``make_grower_manager_headers(org["id"])`` or
``make_dealer_technician_headers(dealer["id"])`` — never a shared constant.
The returned context dict carries those header sets under
``grower_headers`` / ``dealer_headers`` for the test to reuse.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_START_UTC
from .test_users import (
    ADMIN,
    SYSTEM,
    INDEPENDENT_USER_ID,
    make_dealer_technician_headers,
    make_grower_manager_headers,
    make_independent_technician_headers,
    make_partner_app_headers,
)


# --- Logical clock ---------------------------------------------------------


def set_clock(client, current_utc, headers=ADMIN):
    """Advance the logical clock; returns the instant it now reads."""
    response = client.set_clock(current_utc, headers=headers)
    get_success_data(response)
    return current_utc


def reset_clock(client, headers=ADMIN):
    """Pin the clock at its startup instant (monotonic, so always legal)."""
    return set_clock(client, CLOCK_START_UTC, headers=headers)


# --- Tier 1: base entities ---------------------------------------------------


def create_org(client, headers=ADMIN, **overrides):
    """Create a grower organization; returns the Organization."""
    return get_success_data(
        client.create_organization(f.create_organization_payload(**overrides), headers=headers)
    )


def create_dealer(client, headers=ADMIN, **overrides):
    """Register a dealer; returns the Dealer (ACTIVE, zeroed warranty totals)."""
    return get_success_data(
        client.create_dealer(f.create_dealer_payload(**overrides), headers=headers)
    )


def setup_org_dealer(client, org_overrides=None, dealer_overrides=None):
    """Organization + dealer context with correctly threaded role headers."""
    org = create_org(client, **(org_overrides or {}))
    dealer = create_dealer(client, **(dealer_overrides or {}))
    return {
        "org": org,
        "dealer": dealer,
        "grower_headers": make_grower_manager_headers(org["id"]),
        "dealer_headers": make_dealer_technician_headers(dealer["id"]),
    }


def add_machine(ctx, client, **overrides):
    """Register a machine for the context org/dealer; lifecycle REGISTERED,
    modem UNPROVISIONED, posture OFFLINE."""
    payload = f.create_machine_payload(
        ctx["org"]["id"], ctx["dealer"]["id"], **overrides
    )
    return get_success_data(
        client.create_machine(payload, headers=ctx["grower_headers"])
    )


# --- Tier 1: modem provisioning ----------------------------------------------


def begin_provisioning(ctx, client, machine_id, headers=None):
    """Begin (or retry) modem provisioning; PROVISIONING, attempts += 1."""
    response = client.provision_modem(
        machine_id, headers=headers or ctx["dealer_headers"]
    )
    return get_success_data(response)


def complete_provisioning(client, machine_id, outcome="PROVISION_SUCCEEDED", headers=SYSTEM):
    """Network-operator callback: PROVISIONING -> PROVISIONED|PROVISION_FAILED."""
    response = client.report_modem_provisioning_event(
        machine_id, outcome, headers=headers
    )
    return get_success_data(response)


def provision_modem_success(ctx, client, machine_id):
    """Begin + succeed; machine's modem ends PROVISIONED."""
    begin_provisioning(ctx, client, machine_id)
    return complete_provisioning(client, machine_id)


# --- Tier 1/2: data plans ------------------------------------------------------


def create_plan(ctx, client, machine_id, tier="STANDARD", proration_method="CALENDAR_DAY"):
    """Create a PENDING plan; returns the DataPlan."""
    payload = f.create_data_plan_payload(
        ctx["org"]["id"], machine_id, tier=tier, proration_method=proration_method
    )
    return get_success_data(
        client.create_data_plan(payload, headers=ctx["grower_headers"])
    )


def activate_plan(ctx, client, plan_id):
    """PENDING -> ACTIVE; anchors the billing cycle at the current clock."""
    return get_success_data(
        client.activate_data_plan(plan_id, headers=ctx["grower_headers"])
    )


def suspend_plan(ctx, client, plan_id, headers=None):
    return get_success_data(
        client.suspend_data_plan(plan_id, headers=headers or ctx["grower_headers"])
    )


def resume_plan(ctx, client, plan_id):
    return get_success_data(
        client.resume_data_plan(plan_id, headers=ctx["grower_headers"])
    )


def read_plan(ctx, client, plan_id, headers=None):
    return get_success_data(
        client.get_data_plan(plan_id, headers=headers or ctx["grower_headers"])
    )


def change_plan_tier(ctx, client, plan_id, new_tier, expected_plan_version=None):
    """OCC-guarded tier change; reads the plan fresh for the version when the
    caller does not pin ``expected_plan_version`` (pin it to test staleness)."""
    if expected_plan_version is None:
        expected_plan_version = read_plan(ctx, client, plan_id)["version"]
    payload = f.change_tier_payload(new_tier, expected_plan_version)
    return get_success_data(
        client.change_data_plan_tier(plan_id, payload, headers=ctx["grower_headers"])
    )


# --- Tier 1/2: machine lifecycle -----------------------------------------------


def activate_machine_in(ctx, client, machine_id, headers=None):
    """Dealer activation handshake: REGISTERED -> ACTIVATED."""
    return get_success_data(
        client.activate_machine(machine_id, headers=headers or ctx["dealer_headers"])
    )


def read_machine(ctx, client, machine_id, headers=None):
    return get_success_data(
        client.get_machine(machine_id, headers=headers or ctx["grower_headers"])
    )


def ingest_batch(ctx, client, machine_id, **batch_overrides):
    """Ingest one telemetry batch as System; returns the Machine from the
    201 response (first accepted batch flips ACTIVATED -> IN_SERVICE)."""
    payload = f.telemetry_batch_payload(**batch_overrides)
    return get_success_data(
        client.telemetry_ingest(machine_id, payload, headers=SYSTEM)
    )


def get_uptime(ctx, client, machine_id, headers=None):
    return get_success_data(
        client.get_uptime_prediction(
            machine_id, headers=headers or ctx["grower_headers"]
        )
    )


# --- Tier 2/3: named machine scenarios ------------------------------------------


def setup_connected_machine(client, tier="STANDARD", proration_method="CALENDAR_DAY",
                            org_overrides=None, dealer_overrides=None,
                            machine_overrides=None):
    """Org + dealer + machine with PROVISIONED modem and an ACTIVE plan:
    posture CONNECTED, lifecycle still REGISTERED."""
    reset_clock(client)
    ctx = setup_org_dealer(client, org_overrides, dealer_overrides)
    ctx["machine"] = add_machine(ctx, client, **(machine_overrides or {}))
    provision_modem_success(ctx, client, ctx["machine"]["id"])
    ctx["plan"] = create_plan(
        ctx, client, ctx["machine"]["id"], tier=tier, proration_method=proration_method
    )
    ctx["plan"] = activate_plan(ctx, client, ctx["plan"]["id"])
    ctx["machine"] = read_machine(ctx, client, ctx["machine"]["id"])
    return ctx


def setup_activated_machine(client, **kwargs):
    """setup_connected_machine + dealer handshake: lifecycle ACTIVATED."""
    ctx = setup_connected_machine(client, **kwargs)
    ctx["machine"] = activate_machine_in(ctx, client, ctx["machine"]["id"])
    return ctx


def setup_in_service_machine(client, batch_overrides=None, **kwargs):
    """setup_activated_machine + one accepted telemetry batch: IN_SERVICE."""
    ctx = setup_activated_machine(client, **kwargs)
    ctx["machine"] = ingest_batch(
        ctx, client, ctx["machine"]["id"], **(batch_overrides or {})
    )
    return ctx


def setup_machine_with_coverage(client, filled_hours=648,
                                clock_after_activation="2026-09-30T00:00:00Z",
                                batch_start="2026-08-31T00:00:00Z",
                                payload_mb=100, **kwargs):
    """Activated machine carried to IN_SERVICE with exactly ``filled_hours``
    consecutive hour-buckets inside the trailing 720-hour window that ends
    at ``clock_after_activation``.  648 buckets scores exactly 90.0; 647
    scores 89.9 (the warranty coverage boundary)."""
    ctx = setup_activated_machine(client, **kwargs)
    set_clock(client, clock_after_activation)
    ctx["machine"] = ingest_batch(
        ctx,
        client,
        ctx["machine"]["id"],
        start_hour_iso=batch_start,
        hour_count=filled_hours,
        payload_mb=payload_mb,
    )
    return ctx


# --- Tier 1/2: fields and prescriptions ------------------------------------------


def create_field(ctx, client, **overrides):
    """Create a DRAFT field boundary."""
    payload = f.create_field_boundary_payload(ctx["org"]["id"], **overrides)
    return get_success_data(
        client.create_field_boundary(payload, headers=ctx["grower_headers"])
    )


def activate_field(ctx, client, field_id):
    """DRAFT -> ACTIVE; bumps the field version."""
    return get_success_data(
        client.activate_field_boundary(field_id, headers=ctx["grower_headers"])
    )


def add_active_field(ctx, client, **overrides):
    """Field boundary carried to ACTIVE (the only state accepting
    prescriptions)."""
    field = create_field(ctx, client, **overrides)
    return activate_field(ctx, client, field["id"])


def read_field(ctx, client, field_id, headers=None):
    return get_success_data(
        client.get_field_boundary(field_id, headers=headers or ctx["grower_headers"])
    )


def create_prescription(ctx, client, field_id, machine_id,
                        expected_field_boundary_version=None, headers=None,
                        **overrides):
    """Create a DRAFT prescription with the OCC guard satisfied; reads the
    field fresh for its version unless the caller pins one (stale tests)."""
    if expected_field_boundary_version is None:
        expected_field_boundary_version = read_field(ctx, client, field_id)["version"]
    payload = f.create_prescription_payload(
        ctx["org"]["id"],
        field_id,
        machine_id,
        expected_field_boundary_version,
        **overrides
    )
    return get_success_data(
        client.create_prescription(payload, headers=headers or ctx["grower_headers"])
    )


def read_prescription(ctx, client, prescription_id, headers=None):
    return get_success_data(
        client.get_prescription(
            prescription_id, headers=headers or ctx["grower_headers"]
        )
    )


def approve_prescription(ctx, client, prescription_id, headers=None):
    return get_success_data(
        client.approve_prescription(
            prescription_id, headers=headers or ctx["grower_headers"]
        )
    )


def revise_prescription(ctx, client, prescription_id, headers=None):
    return get_success_data(
        client.revise_prescription(
            prescription_id, headers=headers or ctx["grower_headers"]
        )
    )


def send_prescription(ctx, client, prescription_id, headers=None):
    return get_success_data(
        client.send_prescription_to_machine(
            prescription_id, headers=headers or ctx["grower_headers"]
        )
    )


def report_as_applied(client, prescription_id, **overrides):
    return get_success_data(
        client.report_prescription_as_applied(
            prescription_id, f.as_applied_payload(**overrides), headers=SYSTEM
        )
    )


def add_approved_prescription(ctx, client, field_id, machine_id, **overrides):
    """Create + approve; the only state that may be sent to the machine."""
    rx = create_prescription(ctx, client, field_id, machine_id, **overrides)
    return approve_prescription(ctx, client, rx["id"])


def add_sent_prescription(ctx, client, field_id, machine_id, **overrides):
    """Create + approve + send; requires the machine posture CONNECTED."""
    rx = add_approved_prescription(ctx, client, field_id, machine_id, **overrides)
    return send_prescription(ctx, client, rx["id"])


# --- Tier 1/2: data share grants ----------------------------------------------------


def create_grant(ctx, client, grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
                 scopes=("TELEMATICS",), **overrides):
    """Create an ACTIVE data share grant; returns the DataShareGrant."""
    payload = f.create_data_share_grant_payload(
        ctx["org"]["id"],
        grantee_type=grantee_type,
        grantee_ref_id=grantee_ref_id,
        scopes=list(scopes),
        **overrides
    )
    return get_success_data(
        client.create_data_share_grant(payload, headers=ctx["grower_headers"])
    )


def read_grant(ctx, client, grant_id, headers=None):
    return get_success_data(
        client.get_data_share_grant(grant_id, headers=headers or ctx["grower_headers"])
    )


def suspend_grant(ctx, client, grant_id):
    return get_success_data(
        client.suspend_data_share_grant(grant_id, headers=ctx["grower_headers"])
    )


def resume_grant(ctx, client, grant_id):
    return get_success_data(
        client.resume_data_share_grant(grant_id, headers=ctx["grower_headers"])
    )


def revoke_grant(ctx, client, grant_id):
    return get_success_data(
        client.revoke_data_share_grant(grant_id, headers=ctx["grower_headers"])
    )


# --- Tier 1/2: consent tickets --------------------------------------------------------


def request_dealer_ticket(ctx, client, machine_id, ticket_type="REMOTE_DIAGNOSTIC"):
    """Dealer-requested consent ticket: requester_ref_id is the dealer id."""
    payload = f.create_consent_ticket_payload(
        ctx["org"]["id"], machine_id, ctx["dealer"]["id"], ticket_type=ticket_type
    )
    return get_success_data(
        client.create_consent_ticket(payload, headers=ctx["dealer_headers"])
    )


def request_independent_ticket(ctx, client, machine_id, user_id=INDEPENDENT_USER_ID,
                               ticket_type="REMOTE_DIAGNOSTIC"):
    """Independent-technician ticket: requester_ref_id is the caller's own
    X-User-ID; the org must have right_to_repair_enabled."""
    payload = f.create_consent_ticket_payload(
        ctx["org"]["id"], machine_id, user_id, ticket_type=ticket_type
    )
    return get_success_data(
        client.create_consent_ticket(
            payload, headers=make_independent_technician_headers(user_id)
        )
    )


def read_ticket(ctx, client, ticket_id, headers=None):
    return get_success_data(
        client.get_consent_ticket(ticket_id, headers=headers or ctx["grower_headers"])
    )


def grant_ticket(ctx, client, ticket_id):
    """REQUESTED -> GRANTED; a bound waiting delivery advances too."""
    return get_success_data(
        client.grant_consent_ticket(ticket_id, headers=ctx["grower_headers"])
    )


def deny_ticket(ctx, client, ticket_id):
    return get_success_data(
        client.deny_consent_ticket(ticket_id, headers=ctx["grower_headers"])
    )


# --- Tier 2/3: diagnostic sessions -----------------------------------------------------


def open_session(ctx, client, machine_id, ticket_id, headers=None):
    """Open a diagnostic session, consuming the GRANTED ticket; defaults to
    the context dealer's headers (dealer session, EXTENDED detail)."""
    payload = f.create_diagnostic_session_payload(machine_id, ticket_id)
    return get_success_data(
        client.create_diagnostic_session(
            payload, headers=headers or ctx["dealer_headers"]
        )
    )


def open_independent_session(ctx, client, machine_id, ticket_id,
                             user_id=INDEPENDENT_USER_ID):
    """Independent session (BASIC detail); caller identity matches the
    ticket's requester_ref_id."""
    return open_session(
        ctx, client, machine_id, ticket_id,
        headers=make_independent_technician_headers(user_id),
    )


def close_session(client, session_id, headers, fault_found=False):
    return get_success_data(
        client.close_diagnostic_session(
            session_id, f.close_session_payload(fault_found=fault_found),
            headers=headers,
        )
    )


def read_session(ctx, client, session_id, headers=None):
    return get_success_data(
        client.get_diagnostic_session(
            session_id, headers=headers or ctx["grower_headers"]
        )
    )


def setup_open_session(client, **kwargs):
    """Connected machine + granted dealer REMOTE_DIAGNOSTIC ticket + an OPEN
    dealer session.  Context gains ``ticket`` and ``session``."""
    ctx = setup_connected_machine(client, **kwargs)
    ctx["ticket"] = request_dealer_ticket(ctx, client, ctx["machine"]["id"])
    grant_ticket(ctx, client, ctx["ticket"]["id"])
    ctx["session"] = open_session(
        ctx, client, ctx["machine"]["id"], ctx["ticket"]["id"]
    )
    return ctx


# --- Tier 1/2: software packages and update deliveries ----------------------------------


def create_package(client, headers=ADMIN, **overrides):
    """Register a DRAFT software package."""
    return get_success_data(
        client.create_software_package(
            f.create_software_package_payload(**overrides), headers=headers
        )
    )


def publish_package(client, package_id, headers=ADMIN):
    return get_success_data(client.publish_software_package(package_id, headers=headers))


def add_published_package(ctx, client, **overrides):
    """Package carried to PUBLISHED (the only state accepting deliveries)."""
    package = create_package(client, **overrides)
    return publish_package(client, package["id"])


def withdraw_package(client, package_id, headers=ADMIN):
    return get_success_data(client.withdraw_software_package(package_id, headers=headers))


def schedule_delivery(client, machine_id, package_id, headers=ADMIN):
    """Schedule a delivery; the response carries the freshly minted
    SOFTWARE_UPDATE consent ticket id under ``consent_ticket_id``."""
    payload = f.create_update_delivery_payload(machine_id, package_id)
    return get_success_data(client.create_update_delivery(payload, headers=headers))


def read_delivery(ctx, client, delivery_id, headers=None):
    return get_success_data(
        client.get_update_delivery(
            delivery_id, headers=headers or ctx["grower_headers"]
        )
    )


def start_download(client, delivery_id, headers=SYSTEM):
    return get_success_data(client.start_update_download(delivery_id, headers=headers))


def report_installed(client, delivery_id, headers=SYSTEM):
    return get_success_data(client.report_update_installed(delivery_id, headers=headers))


def report_failed(client, delivery_id, failure_reason="CRC mismatch", headers=SYSTEM):
    return get_success_data(
        client.report_update_failed(delivery_id, failure_reason, headers=headers)
    )


def setup_delivery_awaiting_consent(client, package_overrides=None, **kwargs):
    """Activated machine + PUBLISHED package + delivery at AWAITING_CONSENT.
    Context gains ``package``, ``delivery`` and ``ticket_id``."""
    ctx = setup_activated_machine(client, **kwargs)
    ctx["package"] = add_published_package(ctx, client, **(package_overrides or {}))
    ctx["delivery"] = schedule_delivery(
        client, ctx["machine"]["id"], ctx["package"]["id"]
    )
    ctx["ticket_id"] = ctx["delivery"]["consent_ticket_id"]
    return ctx


def setup_delivery_consent_granted(client, **kwargs):
    """Delivery advanced to CONSENT_GRANTED by the grower's grant."""
    ctx = setup_delivery_awaiting_consent(client, **kwargs)
    grant_ticket(ctx, client, ctx["ticket_id"])
    return ctx


def setup_delivery_downloading(client, **kwargs):
    """Delivery at DOWNLOADING: consent granted, first start-download done
    (the bound ticket is now CONSUMED)."""
    ctx = setup_delivery_consent_granted(client, **kwargs)
    ctx["delivery"] = start_download(client, ctx["delivery"]["id"])
    return ctx


# --- Tier 1/2: feature licenses ------------------------------------------------------------


def purchase_license(ctx, client, machine_id, feature_code="AUTO_GUIDANCE",
                     license_type="PERPETUAL", term_months=None,
                     expected_machine_version=None):
    """Purchase a license with the machine OCC guard satisfied; reads the
    machine fresh for its version unless the caller pins one (stale tests)."""
    if expected_machine_version is None:
        expected_machine_version = read_machine(ctx, client, machine_id)["version"]
    overrides = {"feature_code": feature_code, "license_type": license_type}
    if term_months is not None:
        overrides["term_months"] = term_months
    payload = f.create_feature_license_payload(
        machine_id, expected_machine_version, **overrides
    )
    return get_success_data(
        client.create_feature_license(payload, headers=ctx["grower_headers"])
    )


def read_license(ctx, client, license_id, headers=None):
    return get_success_data(
        client.get_feature_license(
            license_id, headers=headers or ctx["grower_headers"]
        )
    )


def activate_license(client, license_id, headers=SYSTEM):
    """PURCHASED|SUSPENDED -> ACTIVATED; requires machine posture CONNECTED."""
    return get_success_data(client.activate_feature_license(license_id, headers=headers))


def suspend_license(client, license_id, headers=ADMIN):
    return get_success_data(client.suspend_feature_license(license_id, headers=headers))


def revoke_license(client, license_id, headers=ADMIN):
    return get_success_data(client.revoke_feature_license(license_id, headers=headers))


# --- Tier 3/4: warranty claims ----------------------------------------------------------------


def read_dealer(ctx, client, dealer_id, headers=None):
    return get_success_data(
        client.get_dealer(dealer_id, headers=headers or ctx["dealer_headers"])
    )


def create_claim(ctx, client, machine_id, headers=None, **overrides):
    """Dealer opens a DRAFT warranty claim against an IN_SERVICE machine."""
    payload = f.create_warranty_claim_payload(machine_id, **overrides)
    return get_success_data(
        client.create_warranty_claim(
            payload, headers=headers or ctx["dealer_headers"]
        )
    )


def submit_claim(ctx, client, claim_id, headers=None):
    """DRAFT -> SUBMITTED; reserves the claim amount on the dealer."""
    return get_success_data(
        client.submit_warranty_claim(
            claim_id, headers=headers or ctx["dealer_headers"]
        )
    )


def decide_claim(client, claim_id, decision, headers=ADMIN):
    return get_success_data(
        client.decide_warranty_claim(claim_id, decision, headers=headers)
    )


def settle_claim(client, claim_id, headers=ADMIN):
    return get_success_data(client.settle_warranty_claim(claim_id, headers=headers))


def read_claim(ctx, client, claim_id, headers=None):
    return get_success_data(
        client.get_warranty_claim(claim_id, headers=headers or ctx["dealer_headers"])
    )


def setup_submitted_claim(client, claim_amount_cents=500000,
                          parts_amount_cents=200000, covered_hours=648,
                          **kwargs):
    """IN_SERVICE machine with ``covered_hours`` of coverage (default exactly
    the 90.0 boundary) plus one claim carried DRAFT -> SUBMITTED.  Context
    gains ``claim``."""
    ctx = setup_machine_with_coverage(client, filled_hours=covered_hours, **kwargs)
    ctx["claim"] = create_claim(
        ctx, client, ctx["machine"]["id"],
        claim_amount_cents=claim_amount_cents,
        parts_amount_cents=parts_amount_cents,
    )
    ctx["claim"] = submit_claim(ctx, client, ctx["claim"]["id"])
    return ctx


# --- Tier 1/2: integration partners -------------------------------------------------------------


def create_partner(client, headers=ADMIN, **overrides):
    """Register an integration partner (REGISTERED, calls_today 0)."""
    return get_success_data(
        client.create_integration_partner(
            f.create_integration_partner_payload(**overrides), headers=headers
        )
    )


def certify_partner(client, partner_id, headers=ADMIN):
    """REGISTERED -> CERTIFICATION_REVIEW -> CERTIFIED; sets
    certification_expires_on to the current logical date + 365 days."""
    get_success_data(client.submit_partner_for_certification(partner_id, headers=headers))
    return get_success_data(
        client.decide_partner_certification(partner_id, "CERTIFY", headers=headers)
    )


def setup_certified_partner(client, quota=100):
    """A CERTIFIED partner plus the headers its data-pull must use."""
    partner = create_partner(client, api_quota_calls_per_day=quota)
    partner = certify_partner(client, partner["id"])
    return {
        "partner": partner,
        "partner_headers": make_partner_app_headers(partner["id"]),
    }


def read_partner(ctx, client, partner_id, headers=None):
    if headers is None:
        headers = ctx.get("partner_headers") or ADMIN
    return get_success_data(client.get_integration_partner(partner_id, headers=headers))


def partner_pull(ctx, client, organization_id, scope="TELEMATICS"):
    return get_success_data(
        client.partner_data_pull(
            ctx["partner"]["id"],
            f.data_pull_payload(organization_id, scope),
            headers=ctx["partner_headers"],
        )
    )


# --- Organization lifecycle ----------------------------------------------------------


def suspend_org(client, org_id, headers=ADMIN):
    return get_success_data(client.suspend_organization(org_id, headers=headers))


def resume_org(client, org_id, headers=ADMIN):
    return get_success_data(client.resume_organization(org_id, headers=headers))


def suspend_dealer(client, dealer_id, headers=ADMIN):
    return get_success_data(client.suspend_dealer(dealer_id, headers=headers))
