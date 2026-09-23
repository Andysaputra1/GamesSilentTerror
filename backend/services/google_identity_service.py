"""Verifikasi ID token Google + nonce sekali pakai, bukan sekadar decode JWT."""
from collections import OrderedDict
from threading import RLock
import secrets
import time
from google.auth.transport.requests import Request
from google.auth.exceptions import TransportError
from google.oauth2 import id_token
from config.settings import settings
from services.auth_service import AuthenticationError, AuthenticationPersistenceError


class NonceStore:
    def __init__(self):
        self.values = OrderedDict()
        self.lock = RLock()

    def issue(self):
        with self.lock:
            now = time.monotonic()
            self.values = OrderedDict((k, v) for k, v in self.values.items() if v > now)
            if len(self.values) >= 1000:
                self.values.popitem(last=False)
            nonce = secrets.token_urlsafe(32)
            self.values[nonce] = now + 300
            return nonce

    def consume(self, nonce):
        with self.lock:
            return self.values.pop(nonce, 0) > time.monotonic()


nonces = NonceStore()


class BoundedGoogleRequest(Request):
    # Library mengambil sertifikat Google; batasi waktu jaringan.
    def __call__(self, *args, **kwargs):
        kwargs['timeout'] = 8
        return super().__call__(*args, **kwargs)


def verify_google(credential, nonce):
    if not settings.google_client_id.strip():
        raise AuthenticationPersistenceError('Login Google belum dikonfigurasi.')
    if not nonces.consume(nonce):
        raise AuthenticationError('Percobaan login kedaluwarsa. Muat ulang halaman.')
    try:
        claims = id_token.verify_oauth2_token(credential, BoundedGoogleRequest(), settings.google_client_id)
        if (claims.get('nonce') != nonce or not claims.get('sub')
                or len(str(claims['sub'])) > 255 or claims.get('email_verified') is not True
                or not isinstance(claims.get('email'), str) or len(claims['email']) > 254):
            raise ValueError('Invalid Google identity')
        return claims
    except (ValueError, TypeError) as error:
        raise AuthenticationError('Identitas Google tidak valid. Coba login ulang.') from error
    except TransportError as error:
        raise AuthenticationPersistenceError('Google belum dapat dihubungi. Coba lagi.') from error
