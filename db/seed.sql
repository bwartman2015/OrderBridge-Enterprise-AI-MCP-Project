-- =============================================================================
-- OrderBridge seed data (all companies and people are fictional)
--
-- Dates are relative to CURRENT_DATE so the demo scenarios stay "live".
-- To refresh them on a later day:  python scripts/reset_db.py
--
-- Deliberate demo scenarios:
--   * Low stock (available <= reorder point): TENT-2P-ULT, FUEL-230, FILTER-SQZ, LAMP-HEAD
--   * At-risk orders (ship within 2 days, not yet allocated): 5 orders
--   * Short order: PK-10005 needs 30 x TENT-2P-ULT but only ~12 are available
-- =============================================================================

INSERT INTO partners (id, code, name, type, edi_isa_id) VALUES
    (1, 'SWIFT', 'SwiftShip Logistics', '3PL', 'SWIFTSHIP'),
    (2, 'PEAK', 'Peak Outfitters', 'RETAILER', 'PEAKOUTFIT'),
    (3, 'GRANITE', 'Granite Manufacturing', 'CM', 'GRANITEMFG');

INSERT INTO products (sku, description, unit_cost, reorder_point, reorder_qty, lead_time_days) VALUES
    ('TENT-2P-ULT', 'Ultralight 2-Person Backpacking Tent', 189.00, 20, 60, 21),
    ('TENT-4P-FAM', 'Family 4-Person Dome Tent', 249.00, 15, 40, 21),
    ('SBAG-20F', 'Down Sleeping Bag, 20F', 159.00, 25, 80, 28),
    ('SBAG-40F', 'Synthetic Sleeping Bag, 40F', 79.00, 30, 100, 14),
    ('PAD-INF-R', 'Inflatable Sleeping Pad, Regular', 69.00, 30, 100, 14),
    ('PACK-45L', 'Trekking Backpack 45L', 139.00, 20, 60, 30),
    ('PACK-65L', 'Expedition Backpack 65L', 199.00, 15, 40, 30),
    ('PACK-DAY-22', 'Daypack 22L', 49.00, 40, 150, 14),
    ('BOOT-HIKE-M', 'Waterproof Hiking Boot, Men''s', 119.00, 30, 90, 35),
    ('BOOT-HIKE-W', 'Waterproof Hiking Boot, Women''s', 119.00, 30, 90, 35),
    ('JKT-RAIN-M', 'Packable Rain Jacket', 89.00, 25, 80, 21),
    ('JKT-DOWN-L', 'Lightweight Down Jacket', 149.00, 20, 60, 28),
    ('STOVE-CAN', 'Canister Backpacking Stove', 39.00, 30, 120, 14),
    ('FUEL-230', 'Isobutane Fuel Canister 230g', 4.50, 100, 400, 7),
    ('POT-TI-750', 'Titanium Cook Pot 750ml', 34.00, 30, 100, 21),
    ('FILTER-SQZ', 'Squeeze Water Filter', 28.00, 30, 120, 14),
    ('BOTTLE-1L', 'Insulated Water Bottle 1L', 18.00, 50, 200, 14),
    ('LAMP-HEAD', 'Headlamp, 400 Lumen', 26.00, 40, 150, 14),
    ('POLE-TREK', 'Carbon Trekking Poles (pair)', 79.00, 20, 60, 21),
    ('CHAIR-CAMP', 'Compact Camp Chair', 45.00, 25, 80, 21),
    ('HAMMOCK-SGL', 'Single Camping Hammock', 39.00, 20, 60, 21),
    ('KNIFE-FOLD', 'Folding Pocket Knife', 22.00, 30, 100, 14),
    ('COMPASS-BASE', 'Baseplate Compass', 15.00, 30, 100, 14),
    ('FAK-TRAIL', 'Trail First Aid Kit', 24.00, 30, 100, 14),
    ('SOCK-MERINO', 'Merino Hiking Socks (3-pack)', 21.00, 60, 200, 14);

