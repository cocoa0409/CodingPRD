# Worklog — task_3285_automation_task_metering_partner_integration_review_error

Scenario: Automation Task Metering, Partner Integration Review & Error Replay (Zapier): workflow construction with triggers, actions, filters and multi-step paths across connected applications, task metering where each successful action consumes a task from a plan allowance with overage behavior, polling versus webhook trigger differences affecting latency and task consumption, error handling with automatic retries, held tasks and manual replay after a downstream service recovers, partner-built integrations reviewed for authentication method, endpoint coverage and error semantics before public listing, account connection management with token refresh and reauthorization prompts, team and company plans with shared connections, folder permissions and usage visibility, version migration when a partner updates an integration

## Step 1: Create task directory — 2026-10-01T00:00:00.000Z

Task directory was pre-allocated by the caller; verified `./tasks/task_3285_automation_task_metering_partner_integration_review_error/` and its empty `workspace/` subdirectory exist. No new task_* directory was created and no index was computed.

## Step 2: Generate scaffold — 2026-10-01T00:31:00.000Z

All three artifacts are complete and lint-clean. Summary:

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3285_automation_task_metering_partner_integration_review_error/SCAFFOLD.yaml` | 2114 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2127 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 2075 |

`scaffold_lint.py` verdict (verbatim tail): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (68 endpoints, 16 entities, 18 §1.8 instances, 26 §1.9 instances, 585 calls scanned). No forbidden concurrency vocabulary present; scenario text is verbatim (line-wrapped only, whitespace-normalized identical).

## Design

**Complexity profile:** primary archetype Pricing engine blended with Quota/allocation; layers = dual-variant calc, rate/threshold triggers, optimistic concurrency, scheduled/deferred actions, cascading side effects; `flat` topology, `parallel` state-machine shape, `peer_roles`, `immediate` consistency.

**Entity model (16):** TeamAccount (metering counters, dual overage fields), Member, Folder, FolderGrant, Workflow, WorkflowAction, WorkflowRun, Integration, IntegrationVersion, IntegrationEndpoint, Connection, WorkflowVersion, plus join/event/log entities FolderFolderGrant, JobEvent, RefundGrant, LapseIncident. All FKs use the canonical `FK -> Entity.id` prefix; every FK has a reverse-reachability GET (sub-resource or filtered-list form). `api_prefix: /zapier`.

**State machines (5):** Workflow DRAFT→ACTIVE with three forked PAUSED reasons and a cyclic ACTIVE↔PAUSED loop; WorkflowAction PENDING/RUNNING/SUCCEEDED/FAILED/HELD/SKIPPED with cyclic HELD→RUNNING and FAILED→PENDING edges; Integration DRAFT→SUBMITTED→IN_REVIEW→LISTED/REJECTED with a LISTED→SUBMITTED version-bump cycle and a REJECTED resubmit block; WorkflowVersion CURRENT↔MIGRATION_REQUIRED→MIGRATED/BROKEN; Connection CONNECTED↔TOKEN_EXPIRED↔REAUTH_REQUIRED→DISCONNECTED with a 5-refresh lifetime cap.

**Endpoints (68), errors (32), validations (28), roles (4: Member entity_backed, PartnerAdmin/Reviewer/PlatformAdmin opaque), concurrency rules (2 OCC on TeamAccount.version and Workflow.version).**

**Difficulty design:** 9 rule_ids × 2 instances = 18, all setup chains lint-clean with full `${var}` placeholder closure. Highlights: nested-ceiling charge math (`ceil(4*2)*ceil(1/3)` = 8 tasks, overage base 1100¢ vs maximum 2500¢), depth-3 cascades, safety-vs-fiscal and referential-vs-constraint priority conflicts, a 0.80 coverage boundary, mixed exact-slot vs aggregate-capacity overlap semantics, and two compensating invariants (task-count refund drift, epoch-step occupation release).

**Corner design:** 26 active instances across all 9 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model) plus 5 `excluded_because:` stubs citing §1.8 instances, all citations resolving.

Note: 68 endpoints exceeds the 40-endpoint threshold from prior experience with this pipeline — Step 6 impl-gen should be watched closely and its files verified on disk.

## Step 3: Copy shared files — 2026-10-01T00:32:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T00:28:00.000Z

PRD generated and verified. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3285_automation_task_metering_partner_integration_review_error/workspace/PRD.md` — 386 lines, 74,774 bytes.

**Sections written**

