# Status Normalization Requirements

**Document ID**: NORM-001  
**Plan Phase**: Phase 4  
**Status**: Draft — Awaiting Review  
**Project**: Delivery Tracking Web Service  
**Dependencies**: [02-data-model.md](./02-data-model.md), [03-polling-service.md](./03-polling-service.md)

---

## 1. Overview

The Parcel App API represents delivery status as an integer code (0–8). The normalization layer translates these codes into a **`SemanticStatus` enum** — a stable, human-readable, machine-usable representation that is used consistently across the database, REST API, and dashboard.

Normalization is applied by the polling service at write time and stored persistently. The REST API exposes only normalized values. The original integer code is also stored for auditability.

---

## 2. SemanticStatus Enum

The canonical definition of `SemanticStatus` lives in `services/normalization.py` and is shared by ORM models, Pydantic schemas, and the frontend TypeScript types.

```python
class SemanticStatus(str, Enum):
    INFO_RECEIVED    = "INFO_RECEIVED"
    IN_TRANSIT       = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    AWAITING_PICKUP  = "AWAITING_PICKUP"
    DELIVERED        = "DELIVERED"
    DELIVERY_FAILED  = "DELIVERY_FAILED"
    EXCEPTION        = "EXCEPTION"
    NOT_FOUND        = "NOT_FOUND"
    FROZEN           = "FROZEN"
    UNKNOWN          = "UNKNOWN"
```

`UNKNOWN` is a sentinel value used exclusively when the Parcel API returns an unrecognised status code. It is never a valid target in a status transition from a known code.

---

## 3. Parcel Code → SemanticStatus Mapping

This is the authoritative, exhaustive mapping. There are no other valid translations.

| Parcel `status_code` | `SemanticStatus` | Display Label | Lifecycle Group | Action Required |
|---------------------|-----------------|---------------|-----------------|:---------------:|
| `0` | `DELIVERED` | Delivered | `TERMINAL` | No |
| `1` | `FROZEN` | Stalled | `TERMINAL` | ⚠️ Investigate |
| `2` | `IN_TRANSIT` | In Transit | `ACTIVE` | No |
| `3` | `AWAITING_PICKUP` | Awaiting Pickup | `ACTIVE` | ✅ Yes — collect it |
| `4` | `OUT_FOR_DELIVERY` | Out for Delivery | `ACTIVE` | No |
| `5` | `NOT_FOUND` | Not Found | `ATTENTION` | ⚠️ Investigate |
| `6` | `DELIVERY_FAILED` | Delivery Failed | `ATTENTION` | ✅ Yes — reschedule |
| `7` | `EXCEPTION` | Exception | `ATTENTION` | ✅ Yes — contact carrier |
| `8` | `INFO_RECEIVED` | Info Received | `ACTIVE` | No |
| *any other* | `UNKNOWN` | Unknown | `ATTENTION` | ⚠️ Service alert |

### Display Label Rules
- **NORM-REQ-001**: Display labels are the user-facing strings rendered in the dashboard. They MUST be defined in the frontend alongside the `SemanticStatus` enum values — not hardcoded in the backend API responses. The API returns the enum value string (e.g. `"OUT_FOR_DELIVERY"`); the frontend maps it to `"Out for Delivery"`.
- **NORM-REQ-002**: Display labels MUST be short enough to render in a constrained table cell (≤ 20 characters). The labels above are the approved set.

---

## 4. Lifecycle Groups

Every `SemanticStatus` belongs to exactly one `LifecycleGroup`. This grouping is used for dashboard filtering, status badge colouring, and future notification logic.

```python
class LifecycleGroup(str, Enum):
    ACTIVE    = "ACTIVE"
    ATTENTION = "ATTENTION"
    TERMINAL  = "TERMINAL"
```