-- allocated = sum of order_allocations below (kept consistent by the generator)
INSERT INTO inventory (sku, warehouse, on_hand, allocated) VALUES
    ('TENT-2P-ULT', 'WH-EAST', 8, 2),
    ('TENT-2P-ULT', 'WH-WEST', 6, 0),
    ('TENT-4P-FAM', 'WH-EAST', 60, 0),
    ('TENT-4P-FAM', 'WH-WEST', 45, 0),
    ('SBAG-20F', 'WH-EAST', 90, 0),
    ('SBAG-20F', 'WH-WEST', 70, 0),
    ('SBAG-40F', 'WH-EAST', 120, 0),
    ('SBAG-40F', 'WH-WEST', 95, 0),
    ('PAD-INF-R', 'WH-EAST', 110, 2),
    ('PAD-INF-R', 'WH-WEST', 85, 0),
    ('PACK-45L', 'WH-EAST', 75, 24),
    ('PACK-45L', 'WH-WEST', 60, 0),
    ('PACK-65L', 'WH-EAST', 50, 18),
    ('PACK-65L', 'WH-WEST', 40, 0),
    ('PACK-DAY-22', 'WH-EAST', 160, 10),
    ('PACK-DAY-22', 'WH-WEST', 140, 0),
    ('BOOT-HIKE-M', 'WH-EAST', 100, 0),
    ('BOOT-HIKE-M', 'WH-WEST', 80, 0),
    ('BOOT-HIKE-W', 'WH-EAST', 95, 6),
    ('BOOT-HIKE-W', 'WH-WEST', 85, 0),
    ('JKT-RAIN-M', 'WH-EAST', 100, 20),
    ('JKT-RAIN-M', 'WH-WEST', 90, 0),
    ('JKT-DOWN-L', 'WH-EAST', 70, 0),
    ('JKT-DOWN-L', 'WH-WEST', 55, 0),
    ('STOVE-CAN', 'WH-EAST', 130, 0),
    ('STOVE-CAN', 'WH-WEST', 110, 0),
    ('FUEL-230', 'WH-EAST', 40, 0),
    ('FUEL-230', 'WH-WEST', 35, 0),
    ('POT-TI-750', 'WH-EAST', 120, 0),
    ('POT-TI-750', 'WH-WEST', 100, 0),
    ('FILTER-SQZ', 'WH-EAST', 12, 0),
    ('FILTER-SQZ', 'WH-WEST', 10, 0),
    ('BOTTLE-1L', 'WH-EAST', 220, 0),
    ('BOTTLE-1L', 'WH-WEST', 180, 0),
    ('LAMP-HEAD', 'WH-EAST', 20, 4),
    ('LAMP-HEAD', 'WH-WEST', 18, 0),
    ('POLE-TREK', 'WH-EAST', 70, 0),
    ('POLE-TREK', 'WH-WEST', 60, 0),
    ('CHAIR-CAMP', 'WH-EAST', 90, 0),
    ('CHAIR-CAMP', 'WH-WEST', 70, 0),
    ('HAMMOCK-SGL', 'WH-EAST', 65, 16),
    ('HAMMOCK-SGL', 'WH-WEST', 50, 0),
    ('KNIFE-FOLD', 'WH-EAST', 110, 24),
    ('KNIFE-FOLD', 'WH-WEST', 90, 0),
    ('COMPASS-BASE', 'WH-EAST', 100, 0),
    ('COMPASS-BASE', 'WH-WEST', 90, 0),
    ('FAK-TRAIL', 'WH-EAST', 105, 0),
    ('FAK-TRAIL', 'WH-WEST', 95, 0),
    ('SOCK-MERINO', 'WH-EAST', 230, 40),
    ('SOCK-MERINO', 'WH-WEST', 200, 0);

