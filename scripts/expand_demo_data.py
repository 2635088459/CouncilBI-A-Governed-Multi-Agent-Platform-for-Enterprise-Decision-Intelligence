"""
Comprehensive demo data expansion script.
Adds: revenue through Dec-2026, 8 products, campaigns table,
      and 20+ rich knowledge documents indexed into the vector store.

Run: python scripts/expand_demo_data.py
"""

import psycopg
import requests
import json
import time

DB_URL = "postgresql://chatbi:chatbi_password@localhost:5432/chatbi"
API_BASE = "http://localhost:8080"
ADMIN_EMAIL = "admin@acme.com"
ADMIN_PASSWORD = "admin1234"

# ──────────────────────────────────────────────
# 1. SQL DATA
# ──────────────────────────────────────────────

REVENUE_ROWS = [
    # 2026 continuation – July drop then recovery
    ("2026-07", 890),
    ("2026-08", 1050),
    ("2026-09", 1185),
    ("2026-10", 1310),
    ("2026-11", 1430),
    ("2026-12", 1690),
    # fill 2024 monthly (was sparse)
    ("2024-01", 820),
    ("2024-02", 855),
    ("2024-03", 890),
    ("2024-04", 910),
    ("2024-05", 940),
    ("2024-06", 975),
    ("2024-07", 1005),
    ("2024-08", 1040),
    ("2024-09", 1060),
    ("2024-10", 1085),
    ("2024-11", 1210),
    ("2024-12", 1440),
    # 2023
    ("2023-01", 640),
    ("2023-02", 660),
    ("2023-03", 685),
    ("2023-04", 700),
    ("2023-05", 720),
    ("2023-06", 750),
    ("2023-07", 770),
    ("2023-08", 790),
    ("2023-09", 805),
    ("2023-10", 815),
    ("2023-11", 920),
    ("2023-12", 1100),
]

# New products to add alongside the existing 4
NEW_PRODUCTS = ["API Platform", "ML Pipeline", "Reporting Studio", "Analytics Hub"]
ALL_PRODUCTS = [
    "Governed Analytics", "Data Connectors", "LLM Gateway",
    "Admin Dashboard", "API Platform", "ML Pipeline",
    "Reporting Studio", "Analytics Hub",
]

TICKET_ROWS = [
    # API Platform  – scaling issues in mid-2026
    ("2025-01", "API Platform", "low",      12, 2.1),
    ("2025-02", "API Platform", "low",      14, 2.3),
    ("2025-03", "API Platform", "medium",   18, 6.8),
    ("2025-04", "API Platform", "medium",   22, 7.1),
    ("2025-05", "API Platform", "high",     16, 15.2),
    ("2025-06", "API Platform", "medium",   19, 6.4),
    ("2025-07", "API Platform", "low",      11, 2.0),
    ("2025-08", "API Platform", "medium",   24, 8.1),
    ("2025-09", "API Platform", "high",     29, 17.3),
    ("2025-10", "API Platform", "critical",  6, 4.1),
    ("2025-11", "API Platform", "medium",   21, 7.9),
    ("2025-12", "API Platform", "high",     27, 16.1),
    ("2026-01", "API Platform", "medium",   23, 7.5),
    ("2026-02", "API Platform", "medium",   20, 6.9),
    ("2026-03", "API Platform", "high",     31, 18.2),
    ("2026-04", "API Platform", "critical",  9, 5.7),
    ("2026-05", "API Platform", "high",     34, 19.5),
    ("2026-06", "API Platform", "medium",   26, 8.3),
    ("2026-07", "API Platform", "critical", 14, 6.2),
    ("2026-08", "API Platform", "high",     28, 17.1),
    # ML Pipeline – ramp in H2 2025
    ("2025-01", "ML Pipeline",  "low",      8,  1.8),
    ("2025-02", "ML Pipeline",  "low",      9,  1.9),
    ("2025-03", "ML Pipeline",  "medium",   13, 5.5),
    ("2025-04", "ML Pipeline",  "medium",   17, 6.2),
    ("2025-05", "ML Pipeline",  "high",     21, 14.8),
    ("2025-06", "ML Pipeline",  "medium",   15, 5.9),
    ("2025-07", "ML Pipeline",  "high",     25, 16.4),
    ("2025-08", "ML Pipeline",  "critical",  4, 3.9),
    ("2025-09", "ML Pipeline",  "high",     28, 17.9),
    ("2025-10", "ML Pipeline",  "medium",   18, 6.7),
    ("2025-11", "ML Pipeline",  "high",     24, 15.2),
    ("2025-12", "ML Pipeline",  "medium",   19, 7.1),
    ("2026-01", "ML Pipeline",  "medium",   22, 7.4),
    ("2026-02", "ML Pipeline",  "high",     26, 16.0),
    ("2026-03", "ML Pipeline",  "medium",   20, 7.0),
    ("2026-04", "ML Pipeline",  "high",     29, 18.3),
    ("2026-05", "ML Pipeline",  "critical",  7, 5.1),
    ("2026-06", "ML Pipeline",  "high",     32, 19.4),
    ("2026-07", "ML Pipeline",  "medium",   21, 7.8),
    ("2026-08", "ML Pipeline",  "medium",   18, 6.5),
    # Reporting Studio – stable, low severity
    ("2025-03", "Reporting Studio", "low",  10, 1.5),
    ("2025-06", "Reporting Studio", "low",  12, 1.7),
    ("2025-09", "Reporting Studio", "medium", 16, 5.8),
    ("2025-12", "Reporting Studio", "low",  11, 1.6),
    ("2026-01", "Reporting Studio", "medium", 18, 6.1),
    ("2026-02", "Reporting Studio", "low",  9,  1.4),
    ("2026-03", "Reporting Studio", "medium", 14, 5.5),
    ("2026-04", "Reporting Studio", "low",  10, 1.6),
    ("2026-05", "Reporting Studio", "medium", 17, 6.3),
    ("2026-06", "Reporting Studio", "low",  8,  1.3),
    ("2026-07", "Reporting Studio", "medium", 20, 7.2),
    ("2026-08", "Reporting Studio", "low",  11, 1.8),
    # Analytics Hub – new product, ramping fast
    ("2025-06", "Analytics Hub", "low",    5,  1.2),
    ("2025-07", "Analytics Hub", "medium", 10, 4.8),
    ("2025-08", "Analytics Hub", "medium", 14, 5.6),
    ("2025-09", "Analytics Hub", "high",   18, 13.5),
    ("2025-10", "Analytics Hub", "critical", 3, 3.2),
    ("2025-11", "Analytics Hub", "high",   22, 14.9),
    ("2025-12", "Analytics Hub", "medium", 16, 6.1),
    ("2026-01", "Analytics Hub", "high",   25, 16.7),
    ("2026-02", "Analytics Hub", "medium", 19, 7.0),
    ("2026-03", "Analytics Hub", "high",   28, 17.8),
    ("2026-04", "Analytics Hub", "critical", 8, 5.5),
    ("2026-05", "Analytics Hub", "high",   31, 18.9),
    ("2026-06", "Analytics Hub", "medium", 24, 8.2),
    ("2026-07", "Analytics Hub", "high",   33, 20.1),
    ("2026-08", "Analytics Hub", "critical", 10, 6.0),
    # Extend existing products to July/Aug 2026
    ("2026-07", "Governed Analytics", "high",     29, 14.3),
    ("2026-07", "Governed Analytics", "medium",   24, 7.1),
    ("2026-07", "Data Connectors",    "medium",   22, 8.8),
    ("2026-07", "LLM Gateway",        "critical",  5, 4.8),
    ("2026-07", "LLM Gateway",        "high",     12, 12.3),
    ("2026-07", "Admin Dashboard",    "low",       7, 1.9),
    ("2026-08", "Governed Analytics", "high",     31, 15.1),
    ("2026-08", "Governed Analytics", "medium",   26, 7.4),
    ("2026-08", "Data Connectors",    "high",     19, 13.7),
    ("2026-08", "LLM Gateway",        "medium",   14, 8.4),
    ("2026-08", "Admin Dashboard",    "medium",    9, 4.2),
]

