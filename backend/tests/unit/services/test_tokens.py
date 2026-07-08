from app.services.tokens import generate_download_token, generate_manage_token


def test_download_token_is_url_safe_and_long() -> None:
    t = generate_download_token()
    assert isinstance(t, str)
    assert len(t) >= 32
    assert all(c.isalnum() or c in "-_" for c in t)


def test_manage_token_is_url_safe_and_long() -> None:
    t = generate_manage_token()
    assert isinstance(t, str)
    assert len(t) >= 32
    assert all(c.isalnum() or c in "-_" for c in t)


def test_tokens_are_distinct_across_calls() -> None:
    tokens = {generate_download_token() for _ in range(100)}
    assert len(tokens) == 100


def test_download_and_manage_use_different_generators() -> None:
    assert generate_download_token() != generate_manage_token()
