"""s2: admin users and sessions, trend fields, starter trends, upscale off

Revision ID: b7e2c91d4f10
Revises: 6cb4d9e6097a
Create Date: 2026-11-25 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2c91d4f10"
down_revision: str | Sequence[str] | None = "6cb4d9e6097a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADMIN_ROLE = postgresql.ENUM("owner", "admin", "support", name="admin_role", create_type=False)
TREND_BADGE = postgresql.ENUM("none", "hot", "new", "top", name="trend_badge", create_type=False)
TREND_AUDIENCE = postgresql.ENUM("all", "women", "men", name="trend_audience", create_type=False)

FIRST_FRAME = (
    "Keep the person's face, identity, age and body exactly as in the selfie. "
    "One adult person only, modest clothing, no logos, no text, no celebrities. Vertical 9:16."
)

# docs/trends-starter.md. Only the four trends checked by the model probe start active.
# slug, title_uz, title_ru, category, audience, badge, active, scene, music
TRENDS = [
    (
        "registon-oqshomi",
        "Registon oqshomi",
        "Вечер у Регистана",
        "national",
        "all",
        "new",
        True,
        "Odam kechki oltin quyosh nurida Samarqanddagi Registon maydonida turibdi, orqada moviy gumbazlar va naqshinkor peshtoqlar. Shamol sochini yengil hilpiratadi, u kameraga qarab sekin jilmayadi. Kamera sekin yaqinlashadi (dolly-in).",
        "tantanali, sharqona torli cholg'u, kinematografik",
    ),
    (
        "atlas-shamolda",
        "Atlas shamolda",
        "Атлас на ветру",
        "national",
        "women",
        "none",
        False,
        "Ayol yorqin xon-atlas ko'ylakda gullagan o'rik bog'ida. Kuchli shamol atlas matoni va ro'molni chiroyli to'lqinlantiradi, u aylanib, kameraga qaraydi. Kamera sekin atrofida aylanadi.",
        "nafis, rubob va yengil ritm",
    ),
    (
        "chopon-toglar",
        "Chopon va tog'lar",
        "Чапан и горы",
        "national",
        "men",
        "none",
        True,
        "Erkak zarbof chopon va do'ppida Chimyon tog'lari cho'qqisida turibdi, ostida bulutlar. Osmonda burgut aylanadi, chopon etaklari shamolda hilpiraydi. Kamera pastdan yuqoriga va orqaga uzoqlashadi.",
        "epik, karnay va baraban",
    ),
    (
        "chimyonda-qor",
        "Chimyonda qor",
        "Снег в Чимгане",
        "seasonal",
        "all",
        "hot",
        True,
        "Odam qishki issiq kiyim va sharfda, qorli archalar orasida. Yirik qor parchalari yog'moqda, u qo'lini cho'zib qorni tutadi va kuladi, nafasidan bug' chiqadi. Kamera sekin yaqinlashadi, fon xira (bokeh).",
        "iliq, fortepiano, sokin",
    ),
    (
        "yangi-yil-tuni",
        "Yangi yil tuni",
        "Новогодняя ночь",
        "seasonal",
        "all",
        "none",
        False,
        "Odam tunda shahar ustidagi tomda qo'lida yonib turgan bengal olovi bilan. Orqada osmonda rang-barang mushaklar portlaydi, uchqunlar yuziga yorug'lik tushiradi. Kamera sekin atrofida aylanadi.",
        "bayramona, qo'ng'iroqchalar, quvnoq",
    ),
    (
        "navruz-bahori",
        "Navro'z bahori",
        "Весна Навруза",
        "seasonal",
        "all",
        "none",
        False,
        "Odam milliy kiyimda bahorgi bog'da, atrofda gullagan daraxtlar, dasturxonda sumalak qozoni va ko'k somsa. Gul barglari havoda uchadi, u kameraga qarab qo'l siltaydi. Kamera sekin yon tomonga suriladi.",
        "quvnoq, doira va nay",
    ),
    (
        "gullar-yomgiri",
        "Gullar yomg'iri",
        "Дождь из лепестков",
        "seasonal",
        "women",
        "none",
        False,
        "Ayol oq ko'ylakda, yuqoridan pushti va oq gul barglari yomg'irdek yog'adi. U yuzini yuqoriga ko'tarib ko'zlarini yumadi va jilmayadi. Sekinlashtirilgan harakat (slow motion), kamera sekin yaqinlashadi.",
        "romantik, torli cholg'ular",
    ),
    (
        "toy-oqshomi",
        "To'y oqshomi",
        "Свадебный вечер",
        "national",
        "all",
        "none",
        False,
        "Odam bayramona kiyimda yorug' to'yxonada, atrofida chiroqlar va havoda konfetti. U raqsga tushib aylanadi, oltin yorug'lik jilolanadi. Kamera atrofida aylanadi.",
        "o'zbekona to'y ritmi, doira va karnay",
    ),
    (
        "iftorlik-chiroqlari",
        "Iftorlik chiroqlari",
        "Огни ифтара",
        "seasonal",
        "all",
        "none",
        False,
        "Odam kamtarona kiyimda kechki hovlida, atrofda osilgan sharqona fonuslar yonmoqda, osmonda yangi oy. U sokin jilmayib dasturxon yoniga o'tiradi. Kamera sekin yaqinlashadi. Hurmatli, sokin kayfiyat, ibodat ko'rsatilmaydi.",
        "sokin, nay, ma'naviy",
    ),
    (
        "stadion-yulduzi",
        "Stadion yulduzi",
        "Звезда стадиона",
        "lifestyle",
        "men",
        "none",
        False,
        "Odam oq-ko'k futbol formasida (logotipsiz, raqamsiz) tunda katta stadion maydonida. Projektorlar yonadi, tribunalar hayqiradi, u qo'llarini yuqoriga ko'tarib g'alabani nishonlaydi. Kamera pastdan aylanib ko'tariladi.",
        "energik, baraban, olomon ritmi",
    ),
    (
        "chavandoz",
        "Dashtdagi chavandoz",
        "Всадник в степи",
        "national",
        "men",
        "none",
        False,
        "Odam milliy kiyimda otda keng dashtda chopib ketmoqda, orqada chang ko'tariladi, quyosh botmoqda. Sekinlashtirilgan harakat, kamera yonma-yon yuradi.",
        "epik, do'mbira va baraban",
    ),
    (
        "tashkent-city",
        "Tashkent City tadbirkori",
        "Бизнес в Tashkent City",
        "lifestyle",
        "all",
        "none",
        False,
        "Odam zamonaviy kostyumda Tashkent City osmono'par binolari orasida ishonch bilan yurib kelmoqda, oyna binolarda quyosh aks etadi. U to'xtab kameraga qaraydi. Kamera orqaga yuradi (tracking).",
        "zamonaviy, ishonchli, elektron",
    ),
    (
        "kino-qahramoni",
        "Kino qahramoni",
        "Герой боевика",
        "cinematic",
        "all",
        "top",
        True,
        "Odam qora ko'zoynak va charm kurtkada kameraga qarab yurib kelmoqda, orqasida katta portlash va olov (hech kim jabrlanmaydi). U ortiga qaramaydi. Sekinlashtirilgan harakat, kamera orqaga yuradi.",
        "dramatik, jangari film uslubi",
    ),
    (
        "koinotda",
        "Koinotda",
        "В открытом космосе",
        "cinematic",
        "all",
        "none",
        False,
        "Odam skafandrda ochiq koinotda suzib yuribdi, shlem oynasidan yuzi ko'rinadi, orqada Yer sayyorasi va yulduzlar. U kameraga qo'l silkitadi. Kamera sekin atrofida aylanadi.",
        "kosmik, sintezator, keng",
    ),
    (
        "multfilm-qahramoni",
        "Multfilm qahramoni",
        "Мультгерой",
        "cinematic",
        "all",
        "none",
        False,
        "Odam yorqin 3D multfilm qahramoniga aylangan (o'z yuz xususiyatlari saqlangan), rang-barang ertak shaharchasida. U quvnoq sakraydi va kameraga ko'z qisadi. Kamera dinamik yaqinlashadi.",
        "o'ynoqi, quvnoq orkestr",
    ),
    (
        "retro-toshkent",
        "Retro Toshkent",
        "Ретро Ташкент",
        "lifestyle",
        "all",
        "none",
        False,
        "1980-yillar Toshkent ko'chasi, eski kino tasmasi doni va iliq ranglar. Odam o'sha davr kiyimida eski mashina yonida turibdi, kameraga qarab kuladi. Kamera sekin yon tomonga suriladi, VHS effekti.",
        "retro, 80-lar estrada uslubi",
    ),
    (
        "polaroid-jonlanadi",
        "Polaroid jonlanadi",
        "Оживший полароид",
        "lifestyle",
        "all",
        "none",
        False,
        "Stol ustida odamning eski polaroid surati yotibdi. Surat asta jonlanib, ichidagi odam harakatlana boshlaydi va ramkadan tashqariga qaraydi. Kamera suratga yaqinlashadi.",
        "nostalgik, gitara",
    ),
    (
        "chorsu-bozori",
        "Chorsu bozorida",
        "На базаре Чорсу",
        "national",
        "all",
        "none",
        False,
        "Odam Chorsu bozorining gumbazi ostida, atrofda rang-barang ziravorlar, quruq mevalar va issiq non. U nonni sindirib, kameraga qarab mamnun jilmayadi. Kamera sekin aylanadi.",
        "quvnoq sharqona ritm",
    ),
    (
        "oltin-soat",
        "Oltin soat",
        "Золотой час",
        "lifestyle",
        "women",
        "none",
        False,
        "Ayol quyosh botayotgan bug'doyzorda, oltin nur yuziga va sochiga tushmoqda. U qo'li bilan bug'doy boshoqlarini silab yuradi va kameraga qaraydi. Kamera sekin yaqinlashadi.",
        "iliq, akustik gitara",
    ),
    (
        "tungi-shahar",
        "Tungi shahar neoni",
        "Неон ночного города",
        "lifestyle",
        "all",
        "none",
        False,
        "Odam yomg'irdan keyingi tungi shahar ko'chasida, neon chiroqlar ho'l asfaltda aks etadi. U qo'lini cho'ntagiga solib yurib kelmoqda, yengil tuman. Kamera orqaga yuradi.",
        "zamonaviy, synthwave",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (ADMIN_ROLE, TREND_BADGE, TREND_AUDIENCE):
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "admin_users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("role", ADMIN_ROLE, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_users")),
        sa.UniqueConstraint("email", name=op.f("uq_admin_users_email")),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            name=op.f("fk_admin_sessions_admin_id_admin_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_admin_sessions")),
    )
    op.create_index(op.f("ix_admin_sessions_admin_id"), "admin_sessions", ["admin_id"])

    op.add_column(
        "trend_templates",
        sa.Column("audience", TREND_AUDIENCE, server_default="all", nullable=False),
    )
    op.add_column(
        "trend_templates", sa.Column("badge", TREND_BADGE, server_default="none", nullable=False)
    )
    op.add_column(
        "trend_templates", sa.Column("preview_file_id", sa.String(length=256), nullable=True)
    )
    op.add_column("trend_templates", sa.Column("music_prompt", sa.Text(), nullable=True))

    for sort, (
        slug,
        title_uz,
        title_ru,
        category,
        audience,
        badge,
        active,
        scene,
        music,
    ) in enumerate(TRENDS):
        bind.execute(
            sa.text(
                "INSERT INTO trend_templates (slug, title_uz, title_ru, category, audience, badge, "
                "prompt_skeleton, first_frame_instructions, music_prompt, sort_order, is_active) "
                "VALUES (:slug, :title_uz, :title_ru, :category, CAST(:audience AS trend_audience), "
                "CAST(:badge AS trend_badge), :scene, :first_frame, :music, :sort, :active)"
            ),
            {
                "slug": slug,
                "title_uz": title_uz,
                "title_ru": title_ru,
                "category": category,
                "audience": audience,
                "badge": badge,
                "scene": scene,
                "first_frame": FIRST_FRAME,
                "music": music,
                "sort": (sort + 1) * 10,
                "active": active,
            },
        )

    # Owner decision 25.11.2026: offer 1080p up front instead of a separate upscale.
    op.execute("UPDATE product_prices SET is_active = false WHERE product = 'upscale'")
    op.execute("UPDATE model_routes SET is_enabled = false WHERE product = 'upscale'")


def downgrade() -> None:
    op.execute("UPDATE model_routes SET is_enabled = true WHERE product = 'upscale'")
    op.execute("UPDATE product_prices SET is_active = true WHERE product = 'upscale'")
    slugs = ", ".join(f"'{trend[0]}'" for trend in TRENDS)
    op.execute(f"DELETE FROM trend_templates WHERE slug IN ({slugs})")
    for column in ("music_prompt", "preview_file_id", "badge", "audience"):
        op.drop_column("trend_templates", column)
    op.drop_index(op.f("ix_admin_sessions_admin_id"), table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
    bind = op.get_bind()
    for enum_type in (TREND_AUDIENCE, TREND_BADGE, ADMIN_ROLE):
        enum_type.drop(bind, checkfirst=False)