- **§1 Introduction** — 3 paragraphs, angle chosen from the metering-vs-failure tension (three audiences: team user, publishing partner, platform operator).
- **§2 Global Specifications** — domain-derived subsection set (§2.1 RBAC; §2.2 verbatim response envelope; §2.3 Pagination; §2.4 Account Metering Ledger and Epoch Rotation; §2.5 The Two Faces of Overage; §2.6 Trigger Factors, Latency Bands, and the Cost of a Task; §2.7 Retry Envelopes and the Compensation Register; §2.8 Optimistic Concurrency Control; §2.9 Integration Review Gate; §2.10 Common Resource Properties; §2.11 Precision and Rounding; §2.12 Nested Retrieval and Left-to-Right Path Validation; §2.13 Validation Order and Error Precedence).
- **§3 Business Logic** — 9 subsections grouped by entity lifecycle interleaved with cross-cutting concerns (workspace construction; activation/pause/disable; run dispatch and the allowance ceiling; attempts/envelopes/ledger wiring; holding-failing-replaying; connections/token lapse/reauthorization; partner integration review; version migration; platform clock and injection surfaces).
- **§4 Endpoint Definitions** — 68-row, 4-column table.
- **§5 Error Code Catalogue** — 32-row, 2-column table.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 67 required, 67 present, 0 missing
- endpoints[].request_body: 43 required, 43 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 28 checked, 28 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 27 checked, 27 fully expressed (all 24 distinct from→to pairs rendered as backticked state-transition tokens in §3; the 3 repeats are be covered by their pair), 0 missing
- calculations[]: 7 checked, 7 fully expressed (metering_factor, trigger_latency_multiplier, charge_task, retry_envelope, overage_amount, review_gate, endpoint_coverage), 0 missing
- validations[] conditions: 28 checked, 27 matchable to error_id in prose, 1 partial — see note
- endpoints[].side_effects / applies_to: 63 side-effect entries across 68 endpoints checked, expressed in §3/§2 narrative, 0 missing
- entities[].fields[] structured content: 67 checked, 67 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (4 Workflow transition branches out of ACTIVE/PAUSED, 2 Integration decision siblings, 2 WorkflowVersion MIGRATION_REQUIRED siblings, 2 Connection TOKEN_EXPIRED siblings, the 4 overage/coverage/metering variant pairs), equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 348
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold rules that were hard to express in prose** (recorded for the worklog):

1. **`validations[].applies_to` is expressed as endpoint paths in the scaffold, but Contract 3 forbids paths in §3.** The existence-rule scopes (§2.12) were transcribable because §2 is unconstrained, but the state/business rules whose `applies_to` lists name 3–4 endpoints each had to be paraphrased by capability ("token refresh, reauthorization and disconnection") rather than enumerated by path. The exact endpoint-per-error mapping is only recoverable by joining §2.13 + §3 narrative to the §4 table, not by reading a single list.
2. **Validation `priority` numbering is a flat 1–28 list mixing auth, existence, state, and business categories, but the skill forbids dumping the ordinal list.** I rendered it as ordered *categories* (§2.13) plus per-operation ordering sentences. A reader gets the precedence but not the literal 1–28 ordinals; if the hidden suite asserts a specific priority tie-break *within* a category that the category ordering doesn't disambiguate, that is the one place a fair implementer could diverge.
3. **One validation (`, category: business_temporal`, the `ERR_DUPLICATE_EPOCH_STEP` entry) has a `check` that conflates two unrelated conditions** — it names both the `expected_account_version` OCC equality *and* the one-OPENING/one-CLOSING epoch-step occupancy. It is stated in §2.8 (OCC) and §3.6 (epoch steps) separately, and the error's 4-endpoint `applies_to` set is split across §2.7/§3.5 narrative; the single-entry coupling is not preservable as one sentence.
4. **`calculations[].calculations` mix two precision conventions in one table** — `retry_envelope` is specified "integer, floor division" while `trigger_latency_multiplier` is "number; 1 decimal place, exact halves", and §2.11 had to state both without letting the round-half-up rule leak into the floor-division one.
5. **`state_machines[].transitions[].trigger` fields encode HTTP methods and paths that cannot appear in §3.** All 27 triggers were converted to state-pair framing (e.g. `` `DRAFT → ACTIVE` ``) or role+verb framing; the mapping from transition to §4 row is thus only implicit.
6. **`locked_upgrade_code` and `grant_id` are field names that belong to a workflow (`OPS_RUN` upgrade lock) and to the `FolderFolderGrant` join with no endpoint that writes them.** They have no natural action narrative, so they were given standalone sentences in §2.4 and §3.9 respectively rather than being implied by a workflow.

**No files outside the output path were written**; the scratch directory `/tmp/prd3285/` holds the four source fragments used to assemble the document and can be ignored. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task was read.

## Step 5: Generate unit tests — 2026-10-01T00:58:00.000Z

Done. Test infrastructure and suite generated for `task_3285_automation_task_metering_partner_integration_review_error`.

## Files written

