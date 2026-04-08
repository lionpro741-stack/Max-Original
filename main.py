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
    description = Column(String,nullable=True)


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


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Получить текущего пользователя по cookie"""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == int(user_id)).first()


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


@app.get('/chats')
def chats_page(request: Request, db: Session = Depends(get_db)):
    # Получаем user_id из cookies
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    current_user_id = int(user_id)
    
    # Получаем все чаты, где участвует текущий пользователь
    chats = db.query(Chat).filter(
        or_(Chat.user1_id == current_user_id, Chat.user2_id == current_user_id)
    ).all()
    
    # Для каждого чата находим собеседника
    chats_with_partners = []
    for chat in chats:
        # Если current_user_id == user1_id, то собеседник — user2_id, и наоборот
        partner_id = chat.user2_id if chat.user1_id == current_user_id else chat.user1_id
        partner = db.query(User).filter(User.id == partner_id).first()
        chats_with_partners.append((chat, partner))
    
    return templates.TemplateResponse("chats.html", {
        "request": request,
        "chats": chats_with_partners
    })


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


@app.get('/settings_page')
def settings_page(request: Request,db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return RedirectResponse("/login_page", status_code=303)

    return templates.TemplateResponse('/settings.html',{"request": request,"user": user})

@app.post('/settings')
def settings(request: Request,name: str = Form(None),password: str = Form(None),avatar: str = Form(None),description:str = Form(None),db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    user = db.query(User).filter(User.id == int(user_id)).first()

    if user:
        if name:
            user.username = name
        if password:
            user.password = password  # Исправлено: был int(password), что ломало строки
        if avatar:
            user.avatar = avatar
        if description:
            user.description = description
        db.commit()


    return RedirectResponse('/profile',status_code=303)


@app.get('/chat/{chat_id}')
def chat_page(chat_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    current_user_id = int(user_id)

    # Находим чат
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return RedirectResponse("/chats", status_code=303)

    # Проверяем, что пользователь участвует в чате
    if chat.user1_id != current_user_id and chat.user2_id != current_user_id:
        return RedirectResponse("/chats", status_code=303)

    # Находим собеседника
    partner_id = chat.user2_id if chat.user1_id == current_user_id else chat.user1_id
    opponent = db.query(User).filter(User.id == partner_id).first()

    # Получаем сообщения
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.id).all()

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "chat_id": chat_id,
        "current_user_id": current_user_id,
        "opponent": opponent,
        "messages": messages
    })


@app.get('/api/messages/{chat_id}')
def get_messages(chat_id: int, request: Request, db: Session = Depends(get_db)):
    """API endpoint для получения новых сообщений"""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(user_id)

    # Проверяем доступ к чату
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return {"error": "Чат не найден"}

    if chat.user1_id != current_user_id and chat.user2_id != current_user_id:
        return {"error": "Нет доступа"}

    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.id).all()
    
    return {
        "messages": [
            {
                "id": m.id,
                "text": m.text,
                "sender_id": m.sender_id,
                "timestamp": m.timestamp
            }
            for m in messages
        ]
    }










