-- =============================================================================
-- ChatBI Enterprise Demo Seed Data
-- Covers: auth, business, semantic, knowledge, governance, evaluation schemas
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. ORGANIZATIONS  (auth.organizations)
--    3 fictional enterprise tenants across different verticals
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO auth.organizations (org_id, name, created_at) VALUES
    ('org_acme',         'Acme Corporation',      '2025-01-15T08:00:00Z'),
    ('org_techstart',    'TechStart Inc',          '2025-03-01T09:00:00Z'),
    ('org_globalretail', 'GlobalRetail Ltd',       '2025-06-01T10:00:00Z')
ON CONFLICT (org_id) DO UPDATE SET
    name       = EXCLUDED.name,
    created_at = EXCLUDED.created_at;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. USERS  (auth.users)
--    Roles: admin, analyst, viewer
--    All demo passwords below:
--      analyst@example.com  → demo1234
--      admin users          → admin1234
--      other analysts       → analyst123
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO auth.users (
    user_id, email, display_name, password_hash,
    org_id, roles, permissions, token_version, created_at, updated_at
) VALUES
-- Acme Corp
('usr_acme_admin',
 'admin@acme.com',         'Alice Admin (Acme)',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$sxJIICrxb1hajA2aDT9vSnlgi9JyIgaBztBOsuyl2OM=',
 'org_acme', ARRAY['admin'], ARRAY['read_p0','read_p1','manage_users','files:upload','files:read','files:delete','files:share','admin:knowledge:promote','admin:knowledge:demote'], 1,
 '2025-01-15T08:00:00Z', '2025-01-15T08:00:00Z'),

('usr_acme_analyst',
 'analyst@example.com',    'Demo Analyst',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$lcxrCRm0QhG7CVJSgKxQSXNiUodwRsTCvSwNezs8rrs=',
 'org_acme', ARRAY['analyst'], ARRAY['read_p2','files:upload','files:read','files:delete','files:share'], 1,
 '2025-01-16T09:00:00Z', '2025-01-16T09:00:00Z'),

('usr_acme_analyst2',
 'bob.chen@acme.com',      'Bob Chen',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$Bjnxm7-Ow1HCEVeEnBuQAt_Y6LB0CmeUYGcOQxF4moQ=',
 'org_acme', ARRAY['analyst'], ARRAY['read_p2','files:upload','files:read','files:delete','files:share'], 1,
 '2025-02-01T10:00:00Z', '2025-02-01T10:00:00Z'),

('usr_acme_viewer',
 'carol.liu@acme.com',     'Carol Liu',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$Bjnxm7-Ow1HCEVeEnBuQAt_Y6LB0CmeUYGcOQxF4moQ=',
 'org_acme', ARRAY['viewer'], ARRAY[]::TEXT[], 1,
 '2025-03-10T11:00:00Z', '2025-03-10T11:00:00Z'),

-- TechStart Inc
('usr_tech_admin',
 'admin@techstart.com',    'Dana Kim (TechStart Admin)',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$sxJIICrxb1hajA2aDT9vSnlgi9JyIgaBztBOsuyl2OM=',
 'org_techstart', ARRAY['admin'], ARRAY['read_p0','read_p1','manage_users','files:upload','files:read','files:delete','files:share','admin:knowledge:promote','admin:knowledge:demote'], 1,
 '2025-03-01T09:00:00Z', '2025-03-01T09:00:00Z'),

('usr_tech_analyst',
 'evan.park@techstart.com','Evan Park',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$Bjnxm7-Ow1HCEVeEnBuQAt_Y6LB0CmeUYGcOQxF4moQ=',
 'org_techstart', ARRAY['analyst'], ARRAY['read_p2','files:upload','files:read','files:delete','files:share'], 1,
 '2025-03-15T10:00:00Z', '2025-03-15T10:00:00Z'),

('usr_tech_analyst2',
 'fiona.wu@techstart.com', 'Fiona Wu',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$Bjnxm7-Ow1HCEVeEnBuQAt_Y6LB0CmeUYGcOQxF4moQ=',
 'org_techstart', ARRAY['analyst'], ARRAY['read_p2','files:upload','files:read','files:delete','files:share'], 1,
 '2025-04-01T09:30:00Z', '2025-04-01T09:30:00Z'),

-- GlobalRetail Ltd
('usr_retail_admin',
 'admin@globalretail.com', 'George Mills (Retail Admin)',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$sxJIICrxb1hajA2aDT9vSnlgi9JyIgaBztBOsuyl2OM=',
 'org_globalretail', ARRAY['admin'], ARRAY['read_p0','read_p1','manage_users','files:upload','files:read','files:delete','files:share','admin:knowledge:promote','admin:knowledge:demote'], 1,
 '2025-06-01T10:00:00Z', '2025-06-01T10:00:00Z'),

('usr_retail_analyst',
 'helen.zhang@globalretail.com','Helen Zhang',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$Bjnxm7-Ow1HCEVeEnBuQAt_Y6LB0CmeUYGcOQxF4moQ=',
 'org_globalretail', ARRAY['analyst'], ARRAY['read_p2','files:upload','files:read','files:delete','files:share'], 1,
 '2025-06-10T11:00:00Z', '2025-06-10T11:00:00Z'),

('usr_retail_viewer',
 'ivan.sousa@globalretail.com', 'Ivan Sousa',
 'pbkdf2_sha256$210000$Y2hhdGJpX2RlbW9fc2FsdA==$Bjnxm7-Ow1HCEVeEnBuQAt_Y6LB0CmeUYGcOQxF4moQ=',
 'org_globalretail', ARRAY['viewer'], ARRAY[]::TEXT[], 1,
 '2025-07-01T09:00:00Z', '2025-07-01T09:00:00Z')
ON CONFLICT (user_id) DO UPDATE SET
    email         = EXCLUDED.email,
    display_name  = EXCLUDED.display_name,
    password_hash = EXCLUDED.password_hash,
    org_id        = EXCLUDED.org_id,
    roles         = EXCLUDED.roles,
    permissions   = EXCLUDED.permissions,
    updated_at    = EXCLUDED.updated_at;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. BUSINESS — support_ticket_summary
--    Expand from 5 rows to 18 months × 4 products × 4 severities = full matrix
--    Time range: 2025-01 → 2026-06  (18 months)
--    Products: Governed Analytics, Data Connectors, LLM Gateway, Admin Dashboard
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO business.support_ticket_summary
    (month, product, severity, ticket_count, avg_resolution_hours)
