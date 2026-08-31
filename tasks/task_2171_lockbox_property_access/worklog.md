# Worklog — task_2171_lockbox_property_access

## Step 1: Create task directory — 2026-08-29T03:57:26.000Z

Created `tasks/task_2171_lockbox_property_access/` and `tasks/task_2171_lockbox_property_access/workspace/`.

## Step 3: Copy shared files — 2026-08-29T03:57:47.000Z

Copied `INSTRUCTION.md` to `tasks/task_2171_lockbox_property_access/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-29T04:52:00.000Z

All three artifacts are generated and pass the skill's linter.

**Verdict block (verbatim from `scaffold_lint.py`):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  699

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files
- `SCAFFOLD.yaml` (1779 lines, §1.0–§1.7 + §1.2.1)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1925 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2928 lines)

## Contents
**Profile** — `access_control_matrix` × `compliance_audit`; layers: cascading_side_effects, dual_variant_calculation, optimistic_concurrency, ops_run_checkpoint; **entity_topology: flat** (0% in skill examples), **state_machine_shape: cyclic**, **role_model: segregation_of_duties**, self-referential + many-to-many + cross-aggregate relationships. `api_prefix: ""` so every entity owns a top-level collection (required for the linter's FK reverse-reachability derivation).

**Counts** — 12 entities · 10 state machines / 66 transitions · 3 OCC concurrency rules · 9 calculations · 20 ordered validations · 47 endpoints · 39 errors · 4 roles (AssociationAdmin/SecurityAuditor/LockboxDevice opaque, Member entity-backed).

**State machines** — Lockbox (cyclic: IN_STOCK→ASSIGNED→PLACED→ASSIGNED→IN_STOCK, plus MISSING→QUARANTINE→IN_STOCK), Member (ACTIVE↔SUSPENDED↔…→TERMINATED), AccessCredential (ACTIVE↔SUSPENDED), Listing (ACTIVE↔UNDER_CONTRACT), IncidentReview (EVIDENCE_LOCKED→CLOSED→EVIDENCE_LOCKED reopen), LockboxPlacement with **two parallel dimensions** (`placement_status` × `billing_status`), plus AccessGrant, ShowingAppointment, BillingCharge, Contractor.

**Calculations** — `replacement_charge_amount` (dual variant: flat_schedule 12000 vs depreciated_book 4560 on the same unit), `lockbox_recovery_rate` (dual variant: 50.00 vs 66.67 on the same placements), `incident_risk_score` (3-factor non-linear product + clamp, mode a), `member_statement_balance` (per-line surcharge rounding pinned: 3076 not 3075, mode b), `late_removal_penalty` (tier keyed on base not total: 11025 not 11550, mode c), `association_posture`, `access_outcome_resolution` (pinned ladder), `grant_occupation_overlap` (half-open + 15-min buffer), `showing_capacity_overlap` (closed interval + capacity).

**§1.8** — 9 rule_ids, **22 instances** (3 rules carry a third instance): depth-4 loss-report cascade (lockbox→placement→grant→showing) and depth-3 suspension cascade; priority conflicts on two distinct category pairs (state×fiscal, safety×temporal); boundaries on the temp-code counter and on an empty recovery cohort; three conserved quantities (inventory count, money, credential entitlement).

**§1.9** — 9 sections, **66 instances** (56 with executable recipes + 10 `excluded_because` stubs pointing at named §1.8 instances).

**Verified mechanically:** zero unbound `${var}` placeholders across 699 calls; all `grounds:` refs resolve into §1.1–§1.7; 86 unique instance names; no forbidden concurrency vocabulary; every error code referenced by at least one design instance; all formula-derived asserts computed with exact `Decimal` arithmetic. Two SCAFFOLD self-consistency fixes were made during generation: priority-40 vs priority-70/85 precedence was pinned explicitly (so `ERR_PLACEMENT_ALREADY_ACTIVE` and `ERR_EVIDENCE_LOCKED` stay reachable), and a Contractor state machine was added so `SUSPENDED` has a declared producer.

## Step 4: Generate PRD — 2026-08-29T05:02:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2171_lockbox_property_access/workspace/PRD.md`.

