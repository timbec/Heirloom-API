import hashlib
import secrets

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()  # Argon2id

# Verified against when the email is unknown, so a miss takes as long as a wrong password
# and response time doesn't reveal which emails have accounts.
_DUMMY_HASH = _password_hash.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_HASH)
        return False
    return _password_hash.verify(password, password_hash)


def new_token() -> str:
    """A bearer token for the client. Only its hash is stored."""
    return secrets.token_urlsafe(30)  # 40 URL-safe characters


def hash_token(token: str) -> str:
    # A fast hash is fine here: tokens are long and random, unlike passwords.
    return hashlib.sha256(token.encode()).hexdigest()