INSERT INTO orders (id, partner_id, po_number, status, requested_ship_date, created_at) VALUES
    (1, 3, 'GM-30001', 'SHIPPED', CURRENT_DATE - 6, now() - interval '22 days'),
    (2, 3, 'GM-30002', 'SHIPPED', CURRENT_DATE - 20, now() - interval '23 days'),
    (3, 3, 'GM-30003', 'SHIPPED', CURRENT_DATE - 9, now() - interval '33 days'),
    (4, 3, 'GM-30004', 'SHIPPED', CURRENT_DATE - 16, now() - interval '27 days'),
    (5, 1, 'SS-20001', 'SHIPPED', CURRENT_DATE - 15, now() - interval '23 days'),
    (6, 3, 'GM-30005', 'SHIPPED', CURRENT_DATE - 17, now() - interval '30 days'),
    (7, 3, 'GM-30006', 'SHIPPED', CURRENT_DATE - 12, now() - interval '35 days'),
    (8, 3, 'GM-30007', 'SHIPPED', CURRENT_DATE - 10, now() - interval '34 days'),
    (9, 2, 'PK-10001', 'SHIPPED', CURRENT_DATE - 17, now() - interval '32 days'),
    (10, 3, 'GM-30008', 'SHIPPED', CURRENT_DATE - 11, now() - interval '33 days'),
    (11, 3, 'GM-30009', 'CANCELLED', CURRENT_DATE + 2, now() - interval '12 days'),
    (12, 2, 'PK-10002', 'CANCELLED', CURRENT_DATE + 2, now() - interval '20 days'),
    (13, 1, 'SS-20002', 'ALLOCATED', CURRENT_DATE + 2, now() - interval '3 days'),
    (14, 1, 'SS-20003', 'ALLOCATED', CURRENT_DATE + 1, now() - interval '5 days'),
    (15, 1, 'SS-20004', 'ALLOCATED', CURRENT_DATE + 4, now() - interval '6 days'),
    (16, 2, 'PK-10003', 'ALLOCATED', CURRENT_DATE + 6, now() - interval '3 days'),
    (17, 1, 'SS-20005', 'ALLOCATED', CURRENT_DATE + 3, now() - interval '6 days'),
    (18, 3, 'GM-30010', 'ALLOCATED', CURRENT_DATE + 6, now() - interval '8 days'),
    (19, 2, 'PK-10004', 'ALLOCATED', CURRENT_DATE + 1, now() - interval '6 days'),
    (20, 1, 'SS-20006', 'ALLOCATED', CURRENT_DATE + 6, now() - interval '8 days'),
    (21, 2, 'PK-10005', 'ACKNOWLEDGED', CURRENT_DATE + 1, now() - interval '4 days'),  -- SHORT on TENT-2P-ULT (at risk)
    (22, 2, 'PK-10006', 'ACKNOWLEDGED', CURRENT_DATE + 2, now() - interval '5 days'),  -- at risk: ships within 2 days, not allocated
    (23, 1, 'SS-20007', 'RECEIVED', CURRENT_DATE + 1, now() - interval '2 days'),  -- at risk: ships within 2 days, not allocated
    (24, 3, 'GM-30011', 'ACKNOWLEDGED', CURRENT_DATE, now() - interval '6 days'),  -- at risk: ships within 2 days, not allocated
    (25, 1, 'SS-20008', 'ACKNOWLEDGED', CURRENT_DATE + 2, now() - interval '3 days'),  -- at risk: ships within 2 days, not allocated
    (26, 3, 'GM-30012', 'ACKNOWLEDGED', CURRENT_DATE + 11, now() - interval '1 days'),
    (27, 2, 'PK-10007', 'RECEIVED', CURRENT_DATE + 8, now() - interval '2 days'),
    (28, 1, 'SS-20009', 'ACKNOWLEDGED', CURRENT_DATE + 20, now() - interval '0 days'),
    (29, 3, 'GM-30013', 'ACKNOWLEDGED', CURRENT_DATE + 18, now() - interval '1 days'),
    (30, 3, 'GM-30014', 'ACKNOWLEDGED', CURRENT_DATE + 8, now() - interval '1 days'),
    (31, 3, 'GM-30015', 'RECEIVED', CURRENT_DATE + 5, now() - interval '0 days'),
    (32, 1, 'SS-20010', 'ACKNOWLEDGED', CURRENT_DATE + 7, now() - interval '4 days'),
    (33, 3, 'GM-30016', 'ACKNOWLEDGED', CURRENT_DATE + 20, now() - interval '1 days'),
    (34, 2, 'PK-10008', 'ACKNOWLEDGED', CURRENT_DATE + 19, now() - interval '0 days'),
    (35, 3, 'GM-30017', 'ACKNOWLEDGED', CURRENT_DATE + 8, now() - interval '1 days'),
    (36, 2, 'PK-10009', 'RECEIVED', CURRENT_DATE + 13, now() - interval '3 days'),
    (37, 3, 'GM-30018', 'ACKNOWLEDGED', CURRENT_DATE + 5, now() - interval '0 days'),
    (38, 1, 'SS-20011', 'ACKNOWLEDGED', CURRENT_DATE + 6, now() - interval '1 days'),
    (39, 3, 'GM-30019', 'ACKNOWLEDGED', CURRENT_DATE + 20, now() - interval '1 days'),
    (40, 3, 'GM-30020', 'ACKNOWLEDGED', CURRENT_DATE + 6, now() - interval '0 days');

