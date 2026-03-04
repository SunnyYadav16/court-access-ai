# Git Push Workflow — CourtAccess AI

This guide documents the exact steps to take before every git push to ensure a clean,
lint-free, security-clean commit.

---

## Prerequisites

Install dev dependencies once:

```bash
# Create and activate virtual environment (if not already done)
python3 -m venv .venv
source .venv/bin/activate          # Mac/Linux
# .venv\Scripts\activate           # Windows

# Install dev tools
pip install -r requirements-dev.txt

# Install pre-commit hooks (run once per clone)
pre-commit install
```

---

## Step 1 — Set Up Your `.env`

Copy the example and fill in real values. **Never commit `.env`.**

```bash
cp .env.example .env
```

Generate required secrets:

```bash
# Airflow Fernet key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Airflow / App secret key
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste each value into the corresponding variable in `.env`.

---

## Step 2 — Lint with Ruff

```bash
# Check for lint errors
ruff check .

# Auto-fix everything fixable
ruff check --fix .

# Format all Python files
ruff format .
```

After running `--fix` and `format`, run `ruff check .` once more to confirm **0 errors** remain.

### Common manual fixes required

| Error code | Cause | Fix |
|---|---|---|
| `UP042` | `class Foo(str, Enum)` | Change to `class Foo(StrEnum)` and `from enum import StrEnum` |
| `SIM105` | `try/except/pass` | Replace with `with contextlib.suppress(ExcType): ...` |
| `B904` | `raise X` inside `except` | Use `raise X from exc` |
| `F841` | Unused variable | Remove the assignment |
| `S105`/`S106` | `"bearer"` or dev defaults flagged as passwords | Add `# noqa: S105` — these are intentional |
| `B008` | `File()`, `Query()`, `Depends()` in function defaults | Add `# noqa: B008` — FastAPI requires this pattern |
| `E402` | Import not at top of file | Move import to top, or add `# noqa: E402` with explanation |
| `RUF001` | EN-dash `–` in a string | Replace with ASCII hyphen `-` |

---

## Step 3 — Security Scan with Bandit

```bash
bandit -r courtaccess/ api/ dags/ db/ -ll
```

`-ll` = only report medium/high severity. Review any findings before pushing.

---

## Step 4 — Run Tests

```bash
pytest --tb=short
```

All tests must pass before committing.

---

## Step 5 — Run Pre-commit (catches everything automatically)

```bash
pre-commit run --all-files
```

This runs Ruff, Bandit, and hygiene checks (trailing whitespace, end-of-file newlines, etc.) on every file at once.

If any hook fails, fix the issues and re-run until all hooks pass.

---

## Step 6 — Review Git Status

```bash
git status --short
```

**Expected:**
- New files show as `??` (untracked, to be staged)
- Modified files show as `M`
- Deleted files show as `D`

**Must NOT appear:**
- `forms/` — DVC-tracked PDFs, excluded by `.gitignore`
- `dvc_storage/` — DVC local remote blobs
- `courtaccess/data/form_catalog.json` — DVC-tracked catalog
- `models/*.dvc` tracked data files
- `.env` — real secrets

If any of the above appear, check your `.gitignore`.

---

## Step 7 — Stage and Commit

```bash
# Stage all changes (new files + modifications + deletions)
git add -A

# Verify what's staged
git diff --cached --name-only

# Commit with a descriptive message
git commit -m "feat: <what you changed>"
```

Conventional commit prefixes:

| Prefix | Use when |
|---|---|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `chore:` | Tooling, config, dependencies |
| `refactor:` | Code restructure with no behaviour change |
| `test:` | Adding or updating tests |
| `docs:` | Documentation only |

---

## Step 8 — Push

```bash
git push origin <your-branch>
# or for first push:
git push -u origin main
```

---

## GitHub Actions (automatic on push)

Three CI checks run automatically:

| Workflow | What it checks |
|---|---|
| `lint.yml` | `ruff check` + `ruff format --check` |
| `security.yml` | Bandit + Gitleaks (secret scanning) |
| `dependencies.yml` | Dependency audit |

If any of these fail on CI, fix locally using the steps above and push again.

---

## DVC Data (model weights & catalog)

These are **not** committed to git. To share data changes with teammates:

```bash
# After a DAG run updates the catalog or model weights:
dvc push      # push data blobs to GCS remote (gs://courtaccess-models/dvc-cache)

# Teammates pull the latest data:
dvc pull
```
