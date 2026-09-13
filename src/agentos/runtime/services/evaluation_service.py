"""Application service for background Evaluation runs."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agentos.core.config import EvaluationSettings
from agentos.core.context import get_user_id, get_workspace_id, new_id
from agentos.core.exceptions import NotFoundError, ValidationError
from agentos.core.tenancy import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
from agentos.evaluation.models import EvaluationDataset, EvaluationRun, EvaluationStatus
from agentos.evaluation.report import EvaluationReportBuilder
from agentos.evaluation.runner import EvaluationRunner
from agentos.evaluation.store import EvaluationStore


class EvaluationService:
    """Create, schedule, persist, and query Evaluation runs."""

    def __init__(
        self,
        store: EvaluationStore,
        runner: EvaluationRunner,
        settings: EvaluationSettings,
    ) -> None:
        self._store = store
        self._runner = runner
        self._settings = settings
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def resolve_dataset(self, dataset_name: str) -> tuple[EvaluationDataset, Path]:
        """Resolve a JSONL dataset inside the configured benchmark root."""
        root = Path(self._settings.dataset_root).expanduser().resolve()
        candidate = (root / dataset_name).resolve()
        if root not in candidate.parents:
            raise ValidationError(
                "dataset path must stay inside evaluation dataset root",
                details={"dataset_root": str(root)},
            )
        if candidate.suffix != ".jsonl":
            candidate = candidate.with_suffix(".jsonl")
        return EvaluationDataset.from_jsonl(candidate), candidate

    def create_run(
        self,
        *,
        dataset_name: str,
        workspace_id: int | None = None,
        user_id: int | None = None,
        config: dict[str, object] | None = None,
    ) -> EvaluationRun:
        """Persist a queued run and schedule its background execution."""
        dataset, path = self.resolve_dataset(dataset_name)
        scope = workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID
        actor = user_id if user_id is not None else get_user_id() or DEFAULT_USER_ID
        run = EvaluationRun(
            id=new_id("evalrun_"),
            workspace_id=scope,
            user_id=actor,
            dataset_name=dataset.name,
            dataset_path=str(path),
            cases=list(dataset.cases),
            total_cases=len(dataset.cases),
            config=dict(config or {}),
            status=EvaluationStatus.QUEUED,
        )
        self._store.save(run)
        task = asyncio.create_task(self._execute(run, dataset))
        self._tasks[run.id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(run.id, None))
        return run

    async def _execute(self, queued: EvaluationRun, dataset: EvaluationDataset) -> None:
        run = queued.model_copy(
            update={"status": EvaluationStatus.RUNNING, "dataset_name": dataset.name}
        )
        self._store.save(run)
        try:
            completed = await self._runner.run(
                dataset,
                run_id=run.id,
                workspace_id=run.workspace_id,
                user_id=run.user_id,
                on_result=self._store.save,
            )
            completed.report = EvaluationReportBuilder.build(completed)
            self._store.save(completed)
        except asyncio.CancelledError:
            run.status = EvaluationStatus.CANCELLED
            self._store.save(run)
            raise
        except Exception as exc:  # noqa: BLE001
            run.status = EvaluationStatus.FAILED
            run.error = str(exc)
            self._store.save(run)

    def get(self, run_id: str, *, workspace_id: int | None = None) -> EvaluationRun:
        scope = workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID
        run = self._store.get(run_id, workspace_id=scope)
        if run is None:
            raise NotFoundError(
                f"evaluation run not found: {run_id}", details={"id": run_id}
            )
        return run

    def list(
        self,
        *,
        workspace_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EvaluationRun], int]:
        return self._store.list(
            workspace_id=workspace_id or get_workspace_id() or DEFAULT_WORKSPACE_ID,
            limit=limit,
            offset=offset,
        )

    async def close(self) -> None:
        """Cancel and await outstanding background tasks."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


__all__ = ["EvaluationService"]