CREATE_CAMPAIGNS_TABLE = """
CREATE TABLE IF NOT EXISTS business.campaigns (
    campaign_id   TEXT PRIMARY KEY,
    month         TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    channel       TEXT NOT NULL,
    spend         NUMERIC(12,2),
    impressions   BIGINT,
    clicks        BIGINT,
    conversions   INTEGER,
    attributed_revenue NUMERIC(12,2),
    status        TEXT NOT NULL
);
"""

CAMPAIGN_ROWS = [
    # campaign_id, month, name, channel, spend, impressions, clicks, conversions, revenue, status
    ("cmp_001", "2026-01", "New Year Push",        "paid_search",  45000, 2_100_000, 42_000, 840,  120_000, "completed"),
    ("cmp_002", "2026-01", "New Year Push",        "social_media", 22000, 4_500_000, 36_000, 540,   62_000, "completed"),
    ("cmp_003", "2026-02", "Valentine's Campaign", "email",         8000,   980_000, 78_400, 627,   45_000, "completed"),
    ("cmp_004", "2026-02", "Valentine's Campaign", "paid_search",  31000, 1_800_000, 36_000, 648,   88_000, "completed"),
    ("cmp_005", "2026-03", "Spring Sale",          "paid_search",  52000, 2_450_000, 49_000, 980,  145_000, "completed"),
    ("cmp_006", "2026-03", "Spring Sale",          "social_media", 28000, 5_600_000, 44_800, 672,   80_000, "completed"),
    ("cmp_007", "2026-04", "Product Launch Q2",    "display",      35000, 8_200_000, 24_600, 369,   58_000, "completed"),
    ("cmp_008", "2026-04", "Product Launch Q2",    "email",         6000,   750_000, 60_000, 540,   39_000, "completed"),
    ("cmp_009", "2026-05", "Summer Teaser",        "social_media", 40000, 9_100_000, 72_800, 874,  118_000, "completed"),
    ("cmp_010", "2026-05", "Summer Teaser",        "paid_search",  55000, 2_600_000, 52_000, 1040, 158_000, "completed"),
    ("cmp_011", "2026-06", "Summer Sale",          "paid_search",  68000, 3_200_000, 64_000, 1280, 195_000, "completed"),
    ("cmp_012", "2026-06", "Summer Sale",          "social_media", 42000, 9_800_000, 78_400, 941,  128_000, "completed"),
    ("cmp_013", "2026-06", "Summer Sale",          "display",      25000, 11_500_000, 34_500, 345,  48_000, "completed"),
    # July – campaign PAUSED
    ("cmp_014", "2026-07", "Summer Sale",          "paid_search",  12000,   560_000, 11_200, 134,   19_000, "paused"),
    ("cmp_015", "2026-07", "Summer Sale",          "social_media",  8000, 1_800_000, 14_400,  86,   11_000, "paused"),
    # August – resumed
    ("cmp_016", "2026-08", "Summer Sale Revival",  "paid_search",  58000, 2_750_000, 55_000, 990,  148_000, "completed"),
    ("cmp_017", "2026-08", "Summer Sale Revival",  "social_media", 36000, 8_400_000, 67_200, 806,  110_000, "completed"),
    ("cmp_018", "2026-09", "Back to School",       "paid_search",  50000, 2_380_000, 47_600, 856,  132_000, "completed"),
    ("cmp_019", "2026-09", "Back to School",       "email",         9000, 1_100_000, 88_000, 704,   52_000, "completed"),
    ("cmp_020", "2026-10", "Q4 Launch",            "paid_search",  62000, 2_950_000, 59_000, 1062, 167_000, "completed"),
    ("cmp_021", "2026-11", "Black Friday",         "paid_search",  95000, 4_500_000, 90_000, 1980, 295_000, "completed"),
    ("cmp_022", "2026-11", "Black Friday",         "social_media", 68000, 16_000_000,128_000,1536, 210_000, "completed"),
    ("cmp_023", "2026-12", "Holiday Peak",         "paid_search", 110000, 5_200_000,104_000, 2288, 345_000, "completed"),
    ("cmp_024", "2026-12", "Holiday Peak",         "email",        15000, 1_850_000,148_000, 1332, 102_000, "completed"),
]

# ──────────────────────────────────────────────
# 2. DOCUMENTS (indexed via API)
# ──────────────────────────────────────────────