**Build method:** incremental — 6 separate appends (Write for §1+§2.1, then verbatim §2.2 from `section-2.2-response-structure.md`, then §2.3–2.10, §3.1–3.3, §3.4, §3.5–3.6, §3.7–3.9, then §4/§5 tables generated programmatically from the YAML). No one-shot write; no truncation.

**Size:** 426 lines, 11,806 words.

**Sections written**
- §1 Introduction (3 paragraphs)
- §2 (10 subsections): 2.1 Actors/Identity/RBAC · 2.2 API Response Structure (verbatim, byte-identical — verified) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Stale-View Rejection on Parent Records (OCC) · 2.6 The Order in Which a Request Is Rejected (full 20-rung ladder) · 2.7 Money, Rounding and the Member Statement · 2.8 Association Posture · 2.9 Cascades and Compensation · 2.10 Window Arithmetic
- §3 (9 subsections): association/inventory setup · membership lifecycle + 3-hop cascade · credentials · assignment/placement/removal-at-closing + late-removal penalty · temporary codes (one-day/inspector/contractor) · showings + device access ladder · loss/theft/recovery/retirement + replacement billing · incident review + risk score · compliance checkpoint + recovery reporting
- §4 endpoint table (4 columns, 47 rows) · §5 error table (2 columns, 39 rows)

**Completeness verification (found vs expected)**
- Entities: **12 / 12**
- State machines fully covered (entity name + every `from`/`to`/initial/terminal state present): **10 / 10**
- Calculations (each located by a distinctive prose anchor): **9 / 9** — note the snake_case calculation identifiers are deliberately *not* emitted verbatim; per the skill's no-pseudocode rule each formula is rendered as reconstructable business prose (variant selectors, constants, pinned rounding orders, tier keying, ladder ordering all stated)
- Validation rules: **20 / 20** (all priorities enumerated in order in §2.6; every `error_id` alternative of every rule present)
- Endpoint paths: **47 / 47**
- Error codes: **39 / 39**
- Roles: **4 / 4**; concurrency rules: **3 / 3** (write_endpoint + occ_field + error_id + 412 all named)

**Hard contracts**
```
Field coverage check:
- entities[].fields: 90 required, 90 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 30 required, 30 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 787
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS

Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed (explicit ordered ladder + two documented precedence exceptions: placement-create addresses the Lockbox at p40 vs ERR_PLACEMENT_ALREADY_ACTIVE at p70; p40 outranks p85 for LOCK_EVIDENCE)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed, 0 missing
- state_machines[].transitions: 10 machines checked, all transitions expressed with preconditions + side effects (incl. the parallel placement_status × billing_status dimensions), 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose
- endpoints[].side_effects / applies_to: all expressed
- entities[].fields[] structured content: defaults, enums, sources, and common_fields:false for AccessEvent all stated
- sibling-branch symmetry: cascade triples (member/lockbox/listing), replacement variants, recovery variants, credential restore paths all rendered at equal density
Status: PASS
```

Constraints honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read. No audit footer was written into PRD.md — it ends at the §5 table.

## Step 6: Generate implementation — 2026-08-29T05:20:00.000Z

Implementation complete and verified.

