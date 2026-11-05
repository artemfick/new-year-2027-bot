"""
Бот-обратный отсчёт до Нового года для Телеграм-группы.

Что делает:
  countdown — каждый день в 00:00 МСК: стикер «До Нового года N дней».
              1 января в 00:00 МСК вместо этого: «московские, с Новым годом 🎄» + стикер.
  eve       — 31 декабря в 20:00 МСК: стикер «С наступающим Новым годом!»
  togliatti — 1 января в 00:00 по Тольятти (GMT+4): текст + стикер «С Новым годом!»
  moscow    — то же поздравление для Москвы (обычно вызывается из countdown)
  say       — сразу отправить свой текст (SAY_TEXT) от имени бота

Ручной запуск может задать TO_CHATS — тогда отправка только туда, а не во все CHAT_IDS.

Служебное:
  python bot.py chats — показать chat_id чатов, где бот видел сообщения
  python bot.py list  — показать стикеры пака по порядку

Расписание запускает скрипт заранее, а он сам дожидается точного времени.
Так GitHub, который иногда опаздывает на 5–30 минут, не сдвигает поздравление.

Переменные окружения:
  BOT_TOKEN   — токен от @BotFather
  CHAT_IDS    — chat_id через запятую
  STICKER_SET — имя пака (то, что после t.me/addstickers/)
  MANUAL=1    — ручной запуск: отправить сразу, без ожидания (для проверки)
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

# ── Настройки, которые можно поменять ─────────────────────────────────
MSK = ZoneInfo("Europe/Moscow")        # GMT+3
TOLYATTI = ZoneInfo("Europe/Samara")   # GMT+4 (Тольятти живёт по самарскому времени)

TEXT_TOLYATTI = "ну че, тольяттинские, с нгшкой чтоли"
TEXT_MOSCOW = "московские, с Новым годом 🎄"

EVE_TIME = dt.time(20, 0)              # когда слать «С наступающим» 31 декабря (МСК)

# Порядок стикеров в паке: №0 = «100 дней» … №99 = «1 день»,
# №100 = «С наступающим Новым годом!», №101 = «С Новым годом!»
FIRST_DAYS = 100
IDX_EVE = 100
IDX_NEW_YEAR = 101
# ──────────────────────────────────────────────────────────────────────


def env(name, required=False):
    value = os.environ.get(name, "").strip()
    if required and not value:
        sys.exit(f"Не задана переменная {name}")
    return value


def call(method, **params):
    url = f"https://api.telegram.org/bot{env('BOT_TOKEN', required=True)}/{method}"
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        res = json.load(e)
    if not res.get("ok"):
        raise RuntimeError(f"{method}: {res.get('description', res)}")
    return res["result"]


# ── Когда и что отправлять ─────────────────────────────────────────────
def next_midnight(tz, now):
    """Ближайшая полночь в поясе tz. Если запуск опоздал (уже после полуночи,
    но раньше 6 утра) — берём только что прошедшую, и тогда отправим сразу."""
    local = now.astimezone(tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight if local.hour < 6 else midnight + dt.timedelta(days=1)


def countdown_actions(msk_date):
    if (msk_date.month, msk_date.day) == (1, 1):
        return [("text", TEXT_MOSCOW), ("sticker", IDX_NEW_YEAR)]
    days = (dt.date(msk_date.year + 1, 1, 1) - msk_date).days
    if 1 <= days <= FIRST_DAYS:
        return [("sticker", FIRST_DAYS - days)]
    return []  # до НГ больше 100 дней — в паке такого стикера нет


def plan(mode, now, manual=False):
    """Возвращает (момент отправки, список действий)."""
    if mode == "countdown":
        target = now if manual else next_midnight(MSK, now)
        return target, countdown_actions(target.astimezone(MSK).date())
    if mode == "eve":
        year = now.astimezone(MSK).year
        target = now if manual else dt.datetime.combine(dt.date(year, 12, 31), EVE_TIME, MSK)
        return target, [("sticker", IDX_EVE)]
    if mode == "togliatti":
        target = now if manual else next_midnight(TOLYATTI, now)
        return target, [("text", TEXT_TOLYATTI), ("sticker", IDX_NEW_YEAR)]
    if mode == "moscow":
        target = now if manual else next_midnight(MSK, now)
        return target, [("text", TEXT_MOSCOW), ("sticker", IDX_NEW_YEAR)]
    sys.exit(f"Неизвестный режим: {mode}")


# ── Команды ─────────────────────────────────────────────────────────────
def run(mode):
    manual = env("MANUAL") == "1"
    now = dt.datetime.now(dt.timezone.utc)
    target, actions = plan(mode, now, manual)
    if not actions:
        print(f"[{mode}] на {target.astimezone(MSK):%d.%m %H:%M} МСК отправлять нечего.")
        return

    chat_ids = get_chat_ids()
    stickers = call("getStickerSet", name=env("STICKER_SET", required=True))["stickers"]
    if len(stickers) <= IDX_NEW_YEAR:
        sys.exit(f"В паке {len(stickers)} стикеров, а нужно минимум {IDX_NEW_YEAR + 1}. Пак изменился?")

    wait = (target - dt.datetime.now(dt.timezone.utc)).total_seconds()
    if wait > 0:
        print(f"[{mode}] жду до {target.astimezone(MSK):%d.%m %H:%M:%S} МСК ({wait / 60:.0f} мин)")
        time.sleep(wait)

    failed = []
    send_all(mode, chat_ids, actions, stickers)


def get_chat_ids():
    """Кому отправлять: TO_CHATS (если задано при ручном запуске), иначе CHAT_IDS."""
    raw = env("TO_CHATS") or env("CHAT_IDS", required=True)
    return [c.strip() for c in raw.split(",") if c.strip()]


def send_all(mode, chat_ids, actions, stickers=None):
    failed = []
    for cid in chat_ids:
        try:
            for kind, value in actions:
                if kind == "text":
                    call("sendMessage", chat_id=cid, text=value)
                else:
                    call("sendSticker", chat_id=cid, sticker=stickers[value]["file_id"])
            print(f"[{mode}] отправил в {cid}")
        except Exception as e:  # один сломанный чат не мешает остальным
            print(f"[{mode}] не смог отправить в {cid}: {e}")
            failed.append(cid)
    if failed:
        sys.exit(f"Ошибки в чатах: {', '.join(failed)}")


def cmd_say():
    """Сообщение от имени бота: текст из SAY_TEXT, отправка сразу."""
    text = env("SAY_TEXT").replace("\\n", "\n")
    if not text:
        sys.exit("Пустой текст — нечего отправлять.")
    send_all("say", get_chat_ids(), [("text", text)])


def cmd_chats():
    seen = {}
    for u in call("getUpdates"):
        for key in ("message", "my_chat_member", "channel_post", "edited_message"):
            chat = (u.get(key) or {}).get("chat")
            if chat:
                seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not seen:
        print("Пусто. Напиши боту или в группу /start@имя_бота и запусти снова.")
    for cid, title in seen.items():
        print(f"{cid}\t{title}")


def cmd_list():
    for i, s in enumerate(call("getStickerSet", name=env("STICKER_SET", required=True))["stickers"]):
        print(f"{i}\t{s.get('emoji', '')}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "countdown"
    if mode == "chats":
        cmd_chats()
    elif mode == "list":
        cmd_list()
    elif mode == "say":
        cmd_say()
    else:
        run(mode)
