"""Managed package chains, installations, upgrades and the two package
calculations (PRD §3.4).

The upgrade-candidate rule governs the stale marker: the eligible candidates for
an installation are the published versions that are not deprecated, that carry a
non-null supersedes_version_id (a first release is never a candidate) and whose
chain root resolves to a version in the installation's own namespace.  The
winning candidate has the greatest major_version, ties broken by the earliest
creation timestamp; the installation is stale exactly when that candidate's
major_version is strictly greater than the installed major_version.
"""

import clock
import db
from errors import (
    ERR_INVALID_STATE,
    ERR_PACKAGE_ALREADY_INSTALLED,
    ERR_PACKAGE_DEPENDENCY_UNMET,
    ERR_STALE_VERSION,
    ERR_VERSION_DEPRECATED,
    fail,
)
from services import common, permissions

UPGRADE_STATES = ("NEEDS_UPGRADE",)
UNINSTALL_STATES = ("INSTALLED", "NEEDS_UPGRADE")


# --- chain helpers ----------------------------------------------------------

def chain_root(version_id, seen=None):
    """Walk supersedes_version_id links up to the root of the chain."""
    seen = set() if seen is None else seen
    current = version_id
    while current is not None and current not in seen:
        seen.add(current)
        version = db.package_versions.get(current)
        if version is None:
            return current
        nxt = version.get("supersedes_version_id")
        if nxt is None:
            return current
        current = nxt
    return current


def is_supersedes_descendant(version_id, ancestor_id):
    """True when version_id extends ancestor_id through supersedes links."""
    current = version_id
    seen = set()
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        version = db.package_versions.get(current)
        if version is None:
            return False
        current = version.get("supersedes_version_id")
    return False


def eligible_candidates(namespace):
    candidates = []
    for version in db.package_versions.values():
        if version.get("deprecated"):
            continue
        supersedes = version.get("supersedes_version_id")
        if supersedes is None:
            continue
        root = chain_root(supersedes)
        root_version = db.package_versions.get(root)
        if root_version is None or root_version.get("namespace") != namespace:
            continue
        candidates.append(version)
    return candidates


def winning_candidate(namespace):
    """Greatest major_version; ties broken by the earliest creation timestamp."""
    candidates = eligible_candidates(namespace)
    if not candidates:
        return None
    top = max(c["major_version"] for c in candidates)
    tied = [c for c in candidates if c["major_version"] == top]
    tied.sort(key=lambda c: (c.get("created_at") or "", c.get("_seq", 0)))
    return tied[0]


def recompute_install_count(version_id=None):
    for vid, version in db.package_versions.items():
        if version_id is not None and vid != version_id:
            continue
        count = sum(
            1
            for row in db.installed_packages.values()
            if row["package_version_id"] == vid and row["status"] != "UNINSTALLED"
        )
        if version.get("install_count") != count:
            version["install_count"] = count
            db.touch(version)


def upgrade_candidate_evaluation(env):
    """Derive InstalledPackage.stale and Environment.installed_version_ids."""
    installed_ids = []
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"]:
            continue
        if row["status"] == "UNINSTALLED":
            continue
        installed_ids.append(row["package_version_id"])
        current = db.package_versions.get(row["package_version_id"])
        candidate = winning_candidate(row["namespace"])
        if candidate is None:
            stale = False  # empty-candidate fallback; never an error
        else:
            installed_major = current["major_version"] if current else 0
            stale = candidate["major_version"] > installed_major
        if row.get("stale") != stale:
            row["stale"] = stale
            db.touch(row)
    if env.get("installed_version_ids") != installed_ids:
        env["installed_version_ids"] = installed_ids
        db.touch(env)


def requires_chain_depth(env, version, seen=None):
    """Length of the requires chain starting at ``version`` (PRD §3.4)."""
    seen = set() if seen is None else seen
    namespace = version.get("requires_namespace")
    if not namespace or version["id"] in seen:
        return 0
    seen.add(version["id"])
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        if row["namespace"] != namespace:
            continue
        dependency = db.package_versions.get(row["package_version_id"])
        if dependency is None:
            return 1
        return 1 + requires_chain_depth(env, dependency, seen)
    return 0


def conflict_entries(env):
    """Non-deprecated versions the environment should converge over (§3.4)."""
    installed_ids = [row["package_version_id"] for row in common.live_installed(env["id"])]
    entries = []
    for version in db.package_versions.values():
        if version.get("deprecated"):
            continue
        if version["id"] in installed_ids:
            entries.append(version)
            continue
        if any(is_supersedes_descendant(vid, version["id"]) for vid in installed_ids):
            entries.append(version)
    return entries