## Files written (`.../workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `core.py` | 362 | Error catalogue (39 IDs → HTTP), response envelope, logical clock, in-memory `Store`, auth rungs 1–2, pagination, path/body lookups |
| `calc.py` | 312 | All 9 calculations: replacement charge (2 variants), late-removal tiers, member statement balance, posture, recovery rate (2 variants), risk score, risk weight, grant/showing interval arithmetic |
| `routes_grant.py` | 248 | Grant request + APPROVE/DENY/REVOKE gates |
| `serialize.py` | 229 | Per-entity serialisers with live computed fields |
| `routes_association.py` | 211 | Association, recovery-summary, 5-step compliance checkpoint, logical clock |
| `routes_lockbox.py` | 203 | Intake + ASSIGN/RETURN/REPORT_LOST/REPORT_STOLEN/RECOVER/RETIRE |
| `routes_review.py` | 162 | Incident reviews, evidence lock/close/reopen |
| `routes_showing.py` | 145 | Showings + CONFIRM/CANCEL/COMPLETE/MARK_NO_SHOW |
| `routes_listing.py` / `routes_member.py` | 136 / 136 | Listing + member state machines with 3-hop cascades |
| `routes_placement.py` | 132 | Placement create + REMOVE |
| `cascades.py` | 127 | Shared cascade/compensation hops, charge creation |
| `routes_credential.py` | 126 | Issuance + cap supersede + state machine |
| `routes_event.py` | 124 | Device ingress, outcome ladder, showing attribution |
| `routes_billing.py` / `routes_contractor.py` | 78 / 74 | Money actions, vendor cycle |
| `app.py` | 70 | Blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `ladder.py` | 62 | Shared rejection-ladder rungs |
| `start.sh` / `requirements.txt` | 8 / 1 | Guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py` |

**2946 lines total.**

## Coverage
- **47/47 endpoints** registered (verified by enumerating `app.url_map`).
- 12 entities, 10 state machines, 9 calculations, 20-rung ladder, 39 errors, 4 roles, OCC on `expected_*_version` for all 12 action endpoints.
- Storage is pure Python dicts; no seeding, no SQLite, no disk writes (grep-audited). `created_at`/`updated_at` follow the **logical clock** (required for the `temp_codes_issued_today` same-UTC-date rule); clock defaults to `2026-08-01T00:00:00Z`.

## Verification
- A 120-assertion end-to-end smoke suite (clock, counters, OCC, cap supersede, buffered grant conflict incl. the exact-buffer-edge accept, closed-interval showing capacity, outcome ladder + attribution + CONSUMED, evidence lock/SOD/reopen, delinquency `base=9000 tier=T2 admin_fee=450` → 9450 → balance 9686, posture FROZEN, both recovery variants, `DEPRECIATED_BOOK` 4560, recovery compensation to balance 0, suspend/reinstate cascade, auth ladder) → **0 failures**.
- **Boot smoke test passed**: `PORT=18571 bash start.sh` served 201/200/401/403/405 correctly on `0.0.0.0`; process killed afterwards and port confirmed closed.

## Spec ambiguities resolved (worth flagging)
1. **Terminal vs. no-declared-transition** — terminal states have no outgoing transitions, so `ERR_ENTITY_TERMINAL` (rung 11) is checked before `ERR_INVALID_STATE` (rung 9); otherwise the former is unreachable. Placement *creation* keeps PRD's literal reading (RETIRED lockbox → `ERR_INVALID_STATE`, since terminal lockdown applies only to `/state` endpoints).
2. **Charges** — PRD §2.6 lists `PAID/WAIVED/VOID` under terminal lockdown, but §3.7 and both error catalogues say a money action on those returns `ERR_CHARGE_NOT_ADJUSTABLE`. Chose the specific rule (`ERR_CHARGE_NOT_ADJUSTABLE`).
3. **RECOVER on a non-MISSING box** — §3.7 mandates `ERR_RECOVERY_WINDOW_CLOSED`, so the rung-9 transition check is deferred for that action (RETIRED still yields `ERR_ENTITY_TERMINAL` first).
4. **Showing CONFIRM** — followed the §2.6 ladder: capacity (60) is checked *before* `ERR_SHOWING_NO_LOCKBOX` (70), against §3.6's "finally, capacity" prose ordering.
5. **`temp_codes_issued_today`** — PRD contains a self-contradiction ("status anything other than DENIED" vs. "a denial does not give the quota back"). Implemented the formula (excludes DENIED), which the scaffold entity field and the DENY side-effect both corroborate.
6. **Member email uniqueness** — asserted in prose but has no error ID in the catalogue, so it is not enforced (enforcing it with a guessed ID risked breaking unrelated fixtures).
7. **`close_date` window containment** in the closing-cohort recovery rate reads the date at `00:00:00.000Z`; `dues_paid_through` / `insurance_expires_on` read at `23:59:59.999Z` per §2.10.

## Step 5: Generate unit tests — 2026-08-29T05:35:00.000Z

Complete. Final verification: 100 tests collected, every citation verbatim-grep-verified against PRD.md, every test carries exactly one `Design:` tag resolving to a real instance.

## Files written

**`test_helpers/`** (9 files, ~1,650 lines)
- `types.py` — 20 status/enum classes + entity TypedDicts; `AccessEvent` deliberately omits `updated_at`/`version` (append-only evidence)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per published endpoint (43 methods incl. `/_clock/set_current_utc`, `/_devices/access-attempts`, `recovery-summary`, `compliance-runs`)
- `api_errors.py` — all 39 error ids + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus `expected_balance()` (per-line half-up surcharge) and invariant checkers
- `factories.py`, `constants.py` (all pinned money/score/posture constants), `test_users.py` (opaque role constants + mandatory `make_member_headers(member_id)` for the entity-backed Member role)
- `fixtures.py` (581 lines) — version-refreshing primitives plus 5 tiers of composites: `setup_placed_box`, `setup_placed_box_with_credential`, `setup_approved_grant`, `setup_removal_due_placement`, `setup_delinquent_placement`, `setup_restricted_association`, `setup_frozen_association`, `setup_locked_review`
- `__init__.py` barrel

**`test_suite/`** — `conftest.py` + 10 domain-named files (`test_01_inventory_intake_and_enrollment.py` … `test_10_access_control_and_error_catalogue.py`), **100 tests**.

## Coverage

- **Queue A (Difficulty):** 44 tests / 22 instances — exactly 2 per instance, no shortfall.
- **Queue B (Corner):** 56 tests / 56 non-stub instances — 1 per instance, no shortfall. The 10 `excluded_because:` stubs were checked (every `difficulty_instance` pointer resolves) and, per spec, not translated.
- **Instances skipped: none.** Every instance passed the PRD-first two-condition filter.

## Judgment calls worth flagging

Three assertions use `validate_error_is_one_of` under the Testing-Philosophy **error-precedence** silence pattern, because PRD §2.6 places terminal lockdown (priority 45) *between* the transition check (40) and the rule the design index names, leaving the winning `error_id` genuinely non-unique:
- `retired_lockbox_terminal_lockdown_rejects_assign` and `showing_cancel_twice_second_attempt_rejected` → `[ERR_ENTITY_TERMINAL, ERR_INVALID_STATE]`
- `void_after_paid_charge_not_adjustable` → `[ERR_CHARGE_NOT_ADJUSTABLE, ERR_ENTITY_TERMINAL]` (§3.7 names the former, the ladder implies the latter)

Two design-index assertions were dropped as non-derivable while keeping the instance covered by its other assertions: the second compliance run's `delinquent_placement_count == 1` (PRD says the run "reports what it did", which reads as 0 flipped — `accrued_charge_count == 0` plus the frozen `late_days`/single charge/balance 1538 carry the claim instead), and `placement_id == null` on the temp-code overage charge (PRD only pins `lockbox_id` empty and `variant_applied` `NOT_APPLICABLE`). Two corner reviews whose recipe opened an unscoped `IncidentReview` were given an explicit `lockbox_id` scope (PRD says a review "is scoped by naming a `lockbox_id`, a `listing_id`, or both"); the asserted outcome — `event_count 0`, `risk_score 0.00`, `severity LOW` — is unchanged.

All pinned money/score values were recomputed independently and match the index: 12000/4560, balances 12300/4674/30750/41513/3076/11301/16913/1538/513, penalties `base=1500 tier=T1 admin_fee=0`, `base=10500 tier=T2 admin_fee=525`, `base=15000 tier=T3 admin_fee=1500`, risk scores 81.75, 70.00, 72.00, 100.00, recovery rates 50.00 vs 66.67.

## Step 7: Run tests and iterate — 2026-08-29T05:45:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2

**Iteration 1** (8 parallel rounds, 99/100 each): one deterministic failure, identical in all 8 rounds — `test_freshly_intaken_lockbox_cannot_be_placed_before_assignment` (`test_suite/test_02_lockbox_lifecycle.py`), `AssertionError: Expected error_id 'ERR_INVALID_STATE', got 'ERR_NOT_RESOURCE_OWNER'`. No flakiness anywhere else.

**Iteration 2** (8 parallel rounds): **100/100 in all 8 rounds.**

**Tests deleted:** none. The single failure passed STEP 1a (PRD §2.6 ¶131 states the rule verbatim: *"when a placement is being created the addressed entity for the transition check at step 9 is the lockbox, not the listing: a unit sitting in `IN_STOCK`, `MISSING`, `QUARANTINE` or `RETIRED` fails there with `ERR_INVALID_STATE`"*) and STEP 1b (no reading admits a different outcome — the sentence names the entity, the step and the error).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_02_lockbox_lifecycle.py`, `test_freshly_intaken_lockbox_cannot_be_placed_before_assignment` — the request identity was wrong, not the assertion. The test issued `POST /lockbox-placements` as a `Member` (the listing agent) against a freshly intaken box whose `assigned_member_id` is still empty. PRD §2.1 (*"a `Member` may act ... on a lockbox only when its `assigned_member_id` equals `X-User-ID`"*) plus §3.4 (*"when the caller is a `Member` the box's `assigned_member_id` must be that member"*) and the §2.6 ladder (Member ownership = priority 25, declared transition = priority 40) mean a PRD-faithful implementation must stop at `ERR_NOT_RESOURCE_OWNER` before ever reaching the step-9 check the test is about. Switched the caller to `admin_headers` — PRD §2.1: *"administrators are consequently exempt from every ownership check in the system"* — so the ladder reaches step 9 and the cited rule is actually exercised. This makes the test more faithful to the PRD sentence it quotes, not less.

