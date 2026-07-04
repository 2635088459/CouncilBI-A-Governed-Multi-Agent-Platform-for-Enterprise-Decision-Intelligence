# 05 Data Platform, Migrations, and Seed Data

## 1. Why This Matters

An industrial project cannot rely on a few hand-written demo rows. The platform needs large, repeatable, meaningful data to verify SQL correctness, analytics stability, RAG evidence quality, permission isolation, and performance.

## 2. Data Categories

The final system needs:

1. Application data: users, organizations, roles, sessions, query history.
2. Business data: orders, customers, products, regions, revenue, refunds.
3. Knowledge data: documents, chunks, embeddings, citations.
4. Runtime data: traces, metrics, logs, evals, audits.

## 3. Storage Choices

PostgreSQL stores users, permissions, business demo data, query history, audit logs, and evaluation results.

Redis stores cache entries, rate-limit counters, short-lived task state, and token blacklist/session support.

pgvector stores document chunk embeddings and supports RAG retrieval.

## 4. Migration Strategy

Schema changes must be managed through migrations:

1. Every schema change has a migration file.
2. Migrations run consistently in local, CI, and cloud environments.
3. Migrations and seed data stay separate.
4. Production migrations require rollback or backup strategy.

## 5. Seed Levels

### Small

For unit tests and quick demos:

1. 2 organizations.
2. 5 to 10 users.
3. Hundreds of business records.
4. Dozens of document chunks.

### Medium

For local integration tests:

1. 5 to 10 organizations.
2. Dozens of users.
3. Around 100k business records.
4. Thousands of document chunks.

### Large

For load testing:

1. Multiple organizations.
2. Millions of business records.
3. Large document corpus.
4. Large query and trace history.

## 6. Test Data Principles

Good seed data should contain business patterns:

1. Holiday revenue spikes.
2. Regional refund anomalies.
3. Product launch growth.
4. Channel conversion decline.
5. Documents that explain the business cause.

This lets the demo show query, analysis, root-cause explanation, and evidence together.

The local small seed must also include a deterministic multi-year monthly
revenue read model. At minimum, `business.revenue_by_month` contains every
month from 2011 through 2025 plus the current 2026 demo months. When a user asks
for a specific revenue year, SQL planning and answer synthesis must filter to
that requested year only. The platform must not answer a 2011 question with
2012 or 2026 rows.

## 7. Data Quality Checks

After seeding, verify:

1. Tables are populated.
2. Foreign keys are valid.
3. Metrics produce reasonable values.
4. Embedding count matches chunk count.
5. Tenants remain isolated.
6. Year-scoped revenue questions return only rows whose `month` begins with the
   requested year, and their evidence anchors cite the same year.

## 8. Implementation Order

1. Define final demo scenarios.
2. Design business and document tables.
3. Add migrations.
4. Add small seed.
5. Add medium and large seed.
6. Add data quality checks.
7. Connect seed commands to CI/local verification.
