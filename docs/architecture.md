# OrderBridge architecture

OrderBridge has two front doors into the same mock ERP. Trading partners come in through
**EDI**. AI agents come in through **MCP**. Both share one set of business rules, one
database, one audit trail, and one event stream.

```mermaid
flowchart LR
    %% ---------- Trading partner / EDI side ----------
    subgraph Partners["Trading partners (fictional)"]
        TP["SwiftShip Logistics (3PL)<br/>Peak Outfitters (Retailer)<br/>Granite Manufacturing (CM)"]
    end

    subgraph EDI["EDI layer"]
        IN[/"edi/inbound/<br/>X12 850 Purchase Orders"/]
        PROC["EDI processor<br/>folder watcher + X12 parser<br/>ISA width, SE count, control numbers"]
        OUT[/"edi/outbound/<br/>855 Acknowledgment, 856 ASN"/]
        ERR[/"edi/error/<br/>bad file + .reason.txt"/]
    end

    %% ---------- Core ----------
    API["FastAPI REST API<br/>/orders, /inventory<br/>Idempotency-Key"]
    SVC["Business rules<br/>orderbridge/services"]
    DB[("PostgreSQL 16 mock ERP<br/>orders, inventory, proposals,<br/>purchase_orders, audit_log, outbox")]

    %% ---------- Events ----------
    PUB["Outbox publisher<br/>retry + exponential backoff"]
    RP[["Redpanda (Kafka API)<br/>topics: orders, inventory, approvals"]]
    WATCH["watch_events.py<br/>live terminal stream"]
    CON["Redpanda Console<br/>localhost:8080"]

    %% ---------- AI side ----------
    USER(["You: questions in plain English"])
    CC["Claude Code<br/>(the AI agent)"]
    MCP["MCP server (stdio)<br/>1. role check  2. validation  3. audit"]
    HUMAN["Human approver<br/>scripts/approve.py"]
    DASH["Live dashboard<br/>/dashboard"]

    TP -- "sends 850" --> IN --> PROC
    PROC -- "valid: create order" --> SVC
    PROC -- "invalid" --> ERR
    PROC -- "855 after commit" --> OUT
    API --> SVC
    SVC -- "856 when shipped" --> OUT
    OUT -. "returned to partner" .-> TP
    SVC -- "change + outbox row<br/>in ONE transaction" --> DB

    DB -- "unpublished outbox rows" --> PUB --> RP
    RP --> WATCH
    RP --> CON

    USER -- asks --> CC -- "calls tools" --> MCP
    MCP -- "reads, allocates, proposes, logs" --> SVC
    HUMAN -- "approves / rejects<br/>(AI cannot)" --> SVC
    DB -- "polled every 3 s" --> DASH
```

## Request paths

| Path | Steps |
|---|---|
| Partner order | Partner drops an 850 into `edi/inbound/`. The watcher validates the envelope, finds the partner from ISA06, and creates the order with an `order.received` outbox row in one transaction. It writes the 855 after commit, marks the order `ACKNOWLEDGED`, and moves the file to `processed/`. |
| AI question | Claude Code calls an MCP tool. The server checks the role from `MCP_ROLE`, validates the arguments, runs the service function in one transaction, and writes an audit row whether the call succeeds, fails, or is denied. |
| Replenishment | Claude proposes a buy (`PENDING`, `replenishment.proposed` event). A human runs `approve.py`, which records their name, creates the purchase order, and emits `replenishment.approved` and `purchase_order.created`. |
| Shipment | `POST /orders/{id}/ship` decrements stock, records the shipment, emits `inventory.changed` and `order.shipped`, then writes the 856 after commit. |

## Event catalogue

| Event type | Topic | Key | Emitted when |
|---|---|---|---|
| `order.received` | orders | PO number | Order created from EDI or the API |
| `order.acknowledged` | orders | PO number | 855 generated |
| `order.allocated` | orders | PO number | Stock reserved for every line |
| `order.shipped` | orders | PO number | Shipment recorded |
| `inventory.changed` | inventory | SKU | Allocation or shipment changes a warehouse row |
| `replenishment.proposed` | approvals | SKU | AI or user proposes a buy |
| `replenishment.approved` / `.rejected` | approvals | SKU | Human decision |
| `purchase_order.created` | approvals | RPO number | Approval creates a purchase order |

Every event has the same envelope: `event_id` (UUID for consumer de-duplication),
`event_type`, `occurred_at` (UTC), `key`, and `data`.

## Why each control exists

| Control | Integration analogy | Where |
|---|---|---|
| Idempotency keys | De-duplication on a retrying HTTP listener | `orderbridge/api/idempotency.py` |
| Transactional outbox | Guaranteed-delivery queue inside the ERP's own database | `orderbridge/events/outbox.py`, `publisher.py` |
| Head-of-line ordering | A FIFO queue that does not skip a failed message | `publish_batch` in `publisher.py` |
| Role check before validation | API gateway policy before the backend is touched | `orderbridge/mcp_server/auth.py` |
| Argument validation | Schema and reference-data checks on inbound documents | `orderbridge/mcp_server/validation.py` |
| Audit in its own transaction | A tracked-fields log that survives a failed process run | `orderbridge/audit.py` |
| Human-only approval | Segregation of duties: requester is never the approver | `scripts/approve.py`, no MCP tool |
| Transient vs permanent EDI errors | Retry queue vs dead-letter folder | `orderbridge/edi/watcher.py` |