DOCUMENTS = [
    {
        "document_id": "doc_july_2026_campaign_pause",
        "source": "incident-management-system",
        "title": "July 2026 Revenue Drop — Campaign Pause Root Cause Analysis",
        "document_type": "incident",
        "published_at": "2026-07-28T00:00:00Z",
        "business_tags": ["revenue", "campaigns", "july-2026", "incident"],
        "permission_tags": [],
        "text": """# July 2026 Revenue Drop — Campaign Pause Root Cause Analysis

## Executive Summary
July 2026 revenue came in at $890,000, a 34.1% decline versus June 2026 ($1,350,000) and 24.8% below the July forecast of $1,183,000. The primary cause was a 21-day suspension of the Summer Sale campaign across paid search and social media channels, triggered by a brand-safety flag raised by our ad-network partner on July 1.

## Timeline of Events
- **June 30, 2026**: Ad-network partner (TrafficGuard) flags three ad creatives for potential association with restricted content categories under updated platform policy v2.4.1.
- **July 1, 2026**: Marketing ops pauses all Summer Sale paid campaigns pending creative review. Affected campaigns: cmp_014 (paid search), cmp_015 (social media). Combined daily spend halted: ~$3,600/day.
- **July 1–7, 2026**: Legal and compliance review of flagged creatives. Two of three creatives cleared. One (hero banner variant B) permanently retired.
- **July 8, 2026**: Cleared creatives resubmitted to ad network. Approval queue backlog causes 13-day processing delay.
- **July 21, 2026**: Campaigns approved and relaunched at reduced budget ($20,000 vs original $135,000 for the month).
- **July 31, 2026**: Month closes at $890,000 revenue. Email channel (not paused) contributed $67,000, offsetting partial losses.

## Revenue Impact Breakdown
| Channel       | July Plan ($) | July Actual ($) | Variance ($) | Variance (%) |
|---------------|--------------|-----------------|-------------|-------------|
| Paid Search   | 285,000      | 19,000          | -266,000    | -93.3%      |
| Social Media  | 198,000      | 11,000          | -187,000    | -94.4%      |
| Email         | 58,000       | 67,000          | +9,000      | +15.5%      |
| Organic/Other | 642,000      | 793,000         | +151,000    | +23.5%      |
| **Total**     | **1,183,000**| **890,000**     | **-293,000**| **-24.8%**  |

Organic traffic benefited from prior-month SEO investments and partially compensated for paid channel losses. Organic conversion rate held at 2.1%, consistent with H1 average.

## Contributing Factors
1. **Campaign concentration risk**: 68% of July revenue was forecasted to come from two paid campaigns. No diversification into affiliate or influencer channels existed.
2. **Ad network policy change**: TrafficGuard updated brand-safety classification rules on June 25 without advance notice to advertisers. Industry-wide impact affected ~12% of active advertisers.
3. **Approval queue congestion**: Post-holiday backlog at TrafficGuard averaged 13 days for re-review, longer than the standard 3-day SLA.
4. **Inventory effect**: July is historically a lower-organic-traffic month (summer lull). Organic uplift partially offset losses but could not fully compensate.

## Recovery Actions
- **August 2026**: Summer Sale Revival campaign launched (cmp_016, cmp_017) at $94,000 combined spend. August revenue recovered to $1,050,000 (+18% MoM).
- **September 2026**: Back to School campaign (cmp_018, cmp_019) drove $1,185,000 revenue, approaching pre-incident levels.
- **Channel diversification**: Affiliate partnership with RetailMedia Network launched August 15. Target: reduce paid search concentration from 68% to 45% of attributed revenue by Q4.
- **Policy monitoring**: Marketing ops team now subscribed to TrafficGuard policy changelog feed. Legal review SLA for creative changes reduced from 7 days to 2 days.

## Lessons Learned
1. No single campaign or channel should account for more than 40% of monthly revenue plan.
2. Creative pre-screening against ad-network policy should occur 2 weeks before campaign launch.
3. Emergency response playbook drafted: if campaign paused mid-month, email and organic budgets boosted within 48 hours.

## Financial Reconciliation
- Lost revenue vs plan: $293,000
- Incremental email and organic gain: $160,000 (estimated)
- Net revenue shortfall vs plan: $133,000
- Recovery in August vs plan: +$12,000 above August forecast of $1,038,000

## Sign-off
Approved by: VP Marketing, CFO, VP Engineering (brand-safety tooling owner)
Date: July 28, 2026
""",
    },
    {
        "document_id": "doc_support_ops_july_2026",
        "source": "support-ops-weekly-reporting",
        "title": "Support Operations Weekly Review — July 2026",
        "document_type": "weekly_report",
        "published_at": "2026-07-31T00:00:00Z",
        "business_tags": ["support", "tickets", "july-2026", "api-platform", "analytics-hub"],
        "permission_tags": [],
        "text": """# Support Operations Weekly Review — July 2026

## Monthly Snapshot
- **Total tickets opened**: 184 (↑ 18% vs June 2026: 156)
- **Critical tickets**: 19 (↑ 58% vs June: 12)
- **Average resolution time**: 11.4 hours (↑ from 8.7 hours in June)
- **First-contact resolution rate**: 62% (↓ from 71% in June)
- **CSAT score**: 4.1 / 5.0 (↓ from 4.4 in June)

## Ticket Volume by Product
| Product            | Total | Critical | High | Medium | Low | Avg Res. (hrs) |
|--------------------|-------|----------|------|--------|-----|----------------|
| Analytics Hub      | 33    | 0        | 33   | 0      | 0   | 20.1           |
| API Platform       | 14    | 14       | 0    | 0      | 0   | 6.2            |
| Governed Analytics | 53    | 0        | 29   | 24     | 0   | 10.9           |
| Data Connectors    | 22    | 0        | 0    | 22     | 0   | 8.8            |
| LLM Gateway        | 17    | 5        | 12   | 0      | 0   | 9.2            |
| ML Pipeline        | 21    | 0        | 0    | 21     | 0   | 7.8            |
| Reporting Studio   | 20    | 0        | 0    | 20     | 0   | 7.2            |
| Admin Dashboard    | 7     | 0        | 0    | 0      | 7   | 1.9            |

## Key Incidents

### API Platform: Authentication Failure — July 3–5 (P0 Incident)
API Platform experienced a complete authentication service outage affecting all enterprise customers from July 3 02:14 UTC to July 5 09:47 UTC (55.5 hours). Root cause: certificate rotation script failed to update the JWT signing key in the distributed cache, causing all token validation to fail. 14 critical tickets opened. Estimated customer impact: 340 enterprise workspaces affected. SLA breach for 28 customers. Incident post-mortem completed July 15. Fix: automated certificate rotation now validates cache sync before completing.

### Analytics Hub: Query Timeout Spike — July 12–16
Analytics Hub query engine experienced intermittent timeouts (P1) affecting 15% of query executions. Root cause: index fragmentation in the underlying columnar store after a bulk data migration on July 11. 33 high-severity tickets opened over 5 days. Resolution: manual index rebuild completed July 16 in a 4-hour maintenance window. Preventive measure: weekly automated index health checks added.

### LLM Gateway: Rate Limit Confusion — Ongoing
5 critical tickets opened by enterprise customers who unexpectedly hit LLM Gateway rate limits after the July 1 rate-limit policy update (400 RPM → 200 RPM per workspace for the Standard tier). Documentation was not updated before policy change. Resolution: documentation updated July 8, affected customers moved to Pro tier temporarily.

## SLA Performance
- P0 (4-hour SLA): 71% met (↓ from 100% in June) — API Platform outage caused 4 breaches
- P1 (24-hour SLA): 84% met (↓ from 92% in June)
- P2 (72-hour SLA): 97% met (consistent with June)

## Backlog Status
- Open tickets end of July: 43 (↑ from 28 in June)
- Tickets older than 14 days: 7 (all P2, pending customer response)

## Actions for August
1. Hire 2 additional senior support engineers to handle Analytics Hub and API Platform growth.
2. Proactive outreach to 28 customers affected by API Platform SLA breach (credits applied automatically).
3. Rate-limit change communication process: require 2-week advance notice to customers for any tier-policy changes.
""",
    },
    {
        "document_id": "doc_q2_2026_revenue_analysis",
        "source": "finance-reporting",
        "title": "Q2 2026 Revenue Deep Dive — Campaign Impact and Regional Breakdown",
        "document_type": "finance_report",
        "published_at": "2026-07-10T00:00:00Z",
        "business_tags": ["revenue", "q2-2026", "campaigns", "regional"],
        "permission_tags": [],
        "text": """# Q2 2026 Revenue Deep Dive — Campaign Impact and Regional Breakdown

## Q2 2026 Performance Summary
Q2 2026 (April–June) delivered total revenue of **$3,850,000**, the strongest quarter in company history.
- Q2 2026 vs Q2 2025: +28.3% YoY growth
- Q2 2026 vs Q1 2026: +11.0% QoQ growth (Q1 2026 total: $3,467,000)
- June 2026 alone: $1,350,000 — best single month ever recorded

## Monthly Breakdown
| Month    | Revenue     | MoM Growth | YoY Growth | Campaign Attributed |
|----------|-------------|-----------|-----------|---------------------|
| Apr 2026 | $1,210,000  | +1.7%     | +32.9%    | $97,000 (8.0%)      |
| May 2026 | $1,290,000  | +6.6%     | +29.0%    | $276,000 (21.4%)    |
| Jun 2026 | $1,350,000  | +4.7%     | +26.5%    | $371,000 (27.5%)    |

## Campaign Attribution Analysis
Q2 included the ramp-up and peak of the Summer Sale campaign (cmp_011, cmp_012, cmp_013).

| Campaign Phase       | Spend ($) | Attributed Revenue ($) | ROI   |
|----------------------|-----------|------------------------|-------|
| Product Launch (Apr) | 41,000    | 97,000                 | 2.37x |
| Summer Teaser (May)  | 95,000    | 276,000                | 2.91x |
| Summer Sale (Jun)    | 135,000   | 371,000                | 2.75x |
| **Q2 Total**         | **271,000**| **744,000**           | **2.75x** |

Campaign ROI in Q2 exceeded the 2.5x target set in the annual plan. The Summer Teaser (May) achieved the highest efficiency at 2.91x, driven by strong social media engagement (72,800 clicks, 874 conversions).

## Regional Revenue Breakdown (Q2 2026)
| Region         | Q2 2026 Revenue | Q2 2025 Revenue | YoY Growth | Q2 Share |
|----------------|-----------------|-----------------|-----------|---------|
| US-West        | $2,233,000      | $1,734,000      | +28.8%    | 58.0%   |
| US-East        | $1,232,000      | $963,000        | +27.9%    | 32.0%   |
| International  | $385,000        | $303,000        | +27.1%    | 10.0%   |

US-West dominance continued, driven by enterprise tech-sector customers. International grew to 10% share (up from 9.5% in Q1), reflecting successful expansion into APAC (Singapore and Australia added 3 new enterprise accounts).

## Product Line Revenue Contribution (Q2 2026)
| Product            | Revenue Share | YoY Volume Growth |
|--------------------|--------------|------------------|
| Governed Analytics | 42%          | +31%             |
| Data Connectors    | 24%          | +22%             |
| LLM Gateway        | 18%          | +48%             |
| API Platform       | 9%           | +19%             |
| Other (new)        | 7%           | N/A (new)        |

LLM Gateway (+48% YoY) is the fastest-growing product, driven by enterprise GenAI adoption. Governed Analytics remains the revenue anchor at 42% share.

## Customer Metrics (Q2 2026)
- Active customers (any purchase): 1,247 (↑ from 1,089 in Q1)
- Average revenue per customer: $3,088 (↑ from $2,941 in Q1)
- New customers acquired: 203 (↓ from 241 in Q4 2025 due to sales team restructuring)
- Churned customers: 45 (churn rate: 3.6%, above 2.5% target)
- Net revenue retention: 118% (strong expansion revenue from existing accounts)

## Key Risks Entering Q3
1. **Summer Sale campaign exposure**: 27.5% of June revenue was campaign-attributed. Campaign pause or underperformance in July poses high downside risk.
2. **Churn acceleration**: Q2 churn rate of 3.6% above target. ML Pipeline integration gaps cited in 14 of 45 churn interviews.
3. **LLM Gateway rate-limit policy change**: Planned reduction from 400 to 200 RPM for Standard tier (effective July 1) may trigger downgrade requests.

## Forecast Q3 2026
- Base case: $3,720,000 (flat QoQ given July headwinds)
- Bull case: $4,100,000 (if campaign ROI maintains at 2.75x and churn stabilizes)
- Bear case: $3,200,000 (if campaign disruption persists through August)

Actual Q3 outcome: $3,425,000 (base case achieved; July drop offset by strong August-September recovery).
""",
    },
    {
        "document_id": "doc_customer_churn_analysis_2026",
        "source": "analytics-reports",
        "title": "Customer Churn Analysis — 2026 Q1 and Q2 Drivers",
        "document_type": "finance_report",
        "published_at": "2026-07-05T00:00:00Z",
        "business_tags": ["churn", "customers", "retention", "q1-2026", "q2-2026"],
        "permission_tags": [],
        "text": """# Customer Churn Analysis — 2026 Q1 and Q2 Drivers

## Overview
H1 2026 saw a churn rate of 3.2% (average across Q1 and Q2), above the annual target of 2.5%. Total churned customers in H1: 87. This report analyzes drivers, segments, and retention initiatives.

## Churn by Quarter and Segment
| Quarter | Segment    | Customers (Start) | Churned | Churn Rate |
|---------|------------|------------------|---------|-----------|
| Q1 2026 | Enterprise | 312              | 6       | 1.9%      |
| Q1 2026 | SMB        | 641              | 36      | 5.6%      |
| Q1 2026 | Startup    | 136              | 9       | 6.6%      |
| Q2 2026 | Enterprise | 320              | 7       | 2.2%      |
| Q2 2026 | SMB        | 614              | 29      | 4.7%      |
| Q2 2026 | Startup    | 131              | 0       | 0.0%      |

Enterprise churn remained within acceptable range (target: <2.5%). SMB churn is the primary concern at 4.7–5.6%.

## Top Churn Reasons (Exit Interview Analysis, n=63 responses)
| Reason                              | % of Responses | Segment Most Affected |
|-------------------------------------|---------------|----------------------|
| ML Pipeline integration too complex | 29%           | SMB                  |
| Pricing — cost exceeded value       | 22%           | SMB, Startup         |
| Switched to competitor              | 18%           | Enterprise, SMB      |
| Missing feature: scheduled reports  | 13%           | SMB                  |
| Support response time too slow      | 11%           | SMB                  |
| Product stability (outages)         | 7%            | Enterprise           |

### Detail: ML Pipeline Integration
29% of churned customers cited ML Pipeline integration complexity as a primary or secondary factor. Specific complaints:
- No native Python SDK (requires REST API calls for each model inference step)
- Documentation examples outdated (based on v1.2; current version is v2.1)
- No drag-and-drop pipeline builder for non-technical users
- Average onboarding time for ML Pipeline: 14 days (target: 5 days)

Roadmap response: Python SDK v1.0 targeted for Q3 2026 release. Pipeline builder UI in scoping phase for Q4 2026.

### Detail: Competitive Losses
18% of churned customers moved to a competitor. Named competitors in exit interviews:
- DataForge (8 customers): cited lower price point and better ML Pipeline UX
- StreamlineBI (5 customers): cited better scheduling and reporting features
- Internal build (3 customers): large enterprises building in-house

## Cohort Retention Analysis (Monthly)
Customers acquired in 2025 are showing lower 12-month retention than 2024 cohorts:
- 2024 cohort 12-month retention: 87%
- 2025 cohort 12-month retention: 82% (projected)
- 2026 cohort 6-month retention: 91% (on track — new onboarding program effect)

The improved 2026 cohort retention reflects the January 2026 onboarding revamp (dedicated customer success manager for first 90 days, structured milestone check-ins).

## High-Risk Accounts (Q3 2026 Watch List)
17 accounts have been flagged as high churn risk based on:
- No login in 30+ days: 8 accounts
- Open support tickets >14 days: 5 accounts
- Downgrade request submitted: 4 accounts

Customer success team has initiated outreach on all 17. Early results: 4 accounts confirmed renewal after roadmap briefing on ML Pipeline SDK.

## Retention Initiatives H2 2026
1. **ML Pipeline Quick-Start Program**: Dedicated onboarding engineer for accounts using ML Pipeline. Target: reduce time-to-value from 14 days to 4 days.
2. **SMB Pricing Review**: Finance team modeling a new SMB tier at $299/month (current: $450/month) to improve price-value perception.
3. **Scheduled Reports (Beta)**: Reporting Studio scheduled delivery (daily/weekly email) targeted for August 2026 release. Addresses 13% of churn reason.
4. **Proactive Health Scores**: New dashboard tracking product usage depth, support ticket frequency, and login recency. Alerts when score drops below 60.
""",
    },
    {
        "document_id": "doc_h1_2026_marketing_performance",
        "source": "marketing-ops",
        "title": "H1 2026 Marketing Campaign Performance Summary",
        "document_type": "campaign",
        "published_at": "2026-07-03T00:00:00Z",
        "business_tags": ["marketing", "campaigns", "h1-2026", "roi"],
        "permission_tags": [],
        "text": """# H1 2026 Marketing Campaign Performance Summary

## H1 2026 Campaign Overview
Total marketing spend in H1 2026: **$450,000**
Total attributed revenue: **$1,124,000**
Blended ROI: **2.50x** (vs 2.2x target, vs 2.1x H1 2025)

## Campaign-by-Campaign Results
| Campaign              | Month    | Channel       | Spend ($) | Attr. Rev ($) | ROI   | Conversions |
|-----------------------|----------|---------------|-----------|---------------|-------|-------------|
| New Year Push         | Jan-2026 | Paid Search   | 45,000    | 120,000       | 2.67x | 840         |
| New Year Push         | Jan-2026 | Social Media  | 22,000    | 62,000        | 2.82x | 540         |
| Valentine's           | Feb-2026 | Email         | 8,000     | 45,000        | 5.63x | 627         |
| Valentine's           | Feb-2026 | Paid Search   | 31,000    | 88,000        | 2.84x | 648         |
| Spring Sale           | Mar-2026 | Paid Search   | 52,000    | 145,000       | 2.79x | 980         |
| Spring Sale           | Mar-2026 | Social Media  | 28,000    | 80,000        | 2.86x | 672         |
| Product Launch Q2     | Apr-2026 | Display       | 35,000    | 58,000        | 1.66x | 369         |
| Product Launch Q2     | Apr-2026 | Email         | 6,000     | 39,000        | 6.50x | 540         |
| Summer Teaser         | May-2026 | Social Media  | 40,000    | 118,000       | 2.95x | 874         |
| Summer Teaser         | May-2026 | Paid Search   | 55,000    | 158,000       | 2.87x | 1,040       |
| Summer Sale           | Jun-2026 | Paid Search   | 68,000    | 195,000       | 2.87x | 1,280       |
| Summer Sale           | Jun-2026 | Social Media  | 42,000    | 128,000       | 3.05x | 941         |
| Summer Sale           | Jun-2026 | Display       | 25,000    | 48,000        | 1.92x | 345         |

## Channel Performance Summary (H1 2026)
| Channel      | Total Spend ($) | Attributed Revenue ($) | ROI   | Avg CPL ($) |
|--------------|-----------------|------------------------|-------|------------|
| Paid Search  | 251,000         | 706,000                | 2.81x | 29.9       |
| Social Media | 132,000         | 388,000                | 2.94x | 22.1       |
| Email        | 14,000          | 84,000                 | 6.00x | 11.2       |
| Display      | 60,000          | 106,000                | 1.77x | 87.4       |
| **Total**    | **457,000**     | **1,284,000**          | **2.81x** | —      |

**Email** is the highest-ROI channel at 6.0x, driven by low cost and strong engagement from existing customer base (78% open rate on Valentine's campaign). However, email reach is limited to existing contacts (980,000 subscribers).

**Display** underperforms at 1.77x ROI. Q3 recommendation: reduce display budget by 40% and reallocate to paid search and social.

## Top-Performing Audiences
1. **Enterprise decision-makers (Director+, US)**: 3.4x ROI on paid search, highest conversion rate (2.9%)
2. **SMB founders (company size 10–50)**: 3.1x ROI on social media, highest volume (2,381 conversions)
3. **Retargeted visitors (30-day window)**: 4.2x ROI across all channels, lowest CPL ($18.3)

## Attribution Model Notes
All attribution uses last-touch with 30-day lookback window. Multi-touch attribution modeling (in progress) estimated to increase measured channel ROI by 15–25% for upper-funnel channels (display, social awareness).

## H2 2026 Marketing Plan Highlights
- Channel mix shift: reduce display from 13% to 8% of budget; increase affiliate from 0% to 7%
- Audience expansion: APAC (Singapore, Australia) paid campaigns starting Q3
- Summer Sale Revival (Aug): $94,000 budget targeting lapsed customers and competitor switchers
- Black Friday / Holiday: $178,000 planned spend (largest single campaign ever; target 2.8x ROI)
""",
    },
    {
        "document_id": "doc_q1_2026_business_review",
        "source": "finance-reporting",
        "title": "Q1 2026 Business Review — Revenue, Orders, and Customer Trends",
        "document_type": "finance_report",
        "published_at": "2026-04-05T00:00:00Z",
        "business_tags": ["revenue", "q1-2026", "orders", "customers"],
        "permission_tags": [],
        "text": """# Q1 2026 Business Review — Revenue, Orders, and Customer Trends

## Q1 2026 Summary
- Total Revenue: **$3,467,000** (↑ 24.7% vs Q1 2025: $2,780,000)
- Total Orders: 11,890
- Average Order Value: $291.60
- Active Customers: 1,089
- New Customers: 241
- Churn: 51 customers (4.5% of starting base — above target)

## Monthly Revenue
| Month    | Revenue     | MoM Change | Orders | AOV    |
|----------|-------------|-----------|--------|--------|
| Jan 2026 | $1,000,000  | +12.5%    | 3,448  | $290.0 |
| Feb 2026 | $1,120,000  | +12.0%    | 3,790  | $295.5 |
| Mar 2026 | $1,180,000  | +5.4%     | 4,652  | $253.7 |

January was the strongest MoM growth month, driven by the New Year Push campaign ($182,000 attributed) and new-year renewal cycle (enterprise contracts typically renew in January).

March revenue growth slowed due to sales team restructuring (VP Sales departure March 1; interim leadership in place until April 15). Enterprise pipeline stalled during transition; 6 deals worth $280,000 pushed to Q2.

## Product Mix (Q1 2026)
| Product            | Revenue ($) | Share  | YoY Growth |
|--------------------|------------|--------|-----------|
| Governed Analytics | 1,457,140  | 42.0%  | +28.2%    |
| Data Connectors    | 832,080    | 24.0%  | +20.1%    |
| LLM Gateway        | 624,060    | 18.0%  | +51.3%    |
| API Platform       | 312,030    | 9.0%   | +18.4%    |
| Other Products     | 241,690    | 7.0%   | N/A       |

LLM Gateway continues explosive growth (+51.3% YoY) as enterprises accelerate GenAI adoption. Pipeline for LLM Gateway expanded to $3.2M (Q2 + Q3) as of March 31.

## Customer Cohort Health
Net Revenue Retention (NRR): **121%** — strong expansion revenue from existing customers purchasing additional products.
Gross Revenue Retention (GRR): **89%** — below 92% target due to above-average churn.

## Key Operational Metrics
- Support ticket volume: 523 (↑ 14% vs Q4 2025)
- Average resolution time: 9.2 hours (↑ from 8.1 hours in Q4 2025)
- Product uptime: 99.6% (below 99.9% target due to February DB migration incident)
- NPS score: 42 (↑ from 38 in Q4 2025)

## Q2 2026 Outlook
Guidance: $3,600,000–$3,900,000 (actual: $3,850,000 — above midpoint)
Drivers: Summer Sale campaign, new VP Sales hired April 15, 6 Q1 deals closing in Q2.
Risks: Churn trend, LLM Gateway rate-limit policy change planned for July.
""",
    },
    {
        "document_id": "doc_holiday_2025_analysis",
        "source": "incident-management-system",
        "title": "2025 Holiday Season Revenue and Support Surge — Post-Mortem",
        "document_type": "incident",
        "published_at": "2026-01-10T00:00:00Z",
        "business_tags": ["holiday", "2025", "revenue", "support", "incident"],
        "permission_tags": [],
        "text": """# 2025 Holiday Season Revenue and Support Surge — Post-Mortem

## Overview
November–December 2025 delivered $2,048,000 in combined revenue ($1,277,000 in November; $771,000 in December pre-Black-Friday-period re-classification — final restatement: $1,677,000 Nov + $1,771,000 Dec = $3,448,000). This was the highest holiday season on record (+31% vs 2024 holiday: $2,631,000).

The revenue surge was accompanied by a support ticket spike that exposed infrastructure gaps.

## Revenue Performance
| Month    | Revenue     | vs 2024   | Campaign Attributed |
|----------|-------------|----------|---------------------|
| Nov 2025 | $1,677,000  | +38.2%   | $462,000 (27.5%)    |
| Dec 2025 | $1,771,000  | +23.8%   | $385,000 (21.7%)    |

Black Friday (November 28) was the single highest-revenue day: $187,000 (prior record: $112,000 in 2024). Cyber Monday (December 1): $143,000.

## Support Surge
| Metric                         | Nov 2025 | Dec 2025 | Oct 2025 (baseline) |
|-------------------------------|----------|----------|---------------------|
| Total tickets                 | 312      | 287      | 178                 |
| Critical tickets              | 28       | 19       | 8                   |
| Average resolution time (hrs) | 16.2     | 12.8     | 8.4                 |
| SLA breach rate (P1)          | 31%      | 18%      | 4%                  |

The SLA breach rate in November reached 31% — the highest in company history. Primary cause: Governed Analytics query engine overload during peak traffic (Black Friday weekend), causing cascading failures in Data Connectors real-time sync.

## Infrastructure Incidents
1. **Nov 28 (Black Friday) — Query Engine Saturation (P0, 3.2 hours)**
   - Symptom: Governed Analytics query latency degraded from 2.1s to 47s average
   - Root cause: Connection pool exhausted due to 4.3x normal concurrent query load
   - Impact: 1,240 enterprise workspaces degraded; 89 tickets opened within 6 hours
   - Fix: Emergency connection pool limit increase from 500 to 1,200; query queue implemented

2. **Dec 1 (Cyber Monday) — Data Connectors Sync Failure (P1, 6.1 hours)**
   - Symptom: Real-time data sync stopped updating for 23% of Data Connectors customers
   - Root cause: Downstream effect of Nov 28 incident; stale connections not properly recycled
   - Impact: 156 workspaces with stale data; 34 tickets opened
   - Fix: Connection recycling on startup; health-check frequency increased to 30s

## Lessons Learned and Remediation (Completed by March 2026)
1. ✅ Query engine connection pool: auto-scaling implemented (scales to 5,000 connections at peak)
2. ✅ Load testing protocol: mandatory load test 4 weeks before any major commercial event
3. ✅ Holiday staffing: 24/7 on-call rotation November 15 – January 5 (was Nov 25 – Jan 1 previously)
4. ✅ Chaos engineering: quarterly game-day exercises introduced; first exercise completed February 2026
5. 🔄 Database read replica for analytics queries: in progress, targeted Q3 2026

## Financial Impact of Support Surge
- Customer credits issued for SLA breaches: $42,000
- Engineering overtime costs: $28,000
- Total incident cost: $70,000
- Net holiday revenue after incident costs: $3,378,000 (still +28.6% vs 2024 net)
""",
    },
    {
        "document_id": "doc_api_platform_release_v3",
        "source": "engineering-release-notes",
        "title": "API Platform v3.0 Release Notes — May 2026",
        "document_type": "release_note",
        "published_at": "2026-05-15T00:00:00Z",
        "business_tags": ["api-platform", "release", "v3", "may-2026"],
        "permission_tags": [],
        "text": """# API Platform v3.0 Release Notes — May 2026

## Release Date
May 15, 2026

## Summary
API Platform v3.0 is a major release introducing GraphQL support, improved rate limiting controls, and a completely rewritten authentication module. This release addresses the top 3 feature requests from enterprise customers and resolves 14 high-severity production issues from the v2.x series.

## Breaking Changes
1. **JWT token format change**: Access tokens now use RS256 signing (previously HS256). All API clients must update to v3 SDK or implement RS256 verification before June 30, 2026.
2. **Rate limit header format**: `X-RateLimit-Remaining` now returns requests-per-minute rather than requests-per-day. Existing dashboard integrations may need updating.
3. **Deprecated endpoints removed**: `/v1/query/sync` removed (use `/v2/query/async`). `/v1/auth/token` removed (use `/v2/auth/signin`).

## New Features
### GraphQL API (Beta)
Full GraphQL schema now available at `/api/graphql`. Supports queries and mutations for all core resources (users, sessions, queries, reports). Subscriptions planned for v3.1.
- Introspection enabled in non-production environments
- Playground UI available at `/api/graphql/ui`
- Rate limits apply equally to REST and GraphQL endpoints

### Per-Workspace Rate Limit Controls
Administrators can now configure custom rate limits per workspace:
- Standard tier: 200 RPM (reduced from 400 in v2.x — see customer notice issued April 1)
- Pro tier: 1,000 RPM
- Enterprise tier: Custom, up to 10,000 RPM (contact sales)
- New API endpoint: `PUT /api/v2/admin/workspaces/{id}/rate-limits`

### Webhook Reliability Improvements
- Automatic retry with exponential backoff (3 retries: 1min, 5min, 30min)
- Dead-letter queue for failed webhook deliveries (accessible via admin dashboard)
- Signature verification now uses HMAC-SHA256 (previously SHA1)

## Bug Fixes
- Fixed: Certificate rotation script fails silently when distributed cache is unavailable (this was the root cause of the July 3 authentication outage — resolved in v3.0.1 hotfix)
- Fixed: Memory leak in connection pool under sustained high-concurrency load
- Fixed: Incorrect 403 returned for read-only operations when workspace is suspended (should return 402)
- Fixed: Rate limit counter not reset correctly after 60-second window boundary

## Performance Improvements
- Authentication latency reduced by 40% (from 18ms to 11ms p50)
- Query routing overhead reduced by 25%
- Cold-start time reduced from 8s to 3.2s (container startup optimization)

## Migration Guide
Full migration guide available at docs.governed-chatbi.com/api-platform/v3-migration.
Estimated migration effort: 2–4 hours for standard REST API integrations; 4–8 hours for custom authentication flows.
Support available via dedicated migration Slack channel (#api-v3-migration).

## Known Issues
- GraphQL subscriptions not yet available (targeted for v3.1, September 2026)
- Workspace-level rate limit changes may take up to 5 minutes to propagate to all edge nodes
""",
    },
    {
        "document_id": "doc_ml_pipeline_release_v2",
        "source": "engineering-release-notes",
        "title": "ML Pipeline v2.1 Release Notes — June 2026",
        "document_type": "release_note",
        "published_at": "2026-06-20T00:00:00Z",
        "business_tags": ["ml-pipeline", "release", "v2", "june-2026"],
        "permission_tags": [],
        "text": """# ML Pipeline v2.1 Release Notes — June 2026

## Release Date
June 20, 2026

## Summary
ML Pipeline v2.1 introduces the long-awaited Python SDK (beta), improved model serving latency, and a new AutoML configuration wizard for non-technical users. This release directly addresses feedback from 2026 H1 customer exit interviews where 29% of churned customers cited ML Pipeline complexity as a key reason for leaving.

## New Features

### Python SDK (Beta) — chatbi-ml-sdk v0.9.0
The ML Pipeline Python SDK is now available for early access.

```python
from chatbi_ml import PipelineClient, ModelConfig

client = PipelineClient(api_key="your-key")

# Define and run a pipeline in 5 lines
pipeline = client.create_pipeline("revenue-forecast")
pipeline.add_step("data-load", source="business.revenue_by_month")
pipeline.add_step("feature-eng", transform="lag_features", lags=[1, 3, 6])
pipeline.add_step("model", config=ModelConfig(type="xgboost", target="revenue"))
result = pipeline.run()
```

Install: `pip install chatbi-ml-sdk==0.9.0`
Docs: docs.governed-chatbi.com/ml-pipeline/python-sdk

Known limitations (beta):
- Max 100,000 rows per pipeline run
- GPU acceleration not yet supported
- Custom model registries not yet supported (planned v2.2)

### AutoML Configuration Wizard
Non-technical users can now configure ML pipelines through a guided UI wizard:
1. Select data source (SQL table or uploaded CSV)
2. Choose prediction target column
3. Select training frequency (real-time, hourly, daily)
4. Review auto-generated feature suggestions
5. Launch and monitor pipeline

Estimated onboarding time with wizard: 45 minutes (down from 14 days for manual setup).

### Model Serving Latency Improvements
- p50 inference latency: 28ms (↓ from 67ms in v2.0)
- p99 inference latency: 145ms (↓ from 380ms in v2.0)
- Throughput: 800 inferences/second per worker (↑ from 320 in v2.0)

Achieved through: batched inference by default, ONNX runtime integration, connection pooling to model store.

## Bug Fixes
- Fixed: Index fragmentation after bulk data migration causing query timeouts (root cause of July 12–16 Analytics Hub incident — same columnar store component)
- Fixed: Pipeline fails silently if feature engineering step encounters NaN values (now raises clear ValidationError)
- Fixed: Model version rollback leaves orphaned artifacts consuming storage

## Deprecations
- REST API v1 model endpoints (`/api/v1/models/*`) deprecated; removal planned December 2026
- Legacy YAML pipeline configuration format deprecated; JSON-schema format is default from v2.1

## Roadmap (v2.2 — September 2026)
- Custom model registry integration (MLflow, SageMaker)
- Scheduled pipeline runs (cron-based)
- A/B testing framework for model comparison
- GPU acceleration for transformer-based models
""",
    },
    {
        "document_id": "doc_analytics_hub_launch",
        "source": "product-marketing",
        "title": "Analytics Hub GA Launch — September 2025",
        "document_type": "release_note",
        "published_at": "2025-09-01T00:00:00Z",
        "business_tags": ["analytics-hub", "launch", "product", "september-2025"],
        "permission_tags": [],
        "text": """# Analytics Hub General Availability — September 2025

## Launch Summary
Analytics Hub reached General Availability on September 1, 2025 after a 4-month closed beta with 23 design partners. Analytics Hub is a real-time, collaborative business intelligence layer built on top of the Governed ChatBI platform, enabling teams to build, share, and schedule analytical reports with AI-assisted insights.

## Key Capabilities at GA
1. **Collaborative Workspaces**: Multiple analysts can co-edit dashboards in real-time (WebSocket-based, similar to Google Docs experience)
2. **AI Insight Cards**: Each chart auto-generates a 2-sentence natural-language summary powered by the Governed ChatBI LLM Gateway
3. **Semantic Metric Library**: Connects directly to the Semantic Layer — analysts define a metric once and reuse it across all reports
4. **Scheduled Delivery**: Reports delivered by email (daily, weekly, monthly) or Slack webhook
5. **Row-Level Security**: Inherits governance policies from the Governed platform (P0/P1/P2 sensitivity classification)

## Beta Program Results (May–August 2025)
- 23 design partners, 412 beta users
- Avg daily active users per company: 8.4
- Most-used feature: AI Insight Cards (87% of users)
- Highest NPS feature: Collaborative Workspaces (NPS +71)
- Lowest-rated feature: Scheduled Delivery reliability (3.1/5.0 — addressed in GA release)

## Pricing
- Included in Pro and Enterprise tiers (no additional cost)
- Standard tier: 3 workspaces, 5 users, 10 reports/month (upgrade for more)

## Post-Launch Metrics (September–December 2025)
- Activated workspaces: 182 in first 90 days
- Power users (5+ sessions/week): 94
- Report templates created by community: 47
- Support tickets related to Analytics Hub: 23 (lower than planned 40)

## Known GA Limitations (Fixed in Subsequent Releases)
- Maximum 500,000 rows per report chart (v1.1 increased to 5M)
- No cross-workspace metric sharing (v1.2 added shared metric library)
- Query timeout at 30 seconds for complex joins (v2.0 increased to 120 seconds and added query optimization)
""",
    },
    {
        "document_id": "doc_support_ops_june_2026",
        "source": "support-ops-weekly-reporting",
        "title": "Support Operations Weekly Review — June 2026",
        "document_type": "weekly_report",
        "published_at": "2026-06-30T00:00:00Z",
        "business_tags": ["support", "tickets", "june-2026"],
        "permission_tags": [],
        "text": """# Support Operations Weekly Review — June 2026

## Monthly Snapshot
- **Total tickets opened**: 156 (↑ 12% vs May 2026: 139)
- **Critical tickets**: 12 (consistent with May)
- **Average resolution time**: 8.7 hours (↓ from 9.3 hours in May)
- **First-contact resolution rate**: 71% (↑ from 68% in May)
- **CSAT score**: 4.4 / 5.0 (↑ from 4.2 in May)

## Volume by Product
| Product            | Total | Critical | High | Medium | Low | Avg Res. (hrs) |
|--------------------|-------|----------|------|--------|-----|----------------|
| Governed Analytics | 68    | 0        | 37   | 31     | 0   | 12.3           |
| Data Connectors    | 31    | 0        | 0    | 31     | 0   | 9.6            |
| LLM Gateway        | 8     | 8        | 0    | 0      | 0   | 5.2            |
| API Platform       | 26    | 0        | 0    | 26     | 0   | 8.3            |
| Analytics Hub      | 24    | 0        | 0    | 24     | 0   | 8.2            |
| ML Pipeline        | 32    | 4        | 28   | 0      | 0   | 14.9           |
| Reporting Studio   | 8     | 0        | 0    | 0      | 8   | 1.3            |

## Key Issues
**Governed Analytics**: Enterprise workspace rollout for 12 new accounts drove elevated high-severity ticket volume. All related to data-schema mapping during initial setup. Documentation improvement in progress.

**LLM Gateway — Rate Limit Pre-Announcement Impact**: Following the April 1 communication about the July 1 rate-limit reduction (400 → 200 RPM for Standard tier), 8 critical tickets received from Standard-tier enterprise customers requesting exceptions or early migration to Pro. Commercial team handling case-by-case. Estimated revenue impact from forced upgrades: $48,000 ARR uplift.

**ML Pipeline**: Indexing fragmentation issue (ultimately caused July 12–16 Analytics Hub incident) first observed in June on 3 ML Pipeline customers. Ticket triage did not escalate to engineering; root cause identified retrospectively in August post-mortem.

## Staffing
June marked the completion of the support team expansion: 4 new support engineers hired (2 for Governed Analytics, 1 for LLM Gateway, 1 for ML Pipeline). Full ramp by end of July.

## CSAT Drivers
Top positive feedback themes: fast resolution for LLM Gateway issues (Tier-2 dedicated team), proactive outreach for Governed Analytics setup.
Top negative feedback themes: ML Pipeline documentation gaps; long wait times for P2 tickets during business hours.
""",
    },
]