**`test_helpers/`** (Stage 1)
- `types.py` — 16 entity TypedDicts + status/role enums; `common_fields: false` entities (`FolderFolderGrant`, `JobEvent`, `RefundGrant`) correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per endpoint (all 68 paths under `/zapier`)
- `api_errors.py` — 32 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters + `assert_append_only` + `assert_account_metering_invariants`
- `factories.py` — payload factories for every input entity
- `constants.py` — metering/latency/retry/coverage/step thresholds
- `test_users.py` — `TEST_USERS` shared constants + mandatory `make_member_headers(user_id)` builder (Member is the only `entity_backed` role)
- `fixtures.py` — composite setup tiers, the canonical `setup_basic_scenario`
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2): `conftest.py` + 8 files, `test_01_metering_and_overage` … `test_08_rbac_and_entities`

## Totals

**71 tests.** Every test passes the last-line Design-tag check, has a verbatim PRD citation (verified programmatically against `PRD.md`), no `skip`/`skipif`/`xfail`, no "scaffold" references in generated code, and every `api_client.*` method and `test_helpers` export resolves.

Orchestrator spot-check on disk: 71 `def test_` functions (10/13/11/7/5/7/11/7 per file), 71 unique Design tags = 18 unique Difficulty tags + 26 unique Corner tags, zero skip/xfail matches, `workspace/implementation/` absent at Step 5 exit (Step 6 isolation physically guaranteed).

## Per-queue breakdown

**Queue A — §1.8 difficulty: 18/18 instances translated, 0 skipped** (44 tagged tests, every instance covered ≥2).

**Queue B — §1.9 corner: 26/26 non-stub instances translated, 0 skipped** (each ≥1 test). The 4 `excluded_because:` stubs were verified (each `difficulty_instance` pointer resolves) and correctly not translated: `ex_submit_coverage_gate_boundary`→`bp_review_coverage_gate_exactly_point_eight`, `ex_token_expired_precedence_over_allowance`→`pp_token_expired_beats_allowance_exhausted`, `ex_workflow_pause_resume_cycle_edges`→`nl_workflow_pause_resume_cycle_with_forked_pause_reasons`, `ex_overage_variant_divergence_at_read`→`dv_overage_base_vs_maximum_variant`.

## Borderline instances (recorded verbatim for the worklog)

1. **Source-YAML arithmetic error, corrected.** `Corner/endpoints/ep_usage_report_matches_account_counters` asserts `overage_amount_cents == 550`, but its stated formula `100*(8-3) + 50*8` evaluates to **900**. I followed the PRD's own worked example (§3.5: "overage_amount_cents grows by the CLOSING rate applied to those 4 tasks plus the 50-cent surcharge") and the rule-bearing quote, asserting **900**. The YAML literal was internally inconsistent with its own comment; the PRD is unambiguous.

2. **`Corner/calculations/cal_retry_envelope_floors_at_one_attempt` — partially represented.** The PRD states the retry-envelope formula (§2.7) and the FAILED-vs-HELD outcome (§3.4), but it nowhere states *which* condition selects HELD over FAILED, and the scaffold's own `RUNNING → FAILED` precondition is self-contradictory (`max(1, 5-int(cents/100)) <= 0` with `cents >= 100` is impossible). The YAML's pre-computed "FAILED at max_retries=1, opening rate 9 USD" is not derivable from the PRD. I therefore omitted the envelope-arithmetic and the FAILED/HELD branch assertions, and kept only the PRD-uniquely-derived part (a poisoned attempt leaves the action non-successful: `RUNNING → FAILED` per the §3.4 quote).

3. **Rates in that instance.** The instance's `opening_cost_per_task_cents: 9` is also mistranscribed in its prose ("opening cost 9 USD" with `task_allowance 200`) — left as-is in the setup since no assertion depends on it.

4. **Skipped by the PRD-first filter (gaps, not weakened tests):** none of the 44 non-stub instances failed both-condition filtering outright; the only coverage shortfall is the envelope-branch outcome in #2 above. Notable near-silences that survive: the auto-pause / `AUTO_SOFT_CAP` cascade is uniquely derivable from the §3.3 prose (not the scaffold table); the "replay restores `tasks_used_current` to 0" invariant (Difficulty `ci_replay_refund_restores_account_task_count`) is asserted on the account counters only, because the PRD never states that the *current-epoch* counter (rather than `tasks_used_previous`) is the field lowered — the assertion is the instance's own named quantity and the §3.5 worked sequence ("the tasks already consumed by that run slide into `tasks_used_previous`") makes the zero-drift outcome the only PRD-consistent reading.

## Step 6: Generate implementation — 2026-10-01T01:25:00.000Z

All clean. Final state verified.

## Summary

