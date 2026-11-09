"""Анализ текста. Единственная точка входа — функция analyze(text, mode).

Этот файл — шов между курсами. Здесь происходит валидация данных, извлечение
лингвистических признаков и (в будущем) вызов ML-модели.
Модуль ничего не знает про веб (FastAPI и т.д.), его можно вызвать из ноутбука.

Правило: ошибки в данных здесь поднимаются как ValueError (с кодом ошибки).
Превращать их в HTTP-ответ — дело main.py.
"""

import re

# --- Константы из контракта API ---
MAX_CHARS = 5000
MIN_WORDS = 3
MIN_RUSSIAN_RATIO = 0.5

MODES = ["complexity", "stats", "freq", "longest"]

# Порог длины предложения в словах, после которого оно считается "длинным"
LONG_SENTENCE_THRESHOLD = 15

# Слова, которые не считаются "знаменательными" в режиме freq
STOPWORDS = {
    "и", "в", "во", "не", "на", "что", "с", "со", "как", "а", "то", "все", "она",
    "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "ее",
    "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "когда",
    "даже", "ну", "ли", "если", "уже", "или", "ни", "быть", "был", "него", "до",
    "вам", "там", "потом", "себя", "ничего", "ей", "они", "тут", "где", "есть",
    "надо", "для", "мы", "их", "чем", "была", "без", "чего", "раз", "себе", "под",
    "будет", "тогда", "кто", "этот", "того", "потому", "этого", "какой", "это",
}


class ModelUnavailable(RuntimeError):
    """Вызывается, когда ML-модель не загрузилась (сервис должен вернуть 503)."""
    pass


def validate_text(text: str):
    """Проверяет текст на соответствие ограничениям из контракта API."""
    # 1. Пустой текст
    if not text or not text.strip():
        raise ValueError("empty_text")

    # 2. Слишком длинный
    if len(text) > MAX_CHARS:
        raise ValueError("text_too_long")

    # 3. Язык (считаем долю русских среди ВСЕХ букв любого алфавита)
    all_letters = re.findall(r"[^\W\d_]", text, flags=re.UNICODE)
    if not all_letters:
        raise ValueError("unsupported_language")

    russian_letters = re.findall(r"[а-яё]", text.lower())
    if len(russian_letters) / len(all_letters) < MIN_RUSSIAN_RATIO:
        raise ValueError("unsupported_language")

    # 4. Слишком короткий (менее 3 слов)
    words = re.findall(r'[а-яёa-z]+', text.lower())
    if len(words) < MIN_WORDS:
        raise ValueError("text_too_short")


