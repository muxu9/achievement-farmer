# achievment-farmer

A small CLI for practicing coauthored GitHub pull requests, with configurable project and coauthor credit, progress tables, offline previews, and resumable runs.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [GitHub CLI](https://cli.github.com/), then:

```bash
gh auth login
git clone https://github.com/muxu9/achievment-farmer.git
cd achievment-farmer
uv sync --locked
uv run farmer --help
```

The tool uses `gh` authentication. Tokens are never stored in its configuration. Every write checks the authenticated account against your configured account. To switch accounts explicitly, use `gh auth switch --user YOUR_ACCOUNT`.

## Choose who and where

```bash
uv run farmer init \
  --account YOUR_ACCOUNT \
  --repo YOUR_ACCOUNT/YOUR_PROJECT \
  --coauthor PARTNER_USERNAME \
  --campaign my-project \
  --title "Pair practice"
```

Your project must already exist, have an initial commit, and allow merge commits. You need permission to open branches and merge PRs. You can create a separate public practice repository with `gh repo create OWNER/PROJECT --public --add-readme`. Public repositories make the project attribution visible on GitHub; private contribution visibility depends on profile settings.

`--coauthor-name` customizes the name in the commit trailer. `--coauthor-email` sets the email used for GitHub account attribution. The default is `ID+LOGIN@users.noreply.github.com`, resolved from GitHub. You can edit the generated, gitignored `farmer.json`, including `author_name` and `author_email`. Use an email associated with the corresponding account. For older accounts, use their actual verified commit address if the default noreply address does not resolve.

GitHub decides which users and projects appear in achievement details. A display name alone cannot select another GitHub account: the commit email establishes that association. Coauthor metadata is an attribution claim, not proof that the named person participated. Choose a new campaign when changing project or coauthor so the progress count reflects one configuration.

## Preview, check, run

```bash
uv run farmer run --dry-run
uv run farmer doctor
uv run farmer run --count 3 --limit 3
uv run farmer status
```

The default run performs **at most three new merges**. `--count` sets the total campaign target, including existing merged PRs. Running the same command again resumes without duplicating merged PRs. Open PRs and branches left by interruption are reused. A closed, unmerged PR stops the run so you can inspect and reopen it. Ctrl+C stops cleanly. GitHub errors stop the run; wait and resume after a rate limit rather than retrying in a tight loop.

Each step adds `runs/CAMPAIGN/NNNN.json` on its own branch, creates a commit with a `Co-authored-by` trailer, opens a PR as the configured account, and merges it with a merge commit to preserve the original attribution. Branches remain in the repository for inspection. Branch protection and rulesets are respected; required checks or reviews can block a merge. Run only one process for a given campaign at a time.

## Gold targets

| Achievement | Default | Bronze | Silver | Gold |
| --- | ---: | ---: | ---: | ---: |
| Pair Extraordinaire | 1 | 10 | 24 | 48 |
| Pull Shark | 2 | 16 | 128 | 1,024 |

These are [community documented thresholds](https://github.com/Schweinepriester/github-profile-achievements#tiers), not a GitHub guarantee. Pair Extraordinaire requires coauthored commits in merged PRs; Pull Shark counts PRs you opened that were merged. All PRs made by this tool include coauthor attribution, so a campaign can work toward both.

```bash
# Pair gold: up to 48 total campaign merges
uv run farmer run --goal pair --limit 48

# Both gold targets: up to 1,024 total campaign merges
uv run farmer run --goal both --limit 1024 --delay 10
```

Runs are sequential and spaced by at least one second (default five). Large runs may encounter GitHub secondary limits and take several sessions. `--yes` skips the CLI confirmation for unattended use. Campaign status counts merged PRs in this project; it does not read badge state or subtract contributions from other projects. Badge processing can be delayed; inspect your GitHub achievement details to verify awards.

The initial live smoke test is limited to **muxu9**. No run on **Eve-146T** is authorized as part of that test.

## Development

```bash
uv run python -m unittest discover -s tests -v
```

See [GitHub's coauthor documentation](https://docs.github.com/en/pull-requests/how-tos/commit-changes/creating-a-commit-with-multiple-authors) for trailer and email requirements.
