from __future__ import annotations

import os
import re
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from integrations.yandex_responses import YandexResponsesClient as AsyncYandexResponsesClient

load_dotenv()


# =============================================================================
# HELPERS
# =============================================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def compact_text(text: str, max_chars: int = 4000) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head - 32
    return text[:head] + "\n\n...[TRUNCATED]...\n\n" + text[-tail:]


def first_non_empty_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return "project"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-zа-я0-9]+", "_", text, flags=re.IGNORECASE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "project"


def extract_section(text: str, heading: str) -> str:
    if not text:
        return ""
    pattern = rf"(?ims)^\s*##+\s*{re.escape(heading)}\s*$([\s\S]*?)(?=^\s*##+\s|\Z)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def extract_score(text: str, labels: List[str]) -> Optional[float]:
    if not text:
        return None

    patterns = []
    for label in labels:
        patterns.extend([
            rf"{re.escape(label)}\s*[:：]\s*(\d+(?:[.,]\d+)?)\s*/\s*100",
            rf"{re.escape(label)}\s*[:：]\s*(\d+(?:[.,]\d+)?)",
        ])

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", ".")
            try:
                value = float(raw)
                if value > 100:
                    value = 100.0
                return value
            except ValueError:
                pass
    return None


def extract_decision(text: str) -> str:
    if not text:
        return "UNKNOWN"

    upper = text.upper()

    if "NO-GO" in upper or "NO GO" in upper:
        return "NO-GO"

    if (
        "GO WITH CONDITIONS" in upper
        or "GO WITH CONDITION" in upper
        or "GO С УСЛОВИЯМИ" in upper
        or "GO WITH CONSTRAINTS" in upper
    ):
        return "GO WITH CONDITIONS"

    if "NEEDS REVISION" in upper:
        return "NEEDS REVISION"

    if re.search(r"(?<!NO[-\s])\bGO\b", upper):
        return "GO"

    return "UNKNOWN"


