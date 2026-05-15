import time
from datetime import datetime, timedelta
from agent.paper_agent import PaperCrawlerAgent
from utils.logger import get_logger


def seconds_until(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_daily(config_path: str = "config.yaml", hour: int = 9, minute: int = 0):
    logger = get_logger()
    logger.info("Scheduler started: %02d:%02d", hour, minute)
    while True:
        s = seconds_until(hour, minute)
        logger.info("Sleep %.0f seconds", s)
        time.sleep(s)
        try:
            PaperCrawlerAgent(config_path).run()
        except Exception as e:
            logger.exception("Scheduled run failed: %s", e)


if __name__ == "__main__":
    run_daily()
