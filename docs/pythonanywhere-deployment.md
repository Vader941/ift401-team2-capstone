# PythonAnywhere Deployment

## Environment

- Python 3.12
- Django dependencies from requirements.txt
- MySQL driver from requirements-production.txt
- Virtual environment: /home/ablesoftwareweb/.virtualenvs/capstone
- Project: /home/ablesoftwareweb/ift401-team2-capstone
- Site: https://ablesoftwareweb.pythonanywhere.com

## Private configuration

The server's ignored .env file defines:

- DJANGO_SECRET_KEY
- DJANGO_DEBUG=False
- DJANGO_ALLOWED_HOSTS=ablesoftwareweb.pythonanywhere.com
- DJANGO_HOSTED=True
- DB_ENGINE=mysql
- DB_NAME
- DB_USER
- DB_PASSWORD
- DB_HOST

Passwords and secret keys must not be committed or copied into
documentation. Local development defaults to SQLite when DB_ENGINE
is not set to mysql.

DJANGO_HOSTED enables HTTPS redirects and secure session/CSRF cookies.
The forwarded HTTPS header setting is intended for PythonAnywhere's
trusted proxy.

## Web configuration

Create a manually configured Python 3.12 web app.

Virtualenv:
`/home/ablesoftwareweb/.virtualenvs/capstone`

Static mapping:
`/static/` → `/home/ablesoftwareweb/ift401-team2-capstone/staticfiles`

The PythonAnywhere WSGI configuration adds the project directory to
sys.path, sets DJANGO_SETTINGS_MODULE to stock_simulator.settings,
and initializes Django through get_wsgi_application().

## Updating the deployment

After the deployment PR merges, the hosted checkout will track main.

In a PythonAnywhere Bash console:

    cd ~/ift401-team2-capstone
    source ~/.virtualenvs/capstone/bin/activate
    git status
    git pull --ff-only origin main
    pip install -r requirements-production.txt
    python manage.py check
    python manage.py migrate
    python manage.py collectstatic --noinput

Stop if the working tree has unexpected changes or any command fails.
Reload the web app from PythonAnywhere's Web tab after successful updates.

Review migrations before applying them. Back up the hosted database
before updates that could change or remove existing data.

## Verification

Initial hosted verification passed:

- Homepage and styling load.
- Admin login works.
- Customer registration succeeds.
- Registration creates a $25,000 Portfolio and opening ledger entry.
- Django is configured to use the hosted MySQL database.

Buy functionality and final interface integration require their
respective PRs to merge and be deployed. Concurrent cash/buy operations
still require verification on MySQL.

## Current staging status

The initial deployment runs feature/pythonanywhere-deployment.
Switch the hosted checkout to main after this PR merges.