Built a complete Python + Flask implementation for `task_3285_automation_task_metering_partner_integration_review_error`, implementing from INSTRUCTION.md, SCAFFOLD.yaml and PRD.md only (no test_suite/test_helpers/design YAML reads, no test runs).

**Files written under `workspace/implementation/` (line counts):**

| File | Lines |
|---|---|
| `start.sh` | 9 |
| `requirements.txt` | 1 |
| `app.py` | 50 |
| `calc.py` | 152 |
| `clock.py` | 62 |
| `common.py` | 108 |
| `db.py` | 42 |
| `errors.py` | 79 |
| `middleware.py` | 48 |
| `models.py` | 262 |
| `response.py` | 75 |
| `routes/__init__.py` | 11 |
| `routes/accounts.py` | 159 |
| `routes/actions.py` | 187 |
| `routes/connections.py` | 114 |
| `routes/folders.py` | 121 |
| `routes/integrations.py` | 137 |
| `routes/versions.py` | 93 |
| `routes/workflows.py` | 179 |
| `services/__init__.py` | 8 |
| `services/connection_service.py` | 87 |
| `services/integration_service.py` | 177 |
| `services/run_service.py` | 253 |
| `services/workflow_service.py` | 70 |

Total 2,483 lines; no zero-byte files; `__pycache__` cleaned.

**Endpoints:** 68 `/zapier` method+path pairs registered, matching the scaffold §1.5 table exactly.

**Boot:** confirmed — `bash start.sh` returns HTTP 200 within ~3 s on a fresh port, store starts empty (`total_count=0`), no seeding anywhere. Verified live: metering (POLLING = 8 tasks/action; 12 runs → 96 tasks, 13th → 104 with `overage_tasks_used=4`, base 5600 vs projected 5800 when rates differ), `AUTO_SOFT_CAP` auto-pause + action SKIPPED, token lapse → HELD → unconsumed REFUND → `ERR_REPLAY_DEFERRED` → recover → replay flips grant to REPLAY; refresh cap 5 → REAUTH_REQUIRED → snapshot demotion; review gate order (auth_method → coverage → endpoint completeness) and 7/8 = 0.88 pass; OCC 412; epoch-step duplication; OPS_RUN rotation; left-to-right 404s; response envelope and pagination.

**Ambiguities (one line each):**
- `filter_expression` evaluation is unspecified (no expression language is given); implemented as "filters are only evaluated on POLLING workflows; non-polling triggers treat the guard as true", overridable per-action — a literal implementation of "the free path opens on the polling evaluation surface" may need adjustment if tests assume all filters evaluate.
- Replay of a `FAILED` action additionally requires charged cost ≤ 99 cents per §1.2, which the run path can never produce (its min charge is 100 at envelope-1); reaching that state requires the `_simulate/action-charge` surface.
- `MIGRATION_REQUIRED → BROKEN` (after 3 attempts) is implemented as 3 attempts onto a target with `schema_coverage < 0.8`; no endpoint exposes a migration attempt counter.
- `ERR_MISSING_ERROR_SEMANTICS` (declared endpoint lacking a response schema) is raised before the coverage shortfall on submit/decision, since an endpoint without a schema is itself a coverage defect.
- No dedicated action-not-found error exists in the catalogue, so `GET /zapier/actions/{unknown}` answers 404 with `ERR_NO_RUNNABLE_ACTION`.

Orchestrator verification on disk: all 24 files present, none zero-byte (`requirements.txt` is 10 bytes, `Flask>=3.0`, no trailing newline — the `wc -l` 0 is a newline artifact, not an empty file); `bash start.sh` on a fresh PORT=38417 booted in <5 s, `GET /` returned the success envelope, `GET /zapier/accounts` correctly returned 401 `ERR_UNAUTHENTICATED`. The 68-endpoint output-cap risk did not materialize — the subagent wrote incrementally as instructed.

## Step 7: Run tests and iterate — 2026-10-01T02:32:00.000Z

All 8 rounds pass in two consecutive sweeps (71/71). Final state verified on disk: no `results.*.json` left behind, `__pycache__` removed, storage confirmed in-memory-only with no seeding and no test-file coupling.

## Summary

**Iterations run.** 6 eight-round parallel sweeps: one diagnostic (15 failures) and five fix/re-verify rounds (15 → 7 → 7 → 1 → 0), ending with two consecutive clean sweeps at 71/71.

**Tests deleted.** None. Every failing test traced to a rule verbatim in PRD, so the deletion criterion never fired.

**Fixes applied to `test_helpers/`.** None. The fixtures, factories, and role-header builders were PRD-faithful throughout — every setup error traced to a *test function's own* inline scenario construction, not to a shared helper.

