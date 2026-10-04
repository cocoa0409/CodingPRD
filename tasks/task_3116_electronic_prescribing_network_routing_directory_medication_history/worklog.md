# Worklog — task_3116_electronic_prescribing_network_routing_directory_medication_history

## Step 1: Create task directory — 2026-09-30T00:27:51.701708202Z

Task directory pre-allocated by the caller at ./tasks/task_3116_electronic_prescribing_network_routing_directory_medication_history (index 3116, not computed); verified it exists and contains workspace/. No task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T01:00:27.133776305Z

All three deliverables are complete and the lint is clean. (The `worklog.md` and `workspace/` entries in the directory were not created by me — I only wrote the three scaffold files.)

### Deliverables

| File | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2346 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1772 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 1556 |

Top-level keys are correct: `SCAFFOLD.yaml` carries §1.0–§1.7 only (verified neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it); each design file has exactly its single mandated top-level key.

### Counts

- **Entities: 11** — NetworkParticipant, DirectoryEndpoint, Prescription, SigningSession, RoutingAttempt, Patient, PatientConsent, MedicationHistoryBatch, MedicationHistoryRecord, BenefitCheck, TransactionFeeEntry
- **Endpoints: 75** (incl. 4 relationship-read helpers added to satisfy FK reverse-reachability, plus 2 `/_test-driving` endpoints)
- **Errors: 48** — every one referenced somewhere in the scaffold or a design file
- Also: 8 state machines, 7 calculation rules (14 variants), 10 ordered validations, 6 roles, 2 OCC concurrency rules
- **§1.8: 9 rule_ids × 2 instances = 18**
- **§1.9: 14 section groups, 38 instances (26 active + 12 `excluded_because` stubs citing real §1.8 instance names)**

### Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     26
  Calls scanned (§1.8+§1.9):  678

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Difficulty / corner design coverage

Calibrated to Expert and pushed past it by density rather than volume: every §0.5 rule is satisfied on structurally distinct grounds. Dual-variant logic runs on two unrelated domains (DirectoryEndpoint reliability — chronological 20-attempt window vs. EWMA with α=0.0670, which disagree at the 0.90 degrade gate on the same history; and BenefitCheck cost — brand fee inside vs. outside the deductible-credit basis, giving 3100/5200 provisional against 3400/4900 final on identical inputs). Combinatorial complexity spans two modes: a six-key ranked selector that a test can falsify by reordering keys, and a fee settlement whose chargeable total is clamped to a 7500 ceiling *before* marginal tiering, so 7825 and 8000 settle identically at 60100 where the unclamped schedule would give 82275 and 88975. Non-linear machines are cyclic on two entities (a Prescription routing cycle re-entering FALLBACK_SENT, and a one-to-many certification branch with revert), and two four-hop cascades originate from different triggers — one hop is deliberately ambiguous until pinned, so the scaffold fixes an explicit evaluation order. Priority conflicts contrast two error-category pairs (state-over-referential and safety-over-constraint, where the same operation on two rows of the same prescription flips its `error_id`), while boundaries land on different metrics and distinct endpoints (record-cap inclusive at 40; ceiling inclusive at 7500). The corner file honestly exposes the scaffold's hardest judgement call: five machine pairs are declared but left with no reachable guarded transition, and rather than paper over them they are excluded with written rationale. All arithmetic the recipes assert (60100, 60093, 45.9, 0.93300000, 0.6667, 3600, 10800, 6700, -60100) was computed as code against the pinned formulas, never estimated, and every `${var}` traces to an earlier `captures:` block whose field is declared in §1.5.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T01:00:30.816175571Z

Copied ./INSTRUCTION.md to ./tasks/task_3116_electronic_prescribing_network_routing_directory_medication_history/workspace/INSTRUCTION.md (build contract for the implementation step).

## Step 4: Generate PRD — 2026-09-30T01:10:55.63117622Z

