import psycopg2
from psycopg2 import extras
import os
import sys

# 프로젝트 루트를 sys.path에 추가하여 config 모듈을 임포트할 수 있도록 함
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(project_root)

# config.settings에서 DB 설정 가져오기 (아직 없으면 임시 설정)
try:
    from config.settings import DB_CONFIG
except ImportError:
    print("경고: config/settings.py에서 DB_CONFIG를 찾을 수 없습니다. 임시 설정을 사용합니다.")
    DB_CONFIG = {
        "host": "localhost",
        "database": "youtube_comments",
        "user": "your_user",
        "password": "your_password",
        "port": "5432"
    }

class DBManager:
    def __init__(self):
        self.conn = None
        self.db_config = DB_CONFIG
        print(f"DBManager 초기화. DB: {self.db_config['database']}")

    def connect(self):
        """데이터베이스에 연결합니다."""
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(**self.db_config)
                self.conn.autocommit = True  # 오토커밋 설정
                print("데이터베이스 연결 성공.")
            except psycopg2.Error as e:
                print(f"데이터베이스 연결 오류: {e}")
                self.conn = None
        return self.conn

    def close(self):
        """데이터베이스 연결을 닫습니다."""
        if self.conn and not self.conn.closed:
            self.conn.close()
            self.conn = None
            print("데이터베이스 연결 닫힘.")

    def insert_comments_batch(self, comments_data: list[dict]):
        """
        댓글 데이터를 COMMENT_MASTER 테이블에 일괄 삽입(Bulk Insert)합니다.
        
        comments_data 예시:
        [
            {
                'video_id': 'vid1', 'comment_id': 'cid1', 'author': 'author1',
                'content': 'content1', 'parent_comment_id': None, 'likes': '10',
                'created_time': '2023-01-01', 'collection_time': '2023-01-01 10:00:00',
                'valid_from_time': '2023-01-01 10:00:00', 'valid_to_time': None
            },
            ...
        ]
        """
        if not comments_data:
            print("삽입할 댓글 데이터가 없습니다.")
            return

        conn = self.connect()
        if not conn:
            print("DB 연결 실패로 댓글을 삽입할 수 없습니다.")
            return

        # 테이블 스키마에 맞게 필드명 확인 및 조정 필요
        # 예시 스키마: video_id, comment_id, author, content, parent_comment_id, likes, created_time, collection_time, valid_from_time, valid_to_time
        columns = comments_data[0].keys()
        
        # SQL VALUES 절 생성을 위한 플레이스홀더
        # 예: %s, %s, %s, ...
        values_placeholder = ','.join(['%s'] * len(columns))
        
        # INSERT 문
        insert_query = f"""
            INSERT INTO COMMENT_MASTER ({','.join(columns)})
            VALUES ({values_placeholder})
            ON CONFLICT (comment_id) DO NOTHING; -- 중복 시 삽입하지 않음 (스키마에 따라 ON CONFLICT 절은 변경될 수 있습니다)
        """
        
        # 데이터를 튜플 리스트로 변환
        data_to_insert = [tuple(comment[col] for col in columns) for comment in comments_data]

        try:
            with conn.cursor() as cursor:
                extras.execute_values(cursor, insert_query, data_to_insert, page_size=1000)
            print(f"{len(comments_data)}개의 댓글 데이터를 COMMENT_MASTER에 성공적으로 일괄 삽입했습니다.")
        except psycopg2.Error as e:
            print(f"댓글 데이터 일괄 삽입 오류: {e}")
            conn.rollback() # 오류 발생 시 롤백 (autocommit=True 일 경우 불필요할 수 있지만 안전을 위해)
        finally:
            self.close() # 작업 후 연결 닫기 (또는 커넥션 풀 사용 시 반환)

# 이 파일이 직접 실행될 때 테스트를 위한 코드 (스케폴딩)
if __name__ == "__main__":
    print("DBManager 테스트 시작...")
    db_manager = DBManager()

    # 테스트 데이터 (실제 댓글 데이터 구조와 일치해야 합니다)
    test_comments = [
        {
            'video_id': 'test_video_1',
            'comment_id': 'test_comment_1',
            'author': 'TestUser1',
            'content': 'This is a test comment 1.',
            'parent_comment_id': None,
            'likes': '5',
            'created_time': '2023-11-25',
            'collection_time': '2023-11-25 12:00:00',
            'valid_from_time': '2023-11-25 12:00:00',
            'valid_to_time': None
        },
        {
            'video_id': 'test_video_1',
            'comment_id': 'test_comment_2',
            'author': 'TestUser2',
            'content': 'This is a test comment 2, a reply.',
            'parent_comment_id': 'test_comment_1',
            'likes': '2',
            'created_time': '2023-11-25',
            'collection_time': '2023-11-25 12:01:00',
            'valid_from_time': '2023-11-25 12:01:00',
            'valid_to_time': None
        }
    ]

    # COMMENT_MASTER 테이블이 없으면 생성하는 예시 (실제 운영 환경에서는 DDL은 따로 관리)
    try:
        conn = db_manager.connect()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS COMMENT_MASTER (
                        video_id VARCHAR(255) NOT NULL,
                        comment_id VARCHAR(255) PRIMARY KEY,
                        author VARCHAR(255),
                        content TEXT,
                        parent_comment_id VARCHAR(255),
                        likes VARCHAR(50),
                        created_time VARCHAR(255),
                        collection_time TIMESTAMP WITH TIME ZONE,
                        valid_from_time TIMESTAMP WITH TIME ZONE,
                        valid_to_time TIMESTAMP WITH TIME ZONE
                    );
                """)
            print("COMMENT_MASTER 테이블 존재 확인 또는 생성 완료.")
    except Exception as e:
        print(f"테이블 생성 오류: {e}")
    finally:
        db_manager.close() # 테이블 생성 후 연결 닫기
    
    # 댓글 데이터 삽입 테스트
    db_manager.insert_comments_batch(test_comments)
    
    print("DBManager 테스트 완료.")
