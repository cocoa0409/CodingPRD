"""Every computed value in the PRD lives here (PRD 3.1-3.9)."""

from decimal import Decimal

import errors
from errors import fail
from store import store, sort_created_asc
from validation import quantize

ZERO2 = Decimal("0.00")
HUNDRED = Decimal("100.00")

AUTOMATED_WEIGHT = Decimal("0.4")
MANUAL_WEIGHT = Decimal("0.6")
MISSING_METHOD_PENALTY = Decimal("25.0")

CODE_SCAN_WEIGHT = Decimal("0.70")
DESIGN_LINT_WEIGHT = Decimal("0.30")


# --------------------------------------------------------------------------
# accessibility evidence -> conformance scores (PRD 3.4)
# --------------------------------------------------------------------------
def defect_load(critical, serious, moderate):
    return 10 * critical + 4 * serious + 1 * moderate


def _impl_audits(impl_id):
    return [a for a in store.audits.values()
            if a["platform_implementation_id"] == impl_id]


def _score_from_loads(load_auto, load_manual):
    missing = 0
    if load_auto is None:
        missing += 1
    if load_manual is None:
        missing += 1
    loaded = (AUTOMATED_WEIGHT * Decimal(load_auto if load_auto is not None else 0)
              + MANUAL_WEIGHT * Decimal(load_manual if load_manual is not None else 0))
    raw = Decimal(100) - loaded - MISSING_METHOD_PENALTY * missing
    if raw < 0:
        raw = Decimal(0)
    return quantize(raw, 2)


def latest_evidence_score(impl):
    """Greatest audit_sequence AA row per method."""
    loads = {}
    for method in ("AUTOMATED", "MANUAL"):
        rows = [a for a in _impl_audits(impl["id"])
                if a["wcag_level"] == "AA" and a["method"] == method]
        if not rows:
            loads[method] = None
            continue
        best = max(rows, key=lambda a: a["audit_sequence"])
        loads[method] = best["defect_load"]
    return _score_from_loads(loads["AUTOMATED"], loads["MANUAL"])


def governance_sweep_score(impl, component):
    """Worst AA row per method at or after the component's baseline."""
    baseline = component["_baseline_dt"]
    loads = {}
    for method in ("AUTOMATED", "MANUAL"):
        rows = [a for a in _impl_audits(impl["id"])
                if a["wcag_level"] == "AA" and a["method"] == method
                and a["_audited_dt"] >= baseline]
        loads[method] = max(a["defect_load"] for a in rows) if rows else None
    return _score_from_loads(loads["AUTOMATED"], loads["MANUAL"])


def component_impls(component_id):
    return [i for i in store.impls.values() if i["component_id"] == component_id]


def recompute_component_conformance(component):
    live = [i for i in component_impls(component["id"])
            if i["status"] in ("SHIPPED", "BLOCKED")]
    if not live:
        component["governance_conformance_score"] = ZERO2
        return
    component["governance_conformance_score"] = min(
        governance_sweep_score(i, component) for i in live)


# --------------------------------------------------------------------------
# platform coverage (PRD 3.3)
# --------------------------------------------------------------------------
def recompute_coverage(component):
    platforms = set(i["platform"] for i in component_impls(component["id"])
                    if i["status"] == "SHIPPED")
    component["shipped_platform_count"] = len(platforms)
    component["coverage_state"] = coverage_state(platforms)


def coverage_state(platforms):
    if not platforms:
        return "NONE"
    if platforms == {"WEB"}:
        return "WEB_ONLY"
    if "WEB" not in platforms:
        return "MOBILE_ONLY"
    mobile = platforms & {"IOS", "ANDROID"}
    if len(mobile) == 2:
        return "FULL"
    return "PARTIAL"


# --------------------------------------------------------------------------
# dependency graph roll-ups (PRD 3.5)
# --------------------------------------------------------------------------
def outgoing_edges(component_id):
    return [d for d in store.deps.values()
            if d["consumer_component_id"] == component_id]


def incoming_edges(component_id):
    return [d for d in store.deps.values()
            if d["provider_component_id"] == component_id]


def recompute_blocked_dependency_count(component):
    component["blocked_dependency_count"] = sum(
        1 for d in outgoing_edges(component["id"])
        if d["compatibility_state"] in ("INCOMPATIBLE", "SUNSET_PROVIDER"))


def compatibility_for(pinned_major, provider):
    if provider["lifecycle_state"] == "SUNSET":
        return "SUNSET_PROVIDER"
    if pinned_major == provider["current_major_version"]:
        return "COMPATIBLE"
    return "INCOMPATIBLE"


