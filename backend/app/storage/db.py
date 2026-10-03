from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings
from app.models.offers import RawOffer


class Base(DeclarativeBase):
    pass


class OfferORM(Base):
    __tablename__ = "offer"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(256), index=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    platform_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512))
    price: Mapped[float] = mapped_column(Float)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    coupon: Mapped[float | None] = mapped_column(Float, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    shop: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sales: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime)


class CrawlLogORM(Base):
    __tablename__ = "crawl_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(256), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    ok: Mapped[bool] = mapped_column(Boolean)
    count: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime)


class FeedbackORM(Base):
    """用户人工标记「不相关」的商品，后续查询直接排除。"""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    platform_id: Mapped[str] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(String(32), default="user_marked")
    ts: Mapped[datetime] = mapped_column(DateTime)


class TraceORM(Base):
    """agent 运行轨迹：每个节点一步，JSON 存储，便于回放。"""

    __tablename__ = "trace"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str] = mapped_column(String(256))
    steps_json: Mapped[str] = mapped_column(String(20000))
    ts: Mapped[datetime] = mapped_column(DateTime)


def save_trace(trace: dict) -> None:
    """保存一次 agent 运行的完整轨迹。"""
    assert _SessionLocal is not None
    import json

    with _SessionLocal() as session:
        session.add(
            TraceORM(
                trace_id=trace["trace_id"],
                query=trace["query"][:256],
                steps_json=json.dumps(trace["steps"], ensure_ascii=False)[:20000],
                ts=datetime.now(UTC),
            )
        )
        session.commit()


def load_trace(trace_id: str) -> dict | None:
    """按 trace_id 读取轨迹。"""
    assert _SessionLocal is not None
    import json

    with _SessionLocal() as session:
        row = (
            session.query(TraceORM)
            .filter(TraceORM.trace_id == trace_id)
            .order_by(TraceORM.id.desc())
            .first()
        )
    if not row:
        return None
    return {"trace_id": row.trace_id, "query": row.query, "steps": json.loads(row.steps_json)}


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def record_search(
    query: str, offers: Sequence[RawOffer], errors: dict[str, str]
) -> None:
    """把一次搜索的结果与抓取日志落库，便于排查某平台为什么缺数据。"""
    assert _SessionLocal is not None
    now = datetime.now(UTC)

    by_platform: dict[str, list[RawOffer]] = {}
    for o in offers:
        by_platform.setdefault(o.platform, []).append(o)

    with _SessionLocal() as session:
        for platform in ("jd", "taobao", "pdd"):
            platform_offers = by_platform.get(platform, [])
            if platform in errors:
                session.add(
                    CrawlLogORM(
                        query=query,
                        platform=platform,
                        ok=False,
                        count=0,
                        error=errors[platform][:1024],
                        ts=now,
                    )
                )
            else:
                session.add(
                    CrawlLogORM(
                        query=query, platform=platform, ok=True, count=len(platform_offers), ts=now
                    )
                )
            for o in platform_offers:
                session.add(
                    OfferORM(
                        query=query,
                        platform=o.platform,
                        platform_id=o.platform_id,
                        title=o.title[:512],
                        price=o.price,
                        original_price=o.original_price,
                        coupon=o.coupon,
                        url=o.url,
                        image=o.image,
                        shop=o.shop,
                        sales=o.sales,
                        ts=o.ts,
                    )
                )
        session.commit()


def record_feedback(platform: str, platform_id: str, reason: str) -> None:
    """记录用户标记，后续查询排除同款。"""
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        session.add(
            FeedbackORM(
                platform=platform, platform_id=platform_id, reason=reason, ts=datetime.now(UTC)
            )
        )
        session.commit()


def get_feedback_ids() -> set[tuple[str, str]]:
    """全部已标记商品 (platform, platform_id)。"""
    assert _SessionLocal is not None
    with _SessionLocal() as session:
        rows = session.query(FeedbackORM.platform, FeedbackORM.platform_id).all()
    return set(rows)
