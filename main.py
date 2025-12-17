import multiprocessing
import os
import sys
import time # time 모듈 추가

# core, utils 등 하위 모듈을 임포트할 수 있도록 프로젝트 루트를 sys.path에 추가
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(project_root)

from workers.worker_runner import worker_process_entry
from db_manager import DBManager

# search_engine 개발 완료 시 주석 해제
from core.search_engine import YouTubeSearcher

def main():
    """
    전체 크롤링 파이프라인을 조율하는 오케스트레이터
    """
    start_time = time.time() # 실행 시간 측정 시작

    keyword = input("검색할 유튜브 영상의 키워드를 입력하세요: ") # 사용자에게 키워드 입력 요청

    # --- DB 저장 로직 (1단계): 키워드 저장 ---
    db_manager = DBManager()
    keyword_id = db_manager.insert_keyword(keyword)
    # 메인 프로세스에서 사용한 DBManager는 키워드 삽입 후 역할을 다했으므로 연결을 닫아줍니다.
    # 각 워커 프로세스는 자신만의 DBManager 인스턴스를 생성하여 사용하게 됩니다.
    db_manager.close() 

    if keyword_id is None:
        print("데이터베이스에 키워드를 저장하는 데 실패했습니다. 프로그램을 종료합니다.")
        return
    print(f"키워드 '{keyword}'가 데이터베이스에 저장되었습니다 (ID: {keyword_id}).")

    target_engine = "requests" # Playwright 엔진을 사용하지 않으므로 requests로 고정
    print(f"크롤러 엔진이 '{target_engine}'으로 고정되었습니다.")

    target_crawl_count = 1
    
    # 1. 생산자: URL 후보 목록 확보
    searcher = YouTubeSearcher()
    videos_data = searcher.search(keyword, limit=50) 

    if not videos_data:
        print("크롤링할 후보 영상을 찾지 못했습니다. 프로그램을 종료합니다.")
        return

    print(f"\n--- 검색된 비디오 ID 목록 (총 {len(videos_data)}개) ---")
    for i, video in enumerate(videos_data, 1):
        print(f"{i}. {video.get('video_id', 'N/A')}")
    print("--------------------------------------------------\n")

    print(f"총 {len(videos_data)}개의 영상을 대상으로 크롤링을 시작합니다.")

    # 3. 소비자: 병렬 처리를 위한 작업 목록 준비 (keyword_id 추가)
    tasks_args = [(video['video_id'], target_engine, keyword_id) for video in videos_data]
    
    num_processes = min(len(videos_data), os.cpu_count(), 1) # 프로세스 수 최대 4개로 조정
    print(f"총 {len(videos_data)}개의 영상을 {num_processes}개의 프로세스로 병렬 크롤링합니다.")
    print(f"사용 엔진: {target_engine}")

    multiprocessing.set_start_method('spawn', force=True)
    
    successful_crawls = 0
    
    # 4. 프로세스 풀을 통해 작업 분배 및 결과 취합
    with multiprocessing.Pool(processes=num_processes) as pool:
        results_iterator = pool.imap_unordered(worker_process_entry, tasks_args)
        
        for result in results_iterator:
            if result["status"] == "success":
                successful_crawls += 1
                print(f"--- 성공: {successful_crawls}/{target_crawl_count} | {result['url']} ({result['comment_count']}개) ---")
            elif result["status"] == "skipped":
                print(f"--- 건너뜀: {result['url']} (필터 조건 미충족: 댓글 수) ---")
            else: # status == "error"
                print(f"--- 오류: {result['url']} ---")

            if successful_crawls >= target_crawl_count:
                print(f"\n목표치({target_crawl_count}개)에 도달했습니다. 나머지 작업을 중단합니다.")
                pool.terminate()
                break

    end_time = time.time() # 실행 시간 측정 종료
    total_time = end_time - start_time

    print("\n--- 최종 크롤링 작업 완료 ---")
    print(f"총 {successful_crawls}개의 영상에서 댓글 수집을 완료했습니다.")
    print(f"총 실행 시간: {total_time:.2f}초") # 실행 시간 출력

if __name__ == "__main__":
    main()