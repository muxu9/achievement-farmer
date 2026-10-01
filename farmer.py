"""GitHub achievement runner. All credentials stay in gh's credential store."""
import json
import re
import subprocess
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, help="Grow Pair Extraordinaire and Pull Shark with resumable coauthored PRs.")
console = Console(markup=False)
GOLD = {"pair": 48, "shark": 1024, "both": 1024}


class FarmerError(Exception):
    pass


def api(path, method="GET", data=None):
    command = ["gh", "api", "--hostname", "github.com", path, "--method", method]
    if data is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                            capture_output=True, text=True)
    if result.returncode:
        raise FarmerError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def validate(config):
    for key in ("account", "coauthor"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", config[key]):
            raise FarmerError(f"Invalid {key} username.")
    if config["account"].lower() == config["coauthor"].lower():
        raise FarmerError("Choose a different account as the coauthor.")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", config["repo"]):
        raise FarmerError("Repository must be OWNER/NAME.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", config["campaign"]):
        raise FarmerError("Campaign must contain 1–60 letters, numbers, underscores or dashes.")
    for key in ("coauthor_name", "coauthor_email", "author_name", "author_email", "title"):
        if not config[key].strip() or any(c in config[key] for c in "\r\n<>"):
            raise FarmerError(f"Invalid {key}: use a single nonempty line without angle brackets.")
    for key in ("coauthor_email", "author_email"):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", config[key]):
            raise FarmerError(f"Invalid {key}.")


def load(path):
    try:
        config = json.loads(path.read_text())
        validate(config)
        return config
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FarmerError(f"Cannot read config {path}: {exc}. Run farmer init.") from exc


def identity(config):
    user = api("user")
    if user["login"].lower() != config["account"].lower():
        raise FarmerError(f"Active GitHub account is {user['login']}; expected {config['account']}. "
                          f"Run gh auth switch --user {config['account']} first.")
    return user


def summary(config, target=None):
    table = Table(title="Achievement farmer")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    for key in ("account", "repo", "coauthor", "coauthor_name", "coauthor_email", "campaign", "title"):
        table.add_row(key.replace("_", " "), str(config[key]))
    if target is not None:
        table.add_row("campaign target", f"{target:,} merged PRs")
    console.print(table)


def campaign_prs(config):
    result = []
    page = 1
    while True:
        batch = api(f"repos/{config['repo']}/pulls?state=all&per_page=100&page={page}")
        result.extend(pr for pr in batch if pr["head"]["ref"].startswith(f"farmer/{config['campaign']}/"))
        if len(batch) < 100:
            return result
        page += 1


def step(config, index, existing):
    repo = config["repo"]
    branch = f"farmer/{config['campaign']}/{index:04d}"
    pr = existing.get(branch)
    if pr and pr.get("merged_at"):
        return pr, False
    if pr and pr["state"] == "closed":
        raise FarmerError(f"PR #{pr['number']} was closed without merging. Reopen it to resume.")
    if not pr:
        metadata = api(f"repos/{repo}")
        base = metadata["default_branch"]
        parent = api(f"repos/{repo}/git/ref/heads/{base}")["object"]["sha"]
        # Reuse a branch after interruption between creating the commit and opening the PR.
        refs = api(f"repos/{repo}/git/matching-refs/heads/{branch}")
        exact = next((ref for ref in refs if ref["ref"] == f"refs/heads/{branch}"), None)
        if exact is None:
            path = f"runs/{config['campaign']}/{index:04d}.json"
            payload = json.dumps({"campaign": config["campaign"], "step": index,
                                  "author": config["account"], "coauthor": config["coauthor"]}, indent=2) + "\n"
            tree = api(f"repos/{repo}/git/commits/{parent}")["tree"]["sha"]
            new_tree = api(f"repos/{repo}/git/trees", "POST", {
                "base_tree": tree, "tree": [{"path": path, "mode": "100644", "type": "blob", "content": payload}]})
            message = f"{config['title']} {index:04d}\n\nCo-authored-by: {config['coauthor_name']} <{config['coauthor_email']}>"
            commit = api(f"repos/{repo}/git/commits", "POST", {
                "message": message, "tree": new_tree["sha"], "parents": [parent],
                "author": {"name": config["author_name"], "email": config["author_email"]}})
            api(f"repos/{repo}/git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        pr = api(f"repos/{repo}/pulls", "POST", {
            "title": f"{config['title']} {index:04d}", "head": branch, "base": base,
            "body": config.get("body", "Update generated record.")})
    identity(config)
    detail = api(f"repos/{repo}/pulls/{pr['number']}")
    merged = api(f"repos/{repo}/pulls/{pr['number']}/merge", "PUT", {
        "merge_method": "merge", "sha": detail["head"]["sha"]})
    if not merged.get("merged"):
        raise FarmerError(f"PR #{pr['number']} did not merge: {merged.get('message')}")
    return pr, True