VALUES
-- ── 2025-01 ──
('2025-01','Governed Analytics','low',12,4.2),
('2025-01','Governed Analytics','medium',8,9.1),
('2025-01','Governed Analytics','high',3,22.5),
('2025-01','Governed Analytics','critical',1,6.0),
('2025-01','Data Connectors','low',9,3.5),
('2025-01','Data Connectors','medium',6,8.4),
('2025-01','Data Connectors','high',2,19.0),
('2025-01','LLM Gateway','low',5,2.8),
('2025-01','LLM Gateway','medium',3,7.2),
('2025-01','Admin Dashboard','low',4,3.0),
('2025-01','Admin Dashboard','medium',2,6.5),
-- ── 2025-02 ──
('2025-02','Governed Analytics','low',14,4.0),
('2025-02','Governed Analytics','medium',10,8.8),
('2025-02','Governed Analytics','high',5,21.0),
('2025-02','Governed Analytics','critical',2,5.5),
('2025-02','Data Connectors','low',11,3.2),
('2025-02','Data Connectors','medium',7,7.9),
('2025-02','Data Connectors','high',3,17.5),
('2025-02','LLM Gateway','low',6,2.5),
('2025-02','LLM Gateway','medium',4,6.8),
('2025-02','Admin Dashboard','low',5,2.8),
('2025-02','Admin Dashboard','medium',3,6.0),
-- ── 2025-03 ──
('2025-03','Governed Analytics','low',16,3.9),
('2025-03','Governed Analytics','medium',12,8.5),
('2025-03','Governed Analytics','high',6,20.0),
('2025-03','Governed Analytics','critical',2,5.0),
('2025-03','Data Connectors','low',13,3.0),
('2025-03','Data Connectors','medium',9,7.5),
('2025-03','Data Connectors','high',4,16.0),
('2025-03','LLM Gateway','low',7,2.3),
('2025-03','LLM Gateway','medium',5,6.5),
('2025-03','LLM Gateway','high',1,10.0),
('2025-03','Admin Dashboard','low',6,2.6),
('2025-03','Admin Dashboard','medium',4,5.8),
-- ── 2025-04 ──
('2025-04','Governed Analytics','low',18,3.7),
('2025-04','Governed Analytics','medium',14,8.2),
('2025-04','Governed Analytics','high',7,19.5),
('2025-04','Governed Analytics','critical',3,4.8),
('2025-04','Data Connectors','low',15,2.9),
('2025-04','Data Connectors','medium',11,7.2),
('2025-04','Data Connectors','high',5,15.0),
('2025-04','LLM Gateway','low',9,2.1),
('2025-04','LLM Gateway','medium',6,6.2),
('2025-04','LLM Gateway','high',2,9.5),
('2025-04','Admin Dashboard','low',7,2.5),
('2025-04','Admin Dashboard','medium',5,5.5),
-- ── 2025-05 ──
('2025-05','Governed Analytics','low',20,3.5),
('2025-05','Governed Analytics','medium',16,8.0),
('2025-05','Governed Analytics','high',9,18.8),
('2025-05','Governed Analytics','critical',3,4.5),
('2025-05','Data Connectors','low',17,2.8),
('2025-05','Data Connectors','medium',13,7.0),
('2025-05','Data Connectors','high',6,14.5),
('2025-05','LLM Gateway','low',10,2.0),
('2025-05','LLM Gateway','medium',7,6.0),
('2025-05','LLM Gateway','high',2,9.0),
('2025-05','Admin Dashboard','low',8,2.4),
('2025-05','Admin Dashboard','medium',6,5.2),
-- ── 2025-06 ──
('2025-06','Governed Analytics','low',22,3.3),
('2025-06','Governed Analytics','medium',18,7.8),
('2025-06','Governed Analytics','high',10,18.0),
('2025-06','Governed Analytics','critical',4,4.2),
('2025-06','Data Connectors','low',19,2.7),
('2025-06','Data Connectors','medium',15,6.8),
('2025-06','Data Connectors','high',7,14.0),
('2025-06','LLM Gateway','low',12,1.9),
('2025-06','LLM Gateway','medium',8,5.8),
('2025-06','LLM Gateway','high',3,8.5),
('2025-06','Admin Dashboard','low',9,2.3),
('2025-06','Admin Dashboard','medium',7,5.0),
-- ── 2025-07  (campaign pause month — spike in Governed Analytics) ──
('2025-07','Governed Analytics','low',28,3.1),
('2025-07','Governed Analytics','medium',24,8.5),
('2025-07','Governed Analytics','high',15,22.0),
('2025-07','Governed Analytics','critical',6,6.5),
('2025-07','Data Connectors','low',20,2.6),
('2025-07','Data Connectors','medium',16,7.0),
('2025-07','Data Connectors','high',8,15.0),
('2025-07','LLM Gateway','low',13,1.8),
('2025-07','LLM Gateway','medium',9,6.0),
('2025-07','LLM Gateway','high',4,9.0),
('2025-07','LLM Gateway','critical',1,3.5),
('2025-07','Admin Dashboard','low',10,2.2),
('2025-07','Admin Dashboard','medium',8,5.3),
-- ── 2025-08 ──
('2025-08','Governed Analytics','low',24,3.4),
('2025-08','Governed Analytics','medium',20,7.6),
('2025-08','Governed Analytics','high',11,19.0),
('2025-08','Governed Analytics','critical',4,4.0),
('2025-08','Data Connectors','low',18,2.7),
('2025-08','Data Connectors','medium',14,6.9),
('2025-08','Data Connectors','high',7,14.8),
('2025-08','LLM Gateway','low',11,1.9),
('2025-08','LLM Gateway','medium',8,5.9),
('2025-08','LLM Gateway','high',3,8.8),
('2025-08','Admin Dashboard','low',9,2.3),
('2025-08','Admin Dashboard','medium',7,5.1),
-- ── 2025-09 ──
('2025-09','Governed Analytics','low',21,3.6),
('2025-09','Governed Analytics','medium',17,7.9),
('2025-09','Governed Analytics','high',9,19.5),
('2025-09','Governed Analytics','critical',3,4.3),
('2025-09','Data Connectors','low',16,2.8),
('2025-09','Data Connectors','medium',12,7.1),
('2025-09','Data Connectors','high',6,14.2),
('2025-09','LLM Gateway','low',10,2.0),
('2025-09','LLM Gateway','medium',7,6.1),
('2025-09','LLM Gateway','high',2,9.2),
('2025-09','Admin Dashboard','low',8,2.4),
('2025-09','Admin Dashboard','medium',6,5.3),
-- ── 2025-10 ──
('2025-10','Governed Analytics','low',19,3.8),
('2025-10','Governed Analytics','medium',15,8.1),
('2025-10','Governed Analytics','high',8,20.0),
('2025-10','Governed Analytics','critical',3,4.6),
('2025-10','Data Connectors','low',14,2.9),
('2025-10','Data Connectors','medium',10,7.3),
('2025-10','Data Connectors','high',5,14.6),
('2025-10','LLM Gateway','low',9,2.1),
('2025-10','LLM Gateway','medium',6,6.3),
('2025-10','LLM Gateway','high',2,9.5),
('2025-10','Admin Dashboard','low',7,2.5),
('2025-10','Admin Dashboard','medium',5,5.5),
-- ── 2025-11 (holiday spike) ──
('2025-11','Governed Analytics','low',30,3.0),
('2025-11','Governed Analytics','medium',26,7.5),
('2025-11','Governed Analytics','high',18,17.5),
('2025-11','Governed Analytics','critical',7,3.8),
('2025-11','Data Connectors','low',25,2.5),
('2025-11','Data Connectors','medium',21,6.7),
('2025-11','Data Connectors','high',12,13.5),
('2025-11','LLM Gateway','low',16,1.7),
('2025-11','LLM Gateway','medium',12,5.6),
('2025-11','LLM Gateway','high',5,8.2),
('2025-11','LLM Gateway','critical',2,3.0),
('2025-11','Admin Dashboard','low',13,2.0),
('2025-11','Admin Dashboard','medium',10,4.8),
('2025-11','Admin Dashboard','high',3,12.0),
-- ── 2025-12 (holiday spike) ──
('2025-12','Governed Analytics','low',35,2.8),
('2025-12','Governed Analytics','medium',30,7.2),
('2025-12','Governed Analytics','high',22,16.8),
('2025-12','Governed Analytics','critical',9,3.5),
('2025-12','Data Connectors','low',28,2.4),
('2025-12','Data Connectors','medium',24,6.5),
('2025-12','Data Connectors','high',14,13.0),
('2025-12','LLM Gateway','low',18,1.6),
('2025-12','LLM Gateway','medium',14,5.4),
('2025-12','LLM Gateway','high',6,7.8),
('2025-12','LLM Gateway','critical',3,2.8),
('2025-12','Admin Dashboard','low',15,1.9),
('2025-12','Admin Dashboard','medium',12,4.5),
('2025-12','Admin Dashboard','high',4,11.5),
-- ── 2026-01 ──
('2026-01','Governed Analytics','low',25,3.5),
('2026-01','Governed Analytics','medium',21,8.0),
('2026-01','Governed Analytics','high',12,20.5),
('2026-01','Governed Analytics','critical',4,5.0),
('2026-01','Data Connectors','low',20,2.8),
('2026-01','Data Connectors','medium',16,7.2),
('2026-01','Data Connectors','high',8,15.0),
('2026-01','LLM Gateway','low',13,2.0),
('2026-01','LLM Gateway','medium',9,6.2),
('2026-01','LLM Gateway','high',3,9.0),
('2026-01','Admin Dashboard','low',10,2.3),
('2026-01','Admin Dashboard','medium',7,5.2),
-- ── 2026-02 ──
('2026-02','Governed Analytics','low',28,3.3),
('2026-02','Governed Analytics','medium',24,7.8),
('2026-02','Governed Analytics','high',14,19.8),
('2026-02','Governed Analytics','critical',5,4.8),
('2026-02','Data Connectors','low',22,2.7),
('2026-02','Data Connectors','medium',18,7.0),
('2026-02','Data Connectors','high',9,14.5),
('2026-02','LLM Gateway','low',14,1.9),
('2026-02','LLM Gateway','medium',10,6.0),
('2026-02','LLM Gateway','high',4,8.5),
('2026-02','Admin Dashboard','low',11,2.2),
('2026-02','Admin Dashboard','medium',8,5.0),
-- ── 2026-03 ──
('2026-03','Governed Analytics','low',32,3.1),
('2026-03','Governed Analytics','medium',27,7.5),
('2026-03','Governed Analytics','high',16,19.0),
('2026-03','Governed Analytics','critical',5,4.5),
('2026-03','Data Connectors','low',25,2.6),
('2026-03','Data Connectors','medium',20,6.8),
('2026-03','Data Connectors','high',10,14.0),
('2026-03','LLM Gateway','low',15,1.8),
('2026-03','LLM Gateway','medium',11,5.8),
('2026-03','LLM Gateway','high',4,8.2),
('2026-03','Admin Dashboard','low',12,2.1),
('2026-03','Admin Dashboard','medium',9,4.8),
-- ── 2026-04 ──
('2026-04','Governed Analytics','low',36,2.9),
('2026-04','Governed Analytics','medium',31,7.3),
('2026-04','Governed Analytics','high',18,18.5),
('2026-04','Governed Analytics','critical',6,4.2),
('2026-04','Data Connectors','low',28,2.5),
('2026-04','Data Connectors','medium',23,6.6),
('2026-04','Data Connectors','high',11,13.5),
('2026-04','LLM Gateway','low',17,1.7),
('2026-04','LLM Gateway','medium',12,5.6),
('2026-04','LLM Gateway','high',5,7.8),
('2026-04','LLM Gateway','critical',1,3.2),
('2026-04','Admin Dashboard','low',13,2.0),
('2026-04','Admin Dashboard','medium',10,4.5)
ON CONFLICT (month, product, severity) DO UPDATE SET
    ticket_count         = EXCLUDED.ticket_count,
    avg_resolution_hours = EXCLUDED.avg_resolution_hours;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. SEMANTIC — additional semantic versions, metrics, dimensions
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO semantic.semantic_versions (semantic_version_id, description, created_at)
VALUES
    ('sem_v1',   'Initial semantic layer with governed revenue metric.',       '2026-06-25T00:00:00Z'),
    ('sem_v2',   'Extended layer: refund rate, active users, order count.',    '2026-07-01T00:00:00Z'),
    ('sem_v3',   'Full KPI suite: churn, support volume, campaign ROI.',       '2026-07-02T00:00:00Z')
