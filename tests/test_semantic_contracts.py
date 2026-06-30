import pytest

from chatbi.semantic.pipeline import SemanticResolveRequest


def test_semantic_resolve_request_accepts_spec_contract_fields() -> None:
    request = SemanticResolveRequest(
        trace_id="trc_001",
        user_id="u_001",
        role="business_user",
        question="show monthly revenue for 2024",
        locale="en",
    )

    assert request.trace_id == "trc_001"
    assert request.role == "business_user"
    assert request.locale == "en"


def test_semantic_resolve_request_rejects_invalid_question_length() -> None:
    with pytest.raises(ValueError, match="question length"):
        SemanticResolveRequest(
            trace_id="trc_001",
            user_id="u_001",
            role="analyst",
            question="",
            locale="zh-CN",
        )


def test_semantic_resolve_request_rejects_invalid_role_and_locale() -> None:
    with pytest.raises(ValueError, match="role"):
        SemanticResolveRequest(
            trace_id="trc_001",
            user_id="u_001",
            role="viewer",  # type: ignore[arg-type]
            question="show revenue",
            locale="en",
        )

    with pytest.raises(ValueError, match="locale"):
        SemanticResolveRequest(
            trace_id="trc_001",
            user_id="u_001",
            role="admin",
            question="show revenue",
            locale="fr",  # type: ignore[arg-type]
        )
