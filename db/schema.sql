-- =============================================================================
-- OrderBridge mock ERP schema (PostgreSQL 16)
-- Loaded automatically by Docker the first time the database volume is created.
-- Re-load any time with:  python scripts/reset_db.py
-- =============================================================================

-- Trading partners: who sends us EDI and who we ship to.
CREATE TABLE partners (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(20)  NOT NULL UNIQUE,
    name        VARCHAR(100) NOT NULL,
    type        VARCHAR(10)  NOT NULL CHECK (type IN ('3PL', 'RETAILER', 'CM')),
    edi_isa_id  VARCHAR(15)  NOT NULL UNIQUE        -- the partner's ISA06 sender ID
);

-- Item master.
CREATE TABLE products (
    sku             VARCHAR(30)    PRIMARY KEY,
    description     VARCHAR(200)   NOT NULL,
    unit_cost       NUMERIC(10, 2) NOT NULL CHECK (unit_cost >= 0),
    reorder_point   INTEGER        NOT NULL CHECK (reorder_point >= 0),
    reorder_qty     INTEGER        NOT NULL CHECK (reorder_qty > 0),
    lead_time_days  INTEGER        NOT NULL CHECK (lead_time_days >= 0)
);

-- Stock per SKU per warehouse. available = on_hand - allocated (computed, never stored).
CREATE TABLE inventory (
    sku        VARCHAR(30) NOT NULL REFERENCES products (sku),
    warehouse  VARCHAR(20) NOT NULL,
    on_hand    INTEGER     NOT NULL DEFAULT 0 CHECK (on_hand >= 0),
    allocated  INTEGER     NOT NULL DEFAULT 0 CHECK (allocated >= 0),
    PRIMARY KEY (sku, warehouse),
    CHECK (allocated <= on_hand)
);

-- Customer purchase orders (inbound 850s or POST /orders).
CREATE TABLE orders (
    id                   SERIAL PRIMARY KEY,
    partner_id           INTEGER     NOT NULL REFERENCES partners (id),
    po_number            VARCHAR(30) NOT NULL,
    status               VARCHAR(15) NOT NULL DEFAULT 'RECEIVED'
                         CHECK (status IN ('RECEIVED', 'ACKNOWLEDGED', 'ALLOCATED', 'SHIPPED', 'CANCELLED')),
    requested_ship_date  DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_orders_partner_po UNIQUE (partner_id, po_number)   -- duplicate PO protection
);
CREATE INDEX ix_orders_status_ship_date ON orders (status, requested_ship_date);

CREATE TABLE order_lines (
    order_id    INTEGER        NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    line_no     INTEGER        NOT NULL,
    sku         VARCHAR(30)    NOT NULL REFERENCES products (sku),
    qty         INTEGER        NOT NULL CHECK (qty > 0),
    unit_price  NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    PRIMARY KEY (order_id, line_no)
);

-- Which warehouse stock was reserved for which order line.
-- Needed so that shipping knows exactly which inventory rows to decrement.
CREATE TABLE order_allocations (
    id         SERIAL PRIMARY KEY,
    order_id   INTEGER     NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    line_no    INTEGER     NOT NULL,
    sku        VARCHAR(30) NOT NULL REFERENCES products (sku),
    warehouse  VARCHAR(20) NOT NULL,
    qty        INTEGER     NOT NULL CHECK (qty > 0),
    FOREIGN KEY (order_id, line_no) REFERENCES order_lines (order_id, line_no) ON DELETE CASCADE
);

CREATE TABLE shipments (
    id               SERIAL PRIMARY KEY,
    order_id         INTEGER     NOT NULL REFERENCES orders (id),
    carrier          VARCHAR(30) NOT NULL,
    tracking_number  VARCHAR(50) NOT NULL,
    shipped_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- AI (or human) suggestions to buy more stock. Only a human can approve them.
CREATE TABLE replenishment_proposals (
    id           SERIAL PRIMARY KEY,
    sku          VARCHAR(30)  NOT NULL REFERENCES products (sku),
    qty          INTEGER      NOT NULL CHECK (qty > 0),
    reason       VARCHAR(500) NOT NULL,
    proposed_by  VARCHAR(100) NOT NULL,
    status       VARCHAR(10)  NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    decided_by   VARCHAR(100),
    decided_at   TIMESTAMPTZ,
    decision_note VARCHAR(500),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- A decision must record who made it and when.
    CHECK ((status = 'PENDING') = (decided_by IS NULL AND decided_at IS NULL))
);

-- Purchase orders to suppliers. Created ONLY when a human approves a proposal.
CREATE TABLE purchase_orders (
    id             SERIAL PRIMARY KEY,
    po_number      VARCHAR(30)    NOT NULL UNIQUE,
    proposal_id    INTEGER        NOT NULL UNIQUE REFERENCES replenishment_proposals (id),
    sku            VARCHAR(30)    NOT NULL REFERENCES products (sku),
    qty            INTEGER        NOT NULL CHECK (qty > 0),
    unit_cost      NUMERIC(10, 2) NOT NULL,
    status         VARCHAR(10)    NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RECEIVED', 'CANCELLED')),
    approved_by    VARCHAR(100)   NOT NULL,
    expected_date  DATE,
    created_at     TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Who did what, through which channel, and whether it was allowed.
CREATE TABLE audit_log (
    id                BIGSERIAL PRIMARY KEY,
    timestamp         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    actor             VARCHAR(100) NOT NULL,
    role              VARCHAR(30)  NOT NULL,
    tool_or_endpoint  VARCHAR(100) NOT NULL,
    arguments         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    result            VARCHAR(10)  NOT NULL CHECK (result IN ('OK', 'DENIED', 'ERROR')),
    detail            TEXT
);
CREATE INDEX ix_audit_log_timestamp ON audit_log (timestamp DESC);

-- Transactional outbox: events are written here in the SAME transaction as the
-- business change, then a separate publisher process sends them to Redpanda.
CREATE TABLE outbox (
    id               BIGSERIAL PRIMARY KEY,
    event_type       VARCHAR(50) NOT NULL,
    payload          JSONB       NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at     TIMESTAMPTZ,                  -- NULL until the broker confirms
    attempts         INTEGER     NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ,                  -- exponential backoff after a failure
    last_error       TEXT
);
-- Partial index: the publisher only ever scans unpublished rows.
CREATE INDEX ix_outbox_unpublished ON outbox (id) WHERE published_at IS NULL;

-- Remembers POST /orders requests so a retried request is not processed twice.
CREATE TABLE idempotency_keys (
    key           VARCHAR(100) PRIMARY KEY,
    request_hash  CHAR(64)     NOT NULL,           -- SHA-256 of the request body
    status_code   INTEGER      NOT NULL,
    response      JSONB        NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- X12 interchange / group control numbers for outbound 855 and 856 documents.
CREATE SEQUENCE edi_control_number_seq START 1001;
