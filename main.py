import argparse
from agent.paper_agent import PaperCrawlerAgent
from utils.logger import get_logger


def parse_args():
    parser = argparse.ArgumentParser(description="Conference paper crawler agent")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--export", action="store_true", help="Export SQLite papers to CSV after crawling")
    parser.add_argument("--export-only", action="store_true", help="Only export CSV, do not crawl")
    return parser.parse_args()


def main():
    args = parse_args()
    logger = get_logger()

    agent = PaperCrawlerAgent(config_path=args.config)

    if args.export_only:
        csv_path = agent.export_csv()
        logger.info("Exported CSV: %s", csv_path)
        return

    agent.run()

    if args.export:
        csv_path = agent.export_csv()
        logger.info("Exported CSV: %s", csv_path)


if __name__ == "__main__":
    main()
