import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
url = "https://openaccess.thecvf.com/CVPR2025?day=all"
base_url = "https://openaccess.thecvf.com"

headers = {
    "User-Agent": "Mozilla/5.0"
}

resp = requests.get(url, headers=headers, timeout=20)
resp.raise_for_status()

soup = BeautifulSoup(resp.text, "lxml")
i=1
for dt in soup.select("dt.ptitle"):
    
    title_a = dt.select_one("a")
    title = title_a.get_text(strip=True)

    author_dd = dt.find_next_sibling("dd")
    authors = []

    for input_tag in author_dd.select('input[name="query_author"]'):
        author = input_tag.get("value")
        if author:
            authors.append(author)

    link_dd = author_dd.find_next_sibling("dd")
    pdf_url = ""

    for a in link_dd.select("a"):
        if a.get_text(strip=True).lower() == "pdf":
            pdf_url = urljoin(base_url, a.get("href"))
            break

    print("题目：", title)
    print("作者：", ", ".join(authors))
    print("PDF：", pdf_url)
    print("-" * 80)
    print(i)
    i+=1
