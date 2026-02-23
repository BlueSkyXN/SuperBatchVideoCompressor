from src.core import (
    add_ignore_decode_errors_flags,
    add_timestamp_repair_flags,
    is_decode_corruption_error,
    is_timestamp_disorder_error,
)


def test_core_exports_decode_error_helpers():
    assert callable(is_decode_corruption_error)
    assert callable(is_timestamp_disorder_error)
    assert callable(add_ignore_decode_errors_flags)
    assert callable(add_timestamp_repair_flags)
