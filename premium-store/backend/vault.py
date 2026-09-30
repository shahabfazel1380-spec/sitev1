"""Encryption key is independent of sessions; preserve it with private backups."""
import os
from cryptography.fernet import Fernet
from . import settings

def cipher():
    key = os.getenv('VAULT_KEY')
    if not key:
        if settings.ENV == 'production':
            raise RuntimeError('VAULT_KEY is required in production')
        settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = settings.DATA_DIR / 'vault-key'
        if not path.exists():
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as f: f.write(Fernet.generate_key())
            except FileExistsError: pass
        key=path.read_bytes()
    return Fernet(key)

def seal(value):
    return cipher().encrypt(value.encode()).decode() if value else ''

def unseal(value):
    return cipher().decrypt(value.encode()).decode() if value else ''
