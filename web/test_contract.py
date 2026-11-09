"""Проверка нашего контракта API v1.1. Запускать, пока работает uvicorn:

    python test_contract.py

Дополняет test_api.py из шаблона курса: тот проверяет общие шаги,
этот — то, что записано в API.md именно для нашего сервиса.
"""

import sys

try:
    import requests
except ImportError:
    sys.exit("Не установлена библиотека requests:  pip install requests")

BASE = "http://127.0.0.1:8000"
URL = f"{BASE}/api/analyze"
EXAMPLE = ("Вчера вечером я долго разговаривал с преподавателем о будущей работе, "
           "и он посоветовал мне обязательно подготовиться заранее. Это было очень полезно.")

passed, failed = 0, 0


def check(title, func):
    global passed, failed
    try:
        problem = func()
    except requests.ConnectionError:
        sys.exit(f"Сервер не отвечает на {BASE} — запущен ли uvicorn main:app --reload?")
    except Exception as error:
        problem = f"{type(error).__name__}: {error}"
    if problem:
        failed += 1
        print(f"  [ ] {title}\n        {problem}")
    else:
        passed += 1
        print(f"  [v] {title}")


def post(payload):
    return requests.post(URL, json=payload, timeout=10)


print(f"Проверяю контракт на {BASE}\n")


def t_success():
    r = post({"text": EXAMPLE, "lang": "ru"})
    if r.status_code != 200:
        return f"ожидался код 200, пришёл {r.status_code}: {r.text[:200]}"
    data = r.json()
    if data.get("meta", {}).get("mode") != "complexity":
        return f"режим по умолчанию должен быть complexity: {data.get('meta')}"
    res = data["result"]
    need = {"level", "score", "all_scores", "factors", "highlights"}
    if set(res) != need:
        return f"в result должны быть ровно поля {sorted(need)}, а пришли {sorted(res)}"
    if res["level"] not in ("A", "B", "C"):
        return f"level должен быть A, B или C: {res['level']}"
    if not 0 <= res["score"] <= 100:
        return f"score вне 0–100: {res['score']}"
    if set(res["all_scores"]) != {"A", "B", "C"} or abs(sum(res["all_scores"].values()) - 1) > 0.01:
        return f"all_scores: ключи A, B, C, сумма 1 — пришло {res['all_scores']}"
    f, h = res["factors"], res["highlights"]
    if f["long_sentences"] != len(h["long_sentences"]) or f["rare_words"] != len(h["rare_words"]):
        return "factors не совпадают с длиной списков в highlights"
    for w in h["rare_words"]:
        if EXAMPLE[w["start"]:w["end"]] != w["word"]:
            return f"text[start:end] не равно слову: {w}"


check("200: ответ ok/result/meta, result по контракту", t_success)


def t_lang_optional():
    r = post({"text": EXAMPLE})
    if r.status_code != 200:
        return f"без lang ожидался код 200, пришёл {r.status_code}"


check("Поле lang необязательно", t_lang_optional)

ERRORS = [
    ("Пустой текст → empty_text", {"text": "   "}, 400, "empty_text"),
    ("Длиннее 5000 → text_too_long", {"text": "слово " * 1000}, 400, "text_too_long"),
    ('lang не "ru" → unsupported_language', {"text": EXAMPLE, "lang": "en"}, 400, "unsupported_language"),
    ("Нерусский текст → unsupported_language", {"text": "Hello world again"}, 400, "unsupported_language"),
    ("Меньше 3 слов → text_too_short", {"text": "Привет мир"}, 400, "text_too_short"),
    ("Нет поля text → invalid_request", {}, 400, "invalid_request"),
    ("text не строка → invalid_request", {"text": 123}, 400, "invalid_request"),
    ("Неизвестный режим → unknown_mode", {"text": EXAMPLE, "mode": "xyz"}, 400, "unknown_mode"),
]

for title, payload, status, code in ERRORS:
    def t(payload=payload, status=status, code=code):
        r = post(payload)
        if r.status_code != status:
            return f"ожидался код {status}, пришёл {r.status_code}: {r.text[:200]}"
        data = r.json()
        if data.get("error") != code or "message" not in data:
            return f"ожидалось {{error: {code}, message: ...}}, пришло {data}"
        if ("limit" in data) != (code == "text_too_long"):
            return f"поле limit должно быть только у text_too_long: {data}"
    check(title, t)


def t_modes():
    modes = requests.get(f"{BASE}/api/modes", timeout=10).json().get("modes", [])
    if "complexity" not in modes:
        return f"в /api/modes нет complexity: {modes}"


def t_health():
    r = requests.get(f"{BASE}/api/health", timeout=10)
    if r.status_code != 200 or r.json().get("status") != "ok":
        return f"ожидалось status: ok, пришло {r.status_code} {r.text[:200]}"


def t_history():
    r = requests.get(f"{BASE}/api/history", params={"limit": 2}, timeout=10)
    if r.status_code != 200 or len(r.json().get("history", [])) > 2:
        return f"history должна вернуть не больше 2 записей: {r.text[:200]}"


check("GET /api/modes содержит complexity", t_modes)
check("GET /api/health отвечает", t_health)
check("GET /api/history?limit=2 возвращает не больше 2 записей", t_history)

print(f"\nГотово: {passed} из {passed + failed}")
