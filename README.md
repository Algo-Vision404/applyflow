# Applyflow

Upload a resume. Applyflow finds internships, early-career, and other eligible roles, reads each job description, tweaks the resume when the posting needs different emphasis, and fills public application forms.

It does **not** log into LinkedIn, Indeed, or Glassdoor, and it will not bypass CAPTCHAs. Applying is a dry-run unless you pass `--live`. Resume tweaks never invent skills or jobs that were not on the original file.

Your profile, resume, and application history stay on this computer under `~/.applyflow` (`%USERPROFILE%\.applyflow` on Windows). That folder is not part of this git repo.

## Install

```powershell
cd applyflow
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install playwright
python -m playwright install chromium
```

Launch the window:

```powershell
applyflow gui
```

or double-click `gui.bat` / `applyflow.cmd`.

## Main loop

```powershell
applyflow init
applyflow resume set .\resume.pdf
applyflow hunt
applyflow hunt --query python --career intern
applyflow hunt --live --yes
```

`hunt` will:

1. Search internships, new-grad / junior roles, and other non-senior jobs you can honestly target
2. Read each job description and score it against your resume
3. Reorder skills and add a targeted summary when the posting needs it (no fake experience)
4. Fill public application forms in a browser (you review and submit unless `--submit`)

Dry-run is the default. `--live` actually opens/fills forms.

## One job

```powershell
applyflow jobs show 12
applyflow resume tailor 12
applyflow apply 12            # dry-run: read JD, maybe tweak, show fill plan
applyflow apply 12 --live     # fill the form with the tailored resume
applyflow apply 12 --live --submit --yes
```

## Search only

```powershell
applyflow search "python intern" --location Remote
applyflow jobs list
```

Target internships only:

```powershell
applyflow profile set --career-level intern
```

`early` (default) = internships + new grad + junior + other non-senior eligible jobs. `any` includes senior roles.

## Form filling

Needs Playwright. Applyflow fills name, email, phone, school, LinkedIn, GitHub, resume upload, and cover letter on public career pages, including Greenhouse/Lever iframes. It stops on CAPTCHA or a login wall.

Hunt already checks public career boards at Google, Amazon, Apple, OpenAI, Anthropic, Palantir, SpaceX, Stripe, Airbnb, Databricks, and many other large US/global companies via their published job APIs (not LinkedIn/Indeed).

Add more:

```powershell
applyflow board add greenhouse cloudflare
applyflow board add lever palantir
applyflow board add ashby openai
```

## What it will not do

- LinkedIn Easy Apply, Indeed, Glassdoor, ZipRecruiter
- CAPTCHA solving or login bypass
- Claim skills that are not on your resume
- Apply without `--live`
- Commit or upload your resume, profile, or SMTP/API secrets

Use this on your own applications, and follow each site's terms of use.
