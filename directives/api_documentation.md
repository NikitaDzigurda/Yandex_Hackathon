# API Documentation - Yandex Hackathon

This document describes the current active endpoints of the backend application (FastAPI). All endpoints are prefixed with `/api/v1`.

---

## 🚀 1. Applications API (`/api/v1/applications`)
Managing the intake of industrial project proposals.

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `POST` | **Create Application:** Initializes a new project and application record. Triggers initial orchestration. |
| `/pending` | `GET` | **List Pending:** Returns applications currently in `SCORING` status (waiting for PM decision). |
| `/{id}` | `GET` | **Get Application:** Returns full details of a specific application, including `scorecard` and `intake_details`. |
| `/{id}/trigger-intake` | `POST` | **Run Intake:** Manually triggers the Intake Agent Committee (5 experts) to evaluate the application. |
| `/{id}/trigger-research` | `POST` | **Run Research:** Manually triggers the Deep Research Pipeline (9 agents). *Requires 'Approved' status.* |
| `/{id}/report` | `GET` | **Get Research Report:** Fetches the latest generated scientific/technical research report for the application. |
| `/{id}/decision` | `POST` | **PM Decision:** Submits the final approval or rejection from the Project Manager. |

---

## 📂 2. Projects API (`/api/v1/projects`)
High-level management and monitoring of projects.

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | **List Projects:** Returns a paginated list of all active projects in the system. |
| `/{id}` | `GET` | **Project Details:** Returns project info and its history of related applications. |
| `/{id}/status` | `GET` | **Project Dashboard Data:** The primary endpoint for the UI. Returns the latest status, intake results, research report segments, and Yandex Tracker tasks. |

---

## 🛠️ 3. Utility & Demo Endpoints
System maintenance and development tools.

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | `GET` | **Health Check:** Verifies connectivity to PostgreSQL, Redis, Yandex Cloud AI, and Yandex Tracker. |
| `/demo/seed` | `POST` | **Seed Data:** Populates the database with demo applications for testing (Disabled in Production). |
| `/` | `GET` | **Static Host:** Serves the built-in frontend dashboard (index.html). |

---

## 💡 Usage Notes

- **Traceability:** The `/{project_id}/status` and `/{application_id}` endpoints now include `intake_details` and `agent_outputs` which contain the raw "thought process" of every LLM agent in the pipeline.
- **Async Execution:** Heavy agents (Intake/Research) are executed asynchronously. They update the database and state upon completion, notifying the PM via Yandex Tracker where configured.
