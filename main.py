import argparse
from dotenv import load_dotenv
from agent.paper_agent import PaperCrawlerAgent
from utils.logger import get_logger


def parse_args():
    parser = argparse.ArgumentParser(description="Paper release crawler agent with LLM release judge")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()
    logger = get_logger()
    agent = PaperCrawlerAgent(config_path=args.config)

    if args.export_only:
        path = agent.export_csv()
        logger.info("Exported CSV: %s", path)
        return

    agent.run()

    if args.export:
        path = agent.export_csv()
        logger.info("Exported CSV: %s", path)


if __name__ == "__main__":
    main()
