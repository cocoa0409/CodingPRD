"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Helpers use get_success_data() so setup
failures surface as clear errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_METHODODOLOGY,
    DEFAULT_EVENT_TIME,
    DEFAULT_WEEK_CLOSES_AT,
    DEFAULT_WEEK_OPENS_AT,
)
from .factories import (
    create_chart_payload,
    create_chart_week_payload,
    create_dispute_payload,
    create_label_payload,
    create_methodology_version_payload,
    create_provider_payload,
    create_recurrent_rule_payload,
    create_report_payload,
    create_sale_batch_payload,
    create_signal_payload,
    create_title_payload,
)
from .test_users import (
    TEST_USERS,
    make_chart_manager_headers,
    make_chart_ops_headers,
    make_data_provider_headers,
    make_investigator_headers,
    make_label_rep_headers,
    make_platform_admin_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["chart_manager_headers"]
OPS = TEST_USERS["chart_ops_headers"]


def set_clock(to_iso8601: str):
    """Advance the logical clock."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


def create_recurrent_rule(**overrides):
    resp = api_client.create_recurrent_rule(
        create_recurrent_rule_payload(**overrides), MANAGER)
    return get_success_data(resp)


def create_label(**overrides):
    resp = api_client.create_label(create_label_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_title(label, **overrides):
    """Create a title owned by the given label; LabelRep identity threaded
    as the label's id."""
    payload = create_title_payload(label["id"], **overrides)
    resp = api_client.create_title(payload, make_label_rep_headers(label["id"]))
    return get_success_data(resp)


def create_chart(recurrent_rule_id, **overrides):
    resp = api_client.create_chart(
        create_chart_payload(recurrent_rule_id, **overrides), MANAGER)
    return get_success_data(resp)


def create_methodology_version(chart, **overrides):
    resp = api_client.create_methodology_version(
        chart["id"], create_methodology_version_payload(**overrides), MANAGER)
    return get_success_data(resp)


def activate_methodology(chart, mv):
    """Activate a methodology version, reading the chart's current version
    first so the OCC precondition holds. Returns the activated version."""
    chart_now = get_success_data(api_client.get_chart(chart["id"], MANAGER))
    resp = api_client.activate_methodology_version(
        chart["id"], mv["id"],
        {"expected_chart_version": chart_now["version"]}, MANAGER)
    return get_success_data(resp)


def get_chart(chart_id):
    return get_success_data(api_client.get_chart(chart_id, MANAGER))


def create_week(chart, **overrides):
    resp = api_client.create_chart_week(
        chart["id"], create_chart_week_payload(**overrides), MANAGER)
    return get_success_data(resp)


def create_provider(**overrides):
    resp = api_client.create_provider(create_provider_payload(**overrides), ADMIN)
    return get_success_data(resp)


def submit_report(provider, title_id, week_id, **overrides):
    """Submit a consumption report under the provider's own registration."""
    payload = create_report_payload(title_id, week_id, **overrides)
    resp = api_client.submit_report(
        provider["id"], payload, make_data_provider_headers(provider["id"]))
    return resp


def submit_report_ok(provider, title_id, week_id, **overrides):
    return get_success_data(submit_report(provider, title_id, week_id, **overrides))


def accept_report(report_id):
    resp = api_client.accept_report(report_id, OPS)
    return get_success_data(resp)


def create_sale_batch(title_id, **overrides):
    resp = api_client.create_sale_batch(
        title_id, create_sale_batch_payload(**overrides), OPS)
    return resp


def create_sale_batch_ok(title_id, **overrides):
    return get_success_data(create_sale_batch(title_id, **overrides))


def create_signal(title_id, week_id, ops_user_id=None, **overrides):
    """File a manipulation signal. ops_user_id controls the filer identity
    (defaults to the shared ChartOps operator)."""
    headers = (make_chart_ops_headers(ops_user_id) if ops_user_id else OPS)
    resp = api_client.create_signal(
        create_signal_payload(title_id, week_id, **overrides), headers)
    return get_success_data(resp)


def escalate_signal(signal_id, assigned_to, ops_user_id=None):
    headers = (make_chart_ops_headers(ops_user_id) if ops_user_id else OPS)
    return api_client.escalate_signal(signal_id, {"assigned_to": assigned_to}, headers)


def escalate_signal_ok(signal_id, assigned_to, ops_user_id=None):
    return get_success_data(escalate_signal(signal_id, assigned_to, ops_user_id))


def resolve_investigation(investigation_id, finding, assigned_to, notes="resolved"):
    resp = api_client.resolve_investigation(
        investigation_id, {"finding": finding, "notes": notes},
        make_investigator_headers(assigned_to))
    return resp


def resolve_investigation_ok(investigation_id, finding, assigned_to, notes="resolved"):
    return get_success_data(
        resolve_investigation(investigation_id, finding, assigned_to, notes))


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenario builders
# ---------------------------------------------------------------------------

def setup_chart_with_active_methodology(chart_kind="SINGLES", chart_scope="MAIN",
                                        genre_tag=None, rule_overrides=None,
                                        methodology_overrides=None):
    """Recurrent rule + chart + methodology version activated (ACTIVE).

    Returns (chart, mv, rr). The returned chart dict reflects state BEFORE
    activation; call get_chart(chart["id"]) for the fresh version/pointer.
    """
    rr = create_recurrent_rule(**(rule_overrides or {}))
    chart_kwargs = {"chart_kind": chart_kind, "chart_scope": chart_scope}
    if genre_tag is not None:
        chart_kwargs["genre_tag"] = genre_tag
    chart = create_chart(rr["id"], **chart_kwargs)
    mv = create_methodology_version(chart, **(methodology_overrides or {}))
    activate_methodology(chart, mv)
    return chart, mv, rr


def setup_open_week_scenario(chart_kind="SINGLES", chart_scope="MAIN",
                             genre_tag=None, title_genre="pop",
                             product_kind="TRACK", title_overrides=None,
                             rule_overrides=None, methodology_overrides=None,
                             week_index=1, opens_at=DEFAULT_WEEK_OPENS_AT,
                             closes_at=DEFAULT_WEEK_CLOSES_AT):
    """Label + title + chart with ACTIVE methodology + one OPEN week.

    Returns dict with keys: label, title, chart, mv, rr, week.
    """
    label = create_label()
    title = create_title(label, product_kind=product_kind,
                         genre_tag=title_genre, **(title_overrides or {}))
    chart, mv, rr = setup_chart_with_active_methodology(
        chart_kind=chart_kind, chart_scope=chart_scope, genre_tag=genre_tag,
        rule_overrides=rule_overrides,
        methodology_overrides=methodology_overrides)
    week = create_week(chart, week_index=week_index,
                       opens_at=opens_at, closes_at=closes_at)
    return {"label": label, "title": title, "chart": chart, "mv": mv,
            "rr": rr, "week": week}


def setup_locked_week_with_sales(title_overrides=None, sales_quantity=10,
                                 chart_kind="SINGLES", chart_scope="MAIN",
                                 genre_tag=None, title_genre="pop",
                                 product_kind="TRACK",
                                 rule_overrides=None,
                                 methodology_overrides=None):
    """Full pipeline to a LOCKED week holding one ACCEPTED DOMESTIC SALES
    report for the title.

    Returns dict with keys: label, title, chart, mv, rr, week, provider,
    report.
    """
    scenario = setup_open_week_scenario(
        chart_kind=chart_kind, chart_scope=chart_scope, genre_tag=genre_tag,
        title_genre=title_genre, product_kind=product_kind,
        title_overrides=title_overrides, rule_overrides=rule_overrides,
        methodology_overrides=methodology_overrides)
    provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
    report = submit_report_ok(provider, scenario["title"]["id"],
                              scenario["week"]["id"], component_kind="SALES",
                              quantity=sales_quantity)
    accept_report(report["id"])
    set_clock(scenario["week"]["closes_at"])
    resp = api_client.lock_week(scenario["week"]["id"], MANAGER)
    get_success_data(resp)
    scenario["provider"] = provider
    scenario["report"] = report
    return scenario


def compute_week(week_id):
    resp = api_client.compute_week(week_id, MANAGER)
    return get_success_data(resp)


def publish_week(week_id):
    resp = api_client.publish_week(week_id, MANAGER)
    return get_success_data(resp)


def find_entry(entries, title_id):
    """Return the entry row for a title from a compute/publish response list,
    or None."""
    for entry in entries:
        if entry.get("title_product_id") == title_id:
            return entry
    return None


def get_week(week_id):
    return get_success_data(api_client.get_chart_week(week_id, MANAGER))


def get_title(title_id):
    return get_success_data(api_client.get_title(title_id, MANAGER))


def get_label(label_id):
    return get_success_data(api_client.get_label(label_id, MANAGER))


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, OPS))


