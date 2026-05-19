from crawlers.cvf import crawl_cvf
from crawlers.ecva import crawl_ecva
from crawlers.generic import crawl_generic
from crawlers.ijcai import crawl_ijcai
from crawlers.neurips import crawl_neurips


CRAWLER_MAP = {
    "cvf": crawl_cvf,
    "ecva": crawl_ecva,
    "ijcai": crawl_ijcai,
    "neurips": crawl_neurips,
    "generic": crawl_generic,
}


def get_crawler(parser_name: str):
    return CRAWLER_MAP.get(parser_name)