def would_create_dependency_cycle(consumer_id, provider_id):
    """True when provider already reaches consumer over all edges."""
    seen = set()
    stack = [provider_id]
    while stack:
        node = stack.pop()
        if node == consumer_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        for edge in outgoing_edges(node):
            stack.append(edge["provider_component_id"])
    return False


# --------------------------------------------------------------------------
# team roll-ups (PRD 3.1, 3.3, 3.9)
# --------------------------------------------------------------------------
def team_components(team_id):
    return [c for c in store.components.values() if c["owning_team_id"] == team_id]


def recompute_team_blocked_impls(team):
    total = 0
    for comp in team_components(team["id"]):
        total += sum(1 for i in component_impls(comp["id"]) if i["status"] == "BLOCKED")
    team["blocked_implementation_count"] = total


def team_grants(team_id):
    return [g for g in store.grants.values() if g["requesting_team_id"] == team_id]


def recompute_team_debt(team):
    outstanding = sum((g["debt_points"] for g in team_grants(team["id"])
                       if g["state"] in ("APPROVED", "EXPIRED")), Decimal(0))
    lifetime = sum((g["debt_points"] for g in team_grants(team["id"])
                    if g["state"] in ("APPROVED", "EXPIRED", "REPAID")), Decimal(0))
    team["outstanding_debt_points"] = quantize(outstanding, 2)
    team["lifetime_debt_points"] = quantize(lifetime, 2)
    team["debt_state"] = ("FROZEN"
                          if team["outstanding_debt_points"] >= team["debt_budget_points"]
                          else "CLEAR")


def recompute_one_off_exception_count(component):
    component["one_off_exception_count"] = sum(
        1 for g in store.grants.values()
        if g["substitute_for_component_id"] == component["id"]
        and g["state"] in ("APPROVED", "EXPIRED"))


GRANT_BASE = {"ONE_OFF_COMPONENT": Decimal("12"),
              "FORK_OF_SYSTEM_COMPONENT": Decimal("8"),
              "RAW_TOKEN_USAGE": Decimal("5")}
GRANT_PLATFORM_FACTOR = {"WEB": Decimal("1.00"), "IOS": Decimal("1.25"),
                         "ANDROID": Decimal("1.25"), "ALL": Decimal("1.75")}
GRANT_MATURITY_FACTOR = {"EXPERIMENTAL": Decimal("0.50"), "BETA": Decimal("0.75"),
                         "STABLE": Decimal("1.50")}


def grant_debt_points(exception_kind, platform_scope, pinned_maturity_level):
    product = (GRANT_BASE[exception_kind]
               * GRANT_PLATFORM_FACTOR[platform_scope]
               * GRANT_MATURITY_FACTOR[pinned_maturity_level])
    return quantize(product, 2)


# --------------------------------------------------------------------------
# adoption measurement (PRD 3.1)
# --------------------------------------------------------------------------
def scan_ratio(system_count, legacy_count, one_off_count):
    total = system_count + legacy_count + one_off_count
    if total == 0:
        return ZERO2
    return quantize(Decimal(system_count) / Decimal(total) * Decimal(100), 2)


def team_scans(team_id, scan_kind=None):
    rows = [s for s in store.scans.values() if s["team_id"] == team_id]
    if scan_kind is not None:
        rows = [s for s in rows if s["scan_kind"] == scan_kind]
    return rows


def recency_order(rows):
    """window_end_at desc, then scanned_at desc, then created_at desc."""
    return sorted(rows,
                  key=lambda s: (s["window_end_at"], s["scanned_at"], s["created_at"]),
                  reverse=True)


def _channel_latest(team_id, kind):
    rows = recency_order(team_scans(team_id, kind))
    return rows[0]["adoption_ratio"] if rows else ZERO2


def _channel_trailing(team_id, kind):
    rows = recency_order(team_scans(team_id, kind))[:2]
    if not rows:
        return ZERO2
    total = sum((r["adoption_ratio"] for r in rows), Decimal(0))
    return quantize(total / Decimal(len(rows)), 2)


def adoption_view(team_id, view):
    if view == "TRAILING_WINDOW":
        code = _channel_trailing(team_id, "CODE_SCAN")
        design = _channel_trailing(team_id, "DESIGN_LINT")
    else:
        code = _channel_latest(team_id, "CODE_SCAN")
        design = _channel_latest(team_id, "DESIGN_LINT")
    index = quantize(code * CODE_SCAN_WEIGHT + design * DESIGN_LINT_WEIGHT, 2)
    return code, design, index


def recompute_team_adoption(team):
    team["adoption_index_latest"] = adoption_view(team["id"], "LATEST_SCAN")[2]
    team["adoption_index_trailing"] = adoption_view(team["id"], "TRAILING_WINDOW")[2]


