# Worklog — task_2945_neighborhood_fiber_build_preorder_campaign

## Step 1: Create task directory — 2026-09-05T19:55:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2945_neighborhood_fiber_build_preorder_campaign` and its `workspace/` subdirectory. Index 2945 was pre-assigned by the orchestrating caller; no index scan was performed (concurrent pipelines on this host would collide).

## Step 2: Generate Scaffold — 2026-09-05T21:07:00.000Z

Step 2 scaffold generation for task_2945 is complete and lint-clean.

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_2945_neighborhood_fiber_build_preorder_campaign/`)

| File | Lines | Notes |
|---|---|---|
| `SCAFFOLD.yaml` | 2970 | §1.0–§1.7 only; top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no design keys leaked in |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2415 | single key `scaffold_difficulty_design`, 9 rule_ids / 19 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3441 | single key `scaffold_corner_design`, 9 sections / 84 instances (57 full recipes, 27 `excluded_because` stubs) |

All three parse under `yaml.safe_load`. `.scratch/step2/` removed; `workspace/` untouched; nothing written outside the task dir.

Linter verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1062

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Domain model
- **14 entities**: Campaign, BuildZone, ServiceAddress, Account, Preorder, PermitApplication, PoleAttachmentRequest, MduOwnerAgreement, InstallCrew, InstallAppointment, RestorationFollowup, FallbackOption, FallbackOffer, DamageClaim, plus an immutable LedgerEntry (no `version`, no update endpoint).
- **65 endpoints** under a `/` prefix, incl. `POST /_clock/set_current_utc` (default clock 2026-08-01T00:00:00Z), paginated lists (`limit/offset/total_count/has_more`), and action endpoints for qualification-run, sequencing-run, construction-start/complete, conversion, serviceability-determination, unserved-exception, threshold/extension patches, permit submit/decision, pole survey/decision/attachment, appointment outcome, restoration follow-up, damage-claim assess/decide/appeal.
- **8 roles**: ProgramManager, PermitOffice, UtilityOperator, InstallCoordinator, ClaimsAssessor, ClaimsApprover (opaque) + Subscriber and MduOwner (`entity_backed: Account`). `role_model: segregation_of_duties` — the assessor of a damage claim cannot decide it.
- **12 state machines** (`state_machine_shape: parallel` — BuildZone carries independent campaign and construction dimensions), **8 calculations**, **33 validations** on a strict 1..33 priority ladder, **54 errors**, **2 `concurrency_rules`** (`preorder-create-stale-zone` → ERR_STALE_BUILD_ZONE_VERSION 412; `appointment-create-stale-crew` → ERR_STALE_CREW_VERSION 412).
- `complexity_profile`: layers `[optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, selector_policy]`, topology `flat`, consistency `immediate`, difficulty `expert_plus`.

## §1.8 difficulty rules (9 rules / 19 instances)
1. **dual_variant_divergence** — `provisional_vs_final_rate_diverge_on_undetermined_address` (UNDETERMINED addresses count provisionally, not finally); `damage_claim_late_filing_variant_reduces_assessment`.
2. **remainder_distribution** — `make_ready_share_floor_then_remainder_order` (integer-cent floor, remainder by zone_code).
3. **tier_evaluation_order** — `conversion_settlement_discount_tier_evaluated_pre_deposit`.
4. **nonlinear_composition** — `readiness_score_nonlinear_min_max_composition`.
5. **parallel_state_dimensions** — `build_zone_parallel_campaign_and_construction_dimensions`; `mdu_agreement_counter_offer_cycle_returns_to_sent` (cyclic COUNTERED→SENT under a counter limit).
6. **transitive_cascade** — `not_qualified_run_cascades_zone_preorder_deposit_ledger_account` (4 hops to the account balance); `pole_denial_cascades_zone_suspend_appointment_cancel_crew_release` (ordering-sensitive).
7. **validation_priority_conflict** — `prereg_window_closed_outranks_duplicate_preorder`; `zone_construction_not_active_outranks_invalid_window`.
8. **boundary_pairs** — `final_rate_exactly_at_threshold_qualifies_one_hundredth_below_does_not`; `crew_daily_capacity_exact_fit_accepted_next_minute_rejected`; `construction_start_blocked_until_every_required_permit_is_approved`; `mdu_conversion_blocked_until_owner_agreement_is_signed`; `crew_buffered_halfopen_interval_rejects_11_29_accepts_11_30`; `zone_bury_concurrency_counts_raw_windows_not_buffered_ones`.
9. **conservation_invariants** — `deposit_cents_conserved_across_preorder_create_then_cancel`; `crew_minutes_conserved_across_appointment_schedule_then_cancel`.

## §1.9 corner sections (taxonomy fixed by the claim-extraction guide)
`entities` 13 · `state_machines` 13 · `calculations` 13 · `validations` 13 · `endpoints` 11 · `errors` 10 · `rbac` 4 · `cross_cutting_complexity_layers` 6 · `consistency_model` 1.

The final two sections added this pass: two full OCC recipes (one per `concurrency_rules` entry, each showing 412-then-succeed-on-reread and that a refused write does **not** bump `version`), two `cascading_side_effects` stubs citing the §1.8 transitive-cascade instances, one `rate_threshold_triggers` recipe (8.00% on 25 households flips NOT_QUALIFIED→QUALIFIED purely by lowering the bar to 8.00, inclusive comparison), one `selector_policy` recipe (speed/price/rank all tie → `created_at ASC` decides, never `id`), and one `immediate` consistency recipe (HELD already in the 201 body; zone rate, account balance and ledger row all correct on the very next reads with no clock movement).

## Design adjudications
- **Error coverage is now 54/54** — a scripted cross-check against `SCAFFOLD.yaml`'s `errors` list found zero uncovered ids. ERR_STALE_BUILD_ZONE_VERSION and ERR_STALE_CREW_VERSION were deliberately deferred to the cross-cutting OCC instances so each `concurrency_rules` entry maps to its own stale-version test, as the guide requires.
- **Instance names were chosen against the linter's `_NEGATIVE_NAME_RE`**: rules (b) role-legality and (c) payload-keys-subset are skipped for negative triggers, so intentionally-invalid-role/payload instances are named to match (`..._are_forbidden_to_other_roles`, `..._returns_the_entity_specific_not_found_code`, `..._rejects_a_response`, `mdu_owner_cannot_...`) rather than weakening §1.5.
- **Stub discipline**: all 27 `excluded_because` stubs cite a §1.8 instance by `name` and omit `test_recipe`; names are unique across the union of both design files (verified programmatically).
- Every numeric literal was derived by reading §1.3 formulas/constants back out of `SCAFFOLD.yaml` (LAWN cap 120000, restoration_sla_days 7, permit valid_days 120 → 2026-11-29, extension_grant_days 30 → 2026-10-30T23:59:00Z, occupied 120+30=150, 100/6→16.67, 200/6→33.33), and every chain was checked for temporal feasibility against the logical clock.
- One YAML trap worth flagging for later steps: inside flow mappings, JSONPath captures must be quoted (`{ le1: "$.data[0].id" }`) because `[` is a YAML indicator.
- The `scenario` value is byte-verbatim, including the leading "Generate task harder than expert level!" directive line — per the standing note, the orchestrator should strip that line before Step 3/4 so it cannot reach PRD.md.

**Orchestrator post-step action:** the difficulty directive line ("Generate task harder than expert level!") plus its trailing blank line were stripped from `SCAFFOLD.yaml`'s `scenario` block by the orchestrator so it cannot reach PRD.md. Verified: `grep -rn "harder than expert" .` returns nothing across all three YAMLs; `yaml.safe_load` still parses. SCAFFOLD.yaml is now 2968 lines.

## Step 3: Copy shared files — 2026-09-05T21:08:56.816Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T21:26:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **448 lines / 107,206 bytes**, ending at a real section boundary (last heading `## 5. Error Code Catalogue` at line 389; final line is the last catalogue row `| ERR_NO_FALLBACK_OPTION_AVAILABLE | 409 |`). Written in 8 incremental appends; no truncation. `SCAFFOLD.yaml` and all other pre-existing files untouched; `.scratch/step4/` removed, parent `.scratch/` left intact. The two withheld design files were never opened, and no sibling task directory was read.

**Section list**
- `# Neighborhood Fiber Build & Preorder Campaign API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors, Identity Headers and RBAC · 2.2 API Response Structure (byte-identical fixed contract) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Parallel State Dimensions · 2.6 Recomputation, Cascades and Version Semantics · 2.7 Money, Rates and Rounding · 2.8 The Append-Only Deposit and Claim Ledger · 2.9 Optimistic Concurrency on Zones and Crews · 2.10 The Order in Which a Request Is Rejected · 2.11 Filters and Reverse Reachability
- `## 3. Business Logic & Workflows` — 3.1 Launching a Campaign and Carving Fiberhoods · 3.2 The Address Registry, MDU Access and the Unserved-Address Path · 3.3 Preregistration: Sign-Ups, Deposits and the Live Rate · 3.4 Qualification and Its Cascades · 3.5 Permits, Pole Attachments and Build Sequencing · 3.6 Breaking Ground, Suspension and Declaring a Fiberhood Ready · 3.7 Converting a Preorder into an Install Order · 3.8 Crews, Appointment Windows and Visit Outcomes · 3.9 Restoration Obligations and Construction Damage Claims
- `## 4. Endpoint Definitions` (4-column table, 65 rows)
- `## 5. Error Code Catalogue` (2-column table, 54 rows)

**Hard Contract results**
1. **Field-Name Coverage — PASS.** Programmatic diff of the 141 required identifiers (131 entity field names ∪ 91 endpoint `input`/`query_params`/`path_params` names, deduped) against every backticked token in PRD.md: **0 missing**. Endpoint-only names (`action`, `current_utc`, `decision`, `expected_build_zone_version`, `expected_crew_version`, `limit`, `offset`, `outcome`, `response`, `tendered_deposit_cents`) all present.
2. **Rule Coverage — PASS.** All 33 validations rendered as an explicitly numbered priority ladder in §2.10 (verified count = 33), each with error ID, HTTP status and exact `applies_to` scope. Both `concurrency_rules` rendered in §2.9 with their 412 rejections. All 12 state machines / 56 transitions rendered with their guards and side effects (18 are phrased without a literal `A -> B` arrow — e.g. the `UNDETERMINED` determination fork, the six symmetric MDU sign/decline/expire branches, the three appointment outcomes, the three offer responses — but each is stated with its from-state, to-state, guard and effects). All 8 calculations rendered with every pinned constant, order-of-operations and rounding rule. All 54 error IDs appear in §1–§4 prose in addition to §5 (verified: 0 absent). All 8 roles named in §2.1 and used throughout. Field-level defaults/initials, sibling-branch symmetry, and the four multi-hop cascades (MDU signature, pole denial, permit expiry, zone suspension) all present.
3. **§3 Path Purity — PASS.** Scan of every backticked token between `## 3.` and `## 4.`: **0 tokens** starting with `/`, bare HTTP methods, or method+path combinations. Literal paths appear only in §2.10/§2.11 (permitted) and §4.

**Adjudications** (scaffold self-contradictions; each resolved toward the statement that governs observable responses, and noted here rather than in the PRD)
1. `daily_capacity_minutes` — entity says 1..1440, validation says 60..1440 -> used **60..1440**.
2. `max_concurrent_bury_ops` — entity says `>= 1`, validation says 1..10 -> used **1..10**.
3. `counts_toward_threshold` — field description implies the FINAL-variant predicate (UNDETERMINED excluded) but `POST /service-addresses` side-effects say it is computed **true** for a new undetermined address -> followed the operational statement, and additionally stated §3.4's FINAL-variant inclusion predicate directly in terms of `serviceability` so the rate is right either way.
4. Deadline-extension window edge — transition says strictly before `prereg_deadline_at`, validation says at-or-before -> used **at or before**.
5. Qualification-run eligibility — transition says `prereg_deadline_at <= current_utc`, validation phrases the refusal as strictly greater -> unified both on **"deadline at or before the logical clock"**.
6. `PoleAttachmentRequest.make_ready_cost_cents` at creation — field says null until surveyed, endpoint says 0 -> used **0**.
7. `Campaign.prereg_window_open_at` — a pre-window sign-up has no dedicated error -> mapped to **`ERR_PREREG_WINDOW_CLOSED`** (the only window error in the catalogue).
8. Conversion when the zone has not broken ground — `ERR_ZONE_CONSTRUCTION_NOT_ACTIVE` is scoped by `applies_to` to appointment booking only -> conversion's zone precondition failure mapped to **`ERR_BUILD_ZONE_STATE_INVALID`**.

Entity class names (`MduOwnerAgreement`, `PermitApplication`, etc.) are intentionally rendered as prose nouns rather than CamelCase identifiers, per the skill's writing-style rule; all 14 resources remain individually identifiable.

**Orchestrator truncation check (per standing guard):** `tail -c 600 PRD.md` shows the §5 error table completing normally at `| ERR_NO_FALLBACK_OPTION_AVAILABLE | 409 |` — a real section boundary, not mid-sentence. 448 lines / 107,206 bytes. `grep -in "scaffold|harder than expert|test_recipe"` returns nothing, so neither the difficulty directive nor the design indices leaked. PRD accepted without regeneration.

## Step 6: Generate Implementation — 2026-09-05T22:04:00.000Z

Implementation complete and verified. Everything lives in `workspace/implementation/`.

## Modules (3,498 lines of Python + `start.sh` + `requirements.txt`)

Support layer: `app.py` 59, `store.py` 186, `errors.py` 72, `envelope.py` 92, `auth.py` 45, `shape.py` 225, `calc.py` 435, `cascades.py` 154, `serialize.py` 285, `listing.py` 41.
Routes (`routes/`): `__init__.py` 40, `clock.py` 19, `campaigns.py` 165, `zones.py` 226, `addresses.py` 215, `accounts.py` 65, `mdu.py` 138, `permits.py` 117, `poles.py` 135, `preorders.py` 180, `crews.py` 48, `appointments.py` 233, `claims.py` 178, `fallback.py` 109, `ledger.py` 36.

`start.sh` is 5 lines: `set -e`, `cd "$(dirname "$0")"`, `export PORT="${PORT:-10000}"`, `exec python3 app.py` (foreground, binds `0.0.0.0`, no `pip install`). All state is module-level dicts in `store.db`; nothing is seeded, nothing touches disk.

## Coverage verified mechanically, not by eye

- **Endpoints: 65 implemented, 65 in PRD §4, zero missing, zero extra.** Diffed `app.url_map` against the method/path pairs parsed out of the PRD table.
- **Errors: 54 codes, exact set match with PRD §5 and zero HTTP-status mismatches** (same programmatic diff).

## Structure

- **State machines** are plain guarded transitions inside each route handler; the three parallel-dimension entities keep their dimensions in separate columns and no handler writes both unless the PRD says the second is a consequence.
- **Calculations** all live in `calc.py` as pure functions over the store (`prereg_rate` with PROVISIONAL/FINAL admission variants, `readiness_score`, `allocate` floor-then-distribute, `settlement`, `assess_claim`, `select_fallback_option`, `balances` by full ledger replay). `Decimal` + `ROUND_HALF_UP`, integer cents throughout.
- **Derived vs stored:** only frozen/stamped values persist (`final_*`, `readiness_score`, `build_sequence_index`, `make_ready_share_cents`, `conversion_*`); every aggregate is recomputed in `serialize.py` at response time, so recomputation can never go stale.
- **Validation ladder:** each handler calls the checks in PRD §2.10's numeric order — `auth.identify`/`gate` (1-2), `must_find` on path ids (3), `listing.resolve` for body FKs (4), `auth.own` (5), `shape.*` (7), then domain gates. `listing.resolve` deliberately defers malformed FK values to step 7 so a non-string id yields 400 not 404.
- **OCC:** `expected_build_zone_version` / `expected_crew_version` are parsed with no minimum bound and compared at ladder positions 11-ish, after the window checks on preorders. Lazy expiry is deliberately *not* run on `POST /preorders`, because a cascading expiry there would bump the zone version underneath the OCC check.
- **Cascades** are centralized in `cascades.py`: `suspend_zone` -> `cancel_zone_appointments` -> one `bump` per distinct crew; `sign_cascade`/`withdrawn_cascade` for MDU outcomes; `expire_*` + `touch_zone`/`touch_address` for lazy expiry; `move_deposit` as the single place the money dimension moves and appends its one signed ledger entry. Every hop bumps exactly once per operation.

## Smoke tests (all servers killed by exact PID; no pattern kills)

Three scripts, ~110 calls, on ports 29457, 29458, 29459.

- Boot, kill, re-boot on the same port: server comes up in <4s and both `/campaigns` and `/build-zones` return `total_count: 0`, proving per-test state wipe.
- Full happy path end to end: clock -> campaign -> zone -> address -> determination -> account -> preorder -> threshold relief -> extension -> qualification-run -> sequencing-run -> permit submit/reject/resubmit/approve -> pole survey/accept/attach -> construction-start (make-ready allocated to the preorder) -> crew -> appointment -> completion -> damage claim file/assess/approve (payout to `credit_balance_cents`) -> conversion (149900 pre-discount, 14990 discount) -> restoration follow-up -> parent satisfied -> suspend/resume -> construction-complete -> MDU agreement offer/counter/sign with the `CONDITIONAL_MDU -> SERVICEABLE` cascade -> all 14 list endpoints.
- Deep cascade and error paths: pole DENY on an `IN_CONSTRUCTION` zone -> zone `SUSPENDED`/`POLE_DENIED`, appointment `CANCELLED`/`ZONE_SUSPENDED`, crew minutes released 90->0 with its own version bump; `ERR_DUPLICATE_PREORDER` correctly preceding `ERR_DEPOSIT_AMOUNT_MISMATCH` (402); `ERR_NOT_RESOURCE_OWNER`, `ERR_CREW_DAILY_CAPACITY_EXCEEDED`, `ERR_INVALID_WINDOW`, `ERR_NO_FALLBACK_OPTION_AVAILABLE`, `ERR_PREREG_DEADLINE_NOT_REACHED`, `ERR_STALE_BUILD_ZONE_VERSION`/`ERR_STALE_CREW_VERSION` (412), unknown role -> 401, unknown id -> typed 404, `limit=0` -> 400; fallback selection picking the 300 Mbps option then, after a DECLINE permanently excludes it, the 50 Mbps one; lazy offer expiry materializing only on the next read.

Every failure the scripts reported turned out to be the scenario being wrong, not the server — each one traced back to the PRD sentence and confirmed the implementation was right (`prereg_deadline_at` is a system field seeded from the campaign close and ignores client input; the FINAL rate variant drops `UNDETERMINED` addresses; exceptions require `NOT_SERVICEABLE`; RESUME is admissible past a DENIED pole when another pole is ATTACHED; account creation is `ProgramManager`-only).

## PRD adjudications worth flagging to Step 7

- **Qualification eligibility is strict** (`prereg_deadline_at < clock`) for both the run gate and per-zone eligibility. §3.4 says "at or before" but its very next sentence says zones "still inside their window are silently skipped", and §2.10.16 defines the deadline instant as *inside* the window — so strict is the only self-consistent reading, and it agrees with §2.10.17.
- `extend-deadline`/`threshold` use the inclusive window comparator (`clock <= deadline`) per §2.10.16, overriding the scaffold's strict form.
- Capacity gates run in ladder order 21 conflict -> 22 bury cap -> 23 daily capacity, with `ERR_ADDRESS_NOT_SERVICEABLE` (24) *after* all three.
- Uniqueness violations (zone_code in campaign, account email, street_address in zone) -> `ERR_INVALID_REQUEST` 400, since the catalogue has no dedicated code.
- Conditionally-required fields (`not_serviceable_reason`, `rejection_reason`, `denial_reason`, `countered_fee_cents`, `parent_appointment_id`) -> 400 at ladder step 7; pole-decision branch roles -> 403 after the enum parse.
- Both run endpoints emit `response_type: "array"` with no pagination block; `POST /_clock/set_current_utc` returns `data: {}`.
- Version fields carry no declared range, so `expected_build_zone_version: 0` yields 412, not 400.

`.scratch/step6/` has been removed; `.scratch/step5/` was left untouched. `worklog.md`, both `SCAFFOLD_*_DESIGN.yaml` files, and `test_suite/`/`test_helpers/` were never read or written.

## Step 5: Generate Unit Tests — 2026-09-05T22:54:00.000Z

Step 5 complete. Test suite generated, self-audited clean, and confined to the task root.

## Files written (task root, not `workspace/`)

`test_helpers/`
| file | lines |
|---|---|
| `__init__.py` | 54 |
| `api_client.py` | 315 |
| `api_errors.py` | 126 |
| `assertions.py` | 525 |
| `constants.py` | 106 |
| `factories.py` | 274 |
| `fixtures.py` | 662 |
| `test_users.py` | 143 |
| `types.py` | 515 |

`test_suite/` — `conftest.py` 61; queue A `test_01` 248, `test_02` 122, `test_03` 172, `test_04` 182, `test_05` 268, `test_06` 201, `test_07` 175, `test_08` 241, `test_09` 236, `test_10` 229; queue B `test_11_entity_shapes` 413, `test_12_state_machine_edges` 316, `test_13_calculation_edges` 232, `test_14_validation_edges` 399, `test_15_endpoint_behaviours` 366, `test_16_error_families` 631, `test_17_rbac` 261, `test_18_concurrency_and_layers` 315. Total 7,788 lines.

## Coverage

- **110 tests total**: queue A (Difficulty) **53**, queue B (Corner) **57**.
- **Difficulty §1.8: 19/19 instances covered**, 53 tests, minimum 2 tests per instance (the skill's audit floor), none under.
- **Corner §1.9: 57/57 live instances covered**, exactly one test each. The yaml holds 84 `- name:` entries; 27 carry `excluded_because:` and no `test_recipe` (stubs), and none of them was tested — no over-reach.
- Every test carries exactly one `Design:` line; every docstring has at least one verbatim >=8-word PRD quote that greps clean after normalisation; no unused `test_helpers` imports; no occurrence of the word "scaffold" anywhere in the generated code. All 28 generated `.py` files `py_compile` clean, so nothing is truncated.

## Skipped instances and reasons

No live design instance was skipped for PRD silence or non-unique-derivability — the PRD is dense enough that all 19 difficulty and all 57 live corner instances were groundable. The only untested instances are the 27 corner stubs, which are excluded by the index itself.

## Notable design adjudications (index vs PRD; PRD wins)

- HTTP statuses: `ERR_INVALID_REQUEST` asserted as **400** (index said 422); `ERR_ADDRESS_LINKAGE_MISMATCH` as **422** (index said 409).
- Field names the index invented were mapped to the PRD's real ones: `submitted_at`/`resubmission_count`/`decided_at`/`determined_at` -> `submission_round`, `approved_at`, `reviewer_user_id`, `serviceability_determined_at`.
- `undetermined_address_may_still_be_preordered`: asserted `counts_toward_threshold is True` (index said false) — §3.2 makes `UNDETERMINED` count.
- `pole_acceptance_rolls_the_quote_into_the_zone_make_ready_cost`: `readiness_posture` asserted **BLOCKED** (index said `POLE_PENDING`) — §2.6 puts the no-approved-permit case at `BLOCKED`.
- Pole `denial_reason` free text in the index ("No spare capacity...") replaced with the enumerated `CAPACITY_FULL`.
- `mdu_owner_cannot_answer_another_owners_agreement`: the index wants the address serviceability "untouched by the signature"; §3.2 only defines `CONDITIONAL_MDU -> SERVICEABLE`, so the fixture leaves the address `UNDETERMINED` and the test asserts that, with the full three-hop cascade sentence as grounding rather than pre-setting `CONDITIONAL_MDU` (which would have contradicted the instance).
- Corner ASSERT lines that cited scaffold sections were re-expressed against PRD text or dropped.

Fixture traps all handled: money as JSON ints in cents, ISO-8601 full instants everywhere the PRD declares instants, timestamp comparison canonicalised in `assertions.assert_instant_equals`, blank headers as `""`, a single envelope-unwrapping convention, both `validate_paginated` and `validate_unpaginated` present and used per declared shape, and distinct `X-User-ID`s per distinct owner (each preorder gets its own account/subscriber identity).

Scratch cleanup removed only `.scratch/step5`; the shared `.scratch/` parent is intact. `workspace/implementation/`, `workspace/PRD.md`, `worklog.md` and the `SCAFFOLD*.yaml` files were not modified.

**Orchestrator verification:** `test_helpers/` and `test_suite/` are both at the task root — no strays under `workspace/`. 110 `def test_` functions and exactly 110 `Design:` tags. `python3 -m py_compile` clean across all 28 files. The orchestrator also pre-wrote `workspace/sweep.sh` for Step 7: a detached script-file sweep (avoids the inline-quoting bug that kills all 8 rounds at t=0), per-round `round.$i.log` files (one shared fd across 8 rounds produces spliced garbage), and a `SWEEP_DONE` sentinel (the `setsid` wrapper returns in ~1 min while the rounds keep running, so exit status is meaningless and relaunching would double the load).

## Step 7: Run Tests and Iterate — 2026-09-05T23:15:00.000Z

All 8 parallel rounds are green: **110/110 passed in every round**, union failure set empty.

## Iterations run: 3

**Iteration 1** — 108/110 in all 8 rounds, 2 deterministic failures (no flakiness anywhere in the suite; the sweep runs in ~2.5 min on this host).

Both failures were the same `readiness_posture` disagreement: `BLOCKED` returned vs `PERMIT_PENDING` asserted, on a `NOT_STARTED` zone with one required permit type (`ROW`) whose only application was `SUBMITTED` (test_12) or `REJECTED` (test_16).

Diagnosis: PRD §2.6 defines the posture as an ordered cascade — *"It reads `BLOCKED` when `construction_status` is `NOT_STARTED` and none of the zone's required permit types has an `APPROVED` application; `PERMIT_PENDING` when at least one required permit type still lacks an `APPROVED` application; ... and `READY` in every remaining case."* The trailing *"in every remaining case"* pins sequential evaluation, and `implementation/calc.py::readiness_posture` implements exactly that cascade. Decisively, the suite contradicted **itself**: `test_12:82` and `test_12:107` assert `BLOCKED` for the identical zone shape with a `DRAFT` application, and nothing in the PRD posture rule distinguishes `DRAFT` from `SUBMITTED`/`REJECTED` (it reads only "has an `APPROVED` application"), so no single implementation could satisfy both call sites. The two failing sites were the minority drift, apparently generated off §3.5's compressed narrative *"steps from `PERMIT_PENDING` to `POLE_PENDING`"* (which is the multi-required-type case, and passes at `test_09:91` where the zone is `SEQUENCED`). Implementation left untouched; minority call sites made to match the majority.

**Iteration 2** — 109/110 in all 8 rounds; one residual assertion in the same test.

**Iteration 3** — clean.

## Tests deleted
None. Both failures were resolved as test-artifact corrections at the assertion level (STEP 2 / STEP 1c partial-coverage handling).

## Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header bug surfaced.

## Fixes applied to `test_suite/`
- `test_suite/test_12_state_machine_edges.py` — `test_approving_the_last_required_permit_steps_the_zone_on_to_pole_pending`:
  - pre-decision assertion `zone_before["readiness_posture"] == "PERMIT_PENDING"` -> `== "BLOCKED"`, matching PRD §2.6's ordered cascade and the suite's own majority convention; docstring extended with the verbatim §2.6 quote. The post-decision `POLE_PENDING` assertion (verbatim §2.6-covered) is retained.
  - removed the uncovered assertion `zone_after["version"] == zone_before["version"] + 1` (STEP 1a silence). PRD attaches *"increments the zone's `version` by 1"* explicitly to pole accept/deny/attach, sequencing, ground-break, suspend, resume and complete — and never to permit create/submit/decide, where §3.5 says only *"recomputes the zone's `readiness_posture`"*. Since §2.6 states `readiness_posture` *"is purely derived and never written directly"*, no zone row mutation occurs, so a PRD-faithful reader leaves the zone version alone. This was the only zone-version assertion around a permit action in the whole suite.
- `test_suite/test_16_error_families.py` — `test_the_resubmission_allowance_is_spent_by_the_second_submission`: final assertion `readiness_posture == "PERMIT_PENDING"` -> `== "BLOCKED"` (same §2.6 cascade; the zone never received an approval). The test's core rule — the resubmission cap and `ERR_RESUBMISSION_LIMIT_REACHED` — is unchanged and fully covered.

## Fixes applied to `implementation/`
None. No implementation defect was found; both failures traced to test-artifact assertions, and no PRD-required check was weakened or removed.

Notes: `worklog.md` was not touched by the subagent, and no `.scratch` content was created or deleted.

**Orchestrator independent verification of the sweep artifacts** (a Step 7 agent has previously claimed a clean sweep with no results files on disk, so this is checked directly rather than trusted): all 8 `workspace/implementation/results.$i.json` exist, timestamped 23:06, each parsing to `passed=110 total=110 failed=0`. `grep -l Terminated workspace/round.*.log` returns nothing, so the reaping signature (SIGTERM'd rounds masquerading as flakiness) is absent and the green result is real.

**Step 8 gating decision:** Step 7 applied **0 `implementation/` fixes** and **0 deletions**, but it DID apply 2 `test_suite/` fixes, one of which (`readiness_posture` `PERMIT_PENDING` vs `BLOCKED`, and the removed permit-action zone-version assertion) is a genuine PRD-ambiguity signal: §3.5's compressed narrative admits a reading that §2.6's ordered cascade contradicts, and the version-bump silence let a test assert a bump the impl does not perform. The skill's skip condition requires zero fixes across *all four* categories, which is not met here, so Step 8 runs with those two items as its focus list.

## Step 8: Finalize PRD — 2026-09-05T23:24:00.000Z

Done. `PRD_FINALIZED.md` written; only that file was created/modified.

## Size
- PRD.md: 448 lines / 107,206 bytes
- PRD_FINALIZED.md: 448 lines / 108,802 bytes (+1,596 bytes, +1.49% by size; 0% by line count — 3 physical lines touched, 6 diff lines total)
- Tail verified: still ends at the §5 error-catalogue's last row (`| ERR_NO_FALLBACK_OPTION_AVAILABLE | 409 |`); `diff` shows exactly the 4 intended edits and nothing else.

## Changes (all traced to the single Step 7 item: the `readiness_posture` disagreement + the one deleted zone-version assertion)

- **§2.6 (posture definition) — insert** — the five clauses are now declared an ordered cascade with first-match-wins, `SUSPENDED` tested before all others, and `BLOCKED` (not `PERMIT_PENDING`) pinned for a `NOT_STARTED` zone with no `APPROVED` application among its required types regardless of how many types it requires or whether the applications sit in `DRAFT`/`SUBMITTED`/`REJECTED`/`EXPIRED` — `implementation/calc.py:222-234`.
- **§3.5 (permit approval narrative) — revise** — "steps from `PERMIT_PENDING` to `POLE_PENDING`" replaced by a re-derivation statement: an unsuspended zone whose last outstanding required type is approved reads `POLE_PENDING`, or `READY` if a pole is already `ATTACHED`, and read `BLOCKED` beforehand when still `NOT_STARTED` with zero approvals, `PERMIT_PENDING` otherwise — `implementation/calc.py:222-234`, `implementation/routes/permits.py:108-117`.
- **§3.5 (end of the deciding paragraph) — insert** — permit-track writes (open/submit/resubmit/approve/reject/lapse) do not touch the zone row, so the zone's `version` and `updated_at` are unchanged; the zone counter moves only where §3 says an operation increments it, which on this track is only the lapse-triggered suspension — `implementation/routes/permits.py:20-117` (no `bump(zone)`), `implementation/cascades.py:92-102`, `implementation/serialize.py:59`.
- **§3.5 (permit expiry) — revise** — "Expiry recomputes the zone's `readiness_posture` to `PERMIT_PENDING`" widened to a §2.6 re-derivation: usually `PERMIT_PENDING`, `BLOCKED` on a still-`NOT_STARTED` zone left with no approval, `SUSPENDED` once the lapse suspends it — `implementation/cascades.py:92-102`, `implementation/calc.py:222-234`.

## Per-edit pre-edit search log

**Edit 1 — §2.6 cascade order.** (a) Subject: how `readiness_posture` is derived and in what order its clauses are tested. (b) Enumerated: `grep -rn "readiness_posture|POSTURES|approved_required_types"` over `implementation/` -> the value has exactly one producer, `calc.py::readiness_posture` (SUSPENDED -> BLOCKED -> PERMIT_PENDING -> POLE_PENDING -> READY), one consumer, `serialize.py:59`, and no route branches on it (`routes/zones.py:147` uses `approved_required_types` directly for the ground-break gate, not the posture). Also read `calc.py::approved_required_types`, `shape.opt_enum_list` (proves `required_permit_types` can never be empty, so the BLOCKED/PERMIT_PENDING overlap is always live and ordering is load-bearing), and every posture-valued claim elsewhere in the PRD (§3.5 attach -> READY, sequencing, §3.6 ground-break/suspend/resume/complete) to check dominance does not contradict them. (c) Adjustment: restricted the "in particular" example to the NOT_STARTED/zero-approval case and explicitly excluded `APPROVED` from the enumerated application states, so the sentence stays true when an `APPROVED` application exists for a *non-required* type (impl: that zone is still `BLOCKED`).

**Edit 2 — §3.5 approval transition.** (a) Subject: the posture value immediately before and after the approval that completes a zone's required set. (b) Enumerated: `routes/permits.py::decide_permit` (bumps only the permit), `calc.readiness_posture` branch-by-branch against zone states `NOT_STARTED` / `SEQUENCED` / `IN_CONSTRUCTION` / `SUSPENDED` / `SERVICE_READY`, `calc.zone_poles` + the `ATTACHED` test, and `routes/poles.py` (attachment path, which owns the POLE_PENDING -> READY step). (c) Adjustments: added "unsuspended" (a `SUSPENDED` zone can still receive an approval — `decide_permit` has no zone-state gate — and stays `SUSPENDED`); added the "or `READY` when a pole already reached `ATTACHED`" alternative; scoped the "beforehand" clause to a zone whose last *outstanding* required type was just approved, which excludes the redundant second-approval case where the prior value was already `POLE_PENDING`.

**Edit 3 — zone `version` on permit actions.** (a) Subject: which operations write the zone row / increment `zone.version`. (b) Enumerated: `grep -rn "bump("` across all of `implementation/` — zone bumps exist at `routes/zones.py:116,133,158,192,225`, `routes/addresses.py:60,134`, `routes/preorders.py:96,143`, `routes/poles.py:107,116,134`, `routes/campaigns.py:92,164`, `cascades.py:34,58,73`; `routes/permits.py` bumps only the permit row (88, 116) and `create_permit` inserts a fresh row; `cascades.expire_permit` bumps the permit and reaches the zone only via `suspend_zone`; `cascades.touch_zone` only loops `expire_permit`; `store.bump` confirms bump = version+1 + updated_at; `serialize.build_zone` confirms posture is computed at read time, never stored. (c) Adjustment: the first draft said the zone counter moves "only through the operations that this section and §3.6 describe as incrementing it" — that would have been a false universal, since the enumeration shows §3.2/§3.3/§3.4 operations (address create, serviceability determination, preorder create/cancel, MDU sign/withdraw cascades, qualification) also bump the zone. Widened to "only where §3 says an operation increments it".

**Edit 4 — §3.5 expiry posture value.** (a) Subject: the posture a zone shows after a permit approval lapses. (b) Enumerated: `cascades.expire_permit` -> `suspend_zone` (only when `IN_CONSTRUCTION`), then `calc.readiness_posture` evaluated for each post-lapse zone state: SUSPENDED -> `SUSPENDED`; NOT_STARTED with zero remaining approvals -> `BLOCKED`; NOT_STARTED multi-type with another approval -> `PERMIT_PENDING`; SEQUENCED/SERVICE_READY -> `PERMIT_PENDING`; IN_CONSTRUCTION cannot persist because the same call suspends it. Also checked the expiry entry points that can materialize the lapse (`routes/permits.py:51,60,76,101`, `cascades.touch_zone` via `routes/zones.py:82,91`, `routes/zones.py:146` ground-break). (c) Adjustment: kept `PERMIT_PENDING` as the stated normal case and added the two exceptions rather than replacing the value outright, so the sentence remains true on every enumerated post-lapse state without over-claiming.

## Step 9: Complete PRD — 2026-09-06T00:03:00.000Z

Step 9 was run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than as a single agent. A single agent cannot hold a 65-endpoint / 3,498-line implementation scan against a 127KB PRD without the scan silently degenerating into a no-op (the tell being a byte-identical output file). Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, and each was handed the prior pass's "already pinned — do not duplicate" list plus its "left to your partition" to-do list so the passes could not thrash the same prose or contradict each other.

Partition: pass 1 = `app/store/errors/envelope/auth/shape/listing/serialize` + `routes/{__init__,clock,campaigns,zones,addresses,accounts}`; pass 2 = `calc/cascades` + `routes/{mdu,permits,poles,preorders}`; pass 3 = `routes/{crews,appointments,claims,fallback,ledger}`.

### Aggregate result
- `PRD_FINALIZED.md` 448 lines / 108,802 chars -> `PRD_COMPLETED.md` 448 lines / **127,245 chars** (**+18,443 chars, +16.9%**). Line count unchanged: every edit was in-paragraph, no new sections.
- **51 edits total: 41 ambiguity-pins, 10 mismatch-revisions.** (pass 1: 19+4; pass 2: 12+3; pass 3: 10+3.)
- 94 changed lines vs `PRD_FINALIZED.md`; file still ends at the real §5 boundary `| ERR_NO_FALLBACK_OPTION_AVAILABLE | 409 |`; not byte-identical to its source.

### Pass 1 (19 ambiguity-pins, 4 mismatch-revisions) — 115,697 chars
- §2.1 revise/mismatch — identity headers also rejected when whitespace-only; role match exact/case-sensitive — auth.py:27-30
- §2.2 insert — `api_request_id` = `req_` + exactly 20 uppercase-alnum chars — envelope.py:20-21
- §2.2 insert — pagination meta only on list endpoints; the two run endpoints answer `array` with no pagination fields and ignore `limit`/`offset` — envelope.py:37-40, campaigns.py:83,165
- §2.3 insert — non-integer `limit`/`offset` -> 400; empty-string param = omitted; `offset` unbounded, past-end yields empty page — envelope.py:62-81
- §2.3 insert — `created_at` ties broken by insertion order, and that rule settles every §3 tie-break chain that runs out of criteria — store.py:140-142
- §2.4 insert — accepted input instant forms (optional seconds/fraction, `T` or space, `Z`/offset/naive-as-UTC), normalized to UTC; bare date rejected — store.py:70-107
- §2.4 revise — clock may move backward and answers 200 with empty `data`; a read of a zone/address materializes its children's lazy expiry with cascades — clock.py:19, zones.py:82,91, addresses.py:68,77, cascades.py:115-126
- §2.7 insert — two decimals govern the value, not the JSON spelling: `10.00` renders as `10.0`, `0.60` as `0.6` — calc.py:86-90
- §2.10 step 4 revise/mismatch — added `POST /service-addresses/{id}/fallback-offers` (`account_id`) to the body-reference list; blank/non-string body FKs fall through to step 7 as 400 — addresses.py:184-185, listing.py:34-41
- §2.10 step 7 insert — numbers accepted as JSON number or string form, booleans never numeric, fractional rejected for ints, percent quantized half-up before range check; absent/unparseable body = `{}`, non-object body rejected — shape.py:17-24,77-144
- §2.11 insert — empty filter ignored; bad enum filter -> 400; unknown FK filter -> 404 and it outranks a bad `limit`; all filters exact and case-sensitive — listing.py:21-31
- §3.1 insert — account email uniqueness exact/case-sensitive, duplicate -> `ERR_INVALID_REQUEST` — accounts.py:36-38
- §3.1 insert — `zone_code` collision within a campaign -> `ERR_INVALID_REQUEST`; reuse across campaigns legal — zones.py:50-52
- §3.2 insert — `street_address` collision in zone -> `ERR_INVALID_REQUEST` — addresses.py:41-43
- §3.2 insert — missing `not_serviceable_reason` -> `ERR_INVALID_REQUEST` at shape time; only `UNDETERMINED`/`SERVICEABLE` admit a manual `NOT_SERVICEABLE`, so `CONDITIONAL_MDU` cannot be ruled out by hand — addresses.py:97-127
- §3.2 insert — `exception_reason` sent with `GRANT`/`DENY` is shape-checked then ignored — addresses.py:144,156-174
- §3.2 insert — offer `expires_at` at or before the clock -> `ERR_INVALID_REQUEST`; multiple concurrent `OFFERED` offers per address allowed — addresses.py:186-188,200-214
- §3.4 revise/**mismatch** — eligibility is `prereg_deadline_at` **strictly earlier** than the clock (was "at or before", contradicting §2.10 step 17); response is evaluated zones in `created_at` order with no pagination block — campaigns.py:75,83
- §3.5 insert — sequencing run is repeatable (rescore, rewrite `build_sequence_index`, bump `version` each time; only `NOT_STARTED` advances to `SEQUENCED`); no qualified zone -> 200 with empty array — campaigns.py:146-165
- §3.6 insert — writing `make_ready_share_cents` bumps each recipient preorder's `version`/`updated_at` — zones.py:175-177
- §3.6 insert/mismatch — an operator may name any of the three `suspension_reason` values, not just `MANUAL`; a reason sent with `RESUME` is ignored — zones.py:202,209
- §4 preamble insert — trailing slash insignificant — app.py:19
- §5 preamble insert — unknown path/method answer `ERR_INVALID_REQUEST` at 404/405 rather than 400 — app.py:26-41

No change needed for: the §5 status table (errors.py matches all 54 ids exactly), the 13-versioned-entity / ledger-exception rule, `zone_count` semantics, address-creation bumping the zone while zone-creation does not bump the campaign, and the §2.10 step-5 ownership list (impl applies no owner check to `GET /accounts/{id}`).

### Pass 2 (12 ambiguity-pins, 3 mismatch-revisions) — 122,429 chars
- §2.4 insert — list reads sweep expiry over the whole collection *before* filters and paging, so `?status=SENT`/`?status=EXPIRED` and `total_count` see post-expiry values; materialization reaches no further than the two named hops (a zone read does not expire its addresses' agreements; a preorder read expires nothing), with the concrete `prereg_rate_pct` lag spelled out — cascades.py:115-126, mdu.py:62-67, permits.py:55-60, preorders.py:100-120
- §2.8 insert — the five `memo` strings are fixed per `entry_type` and pinned verbatim — cascades.py:133-139, claims.py:151-157
- §3.2 insert — agreement `expires_at` need not lie ahead of the clock (an already-past instant opens a dead negotiation); owner account may be of any `account_type`; opening bumps neither address nor zone; multiple agreements per address are legal — mdu.py:28-50
- §3.2 insert — clock at/past `expires_at` is `ERR_MDU_AGREEMENT_STATE_INVALID`, and that is the *only* way expiry bites a `DRAFT` row since lazy expiry touches only `SENT`/`COUNTERED`, so `DRAFT` never becomes `EXPIRED`; a re-offer leaves `countered_fee_cents` standing — mdu.py:85-96, cascades.py:81-89
- §3.2 insert — `countered_fee_cents` omitted from a `COUNTER` is `ERR_INVALID_REQUEST`; sent with `SIGN`/`DECLINE` it is shape-checked then ignored — mdu.py:107-109
- §3.2 revise/**mismatch** — the three-hop sign cascade is conditioned on the address standing in `CONDITIONAL_MDU`; otherwise only the agreement row moves and the zone's `version` is *not* incremented (PRD had stated it unconditionally) — cascades.py:47-58
- §3.2 revise/**mismatch** — same conditioning for decline/expire, plus the other-`SIGNED`-agreement early return leaves the zone's `version` alone — cascades.py:61-73
- §3.3 revise/**mismatch** — `unit_designator` is optional and *uncoupled* from dwelling type (PRD read as a constraint); a negative `tendered_deposit_cents` is `ERR_INVALID_REQUEST` at step 7, not `ERR_DEPOSIT_AMOUNT_MISMATCH`; `expected_build_zone_version` has no declared range — preorders.py:40-42,69-73
- §3.3 insert — conversion moves the same figures but is the one such write that does not bump the zone's `version` — preorders.py:147-180
- §3.3 insert — cancellation is gated on lifecycle state alone, not on the prereg window or either zone dimension — preorders.py:123-144
- §3.5 insert — neither outside-party track is gated on the zone's own two state dimensions at any step — permits.py:20-117, poles.py:24-135
- §3.5 insert — `permit_type` need not be in `required_permit_types`, duplicates allowed, unrequired types never contribute to posture, the ground-break gate, or the permit factor — permits.py:26, calc.py:213-219
- §3.5 insert — a `rejection_reason` sent with `APPROVE` is shape-checked then discarded — permits.py:98,112
- §3.5 insert — opening a pole request and filing its survey leave the zone's `version`/`updated_at` untouched; the counter moves only on decision and attachment; a surveyed quote is not yet in `make_ready_cost_cents` — poles.py:24-82, calc.py:193-198
- §3.5 insert — wrong role for a pole-decision branch is `ERR_FORBIDDEN_ROLE`, settled right after the `decision` enum is recognized and *before* the missing-`denial_reason` step-7 complaint and step-10 state check — poles.py:90-97
- §3.6 insert — exactly one `version` increment per *distinct* crew however many of its appointments one cascade cancelled — cascades.py:12-26

### Pass 3 (10 ambiguity-pins, 3 mismatch-revisions) — 127,245 chars
- §3.8 insert — booking consults no field of the preorder beyond its zone and address: `preorder_status` is not a precondition, and `appointment_type` need not agree with the `drop_method` frozen at conversion — appointments.py:45,74,97
- §4 (`POST /install-appointments`) revise/**mismatch** — description said "for a converted preorder", which no impl check enforces; now "for a preorder whose zone is actively under construction, whatever lifecycle state that preorder itself is in" — appointments.py:41-99
- §3.8 insert — the simultaneous-bury gate is consulted only when the new appointment is itself `DROP_BURY` — appointments.py:94-95
- §2.10 step 22 revise — same fact at the ladder step, which read as universal over `POST /install-appointments` — appointments.py:94
- §3.8 insert — both optional outcome fields are shape-checked on every outcome but applied only on their own branch (`restoration_required` defaults false, `COMPLETED` only; `cancellation_reason`, `CANCELLED` only), and an outcome rewrites only the appointment, the crew and (restoration branch) the parent — never the preorder, address or ledger, and never bumps the zone — appointments.py:203-233
- §3.8 insert — the campaign supplying `restoration_sla_days` is reached appointment -> preorder -> `build_zone_id` -> `campaign_id`, not through the address — appointments.py:36-38,219-221
- §3.8 revise/**mismatch** — PRD implied an operator may only name `SUBSCRIBER_REQUEST`/`CREW_UNAVAILABLE`; impl accepts all three including `ZONE_SUSPENDED`, and the field is optional (null when omitted) — appointments.py:205-207,222-223
- §3.9 insert — filing exactly at the deadline instant is still inside the window; the campaign supplying `claim_filing_window_days` and `late_filing_factor` is the one reached appointment -> preorder -> zone -> campaign, never via the claimed `service_address_id` — claims.py:19-24,60-62
- §3.9 insert — `assessed_by_user_id` is overwritten each round, and the assessment endpoint consults no request body at all (not even the "must be a JSON object" rule) — claims.py:110-126
- §3.9 insert — a `denial_reason` sent with `APPROVE` is shape-checked (1-240 chars) then ignored; the paid claim's `denial_reason` stays null — claims.py:140-157
- §3.9 insert — an appeal retains `decided_by_user_id`, reads no body, always re-prices to the identical amount/variant (`filed_at` frozen, factor and `restoration_due_by` immutable), and segregation of duties on the next decision is measured against the *current* `assessed_by_user_id` — claims.py:124,133,165-178
- §3.2 insert — `max_serviceable_distance_m` is required and zero or more — fallback.py:32
- §3.2 insert/revise — offer `ACCEPT` bumps the address's `version` and overwrites `active_fallback_technology` unconditionally; `DECLINE` writes only the offer row and leaves the address, its version and its active technology alone — fallback.py:101-108

### Pass 3 closing consistency read (the last chance to catch a pass-1/2 sentence that mis-describes pass 3's files)
Re-checked: §2.1 SoD wording (matches claims.py:133 including the `is not None` guard, so an unassessed claim falls through to the state error); §2.3 insertion-order tie-break (matches `ordered()` and `select_fallback_option`'s `_seq` tail); §2.4 lazy offer expiry incl. list sweep before filters/paging (fallback.py:63-86) and its "no further than two hops" clause; §2.7 `late_filing_factor` JSON spelling; §2.8's five memos / positive `CLAIM_PAYOUT` / null `preorder_id` on payouts (claims.py:151-157); §2.10 step 4 body-FK list, step 5 ownership list (correctly excludes all read endpoints — impl applies `auth.own` on no GET anywhere), step 7 ranges for `travel_buffer_minutes`/`daily_capacity_minutes`/`claimed_amount_cents`; §2.11 filter lists for crews, appointments, claims, options, offers and ledger; §3.6's one-bump-per-distinct-crew suspension cascade. **No pass-1/2 sentence needed correcting.** One cosmetic item left alone deliberately: §2.10 step 4's endpoint list includes `POST /install-crews`, which carries no body foreign key at all — pre-existing in `PRD_FINALIZED.md`, vacuous rather than contradictory, so removing it would have been a non-behavioral edit.

### Orchestrator final verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran) — 94 changed lines, +18,443 chars.
- Ends at the real §5 boundary; 448 lines, so nothing was truncated and no section was dropped.
- All 8 `results.$i.json` re-checked after Steps 8-9: still `passed == total` on every round (Steps 8 and 9 only touch PRD prose, never `implementation/`, so the green sweep from Step 7 remains the valid evidence).
- Exactly one `worklog.md`, at the task root — no stray copies under `workspace/` from cwd drift. `.scratch/` is empty: every pass removed only its own `step9pN` subdir and none wiped the shared parent.

**Pipeline complete through Step 9.**