def get_dispute(dispute_id):
    return get_success_data(api_client.get_dispute(dispute_id, MANAGER))


def freeze_chart(chart_id, reason="audit"):
    """Freeze a chart, reading its current version for OCC. Returns the
    ChartFreeze."""
    chart_now = get_chart(chart_id)
    resp = api_client.freeze_chart(
        chart_id, {"reason": reason,
                   "expected_chart_version": chart_now["version"]}, MANAGER)
    return get_success_data(resp)


def setup_signal_escalated(signal_kind="ARTIFICIAL_STREAMING",
                           ops_user_id="ops-1", investigator_id="inv-1"):
    """Open-week scenario + signal filed and escalated to an investigation.

    Returns dict with scenario keys plus: signal, investigation.
    """
    scenario = setup_open_week_scenario()
    signal = create_signal(scenario["title"]["id"], scenario["week"]["id"],
                           ops_user_id=ops_user_id, signal_kind=signal_kind)
    investigation = escalate_signal_ok(signal["id"], investigator_id,
                                       ops_user_id=ops_user_id)
    scenario["signal"] = signal
    scenario["investigation"] = investigation
    return scenario


def disqualify_title_via_investigation(title_id, week_id, investigator_id):
    """File -> escalate -> resolve(DISQUALIFY) a signal against a title.

    Returns the closed investigation."""
    signal = create_signal(title_id, week_id)
    investigation = escalate_signal_ok(signal["id"], investigator_id)
    resolve_investigation_ok(investigation["id"], "DISQUALIFY", investigator_id)
    return investigation


def create_dispute_under_review(title, chart, label, claimed_genre=None):
    """File a genre dispute (LabelRep identity = owning label) and move it
    to UNDER_REVIEW. Returns the dispute."""
    payload = create_dispute_payload(
        title["id"], chart["id"], label["id"],
        claimed_genre=claimed_genre or chart["genre_tag"])
    resp = api_client.create_dispute(payload, make_label_rep_headers(label["id"]))
    dispute = get_success_data(resp)
    resp = api_client.review_dispute(dispute["id"], OPS)
    return get_success_data(resp)