**Fixes applied to `implementation/`:** none. The implementation's ownership-before-transition ordering in `routes_placement.create_placement` was correct and was left intact rather than weakened to accommodate the fixture.

Results artifacts for the confirming sweep are at `workspace/implementation/results.{1..8}.json` (all `passed == total == 100`).

**Orchestrator verification (post-Step-7 audit):** all 8 `results.*.json` present with `passed==total==100, failed=0`; 100 test functions on disk; 100 `Design:` tags (1:1); 0 `pytest.mark.skip`/`xfail` markers; no sqlite/file-write persistence in `implementation/`.

## Step 8: Finalize PRD — 2026-08-29T05:52:00.000Z

`PRD_FINALIZED.md` written. Near-zero change, as anticipated — exactly one clause revised.

## Line counts
- `PRD.md`: 426 lines
- `PRD_FINALIZED.md`: 426 lines
- Delta: 0 lines (0.00%); 1 line revised in place (0.23% of lines touched)

## Changes
- **§3.4 (listings paragraph, PRD line 215)** — *revise* — dropped the claim that "only the listing's agent may place a box on it", replacing it with an explicit statement that placement creation runs **no** listing-agent ownership check and is gated solely on the box's `assigned_member_id` — `implementation/routes_placement.py:42` (`assert_owner(role, user_id, lockbox.get("assigned_member_id"))`; no `listing_agent_id` comparison anywhere in `create_placement`).

