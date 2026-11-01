import asyncio

from app.core.tasks import TaskSupervisor


async def test_spawned_task_runs_and_is_released() -> None:
    supervisor = TaskSupervisor()
    done = asyncio.Event()

    async def work() -> None:
        done.set()

    supervisor.spawn(work(), name="work")
    await asyncio.wait_for(done.wait(), timeout=1)
    await asyncio.sleep(0)
    assert supervisor.running == 0


async def test_unhandled_exception_is_logged_not_lost(capsys) -> None:  # type: ignore[no-untyped-def]
    supervisor = TaskSupervisor()

    async def boom() -> None:
        raise RuntimeError("kaboom")

    task = supervisor.spawn(boom(), name="boom")
    await asyncio.wait({task})
    await asyncio.sleep(0)
    assert supervisor.running == 0
    assert "background_task_failed" in capsys.readouterr().out


async def test_shutdown_cancels_running_tasks() -> None:
    supervisor = TaskSupervisor()
    cleaned_up = asyncio.Event()

    async def forever() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            cleaned_up.set()

    supervisor.spawn(forever(), name="forever")
    await asyncio.sleep(0)
    await supervisor.shutdown()
    assert cleaned_up.is_set()
    assert supervisor.running == 0
