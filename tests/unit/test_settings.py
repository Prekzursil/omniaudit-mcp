from omniaudit.core.settings import Settings


def test_csv_set_fields_are_parsed() -> None:
    cfg = Settings(
        repo_write_allowlist="a/b,c/d",
        url_allowlist="example.com",
        url_denylist="localhost,127.0.0.1",
    )

    assert cfg.repo_write_allowlist_set == {"a/b", "c/d"}
    assert cfg.url_allowlist_set == {"example.com"}
    assert cfg.url_denylist_set == {"localhost", "127.0.0.1"}
