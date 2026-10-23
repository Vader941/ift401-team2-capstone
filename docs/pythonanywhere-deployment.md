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

## Background market worker

The market worker attempts price updates for all active stocks, then
evaluates customers' pending orders. It waits 60 seconds after each cycle.
Market hours use America/New_York, regardless of the server's UTC timezone.

Browsing and trading use stored prices and do not generate price changes.
Opening the dashboard does not execute pending orders.

### Local use

Run one cycle:

```bash
python manage.py run_market --once
```

Run continuously in a separate terminal:

```bash
python manage.py run_market
```

Stop the local worker with Ctrl+C. Keep the Django development server
running in its own terminal.

### PythonAnywhere setup

After this feature has been merged and deployed, create one always-on
task with this command:

```bash
/home/ablesoftwareweb/.virtualenvs/capstone/bin/python -u /home/ablesoftwareweb/ift401-team2-capstone/manage.py run_market
```

The application settings load the project's .env file. The task must
connect to the same database as the web application.

Use the task log to verify startup and cycle results. During market
hours, it reports stocks checked, prices changed, portfolios processed,
and portfolio errors. Outside market hours, it reports no changes.

Run only one market worker per database. Do not also schedule the
price-only command or leave another worker running in a console.

### Deployment and restart

The existing deployment workflow reloads the web application. It does
not restart the separate always-on worker.

For deployments after the worker has been activated:
1. Pause the always-on task and confirm that it has stopped.
2. Deploy through the normal merge workflow and wait for success.
3. Unpause the task so it starts with the deployed code.
4. Check the task log for successful startup and cycle results.

### Failure behavior

A price-update failure stops that cycle before pending-order processing.
Earlier successful price updates remain committed.

Each customer's pending orders are processed in a separate transaction.
A customer-processing failure is logged and rolled back; other customers
can still be processed.

The continuous worker retries after 60 seconds. It does not reconstruct
missed price history after downtime. Pending orders are evaluated at
stored prices when processing resumes during market hours.

Price history records actual changes only. An unchanged price does not
create a history row.