INSERT INTO order_lines (order_id, line_no, sku, qty, unit_price) VALUES
    (1, 1, 'BOOT-HIKE-M', 8, 190.40),
    (1, 2, 'SOCK-MERINO', 6, 33.60),
    (2, 1, 'SBAG-20F', 10, 254.40),
    (2, 2, 'TENT-4P-FAM', 10, 398.40),
    (2, 3, 'SBAG-40F', 4, 126.40),
    (3, 1, 'BOOT-HIKE-M', 12, 190.40),
    (3, 2, 'POLE-TREK', 4, 126.40),
    (3, 3, 'COMPASS-BASE', 8, 24.00),
    (4, 1, 'PACK-45L', 15, 222.40),
    (4, 2, 'PACK-DAY-22', 6, 78.40),
    (5, 1, 'STOVE-CAN', 12, 62.40),
    (5, 2, 'FAK-TRAIL', 4, 38.40),
    (6, 1, 'POT-TI-750', 6, 54.40),
    (7, 1, 'COMPASS-BASE', 6, 24.00),
    (7, 2, 'PACK-DAY-22', 4, 78.40),
    (8, 1, 'SBAG-40F', 6, 126.40),
    (8, 2, 'BOOT-HIKE-M', 20, 190.40),
    (9, 1, 'PACK-65L', 15, 318.40),
    (9, 2, 'STOVE-CAN', 10, 62.40),
    (10, 1, 'FAK-TRAIL', 8, 38.40),
    (11, 1, 'POLE-TREK', 20, 126.40),
    (12, 1, 'JKT-DOWN-L', 4, 238.40),
    (13, 1, 'LAMP-HEAD', 4, 41.60),
    (13, 2, 'PACK-DAY-22', 10, 78.40),
    (14, 1, 'TENT-2P-ULT', 2, 302.40),
    (14, 2, 'PAD-INF-R', 2, 110.40),
    (15, 1, 'KNIFE-FOLD', 12, 35.20),
    (15, 2, 'SOCK-MERINO', 20, 33.60),
    (16, 1, 'PACK-45L', 24, 222.40),
    (16, 2, 'HAMMOCK-SGL', 6, 62.40),
    (17, 1, 'SOCK-MERINO', 20, 33.60),
    (17, 2, 'PACK-65L', 6, 318.40),
    (18, 1, 'HAMMOCK-SGL', 4, 62.40),
    (18, 2, 'BOOT-HIKE-W', 6, 190.40),
    (18, 3, 'KNIFE-FOLD', 12, 35.20),
    (19, 1, 'JKT-RAIN-M', 20, 142.40),
    (20, 1, 'HAMMOCK-SGL', 6, 62.40),
    (20, 2, 'PACK-65L', 12, 318.40),
    (21, 1, 'TENT-2P-ULT', 30, 302.40),
    (21, 2, 'PACK-45L', 10, 222.40),
    (22, 1, 'SBAG-20F', 12, 254.40),
    (22, 2, 'PAD-INF-R', 12, 110.40),
    (23, 1, 'STOVE-CAN', 20, 62.40),
    (23, 2, 'POT-TI-750', 20, 54.40),
    (24, 1, 'BOTTLE-1L', 50, 28.80),
    (25, 1, 'LAMP-HEAD', 10, 41.60),
    (25, 2, 'FUEL-230', 24, 7.20),
    (26, 1, 'PACK-65L', 4, 318.40),
    (26, 2, 'KNIFE-FOLD', 15, 35.20),
    (27, 1, 'BOOT-HIKE-M', 10, 190.40),
    (27, 2, 'SBAG-20F', 6, 254.40),
    (28, 1, 'PACK-45L', 8, 222.40),
    (28, 2, 'CHAIR-CAMP', 12, 72.00),
    (29, 1, 'JKT-RAIN-M', 15, 142.40),
    (29, 2, 'POT-TI-750', 24, 54.40),
    (30, 1, 'SBAG-40F', 4, 126.40),
    (30, 2, 'JKT-DOWN-L', 10, 238.40),
    (31, 1, 'BOOT-HIKE-M', 6, 190.40),
    (32, 1, 'BOOT-HIKE-W', 10, 190.40),
    (32, 2, 'CHAIR-CAMP', 8, 72.00),
    (33, 1, 'BOTTLE-1L', 6, 28.80),
    (33, 2, 'PACK-DAY-22', 20, 78.40),
    (33, 3, 'PAD-INF-R', 15, 110.40),
    (34, 1, 'SBAG-20F', 20, 254.40),
    (35, 1, 'PACK-DAY-22', 24, 78.40),
    (35, 2, 'KNIFE-FOLD', 8, 35.20),
    (36, 1, 'SBAG-40F', 6, 126.40),
    (36, 2, 'POLE-TREK', 4, 126.40),
    (37, 1, 'PACK-65L', 24, 318.40),
    (37, 2, 'BOTTLE-1L', 24, 28.80),
    (38, 1, 'TENT-4P-FAM', 24, 398.40),
    (38, 2, 'POT-TI-750', 12, 54.40),
    (38, 3, 'BOOT-HIKE-W', 20, 190.40),
    (39, 1, 'JKT-RAIN-M', 4, 142.40),
    (39, 2, 'PACK-DAY-22', 4, 78.40),
    (40, 1, 'HAMMOCK-SGL', 4, 62.40),
    (40, 2, 'SOCK-MERINO', 6, 33.60),
    (40, 3, 'PACK-65L', 8, 318.40);

