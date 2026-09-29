"""Component inventory, dependencies, platform implementations, a11y evidence
(PRD 3.3, 3.4, 3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
import errors
from auth import (CONTRIBUTING_TEAM, DESIGN_SYSTEM_LEAD, SYSTEM_ADMIN, actor_id,
                  ensure_owner, require_roles)
from entities import (audit_json, component_json, dependency_json, get_component,
                      get_dependency, get_impl, get_team, impl_json)
from errors import fail
from responses import created, ok
from routes.common import respond_list
from store import sort_created_asc, store
from validation import (body, opt_decimal, opt_enum, pagination, query_enum,
                        query_string, req_decimal, req_enum, req_int, req_semver,
                        req_string)

bp = Blueprint("components", __name__, url_prefix="/design-system")

DOCS_STATES = ("MISSING", "DRAFT", "PUBLISHED")
MATURITY_LEVELS = ("EXPERIMENTAL", "BETA", "STABLE")
LIFECYCLE_STATES = ("ACTIVE", "DEPRECATION_ANNOUNCED", "SUNSET", "REMOVED")
COVERAGE_STATES = ("NONE", "WEB_ONLY", "MOBILE_ONLY", "PARTIAL", "FULL")
PLATFORMS = ("WEB", "IOS", "ANDROID")
IMPL_STATUSES = ("PLANNED", "SHIPPED", "BLOCKED", "RETIRED")
COMPATIBILITY_STATES = ("COMPATIBLE", "INCOMPATIBLE", "SUNSET_PROVIDER")
DIRECTIONS = ("ALL", "CONSUMES", "PROVIDES")
AUDIT_METHODS = ("AUTOMATED", "MANUAL")
WCAG_LEVELS = ("A", "AA", "AAA")


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------
@bp.post("/components")
@require_roles(DESIGN_SYSTEM_LEAD, SYSTEM_ADMIN)
def create_component():
    payload = body()
    name = req_string(payload, "name", 1, 120)
    slug = req_string(payload, "slug", 1, 120)
    owning_team_id = req_string(payload, "owning_team_id", 1, 200)
    docs_state = opt_enum(payload, "docs_state", DOCS_STATES, "MISSING")

    get_team(owning_team_id)

    for existing in store.components.values():
        if existing["slug"] == slug:
            fail(errors.ERR_UNIQUENESS_CONFLICT,
                 "A component with slug '%s' already exists." % slug)

    row = store.new_row()
    row.update({
        "name": name,
        "slug": slug,
        "owning_team_id": owning_team_id,
        "maturity_level": "EXPERIMENTAL",
        "lifecycle_state": "ACTIVE",
        "current_major_version": 1,
        "docs_state": docs_state,
        "docs_last_reviewed_at": store.now_iso if docs_state == "PUBLISHED" else None,
        "shipped_platform_count": 0,
        "coverage_state": "NONE",
        "governance_conformance_score": Decimal("0.00"),
        "conformance_baseline_at": store.now_iso,
        "_baseline_dt": store.now,
        "blocked_dependency_count": 0,
        "pending_breaking_change_count": 0,
        "maturity_demotion_reason": "NONE",
        "one_off_exception_count": 0,
    })
    store.components[row["id"]] = row
    return created(component_json(row))


@bp.get("/components")
@require_roles()
def list_components():
    limit, offset = pagination()
    owning_team_id = query_string("owning_team_id")
    maturity_level = query_enum("maturity_level", MATURITY_LEVELS)
    lifecycle_state = query_enum("lifecycle_state", LIFECYCLE_STATES)
    coverage_state = query_enum("coverage_state", COVERAGE_STATES)

    rows = list(store.components.values())
    if owning_team_id is not None:
        rows = [c for c in rows if c["owning_team_id"] == owning_team_id]
    if maturity_level is not None:
        rows = [c for c in rows if c["maturity_level"] == maturity_level]
    if lifecycle_state is not None:
        rows = [c for c in rows if c["lifecycle_state"] == lifecycle_state]
    if coverage_state is not None:
        rows = [c for c in rows if c["coverage_state"] == coverage_state]
    return respond_list(sort_created_asc(rows), component_json, limit, offset)


@bp.get("/components/<component_id>")
@require_roles()
def read_component(component_id):
    component = get_component(component_id)
    ensure_owner(component["owning_team_id"])
    return ok(component_json(component))


@bp.post("/components/<component_id>/promote-maturity")
@require_roles(DESIGN_SYSTEM_LEAD)
def promote_maturity(component_id):
    payload = body()
    target = req_enum(payload, "target_maturity_level", MATURITY_LEVELS)
    component = get_component(component_id)

    current = component["maturity_level"]
    declared = (current == "EXPERIMENTAL" and target == "BETA") or \
               (current == "BETA" and target == "STABLE")
    if not declared:
        fail(errors.ERR_INVALID_COMPONENT_MATURITY_TRANSITION,
             "Maturity cannot move from %s to %s." % (current, target))
    if target == "STABLE" and component["docs_state"] != "PUBLISHED":
        fail(errors.ERR_INVALID_COMPONENT_MATURITY_TRANSITION,
             "A STABLE component requires a PUBLISHED documentation page.")

    if target == "BETA":
        if component["shipped_platform_count"] < 1:
            fail(errors.ERR_PLATFORM_COVERAGE_INSUFFICIENT,
                 "BETA requires at least one shipped platform implementation.")
        minimum = Decimal("70.00")
    else:
        if component["coverage_state"] not in ("PARTIAL", "FULL"):
            fail(errors.ERR_PLATFORM_COVERAGE_INSUFFICIENT,
                 "STABLE requires PARTIAL or FULL platform coverage.")
        minimum = Decimal("90.00")

    if component["governance_conformance_score"] < minimum:
        fail(errors.ERR_A11Y_CONFORMANCE_INSUFFICIENT,
             "The governance conformance score is below %s." % minimum)

    for plan in store.plans.values():
        if plan["component_id"] == component["id"] and \
                plan["state"] in ("ANNOUNCED", "SUNSET"):
            fail(errors.ERR_COMPONENT_DEPRECATION_IN_PROGRESS,
                 "A deprecation plan for this component is in progress.")

    if component["blocked_dependency_count"] != 0:
        fail(errors.ERR_BLOCKED_DEPENDENCY,
             "The component has blocked dependency edges.")

    component["maturity_level"] = target
    component["maturity_demotion_reason"] = "NONE"
    component["conformance_baseline_at"] = store.now_iso
    component["_baseline_dt"] = store.now
    calc.recompute_component_conformance(component)
    store.touch(component)
    return ok(component_json(component))


# --------------------------------------------------------------------------
# dependency edges
# --------------------------------------------------------------------------
@bp.post("/components/<component_id>/dependencies")
@require_roles(DESIGN_SYSTEM_LEAD, CONTRIBUTING_TEAM)
def create_dependency(component_id):
    payload = body()
    provider_id = req_string(payload, "provider_component_id", 1, 200)
    pinned_major = req_int(payload, "pinned_provider_major", minimum=1)
    if provider_id == component_id:
        fail(errors.ERR_INVALID_REQUEST, "A component may not depend on itself.")

    consumer = get_component(component_id)
    provider = get_component(provider_id)
    ensure_owner(consumer["owning_team_id"])

    if calc.would_create_dependency_cycle(consumer["id"], provider["id"]):
        fail(errors.ERR_DEPENDENCY_CYCLE,
             "The edge would close a cycle in the dependency graph.")

    for edge in store.deps.values():
        if edge["consumer_component_id"] == consumer["id"] and \
                edge["provider_component_id"] == provider["id"]:
            fail(errors.ERR_UNIQUENESS_CONFLICT,
                 "This dependency edge already exists.")

    row = store.new_row()
    row.update({
        "consumer_component_id": consumer["id"],
        "provider_component_id": provider["id"],
        "pinned_provider_major": pinned_major,
        "compatibility_state": calc.compatibility_for(pinned_major, provider),
    })
    store.deps[row["id"]] = row

    calc.recompute_blocked_dependency_count(consumer)
    store.touch(consumer)
    return created(dependency_json(row))


@bp.get("/components/<component_id>/dependencies")
@require_roles()
def list_dependencies(component_id):
    limit, offset = pagination()
    direction = query_enum("direction", DIRECTIONS, "ALL")
    compatibility_state = query_enum("compatibility_state", COMPATIBILITY_STATES)
    component = get_component(component_id)

    rows = []
    for edge in store.deps.values():
        if direction in ("ALL", "CONSUMES") and \
                edge["consumer_component_id"] == component["id"]:
            rows.append(edge)
        elif direction in ("ALL", "PROVIDES") and \
                edge["provider_component_id"] == component["id"]:
            rows.append(edge)
    if compatibility_state is not None:
        rows = [e for e in rows if e["compatibility_state"] == compatibility_state]
    return respond_list(sort_created_asc(rows), dependency_json, limit, offset)


@bp.put("/component-dependencies/<dependency_id>")
@require_roles(DESIGN_SYSTEM_LEAD, CONTRIBUTING_TEAM)
def repin_dependency(dependency_id):
    payload = body()
    pinned_major = req_int(payload, "pinned_provider_major", minimum=1)
    edge = get_dependency(dependency_id)
    consumer = store.components[edge["consumer_component_id"]]
    provider = store.components[edge["provider_component_id"]]
    ensure_owner(consumer["owning_team_id"])

    edge["pinned_provider_major"] = pinned_major
    edge["compatibility_state"] = calc.compatibility_for(pinned_major, provider)
    store.touch(edge)

    calc.recompute_blocked_dependency_count(consumer)
    store.touch(consumer)
    return ok(dependency_json(edge))


# --------------------------------------------------------------------------
# platform implementations
# --------------------------------------------------------------------------
@bp.post("/components/<component_id>/platform-implementations")
@require_roles(CONTRIBUTING_TEAM, DESIGN_SYSTEM_LEAD)
def create_implementation(component_id):
    payload = body()
    platform = req_enum(payload, "platform", PLATFORMS)
    package_name = req_string(payload, "package_name", 1, 160)
    package_version = req_semver(payload, "package_version")
    ratio = opt_decimal(payload, "token_compliance_ratio", places=2,
                        minimum=Decimal("0.00"), maximum=Decimal("1.00"),
                        default=Decimal("0.00"))

    component = get_component(component_id)
    ensure_owner(component["owning_team_id"])

    for existing in calc.component_impls(component["id"]):
        if existing["platform"] == platform:
            fail(errors.ERR_UNIQUENESS_CONFLICT,
                 "This component already has a %s implementation." % platform)

    row = store.new_row()
    row.update({
        "component_id": component["id"],
        "platform": platform,
        "package_name": package_name,
        "package_version": package_version,
        "token_compliance_ratio": ratio,
        "status": "PLANNED",
        "conformance_score": Decimal("0.00"),
        "last_audit_sequence": 0,
        "blocked_reason": "NONE",
        "shipped_at": None,
    })
    store.impls[row["id"]] = row
    return created(impl_json(row))


@bp.get("/components/<component_id>/platform-implementations")
@require_roles()
def list_implementations(component_id):
    limit, offset = pagination()
    status = query_enum("status", IMPL_STATUSES)
    platform = query_enum("platform", PLATFORMS)
    component = get_component(component_id)
    ensure_owner(component["owning_team_id"])

    rows = calc.component_impls(component["id"])
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if platform is not None:
        rows = [i for i in rows if i["platform"] == platform]
    return respond_list(sort_created_asc(rows), impl_json, limit, offset)


@bp.get("/platform-implementations/<impl_id>")
@require_roles()
def read_implementation(impl_id):
    impl = get_impl(impl_id)
    component = store.components[impl["component_id"]]
    ensure_owner(component["owning_team_id"])
    return ok(impl_json(impl))


@bp.post("/platform-implementations/<impl_id>/ship")
@require_roles(CONTRIBUTING_TEAM)
def ship_implementation(impl_id):
    payload = body()
    package_version = req_semver(payload, "package_version")
    ratio = req_decimal(payload, "token_compliance_ratio", places=2,
                        minimum=Decimal("0.00"), maximum=Decimal("1.00"))
    if ratio < Decimal("0.90"):
        fail(errors.ERR_INVALID_REQUEST,
             "Field 'token_compliance_ratio' must be at least 0.90 to ship.")

    impl = get_impl(impl_id)
    component = store.components[impl["component_id"]]
    ensure_owner(component["owning_team_id"])

    if impl["status"] not in ("PLANNED", "BLOCKED"):
        fail(errors.ERR_INVALID_IMPLEMENTATION_STATE,
             "An implementation in %s cannot ship." % impl["status"])
    if component["lifecycle_state"] not in ("ACTIVE", "DEPRECATION_ANNOUNCED"):
        fail(errors.ERR_COMPONENT_LIFECYCLE_BLOCKS_SHIP,
             "The component's lifecycle state blocks shipping.")

    aa_automated = [a for a in calc._impl_audits(impl["id"])
                    if a["wcag_level"] == "AA" and a["method"] == "AUTOMATED"]
    latest = max(aa_automated, key=lambda a: a["audit_sequence"]) if aa_automated else None
    if latest is None or latest["violations_critical"] != 0:
        fail(errors.ERR_A11Y_CRITICAL_VIOLATIONS_OPEN,
             "The latest AUTOMATED AA audit is missing or reports critical violations.")

    if component["blocked_dependency_count"] != 0:
        fail(errors.ERR_BLOCKED_DEPENDENCY,
             "The owning component has blocked dependency edges.")

    was_blocked = impl["status"] == "BLOCKED"
    impl["status"] = "SHIPPED"
    impl["package_version"] = package_version
    impl["token_compliance_ratio"] = ratio
    impl["blocked_reason"] = "NONE"
    impl["shipped_at"] = store.now_iso
    store.touch(impl)

    calc.recompute_coverage(component)
    calc.recompute_component_conformance(component)
    store.touch(component)

    if was_blocked:
        team = store.teams.get(component["owning_team_id"])
        if team is not None:
            calc.recompute_team_blocked_impls(team)
            store.touch(team, bump=False)

    return ok(impl_json(impl))


# --------------------------------------------------------------------------
# accessibility evidence
# --------------------------------------------------------------------------
@bp.post("/platform-implementations/<impl_id>/accessibility-audits")
@require_roles(CONTRIBUTING_TEAM, DESIGN_SYSTEM_LEAD)
def file_audit(impl_id):
    payload = body()
    method = req_enum(payload, "method", AUDIT_METHODS)
    wcag_level = req_enum(payload, "wcag_level", WCAG_LEVELS)
    critical = req_int(payload, "violations_critical", minimum=0)
    serious = req_int(payload, "violations_serious", minimum=0)
    moderate = req_int(payload, "violations_moderate", minimum=0)
    evidence_url = req_string(payload, "evidence_url", 1, 500)

    impl = get_impl(impl_id)
    component = store.components[impl["component_id"]]
    ensure_owner(component["owning_team_id"])

    row = store.new_row(mutable=False)
    row.update({
        "platform_implementation_id": impl["id"],
        "method": method,
        "wcag_level": wcag_level,
        "violations_critical": critical,
        "violations_serious": serious,
        "violations_moderate": moderate,
        "evidence_url": evidence_url,
        "audit_sequence": impl["last_audit_sequence"] + 1,
        "defect_load": calc.defect_load(critical, serious, moderate),
        "audited_at": store.now_iso,
        "_audited_dt": store.now,
    })
    store.audits[row["id"]] = row

    impl["last_audit_sequence"] = row["audit_sequence"]
    impl["conformance_score"] = calc.latest_evidence_score(impl)
    store.touch(impl)

    calc.recompute_component_conformance(component)
    if component["maturity_level"] == "BETA" and \
            component["governance_conformance_score"] < Decimal("70.00"):
        component["maturity_demotion_reason"] = "CONFORMANCE_REGRESSION"
    store.touch(component)

    return created(audit_json(row))


@bp.get("/platform-implementations/<impl_id>/accessibility-audits")
@require_roles()
def list_audits(impl_id):
    limit, offset = pagination()
    method = query_enum("method", AUDIT_METHODS)
    wcag_level = query_enum("wcag_level", WCAG_LEVELS)
    impl = get_impl(impl_id)
    component = store.components[impl["component_id"]]
    ensure_owner(component["owning_team_id"])

    rows = calc._impl_audits(impl["id"])
    if method is not None:
        rows = [a for a in rows if a["method"] == method]
    if wcag_level is not None:
        rows = [a for a in rows if a["wcag_level"] == wcag_level]
    rows.sort(key=lambda a: a["audit_sequence"])
    return respond_list(rows, audit_json, limit, offset)
