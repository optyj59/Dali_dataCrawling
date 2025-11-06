import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

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
        2단계 대기 로직을 사용하여 댓글의 초기 배치를 안정적으로 추출합니다.
        1. 댓글 전체를 감싸는 컨테이너(`ytd-comments#comments`)가 나타날 때까지 대기합니다.
        2. 컨테이너가 나타나면, 그 안에서 첫 번째 댓글 스레드(`ytd-comment-thread-renderer`)가 렌더링될 때까지 대기합니다.
        """
        print(f"댓글 수집 시작: {video_url}")
        if self.page.url != video_url:
            await self.page.goto(video_url, wait_until="load")

        try:
            # 페이지를 약간 아래로 스크롤하여 댓글 섹션 로드를 유도
            await self.page.evaluate("window.scrollTo(0, 500)")

            # 1단계: 댓글의 메인 컨테이너(`ytd-comments#comments`)가 표시될 때까지 대기
            print("1단계: 댓글 메인 컨테이너(ytd-comments#comments)를 기다립니다...")
            comments_container_selector = "ytd-comments#comments"
            await self.page.wait_for_selector(comments_container_selector, state="visible", timeout=15000)
            print("=> 1단계 성공: 메인 컨테이너 확인.")

            # 2단계: 첫 번째 댓글 스레드(`ytd-comment-thread-renderer`)가 렌더링될 때까지 대기
            print("2단계: 첫 댓글 스레드(ytd-comment-thread-renderer) 렌더링을 기다립니다...")
            first_comment_selector = "ytd-comment-thread-renderer"
            await self.page.wait_for_selector(first_comment_selector, state="visible", timeout=15000)
            print("=> 2단계 성공: 첫 댓글 확인. 파싱을 시작합니다.")

            # 잠시 후 DOM이 안정화될 시간을 줌
            await asyncio.sleep(1)

            html_content = await self.page.content()
            soup = BeautifulSoup(html_content, 'html.parser')

            comments = []
            processed_comment_ids = set()

            # `ytd-comment-thread-renderer`를 기준으로 파싱
            for thread in soup.select("ytd-comment-thread-renderer"):
                comment_view = thread.select_one("ytd-comment-view-model")
                if not comment_view: continue

                time_link = comment_view.select_one('#published-time-text a')
                if not time_link or not time_link.get('href'): continue
                
                href = time_link['href']
                match = re.search(r'&lc=([\w.-]+)', href)
                if not match: continue
                comment_id = match.group(1)

                if comment_id in processed_comment_ids: continue

                author_text_element = comment_view.select_one("#author-text")
                content_text_element = comment_view.select_one("#content-text")
                like_count_element = comment_view.select_one("#vote-count-middle")

                if not author_text_element or not content_text_element: continue

                comments.append({
                    'id': comment_id,
                    'author': self.mask_pii(author_text_element.text.strip()),
                    'content': self.mask_pii(content_text_element.text.strip()),
                    'likes': like_count_element.text.strip() if like_count_element else '0'
                })
                processed_comment_ids.add(comment_id)

            print(f"총 {len(comments)}개의 댓글을 초기 배치에서 수집했습니다.")
            return comments

        except Exception as e:
            print(f"오류: 새로운 2단계 대기 로직 실행 중 문제가 발생했습니다. ({e})")
            print("디버깅을 위해 현재 페이지의 HTML을 'src/debug_page_content.html'에 저장합니다.")
            html_content = await self.page.content()
            with open("src/debug_page_content.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            return []

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
    video_url = "https://www.youtube.com/watch?v=ftQZo7XaTOA" # 테스트 영상 URL
    
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
            
            print("\n--- 최종 수집된 댓글 샘플 ---")
            if comments:
                for i, comment in enumerate(comments[:5]):
                    print(f"ID: {comment['id']}, 좋아요: {comment['likes']}, 내용: {comment['content'][:50]}...")
            else:
                print("수집된 댓글이 없습니다.")
            
        else:
            print("\n[조건 미충족] 댓글을 수집하지 않습니다.")

    except Exception as e:
        print(f"\n치명적인 오류 발생: {e}")
        
    finally:
        await crawler.close()

if __name__ == "__main__":
    asyncio.run(main())