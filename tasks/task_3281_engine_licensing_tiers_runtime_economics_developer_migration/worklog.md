# Worklog — task_3281_engine_licensing_tiers_runtime_economics_developer_migration

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Pre-allocated task directory verified to exist with `workspace/` inside: `./tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration` (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T17:15:00.000Z

All three files are written and lint-clean. Final report:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/SCAFFOLD_CORNER_DESIGN.yaml`

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     30
  Calls scanned (§1.8+§1.9):  434

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

- **Entities: 16** (TierConfig, DeveloperOrg, RevenueDeclaration, SeatSubscription, EditorVersion, GameProject, InstallReport, RuntimeFeeInvoice, PolicyChange, GrandfatherCommitment, AssetListing, AssetPurchase, ExportAgreement, ExportBuild, AuditCase, MigrationAssessment)
- **Endpoints: 71** declared in §1.5 — note this exceeds the ~40 sweet spot flagged in memory as risky for impl-gen; the overshoot is driven almost entirely by FK reverse-reachability GETs and single-resource GETs that `scaffold_lint.py` check (f) and segment derivation require. The *business-action* surface is ~45 endpoints; the rest are thin reads. If impl-gen struggles, the filtered-list GETs (`/install-reports`, `/invoices`, `/export-builds`, `/grandfather-commitments`) are the first candidates to consolidate.
- **Errors: 26**, **Validations: 20** (ordered priority bands), **Calculations: 7**, **State machines: 11**, **Roles: 5**, **OCC concurrency rules: 2**
- **§1.8: 9 rules × 2 instances = 18**, all with structured `setup_api_calls` and precomputed literal asserts (I executed every formula in Python before pinning values: e.g. provisional fee 2,250,000¢; buyout 198,000¢; back-bill 250,000¢; creator share 140,000¢; risk scores 7→15)
- **§1.9: 30 instances across 9 sections**, no name collisions across the union

## Notable design decisions ("much harder than expert" levers)

1. **Dual-variant pairs on different domains**: tier determination (actual-TTM vs annualized projection, flips PERSONAL→PRO on identical data) × runtime fee (provisional vs final, 2,250,000¢ → 0¢ after dispute revision).
2. **Combinatorial formulas in different modes**: buyout settlement (mode a: 4-input tenure-tier × partial-month-rounds-UP interaction) × runtime fee (mode b: pinned line-then-sum rounding).
3. **Two interval semantics that deliberately disagree**: seat subscriptions use half-open `[start,end)` where adjacency is *allowed*; export agreements and LTS windows use closed `[start,end]` where touching endpoints *conflict* — same-looking data, opposite verdicts.
4. **Depth-3 cascades from different triggers**: audit-CONVERT (tier→trust→back-bill→invoice re-rate) and policy-activate (commitment snapshot→pin→trust decrement→listing re-review below trust floor 50).
5. **GrandfatherCommitment attestation window**: commitments auto-VOID past `announcement_date + grandfather_window_days` unless the org attests — adds a scheduled/deferred dimension to retroactive policy handling; anti-double-counting pinned explicitly in `runtime_fee_assessment` (retroactivity changes the rate going forward, never re-bills accepted installs).
6. **Parallel state dimensions** on RuntimeFeeInvoice (assessment × payment) and a true revision cycle on InstallReport (DRAFT→SUBMITTED→UNDER_REVIEW→DISPUTED→DRAFT).
7. **Logical clock** with the mandated fixed default `2026-09-01T00:00:00Z`; all date math (due dates, cooling-off, refund window, tenure, LTS windows) keys off it.
8. `api_prefix: ""` — the API is multi-root (`/orgs`, `/projects`, `/tiers`, …); a non-empty prefix breaks the lint's segment heuristic, which assumes the whole API hangs under one root collection (as in the examples).

## Step 3: Copy Shared Files — 2026-09-30T17:16:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T17:25:00.000Z

All three contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/workspace/PRD.md` — 336 lines.

**Sections covered:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (5 roles with identity prose), 2.2 verbatim response envelope, 2.3 pagination (limit default 10 / min 1 / max 100, offset 0, created_at ascending), 2.4 common resource properties (incl. the three `common_fields: false` entities — RevenueDeclaration, AssetPurchase, ExportBuild), 2.5 logical clock (2026-09-01T00:00:00Z default), 2.6 integer-cents + pinned line-then-sum rounding, 2.7 two tier-determination variants, 2.8 invoice ledger compensating invariant, 2.9 OCC (`expected_org_version`, `expected_project_version`, `ERR_STALE_VERSION`/412), 2.10 left-to-right path resolution + full 20-priority validation ordering, 2.11 status codes.
- §3 Business Logic in 8 subsections: tiers & onboarding (tier_determination both variants), seats (half-open overlap, EXHAUSTED/EXPIRED), editor versions & projects (LTS closed-window overlap, upgrade_risk_score formula), install reports & runtime fees (dual threshold 1,000,000 installs + 100,000,000 cents, rates 20/5 cents at 100,000 boundary, provisional/final variants, pay/waive with 0.5 cap), policy changes & grandfathering (3-hop cascade, trust −10, 30-day window rule), marketplace (30%/25% share at 100,000,000-cent boundary, refund 14 days), export agreements (closed-interval overlap, revoke cascade), audits & migration (back-bill formula, appeal ±15 trust reversal, buyout settlement with 15,000-cent seat-month and 36/12-month tenure tiers, 14-day cooling-off, completion gate).
- §4 endpoint table — all **71/71** scaffold endpoints present with method, path, description, roles; 4-column format.
- §5 error catalogue — all **26/26** error IDs with HTTP statuses; 2-column format.

**Contract reports:**
- Field coverage check: 111 required (entities + endpoint inputs/query/path), 111 present, 0 missing. Status: PASS
- Rule coverage check: 20 priority-ordered validations expressed in §2.10 with endpoint scopes in §3; 2 OCC rules fully specified (endpoint + expected-version field + `ERR_STALE_VERSION`/412); all state-machine transitions across 10 machines expressed with preconditions and side effects (incl. the 3 cascades: policy activation, audit conversion, revocation, migration completion); all 7 calculations in precise prose with constants; every error_id matchable to a prose trigger; sibling branches (CLEARED/CONVERTED resolve, appeal outcomes, DISPUTED revision cycle) symmetric. Status: PASS
- Path purity check (§3 only): 582 backtick tokens scanned, 0 path/method violations. Status: PASS

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate Unit Tests — 2026-09-30T17:45:00.000Z

All clean. Final summary of the generation.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/`):

Stage 1 — `test_helpers/` (9 files): `__init__.py` (barrel export), `types.py` (15 entity TypedDicts with correct common_fields branching — RevenueDeclaration/ExportBuild/AssetPurchase omit `version`/`updated_at` per PRD §2.4, 19 status enums, role enum), `api_client.py` (52 endpoint methods covering the full §4 surface), `api_errors.py` (26 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + seat-pool invariant), `constants.py` (PRD thresholds incl. canonical tier configs), `factories.py`, `test_users.py` (opaque shared constants + mandatory `make_org_owner_headers(org_id)` entity-backed builder), `fixtures.py` (composite helpers: tier setup, org/project/ship, report lifecycle through ACCEPTED/DISPUTED, subscriptions, marketplace purchase, agreements, audit conversion, migration cooling-off, clock).

Stage 2 — `test_suite/` (8 files): `conftest.py` plus `test_01_tiers_and_orgs.py` (7 tests), `test_02_seat_subscriptions.py` (6), `test_03_editor_versions.py` (3), `test_04_install_reports.py` (12), `test_05_invoices.py` (8), `test_06_policy_changes.py` (4), `test_07_marketplace.py` (5), `test_08_exports.py` (5), `test_09_audit.py` (3), `test_10_migration.py` (5), `test_11_security.py` (2).

**Test counts**: 66 total — Queue A (Difficulty): 18/18 instances × ≥2 tests (36); Queue B (Corner): 30/30 non-stub instances × ≥1 (30). No stubs existed in queue B; no instances skipped — every instance passed the PRD-first two-condition filter.

**Notable adjudications**: the corner `default_clock_is_fixed_startup_time` recipe's no-op clock-set was omitted (the PRD's "before any clock-set call" default must hold unmutated; the due_date assertion retains the discriminating assertion). One ambiguity found: `test_cooling_off_not_elapsed_blocks_completion` asserts error one-of {ERR_MIGRATION_BLOCKED, ERR_INVALID_STATE} because PRD §2.10's state-vs-migration-gate ordering is not pinned for this pair (state precedence would be invented from the scaffold otherwise).

**Stage 1 self-check**: all files compile; `import test_helpers` succeeds; pytest collects 66 tests; no skip/xfail markers; no scaffold references in generated code.

**Stage 2 self-check**: automated audit confirms every queue-A instance has ≥2 tests and every queue-B non-stub instance has ≥1 test, all 66 tags resolve to real instances, exactly one `Design:` line per test, and all 84 PRD citations contain ≥8-word verbatim substrings of `workspace/PRD.md` (backtick/whitespace-normalized).

## Step 6: Generate Implementation — 2026-09-30T17:50:00.000Z

Implementation complete and verified.

## Summary

**Files written** (19 files, 3,042 lines total) in `/home/ubuntu/github/CodingPRD/tasks/task_3281_engine_licensing_tiers_runtime_economics_developer_migration/workspace/implementation/`:

| File | Lines | Purpose |
|---|---|---|
| start.sh | 9 | Guarded pip install + `exec python3 app.py` |
| requirements.txt | 1 | flask |
| app.py | 39 | Flask app, blueprint registration, 0.0.0.0:$PORT |
| db.py | 35 | Empty in-memory store + logical clock default 2026-09-01 |
| errors.py | 41 | ApiError + all 26 error IDs with HTTP statuses |
| helpers.py | 256 | Envelope (`meta`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`), dates, OCC touch/version |
| middleware.py | 61 | X-User-ID/X-User-Role auth, RBAC, OrgOwner ownership |
| services_calc.py | 281 | tier_determination (both variants), runtime_fee_assessment (tiered, line-then-sum ROUND_HALF_UP), standing, risk score, balance ledger, fee-schedule selection |
| services_clock.py | 62 | Clock-advance cascades (subscription/agreement expiry, invoice OVERDUE, commitment voiding) |
| routes_core.py | 99 | Clock set + tier CRUD/supersession |
| routes_orgs.py | 179 | Org registration, declarations, tier-assessment, ledger |
| routes_seats.py | 123 | Subscription purchase (OCC, half-open overlap), assign/release |
| routes_editor.py | 154 | Editor versions + LTS/DEPRECATED/SUNSET transitions |
| routes_projects.py | 163 | Project create/list/ship with grandfathering evaluation |
| routes_reports.py | 269 | Install reports, supersession, submit/review/revise pipeline |
| routes_invoices.py | 175 | Invoice finalize/pay/waive with waterfall + waiver cap |
| routes_policy.py | 193 | Policy changes, 3-hop activation cascade, commitments, attest |
| routes_marketplace.py | 269 | Listings lifecycle, purchases (30%/25% share), refunds |
| routes_exports.py | 216 | Agreements (closed-interval overlap), activation, builds |
| routes_audits.py | 221 | Audit cases, CONVERT cascade with back-bill, appeals |
| routes_migration.py | 196 | Migration assessments, buyout settlement, completion gate |

