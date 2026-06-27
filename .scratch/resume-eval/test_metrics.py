import run_resume_eval
import sys
from pathlib import Path
from run_resume_eval import percentile_nearest_rank, recall_at_k


def test_recall_at_k_uses_only_first_k_results():
    assert recall_at_k(["a", "b"], ["x", "a", "y", "z", "q", "b"], 5) == 0.5


def test_percentile_nearest_rank_returns_observed_value():
    assert percentile_nearest_rank([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0


def test_cli_initializes_application_runtime_before_evaluation():
    assert hasattr(run_resume_eval, "initialize_runtime")


def test_knowledge_base_instruction_document_is_not_an_eval_case():
    assert run_resume_eval.is_eval_document_title("00_知识库使用说明") is False
    assert run_resume_eval.is_eval_document_title("08_退换货规则与流程") is True


def test_project_root_is_added_to_python_import_path():
    project_root = Path(run_resume_eval.__file__).resolve().parents[2]
    assert str(project_root) in sys.path


def test_explicit_embedding_url_overrides_database_cache():
    from app.services import embedding_config

    original = dict(embedding_config._cache)
    try:
        embedding_config._cache["embedding_base_url"] = "http://host.docker.internal:11434"
        run_resume_eval.override_embedding_base_url("http://127.0.0.1:11434/")
        assert embedding_config.get_embedding_base_url() == "http://127.0.0.1:11434"
    finally:
        embedding_config._cache.clear()
        embedding_config._cache.update(original)