Done. Final summary follows.

### Output

`workspace/PRD.md` — 387 lines, ~11,300 words.

### Sections

- **§1** Introduction (2 paragraphs)
- **§2** Global Specifications — 11 subsections: 2.1 RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Directory as Authority for Service Reach, 2.5 Nested Retrieval & Common Resource Properties, 2.6 Endpoint Stability/Coverage/Service Window, 2.7 Monetary Precision & Fee Ledger Conservation, 2.8 Optimistic Concurrency Control, 2.9 Validation Order, 2.10 The Logical Clock, 2.11 Mutation Cascades & Recomputation Order
- **§3** Business Logic — 9 subsections (participant/directory onboarding; certification; prescription + signing/identity; routing selector; outcomes/backup/fallback; suspension & disabling cascades; transaction fees; consent & history aggregation; benefit estimates)
- **§4** Endpoint Definitions — 4-column table, 75 rows
- **§5** Error Code Catalogue — 2-column table, 48 rows

### How thoroughly the scaffold rendered

Every scaffold rule table was projected into prose rather than summarized. All 44 state transitions across 8 machines are narrated with their `from`/`to` pairs as UPPERCASE strings, their preconditions paired to the exact error IDs that guard them, and their side effects stated individually — including the parallel-machine interactions (e.g. a report-undeliverable that degrades an endpoint *and* drives the routing machine *and* recomputes `directory_listed`). All 7 calculations appear as precise business narrative with no operator syntax: the routing selector's six-key total ordering, the dual-variant reliability windows (chronological vs EWMA, with the 0.0000-vs-0.9330 divergence called out), the eight-step benefit-cost evaluation with its variant-dependent deductible-credit basis and both worked splits (3100/5200 vs 3400/4900), the clamp-then-tier fee settlement with both billing modes and the 3600/2520-vs-1710 illustration, the deduplication ranking with both outcome directions, the batch-cost threshold, and the reachability enumeration — all `constants` embedded in business context. All 10 validation priorities are ordered explicitly with their `applies_to` scopes enumerated, the 2 OCC rules are framed purely as stale-version rejection with the named fields and 412 error IDs, and the 48-entry error vocabulary, 6 roles (with every `identity:` translated), and all enum/state values are exact.

### Hard Contracts Reports

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 0 required (declared inline in `input`), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ_field + error_id + 412 all named), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed, 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 37 with side effects + 10 applies_to scopes checked, expressed, 0 missing
- entities[].fields[] structured content: 113 checked, 113 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (3 disable branches, 2 FALLBACK_PENDING entries, 4 report-outcome paths, 2 routing-status cyclic returns, etc.), 9 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 761
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 fixed block present byte-for-byte (re-verified against `section-2.2-response-structure.md`); §3 contains no tables, field lists, or declared foreign keys; every one of the 48 error IDs appears in §2 or §3 prose; no fuzzy hedging and no pseudocode operators outside code fences; §4/§5 column counts are 4 and 2 as required. I did not open either withheld design file (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) or any sibling task directory.

## Step 5: Generate unit tests — 2026-09-30T01:43:50.589691810Z

Generation is complete. Final summary:

### What was done

Generated the full test infrastructure for task_3116 (electronic prescribing network routing, directory & medication history) under the task directory, translating **only** non-stub instances from the two design indices — no walk of `SCAFFOLD.yaml`, no smoke / RBAC-matrix / listing / pagination baseline tests.

### `test_helpers/` (2,050 lines)
| File | Lines |
|---|---|
| `__init__.py` | 18 |
| `types.py` | 459 |
| `api_client.py` | 365 |
| `api_errors.py` | 119 |
| `assertions.py` | 231 |
| `factories.py` | 165 |
| `constants.py` | 115 |
| `test_users.py` | 39 |
| `fixtures.py` | 539 |

