"""Bot copy in Uzbek (Latin) and Russian. Every key exists in both languages (tested)."""

from app.models.enums import Language

TEXTS: dict[Language, dict[str, str]] = {
    Language.UZ: {
        "choose_language": "Tilni tanlang · Выберите язык",
        "welcome": (
            "Salom! Men <b>Contentor AI</b> — selfingizdan trend video yasayman.\n\n"
            "1. Trendni tanlang\n2. Selfi yuboring\n3. ~3 daqiqada tayyor video oling"
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
    },
    Language.RU: {
        "choose_language": "Tilni tanlang · Выберите язык",
        "welcome": (
            "Привет! Я <b>Contentor AI</b> — делаю трендовые видео из вашего селфи.\n\n"
            "1. Выберите тренд\n2. Пришлите селфи\n3. Получите видео примерно через 3 минуты"
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
    },
}


def t(language: Language, key: str, **values: object) -> str:
    text = TEXTS[language][key]
    return text.format(**values) if values else text
