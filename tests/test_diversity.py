from krystal_quorum.diversity import analyze_reviewer_diversity, reviewer_family


def test_diversity_ok_for_pairwise_distinct_families():
    report = analyze_reviewer_diversity(
        ["ollama:qwen2.5:14b", "openai:gpt-4.1", "command:codex"]
    )

    assert report.status == "ok"
    assert [item.family for item in report.reviewers] == ["qwen2.5", "gpt-4.1", "codex"]


def test_diversity_low_when_two_reviewers_share_family():
    report = analyze_reviewer_diversity(["openai:gpt-4.1", "openai:gpt-4.1-mini"])

    assert report.status == "low"
    assert "gpt-4.1" in report.reason


def test_diversity_low_for_duplicate_ollama_size_variants():
    report = analyze_reviewer_diversity(["ollama:qwen2.5:14b", "ollama:qwen2.5:32b"])

    assert report.status == "low"


def test_diversity_reason_lists_all_shared_families():
    report = analyze_reviewer_diversity(
        [
            "ollama:qwen2.5:14b",
            "ollama:qwen2.5:32b",
            "openai:gpt-4.1",
            "openai:gpt-4.1-mini",
        ]
    )

    assert report.status == "low"
    assert "qwen2.5" in report.reason
    assert "gpt-4.1" in report.reason


def test_reviewer_family_strips_common_tags_and_profiles():
    assert reviewer_family("ollama:deepseek-v4-pro:cloud").family == "deepseek-v4"
    assert reviewer_family("ollama:igorls/gemma-4-12B-it-heretic-GGUF:latest").family == (
        "gemma-4"
    )
