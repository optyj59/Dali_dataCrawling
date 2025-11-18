import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re
import csv
from datetime import datetime
import os

class CrawlerEngine:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None

    async def initialize(self):
        print("Playwright를 초기화합니다...")
        # headless=False로 설정하여 브라우저 동작을 눈으로 확인할 수 있습니다. (디버깅 용이)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=False)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        print("Playwright 초기화 완료.")
 
    async def get_video_metadata(self, video_url: str):
        """
        영상 페이지에서 메타데이터 (조회수, 댓글 수 등)를 추출합니다.
        """
        print(f"영상 메타데이터 수집 중: {video_url}")
        await self.page.goto(video_url)
        await self.page.wait_for_load_state('networkidle')

        # 페이지를 약간 아래로 스크롤하여 댓글 섹션 로드를 유도합니다.
        await self.page.evaluate("window.scrollTo(0, 500)")
        
        # 댓글 섹션의 핵심 요소가 나타날 때까지 대기
        try:
            await self.page.wait_for_selector("ytd-comments-header-renderer .count-text", timeout=10000)
        except Exception:
            print("경고: 댓글 섹션 로드에 실패했습니다.")

        # Beautiful Soup 파싱을 위한 HTML 콘텐츠 추출
        html_content = await self.page.content()
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- 메타데이터 추출 로직 (이전 코드 유지) ---
        def parse_count(text):
            text = text.lower().replace(',', '')
            text = re.sub(r'(views|조회수|댓글)\s*', '', text)
            value = re.search(r'[\d,.]+', text)
            if not value: return 0
            value = value.group()
            
            if 'k' in text or '천' in text: return int(float(value) * 1000)
            if 'm' in text or '백만' in text: return int(float(value) * 1000000)
            if '만' in text: return int(float(value) * 10000)
            try: return int(float(value))
            except ValueError: return 0
            
        view_count_text = '0'
        tooltip_element = soup.select_one('tp-yt-paper-tooltip.ytd-watch-info-text')
        if tooltip_element:
            tooltip_content = tooltip_element.select_one('#tooltip')
            if tooltip_content:
                tooltip_text = tooltip_content.text.strip()
                match = re.search(r'조회수 ([\d,]+)회', tooltip_text)
                if match: view_count_text = match.group(1)

        upload_date_element = soup.select_one('meta[itemprop="uploadDate"]')
        upload_date_text = upload_date_element['content'] if upload_date_element and 'content' in upload_date_element.attrs else ''
        
        comment_count_text = '0'
        count_element = soup.select_one("ytd-comments-header-renderer .count-text")
        if count_element:
            comment_count_text = count_element.text
        # --- 메타데이터 추출 로직 끝 ---
        
        metadata = {
            'upload_date': upload_date_text,
            'view_count': parse_count(view_count_text),
            'comment_count': parse_count(comment_count_text)
        }
        return metadata

    async def extract_comments(self, video_url: str):
        """
        초고속 / 안정 완전수집 버전 (reply 증가량 기반 종료)
        1) 모든 top-level thread 로딩 (stall 기반)
        2) reply 버튼을 전역에서 모두 클릭하되,
           reply DOM 증가량이 0이면 즉시 종료
        3) HTML 파싱
        """

        print(f"[INFO] 시작: 댓글 수집 (reply 증가량 기반 완전수집) {video_url}")

        if self.page.url != video_url:
            await self.page.goto(video_url, wait_until="load")

        # 초기 스크롤
        await self.page.evaluate("window.scrollTo(0, 600)")
        await self.page.wait_for_selector("ytd-comment-thread-renderer", timeout=20000)
        print("[INFO] 댓글 섹션 로드 완료")

        # ---------------------------------------------------
        # STEP 1 — 스크롤해 전체 top-level thread 로딩
        # ---------------------------------------------------
        print("[INFO] STEP 1: 최상위 댓글 로딩 시작")

        stall = 0
        STALL_LIMIT = 5

        while True:
            prev_count = await self.page.evaluate(
                "document.querySelectorAll('ytd-comment-thread-renderer').length"
            )

            await self.page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await asyncio.sleep(1.2)

            new_count = await self.page.evaluate(
                "document.querySelectorAll('ytd-comment-thread-renderer').length"
            )

            if new_count == prev_count:
                stall += 1
                print(f"[SCROLL] thread 증가 없음 (stall {stall}/{STALL_LIMIT})")
            else:
                stall = 0
                print(f"[SCROLL] thread 증가: {new_count}")

            if stall >= STALL_LIMIT:
                print("[INFO] 최상위 댓글 완전 로드 완료")
                break

        # ---------------------------------------------------
        # STEP 2 — [실험] 단일 실행(Single-pass)으로 reply 열기
        # ---------------------------------------------------
        print("\n[INFO] STEP 2: 단일 실행으로 reply 열기 시작")

        # 1. 아직 열리지 않은 '답글 보기' 버튼 찾기
        initial_reply_buttons = await self.page.query_selector_all(
            "ytd-comment-thread-renderer:has(ytd-comment-replies-renderer[hidden]) #more-replies:not([disabled])"
        )

        # 2. 이미 열린 섹션 내부의 '답글 더보기' 버튼 찾기
        more_reply_buttons = await self.page.query_selector_all(
            "ytd-comment-replies-renderer:not([hidden]) #more-replies:not([disabled])"
        )

        candidate_buttons = initial_reply_buttons + more_reply_buttons
        print(f"[REPLIES] 클릭 후보 버튼 {len(candidate_buttons)}개 발견")

        buttons_to_click = []
        # 텍스트 필터링으로 '숨기기' 버튼 제외
        for btn in candidate_buttons:
            try:
                btn_text = await btn.inner_text()
                if '숨기기' not in btn_text and 'Hide' not in btn_text:
                    buttons_to_click.append(btn)
            except Exception:
                # 버튼이 사라지는 등의 예외 상황 처리
                pass

        if not buttons_to_click:
            print("[INFO] 클릭할 답글 버튼이 없습니다.")
        else:
            print(f"[REPLIES] 실제 클릭할 버튼 {len(buttons_to_click)}개 필터링 완료")

            # 필터링된 버튼들 클릭
            for btn in buttons_to_click:
                try:
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    await asyncio.sleep(0.1)
                except Exception as e:
                    print(f"[WARN] 버튼 클릭 중 오류 발생 (무시): {e}")
                    pass

            # 답글이 렌더링될 시간을 충분히 줌
            print("[REPLIES] 모든 버튼 클릭 완료. 5초간 최종 렌더링 대기...")
            await asyncio.sleep(5)

        print("[REPLIES] 단일 실행 완료. HTML 파싱으로 넘어갑니다.")

        # ---------------------------------------------------
        # STEP 3 — HTML 파싱
        # ---------------------------------------------------
        print("\n[INFO] STEP 3: HTML 파싱 시작")

        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")

        comments = []
        processed_ids = set()

        # top-level + replies 모두 파싱
        for thread in soup.select("ytd-comment-thread-renderer"):

            # -------- top-level --------
            top = thread.select_one("ytd-comment-view-model")
            if top:
                time_link = top.select_one('#published-time-text a')
                href = time_link.get('href') if time_link else None
                cid, pid = None, None

                if href:
                    m = re.search(r'&lc=([\w.-]+)', href)
                    if m:
                        fid = m.group(1)
                        if '.' in fid:
                            pid, cid = fid.split('.', 1)
                        else:
                            cid = fid

                if cid and cid not in processed_ids:
                    comments.append({
                        "id": cid,
                        "parent_id": pid,
                        "author": (top.select_one("#author-text") or {}).text.strip(),
                        "content": (top.select_one("#content-text") or {}).text.strip(),
                        "likes": (top.select_one("#vote-count-middle") or {}).text.strip() or "0",
                        "created_time": time_link.text.strip() if time_link else "",
                    })
                    processed_ids.add(cid)

            # -------- replies --------
            for reply in thread.select("ytd-comment-replies-renderer ytd-comment-view-model"):
                time_link = reply.select_one('#published-time-text a')
                href = time_link.get('href') if time_link else None
                rid, pid = None, None

                if href:
                    m = re.search(r'&lc=([\w.-]+)', href)
                    if m:
                        fid = m.group(1)
                        if '.' in fid:
                            pid, rid = fid.split('.', 1)
                        else:
                            rid = fid

                if rid and rid not in processed_ids:
                    comments.append({
                        "id": rid,
                        "parent_id": pid,
                        "author": (reply.select_one("#author-text") or {}).text.strip(),
                        "content": (reply.select_one("#content-text") or {}).text.strip(),
                        "likes": (reply.select_one("#vote-count-middle") or {}).text.strip() or "0",
                        "created_time": time_link.text.strip() if time_link else "",
                    })
                    processed_ids.add(rid)

        print(f"[INFO] 총 수집된 댓글 수(답글 포함): {len(comments)}")
        return comments


    def mask_pii(self, text: str) -> str:
        """
        간단한 PII 마스킹을 적용합니다. (이메일, 전화번호)
        """
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_MASKED]', text)
        text = re.sub(r'\d{2,3}-\d{3,4}-\d{4}', '[PHONE_MASKED]', text)
        return text

    async def close(self):
        print("Playwright를 종료합니다...")
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("Playwright 종료 완료.")

