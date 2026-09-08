# Development Setup

This page will contain the authoritative setup procedure after the Django project is initialized.

## Prerequisites

The expected local tools are:

- Git
- A team-approved Python version
- A code editor such as Visual Studio Code
- Access to the GitHub repository

## Initial Clone

```bash
git clone https://github.com/Vader941/ift401-team2-capstone.git
cd ift401-team2-capstone
```

## Planned Python Environment

The exact commands will be verified when `requirements.txt` is added. The intended workflow is to create a local virtual environment, activate it, install the pinned dependencies, and create a local `.env` file from `.env.example`.

Do not install project dependencies globally and do not commit the virtual environment.

## Setup Verification

Once the Django project exists, this guide will include exact commands for:

- Installing dependencies
- Applying migrations
- Creating optional development-only seed data
- Running the development server
- Running automated tests
- Verifying required environment variables

Do not invent or rely on undocumented setup steps. If a required step is missing, update this guide as part of the same pull request that introduces the requirement.