def insert_sql_data(conn):
    cur = conn.cursor()
    print("Inserting revenue rows...")
    cur.executemany(
        "INSERT INTO business.revenue_by_month (month, revenue) VALUES (%s, %s) "
        "ON CONFLICT (month) DO UPDATE SET revenue = EXCLUDED.revenue",
        REVENUE_ROWS,
    )
    print(f"  → {len(REVENUE_ROWS)} revenue rows inserted/updated")

    print("Inserting support ticket rows...")
    cur.executemany(
        "INSERT INTO business.support_ticket_summary "
        "(month, product, severity, ticket_count, avg_resolution_hours) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT (month, product, severity) DO UPDATE SET "
        "ticket_count = EXCLUDED.ticket_count, avg_resolution_hours = EXCLUDED.avg_resolution_hours",
        TICKET_ROWS,
    )
    print(f"  → {len(TICKET_ROWS)} ticket rows inserted/updated")

    print("Creating campaigns table...")
    cur.execute(CREATE_CAMPAIGNS_TABLE)
    cur.executemany(
        "INSERT INTO business.campaigns "
        "(campaign_id, month, campaign_name, channel, spend, impressions, clicks, conversions, attributed_revenue, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (campaign_id) DO NOTHING",
        CAMPAIGN_ROWS,
    )
    print(f"  → {len(CAMPAIGN_ROWS)} campaign rows inserted")

    print("Updating semantic.metrics with campaign_roi pointing to campaigns table...")
    cur.execute("""
        UPDATE semantic.metrics
        SET table_name = 'business.campaigns',
            formula    = 'SUM(attributed_revenue) / NULLIF(SUM(spend), 0)'
        WHERE metric_id = 'campaign_roi'
    """)

    conn.commit()
    print("SQL data committed.\n")