## Pre-edit search log

**Edit 1 — §3.4 listing-agent clause**

(a) **Subject identified:** which ownership predicate governs a `Member` caller on `POST /lockbox-placements` — the box's `assigned_member_id`, the listing's `listing_agent_id`, or both. This is precisely the subject of the Step 7 test_suite fix: the fixture called as the *listing agent* against a box whose `assigned_member_id` was empty and got `ERR_NOT_RESOURCE_OWNER`. PRD.md contained two clauses in tension — §3.4's placement paragraph naming only the box's holder, and §3.4's listing paragraph asserting "only the listing's agent may place a box on it". A fresh implementer reading the latter would add a `listing_agent_id` gate that the implementation does not have.

(b) **Impl paths enumerated** (grepped every `assert_owner` callsite in `implementation/`, then read each in full):
- `routes_placement.py:42` — placement creation, owner = `lockbox.assigned_member_id`. **No listing-agent check.** <- the divergence
- `routes_placement.py:113` — placement `REMOVE`, owner = `placed_by_member_id` (matches PRD verbatim)
- `routes_listing.py:56` — listing creation, owner = supplied `listing_agent_id`
- `routes_listing.py:109` — listing state actions, owner = `listing.listing_agent_id` -> the surviving "may act on it" clause is correct
- `routes_grant.py:78` — grant request, owner = `listing.listing_agent_id` -> the surviving "may issue codes against it" clause is correct
- `routes_grant.py:189` — grant actions, owner = `issued_by_member_id`
- `routes_lockbox.py:121` — lockbox state actions, owner = `assigned_member_id`
- `routes_showing.py:51,95` — showing request / actions, owner = `showing_member_id`
- `ladder.py:39` — `assert_owner`: admins exempt, and a `None`/empty owner never equals a `Member`'s `X-User-ID`, so a freshly intaken box refuses every Member — matching §2.1 as already written
- Also read the rest of `create_placement`: the only other cross-entity constraint is `listing.association_id == lockbox.association_id` plus `listing.status == "ACTIVE"`, both already stated in §3.4.

