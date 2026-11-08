"""Test settings that must be in place before the app is imported."""

import os

# The app opens its database on import; tests never touch the real file.
os.environ["CODESEAT_DATABASE"] = ":memory:"

from app import accounts  # noqa: E402  (after the environment is set)

# Password hashing is deliberately slow; the tests need many accounts, not slow ones.
accounts.SCRYPT_N = 2**10
