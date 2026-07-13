"""Spec FV10.4 §6.4: session-scoped file_ids inheritance (FR-FV10-055)."""

from chatbi.history import InMemorySessionFileContext, resolve_effective_file_ids


def test_explicit_file_ids_win_and_become_the_sessions_active_value() -> None:
    # TC-FV10-146
    context = InMemorySessionFileContext()

    result = resolve_effective_file_ids(("ufile_x",), "ses_1", context)

    assert result == ("ufile_x",)
    assert context.get_active_file_ids("ses_1") == ("ufile_x",)


def test_empty_file_ids_inherits_the_sessions_active_value() -> None:
    # TC-FV10-147
    context = InMemorySessionFileContext()
    context.set_active_file_ids("ses_1", ("ufile_x",))

    result = resolve_effective_file_ids((), "ses_1", context)

    assert result == ("ufile_x",)


def test_empty_file_ids_with_no_active_value_stays_fileless() -> None:
    # TC-FV10-148
    context = InMemorySessionFileContext()

    result = resolve_effective_file_ids((), "ses_1", context)

    assert result == ()


def test_setting_one_sessions_active_file_ids_does_not_affect_another_session() -> None:
    # TC-FV10-149 / NFR-FV10-020
    context = InMemorySessionFileContext()

    resolve_effective_file_ids(("ufile_x",), "ses_a", context)

    assert context.get_active_file_ids("ses_b") == ()


def test_a_later_explicit_file_ids_replaces_the_sessions_previous_active_value() -> None:
    context = InMemorySessionFileContext()
    resolve_effective_file_ids(("ufile_x",), "ses_1", context)

    result = resolve_effective_file_ids(("ufile_y",), "ses_1", context)

    assert result == ("ufile_y",)
    assert context.get_active_file_ids("ses_1") == ("ufile_y",)


def test_empty_file_ids_after_an_explicit_value_still_inherits_it() -> None:
    context = InMemorySessionFileContext()
    resolve_effective_file_ids(("ufile_x",), "ses_1", context)

    result = resolve_effective_file_ids((), "ses_1", context)

    assert result == ("ufile_x",)