**Fixes applied to `test_suite/`** (each made the test more PRD-faithful, never weaker):
- `test_03_connections_and_epoch_steps.py` — the two epoch-step tests ended by refreshing a connection they had just **disconnected**, but PRD §3.6 makes `DISCONNECTED` terminal (`CONNECTED → DISCONNECTED`, "after which the connection stays DISCONNECTED"), so the setup could never succeed. Re-seeded the next epoch on a fresh connection of the same account; the released OPENING slot being account-level is what the test actually pins. Also re-pointed the envelope test at `forced_failure` rather than `charge="hold"`, so it exercises PRD §3.4's fail path rather than §3.5's recovery path.
- `test_05_integration_review.py` — the submit-at-0.80 test claimed "enters review", but PRD §2.9 also forbids submitting with any schema-less endpoint, so 4-of-5 coverage is unreachable for `IN_REVIEW`. De-stubbed it into a real boundary pair: at 0.80 the coverage gate does **not** fire (endpoint-completeness error instead), at 0.67 it does. The review-after-drop test now submits a fully-covered integration first, so its coverage drop is the rule actually under test.
- `test_06_cascades_and_migration.py` — the migration test created its snapshot *before* the schema-less endpoint, so its pinned revision was 1.0 and nothing ever demoted it. Re-seeded a 4-of-5 snapshot so the published 0.80 revision genuinely triggers `CURRENT → MIGRATION_REQUIRED` while still clearing the 0.8 migration bar.

**Fixes applied to `implementation/`:**
- `calc.py` — `charge_task` now adds the retry surcharge to `overage_amount_cents` only when the charge actually lands beyond the allowance (PRD §2.5). It was billing the surcharge on in-allowance charges, which the §3.5 worked example counts as $0.
- `services/run_service.py` — split the two envelope-exhaustion paths that PRD §3.3/§3.4/§3.5 describes: a hold request (`charge="hold"`) or a failed credential leaves the action `HELD` and mints the REFUND grant, while `forced_failure` on a live credential is the §3.4 `RUNNING → FAILED` path. Added `_reverse_charge`, so a HELD replay actually gives the charged whole tasks back (PRD §3.5 "neither lose the work nor pay for it"; §2.7 "the run whose task charge it reverses").
- `routes/connections.py` — `_lapse/tokens/expire` only rejects a `DISCONNECTED` connection; re-asserting a lapse on an already-expired credential is a no-op, matching the §3.9 injection surface.
- `services/integration_service.py` — submit and review-decision now consult the gate in PRD §2.9's order (auth_method → coverage) and check endpoint completeness **after**, so a submission at adequate coverage reports its coverage status instead of a completeness error; `_snapshot_for_target` now selects the workflow snapshot deterministically.
- `services/workflow_service.py` — resume blocked by a lapsed credential reports `ERR_CONNECTION_INVALID_STATE` rather than a generic workflow-state error, matching PRD §3.2's "back to `CONNECTED`" condition.
- `common.py` / `routes/workflows.py` — attaching an action is filed under the workflow's folder, so folder reachability (PRD §2.1/§2.13, a referential check) is now evaluated ahead of the position-uniqueness constraint.

**Key finding.** The single largest failure cluster (7 of the original 15) came from one implementation misreading: I had merged PRD §3.4's "charged cost ≥ 100 cents → FAILED" with §3.5's hold path. Because the retry surcharge is 50 cents *per whole task*, an 8-task polled charge is 400 cents of surcharge, so a dispatcher explicitly asking for `charge="hold"` was being failed instead of held — and the compensation register was never written. Splitting the two triggers on the request's own disposition is what PRD §3.3's three-way `charge` input describes.

Orchestrator verification (this is a Step-7-with-fixes, so the hand-back was spot-checked against disk rather than trusted):
- Test count still 71 after the loop — confirms "no tests deleted".
- `test_helpers/*.py` mtimes all 18:25–18:32 (Step 5 timestamps) — confirms "no test_helpers fixes". `test_suite/` mtimes show exactly three files rewritten post-Step-6 (test_03 20:02, test_05 19:52, test_06 19:51) — matches the three reported test_suite fixes, no more.
- I re-ran the 8-round sweep myself: **8/8 rounds passed=71 total=71 failed=0**. Last implementation write was 20:02:16, before my sweep, so no post-sweep write invalidated it. `results.{1..8}.json` are present in `workspace/implementation/` as the final evidence artifacts.

## Step 8: Finalize PRD — 2026-10-01T02:52:00.000Z

PRD_FINALIZED.md is complete. All 8 edits are in place and consistent with the full implementation, not just the Step 7 sites.

## Summary

- **PRD.md**: 386 lines. **PRD_FINALIZED.md**: 388 lines. Delta: **+2 lines (+0.52%)**.
- No sections added; every change is an inline insert or revise on an existing paragraph.

