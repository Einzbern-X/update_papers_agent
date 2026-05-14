#!/usr/bin/env python3
"""
快手BI SQL查询API脚本
通过API直接提交查询并下载结果为CSV
"""

import requests
import time
import csv
import sys

import uuid


# ==================== 配置区域 ====================
# 【重要】请从浏览器开发者工具复制完整的Cookie值
COOKIE = """
_did=web_54655717DB33610; apdid=3f1051ab-10b6-4f10-9479-6a76cb8d4a7053ba5ecdb6f36f971cf29838da782433:1773632143:1; hdige2wqwoino=TmXpSx2P64wBzdeJric5wTN2RYA3abT80c2b96ea; hdige3wqwoino=815737-386e312619454e5a032f721b8; ks_sso_gray_cookie=1; userToken=uDIIgZctX6tO1rP4IV8Xrw==-chenchengxu; userName=chenchengxu; userId=chenchengxu; did=web_aabcc826f5b3003bf917df7ab151addd; kwpsecproductname=kuaishou-vision; g-token=dc5c6659-8508-4401-91ba-46d283de2330; kwfv1=PnGU+9+Y8008S+nH0U+0mjPf8fP08f+98f+nLlwnrIP9P9G98YPf8jPBQSweS0+nr9G0mD8B+fP/L98/qlPe4f8BG9PezY80+YP0bSG0r7+0LE8nz0wBHlG0Dl8/+fG/qh+/DEwecUP/rIP/WFPBzS+eZA+eq7PAqAGfHhPfHhGAL=; _twpid=tw.1776080152676.782159189439969525; ksCorpDeviceid=9e376595-4f0e-40f7-a8e3-238471689f54; _ga=GA1.1.3177883.1776074293; _ga_F6CM1VE30P=GS2.1.s1776864704$o10$g1$t1776864713$j51$l0$h0; accessproxy_session=01ff9a6319ae785c5516dbc49a961ea4785243e991GOzIwqDlMxADCiQyNGZhMjA0Mi05OGNkLTRhYmEtOWYwNy0wNTFkMWMxYTljMmUqFRgBEgtjaGVuY2hlbmd4dQoEGAEoASIYa3dhaWJpLmNvcnAua3VhaXNob3UuY29t; AMCV_98CF678254E93B1B0A4C98A5%40AdobeOrg=179643557%7CMCMID%7C63928997701522629642539107119224652179%7CMCAAMLH-1777615017%7C11%7CMCAAMB-1777615017%7C6G1ynYcLPuiQxYZrsz_pkqfLG9yMXBpb2zX5dvJdYQJzPXImdj0y%7CMCOPTOUT-1777017417s%7CNONE%7CvVersion%7C5.5.0; _rdt_uuid=1776080152710.b91b36cf-f0f4-4f37-9ab2-2ea80ae6edb4; user=chenchengxu; dp_user_name=chenchengxu; ks_security_encrypt=ChVjb3Jwc2VjLnNzby5jYXMudG9rZW4SIDzezrFy3F3kdYrae4Sbxxyb6I5DTE3Z/taU/YfHjwDxGhLRqY2kaa2mejBq4Q6dzj6iO+AiIMAvWrtTem0Zh07Q+VZvhMO/qnkdfHgNou4qFSWygtgmKAUwAQ==; tag=U1QtMzY0ODAyLTctY0FlZkw1TDc4djhVTzQ4M2lzQy0tVWpIVS1rc3Nzb3Byb2Q=; dpUserToken=ChVkcC53ZWIuY29tbW9uLnNzby5rZXkSILE2kmIsPRhr0/RSnPHppB0JxN9ZS6MDkD2uG462C5f9GhKitCom3BvwNoOe2zdKgPjiHagiIHR+e6+zZaK+rXCio8zNQa7HtcvK82tyDhiTCtkRoxVXKAUwAQ==-chenchengxu; ehid=23cY-3i6y2fmcCqbdNyn2NJJUobgSGSlvhEh7; kwaibi-user-token=eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJrd2FpYmkiLCJhdWQiOiJjaGVuY2hlbmd4dSIsImlhdCI6MTc3ODMwODM0OSwiZXhwIjoxNzc4Mzk0NzQ5LCJqdGkiOiJmYjA2NTIyMi05YTZjLTQ4NWEtYThhZi0wYTAzNDA0ZDQ0N2EifQ.CEy6vN4O7yXrolN4GikEym_5X-_a5lyW01Uvu6nzMKI; ticket=y4WqGl0vMnC3zR4yswRay/TaaLwZKADwwSPv81n1zgZ6eXW8XpaILL8uSpEIwbUg; time=1778308349300; JSESSIONID=B552D745643C941B58986574BE582416
"""