def analyze(text: str, mode: str = "complexity") -> dict:
    """
    Главная точка входа.
    Возвращает словарь 'result', строго соответствующий контракту API.
    """
    # Сначала проверяем сам текст (порядок ошибок 400)
    validate_text(text)

    # Общая токенизация для всех режимов (в нижнем регистре для подсчетов)
    words_lower = re.findall(r'[а-яёa-z]+', text.lower())

    # Разбиваем на предложения с учетом многоточия
    sentences = [s.strip() for s in re.split(r'[.!?…]+', text) if s.strip()]

    # ——— Учебные режимы (stats, freq, longest) ———

    if mode == "stats":
        return {
            "words": len(words_lower),
            "unique": len(set(words_lower)),
            "ttr": round(len(set(words_lower)) / max(len(words_lower), 1), 3),
            "sentences": len(sentences),
            "avg_sentence": round(len(words_lower) / max(len(sentences), 1), 1),
        }

    if mode == "freq":
        meaningful = [w for w in words_lower if w not in STOPWORDS and len(w) > 2]
        counts = {}
        for w in meaningful:
            counts[w] = counts.get(w, 0) + 1

        sorted_words = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:10]
        return {
            "top": [{"word": w, "count": c} for w, c in sorted_words],
            "total_counted": len(meaningful)
        }

    if mode == "longest":
        unique_words = sorted(set(words_lower), key=len, reverse=True)[:10]
        return {
            "words": unique_words,
            "max_length": len(unique_words[0]) if unique_words else 0
        }

    # ——— Основной режим: Оценка сложности (complexity) ———

    if mode == "complexity":
        # TODO: В будущем здесь будет вызов модели.
        # Пока используем эвристическую заглушку.

        # 1. Поиск длинных предложений (индексы start/end в ИСХОДНОМ тексте)
        long_sentences_highlights = []
        for match in re.finditer(r'[^.!?…]+[.!?…]*', text):
            sent_text = match.group()
            if len(re.findall(r'[а-яёa-z]+', sent_text.lower())) >= LONG_SENTENCE_THRESHOLD:
                # Обрезаем пробелы по краям для точных индексов
                start = match.start() + len(sent_text) - len(sent_text.lstrip())
                end = match.end() - len(sent_text) + len(sent_text.rstrip())
                if start < end:
                    long_sentences_highlights.append({"start": start, "end": end})

        # 2. Поиск редких/сложных слов (длина > 6, эвристика)
        rare_words_highlights = []
        # Ищем в исходном тексте (с сохранением регистра)
        for match in re.finditer(r'[а-яёa-z]+', text, flags=re.IGNORECASE):
            word = match.group()
            if len(word) > 6:
                rare_words_highlights.append({
                    "word": word,
                    "start": match.start(),
                    "end": match.end()
                })

        # 3. Расчет score (0-100, где 100 - максимально сложно)
        avg_sent_len = len(words_lower) / max(len(sentences), 1)
        ratio_long_words = len(rare_words_highlights) / max(len(words_lower), 1)

        # Формула-заглушка: штраф за длинные предложения и длинные слова
        score = min(100, round(avg_sent_len * 2.5 + ratio_long_words * 40))

        # 4. Генерация вероятностей (all_scores) на основе score.
        # Задаем базовые центры сложности для классов A, B, C.
        def get_prob(score_val, center):
            distance = abs(score_val - center)
            return max(0.01, 1.0 / (1.0 + (distance / 15) ** 2))

        p_a = get_prob(score, 15)
        p_b = get_prob(score, 50)
        p_c = get_prob(score, 85)

        # Нормализация, чтобы сумма была 1.0
        total_prob = p_a + p_b + p_c
        probs = {"A": p_a / total_prob, "B": p_b / total_prob, "C": p_c / total_prob}

        # 5. Выбор максимальной вероятности и согласование с уровнем
        level = max(probs, key=probs.get)

        # 6. Округление и корректировка суммы до ровно 1.0
        all_scores = {k: round(v, 3) for k, v in probs.items()}
        diff = round(1.0 - sum(all_scores.values()), 3)

        if diff != 0:
            # Находим класс с максимальной вероятностью и добавляем к нему остаток
            max_key = max(all_scores, key=all_scores.get)
            all_scores[max_key] = round(all_scores[max_key] + diff, 3)

        # Формируем factors строго по контракту (целые числа)
        factors = {
            "long_sentences": len(long_sentences_highlights),
            "rare_words": len(rare_words_highlights),
            "syntax_depth": round(1.0 + (text.count(',') / max(len(sentences), 1)), 2)
        }

        return {
            "level": level,
            "score": score,
            "all_scores": all_scores,
            "factors": factors,
            "highlights": {
                "long_sentences": long_sentences_highlights,
                "rare_words": rare_words_highlights
            }
        }

    # Если режим не распознан (проверяется в самом конце, как в контракте)
    raise ValueError("unknown_mode")


# Проверить модуль можно и без сервера: python nlp.py
if __name__ == "__main__":
    import json

    sample = ("Язык устроен так, что небольшое число элементов порождает "
              "бесконечное число сообщений. Эта способность называется продуктивностью. "
              "Но иногда встречаются очень длинные предложения, которые содержат "
              "множество сложных слов, вроде «интернационализация» или «экзистенциальный».")

    for m in MODES:
        try:
            res = analyze(sample, m)
            print(f"--- {m} ---")
            print(json.dumps(res, ensure_ascii=False, indent=2))
        except ValueError as e:
            print(f"{m} → ошибка:", e)

    # Тесты ошибок
    print("\n--- Тесты ошибок ---")
    tests = [
        ("", "complexity", "empty_text"),
        ("а б", "complexity", "text_too_short"),
        ("Hello world", "complexity", "unsupported_language"),
        (sample, "unknown", "unknown_mode")
    ]
    for bad_text, bad_mode, expected in tests:
        try:
            analyze(bad_text, bad_mode)
        except ValueError as e:
            assert str(e) == expected, f"Ожидалось {expected}, получено {e}"
            print(f"Успешно отловлено: {e}")