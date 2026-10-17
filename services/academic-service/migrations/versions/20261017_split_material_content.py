"""move lecture material content from PostgreSQL to MongoDB

Revision ID: 20261017_material_content
Revises: 6228e2e251a8
Create Date: 2026-10-17
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from urllib.parse import quote_plus

import sqlalchemy as sa
from alembic import op
from pymongo import MongoClient
from sqlalchemy.dialects import postgresql

revision: str = "20261017_material_content"
down_revision: str | Sequence[str] | None = "6228e2e251a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLLECTION_NAME = "lecture_material_contents"


def mongo_client() -> MongoClient:
    if uri := os.getenv("MONGODB_URI"):
        return MongoClient(uri, serverSelectionTimeoutMS=5000)
    user = quote_plus(os.environ["MONGODB_USER"])
    password = quote_plus(os.environ["MONGODB_PASSWORD"])
    host = os.getenv("MONGODB_HOST", "mongodb")
    port = os.getenv("MONGODB_PORT", "27017")
    auth_source = quote_plus(os.getenv("MONGODB_AUTH_SOURCE", "academic_content"))
    return MongoClient(
        f"mongodb://{user}:{password}@{host}:{port}/?authSource={auth_source}",
        serverSelectionTimeoutMS=5000,
    )


def content_reference(material_id: object) -> str:
    database = os.getenv("MONGODB_ACADEMIC_DB", "academic_content")
    return f"mongodb://{database}/{COLLECTION_NAME}/{material_id}"


def upgrade() -> None:
    op.add_column(
        "lecture_materials", sa.Column("content_ref", sa.Text(), nullable=True)
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, content_text, metadata FROM lecture_materials ORDER BY id")
    ).mappings()
    client = mongo_client()
    try:
        collection = client[os.getenv("MONGODB_ACADEMIC_DB", "academic_content")][
            COLLECTION_NAME
        ]
        client.admin.command("ping")
        for row in rows:
            document: dict[str, object] = {"_id": str(row["id"])}
            if row["content_text"] is not None:
                document["content_text"] = row["content_text"]
            if row["metadata"]:
                document["metadata"] = row["metadata"]
            if len(document) == 1:
                continue
            collection.replace_one({"_id": document["_id"]}, document, upsert=True)
            bind.execute(
                sa.text(
                    "UPDATE lecture_materials SET content_ref = :content_ref "
                    "WHERE id = :material_id"
                ),
                {
                    "content_ref": content_reference(row["id"]),
                    "material_id": row["id"],
                },
            )
    finally:
        client.close()

    op.drop_constraint(
        op.f("ck_lecture_materials_material_has_content"),
        "lecture_materials",
        type_="check",
    )
    op.drop_column("lecture_materials", "content_text")
    op.drop_column("lecture_materials", "metadata")
    op.create_check_constraint(
        op.f("ck_lecture_materials_material_has_content"),
        "lecture_materials",
        "content_ref IS NOT NULL OR file_url IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_lecture_materials_material_has_content"),
        "lecture_materials",
        type_="check",
    )
    op.add_column(
        "lecture_materials", sa.Column("content_text", sa.Text(), nullable=True)
    )
    op.add_column(
        "lecture_materials",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    bind = op.get_bind()
    material_ids = bind.execute(sa.text("SELECT id FROM lecture_materials")).scalars()
    client = mongo_client()
    try:
        collection = client[os.getenv("MONGODB_ACADEMIC_DB", "academic_content")][
            COLLECTION_NAME
        ]
        for material_id in material_ids:
            document = collection.find_one({"_id": str(material_id)}) or {}
            bind.execute(
                sa.text(
                    "UPDATE lecture_materials "
                    "SET content_text = :content_text, metadata = CAST(:metadata AS jsonb) "
                    "WHERE id = :material_id"
                ),
                {
                    "content_text": document.get("content_text"),
                    "metadata": __import__("json").dumps(document.get("metadata", {})),
                    "material_id": material_id,
                },
            )
    finally:
        client.close()

    op.drop_column("lecture_materials", "content_ref")
    op.create_check_constraint(
        op.f("ck_lecture_materials_material_has_content"),
        "lecture_materials",
        "content_text IS NOT NULL OR file_url IS NOT NULL OR metadata <> '{}'::jsonb",
    )
