from examples.rag_v2_demo import run_demo


def test_rag_v2_demo_runs_end_to_end() -> None:
    output = run_demo()

    assert "answer_text=" in output
    assert "ev_doc_demo_release_note_chunk_1" in output
    assert "rag_evt_trc_demo_rag_v2_1" in output
