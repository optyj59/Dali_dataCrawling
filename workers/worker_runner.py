import asyncio
import os
import sys

# 상위 폴더(프로젝트 루트)를 sys.path에 추가하여 core 모듈을 임포트할 수 있도록 함
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from core.crawler_engine import CrawlerEngine
from core.request_engine import RequestCommentEngineA
from utils.file_utils import save_comments_to_csv # CSV 저장 함수 임포트

async def run_crawl_async(video_id: str, engine_function_name: str):
    """
    하나의 프로세스 내에서 비동기로 실행될 크롤링 로직 (Playwright)
    """
    print(f"[PID: {os.getpid()}] (Playwright) 워커 시작: {video_id}")
    crawler = CrawlerEngine()
    try:
        await crawler.initialize()
        metadata = await crawler.get_video_metadata(video_id)
        
        MIN_COMMENTS = 5
        if metadata.get('comment_count', 0) >= MIN_COMMENTS:
            print(f"[PID: {os.getpid()}] (Playwright) 조건 충족. '{engine_function_name}' 엔진 가동...")
            engine_function = getattr(crawler, engine_function_name)
            comments = await engine_function(video_id)
            
            if comments:
                # save_comments_to_csv는 동기 함수이므로 to_thread 사용
                await asyncio.to_thread(save_comments_to_csv, video_id, comments)
            
            return {"url": crawler.BASE_URL + video_id, "status": "success", "comment_count": len(comments)}
        else:
            print(f"[PID: {os.getpid()}] (Playwright) 조건 미충족. 건너뜀: 댓글 수 {metadata.get('comment_count', 0)}")
            return {"url": crawler.BASE_URL + video_id, "status": "skipped", "comment_count": 0}
    except Exception as e:
        print(f"[PID: {os.getpid()}] (Playwright) 워커 오류: {video_id} | {e}")
        return {"url": crawler.BASE_URL + video_id, "status": "error", "comment_count": 0}
    finally:
        await crawler.close()

def run_request_engine_sync(video_id: str):
    """
    하나의 프로세스 내에서 동기로 실행될 크롤링 로직 (Requests)
    """
    print(f"[PID: {os.getpid()}] (Requests) 워커 시작: {video_id}")
    
    engine = RequestCommentEngineA()
    MIN_COMMENTS = 5
    video_url = engine.BASE_URL + video_id
    
    try:
        comments = engine.get_all_comments(video_id, min_comments=MIN_COMMENTS)
        
        if comments:
            save_comments_to_csv(video_id, comments)
            return {"url": video_url, "status": "success", "comment_count": len(comments)}
        else:
            print(f"[PID: {os.getpid()}] (Requests) 조건 미충족 또는 댓글 없음. 건너뜁니다.")
            return {"url": video_url, "status": "skipped", "comment_count": 0}

    except Exception as e:
        print(f"[PID: {os.getpid()}] (Requests) 워커 오류: {video_id} | {e}")
        return {"url": video_url, "status": "error", "comment_count": 0}

def worker_process_entry(args):
    """
    각 프로세스의 시작점(entry-point)이 되는 동기 함수.
    엔진 선택에 따라 적절한 크롤러를 실행합니다.
    """
    video_id, engine_choice = args
    
    if engine_choice == "playwright":
        return asyncio.run(run_crawl_async(video_id, "extract_comments"))
    elif engine_choice == "requests":
        return run_request_engine_sync(video_id)
    else:
        print(f"알 수 없는 엔진: {engine_choice}")
        engine = RequestCommentEngineA() # for BASE_URL
        return {"url": engine.BASE_URL + video_id, "status": "error", "comment_count": 0}
