# Alliance Auth Admin Toolkit

An Admin Toolkit for Alliance Auth to run management commands from UI.

## Features
- Run management commands like `auth check`, `auth showmigrations` directly from the web interface
- Run Discord sync commands if `aadiscordbot` is installed
- View command output and logs securely
- Use a dedicated operations page for runtime actions while keeping the dashboard as an overview
- Restrict access with superuser-only mode or optional settings-based allowlists
- Optionally restrict access by Alliance Auth EVE character IDs or names

## Installation

1. Install via pip:
```bash
pip install git+https://github.com/Thrainkrilleve/aa-admin-toolkit.git
```

2. Add `'aa_admin_toolkit'` to your `INSTALLED_APPS` in `local.py`.

3. Run migrations and collect static files:
```bash
python manage.py migrate
python manage.py collectstatic
```

4. Restart Celery workers and Gunicorn.

## Usage
By default, only `is_superuser` users can view and execute actions in the Admin Toolkit.
The toolkit always keeps `local.py` editable so you can define Alliance Auth access settings there.

Example `local.py` setup:

```python
INSTALLED_APPS += [
	"aa_admin_toolkit",
]

AA_ADMIN_TOOLKIT_ALLOW_VIEW_NON_SUPERUSERS = True
AA_ADMIN_TOOLKIT_ALLOW_EXECUTE_NON_SUPERUSERS = False

AA_ADMIN_TOOLKIT_VIEW_ALLOWED_USERS = ["viewer1", "viewer2"]
AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_USERS = ["operator1"]
```

## Settings

### Access control

- `AA_ADMIN_TOOLKIT_ALLOW_NON_SUPERUSERS`: Legacy master switch for non-superuser access.
- `AA_ADMIN_TOOLKIT_ALLOW_VIEW_NON_SUPERUSERS`: Allow non-superusers to view dashboards and logs.
- `AA_ADMIN_TOOLKIT_ALLOW_EXECUTE_NON_SUPERUSERS`: Allow non-superusers to run actions.

View scope allowlists:

- `AA_ADMIN_TOOLKIT_VIEW_ALLOWED_USERS`
- `AA_ADMIN_TOOLKIT_VIEW_ALLOWED_GROUPS`
- `AA_ADMIN_TOOLKIT_VIEW_ALLOWED_PERMISSIONS`
- `AA_ADMIN_TOOLKIT_VIEW_ALLOWED_EVE_CHARACTER_IDS`
- `AA_ADMIN_TOOLKIT_VIEW_ALLOWED_EVE_CHARACTER_NAMES`

Execute scope allowlists:

- `AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_USERS`
- `AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_GROUPS`
- `AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_PERMISSIONS`
- `AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_EVE_CHARACTER_IDS`
- `AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_EVE_CHARACTER_NAMES`

If view/execute allowlists are not set, they fall back to the legacy allowlists:

- `AA_ADMIN_TOOLKIT_ALLOWED_USERS`
- `AA_ADMIN_TOOLKIT_ALLOWED_GROUPS`
- `AA_ADMIN_TOOLKIT_ALLOWED_PERMISSIONS`
- `AA_ADMIN_TOOLKIT_ALLOWED_EVE_CHARACTER_IDS`
- `AA_ADMIN_TOOLKIT_ALLOWED_EVE_CHARACTER_NAMES`

### Docker and operations

- `AA_ADMIN_TOOLKIT_ENABLE_DOCKER`
- `AA_ADMIN_TOOLKIT_COMPOSE_COMMAND` (default: `docker compose`)
- `AA_ADMIN_TOOLKIT_COMPOSE_PROJECT_DIRECTORY`
- `AA_ADMIN_TOOLKIT_ALLOWED_DOCKER_SERVICES`
- `AA_ADMIN_TOOLKIT_ENABLE_FULL_STACK_RESTART`
- `AA_ADMIN_TOOLKIT_APP_SERVICE`
- `AA_ADMIN_TOOLKIT_APP_PYTHON_COMMAND`
- `AA_ADMIN_TOOLKIT_APP_MANAGEMENT_COMMAND`

### Database backup

- `AA_ADMIN_TOOLKIT_DB_SERVICE`
- `AA_ADMIN_TOOLKIT_DB_BACKUP_COMMAND`
- `AA_ADMIN_TOOLKIT_DB_BACKUP_OUTPUT_DIR`
- `AA_ADMIN_TOOLKIT_DB_BACKUP_FILENAME_PREFIX`

### Other

- `AA_ADMIN_TOOLKIT_ALLOWED_EDITABLE_FILES` (the toolkit always keeps `local.py` editable)
- `AA_ADMIN_TOOLKIT_ALLOWED_MANAGE_COMMANDS`
- `AA_ADMIN_TOOLKIT_MAINTENANCE_SENTINEL_PATH`
- `AA_ADMIN_TOOLKIT_AUDIT_WEBHOOK_URL`

### Example local.py access settings

Put your toolkit access rules in `local.py` so they stay alongside your Alliance Auth configuration:

```python
AA_ADMIN_TOOLKIT_ALLOW_VIEW_NON_SUPERUSERS = True
AA_ADMIN_TOOLKIT_ALLOW_EXECUTE_NON_SUPERUSERS = False

AA_ADMIN_TOOLKIT_VIEW_ALLOWED_GROUPS = ["Admin Toolkit Viewers"]
AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_GROUPS = ["Admin Toolkit Operators"]

AA_ADMIN_TOOLKIT_VIEW_ALLOWED_EVE_CHARACTER_IDS = [123456789]
AA_ADMIN_TOOLKIT_EXECUTE_ALLOWED_EVE_CHARACTER_IDS = [987654321]
```