**Endpoint coverage: 71/71** declared endpoints implemented.

**Boot verification** (server launched via `bash start.sh` on a free port, killed by exact PID):
- `GET /tiers` without headers → 401 `ERR_UNAUTHENTICATED` (correct envelope)
- `POST /_clock/set_current_utc` → `{"current_utc":"2026-09-15T00:00:00.000Z"}`
- Full lifecycle verified end-to-end: tier create → org register → declaration → seat subscription (OCC) → project → ship → install report → submit → REVIEW → ACCEPT → invoice FINALIZED with correct fee **2,500,000** (1.2M installs, 200k chargeable above 1M threshold: 100k×20¢ + 100k×5¢) → exact pay → PAID → audit open/evidence/clear → migration EXPORT_READY → COOLING_OFF → clock advance → COMPLETED → project ARCHIVED
- Marketplace: 1000¢ purchase splits 300 platform / 700 creator, credit accrues, refund reverses to 0; `ERR_BUYER_IS_CREATOR` on self-purchase
- Error paths confirmed: `ERR_AGREEMENT_OVERLAP` (closed-interval adjacency), `ERR_POLICY_WINDOW_TOO_SHORT`, `ERR_FORBIDDEN_ORG` (foreign org), `ERR_NOT_FOUND` (nonexistent org as OrgOwner)

