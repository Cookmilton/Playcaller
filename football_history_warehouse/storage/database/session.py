"""
Session factory and transaction scope helper.

Repositories (when implemented) should accept a :class:`~sqlalchemy.orm.Session`
or use :func:`session_scope` for unit-of-work boundaries.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """
    Provide a transactional scope: commit on success, rollback on error.

    Does not call ``engine.dispose()``; manage engine lifetime outside.
    """
    factory = make_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
