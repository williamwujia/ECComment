from __future__ import annotations

from matching.content_identity import match_pair


def detect_overlap_boundary(
    old_contents: list[dict],
    new_contents: list[dict],
    window_size: int = 50,
) -> dict:
    """Find the longest reliable contiguous block in old head versus new tail."""
    old_head = old_contents[: max(window_size, 1)]
    new_start = max(0, len(new_contents) - max(window_size, 1))
    new_tail = new_contents[new_start:]
    if not old_head or not new_tail:
        return _fallback()

    lengths = [[0] * (len(new_tail) + 1) for _ in range(len(old_head) + 1)]
    best: tuple[int, int, int, list[dict]] = (0, -1, -1, [])
    for old_index, old_row in enumerate(old_head, 1):
        for new_index, new_row in enumerate(new_tail, 1):
            matched, high, method = match_pair(old_row, new_row)
            if not matched:
                continue
            length = lengths[old_index - 1][new_index - 1] + 1
            lengths[old_index][new_index] = length
            pairs = []
            for offset in range(length):
                left_index = old_index - length + offset
                right_index = new_index - length + offset
                _, pair_high, pair_method = match_pair(
                    old_head[left_index], new_tail[right_index]
                )
                pairs.append(
                    {
                        "old_index": left_index,
                        "new_index": new_start + right_index,
                        "method": pair_method,
                        "high_confidence": pair_high,
                    }
                )
            high_count = sum(pair["high_confidence"] for pair in pairs)
            eligible = length >= 3 and high_count == length
            eligible = eligible or (length >= 5 and high_count >= 3)
            if eligible and length > best[0]:
                best = (length, old_index - length, new_index - length, pairs)

    if not best[0]:
        return _fallback()
    overlap_length, _, tail_start, pairs = best
    new_prefix_end = new_start + tail_start
    high_count = sum(pair["high_confidence"] for pair in pairs)
    return {
        "status": "overlap_found",
        "overlap_length": overlap_length,
        "new_prefix_end": new_prefix_end,
        "matched_pairs": pairs,
        "confidence": "high" if high_count == overlap_length else "medium",
    }


def _fallback() -> dict:
    return {
        "status": "fallback",
        "overlap_length": 0,
        "new_prefix_end": None,
        "matched_pairs": [],
        "confidence": "low",
    }
