from __future__ import annotations

import time

from fastapi.testclient import TestClient

from deep_research_api import create_app


def main() -> None:
    app = create_app()
    client = TestClient(app)

    payload = {
        "proposal_text": (
            """**Название проекта:** РАЗРАБОТКА ПРОГРАММНОГО ОБЕСПЕЧЕНИЯ ПОИСКА И ИНТЕЛЛЕКТУАЛЬНОЙ ОБРАБОТКИ ФАРМАКОПЕЙНОЙ ИНФОРМАЦИИ
- **Описание проекта:** Разрабатываемое программное обеспечение предназначено для автоматизированного поиска, обработки (включая перевод с иностранных языков) и анализа документов в области фармакологии с использованием технологий искусственного интеллекта на основе больших языковых моделей (БЯМ), при строгом соблюдении требований к безопасности и конфиденциальности, в ФГБУ «НЦЭСМП» Минздрава России, а также в фармацевтических компаниях и иных регуляторных органах и организациях, занимающихся контролем качества лекарственных средств.
- **Задача проекта:** Создание ПО «Фармадок» направлено на решение следующих задач: 1) Автоматизация анализа инструкций к лекарственным препаратам и иных документов из состава регистрационных досье лекарственных средств на соответствие регуляторным требованиям. Критерий достижения – сокращение времени на анализ одного документа не менее чем на 50% по сравнению с ручным методом. 2) Повышение качества оформления и правильности форматирования инструкций, снижение количества орфографических ошибок. Критерий достижения – экспертная оценка на основе не менее 30 тестовых документов, сгенерированных системой и проверенных вручную экспертами. 3) Автоматизация и повышение оперативности поиска релевантной информации на разр...
- **Этап:** Проведен аудит объекта автоматизации, разработано техническое задание, осуществляется поиск исполнителей. По просьбе заказчика разработан MVP для решения частной, но трудоемкой задачи - сравнения инструкций лекарственных препаратов с выявлением различий и генерацией отчета в docx (gradio + docling + deepseek + python-docx).
- **Технологии Яндекса:** YandexGPT
- **Сроки:** 2025-07-01 - 2025-12-31"""
        ),
        "evaluation_prompt": "Не учитывай техническую проработанность",
        "artifact_dir": "a_async",
        "continue_on_agent_error": False,
        "suppress_stdout": True,
    }

    start_resp = client.post("/deep-research/evaluate/async", json=payload)
    start_resp.raise_for_status()
    job_id = start_resp.json()["job_id"]
    print(f"Started job_id={job_id}")

    while True:
        status_resp = client.get(f"/deep-research/evaluate/status/{job_id}")
        status_resp.raise_for_status()
        status = status_resp.json()
        print(
            f"status={status['status']}, "
            f"current_agent={status.get('current_agent')}, "
            f"progress={status['completed_agents']}/{status['total_agents']}"
        )

        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(2)

    result_resp = client.get(f"/deep-research/evaluate/result/{job_id}")
    result_resp.raise_for_status()
    data = result_resp.json()
    print(f"final_status={data['status']}")
    if data["status"] == "completed" and data.get("result"):
        result = data["result"]
        print(f"verdict={result.get('verdict')}")
        print(f"confidence={result.get('confidence')}")
        print((result.get("moderator_output") or "")[:1000])
    else:
        print(f"error={data.get('error')}")


if __name__ == "__main__":
    main()
