# OI Reversal Scanner
## System Architecture

Version: 1.0

Author: Sagarkumar
Architecture: Production
Database: Supabase PostgreSQL
Backend: Python
Deployment: Ubuntu VPS

---

# Project Goal

Build a professional market scanner capable of running 24/7 on Ubuntu VPS.

The scanner will:

• Download TradingView market data
• Detect OI Reversal Zones
• Store all market data
• Store all detected zones
• Serve data to a secure web dashboard
• Later connect to MT5, Telegram and AI services

The scanner must be scalable, secure and maintainable.

---

# High Level Architecture

                TradingView
                     │
             tvDatafeed Library
                     │
                     ▼
              Scanner Service
                     │
                     ▼
            Repository Layer
                     │
                     ▼
          PostgreSQL (Supabase)
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
      FastAPI API          Background Jobs
          │
          ▼
     HTML Dashboard

---

# Folder Structure

ForVPS/

│
├── app/
│
│   ├── api/
│   │
│   ├── dashboard/
│   │
│   ├── database/
│   │     client.py
│   │     repository.py
│   │     models.py
│   │     health.py
│   │
│   ├── scanner/
│   │     oi_reversal_scanner.py
│   │     zone_engine.py
│   │
│   ├── services/
│   │
│   ├── utils/
│   │
│   ├── config.py
│   │
│   └── __init__.py
│
├── tests/
│
├── logs/
│
├── .venv/
│
├── .env
│
├── requirements.txt
│
├── README.md
│
└── ARCHITECTURE.md

---

# Module Responsibilities

config.py

Responsible for

• Environment Variables
• Global Settings
• Secrets
• API Keys

No business logic.

---

database/

Responsible for

• PostgreSQL Connection
• Transactions
• Queries
• Bulk Insert
• Reset Database
• Repository Pattern

No scanner logic.

---

scanner/

Responsible for

• Fetch TradingView Data
• Normalize Data
• Detect Zones
• Call Repository

No SQL.

---

api/

Responsible for

• REST API
• Authentication
• Dashboard Data
• Future Mobile App

No Scanner Logic.

---

dashboard/

Responsible only for

• HTML
• CSS
• JavaScript

Never accesses PostgreSQL directly.

Always through API.

---

services/

Future

Telegram

Email

Scheduler

Notifications

AI

License Server

---

utils/

Reusable helper functions.

No business logic.

---

# Data Flow

TradingView

↓

Scanner

↓

Repository

↓

PostgreSQL

↓

FastAPI

↓

Dashboard

---

# Database Philosophy

Python handles

Business Logic

PostgreSQL handles

Data Logic

Examples

Python

Scanner

↓

Repository

↓

Database

Repository decides

INSERT

UPDATE

UPSERT

DELETE

Transactions

Scanner never knows SQL.

---

# Scanner Philosophy

Scanner does only

Fetch

↓

Process

↓

Save

↓

Exit

Everything else belongs elsewhere.

---

# Dashboard Philosophy

Dashboard is READ ONLY.

Dashboard never

Deletes

Updates

Creates

Database records.

Only API can do that.

---

# Security

Never expose PostgreSQL.

Never expose Supabase keys.

Never expose scanner.

Public Internet

↓

Nginx

↓

FastAPI

↓

Repository

↓

Database

---

# Deployment

Windows

↓

Development

↓

Git

↓

Ubuntu VPS

↓

Systemd

↓

Nginx

↓

HTTPS

↓

Production

---

# Git Workflow

Every milestone

Code

↓

Test

↓

Commit

↓

Push

↓

Next Milestone

Never continue with failing tests.

---

# Coding Rules

Always use

Type Hints

Meaningful Function Names

Small Functions

Repository Pattern

Logging

Exception Handling

Never duplicate code.

---

# Future Roadmap

Phase 1

Project Structure

✓

Phase 2

Database Layer

In Progress

Phase 3

Scanner Refactor

Pending

Phase 4

FastAPI

Pending

Phase 5

HTML Dashboard

Pending

Phase 6

Authentication

Pending

Phase 7

Ubuntu Deployment

Pending

Phase 8

Scheduler

Pending

Phase 9

Telegram Alerts

Pending

Phase 10

MT5 Bridge

Pending

Phase 11

AI Engine

Pending

Phase 12

License Server

Pending

---

# Long Term Goal

One backend.

Many clients.

Desktop

Web

Mobile

Telegram

MT5

AI

All consume the same API.