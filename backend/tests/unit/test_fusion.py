import pytest

from app.services.retrieval.fusion import reciprocal_rank_fusion


def test_single_ranking_keeps_order_with_rrf_scores() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"]], k=60)

    assert [key for key, _ in fused] == ["a", "b", "c"]
    assert fused[0][1] == pytest.approx(1 / 61)
    assert fused[2][1] == pytest.approx(1 / 63)


def test_scores_sum_across_rankings() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=10))

    assert fused["a"] == pytest.approx(1 / 11 + 1 / 12)
    assert fused["b"] == pytest.approx(1 / 12 + 1 / 11)


def test_item_in_both_lists_beats_top_of_one_list() -> None:
    keyword = ["k1", "shared", "k3"]
    vector = ["v1", "shared", "v3"]

    fused = reciprocal_rank_fusion([keyword, vector], k=60)

    assert fused[0][0] == "shared"
    assert {key for key, _ in fused} == {"k1", "k3", "v1", "v3", "shared"}


def test_ties_broken_by_best_rank_then_first_appearance() -> None:
    # "x" and "y" each appear once at rank 1 -> exact score tie, first seen wins.
    assert [key for key, _ in reciprocal_rank_fusion([["x"], ["y"]], k=60)] == ["x", "y"]
    # "p" (ranks 1 and 3) vs "q" (ranks 2 and 2): nearly equal sums; the exact values decide.
    fused = reciprocal_rank_fusion([["p", "q", "r"], ["s", "q", "p"]], k=1)
    scores = dict(fused)
    assert scores["p"] == pytest.approx(1 / 2 + 1 / 4)
    assert scores["q"] == pytest.approx(1 / 3 + 1 / 3)
    assert [key for key, _ in fused][:2] == ["p", "q"]


def test_duplicates_within_a_ranking_count_once() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "a", "b"]], k=1))

    assert fused["a"] == pytest.approx(1 / 2)
    assert fused["b"] == pytest.approx(1 / 4)  # rank 3 is still its position in the list


def test_larger_k_reduces_gap_between_ranks() -> None:
    small_k = dict(reciprocal_rank_fusion([["a", "b"]], k=1))
    large_k = dict(reciprocal_rank_fusion([["a", "b"]], k=1000))

    assert small_k["a"] / small_k["b"] > large_k["a"] / large_k["b"]


def test_empty_inputs() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_works_with_integer_ids() -> None:
    assert [key for key, _ in reciprocal_rank_fusion([[3, 1], [1, 2]], k=60)] == [1, 3, 2]


def test_invalid_k() -> None:
    with pytest.raises(ValueError, match="k must be"):
        reciprocal_rank_fusion([["a"]], k=0)
