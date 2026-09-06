# Project Prompt: Smart Expense Tracker (Django + Telegram Bot)

Build a Django-based personal expense tracker with an integrated Telegram bot, sharing the same backend/database, with a 3D-styled web UI.

## 1. Project Setup
- Create a Python virtual environment named `.venv`, activate it, install Django inside it
- Create a Django project named `smart`
- Create a Django app named `tracker`, registered in settings
- Create a `.env` file for sensitive data (`SECRET_KEY`, `DEBUG`, `TELEGRAM_BOT_TOKEN`, DB credentials), loaded via `python-decouple` or `django-environ`
- Create a `.gitignore` excluding `.env`, `.venv/`, `db.sqlite3`, `__pycache__/`, `*.pyc`, `media/`, `staticfiles/`

## 2. Architecture
- Telegram bot and website share the same backend — actions on one reflect instantly on the other
- Bot runs as a separate long-running process (polling), using Django ORM directly or via a REST API
- `/link <code>` flow to map a Telegram chat ID to a Django user account (code generated from the Profile page)
- Short-lived session state per chat (via a `TelegramSession` model or Django cache) for multi-step commands like delete confirmation
- One shared filtering utility function (returns `{date, month, year, category}`) reused across `/show`, `/total`, and `/pdf` parsing
- One shared PDF-generation function used by both the bot and the website
- Category creation deduplicated per user, case-insensitive/normalized (e.g. "Food" = "food")
- Invalid/ambiguous command input handled gracefully with helpful error replies instead of crashing
- Scheduled tasks (monthly budget prompt, end-of-month report, budget threshold checks) handled via Celery + Celery Beat (Redis broker) for robustness, or `django-crontab` / an asyncio loop in the bot process for a lighter personal-project setup

## 3. Data Models
- `Category` — name, user (FK)
- `Expense` — category (FK), type/description, amount, date, created_via (`bot`/`web`)
- `Budget` — user (FK), amount, month, year, notified_80 (bool), notified_100 (bool)
- `TelegramSession` — chat_id, last_shown_list (JSON), pending_action, pending_data
- `TelegramLink` — user (FK), chat_id, link_code, linked_at

## 4. Website Pages
- **Dashboard** — charts for monthly spending trend and category-wise breakdown (Chart.js / Recharts)
- **Add Expense** — form to add a new expense
- **All Expenses** — filterable/sortable table (by date, month, category)
- **Profile** — Telegram link status, link code, basic user info
- **3D UI** — clarify whether "3D" means true 3D elements (Three.js — e.g. rotating dashboard visuals, animated category icons) or a modern layered/glassmorphic-neumorphic visual style (CSS-based, far less overhead). Recommend the latter unless a specific 3D visualization is wanted.

## 5. Telegram Bot Commands

**Help**
- `/help` — list all available commands

**Add**
- `/add <category> <type> <price>` — e.g. `/add food pizza 50`, `/add travel auto 10`

**Show**
- `/show` — show all expenses
- `/show <month>` — e.g. `/show september` — expenses for that month
- `/show <date>` — e.g. `/show 26 september 2026` — detailed expenses for that day, in order

**Delete**
- `/delete <number>` — delete the item at that position from the last shown list; bot asks yes/no confirmation before deleting

**Totals**
- `/total` — total of all expenses
- `/total <month>` — total for that month
- `/total <date>` — total for that specific date
- `/total <category>` — total for that category
- `/total <month> <category>` — total for that category within that month

**Category**
- `/create <category>` — create a new custom category (e.g. food, travel, clothes)

**PDF Export**
- `/pdf` — PDF of all expenses
- `/pdf <month>` — PDF for that month
- `/pdf <category>` — PDF for that category
- `/pdf <month> <category>` — PDF for that category within that month
- `/pdf <date>` — PDF for that specific date
- `/pdf <date> <category>` — PDF for that category on that date
- Bot sends the PDF directly in chat as a downloadable file; same reports downloadable from the website

**Budget**
- `/budget <amount>` — set a spending limit for the current month
- `/budget <month> <amount>` — set a limit for a specific month
- `/budget` — show current month's budget, spent, and remaining
- `/budget remaining` — show only remaining budget
- `/budget add <amount>` — add more amount to the current budget
- `/budget remove <amount>` — subtract amount from the current budget
- Auto-prompt on the 1st of each month asking the user to set that month's budget — a plain numeric reply (e.g. `4000`) is saved automatically as that month's budget
- Notification when spending reaches/crosses the set limit
- Auto-generated report on the last day of the month: total budget, total spent, remaining budget, category-wise spending list

## 6. Suggested Additions (recommended, confirm before building)
- **PDF library**: WeasyPrint (styled HTML/CSS templates, reuses website styling) vs ReportLab (more precise table/layout control, lighter weight) — recommend WeasyPrint if visual consistency with the website matters, ReportLab if simplicity/performance matters more
- **Two-tier budget alerts**: notify at 80% and 100% of budget instead of only at 100%, using the `notified_80`/`notified_100` flags to avoid repeat spam
- **Budget auto-create**: if `/budget add` or `/budget remove` is sent with no budget set yet for the month, auto-create one starting at 0 (or prompt for an initial amount first)
- **`/edit <number>`** command to edit an existing entry instead of delete + re-add
- **Daily/weekly summary** auto-sent by the bot, reusing the same scheduler as the budget prompts/reports
- **Build in phases** rather than all at once, given the scope: (1) core models + CRUD, (2) website pages, (3) bot commands, (4) PDF export, (5) budget + scheduling, (6) 3D UI polish — each phase testable before moving to the next

---
*This prompt reflects all requirements gathered so far. Add further requirements before development begins, or confirm this is final to start the build.*