**Bug found and fixed during verification:** the ACCEPT handler originally consumed billable installs into `lifetime_installs` before recomputing the final fee, which inflated the chargeable portion (7.5M instead of 2.5M). Reordered so the gate uses pre-consumption lifetime; `POST /invoices/{id}/finalize` passes an explicit `lifetime_before_override` since acceptance has already consumed the installs.

**Orchestrator disk verification:** 19 files on disk (3,048 lines per `wc -l`), `python3 -m py_compile` passes on all .py files, `@bp.route` decorator count across `routes_*.py` is exactly 71 — matches the declared endpoint count.

## Step 7: Run Tests and Iterate — 2026-09-30T18:10:00.000Z

All 8 rounds pass 66/66. Clean sweep.

## Summary

**Iterations run:** 2 (initial sweep: 56/66 with 10 unique deterministic failures; second sweep after fixes: 8/8 rounds clean at 66/66).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**

- `test_suite/test_01_tiers_and_orgs.py` — `test_tier_assessment_variants_partial_year` and `test_tier_assessment_effective_tier_bumped_to_org`: monthly declaration amounts were 40_000_000, which made actual TTM (160M) exceed even the PRO ceiling (100M), contradicting the test's own expected `tier_by_actual == "PERSONAL"`. Reduced to 4_000_000/month (actual 16M < 20M PERSONAL ceiling; annualized 48M → PRO), matching the PRD §3.1 partial-year annualization rule.
- `test_suite/test_04_install_reports.py` — `test_provisional_charged_final_zero_after_downward_revision` and `test_final_variant_uses_lifetime_at_acceptance`: the original setup (lifetime 1M, revise 150k→50k) could never yield final == 0 under the PRD §3.4 formula (chargeable would be 50k × 20c = 1M), and its two assertions were mutually inconsistent. Rebuilt the scenario per the cited PRD sentence ("a dispute revision that lowers billable installs below the crossing point"): lifetime 950k, revise to 40k → gate fails at acceptance (990k < 1M) → final 0; provisional corrected to 2_000_000.
- `test_suite/test_05_invoices.py` — `test_partial_waive_then_exact_pay_zeroes_balance` and `test_waive_reduces_balance_by_exact_amount`: setup used `charity_flag=True` while asserting a 2M final invoice, contradicting PRD §3.4 verbatim ("the project's charity_flag is set → the amount is zero regardless of the gate"). Added `_setup_grandfathered_finalized_invoice` which builds waiver eligibility via the PRD's "grandfathering was applied in error" branch (retroactive adverse policy activation pins a BASE GrandfatherCommitment, invoice labeled BASE, capped-not-full waiver), preserving the 50%-cap and compensating-invariant assertions.
- `test_suite/test_06_policy_changes.py` — `test_trust_below_50_flips_standing_and_forces_re_review`: project shipped at the default clock (2026-09-01), after all four announcement dates, so PRD §3.5 hop one ("shipped_on on or before the announcement_date") never applied and no trust drop occurred. Added `set_clock("2026-01-05T00:00:00Z")` before setup so shipped_on precedes the announcements.