### Changes (one per bullet)

- **§2.5** — insert — base `overage_amount_cents` grows only when a charge actually lands beyond `task_allowance` (retry surcharge on in-allowance charges does not enter it), and hold-replay reverse-bills: whole tasks off `tasks_used_current`, beyond-allowance tasks off `overage_tasks_used`, and the full charged amount off the base figure when ≥1 beyond-allowance task is released — `implementation/calc.py:79-80`, `implementation/services/run_service.py:273-296`
- **§2.9** — revise — `ERR_MISSING_ERROR_SEMANTICS` endpoint-completeness is evaluated only after the auth-method and coverage checks, for both submit and review-decision — `implementation/services/integration_service.py:21-26,40-45`
- **§3.1** — insert — attaching an action re-checks folder reachability (referential), and this precedes the position-uniqueness constraint, so a foreign-folder duplicate-position attach reports `ERR_FOLDER_NOT_PERMITTED` — `implementation/common.py:86-93`, `implementation/routes/workflows.py:64-83`
- **§3.2** — insert — resume blocked by a still-lapsed credential reports `ERR_CONNECTION_INVALID_STATE`; the allowance-guard block stays `ERR_WORKFLOW_INVALID_STATE` — `implementation/services/workflow_service.py:52-63`
- **§3.4** — revise — a `charge="hold"` request (or a non-`CONNECTED` credential) routes an exhausted action to the §3.5 recovery path regardless of charged cost; only a live-credential, non-hold exhaustion at ≥100 cents fails permanently — `implementation/services/run_service.py:56-87,148-153,175-177`, `implementation/routes/actions.py:122-133,156-163`
- **§3.5** — insert — spending the refund grant in the worked sequence also reverses the settled charge, so the account ends back at the tasks the hold had not already returned — `implementation/services/run_service.py:267,273-296`
- **§3.6** — revise — re-asserting a token lapse is a no-op once the connection is `TOKEN_EXPIRED` (only `DISCONNECTED` is refused) — `implementation/routes/connections.py:84-85`
- **§3.8** — insert — the migration target snapshot is chosen deterministically: explicit identifier, else the `MIGRATION_REQUIRED` snapshot, else the workflow's oldest — `implementation/services/integration_service.py:172-187`

### Per-edit pre-edit search log

1. **§2.5 base growth + reversal.** Subject: `overage_amount_cents` mutation. Enumerated/read: `calc.py:54-83` (`charge_task`), `calc.py:86-94` (`_refresh_account_derived`), `calc.py:97-112` (`projected_overage`), `run_service.py:273-296` (`_reverse_charge`), `routes/accounts.py:99-100`, `models.py:55-56`. Wording adjustment (c): initially added "so it tracks the account's current state" to the max-figure sentence; removed it after confirming `projected_overage` is invariant under any current-state change that preserves `tasks_used_current`/`tasks_used_previous`/allowance/rates, while `overage_amount_cents` is not — the contrast is now simply "derived from the two epochs' counters rather than accumulated by charging".

2. **§2.9 gate order.** Subject: review-gate evaluation order. Enumerated/read: `calc.py:145-151` (`review_gate`), `integration_service.py:15-57` (submit + review_decision), `routes/integrations.py:44-64`. Wording adjustment (c): first wrote "a submission that declares…"; widened to "a submission **or a review decision**" because `review_decision` calls the same gate on the same path.

3. **§3.1 attach-action folder check.** Subject: create-action validation order. Enumerated/read: `common.py:63-93` (`folder_visible`, both require helpers), `routes/workflows.py:17-88` (create-workflow and create-action), `routes/folders.py:50-66` (grant creation). Wording adjustment (c): none — scoped the sentence to "attaching an action" so it does not over-claim the create-workflow path (where folder reachability is already documented) or the grant path.

4. **§3.2 resume error.** Subject: resume blocking condition. Enumerated/read: `workflow_service.py:45-67` (resume), `routes/workflows.py:132-136`, `run_service.py:27-31` (`USER_PAUSED`/`AUTO_SOFT_CAP` writers), `routes/actions.py:150-153`. Wording adjustment (c): added the allowance-guard branch (`ERR_WORKFLOW_INVALID_STATE`) so the new sentence does not imply every blocked resume reports the connection error.

5. **§3.4 failure vs hold.** Subject: exhausted-attempt disposition. Enumerated/read: `run_service.py:51-87` (`_granted_attempts`, `_exhaust`), `run_service.py:119-178` (dispatch), `routes/actions.py:92-180` (`_spend`). Wording adjustment (c): avoided the phrase "the run's own disposition" (the same flag is already used for the `_disposition` skip/run override) and split the wording into two independent triggers — explicit `charge="hold"` (run and injection) and non-`CONNECTED` credential (injection `_spend`) — plus the live-credential threshold, so all three paths are covered without overstating a shared mechanism.

