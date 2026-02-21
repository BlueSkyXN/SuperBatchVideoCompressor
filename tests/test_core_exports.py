from src.core import add_ignore_decode_errors_flags, is_decode_corruption_error


def test_core_exports_decode_error_helpers():
    assert callable(is_decode_corruption_error)
    assert callable(add_ignore_decode_errors_flags)
