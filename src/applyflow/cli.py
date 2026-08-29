from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from applyflow import __version__
from applyflow.apply import apply_many, playwright_available
from applyflow.analyze import read_job
from applyflow.career import classify_resume
from applyflow.config import Board, load_profile, save_profile, update_profile
from applyflow.hunt import discover_jobs, prepare_and_apply
from applyflow.match import score_job
from applyflow.resume import parse_resume, save_resume
from applyflow.sources import search_jobs
from applyflow.store import (
    get_job,
    init_db,
    list_applications,
    list_jobs,
    upsert_job,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Search internships and early-career jobs. Run with no arguments to open the GUI.",
)
resume_app = typer.Typer(help="Upload and inspect your resume.")
profile_app = typer.Typer(help="Edit your applicant profile.")
board_app = typer.Typer(help="Watch company career boards (Greenhouse, Lever, Ashby).")
jobs_app = typer.Typer(help="Browse saved jobs.")

app.add_typer(resume_app, name="resume")
app.add_typer(profile_app, name="profile")
app.add_typer(board_app, name="board")
app.add_typer(jobs_app, name="jobs")

console = Console(legacy_windows=False)


def _ok(msg: str) -> None:
    console.print(f"[green]ok[/green]  {msg}")


def _warn(msg: str) -> None:
    console.print(f"[yellow]![/yellow]  {msg}")


def _err(msg: str) -> None:
    console.print(f"[red]x[/red]  {msg}")


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    init_db()
    if ctx.invoked_subcommand is None:
        from applyflow.gui import launch

        launch()


@app.command()
def gui() -> None:
    """Open the Applyflow window (upload resume, hunt, apply)."""
    from applyflow.gui import launch

    launch()


@app.command()
def version() -> None:
    """Show the CLI version."""
    console.print(__version__)


@app.command()
def init() -> None:
    """Interactive setup: name, contact details, and resume."""
    console.print(Panel("Applyflow setup", subtitle="stored in ~/.applyflow"))
    profile = load_profile()
    profile.first_name = Prompt.ask("First name", default=profile.first_name or "")
    profile.last_name = Prompt.ask("Last name", default=profile.last_name or "")
    profile.email = Prompt.ask("Email", default=profile.email or "")
    profile.phone = Prompt.ask("Phone", default=profile.phone or "")
    profile.location = Prompt.ask("Location (city or Remote)", default=profile.location or "Remote")
    profile.linkedin = Prompt.ask("LinkedIn URL", default=profile.linkedin or "")
    profile.github = Prompt.ask("GitHub URL", default=profile.github or "")
    profile.school = Prompt.ask("School / university", default=profile.school or "")
    profile.graduation_year = Prompt.ask("Graduation year", default=profile.graduation_year or "")
    profile.career_level = Prompt.ask(
        "Target roles: auto (from resume), intern, early, or any",
        default=profile.career_level or "auto",
    )
    profile.work_authorization = Prompt.ask(
        "Work authorization note (optional)",
        default=profile.work_authorization or "",
    )
    resume_path = Prompt.ask("Path to resume (PDF/DOCX)", default=profile.resume_path or "")
    if resume_path:
        dest = save_resume(Path(resume_path))
        profile.resume_path = str(dest)
        _ok(f"Resume stored at {dest}")
    extra = Prompt.ask(
        "Keywords to prioritize (comma-separated)",
        default=", ".join(profile.keywords) or "",
    )
    if extra.strip():
        profile.keywords = [k.strip() for k in extra.split(",") if k.strip()]
    save_profile(profile)
    _ok("Profile saved. Next: applyflow hunt")