| `LifecycleGroup` | Member `SemanticStatus` Values | Meaning |
|-----------------|-------------------------------|---------|
| `ACTIVE` | `INFO_RECEIVED`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `AWAITING_PICKUP` | Delivery is progressing. No user action needed (except `AWAITING_PICKUP`). |
| `ATTENTION` | `NOT_FOUND`, `DELIVERY_FAILED`, `EXCEPTION`, `UNKNOWN` | Something requires awareness or action. |
| `TERMINAL` | `DELIVERED`, `FROZEN` | No further Parcel API updates are expected. |

**NORM-REQ-003**: The mapping from `SemanticStatus` to `LifecycleGroup` MUST be defined in `services/normalization.py` as a constant dictionary. The REST API MUST include `lifecycle_group` alongside `semantic_status` in all delivery response payloads.

**NORM-REQ-004**: `LifecycleGroup` is **derived** — it is never stored in the database. It is computed at serialization time from the stored `semantic_status` value. This ensures that if the grouping rules change, no migration is needed.

---

## 5. Status Transition Matrix

Not all status transitions are valid in a real delivery lifecycle. The transition matrix below defines which transitions are **expected**, which are **anomalous** (possible but unusual), and which are **invalid** (should not occur but must be handled gracefully).

### 5.1 Valid Transitions

```
INFO_RECEIVED    → IN_TRANSIT
INFO_RECEIVED    → OUT_FOR_DELIVERY   (carrier skips intermediate scans)
INFO_RECEIVED    → NOT_FOUND          (carrier can't locate the parcel)
INFO_RECEIVED    → FROZEN             (no further updates received)

IN_TRANSIT       → OUT_FOR_DELIVERY
IN_TRANSIT       → AWAITING_PICKUP
IN_TRANSIT       → DELIVERED          (rare — carrier marks delivered without OFD scan)
IN_TRANSIT       → EXCEPTION
IN_TRANSIT       → NOT_FOUND
IN_TRANSIT       → FROZEN

OUT_FOR_DELIVERY → DELIVERED
OUT_FOR_DELIVERY → DELIVERY_FAILED
OUT_FOR_DELIVERY → EXCEPTION
OUT_FOR_DELIVERY → AWAITING_PICKUP    (redirect to pickup point)

DELIVERY_FAILED  → OUT_FOR_DELIVERY   (re-attempt)
DELIVERY_FAILED  → AWAITING_PICKUP    (redirect to pickup point)
DELIVERY_FAILED  → EXCEPTION
DELIVERY_FAILED  → FROZEN

AWAITING_PICKUP  → DELIVERED          (recipient collected)
AWAITING_PICKUP  → EXCEPTION
AWAITING_PICKUP  → FROZEN             (uncollected, expired)

EXCEPTION        → IN_TRANSIT         (resolved, back in network)
EXCEPTION        → OUT_FOR_DELIVERY
EXCEPTION        → DELIVERY_FAILED
EXCEPTION        → FROZEN

NOT_FOUND        → IN_TRANSIT         (located and back in network)
NOT_FOUND        → FROZEN
```

### 5.2 Terminal Transitions

`DELIVERED` and `FROZEN` are terminal states. In normal operation, a delivery in a terminal state should not transition to any other state.

**NORM-REQ-005**: If the Parcel API returns a non-terminal status for a delivery whose last stored `semantic_status` is `DELIVERED` or `FROZEN`, this is classified as an **anomalous transition**. The polling service MUST:
1. Process the update normally (update the record, write StatusHistory)
2. Log a `WARNING`: `"Anomalous status transition from terminal state detected"` with tracking number, carrier code, old status, and new status

> This handles real-world edge cases such as a delivery being re-opened, re-processed, or the Parcel API returning out-of-order data.

### 5.3 Transition Validation Policy

**NORM-REQ-006**: The service MUST NOT reject or silently discard any status transition, including anomalous ones. All transitions received from the Parcel API are persisted. Validation is **observational only** — warnings are logged, but no data is suppressed.

**Rationale**: The Parcel API is the source of truth. Discarding transitions would corrupt the delivery history and violate the full-history-retention requirement.

