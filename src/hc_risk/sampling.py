from __future__ import annotations

import pandas as pd


def stratified_sample(
    frame: pd.DataFrame,
    target_col: str,
    max_rows: int | None,
    random_state: int,
) -> pd.DataFrame:
    if max_rows is None or len(frame) <= max_rows:
        return frame.copy()
    parts = []
    for idx, (target_value, group) in enumerate(frame.groupby(target_col, sort=False)):
        sample_n = max(1, round(len(group) / len(frame) * max_rows))
        sample_n = min(len(group), sample_n)
        parts.append(group.sample(n=sample_n, random_state=random_state + idx))
    sampled = pd.concat(parts, axis=0, ignore_index=True)
    if len(sampled) > max_rows:
        sampled = sampled.sample(n=max_rows, random_state=random_state).reset_index(drop=True)
    return sampled
