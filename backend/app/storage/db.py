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
                        ts=o.ts,
                    )
                )
        session.commit()