**Fixes applied to `implementation/`:**

- `services_calc.py` — `recompute_effective_tier`: switched from the actual variant to the annualized projection variant (PRD §3.1: "the annualized variant governs the self-service tier assessment"; the actual variant is reserved for audit review and invoice qualification). `_signal_tier`: removed the un-PRD fallback to ENTERPRISE when no ACTIVE tier config admits the figures — PRD reads constants "from ACTIVE tier configs only", so with no admitting config there is no signal tier and the effective tier stays at the declared tier (`effective_tier_from_variant` handles the None signal).
- `routes_reports.py` — `submit_report`: resubmitting a report that went DISPUTED → revise → DRAFT now re-rates its existing ADJUSTED invoice back to PROVISIONAL instead of creating a second invoice for the same report (PRD §3.4: "The revision cycle DISPUTED back through DRAFT and SUBMITTED may repeat as often as needed" — one invoice per report, created "at submission" in PROVISIONAL status).

**Orchestrator verification:** all 8 `results.{1..8}.json` on disk report 66/66 passed / 0 failed; newest implementation source edit (18:01) predates the sweep results (18:06) — no post-sweep writes invalidated the sweep.

## Step 8: Finalize PRD — 2026-09-30T18:20:00.000Z

The diff is clean — exactly two in-place revisions, no duplication. Done.

