import multiprocessing
import os
import sys
import time # time 모듈 추가
import pandas as pd

# core, utils 등 하위 모듈을 임포트할 수 있도록 프로젝트 루트를 sys.path에 추가
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(project_root)

from workers.worker_runner import worker_process_entry
from db_manager import DBManager

# search_engine 개발 완료 시 주석 해제
# search_engine 개발 완료 시 주석 해제
from core.search_engine import YouTubeSearcher

def process_keyword(keyword):
    """
    하나의 키워드에 대한 전체 크롤링 파이프라인을 실행합니다.
    """
    print(f"\n{'='*60}\n[시작] 키워드: '{keyword}'\n{'='*60}")
    keyword_start_time = time.time()

    # --- DB 저장 로직 (1단계): 키워드 저장 ---
    db_manager = DBManager()
    keyword_id = db_manager.insert_keyword(keyword)
    db_manager.close() 

    if keyword_id is None:
        print(f"키워드 '{keyword}'를 데이터베이스에 저장하는 데 실패했습니다. 다음 키워드로 넘어갑니다.")
        return
    print(f"키워드 '{keyword}'가 데이터베이스에 저장되었습니다 (ID: {keyword_id}).")

    target_engine = "requests"
    target_crawl_count = 1
    
    # 1. 생산자: URL 후보 목록 확보
    print(f"'{keyword}'에 대한 YouTube 영상 검색 중...")
    searcher = YouTubeSearcher()
    videos_data = searcher.search(keyword, limit=50) 

    if not videos_data:
        print("크롤링할 후보 영상을 찾지 못했습니다. 다음 키워드로 넘어갑니다.")
        return

    print(f"'{keyword}'에 대해 총 {len(videos_data)}개의 영상을 대상으로 크롤링을 시작합니다.")

    # 3. 소비자: 병렬 처리를 위한 작업 목록 준비
    tasks_args = [(video['video_id'], target_engine, keyword_id) for video in videos_data]
    
    num_processes = min(len(videos_data), os.cpu_count(), 4) # 프로세스 수 최대 4개로 조정
    print(f"총 {len(videos_data)}개의 영상을 {num_processes}개의 프로세스로 병렬 크롤링합니다.")
    
    multiprocessing.set_start_method('spawn', force=True)
    
    successful_crawls = 0
    
    # 4. 프로세스 풀을 통해 작업 분배 및 결과 취합
    with multiprocessing.Pool(processes=num_processes) as pool:
        results_iterator = pool.imap_unordered(worker_process_entry, tasks_args)
        
        for result in results_iterator:
            if result["status"] == "success":
                successful_crawls += 1
                print(f"--- 성공: {result['url']} ({result['comment_count']}개 댓글 수집)")
            elif result["status"] == "skipped":
                # 건너뛰는 경우는 너무 많을 수 있으므로 상세 로그는 주석 처리
                # print(f"--- 건너뜀: {result['url']} (필터 조건 미충족)")
                pass
            else: # status == "error"
                print(f"--- 오류: {result['url']} - {result.get('error_message', 'N/A')}")

            if successful_crawls >= target_crawl_count:
                print(f"\n키워드 '{keyword}'에 대한 목표치({target_crawl_count}개)에 도달했습니다. 나머지 작업을 중단합니다.")
                pool.terminate()
                break
    
    keyword_end_time = time.time()
    print(f"\n[종료] 키워드: '{keyword}' (총 실행 시간: {keyword_end_time - keyword_start_time:.2f}초, {successful_crawls}개 영상 성공)")


def main():
    """
    CSV 파일에서 키워드를 읽어와 각 키워드에 대한 크롤링 파이프라인을 조율합니다.
    """
    overall_start_time = time.time()
    
    try:
        trends_df = pd.read_csv('google_trends_kr_50.csv', encoding='utf-8-sig')
        keywords = trends_df['검색어'].tolist()
        print(f"'{'google_trends_kr_50.csv'}' 파일에서 {len(keywords)}개의 키워드를 읽었습니다.\n")
    except FileNotFoundError:
        print("'google_trends_kr_50.csv' 파일을 찾을 수 없습니다. 먼저 keyword.py를 실행하여 파일을 생성해주세요.")
        return

    for i, keyword in enumerate(keywords, 1):
        print(f"--- 전체 진행률: {i}/{len(keywords)} ---")
        process_keyword(keyword)

    overall_end_time = time.time()
    print(f"\n{'='*60}\n[전체 작업 완료]\n총 실행 시간: {(overall_end_time - overall_start_time) / 60:.2f}분\n{'='*60}")

if __name__ == "__main__":
    main()