(c) **Wording adjustment:** the naive minimal edit (delete "place a box on it") would have left the sentence silent again, reproducing the same ambiguity. I instead kept both clauses that the enumeration confirmed (`may act on it` -> `routes_listing.py:109`; `may issue codes against it` -> `routes_grant.py:78`) verbatim in substance and added an explicit negative plus the positive consequence ("a `Member` who holds the unit may hang it on a listing another agent owns"), which I verified against `create_placement` in full — nothing there constrains the placer to the listing's agent. Scoped the negative claim to placement creation only, so it does not bleed into placement `REMOVE`, listing actions, or grant issuance.

## Items deliberately NOT patched
- **Ownership (priority 25) ordered before the declared-transition check (priority 40) on placement creation** — §2.6 pins the ladder numerically and §2.6's callout names the lockbox as the addressed entity at step 9, verbatim. `routes_placement.py` runs the rungs in exactly that order. No PRD silence; kept verbatim.
- **Admin exemption from ownership** — §2.1 states it verbatim ("administrators are consequently exempt from every ownership check in the system"); `ladder.py:41` gates on `role == "Member"`. Kept verbatim.
- **`ERR_NOT_RESOURCE_OWNER` for an empty `assigned_member_id`** — follows from §2.1's equality phrasing; no edit needed.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` confirms exactly one changed line (215), matching the reported edit.

## Step 9: Complete PRD — 2026-08-29T06:02:00.000Z

`PRD_COMPLETED.md` is written at `workspace/PRD_COMPLETED.md`.

**Scope**: walked all 20 modules (~2,950 lines) of `workspace/implementation/` — every route, state-transition table, ladder call site, calc formula, cascade, and serializer field.

**Line/char counts**: PRD_FINALIZED.md 426 lines / 82,582 chars -> PRD_COMPLETED.md 426 lines / 89,282 chars (+6,700 chars). 29 lines revised in place; no new sections, no new paragraphs.

**Counts**: 24 ambiguity-pins, 7 mismatch-revisions (31 changes total).

All seven flagged ambiguities resolved: #1 (§2.6 L120/L217), #2 (§2.6 L133), #3 (§3.7 L287), #4 (§3.6 L252), #5 (§3.5 L240), #6 (§3.2 L184), #7 (§2.10 L169).

**Changes**

