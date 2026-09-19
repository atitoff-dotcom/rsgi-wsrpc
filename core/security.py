# core/security.py
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
import hashlib
import jwt

ALGORITHM = "HS256"
logger = logging.getLogger("core.security")

from core.lib.config import settings

def get_secret_key() -> str:
    key = None
    try:
        key = settings.security.secret_key
    except Exception:
        pass
    if not key:
        key = os.getenv("SECRET_KEY", "dev-insecure-secret-key-change-in-production")
    if key == "dev-insecure-secret-key-change-in-production":
        if not getattr(get_secret_key, "_warned", False):
            logger.warning(
                "[SECURITY] Внимание: используется небезопасный dev secret_key по умолчанию! "
                "Задайте secret_key в коде через configure(secret_key=...) или через переменную окружения SECRET_KEY!"
            )
            get_secret_key._warned = True
    return key

SECRET_KEY = get_secret_key()


def create_access_token(user_id: int, username: str, roles: list[str], user_agent: str) -> tuple[str, str, datetime]:
    """
    Генерирует JWT токен на 7 дней с привязкой к отпечатку браузера.
    """
    jti = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(days=7)

    # Создаем цифровой отпечаток браузера (хэш от User-Agent)
    ua_fingerprint = hashlib.sha256(user_agent.encode('utf-8', errors='ignore')).hexdigest()

    payload = {
        "sub": str(user_id),
        "username": username,
        "roles": roles,
        "iat": int(now_utc.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
        "fpt": ua_fingerprint  # Зашиваем Fingerprint в Payload токена
    }

    token_str = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)
    return token_str, jti, expires_at


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])


import os
import base64

PASSWORD_ITERATIONS = 600000
try:
    PASSWORD_ITERATIONS = int(settings.security.password_iterations)
except AttributeError:
    pass


def hash_password(password: str) -> str:
    """
    Хэширует пароль с помощью PBKDF2-SHA256 с солью и количеством итераций из настроек.
    """
    salt = os.urandom(16)
    iterations = PASSWORD_ITERATIONS
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode('utf-8')}${base64.b64encode(key).decode('utf-8')}"


def verify_password(password: str, hashed: str) -> bool:
    """
    Проверяет пароль на соответствие хэшу PBKDF2-SHA256.
    Строго требует хэшированный пароль.
    (Устарело: используйте User.verify_password)
    """
    from core.logger import logger
    logger.warning("Использование устаревшей функции core.security.verify_password. Перейдите на User.verify_password.")
    if not hashed or not hashed.startswith("pbkdf2_sha256$"):
        return False

    try:
        parts = hashed.split('$')
        if len(parts) != 4:
            return False
        algorithm, iterations, salt_b64, key_b64 = parts
        salt = base64.b64decode(salt_b64)
        iterations = int(iterations)
        expected_key = base64.b64decode(key_b64)
        
        actual_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
        return actual_key == expected_key
    except Exception:
        return False


from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes

def generate_rsa_keypair() -> tuple[str, str]:
    """
    Генерирует эфемерную пару ключей RSA (2048 бит).
    Возвращает кортеж (private_key_pem, public_key_pem).
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    
    return private_pem, public_pem


def decrypt_rsa(private_key_pem: str, encrypted_base64: str) -> str:
    """
    Расшифровывает данные, зашифрованные с помощью RSA-OAEP и закодированные в Base64.
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode('utf-8'),
        password=None
    )
    
    encrypted_data = base64.b64decode(encrypted_base64)
    
    decrypted = private_key.decrypt(
        encrypted_data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    
    return decrypted.decode('utf-8')