INSERT INTO order_allocations (order_id, line_no, sku, warehouse, qty) VALUES
    (13, 1, 'LAMP-HEAD', 'WH-EAST', 4),
    (13, 2, 'PACK-DAY-22', 'WH-EAST', 10),
    (14, 1, 'TENT-2P-ULT', 'WH-EAST', 2),
    (14, 2, 'PAD-INF-R', 'WH-EAST', 2),
    (15, 1, 'KNIFE-FOLD', 'WH-EAST', 12),
    (15, 2, 'SOCK-MERINO', 'WH-EAST', 20),
    (16, 1, 'PACK-45L', 'WH-EAST', 24),
    (16, 2, 'HAMMOCK-SGL', 'WH-EAST', 6),
    (17, 1, 'SOCK-MERINO', 'WH-EAST', 20),
    (17, 2, 'PACK-65L', 'WH-EAST', 6),
    (18, 1, 'HAMMOCK-SGL', 'WH-EAST', 4),
    (18, 2, 'BOOT-HIKE-W', 'WH-EAST', 6),
    (18, 3, 'KNIFE-FOLD', 'WH-EAST', 12),
    (19, 1, 'JKT-RAIN-M', 'WH-EAST', 20),
    (20, 1, 'HAMMOCK-SGL', 'WH-EAST', 6),
    (20, 2, 'PACK-65L', 'WH-EAST', 12);

INSERT INTO shipments (order_id, carrier, tracking_number, shipped_at) VALUES
    (1, 'UPS', 'UP3555656321', (CURRENT_DATE - 6)::timestamptz + interval '15 hours'),
    (2, 'FEDEX', 'FE2734202799', (CURRENT_DATE - 20)::timestamptz + interval '15 hours'),
    (3, 'FEDEX', 'FE9760623742', (CURRENT_DATE - 9)::timestamptz + interval '15 hours'),
    (4, 'UPS', 'UP7540301973', (CURRENT_DATE - 16)::timestamptz + interval '15 hours'),
    (5, 'XPO', 'XP8370987661', (CURRENT_DATE - 15)::timestamptz + interval '15 hours'),
    (6, 'FEDEX', 'FE6435772945', (CURRENT_DATE - 17)::timestamptz + interval '15 hours'),
    (7, 'FEDEX', 'FE6583444930', (CURRENT_DATE - 12)::timestamptz + interval '15 hours'),
    (8, 'XPO', 'XP5018948187', (CURRENT_DATE - 10)::timestamptz + interval '15 hours'),
    (9, 'UPS', 'UP5278201677', (CURRENT_DATE - 17)::timestamptz + interval '15 hours'),
    (10, 'UPS', 'UP3309122187', (CURRENT_DATE - 11)::timestamptz + interval '15 hours');

-- One historical, already-approved replenishment so the approval tables are not empty.
INSERT INTO replenishment_proposals (id, sku, qty, reason, proposed_by, status, decided_by, decided_at, decision_note, created_at) VALUES
    (1, 'SOCK-MERINO', 200, 'Seasonal demand increase ahead of fall hiking season', 'claude (actor: jordan.rivera)',
     'APPROVED', 'morgan.chen', now() - interval '9 days', 'Approved for fall season', now() - interval '10 days');

INSERT INTO purchase_orders (po_number, proposal_id, sku, qty, unit_cost, status, approved_by, expected_date, created_at) VALUES
    ('RPO-000001', 1, 'SOCK-MERINO', 200, 21.00, 'RECEIVED', 'morgan.chen', CURRENT_DATE - 2, now() - interval '9 days');

-- Explicit ids were used above, so move each SERIAL sequence past them.
SELECT setval('partners_id_seq', (SELECT max(id) FROM partners));
SELECT setval('orders_id_seq', (SELECT max(id) FROM orders));
SELECT setval('order_allocations_id_seq', (SELECT max(id) FROM order_allocations));
SELECT setval('shipments_id_seq', (SELECT max(id) FROM shipments));
SELECT setval('replenishment_proposals_id_seq', (SELECT max(id) FROM replenishment_proposals));
SELECT setval('purchase_orders_id_seq', (SELECT max(id) FROM purchase_orders));
