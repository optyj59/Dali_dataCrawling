import time
import csv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def scrape_youtube_comments(video_url):
    # Chrome 옵션 설정
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-extensions")
    ##options.add_argument("--headless")  # 필요시 headless 모드를 제거하거나 변경하세요
    options.add_argument("--no-sandbox")  # 샌드박스 비활성화
    options.add_argument("--disable-dev-shm-usage")  # 리소스 사용 최적화
    options.add_argument("--disable-gpu")  # GPU 비활성화
    options.add_argument("start-maximized")  # 최대화
    options.add_argument("disable-infobars")  # 정보 표시줄 비활성화

    # ChromeDriver 실행 경로 설정
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    driver.get(video_url)

    # 영상이 완전히 로드될 때까지 기다리기
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-primary-info-renderer")))
    except:
        print("영상 로딩 실패")
        driver.quit()
        return []

    # 댓글 창이 로드될 때까지 기다리기
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-comment-view-model")))
    except:
        print("댓글 창 로딩 실패")
        driver.quit()
        return []

    comments_loaded = False
    while not comments_loaded:
        # 댓글 창까지 스크롤 내리기
        driver.execute_script("""
            window.scrollTo(0, document.documentElement.scrollHeight);
        """)

        # 댓글이 로드될 때까지 기다리기
        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-comment-view-model")))
            comments_loaded = True
        except:
            # 댓글이 로드되지 않으면 스크롤 계속 내리기
            print("🌀 댓글이 아직 로드되지 않았습니다. 스크롤 계속 진행...")
            time.sleep(3)

    # 댓글 요소 수집
    comments = driver.find_elements(By.CSS_SELECTOR, "ytd-comment-view-model")
    print(f"🔍 댓글 {len(comments)}개 수집 완료!")

    results = []
    for comment in comments:
        try:
            # 작성자
            author = comment.find_element(By.CSS_SELECTOR, "#author-text").text.strip()
        except:
            author = "Unknown"

        try:
            # 댓글 내용
            content = comment.find_element(By.CSS_SELECTOR, "#content").text.strip()
        except:
            content = ""

        results.append({
            "author": author,
            "content": content
        })

    # CSV로 저장
    with open('youtube_comments.csv', mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=["author", "content"])
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print("📂 댓글 데이터를 'youtube_comments.csv'에 저장했습니다.")
    driver.quit()

    return results


if __name__ == "__main__":
    video_url = "https://www.youtube.com/watch?v=ftQZo7XaTOA"
    comments = scrape_youtube_comments(video_url)
    for c in comments[:10]:  # 앞부분만 출력
        print(f"작성자: {c['author']}\n댓글: {c['content']}\n{'-'*50}")