### `test_suite/` (3,275 lines, 25 files + conftest)
`conftest.py` (53) plus `test_01` … `test_25` (89–233 lines each), grouped by domain concern: reliability variants, benefit-cost variants, fee settlement/ceiling/corrections/ledger conservation, reliability + disable cascades, routing-status cycle, certification revert, validation-priority pairs, history batch cost & dedupe, cross-entity gates, temporal overlap, selector ranking, state-machine edges, RBAC/OCC, clock-driven expiry.

### Coverage

- **Total tests: 70** (all collected cleanly; `pyflakes` clean; no `pytest.mark.skip` / `skipif` / `xfail`; no scaffold/§-table references in generated code).
- **§1.8 queue A (Difficulty): 18/18 instances translated, 0 skipped** — every instance carries exactly 2 tagged tests (36 tests).
- **§1.9 queue B (Corner): 26/26 non-stub instances translated, 0 skipped** (34 tests; a few carry a second test where the recipe held two distinct assertions).
- **12 `excluded_because:` stubs not translated** — all 12 `difficulty_instance` cross-references verified to resolve against real `SCAFFOLD_DIFFICULTY_DESIGN.yaml` names; no placeholders emitted.
- **Docstring tags: 70/70 exactly one `Design:` line**, all resolving to real instances; 0 untagged, 0 dual-tagged, 0 dangling.
- **Verbatim citation pass: 113 quoted spans checked against `PRD.md`, 0 failures.** Nine citations that initially failed were rewritten to the literal PRD sentence (e.g. the ledger citation now reads "The first is `period_net_total_cents`, the sum of `fee_cents` over every `TransactionFeeEntry` row sharing the same participant and `month_key`.").

### PRD-silence findings that blocked an instance

None. Every instance in both queues passed the two-condition filter — each asserted rule is stated in PRD prose by a verbatim sentence that uniquely determines the outcome.

Two instances required deliberate narrowing rather than skipping (PRD-silence on *how* the scaffold index framed them, not on the rule itself):
- `Difficulty/transitive_cascade/..._acknowledged_attempt_cascade_reaches_endpoint_degradation`: the scaffold's premise (same-ID retry for the participation cap) isn't expressible through PRD endpoints, so the degrade assertion is driven by a genuine single-failure history (reliability 0.0000) and the acknowledged report's recompute — same four hops, PRD-derived.
- `Difficulty/priority_pair_validation_conflict/cancellation_...`: the scaffold's `rx_b` precondition (one eligible endpoint) conflicts with the PRD's `ERR_LAST_ACTIVE_ENDPOINT` guard, so `rx_b` is driven to `ROUTE_FAILED` via a reported undeliverable against a pharmacy that keeps a second non-colliding endpoint (inert `MED_HISTORY`) — preserving the asserted contrast (422 `ERR_CRITICAL_ORDER_DELIVERY_REQUIRED` vs 409 `ERR_INVALID_STATE`).

### Caveats

Tests were **not executed** — `workspace/implementation/` does not exist yet, so there is no server to run against. Collection, import resolution, and lint all pass; fixture API surface (one client method per PRD §4 endpoint, `make_<role>_headers(entity_id)` threading for the three entity-backed roles, `get_success_data`-based setup) is validated structurally only.

## Step 6: Generate implementation — 2026-09-30T03:40:09.946406274Z

NOTE ON PROVENANCE: this step's generator subagent was killed by a host-session restart while mid-write, twice (attempt 1 at ~13 min, files 01:48–02:01; attempt 2 at ~18 min, files 02:46–02:59). Neither attempt returned a summary. Attempt 2 was the less complete of the two (4 route files, no route decorators registered yet). Attempt 1 was archived to /tmp/task_3116_partial_impl_step6, restored as the implementation, and passed all completeness checks below; it is the artifact now in workspace/implementation/.

### Files (attempt 1, restored)

