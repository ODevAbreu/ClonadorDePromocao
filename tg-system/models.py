"""Modelo de dados compartilhado entre o painel e o worker."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class Setting(Base):
    """Pares chave/valor de configuração (ex.: API_ID, API_HASH) editáveis no painel."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Account(Base):
    """Uma conta de Telegram logada. A sessão (credencial) mora aqui."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    session_string: Mapped[str] = mapped_column(Text, default="")
    # authenticated | not_authenticated | failed
    status: Mapped[str] = mapped_column(String(32), default="not_authenticated")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow
    )

    tasks: Mapped[list["ForwardTask"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


# Vínculo N:N entre tarefas e integrações (uma tarefa usa várias, e vice-versa).
forward_task_integrations = Table(
    "forward_task_integrations",
    Base.metadata,
    Column("task_id", ForeignKey("forward_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("integration_id", ForeignKey("integrations.id", ondelete="CASCADE"), primary_key=True),
)

clone_task_integrations = Table(
    "clone_task_integrations",
    Base.metadata,
    Column("task_id", ForeignKey("clone_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("integration_id", ForeignKey("integrations.id", ondelete="CASCADE"), primary_key=True),
)


class Integration(Base):
    """Uma integração de afiliado (global, aplicada às tarefas habilitadas).

    config é um JSON com os campos de cada tipo:
      amazon  -> {"store_id": "..."}
      generic -> {"domains": "a.com,b.com", "params": "aff=x;ref=y", "strip": "gclid,fbclid"}
      shopee  -> {"app_id": "...", "secret": "..."}
    """

    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(32))  # amazon | generic | shopee
    config: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    tasks: Mapped[list["ForwardTask"]] = relationship(
        secondary=forward_task_integrations, back_populates="integrations"
    )
    clone_tasks: Mapped[list["CloneTask"]] = relationship(
        secondary=clone_task_integrations, back_populates="integrations"
    )


class CloneTask(Base):
    """Trabalho de clonagem: percorre o histórico da origem e repassa ao destino.

    status: idle | running | paused | done | error
    last_message_id guarda o progresso para retomar de onde parou.
    """

    __tablename__ = "clone_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    source_id: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(200), default="")
    target_id: Mapped[str] = mapped_column(String(64))
    target_name: Mapped[str] = mapped_column(String(200), default="")

    deny_items: Mapped[str] = mapped_column(Text, default="")
    allow_items: Mapped[str] = mapped_column(Text, default="")
    whole_word: Mapped[bool] = mapped_column(Boolean, default=True)
    replacements: Mapped[str] = mapped_column(Text, default="")

    delay_between: Mapped[float] = mapped_column(Float, default=2.0)
    rest_every: Mapped[int] = mapped_column(Integer, default=0)      # 0 = sem descanso
    rest_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(String(16), default="idle")
    detail: Mapped[str] = mapped_column(String(300), default="")
    cloned_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_id: Mapped[int] = mapped_column(Integer, default=0)

    account: Mapped["Account"] = relationship()
    integrations: Mapped[list[Integration]] = relationship(
        secondary=clone_task_integrations, back_populates="clone_tasks"
    )


class ForwardTask(Base):
    """Uma tarefa de encaminhamento: de um chat de origem para um destino."""

    __tablename__ = "forward_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    source_id: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(200), default="")
    target_id: Mapped[str] = mapped_column(String(64))
    target_name: Mapped[str] = mapped_column(String(200), default="")

    # Filtros (a lógica que estudamos). Listas separadas por vírgula.
    deny_items: Mapped[str] = mapped_column(Text, default="")
    allow_items: Mapped[str] = mapped_column(Text, default="")
    whole_word: Mapped[bool] = mapped_column(Boolean, default=True)

    # Substituições "de=>para;de2=>para2" (prefixe de com re: para regex).
    replacements: Mapped[str] = mapped_column(Text, default="")

    delay_before_forward: Mapped[float] = mapped_column(Float, default=0.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    forwarded_count: Mapped[int] = mapped_column(Integer, default=0)

    account: Mapped[Account] = relationship(back_populates="tasks")
    integrations: Mapped[list[Integration]] = relationship(
        secondary=forward_task_integrations, back_populates="tasks"
    )

    def signature(self) -> tuple:
        """Identidade do comportamento — se muda, o worker reconstrói o handler."""
        return (
            self.id,
            self.account_id,
            self.source_id,
            self.target_id,
            self.deny_items,
            self.allow_items,
            self.whole_word,
            self.replacements,
            self.delay_before_forward,
            self.enabled,
        )


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_setting(key: str, default: str = "") -> str:
    with SessionLocal() as db:
        s = db.get(Setting, key)
        return s.value if s and s.value else default


def set_setting(key: str, value: str) -> None:
    with SessionLocal() as db:
        s = db.get(Setting, key) or Setting(key=key)
        s.value = value
        db.add(s)
        db.commit()


def init_db() -> None:
    import os

    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL.replace("sqlite:///", "", 1)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Base.metadata.create_all(engine)
    _auto_migrate()


def _auto_migrate() -> None:
    """Adiciona colunas novas a tabelas existentes sem perder dados (SQLite)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    wanted = {"forward_tasks": [("forwarded_count", "INTEGER DEFAULT 0")]}
    with engine.begin() as conn:
        for table, columns in wanted.items():
            existing = {row[1] for row in conn.exec_driver_sql(
                f"PRAGMA table_info({table})")}
            for col, decl in columns:
                if col not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