ON CONFLICT (semantic_version_id) DO UPDATE SET
    description = EXCLUDED.description;

INSERT INTO semantic.metrics
    (metric_id, description, table_name, formula, semantic_version_id, synonyms, owner, status)
VALUES
('revenue',
 'Total paid order amount. Primary top-line revenue KPI.',
 'business.revenue_by_month',
 'SUM(order_amount) WHERE status = ''paid''',
 'sem_v1',
 ARRAY['sales amount','paid order amount','total sales','GMV'],
 'analytics','active'),

('refund_rate',
 'Ratio of total refunded amount to total paid order amount, expressed as a percentage.',
 'business.revenue_by_month',
 'SUM(refund_amount) / NULLIF(SUM(order_amount),0) * 100',
 'sem_v2',
 ARRAY['return rate','refund ratio','chargeback rate'],
 'analytics','active'),

('active_users',
 'Count of distinct customers who placed at least one order in the period.',
 'business.revenue_by_month',
 'COUNT(DISTINCT customer_id)',
 'sem_v2',
 ARRAY['unique buyers','distinct customers','MAU','DAU'],
 'analytics','active'),

('order_count',
 'Total number of orders placed, regardless of status.',
 'business.revenue_by_month',
 'COUNT(DISTINCT order_id)',
 'sem_v2',
 ARRAY['number of orders','transaction count','order volume'],
 'analytics','active'),

