import uvicorn
import datetime
from fastapi import FastAPI, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, or_, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# 1. База данных
DB_URL = "sqlite:///./users.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)
    number = Column(Integer, unique=True)
    password = Column(String)
    adders = Column(String)
    avatar = Column(String)


class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True, index=True)
    user1_id = Column(Integer, ForeignKey("users.id"))
    user2_id = Column(Integer, ForeignKey("users.id"))


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    text = Column(String)
    timestamp = Column(String)


Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- МАРШРУТЫ ---

@app.get('/')
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get('/login_page')
def login_page(request: Request):
    return templates.TemplateResponse('login.html', {"request": request})


@app.post('/register')
def register(
        username: str = Form(...),
        number: int = Form(...),
        adders: str = Form(...),
        avatar: str = Form(...),
        password: str = Form(...),
        db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.number == number).first()
    if existing:
        return {"error": "Пользователь с таким номером уже существует"}

    new_user = User(username=username, number=number, adders=adders, avatar=avatar, password=password)
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/login_page", status_code=303)


@app.post('/login')
def login(username: str = Form(...), number: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    check = db.query(User).filter(User.username == username, User.password == password, User.number == number).first()
    if not check:
        return RedirectResponse('/login_page', status_code=303)

    response = RedirectResponse('/profile', status_code=303)
    response.set_cookie(key="user_id", value=str(check.id))
    return response


@app.get('/profile')
def profile_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return RedirectResponse("/login_page", status_code=303)

    return templates.TemplateResponse("profile.html", {"request": request, "user": user})


@app.get('/logout')
def logout():
    response = RedirectResponse(url="/login_page", status_code=303)
    response.delete_cookie("user_id")
    return response


@app.get('/add_number_page')
def add_number_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    return templates.TemplateResponse("add_number.html", {"request": request, "user": user})


@app.post('/add_number')
def add_number(request: Request, number: str = Form(...), db: Session = Depends(get_db)):
    current_user_id = request.cookies.get("user_id")
    if not current_user_id:
        return RedirectResponse('/login_page', status_code=303)

    current_user_id = int(current_user_id)
    target_user = db.query(User).filter(User.number == number).first()

    if not target_user or target_user.id == current_user_id:
        return RedirectResponse('/add_number_page', status_code=303)

    existing_chat = db.query(Chat).filter(
        or_(
            and_(Chat.user1_id == current_user_id, Chat.user2_id == target_user.id),
            and_(Chat.user1_id == target_user.id, Chat.user2_id == current_user_id)
        )
    ).first()

    if existing_chat:
        return RedirectResponse(f'/chat/{existing_chat.id}', status_code=303)

    new_chat = Chat(user1_id=current_user_id, user2_id=target_user.id)
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)

    return RedirectResponse(f'/chat/{new_chat.id}', status_code=303)


@app.post('/send_message/{chat_id}')
def send_message(
    chat_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    # создаём сообщение
    new_message = Message(
        chat_id=chat_id,
        sender_id=int(user_id),
        text=text,
        timestamp=str(datetime.datetime.now().strftime("%H:%M"))
    )

    db.add(new_message)
    db.commit()

    # возвращаем обратно в чат
    return RedirectResponse(f'/chat/{chat_id}', status_code=303)


print("hi")