BASE_URL = "https://kwaibi.corp.kuaishou.com/sql-access/api/v1"
OUTPUT_CSV = "paper_results.csv"
# ==================================================

# SQL查询语句
SQL_QUERY = """
set hive.auto.convert.join = false;

with base_data as (
    select
        biz_key,
        create_time,
        update_time,
        get_json_object(subject, '$.zh') as subject_zh,
        substring_index(get_json_object(subject, '$.zh'), '_', -1) as applicant_name,
        case
            when get_json_object(subject, '$.zh') like '%/%_%' then
                regexp_replace(
                    regexp_extract(
                        substring_index(get_json_object(subject, '$.zh'), '_', 1),
                        '/([^/]+)$',
                        1
                    ),
                    '[A-Z]\\\\d+$',
                    ''
                )
            when get_json_object(subject, '$.zh') like '%_%' then
                regexp_replace(
                    substring_index(get_json_object(subject, '$.zh'), '_', 1),
                    '[A-Z]\\\\d+$',
                    ''
                )
            else null
        end as applicant_dept,
        regexp_extract(
            substring_index(get_json_object(subject, '$.zh'), '_', 1),
            '([A-Z]\\\\d+)',
            1
        ) as dept_code,
        model_data,
        summary
    from
        bpm.s_bpm_data_agile_testlw_form_data_t1_df
    where
        dt = '2026-05-08'
        and deleted = 0
        and status = 1
),
parsed_model_data as (
    select
        biz_key,
        create_time,
        update_time,
        applicant_dept,
        dept_code,
        applicant_name,
        subject_zh,
        max(
            case
                when get_json_object(item, '$.id') = 'ceoyx5qxuzj7qh' 
                then get_json_object(item, '$.value')
            end
        ) as paper_title,
        max(
            case
                when get_json_object(item, '$.id') = 'cgus97lp78681f' 
                then get_json_object(item, '$.value')
            end
        ) as paper_abstract,
        max(
            case
                when get_json_object(item, '$.id') = 'cg3h1gt15v9sf2' 
                then get_json_object(item, '$.value')
            end
        ) as acceptance_status,
        max(
            case
                when get_json_object(item, '$.id') = 'cem5o3du4xkjug' 
                then get_json_object(item, '$.value')
            end
        ) as conference_name_model,
        max(
            case
                when get_json_object(item, '$.id') = 'ck4h4xg82i5v1c' 
                then get_json_object(item, '$.value')
            end
        ) as is_university_research,
        from_unixtime(
            cast(
                max(
                    case
                        when get_json_object(item, '$.id') = 'cxs8y7f5qbb4vx' 
                        then get_json_object(item, '$.value')
                    end
                ) / 1000 as bigint
            ),
            'yyyy-MM-dd'
        ) as expected_publish_date,
        regexp_extract(
            model_data,
            '"id":"clpeboy5vx9bjw","value":(\\\\[\\\\[.*?\\\\]\\\\])(?=,"isShow")',
            1
        ) as author_array_json,
        summary
    from
        base_data
        lateral view explode(
            split(
                regexp_replace(
                    regexp_replace(model_data, '^\\\\[|\\\\]$', ''),
                    '\\\\},\\\\{',
                    '\\\\}====\\\\{'
                ),
                '===='
            )
        ) tmp as item
    group by
        biz_key,
        create_time,
        update_time,
        applicant_dept,
        dept_code,
        applicant_name,
        subject_zh,
        model_data,
        summary
),
parsed_authors as (
    select
        biz_key,
        concat_ws(
            ',',
            collect_list(
                case
                    when get_json_object(author_field, '$.id') = 'cyx1yy8zu4sp1h' 
                    then get_json_object(author_field, '$.value')
                end
            )
        ) as author_names_zh
    from
        parsed_model_data
        lateral view explode(
            split(
                regexp_replace(
                    regexp_replace(author_array_json, '^\\\\[\\\\[|\\\\]\\\\]$', ''),
                    '\\\\],\\\\[',
                    '\\\\]===\\\\['
                ),
                '==='
            )
        ) t1 as author_row
        lateral view explode(
            split(
                regexp_replace(
                    regexp_replace(author_row, '^\\\\[|\\\\]$', ''),
                    '\\\\},\\\\{',
                    '\\\\}====\\\\{'
                ),
                '===='
            )
        ) t2 as author_field
    where
        author_array_json is not null
        and author_array_json != ''
    group by
        biz_key
),
parsed_summary as (
    select
        biz_key,
        max(
            case
                when get_json_object(item, '$.fieldName') = '拟发表学术会议或期刊名称' 
                then get_json_object(item, '$.fieldValue')
            end
        ) as conference_name_summary,
        max(
            case
                when get_json_object(item, '$.fieldName') = '是否为高校科研项目产出' 
                then get_json_object(item, '$.fieldValue')
            end
        ) as is_university_research_summary
    from
        parsed_model_data
        lateral view explode(
            split(
                regexp_replace(
                    regexp_replace(summary, '^\\\\[|\\\\]$', ''),
                    '\\\\},\\\\{',
                    '\\\\}====\\\\{'
                ),
                '===='
            )
        ) tmp as item
    where
        summary is not null
        and summary != ''
    group by
        biz_key
)
select
    a.create_time,
    a.update_time,
    a.applicant_dept,
    a.dept_code,
    a.applicant_name,
    a.paper_title,
    a.paper_abstract,
    a.acceptance_status,
    coalesce(c.conference_name_summary, a.conference_name_model) as conference_name,
    coalesce(c.is_university_research_summary, a.is_university_research) as is_university_research,
    a.expected_publish_date,
    regexp_replace(
        regexp_replace(coalesce(b.author_names_zh, ''), ',+', ','),
        '^,|,$',
        ''
    ) as author_names_zh
from
    parsed_model_data a
    left join parsed_authors b on a.biz_key = b.biz_key
    left join parsed_summary c on a.biz_key = c.biz_key
where
    a.acceptance_status = '已中稿'
order by
    a.update_time desc;
"""