6. **§3.5 worked example.** Subject: replay compensation. Enumerated/read: `run_service.py:218-296` (`replay_action`, `_reverse_charge`), `routes/accounts.py:75-103` (usage report). Wording adjustment (c): reworded "ends the sequence back at zero" to "back at the tasks the hold had not already returned" so the sentence stays true when the epoch rotated after the hold (as several tests do).

7. **§3.6 token lapse.** Subject: `/zapier/_lapse/tokens/expire`. Enumerated/read: `routes/connections.py:75-98`, `connection_service.py:40-88`, `middleware.py`, and the `force_reauth` fixture (the repeated-lapse flow). Wording adjustment (c): first draft said "already lapsed is a no-op"; broadened to "on a connection that has not yet entered `TOKEN_EXPIRED` performs the transition" because the guard admits any non-`DISCONNECTED` status, so the claim must not name only the `TOKEN_EXPIRED → TOKEN_EXPIRED` case.

8. **§3.8 snapshot selection.** Subject: migrate target lookup. Enumerated/read: `integration_service.py:134-187` (`migrate`, `_snapshot_for_target`), `routes/versions.py:52-58`, `routes/actions.py` (`_latest_run_for`, which uses the same oldest-first pattern). Wording adjustment (c): none — note one item in the diff ("re-seeded a 4-of-5 snapshot…") traces to a *test* fixture change, not to implementation, so no PRD edit was made for it; `implementation/services/integration_service.py:116-118` already sets `schema_issue_count = gaps` per PRD §3.8 verbatim.

### Scope note
A filtered-action path (`run_service.py:34-48`) behaves in a way PRD §3.3 does not pin, but it traces to no Step-7 fix item (no test exercises `filter_expression`), so per the HARD SCOPE and NO-NEW-MISMATCH rules I left §3.3's filter prose verbatim rather than inventing a pin.

Orchestrator verification: `wc -l` gives 386 → 388 lines; `diff` shows 16 changed lines = 8 replaced line-pairs, matching the 8 reported edits exactly (no unreported edits). The §3.3 filter gap is correctly deferred to Step 9, whose full-scan mandate covers it.

## Step 9: Complete PRD — 2026-10-01T03:10:00.000Z

Final verification passed: 388 lines both, +11,993 chars, all headers and tables preserved, 22 in-place edit blocks, no new sections.

## Summary

`workspace/PRD_COMPLETED.md` produced as a minimal in-place patch over `workspace/PRD_FINALIZED.md` (which existed; `PRD.md` was 2 lines shorter and superseded).

**Line/char counts**
- Source `PRD_FINALIZED.md`: 388 lines / 78,035 chars
- `PRD_COMPLETED.md`: 388 lines / 90,028 chars (+11,993 chars, same line count, all 30 headings and 3 tables byte-identical)
- 22 edit blocks; no new sections or paragraphs — every change is an inline sentence insert/revision inside the paragraph that already owned the behavior.

**Counts**
- Ambiguity-pins: 30 distinct behavior-level pins across 19 blocks
- Mismatch-revisions: 4 blocks (behavior the PRD described differently from impl)

