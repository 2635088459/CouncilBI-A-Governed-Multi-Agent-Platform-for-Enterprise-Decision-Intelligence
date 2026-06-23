import pytest

from chatbi.core.contracts import Locale
from chatbi.frontend.i18n import (
    TranslationKey,
    translate,
    translated_texts,
)


def test_translate_returns_locale_specific_text() -> None:
    assert translate(TranslationKey.CHAT_SEND, Locale.EN) == "Send"
    assert translate(TranslationKey.CHAT_SEND, Locale.ZH_CN) == "发送"


def test_translate_fills_template_variables() -> None:
    text = translate(
        TranslationKey.RESULT_CONFIDENCE,
        Locale.EN,
        variables={"confidence": "92%"},
    )

    assert text == "Confidence: 92%"


def test_translate_rejects_missing_template_variables() -> None:
    with pytest.raises(ValueError, match="confidence"):
        translate(TranslationKey.RESULT_CONFIDENCE, Locale.EN, variables={})


def test_translated_texts_returns_full_locale_dictionary() -> None:
    texts = translated_texts(Locale.ZH_CN)

    assert len(texts) == len(TranslationKey)
    assert {text.key for text in texts} == set(TranslationKey)
