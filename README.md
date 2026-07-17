# Alliance Auth Admin Toolkit

An Admin Toolkit for Alliance Auth to run management commands from UI.

## Features
- Run management commands like `auth check`, `auth showmigrations` directly from the web interface
- Run Discord sync commands if `aadiscordbot` is installed
- View command output and logs securely

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
Only users with `is_superuser` privileges can access the Admin Toolkit via the Alliance Auth sidebar.
