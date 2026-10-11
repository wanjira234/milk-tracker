"""Modal schedule for the weekly snapshot of what the model believes. Logic is in src/dispatch.py.

There is no model file to retrain: every daily run refits on all the farm's data. The weekly
job only records the result, so "what changed" can be shown later.
Deploy: modal deploy modal_jobs/weekly_retrain.py   (uses the same `milk-tracker` secret)
"""
import modal

app = modal.App("milk-tracker-weekly")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
    .add_local_python_source("src")
)


@app.function(image=image, secrets=[modal.Secret.from_name("milk-tracker")],
              schedule=modal.Cron("0 4 * * 1"), timeout=900)  # Mondays 04:00 UTC = 07:00 in Nairobi
def weekly():
    from src.dispatch import run_weekly_snapshot

    print("snapshots saved for farmers:", run_weekly_snapshot())
