# Trakindo Dashboard Showcase Plan

## Status

Ready for Validation

## Mode

NEW

## Goal

Build a lean but production-like analytics dashboard showcase for Trakindo that demonstrates:

- business understanding of the heavy equipment and aftermarket service model
- dashboard narrative across fleet, maintenance, sales, and SQL exploration
- practical SQL skills through marts, KPI logic, and example analytical queries
- Azure-ready deployment within an Azure for Students budget

## User-Approved Scope

The user explicitly approved proceeding with implementation on 2026-03-19 by asking: "go build it".

## Requirements

- Python application using Streamlit
- SQL-backed data model using PostgreSQL-compatible SQL
- Four dashboard pages:
  - Fleet Overview
  - Maintenance Risk
  - Sales Analytics
  - SQL Explorer
- Local development workflow
- Azure deployment scaffolding
- GitHub-friendly structure
- Interview assets:
  - KPI definitions
  - sample SQL
  - presentation narrative
  - SQL experience framing

## Architecture Decision

### Application

- Streamlit multi-page app
- Python query/service layer
- Plotly for charts

### Database

- Primary target: PostgreSQL
- Local development: PostgreSQL via Docker Compose
- Azure target: Azure Database for PostgreSQL Flexible Server when available in subscription
- Fallback target: Azure SQL Database free tier if PostgreSQL free option is unavailable

### Hosting

- Local: Docker Compose
- Azure target: Azure Container Apps with scale-to-zero

### Delivery

- Container image build through Docker
- GitHub Actions workflow for validation/build scaffolding
- Environment variables for connection strings and runtime config

## Cost Guardrails

- Keep Azure Container Apps at `min_replicas=0`
- Keep dataset synthetic and small
- Prefer free grants and student credit usage
- Avoid unnecessary managed services

## Deliverables

- Streamlit app scaffold and pages
- SQL DDL and seed-generation assets
- Query/KPI layer
- Local run instructions
- Docker and compose files
- Azure deployment scaffolding
- Interview/presentation documentation

## Execution Steps

1. Create project directories and core documentation - completed
2. Define schema, marts, and synthetic dataset generator - completed
3. Build Streamlit pages and SQL explorer experience - completed
4. Add local containerization and environment config - completed
5. Add Azure deployment scaffolding and CI workflow - completed
6. Verify data generation and Python compilation - completed
7. Verify installed Streamlit runtime locally - pending dependency installation approval

## Risks

- Streamlit and database client packages may not be installed locally
- Azure deployment cannot be executed without subscription context and credentials
- Container-based verification may be limited if Docker is unavailable locally
