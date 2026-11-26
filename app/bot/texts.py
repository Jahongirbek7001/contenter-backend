"""Bot copy in Uzbek (Latin) and Russian. Every key exists in both languages (tested)."""

from app.models.enums import Language

TEXTS: dict[Language, dict[str, str]] = {
    Language.UZ: {
        "choose_language": "Tilni tanlang · Выберите язык",
        "welcome": (
            "Salom! Men <b>Contentor AI</b> — selfingizdan video yasayman.\n\n"
            "🎬 <b>Trendlar</b> — 8 soniyalik trend video\n"
            "🎙 <b>Gapiruvchi video</b> — siz kameraga gapirasiz: reklama, maslahat, POV\n"
            "🎞 <b>Seriya</b> — 3 qismli, 30 soniyalik hikoya"
        ),
        "menu_trends": "🎬 Trendlar",
        "menu_balance": "⚡ Balans",
        "menu_language": "🌐 Til",
        "menu_help": "❓ Yordam",
        "rules": (
            "<b>Foydalanish qoidalari</b>\n\n"
            "Mumkin emas:\n"
            "• boshqa odamning rasmini uning roziligisiz yuklash\n"
            "• 18 yoshga to'lmaganlar rasmini yuklash\n"
            "• yalang'och yoki odobsiz rasmlar\n"
            "• videolarni aldash, tuhmat yoki qonunga zid ishlar uchun ishlatish\n\n"
            "Rasmlaringiz faqat video yaratish uchun ishlatiladi va 24 soatdan keyin o'chiriladi."
        ),
        "rules_accept": "✅ Roziman",
        "gallery_empty": "Hozircha faol trendlar yo'q. Tez orada qo'shiladi!",
        "filter_all": "Hammasi",
        "filter_women": "Ayollar",
        "filter_men": "Erkaklar",
        "card": "{badge}<b>{title}</b>\n{position}",
        "pick": "✅ Tanlash · {price} ⚡",
        "send_selfie": (
            "<b>{title}</b> — selfi yuboring.\n\n"
            "• yuzingiz aniq ko'rinsin, yorug' joyda\n"
            "• rasmda faqat siz bo'ling\n"
            "• sifat yuqori bo'lishi uchun rasmni «fayl» qilib yuborsangiz ham bo'ladi"
        ),
        "not_a_photo": "Iltimos, rasm yuboring (JPG yoki PNG).",
        "photo_too_big": "Rasm juda katta. 10 MB dan kichik rasm yuboring.",
        "trend_unavailable": "Bu trend hozir mavjud emas. Boshqasini tanlang.",
        "insufficient": (
            "⚡ yetarli emas: kerak <b>{required}</b>, sizda <b>{available}</b>.\n"
            "Paketlar tez orada sotuvga chiqadi."
        ),
        "started": (
            "🎬 Video tayyorlanmoqda, taxminan 3 daqiqa.\n"
            "Botni yopishingiz mumkin — tayyor bo'lganda o'zim yuboraman."
        ),
        "result": "Tayyor! ✨ Do'stlaringizga ulashing.",
        "regenerate": "🔁 Qayta yaratish · {price} ⚡",
        "share": "📤 Ulashish",
        "share_text": "Men Contentor AI'da selfimdan trend video yasadim!",
        "regen_need_photo": "Avvalgi rasm saqlanmagan. Selfini qayta yuboring.",
        "balance": "Balansingiz: <b>{available} ⚡</b>",
        "balance_held": "Balansingiz: <b>{available} ⚡</b> (yana {held} ⚡ jarayondagi videoda)",
        "help": (
            "Trend video — 2 ⚡, 1080p, 8 soniya, musiqa bilan.\n"
            "Gapiruvchi video (10 s) — 1 / 3 / 5 ⚡ (360p / 720p / 1080p).\n"
            "Seriya (3×10 s) — 3 / 9 / 15 ⚡.\n"
            "Video chiqmasa yoki bloklansa, ⚡ to'liq qaytariladi."
        ),
        "language_set": "Til: O'zbekcha ✅",
        "failed_photo_no_face": "Rasmda yuz aniq ko'rinmadi. Yuzingiz yaxshi ko'ringan selfi yuboring.",
        "failed_photo_several_people": "Rasmda bir nechta odam bor. Faqat o'zingiz tushgan selfi yuboring.",
        "failed_photo_minor": "Kechirasiz, 18 yoshga to'lmaganlar rasmi bilan video yaratmaymiz.",
        "failed_photo_celebrity": "Mashhur odamlar rasmi bilan video yaratmaymiz. O'z selfingizni yuboring.",
        "failed_photo_nudity": "Bu rasmni qabul qila olmaymiz. Boshqa selfi yuboring.",
        "failed_photo_low_quality": "Rasm sifati past (xira yoki qorong'i). Yorug' joyda qayta suratga oling.",
        "failed_blocked": "Uzr, bu safar o'xshamadi — xavfsizlik filtri videoni to'xtatdi. ⚡ qaytarildi.",
        "failed_failed": "Uzr, texnik xato bo'ldi. ⚡ qaytarildi, birozdan keyin qayta urinib ko'ring.",
        "failed_refund_note": "⚡ yechilmadi.",
        "blocked": "Hisobingiz cheklangan. Savollar bo'lsa, qo'llab-quvvatlashga yozing.",
        "menu_talking": "🎙 Gapiruvchi video",
        "menu_series": "🎞 Seriya 3×10",
        "product_talking": "Gapiruvchi video · 10 soniya",
        "product_series": "Seriya · 3 qism × 10 soniya",
        "choose_style": "<b>{product}</b>\n\nVideoda siz kameraga qarab gapirasiz. Uslubni tanlang:",
        "styles_empty": "Hozircha uslublar yo'q. Tez orada qo'shiladi!",
        "style_unavailable": "Bu uslub hozir mavjud emas. Boshqasini tanlang.",
        "spoken_send_selfie": (
            "Selfi yuboring — videoda shu odam gapiradi.\n\n"
            "• yuz to'g'ridan, aniq va yorug' joyda\n"
            "• rasmda faqat siz bo'ling"
        ),
        "send_idea": (
            "Endi g'oyangizni yozing yoki ovozli xabar yuboring (1 daqiqagacha).\n\n"
            "Masalan: «Do'konimga yangi qishki kurtkalar keldi, 20% chegirma, Chilonzor 5-kvartal»"
        ),
        "idea_needed": "G'oyani matn yoki ovozli xabar qilib yuboring.",
        "voice_too_long": "Ovozli xabar 1 daqiqadan oshmasin.",
        "writing_script": "✍️ Ssenariy yozilmoqda…",
        "script": (
            "<b>Ssenariy</b> · {style}\n\n{lines}\n\n"
            "Matnni bepul o'zgartirishingiz mumkin. ⚡ faqat video yaratilganda yechiladi."
        ),
        "script_approve": "✅ Davom etish",
        "script_rewrite": "🔄 Boshqasini yozish",
        "script_edit": "✏️ O'zim yozaman",
        "send_other_selfie": "Boshqa selfi yuboring.",
        "idea_rejected": "Bu g'oya bo'yicha video yarata olmayman. Boshqa g'oya yuboring.",
        "script_failed": "Ssenariy yozib bo'lmadi. Birozdan keyin g'oyani qayta yuboring.",
        "rewrite_limit": "Bu video uchun {limit} ta variant yozildi. Matnni o'zingiz tahrirlashingiz mumkin.",
        "own_text_prompt": (
            "Matnni yuboring: {parts} ta qator, har qism alohida qatorda, "
            "har qatorda 22 so'zgacha (10 soniyaga sig'ishi uchun)."
        ),
        "own_wrong_parts": "{parts} ta qator kerak: har qism alohida qatorda.",
        "own_too_long": "Qatorlar juda uzun. Har qatorda 22 so'zgacha bo'lsin.",
        "choose_resolution": "Sifatni tanlang:",
        "resolution_button": "{resolution} · {price} ⚡",
        "options": (
            "<b>Hammasi tayyor</b>\n\n"
            "Sifat: {resolution}\nSubtitr: {subtitles}\nKontakt: {contact}\n\n"
            "Narx: <b>{price} ⚡</b>"
        ),
        "option_subtitles_on": "✅ Subtitr",
        "option_subtitles_off": "⬜ Subtitr",
        "option_contact": "📇 Kontakt matni",
        "option_create": "🚀 Yaratish · {price} ⚡",
        "word_on": "bor",
        "word_off": "yo'q",
        "ask_contact": (
            "Videoning tepasida chiqadigan matnni yuboring (64 belgigacha): telefon, manzil "
            "yoki @username.\nOlib tashlash uchun «-» yuboring."
        ),
        "started_talking": (
            "🎬 Video tayyorlanmoqda, taxminan 3–5 daqiqa.\n"
            "Botni yopishingiz mumkin — tayyor bo'lganda o'zim yuboraman."
        ),
        "started_series": (
            "🎬 Seriya tayyorlanmoqda, taxminan 10 daqiqa.\n"
            "Botni yopishingiz mumkin — tayyor bo'lganda o'zim yuboraman."
        ),
        "spoken_result": "Tayyor! ✨",
        "flow_expired": "Bu bosqich eskirdi. Menyudan qaytadan boshlang.",
    },
    Language.RU: {
        "choose_language": "Tilni tanlang · Выберите язык",
        "welcome": (
            "Привет! Я <b>Contentor AI</b> — делаю видео из вашего селфи.\n\n"
            "🎬 <b>Тренды</b> — трендовое видео 8 секунд\n"
            "🎙 <b>Говорящее видео</b> — вы говорите на камеру: реклама, совет, POV\n"
            "🎞 <b>Серия</b> — история из 3 частей, 30 секунд"
        ),
        "menu_trends": "🎬 Тренды",
        "menu_balance": "⚡ Баланс",
        "menu_language": "🌐 Язык",
        "menu_help": "❓ Помощь",
        "rules": (
            "<b>Правила использования</b>\n\n"
            "Нельзя:\n"
            "• загружать фото другого человека без его согласия\n"
            "• загружать фото людей младше 18 лет\n"
            "• обнажённые или непристойные фото\n"
            "• использовать видео для обмана, клеветы или незаконных целей\n\n"
            "Ваши фото используются только для создания видео и удаляются через 24 часа."
        ),
        "rules_accept": "✅ Согласен",
        "gallery_empty": "Пока нет активных трендов. Скоро добавим!",
        "filter_all": "Все",
        "filter_women": "Женские",
        "filter_men": "Мужские",
        "card": "{badge}<b>{title}</b>\n{position}",
        "pick": "✅ Выбрать · {price} ⚡",
        "send_selfie": (
            "<b>{title}</b> — пришлите селфи.\n\n"
            "• лицо хорошо видно, светлое место\n"
            "• на фото только вы\n"
            "• для лучшего качества можно отправить фото «файлом»"
        ),
        "not_a_photo": "Пожалуйста, пришлите фото (JPG или PNG).",
        "photo_too_big": "Фото слишком большое. Пришлите фото меньше 10 МБ.",
        "trend_unavailable": "Этот тренд сейчас недоступен. Выберите другой.",
        "insufficient": (
            "Недостаточно ⚡: нужно <b>{required}</b>, у вас <b>{available}</b>.\n"
            "Пакеты скоро появятся в продаже."
        ),
        "started": (
            "🎬 Видео готовится, примерно 3 минуты.\n"
            "Можно закрыть бот — пришлю, когда будет готово."
        ),
        "result": "Готово! ✨ Поделитесь с друзьями.",
        "regenerate": "🔁 Создать заново · {price} ⚡",
        "share": "📤 Поделиться",
        "share_text": "Смотрите, какое видео из селфи получилось в Contentor AI!",
        "regen_need_photo": "Прошлое фото не сохранилось. Пришлите селфи ещё раз.",
        "balance": "Ваш баланс: <b>{available} ⚡</b>",
        "balance_held": "Ваш баланс: <b>{available} ⚡</b> (ещё {held} ⚡ в видео, которое готовится)",
        "help": (
            "Трендовое видео — 2 ⚡, 1080p, 8 секунд, с музыкой.\n"
            "Говорящее видео (10 с) — 1 / 3 / 5 ⚡ (360p / 720p / 1080p).\n"
            "Серия (3×10 с) — 3 / 9 / 15 ⚡.\n"
            "Если видео не получилось или заблокировано, ⚡ возвращаются полностью."
        ),
        "language_set": "Язык: Русский ✅",
        "failed_photo_no_face": "Лицо на фото плохо видно. Пришлите селфи, где хорошо видно лицо.",
        "failed_photo_several_people": "На фото несколько человек. Пришлите селфи, где только вы.",
        "failed_photo_minor": "Извините, мы не создаём видео с фото людей младше 18 лет.",
        "failed_photo_celebrity": "Мы не создаём видео с фото знаменитостей. Пришлите своё селфи.",
        "failed_photo_nudity": "Мы не можем принять это фото. Пришлите другое селфи.",
        "failed_photo_low_quality": "Фото низкого качества (размыто или темно). Переснимите при хорошем свете.",
        "failed_blocked": "Извините, в этот раз не получилось — фильтр безопасности остановил видео. ⚡ возвращены.",
        "failed_failed": "Извините, произошла техническая ошибка. ⚡ возвращены, попробуйте чуть позже.",
        "failed_refund_note": "⚡ не списаны.",
        "blocked": "Ваш аккаунт ограничен. Если есть вопросы, напишите в поддержку.",
        "menu_talking": "🎙 Говорящее видео",
        "menu_series": "🎞 Серия 3×10",
        "product_talking": "Говорящее видео · 10 секунд",
        "product_series": "Серия · 3 части × 10 секунд",
        "choose_style": "<b>{product}</b>\n\nВ видео вы говорите на камеру. Выберите стиль:",
        "styles_empty": "Пока нет стилей. Скоро добавим!",
        "style_unavailable": "Этот стиль сейчас недоступен. Выберите другой.",
        "spoken_send_selfie": (
            "Пришлите селфи — в видео будет говорить этот человек.\n\n"
            "• лицо анфас, чётко, при хорошем свете\n"
            "• на фото только вы"
        ),
        "send_idea": (
            "Теперь напишите идею или отправьте голосовое (до 1 минуты).\n\n"
            "Например: «В моём магазине новые зимние куртки, скидка 20%, Чиланзар 5-квартал»"
        ),
        "idea_needed": "Пришлите идею текстом или голосовым сообщением.",
        "voice_too_long": "Голосовое должно быть не длиннее 1 минуты.",
        "writing_script": "✍️ Пишу сценарий…",
        "script": (
            "<b>Сценарий</b> · {style}\n\n{lines}\n\n"
            "Текст можно менять бесплатно. ⚡ списываются только при создании видео."
        ),
        "script_approve": "✅ Продолжить",
        "script_rewrite": "🔄 Другой вариант",
        "script_edit": "✏️ Напишу сам",
        "send_other_selfie": "Пришлите другое селфи.",
        "idea_rejected": "Не могу сделать видео по этой идее. Пришлите другую.",
        "script_failed": "Не получилось написать сценарий. Пришлите идею ещё раз чуть позже.",
        "rewrite_limit": "Для этого видео уже написано {limit} вариантов. Текст можно отредактировать самому.",
        "own_text_prompt": (
            "Пришлите текст: {parts} строк(и), каждая часть с новой строки, "
            "до 22 слов в строке (чтобы уложиться в 10 секунд)."
        ),
        "own_wrong_parts": "Нужно {parts} строк(и): каждая часть с новой строки.",
        "own_too_long": "Строки слишком длинные. Не больше 22 слов в строке.",
        "choose_resolution": "Выберите качество:",
        "resolution_button": "{resolution} · {price} ⚡",
        "options": (
            "<b>Всё готово</b>\n\n"
            "Качество: {resolution}\nСубтитры: {subtitles}\nКонтакт: {contact}\n\n"
            "Цена: <b>{price} ⚡</b>"
        ),
        "option_subtitles_on": "✅ Субтитры",
        "option_subtitles_off": "⬜ Субтитры",
        "option_contact": "📇 Текст контакта",
        "option_create": "🚀 Создать · {price} ⚡",
        "word_on": "есть",
        "word_off": "нет",
        "ask_contact": (
            "Пришлите текст, который будет вверху видео (до 64 символов): телефон, адрес "
            "или @username.\nЧтобы убрать, отправьте «-»."
        ),
        "started_talking": (
            "🎬 Видео готовится, примерно 3–5 минут.\n"
            "Можно закрыть бот — пришлю, когда будет готово."
        ),
        "started_series": (
            "🎬 Серия готовится, примерно 10 минут.\n"
            "Можно закрыть бот — пришлю, когда будет готово."
        ),
        "spoken_result": "Готово! ✨",
        "flow_expired": "Этот шаг устарел. Начните заново из меню.",
    },
}


def t(language: Language, key: str, **values: object) -> str:
    text = TEXTS[language][key]
    return text.format(**values) if values else text


MENU_KEYS = (
    "menu_trends",
    "menu_talking",
    "menu_series",
    "menu_balance",
    "menu_language",
    "menu_help",
)
# Reply-keyboard buttons; free-text steps ignore them so the menu always works.
MENU_TEXTS = frozenset(TEXTS[language][key] for language in Language for key in MENU_KEYS)
