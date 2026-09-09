"""Validated MySQL configuration. Values come from environment, never JSON secrets."""

from urllib.parse import quote_plus

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class MySQLSettings(BaseSettings):
    # Both the existing MYSQL_* names and the requested DB_* names are accepted.
    mysql_host: str = Field(default="localhost", validation_alias=AliasChoices("MYSQL_HOST", "DB_HOST"))
    mysql_port: int = Field(default=3306, ge=1, le=65535, validation_alias=AliasChoices("MYSQL_PORT", "DB_PORT"))
    mysql_database: str = Field(default="shadow_heist", validation_alias=AliasChoices("MYSQL_DATABASE", "DB_NAME"))
    mysql_user: str = Field(default="shadow_app", validation_alias=AliasChoices("MYSQL_USER", "DB_USER"))
    mysql_password: str = Field(default="shadow_app_dev_2026", repr=False, validation_alias=AliasChoices("MYSQL_PASSWORD", "DB_PASSWORD"))
    database_url: str | None = Field(default=None, repr=False)
    sql_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)

    @property
    # PROPERTY: susun URL koneksi MySQL dengan kredensial yang di-encode, atau gunakan database_url khusus.
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        database = quote_plus(self.mysql_database)
        return (
            f"mysql+pymysql://{user}:{password}@{self.mysql_host}:"
            f"{self.mysql_port}/{database}?charset=utf8mb4"
        )
