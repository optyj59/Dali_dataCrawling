import asyncio
import os
import sys
import logging

# 상위 폴더(프로젝트 루트)를 sys.path에 추가하여 core 모듈을 임포트할 수 있도록 함
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from core.request_engine import RequestCommentEngineA
from utils.file_utils import save_comments_to_csv # CSV 저장 함수 임포트
from db_manager import DBManager
from utils.logger import setup_logger

def run_request_engine_sync(video_id: str, keyword_id: int, log_filename: str):
    """
    하나의 프로세스 내에서 동기로 실행될 크롤링 로직 (Requests)
    """
    logger = setup_logger(f'worker-{os.getpid()}', log_filename)
    # logger.info(f"워커 시작: {video_id}") # 로그 파일의 가독성을 위해 시작 로그는 주석 처리
    
    db_manager = DBManager()
    engine = RequestCommentEngineA()
    video_url = engine.BASE_URL + video_id
    
    status = "error"
    comment_count = 0
    error_message = ""
    
    try:
        video_data, comments = engine.get_all_comments(video_id, min_comments=5)
        
        if video_data:
            is_success = db_manager.process_full_data_transaction(video_data, keyword_id, comments)
            if is_success:
                status = "success"
                comment_count = len(comments)
                logger.info(f"DB 저장 성공: 영상 ID {video_id}에 {comment_count}개의 댓글 저장 완료.")
            else:
                error_message = "DB 트랜잭션 실패"
                logger.error(f"DB 저장 실패: {video_id}")
        else: # 비디오 데이터가 없는 경우 (예: 댓글 수 필터링, 영상 삭제 등)
            status = "skipped"
            logger.info(f"영상 ID {video_id}는 필터링 기준 미달 또는 데이터 미비로 건너뜁니다.")

    except Exception as e:
        error_message = str(e)
        logger.error(f"워커 오류: {video_id} | {e}", exc_info=True) # exc_info=True로 트레이스백 기록
        status = "error"
    finally:
        db_manager.close()
        return {
            "url": video_url, 
            "status": status, 
            "comment_count": comment_count,
            "error_message": error_message
        }

def worker_process_entry(args):
    """
    각 프로세스의 시작점(entry-point)이 되는 동기 함수.
    엔진 선택에 따라 적절한 크롤러를 실행합니다.
    """
    video_id, engine_choice, keyword_id, log_filename = args
    
    # Playwright 엔진을 사용하지 않으므로, requests 엔진을 바로 실행합니다.
    return run_request_engine_sync(video_id, keyword_id, log_filename)
