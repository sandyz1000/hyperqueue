import json
import os
import time
from os.path import dirname, join

from ..conftest import HqEnv
from ..utils.wait import wait_until
from .pbs_mock import JobState, NewJobFailed, NewJobId, PbsMock
from .utils import (
    add_queue,
    extract_script_args,
    prepare_tasks,
    program_code_store_args_json,
    remove_queue,
    wait_for_event,
)


def test_add_pbs_descriptor(hq_env: HqEnv):
    hq_env.start_server(args=["--autoalloc-interval", "500ms"])
    output = add_queue(
        hq_env,
        manager="pbs",
        name="foo",
        backlog=5,
        workers_per_alloc=2,
    )
    assert "Allocation queue 1 successfully created" in output

    info = hq_env.command(["alloc", "list"], as_table=True)
    info.check_column_value("ID", 0, "1")


def test_pbs_queue_qsub_fail(hq_env: HqEnv):
    mock = PbsMock(hq_env, new_job_responses=[NewJobFailed("failure")])

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env)
        wait_for_event(hq_env, "Allocation submission failed")
        table = hq_env.command(["alloc", "events", "1"], as_table=True)
        table.check_column_value(
            "Message",
            0,
            "qsub execution failed\nCaused by:\nExit code: 1\nStderr: failure\nStdout:",
        )


def test_pbs_queue_qsub_args(hq_env: HqEnv):
    path = join(hq_env.work_path, "qsub.out")
    qsub_code = program_code_store_args_json(path)

    with hq_env.mock.mock_program("qsub", qsub_code):
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env, time_limit="3m", additional_args="--foo=bar a b --baz 42")
        wait_until(lambda: os.path.exists(path))

        with open(path) as f:
            args = json.loads(f.read())
            qsub_script_path = args[1]
        with open(qsub_script_path) as f:
            data = f.read()
            pbs_args = extract_script_args(data, "#PBS")
            assert pbs_args == [
                "-l select=1",
                "-N hq-alloc-1",
                f"-o {join(dirname(qsub_script_path), 'stdout')}",
                f"-e {join(dirname(qsub_script_path), 'stderr')}",
                "-l walltime=00:03:00",
                "--foo=bar a b --baz 42",
            ]


def test_pbs_queue_qsub_success(hq_env: HqEnv):
    mock = PbsMock(hq_env, new_job_responses=[NewJobId(id="123.job")])

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env)
        wait_for_event(hq_env, "Allocation queued")
        table = hq_env.command(["alloc", "events", "1"], as_table=True)
        table.check_column_value("Message", 0, "123.job")


def test_pbs_events_job_lifecycle(hq_env: HqEnv):
    mock = PbsMock(hq_env)

    job_id = mock.job_id(0)

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        mock.update_job_state(job_id, JobState(status="Q"))
        add_queue(hq_env)

        # Queued
        wait_for_event(hq_env, "Allocation queued")

        # Started
        mock.update_job_state(
            job_id, JobState(status="R", stime="Thu Aug 19 13:05:39 2021")
        )
        wait_for_event(hq_env, "Allocation started")

        # Finished
        mock.update_job_state(
            job_id, JobState(status="F", mtime="Thu Aug 19 13:06:39 2021", exit_code=0)
        )
        wait_for_event(hq_env, "Allocation finished")


def test_pbs_events_job_failed(hq_env: HqEnv):
    mock = PbsMock(hq_env)
    mock.update_job_state(
        mock.job_id(0),
        JobState(
            status="F",
            stime="Thu Aug 19 13:05:39 2021",
            mtime="Thu Aug 19 13:05:39 2021",
            exit_code=1,
        ),
    )

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env)

        wait_for_event(hq_env, "Allocation failed")


def test_pbs_allocations_job_lifecycle(hq_env: HqEnv):
    mock = PbsMock(hq_env)
    mock.update_job_state(
        mock.job_id(0),
        JobState(
            status="Q",
            qtime="Thu Aug 19 13:05:38 2021",
            stime="Thu Aug 19 13:05:39 2021",
            mtime="Thu Aug 19 13:05:39 2021",
        ),
    )

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env, name="foo")
        wait_for_alloc(hq_env, "Queued")

        mock.update_job_state(mock.job_id(0), JobState(status="R"))
        wait_for_alloc(hq_env, "Running")

        mock.update_job_state(mock.job_id(0), JobState(status="F", exit_code=0))
        wait_for_alloc(hq_env, "Finished")


def test_pbs_ignore_job_changes_after_finish(hq_env: HqEnv):
    mock = PbsMock(hq_env)
    for index in range(2):
        mock.update_job_state(
            mock.job_id(index),
            JobState(
                status="F",
                qtime="Thu Aug 19 13:05:38 2021",
                stime="Thu Aug 19 13:05:39 2021",
                mtime="Thu Aug 19 13:05:39 2021",
                exit_code=0,
            ),
        )

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env)
        wait_for_alloc(hq_env, "Finished")
        wait_for_alloc(hq_env, "Finished", index=1)

        mock.update_job_state(mock.job_id(0), JobState(status="R"))
        time.sleep(0.5)

        table = hq_env.command(["alloc", "info", "1"], as_table=True)
        table.check_column_value("State", 0, "Finished")
        table.check_column_value("State", 1, "Finished")


