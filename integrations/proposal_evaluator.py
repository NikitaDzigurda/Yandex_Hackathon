from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from deep_research import (
    Config,
    YandexResponsesClient,
    ensure_dir,
    extract_score,
    now_iso,
    safe_write,
)

load_dotenv()


@dataclass(frozen=True)
class EvaluatorConfig:
    name: str
    env_var: str
    timeout_sec: int
    retries: int = 3


@dataclass
class EvaluatorRun:
    index: int
    evaluator_name: str
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


class EvalConfig:
    API_KEY = os.getenv("YANDEX_API_KEY", "").strip()
    BASE_URL = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1").rstrip("/")
    PROJECT_ID = os.getenv("YANDEX_PROJECT_ID", "").strip()

    EVALUATORS: Dict[str, EvaluatorConfig] = {
        "technical_analyst": EvaluatorConfig("technical_analyst", "EVAL_TECHNICAL_ANALYST_ID", 180),
        "market_researcher": EvaluatorConfig("market_researcher", "EVAL_MARKET_RESEARCHER_ID", 180),
        "innovator": EvaluatorConfig("innovator", "EVAL_INNOVATOR_ID", 300),
        "risk_assessor": EvaluatorConfig("risk_assessor", "EVAL_RISK_ASSESSOR_ID", 180),
        "moderator": EvaluatorConfig("moderator", "EVAL_MODERATOR_ID", 300),
    }

    ORDER = [
        "technical_analyst",
        "market_researcher",
        "innovator",
        "risk_assessor",
        "moderator",
    ]

    TITLES = {
        "technical_analyst": "TECHNICAL ANALYST",
        "market_researcher": "MARKET RESEARCHER",
        "innovator": "INNOVATOR",
        "risk_assessor": "RISK ASSESSOR",
        "moderator": "MODERATOR",
    }

    @classmethod
    def validate(cls) -> None:
        if not cls.API_KEY:
            raise ValueError("YANDEX_API_KEY не установлен")
        if not cls.PROJECT_ID:
            raise ValueError("YANDEX_PROJECT_ID не установлен")

        missing: List[str] = []
        for name, cfg in cls.EVALUATORS.items():
            if not os.getenv(cfg.env_var, "").strip():
                missing.append(f"{name} ({cfg.env_var})")

        if missing:
            raise ValueError("Не заданы prompt id для evaluator-агентов:\n- " + "\n- ".join(missing))


def extract_verdict(text: str) -> str:
    upper = (text or "").upper()
    if "REJECT" in upper or "ОТКЛОНИТ" in upper or "ОТКАЗ" in upper:
        return "REJECT"
    if "APPROVE" in upper or "УТВЕРДИТ" in upper or "УТВЕРЖД" in upper:
        return "APPROVE"
    return "UNDECIDED"


