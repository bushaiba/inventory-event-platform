from inventory_event_platform.synthetic import seed_demo


def test_demo_seed_runs_end_to_end(service):
    summary = seed_demo(service, containers=20, seed=42)

    assert summary["created"] == 20
    assert summary["moved"] == 10
    assert summary["temporary_moves"] == 2
    assert summary["restores_completed"] == 2
    assert summary["reconciliation_drift"] == 0
    assert summary["outbox_published"] > 20