# --------------------------------------------------------------------------
# token architecture (PRD 3.2)
# --------------------------------------------------------------------------
def set_tokens(token_set_id):
    return [t for t in store.tokens.values() if t["token_set_id"] == token_set_id]


def _alias_map(token_set_id, override=None, extra=None):
    """id -> alias target (or None) for one set, with a hypothetical write applied."""
    alias_of = {}
    raw_of = {}
    for tok in set_tokens(token_set_id):
        alias_of[tok["id"]] = tok["alias_of_token_id"]
        raw_of[tok["id"]] = tok["raw_value"]
    if extra:
        alias_of[extra["id"]] = extra["alias_of_token_id"]
        raw_of[extra["id"]] = extra["raw_value"]
    if override:
        alias_of[override["id"]] = override["alias_of_token_id"]
        raw_of[override["id"]] = override["raw_value"]
    return alias_of, raw_of


def _walk(start_id, alias_of):
    """Returns (hops, leaf_id, path) or ('CYCLE', None, None)."""
    visited = [start_id]
    seen = {start_id}
    current = start_id
    hops = 0
    while alias_of.get(current) is not None:
        nxt = alias_of[current]
        if nxt in seen or nxt not in alias_of:
            if nxt in seen:
                return "CYCLE", None, None
            break
        seen.add(nxt)
        visited.append(nxt)
        current = nxt
        hops += 1
    return hops, current, visited


def validate_alias_graph(token_set_id, override=None, extra=None):
    """Cycle guard (rule 17) strictly before the depth guard (rule 20)."""
    alias_of, _raw = _alias_map(token_set_id, override=override, extra=extra)
    walks = {}
    for token_id in alias_of:
        hops, leaf, path = _walk(token_id, alias_of)
        if hops == "CYCLE":
            fail(errors.ERR_TOKEN_ALIAS_CYCLE,
                 "The requested alias edge closes a cycle in the token set.")
        walks[token_id] = (hops, leaf, path)
    for token_id, (hops, _leaf, _path) in walks.items():
        if hops > 5:
            fail(errors.ERR_TOKEN_ALIAS_DEPTH_EXCEEDED,
                 "The alias walk does not terminate within 5 hops.")
    return walks


def resolve_set(token_set_id):
    """id -> (alias_depth, resolved_value, path) for every token in the set."""
    alias_of, raw_of = _alias_map(token_set_id)
    out = {}
    for token_id in alias_of:
        hops, leaf, path = _walk(token_id, alias_of)
        if hops == "CYCLE":
            out[token_id] = (0, None, [token_id])
        else:
            out[token_id] = (hops, raw_of.get(leaf), path)
    return out


def recompute_token_set(token_set):
    """Rewrites alias_depth / resolved_value on every token; returns touched ids."""
    resolved = resolve_set(token_set["id"])
    changed = []
    for token_id, (depth, value, _path) in resolved.items():
        tok = store.tokens[token_id]
        if tok["alias_depth"] != depth or tok["resolved_value"] != value:
            changed.append(token_id)
        tok["alias_depth"] = depth
        tok["resolved_value"] = value
    rows = set_tokens(token_set["id"])
    token_set["token_count"] = len(rows)
    token_set["max_alias_depth"] = max((t["alias_depth"] for t in rows), default=0)
    return changed, resolved


LAYER_ORDER_BRAND = None  # layer precedence is computed inline below


def resolve_layers(token_set_id, brand, mode):
    """Four-layer precedence per distinct token name (PRD 3.2)."""
    rows = set_tokens(token_set_id)
    by_name = {}
    for tok in rows:
        by_name.setdefault(tok["name"], {})[(tok["brand"], tok["mode"])] = tok
    resolved = resolve_set(token_set_id)
    out = []
    for name in sorted(by_name):
        layers = by_name[name]
        chosen = None
        for key in ((brand, mode), (brand, "ANY"), ("BASE", mode), ("BASE", "ANY")):
            if key in layers:
                chosen = layers[key]
                break
        if chosen is None:
            continue
        depth, value, _path = resolved[chosen["id"]]
        out.append({
            "name": name,
            "token_id": chosen["id"],
            "brand": chosen["brand"],
            "mode": chosen["mode"],
            "category": chosen["category"],
            "alias_depth": depth,
            "resolved_value": value,
        })
    return out


# --------------------------------------------------------------------------
# deprecation notice window (PRD 3.8)
# --------------------------------------------------------------------------
NOTICE_BASE = {"EXPERIMENTAL": 14, "BETA": 45, "STABLE": 90}
NOTICE_SURCHARGE = {"NONE": 0, "WEB_ONLY": 0, "MOBILE_ONLY": 0,
                    "PARTIAL": 15, "FULL": 30}