**Changes (PRD section — insert/revise — ambiguity/mismatch — what changed — impl ref)**
- §2.4 — insert — ambiguity — `locked_upgrade_code` is never bookable by any defined operation, so it always reads null — `models.py:57`
- §2.4 — insert — ambiguity — OPS_RUN turnover zeroes `overage_tasks_used` (not just `tasks_used_current`), releases both epoch steps, and names the usage-report surface incl. `replay_affected_workflow_ids` — `routes/accounts.py:122-128,95-103`
- §2.5 — insert — ambiguity — `projected_overage` = higher rate × beyond-allowance tasks of both epochs + 50¢ × all tasks of both epochs, counters-derived — `calc.py:97-112`
- §2.6 — insert — ambiguity — third charge factor: attempt class `ceil(attempt_no / max_retries)` — `calc.py:45-50`
- §2.8 — insert — ambiguity — expected version compared as integer equality; non-integer/absent ⇒ stale; single-use after any charge — `calc.py:59`, `integration_service.py:150`
- §2.11 — insert — ambiguity — a 0 rate is honoured as 0, not defaulted to 1 — `models.py:48-49`
- §2.12 — insert — ambiguity — unresolvable folder ⇒ 403 `ERR_FOLDER_NOT_PERMITTED`; connection create resolves `integration_id`/`owner_member_id` eagerly — `common.py:56-60`, `routes/connections.py:20-24`
- §2.13 — revise — **mismatch** — OCC version-first is NOT uniform across both surfaces; migration checks snapshot state before the version compare — `integration_service.py:143-151`
- §3.1 — insert — ambiguity — `trigger_type` outside the three ⇒ 403; `poll_interval_seconds` < 60 / non-int ⇒ 403; folder-account mismatch ⇒ 403 — `routes/workflows.py:27-34,23-24`
- §3.1 — insert — ambiguity — invalid-or-<1 `position` ⇒ 409 `ERR_DUPLICATE_ACTION_POSITION` — `routes/workflows.py:67-72`
- §3.1 — insert — ambiguity — duplicate email in an account ⇒ 409 `ERR_DUPLICATE_GRANT` — `routes/accounts.py:139-141`
- §3.1 — insert — ambiguity — member's serialized field set; no update surface — `models.py:64-73`
- §3.1 — insert — ambiguity — workflow creation validations/ordering — `routes/workflows.py:29-34`
- §3.3 — revise + insert — **mismatch** — dispatch does not "walk to completion": candidate set = resting actions, else first `SUCCEEDED` as head-reprise; `charge` echoed (default `success`); final status derived — `run_service.py:90-104,106-108,182-197`
- §3.3 — insert — **the known open item** — filter is consulted only on POLLING (webhook triggers treat the guard as true), expression text opaque, explicit `_disposition` overrides both ways — `run_service.py:34-48`
- §3.3 — insert — ambiguity — filtered action appends a `SKIPPED` event; it is the sole zero-charge path to `SKIPPED` — `run_service.py:142-146`
- §3.3 — insert — ambiguity — `ERR_WORKFLOW_MAX_STEPS_EXCEEDED` measures the candidate set, not `action_count`; `ERR_NO_RUNNABLE_ACTION` decided first — `run_service.py:101-104`
- §3.3 — insert — ambiguity — auto-pause also appends a `SKIPPED` job event — `run_service.py:160-163`
- §3.3 — revise — **mismatch** — no run-level terminal `SUCCEEDED` event exists; run status is derived from action states at stop — `run_service.py:183-197`
- §3.4 — insert — ambiguity — job-event field set carries only `id`/`created_at` (no version) — `models.py:225-235`
- §3.5 — insert — ambiguity — HELD replay needs a dispatched run for the refund lookup; injection-only charge not settled — `run_service.py:204-208,246-251`, `routes/actions.py:169-171`
- §3.5 — insert — ambiguity — deferral vs terminal replay refusals distinguished — `run_service.py:245,251,270`
- §3.6 — insert — ambiguity — refresh claims the OPENING step before mutating the connection — `connection_service.py:44-48`
- §3.7 — insert — ambiguity — missing `path` ⇒ 403; duplicate path ⇒ 409 `ERR_VERSION_NOT_MONOTONIC` — `routes/integrations.py:72-78`
- §3.7 — insert — ambiguity — decision endpoint moves `SUBMITTED`→`IN_REVIEW` first; `_cycle_rejected` blocks re-submission — `routes/integrations.py:61-62`, `integration_service.py:16`
- §3.8 — insert — ambiguity — snapshot creation resolves all three ids (workflow→version→connection) and does not mutate the workflow — `routes/versions.py:18-25`, `integration_service.py:122-131`
- §3.8 — insert — ambiguity — migrate state checks precede OCC — `integration_service.py:143-151`
- §3.9 — insert — ambiguity — incident counter consumed by recovery / account incidents; recovery returns released action ids — `routes/connections.py:106-119`, `routes/accounts.py:118-121`
- §3.9 — insert — ambiguity — injection disposition mapping, `auth_error` pause, allowance pause + SKIP — `routes/actions.py:98-139`

Treated tests only as cross-reference; every pin above was derived from `implementation/` source, not from test assertions.

Orchestrator verification: PRD_COMPLETED.md present (90,071 bytes), 388 lines like its source, 30 headings / 104 table rows byte-identical to PRD_FINALIZED.md — confirms "no new sections, no table drift". Post-Step-9 write check over `implementation/`, `test_suite/`, `test_helpers/`: the only files newer than the Step 7 sweep are `results.{1..8}.json` themselves (written by that very sweep), so no implementation or test file was touched after the clean 8/8 run — the sweep is still valid evidence.

---

## Pipeline complete

Final state: 68 endpoints, 71 tests, 8/8 stability rounds at 71/71, 0 tests deleted, 0 test_helpers fixes, 3 test_suite faithfulness fixes, 6 implementation fixes across 6 files. PRD evolved PRD.md (386 lines) → PRD_FINALIZED.md (388, +8 Step-7-traced edits) → PRD_COMPLETED.md (388 lines, +11,993 chars, 30 ambiguity-pins + 4 mismatch-revisions from the full impl scan).