def conflict_winner(env):
    """Strict maximum of the (requires_chain_depth, major_version) rank pair.

    A tie on the whole pair is broken by the latest creation timestamp.
    """
    entries = conflict_entries(env)
    if not entries:
        return None
    ranked = [
        (requires_chain_depth(env, v), v["major_version"], v)
        for v in entries
    ]
    top = max((depth, major) for depth, major, _ in ranked)
    tied = [v for depth, major, v in ranked if (depth, major) == top]
    tied.sort(key=lambda v: (v.get("created_at") or "", v.get("_seq", 0)))
    return tied[-1]


def package_conflict_resolution(env):
    winner = conflict_winner(env)
    return winner


# --- publish ----------------------------------------------------------------

def publish_version(actor, b):
    from validate import optional_string, require_int, require_string

    namespace = require_string(b, "namespace")
    major_version = require_int(b, "major_version", min_value=1)
    # PRD §3.4: the publisher supplies the namespace, the major version and a
    # human-readable name; only supersedes_version_id / requires_namespace /
    # requires_min_version_id are optional.
    name = require_string(b, "name")
    supersedes_version_id = optional_string(b, "supersedes_version_id", default=None)
    requires_namespace = optional_string(b, "requires_namespace", default=None)
    requires_min_version_id = optional_string(b, "requires_min_version_id", default=None)

    superseded = None
    if supersedes_version_id is not None:
        superseded = common.get_package_version(supersedes_version_id)
    if requires_min_version_id is not None:
        common.get_package_version(requires_min_version_id)

    version = db.create(
        db.package_versions,
        {
            "namespace": namespace,
            "major_version": major_version,
            "name": name,
            "deprecated": False,
            "supersedes_version_id": supersedes_version_id,
            "requires_namespace": requires_namespace,
            "requires_min_version_id": requires_min_version_id,
            # A first release loads the remaining-bytes figure from the managed
            # package metadata blob; a version that extends a chain marks its
            # predecessor deprecated instead (PRD §3.4).
            "unlimited_remaining_bytes_dec": "0" if supersedes_version_id is None else None,
            "install_count": 0,
        },
    )

    if superseded is not None and not superseded.get("deprecated"):
        superseded["deprecated"] = True
        db.touch(superseded)

    # HOP 1: every installation, across every environment, whose namespace is
    # the published namespace gets refreshed_at stamped.
    affected = set()
    for row in db.installed_packages.values():
        if row["namespace"] != namespace:
            continue
        row["refreshed_at"] = clock.default_iso()
        db.touch(row)
        affected.add(row["environment_id"])

    # The installation write drives the stale re-derivation for those envs.
    for env_id in affected:
        env = db.environments.get(env_id)
        if env is not None:
            upgrade_candidate_evaluation(env)
            package_conflict_resolution(env)

    return version


# --- install ----------------------------------------------------------------

def dependency_satisfied(env, version):
    namespace = version.get("requires_namespace")
    if not namespace:
        return True
    floor = version.get("requires_min_version_id")
    min_major = None
    if floor is not None:
        floor_version = db.package_versions.get(floor)
        if floor_version is not None:
            min_major = floor_version["major_version"]
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        if row["namespace"] != namespace:
            continue
        installed = db.package_versions.get(row["package_version_id"])
        if installed is None:
            continue
        if min_major is None or installed["major_version"] >= min_major:
            return True
    return False


def install_package(actor, env, b):
    from validate import require_int, require_string

    version_id = require_string(b, "package_version_id")
    expected = require_int(b, "expected_environment_version")

    version = common.get_package_version(version_id)

    # Optimistic concurrency on the parent environment (PRD §2.6).  The second
    # installation is legitimate product behaviour; the stale
    # expected_environment_version is the sole reason for rejection.
    if expected != env["version"]:
        fail(
            ERR_STALE_VERSION,
            "expected_environment_version does not match the environment's current version.",
        )

    if not dependency_satisfied(env, version):
        fail(
            ERR_PACKAGE_DEPENDENCY_UNMET,
            "The required namespace '%s' is not installed at a satisfying version."
            % (version.get("requires_namespace"),),
        )

    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        if row["namespace"] == version["namespace"]:
            fail(
                ERR_PACKAGE_ALREADY_INSTALLED,
                "The environment already carries an installation for namespace '%s'."
                % version["namespace"],
            )

    if version.get("deprecated"):
        fail(ERR_VERSION_DEPRECATED, "The managed package version is deprecated.")

    row = db.create(
        db.installed_packages,
        {
            "environment_id": env["id"],
            "package_version_id": version["id"],
            "namespace": version["namespace"],
            "status": "INSTALLED",
            "stale": False,
            "installed_at": clock.default_iso(),
            "refreshed_at": None,
            "pending_refresh_job_id": None,
        },
    )

    db.touch(env)
    # HOP 1: install_count recomputed for the newly installed version.
    recompute_install_count(version["id"])
    # HOP 2: stale re-derived across the environment's installations.
    upgrade_candidate_evaluation(env)
    # HOP 3: sharing scopes re-derived to NAMESPACE_READ for grants scoped to
    # the installed namespace.
    permissions.recompute_sharing_scopes(env, mode="NAMESPACE_READ")
    package_conflict_resolution(env)
    return row


