"""Cryptographic helpers for the public WeChat callback."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeChatCryptoError(ValueError):
    """Raised when an encrypted official-account message is invalid."""


def build_wechat_signature(token: str, timestamp: str, nonce: str) -> str:
    """Build the SHA-1 signature defined by the WeChat callback protocol."""

    parts = sorted((token, timestamp, nonce))
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def verify_wechat_signature(
    *, token: str, timestamp: str, nonce: str, signature: str
) -> bool:
    """Compare a callback signature without leaking timing information."""

    if not all((token, timestamp, nonce, signature)):
        return False
    expected = build_wechat_signature(token, timestamp, nonce)
    return hmac.compare_digest(expected, signature.lower())


def build_message_signature(
    token: str, timestamp: str, nonce: str, encrypted: str
) -> str:
    """Build the SHA-1 signature used by encrypted callback messages."""

    parts = sorted((token, timestamp, nonce, encrypted))
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def verify_message_signature(
    *, token: str, timestamp: str, nonce: str, encrypted: str, signature: str
) -> bool:
    """Verify the signature covering an encrypted callback payload."""

    if not all((token, timestamp, nonce, encrypted, signature)):
        return False
    expected = build_message_signature(token, timestamp, nonce, encrypted)
    return hmac.compare_digest(expected, signature.lower())


def _decode_aes_key(encoding_aes_key: str) -> bytes:
    try:
        key = base64.b64decode(encoding_aes_key + "=", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise WeChatCryptoError("Invalid EncodingAESKey") from exc
    if len(key) != 32:
        raise WeChatCryptoError("Invalid EncodingAESKey")
    return key


def _pkcs7_pad(payload: bytes) -> bytes:
    amount = 32 - (len(payload) % 32)
    return payload + bytes((amount,)) * amount


def _pkcs7_unpad(payload: bytes) -> bytes:
    if not payload:
        raise WeChatCryptoError("Invalid encrypted payload")
    amount = payload[-1]
    if amount < 1 or amount > 32 or payload[-amount:] != bytes((amount,)) * amount:
        raise WeChatCryptoError("Invalid encrypted payload")
    return payload[:-amount]


def encrypt_message(
    message_xml: str,
    *,
    encoding_aes_key: str,
    app_id: str,
    random_bytes: bytes | None = None,
) -> str:
    """Encrypt reply XML using the official-account AES-CBC envelope."""

    if not app_id:
        raise WeChatCryptoError("AppID is not configured")
    key = _decode_aes_key(encoding_aes_key)
    prefix = random_bytes if random_bytes is not None else os.urandom(16)
    if len(prefix) != 16:
        raise WeChatCryptoError("Random prefix must be 16 bytes")
    message = message_xml.encode("utf-8")
    payload = prefix + struct.pack("!I", len(message)) + message + app_id.encode("utf-8")
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    encrypted = encryptor.update(_pkcs7_pad(payload)) + encryptor.finalize()
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_message(
    encrypted: str, *, encoding_aes_key: str, app_id: str
) -> str:
    """Decrypt callback XML and verify that its trailing AppID matches."""

    if not app_id:
        raise WeChatCryptoError("AppID is not configured")
    key = _decode_aes_key(encoding_aes_key)
    try:
        ciphertext = base64.b64decode(encrypted, validate=True)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
        payload = _pkcs7_unpad(decryptor.update(ciphertext) + decryptor.finalize())
        if len(payload) < 20:
            raise WeChatCryptoError("Invalid encrypted payload")
        message_length = struct.unpack("!I", payload[16:20])[0]
        message_end = 20 + message_length
        message = payload[20:message_end]
        embedded_app_id = payload[message_end:]
        if message_end > len(payload) or not hmac.compare_digest(
            embedded_app_id, app_id.encode("utf-8")
        ):
            raise WeChatCryptoError("Encrypted payload AppID mismatch")
        return message.decode("utf-8")
    except WeChatCryptoError:
        raise
    except (ValueError, UnicodeDecodeError, struct.error) as exc:
        raise WeChatCryptoError("Invalid encrypted payload") from exc
