"""Golden test vectors — fixed master key, file key, IV, plaintext → fixed ciphertext.

Purpose: catch accidental algorithm changes or library-version regressions.
If this fails, stop and investigate — changing these vectors means existing
ciphertext in production may become unreadable.
"""

import io

from app.crypto.envelope import unwrap_key, wrap_key
from app.crypto.stream import decrypt_stream, encrypt_stream

# ---- fixed inputs (do not change) ----
MASTER_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f" "101112131415161718191a1b1c1d1e1f")
FILE_KEY = bytes.fromhex("202122232425262728292a2b2c2d2e2f" "303132333435363738393a3b3c3d3e3f")
IV = bytes.fromhex("404142434445464748494a4b")
PLAINTEXT = b"Fylix golden vector v1"

# ---- expected outputs (computed once; changing these means broken backwards-compat) ----
EXPECTED_WRAPPED_HEX = (
    "04f8a3c3c302d3b0b7e94b14dcf85ad1da69cd74056ed7907d3cb49fb27799a4104db058f2901adb"
)
EXPECTED_CT_HEX = "842dd1e82856a2643e563546a53c341167e1efa38371592fd86fb8fbe0c4ad018212c117acaf"
EXPECTED_SHA256_HEX = "e3b38ed3f0098ded9026ec0fc40c7cde0c223a6a63b3bd15e63a1af42f2fcca6"


def test_wrap_is_deterministic() -> None:
    wrapped = wrap_key(MASTER_KEY, FILE_KEY)
    assert wrapped.hex() == EXPECTED_WRAPPED_HEX
    assert unwrap_key(MASTER_KEY, wrapped) == FILE_KEY


def test_encrypt_is_deterministic() -> None:
    out = io.BytesIO()
    sha = encrypt_stream(FILE_KEY, IV, io.BytesIO(PLAINTEXT), out)
    assert out.getvalue().hex() == EXPECTED_CT_HEX
    assert sha.hex() == EXPECTED_SHA256_HEX

    # roundtrip decryption also works
    back = io.BytesIO()
    decrypt_stream(FILE_KEY, IV, io.BytesIO(out.getvalue()), back)
    assert back.getvalue() == PLAINTEXT