async def main():
    crawler = CrawlerEngine()
    video_url = "https://www.youtube.com/watch?v=ftQZo7XaTOA&t=1231s" # 테스트 영상 URL
    
    try:
        await crawler.initialize()
        
        metadata = await crawler.get_video_metadata(video_url)
        
        print("\n--- 영상 메타데이터 ---")
        print(f"URL: {video_url}")
        print(f"조회수: {metadata['view_count']}, 댓글 수: {metadata['comment_count']}")

        # 저희의 필터 조건(조회수 100회 이상, 댓글 5개 이상)이 충족되는지 확인한다고 가정
        if metadata['view_count'] >= 100 and metadata['comment_count'] >= 5:
            print("\n[조건 충족] 댓글 수집을 시작합니다...")
            comments = await crawler.extract_comments(video_url)
            
            if comments:
                print(f"\n--- 최종 수집된 댓글 ({len(comments)}개) ---")
                for i, comment in enumerate(comments[:5]):
                    print(f"ID: {comment['id']}, Parent ID: {comment['parent_id']}, 작성자: {comment['author']}, 좋아요: {comment['likes']}, 작성시간: {comment['created_time']}, 내용: {comment['content'][:30]}...")

                # --- CSV 저장 로직 ---
                video_id = video_url.split('v=')[-1]
                collection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # 스크립트 파일의 위치를 기준으로 프로젝트 루트 경로를 계산
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
                
                # 저장할 파일 경로를 절대 경로로 지정
                output_path = os.path.join(project_root, "data", "comments_raw.csv")
                
                # 저장할 데이터 가공
                save_data = []
                for comment in comments:
                    save_data.append({
                        'video_id': video_id,
                        'comment_id': comment['id'],
                        'parent_comment_id': comment['parent_id'],
                        'author': comment['author'],
                        'content': comment['content'],
                        'likes': comment['likes'],
                        'created_time': comment['created_time'],
                        'collection_time': collection_time
                    })

                # CSV 파일에 저장
                try:
                    # 파일 저장 전 디렉터리 존재 확인 및 생성
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)

                    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
                        # 헤더는 저장할 데이터의 key 값들을 사용
                        writer = csv.DictWriter(f, fieldnames=save_data[0].keys(), quoting=csv.QUOTE_MINIMAL)
                        writer.writeheader()
                        writer.writerows(save_data)
                    print(f"\n성공: 수집된 댓글 {len(save_data)}개를 '{output_path}'에 저장했습니다.")
                except Exception as e:
                    print(f"\n오류: CSV 파일 저장에 실패했습니다. ({e})")
                # --- CSV 저장 로직 끝 ---

            else:
                print("\n수집된 댓글이 없습니다.")
            
        else:
            print("\n[조건 미충족] 댓글을 수집하지 않습니다.")

    except Exception as e:
        print(f"\n치명적인 오류 발생: {e}")
        
    finally:
        await crawler.close()

if __name__ == "__main__":
    asyncio.run(main())