import time


def test_prune_removes_finished_jobs_after_ttl(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "LOAD_JOB_TTL_SECONDS", 10)
    monkeypatch.setattr(app_module, "LOAD_JOB_STALE_SECONDS", 1000)
    monkeypatch.setattr(app_module, "LOAD_JOB_MAX", 50)

    now = time.time()
    with app_module.load_lock:
        app_module.load_jobs.clear()
        app_module.load_jobs["old"] = {
            "status": "done",
            "created_at": now - 100,
            "updated_at": now - 50,
            "html": "<html></html>",
        }
        app_module.load_jobs["fresh"] = {
            "status": "done",
            "created_at": now,
            "updated_at": now,
            "html": "<html></html>",
        }
        app_module.load_jobs["running"] = {
            "status": "running",
            "created_at": now - 50,
            "updated_at": now - 50,
            "html": None,
        }

    app_module.prune_load_jobs()

    with app_module.load_lock:
        assert "old" not in app_module.load_jobs
        assert "fresh" in app_module.load_jobs
        assert "running" in app_module.load_jobs


def test_prune_enforces_max_jobs(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "LOAD_JOB_TTL_SECONDS", 10_000)
    monkeypatch.setattr(app_module, "LOAD_JOB_STALE_SECONDS", 10_000)
    monkeypatch.setattr(app_module, "LOAD_JOB_MAX", 2)

    now = time.time()
    with app_module.load_lock:
        app_module.load_jobs.clear()
        for i in range(5):
            app_module.load_jobs[f"j{i}"] = {
                "status": "done",
                "created_at": now - i,
                "updated_at": now - i,
                "html": None,
            }

    app_module.prune_load_jobs()

    with app_module.load_lock:
        assert len(app_module.load_jobs) == 2