# --- upgrade ----------------------------------------------------------------

def _dependency_floor_satisfied_for_upgrade(env, target):
    namespace = target.get("requires_namespace")
    if not namespace:
        return True
    floor = target.get("requires_min_version_id")
    min_major = None
    if floor is not None:
        floor_version = db.package_versions.get(floor)
        if floor_version is not None:
            min_major = floor_version["major_version"]
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        if row["namespace"] != namespace:
            continue
        installed = db.package_versions.get(row["package_version_id"])
        if installed is None:
            continue
        if min_major is None or installed["major_version"] >= min_major:
            return True
    return False


def dependency_closure(deprecated_namespace):
    """Re-evaluate installations that require the freshly deprecated namespace."""
    affected = set()
    for row in db.installed_packages.values():
        if row["status"] == "UNINSTALLED":
            continue
        installed = db.package_versions.get(row["package_version_id"])
        if installed is None:
            continue
        if installed.get("requires_namespace") == deprecated_namespace:
            row["status"] = "NEEDS_UPGRADE"
            db.touch(row)
            affected.add(row["environment_id"])
    for env_id in affected:
        env = db.environments.get(env_id)
        if env is not None:
            upgrade_candidate_evaluation(env)
    return affected


def upgrade_installation(actor, installed, b):
    from validate import require_string

    env = common.get_environment(installed["environment_id"])

    if installed["status"] not in UPGRADE_STATES:
        fail(ERR_INVALID_STATE, "The installation is not in NEEDS_UPGRADE.")

    target_id = require_string(b, "target_package_version_id")
    target = common.get_package_version(target_id)

    if target.get("namespace") != installed["namespace"]:
        fail(
            ERR_INVALID_STATE,
            "The target version does not belong to the installed namespace.",
        )

    if not _dependency_floor_satisfied_for_upgrade(env, target):
        fail(
            ERR_PACKAGE_DEPENDENCY_UNMET,
            "The required namespace '%s' is not installed at a satisfying version."
            % (target.get("requires_namespace"),),
        )

    if target.get("deprecated"):
        fail(ERR_VERSION_DEPRECATED, "The target managed package version is deprecated.")

    previous_id = installed["package_version_id"]
    installed["package_version_id"] = target["id"]
    installed["status"] = "UPGRADED"
    installed["stale"] = False
    installed["refreshed_at"] = clock.default_iso()
    db.touch(installed)

    db.touch(env)
    # HOP 1: install_count recomputed for the promoted version.
    recompute_install_count(target["id"])
    # HOP 2: the publish-batch deprecation cascade marks the predecessor.
    previous = db.package_versions.get(previous_id)
    deprecated_namespace = None
    if previous is not None and not previous.get("deprecated"):
        previous["deprecated"] = True
        deprecated_namespace = previous["namespace"]
        db.touch(previous)
    # HOP 3: the dependency closure re-evaluates installations requiring it.
    if deprecated_namespace is not None:
        dependency_closure(deprecated_namespace)
    upgrade_candidate_evaluation(env)
    package_conflict_resolution(env)
    return installed


# --- uninstall --------------------------------------------------------------

def uninstall_installation(actor, installed):
    env = common.get_environment(installed["environment_id"])

    if installed["status"] not in UNINSTALL_STATES:
        fail(ERR_INVALID_STATE, "The installation cannot be uninstalled from its state.")

    namespace = installed["namespace"]
    for row in db.installed_packages.values():
        if row["id"] == installed["id"]:
            continue
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        dependency = db.package_versions.get(row["package_version_id"])
        if dependency is not None and dependency.get("requires_namespace") == namespace:
            fail(
                ERR_INVALID_STATE,
                "Another installation in this environment still requires namespace '%s'."
                % namespace,
            )

    removed_version_id = installed["package_version_id"]
    installed["status"] = "UNINSTALLED"
    db.touch(installed)

    db.touch(env)
    # HOP 1: install_count recomputed for the removed version.
    recompute_install_count(removed_version_id)
    # HOP 2: the stale marker re-derived for the remaining installations.
    upgrade_candidate_evaluation(env)
    permissions.recompute_sharing_scopes(env, mode="NAMESPACE_READ")
    package_conflict_resolution(env)
    return installed


# --- reads ------------------------------------------------------------------

def successors_of(version_id):
    """Versions extending this one, through the chain or the dependency floor."""
    out = []
    for version in db.package_versions.values():
        if version["id"] == version_id:
            continue
        if is_supersedes_descendant(version["id"], version_id):
            out.append(version)
            continue
        if version.get("requires_min_version_id") == version_id:
            out.append(version)
    return out


def installations_of(version_id):
    import calculations

    rows = [
        row
        for row in db.installed_packages.values()
        if row["package_version_id"] == version_id
    ]
    return calculations.sort_asc(rows)