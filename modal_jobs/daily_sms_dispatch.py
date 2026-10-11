"""Modal schedule for the daily SMS job. All the logic is in src/dispatch.py.

Setup once:  modal secret create milk-tracker DATABASE_URL=... ANTHROPIC_API_KEY=... \
                 AT_USERNAME=... AT_API_KEY=... AT_SENDER_ID=...
Try it:      modal run modal_jobs/daily_sms_dispatch.py          (dry run: sends nothing)
Deploy:      modal deploy modal_jobs/daily_sms_dispatch.py
"""
import modal

app = modal.App("milk-tracker-daily")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements("requirements.txt")
    .add_local_python_source("src")
)


@app.function(image=image, secrets=[modal.Secret.from_name("milk-tracker")],
              schedule=modal.Cron("0 5 * * *"), timeout=900)  # 05:00 UTC = 08:00 in Nairobi
def daily():
    from src.dispatch import run_daily

    for row in run_daily(send=True):
        print(row)


@app.function(image=image, secrets=[modal.Secret.from_name("milk-tracker")])
def dry_run():
    from src.dispatch import run_daily

    for row in run_daily(send=False):
        print(row)


@app.local_entrypoint()
def main():
    dry_run.remote()