## Summary

**Line counts:** PRD.md 335 lines; PRD_FINALIZED.md 335 lines (0% delta — both edits are in-place revisions to existing paragraphs, no new sections).

**Changes (one bullet each):**

- **§3.1 (Tier determination paragraph, line 142) — revise** — Added "If no ACTIVE config admits the figures, there is no signal tier and the effective tier remains the declared tier," and pinned that the declaration-triggered `effective_tier_code` recomputation runs under the **annualized projection variant** (per §2.7), with the actual variant reserved for audit review and invoice qualification — `implementation/services_calc.py:68-88` (`_signal_tier` returns None, no ENTERPRISE fallback), `services_calc.py:100-101` (`effective_tier_from_variant` keeps declared tier on None signal), `services_calc.py:107-115` (`recompute_effective_tier` calls `effective_tier_from_variant(org, "annualized")`), exercised by `routes_orgs.py:109`.

- **§3.4 (Install report submission paragraph, line 172) — revise** — Appended: a report carries exactly one non-`VOIDED` invoice across its lifecycle; resubmitting a report with an existing invoice (e.g. the `ADJUSTED` invoice left by a dispute revision) re-rates that same invoice back to `PROVISIONAL` with recomputed `provisional_amount_cents` instead of creating a second invoice — `implementation/routes_reports.py:161-172` (`submit_report` existing-invoice branch).

**Step 7 diff items that required NO PRD edit** (verified against impl/tests): all four test-only fixes (test_01 amounts, test_04 fixture scenarios, test_05 grandfathered waiver setup, test_06 clock positioning) were fixture bugs aligning tests to PRD-determined behavior; the PRD text they cite (§2.7, §3.1 annualization, §3.4 charity-zero/provisional-vs-final, §3.4 waiver cap, §3.5 hop-one "on or before announcement_date") already matches the implementation verbatim.

**Per-edit pre-edit search log:**

*Edit 1 (effective-tier variant + no-signal-tier):*
- (a) Subject: which revenue variant drives `effective_tier_code` recomputation, and the signal-tier outcome when no ACTIVE tier config admits the figures.
- (b) Paths enumerated: `services_calc.py` `_signal_tier` (L68-88), `effective_tier_from_variant` (L91-104, both `"actual"` and `"annualized"` variants), `recompute_effective_tier` (L107-115); callsites via grep — `routes_orgs.py:109` (declaration recompute), `routes_orgs.py:139-141` (tier-assessment read, both variants), plus audit conversion (`routes_audits.py:88-127`) which sets the tier directly and bypasses signal logic. Tier fixture constants checked in `test_helpers/constants.py:57-99` (ENTERPRISE unlimited 0/0 in canonical fixtures).
- (c) Wording adjustments: (i) scoped the variant pin to "recomputed under the annualized projection variant" and explicitly preserved the actual variant's role in audit review/invoice qualification, so `tier_by_actual` and the §3.4 revenue gate remain correctly described; (ii) scoped the no-config clause with "If no ACTIVE config admits the figures" rather than a universal claim, leaving the always-admitting-config paths (canonical ENTERPRISE 0/0 fixtures) untouched; (iii) used "remains the declared tier" (matching `return declared`, which may equal the current effective tier) instead of "is unchanged" to avoid mis-describing the convergent case where effective == declared.