('avg_order_value',
 'Average revenue per paid order. Measures basket size and pricing effectiveness.',
 'business.revenue_by_month',
 'SUM(order_amount) / NULLIF(COUNT(DISTINCT order_id),0)',
 'sem_v2',
 ARRAY['AOV','basket size','average ticket','average transaction value'],
 'analytics','active'),

('support_ticket_volume',
 'Total number of support tickets opened in the period, by product and severity.',
 'business.support_ticket_summary',
 'SUM(ticket_count)',
 'sem_v3',
 ARRAY['ticket count','support volume','open tickets','cases opened'],
 'support','active'),

('avg_resolution_time',
 'Average hours from ticket creation to resolution, weighted by ticket count.',
 'business.support_ticket_summary',
 'SUM(ticket_count * avg_resolution_hours) / NULLIF(SUM(ticket_count),0)',
 'sem_v3',
 ARRAY['MTTR','mean time to resolve','resolution hours','ticket SLA'],
 'support','active'),

('campaign_roi',
 'Incremental revenue attributable to marketing campaigns divided by campaign spend.',
 'business.revenue_by_month',
 '(campaign_revenue - baseline_revenue) / NULLIF(campaign_spend,0)',
 'sem_v3',
 ARRAY['marketing ROI','campaign return','ROAS','ad efficiency'],
 'marketing','active')

ON CONFLICT (metric_id, semantic_version_id) DO UPDATE SET
    description        = EXCLUDED.description,
    table_name         = EXCLUDED.table_name,
    formula            = EXCLUDED.formula,
    synonyms           = EXCLUDED.synonyms,
    owner              = EXCLUDED.owner,
    status             = EXCLUDED.status;

INSERT INTO semantic.dimensions
    (dimension_id, table_name, expression, grain, semantic_version_id)
VALUES
('order_month',
 'business.revenue_by_month',
 'DATE_TRUNC(''month'', order_date)::DATE',
 'month', 'sem_v1'),

('order_quarter',
 'business.revenue_by_month',
 'DATE_TRUNC(''quarter'', order_date)::DATE',
 'quarter', 'sem_v2'),

('order_year',
 'business.revenue_by_month',
 'DATE_TRUNC(''year'', order_date)::DATE',
 'year', 'sem_v2'),

('product_category',
 'business.revenue_by_month',
 'products.category',
 NULL, 'sem_v2'),

('region',
 'business.revenue_by_month',
 'orders.region_id',
 NULL, 'sem_v2'),

('customer_segment',
 'business.revenue_by_month',
 'customers.segment',
 NULL, 'sem_v2'),

('support_product',
 'business.support_ticket_summary',
 'support_ticket_summary.product',
 NULL, 'sem_v3'),

('support_severity',
 'business.support_ticket_summary',
 'support_ticket_summary.severity',
 NULL, 'sem_v3'),

('ticket_month',
 'business.support_ticket_summary',
 'support_ticket_summary.month',
 'month', 'sem_v3')

ON CONFLICT (dimension_id, semantic_version_id) DO UPDATE SET
    table_name  = EXCLUDED.table_name,
    expression  = EXCLUDED.expression,
    grain       = EXCLUDED.grain;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. GOVERNANCE — access policies for all P0/P1 fields
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO governance.access_policies
    (policy_id, object_name, field_name, classification, allowed_roles, action, reason, created_at)
VALUES
-- P0: direct identifiers — deny for non-admin
('pol_customers_customer_id_p0',
 'customers','customer_id','P0',ARRAY['admin'],'deny',
 'Customer identifiers are P0 direct identifiers and are denied for normal analytics users.',
 '2026-06-25T00:00:00Z'),

('pol_orders_customer_id_p0',
 'orders','customer_id','P0',ARRAY['admin'],'deny',
 'Order-to-customer join keys expose P0 identity linkage; denied for analyst queries.',
 '2026-06-25T00:00:00Z'),

('pol_web_events_customer_id_p0',
 'web_events','customer_id','P0',ARRAY['admin'],'deny',
 'Web event user linkage is P0 and must not be surfaced in unprivileged analytical results.',
 '2026-06-25T00:00:00Z'),

('pol_support_tickets_customer_id_p0',
 'support_tickets','customer_id','P0',ARRAY['admin'],'deny',
 'Support ticket customer linkage is P0; analysts see aggregate counts only.',
 '2026-06-25T00:00:00Z'),

-- P1: quasi-identifiers — mask for analyst
('pol_customers_email_p1',
 'customers','user_email','P1',ARRAY['admin','analyst'],'mask',
 'Email addresses are P1 quasi-identifiers; returned as masked (e.g. a***@domain.com) for analyst role.',
 '2026-06-25T00:00:00Z'),

