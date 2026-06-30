from chatbi.core.contracts import ErrorCode
from chatbi.governance import GuardrailErrorPayloadBuilder


def test_guardrail_error_payload_builder_maps_object_denial() -> None:
    error = GuardrailErrorPayloadBuilder().build(
        error_code=ErrorCode.SQL_DENY_OBJECT,
        message="Role business_user is not allowed to query table users.",
    )

    assert error == {
        "code": "SQL_DENIED_OBJECT",
        "message": "Role business_user is not allowed to query table users.",
        "retryable": False,
    }


def test_guardrail_error_payload_builder_maps_timeout_denial() -> None:
    error = GuardrailErrorPayloadBuilder().build(
        error_code=ErrorCode.SQL_DENY_TIMEOUT,
        message="Query exceeded timeout.",
    )

    assert error == {
        "code": "SQL_DENIED_TIMEOUT",
        "message": "Query exceeded timeout.",
        "retryable": False,
    }


def test_guardrail_error_payload_builder_maps_write_denial() -> None:
    error = GuardrailErrorPayloadBuilder().build(
        error_code=ErrorCode.SQL_DENY_STATEMENT,
        message="Only SELECT statements are allowed.",
    )

    assert error == {
        "code": "SQL_DENIED_WRITE_OPERATION",
        "message": "Only SELECT statements are allowed.",
        "retryable": False,
    }


def test_guardrail_error_payload_builder_uses_default_message() -> None:
    error = GuardrailErrorPayloadBuilder().build(error_code=None, message=None)

    assert error == {
        "code": "SQL_DENIED_WRITE_OPERATION",
        "message": "SQL was denied by guardrail.",
        "retryable": False,
    }
