import multiprocessing
import os
import sys
import time
import logging
import pandas as pd
import asyncio # Add asyncio for running async functions

# core, utils 등 하위 모듈을 임포트할 수 있도록 프로젝트 루트를 sys.path에 추가
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(project_root)

from workers.worker_runner import worker_process_entry
from db_manager import DBManager
from core.search_engine import YouTubeSearcher
from utils.logger import get_timestamped_log_filename, setup_logger
from keyword_scraper import scrape_google_trends # Import the async scrape function

def process_keyword(keyword, logger, log_filename):
    """
    하나의 키워드에 대한 전체 크롤링 파이프라인을 실행합니다.
    """
    logger.info(f"[{keyword}] 키워드 처리 시작")
    keyword_start_time = time.time()

    # --- DB 저장 로직 (1단계): 키워드 저장 ---
    db_manager = DBManager()
    keyword_id, existed = db_manager.insert_keyword(keyword)
    db_manager.close() 

    if keyword_id is None:
        logger.error(f"[{keyword}] 키워드를 데이터베이스에 저장하는 데 실패했습니다. 다음 키워드로 넘어갑니다.")
        return
    
    if existed:
        logger.info(f"[{keyword}] 기존 키워드의 검색 시간을 최신화했습니다 (ID: {keyword_id}).")
    else:
        logger.info(f"[{keyword}] 신규 키워드를 데이터베이스에 저장했습니다 (ID: {keyword_id}).")

    target_engine = "requests"
    target_crawl_count = 1
    
    # 1. 생산자: URL 후보 목록 확보
    logger.info(f"[{keyword}] YouTube 영상 검색 중...")
    searcher = YouTubeSearcher()
    videos_data = searcher.search(keyword, limit=50) 

    if not videos_data:
        logger.warning(f"[{keyword}] 크롤링할 후보 영상을 찾지 못했습니다. 다음 키워드로 넘어갑니다.")
        return

    video_ids = [video.get('video_id', 'N/A') for video in videos_data]
    logger.info(f"[{keyword}] {len(video_ids)}개의 영상 탐색 완료: {video_ids}")

    # 3. 소비자: 병렬 처리를 위한 작업 목록 준비
    tasks_args = [(video['video_id'], target_engine, keyword_id, log_filename) for video in videos_data]
    
    num_processes = min(len(videos_data), os.cpu_count(), 4)
    logger.info(f"[{keyword}] {len(videos_data)}개의 영상을 {num_processes}개의 프로세스로 병렬 크롤링합니다.")
    
    multiprocessing.set_start_method('spawn', force=True)
    
    successful_crawls = 0
    
    # 4. 프로세스 풀을 통해 작업 분배 및 결과 취합
    with multiprocessing.Pool(processes=num_processes) as pool:
        results_iterator = pool.imap_unordered(worker_process_entry, tasks_args)
        
        for result in results_iterator:
            # 결과 로깅은 worker_runner에서 직접 수행
            if result["status"] == "success":
                successful_crawls += 1
            
            if successful_crawls >= target_crawl_count:
                logger.info(f"[{keyword}] 목표치({target_crawl_count}개)에 도달했습니다. 나머지 작업을 중단합니다.")
                pool.terminate()
                break
    
    keyword_end_time = time.time()
    logger.info(f"[{keyword}] 키워드 처리 종료 (총 실행 시간: {keyword_end_time - keyword_start_time:.2f}초, {successful_crawls}개 영상 성공)")


async def main():
    """
    CSV 파일에서 키워드를 읽어와 각 키워드에 대한 크롤링 파이프라인을 조율합니다.
    """
    log_filename = get_timestamped_log_filename()
    logger = setup_logger('main', log_filename)
    
    logger.info("="*30 + " 크롤링 실행 시작 " + "="*30)
    overall_start_time = time.time()

    try:
        # --- Step 1: Generate keyword CSV ---
        logger.info("구글 트렌드 키워드 스크래핑 시작...")
        try:
            await scrape_google_trends()
            logger.info("구글 트렌드 키워드 스크래핑 완료.")
        except Exception as e:
            logger.error(f"구글 트렌드 키워드 스크래핑 중 오류 발생: {e}", exc_info=True)
            if not os.path.exists('google_trends_kr_50.csv'):
                logger.critical("스크래핑 실패 및 기존 CSV 파일 없음. 프로그램을 종료합니다.")
                return

        # --- Step 2: Read keywords and process ---
        try:
            trends_df = pd.read_csv('google_trends_kr_50.csv', encoding='utf-8-sig')
            keywords = trends_df['검색어'].tolist()
            logger.info(f"'{'google_trends_kr_50.csv'}' 파일에서 {len(keywords)}개의 키워드 탐색 완료.")
        except FileNotFoundError:
            logger.critical("'google_trends_kr_50.csv' 파일을 찾을 수 없습니다. 프로그램을 종료합니다.")
            return

        for i, keyword in enumerate(keywords, 1):
            try:
                logger.info(f"--- 전체 진행률: {i}/{len(keywords)} ---")
                process_keyword(keyword, logger, log_filename)
            except Exception as e:
                logger.error(f"키워드 '{keyword}' 처리 중 예기치 않은 오류 발생. 다음 키워드로 넘어갑니다.", exc_info=True)

    except Exception as e:
        logger.critical(f"프로그램 실행 중 치명적인 오류 발생: {e}", exc_info=True)
    finally:
        overall_end_time = time.time()
        logger.info(f"총 실행 시간: {(overall_end_time - overall_start_time) / 60:.2f}분")
        logger.info("="*30 + " 크롤링 실행 종료 " + "="*30)


if __name__ == "__main__":
    asyncio.run(main()) # Run the async main function