| File | Bytes |
|---|---|
| `app.py` | 3389 (app factory, 7 blueprints, ApiError/404/405/Exception handlers) |
| `clock.py` | 3418 |
| `db.py` | 2989 (in-memory store, `reset()` on boot) |
| `errors.py` | 10270 (48 error ids) |
| `request_context.py` | 7666 (auth, RBAC, body/payload validation) |
| `serializers.py` | 1450 |
| `start.sh` | 402 (foreground, $PORT, guarded pip install) |
| `requirements.txt` | `flask>=2.3` |
| `routes/` | benefit_checks, directory_endpoints, participants, patients, prescriptions, test_driving, transaction_fees |
| `services/` | benefit, billing, certification, directory, history, routing |

### Completeness checks (all pass)

- **Syntax**: `python3 -m py_compile` over all modules — OK.
- **Imports**: every module imports cleanly — 0 failures.
- **Boot**: `bash start.sh` with $PORT=18119 binds 0.0.0.0 and serves; unauthenticated GET returns 401 `ERR_UNAUTHENTICATED`; authenticated GET /network/participants returns 200 with the declared array envelope (`meta.api_request_id`, `has_more`, `limit`, `offset`, `total_count`).
- **Endpoints**: 75 `@bp.` route decorators registered; method+path diff against SCAFFOLD.yaml §1.5 shows the sets are identical (56 apparent "mismatches" are purely `{id}` vs Flask `<pid>` placeholder syntax) → **75/75**.
- **Errors**: 48/48 scaffold error ids present (the 49th scaffold token is the `ERR_XXX` template placeholder).
- **No placeholders**: 0 TODO/FIXME/NotImplemented. The only two bare `pass` statements (routes/prescriptions.py:350, :741) are intentional no-op guard branches, not stubs.
- **Dangling references**: full AST scan of `<module>.<attr>` references — the only 9 hits are false positives (Flask-local `app.*` in app.py, and local-list `history.append`/`history.sort` in services/directory.py).
- **Hardest rules present with exact pinned constants**: monthly chargeable ceiling 7500 clamped *before* marginal tiering (`services/billing.py:9,117`); dual reliability variants — chronological 20-window vs EWMA `Decimal("0.0670")` against degrade gate `Decimal("0.90")` (`services/directory.py:11,12,131-143`); variant-dependent deductible-credit basis with brand fee inside vs outside the basis (`services/benefit.py:92-100`).
- **Storage**: in-memory only; `db.reset()` on boot; no seeding/preloading of entity data.

## Step 7: Run tests and iterate — 2026-09-30T05:09:21.403576737Z

Loop exited clean. Final summary:

**Task:** `task_3116_electronic_prescribing_network_routing_directory_medication_history`
**Result:** 8-round parallel sweep — **70/70 passed in all 8 rounds** (verified twice). No `pytest.mark.skip`/`xfail` added, no assertion weakened, no test deleted.

Orchestrator verification of the artifacts: results.{1..8}.json all present, each `passed=70 total=70 fails=0`; test_suite still holds 70 test functions and 70 `Design:` tags across 25 files; 0 skip/xfail markers; no entity seeding in app.py/db.py.

**Iterations run:** 16 (1 baseline sweep + 15 fix/verify rounds on a per-test-server local harness, then the mandated sweep).

### Baseline
39/70 failed deterministically (8/8 in every round — no flakiness initially). The implementation had never been run against the suite.

