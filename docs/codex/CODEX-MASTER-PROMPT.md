# Ready-to-paste Codex prompt

You are continuing Phase A1 of the stable catalog distribution project.

Repository:
`gaato77/media-organizer-catalog`

Required branch:
`codex/stable-channel-backfill`

## 1. Synchronize safely before doing any work

1. Run `git status --short` and record the output.
2. The aborted previous attempt reported only these uncommitted SDD scratch paths:
   - `.superpowers/sdd/.gitignore`
   - `.superpowers/sdd/2026-07-25-stable-channel-and-historical-backfill/progress.md`
3. If and only if those are the only uncommitted paths, remove/reset them because they belong to the superseded plan.
4. If any other uncommitted path exists, inspect it and do not discard it without reporting why.
5. Fetch origin and fast-forward the worktree to the latest `origin/codex/stable-channel-backfill`.
6. Verify these files exist:
   - `docs/codex/CODEX-HANDOFF.md`
   - `docs/codex/PHASE-A1-MASTER-PLAN.md`
   - `docs/codex/CODEX-MASTER-PROMPT.md`

Read the complete `docs/codex/CODEX-HANDOFF.md` and then the complete `docs/codex/PHASE-A1-MASTER-PLAN.md`.

`docs/codex/PHASE-A1-MASTER-PLAN.md` is the single authoritative source for this task. It supersedes every earlier prompt, handoff, cross-repository plan, and old SDD ledger wherever they conflict.

## 2. Scope resolution

Execute Phase A1 only.

During A1:

- implement and test code and workflow definitions in `codex/stable-channel-backfill`;
- do not dispatch the new historical workflow;
- do not publish real base, supplement, or current-year assets;
- do not require public component pointers or `catalog/channel/stable.json` during PR CI;
- do not create fake pointers, hashes, releases, or stable-channel files;
- never commit directly to `main`;
- never merge the pull request.

Real publication is Phase A2, after human review and merge of the A1 PR to `main`.
The reason is that GitHub cannot manually dispatch a new `workflow_dispatch` workflow until the workflow file exists on the default branch.

## 3. Mandatory technical safeguards

Treat every item below as review-blocking:

1. All base, supplement, and current-year publication paths use the same concurrency group `stable-catalog-publication` with `cancel-in-progress: false`.
2. Historical base and supplement release tags are immutable:
   - never overwrite them with `--clobber`;
   - create when absent;
   - when present, verify existing asset names, sizes, and SHA-256 values;
   - continue only when byte-for-byte equivalent, otherwise fail without changing releases or pointers.
3. The 1950–2015 recovery workflow exposes optional `source_run_id`, default `30157271026`, and preflights that all `year-1950` through `year-2015` artifacts exist before download/build/publication.
4. No pointer or stable channel is written until release upload and verification succeed.
5. Publishing workflows commit only intended generated pointers, `catalog/current/latest.json` when applicable, and `catalog/channel/stable.json`; unrelated changes cause failure.
6. Publishing workflows pull/rebase before generated commits and never force-push.
7. PR CI validates every workflow YAML with a concretely pinned official `actionlint` version plus checksum or immutable image digest; mutable `latest` is prohibited.
8. The application-facing channel never permanently hardcodes 2026 or another current year.
9. Default PR tests run offline and do not depend on real releases; network distribution verification is opt-in through `CATALOG_DISTRIBUTION_ROOT`.
10. Durable user downloads come only from GitHub Releases, never Actions artifact URLs.

## 4. Execute with Superpowers subagent-driven development

- use an isolated worktree;
- initialize a fresh persistent ledger whose first line names `docs/codex/PHASE-A1-MASTER-PLAN.md`;
- do not reuse the ledger from the superseded plan;
- create one todo per master-plan task;
- use a fresh implementer for every task;
- after each task, run separate specification-compliance and code-quality reviews;
- resolve findings before marking a task complete;
- commit each approved task with the commit message specified by the master plan;
- do not run conflicting implementation tasks in parallel in this repository;
- continue without asking for confirmation between tasks;
- perform the complete final verification and whole-branch review;
- push `codex/stable-channel-backfill` and open a PR to `main`;
- stop after the unmerged PR has green CI and A1 evidence is recorded.

## 5. Required task sequence

1. Implement strict stable-channel models and tests.
2. Implement verified component-pointer generation and CLI.
3. Implement atomic stable-channel assembler and CLI.
4. Prepare the durable 1950–2015 base publication workflow, including source artifact preflight, immutable publication behavior, shared concurrency, actionlint CI, and static/local verification only.
5. Prepare the 2016–2025 matrix/consolidation/publication workflow, immutable publication behavior, shared concurrency, and static/local verification only.
6. Integrate dynamic current-year pointer and stable-channel generation with release-before-pointer ordering and shared concurrency, static/local verification only.
7. Add default-offline and opt-in-network distribution tests plus maintainer/user documentation.
8. Run final verification, independent whole-branch review, push, and open the unmerged PR.

## 6. Required final commands

```bash
python -m pip install -e "builder[test]"
python -m pytest builder/tests -q
python -m ruff check builder
python -m ruff format --check builder
python -m mypy builder/src/media_catalog_builder
```

Also run the exact pinned actionlint command used by CI when locally available; CI must run it regardless.

## 7. Pull request completion criteria

The PR must:

- target `main` from `codex/stable-channel-backfill`;
- remain unmerged;
- have green CI, including actionlint;
- contain focused reviewed commits;
- contain no fake generated distribution files;
- describe that actual publication is Phase A2 after merge;
- document the exact A2 order: base publication, supplement publication, current-year publication, then public network verification.

Suggested title:

`Prepare stable catalog channel and complete historical coverage`

## 8. Blocking policy

A genuine blocker is something not resolved by the authoritative master plan and not correctable from repository evidence.

A blocker report must include:

- exact command;
- complete relevant output;
- file path;
- branch and commit;
- investigation performed;
- why the master plan does not resolve it;
- one specific decision required.

Start now at Task 1 and continue through all of Phase A1 without further confirmation.