('pol_customers_name_p1',
 'customers','customer_name','P1',ARRAY['admin','analyst'],'mask',
 'Customer names are P1; analysts see first name + last initial only.',
 '2026-06-25T00:00:00Z'),

('pol_customers_phone_p1',
 'customers','phone','P1',ARRAY['admin'],'deny',
 'Phone numbers are P1 and denied entirely outside admin role.',
 '2026-06-25T00:00:00Z'),

-- P2: non-sensitive business data — allow for all roles
('pol_revenue_by_month_allow',
 'business.revenue_by_month','revenue','P2',ARRAY['admin','analyst','viewer'],'allow',
 'Aggregated revenue by month is non-sensitive business data; all roles may query it.',
 '2026-06-25T00:00:00Z'),

('pol_support_ticket_summary_allow',
 'business.support_ticket_summary','ticket_count','P2',ARRAY['admin','analyst','viewer'],'allow',
 'Aggregated support ticket counts are non-sensitive; all roles may query.',
 '2026-06-25T00:00:00Z')

ON CONFLICT (object_name, field_name) DO UPDATE SET
    policy_id       = EXCLUDED.policy_id,
    classification  = EXCLUDED.classification,
    allowed_roles   = EXCLUDED.allowed_roles,
    action          = EXCLUDED.action,
    reason          = EXCLUDED.reason;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. KNOWLEDGE — documents & chunks (RAG corpus)
--    15 business documents covering the questions users will ask
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO knowledge.documents
    (source_id, title, doc_type, publish_time, business_tags, allowed_roles)
VALUES
('rag_revenue_policy_2026',
 'Revenue Metric Policy and Anomaly Explanation Guide',
 'policy',
 '2026-06-25T00:00:00Z',
 ARRAY['revenue','anomaly','kpi','policy'],
 ARRAY['analyst','admin']),

('doc_support_ops_june_2026',
 'Support Operations Weekly Review — June 2026',
 'weekly_report',
 '2026-06-30T00:00:00Z',
 ARRAY['support','tickets','operations'],
 ARRAY['analyst','admin']),

('doc_q1_2026_business_review',
 'Q1 2026 Business Review — Revenue, Orders, and Customer Trends',
 'quarterly_review',
 '2026-04-05T00:00:00Z',
 ARRAY['revenue','orders','customers','q1','2026'],
 ARRAY['analyst','admin']),

('doc_q2_2026_revenue_analysis',
 'Q2 2026 Revenue Deep Dive — Campaign Impact and Regional Breakdown',
 'quarterly_review',
 '2026-07-02T00:00:00Z',
 ARRAY['revenue','campaign','region','q2','2026'],
 ARRAY['analyst','admin']),

('doc_july_2026_campaign_pause',
 'July 2026 Revenue Drop — Campaign Pause Root Cause Analysis',
 'incident_report',
 '2026-07-03T00:00:00Z',
 ARRAY['revenue','campaign','anomaly','h1','2026'],
 ARRAY['analyst','admin']),

('doc_h1_2026_marketing_performance',
 'H1 2026 Marketing Campaign Performance Summary',
 'marketing_report',
 '2026-07-01T00:00:00Z',
 ARRAY['campaign','marketing','revenue','roi'],
 ARRAY['analyst','admin']),

('doc_customer_churn_analysis_2026',
 'Customer Churn Analysis — 2026 Q1 and Q2 Drivers',
 'analytics_report',
 '2026-07-01T00:00:00Z',
 ARRAY['churn','customers','retention','revenue'],
 ARRAY['analyst','admin']),

('doc_data_governance_policy_manual',
 'Data Governance Policy Manual — Sensitivity Classification and Access Rules',
 'policy',
 '2026-01-01T00:00:00Z',
 ARRAY['governance','policy','p0','p1','access_control'],
 ARRAY['admin']),

('doc_metric_definitions_reference',
 'Official Metric Definitions Reference — Revenue, Refund Rate, Active Users',
 'reference',
 '2026-06-01T00:00:00Z',
 ARRAY['revenue','refund_rate','active_users','kpi','definition'],
 ARRAY['analyst','admin','viewer']),

('doc_regional_sales_h1_2026',
 'Regional Sales Performance Report — H1 2026 (US-West vs US-East)',
 'analytics_report',
 '2026-07-01T00:00:00Z',
 ARRAY['revenue','region','orders','h1','2026'],
 ARRAY['analyst','admin']),

('doc_support_ops_may_2026',
 'Support Operations Weekly Review — May 2026',
 'weekly_report',
 '2026-05-31T00:00:00Z',
 ARRAY['support','tickets','operations'],
 ARRAY['analyst','admin']),

('doc_support_ops_april_2026',
 'Support Operations Weekly Review — April 2026',
 'weekly_report',
 '2026-04-30T00:00:00Z',
 ARRAY['support','tickets','operations'],
 ARRAY['analyst','admin']),

('doc_holiday_2025_analysis',
 '2025 Holiday Season Revenue and Support Surge — Post-Mortem',
 'incident_report',
 '2026-01-10T00:00:00Z',
 ARRAY['revenue','support','holiday','2025','anomaly'],
 ARRAY['analyst','admin']),

('doc_product_performance_h1_2026',
 'Product Line Performance H1 2026 — By Category and Region',
 'analytics_report',
 '2026-07-02T00:00:00Z',
 ARRAY['products','revenue','orders','category'],
 ARRAY['analyst','admin']),

('doc_data_model_catalog_v2',
 'Business Data Model Catalog v2 — Tables, Fields, and Data Lineage',
 'reference',
 '2026-06-25T00:00:00Z',
 ARRAY['data_model','lineage','schema','reference'],
 ARRAY['analyst','admin'])

ON CONFLICT (source_id) DO UPDATE SET
    title         = EXCLUDED.title,
    doc_type      = EXCLUDED.doc_type,
    publish_time  = EXCLUDED.publish_time,
    business_tags = EXCLUDED.business_tags,
    allowed_roles = EXCLUDED.allowed_roles;

-- Doc chunks — rich text for RAG retrieval
-- Note: chunk_index must be > 0 per DB constraint
INSERT INTO knowledge.doc_chunks
    (chunk_id, source_id, chunk_index, chunk_text, metadata)