def test_pbs_cancel_active_jobs_on_server_stop(hq_env: HqEnv):
    mock = PbsMock(hq_env)

    # Keep 2 running and 2 queued jobs
    for index in range(2):
        mock.update_job_state(
            mock.job_id(index),
            JobState(
                status="R",
                qtime="Thu Aug 19 13:05:38 2021",
                stime="Thu Aug 19 13:05:39 2021",
                mtime="Thu Aug 19 13:05:39 2021",
            ),
        )
    for index in range(2, 4):
        mock.update_job_state(
            mock.job_id(index),
            JobState(
                status="Q",
                qtime="Thu Aug 19 13:05:38 2021",
                stime="Thu Aug 19 13:05:39 2021",
                mtime="Thu Aug 19 13:05:39 2021",
            ),
        )

    with mock.activate():
        process = hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env, name="foo", backlog=2, workers_per_alloc=1)

        def wait_until_fixpoint():
            jobs = hq_env.command(["alloc", "info", "1"], as_table=True)
            # 2 running + 2 queued
            return len(jobs) == 5

        wait_until(lambda: wait_until_fixpoint())

        hq_env.command(["server", "stop"])
        process.wait()
        hq_env.check_process_exited(process)

        expected_job_ids = set(mock.job_id(index) for index in range(4))
        wait_until(lambda: expected_job_ids == set(mock.deleted_jobs()))


def test_pbs_cancel_queued_jobs_on_remove_descriptor(hq_env: HqEnv):
    mock = PbsMock(hq_env)

    for index in range(2):
        mock.update_job_state(
            mock.job_id(index),
            JobState(
                status="Q",
                qtime="Thu Aug 19 13:05:38 2021",
                stime="Thu Aug 19 13:05:39 2021",
                mtime="Thu Aug 19 13:05:39 2021",
            ),
        )

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env, name="foo", backlog=2, workers_per_alloc=1)

        def wait_until_fixpoint():
            jobs = hq_env.command(["alloc", "info", "1"], as_table=True)
            return len(jobs) == 3

        wait_until(lambda: wait_until_fixpoint())

        remove_queue(hq_env, 1)
        wait_until(lambda: len(hq_env.command(["alloc", "list"], as_table=True)) == 1)

        expected_job_ids = set(mock.job_id(index) for index in range(2))
        wait_until(lambda: expected_job_ids == set(mock.deleted_jobs()))


def test_fail_on_remove_descriptor_with_running_jobs(hq_env: HqEnv):
    mock = PbsMock(hq_env)

    mock.update_job_state(
        mock.job_id(0),
        JobState(
            status="R",
            qtime="Thu Aug 19 13:05:38 2021",
            stime="Thu Aug 19 13:05:39 2021",
            mtime="Thu Aug 19 13:05:39 2021",
        ),
    )

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env, name="foo", backlog=2, workers_per_alloc=1)

        wait_for_alloc(hq_env, "Running")

        remove_queue(
            hq_env,
            1,
            expect_fail="Allocation queue has running jobs, so it will not be removed. "
            "Use `--force` if you want to remove the queue anyway",
        )
        wait_for_alloc(hq_env, "Running")


def test_pbs_cancel_active_jobs_on_forced_remove_descriptor(hq_env: HqEnv):
    mock = PbsMock(hq_env)

    # Keep 2 running and 2 queued jobs
    for index in range(2):
        mock.update_job_state(
            mock.job_id(index),
            JobState(
                status="R",
                qtime="Thu Aug 19 13:05:38 2021",
                stime="Thu Aug 19 13:05:39 2021",
                mtime="Thu Aug 19 13:05:39 2021",
            ),
        )
    for index in range(2, 4):
        mock.update_job_state(
            mock.job_id(index),
            JobState(
                status="Q",
                qtime="Thu Aug 19 13:05:38 2021",
                stime="Thu Aug 19 13:05:39 2021",
                mtime="Thu Aug 19 13:05:39 2021",
            ),
        )

    with mock.activate():
        hq_env.start_server(args=["--autoalloc-interval", "100ms"])
        prepare_tasks(hq_env)

        add_queue(hq_env, name="foo", backlog=2, workers_per_alloc=1)

        def wait_until_fixpoint():
            jobs = hq_env.command(["alloc", "info", "1"], as_table=True)
            # 2 running + 2 queued
            return len(jobs) == 5

        wait_until(lambda: wait_until_fixpoint())

        remove_queue(hq_env, 1, force=True)
        wait_until(lambda: len(hq_env.command(["alloc", "list"], as_table=True)) == 1)

        expected_job_ids = set(mock.job_id(index) for index in range(4))
        wait_until(lambda: expected_job_ids == set(mock.deleted_jobs()))


def wait_for_alloc(hq_env: HqEnv, state: str, index=0):
    """
    Wait until an allocation has the given `state`.
    Assumes a single allocation queue.
    """

    def wait():
        table = hq_env.command(["alloc", "info", "1"], as_table=True)
        alloc_states = table.get_column_value("State")
        if index >= len(alloc_states):
            return False
        return alloc_states[index] == state

    wait_until(wait)