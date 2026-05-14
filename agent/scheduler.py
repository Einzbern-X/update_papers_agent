import time
from datetime import datetime, timedelta

from agent.paper_agent import PaperCrawlerAgent
from utils.logger import get_logger


def seconds_until_next_run(hour: int = 9, minute: int = 0) -> float:
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if next_run <= now:
        next_run += timedelta(days=1)

    return (next_run - now).total_seconds()


def run_daily(config_path: str = "config.yaml", hour: int = 9, minute: int = 0):
    logger = get_logger()
    logger.info("Scheduler started. Daily run time: %02d:%02d", hour, minute)

    while True:
        sleep_seconds = seconds_until_next_run(hour, minute)
        logger.info("Sleeping %.0f seconds until next run", sleep_seconds)
        time.sleep(sleep_seconds)

        try:
            agent = PaperCrawlerAgent(config_path=config_path)
            agent.run()
        except Exception as e:
            logger.exception("Scheduled run failed: %s", e)


if __name__ == "__main__":
    run_daily()
