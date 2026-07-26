# Ready-to-paste Codex prompt

You are continuing Phase A1 of the stable catalog distribution project.

Repository:
`gaato77/media-organizer-catalog`

Required branch:
`codex/stable-channel-backfill`

First synchronize safely:

1. Run `git status --short` and record the output.
2. The aborted previous attempt was reported to have created only these uncommitted SDD scratch paths:
   - `.superpowers/sdd/.gitignore`
   - `.superpowers/sdd/2026-07-25-stable-channel-and-historical-backfill/progress.md`
3. If and only if those are the only uncommitted paths, remove/reset those scratch changes because they belong to the superseded plan.
4. If any other uncommitted path exists, inspect it and do not discard it without reporting why.
5. Fetch origin and fast-forward the worktree to the latest `origin/codex/stable-channel-backfill`.
6. Verify these two files exist in the local branch:
   - `docs/codex/CODEX-HANDOFF.md`
   - `docs/codex/PHASE-A1-MASTER-PLAN.md`

Read `docs/codex/CODEX-HANDOFF.md`, then read the complete `docs/codex/PHASE-A1-MASTER-PLAN.md`.

The master plan is the single authoritative source for this task. It supersedes all earlier prompts, handoffs, and cross-repository plans wherever they conflict.

Critical resolution:

- Execute Phase A1 only.
- Implement and test the code and workflow definitions in the feature branch.
- Do not dispatch the new historical workflow during A1.
- Do not publish real base, supplement, or current-year assets during A1.
- Do not require public component pointers or `catalog/channel/stable.json` to exist during PR CI.
- Do not create fake pointers, hashes, releases, or stable-channel files.
- Real publication is Phase A2, after a human reviews and merges the A1 PR to `main`.
- Never commit directly to `main`.
- Never merge the pull request.

Use Superpowers subagent-driven development exactly as follows:

- use an isolated worktree;
- initialize a fresh persistent ledger whose first line names `docs/codex/PHASE-A1-MASTER-PLAN.md`;
- do not reuse the ledger from the superseded plan;
- create one todo per master-plan task;
- use a fresh implementer for each task;
- after each task, perform separate specification-compliance and code-quality review;
- resolve review findings before marking the task complete;
- commit each approved task with the commit message specified by the master plan;
- do not run conflicting implementation tasks in parallel inside this repository;
- continue without asking me for confirmation between tasks;
- run the complete final verification and whole-branch review;
- push `codex/stable-channel-backfill` and open a pull request to `main`;
- stop after the PR has green CI and Phase A1 evidence is recorded.

The expected task sequence is:

1. strict stable-channel models and tests;
2. verified component-pointer generation and CLI;
3. atomic stable-channel assembler and CLI;
4. prepare durable 1950–2015 base publication workflow, static/local verification only;
5. prepare 2016–2025 historical-range workflow, static/local verification only;
6. integrate dynamic current-year pointer and stable-channel generation, static/local verification only;
7. add default-offline and opt-in-network distribution tests plus documentation;
8. complete verification, independent branch review, push, and open the unmerged PR.

Required final local commands:

```bash
python -m pip install -e "builder[test]"
python -m pytest builder/tests -q
python -m ruff check builder
python -m ruff format --check builder
python -m mypy builder/src/media_catalog_builder
```

A genuine blocker is something not resolved by the master plan and not correctable from repository evidence. A blocker report must include the exact command, complete relevant output, file path, branch, commit, investigation performed, and the single decision required.

Start now at Task 1 and continue through all of Phase A1 without further confirmation.