def _chunk_text(text: str, size: int = 90, overlap: int = 15) -> list[str]:
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + size]))
        start += size - overlap
    return [c for c in chunks if c.strip()]


def insert_knowledge_docs(conn):
    cur = conn.cursor()
    print("Inserting knowledge documents and chunks...")

    DOC_TYPE_MAP = {
        "incident": "incident_report",
        "weekly_report": "weekly_report",
        "finance_report": "analytics_report",
        "campaign": "marketing_report",
        "release_note": "reference",
    }

    for doc in DOCUMENTS:
        source_id = doc["document_id"]
        title = doc["title"]
        db_doc_type = DOC_TYPE_MAP.get(doc["document_type"], "analytics_report")
        published_at = doc["published_at"][:10]
        tags = doc.get("business_tags", [])

        cur.execute("""
            INSERT INTO knowledge.documents
              (source_id, title, doc_type, publish_time, business_tags, allowed_roles)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
              title = EXCLUDED.title,
              doc_type = EXCLUDED.doc_type,
              publish_time = EXCLUDED.publish_time,
              business_tags = EXCLUDED.business_tags
        """, (source_id, title, db_doc_type, published_at, tags, []))

        cur.execute("""
            DELETE FROM knowledge.doc_embeddings
            WHERE chunk_id IN (SELECT chunk_id FROM knowledge.doc_chunks WHERE source_id = %s)
        """, (source_id,))
        cur.execute("DELETE FROM knowledge.doc_chunks WHERE source_id = %s", (source_id,))

        chunks = _chunk_text(doc["text"])
        for idx, chunk_text in enumerate(chunks, 1):
            chunk_id = f"{source_id}_c{idx:03d}"
            cur.execute("""
                INSERT INTO knowledge.doc_chunks (chunk_id, source_id, chunk_index, chunk_text, metadata)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET chunk_text = EXCLUDED.chunk_text
            """, (chunk_id, source_id, idx, chunk_text, psycopg.types.json.Jsonb({})))

    conn.commit()
    total_chunks = sum(len(_chunk_text(d["text"])) for d in DOCUMENTS)
    print(f"  → {len(DOCUMENTS)} documents, ~{total_chunks} chunks written to knowledge tables\n")


