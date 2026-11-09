"""Сервис «Классификатор сложности текста для РКИ». Веб-часть на FastAPI.

Работает по контракту API v1.1 (файл API.md).

Запуск:   uvicorn main:app --reload
Проверка: http://127.0.0.1:8000/docs
Тесты (в другом окне, пока сервер работает):
          python test_api.py        — проверка из шаблона курса
          python test_contract.py   — проверка нашего контракта
"""

import time
from datetime import datetime

from fastapi import FastAPI, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictStr

from nlp import MAX_CHARS, MIN_WORDS, MODES, ModelUnavailable, analyze

app = FastAPI(
    title="Классификатор сложности текста для РКИ",
    description=(
        "Определяет уровень сложности русского текста для изучающих русский "
        "как иностранный: A (A1–A2), B (B1–B2) или C (C1–C2). "
        "Учебный проект курсов «Основы web-программирования» и АОЕЯ."
    ),
    version="1.1.0",
)

# Страница интерфейса и сервер будут по разным адресам — без этого браузер
# не пустит запросы страницы к серверу.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HISTORY = []        # история запросов живёт в памяти процесса: перезапуск её обнуляет


# ——————————————————————————————————————————————————————————————
# Ошибки по контракту: {"error": "<код>", "message": "<текст>"}
# ——————————————————————————————————————————————————————————————

MESSAGES = {
    "empty_text": "Введите текст",
    "text_too_long": f"Текст длиннее {MAX_CHARS} знаков",
    "unsupported_language": "Сервис работает только с русским текстом",
    "text_too_short": f"Текст слишком короткий: нужно не меньше {MIN_WORDS} слов",
    "invalid_request": "Некорректный запрос: нужно поле text со строкой",
    "unknown_mode": "Неизвестный режим. Доступны: " + ", ".join(MODES),
    # коды выше nlp.py поднимает как ValueError("<код>"), main.py подставляет текст
    "model_unavailable": "Модель недоступна, попробуйте позже",
}
STATUS = {"model_unavailable": 503}          # остальные ошибки — 400


class ApiError(Exception):
    def __init__(self, code, message=None):
        super().__init__(code)
        self.code = code
        self.message = message or MESSAGES[code]
        self.status = STATUS.get(code, 400)

    def body(self):
        data = {"error": self.code, "message": self.message}
        if self.code == "text_too_long":
            data["limit"] = MAX_CHARS            # limit есть только у этой ошибки
        return data


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content=exc.body())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Эндпоинты проекта (/api/...) отвечают по нашему контракту: 400 invalid_request.
    # Учебные эндпоинты (/greet, /feedback) оставляем со стандартным ответом FastAPI 422.
    if request.url.path.startswith("/api/"):
        message = None if request.url.path == "/api/analyze" else "Некорректные параметры запроса"
        return JSONResponse(status_code=400, content=ApiError("invalid_request", message).body())
    return await request_validation_exception_handler(request, exc)


# ——————————————————————————————————————————————————————————————
# Шаг 1. Готово — смотрите, как устроен эндпоинт
# ——————————————————————————————————————————————————————————————

@app.get("/hello")
def hello():
    return {"message": "Hello, FastAPI!"}


# ——————————————————————————————————————————————————————————————
# Шаг 2. Эндпоинт /greet с параметром запроса
# ——————————————————————————————————————————————————————————————

@app.get("/greet")
def greet(name: str = Query("stranger", min_length=1, max_length=50)):
    return {"message": f"Hello, {name}!"}


# ——————————————————————————————————————————————————————————————
# Шаг 3. POST /feedback с Pydantic-моделью
# ——————————————————————————————————————————————————————————————

class Feedback(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    comment: str = Field(min_length=1, max_length=1000)


@app.post("/feedback")
def feedback(item: Feedback):
    return {"message": f"Thanks for your feedback, {item.username}!"}


# ——————————————————————————————————————————————————————————————
# Шаг 4. Главный эндпоинт проекта: POST /api/analyze
# ——————————————————————————————————————————————————————————————
# Ответ: {"ok": true, "result": {...}, "meta": {...}}.
# В режиме complexity result — это объект из контракта
# (level, score, all_scores, factors, highlights).

EXAMPLE_TEXT = (
    "Вчера вечером я долго разговаривал с преподавателем о будущей работе, "
    "и он посоветовал мне обязательно подготовиться заранее. Это было очень полезно."
)

class AnalyzeIn(BaseModel):
    # Длину текста здесь не ограничиваем: её проверяет nlp.py, чтобы
    # вернуть коды ошибок из контракта, а не общий ответ 422.
    text: StrictStr = Field(..., description="Русский текст: от 3 слов до 5 000 символов",
                            examples=[EXAMPLE_TEXT])
    lang: StrictStr = Field("ru", description='Только "ru"', examples=["ru"])
    mode: StrictStr = Field("complexity", description="Режим анализа, см. GET /api/modes",
                            examples=["complexity"])


def check_lang(text, lang):
    """Поле lang в nlp.py не передаётся, поэтому его проверяет main.py.

    По контракту пустой и слишком длинный текст проверяются раньше языка,
    поэтому при неверном lang сначала смотрим на них.
    """
    if lang == "ru":
        return
    if not text.strip():
        raise ApiError("empty_text")
    if len(text) > MAX_CHARS:
        raise ApiError("text_too_long")
    raise ApiError("unsupported_language")


@app.post("/api/analyze", summary="Определить уровень сложности текста")
def analyze_text(item: AnalyzeIn):
    started = time.perf_counter()
    check_lang(item.text, item.lang)

    try:
        result = analyze(item.text, item.mode)
    except ModelUnavailable:
        raise ApiError("model_unavailable")
    except ValueError as error:
        # nlp.py поднимает ValueError с кодом ошибки из контракта
        code = str(error)
        if code == "unknown_mode":
            raise ApiError(code, f"Неизвестный режим: {item.mode}. Доступны: {', '.join(MODES)}")
        if code in MESSAGES:
            raise ApiError(code)
        raise ApiError("invalid_request", code)    # непредусмотренный отказ nlp.py

    response = {
        "ok": True,
        "result": result,
        "meta": {
            "chars": len(item.text),
            "mode": item.mode,
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }
    HISTORY.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "text": item.text[:80],
        "mode": item.mode,
        "result": result,
    })
    return response


# ——————————————————————————————————————————————————————————————
# Шаг 5. Список режимов — страница построит из него выпадающий список
# ——————————————————————————————————————————————————————————————

@app.get("/api/modes")
def modes():
    return {"modes": MODES}


# ——————————————————————————————————————————————————————————————
# Со звёздочкой
# ——————————————————————————————————————————————————————————————

@app.get("/api/health")
def health():
    return {"status": "ok", "requests": len(HISTORY)}


@app.get("/api/history")
def history(limit: int = Query(10, ge=1, le=100)):
    return {"history": list(reversed(HISTORY[-limit:]))}     # новые сверху
