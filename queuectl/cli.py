"""Click CLI entrypoint for queuectl."""

import click


@click.group()
def main():
    """QueueCTL — a SQLite-backed job queue with worker processes."""
    pass


@main.command()
@click.argument("job_json")
def enqueue(job_json):
    """Enqueue a new job from JSON."""
    pass


@main.group()
def worker():
    """Manage worker processes."""
    pass


@worker.command("start")
@click.option("--count", default=1, help="Number of worker processes to spawn.")
def worker_start(count):
    """Start worker process(es) in the foreground."""
    pass


@worker.command("stop")
def worker_stop():
    """Stop all running workers gracefully."""
    pass


@main.command()
def status():
    """Show job counts per state and live worker count."""
    pass


@main.command("list")
@click.option("--state", required=True, help="Filter jobs by state.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
def list_jobs(state, as_json):
    """List jobs filtered by state."""
    pass


@main.group("dlq")
def dlq():
    """Dead letter queue operations."""
    pass


@dlq.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
def dlq_list(as_json):
    """List jobs in the dead letter queue."""
    pass


@dlq.command("retry")
@click.argument("job_id")
def dlq_retry(job_id):
    """Re-enqueue a dead job for retry."""
    pass


@main.group()
def config():
    """Manage queue configuration."""
    pass


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value."""
    pass


if __name__ == "__main__":
    main()
