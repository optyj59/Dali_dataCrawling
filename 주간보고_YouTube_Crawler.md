# 주간 보고서 - YouTube 댓글 크롤러 개발 현황

## 1. 보고 기간
2025년 11월 18일 ~ 2025년 11월 20일 (현재까지)

## 2. 프로젝트 목표
사용자가 발음 영상이나 녹음본을 보내면 AI가 분석하여 개선안을 제공하는 발음 교정 서비스의 일환으로, YouTube 영상의 댓글 데이터를 효율적이고 안정적으로 수집하는 시스템 구축.

## 3. 주요 진행 내용

### 3.1. 크롤링 로직 강건성 확보 (댓글 및 답글 수집)
*   **초기 문제점 분석:** `crawler_engine.py`의 답글 수집 루프가 '답글 보기'와 '답글 숨기기' 버튼을 구분하지 못해 무한 루프에 빠지거나 비효율적으로 작동하는 문제점 파악.
*   **다양한 해결 시도:**
    *   버튼 텍스트 기반 필터링 (`"숨기기"` 제외)
    *   `hidden` 속성 및 `:has()` 셀렉터를 활용한 정교한 버튼 식별
    *   단일 실행(Single-pass) 실험을 통한 문제 진단
    *   `aria-label="답글 더보기"` 속성 활용 시도 (YouTube 구조 변경으로 인한 실패)
*   **최종 적용 로직:**
    *   `crawler_engine.py` 내 `extract_comments` 메서드를 **2단계 접근법**으로 재구성.
    *   **1단계:** `ytd-comment-thread-renderer:has(ytd-comment-replies-renderer[hidden])` 셀렉터를 사용하여 닫힌 답글 섹션의 '답글 보기' 버튼을 일괄 클릭하여 초기 확장.
    *   **2단계:** `ytd-comment-replies-renderer:not([hidden]) ytd-continuation-item-renderer button` 셀렉터를 사용하여 이미 열린 답글 섹션 내의 '답글 더보기' 버튼을 반복적으로 클릭하여 모든 답글 로드.
    *   각 단계별 충분한 `asyncio.sleep` 대기 시간을 확보하여 DOM 안정화 및 렌더링 대기.
    *   (사용자 직접 수정으로 최종 로직 완성)

### 3.2. 병렬 처리 아키텍처 구현
*   **`asyncio` 기반 동시성 vs `multiprocessing` 기반 병렬 처리 논의:** 사용자 요구사항에 맞춰 `multiprocessing`을 통한 진정한 병렬 처리로 전환 결정.
*   **`main.py` (감독관) 역할 구현:**
    *   `multiprocessing.Pool`을 사용하여 여러 워커 프로세스 생성 및 관리.
    *   `pool.imap_unordered`를 통해 작업(URL)을 워커에게 동적으로 할당하고, 작업 완료 순서대로 결과 수신.
    *   필터 조건을 통과한 영상이 목표치(10개)에 도달하면, 나머지 작업을 즉시 중단하고 종료하는 로직 구현.
*   **`workers/worker_runner.py` (일꾼) 역할 구현:**
    *   각 워커 프로세스의 시작점(`worker_process_entry`) 정의.
    *   `asyncio.run()`을 사용하여 각 프로세스 내에서 `Playwright` 기반의 비동기 크롤링 로직(`run_crawl_async`) 실행.
    *   `run_crawl_async` 내에서 `crawler_engine.py`의 `get_video_metadata`를 이용한 필터링 로직 구현.
    *   필터 통과 시 `extract_comments` 실행, 결과 보고.
*   **CPU 점유율 100% 이슈 논의:** 멀티프로세싱의 목적이 '전체 작업 시간 단축'에 있음을 설명하고, 100% CPU 점유율은 정상적인 작동의 결과임을 확인.

### 3.3. 프로젝트 폴더 구조 개선
*   `log.txt`에 제시된 모듈화된 폴더 구조(`config`, `core`, `workers`, `utils`, `output` 등) 적용.
*   기존 파일(`crawler_engine.py`, `config.py`, `utils.py`)을 새 구조에 맞게 이동 및 파일명 변경.
*   `output/raw`, `output/cleaned`, `output/debug/html_dump` 등 세부 출력 폴더 생성.
*   `main.py` 및 `core/crawler_engine.py` 내 임포트 경로 및 CSV 저장 경로를 새 구조에 맞게 수정 완료.

### 3.4. `core/search_engine.py` 개발 보류
*   `requests` + `BeautifulSoup` 기반의 YouTube 검색 및 URL 추출 기능 개발은 현재 보류 중.
*   `main.py`에 해당 기능의 임포트 및 사용 코드를 주석 처리된 형태로 반영하여, 개발 완료 시 즉시 활용 가능하도록 준비.

## 4. 성과
*   YouTube 댓글 및 답글을 안정적으로 수집하는 `crawler_engine` 로직 확보.
*   `multiprocessing`을 활용한 효율적인 병렬 크롤링 시스템의 핵심 구조 구축.
*   모듈화된 프로젝트 구조를 통해 향후 유지보수 및 기능 확장이 용이하도록 기반 마련.

## 5. 이슈 및 향후 계획

*   **`core/search_engine.py` 개발 및 안정화:** 현재 보류 중인 `requests` + `BeautifulSoup` 기반의 YouTube 검색 및 URL 추출 기능 개발을 완료하고 안정화해야 함. (YouTube 페이지 구조 변경에 대한 강건성 확보 필요)
*   **나머지 유틸리티 모듈 구현:** `utils/logger.py`, `utils/file_utils.py`, `core/html_parser.py`, `config/settings.py` 등 `log.txt`에 명시된 나머지 모듈들을 구현하여 시스템 완성도 높이기.
*   **'Top-level 전용 크롤러 엔진' 구현:** `crawler_engine.py` 내에 답글을 수집하지 않고 최상위 댓글만 수집하는 별도의 엔진 함수 구현.
*   **성능 측정 및 주간 보고 준비:** 구현된 두 가지 엔진(답글 포함/Top-level)의 병렬 처리 성능을 측정하고, 최종 주간 보고서 작성.
