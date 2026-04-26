import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "gameveredito.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    app_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    sub = Column(String, nullable=True)
    price = Column(String)
    discount = Column(Integer, default=0)
    original_price = Column(String, nullable=True)
    lowest_price = Column(String, nullable=True)
    image_url = Column(String)
    steam_url = Column(String)
    review_score = Column(Integer, nullable=True)
    analyzed_at = Column(DateTime, nullable=False)
    analysis_json = Column(Text, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    # Migrate: add 'sub' column if the DB was created before this field existed
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(
            __import__("sqlalchemy").text("PRAGMA table_info(analyses)")
        )]
        if "sub" not in cols:
            conn.execute(__import__("sqlalchemy").text("ALTER TABLE analyses ADD COLUMN sub TEXT"))
            conn.commit()
            log.info("Migrated: added 'sub' column to analyses table")
    log.info("Database ready at %s", DB_PATH)


def save_analysis(game_data) -> None:
    with Session(engine) as session:
        row = Analysis(
            app_id=game_data.app_id,
            title=game_data.title,
            sub=game_data.sub,
            price=game_data.price,
            discount=game_data.discount,
            original_price=game_data.original_price,
            lowest_price=game_data.lowest_price,
            image_url=game_data.image_url,
            steam_url=game_data.steam_url,
            review_score=game_data.review_score,
            # Store as naive UTC — SQLite has no tz support
            analyzed_at=game_data.analyzed_at.replace(tzinfo=None),
            analysis_json=game_data.analysis.model_dump_json(),
        )
        session.merge(row)
        session.commit()
    log.debug("Saved analysis for app_id=%s", game_data.app_id)


def _row_to_game_data(row: Analysis):
    from app.schemas.game import GameAnalysis, GameData

    analysis = GameAnalysis.model_validate_json(row.analysis_json)
    return GameData(
        app_id=row.app_id,
        title=row.title,
        sub=row.sub,
        price=row.price,
        discount=row.discount or 0,
        original_price=row.original_price,
        lowest_price=row.lowest_price,
        image_url=row.image_url,
        steam_url=row.steam_url,
        review_score=row.review_score,
        analyzed_at=row.analyzed_at,  # ensure_utc validator in GameData handles tzinfo
        analysis=analysis,
    )


def load_all_analyses():
    with Session(engine) as session:
        rows = session.query(Analysis).order_by(Analysis.analyzed_at.desc()).all()
        result = []
        for row in rows:
            try:
                result.append(_row_to_game_data(row))
            except Exception as e:
                log.warning("Skipping corrupt row app_id=%s: %s", row.app_id, e)
        return result


def load_analysis_by_id(app_id: str) -> Optional[object]:
    with Session(engine) as session:
        row = session.get(Analysis, app_id)
        if row is None:
            return None
        try:
            return _row_to_game_data(row)
        except Exception as e:
            log.warning("Failed to load app_id=%s from DB: %s", app_id, e)
            return None