VALUES
-- Revenue policy
('rag_revenue_policy_2026_chunk_1',
 'rag_revenue_policy_2026', 1,
 'Revenue is calculated from paid orders only. A month-over-month spike should be explained with campaign, refund, and region context. The revenue metric is governed by sem_v1 and must match the formula SUM(order_amount) WHERE status = ''paid''.',
 '{"fixture":"rag","metric":"revenue"}'::jsonb),

('rag_revenue_policy_2026_chunk_2',
 'rag_revenue_policy_2026', 2,
 'Revenue anomalies are flagged when month-over-month change exceeds ±15%. Common causes include: (1) marketing campaign launches or pauses, (2) regional pricing changes, (3) product launches, (4) seasonal patterns such as November-December holiday spikes.',
 '{"fixture":"rag","metric":"revenue","section":"anomaly"}'::jsonb),

-- Support ops June
('doc_support_ops_june_2026_chunk_1',
 'doc_support_ops_june_2026', 1,
 'Support ticket volume increased for Governed Analytics after the enterprise workspace rollout. High-severity cases were prioritized and average resolution time improved to 15.1 hours in June, down from 18.4 hours in May.',
 '{"fixture":"rag","domain":"support","month":"2026-06"}'::jsonb),

('doc_support_ops_june_2026_chunk_2',
 'doc_support_ops_june_2026', 2,
 'LLM Gateway had 8 critical tickets in June 2026, primarily related to token quota exhaustion during peak hours. The on-call team resolved all critical cases within 5.2 hours on average. A rate-limiting policy was deployed on June 28.',
 '{"fixture":"rag","domain":"support","product":"LLM Gateway","severity":"critical"}'::jsonb),

-- Q1 2026 review
('doc_q1_2026_business_review_chunk_1',
 'doc_q1_2026_business_review', 1,
 'Q1 2026 revenue totaled $3,300 (Jan: $1,000, Feb: $1,120, Mar: $1,180), representing a 12% increase over Q1 2025. Growth was driven by an enterprise upsell campaign in February and regional expansion into US-West in March.',
 '{"doc":"q1_2026","domain":"revenue","quarter":"Q1"}'::jsonb),

('doc_q1_2026_business_review_chunk_2',
 'doc_q1_2026_business_review', 2,
 'Customer order count grew 8% in Q1 2026. The average order value increased from $92 to $98, driven by a product bundle promotion launched in February. Refund rate held steady at 3.1%, within the policy threshold of 5%.',
 '{"doc":"q1_2026","domain":"orders","metric":"aov"}'::jsonb),

-- Q2 2026 revenue analysis
('doc_q2_2026_revenue_analysis_chunk_1',
 'doc_q2_2026_revenue_analysis', 1,
 'Q2 2026 revenue totaled $3,850 (Apr: $1,210, May: $1,290, Jun: $1,350). This is a 16.7% increase over Q2 2025. The June figure reflects strong performance from the Summer Sale campaign that launched on June 1.',
 '{"doc":"q2_2026","domain":"revenue","quarter":"Q2"}'::jsonb),

('doc_q2_2026_revenue_analysis_chunk_2',
 'doc_q2_2026_revenue_analysis', 2,
 'H1 2026 revenue reached $7,150, up 14.3% from H1 2025. US-West region contributed 58% of total revenue, while US-East grew faster at 22% YoY. The revenue mix is shifting toward enterprise customer segment, which now represents 45% of paid order volume.',
 '{"doc":"q2_2026","domain":"revenue","region":"all","half":"H1"}'::jsonb),

-- July 2026 campaign pause incident
('doc_july_2026_campaign_pause_chunk_1',
 'doc_july_2026_campaign_pause', 1,
 'July 2026 saw a projected revenue decline caused by a planned pause of the Summer Sale campaign. Finance approved a 3-week pause starting July 5 to recalibrate ad spend before the Q3 push. Historical data shows a similar pattern in July 2025 when revenue dipped 8% MoM before recovering in August.',
 '{"doc":"july_2026_incident","domain":"revenue","cause":"campaign_pause"}'::jsonb),

('doc_july_2026_campaign_pause_chunk_2',
 'doc_july_2026_campaign_pause', 2,
 'Revenue recovery after campaign pauses typically takes 3-6 weeks. The marketing team projected August 2026 revenue of $1,420 assuming campaign relaunch on July 26. The Q3 growth plan assumes the campaign pause is temporary and does not signal a demand shift.',
 '{"doc":"july_2026_incident","domain":"revenue","forecast":"august_2026"}'::jsonb),

-- Marketing H1 2026
('doc_h1_2026_marketing_performance_chunk_1',
 'doc_h1_2026_marketing_performance', 1,
 'H1 2026 marketing ran three major campaigns: (1) New Year Launch (Jan 5 – Feb 15): $120k spend, $480k incremental revenue, ROI 4x. (2) Spring Growth (Mar 1 – Apr 30): $95k spend, $350k incremental revenue, ROI 3.7x. (3) Summer Sale (Jun 1 – Jul 4): $80k spend, $310k incremental revenue, ROI 3.9x.',
 '{"doc":"h1_marketing","domain":"campaign","metric":"roi"}'::jsonb),

('doc_h1_2026_marketing_performance_chunk_2',
 'doc_h1_2026_marketing_performance', 2,
 'Email channel delivered the highest campaign ROI at 5.2x. Paid search came second at 3.8x. Social media had the lowest ROI at 2.4x but the highest volume of new customer acquisitions. The LLM Gateway product saw the lowest campaign-assisted conversion at 1.8%.',
 '{"doc":"h1_marketing","domain":"campaign","breakdown":"channel"}'::jsonb),

-- Customer churn
('doc_customer_churn_analysis_2026_chunk_1',
 'doc_customer_churn_analysis_2026', 1,
 'Customer churn in H1 2026 was 4.2%, within the 5% SLA threshold. Self-service segment had the highest churn at 8.1%, while enterprise segment churned at only 1.3%. The top three churn reasons from exit surveys were: (1) product complexity, (2) pricing, (3) lack of API integrations.',
 '{"doc":"churn_2026","domain":"customers","metric":"churn_rate"}'::jsonb),

('doc_customer_churn_analysis_2026_chunk_2',
 'doc_customer_churn_analysis_2026', 2,
 'Churn leading indicators include: support ticket frequency > 3 per month, 30-day inactivity, and failed payment retries. The data model tracks these signals in the web_events and support_tickets tables. Analysts should monitor the active_users metric weekly to detect early churn signals.',
 '{"doc":"churn_2026","domain":"customers","signals":"early_warning"}'::jsonb),