---

## 6. Storage Model

**NORM-REQ-007**: Both `parcel_status_code` (integer) and `semantic_status` (string enum value) are stored in the `deliveries` table. This redundancy is intentional:
- `parcel_status_code` preserves the raw source value for auditability and re-derivation
- `semantic_status` enables database-level filtering and sorting without application-layer translation
- `LifecycleGroup` is derived at query time and never stored

**NORM-REQ-008**: `StatusHistory` records store both `parcel_status_code` and `semantic_status` for both the previous and new state. This creates a fully self-contained audit record that does not rely on joining to the current `deliveries` row.

**NORM-REQ-009**: If the normalization mapping is ever updated (e.g. a new Parcel status code is added), existing `StatusHistory` records MUST NOT be retroactively modified. Historical records reflect the mapping at the time they were written.

---

## 7. Normalization Function Specification

The canonical normalization function is implemented in `services/normalization.py`:

```python
# Conceptual specification — not prescriptive of implementation style

PARCEL_CODE_TO_SEMANTIC: dict[int, SemanticStatus] = {
    0: SemanticStatus.DELIVERED,
    1: SemanticStatus.FROZEN,
    2: SemanticStatus.IN_TRANSIT,
    3: SemanticStatus.AWAITING_PICKUP,
    4: SemanticStatus.OUT_FOR_DELIVERY,
    5: SemanticStatus.NOT_FOUND,
    6: SemanticStatus.DELIVERY_FAILED,
    7: SemanticStatus.EXCEPTION,
    8: SemanticStatus.INFO_RECEIVED,
}

SEMANTIC_TO_LIFECYCLE: dict[SemanticStatus, LifecycleGroup] = {
    SemanticStatus.INFO_RECEIVED:    LifecycleGroup.ACTIVE,
    SemanticStatus.IN_TRANSIT:       LifecycleGroup.ACTIVE,
    SemanticStatus.OUT_FOR_DELIVERY: LifecycleGroup.ACTIVE,
    SemanticStatus.AWAITING_PICKUP:  LifecycleGroup.ACTIVE,
    SemanticStatus.DELIVERED:        LifecycleGroup.TERMINAL,
    SemanticStatus.FROZEN:           LifecycleGroup.TERMINAL,
    SemanticStatus.DELIVERY_FAILED:  LifecycleGroup.ATTENTION,
    SemanticStatus.EXCEPTION:        LifecycleGroup.ATTENTION,
    SemanticStatus.NOT_FOUND:        LifecycleGroup.ATTENTION,
    SemanticStatus.UNKNOWN:          LifecycleGroup.ATTENTION,
}

def normalize_status(parcel_code: int) -> SemanticStatus:
    """
    Map a Parcel integer status code to SemanticStatus.
    Returns SemanticStatus.UNKNOWN for unrecognised codes.
    Never raises.
    """
    return PARCEL_CODE_TO_SEMANTIC.get(parcel_code, SemanticStatus.UNKNOWN)

def get_lifecycle_group(status: SemanticStatus) -> LifecycleGroup:
    """
    Return the LifecycleGroup for a given SemanticStatus.
    UNKNOWN maps to ATTENTION.
    Never raises.
    """
    return SEMANTIC_TO_LIFECYCLE.get(status, LifecycleGroup.ATTENTION)
```

**NORM-REQ-010**: `normalize_status()` MUST never raise an exception for any integer input. Unknown codes return `UNKNOWN`.

**NORM-REQ-011**: `get_lifecycle_group()` MUST never raise an exception for any `SemanticStatus` input including `UNKNOWN`.

**NORM-REQ-012**: Both functions MUST be covered by unit tests with 100% branch coverage including the `UNKNOWN` fallback path.

---

## 8. Frontend Representation

The frontend TypeScript definition MUST mirror the backend enum exactly:

```typescript
// Canonical TypeScript representation

export type SemanticStatus =
  | "INFO_RECEIVED"
  | "IN_TRANSIT"
  | "OUT_FOR_DELIVERY"
  | "AWAITING_PICKUP"
  | "DELIVERED"
  | "DELIVERY_FAILED"
  | "EXCEPTION"
  | "NOT_FOUND"
  | "FROZEN"
  | "UNKNOWN";

export type LifecycleGroup = "ACTIVE" | "ATTENTION" | "TERMINAL";

export const STATUS_DISPLAY: Record<SemanticStatus, string> = {
  INFO_RECEIVED:    "Info Received",
  IN_TRANSIT:       "In Transit",
  OUT_FOR_DELIVERY: "Out for Delivery",
  AWAITING_PICKUP:  "Awaiting Pickup",
  DELIVERED:        "Delivered",
  DELIVERY_FAILED:  "Delivery Failed",
  EXCEPTION:        "Exception",
  NOT_FOUND:        "Not Found",
  FROZEN:           "Stalled",
  UNKNOWN:          "Unknown",
};

export const STATUS_LIFECYCLE: Record<SemanticStatus, LifecycleGroup> = {
  INFO_RECEIVED:    "ACTIVE",
  IN_TRANSIT:       "ACTIVE",
  OUT_FOR_DELIVERY: "ACTIVE",
  AWAITING_PICKUP:  "ACTIVE",
  DELIVERED:        "TERMINAL",
  FROZEN:           "TERMINAL",
  DELIVERY_FAILED:  "ATTENTION",
  EXCEPTION:        "ATTENTION",
  NOT_FOUND:        "ATTENTION",
  UNKNOWN:          "ATTENTION",
};

// Dashboard badge colours by lifecycle group
export const LIFECYCLE_COLOUR: Record<LifecycleGroup, string> = {
  ACTIVE:    "blue",    // e.g. Tailwind: bg-blue-100 text-blue-800
  ATTENTION: "red",     // e.g. Tailwind: bg-red-100 text-red-800
  TERMINAL:  "grey",    // e.g. Tailwind: bg-gray-100 text-gray-600
};
```

**NORM-REQ-013**: The `STATUS_DISPLAY` map in the frontend MUST be the single source of display label strings. Labels MUST NOT be hardcoded in component JSX. Components receive a `SemanticStatus` value and look up its label via this map.

**NORM-REQ-014**: Status badge colour is determined by `LifecycleGroup` (not by individual `SemanticStatus`). This ensures new statuses within an existing group inherit the correct colour automatically.

---

## 9. Requirements Summary

| ID | Requirement |
|----|-------------|
| NORM-REQ-001 | Display labels defined in frontend, not backend |
| NORM-REQ-002 | Display labels ≤ 20 characters |
| NORM-REQ-003 | `lifecycle_group` included in all delivery API responses |
| NORM-REQ-004 | `LifecycleGroup` derived at runtime, never stored |
| NORM-REQ-005 | Anomalous terminal-state transitions logged as WARNING, still persisted |
| NORM-REQ-006 | No transitions rejected or discarded — all persisted |
| NORM-REQ-007 | Both `parcel_status_code` and `semantic_status` stored in `deliveries` |
| NORM-REQ-008 | `StatusHistory` stores full status pair (code + semantic) for both states |
| NORM-REQ-009 | Historical `StatusHistory` records never retroactively modified |
| NORM-REQ-010 | `normalize_status()` never raises; unknown codes return `UNKNOWN` |
| NORM-REQ-011 | `get_lifecycle_group()` never raises |
| NORM-REQ-012 | 100% branch coverage required on both normalization functions |
| NORM-REQ-013 | Display labels via `STATUS_DISPLAY` map only — no inline strings |
| NORM-REQ-014 | Badge colour driven by `LifecycleGroup`, not individual status |

---

*Source: Parcel API reference (//delivery-tracking/api-reference.md), data model (02-data-model.md)*  
*Traceability: NORM-REQ-001 through NORM-REQ-014*
