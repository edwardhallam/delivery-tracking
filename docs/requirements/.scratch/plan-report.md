# Delivery Tracking Service — Requirements Definition

## Overview

Define comprehensive, implementation-ready requirements for a greenfield Delivery Tracking Web Service that wraps the Parcel App API.

## Goals
- Poll Parcel API every 15 minutes for active deliveries
- Normalize status codes into human-readable semantic states
- Expose a REST API for a web dashboard consumer
- Web dashboard: lists deliveries with sender, status, expected delivery date
- Single-user credential-based access (username + password)
- Full persistent history retained for all deliveries
- Docker self-hosted deployment

## Inputs
- Parcel API Reference: //delivery-tracking/api-reference.md
- Original API Docs: //delivery-tracking/parcel-api-view-deliveries.md
- User scoping answers: No notifications, single tenant, dashboard consumer, Docker, full history, 15-min polling

## Output
- Comprehensive requirements document at //delivery-tracking/docs/requirements/
- Data model specification
- REST API specification
- Deployment specification

## Plan Information

- **Workspace:** delivery-tracking
- **Plan ID:** requirements
- **Created:** 2026-04-01 10:48:07.429213
- **Last Updated:** 2026-04-01 12:01:45.506938
- **Total Tasks:** 9
- **Completed Tasks:** 9 (100.0%)

## Tasks

- [x] **Phase 1 — Architecture & Tech Stack Selection** 🔴
  Define and document the system architecture, selected technology stack, and component breakdown. This forms the structural backbone all other requirements are written against.
  
  *Context:*
  IN PROGRESS. Writing architecture decision record and component diagram. Tech stack selected: Python/FastAPI backend + APScheduler, PostgreSQL, React/Vite frontend, Nginx reverse proxy, Docker Compose.
  
  *Created: 2026-04-01 10:48:17.568432 | Updated: 2026-04-01 10:49:16.112946 | Priority: High*
  

- [x] **Phase 2 — Data Model Requirements** 🔴
  Define all persistent data entities: deliveries, events, status history, and user credentials. Include field-level constraints, relationships, and indexing strategy.
  
  *Context:*
  Inputs: Parcel API Delivery and Event schemas from api-reference.md, full history retention requirement.
  Deliverable: //delivery-tracking/docs/requirements/02-data-model.md with entity diagrams (Mermaid ERD), field specs, constraints, and migration strategy notes.
  Key entities: Delivery, DeliveryEvent, StatusHistory, User.
  Must capture: carrier_code enrichment, timezone-ambiguous date fields, status code→enum mapping.
  
  *Created: 2026-04-01 10:48:23.670047 | Updated: 2026-04-01 10:48:23.670050 | Priority: High*
  

- [x] **Phase 3 — Polling Service Requirements** 🔴
  Define requirements for the background polling subsystem: scheduling, rate limit compliance, change detection, error handling, and retry logic.
  
  *Context:*
  Inputs: Parcel API rate limit (20 req/hr), polling interval (15 min), single Parcel API key, full history retention.
  Deliverable: //delivery-tracking/docs/requirements/03-polling-service.md
  Key areas: scheduler setup, API key management, diff/change-detection algorithm, status transition detection, error + retry strategy, startup behaviour (cold start).
  
  *Created: 2026-04-01 10:48:31.529689 | Updated: 2026-04-01 10:48:31.529693 | Priority: High*
  

- [x] **Phase 4 — Status Normalization Requirements**
  Define the status normalization layer: mapping Parcel integer codes to semantic enums, human-readable labels, grouping into lifecycle phases, and transition validation.
  
  *Context:*
  Inputs: Parcel status codes 0–8 from api-reference.md.
  Deliverable: //delivery-tracking/docs/requirements/04-status-normalization.md
  Must define: SemanticStatus enum, display labels, lifecycle groupings (terminal/active/attention), valid transition matrix, how normalized status is stored vs derived.
  
  *Created: 2026-04-01 10:48:36.875186 | Updated: 2026-04-01 10:48:36.875190 | Priority: Medium*
  

- [x] **Phase 5 — REST API Requirements** 🔴
  Define all REST API endpoints exposed by the service: resources, HTTP methods, request/response schemas, auth requirements, pagination, filtering, and error formats.
  
  *Context:*
  Inputs: data model (Phase 2), web dashboard requirements (upcoming deliveries, sender, status, expected date).
  Deliverable: //delivery-tracking/docs/requirements/05-rest-api.md with endpoint catalogue, request/response schemas, OpenAPI-style definitions, auth patterns, error schema.
  Key endpoints: list deliveries, get delivery detail (with event history), auth endpoints.
  
  *Created: 2026-04-01 10:48:42.236622 | Updated: 2026-04-01 10:48:42.236626 | Priority: High*
  

- [x] **Phase 6 — Web Dashboard Requirements**
  Define the web dashboard UI requirements: views, data displayed per delivery, interactions, filter/sort options, and how it connects to the REST API.
  
  *Context:*
  Inputs: User requirement (upcoming deliveries, sender, status, expected delivery date), single-user credential login.
  Deliverable: //delivery-tracking/docs/requirements/06-web-dashboard.md
  Must cover: login page, delivery list view (columns, sort, filter), delivery detail view, status indicators, refresh behaviour, session management.
  
  *Created: 2026-04-01 10:48:47.124972 | Updated: 2026-04-01 10:48:47.124975 | Priority: Medium*
  

- [x] **Phase 7 — Authentication & Security Requirements** 🔴
  Define authentication mechanism for the single user: credential storage, session/token management, API route protection, and basic security hardening.
  
  *Context:*
  Inputs: Single-user credential access requirement, Docker self-hosted context.
  Deliverable: //delivery-tracking/docs/requirements/07-auth-security.md
  Must cover: password hashing, JWT or session tokens, token expiry, protected routes, CORS policy, HTTPS considerations for self-hosted.
  
  *Created: 2026-04-01 10:48:52.306675 | Updated: 2026-04-01 10:48:52.306680 | Priority: High*
  

- [x] **Phase 8 — Deployment & Configuration Requirements**
  Define Docker Compose topology, service configuration, environment variable schema, volume strategy for persistence, health checks, and operational considerations.
  
  *Context:*
  Inputs: Docker self-hosted requirement, PostgreSQL persistence, single-user.
  Deliverable: //delivery-tracking/docs/requirements/08-deployment.md
  Must cover: Docker Compose services, image base selections, env vars schema, volume mounts, port exposure, health check endpoints, startup ordering, first-run setup (initial user creation).
  
  *Created: 2026-04-01 10:48:57.413447 | Updated: 2026-04-01 10:48:57.413453 | Priority: Medium*
  

- [x] **Phase 9 — Master Requirements Document** 🔴
  Compile all phase outputs into a single consolidated requirements document with executive summary, traceability table, and open questions log.
  
  *Context:*
  Inputs: All docs from phases 1–8.
  Deliverable: //delivery-tracking/docs/requirements/00-master-requirements.md
  Must include: executive summary, scope statement, full requirements catalogue with IDs (REQ-XXX), traceability to source (user input / API docs / inferred), open questions/assumptions log.
  
  *Created: 2026-04-01 10:49:03.073002 | Updated: 2026-04-01 10:49:03.073007 | Priority: High*
  

---
*Report generated on 2026-04-01T12:01:59.413684*