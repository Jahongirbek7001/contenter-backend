"""s3: script styles, talking/series generation fields

Revision ID: d5a8e3f1c720
Revises: c41a7d2e9b35
Create Date: 2026-11-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5a8e3f1c720"
down_revision: str | Sequence[str] | None = "c41a7d2e9b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LANGUAGE = postgresql.ENUM("uz", "ru", name="language", create_type=False)

# Business styles from docs/plan.md plus the trend monologs (POV, humor) agreed for S3.
# Only the business styles may end with a call to action: the S1 probe showed Hydrogen
# turns every continuation into an ad unless told otherwise.
# slug, title_uz, title_ru, instructions
STYLES = [
    (
        "sotuv",
        "💰 Sotuv",
        "💰 Продажа",
        "Sell the product or service from the idea. Open with a hook about the viewer's problem, "
        "give one or two concrete benefits, and end the last line with a short call to action "
        "(write, call or visit). Honest claims only: no guarantees, no invented prices or numbers.",
    ),
    (
        "ekspert",
        "🎓 Ekspert",
        "🎓 Эксперт",
        "The speaker is an expert sharing one useful tip or fact from their field. Confident, "
        "friendly and specific. No selling; the last line may invite viewers to follow for more. "
        "No medical, legal or financial promises.",
    ),
    (
        "promo",
        "📣 Promo",
        "📣 Промо",
        "Announce an offer, opening or event from the idea. Energetic, with a reason to act now. "
        "Mention only the dates, places and discounts the user gave; never invent them. "
        "End with a short call to action.",
    ),
    (
        "pov",
        "🎭 POV monolog",
        "🎭 POV-монолог",
        "A first-person trend monolog in the style of 'POV: ...' videos: a relatable everyday "
        "situation told with emotion or irony. This is not an ad: no products, brands, links, "
        "calls to action or 'subscribe'.",
    ),
    (
        "hazil",
        "😂 Hazil",
        "😂 Юмор",
        "A short funny monolog about everyday life in Uzbekistan with a punchline at the end. "
        "Kind humor only: no insults, politics, religion or ethnic jokes. This is not an ad: no "
        "products, brands, links or calls to action.",
    ),
]


def upgrade() -> None:
    styles = op.create_table(
        "script_styles",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title_uz", sa.String(length=128), nullable=False),
        sa.Column("title_ru", sa.String(length=128), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_script_styles")),
        sa.UniqueConstraint("slug", name=op.f("uq_script_styles_slug")),
    )
    op.bulk_insert(
        styles,
        [
            {
                "slug": slug,
                "title_uz": title_uz,
                "title_ru": title_ru,
                "instructions": instructions,
                "sort_order": index,
            }
            for index, (slug, title_uz, title_ru, instructions) in enumerate(STYLES)
        ],
    )
    op.add_column("generations", sa.Column("style_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_generations_style_id_script_styles"),
        "generations",
        "script_styles",
        ["style_id"],
        ["id"],
    )
    op.add_column("generations", sa.Column("speech_language", LANGUAGE, nullable=True))
    op.add_column(
        "generations",
        sa.Column("subtitles", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("generations", sa.Column("contact_text", sa.String(length=64), nullable=True))
    op.add_column(
        "generations", sa.Column("output_media_key", sa.String(length=256), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("generations", "output_media_key")
    op.drop_column("generations", "contact_text")
    op.drop_column("generations", "subtitles")
    op.drop_column("generations", "speech_language")
    op.drop_constraint(
        op.f("fk_generations_style_id_script_styles"), "generations", type_="foreignkey"
    )
    op.drop_column("generations", "style_id")
    op.drop_table("script_styles")
