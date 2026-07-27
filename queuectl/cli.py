"""Click CLI entrypoint for queuectl."""

import json
import sys

import click

from queuectl import config as config_module
from queuectl import queue_ops
from queuectl import worker as worker_module


@click.group()
def main():
    """QueueCTL — a SQLite-backed job queue with worker processes."""
    pass


@main.command()
@click.argument("job_json")
def enqueue(job_json):
    """Enqueue a new job from JSON."""
    try:
        job = queue_ops.enqueue_job(job_json)
        click.echo(json.dumps(job.to_dict()))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@main.group()
def worker():
    """Manage worker processes."""
    pass


@worker.command("start")
@click.option("--count", default=1, help="Number of worker processes to spawn.")
def worker_start(count):
    """Start worker process(es) in the foreground."""
    try:
        worker_module.start_workers(count)
    except NotImplementedError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@worker.command("stop")
def worker_stop():
    """Stop all running workers gracefully."""
    stopped = worker_module.stop_all_workers()
    if stopped:
        click.echo(f"Sent SIGTERM to worker(s): {', '.join(str(p) for p in stopped)}")
    else:
        click.echo("No running workers found.")


@main.command()
def status():
    """Show job counts per state and live worker count."""
    counts = queue_ops.get_job_counts()
    workers = queue_ops.get_live_worker_count()
    click.echo("Job counts:")
    for state, count in counts.items():
        click.echo(f"  {state}: {count}")
    click.echo(f"Live workers: {workers}")


@main.command("list")
@click.option("--state", required=True, help="Filter jobs by state.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
def list_jobs(state, as_json):
    """List jobs filtered by state."""
    try:
        jobs = queue_ops.list_jobs_by_state(state)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if as_json:
        payload = [job.to_dict() for job in jobs]
        click.echo(json.dumps(payload))
    else:
        if not jobs:
            click.echo(f"No jobs in state '{state}'.")
        for job in jobs:
            click.echo(f"{job.id}  {job.state}  {job.command}")


@main.group("dlq")
def dlq():
    """Dead letter queue operations."""
    pass


@dlq.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
def dlq_list(as_json):
    """List jobs in the dead letter queue."""
    jobs = queue_ops.list_dlq_jobs()
    if as_json:
        click.echo(json.dumps([job.to_dict() for job in jobs]))
    else:
        if not jobs:
            click.echo("No jobs in the dead letter queue.")
        for job in jobs:
            click.echo(f"{job.id}  {job.command}  attempts={job.attempts}")


@dlq.command("retry")
@click.argument("job_id")
def dlq_retry(job_id):
    """Re-enqueue a dead job for retry."""
    try:
        job = queue_ops.dlq_retry_job(job_id)
        click.echo(json.dumps(job.to_dict()))
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@main.group()
def config():
    """Manage queue configuration."""
    pass


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value."""
    try:
        config_module.set_config(key, value)
        click.echo(f"Set {key} = {value}")
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
