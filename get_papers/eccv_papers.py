import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url = "https://www.ecva.net/papers.php"
base_url = "https://www.ecva.net/"

headers = {
    "User-Agent": "Mozilla/5.0"
}

resp = requests.get(url, headers=headers, timeout=20)
resp.raise_for_status()

soup = BeautifulSoup(resp.text, "lxml")

# 找到 ECCV 2024 这个按钮
eccv_2024_button = None

for button in soup.select("button.accordion"):
    if "ECCV 2024 Papers" in button.get_text(strip=True):
        eccv_2024_button = button
        break

if eccv_2024_button is None:
    raise RuntimeError("没有找到 ECCV 2024 Papers")

# 只取 ECCV 2024 后面的 accordion-content
eccv_2024_content = eccv_2024_button.find_next_sibling(
    "div",
    class_="accordion-content"
)

if eccv_2024_content is None:
    raise RuntimeError("没有找到 ECCV 2024 的论文内容区域")
i = 1
# 遍历 ECCV 2024 里的所有论文
for dt in eccv_2024_content.select("dt.ptitle"):
    # 1. 取出题目
    title_a = dt.select_one("a")
    title = title_a.get_text(" ", strip=True) if title_a else ""

    # 2. 取出作者
    author_dd = dt.find_next_sibling("dd")
    authors = author_dd.get_text(" ", strip=True) if author_dd else ""

    # 3. 取出 PDF 链接
    link_dd = author_dd.find_next_sibling("dd") if author_dd else None
    pdf_url = ""

    if link_dd:
        for a in link_dd.select("a"):
            if a.get_text(strip=True).lower() == "pdf":
                pdf_url = urljoin(base_url, a.get("href"))
                break

    print("题目：", title)
    print("作者：", authors)
    print("PDF：", pdf_url)
    print(i)
    i += 1
    print("-" * 100)