*Edit 2 (one invoice per report on resubmission):*
- (a) Subject: invoice creation/reuse semantics at report submission, including the DISPUTED → revise → DRAFT → resubmit cycle.
- (b) Paths enumerated: `routes_reports.py` `submit_report` (L138-187, both new-invoice and existing-invoice branches), `revise_report` (L254-284, sets `ADJUSTED` in place), `review_report` DISPUTE (L239-251) and ACCEPT (L216-237, finalizes `PROVISIONAL`/`DISPUTED`/`ADJUSTED` in place), `create_report` (L60-75, voids only the superseded *draft's* PROVISIONAL invoice — different report), `routes_audits.py` `_conversion_cascade`/`_reversal_cascade` (L129-140, 153-163, re-rate in place), `routes_policy.py` `activate_policy` (L107-111, relabels in place), `routes_invoices.py` `finalize_invoice` (L85-111).
- (c) Wording adjustments: (i) qualified "exactly one **non-`VOIDED`** invoice" so the create-report supersession path (which legitimately leaves a VOIDED invoice behind, per the untouched §3.4 draft-supersession sentence) is not contradicted; (ii) framed the common case as an example ("for instance an ADJUSTED invoice left by a dispute revision") since the impl's lookup accepts any non-VOIDED status; (iii) placed the sentence after the creation sentence so "creates the report's RuntimeFeeInvoice" still governs the first-submission path, matching the impl's create-if-none branch.

## Step 9: Complete PRD — 2026-09-30T18:30:00.000Z

The diff shows only additive sentence-level changes (35 `>` lines across 21 edited passages; every `<` line is a paragraph that was revised in place, not removed wholesale). PRD_COMPLETED.md is written.

## Summary

**Source vs output**: `workspace/PRD_FINALIZED.md` — 335 lines / 62,470 chars → `workspace/PRD_COMPLETED.md` — 340 lines / 69,534 chars (+5 lines, +7,064 chars).

**Counts**: 20 ambiguity-pins, 6 mismatch-revisions.

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what — impl file:line):