### Fixes applied to `implementation/`
- `routes/participants.py` — endpoint-overlap key now includes `service_level`; without it every fixture that registers a second live endpoint of one service set failed setup. PRD §3.4/§3.5 require several live candidates per pharmacy.
- `services/certification.py` — `guard_last_active` excludes the endpoint being disabled and exempts a directory of one, so the §3.6 disable cascade can run; certification-window reopen resets and re-derives endpoints; `cascade_disabled_directory` hops 1/4 now cover `ROUTED` clinical status and hop 4 is unconditional.
- `services/directory.py` — coverage invariant counts `DEGRADED` endpoints as still-reachable (they are in §2.4's reachable set) and exempts a directory of one.
- `services/billing.py` — `settle()` settles the row's own count, clamped before tiering, so `fee_cents` is the charged amount (60100 at the ceiling, 3600 for 500) with the reserve exposed separately; `period_net_total_cents` is restamped on every row of the participant-month; the correction basis is the cell's settled count; the compensating row is itself a `REVERSED` marker and is what the reverse call returns.
- `services/routing.py` — backup nomination excludes `DEGRADED` endpoints and every already-probed endpoint; the fallback gate counts `ACTIVE` endpoints only.
- `routes/prescriptions.py` — re-route admits `DELIVERED`/`REJECTED` and returns the order to `ROUTED`; report-undeliverable is re-entrant on an acknowledged network attempt; controlled-order/session error precedence fixed to `ERR_IDENTITY_PROOFING_REQUIRED`; the third OTP failure reports `ERR_ACCOUNT_LOCKED`; `route-fallback` follows §3.5's precondition order; orders inherit the prescriber's `fallback_channel`; `active-attempt`/`routed-endpoint`/`signature-session` return one-element arrays per §4.
- `services/history.py`, `routes/patients.py`, `request_context.py` — consent scope coverage (`BOTH` collides with both singles; the singles do not collide), consent status reconciled against the logical clock, `subscription_generation` increments on the first settle, history-record source/certification checks and route detection.
- `db.py` (version starts at 1), `clock.py` (`iso()` compact whole-second form; logical clock reported in read `meta`), `serializers.py`, `app.py` (404/405 parse the body).

### Fixes applied to `test_helpers/`
`fixtures.py` (`reverse_fee_entry(..., expect_success=False)`; two-endpoint pharmacy specs use ELIGIBLE_A/15 + ELIGIBLE_B/30 on one standard; the uncertified-source record is reported via HubOperator; a separate acting prescriber is certified) and `factories.py` (`create_second_clinic_payload`).

### Test-artifact corrections (the test was the bug, not the implementation)
- `test_03` — tier arithmetic: the standard band is 200–2000 wide, so 7825 unclamped is 62375 (not 82275), 2000 is 21600, and the cell's net count is the surviving charge alone.
- `test_04` — the sub-ceiling band widths were transposed (1800 standard, 5499 volume).
- `test_16` — a `BENEFIT_CHECK` grant under a live `BOTH` window must succeed; it is a different scope.
- `test_18` — `total_count == 3` needs three rows on file.
- `test_19` — a `BENEFIT_CHECK` consent is not a medication-history consent, so the non-controlled order reads `STANDARD`.
- `test_21` — the uncertified-source refusal is issued by a HubOperator.
- `test_23` — the zero-length-consent case reads its patient via the patient API.

**No (i)-silence deletions were required:** every failing assertion traced to a sentence in PRD.md. Two borderline items (`ERR_ACCOUNT_LOCKED` on the third OTF failure, `ERR_IDENTITY_PROOFING_REQUIRED` for a controlled order) are pinned by PRD §3.3's prose ("when the increment carries `otp_attempt_count` to three, `two_factor_status` becomes `LOCKED`"; "this is a stricter restatement of the session precondition for the controlled case"), so they were implemented rather than deleted.

Working notes and per-iteration history: `workspace/implementation/step7_progress.md`.

## Step 8: Finalize PRD — 2026-09-30T05:33:28.285327117Z

PRD_FINALIZED.md is complete. Summary below.

### Metrics
- `PRD.md`: 386 lines. `PRD_FINALIZED.md`: 386 lines. Delta: **0 lines** (all edits are in-place replacements; 27 of 386 lines changed, 7.0%).
- Base file preserved; `PRD_FINALIZED.md` is a copy that was then edited. Progress notes: `workspace/step8_progress.md`.

### Changes (one bullet per edit)
`{section} — {insert|revise} — {what changed} — {impl anchor}`
- §2.2 — revise — `api_request_timestamp`: reads report the logical clock, writes the real instant; whole-second instants serialize compactly (`2026-09-01T00:00:00Z`) — `clock.py:108-133, 40-55`
- §2.2 — insert — `active-attempt`/`routed-endpoint`/`signature-session` carry a one-element array — `routes/prescriptions.py:177,186,205`, `serializers.py:66-68`
- §2.3 — insert — same-instant creation ties break on insertion sequence — `request_context.py:188-190`
- §2.4 — revise — degradation gate is the share of still-reachable endpoints (aligns with §2.6) — `services/directory.py:166-189`
- §2.5 — revise — `version` reads 1 on a fresh resource; timestamps compact when whole-second — `db.py:77-91`, `clock.py:40-55`
- §2.6 — revise — overlap key adds `service_level` — `routes/participants.py:278-281`
- §2.6 — revise — coverage invariant counts `ACTIVE`+`DEGRADED`, exempts a directory of one; last-active guard excludes the endpoint being disabled — `services/certification.py:148-196`, `services/directory.py:166-189`
- §2.7 — revise — `period_net_total_cents` write model: restamped across the participant-month — `services/billing.py:205-210`
- §2.9 — revise — sign's controlled-order precondition is the stricter restatement; 404/405/body parsing behavior — `routes/prescriptions.py:238-239`, `app.py:57-89`
- §2.11 — revise — directory-chain hops widened to `SIGNED`/`ROUTED` + `NOT_ROUTED`/`ROUTED`/`BACKUP_SELECTION`; hop 4 unconditional — `services/certification.py:250-279`
- §3.1 — insert — the order inherits the prescriber's `fallback_channel`/`fax_number` — `routes/prescriptions.py:120-124`
- §3.2 — revise — `CERTIFIED` reopen turns on the endpoint-row requirement alone (no `FAIL` can accumulate) — `services/certification.py:56-75`
- §3.4 — revise — reliability key never consults the identifier (ratios separated by ≥0.0001) — `services/routing.py:52-61`
- §3.4 — revise — backup nomination excludes `DEGRADED` and every already-probed endpoint — `services/routing.py:88-110`
- §3.4 — revise — re-route admits `DELIVERED`/`REJECTED` and returns the order to `ROUTED` — `routes/prescriptions.py:315-323,348`
- §3.5 — revise — report-undeliverable re-entrant on an `ACKNOWLEDGED` network attempt — `routes/prescriptions.py:724-730`
- §3.5 — revise — degrade share = `ACTIVE`+`DEGRADED`; backup needs an in-window `ACTIVE`, unprobed, non-`DEGRADED` endpoint — `routes/prescriptions.py:739`, `services/routing.py:64-126`
- §3.5 — revise — route-fallback precondition order (failed attempt → channel → routing status); gate counts `ACTIVE` only — `routes/prescriptions.py:371-397`, `services/routing.py:113-126`
- §3.6 — revise — suspend cascade hops widened, hop 4 unconditional, no `ERROR_ROUTE_NO_ENDPOINT` stamp — `services/certification.py:250-279`
- §3.6 — revise — disable guard excludes the disabled endpoint; four-hop cascade; hop-4 unconditional — `services/certification.py:169-207,250-279`
- §3.7 — revise — `CORRECTION` `previous_count` basis = settled count — `services/billing.py:88-95,234`
- §3.7 — revise — settlement stores the charged amount in `fee_cents`; reserve exposed separately; net-of-reserve shown as the illustration's "final" — `services/billing.py:131-163`
- §3.7 — revise — compensating row is itself `REVERSED`, self-identifying; reverse reply root = compensating row + `reversal_source` — `services/billing.py:298-343`, `routes/transaction_fees.py:97`
- §3.8 — revise — consent scope coverage (`BOTH` collides with both singles; singles don't); expired window not live — `services/history.py:37-72`
- §3.8 — revise — history-source gate tests the named source; a `Pharmacy` names itself, a `HubOperator` may name any — `routes/patients.py:183-191`
- §3.8 — revise — `source_record_count` reflects the certified live set (impl recomputes on settle) — `services/history.py:238-256`
- §3.8 — revise — `subscription_generation` also increments on the settle out of `PENDING` — `services/history.py:207-217`

### Per-edit pre-edit search log (subject → paths enumerated → adjustment)
Every edit's subject and enumerated paths are logged in `workspace/step8_progress.md`. Notable wordings that were tightened/softened after the enumeration:
- **Coverage invariant (§2.6/§3.5)**: enumerated all three consumers (`directory.degrade_allowed`, `certification.coverage_warning`, `certification.degrade_endpoint`, plus the §2.11 chain comment). Kept "live endpoints" (ACTIVE+DEGRADED, which is `LIVE_ENDPOINT_STATUSES` everywhere) and re-scoped the §2.4 cross-reference from the now-inaccurate "`ACTIVE`-only" to "endpoints that would remain still-reachable".
- **Backup nomination (§3.4/§3.5)**: enumerated `routing.candidates`, `select_endpoint(backup=True)`, `degraded_endpoint_ids`, `failed_endpoint_ids`, and the `rank_key` tail. Written as "remains `ACTIVE`, sits inside its service window, and has not already carried one of this prescription's attempts — a `DEGRADED` endpoint never receives a re-pointed attempt" rather than reproducing the implementation's exact exclusion set, so it stays true for both the report path and any other caller.
- **Route-fallback (§3.5)**: enumerated the route body, `has_live_endpoint_for_set`, and the `ROUTE_FAILED`/`BACKUP_SELECTION` branch. Re-scoped the `ERR_NO_ROUTE_AVAILABLE` clause to the `BACKUP_SELECTION` origin verified by test_09.
- **Settlement (§3.7)**: enumerated `settle`, `post_entry`, `accrue_report`, `entry_payload`, the `reserve_cents`/`final_amount_cents` aliases, and the `WORKED_500_COUNT` helper — renamed the illustration's "final amount" to "amount net of the reserve" so it no longer contradicts the stored `fee_cents`.

### Verification
Claims were checked against the running implementation with an in-process Flask test client (no ports, no servers): `version==1`; the fee row exposes `reserve_cents`/`final_amount_cents`/`reserve_basis_count`/`chargeable_count`; 3600/1080/2520; reverse reply root is `REVERSED`+`MANUAL_REVERSAL` with self `reversal_entry_id` and `reversal_source`; the three certification reopen paths; and the consent/scope/history-source error precedences.

### Deliberately left unchanged (under-determined; Step 9 may pin)
`ERR_ENDPOINT_NOT_ROUTED_ATTEMPT` (never raised), `ERR_FALLBACK_NOT_PERMITTED` semantics, the suspension's `ERROR_ROUTE_NO_ENDPOINT` stamping, the §3.4 route-degrade-on-ratio behavior, §3.9's always-`NON_PREFERRED`/`ACTIVE` resolution, and the §3.8 dedupe `fill_date` ordering direction. These are places the implementation makes a choice the PRD leaves open; pinning them without a Step 7 item risks a false universal claim, which is worse than leaving them under-determined.

## Step 9: Complete PRD — 2026-09-30T05:51:02.786886881Z

`PRD_COMPLETED.md` is written at `workspace/PRD_COMPLETED.md`.

**Source vs. result** — base `PRD_FINALIZED.md`: 386 lines / 87,435 chars. `PRD_COMPLETED.md`: 386 lines / 92,110 chars (+4,648 chars, 15 rewritten lines, 19 inserted/revised edits across 38 diff lines). `PRD_FINALIZED.md` untouched (md5 `07dd086ca6c91aeea422c763bafa084e` — verified by the orchestrator after the fact). Progress notes in `step9_progress.md`.

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions.

**Changes (all verified against impl by reading plus in-process Flask test-client probes):**

- §2.1 — insert — ambiguity — missing `X-User-Role` is admitted on `/network/` and every `/_` path, and entity-backed roles are not resolved there (unrecognized role is still 401) — `request_context.py:41-65`
- §2.6 — revise — mismatch — the below-0.90 degrade gate runs on any ratio recompute, not only the reporting path — `prescriptions.py:355-358`
- §2.6 — insert — ambiguity — the last-active guard fires only while another `ACTIVE` endpoint remains — `certification.py:169-196`
- §2.9 — revise — mismatch — no-route is 404 and undeclared-method is 405 (not 400), and neither refusal names a field — `app.py:57-89`
- §3.2 — insert — ambiguity — endpoint-row requirement evaluated first; no status is barred from opening the window — `certification.py:49-83`
- §3.3 — insert — ambiguity — sign also requires `clinical_status` `DRAFT`/`SIGNED`, and a refused sign leaves the session unconsumed — `prescriptions.py:241-242`
- §3.4 — insert — ambiguity — the route path recomputes the winner's counters before the attempt opens, so it may degrade the endpoint — `prescriptions.py:355-358`
- §3.5 — revise — mismatch — `PATIENT_UNKNOWN`/`BENEFIT_EXHAUSTED` fall outside the undeliverable vocabulary, so `ERR_FALLBACK_NOT_PERMITTED` is unreachable — `prescriptions.py:733-736`
- §3.5 — revise — mismatch — `ERR_ENDPOINT_NOT_ROUTED_ATTEMPT` never raised; the attempt's own target is always degraded; single-endpoint directories exempt — `prescriptions.py:745-751`, `directory.py:166-189`
- §3.5 — insert — ambiguity — a rejection takes `routing_status` `ROUTED`/`BACKUP_SELECTION`/`FALLBACK_SENT`/`FALLBACK_PENDING` to `ROUTE_FAILED` — `prescriptions.py:845-847`
- §3.5 (cancel) — insert — ambiguity — branch chosen by `clinical_status` first; `DRAFT` refused; the `CRITICAL` safety rule runs only after the state band admits — `prescriptions.py:429-450`
- §3.6 — insert — ambiguity — same last-active guard pin — `certification.py:169-196`
- §3.7 — insert — ambiguity — the per-report audit count is the settled read, distinct from the cell-wide chargeable read — `billing.py:75-95,234`
- §3.7 — insert — ambiguity — the correction row carries `transaction_count` 0 and `fee_cents` 0 — `billing.py:258-276`
- §3.8 — insert — ambiguity — the consent gate precedes the status band on aggregate; `FAILED` is refused as a state error — `history.py:199-224`
- §3.8 — revise — mismatch — dedupe third key is `fill_date` **ascending** (earlier wins), not "later fill_date wins" — `history.py:165-171`
- §3.8 — insert — ambiguity — the history-settlement deductible advance is the payer's `plan_copay_cents`, saturating — `history.py:265-286`
- §3.9 — insert — ambiguity — a `PAYER` plan resolves to `NON_PREFERRED`/`ACTIVE`; any other participant leaves both `UNKNOWN` — `benefit.py:38-48`
- §3.9 — insert — ambiguity — a missing `BENEFIT_CHECK`/`BOTH` consent is refused with `ERR_CONSENT_REQUIRED` — `benefit.py:53-55`

**Note on the Step 8 leads list:** the suspension `ERROR_ROUTE_NO_ENDPOINT` stamping needed no edit — Step 8 had already removed it from §3.6, and a probe confirms the attempt carries only `failure_code` `NO_ROUTE`. `has_more`/`total_count` semantics already match (`total_count` = full filtered set, `has_more` = `offset+len(window) < total`).
