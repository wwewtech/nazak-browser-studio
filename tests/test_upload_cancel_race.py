"""Regression tests for hunt round 4, part 2: the upload-cancel race (R-02)."""

from __future__ import annotations

import asyncio

from nazak.core.upload_queue import UploadJob, UploadQueueManager


def _manager() -> UploadQueueManager:
    q = UploadQueueManager.__new__(UploadQueueManager)
    q.jobs = {}
    q.is_running = False
    q._cancel_requested = False
    q._batch_lock = asyncio.Lock()
    q._profile_locks = {}
    q._launched_here = set()
    return q


def test_set_job_status_guard_keeps_canceled_verdict():
    """A non-terminal transition must never overwrite a user cancel."""
    q = _manager()
    job = UploadJob(profile_id="p1", profile_name="P1", source_video="v.mp4", platform="youtube_shorts")
    job.status = "canceled"
    assert q._set_job_status(job, "launching", "Launching...") is False
    assert job.status == "canceled"
    assert q._set_job_status(job, "uploading") is False
    assert job.status == "canceled"
    assert q._set_job_status(job, "uniqueizing", "...") is False
    assert job.status == "canceled"


def test_set_job_status_normal_transitions_work():
    q = _manager()
    job = UploadJob(profile_id="p1", profile_name="P1", source_video="v.mp4", platform="youtube_shorts")
    assert q._set_job_status(job, "uniqueizing", "msg") is True
    assert job.status == "uniqueizing" and job.progress_message == "msg"
    assert q._set_job_status(job, "launching") is True
    assert job.status == "launching" and job.progress_message == "msg"  # message untouched when None


def test_cancel_then_batch_transition_keeps_cancel():
    """The exact R-02 sequence: cancel_all mid-flight, the batch loop's next
    transition (previously unconditional) must not resurrect the job."""
    q = _manager()
    job = UploadJob(profile_id="p2", profile_name="P2", source_video="v.mp4", platform="youtube_shorts")
    job.status = "uploading"
    q.jobs["p2"] = job
    q._cancel_requested = True
    job.status = "canceled"  # what cancel_all does
    # ... the batch loop wakes from its await and tries to transition:
    assert q._set_job_status(job, "launching", "Launching...") is False
    assert job.status == "canceled"
