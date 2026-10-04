"""Composite setup helpers (PRD §3 workflows).

Every helper rebuilds its preconditions from scratch through the public API —
each test runs against a freshly restarted server with an empty database and
the logical clock at its default (PRD §2.5). Setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import CLOCK_DEFAULT, EMBARGO_LIFT_AT, U_AWARDS_OFFICER, U_METHODOLOGY_LEAD
from .factories import (
    create_brand_payload,
    create_client_payload,
    create_license_payload,
    create_methodology_payload,
    create_response_payload,
    create_sample_frame_payload,
    create_study_payload,
    create_subscription_payload,
    create_usage_audit_payload,
)
from .test_users import (
    TEST_USERS,
    make_awards_officer_headers,
    make_client_user_headers,
    make_licensing_manager_headers,
    make_methodology_lead_headers,
)

ADMIN = TEST_USERS["study_admin_headers"]
FOPS = TEST_USERS["field_ops_headers"]
LICMGR = TEST_USERS["licensing_manager_headers"]


# ---------------------------------------------------------------------------
# Small steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_DEFAULT):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_study(set_default_clock=True, **overrides) -> dict:
    if set_default_clock:
        set_clock(CLOCK_DEFAULT)
    resp = api_client.create_study(create_study_payload(**overrides), ADMIN)
    return validate_success(resp, expected_status=201)


def pin_methodology(study, pin_user_id=U_METHODOLOGY_LEAD, **mv_overrides) -> dict:
    """Draft a methodology for the study and pin it (OCC on study.version)."""
    ml = make_methodology_lead_headers(pin_user_id)
    mv = validate_success(
        api_client.create_methodology_version(
            create_methodology_payload(study["id"], **mv_overrides), ml
        ),
        expected_status=201,
    )
    pinned = validate_success(
        api_client.pin_methodology_version(
            mv["id"], {"expected_study_version": study["version"]}, ml
        )
    )
    return pinned


def create_study_with_pinned_methodology(set_default_clock=True, pin_user_id=U_METHODOLOGY_LEAD,
                                         mv_overrides=None, **study_overrides) -> dict:
    """Study + pinned methodology. Returns {"study": <fresh>, "mv": pinned mv}."""
    study = create_study(set_default_clock=set_default_clock, **study_overrides)
    mv = pin_methodology(study, pin_user_id=pin_user_id, **(mv_overrides or {}))
    fresh = get_success_data(api_client.get_study(study["id"], ADMIN))
    return {"study": fresh, "mv": mv}


def add_brand(name="BrandA", industry_code="AUTO") -> dict:
    return validate_success(
        api_client.create_brand(create_brand_payload(name=name, industry_code=industry_code), ADMIN),
        expected_status=201,
    )


def add_frame(study_id, brand_id, source_type="PANEL", target_completes=3) -> dict:
    return validate_success(
        api_client.create_sample_frame(
            create_sample_frame_payload(
                study_id, brand_id, source_type=source_type, target_completes=target_completes
            ),
            FOPS,
        ),
        expected_status=201,
    )


def study_goto(study_id, to_status) -> dict:
    return validate_success(
        api_client.study_state(study_id, {"to_status": to_status}, ADMIN)
    )


def open_fielding(study_id) -> dict:
    return study_goto(study_id, "FIELDING")


def close_fielding(study_id) -> dict:
    return study_goto(study_id, "FIELDING_CLOSED")


def ingest(frame_id, token, qual, feat, duration=300, items=15, distinct=4, clock=None) -> dict:
    """Ingest one response; optionally advance the clock first (submitted_at ordering)."""
    if clock is not None:
        set_clock(clock)
    return validate_success(
        api_client.create_response(
            create_response_payload(
                frame_id, token, qual, feat,
                duration_seconds=duration, item_count=items, distinct_values=distinct,
            ),
            FOPS,
        ),
        expected_status=201,
    )


def compute_scores(study_id, as_user_id=U_AWARDS_OFFICER) -> dict:
    return validate_success(
        api_client.compute_scoring(study_id, make_awards_officer_headers(as_user_id))
    )


def determine_awards(study_id, as_user_id=U_AWARDS_OFFICER) -> dict:
    return validate_success(
        api_client.determine_awards(study_id, make_awards_officer_headers(as_user_id)),
        expected_status=201,
    )


def publish_study(study_id, at=EMBARGO_LIFT_AT) -> dict:
    set_clock(at)
    return study_goto(study_id, "PUBLISHED")


def register_client(name="ClientA", brand_id=None, client_type="BRAND", country="US") -> dict:
    payload = create_client_payload(name=name, client_type=client_type, country=country)
    if brand_id is not None:
        payload["brand_id"] = brand_id
    return validate_success(api_client.create_client(payload, ADMIN), expected_status=201)


def quote_license(award_id, client_id, tier="DIGITAL", term_months=12, markets_count=1) -> dict:
    return validate_success(
        api_client.create_license(
            create_license_payload(
                award_id, client_id, tier=tier, term_months=term_months, markets_count=markets_count
            ),
            LICMGR,
        ),
        expected_status=201,
    )


def license_goto(license_id, to_status) -> dict:
    return validate_success(
        api_client.license_state(license_id, {"to_status": to_status}, LICMGR)
    )


def activate_license(license_id) -> dict:
    return license_goto(license_id, "ACTIVE")


def file_audit(license_id, severity="MINOR", note="audit note") -> dict:
    return validate_success(
        api_client.create_usage_audit(
            create_usage_audit_payload(license_id, severity=severity, note=note), LICMGR
        ),
        expected_status=201,
    )


def audit_goto(audit_id, to_status) -> dict:
    return validate_success(
        api_client.usage_audit_state(audit_id, {"to_status": to_status}, LICMGR)
    )


def create_subscription(client_id, study_id, tier="DIAGNOSTIC",
                        starts_at="2026-09-01T00:00:00Z", ends_at="2027-08-31T00:00:00Z") -> dict:
    """Create a TRIAL subscription as the owning ClientUser."""
    return validate_success(
        api_client.create_subscription(
            create_subscription_payload(
                client_id, study_id, tier=tier, starts_at=starts_at, ends_at=ends_at
            ),
            make_client_user_headers(client_id),
        ),
        expected_status=201,
    )


def activate_subscription(subscription_id, client_id) -> dict:
    return validate_success(
        api_client.subscription_state(
            subscription_id, {"to_status": "ACTIVE"}, make_client_user_headers(client_id)
        )
    )


def create_active_subscription(client_id, study_id, tier="DIAGNOSTIC",
                               starts_at="2026-09-01T00:00:00Z",
                               ends_at="2027-08-31T00:00:00Z") -> dict:
    sub = create_subscription(client_id, study_id, tier=tier, starts_at=starts_at, ends_at=ends_at)
    return activate_subscription(sub["id"], client_id)


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_fielding_study(min_sample=3, brands=None, tie_epsilon=3, weights=None,
                         study_code="VDS-2026", cycle_year=2026, embargo_lift_at=EMBARGO_LIFT_AT,
                         prior_study_id=None, change_class="FULL_COMPARABLE",
                         min_duration=180, straightline=12, pin_user_id=U_METHODOLOGY_LEAD,
                         set_default_clock=True) -> dict:
    """Study with pinned methodology, frames, FIELDING open, responses ingested.

    brands: list of dicts, each:
      {"name", "source_type" ("PANEL"), "target" (3),
       "responses": [{"token", "qual", "feat", "duration"=300, "items"=15,
                      "distinct"=4, "clock"=None}]}
    Returns {"study", "mv", "brands": {name: brand}, "frames": {name: frame},
             "responses": [response, ...]}.
    """
    study_kwargs = dict(
        code=study_code, cycle_year=cycle_year, min_sample_per_brand=min_sample,
        embargo_lift_at=embargo_lift_at,
    )
    if prior_study_id is not None:
        study_kwargs["prior_study_id"] = prior_study_id
    mv_overrides = dict(change_class=change_class, tie_epsilon=tie_epsilon,
                        min_duration_seconds=min_duration, straightline_min_items=straightline)
    if weights is not None:
        mv_overrides["factors"] = [
            {"code": code, "name": name, "weight_bp": weight, "ordinal": i + 1}
            for i, (code, name, weight) in enumerate(weights)
        ]
    ctx = create_study_with_pinned_methodology(
        set_default_clock=set_default_clock, pin_user_id=pin_user_id,
        mv_overrides=mv_overrides, **study_kwargs,
    )
    study = ctx["study"]
    ctx["brands"] = {}
    ctx["frames"] = {}
    ctx["responses"] = []
    for spec in (brands or []):
        if "brand_id" in spec:
            brand = get_success_data(api_client.get_brand(spec["brand_id"], ADMIN))
        else:
            brand = add_brand(spec["name"])
        ctx["brands"][spec["name"]] = brand
        frame = add_frame(study["id"], brand["id"],
                          source_type=spec.get("source_type", "PANEL"),
                          target_completes=spec.get("target", 3))
        ctx["frames"][spec["name"]] = frame
    open_fielding(study["id"])
    for spec in (brands or []):
        frame = ctx["frames"][spec["name"]]
        for r in spec.get("responses", []):
            ctx["responses"].append(
                ingest(
                    frame["id"], r["token"], r["qual"], r["feat"],
                    duration=r.get("duration", 300), items=r.get("items", 15),
                    distinct=r.get("distinct", 4), clock=r.get("clock"),
                )
            )
    ctx["study"] = get_success_data(api_client.get_study(study["id"], ADMIN))
    return ctx


def setup_scored_study(**kwargs) -> dict:
    """Fielding study driven FIELDING_CLOSED -> SCORING -> SCORED."""
    ctx = setup_fielding_study(**kwargs)
    sid = ctx["study"]["id"]
    close_fielding(sid)
    study_goto(sid, "SCORING")
    ctx["compute"] = compute_scores(sid)
    ctx["study"] = get_success_data(api_client.get_study(sid, ADMIN))
    return ctx


def setup_awards_set_study(determine_user_id=U_AWARDS_OFFICER, **kwargs) -> dict:
    """Study driven through award determination (AWARDS_SET)."""
    ctx = setup_scored_study(**kwargs)
    sid = ctx["study"]["id"]
    ctx["determine"] = determine_awards(sid, as_user_id=determine_user_id)
    ctx["awards"] = get_success_data(api_client.list_awards(ADMIN, params={"study_id": sid}))
    ctx["study"] = get_success_data(api_client.get_study(sid, ADMIN))
    return ctx


def setup_published_study(publish_at=EMBARGO_LIFT_AT, **kwargs) -> dict:
    """Full canonical chain through PUBLISHED. ctx["award"] is the first award."""
    ctx = setup_awards_set_study(**kwargs)
    sid = ctx["study"]["id"]
    publish_study(sid, at=publish_at)
    ctx["study"] = get_success_data(api_client.get_study(sid, ADMIN))
    ctx["awards"] = get_success_data(api_client.list_awards(ADMIN, params={"study_id": sid}))
    ctx["award"] = ctx["awards"][0] if ctx["awards"] else None
    return ctx


def get_brand_result_for(study_id, brand_id, headers=None) -> dict:
    """Fetch the single BrandResult for (study, brand)."""
    rows = get_success_data(
        api_client.list_brand_results(headers or ADMIN,
                                      params={"study_id": study_id, "brand_id": brand_id})
    )
    matches = [r for r in rows if r["brand_id"] == brand_id]
    assert len(matches) == 1, f"expected exactly one BrandResult for brand {brand_id}, got {len(matches)}"
    return matches[0]


def list_brand_results_for(study_id, headers=None) -> list:
    return get_success_data(
        api_client.list_brand_results(headers or ADMIN, params={"study_id": study_id})
    )


def list_frame_responses(frame_id, quality_status=None, headers=None) -> list:
    params = {}
    if quality_status:
        params["quality_status"] = quality_status
    return get_success_data(
        api_client.list_frame_responses(frame_id, headers or FOPS, params=params or None)
    )


def list_awards_for(study_id, headers=None) -> list:
    return get_success_data(api_client.list_awards(headers or ADMIN, params={"study_id": study_id}))


def get_license(license_id, headers=None) -> dict:
    return get_success_data(api_client.get_license(license_id, headers or LICMGR))


def get_frame(frame_id, headers=None) -> dict:
    return get_success_data(api_client.get_sample_frame(frame_id, headers or FOPS))


def get_study(study_id, headers=None) -> dict:
    return get_success_data(api_client.get_study(study_id, headers or ADMIN))