def required_notice_days(component):
    return (NOTICE_BASE[component["maturity_level"]]
            + NOTICE_SURCHARGE[component["coverage_state"]])


# --------------------------------------------------------------------------
# required evidence set (PRD 3.6)
# --------------------------------------------------------------------------
EVIDENCE_KINDS = ("A11Y_AUTOMATED", "A11Y_MANUAL", "DOC_PAGE", "MIGRATION_GUIDE",
                  "PLATFORM_PARITY", "TOKEN_COMPLIANCE")
ROUND_DURABLE_KINDS = ("DOC_PAGE", "MIGRATION_GUIDE")

EVIDENCE_BASE = {
    "NEW_COMPONENT": ["A11Y_AUTOMATED", "A11Y_MANUAL", "DOC_PAGE", "TOKEN_COMPLIANCE"],
    "ENHANCEMENT": ["A11Y_AUTOMATED", "TOKEN_COMPLIANCE"],
    "BREAKING_CHANGE": ["A11Y_AUTOMATED", "A11Y_MANUAL", "DOC_PAGE",
                        "MIGRATION_GUIDE", "TOKEN_COMPLIANCE"],
}


def required_evidence_kinds(proposal_kind, coverage_state_value):
    kinds = set(EVIDENCE_BASE[proposal_kind])
    if coverage_state_value in ("PARTIAL", "FULL"):
        kinds.add("PLATFORM_PARITY")
    return sorted(kinds)


# --------------------------------------------------------------------------
# release version bump (PRD 3.7) -- single pinned forward pass
# --------------------------------------------------------------------------
def raw_change_class(proposal):
    if proposal["proposal_kind"] == "BREAKING_CHANGE":
        return "MAJOR"
    if proposal["proposal_kind"] == "NEW_COMPONENT":
        return "MINOR"
    return "MINOR" if proposal["touches_public_api"] else "PATCH"


def release_version_bump(release, carried):
    """Returns (per_proposal_classes, ratio, tier, breaking_count, escalated, semver)."""
    raw = {}
    step2 = {}
    for prop in carried:
        raw[prop["id"]] = raw_change_class(prop)
        cls = raw[prop["id"]]
        if cls == "MAJOR":
            component = store.components.get(prop["target_component_id"])
            if component is not None and component["maturity_level"] == "EXPERIMENTAL":
                cls = "MINOR"
        step2[prop["id"]] = cls

    major_count = sum(1 for v in step2.values() if v == "MAJOR")
    ratio = quantize(Decimal(major_count) / Decimal(len(carried)), 4)
    tier = "BATCHED" if ratio >= Decimal("0.50") else "INCREMENTAL"

    effective = {}
    for prop in carried:
        cls = step2[prop["id"]]
        if tier == "BATCHED" and cls == "MINOR" and prop["touches_public_api"]:
            cls = "MAJOR"
        effective[prop["id"]] = cls

    breaking_count = sum(1 for v in effective.values() if v == "MAJOR")
    escalated = sum(1 for pid in effective if effective[pid] != raw[pid])

    major, minor, patch = (int(p) for p in release["semver_base"].split("."))
    if breaking_count > 0:
        semver = "%d.%d.%d" % (major + 1, 0, 0)
    elif any(v == "MINOR" for v in effective.values()):
        semver = "%d.%d.%d" % (major, minor + 1, 0)
    else:
        semver = "%d.%d.%d" % (major, minor, patch + 1)

    return raw, effective, ratio, tier, breaking_count, escalated, semver


def check_alias_cycles(token_set_id, override=None, extra=None):
    """Rule 17 only: cycle detection, no depth judgement."""
    alias_of, _raw = _alias_map(token_set_id, override=override, extra=extra)
    for token_id in alias_of:
        hops, _leaf, _path = _walk(token_id, alias_of)
        if hops == "CYCLE":
            fail(errors.ERR_TOKEN_ALIAS_CYCLE,
                 "The requested alias edge closes a cycle in the token set.")


def check_alias_depth(token_set_id, override=None, extra=None):
    """Rule 20 only: the alias walk must terminate within 5 hops."""
    alias_of, _raw = _alias_map(token_set_id, override=override, extra=extra)
    for token_id in alias_of:
        hops, _leaf, _path = _walk(token_id, alias_of)
        if hops != "CYCLE" and hops > 5:
            fail(errors.ERR_TOKEN_ALIAS_DEPTH_EXCEEDED,
                 "The alias walk does not terminate within 5 hops.")