@app.command()
def init(
    account: str = typer.Option(..., help="Account that opens the PRs."),
    coauthor: str = typer.Option(..., help="GitHub username credited on each commit."),
    repo: str = typer.Option(..., help="Existing target repository, OWNER/NAME."),
    coauthor_name: str = typer.Option("", help="Override the displayed coauthor name."),
    coauthor_email: str = typer.Option("", help="Override with an email associated with the coauthor account."),
    campaign: str = typer.Option("gold", help="Stable ID used to resume this campaign."),
    title: str = typer.Option("Pair practice", help="Commit and PR title prefix."),
    config: Path = typer.Option(Path("farmer.json")),
    force: bool = typer.Option(False, help="Replace an existing configuration."),
):
    """Configure account, project and displayed coauthor (no GitHub writes)."""
    if config.exists() and not force:
        raise FarmerError(f"{config} already exists. Use --force to replace it.")
    settings = dict(account=account, repo=repo, coauthor=coauthor, campaign=campaign, title=title,
                    coauthor_name=coauthor_name or coauthor, coauthor_email=coauthor_email or "pending@example.com",
                    author_name=account, author_email="pending@example.com")
    validate(settings)
    author = identity(settings)
    partner = api(f"users/{coauthor}")
    settings.update(author_name=author.get("name") or author["login"],
                    author_email=f"{author['id']}+{author['login']}@users.noreply.github.com",
                    coauthor_name=coauthor_name or partner.get("name") or partner["login"],
                    coauthor_email=coauthor_email or f"{partner['id']}+{partner['login']}@users.noreply.github.com")
    validate(settings)
    config.write_text(json.dumps(settings, indent=2) + "\n")
    summary(settings)
    console.print(f"Saved {config}. Preview with: farmer run --dry-run")


@app.command()
def doctor(config: Path = typer.Option(Path("farmer.json"))):
    """Check authentication, coauthor, repository and merge permissions."""
    settings = load(config)
    identity(settings)
    api(f"users/{settings['coauthor']}")
    metadata = api(f"repos/{settings['repo']}")
    if metadata.get("archived") or not metadata.get("permissions", {}).get("push"):
        raise FarmerError("Target repository must be writable and not archived.")
    if not metadata.get("allow_merge_commit", True):
        raise FarmerError("Enable merge commits in the target repository settings.")
    api(f"repos/{settings['repo']}/git/ref/heads/{metadata['default_branch']}")
    summary(settings)
    console.print("Ready. Branch protection and rulesets may still require reviews or checks.")


@app.command()
def status(config: Path = typer.Option(Path("farmer.json"))):
    """Show campaign progress, independently of GitHub badge processing."""
    settings = load(config)
    identity(settings)
    prs = campaign_prs(settings)
    merged = sum(bool(pr.get("merged_at")) for pr in prs)
    summary(settings)
    console.print(f"Campaign: {merged:,} merged / {len(prs):,} opened")
    console.print(f"Pair gold target: {min(merged, 48)}/48 · Pull Shark gold target: {min(merged, 1024)}/1024")
    console.print("Counts cover this campaign only; badge awards and prior contributions are tracked by GitHub.")


@app.command()
def run(
    goal: str = typer.Option("both", help="Gold target: pair, shark, or both."),
    count: int | None = typer.Option(None, min=1, help="Total campaign target, including already merged PRs."),
    limit: int = typer.Option(3, min=1, help="Maximum new merges in this invocation."),
    delay: float = typer.Option(5.0, min=1.0, help="Seconds between merges; increase if GitHub rate limits you."),
    dry_run: bool = typer.Option(False, help="Preview offline without any GitHub requests."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the interactive confirmation."),
    config: Path = typer.Option(Path("farmer.json")),
):
    """Open and merge coauthored PRs. Rerun to resume after interruption."""
    settings = load(config)
    if goal not in GOLD:
        raise FarmerError("Goal must be pair, shark, or both.")
    target = count or GOLD[goal]
    summary(settings, target)
    console.print(f"At most {limit:,} new merges; {delay:g}s between merges.")
    if dry_run:
        console.print(f"DRY RUN · {settings['title']} 0001\n\n"
                      f"Co-authored-by: {settings['coauthor_name']} <{settings['coauthor_email']}>")
        return
    doctor(config)
    if not yes:
        typer.confirm("Create and merge PRs with these settings?", abort=True)
    existing = {pr["head"]["ref"]: pr for pr in campaign_prs(settings)}
    made = 0
    for index in range(1, target + 1):
        branch = f"farmer/{settings['campaign']}/{index:04d}"
        if existing.get(branch, {}).get("merged_at"):
            continue
        if made >= limit:
            break
        identity(settings)
        if made:
            time.sleep(delay)
        pr, created = step(settings, index, existing)
        made += int(created)
        console.print(f"Merged {index:04d}/{target:04d} · {pr['html_url']}")
    console.print(f"Done: {made} new merged PRs. Rerun the same command to continue.")


def main():
    try:
        app()
    except (FarmerError, FileNotFoundError) as exc:
        console.print(f"Error: {exc}", style="red")
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        console.print("Stopped. Rerun the same command to resume.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
