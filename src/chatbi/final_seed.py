"""Final-version deterministic seed profiles and quality checks."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Mapping, cast

from chatbi.embedding_vector_rag import DocumentRecord, EmbeddingVectorRagService
from chatbi.metrics import MetricEvaluator


class SeedProfileName(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass(frozen=True, slots=True)
class SeedProfile:
    name: SeedProfileName
    org_count: int
    user_count: int
    business_row_count: int
    document_count: int
    chunk_token_limit: int
    explicit_only: bool = False


@dataclass(frozen=True, slots=True)
class SeedDataset:
    profile: SeedProfile
    organizations: tuple[Mapping[str, object], ...]
    users: tuple[Mapping[str, object], ...]
    customers: tuple[Mapping[str, object], ...]
    orders: tuple[Mapping[str, object], ...]
    refunds: tuple[Mapping[str, object], ...]
    documents: tuple[DocumentRecord, ...]
    vector_chunk_count: int
    vector_count: int
    vector_rag_service: EmbeddingVectorRagService

    @property
    def rows_by_table(self) -> Mapping[str, tuple[Mapping[str, object], ...]]:
        return {
            "organizations": self.organizations,
            "users": self.users,
            "customers": self.customers,
            "orders": self.orders,
            "refunds": self.refunds,
        }


@dataclass(frozen=True, slots=True)
class SeedQualityViolation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SeedQualityReport:
    profile_name: SeedProfileName
    violations: tuple[SeedQualityViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


SEED_PROFILES: Mapping[SeedProfileName, SeedProfile] = {
    SeedProfileName.SMALL: SeedProfile(
        name=SeedProfileName.SMALL,
        org_count=2,
        user_count=5,
        business_row_count=240,
        document_count=4,
        chunk_token_limit=32,
    ),
    SeedProfileName.MEDIUM: SeedProfile(
        name=SeedProfileName.MEDIUM,
        org_count=5,
        user_count=35,
        business_row_count=100_000,
        document_count=1_000,
        chunk_token_limit=32,
    ),
    SeedProfileName.LARGE: SeedProfile(
        name=SeedProfileName.LARGE,
        org_count=10,
        user_count=100,
        business_row_count=1_000_000,
        document_count=10_000,
        chunk_token_limit=32,
        explicit_only=True,
    ),
}


def build_seed_dataset(
    profile_name: SeedProfileName = SeedProfileName.SMALL,
    *,
    reset: bool = True,
    allow_large: bool = False,
) -> SeedDataset:
    profile = SEED_PROFILES[profile_name]
    if profile.explicit_only and not allow_large:
        raise ValueError("large seed must be explicitly enabled with allow_large=True")

    vector_rag_service = EmbeddingVectorRagService()
    organizations = _organizations(profile.org_count)
    users = _users(organizations, profile.user_count)
    customers = _customers(organizations)
    orders = _orders(organizations, customers, profile.business_row_count)
    refunds = _refunds(orders)
    documents, vector_chunk_count = _index_documents(
        profile=profile,
        organizations=organizations,
        vector_rag_service=vector_rag_service,
    )

    return SeedDataset(
        profile=profile,
        organizations=organizations,
        users=users,
        customers=customers,
        orders=orders,
        refunds=refunds,
        documents=documents,
        vector_chunk_count=vector_chunk_count,
        vector_count=vector_chunk_count,
        vector_rag_service=vector_rag_service,
    )


def validate_seed_dataset(dataset: SeedDataset) -> SeedQualityReport:
    violations: list[SeedQualityViolation] = []
    required_tables = {
        "organizations": dataset.organizations,
        "users": dataset.users,
        "customers": dataset.customers,
        "orders": dataset.orders,
        "documents": dataset.documents,
    }
    for table_name, rows in required_tables.items():
        if not rows:
            violations.append(
                SeedQualityViolation(
                    code="EMPTY_REQUIRED_TABLE",
                    message=f"{table_name} must not be empty.",
                )
            )

    org_ids = {str(org["org_id"]) for org in dataset.organizations}
    if len(org_ids) < 2:
        violations.append(
            SeedQualityViolation(
                code="TENANT_COUNT_TOO_LOW",
                message="seed data must include at least two tenants.",
            )
        )

    customer_org_by_id = {customer["customer_id"]: customer["org_id"] for customer in dataset.customers}
    for order in dataset.orders:
        customer_org = customer_org_by_id.get(order.get("customer_id"))
        if customer_org is None:
            violations.append(
                SeedQualityViolation(
                    code="MISSING_CUSTOMER_FK",
                    message=f"order {order.get('order_id')} references a missing customer.",
                )
            )
        elif customer_org != order.get("org_id"):
            violations.append(
                SeedQualityViolation(
                    code="TENANT_LEAKAGE",
                    message=f"order {order.get('order_id')} crosses tenant boundary.",
                )
            )

    if dataset.vector_chunk_count == 0 or dataset.vector_count == 0:
        violations.append(
            SeedQualityViolation(
                code="EMPTY_VECTOR_STORE",
                message="seeded vector store must include chunks and vectors.",
            )
        )
    if dataset.vector_chunk_count != dataset.vector_count:
        violations.append(
            SeedQualityViolation(
                code="VECTOR_COUNT_MISMATCH",
                message="seeded vector count must equal chunk count.",
            )
        )

    revenue = MetricEvaluator().evaluate("revenue", {"orders": dataset.orders})
    if not isinstance(revenue, Decimal) or revenue <= Decimal("0"):
        violations.append(
            SeedQualityViolation(
                code="METRIC_SANITY_FAILED",
                message="seed revenue must be positive.",
            )
        )

    return SeedQualityReport(
        profile_name=dataset.profile.name,
        violations=tuple(violations),
    )


def seed_dataset_to_artifact(dataset: SeedDataset) -> dict[str, object]:
    return {
        "profile": dataset.profile.name.value,
        "counts": {
            "organizations": len(dataset.organizations),
            "users": len(dataset.users),
            "customers": len(dataset.customers),
            "orders": len(dataset.orders),
            "refunds": len(dataset.refunds),
            "documents": len(dataset.documents),
            "vector_chunks": dataset.vector_chunk_count,
            "vectors": dataset.vector_count,
        },
        "tables": {
            "organizations": list(dataset.organizations),
            "users": list(dataset.users),
            "customers": list(dataset.customers),
            "orders": list(dataset.orders),
            "refunds": list(dataset.refunds),
        },
        "documents": [
            {
                "document_id": document.document_id,
                "org_id": document.org_id,
                "title": document.title,
                "source_type": document.source_type,
                "owner_user_id": document.owner_user_id,
                "version": document.version,
                "access_policy": dict(document.access_policy),
                "status": document.status,
            }
            for document in dataset.documents
        ],
    }


def read_seed_artifact(path: str | Path) -> dict[str, object]:
    raw_artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw_artifact, dict):
        raise ValueError("seed artifact must be a JSON object")
    return cast(dict[str, object], raw_artifact)


def validate_seed_artifact(artifact: Mapping[str, object]) -> SeedQualityReport:
    violations: list[SeedQualityViolation] = []
    profile_name = _profile_name_from_artifact(artifact, violations)
    counts = _mapping_field(artifact, "counts", violations)
    tables = _mapping_field(artifact, "tables", violations)
    organizations = _rows_field(tables, "organizations", violations)
    users = _rows_field(tables, "users", violations)
    customers = _rows_field(tables, "customers", violations)
    orders = _rows_field(tables, "orders", violations)
    refunds = _rows_field(tables, "refunds", violations)
    documents = _rows_field(artifact, "documents", violations)

    table_counts = {
        "organizations": len(organizations),
        "users": len(users),
        "customers": len(customers),
        "orders": len(orders),
        "refunds": len(refunds),
        "documents": len(documents),
    }
    for count_name, actual_count in table_counts.items():
        expected_count = _int_count(counts, count_name, violations)
        if expected_count is not None and expected_count != actual_count:
            violations.append(
                SeedQualityViolation(
                    code="ARTIFACT_COUNT_MISMATCH",
                    message=(
                        f"artifact count {count_name}={expected_count} "
                        f"does not match rows={actual_count}."
                    ),
                )
            )

    org_ids = {str(org.get("org_id")) for org in organizations if org.get("org_id") is not None}
    if len(org_ids) < 2:
        violations.append(
            SeedQualityViolation(
                code="TENANT_COUNT_TOO_LOW",
                message="seed artifact must include at least two tenants.",
            )
        )

    customer_org_by_id = {
        customer.get("customer_id"): customer.get("org_id")
        for customer in customers
        if customer.get("customer_id") is not None
    }
    for order in orders:
        customer_org = customer_org_by_id.get(order.get("customer_id"))
        if customer_org is None:
            violations.append(
                SeedQualityViolation(
                    code="MISSING_CUSTOMER_FK",
                    message=f"artifact order {order.get('order_id')} references a missing customer.",
                )
            )
        elif customer_org != order.get("org_id"):
            violations.append(
                SeedQualityViolation(
                    code="TENANT_LEAKAGE",
                    message=f"artifact order {order.get('order_id')} crosses tenant boundary.",
                )
            )

    vector_chunk_count = _int_count(counts, "vector_chunks", violations)
    vector_count = _int_count(counts, "vectors", violations)
    if vector_chunk_count == 0 or vector_count == 0:
        violations.append(
            SeedQualityViolation(
                code="EMPTY_VECTOR_STORE",
                message="seed artifact must include chunk and vector counts.",
            )
        )
    if vector_chunk_count is not None and vector_count is not None and vector_chunk_count != vector_count:
        violations.append(
            SeedQualityViolation(
                code="VECTOR_COUNT_MISMATCH",
                message="seed artifact vector count must equal chunk count.",
            )
        )

    revenue = MetricEvaluator().evaluate("revenue", {"orders": orders})
    if not isinstance(revenue, Decimal) or revenue <= Decimal("0"):
        violations.append(
            SeedQualityViolation(
                code="METRIC_SANITY_FAILED",
                message="seed artifact revenue must be positive.",
            )
        )

    return SeedQualityReport(
        profile_name=profile_name,
        violations=tuple(violations),
    )


def _profile_name_from_artifact(
    artifact: Mapping[str, object],
    violations: list[SeedQualityViolation],
) -> SeedProfileName:
    profile_value = artifact.get("profile")
    try:
        return SeedProfileName(str(profile_value))
    except ValueError:
        violations.append(
            SeedQualityViolation(
                code="UNKNOWN_SEED_PROFILE",
                message=f"seed artifact profile {profile_value!r} is not supported.",
            )
        )
        return SeedProfileName.SMALL


def _mapping_field(
    row: Mapping[str, object],
    field_name: str,
    violations: list[SeedQualityViolation],
) -> Mapping[str, object]:
    value = row.get(field_name)
    if isinstance(value, dict):
        return cast(Mapping[str, object], value)
    violations.append(
        SeedQualityViolation(
            code="ARTIFACT_SCHEMA_INVALID",
            message=f"seed artifact field {field_name} must be an object.",
        )
    )
    return {}


def _rows_field(
    row: Mapping[str, object],
    field_name: str,
    violations: list[SeedQualityViolation],
) -> tuple[Mapping[str, object], ...]:
    value = row.get(field_name)
    if not isinstance(value, list):
        violations.append(
            SeedQualityViolation(
                code="ARTIFACT_SCHEMA_INVALID",
                message=f"seed artifact field {field_name} must be an array.",
            )
        )
        return ()
    rows: list[Mapping[str, object]] = []
    items = cast(list[object], value)
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            violations.append(
                SeedQualityViolation(
                    code="ARTIFACT_SCHEMA_INVALID",
                    message=f"seed artifact field {field_name}[{index}] must be an object.",
                )
            )
            continue
        rows.append(cast(Mapping[str, object], item))
    return tuple(rows)


def _int_count(
    counts: Mapping[str, object],
    count_name: str,
    violations: list[SeedQualityViolation],
) -> int | None:
    value = counts.get(count_name)
    if isinstance(value, int):
        return value
    violations.append(
        SeedQualityViolation(
            code="ARTIFACT_SCHEMA_INVALID",
            message=f"seed artifact count {count_name} must be an integer.",
        )
    )
    return None


def _organizations(count: int) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "org_id": f"org_seed_{index + 1}",
            "name": f"Seed Organization {index + 1}",
        }
        for index in range(count)
    )


def _users(
    organizations: tuple[Mapping[str, object], ...],
    user_count: int,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "user_id": f"user_seed_{index + 1}",
            "org_id": organizations[index % len(organizations)]["org_id"],
            "email": f"user{index + 1}@seed.example",
            "role": "analyst" if index % 3 else "admin",
        }
        for index in range(user_count)
    )


def _customers(organizations: tuple[Mapping[str, object], ...]) -> tuple[Mapping[str, object], ...]:
    customers: list[Mapping[str, object]] = []
    customer_id = 1
    for org in organizations:
        for segment in ("enterprise", "growth", "self_service"):
            customers.append(
                {
                    "customer_id": customer_id,
                    "org_id": org["org_id"],
                    "segment": segment,
                    "region_id": "us-west" if customer_id % 2 else "us-east",
                }
            )
            customer_id += 1
    return tuple(customers)


def _orders(
    organizations: tuple[Mapping[str, object], ...],
    customers: tuple[Mapping[str, object], ...],
    row_count: int,
) -> tuple[Mapping[str, object], ...]:
    customers_by_org: dict[object, tuple[Mapping[str, object], ...]] = {}
    for org in organizations:
        customers_by_org[org["org_id"]] = tuple(
            customer for customer in customers if customer["org_id"] == org["org_id"]
        )

    orders: list[Mapping[str, object]] = []
    for index in range(row_count):
        org = organizations[index % len(organizations)]
        org_customers = customers_by_org[org["org_id"]]
        customer = org_customers[index % len(org_customers)]
        month = (index % 12) + 1
        campaign_boost = Decimal("1.35") if month in {6, 11} else Decimal("1.00")
        amount = Decimal("80.00") + Decimal(index % 37) * Decimal("3.25")
        orders.append(
            {
                "order_id": index + 1,
                "org_id": org["org_id"],
                "customer_id": customer["customer_id"],
                "product_id": (index % 9) + 1,
                "region_id": customer["region_id"],
                "order_amount": str((amount * campaign_boost).quantize(Decimal("0.01"))),
                "status": "paid" if index % 11 else "refunded",
                "order_date": f"2026-{month:02d}-{(index % 28) + 1:02d}",
                "scenario": "campaign_pause" if month == 7 else "baseline_growth",
            }
        )
    return tuple(orders)


def _refunds(orders: tuple[Mapping[str, object], ...]) -> tuple[Mapping[str, object], ...]:
    refunds: list[Mapping[str, object]] = []
    for order in orders:
        order_id = cast(int, order["order_id"])
        if order_id % 17 == 0:
            refunds.append(
                {
                    "refund_id": len(refunds) + 1,
                    "org_id": order["org_id"],
                    "order_id": order_id,
                    "refund_amount": "12.50",
                    "refund_date": order["order_date"],
                }
            )
    return tuple(refunds)


def _index_documents(
    *,
    profile: SeedProfile,
    organizations: tuple[Mapping[str, object], ...],
    vector_rag_service: EmbeddingVectorRagService,
) -> tuple[tuple[DocumentRecord, ...], int]:
    documents: list[DocumentRecord] = []
    chunk_count = 0
    for index in range(profile.document_count):
        org = organizations[index % len(organizations)]
        document = DocumentRecord(
            document_id=f"doc_seed_{profile.name}_{index + 1}",
            org_id=str(org["org_id"]),
            title=f"Seed revenue scenario {index + 1}",
            source_type="seed_report",
            owner_user_id=f"user_seed_{(index % profile.user_count) + 1}",
            version="2026-07-02",
            access_policy={"permission_tags": ("analyst",)},
        )
        chunks = vector_rag_service.index_document(
            trace_id=f"trc_seed_{profile.name}_{index + 1}",
            document=document,
            text=(
                "Revenue changed because campaign spend paused in July. "
                "Finance approval notes link campaign timing to revenue recovery."
            ),
            token_limit=profile.chunk_token_limit,
        )
        documents.append(document)
        chunk_count += len(chunks)
    return tuple(documents), chunk_count


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic final-version seed data.")
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in SeedProfileName),
        default=SeedProfileName.SMALL.value,
    )
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--output-json", help="Write a deterministic seed artifact JSON file.")
    parser.add_argument("--validate-json", help="Validate an existing deterministic seed artifact JSON file.")
    args = parser.parse_args(argv)

    if args.validate_json:
        artifact = read_seed_artifact(args.validate_json)
        report = validate_seed_artifact(artifact)
        print(
            f"seed_artifact={args.validate_json} profile={report.profile_name.value} "
            f"quality={'passed' if report.passed else 'failed'}"
        )
        if report.passed:
            return 0
        for violation in report.violations:
            print(f"{violation.code}: {violation.message}")
        return 1

    dataset = build_seed_dataset(
        SeedProfileName(args.profile),
        reset=True,
        allow_large=bool(args.allow_large),
    )
    report = validate_seed_dataset(dataset)
    print(
        "seed_profile="
        f"{dataset.profile.name.value} orgs={len(dataset.organizations)} "
        f"users={len(dataset.users)} business_rows={len(dataset.orders)} "
        f"documents={len(dataset.documents)} chunks={dataset.vector_chunk_count} "
        f"quality={'passed' if report.passed else 'failed'}"
    )
    if report.passed:
        if args.output_json:
            output_path = Path(args.output_json)
            output_path.write_text(
                json.dumps(seed_dataset_to_artifact(dataset), indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return 0
    for violation in report.violations:
        print(f"{violation.code}: {violation.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
