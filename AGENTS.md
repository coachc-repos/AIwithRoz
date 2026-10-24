# Agent and contributor instructions

LineDrive is a Python project. The active web app is `scriptcraft-app-v2/`. Baseball scrapers live under `scraper/` and `batch_scrapers/`. There is no separate lint, type-check, or build step.

## Run the tests

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest
```

CI runs that same command on Python 3.12 for every push and every pull request. The GitHub check is named **Tests / pytest**. Green means these tests passed. Red means do not merge.

`requirements-dev.txt` only installs pytest, Flask, and requests. It does not install Azure, HeyGen, Gemini, Grok, Pexels, or Selenium, and it does not need API keys.

## Test-first rule for bug fixes

For every bug fix:

1. Write a test that reproduces the bug. Run it and confirm it fails for the right reason.
2. Make the fix. Do not change behavior beyond the bug.
3. Run the new test again and confirm it passes.
4. Run the full suite (`python -m pytest`) and confirm it stays green. The pull request's **Tests / pytest** check must be green before merge.

Put new tests in `tests/`. Prefer the real function or route. Use a fake key or an in-memory fixture when the code would otherwise call a paid API. Do not add GitHub Actions secrets.

On a bug-fix pull request, check **Added a failing test that reproduces the bug** in the pull request template.

Changes that are not bug fixes (docs, CI, new features) do not need a failing-test-first step. They still need the suite to stay green when they touch code.

## What the suite covers

The tests exercise code that does not need a network or a desktop app:

- Script title extraction, filesystem-safe names, B-roll tables, and animation suggestions in `scriptcraft-app-v2/web_gui.py`
- The ScriptCraft home page, agent-mode API, and auth gate, using Flask's test client and a fake token
- HeyGen spoken-text cleanup and chapter splitting in `scriptcraft-app-v2/console_ui/text_processing.py` (curl text is built locally; nothing is sent to HeyGen)
- Teleprompter text, tool-link descriptions, and demo-step cleanup
- DaVinci project-name sanitizing and media-file collection (no Resolve install)
- Tournament records, distance filtering, and Perfect Game search filters

## What CI does not test

These need API keys, a browser, or software that is not on the GitHub runner. Do not point CI at them, and do not commit keys to make them pass:

- Azure AI Foundry agents and blob storage
- HeyGen, Gemini, Grok, Pexels, and X/Twitter live calls
- Perfect Game / Little League / USA Baseball scraping
- DaVinci Resolve and Fusion timeline builds

Skip or mock those paths. Say so in the pull request notes.
