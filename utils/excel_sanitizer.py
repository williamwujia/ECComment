from __future__ import annotations

import pandas as pd

from utils.text_cleaner import remove_invalid_xml_chars


def sanitize_frame_for_excel(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy whose string cells are safe for XML-based workbooks."""
    result = frame.copy()
    for column in result.columns:
        result[column] = result[column].map(
            lambda value: remove_invalid_xml_chars(value)
            if isinstance(value, str)
            else value
        )
    return result