@resume_app.command("set")
def resume_set(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    """Copy a resume into Applyflow and parse it."""
    dest = save_resume(path)
    parsed = parse_resume(dest)
    _ok(f"Saved resume: {dest}")
    console.print(f"Detected skills: {', '.join(parsed.skills[:20]) or '(none)'}")
    if parsed.timeline:
        console.print(f"Timeline: {parsed.timeline}")
    if parsed.emails:
        console.print(f"Emails on resume: {', '.join(parsed.emails)}")


@resume_app.command("tailor")
def resume_tailor(job_id: int = typer.Argument(..., help="Saved job id")) -> None:
    """Read a job description and write a tailored resume if the original needs tweaking."""
    profile = load_profile()
    job = get_job(job_id)
    if not job:
        _err(f"No job {job_id}")
        raise typer.Exit(1)
    try:
        resume = parse_resume()
    except FileNotFoundError as exc:
        _err(str(exc))
        raise typer.Exit(1) from exc
    reading = read_job(job, resume)
    from applyflow.tailor import tailor_resume

    result = tailor_resume(job, resume, profile, reading)
    console.print(Panel(reading.summary, title="Job description read"))
    if result.tweaked:
        job.tailored_path = str(result.path)
        from applyflow.store import upsert_job

        upsert_job(job)
        _ok(f"Tailored resume written to {result.path}")
    else:
        _ok(result.notes)
    if reading.missing:
        console.print(f"Not claimed (not on original resume): {', '.join(reading.missing[:8])}")


@resume_app.command("show")
def resume_show() -> None:
    """Print parsed resume details."""
    try:
        parsed = parse_resume()
    except FileNotFoundError as exc:
        _err(str(exc))
        raise typer.Exit(1) from exc
    console.print(Panel(parsed.path, title="Resume file"))
    console.print(f"[bold]Skills[/bold]: {', '.join(parsed.skills) or '(none detected)'}")
    console.print(f"[bold]Keywords[/bold]: {', '.join(parsed.keywords[:30])}")
    preview = parsed.text.strip()[:800] or "(no text extracted)"
    console.print(Panel(preview, title="Text preview"))
    console.print(f"[bold]Inferred target[/bold]: {classify_resume(parsed)}")
    if parsed.timeline:
        console.print(f"[bold]Timeline[/bold]: {parsed.timeline}")


@profile_app.command("show")
def profile_show() -> None:
    """Show the current profile."""
    profile = load_profile()
    table = Table(show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for key, value in profile.model_dump().items():
        if key in {"smtp_password", "usajobs_key", "adzuna_app_key", "cover_letter_template"}:
            if value:
                value = "********"
        table.add_row(key, str(value))
    console.print(table)


@profile_app.command("set")
def profile_set(
    first_name: str | None = typer.Option(None),
    last_name: str | None = typer.Option(None),
    email: str | None = typer.Option(None),
    phone: str | None = typer.Option(None),
    location: str | None = typer.Option(None),
    linkedin: str | None = typer.Option(None),
    website: str | None = typer.Option(None),
    github: str | None = typer.Option(None),
    school: str | None = typer.Option(None),
    graduation_year: str | None = typer.Option(None),
    career_level: str | None = typer.Option(None, help="intern | early | any"),
    min_score: int | None = typer.Option(None, help="Minimum match score 0-100"),
) -> None:
    """Update profile fields."""
    profile = update_profile(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        location=location,
        linkedin=linkedin,
        website=website,
        github=github,
        school=school,
        graduation_year=graduation_year,
        career_level=career_level,
        min_score=min_score,
    )
    _ok(f"Updated profile for {profile.full_name or profile.email or 'you'}")


@board_app.command("add")
def board_add(
    kind: str = typer.Argument(..., help="greenhouse | lever | ashby"),
    token: str = typer.Argument(..., help="Board token from the careers URL"),
    label: str = typer.Option("", help="Company display name"),
) -> None:
    """Watch a public company job board.

    Examples:
      applyflow board add greenhouse stripe
      applyflow board add lever netflix
      applyflow board add ashby openai
    """
    kind = kind.lower().strip()
    if kind not in {"greenhouse", "lever", "ashby"}:
        _err("kind must be greenhouse, lever, or ashby")
        raise typer.Exit(1)
    profile = load_profile()
    profile.boards = [b for b in profile.boards if not (b.kind == kind and b.token == token)]
    profile.boards.append(Board(kind=kind, token=token, label=label or token))
    save_profile(profile)
    _ok(f"Watching {kind} board '{token}'")


@board_app.command("list")
def board_list() -> None:
    """List watched company boards."""
    profile = load_profile()
    if not profile.boards:
        _warn("No boards yet. Example: applyflow board add greenhouse stripe")
        return
    table = Table(title="Company boards")
    table.add_column("Kind")
    table.add_column("Token")
    table.add_column("Label")
    for board in profile.boards:
        table.add_row(board.kind, board.token, board.label or board.token)
    console.print(table)


@app.command()
def hunt(
    query: str = typer.Option("", "--query", "-q", help="Optional extra keywords, e.g. python"),
    location: str = typer.Option("", "--location", "-l"),
    career: str | None = typer.Option(None, "--career", help="auto | intern | early | any"),
    limit: int = typer.Option(12, "--limit", "-n"),
    min_score: int | None = typer.Option(None, "--min-score"),
    live: bool = typer.Option(False, "--live", help="Fill/send applications (default dry-run)"),
    fill: bool = typer.Option(True, "--fill/--no-fill", help="Fill public application forms"),
    tweak: bool = typer.Option(True, "--tweak/--no-tweak", help="Tailor the resume when the JD needs it"),
    submit: bool = typer.Option(False, "--submit", help="Click Submit after filling"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    source: str = typer.Option("", "--source", "-s"),
) -> None:
    """Find internships and early-career jobs, read each JD, tweak the resume, fill forms."""
    console.print("[dim]Terminal hunt — this prints here. For the window, run: applyflow gui[/dim]")
    profile = load_profile()
    try:
        resume = parse_resume()
    except FileNotFoundError as exc:
        _err(str(exc))
        raise typer.Exit(1) from exc

    threshold = min_score if min_score is not None else profile.min_score
    sources = [s.strip() for s in source.split(",") if s.strip()] if source else None
    career_level = career or "auto"

    def progress(msg: str) -> None:
        console.print(f"[dim]{msg}[/dim]")

    ranked = discover_jobs(
        resume,
        profile,
        query=query,
        location=location,
        career_level=career_level,
        sources=sources,
        limit=limit * 2,
        on_progress=progress,
    )
    matched = [j for j in ranked if j.score >= threshold]
    jobs = (matched or ranked)[:limit]
    if ranked and not matched:
        _warn(f"No roles scored >={threshold}; showing closest matches.")

    if not jobs:
        _warn("No eligible roles found. Try --career intern, a broader --query, or lower --min-score.")
        return

    _print_jobs(jobs)
    if live and fill and not playwright_available():
        _warn("Form filling needs Playwright: pip install applyflow[browser] && playwright install chromium")
    if live and not yes and not Confirm.ask(f"Read JDs, tweak resumes, and apply to these {len(jobs)} roles?", default=False):
        raise typer.Exit()

    for job in jobs:
        result, reading = prepare_and_apply(
            job,
            resume,
            profile,
            live=live,
            fill=fill,
            submit=submit,
            tweak=tweak,
        )
        tweak_note = "tweaked" if job.tailored_path else "resume ok"
        _print_result(
            result.status,
            f"#{job.id} [{job.career_level or '-'}] {job.title} @ {job.company} ({tweak_note}) - {reading.summary[:120]}",
        )


@app.command()
def search(
    query: str = typer.Argument(..., help="Role keywords, e.g. 'python engineer'"),
    location: str = typer.Option("", "--location", "-l"),
    source: str = typer.Option(
        "",
        "--source",
        "-s",
        help="Comma-separated: remoteok,remotive,arbeitnow,jobicy,greenhouse,lever,ashby,usajobs,adzuna",
    ),
    limit: int = typer.Option(30, "--limit", "-n"),
    save: bool = typer.Option(True, "--save/--no-save"),
) -> None:
    """Search public job APIs and match them against your resume."""
    profile = load_profile()
    try:
        resume = parse_resume()
    except FileNotFoundError:
        resume = None
        _warn("No resume uploaded yet - scoring will be weak. Run: applyflow resume set <file>")

    sources = [s.strip() for s in source.split(",") if s.strip()] if source else None
    with console.status("Searching internships and eligible jobs..."):
        if resume:
            jobs = discover_jobs(
                resume,
                profile,
                query=query,
                location=location,
                career_level="auto",
                sources=sources,
                limit=limit,
            )
        else:
            jobs = search_jobs(
                query,
                profile,
                location=location,
                sources=sources,
                limit=limit * 3,
                career_level="auto",
                resume=resume,
            )
            jobs = jobs[:limit]

    if not jobs:
        _warn("No jobs found. Try a broader query, or add company boards.")
        return

    if save:
        for job in jobs:
            job.id = upsert_job(job)

    _print_jobs(jobs)
    _ok(f"{len(jobs)} eligible roles. Next: applyflow hunt   or   applyflow apply <id>")


@jobs_app.command("list")
def jobs_list(
    min_score: int = typer.Option(0, "--min-score"),
    limit: int = typer.Option(40, "--limit", "-n"),
) -> None:
    """List saved jobs, highest match first."""
    jobs = list_jobs(limit=limit, min_score=min_score)
    if not jobs:
        _warn("No saved jobs. Run applyflow search first.")
        return
    _print_jobs(jobs)


@jobs_app.command("show")
def jobs_show(job_id: int) -> None:
    """Show one saved job."""
    job = get_job(job_id)
    if not job:
        _err(f"No job {job_id}")
        raise typer.Exit(1)
    extra = ""
    try:
        resume = parse_resume()
        reading = read_job(job, resume)
        extra = f"\n\nRead: {reading.summary}\nMatch: {', '.join(reading.matching) or '-'}\nMissing (not invented): {', '.join(reading.missing) or '-'}"
    except FileNotFoundError:
        extra = ""
    console.print(
        Panel(
            f"[bold]{job.title}[/bold] at {job.company}\n"
            f"{job.location}  |  {job.source}  |  {job.career_level or '-'}  |  score {job.score}\n"
            f"{job.apply_target()}\n\n"
            f"{(job.description or '')[:1200]}{extra}",
            title=f"Job #{job.id}",
        )
    )


@app.command()
def apply(
    job_id: int = typer.Argument(..., help="Saved job id from search/jobs list"),
    live: bool = typer.Option(False, "--live", help="Actually send/open the application (default is dry-run)"),
    fill: bool = typer.Option(True, "--fill/--no-fill", help="Fill the public application form"),
    browser: bool = typer.Option(False, "--browser", help="Alias for --fill"),
    tweak: bool = typer.Option(True, "--tweak/--no-tweak"),
    submit: bool = typer.Option(False, "--submit", help="Click Submit after filling"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Read the JD, tweak the resume if needed, and fill the application form."""
    profile = load_profile()
    job = get_job(job_id)
    if not job:
        _err(f"No job {job_id}")
        raise typer.Exit(1)
    try:
        resume = parse_resume()
    except FileNotFoundError as exc:
        _err(str(exc))
        raise typer.Exit(1) from exc

    console.print(f"[bold]{job.title}[/bold] @ {job.company}")
    console.print(job.apply_target())
    if live and not yes and not Confirm.ask("Read JD, tweak resume, and apply?", default=False):
        raise typer.Exit()

    result, reading = prepare_and_apply(
        job,
        resume,
        profile,
        live=live,
        fill=fill or browser,
        submit=submit,
        tweak=tweak,
    )
    console.print(reading.summary)
    _print_result(result.status, f"{result.method}: {result.notes}")


@app.command("linkedin")
def linkedin_apply(
    url: str = typer.Argument(..., help="LinkedIn job URL, e.g. https://www.linkedin.com/jobs/view/123"),
    live: bool = typer.Option(True, "--live/--dry-run", help="Open Chromium and fill Easy Apply"),
    submit: bool = typer.Option(False, "--submit", help="Click Submit application after filling"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Fill LinkedIn Easy Apply in Chromium. Sign in in that window if asked."""
    from applyflow.apply import job_from_linkedin_url
    from applyflow.sources import is_linkedin_url

    if not is_linkedin_url(url):
        _err("That is not a LinkedIn job URL.")
        raise typer.Exit(1)
    profile = load_profile()
    try:
        resume = parse_resume()
    except FileNotFoundError as exc:
        _err(str(exc))
        raise typer.Exit(1) from exc
    job = job_from_linkedin_url(url)
    job.id = upsert_job(job)
    console.print(job.apply_target())
    if live and not yes and not Confirm.ask(
        "Open Chromium, sign in to LinkedIn if needed, and fill Easy Apply?",
        default=True,
    ):
        raise typer.Exit()
    result, reading = prepare_and_apply(
        job,
        resume,
        profile,
        live=live,
        fill=True,
        submit=submit,
        tweak=True,
        hold_for_review=True,
    )
    console.print(reading.summary)
    _print_result(result.status, f"{result.method}: {result.notes}")


@app.command()
def run(
    query: str = typer.Option(..., "--query", "-q", help="What to search for"),
    location: str = typer.Option("", "--location", "-l"),
    min_score: int | None = typer.Option(None, "--min-score"),
    limit: int = typer.Option(10, "--limit", "-n"),
    live: bool = typer.Option(False, "--live", help="Actually apply (default dry-run)"),
    browser: bool = typer.Option(False, "--browser"),
    submit: bool = typer.Option(False, "--submit"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    source: str = typer.Option("", "--source", "-s"),
) -> None:
    """Search, read JDs, tweak resumes, and apply (same as hunt with a required query)."""
    hunt(
        query=query,
        location=location,
        career=None,
        limit=limit,
        min_score=min_score,
        live=live,
        fill=True,
        tweak=True,
        submit=submit,
        yes=yes,
        source=source,
    )


@app.command()
def history(limit: int = typer.Option(30, "--limit", "-n")) -> None:
    """Show application history."""
    rows = list_applications(limit=limit)
    if not rows:
        _warn("No applications yet.")
        return
    table = Table(title="Application history")
    table.add_column("ID")
    table.add_column("When")
    table.add_column("Status")
    table.add_column("Method")
    table.add_column("Role")
    for row in rows:
        table.add_row(
            str(row.id),
            row.created_at.replace("T", " ")[:19],
            row.status,
            row.method,
            f"{row.title} @ {row.company}",
        )
    console.print(table)


@app.command()
def watch(
    query: str = typer.Option(..., "--query", "-q"),
    interval: int = typer.Option(1800, "--interval", help="Seconds between searches"),
    location: str = typer.Option("", "--location", "-l"),
    min_score: int | None = typer.Option(None, "--min-score"),
    live: bool = typer.Option(False, "--live"),
    browser: bool = typer.Option(False, "--browser"),
) -> None:
    """Keep searching and (optionally) applying when new matches appear."""
    import time

    profile = load_profile()
    threshold = min_score if min_score is not None else profile.min_score
    try:
        resume = parse_resume()
    except FileNotFoundError as exc:
        _err(str(exc))
        raise typer.Exit(1) from exc

    _ok(f"Watching for '{query}' every {interval}s (Ctrl+C to stop)")
    try:
        while True:
            jobs = search_jobs(query, profile, location=location, limit=50)
            fresh = []
            for job in jobs:
                job.score = score_job(job, resume, profile)
                job.id = upsert_job(job)
                if job.score >= threshold:
                    fresh.append(job)
            fresh.sort(key=lambda j: j.score, reverse=True)
            if fresh:
                console.print(f"[cyan]{len(fresh)} matches[/cyan] this round")
                apply_many(fresh[:8], profile, resume, live=live, browser=browser)
            else:
                console.print("No new strong matches.")
            time.sleep(interval)
    except KeyboardInterrupt:
        _ok("Stopped watching.")


def _print_jobs(jobs) -> None:
    table = Table(title="Roles")
    table.add_column("ID", style="cyan")
    table.add_column("Score")
    table.add_column("Level")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Location")
    table.add_column("Source")
    table.add_column("ATS")
    for job in jobs:
        table.add_row(
            str(job.id or "-"),
            str(job.score),
            job.career_level or "-",
            job.title[:44],
            job.company[:22],
            (job.location or "")[:20],
            job.source,
            job.ats or "-",
        )
    console.print(table)


def _print_result(status: str, detail: str) -> None:
    color = {
        "applied": "green",
        "submitted": "green",
        "opened": "cyan",
        "dry-run": "yellow",
        "queued": "yellow",
        "skipped": "magenta",
        "failed": "red",
    }.get(status, "white")
    console.print(f"[{color}]{status}[/{color}]  {detail}")


if __name__ == "__main__":
    app()
