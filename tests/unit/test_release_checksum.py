from omniaudit.modules.releasebutler.checksum import sha256_hex, verify_checksum


def test_release_checksum_verifies() -> None:
    data = b"omniaudit"
    digest = sha256_hex(data)

    assert verify_checksum(data, digest) is True
    assert verify_checksum(data, "deadbeef") is False
