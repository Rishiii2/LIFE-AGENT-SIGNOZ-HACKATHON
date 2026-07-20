from sqlmodel import Field, SQLModel, create_engine, Session
from typing import Optional

class PlayerState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    telegram_id: str = Field(unique=True, index=True)
    hp: int = Field(default=100)
    mana: int = Field(default=100)
    xp: int = Field(default=0)
    level: int = Field(default=1)

class ProcessedUpdate(SQLModel, table=True):
    update_id: int = Field(primary_key=True)
    processed_at: str = Field(default="N/A")

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
