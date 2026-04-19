import uvicorn
import datetime
import json
from fastapi import FastAPI, Depends, Form, Request, Response, WebSocket
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, or_, and_, Boolean
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
    is_delivered = Column(Boolean, default=True)  # Доставлено (отправлено на сервер)
    is_read = Column(Boolean, default=False)  # Прочитано собеседником


Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")


# ===== МЕНЕДЖЕР WEBSOCKET ПОДКЛЮЧЕНИЙ =====
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_notification(self, user_id: int, data: dict):
        """Отправить уведомление пользователю"""
        if user_id in self.active_connections:
            for websocket in self.active_connections[user_id]:
                try:
                    await websocket.send_json(data)
                except Exception:
                    pass


manager = ConnectionManager()


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(user_id, websocket)
    db = SessionLocal()
    try:
        while True:
            data = await websocket.receive_json()
            
            # Обработка разных типов сообщений
            if data.get("type") == "typing":
                # Можно добавить обработку статуса "печатает"
                pass
            elif data.get("type") == "mark_as_delivered":
                # Отмечаем сообщение как доставленное
                message_id = data.get("message_id")
                if message_id:
                    msg = db.query(Message).filter(Message.id == message_id).first()
                    if msg:
                        msg.is_delivered = True
                        db.commit()
                        
                        # Уведомляем отправителя
                        await manager.send_notification(msg.sender_id, {
                            "type": "message_delivered",
                            "message_id": message_id,
                            "chat_id": msg.chat_id
                        })
    except Exception:
        manager.disconnect(user_id, websocket)
    finally:
        db.close()


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

    return templates.TemplateResponse("profile.html", context={request: request, "user": user})


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

    return templates.TemplateResponse("messenger.html", context={request: request})


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
            "is_mine": msg.sender_id == current_user_id,
            "is_delivered": msg.is_delivered,
            "is_read": msg.is_read
        }
        for msg in messages
    ]


@app.post('/api/send_message/{chat_id}')
async def api_send_message(
    chat_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(user_id)

    # Находим чат и определяем собеседника
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return {"error": "Чат не найден"}

    partner_id = chat.user2_id if chat.user1_id == current_user_id else chat.user1_id

    new_message = Message(
        chat_id=chat_id,
        sender_id=current_user_id,
        text=text,
        timestamp=str(datetime.datetime.now().strftime("%H:%M")),
        is_delivered=True,  # Сообщение доставлено на сервер
        is_read=False  # Ещё не прочитано
    )

    db.add(new_message)
    db.commit()

    # Уведомляем собеседника о новом сообщении через WebSocket
    await manager.send_notification(partner_id, {
        "type": "new_message",
        "chat_id": chat_id,
        "message": {
            "id": new_message.id,
            "text": text,
            "timestamp": new_message.timestamp,
            "sender_id": current_user_id
        }
    })

    # Отправляем отправителю подтверждение с актуальными статусами
    # Проверяем, онлайн ли собеседник
    is_partner_online = partner_id in manager.active_connections
    
    return {
        "status": "ok",
        "message_id": new_message.id,
        "is_delivered": True,
        "is_read": False,
        "partner_online": is_partner_online
    }


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


# ===== ЭНДПОИНТЫ ДЛЯ СТАТУСОВ СООБЩЕНИЙ =====

@app.post('/api/mark_as_read/{chat_id}')
async def api_mark_as_read(chat_id: int, request: Request, db: Session = Depends(get_db)):
    """Отметить все сообщения в чате как прочитанные"""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(user_id)

    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return {"error": "Чат не найден"}

    if chat.user1_id != current_user_id and chat.user2_id != current_user_id:
        return {"error": "Нет доступа"}

    # Определяем отправителя сообщений (собеседника)
    sender_id = chat.user2_id if chat.user1_id == current_user_id else chat.user1_id

    # Находим все непрочитанные сообщения от собеседника
    unread_messages = db.query(Message).filter(
        Message.chat_id == chat_id,
        Message.sender_id == sender_id,
        Message.is_read == False
    ).all()

    updated_count = 0
    updated_message_ids = []
    for msg in unread_messages:
        msg.is_read = True
        msg.is_delivered = True
        updated_message_ids.append(msg.id)
        updated_count += 1

    db.commit()

    # Уведомляем собеседника, что его сообщения прочитаны
    if updated_count > 0:
        await manager.send_notification(sender_id, {
            "type": "messages_read",
            "chat_id": chat_id,
            "reader_id": current_user_id,
            "message_ids": updated_message_ids
        })

    return {
        "status": "ok",
        "updated_count": updated_count,
        "message_ids": updated_message_ids
    }


@app.get('/api/message_status/{chat_id}')
def api_get_message_status(chat_id: int, request: Request, db: Session = Depends(get_db)):
    """Получить статусы сообщений в чате (для синхронизации при открытии)"""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return {"error": "Не авторизован"}

    current_user_id = int(user_id)

    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return {"error": "Чат не найден"}

    if chat.user1_id != current_user_id and chat.user2_id != current_user_id:
        return {"error": "Нет доступа"}

    # Получаем все сообщения, где sender == current_user (мои сообщения)
    my_messages = db.query(Message).filter(
        Message.chat_id == chat_id,
        Message.sender_id == current_user_id
    ).all()

    return {
        "messages": [
            {
                "id": msg.id,
                "is_delivered": msg.is_delivered,
                "is_read": msg.is_read
            }
            for msg in my_messages
        ]
    }


@app.get('/add_number_page')
def add_number_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    return templates.TemplateResponse("add_number.html", context={request: request, "user": user})


@app.get('/settings_page')
def settings_page(request: Request,db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse("/login_page", status_code=303)

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        return RedirectResponse("/login_page", status_code=303)

    return templates.TemplateResponse('/settings.html', context={request: request, "user": user})

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



if __name__ == '__main__':
    uvicorn.run('main:app', host='127.0.0.1', port=8000, reload=True)

print("Сервер запущен на http://)")