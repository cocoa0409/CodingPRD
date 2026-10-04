"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures raise
clear "Setup step failed" errors instead of confusing assertion failures.

Identity threading: after a provider row is created, ownership-gated calls made
as the ServiceProvider role use `make_service_provider_headers(provider_id)` —
never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_PAST_WEEK,
    TEST_DEFAULTS,
    WEEK_START,
)
from .factories import (
    create_agreement_payload,
    create_chargeback_claim_payload,
    create_deduction_payload,
    create_dispute_payload,
    create_driver_payload,
    create_insurance_policy_payload,
    create_performance_metric_payload,
    create_route_assignment_payload,
    create_service_area_payload,
    create_service_provider_payload,
    create_settlement_period_payload,
    create_stop_observation_payload,
    create_vehicle_payload,
)
from .test_users import TEST_USERS, make_service_provider_headers

AM = TEST_USERS["account_manager_headers"]
SA = TEST_USERS["settlement_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PA = TEST_USERS["platform_admin_headers"]



# ── Clock ─────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PlatformAdmin only, §2.12)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, PA))


def read_clock() -> dict:
    return get_success_data(api_client.get_current_utc(PA))


# ── Tier 1: State progression ─────────────────────────────────────

def create_provider(legal_name=None, tax_id=None, provider_type=None, **kw):
    """Register a ServiceProvider (born UNDER_REVIEW)."""
    payload = create_service_provider_payload(
        legal_name=legal_name or TEST_DEFAULTS["LEGAL_NAME"],
        tax_id=tax_id or TEST_DEFAULTS["TAX_ID"],
    )
    if provider_type is not None:
        payload["provider_type"] = provider_type
    payload.update(kw)
    return get_success_data(api_client.create_service_provider(payload, AM))


def create_area(area_code=None, state_code=None, zip_low=None, zip_high=None,
                stop_capacity=None, **kw):
    """Create a ServiceArea (born UNASSIGNED)."""
    payload = create_service_area_payload(
        area_code=area_code or TEST_DEFAULTS["AREA_CODE"],
        state_code=state_code or TEST_DEFAULTS["STATE_CODE"],
        zip_prefix_low=zip_low or TEST_DEFAULTS["ZIP_LOW"],
        zip_prefix_high=zip_high or TEST_DEFAULTS["ZIP_HIGH"],
        stop_capacity_weekly=stop_capacity if stop_capacity is not None
        else TEST_DEFAULTS["STOP_CAPACITY"],
    )
    payload.update(kw)
    return get_success_data(api_client.create_service_area(payload, AM))


def file_and_verify_policy(provider_id, coverage_cents=None, expires_at=None,
                           policy_type="AUTO_LIABILITY", verify=True, **kw):
    """File an insurance certificate (as the provider) and verify it (as ComplianceOfficer)."""
    payload = create_insurance_policy_payload(
        provider_id,
        policy_type=policy_type,
        coverage_cents=coverage_cents if coverage_cents is not None
        else TEST_DEFAULTS["POLICY_COVERAGE_CENTS"],
        expires_at=expires_at or TEST_DEFAULTS["POLICY_EXPIRES_AT"],
    )
    payload.update(kw)
    policy = get_success_data(
        api_client.create_insurance_policy(payload, make_service_provider_headers(provider_id))
    )
    if verify:
        policy = get_success_data(api_client.verify_insurance_policy(policy["id"], CO))
    return policy


def create_and_activate_vehicle(provider_id, area_id, **kw):
    """Create a vehicle and bring it into the ACTIVE fleet."""
    payload = create_vehicle_payload(provider_id, area_id, **kw)
    vehicle = get_success_data(api_client.create_vehicle(payload, AM))
    return get_success_data(api_client.activate_vehicle(vehicle["id"], AM))


def create_and_qualify_driver(provider_id, area_id, license_class="CLASS_B",
                              qualification_status="QUALIFIED", **kw):
    """Create a driver and record its qualification finding."""
    payload = create_driver_payload(
        provider_id, area_id,
        license_class=license_class,
        qualification_status=qualification_status,
        **kw,
    )
    driver = get_success_data(api_client.create_driver(payload, AM))
    driver = get_success_data(
        api_client.qualify_driver(driver["id"], {"qualification_status": qualification_status}, CO)
    )
    return driver


def approve_provider(provider_id, expect_success=True):
    """Approve a provider whose insurance and branding gates have cleared."""
    res = api_client.approve_service_provider(provider_id, AM)
    if expect_success:
        return get_success_data(res)
    return res


def draft_and_sign_agreement(provider_id, area_id, **kw):
    """Draft an agreement, submit it as the provider, sign it as AccountManager."""
    payload = create_agreement_payload(provider_id, area_id, **kw)
    agreement = get_success_data(api_client.create_agreement(payload, AM))
    get_success_data(
        api_client.submit_agreement(agreement["id"], make_service_provider_headers(provider_id))
    )
    return get_success_data(api_client.sign_agreement(agreement["id"], AM))


# ── Tier 2: Full provider + area + agreement + active title ────────

def setup_provider_compliance(provider_id, area_id, vehicle_class="BOX_TRUCK",
                              gvwr_pounds=26000, coverage_cents=None, expires_at=None,
                              driver_license_class="CLASS_B", approve=True):
    """Give a provider a verified AUTO_LIABILITY policy, one activated PASSED vehicle
    and one qualified driver, then approve it. Returns (policy, vehicle, driver).

    Pass approve=False to stop short of the approval call when the test needs to
    drive that transition itself (e.g. to observe the role gate)."""
    policy = file_and_verify_policy(provider_id, coverage_cents=coverage_cents,
                                    expires_at=expires_at)
    vehicle = create_and_activate_vehicle(provider_id, area_id, vehicle_class=vehicle_class,
                                          gvwr_pounds=gvwr_pounds)
    driver = create_and_qualify_driver(provider_id, area_id, license_class=driver_license_class)
    if approve:
        approve_provider(provider_id)
    return policy, vehicle, driver


def setup_active_provider(title_prefix="Acme"):
    """Provider A APPROVED with a PASSED vehicle, QUALIFIED CLASS_B driver and a
    VERIFIED AUTO_LIABILITY policy on area A1, holding an ACTIVE title with an
    ACTIVE agreement over A1.

    Returns dict with keys: provider, area, agreement, assignment, vehicle, driver, policy.
    """
    provider = create_provider(legal_name=f"{title_prefix} Route Services LLC")
    area = create_area()
    policy, vehicle, driver = setup_provider_compliance(provider["id"], area["id"])
    agreement = draft_and_sign_agreement(provider["id"], area["id"])
    area_now = get_success_data(api_client.get_service_area(area["id"], AM))
    assignment = get_success_data(api_client.create_route_assignment(
        create_route_assignment_payload(area["id"], provider["id"], area_now["version"]), AM
    ))
    assignment = get_success_data(api_client.activate_route_assignment(assignment["id"], AM))
    return {
        "provider": provider,
        "area": area,
        "agreement": agreement,
        "assignment": assignment,
        "vehicle": vehicle,
        "driver": driver,
        "policy": policy,
    }


def setup_two_approved_providers():
    """Provider A (with an ACTIVE title over area A1) and Provider B APPROVED and
    ready to acquire. Returns dict with provider_a, provider_b, area, agreement,
    assignment."""
    base = setup_active_provider("Acme")
    provider_b = create_provider(legal_name="Northgate Logistics Partner LLC", tax_id="27-1000003")
    # Provider B needs an approved posture with its own coverage to pass the acquirer gate.
    file_and_verify_policy(provider_b["id"])
    approve_provider(provider_b["id"])
    base["provider_b"] = provider_b
    return base


def setup_two_approved_providers_after_transfer():
    """Provider A, Provider B and a title already pending transfer over area A1.

    The A1 title is ACTIVE over A1 and Provider B is the APPROVED acquirer the
    provider named when it opened the sale, so the title sits in PENDING_TRANSFER
    with the governing agreement moved to RE_NEGOTIATION.

    Returns dict with provider, provider_b, area, agreement, assignment.
    """
    base = setup_active_provider("Acme")
    provider_b = create_provider(legal_name="Northgate Logistics Partner LLC", tax_id="27-1000003")
    file_and_verify_policy(provider_b["id"])
    approve_provider(provider_b["id"])
    base["provider_b"] = provider_b

    # Reach PENDING_TRANSFER through the endpoint that owns that transition, so
    # the server state (not just the local dict) carries the pending sale.
    assignment = get_success_data(api_client.request_transfer(
        base["assignment"]["id"],
        {"acquiring_provider_id": provider_b["id"], "transfer_price_cents": 4500000},
        make_service_provider_headers(base["provider"]["id"]),
    ))
    base["assignment"] = assignment
    return base


# ── Tier 3: Settlement week lifecycle ──────────────────────────────

def open_week(provider_id, area_id, week_start=None, is_peak_week=False,
              fuel_rate_cents_per_mile=None, **kw):
    """Open a settlement week against the provider's current version (§2.11)."""
    provider_now = get_success_data(api_client.get_service_provider(provider_id, SA))
    payload = create_settlement_period_payload(
        provider_id, area_id, provider_now["version"],
        week_start_at=week_start or WEEK_START,
        is_peak_week=is_peak_week,
        fuel_rate_cents_per_mile=(fuel_rate_cents_per_mile
                                  if fuel_rate_cents_per_mile is not None
                                  else TEST_DEFAULTS["FUEL_RATE_CENTS_PER_MILE"]),
    )
    payload.update(kw)
    return get_success_data(api_client.create_settlement_period(payload, SA))


def add_observation(period_id, **kw):
    payload = create_stop_observation_payload(**kw)
    return get_success_data(api_client.create_stop_observation(period_id, payload, SA))


def add_deduction(period_id, deduction_type, amount_cents, **kw):
    payload = create_deduction_payload(deduction_type, amount_cents, **kw)
    return get_success_data(api_client.create_deduction(period_id, payload, SA))


def compose_metric(provider_id, service_score, safety_score, customer_experience_score):
    """Record a scorecard and compose it. Returns the composed metric."""
    metric = get_success_data(api_client.create_performance_metric(
        create_performance_metric_payload(
            provider_id,
            service_score=service_score,
            safety_score=safety_score,
            customer_experience_score=customer_experience_score,
        ), SA
    ))
    return get_success_data(api_client.compose_performance_metric(metric["id"], SA))


def close_accrual(period_id, expect_success=True):
    res = api_client.close_accrual(period_id, SA)
    if expect_success:
        return get_success_data(res)
    return res


def reconcile(period_id, deduction_order=None, allow_over_cap=None, expect_success=True):
    payload = {}
    if deduction_order is not None:
        payload["deduction_order"] = deduction_order
    if allow_over_cap is not None:
        payload["allow_over_cap"] = allow_over_cap
    res = api_client.reconcile_period(period_id, payload, SA)
    if expect_success:
        return get_success_data(res)
    return res


def setup_reconciled_week(provider=None, area=None, agreement=None, assignment=None,
                          week_start=None, is_peak_week=False,
                          observation_overrides=None, deductions=None,
                          metric_scores=None, close_clock=CLOCK_PAST_WEEK,
                          reconcile_kwargs=None):
    """Build an already-RECONCILED settlement week.

    Preamble: provider + area + agreement + ACTIVE title (reused if supplied),
    open week -> post one observation -> post deductions -> metric -> close-accrual -> reconcile.

    Returns dict: provider, area, agreement, assignment, period, observations, deductions.
    """
    if provider is None:
        base = setup_active_provider()
        provider, area, agreement, assignment = (
            base["provider"], base["area"], base["agreement"], base["assignment"]
        )
    period = open_week(provider["id"], area["id"], week_start=week_start,
                       is_peak_week=is_peak_week)
    obs = add_observation(period["id"], **(observation_overrides or {}))
    deduction_rows = []
    for d in (deductions or []):
        deduction_rows.append(add_deduction(period["id"], **d))
    if metric_scores is not None:
        compose_metric(provider["id"], *metric_scores)
    set_clock(close_clock)
    close_accrual(period["id"])
    period = reconcile(period["id"], **(reconcile_kwargs or {}))
    return {
        "provider": provider,
        "area": area,
        "agreement": agreement,
        "assignment": assignment,
        "period": period,
        "observations": [obs],
        "deductions": deduction_rows,
    }


def setup_open_week_with_provider(provider=None, area=None, week_start=None,
                                  is_peak_week=False, stops=None, packages=None,
                                  accessorial_cents=None, with_agreement=True,
                                  with_assignment=True):
    """Provider A APPROVED (optionally with agreement and ACTIVE title) plus an OPEN week."""
    if provider is None:
        base = setup_active_provider()
        provider, area = base["provider"], base["area"]
        agreement, assignment = base["agreement"], base["assignment"]
    else:
        agreement = assignment = None
    period = open_week(provider["id"], area["id"], week_start=week_start,
                       is_peak_week=is_peak_week)
    return {
        "provider": provider,
        "area": area,
        "agreement": agreement,
        "assignment": assignment,
        "period": period,
    }


def setup_disputed_week(provider=None, area=None, week_start=None,
                        observation_overrides=None, deductions=None,
                        metric_scores=None, reason_code="DEDUCTION",
                        disputed_amount_cents=3000):
    """Reach a RECONCILED week, then file a dispute so the week is DISPUTED.

    Returns dict with provider, area, agreement, assignment, period, dispute.
    """
    ctx = setup_reconciled_week(
        provider=provider, area=area, week_start=week_start,
        observation_overrides=observation_overrides, deductions=deductions,
        metric_scores=metric_scores,
    )
    dispute = get_success_data(api_client.dispute_period(
        ctx["period"]["id"],
        create_dispute_payload(reason_code=reason_code,
                               disputed_amount_cents=disputed_amount_cents),
        make_service_provider_headers(ctx["provider"]["id"]),
    ))
    ctx["dispute"] = dispute
    return ctx


def file_and_approve_claim(period_id, provider_id, claim_type="DAMAGE",
                           amount_cents=20000, recovery_rate_pct=0, **kw):
    """File a charge-back claim and approve it."""
    payload = create_chargeback_claim_payload(
        provider_id, period_id, claim_type=claim_type, amount_cents=amount_cents,
        recovery_rate_pct=recovery_rate_pct, **kw,
    )
    claim = get_success_data(api_client.create_chargeback_claim(payload, AM))
    return get_success_data(api_client.approve_chargeback_claim(claim["id"], AM))

# ── Record-driven scenario runner ──────────────────────────────────
# The design indices express each scenario as a structured chain of API calls
# with ${var} interpolation and $.path captures. This runner executes such a
# chain verbatim so a translated test reproduces the index's scenario exactly.

_ROLE_HEADERS = {
    "AccountManager": AM,
    "SettlementAnalyst": SA,
    "ComplianceOfficer": CO,
    "PlatformAdmin": PA,
}


def _resolve(value, captures):
    """Substitute ${var} references inside a payload value."""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            name = value[2:-1]
            return captures[name]
        out = value
        for key, val in captures.items():
            out = out.replace("${" + key + "}", str(val))
        return out
    if isinstance(value, dict):
        return {k: _resolve(v, captures) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, captures) for v in value]
    return value


