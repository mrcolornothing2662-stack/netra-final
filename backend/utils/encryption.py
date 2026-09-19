"""
CyberDrishti AI — File Vault Envelope Encryption
Provides AES-256-GCM envelope encryption at rest for seized forensic evidence.
Keys are managed via a pluggable KeyProvider interface (environment/local for dev,
extensible for KMS/HSM in on-premise production deployments).
"""
from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from config import settings


class KeyProvider(ABC):
    """Abstract interface for loading the Key Encryption Key (KEK / Master Key)."""

    @abstractmethod
    def get_kek(self) -> bytes:
        """Returns 32 bytes (256 bits) Key Encryption Key."""
        raise NotImplementedError


class EnvKeyProvider(KeyProvider):
    """
    Key provider loading the master key from environment variables.
    Derives a 256-bit key using HKDF-SHA256 if the raw key is not exactly 32 bytes.
    """

    def __init__(self, key_material: Optional[str] = None):
        self._raw_material = (
            key_material
            or getattr(settings, "vault_master_key", None)
            or settings.secret_key
        )

    def get_kek(self) -> bytes:
        raw_bytes = self._raw_material.encode("utf-8")
        if len(raw_bytes) == 32:
            return raw_bytes
        # Derive a cryptographically sound 32-byte key via HKDF
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"CYBERDRISHTI_FILE_VAULT_KEK_SALT_v1",
            info=b"NETRA_ENVELOPE_ENCRYPTION_MASTER_KEY",
        )
        return hkdf.derive(raw_bytes)


_default_provider: Optional[KeyProvider] = None


def get_default_key_provider() -> KeyProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = EnvKeyProvider()
    return _default_provider


def set_default_key_provider(provider: KeyProvider) -> None:
    global _default_provider
    _default_provider = provider


class EnvelopeEncryption:
    """
    Two-tier envelope encryption:
      1. Plaintext evidence bytes are encrypted with a random 256-bit Data Encryption Key (DEK).
      2. The DEK is encrypted with the Key Encryption Key (KEK) provided by the KeyProvider.
      3. Both the encrypted payload and the wrapped DEK are stored securely.
    """

    @staticmethod
    def encrypt_bytes(
        plaintext: bytes,
        provider: Optional[KeyProvider] = None,
    ) -> tuple[bytes, str, str]:
        """
        Encrypts plaintext bytes with a one-time random DEK under AES-256-GCM.
        Returns:
            (ciphertext_bytes, encrypted_dek_base64, iv_base64)
        """
        key_provider = provider or get_default_key_provider()
        kek = key_provider.get_kek()

        # 1. Generate one-time 256-bit DEK & 96-bit payload IV
        dek = AESGCM.generate_key(bit_length=256)
        payload_iv = os.urandom(12)

        # 2. Encrypt plaintext with DEK
        payload_cipher = AESGCM(dek)
        ciphertext = payload_cipher.encrypt(payload_iv, plaintext, None)

        # 3. Encrypt DEK with KEK (Envelope wrapping)
        dek_iv = os.urandom(12)
        kek_cipher = AESGCM(kek)
        wrapped_dek_raw = kek_cipher.encrypt(dek_iv, dek, None)
        # Store dek_iv + wrapped_dek together
        encrypted_dek_bundle = dek_iv + wrapped_dek_raw
        encrypted_dek_b64 = base64.b64encode(encrypted_dek_bundle).decode("ascii")
        payload_iv_b64 = base64.b64encode(payload_iv).decode("ascii")

        return ciphertext, encrypted_dek_b64, payload_iv_b64

    @staticmethod
    def decrypt_bytes(
        ciphertext: bytes,
        encrypted_dek_b64: str,
        iv_b64: str,
        provider: Optional[KeyProvider] = None,
    ) -> bytes:
        """
        Unwraps the DEK using the KEK, then decrypts the ciphertext under AES-256-GCM.
        """
        key_provider = provider or get_default_key_provider()
        kek = key_provider.get_kek()

        # 1. Unwrap DEK
        encrypted_dek_bundle = base64.b64decode(encrypted_dek_b64.encode("ascii"))
        if len(encrypted_dek_bundle) < 28:
            raise ValueError("Corrupted encrypted DEK bundle")
        dek_iv = encrypted_dek_bundle[:12]
        wrapped_dek = encrypted_dek_bundle[12:]

        kek_cipher = AESGCM(kek)
        dek = kek_cipher.decrypt(dek_iv, wrapped_dek, None)

        # 2. Decrypt ciphertext
        payload_iv = base64.b64decode(iv_b64.encode("ascii"))
        payload_cipher = AESGCM(dek)
        plaintext = payload_cipher.decrypt(payload_iv, ciphertext, None)

        return plaintext
