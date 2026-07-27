# Healthcare Referral Routing Hub

A lightweight FHIR-based web service for routing healthcare referrals between providers and care networks.

## Overview

This service acts as the central hub for processing and routing patient referral requests according to the [HL7 FHIR](https://www.hl7.org/fhir/) standard. It receives referral data, determines the appropriate downstream provider or care network, and dispatches routing decisions — enabling interoperability across healthcare systems.

## Stack

- **Runtime**: Python 3
- **Framework**: Flask
- **Database**: PostgreSQL (via psycopg2)
- **Standard**: HL7 FHIR R4

## Running Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the server:

```bash
python app.py
```

The server listens on port `5000` by default. Set the `PORT` environment variable to override.

## Environment Variables

| Variable       | Description                        |
|----------------|------------------------------------|
| `DATABASE_URL` | PostgreSQL connection string       |
| `PORT`         | Port to listen on (default: 5000)  |

## Routes

| Method | Path      | Description            |
|--------|-----------|------------------------|
| GET    | `/health` | Health check endpoint  |

## Health Check

```bash
curl http://localhost:5000/health
# {"status": "ok"}
```
