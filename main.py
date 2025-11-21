from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select
from typing import Optional, List
from datetime import datetime

# ==============================
# Database setup
# ==============================

DATABASE_URL = "sqlite:///./inventory.db"
engine = create_engine(DATABASE_URL, echo=False)


class ItemBase(SQLModel):
    name: str
    category: Optional[str] = None
    quantity: int = 0
    location: Optional[str] = None
    qr_value: str
    unit_price: Optional[float] = None
    image_url: Optional[str] = None


class Item(ItemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ItemCreate(ItemBase):
    """Schema for creating a new item"""
    pass


class ItemUpdate(SQLModel):
    """Schema for partial updates"""
    name: Optional[str] = None
    category: Optional[str] = None
    quantity: Optional[int] = None
    location: Optional[str] = None
    unit_price: Optional[float] = None
    image_url: Optional[str] = None


class ItemRead(ItemBase):
    """Schema used in responses"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


# ==============================
# FastAPI app
# ==============================

app = FastAPI(title="Mobile Inventory Backend")

# CORS for Flutter (Android, emulator, web, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for hackathon it's fine; tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# ==============================
# Routes
# ==============================

@app.get("/")
def root():
    return {"message": "Mobile Inventory Backend running"}


@app.get("/items", response_model=List[ItemRead])
def list_items():
    with Session(engine) as session:
        items = session.exec(select(Item)).all()
        return items


@app.post("/items", response_model=ItemRead)
def create_item(item: ItemCreate):
    with Session(engine) as session:
        # qr_value must be unique
        existing = session.exec(
            select(Item).where(Item.qr_value == item.qr_value)
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="qr_value already exists. Use another QR / SKU.",
            )

        db_item = Item(**item.dict())
        session.add(db_item)
        session.commit()
        session.refresh(db_item)
        return db_item


@app.get("/items/{item_id}", response_model=ItemRead)
def get_item(item_id: int):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        return item


@app.get("/items/by-qr/{qr_value}", response_model=ItemRead)
def get_item_by_qr(qr_value: str):
    """
    Used by Flutter QR scanner.
    QR content = qr_value (e.g. 'LAP-001')
    """
    with Session(engine) as session:
        statement = select(Item).where(Item.qr_value == qr_value)
        item = session.exec(statement).first()
        if not item:
            raise HTTPException(
                status_code=404,
                detail="Item not found for this QR",
            )
        return item


@app.patch("/items/{item_id}", response_model=ItemRead)
def update_item(item_id: int, data: ItemUpdate):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        update_data = data.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(item, key, value)

        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
        return item


@app.delete("/items/{item_id}", response_model=dict)
def delete_item(item_id: int):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        session.delete(item)
        session.commit()
        return {"detail": "Item deleted"}
