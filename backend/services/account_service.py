"""Registrasi dan identitas federasi. Tidak pernah menggabungkan akun berdasarkan email."""
import secrets
from datetime import timedelta, timezone
from sqlalchemy.exc import IntegrityError
from config.settings import settings
from models import auth_queries
from services.auth_service import (
    auth_service, AuthenticationError, AuthenticatedUser, LoginResult, _utc_now, _token_hash,
)
from services.password_service import hash_password


class AccountConflict(ValueError):
    """Username/email sudah dipakai; jangan mengubah akun lama."""


def issue_session(database, account):
    """Buat sesi aplikasi biasa; token Google tidak disimpan."""
    if not account['is_active']:
        raise AuthenticationError('Akun tidak aktif.')
    token = secrets.token_urlsafe(32)
    expires = _utc_now() + timedelta(hours=settings.auth_session_hours)
    auth_queries.create_session(database, user_id=account['id'], token_hash=_token_hash(token), expires_at=expires)
    return LoginResult(token, expires.replace(tzinfo=timezone.utc),
                       AuthenticatedUser(account['id'], account['username'], account['display_name']))


def register_account(body):
    """Simpan akun + email dalam satu transaksi dan login setelah pendaftaran."""
    reserved = {'nox', 'echo', 'veil', 'admin', 'user1'}
    reserved.update(name.strip().casefold() for name in settings.admin_usernames.split(','))
    if body.username.casefold() in reserved:
        raise AccountConflict('Username tidak tersedia.')
    password_hash = hash_password(body.password)

    def operation(database):
        try:
            user_id = auth_queries.create_account(database, username=body.username,
                display_name=body.username, password_hash=password_hash)
            # Konfirmasi email di form hanya pencocokan, bukan bukti kepemilikan.
            auth_queries.create_identity(database, user_id, str(body.email).lower())
            return issue_session(database, {'id': user_id, 'username': body.username,
                                           'display_name': body.username, 'is_active': True})
        except IntegrityError as error:
            database.rollback()
            raise AccountConflict('Username atau email sudah digunakan. Silakan login.') from error
    return auth_service._transaction(operation)


def google_account(claims):
    """Google sub adalah identitas utama. Email yang sama tidak otomatis mengambil alih akun."""
    def operation(database):
        account = auth_queries.account_by_google_subject(database, claims['sub'])
        if account:
            return issue_session(database, account)
        try:
            # Username tidak berasal dari email dan tidak dapat bertabrakan dengan admin.
            username = 'google_' + secrets.token_hex(8)
            display_name = str(claims.get('name') or 'Detective')[:100]
            user_id = auth_queries.create_account(database, username=username,
                display_name=display_name, password_hash='google_only')
            auth_queries.create_identity(database, user_id, claims['email'].lower(), claims['sub'])
            return issue_session(database, {'id': user_id, 'username': username,
                                           'display_name': display_name, 'is_active': True})
        except IntegrityError as error:
            database.rollback()
            raise AccountConflict('Email sudah terdaftar. Gunakan metode login awal; penautan akun belum tersedia.') from error
    return auth_service._transaction(operation)