def extract_executive_summary(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"(?ims)^\s*##\s*Executive Summary\s*$([\s\S]*?)(?=^\s*##\s|\Z)",
        r"(?ims)^\s*#\s*Executive Summary\s*$([\s\S]*?)(?=^\s*##\s|\Z)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return compact_text(text, 3000)


def safe_write(path: Path, content: str) -> None:
    path.write_text(content or "", encoding="utf-8")


def print_block(title: str, content: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    print(content or "[EMPTY]")
    print("=" * 100 + "\n")


# =============================================================================
# CONFIG
# =============================================================================

@dataclass(frozen=True)
class AgentConfig:
    name: str
    env_var: str
    timeout_sec: int
    retries: int = 3


class Config:
    API_KEY = os.getenv("YANDEX_API_KEY", "").strip()
    BASE_URL = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1").rstrip("/")
    PROJECT_ID = os.getenv("YANDEX_PROJECT_ID", "").strip()

    PRINT_FULL_AGENT_OUTPUTS = os.getenv("PRINT_FULL_AGENT_OUTPUTS", "1").lower() in {"1", "true", "yes", "y"}
    SAVE_FULL_PROMPTS = os.getenv("SAVE_FULL_PROMPTS", "1").lower() in {"1", "true", "yes", "y"}
    RETRY_BACKOFF_SEC = float(os.getenv("YANDEX_RETRY_BACKOFF_SEC", "5"))

    AGENTS: Dict[str, AgentConfig] = {
        "project_analyst": AgentConfig("project_analyst", "AGENT_PROJECT_ANALYST_ID", 180),
        "research_strategist": AgentConfig("research_strategist", "AGENT_RESEARCH_STRATEGIST_ID", 180),
        "technical_researcher": AgentConfig("technical_researcher", "AGENT_TECHNICAL_RESEARCHER_ID", 300),
        "architect": AgentConfig("architect", "AGENT_ARCHITECT_ID", 300),
        "roadmap_manager": AgentConfig("roadmap_manager", "AGENT_ROADMAP_MANAGER_ID", 300),
        "hr_specialist": AgentConfig("hr_specialist", "AGENT_HR_SPECIALIST_ID", 180),
        "risk_analyst": AgentConfig("risk_analyst", "AGENT_RISK_ANALYST_ID", 180),
        "quality_reviewer": AgentConfig("quality_reviewer", "AGENT_QUALITY_REVIEWER_ID", 180),
        "synthesis_manager": AgentConfig("synthesis_manager", "AGENT_SYNTHESIS_MANAGER_ID", 300),
    }

    AGENT_ORDER = [
        "project_analyst",
        "research_strategist",
        "technical_researcher",
        "architect",
        "roadmap_manager",
        "hr_specialist",
        "risk_analyst",
        "quality_reviewer",
        "synthesis_manager",
    ]

    AGENT_TITLES = {
        "project_analyst": "PROJECT ANALYST",
        "research_strategist": "RESEARCH STRATEGIST",
        "technical_researcher": "TECHNICAL RESEARCHER",
        "architect": "ARCHITECT",
        "roadmap_manager": "ROADMAP MANAGER",
        "hr_specialist": "HR SPECIALIST",
        "risk_analyst": "RISK ANALYST",
        "quality_reviewer": "QUALITY REVIEWER",
        "synthesis_manager": "SYNTHESIS MANAGER",
    }

    @classmethod
    def validate(cls) -> None:
        if not cls.API_KEY:
            raise ValueError("YANDEX_API_KEY не установлен")
        if not cls.PROJECT_ID:
            raise ValueError("YANDEX_PROJECT_ID не установлен")

        missing = []
        for name, cfg in cls.AGENTS.items():
            if not os.getenv(cfg.env_var, "").strip():
                missing.append(f"{name} ({cfg.env_var})")

        if missing:
            raise ValueError(
                "Не заданы prompt id для агентов:\n- " + "\n- ".join(missing)
            )


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class AgentRun:
    index: int
    agent_name: str
    prompt_id: str
    started_at: str
    finished_at: str
    duration_sec: float
    input_text: str
    output_text: str
    success: bool
    response_id: Optional[str] = None
    response_status: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# =============================================================================
# YANDEX RESPONSES CLIENT
# =============================================================================

class YandexResponsesClient:
    def __init__(self, api_key: str, base_url: str, project_id: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.project_id = project_id

    def call(
        self,
        prompt_id: str,
        input_text: str,
        timeout_sec: int,
        retries: int,
    ) -> Tuple[str, Dict[str, Any]]:
        url = f"{self.base_url}/responses"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {self.api_key}",
            "OpenAI-Project": self.project_id,
        }
        payload = {
            "prompt": {"id": prompt_id},
            "input": input_text,
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout_sec,
                )
                response.raise_for_status()
                data = response.json()
                text = self._extract_text(data)

                if not text.strip():
                    raise RuntimeError("Пустой ответ от API")

                return text, data

            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    sleep_for = Config.RETRY_BACKOFF_SEC * attempt
                    print(f"  ⚠️ Ошибка вызова API (attempt {attempt}/{retries}): {exc}")
                    print(f"  🔄 Повтор через {sleep_for:.1f}s...")
                    time.sleep(sleep_for)
                else:
                    break

        raise RuntimeError(f"Не удалось вызвать prompt_id={prompt_id}: {last_error}")

    def _extract_text(self, data: Dict[str, Any]) -> str:
        # 1. Частый формат Yandex Responses
        content = data.get("content")
        if isinstance(content, list):
            text = self._collect_texts(content)
            if text:
                return text

        # 2. Иногда ответ лежит в output
        output = data.get("output")
        if isinstance(output, list):
            text = self._collect_texts(output)
            if text:
                return text
        elif isinstance(output, dict):
            text = self._collect_texts([output])
            if text:
                return text
        elif isinstance(output, str):
            if output.strip():
                return output

        # 3. Иногда top-level text
        if isinstance(data.get("text"), str) and data["text"].strip():
            return data["text"]

        # 4. Иногда output_text
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"]

        # 5. fallback
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _collect_texts(self, items: List[Any]) -> str:
        texts: List[str] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                obj_type = obj.get("type")
                text_val = obj.get("text")

                if isinstance(text_val, str):
                    if obj_type in (None, "output_text", "text"):
                        stripped = text_val.strip()
                        if stripped:
                            texts.append(stripped)

                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        walk(value)

            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(items)

        uniq: List[str] = []
        seen = set()
        for t in texts:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return "\n\n".join(uniq).strip()


# =============================================================================
# DEEP RESEARCH SYSTEM
# =============================================================================

class DeepResearchSystem:
    def __init__(
        self,
        print_agent_outputs: bool = True,
        save_prompts: bool = True,
    ) -> None:
        Config.validate()
        self.print_agent_outputs = print_agent_outputs
        self.save_prompts = save_prompts
        self.client = YandexResponsesClient(
            api_key=Config.API_KEY,
            base_url=Config.BASE_URL,
            project_id=Config.PROJECT_ID,
        )

    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def run(
        self,
        project_description: str,
        tracker_context: str = "",
        source_craft_context: str = "",
        artifact_dir: Optional[str] = None,
        continue_on_agent_error: bool = False,
    ) -> Dict[str, Any]:
        if not project_description.strip():
            raise ValueError("project_description пустой")

        project_name = first_non_empty_line(project_description)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        artifact_path = Path(artifact_dir) if artifact_dir else None

        if artifact_path:
            ensure_dir(artifact_path)
            ensure_dir(artifact_path / "agent_outputs")
            ensure_dir(artifact_path / "agent_prompts")

        state: Dict[str, Any] = {
            "run_id": run_id,
            "started_at": now_iso(),
            "project_name": project_name,
            "project_description": project_description.strip(),
            "tracker_context": tracker_context.strip(),
            "source_craft_context": source_craft_context.strip(),

            "project_analysis": "",
            "research_strategy": "",
            "technical_research": "",
            "architecture": "",
            "roadmap": "",
            "team_plan": "",
            "risk_assessment": "",
            "quality_review": "",
            "final_report": "",
            "executive_summary": "",

            "decision": "UNKNOWN",
            "feasibility_score": None,
            "quality_score": None,
            "completeness_score": None,

            "agent_outputs": {},
            "agent_runs": [],
        }

        print("\n" + "=" * 100)
        print("🚀 DEEP RESEARCH SYSTEM START")
        print("=" * 100)
        print(f"Project: {project_name}")
        print(f"Tracker context: {'YES' if tracker_context.strip() else 'NO'}")
        print(f"Source Craft context: {'YES' if source_craft_context.strip() else 'NO'}")
        print(f"Artifacts dir: {artifact_path if artifact_path else 'not set'}")
        print("=" * 100 + "\n")

        pipeline = [
            ("project_analyst", self.build_project_analyst_prompt, "project_analysis"),
            ("research_strategist", self.build_research_strategist_prompt, "research_strategy"),
            ("technical_researcher", self.build_technical_researcher_prompt, "technical_research"),
            ("architect", self.build_architect_prompt, "architecture"),
            ("roadmap_manager", self.build_roadmap_prompt, "roadmap"),
            ("hr_specialist", self.build_hr_prompt, "team_plan"),
            ("risk_analyst", self.build_risk_prompt, "risk_assessment"),
            ("quality_reviewer", self.build_quality_prompt, "quality_review"),
            ("synthesis_manager", self.build_synthesis_prompt, "final_report"),
        ]

        for agent_name, prompt_builder, state_key in pipeline:
            try:
                output = self._run_agent(
                    agent_name=agent_name,
                    prompt_text=prompt_builder(state),
                    state=state,
                    artifact_path=artifact_path,
                )
                state[state_key] = output

                if agent_name == "risk_analyst":
                    state["decision"] = extract_decision(output)
                    state["feasibility_score"] = extract_score(
                        output,
                        labels=[
                            "ИТОГОВАЯ FEASIBILITY",
                            "ИТОГОВАЯ ОЦЕНКА FEASIBILITY",
                            "FEASIBILITY",
                            "ИТОГОВАЯ ОЦЕНКА",
                        ],
                    )

                if agent_name == "quality_reviewer":
                    state["quality_score"] = extract_score(
                        output,
                        labels=["Оценка качества", "Качество", "Quality"],
                    )
                    state["completeness_score"] = extract_score(
                        output,
                        labels=["Оценка полноты", "Полнота", "Completeness"],
                    )

                if agent_name == "synthesis_manager":
                    state["executive_summary"] = extract_executive_summary(output)
                    if state["decision"] == "UNKNOWN":
                        state["decision"] = extract_decision(output)

            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                print(f"\n❌ Agent failed: {agent_name} -> {err}\n")

                if not continue_on_agent_error:
                    raise

                fallback_output = (
                    f"# {agent_name}\n\n"
                    f"Ошибка выполнения агента.\n\n"
                    f"```\n{err}\n```"
                )
                state[state_key] = fallback_output
                state["agent_outputs"][agent_name] = fallback_output

        state["finished_at"] = now_iso()
        state["duration_sec"] = self._duration_seconds(state["started_at"], state["finished_at"])

        result: Dict[str, Any] = {
            "run_id": state["run_id"],
            "project_name": state["project_name"],
            "project_description": state["project_description"],
            "tracker_context": state["tracker_context"],
            "source_craft_context": state["source_craft_context"],

            "started_at": state["started_at"],
            "finished_at": state["finished_at"],
            "duration_sec": state["duration_sec"],

            "decision": state["decision"],
            "feasibility_score": state["feasibility_score"],
            "quality_score": state["quality_score"],
            "completeness_score": state["completeness_score"],

            "project_analysis": state["project_analysis"],
            "research_strategy": state["research_strategy"],
            "technical_research": state["technical_research"],
            "architecture": state["architecture"],
            "roadmap": state["roadmap"],
            "team_plan": state["team_plan"],
            "risk_assessment": state["risk_assessment"],
            "quality_review": state["quality_review"],
            "final_report": state["final_report"],
            "executive_summary": state["executive_summary"],

            "agent_outputs": state["agent_outputs"],
            "agent_runs": state["agent_runs"],
        }

        if artifact_path:
            self.save_artifacts(result, artifact_path)

        print("\n" + "=" * 100)
        print("✅ DEEP RESEARCH FINISHED")
        print("=" * 100)
        print(f"Decision: {result['decision']}")
        print(f"Feasibility: {result['feasibility_score']}")
        print(f"Quality: {result['quality_score']}")
        print(f"Completeness: {result['completeness_score']}")
        print(f"Duration: {result['duration_sec']:.1f}s")
        print("=" * 100 + "\n")

        return result

    def print_agent_outputs(self, result: Dict[str, Any]) -> None:
        for agent_name in Config.AGENT_ORDER:
            output = result.get("agent_outputs", {}).get(agent_name, "")
            title = Config.AGENT_TITLES.get(agent_name, agent_name)
            print_block(f"🤖 {title}", output)

    def save_artifacts(self, result: Dict[str, Any], artifact_dir: Path | str) -> None:
        artifact_dir = Path(artifact_dir)
        ensure_dir(artifact_dir)
        ensure_dir(artifact_dir / "agent_outputs")

        safe_write(artifact_dir / "final_report.md", result.get("final_report", ""))
        safe_write(artifact_dir / "executive_summary.md", result.get("executive_summary", ""))

        for idx, agent_name in enumerate(Config.AGENT_ORDER, start=1):
            content = result.get("agent_outputs", {}).get(agent_name, "")
            safe_write(
                artifact_dir / "agent_outputs" / f"{idx:02d}_{agent_name}.md",
                content,
            )

        safe_write(
            artifact_dir / "result.json",
            json.dumps(result, ensure_ascii=False, indent=2),
        )

    # -------------------------------------------------------------------------
    # INTERNALS
    # -------------------------------------------------------------------------

    def _run_agent(
        self,
        agent_name: str,
        prompt_text: str,
        state: Dict[str, Any],
        artifact_path: Optional[Path],
    ) -> str:
        cfg = Config.AGENTS[agent_name]
        prompt_id = os.getenv(cfg.env_var, "").strip()

        idx = len(state["agent_runs"]) + 1
        title = Config.AGENT_TITLES.get(agent_name, agent_name)
        started = now_iso()

        print(f"\n--- [{idx}/{len(Config.AGENT_ORDER)}] {title} ---")
        print(f"Prompt ID: {prompt_id}")
        print(f"Timeout: {cfg.timeout_sec}s")

        output_text = ""
        response_data: Dict[str, Any] = {}
        success = False
        error_text: Optional[str] = None

        try:
            output_text, response_data = self.client.call(
                prompt_id=prompt_id,
                input_text=prompt_text,
                timeout_sec=cfg.timeout_sec,
                retries=cfg.retries,
            )
            success = True
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            finished = now_iso()
            duration = self._duration_seconds(started, finished)

            run = AgentRun(
                index=idx,
                agent_name=agent_name,
                prompt_id=prompt_id,
                started_at=started,
                finished_at=finished,
                duration_sec=duration,
                input_text=prompt_text,
                output_text=output_text,
                success=success,
                response_id=response_data.get("id") if isinstance(response_data, dict) else None,
                response_status=response_data.get("status") if isinstance(response_data, dict) else None,
                usage=response_data.get("usage") if isinstance(response_data, dict) else None,
                error=error_text,
            )
            state["agent_runs"].append(asdict(run))

            if success:
                state["agent_outputs"][agent_name] = output_text

                if self.print_agent_outputs:
                    print_block(f"🤖 {title}", output_text)

                if artifact_path:
                    if self.save_prompts:
                        safe_write(
                            artifact_path / "agent_prompts" / f"{idx:02d}_{agent_name}_prompt.md",
                            prompt_text,
                        )
                    safe_write(
                        artifact_path / "agent_outputs" / f"{idx:02d}_{agent_name}.md",
                        output_text,
                    )

        return output_text

    def _duration_seconds(self, start_iso: str, end_iso: str) -> float:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return (end - start).total_seconds()

    # -------------------------------------------------------------------------
    # MCP CONTEXT
    # -------------------------------------------------------------------------

    def build_mcp_context(self, state: Dict[str, Any]) -> str:
        tracker_context = state.get("tracker_context", "").strip()
        source_craft_context = state.get("source_craft_context", "").strip()

        blocks = []

        if tracker_context:
            blocks.append(
                "### Yandex Tracker context\n"
                "Если у тебя реально подключён MCP Yandex Tracker и хватает контекста — используй его.\n"
                "Если доступа недостаточно, НЕ выдумывай данные и явно напиши, что анализ выполнен по входному описанию.\n\n"
                f"{tracker_context}"
            )

        if source_craft_context:
            blocks.append(
                "### Source Craft context\n"
                "Если у тебя реально подключён MCP Source Craft и хватает контекста — используй его для анализа кода/структуры.\n"
                "Если доступа недостаточно, НЕ выдумывай детали кода и явно напиши это.\n\n"
                f"{source_craft_context}"
            )

        if not blocks:
            return "MCP-контекст не предоставлен. Работай по описанию проекта."

        return "\n\n".join(blocks)

    # -------------------------------------------------------------------------
    # PROMPT BUILDERS
    # -------------------------------------------------------------------------

    def build_project_analyst_prompt(self, state: Dict[str, Any]) -> str:
        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: сделать стартовый продуктовый анализ ПРИНЯТОГО проекта и подготовить основу для планирования разработки.

Важно:
- проект уже принят;
- не спорь с самим фактом проекта;
- фокус на том, ЧТО и КАК нужно разрабатывать дальше;
- если есть MCP и достаточно данных — используй;
- если данных нет — не придумывай.

## Входное описание проекта
{state["project_description"]}

## Контекст MCP
{self.build_mcp_context(state)}

Нужно подготовить структурированный ответ в Markdown со следующими разделами:

## Суть проекта
Кратко: что это за продукт, для кого, какую проблему решает.

## Бизнес-цели
Только измеримые или максимально конкретные цели.

## Целевая аудитория
Сегменты пользователей и их задачи.

## Требования к разработке

### Функциональные требования
Список конкретных функций, которые нужно реализовать или развить.

### Нефункциональные требования
Производительность, масштабируемость, безопасность, надёжность, observability, совместимость и т.д.
Пиши измеримо.

### Бизнес-требования
Метрики успеха, go-to-market, ограничения запуска, требования к adoption и т.д.

## Приоритетные направления развития
Нумерованный список направлений с кратким обоснованием и приоритетом.

## Ограничения
Технические, бизнесовые, юридические, инфраструктурные, ресурсные.

## Анализ Tracker/SourceCraft
Если использовал MCP — кратко что именно это дало.
Если не использовал — явно напиши это.

## Ключевые вопросы для исследования
Что обязательно нужно изучить до передачи в разработку.

Требования к ответу:
- максимум конкретики;
- без воды;
- требования должны быть пригодны для следующих агентов.
""".strip()

    def build_research_strategist_prompt(self, state: Dict[str, Any]) -> str:
        analysis = compact_text(state.get("project_analysis", ""), 5000)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: на основе стартового анализа построить СТРАТЕГИЮ развития проекта и гипотезы, которые дальше проверит исследование.

Важно:
- проект уже принят;
- гипотезы должны быть про РАЗВИТИЕ продукта и разработку;
- каждая гипотеза должна быть проверяемой и измеримой;
- используй интернет-поиск, если он у тебя подключён.

## Анализ проекта
{analysis}

Подготовь Markdown-ответ со структурой:

## Стратегические гипотезы

### Функциональное развитие
Для каждой гипотезы:
- Гипотеза
- Обоснование
- Как проверим
- Приоритет
- Риски

### Технологическое развитие
Аналогично.

### Масштабирование
Аналогично.

### При необходимости: монетизация / adoption / distribution
Только если релевантно проекту.

## План исследования
Для 5-8 исследовательских направлений:
- что изучаем;
- зачем;
- какие гипотезы покрываем;
- какие источники использовать;
- ожидаемый результат;
- приоритет 1-5.

## Краткий конкурентный анализ
2-5 релевантных аналогов/конкурентов:
- что у них хорошо;
- чему стоит научиться;
- где у проекта шанс быть лучше.

## Критерии успеха исследования
Что обязательно должно быть раскрыто, чтобы можно было передать план в разработку.

Требования:
- конкретные гипотезы, не общие слова;
- метрики в гипотезах;
- приоритеты должны быть обоснованы.
""".strip()

    def build_technical_researcher_prompt(self, state: Dict[str, Any]) -> str:
        analysis = compact_text(state.get("project_analysis", ""), 3000)
        strategy = compact_text(state.get("research_strategy", ""), 4000)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: подобрать КОНКРЕТНЫЕ технологии, практики и технические решения для реализации проекта.

Важно:
- ориентируйся на production-ready решения;
- используй свежую информацию;
- активно используй интернет-поиск, если он подключён;
- кратко, без воды;
- нужны реальные рекомендации для архитектуры и разработки.

## Анализ проекта
{analysis}

## Стратегия и гипотезы
{strategy}

Подготовь Markdown-ответ:

## Технологии для реализации

### Backend
Для каждой рекомендации:
- технология + версия;
- для каких задач подходит;
- плюсы;
- минусы;
- источник.

### Frontend
Аналогично.

### Databases / Storage
Аналогично.

### Infrastructure / DevOps
Аналогично.

### Security / Auth / Observability
Аналогично.

## Best Practices
5-10 практик, важных именно для такого проекта.

## Case Studies
2-5 коротких кейсов:
- кто решал похожую задачу;
- каким стеком;
- чему это учит нас.

## Проверка гипотез
Список гипотез с пометкой:
- подтверждена;
- опровергнута;
- требует уточнения;
и краткими аргументами.

## Технические риски
Краткий список ключевых рисков и способов митигации.

## Краткое резюме
Главные технические выводы, которые надо использовать в архитектуре.

Требования:
- технологии с версиями;
- ссылки или названия источников;
- минимум общих слов;
- ориентир на 2023-2025 production практики.
""".strip()

    def build_architect_prompt(self, state: Dict[str, Any]) -> str:
        analysis = compact_text(state.get("project_analysis", ""), 2500)
        tech = compact_text(state.get("technical_research", ""), 5000)
        strategy = compact_text(state.get("research_strategy", ""), 2500)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: спроектировать целевую архитектуру продукта и детальный tech stack для команды разработки.

Важно:
- проект уже принят;
- решения должны быть реализуемыми;
- все ключевые компоненты должны быть описаны;
- технологии указывай конкретно, с версиями;
- для каждого выбора давай короткое обоснование и альтернативы.

## Проект
{state["project_description"]}

## Стартовый анализ
{analysis}

## Стратегия развития
{strategy}

## Техническое исследование
{tech}

## Контекст MCP
{self.build_mcp_context(state)}

Подготовь Markdown-ответ со структурой:

## Архитектурный стиль
- выбор;
- обоснование;
- trade-offs.

## Высокоуровневая архитектура
Текстовая диаграмма или структурное описание компонентов и связей.

## Компоненты системы
Для каждого ключевого компонента:
- название;
- назначение;
- технология;
- интерфейсы;
- почему выбран;
- альтернативы.

## Технологический стек
Разделы:
- Backend
- Frontend
- Databases
- Infrastructure
- CI/CD
- Security
- Observability

Для каждого:
- технология + версия;
- роль в системе;
- обоснование;
- альтернативы.

## Data Model
Ключевые сущности и связи.

## Data Flow
Основные пользовательские и системные потоки.

## Масштабируемость
- scaling strategy;
- caching;
- bottlenecks;
- performance targets.

## Безопасность
- authentication / authorization;
- data protection;
- network/security controls.

## Deployment Architecture
- dev / staging / production;
- deployment strategy;
- rollback / release strategy.

## Cost Estimation
Кратко:
- development/staging/prod;
- MVP vs scale.

Требования:
- никакой абстракции;
- всё должно быть пригодно для немедленного перехода к roadmap.
""".strip()

    def build_roadmap_prompt(self, state: Dict[str, Any]) -> str:
        analysis = compact_text(state.get("project_analysis", ""), 2000)
        architecture = compact_text(state.get("architecture", ""), 6000)
        tech = compact_text(state.get("technical_research", ""), 2500)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: построить РЕАЛЬНЫЙ roadmap разработки.

Критически важно:
- учитывай modern development with LLM;
- типичные классические оценки нужно сокращать в 2-4 раза там, где это действительно разумно;
- то, что раньше оценивали в неделю, сегодня часто делается за 1-3 дня;
- но НЕ занижай discovery, интеграцию, сложную отладку, внешние зависимости и прод-инфраструктуру;
- задачи давай в человеко-днях; крупные фазы можно в днях/неделях.

## Проект
{state["project_description"]}

## Базовый анализ
{analysis}

## Техническое исследование
{tech}

## Архитектура
{architecture}

Подготовь Markdown-ответ:

## Overview
- общая длительность;
- число фаз;
- число milestones;
- рекомендуемая методология;
- длительность спринта (если нужен).

## Фазы разработки
Для каждой фазы:

### Фаза X: [название] ([длительность])
**Цели**
**Deliverables**
**Критерии завершения**
**Задачи**:
- конкретная задача;
- исполнитель/роль;
- оценка в днях;
- зависимости, если есть.

Важно:
- фазы должны вести к реальным инкрементам продукта;
- MVP должен быть выделен явно.

## Milestones
Для каждого milestone:
- дата/день/неделя;
- что должно быть готово;
- какие метрики/критерии успеха.

## Timeline
Сжатое календарное представление по дням/неделям.

## Зависимости
- критический путь;
- блокирующие зависимости;
- параллельные треки.

## Ресурсы
Какая команда нужна по фазам.

## Оценки длительности
- оптимистичная;
- реалистичная;
- пессимистичная.

## Риски roadmap
Основные риски выполнения и буферы.

## Yandex Tracker Structure
Если релевантно — предложи структуру эпиков, stories и задач.

Требования:
- никакого 'сделать backend' без расшифровки;
- сроки реалистичны для команды с LLM-поддержкой;
- короткие задачи — в днях, не в неделях.
""".strip()

    def build_hr_prompt(self, state: Dict[str, Any]) -> str:
        architecture = compact_text(state.get("architecture", ""), 4000)
        roadmap = compact_text(state.get("roadmap", ""), 6000)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: определить команду, которая сможет реализовать проект по roadmap.

Важно:
- команда должна быть достаточной, но не раздутой;
- требования к ролям должны опираться на реальный tech stack;
- оценивай роли, приоритет найма, онбординг, модель найма и стоимость.

## Архитектура
{architecture}

## Roadmap
{roadmap}

Подготовь Markdown-ответ:

## Структура команды
- роли;
- иерархия / взаимодействие;
- итоговый размер команды;
- ориентировочная стоимость в месяц и в год.

## Роли и требования
Для каждой роли:
- название;
- количество;
- seniority;
- full-time / contract / part-time;
- обязанности;
- hard skills;
- nice-to-have skills;
- soft skills;
- зарплатный диапазон;
- когда нанимать;
- приоритет найма.

## Потребности по фазам
Какие роли критичны на каких этапах roadmap.

## Стратегия найма
- wave 1 / wave 2 / wave 3;
- кого брать full-time;
- кого можно на контракт;
- где допустим offshore/nearshore.

## Стоимость команды
Таблица по ролям:
- salary;
- benefits/overhead;
- total.

## План онбординга
- pre-start;
- week 1;
- week 2-4;
- необходимая документация.

## Риски команды
Ключевые риски найма/удержания/зависимости от людей.

Требования:
- используй конкретные технологии из архитектуры;
- цифры должны быть реалистичными;
- ответ должен быть пригоден для запуска hiring.
""".strip()

    def build_risk_prompt(self, state: Dict[str, Any]) -> str:
        architecture = compact_text(state.get("architecture", ""), 3500)
        roadmap = compact_text(state.get("roadmap", ""), 4500)
        team_plan = compact_text(state.get("team_plan", ""), 3500)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: провести risk assessment уже спланированного проекта.

Важно:
- не анализируй, нужен ли проект миру в общем;
- оценивай, насколько РЕАЛЬНО выполним предложенный план;
- для каждого риска нужна конкретная митигация;
- итог должен помочь принять решение GO / NO-GO / GO WITH CONDITIONS.

## Проект
{state["project_description"]}

## Архитектура
{architecture}

## Roadmap
{roadmap}

## Команда
{team_plan}

Подготовь Markdown-ответ:

## Риски проекта

### Технические риски
Для каждого:
- название;
- вероятность (%);
- impact;
- описание;
- митигация;
- contingency plan.

### Организационные риски
Аналогично.

### Бизнес-риски
Аналогично.

### Внешние риски
Аналогично.

## Оценка Feasibility
Отдельно:
- техническая;
- организационная;
- финансовая;
- рыночная;
- итоговая feasibility.

Для каждой оценки:
- score /100;
- краткое обоснование.

## Оценка стоимости
- команда;
- инфраструктура;
- прочие расходы;
- суммарно Year 1;
- примерно Year 2+.

## Time to Market
- MVP;
- PMF / next release;
- scale-ready stage.

## ИТОГОВАЯ РЕКОМЕНДАЦИЯ
Один из вариантов:
- GO
- NO-GO
- GO WITH CONDITIONS

И далее:
- pros;
- cons;
- must-have conditions;
- should-have conditions;
- red flags for stop;
- следующие шаги.

Требования:
- конкретные риски и конкретные митигации;
- итоговая рекомендация обязательна;
- оценки должны быть честными.
""".strip()

    def build_quality_prompt(self, state: Dict[str, Any]) -> str:
        analysis = compact_text(state.get("project_analysis", ""), 1800)
        strategy = compact_text(state.get("research_strategy", ""), 1800)
        tech = compact_text(state.get("technical_research", ""), 2200)
        architecture = compact_text(state.get("architecture", ""), 2200)
        roadmap = compact_text(state.get("roadmap", ""), 2200)
        team_plan = compact_text(state.get("team_plan", ""), 1800)
        risk = compact_text(state.get("risk_assessment", ""), 2200)

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: проверить, хватает ли уже собранного research для передачи проекта в разработку.

Важно:
- будь критичен, но не тормози проект без причины;
- ищи именно пробелы, мешающие старту;
- если всё достаточно — так и скажи;
- если не хватает — укажи ЧТО именно.

## Анализ проекта
{analysis}

## Стратегия
{strategy}

## Техническое исследование
{tech}

## Архитектура
{architecture}

## Roadmap
{roadmap}

## Команда
{team_plan}

## Риски
{risk}

Подготовь Markdown-ответ:

## Оценка полноты: X/100
- что покрыто хорошо;
- что покрыто недостаточно.

## Оценка качества: Y/100
- сильные стороны;
- слабые стороны.

## Проверка согласованности
- roadmap ↔ architecture;
- roadmap ↔ team;
- risks ↔ roadmap;
- budget ↔ scope.

## Найденные пробелы
### Критичные
### Некритичные

## Решение о дополнительном research
- нужно / не нужно;
- почему;
- если нужно — что ещё исследовать.

## Готовность к разработке
- можно начинать / нельзя / можно с оговорками;
- какие оговорки.

## Quality Gates
- пройденные;
- проваленные.

## Итоговые рекомендации
Короткий actionable список.

Требования:
- конкретно;
- оцени именно пригодность research как handoff package для команды разработки.
""".strip()

    def build_synthesis_prompt(self, state: Dict[str, Any]) -> str:
        analysis = compact_text(state.get("project_analysis", ""), 2500)
        strategy = compact_text(state.get("research_strategy", ""), 2500)
        tech = compact_text(state.get("technical_research", ""), 3000)
        architecture = compact_text(state.get("architecture", ""), 4500)
        roadmap = compact_text(state.get("roadmap", ""), 5000)
        team_plan = compact_text(state.get("team_plan", ""), 3500)
        risk = compact_text(state.get("risk_assessment", ""), 3500)
        quality = compact_text(state.get("quality_review", ""), 2500)

        feasibility_score = state.get("feasibility_score")
        quality_score = state.get("quality_score")
        completeness_score = state.get("completeness_score")
        decision = state.get("decision", "UNKNOWN")

        return f"""
Ты работаешь в мультиагентной Deep Research системе.

Задача: собрать весь research в один ФИНАЛЬНЫЙ, ИСЧЕРПЫВАЮЩИЙ, ACTIONABLE документ для передачи команде разработки и руководству.

Важно:
- не используй шаблонные заглушки вроде "информация не предоставлена", если её можно вывести из материалов;
- если информации действительно нет — коротко укажи gap и сразу предложи решение;
- документ должен быть полезен как реальный handoff package;
- executive summary должно быть коротким, но содержательным;
- весь отчёт — без воды.

## Входные материалы

### Project analysis
{analysis}

### Strategy
{strategy}

### Technical research
{tech}

### Architecture
{architecture}

### Roadmap
{roadmap}

### Team plan
{team_plan}

### Risk assessment
{risk}

### Quality review
{quality}

### Known scores
- Decision: {decision}
- Feasibility: {feasibility_score}
- Quality: {quality_score}
- Completeness: {completeness_score}

Нужно вернуть Markdown-документ со строгой структурой:

# Deep Research Report: [название проекта]

## Executive Summary
Кратко:
- что за проект;
- что рекомендуем;
- ключевые метрики;
- сроки;
- команда;
- top risks;
- next 30 days.

## 1. Обзор проекта
- описание;
- бизнес-цели;
- аудитория;
- ценностное предложение.

## 2. Методология
- как проводился research;
- гипотезы;
- что было исследовано.

## 3. Требования
- функциональные;
- нефункциональные;
- бизнес-требования;
- ограничения.

## 4. Архитектура
- стиль;
- high-level architecture;
- компоненты;
- data model;
- data flow;
- scaling;
- security;
- observability.

## 5. Технологический стек
Сделай структурированно и конкретно, лучше в таблицах:
- backend;
- frontend;
- storage;
- infra;
- CI/CD;
- security;
- monitoring.

## 6. Roadmap
- overview;
- фазы;
- задачи;
- milestones;
- timeline;
- зависимости;
- оценки сроков.

## 7. Команда
- структура;
- роли;
- hiring priority;
- стоимость;
- onboarding.

## 8. Риски
- технические;
- организационные;
- бизнес;
- внешние;
- top critical risks.

## 9. Оценки
- feasibility;
- сроки;
- стоимость;
- качество research.

## 10. Рекомендации
- итоговое решение;
- обоснование;
- условия для GO;
- next 90 days;
- success metrics;
- decision gates.

## 11. Приложения
- полный tech stack;
- детальный roadmap;
- job descriptions summary;
- полный список рисков.

Требования:
- не теряй конкретику;
- используешь реальные выводы предыдущих агентов;
- не пиши пустых разделов;
- если есть пробел, заполни его рабочей рекомендацией, а не просто констатацией отсутствия.
""".strip()


# =============================================================================
# ASYNC DEEP RESEARCH SYSTEM
# =============================================================================

class AsyncDeepResearchSystem:
    """Native async version of deep research runner."""

    def __init__(self, print_agent_outputs: bool = True, save_prompts: bool = True) -> None:
        Config.validate()
        self.print_agent_outputs = print_agent_outputs
        self.save_prompts = save_prompts
        self.client = AsyncYandexResponsesClient()
        # Reuse prompt builders and extract helpers from original implementation.
        self._sync = DeepResearchSystem(print_agent_outputs=print_agent_outputs, save_prompts=save_prompts)

    async def run(
        self,
        project_description: str,
        tracker_context: str = "",
        source_craft_context: str = "",
        artifact_dir: Optional[str] = None,
        continue_on_agent_error: bool = False,
    ) -> Dict[str, Any]:
        if not project_description.strip():
            raise ValueError("project_description пустой")

        project_name = first_non_empty_line(project_description)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        artifact_path = Path(artifact_dir) if artifact_dir else None
        if artifact_path:
            ensure_dir(artifact_path)
            ensure_dir(artifact_path / "agent_outputs")
            ensure_dir(artifact_path / "agent_prompts")

        state: Dict[str, Any] = {
            "run_id": run_id,
            "started_at": now_iso(),
            "project_name": project_name,
            "project_description": project_description.strip(),
            "tracker_context": tracker_context.strip(),
            "source_craft_context": source_craft_context.strip(),
            "project_analysis": "",
            "research_strategy": "",
            "technical_research": "",
            "architecture": "",
            "roadmap": "",
            "team_plan": "",
            "risk_assessment": "",
            "quality_review": "",
            "final_report": "",
            "executive_summary": "",
            "decision": "UNKNOWN",
            "feasibility_score": None,
            "quality_score": None,
            "completeness_score": None,
            "agent_outputs": {},
            "agent_runs": [],
        }

        pipeline = [
            ("project_analyst", self._sync.build_project_analyst_prompt, "project_analysis"),
            ("research_strategist", self._sync.build_research_strategist_prompt, "research_strategy"),
            ("technical_researcher", self._sync.build_technical_researcher_prompt, "technical_research"),
            ("architect", self._sync.build_architect_prompt, "architecture"),
            ("roadmap_manager", self._sync.build_roadmap_prompt, "roadmap"),
            ("hr_specialist", self._sync.build_hr_prompt, "team_plan"),
            ("risk_analyst", self._sync.build_risk_prompt, "risk_assessment"),
            ("quality_reviewer", self._sync.build_quality_prompt, "quality_review"),
            ("synthesis_manager", self._sync.build_synthesis_prompt, "final_report"),
        ]

        for agent_name, prompt_builder, state_key in pipeline:
            try:
                output = await self._run_agent(agent_name, prompt_builder(state), state, artifact_path)
                state[state_key] = output
                if agent_name == "risk_analyst":
                    state["decision"] = extract_decision(output)
                    state["feasibility_score"] = extract_score(output, ["ИТОГОВАЯ FEASIBILITY", "FEASIBILITY", "ИТОГОВАЯ ОЦЕНКА"])
                if agent_name == "quality_reviewer":
                    state["quality_score"] = extract_score(output, ["Оценка качества", "Качество", "Quality"])
                    state["completeness_score"] = extract_score(output, ["Оценка полноты", "Полнота", "Completeness"])
                if agent_name == "synthesis_manager":
                    state["executive_summary"] = extract_executive_summary(output)
                    if state["decision"] == "UNKNOWN":
                        state["decision"] = extract_decision(output)
            except Exception as exc:
                if not continue_on_agent_error:
                    raise
                fallback_output = f"# {agent_name}\n\nОшибка выполнения агента.\n\n```\n{type(exc).__name__}: {exc}\n```"
                state[state_key] = fallback_output
                state["agent_outputs"][agent_name] = fallback_output

        state["finished_at"] = now_iso()
        state["duration_sec"] = self._sync._duration_seconds(state["started_at"], state["finished_at"])  # noqa: SLF001
        result: Dict[str, Any] = {
            "run_id": state["run_id"],
            "project_name": state["project_name"],
            "project_description": state["project_description"],
            "tracker_context": state["tracker_context"],
            "source_craft_context": state["source_craft_context"],
            "started_at": state["started_at"],
            "finished_at": state["finished_at"],
            "duration_sec": state["duration_sec"],
            "decision": state["decision"],
            "feasibility_score": state["feasibility_score"],
            "quality_score": state["quality_score"],
            "completeness_score": state["completeness_score"],
            "project_analysis": state["project_analysis"],
            "research_strategy": state["research_strategy"],
            "technical_research": state["technical_research"],
            "architecture": state["architecture"],
            "roadmap": state["roadmap"],
            "team_plan": state["team_plan"],
            "risk_assessment": state["risk_assessment"],
            "quality_review": state["quality_review"],
            "final_report": state["final_report"],
            "executive_summary": state["executive_summary"],
            "agent_outputs": state["agent_outputs"],
            "agent_runs": state["agent_runs"],
        }
        if artifact_path:
            self._sync.save_artifacts(result, artifact_path)
        return result

    async def _run_agent(
        self,
        agent_name: str,
        prompt_text: str,
        state: Dict[str, Any],
        artifact_path: Optional[Path],
    ) -> str:
        cfg = Config.AGENTS[agent_name]
        prompt_id = os.getenv(cfg.env_var, "").strip()
        started = now_iso()
        output_text, response_data = await self.client.async_call(
            prompt_id=prompt_id,
            input_text=prompt_text,
            timeout_sec=cfg.timeout_sec,
            retries=cfg.retries,
        )
        finished = now_iso()
        duration = self._sync._duration_seconds(started, finished)  # noqa: SLF001
        run = AgentRun(
            index=len(state["agent_runs"]) + 1,
            agent_name=agent_name,
            prompt_id=prompt_id,
            started_at=started,
            finished_at=finished,
            duration_sec=duration,
            input_text=prompt_text,
            output_text=output_text,
            success=True,
            response_id=response_data.get("id") if isinstance(response_data, dict) else None,
            response_status=response_data.get("status") if isinstance(response_data, dict) else None,
            usage=response_data.get("usage") if isinstance(response_data, dict) else None,
        )
        state["agent_runs"].append(asdict(run))
        state["agent_outputs"][agent_name] = output_text
        if artifact_path:
            stage_idx = len(state["agent_runs"])
            if self.save_prompts:
                safe_write(artifact_path / "agent_prompts" / f"{stage_idx:02d}_{agent_name}_prompt.md", prompt_text)
            safe_write(artifact_path / "agent_outputs" / f"{stage_idx:02d}_{agent_name}.md", output_text)
        return output_text


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def run_deep_research(
    project_description: str,
    tracker_context: str = "",
    source_craft_context: str = "",
    artifact_dir: Optional[str] = None,
    print_agent_outputs: bool = True,
    continue_on_agent_error: bool = False,
) -> Dict[str, Any]:
    system = DeepResearchSystem(
        print_agent_outputs=print_agent_outputs,
        save_prompts=Config.SAVE_FULL_PROMPTS,
    )
    return system.run(
        project_description=project_description,
        tracker_context=tracker_context,
        source_craft_context=source_craft_context,
        artifact_dir=artifact_dir,
        continue_on_agent_error=continue_on_agent_error,
    )


async def run_deep_research_async(
    project_description: str,
    tracker_context: str = "",
    source_craft_context: str = "",
    artifact_dir: Optional[str] = None,
    print_agent_outputs: bool = True,
    continue_on_agent_error: bool = False,
) -> Dict[str, Any]:
    system = AsyncDeepResearchSystem(
        print_agent_outputs=print_agent_outputs,
        save_prompts=Config.SAVE_FULL_PROMPTS,
    )
    return await system.run(
        project_description=project_description,
        tracker_context=tracker_context,
        source_craft_context=source_craft_context,
        artifact_dir=artifact_dir,
        continue_on_agent_error=continue_on_agent_error,
    )


def print_agent_outputs(result: Dict[str, Any]) -> None:
    system = DeepResearchSystem(
        print_agent_outputs=True,
        save_prompts=Config.SAVE_FULL_PROMPTS,
    )
    system.print_agent_outputs(result)


def save_artifacts(result: Dict[str, Any], artifact_dir: str = "deep_research_output") -> None:
    system = DeepResearchSystem(
        print_agent_outputs=False,
        save_prompts=Config.SAVE_FULL_PROMPTS,
    )
    system.save_artifacts(result, artifact_dir)


def print_summary(result: Dict[str, Any]) -> None:
    print("\n" + "=" * 100)
    print("📌 RESEARCH SUMMARY")
    print("=" * 100)
    print(f"Project: {result.get('project_name')}")
    print(f"Decision: {result.get('decision')}")
    print(f"Feasibility: {result.get('feasibility_score')}")
    print(f"Quality: {result.get('quality_score')}")
    print(f"Completeness: {result.get('completeness_score')}")
    print(f"Duration: {result.get('duration_sec'):.1f}s")
    print("=" * 100)
    print("\nExecutive Summary:\n")
    print(result.get("executive_summary", "") or "[EMPTY]")
    print("\n" + "=" * 100 + "\n")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    project = """
HISTOSCAN — комплекс программных продуктов для врачей-патологов, который позволяет
управлять, хранить и обмениваться цифровыми изображениями микроскопических
и макроскопических исследований.

Есть on-premise и облачная версии.
Облачная версия популярнее, более 4700 пользователей, около 250 тысяч изображений.

Нужно провести deep research проекта и подготовить полный пакет для уже спланированной
разработки: стратегия развития, архитектура, roadmap, команда, риски, метрики, этапы.
    """.strip()

    result = run_deep_research(
        project_description=project,
        tracker_context="",
        source_craft_context="",
        artifact_dir="deep_research_output",
        print_agent_outputs=True,
        continue_on_agent_error=False,
    )

    print_summary(result)