class ProposalEvaluationSystem:
    def __init__(self, save_prompts: bool = True) -> None:
        EvalConfig.validate()
        self.save_prompts = save_prompts
        self.client = YandexResponsesClient(
            api_key=EvalConfig.API_KEY,
            base_url=EvalConfig.BASE_URL,
            project_id=EvalConfig.PROJECT_ID,
        )

    def run(
        self,
        proposal_text: str,
        evaluation_prompt: str = "",
        tracker_context: str = "",
        source_craft_context: str = "",
        artifact_dir: Optional[str] = None,
        continue_on_agent_error: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        if not proposal_text.strip():
            raise ValueError("proposal_text пустой")

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        artifact_path = Path(artifact_dir) if artifact_dir else None
        if artifact_path:
            ensure_dir(artifact_path)
            ensure_dir(artifact_path / "agent_outputs")
            ensure_dir(artifact_path / "agent_prompts")

        state: Dict[str, Any] = {
            "run_id": run_id,
            "started_at": now_iso(),
            "proposal_text": proposal_text.strip(),
            "evaluation_prompt": evaluation_prompt.strip(),
            "tracker_context": tracker_context.strip(),
            "source_craft_context": source_craft_context.strip(),
            "technical_analyst_output": "",
            "market_researcher_output": "",
            "innovator_output": "",
            "risk_assessor_output": "",
            "moderator_output": "",
            "verdict": "UNDECIDED",
            "confidence": None,
            "agent_outputs": {},
            "agent_runs": [],
        }

        def emit(status: str, current_agent: Optional[str] = None) -> None:
            if not progress_callback:
                return
            progress_callback(
                {
                    "run_id": state["run_id"],
                    "status": status,
                    "current_agent": current_agent,
                    "completed_agents": len(state["agent_outputs"]),
                    "total_agents": len(EvalConfig.ORDER),
                    "started_at": state["started_at"],
                }
            )

        emit("running")

        parallel_stage = [
            ("technical_analyst", self._build_common_prompt(state, "technical_analyst"), "technical_analyst_output"),
            ("market_researcher", self._build_common_prompt(state, "market_researcher"), "market_researcher_output"),
            ("innovator", self._build_common_prompt(state, "innovator"), "innovator_output"),
            ("risk_assessor", self._build_common_prompt(state, "risk_assessor"), "risk_assessor_output"),
        ]

        state_key_by_agent = {agent_name: state_key for agent_name, _, state_key in parallel_stage}
        lock = Lock()
        emit("running_parallel_evaluators")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._run_agent, agent_name, prompt_text, artifact_path): agent_name
                for agent_name, prompt_text, _ in parallel_stage
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                emit("running_parallel_evaluators", current_agent=agent_name)
                try:
                    output, run_data = future.result()
                    with lock:
                        state[state_key_by_agent[agent_name]] = output
                        state["agent_outputs"][agent_name] = output
                        state["agent_runs"].append(run_data)
                except Exception as exc:
                    if not continue_on_agent_error:
                        raise
                    fallback = f"# {agent_name}\n\nОшибка выполнения.\n\n```\n{type(exc).__name__}: {exc}\n```"
                    with lock:
                        state[state_key_by_agent[agent_name]] = fallback
                        state["agent_outputs"][agent_name] = fallback

        try:
            emit("running_moderator", current_agent="moderator")
            moderator_prompt = self._build_moderator_prompt(state)
            moderator_output, moderator_run = self._run_agent("moderator", moderator_prompt, artifact_path)
            state["moderator_output"] = moderator_output
            state["agent_outputs"]["moderator"] = moderator_output
            state["agent_runs"].append(moderator_run)
        except Exception as exc:
            if not continue_on_agent_error:
                raise
            state["moderator_output"] = f"# moderator\n\nОшибка выполнения.\n\n```\n{type(exc).__name__}: {exc}\n```"
            state["agent_outputs"]["moderator"] = state["moderator_output"]

        state["verdict"] = extract_verdict(state["moderator_output"])
        state["confidence"] = extract_score(
            state["moderator_output"],
            labels=["confidence", "уверенность", "confidence score", "итоговая уверенность"],
        )
        state["finished_at"] = now_iso()
        state["duration_sec"] = self._duration_seconds(state["started_at"], state["finished_at"])

        result = {
            "run_id": state["run_id"],
            "started_at": state["started_at"],
            "finished_at": state["finished_at"],
            "duration_sec": state["duration_sec"],
            "proposal_text": state["proposal_text"],
            "evaluation_prompt": state["evaluation_prompt"],
            "tracker_context": state["tracker_context"],
            "source_craft_context": state["source_craft_context"],
            "verdict": state["verdict"],
            "confidence": state["confidence"],
            "technical_analyst_output": state["technical_analyst_output"],
            "market_researcher_output": state["market_researcher_output"],
            "innovator_output": state["innovator_output"],
            "risk_assessor_output": state["risk_assessor_output"],
            "moderator_output": state["moderator_output"],
            "agent_outputs": state["agent_outputs"],
            "agent_runs": state["agent_runs"],
        }

        if artifact_path:
            self.save_artifacts(result, artifact_path)

        emit("completed")
        return result

    def save_artifacts(self, result: Dict[str, Any], artifact_dir: Path | str) -> None:
        path = Path(artifact_dir)
        ensure_dir(path)
        ensure_dir(path / "agent_outputs")
        safe_write(path / "moderator_verdict.md", result.get("moderator_output", ""))
        safe_write(path / "result.json", json.dumps(result, ensure_ascii=False, indent=2))
        for idx, agent_name in enumerate(EvalConfig.ORDER, start=1):
            safe_write(path / "agent_outputs" / f"{idx:02d}_{agent_name}.md", result.get("agent_outputs", {}).get(agent_name, ""))

    def _run_agent(
        self,
        agent_name: str,
        prompt_text: str,
        artifact_path: Optional[Path],
    ) -> tuple[str, Dict[str, Any]]:
        cfg = EvalConfig.EVALUATORS[agent_name]
        prompt_id = os.getenv(cfg.env_var, "").strip()
        started = now_iso()
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
            output_text, response_data = self._ensure_final_answer(
                agent_name=agent_name,
                prompt_id=prompt_id,
                original_prompt=prompt_text,
                output_text=output_text,
                response_data=response_data,
                timeout_sec=cfg.timeout_sec,
                retries=cfg.retries,
            )
            success = True
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            finished = now_iso()
            run = EvaluatorRun(
                index=0,
                evaluator_name=agent_name,
                prompt_id=prompt_id,
                started_at=started,
                finished_at=finished,
                duration_sec=self._duration_seconds(started, finished),
                input_text=prompt_text,
                output_text=output_text,
                success=success,
                response_id=response_data.get("id") if isinstance(response_data, dict) else None,
                response_status=response_data.get("status") if isinstance(response_data, dict) else None,
                usage=response_data.get("usage") if isinstance(response_data, dict) else None,
                error=error_text,
            )
            run_data = asdict(run)
            if success and artifact_path:
                stage_idx = EvalConfig.ORDER.index(agent_name) + 1
                if self.save_prompts:
                    safe_write(artifact_path / "agent_prompts" / f"{stage_idx:02d}_{agent_name}_prompt.md", prompt_text)
                safe_write(artifact_path / "agent_outputs" / f"{stage_idx:02d}_{agent_name}.md", output_text)
        return output_text, run_data

    def _ensure_final_answer(
        self,
        agent_name: str,
        prompt_id: str,
        original_prompt: str,
        output_text: str,
        response_data: Dict[str, Any],
        timeout_sec: int,
        retries: int,
    ) -> tuple[str, Dict[str, Any]]:
        # These two agents more often return intermediate "thinking" traces.
        if agent_name not in {"market_researcher", "innovator"}:
            return output_text, response_data

        current_text = output_text or ""
        current_data = response_data if isinstance(response_data, dict) else {}
        max_finalize_attempts = 2

        for _ in range(max_finalize_attempts):
            if not self._is_intermediate_answer(agent_name, current_text, current_data):
                return current_text, current_data

            finalize_prompt = (
                f"{original_prompt}\n\n"
                "Ниже твой предыдущий черновой ответ:\n"
                f"{current_text}\n\n"
                "Сейчас верни только финальный ответ по своей роли. "
                "Не пиши этапы рассуждений, планы поиска, фразы 'теперь', 'давайте поищем', "
                "'мне нужно'. Верни завершенную оценку."
            )
            current_text, current_data = self.client.call(
                prompt_id=prompt_id,
                input_text=finalize_prompt,
                timeout_sec=timeout_sec,
                retries=retries,
            )

        return current_text, current_data

    def _is_intermediate_answer(
        self,
        agent_name: str,
        output_text: str,
        response_data: Dict[str, Any],
    ) -> bool:
        status = str((response_data or {}).get("status", "")).lower().strip()
        text = (output_text or "").strip()
        low = text.lower()

        intermediate_markers = [
            "я проведу",
            "теперь мне нужно",
            "давайте поищем",
            "мне нужно собрать",
            "сначала мне нужно",
        ]
        has_intermediate_markers = any(marker in low for marker in intermediate_markers)

        # Broad "looks like a finished report" markers.
        final_markers = [
            "итоговый балл",
            "рекомендация",
            "вывод",
            "обоснование",
            "оценка",
        ]
        has_final_markers = any(marker in low for marker in final_markers)

        if status and status != "completed":
            return True

        if len(text) < 250 and has_intermediate_markers:
            return True

        if agent_name in {"market_researcher", "innovator"} and has_intermediate_markers and not has_final_markers:
            return True

        return False

    def _build_context_block(self, state: Dict[str, Any]) -> str:
        tracker_context = state.get("tracker_context", "").strip()
        source_craft_context = state.get("source_craft_context", "").strip()
        blocks: List[str] = []
        if tracker_context:
            blocks.append(f"### Yandex Tracker context\n{tracker_context}")
        if source_craft_context:
            blocks.append(f"### Source Craft context\n{source_craft_context}")
        if not blocks:
            return "Дополнительный MCP-контекст не предоставлен."
        return "\n\n".join(blocks)

    def _build_common_prompt(self, state: Dict[str, Any], evaluator_name: str) -> str:
        return f"""
Ты evaluator-агент: {evaluator_name}.
Оцени заявку строго по фактам и не додумывай недостающие данные.
Если данных недостаточно, явно укажи это как риск.

## Входная заявка
{state["proposal_text"]}

## Пользовательские приоритеты оценки (optional)
{state.get("evaluation_prompt", "") or "Не указаны"}

## Дополнительный контекст
{self._build_context_block(state)}

        """.strip()

    def _build_moderator_prompt(self, state: Dict[str, Any]) -> str:
        return f"""
Ты moderator финального решения по заявке.
Ниже выводы 4 evaluator-агентов. Синтезируй их и вынеси итог.
Нельзя игнорировать критические риски без смягчающих мер.

## Заявка
{state["proposal_text"]}

## Пользовательские приоритеты оценки (optional)
{state.get("evaluation_prompt", "") or "Не указаны"}

## Вывод technical_analyst
{state["technical_analyst_output"]}

## Вывод market_researcher
{state["market_researcher_output"]}

## Вывод innovator
{state["innovator_output"]}

## Вывод risk_assessor
{state["risk_assessor_output"]}

        """.strip()

    def _duration_seconds(self, start_iso: str, end_iso: str) -> float:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return (end - start).total_seconds()


def run_proposal_evaluation(
    proposal_text: str,
    evaluation_prompt: str = "",
    tracker_context: str = "",
    source_craft_context: str = "",
    artifact_dir: Optional[str] = None,
    continue_on_agent_error: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    system = ProposalEvaluationSystem(save_prompts=Config.SAVE_FULL_PROMPTS)
    result = system.run(
        proposal_text=proposal_text,
        evaluation_prompt=evaluation_prompt,
        tracker_context=tracker_context,
        source_craft_context=source_craft_context,
        artifact_dir=artifact_dir,
        continue_on_agent_error=continue_on_agent_error,
        progress_callback=progress_callback,
    )
    for idx, run in enumerate(result.get("agent_runs", []), start=1):
        run["index"] = idx
    return result