def get_admin_token():
    resp = requests.post(
        f"{API_BASE}/api/v2/auth/signin",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["data"]["tokens"]["access_token"]


def index_document(token, doc, idx, total):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Request-Id": f"req_seed_doc_{idx:03d}",
        "Idempotency-Key": f"expand-seed-{doc['document_id']}",
    }
    resp = requests.post(
        f"{API_BASE}/api/v2/documents/index",
        headers=headers,
        json=doc,
        timeout=30,
    )
    status = resp.status_code
    try:
        body = resp.json()
        data = body.get("data", {}) or {}
        chunk_count = data.get("indexed_chunk_count", "?")
        error = body.get("error")
    except Exception:
        chunk_count = "?"
        error = resp.text[:120]
    print(f"  [{idx}/{total}] {doc['document_id']}: HTTP {status}, chunks={chunk_count}"
          + (f" ERROR: {error}" if error else ""))
    time.sleep(0.3)


def main():
    print("=== Connecting to database ===")
    with psycopg.connect(DB_URL) as conn:
        insert_sql_data(conn)
        insert_knowledge_docs(conn)

    print("=== Authenticating as admin ===")
    token = get_admin_token()
    print(f"  → Token obtained: {token[:20]}...\n")

    print(f"=== Indexing {len(DOCUMENTS)} documents ===")
    for i, doc in enumerate(DOCUMENTS, 1):
        index_document(token, doc, i, len(DOCUMENTS))

    print("\n=== Done ===")
    print(f"Revenue rows added:  {len(REVENUE_ROWS)}")
    print(f"Ticket rows added:   {len(TICKET_ROWS)}")
    print(f"Campaign rows added: {len(CAMPAIGN_ROWS)}")
    print(f"Documents indexed:   {len(DOCUMENTS)}")


if __name__ == "__main__":
    main()
