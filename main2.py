from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from pydantic import BaseModel, validator
from datetime import datetime
from passlib.context import CryptContext
import re

# ================= 0. 보안 및 암호화 설정 =================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ================= 1. 데이터베이스(SQLite) 설정 =================
DATABASE_URL = "sqlite:///./schools.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class School(Base):
    __tablename__ = "schools"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    lat = Column(Float)
    lng = Column(Float)
    address = Column(String)  
    region = Column(String, index=True)   

class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    school_name = Column(String, index=True)
    username = Column(String, index=True)  # 👈 [추가] 수정/삭제 권한 확인용 작성자 ID
    content = Column(String)
    rating_school = Column(Integer)  # 학교평가지수
    rating_love = Column(Integer)    # 사랑지수
    created_at = Column(String)

class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True, index=True)  # 아이디
    password = Column(String)                                # 암호화된 비밀번호
    nickname = Column(String, unique=True, index=True)       # 👈 [추가] 유저 닉네임
    has_written_review = Column(Boolean, default=False)      # 최소 1개 리뷰 작성 여부

Base.metadata.create_all(bind=engine)

# ================= 2. CSV 데이터를 가공하여 DB에 최초 등록 =================
# db = SessionLocal()
# if db.query(School).count() == 0:
#     print("⏳ 데이터베이스에 주소 정보를 포함한 전국 '초등학교' 데이터를 등록 중입니다...")
#     df = pd.read_csv("schools.csv", encoding="cp949").dropna(subset=["학교명", "위도", "경도"])
#     df = df[df["학교명"].str.endswith("초등학교")]
    
#     addr_col = "소재지도로명주소" if "소재지도로명주소" in df.columns else ("도로명주소" if "도로명주소" in df.columns else "주소")
    
#     for index, row in df.iterrows():
#         full_address = str(row[addr_col]) if addr_col in df.columns else "주소 정보 없음"
#         region_name = full_address.split()[0] if full_address != "주소 정보 없음" else "미분류"
        
#         db_school = School(
#             name=row["학교명"],
#             lat=float(row["위도"]),
#             lng=float(row["경도"]),
#             address=full_address,
#             region=region_name
#         )
#         db.add(db_school)
#     db.commit()
#     print(f"✅ 총 {db.query(School).count()}개의 초등학교 및 주소 데이터 등록 완료!")
# db.close()

# ================= 3. FastAPI 서버 및 통로(API) 설정 =================
app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# 바이트 수 계산 함수 (한글 2바이트, 영문/숫자 1바이트)
def get_byte_length(text: str) -> int:
    length = 0
    for char in text:
        if re.match(r'[ㄱ-ㅣ가-힣]', char):
            length += 2
        else:
            length += 1
    return length

# 프론트엔드 데이터 형식 정의
class ReviewCreate(BaseModel):
    school_name: str
    content: str
    rating_school: int  
    rating_love: int 
    username: str 

class ReviewUpdate(BaseModel):
    content: str
    rating_school: int
    rating_love: int
    username: str  # 본인 검증용

class ReviewDelete(BaseModel):
    username: str  # 본인 검증용

class UserSignup(BaseModel):
    username: str
    password: str
    nickname: str

class UserLogin(BaseModel):
    username: str
    password: str

# [통로 1] 화면 범위 내의 학교 목록 조회
@app.get("/api/schools")
def get_schools(min_lat: float, max_lat: float, min_lng: float, max_lng: float):
    db = SessionLocal()
    query_result = db.query(School).filter(
        School.lat >= min_lat, School.lat <= max_lat,
        School.lng >= min_lng, School.lng <= max_lng
    ).all()
    
    school_list = [{"name": s.name, "lat": s.lat, "lng": s.lng, "address": s.address} for s in query_result]
    db.close()
    return school_list

# [통로 2] 학교 이름 실시간 검색 API
@app.get("/api/schools/search")
def search_schools(keyword: str = Query(..., min_length=1)):
    db = SessionLocal()
    results = db.query(School).filter(School.name.like(f"%{keyword}%")).limit(20).all()
    
    search_list = []
    for s in results:
        search_list.append({
            "name": s.name,
            "lat": s.lat,
            "lng": s.lng,
            "address": s.address,
            "region": s.region
        })
    db.close()
    return search_list

# [통로 3] 사용자가 쓴 리뷰를 DB에 저장하고, 유저 권한 잠금을 해제합니다.
@app.post("/api/reviews")
def create_review(review_data: ReviewCreate):
    db = SessionLocal()
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    new_review = Review(
        school_name=review_data.school_name,
        username=review_data.username,  # 작성자 등록
        content=review_data.content,
        rating_school=review_data.rating_school,  
        rating_love=review_data.rating_love,      
        created_at=current_date
    )
    db.add(new_review)
    
    user = db.query(User).filter(User.username == review_data.username).first()
    if user:
        user.has_written_review = True
        
    db.commit()
    db.close()
    return {"message": "리뷰 등록 완료"}