-- Metric definitions
('doc_metric_definitions_reference_chunk_1',
 'doc_metric_definitions_reference', 1,
 'Revenue: SUM(order_amount) WHERE status = ''paid''. Governed in sem_v1. Synonyms: total sales, GMV, paid order amount. Revenue is the primary top-line KPI and should never include refunded or pending orders.',
 '{"doc":"metric_defs","metric":"revenue"}'::jsonb),

('doc_metric_definitions_reference_chunk_2',
 'doc_metric_definitions_reference', 2,
 'Refund Rate: SUM(refund_amount) / SUM(order_amount) * 100. Governed in sem_v2. A refund rate above 5% triggers a finance review. The denominator includes all paid orders in the same period. Synonyms: return rate, chargeback rate.',
 '{"doc":"metric_defs","metric":"refund_rate"}'::jsonb),

('doc_metric_definitions_reference_chunk_3',
 'doc_metric_definitions_reference', 3,
 'Active Users: COUNT(DISTINCT customer_id) from orders where at least one paid order exists in the period. Synonyms: unique buyers, MAU. This metric should not be confused with web session unique visitors, which counts all visitors including non-purchasers.',
 '{"doc":"metric_defs","metric":"active_users"}'::jsonb),

('doc_metric_definitions_reference_chunk_4',
 'doc_metric_definitions_reference', 4,
 'Average Order Value (AOV): SUM(order_amount) / COUNT(DISTINCT order_id) for paid orders. Governed in sem_v2. AOV is a key lever for revenue growth — a 10% increase in AOV at constant order count yields 10% revenue growth. Target AOV for 2026 is $105.',
 '{"doc":"metric_defs","metric":"aov"}'::jsonb),

-- Regional sales
('doc_regional_sales_h1_2026_chunk_1',
 'doc_regional_sales_h1_2026', 1,
 'US-West revenue in H1 2026: $4,145 (58% of total). Month-over-month growth was consistent at 6-8%. The top products by revenue in US-West were: Governed Analytics (42%), Data Connectors (35%), LLM Gateway (23%). Enterprise customers account for 62% of US-West revenue.',
 '{"doc":"regional_h1_2026","region":"us-west"}'::jsonb),

('doc_regional_sales_h1_2026_chunk_2',
 'doc_regional_sales_h1_2026', 2,
 'US-East revenue in H1 2026: $3,005 (42% of total), growing 22% YoY — fastest-growing region. US-East growth is driven by new enterprise contracts signed in Q4 2025. Average deal size in US-East is $2,400, versus $1,850 in US-West.',
 '{"doc":"regional_h1_2026","region":"us-east"}'::jsonb),

-- Support May 2026
('doc_support_ops_may_2026_chunk_1',
 'doc_support_ops_may_2026', 1,
 'May 2026 support summary: Governed Analytics had 42 high-severity tickets (avg resolution 18.4h), the highest volume in any product this month. Data Connectors medium tickets numbered 27 (avg 11.3h). The spike in Governed Analytics high-severity tickets was traced to a schema migration issue in the enterprise workspace.',
 '{"doc":"support_may_2026","month":"2026-05"}'::jsonb),

-- Holiday 2025 post-mortem
('doc_holiday_2025_analysis_chunk_1',
 'doc_holiday_2025_analysis', 1,
 'November-December 2025 revenue surge: Nov revenue was $1,484, Dec was $1,625 — the highest two-month revenue in company history at that point. The holiday surge was driven by a 40% increase in campaign spend and enterprise year-end budget flush. Support ticket volume also peaked in December at 35 high-severity tickets for Governed Analytics.',
 '{"doc":"holiday_2025","domain":"revenue","period":"2025-11-12"}'::jsonb),

('doc_holiday_2025_analysis_chunk_2',
 'doc_holiday_2025_analysis', 2,
 'Lessons from 2025 holiday surge: (1) Provision 30% more support capacity in November-December. (2) Pre-approve schema freezes to prevent risky deployments during peak revenue. (3) Set up automated traffic alerts when order volume exceeds 2x daily baseline. These protocols are now in the 2026 holiday readiness plan.',
 '{"doc":"holiday_2025","domain":"support","lessons_learned":true}'::jsonb),

-- Data model catalog
('doc_data_model_catalog_v2_chunk_1',
 'doc_data_model_catalog_v2', 1,
 'Core business tables: orders (order_id, customer_id, product_id, region_id, order_amount, status, order_date), refunds (refund_id, order_id, refund_amount, refund_date, reason), customers (customer_id P0, customer_name P1, user_email P1, phone P1, region_id, created_at), products (product_id, product_name, category, price), regions (region_id, region_name, country).',
 '{"doc":"data_catalog_v2","domain":"schema","section":"business_tables"}'::jsonb),

('doc_data_model_catalog_v2_chunk_2',
 'doc_data_model_catalog_v2', 2,
 'Sensitivity classifications: P0 = direct identifiers (customer_id, order-to-customer linkage). P1 = quasi-identifiers (names, emails, phone numbers). P2 = non-sensitive aggregates (revenue totals, ticket counts, product names). P0 fields are denied for analyst role. P1 fields are masked. P2 fields are open to all roles.',
 '{"doc":"data_catalog_v2","domain":"governance","section":"sensitivity"}'::jsonb)

ON CONFLICT (chunk_id) DO UPDATE SET
    source_id  = EXCLUDED.source_id,
    chunk_index = EXCLUDED.chunk_index,
    chunk_text = EXCLUDED.chunk_text,
    metadata   = EXCLUDED.metadata;

-- Embeddings for the new chunks (local-deterministic model, vector_ref pointer)
INSERT INTO knowledge.doc_embeddings
    (embedding_id, chunk_id, embedding_model, embedding_dimensions, vector_ref)
SELECT
    chunk_id || '_emb',
    chunk_id,
    'local-deterministic-v1',
    8,
    'pgvector://knowledge.doc_chunks/' || chunk_id