def _jsonpath(payload, expr):
    """Read a small subset of JSONPath: $.a.b.c."""
    cur = payload
    for part in expr.lstrip("$").lstrip(".").split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _headers_for(call, captures):
    role = call["as"]
    user_id = call.get("as_user_id")
    if user_id is not None:
        from prd_bench_local_runner.testing import build_user_headers
        if isinstance(user_id, str) and user_id.startswith("${"):
            user_id = _resolve(user_id, captures)
        return build_user_headers(str(user_id), role)
    return _ROLE_HEADERS[role]


def run_call_chain(calls, captures):
    """Execute a list of structured API calls, recording captures and responses."""
    from .api_client import api_client as _c
    results = []
    for call in calls:
        spec = call["call"]
        method, path = spec.split(" ", 1)
        # The path carries ${var} references just as payloads do (e.g.
        # "POST /route-settlement/insurance-policies/${pol_a_id}/verify");
        # without this substitution the literal placeholder is sent as a path id.
        path = _resolve(path, captures)
        payload = _resolve(call.get("payload", {}) or {}, captures)
        headers = _headers_for(call, captures)
        if method.upper() in ("GET", "DELETE"):
            response = _c._request(method, path, headers=headers, params=payload or None)
        else:
            response = _c._request(method, path, payload, headers)
        results.append((spec, response))
        for var, expr in (call.get("captures") or {}).items():
            body = response.json()
            captures[var] = _jsonpath(body, expr)
        assert response.status_code < 400 or call.get("captures"), (
            f"Setup call {spec} failed with HTTP {response.status_code}: {response.text}"
        )
    return results


def run_scenario(record):
    """Execute a design-index `test_recipe` (setup_api_calls then trigger).

    Returns (captures: dict, trigger_results: list[(call, Response)]).
    """
    captures = {}
    run_call_chain(record.get("setup_api_calls", []) or [], captures)
    trigger_results = run_call_chain(record.get("trigger", []) or [], captures)
    return captures, trigger_results


def vars_for(record):
    """Pre-scan a recipe's declared `captures` so a test can reference ${names}
    even before running it."""
    names = set()
    for call in (record.get("setup_api_calls", []) or []) + (record.get("trigger", []) or []):
        names.update((call.get("captures") or {}).keys())
    return names