# [통로 4] 특정 학교의 리뷰 목록 및 평균 별점 가져오기
@app.get("/api/reviews")
def get_reviews(school_name: str):
    db = SessionLocal()
    reviews = db.query(Review).filter(Review.school_name == school_name).all()
    
    review_list = []
    total_school = 0
    total_love = 0
    
    for r in reviews:
        total_school += r.rating_school
        total_love += r.rating_love
        
        # 작성자 아이디를 기반으로 닉네임 조회 기본값은 '익명'
        user_info = db.query(User).filter(User.username == r.username).first()
        author_nickname = user_info.nickname if user_info else "익명"

        review_list.append({
            "id": r.id, 
            "username": r.username, # 프론트엔드에서 수정/삭제 버튼 노출 여부 판단용
            "nickname": author_nickname, # 화면에 뿌려줄 익명 닉네임
            "content": r.content, 
            "rating_school": r.rating_school,  
            "rating_love": r.rating_love,      
            "date": r.created_at
        })
    
    count = len(reviews)
    avg_school = round(total_school / count, 2) if count > 0 else 0.0
    avg_love = round(total_love / count, 2) if count > 0 else 0.0
    
    db.close()
    return {
        "average_school": avg_school,  
        "average_love": avg_love,      
        "reviews": review_list
    }

# 🌟 [통로 4-2] 리뷰 수정 API
@app.put("/api/reviews/{review_id}")
def update_review(review_id: int, review_data: ReviewUpdate):
    db = SessionLocal()
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        db.close()
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    if review.username != review_data.username:
        db.close()
        raise HTTPException(status_code=403, detail="본인이 작성한 리뷰만 수정할 수 있습니다.")
    
    review.content = review_data.content
    review.rating_school = review_data.rating_school
    review.rating_love = review_data.rating_love
    db.commit()
    db.close()
    return {"message": "리뷰가 성공적으로 수정되었습니다."}

# 🌟 [통로 4-3] 리뷰 삭제 API
@app.post("/api/reviews/{review_id}/delete")
def delete_review(review_id: int, review_data: ReviewDelete):
    db = SessionLocal()
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        db.close()
        raise HTTPException(status_code=404, detail="리뷰를 찾을 수 없습니다.")
    if review.username != review_data.username:
        db.close()
        raise HTTPException(status_code=403, detail="본인이 작성한 리뷰만 삭제할 수 있습니다.")
    
    username = review.username
    db.delete(review)
    db.commit()
    
    # 만약 유저가 작성한 리뷰가 이제 하나도 없다면 잠금 상태 해제 취소
    remaining = db.query(Review).filter(Review.username == username).count()
    if remaining == 0:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user.has_written_review = False
            db.commit()
            
    db.close()
    return {"message": "리뷰가 성공적으로 삭제되었습니다.", "has_written_review": remaining > 0}

# [통로 5] 회원가입 API (닉네임 글자 수 유효성 검사 적용)
@app.post("/api/signup")
def signup(user_data: UserSignup):
    db = SessionLocal()
    
    # 1. 아이디 중복 체크
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        db.close()
        raise HTTPException(status_code=400, detail="이미 존재하는 아이디입니다.")
        
    # 2. 닉네임 중복 체크
    existing_nick = db.query(User).filter(User.nickname == user_data.nickname).first()
    if existing_nick:
        db.close()
        raise HTTPException(status_code=400, detail="이미 존재하는 닉네임입니다.")
    
    # 3. 🌟 닉네임 바이트 수 유효성 검사 (한글 최대 6자, 영문 최대 12자 교차 매칭)
    nick_len = get_byte_length(user_data.nickname.strip())
    if nick_len < 2 or nick_len > 12:
        db.close()
        raise HTTPException(status_code=400, detail="닉네임 길이를 확인해 주세요. (한글 최대 6자, 영문/숫자 최대 12자)")

    hashed_password = pwd_context.hash(clean_password)
    new_user = User(
        username=user_data.username,
        password=hashed_password,
        nickname=user_data.nickname.strip(),
        has_written_review=False 
    )
    db.add(new_user)
    db.commit()
    db.close()
    return {"message": "회원가입 성공"}

# [통로 6] 로그인 API
@app.post("/api/login")
def login(user_data: UserLogin):
    db = SessionLocal()
    user = db.query(User).filter(User.username == user_data.username).first()
    
    if not user or not pwd_context.verify(user_data.password, user.password):
        db.close()
        raise HTTPException(status_code=400, detail="아이디 또는 비밀번호가 일치하지 않습니다.")
    
    auth_info = {
        "username": user.username,
        "nickname": user.nickname,
        "has_written_review": user.has_written_review
    }
    db.close()
    return {"message": "로그인 성공", "user": auth_info}