FROM knowledge.doc_chunks
WHERE chunk_id NOT IN (SELECT chunk_id FROM knowledge.doc_embeddings)
ON CONFLICT (embedding_id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. EVALUATION — eval cases covering all demo questions shown in the UI
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO evaluation.eval_cases
    (eval_case_id, question, expected_metric_id, expected_sql_pattern, expected_answer, tags, created_at)
VALUES
('case_revenue_kpi_2026_h1',
 'What is revenue by month for the first half of 2026?',
 'revenue',
 'SELECT month, revenue FROM business.revenue_by_month',
 '{"metric":"revenue","grain":"month","period":"H1 2026"}'::jsonb,
 ARRAY['kpi','revenue','demo','h1'],
 '2026-06-25T00:00:00Z'),

('case_revenue_highest_month_2012',
 'Which month had the highest revenue in 2012?',
 'revenue',
 'SELECT month, revenue FROM business.revenue_by_month WHERE month LIKE ''2012-%'' ORDER BY revenue DESC LIMIT 1',
 '{"metric":"revenue","grain":"month","period":"2012","expected_month":"2012-12"}'::jsonb,
 ARRAY['kpi','revenue','2012','max'],
 '2026-06-25T00:00:00Z'),

('case_revenue_change_h1_2026',
 'Explain why revenue changed in H1 2026.',
 'revenue',
 'SELECT month, revenue FROM business.revenue_by_month WHERE month >= ''2026-01'' AND month <= ''2026-06''',
 '{"metric":"revenue","grain":"month","period":"H1 2026","requires_rag":true}'::jsonb,
 ARRAY['kpi','revenue','anomaly','explanation','demo'],
 '2026-06-25T00:00:00Z'),

('case_support_ticket_attention',
 'Which support ticket area needs attention?',
 'support_ticket_volume',
 'SELECT product, severity, SUM(ticket_count) FROM business.support_ticket_summary GROUP BY product, severity ORDER BY SUM(ticket_count) DESC',
 '{"metric":"support_ticket_volume","grain":"product_severity","requires_analysis":true}'::jsonb,
 ARRAY['support','tickets','attention','demo'],
 '2026-06-25T00:00:00Z'),

('case_refund_rate_q1_2026',
 'What is the refund rate for Q1 2026?',
 'refund_rate',
 'SELECT SUM(refund_amount) / NULLIF(SUM(order_amount),0) * 100 FROM business.revenue_by_month',
 '{"metric":"refund_rate","grain":"quarter","period":"Q1 2026"}'::jsonb,
 ARRAY['refund_rate','q1','2026'],
 '2026-07-01T00:00:00Z'),

('case_avg_resolution_by_product_2026',
 'Which product has the longest average resolution time for support tickets in 2026?',
 'avg_resolution_time',
 'SELECT product, SUM(ticket_count * avg_resolution_hours) / NULLIF(SUM(ticket_count),0) AS avg_hours FROM business.support_ticket_summary WHERE month >= ''2026-01'' GROUP BY product ORDER BY avg_hours DESC',
 '{"metric":"avg_resolution_time","grain":"product","period":"2026"}'::jsonb,
 ARRAY['support','resolution_time','2026'],
 '2026-07-01T00:00:00Z'),

('case_revenue_yoy_growth_2025_2026',
 'How did revenue grow year over year from 2025 to 2026?',
 'revenue',
 'SELECT DATE_TRUNC(''year'', TO_DATE(month, ''YYYY-MM''))::TEXT AS year, SUM(revenue) FROM business.revenue_by_month GROUP BY 1 ORDER BY 1',
 '{"metric":"revenue","grain":"year","period":"2025-2026","requires_yoy":true}'::jsonb,
 ARRAY['revenue','yoy','growth','2025','2026'],
 '2026-07-01T00:00:00Z'),

('case_support_critical_tickets_june_2026',
 'How many critical support tickets were there in June 2026 and which products had them?',
 'support_ticket_volume',
 'SELECT product, ticket_count, avg_resolution_hours FROM business.support_ticket_summary WHERE month = ''2026-06'' AND severity = ''critical''',
 '{"metric":"support_ticket_volume","grain":"product","period":"2026-06","severity":"critical"}'::jsonb,
 ARRAY['support','critical','2026-06'],
 '2026-07-01T00:00:00Z'),

('case_revenue_by_half_comparison',
 'Compare revenue in H1 2026 vs H1 2025.',
 'revenue',
 'SELECT CASE WHEN month >= ''2026-01'' AND month <= ''2026-06'' THEN ''H1 2026'' WHEN month >= ''2025-01'' AND month <= ''2025-06'' THEN ''H1 2025'' END AS half, SUM(revenue) FROM business.revenue_by_month GROUP BY 1',
 '{"metric":"revenue","grain":"half_year","comparison":true}'::jsonb,
 ARRAY['revenue','h1','2025','2026','comparison'],
 '2026-07-02T00:00:00Z'),

('case_support_ticket_trend_2025_2026',
 'Show me the trend of high-severity Governed Analytics tickets from 2025 to 2026.',
 'support_ticket_volume',
 'SELECT month, ticket_count FROM business.support_ticket_summary WHERE product = ''Governed Analytics'' AND severity = ''high'' ORDER BY month',
 '{"metric":"support_ticket_volume","grain":"month","product":"Governed Analytics","severity":"high"}'::jsonb,
 ARRAY['support','trend','governed_analytics','high','2025','2026'],
 '2026-07-02T00:00:00Z')

ON CONFLICT (eval_case_id) DO UPDATE SET
    question              = EXCLUDED.question,
    expected_metric_id    = EXCLUDED.expected_metric_id,
    expected_sql_pattern  = EXCLUDED.expected_sql_pattern,
    expected_answer       = EXCLUDED.expected_answer,
    tags                  = EXCLUDED.tags,
    created_at            = EXCLUDED.created_at;

-- ─────────────────────────────────────────────────────────────────────────────
-- Done.
-- Summary of what was seeded:
--   auth.organizations       3 orgs (Acme, TechStart, GlobalRetail)
--   auth.users              10 users (admin/analyst/viewer per org)
--   business.support_ticket_summary  ~170 rows (18 months, 4 products, 4 severities)
--   semantic.semantic_versions  3 versions
--   semantic.metrics            8 metrics
--   semantic.dimensions         9 dimensions
--   governance.access_policies  9 policies (P0 deny, P1 mask, P2 allow)
--   knowledge.documents        15 business documents
--   knowledge.doc_chunks       30+ text chunks for RAG
--   knowledge.doc_embeddings   auto-seeded for all chunks
--   evaluation.eval_cases      10 test questions covering all demo scenarios
-- ─────────────────────────────────────────────────────────────────────────────
