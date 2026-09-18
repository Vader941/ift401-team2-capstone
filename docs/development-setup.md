# Development Setup

## Prerequisites

Install the following tools:

- Git
- Python 3.12
- A code editor such as Visual Studio Code
- Access to the GitHub repository

## Clone the Repository

```bash
git clone https://github.com/Vader941/ift401-team2-capstone.git
cd ift401-team2-capstone
```

## Create the Python Environment

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it in Git Bash on Windows:

```bash
source .venv/Scripts/activate
```

Activate it in PowerShell on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

## Install Dependencies

With the virtual environment active, run:

```bash
python -m pip install -r requirements.txt
```

## Configure Local Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Replace the placeholder `DJANGO_SECRET_KEY` value in `.env` with a private local development key. Never commit `.env` or share its secret value.

A key can be generated with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Initialize the Local Database

Apply the included database migrations:

```bash
python manage.py migrate
```

The local SQLite database is generated for each developer and is not committed.

## Run the Application

Start the development server:

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in a browser.

Stop the server with `Ctrl+C`.

## Run Automated Checks

Run Django's configuration checks:

```bash
python manage.py check
```

Run the automated test suite:

```bash
python manage.py test
```

Confirm that model changes include migrations:

```bash
python manage.py makemigrations --check
```

All three commands should pass before opening a pull request.
