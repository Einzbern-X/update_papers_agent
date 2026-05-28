"""
Paper Crawler Web Interface
Allows LAN users to download conference papers via web interface.
"""
import os
import yaml
import threading
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, send_file, request
from dotenv import load_dotenv

# Add project root to path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.paper_agent import PaperCrawlerAgent
from database.paper_repo import fetch_all_papers, export_papers_to_csv
from database.source_repo import get_source_status
from utils.logger import get_logger

app = Flask(__name__, template_folder='templates')
logger = get_logger()

# Store crawl tasks status
crawl_tasks = {}

def load_config():
    """Load configuration from config.yaml"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def get_conferences():
    """Get list of enabled conferences from config"""
    config = load_config()
    sources = config.get('sources', [])
    conferences = []
    for source in sources:
        if source.get('enabled', True):
            conferences.append({
                'name': source.get('name', ''),
                'venue': source.get('venue', ''),
                'year': source.get('year', ''),
                'url': source.get('url', ''),
            })
    return conferences

def get_source_by_name(name: str):
    """Get source config by name"""
    config = load_config()
    sources = config.get('sources', [])
    for source in sources:
        if source.get('name') == name:
            return source
    return None

def check_source_status(source_name: str):
    """Check if source has been crawled and has papers"""
    source = get_source_by_name(source_name)
    if not source:
        return None
    
    db_path = os.path.join(os.path.dirname(__file__), 'data/papers.db')
    status = get_source_status(source, db_path)
    return status

def crawl_conference_task(source_name: str, task_id: str):
    """Background task to crawl a specific conference"""
    try:
        crawl_tasks[task_id] = {'status': 'running', 'message': 'Starting crawl...'}
        
        source = get_source_by_name(source_name)
        if not source:
            crawl_tasks[task_id] = {'status': 'error', 'message': 'Source not found'}
            return
        
        # Temporarily disable skip_done_sources to force crawl
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        
        # Set skip_done_sources to False temporarily
        if 'agent' not in config:
            config['agent'] = {}
        original_skip = config['agent'].get('skip_done_sources', True)
        config['agent']['skip_done_sources'] = False
        
        # Save modified config
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True)
        
        try:
            # Run the crawler
            crawl_tasks[task_id] = {'status': 'running', 'message': 'Crawling papers...'}
            agent = PaperCrawlerAgent(config_path=config_path)
            
            # Only crawl the specific source
            agent.run_source(source)
            
            # Check result
            status = check_source_status(source_name)
            if status and status.get('status', '').startswith('released'):
                paper_count = status.get('paper_count', 0)
                crawl_tasks[task_id] = {
                    'status': 'success', 
                    'message': f'Successfully crawled {paper_count} papers',
                    'paper_count': paper_count
                }
            else:
                # 未放榜或爬取失败 → 显示「尚未放榜」
                crawl_tasks[task_id] = {'status': 'not_released', 'message': '尚未放榜'}
        finally:
            # Restore original config
            config['agent']['skip_done_sources'] = original_skip
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True)
                
    except Exception as e:
        logger.exception(f"Crawl task failed: {e}")
        crawl_tasks[task_id] = {'status': 'error', 'message': str(e)}

@app.route('/')
def index():
    """Main page with conference buttons"""
    conferences = get_conferences()
    return render_template('index.html', conferences=conferences)

@app.route('/api/conferences')
def api_conferences():
    """Get list of conferences with their status"""
    conferences = get_conferences()
    result = []
    for conf in conferences:
        status = check_source_status(conf['name'])
        result.append({
            'name': conf['name'],
            'venue': conf['venue'],
            'year': conf['year'],
            'url': conf['url'],
            'status': status.get('status', 'not_crawled') if status else 'not_crawled',
            'paper_count': status.get('paper_count', 0) if status else 0,
            'last_checked': status.get('last_checked_at', '') if status else '',
        })
    return jsonify(result)

@app.route('/api/crawl/<source_name>')
def api_crawl(source_name):
    """Start crawling a specific conference"""
    import uuid
    task_id = str(uuid.uuid4())
    
    # Check if already crawling
    for tid, task in crawl_tasks.items():
        if task.get('status') == 'running':
            return jsonify({'error': 'Another crawl is in progress', 'task_id': tid}), 409
    
    # Start background crawl
    thread = threading.Thread(target=crawl_conference_task, args=(source_name, task_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'task_id': task_id, 'message': 'Crawl started'})

@app.route('/api/status/<task_id>')
def api_status(task_id):
    """Get status of a crawl task"""
    task = crawl_tasks.get(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(task)

@app.route('/api/download/<source_name>')
def api_download(source_name):
    """Download CSV for a specific conference"""
    source = get_source_by_name(source_name)
    if not source:
        return jsonify({'error': 'Source not found'}), 404
    
    # Check if source has been crawled
    status = check_source_status(source_name)
    if not status or not status.get('status', '').startswith('released'):
        return jsonify({'error': 'Please crawl this conference first'}), 400
    
    # Export to CSV
    db_path = os.path.join(os.path.dirname(__file__), 'data/papers.db')
    export_dir = os.path.join(os.path.dirname(__file__), 'exports')
    Path(export_dir).mkdir(parents=True, exist_ok=True)
    
    venue = source.get('venue', '')
    year = source.get('year', '')
    csv_filename = f'{venue}_{year}_papers.csv'
    csv_path = os.path.join(export_dir, csv_filename)
    
    # Filter papers for this conference
    all_papers = fetch_all_papers(db_path)
    filtered_papers = [p for p in all_papers 
                      if p.get('venue') == venue and p.get('year') == year]
    
    if not filtered_papers:
        return jsonify({'error': 'No papers found for this conference'}), 404
    
    # Export filtered papers
    import pandas as pd
    pd.DataFrame(filtered_papers).to_csv(csv_path, index=False, encoding='utf-8-sig')
    
    return send_file(csv_path, as_attachment=True, download_name=csv_filename)

def get_local_ip():
    """Get local IP address for LAN access"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "0.0.0.0"

if __name__ == '__main__':
    load_dotenv()
    local_ip = get_local_ip()

    
    app.run(host='0.0.0.0', port=5001, debug=True)