- §2.2 Error format — insert — ambiguity — unrouted paths and wrong-method requests return 404 `ERR_NOT_FOUND` — helpers.py:227-243
- §2.3 Pagination — revise — ambiguity — non-numeric limit/offset fall back to defaults; out-of-range values clamped (1/100/0) — helpers.py:132-147
- §2.5 Logical clock — revise — mismatch — clock is set (not "advanced"), cascades cover commitment voiding; editor-version transitions are endpoint-driven, not clock-driven; no separate clock-read endpoint; malformed `to_iso8601` → `ERR_VALIDATION` — routes_core.py:17-29, services_clock.py:9-62
- §2.8 Invoice ledger — insert — ambiguity — pay/waive on non-FINALIZED or non-UNPAID/OVERDUE invoice rejected with `ERR_INVALID_STATE` — routes_invoices.py:119-122, 146-149
- §2.10 Validation ordering — insert — ambiguity — org-pathed endpoints: nonexistent org → 404 before ownership → 403; bare-id endpoints resolve the resource (404) before org-chain ownership (403) — middleware.py:35-47, routes_reports.py:39-43
- §3.1 Org registration — insert — ambiguity — trust score adjustments clamp to [0,100] — routes_policy.py:119, routes_audits.py:150
- §3.1 Tier determination — revise — ambiguity — EDUCATION demotion applies to declared-tier rank too; equal rank resolves to signal tier; audit suggestion surfaced as org field `audit_suggestion` = `REVENUE_CEILING_BREACH` — services_calc.py:96-104, routes_orgs.py:111-116
- §3.1 Standing gates — revise — mismatch — standing thresholds pinned (trust <25 → SUSPENDED; <50/open audit/overdue → REVIEW); migration_status mapping pinned; SUSPENDED gate also covers declarations, seat purchases, project/report/agreement creation; those creates apply the same rejection to migrated orgs — services_calc.py:132-167, routes_orgs.py:87-88
- §3.2 Seat purchase — insert — ambiguity — overlap check disregards EXPIRED subscriptions — routes_seats.py:43-50
- §3.2 Seat assign/release — revise — ambiguity — assign from non-ACTIVE subscription → `ERR_SEAT_CAPACITY`; `member_label` accepted but not persisted — routes_seats.py:94-108
- §3.3 EditorVersion creation — insert — ambiguity — new versions start with `lts_window_start`/`lts_window_end` unset — routes_editor.py:45-46
- §3.3 Editor transitions — revise — mismatch — allowed pairs enumerated, others → `ERR_INVALID_STATE`; LTS overlap checks only other versions in LTS/DEPRECATED; date-gate failures → `ERR_INVALID_STATE`; SUNSET always reached via LTS so window exists — routes_editor.py:98-154
- §3.3 Project creation — insert — ambiguity — risk score initialized by the §3.3 formula at creation (lands on 0 for fresh SUPPORTED versions) — routes_projects.py:59
- §3.3 Ship — insert — ambiguity — ship-time grandfather evaluation also sets `pinned_policy_change_id` — routes_projects.py:161
- §3.4 Report submit — revise — mismatch — APPEALED cases do not freeze report submission (only OPENED/EVIDENCE_REQUESTED); non-DRAFT submit → `ERR_INVALID_STATE`; non-SHIPPED project → `ERR_INVALID_STATE` — routes_reports.py:146-154
- §3.4 Review pipeline — revise — ambiguity — acceptance order pinned (finalize invoice against pre-consumption lifetime, then consume installs, then balance); REVIEW/ACCEPT/DISPUTE require SUBMITTED/UNDER_REVIEW states; DISPUTE requires a non-empty `review_note` (`ERR_VALIDATION`) — routes_reports.py:209-251
- §3.4 Schedule selection — revise — mismatch — CONVERTED branch = org has CONVERTED/APPEALED case or any ACTIVE policy change; CONVERTED pricing uses latest ACTIVE change's `new_per_install_cents` as a flat rate for both bands, else base rates — services_calc.py:210-270
- §3.4 Waiver — revise — ambiguity — qualification operationalized (charity flag, exempt current tier config, BASE label); charity/exempt qualify for full waiver; BASE-label cap compares cumulative waived + amount against half of final; over-outstanding → `ERR_WAIVER_NOT_ALLOWED` — routes_invoices.py:159-175
- §3.4 Overdue + ledger — revise — ambiguity — overdue flip requires FINALIZED/UNPAID and strictly past due date; ledger totals aggregate all non-VOIDED invoices — services_clock.py:34-49, routes_orgs.py:154-179
- §3.5 Policy create/activate — revise — ambiguity — all policy fields required at creation (`ERR_VALIDATION`), so dates are always set by activation; only DRAFT may activate/rescind; trust drop floored at 0 — routes_policy.py:20-57, 70-84
- §3.5 Attestation — insert — ambiguity — attestation after deadline rejected `ERR_INVALID_STATE` and voids the commitment on the spot — routes_policy.py:170-193
- §3.6 Listing review — insert — ambiguity — review on non-PENDING_REVIEW listing → `ERR_INVALID_STATE`; revise updates title/price only when supplied — routes_marketplace.py:111-151
- §3.6 Purchase — insert — ambiguity — buyer `X-User-ID` must be an existing org (`ERR_NOT_FOUND`) — routes_marketplace.py:177-179
- §3.6 Refund — revise — ambiguity — window inclusive of exactly purchased_at+14d; credit decrement floored at zero — routes_marketplace.py:246-269
- §3.7 Agreements/builds — revise — mismatch — removed unimplemented revocation second hop (billable console installs treated as bundle_installs); activation overlap check excludes the agreement itself; builds on FROZEN/ARCHIVED projects → `ERR_PROJECT_FROZEN`; expiry strict `today > term_end` and applies to PENDING and ACTIVE — routes_exports.py:103-171, services_clock.py:25-31
- §3.8 Conversion cascade — insert — ambiguity — invalid/not-higher `resolved_tier_code` → `ERR_VALIDATION`; case records pre-conversion tier; trust reversal capped at 100 — routes_audits.py:184-193, 88-151
- §3.8 Migration advance — revise — ambiguity — allowed edges enumerated with `ERR_INVALID_STATE` otherwise; VOIDED invoices do not block COMPLETED — routes_migration.py:126-183
