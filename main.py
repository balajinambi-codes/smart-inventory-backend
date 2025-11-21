from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional, List
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

# ===== DATABASE SETUP =====
DATABASE_URL = "sqlite:///./inventory.db"
engine = create_engine(DATABASE_URL, echo=False)


# ===== EMAIL (SMTP) CONFIG =====
# Use Gmail with App Password OR any SMTP server.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "codesinisters@gmail.com"           # TODO: change
SMTP_PASSWORD = "ufbputduxwxhypao"    # TODO: change (App password)
ALERT_RECEIVER = "codesinisters@gmail.com"     # TODO: change (teacher/your mail)
LOW_STOCK_THRESHOLD = 3  # When quantity <= this, send mail


def send_low_stock_email(item_name: str, qr_value: str, quantity: int):
    subject = f"[Inventory Alert] Low stock for {item_name}"
    body = (
        f"Item: {item_name}\n"
        f"QR: {qr_value}\n"
        f"Current quantity: {quantity}\n\n"
        "Please restock this item as soon as possible."
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_RECEIVER

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"[EMAIL] Low stock email sent for {item_name}")
    except Exception as e:
        print("[EMAIL ERROR]", e)


# ===== MODELS =====
class ItemBase(SQLModel):
    name: str
    category: Optional[str] = None
    quantity: int = 0
    location: Optional[str] = None
    qr_value: str


class Item(ItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ItemCreate(ItemBase):
    pass


class ItemUpdate(SQLModel):
    name: Optional[str] = None
    category: Optional[str] = None
    quantity: Optional[int] = None
    location: Optional[str] = None


class ItemResponse(ItemBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EspEvent(SQLModel):
    qr_value: str
    delta: int  # +1 or -1


# ===== DB INIT =====
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


# ===== APP SETUP =====
app = FastAPI(title="Smart Inventory Backend")

# CORS for Flutter app / others
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for dev; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# ===== ROUTES =====
@app.get("/")
def root():
    return {"message": "Smart Inventory Backend running"}


@app.get("/items", response_model=List[ItemResponse])
def list_items():
    with Session(engine) as session:
        items = session.exec(select(Item)).all()
        return items


@app.post("/items", response_model=ItemResponse)
def create_item(item: ItemCreate):
    with Session(engine) as session:
        # Ensure unique qr_value
        existing = session.exec(
            select(Item).where(Item.qr_value == item.qr_value)
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="qr_value already exists")

        db_item = Item(**item.dict())
        session.add(db_item)
        session.commit()
        session.refresh(db_item)
        return db_item


@app.get("/items/{item_id}", response_model=ItemResponse)
def get_item(item_id: int):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item


@app.get("/items/by-qr/{qr_value}", response_model=ItemResponse)
def get_item_by_qr(qr_value: str):
    with Session(engine) as session:
        statement = select(Item).where(Item.qr_value == qr_value)
        item = session.exec(statement).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found for this QR")
        return item


@app.patch("/items/{item_id}", response_model=ItemResponse)
def update_item(
    item_id: int, data: ItemUpdate, background_tasks: BackgroundTasks
):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        for key, value in data.dict(exclude_unset=True).items():
            setattr(item, key, value)

        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)

        # Email alert if low stock after manual update
        if item.quantity <= LOW_STOCK_THRESHOLD:
            background_tasks.add_task(
                send_low_stock_email, item.name, item.qr_value, item.quantity
            )

        return item


@app.post("/esp/event", response_model=ItemResponse)
def handle_esp_event(event: EspEvent, background_tasks: BackgroundTasks):
    """
    Called by ESP32 when an item is taken/added.
    event.delta: +1 (added) or -1 (removed)
    """
    with Session(engine) as session:
        statement = select(Item).where(Item.qr_value == event.qr_value)
        item = session.exec(statement).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found for this QR")

        new_qty = item.quantity + event.delta
        if new_qty < 0:
            new_qty = 0
        item.quantity = new_qty
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)

        if item.quantity <= LOW_STOCK_THRESHOLD:
            background_tasks.add_task(
                send_low_stock_email, item.name, item.qr_value, item.quantity
            )

        return item