class KwaiBIClient:
    def __init__(self, cookie):
        self.session = requests.Session()
        
        # 完整的请求头（模拟浏览器）
        self.session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Content-Type': 'application/json',
            'Cookie': cookie.strip(),
            'Origin': 'https://kwaibi.corp.kuaishou.com',
            'Referer': 'https://kwaibi.corp.kuaishou.com/self-access/sql-access/',
            'Sec-Ch-Ua': '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36'
        })
    
    def get_user_notebooks(self):
        """获取用户的notebook列表"""
        url = f"{BASE_URL}/folder/getUserFolder"
        params = {
            'withLeaf': 'true',
            'searchInfo': ''
        }
        
        print("📋 获取用户notebook列表...")
        response = self.session.get(url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"获取列表失败: HTTP {response.status_code}")
        
        result = response.json()
        if result.get('result') != 1:
            raise Exception(f"获取列表失败: {result.get('error_msg')}")
        
        # 递归提取所有notebook
        notebooks = []
        def extract_notebooks(node):
            if isinstance(node, dict):
                if node.get('type') == 1:  # type=1 表示notebook
                    notebooks.append({
                        'id': node.get('id'),
                        'uuid': node.get('uuid'),
                        'name': node.get('name'),
                        'creator': node.get('creator')
                    })
                # 递归处理children
                if 'children' in node:
                    for child in node['children']:
                        extract_notebooks(child)
            elif isinstance(node, list):
                for item in node:
                    extract_notebooks(item)
        
        data = result.get('data', [])
        extract_notebooks(data)
        
        print(f"✅ 找到 {len(notebooks)} 个notebook")
        return notebooks
    
    def submit_query(self, sql):
        """提交SQL查询 - 使用已有notebook执行"""
        # 1. 获取用户的notebook列表
        notebooks = self.get_user_notebooks()
        
        if not notebooks:
            raise Exception("未找到可用的notebook，请先在网页上创建一个查询")
        
        # 2. 使用第一个notebook
        notebook = notebooks[0]
        print(f"📝 使用notebook: {notebook['name']} (ID: {notebook['id']})")
        
        # 3. 提交执行
        url = f"{BASE_URL}/notebook/snippet/execute"
        
        # 生成新的snippet UUID
        snippet_uuid = str(uuid.uuid4())
        
        payload = {
            "id": notebook['id'],
            "uuid": notebook['uuid'],
            "name": notebook['name'],
            "creator": notebook['creator'],
            "type": 1,
            "exePlatform": 1,
            "data": {
                "snippetList": [
                    {
                        "name": "Snippet 1",
                        "query": sql,
                        "dbEngine": 1,        # Hive
                        "hiveEngine": 1,      # 智能路由
                        "userGroup": 338,     # 国内
                        "uuid": snippet_uuid,
                        "exePlatform": 1,
                        "exeType": 0,
                        "varMap": {}
                    }
                ]
            }
        }
        
        print("� 提交SQL查询...")
        response = self.session.post(url, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"提交失败: HTTP {response.status_code}\n{response.text}")
        
        result = response.json()
        if result.get('result') != 1:
            raise Exception(f"提交失败: {result.get('error_msg')}")
        
        # 从返回的data中获取taskUuid（用于轮询状态）
        task_data = result.get('data', {})
        if isinstance(task_data, list) and len(task_data) > 0:
            task_uuid = task_data[0].get('taskUuid')
            task_id = task_data[0].get('id')  # snippet execution id
        else:
            task_uuid = task_data.get('taskUuid')
            task_id = task_data.get('id')
            
        if not task_uuid:
            raise Exception(f"未能获取taskUuid: {result}")
            
        print(f"✅ 提交成功! Task UUID: {task_uuid}, ID: {task_id}")
        return task_uuid
    
    def get_result(self, task_uuid, max_wait=300):
        """获取查询结果（轮询）- 使用taskUuid"""
        url = f"{BASE_URL}/task/result"
        
        print(f"⏳ 等待查询完成 (Task UUID: {task_uuid})...")
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                raise Exception(f"查询超时（超过{max_wait}秒）")
            
            response = self.session.get(url, params={'taskUuid': task_uuid})
            
            if response.status_code != 200:
                raise Exception(f"获取结果失败: HTTP {response.status_code}")
            
            result = response.json()
            
            if result.get('result') != 1:
                error_msg = result.get('error_msg', 'Unknown error')
                
                # 检查是否还在执行中
                if error_msg in ['running', 'pending', 'waiting', 'canDiff']:
                    print(f"  查询中... ({int(elapsed)}s)")
                    time.sleep(3)
                    continue
                else:
                    raise Exception(f"查询失败: {error_msg}")
            
            # 查询成功
            data = result.get('data', {})
            data_list = data.get('dataList', [])
            result_rows = len(data_list)
            
            print(f"✅ 查询完成! 返回 {result_rows} 行数据")
            return data_list
    
    def save_to_csv(self, data_list, filename):
        """保存结果为CSV"""
        if not data_list:
            print("⚠️  没有数据可保存")
            return
        
        # 定义表头
        headers = [
            '创建时间', '更新时间', '申请人部门', '部门编码',
            '申请人姓名', '论文标题', '论文摘要', '中稿情况',
            '会议/期刊名称', '是否为高校科研项目产出', '预期发表日期',
            '作者列表'
        ]
        
        print(f"💾 保存到 {filename}...")
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data_list)
        
        print(f"✅ 成功保存 {len(data_list)} 行数据到 {filename}")


def main():
    # 检查Cookie配置
    if not COOKIE.strip() or "在这里粘贴" in COOKIE:
        print("❌ 错误: 请先在脚本顶部配置Cookie！")
        print("\n获取Cookie的步骤：")
        print("1. 在Chrome浏览器中打开 https://kwaibi.corp.kuaishou.com/sql-access/")
        print("2. 按F12打开开发者工具 → 切换到 Network 标签")
        print("3. 在页面中执行任意SQL查询")
        print("4. 在Network中找到 'getResult' 请求 → 点击 Headers")
        print("5. 向下滚动找到 'Cookie' 字段，复制完整的值")
        print("6. 粘贴到脚本顶部的 COOKIE 变量中")
        sys.exit(1)
    
    try:
        client = KwaiBIClient(COOKIE)
        
        # 1. 提交查询
        task_id = client.submit_query(SQL_QUERY)
        
        # 2. 获取结果
        data_list = client.get_result(task_id, max_wait=300)
        
        # 3. 保存为CSV
        client.save_to_csv(data_list, OUTPUT_CSV)
        
        print("\n🎉 全部完成!")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()