- §2.1 — insert — ambiguity — per-action admin-only narrowing (`ASSIGN`/`RECOVER`/`RETIRE`, `APPROVE`/`DENY`) rejected `ERR_FORBIDDEN_ROLE` at rung 2, before path resolution — routes_lockbox.py:97-99, routes_grant.py:181-183
- §2.2 — revise — ambiguity — `api_request_timestamp` reads host wall clock, not the logical clock — core.py:214
- §2.6 rung 11 — revise — **mismatch** — terminal lockdown is reached before the step-9 transition check on every existing-entity state endpoint; placement creation is the stated exception — ladder.py:45-56, routes_member.py:100-101, routes_lockbox.py:127-134
- §2.6 ¶after ladder — revise — **mismatch** — `BillingCharge` removed from `ERR_ENTITY_TERMINAL` lockdown; settled charges answer `ERR_CHARGE_NOT_ADJUSTABLE`, evaluated ahead of the transition check — routes_billing.py:51-54
- §2.10 — revise — **mismatch** — `close_date` resolves at `00:00:00.000Z` when tested for recovery-window containment — calc.py:236
- §3.1 policy dials — insert — ambiguity — dials must be non-negative integers / number, else `ERR_INVALID_REQUEST` — routes_association.py:36-48
- §3.1 counters — insert — ambiguity — `recovery_rate_pct` is stored, not live; refreshed only on close/withdraw, removal, checkpoint — serialize.py:27, calc.py:252-256
- §3.2 enrolment — revise — **mismatch** — member `email` uniqueness is expected but not enforced (no error id exists) — routes_member.py:32-60
- §3.2 enrolment — insert — ambiguity — member read also exposes `loss_report_count` and `temp_codes_issued_today` — serialize.py:45-46
- §3.2 termination — insert — ambiguity — holding hardware refuses with `ERR_INVALID_STATE` — routes_member.py:110
- §3.2 renewal — insert — ambiguity — a non-future `paid_through_date` is `ERR_INVALID_REQUEST` — routes_member.py:111-112
- §3.3 issuance — insert — ambiguity — issuance runs no standing/terminal check and no `expires_at` constraint — routes_credential.py:26-72
- §3.3 credential cap — insert — ambiguity — a cap of 0 disables the supersede — routes_credential.py:55
- §3.4 assignment — insert — ambiguity — cross-association member is `ERR_INVALID_REQUEST` at step 5 — routes_lockbox.py:117-118
- §3.4 reassignment — insert — ambiguity — reassigning to the current holder is `ERR_INVALID_STATE` — routes_lockbox.py:137-138
- §3.4 return — insert — ambiguity — blocked return is `ERR_INVALID_STATE` — routes_lockbox.py:155-156
- §3.4 placement creation — insert — ambiguity — cross-association is `ERR_INVALID_REQUEST` (step 5); box status checked before listing status, both `ERR_INVALID_STATE` at step 9 — routes_placement.py:38-48
- §3.4 late-removal charge — insert — ambiguity — `variant_applied` is `NOT_APPLICABLE` — routes_association.py:179
- §3.5 structural checks — insert — ambiguity — missing-box gate (50) precedes linkage (70); posture, window geometry and quota fall between — routes_grant.py:84-125
- §3.5 daily quota — revise — **mismatch** — internal contradiction resolved toward the formula: a denial *does* return the quota — calc.py:105-106
- §3.5 overage charge — insert — ambiguity — `basis` is `overage_fee=<cents>` — routes_grant.py:150
- §3.5 occupation gate — insert — ambiguity — the `supersedes_grant_id` target is excluded from the conflict scan — routes_grant.py:221
- §3.5 denial — insert — ambiguity — `DENY` does not advance the listing's `version` — routes_grant.py:239-240
- §3.6 showing request — insert — ambiguity — `window_start < window_end` else `ERR_INVALID_WINDOW` — routes_showing.py:54-55
- §3.6 confirmation — revise — **mismatch** — capacity (step 14) is checked before `ERR_SHOWING_NO_LOCKBOX` (step 16), reversing §3.6's "finally, capacity" prose; listing-status failure is `ERR_INVALID_STATE` — routes_showing.py:104-124
- §3.6 event derivation — insert — ambiguity — `risk_weight` computed and stored on every event at write time — routes_event.py:75
- §3.7 recovery — revise — **mismatch** — step-9 deferred for `RECOVER`, but a `RETIRED` box yields `ERR_ENTITY_TERMINAL` first — routes_lockbox.py:127-134
- §3.7 replacement charge — insert — ambiguity — `basis` string formats for both variants — calc.py:155-169
- §3.8 review scope — insert — ambiguity — both identifiers widen (OR) the scope; neither is accepted and yields a permanently empty evidence set — routes_review.py:23-36
- §3.8 review close — insert — ambiguity — the `findings` check (priority 20) outranks segregation of duties (priority 30) — routes_review.py:133-140
- §3.9 checkpoint — insert — ambiguity — every step scoped to the association in the path — routes_association.py:117-167
- §3.9 recovery summary — insert — ambiguity — `variant`/`window_start`/`window_end` are query parameters; bad values are `ERR_INVALID_REQUEST` — routes_association.py:68-88

**Orchestrator verification:** 426 lines preserved; 29 lines changed vs PRD_FINALIZED.md; markdown header count unchanged; 90 table rows (47 endpoint + 39 error + separators) intact.

---

# Pipeline complete — final state

All 9 steps done. Final confirming sweep: `results.{1..8}.json`, each `passed == total == 100`, `failed == 0`.
