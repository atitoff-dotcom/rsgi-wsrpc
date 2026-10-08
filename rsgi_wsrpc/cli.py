# -*- coding: utf-8 -*-
"""
CLI-утилита администрирования rsgi-wsrpc.
Позволяет создавать первого администратора системы:
    python -m rsgi_wsrpc createsuperuser
"""

from __future__ import annotations
import asyncio
import argparse
import sys
import getpass
from sqlalchemy import select

from rsgi_wsrpc.core.constants import ADMIN_ROLE, DEFAULT_USER_ROLE
from rsgi_wsrpc.plugins.db import async_session, Base, engine
from rsgi_wsrpc.plugins.auth.models import User, Role
from rsgi_wsrpc.plugins.auth.core import system_bypass_ctx
from rsgi_wsrpc.plugins.auth.discovery import sync_rpc_permissions


async def async_create_superuser(username: str, password: str, email: str = None) -> None:
    """Асинхронно создает пользователя с ролью администратора (admin)."""
    # Гарантируем создание таблиц
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Синхронизируем базовые роли
    await sync_rpc_permissions()

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            # Ищем роль admin
            stmt_role = select(Role).where(Role.name == ADMIN_ROLE)
            admin_role = (await db.execute(stmt_role)).scalar_one_or_none()
            if not admin_role:
                admin_role = Role(name=ADMIN_ROLE, description="Системный администратор")
                db.add(admin_role)
                await db.commit()
                await db.refresh(admin_role)

            # Ищем или создаем пользователя
            stmt_user = select(User).where(User.login == username)
            user = (await db.execute(stmt_user)).scalar_one_or_none()

            pwd_hash = User._hash_password(password)
            if user:
                user.password_hash = pwd_hash
                if email:
                    user.email = email
                if admin_role not in user.roles:
                    user.roles.append(admin_role)
                print(f"[OK] Пользователь '{username}' обновлен и наделен правами администратора ({ADMIN_ROLE}).")
            else:
                user = User(
                    login=username,
                    name=username,
                    email=email,
                    password_hash=pwd_hash,
                )
                user.roles.append(admin_role)
                db.add(user)
                print(f"[OK] Администратор '{username}' успешно создан с ролью '{ADMIN_ROLE}'.")

            await db.commit()
    finally:
        system_bypass_ctx.reset(token)


async def async_set_password(login: str = "admin", password: str = None) -> str:
    """Обновляет пароль пользователя в существующей БД строго DML (без DDL во избежание версионных проблем)."""
    import secrets
    import string
    token = system_bypass_ctx.set(True)
    try:
        if not password:
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            password = "".join(secrets.choice(chars) for _ in range(16))
        async with async_session() as db:
            stmt = select(User).where(User.login == login)
            user = (await db.execute(stmt)).scalar_one_or_none()
            if not user:
                raise ValueError(
                    f"Пользователь с логином '{login}' не найден в базе данных. "
                    "Схема данных и пользователи должны быть предварительно инициализированы приложением."
                )
            user.password_hash = User._hash_password(password)
            await db.commit()
            return password
    finally:
        system_bypass_ctx.reset(token)


def main():
    parser = argparse.ArgumentParser(description="rsgi-wsrpc CLI management tool")
    subparsers = parser.add_subparsers(dest="command", help="Команда для выполнения")

    passwd_parser = subparsers.add_parser("set-admin-password", help="Установить или сгенерировать пароль администратора в существующей БД")
    passwd_parser.add_argument("--login", "-l", type=str, default="admin", help="Логин пользователя (по умолчанию admin)")
    passwd_parser.add_argument("--password", "-p", type=str, help="Новый пароль (если не указан, будет сгенерирован автоматически)")

    create_parser = subparsers.add_parser("createsuperuser", help="Создать администратора системы (admin)")
    create_parser.add_argument("--username", "-u", type=str, help="Имя пользователя (логин)")
    create_parser.add_argument("--password", "-p", type=str, help="Пароль администратора")
    create_parser.add_argument("--email", "-e", type=str, help="Email (опционально)")

    sync_parser = subparsers.add_parser("sync-rpc", help="Синхронизировать RPC методы с базой данных")

    args = parser.parse_args()

    if args.command == "set-admin-password":
        try:
            pwd = asyncio.run(async_set_password(login=args.login, password=args.password))
            print("=" * 64)
            print(" 🛡️  rsgi-wsrpc: Пароль успешно обновлен в базе данных!")
            print(f" 👤 Логин:       {args.login}")
            print(f" 🔑 Пароль:      {pwd}")
            print("=" * 64)
            print(" 👉 Войдите через форму авторизации вашего приложения.")
        except Exception as e:
            print(f"❌ Ошибка смены пароля: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "createsuperuser":
        username = args.username
        password = args.password
        email = args.email

        if not username:
            try:
                username = input("Имя пользователя (login): ").strip()
            except (KeyboardInterrupt, EOFError):
                sys.exit(1)

        if not username:
            print("Ошибка: имя пользователя не может быть пустым.", file=sys.stderr)
            sys.exit(1)

        if not password:
            try:
                password = getpass.getpass("Пароль: ")
                password_confirm = getpass.getpass("Подтверждение пароля: ")
                if password != password_confirm:
                    print("Ошибка: пароли не совпадают.", file=sys.stderr)
                    sys.exit(1)
            except (KeyboardInterrupt, EOFError):
                sys.exit(1)

        if not password or len(password) < 6:
            print("Ошибка: пароль должен содержать минимум 6 символов.", file=sys.stderr)
            sys.exit(1)

        asyncio.run(async_create_superuser(username, password, email))

    elif args.command == "sync-rpc":
        asyncio.run(sync_rpc_permissions())
        print("[OK] Синхронизация RPC-методов успешно завершена.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
