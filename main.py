import uvicorn
import datetime
import json
from fastapi import FastAPI, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse, JSONResponse
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


# --- МАРШРУТЫ ---

@app.get('/')
def register_page(request: Request):
    return templates.TemplateResponse("register.html", context={"request": request})


@app.get('/login_page')
def login_page(request: Request):
    return templates.TemplateResponse('login.html', context={"request": request})


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

    return templates.TemplateResponse("profile.html", context={"request": request, "user": user})


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

    return templates.TemplateResponse("messenger.html", context={"request": request})


# ===== API ЭНДПОИНТЫ =====

@app.get('/api/chats')
def api_get_chats(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(user_id)

    chats = db.query(Chat).filter(
        or_(Chat.user1_id == current_user_id, Chat.user2_id == current_user_id)
    ).all()

    result = []
    for chat in chats:
        partner_id = chat.user2_id if chat.user1_id == current_user_id else chat.user1_id
        partner = db.query(User).filter(User.id == partner_id).first()
        
        # Последнее сообщение
        last_msg = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.id.desc()).first()
        
        result.append({
            "chat_id": chat.id,
            "partner": {
                "id": partner.id,
                "username": partner.username,
                "avatar": partner.avatar,
                "description": partner.description
            },
            "last_message": {
                "text": last_msg.text if last_msg else None,
                "timestamp": last_msg.timestamp if last_msg else None
            } if last_msg else None
        })

    return result


@app.get('/api/messages/{chat_id}')
def api_get_messages(chat_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(user_id)
    
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return {"error": "Чат не найден"}
    
    if chat.user1_id != current_user_id and chat.user2_id != current_user_id:
        return {"error": "Нет доступа"}

    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.id).all()
    
    return [
        {
            "id": msg.id,
            "text": msg.text,
            "timestamp": msg.timestamp,
            "is_mine": msg.sender_id == current_user_id
        }
        for msg in messages
    ]


@app.post('/api/send_message/{chat_id}')
def api_send_message(
    chat_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    new_message = Message(
        chat_id=chat_id,
        sender_id=int(user_id),
        text=text,
        timestamp=str(datetime.datetime.now().strftime("%H:%M"))
    )

    db.add(new_message)
    db.commit()

    return {"status": "ok", "message_id": new_message.id}


@app.post('/api/add_number')
def api_add_number(request: Request, number: str = Form(...), db: Session = Depends(get_db)):
    current_user_id = request.cookies.get("user_id")
    if not current_user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(current_user_id)
    target_user = db.query(User).filter(User.number == number).first()

    if not target_user or target_user.id == current_user_id:
        return {"error": "Пользователь не найден"}

    existing_chat = db.query(Chat).filter(
        or_(
            and_(Chat.user1_id == current_user_id, Chat.user2_id == target_user.id),
            and_(Chat.user1_id == target_user.id, Chat.user2_id == current_user_id)
        )
    ).first()

    if existing_chat:
        return {
            "chat_id": existing_chat.id,
            "partner": {
                "id": target_user.id,
                "username": target_user.username,
                "avatar": target_user.avatar,
                "description": target_user.description
            }
        }

    new_chat = Chat(user1_id=current_user_id, user2_id=target_user.id)
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)

    return {
        "chat_id": new_chat.id,
        "partner": {
            "id": target_user.id,
            "username": target_user.username,
            "avatar": target_user.avatar,
            "description": target_user.description
        }
    }


@app.get('/add_number_page')
def add_number_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    return templates.TemplateResponse("add_number.html", context={"request": request, "user": user})


@app.get('/settings_page')
def settings_page(request: Request,db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return RedirectResponse("/login_page", status_code=303)

    return templates.TemplateResponse('/settings.html', context={"request": request, "user": user})

@app.post('/settings')
def settings(request: Request,name: str = Form(None),password: str = Form(None),avatar: str = Form(None),description:str = Form(None),db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    user = db.query(User).filter(User.id == int(user_id)).first()

    if user:
        if name:
            user.username = name
        if password:
            user.password = int(password)
        if avatar:
            user.avatar = avatar
        if description:
            user.description = description
        db.commit()


    return RedirectResponse('/profile',status_code=303)


if __name__ == '__main__':
    uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=True)