# Workflow · Telegram Bot

A role-based Telegram bot for coordinating a content team, tracking completed work and preparing daily PDF reports.

**Stack:** Python · python-telegram-bot · SQLite · fpdf2

## Features

- Separate workflows for editors, admins, supervisors and managers.
- Checklists, issue escalation and scheduled reminders.
- SQLite persistence for work records.
- PDF reporting with fonts supporting Uzbek text.

## Local setup

Python 3.10+ and a Telegram bot token; test role IDs configured locally.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill BOT_TOKEN and the role IDs using your test bot.
python bot.py
```

## Validation commands

```bash
# No automated test suite was found in this snapshot.
# Validate role flows and report generation with a dedicated test bot.
```

These are reproducible commands, not a claim that the full application suite passed during portfolio preparation. See the workspace validation report for checks actually run.

## Structure

```text
bot.py        handlers and conversation flows
config.py     environment-based configuration
db.py         persistence
report.py     PDF reporting
assets/fonts/ report fonts
```

## Limitations and configuration

User databases, real reports, screenshots, logs and tokens are excluded. The bot sends messages and can publish content when configured, so use your own test bot and test chats for a walkthrough.

## Further documentation

[Original project documentation](docs/ORIGINAL_README.md) is preserved for implementation details and original context.
