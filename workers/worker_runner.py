import asyncio
import os
import sys

# 상위 폴더(프로젝트 루트)를 sys.path에 추가하여 core 모듈을 임포트할 수 있도록 함
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from core.request_engine import RequestCommentEngineA
from utils.file_utils import save_comments_to_csv # CSV 저장 함수 임포트
from db_manager import DBManager # DB 저장 기능 임포트

def run_request_engine_sync(video_id: str, keyword_id: int):
    """
    하나의 프로세스 내에서 동기로 실행될 크롤링 로직 (Requests)
    """
    print(f"[PID: {os.getpid()}] (Requests) 워커 시작: {video_id}")
    
    db_manager = DBManager() # 워커별로 DBManager 인스턴스 생성
    engine = RequestCommentEngineA()
    # MIN_COMMENTS = 5 # RequestCommentEngineA.get_all_comments에서 처리되므로 여기서는 제거
    video_url = engine.BASE_URL + video_id
    
    status = "error"
    comment_count = 0
    
    try:
        # RequestCommentEngineA.get_all_comments는 이제 video_data와 comments를 반환
        video_data, comments = engine.get_all_comments(video_id, min_comments=5) # min_comments 전달
        
        if video_data: # 비디오 메타데이터가 있으면, 댓글이 없더라도 DB 트랜잭션을 실행
            # DBManager의 통합 트랜잭션 함수 호출 (comments는 비어있을 수 있음)
            is_success = db_manager.process_full_data_transaction(video_data, keyword_id, comments)
            if is_success:
                status = "success"
                comment_count = len(comments)
                print(f"[PID: {os.getpid()}] (Requests) DB 저장 성공: {video_id} ({comment_count}개 댓글)")
            else:
                print(f"[PID: {os.getpid()}] (Requests) DB 저장 실패: {video_id}")
        else: # 비디오 데이터가 없는 경우 (조회수 필터링 등)
            status = "skipped" 
            print(f"[PID: {os.getpid()}] (Requests) 비디오 데이터 없음 (필터링 또는 오류): {video_id}")

    except Exception as e:
        print(f"[PID: {os.getpid()}] (Requests) 워커 오류: {video_id} | {e}")
        status = "error"
    finally:
        db_manager.close() # 워커 작업 완료 후 DB 연결 닫기
        return {"url": video_url, "status": status, "comment_count": comment_count}

def worker_process_entry(args):
    """
    각 프로세스의 시작점(entry-point)이 되는 동기 함수.
    엔진 선택에 따라 적절한 크롤러를 실행합니다.
    """
    video_id, engine_choice, keyword_id = args # engine_choice는 더 이상 사용되지 않지만, 인자 형태 유지를 위해 남겨둡니다.
    
    # Playwright 엔진을 사용하지 않으므로, requests 엔진을 바로 실행합니다.
    return run_request_engine_sync(video_id, keyword_id)
